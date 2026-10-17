import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

RUNNER = Path(__file__).resolve().parents[1] / 'runtime/pstack_run.py'
sys.path.insert(0, str(RUNNER.parent))
import pstack_run

CODEX_OK = '''#!/usr/bin/env python3
import json, sys, pathlib
pathlib.Path(sys.argv[0] + '.argv').write_text(json.dumps(sys.argv[1:]))
prompt = sys.stdin.read()
resumed = 'resume' in sys.argv
print(json.dumps({'type': 'thread.started', 'thread_id': 'thread-1'}), flush=True)
pathlib.Path('made.txt').write_text('resumed' if resumed else 'made')
text = 'follow-up done' if resumed else 'done: ' + str('BRIEF' in prompt)
if 'LONG' in prompt:
    text = 'x' * 2500
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}}))
if '-o' in sys.argv:
    pathlib.Path(sys.argv[sys.argv.index('-o') + 1]).write_text(text)
print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 5, 'output_tokens': 2}}))
'''
CODEX_NO_TERMINAL = '''#!/usr/bin/env python3
import json
print(json.dumps({'type': 'thread.started', 'thread_id': 'thread-2'}))
print('not json')
'''
CODEX_LIMITED = '''#!/usr/bin/env python3
import json
print(json.dumps({'type': 'thread.started', 'thread_id': 'thread-6'}), flush=True)
print(json.dumps({'type': 'error', 'message': "You've hit your usage limit. resets 3:10am (UTC)"}))
'''
SILENT = '#!/bin/sh\nexec sleep 60\n'
CLOSES_OUTPUT_THEN_HANGS = '#!/bin/sh\necho \'{"type":"thread.started","thread_id":"thread-4"}\'\nexec >&- 2>&-\nexec sleep 60\n'
PAID_THEN_HANGS = ('#!/bin/sh\necho \'{"type":"thread.started","thread_id":"thread-5"}\'\n'
                   'echo \'{"type":"turn.completed","usage":{"input_tokens":9}}\'\nexec sleep 60\n')
CHATTY_THEN_HANGS = '#!/bin/sh\necho \'{"type":"thread.started","thread_id":"thread-3"}\'\nexec sleep 60\n'


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        for command in (['init', '-q'], ['config', 'user.name', 'Fixture'], ['config', 'user.email', 'fixture@example.com']):
            subprocess.run(['git', '-C', str(self.project), *command], check=True)
        (self.project / 'a.txt').write_text('a\n')
        (self.project / '.gitignore').write_text('.pstack/runs/\n')
        subprocess.run(['git', '-C', str(self.project), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.project), 'commit', '-qm', 'base'], check=True)
        self.brief = self.root / 'brief.md'
        self.brief.write_text('Do the fixture task.\n')

    def fake(self, body):
        path = self.root / 'fake-codex'
        path.write_text(body)
        path.chmod(0o755)
        return path

    def invoke(self, body, *arguments, wait=True):
        env = {**os.environ, 'CODEX_BINARY': str(self.fake(body))}
        command = [sys.executable, str(RUNNER), '--project', str(self.project), *arguments]
        if not wait:
            return subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)

    def status(self, task):
        return json.loads((self.project / '.pstack/runs' / task / 'status.json').read_text())

    def test_run_creates_owned_worktree_and_receipt_then_resumes_session(self):
        result = self.invoke(CODEX_OK, 'run', 'codex', 'task-1', str(self.brief), '--model', 'm1', '--effort', 'low')
        self.assertEqual(result.returncode, 0, result.stderr)
        started, receipt = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(started['event'], 'pstack.started')
        self.assertEqual((receipt['state'], receipt['session_id'], receipt['summary']), ('succeeded', 'thread-1', 'done: True'))
        self.assertEqual(receipt['diffstat'], '1 file changed, 1 insertion(+)')
        status = self.status('task-1')
        worktree = self.root / '.pstack-worktrees/project/task-1'
        self.assertEqual((status['cwd'], status['branch']), (str(worktree), 'pstack/task-1'))
        self.assertTrue((worktree / 'made.txt').is_file())
        self.assertFalse((self.project / 'made.txt').exists())
        self.assertEqual(status['usage'], {'input_tokens': 5, 'output_tokens': 2})
        argv = status['argv']
        self.assertIn('--dangerously-bypass-approvals-and-sandbox', argv)
        self.assertNotIn('--sandbox', argv)
        prompt = (self.project / '.pstack/runs/task-1/prompt.txt').read_text()
        self.assertIn('Commit your finished work on `pstack/task-1`', prompt)
        self.assertIn('You are a worker, not the coordinator.', prompt)
        self.assertIn('model_reasoning_effort="low"', argv)
        events = [json.loads(line)['type'] for line in Path(status['events']).read_text().splitlines()]
        self.assertEqual(events[0], 'pstack.started')
        self.assertEqual(events[-1], 'pstack.finished')
        # A second run on the same id must be an explicit choice.
        self.assertEqual(self.invoke(CODEX_OK, 'run', 'codex', 'task-1', str(self.brief)).returncode, 2)
        result = self.invoke(CODEX_OK, 'resume', 'task-1', str(self.brief))
        self.assertEqual(result.returncode, 0, result.stderr)
        recorded = json.loads((self.root / 'fake-codex.argv').read_text())
        self.assertEqual(recorded[:3], ['exec', 'resume', 'thread-1'])
        status = self.status('task-1')
        self.assertEqual((status['attempt'], status['summary'], status['model']), (2, 'follow-up done', 'm1'))
        self.assertEqual([(entry['attempt'], entry['state'], entry['usage']) for entry in status['attempts']],
                         [(1, 'succeeded', {'input_tokens': 5, 'output_tokens': 2}), (2, 'succeeded', {'input_tokens': 5, 'output_tokens': 2})])
        self.assertEqual(status['totals']['attempts'], 2)
        self.assertEqual(status['totals']['duration_s'], round(sum(entry['duration_s'] for entry in status['attempts']), 1))
        self.assertEqual(Path(status['attempts'][0]['last_message']).read_text(), 'done: True')
        resumed = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual((resumed['attempt'], resumed['total_duration_s']), (2, status['totals']['duration_s']))
        self.assertGreaterEqual(resumed['total_duration_s'], resumed['duration_s'])
        patch = self.invoke(CODEX_OK, 'diff', 'task-1', '--patch').stdout
        self.assertIn('+resumed', patch)
        self.assertEqual(self.invoke(CODEX_OK, 'clean', 'task-1', '--force').returncode, 0)
        self.assertFalse(worktree.exists())

    def test_totals_sum_cost_over_attempts_and_upgrade_a_status_without_history(self):
        self.assertEqual(pstack_run.totals([{'cost_usd': 0.21, 'duration_s': 420.0}, {'cost_usd': 0.05, 'duration_s': 30.5}]),
                         {'attempts': 2, 'cost_usd': 0.26, 'duration_s': 450.5})
        self.assertIsNone(pstack_run.totals([{'cost_usd': None, 'duration_s': 3.0}])['cost_usd'])
        legacy = {'attempt': 1, 'state': 'succeeded', 'cost_usd': 0.21, 'duration_s': 420.0}
        self.assertEqual([(entry['attempt'], entry['cost_usd']) for entry in pstack_run.history(legacy)], [(1, 0.21)])
        self.assertEqual(pstack_run.history({'attempt': 1, 'state': 'running'})[0]['state'], 'lost')
        self.assertEqual(pstack_run.history(None), [])

    def test_long_summary_is_cut_at_the_limit_and_points_to_the_full_message(self):
        self.brief.write_text('LONG answer please.\n')
        result = self.invoke(CODEX_OK, 'run', 'codex', 'long', str(self.brief), '--mode', 'read')
        receipt = json.loads(result.stdout.splitlines()[-1])
        self.assertTrue(receipt['summary_truncated'])
        self.assertEqual(len(receipt['summary']), pstack_run.SUMMARY_LIMIT + 2)
        self.assertEqual(Path(receipt['last_message']).read_text().strip(), 'x' * 2500)
        self.brief.write_text('Short.\n')
        short = json.loads(self.invoke(CODEX_OK, 'run', 'codex', 'short', str(self.brief), '--mode', 'read').stdout.splitlines()[-1])
        self.assertFalse(short['summary_truncated'])
        self.assertGreaterEqual(pstack_run.SUMMARY_LIMIT, 2000)

    def test_read_task_runs_in_project_without_worktree(self):
        result = self.invoke(CODEX_NO_TERMINAL, 'run', 'codex', 'reader', str(self.brief), '--mode', 'read')
        status = self.status('reader')
        self.assertEqual((result.returncode, status['state'], status['cwd']), (1, 'failed', str(self.project)))
        self.assertEqual(status['error'], 'no successful terminal event')
        self.assertIsNone(status['branch'])
        argv = status['argv']
        self.assertIn('--dangerously-bypass-approvals-and-sandbox', argv)
        self.assertIn('read-only task', (self.project / '.pstack/runs/reader/prompt.txt').read_text())
        self.assertIn('pstack.raw', Path(status['events']).read_text())

    def test_startup_watchdog_stops_a_silent_worker(self):
        result = self.invoke(SILENT, 'run', 'codex', 'silent', str(self.brief), '--startup-timeout', '1')
        status = self.status('silent')
        self.assertEqual((result.returncode, status['state']), (124, 'startup_timeout'))
        self.assertIsNone(pstack_run.start_identity(status['pid']))

    def test_idle_watchdog_and_kill(self):
        result = self.invoke(CHATTY_THEN_HANGS, 'run', 'codex', 'idle', str(self.brief), '--idle-timeout', '1')
        self.assertEqual((result.returncode, self.status('idle')['state']), (124, 'stalled'))
        runner = self.invoke(CHATTY_THEN_HANGS, 'run', 'codex', 'victim', str(self.brief), wait=False)
        self.addCleanup(runner.kill)
        deadline = time.monotonic() + 20
        path = self.project / '.pstack/runs/victim/status.json'
        while time.monotonic() < deadline and not (path.is_file() and self.status('victim')['state'] == 'running'):
            time.sleep(0.1)
        self.assertEqual(self.status('victim')['session_id'], 'thread-3')
        killed = self.invoke(CHATTY_THEN_HANGS, 'kill', 'victim')
        self.assertEqual(json.loads(killed.stdout)['state'], 'killed')
        self.assertEqual(runner.wait(timeout=20), 130)
        runner.stdout.close()
        runner.stderr.close()
        self.assertIsNone(pstack_run.start_identity(self.status('victim')['pid']))

    def test_worker_that_closes_output_and_hangs_still_meets_the_deadline(self):
        result = self.invoke(CLOSES_OUTPUT_THEN_HANGS, 'run', 'codex', 'mute', str(self.brief), '--timeout', '2', '--idle-timeout', '0')
        self.assertEqual((result.returncode, self.status('mute')['state']), (124, 'timeout'))
        self.assertIsNone(pstack_run.start_identity(self.status('mute')['pid']))

    def test_runner_killed_after_the_answer_keeps_usage_and_the_orphan_is_reaped_on_the_next_run(self):
        runner = self.invoke(PAID_THEN_HANGS, 'run', 'codex', 'orphan', str(self.brief), wait=False)
        self.addCleanup(runner.kill)
        path = self.project / '.pstack/runs/orphan/status.json'
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not (path.is_file() and self.status('orphan').get('usage')):
            time.sleep(0.1)
        worker = self.status('orphan')['pid']
        runner.kill()
        runner.wait(timeout=10)
        runner.stdout.close()
        runner.stderr.close()
        self.assertIsNotNone(pstack_run.start_identity(worker))
        self.addCleanup(lambda: pstack_run.reap({'pid': worker, 'state': 'running', 'cwd': self.status('orphan')['cwd']}))
        result = self.invoke(CODEX_OK, 'run', 'codex', 'orphan', str(self.brief), '--force')
        self.assertEqual(result.returncode, 0, result.stderr)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and pstack_run.start_identity(worker) is not None \
                and Path(f'/proc/{worker}/stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z':
            time.sleep(0.1)
        status = self.status('orphan')
        self.assertEqual([(entry['attempt'], entry['state'], entry['usage']) for entry in status['attempts']],
                         [(1, 'lost', {'input_tokens': 9}), (2, 'succeeded', {'input_tokens': 5, 'output_tokens': 2})])
        self.assertEqual(status['totals']['attempts'], 2)

    def test_second_resume_waits_out_by_refusal_and_never_overwrites_a_running_attempt(self):
        self.assertEqual(self.invoke(CODEX_OK, 'run', 'codex', 'busy', str(self.brief)).returncode, 0)
        first = self.invoke(CHATTY_THEN_HANGS, 'resume', 'busy', str(self.brief), wait=False)
        self.addCleanup(first.kill)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and self.status('busy')['attempt'] != 2:
            time.sleep(0.1)
        second = self.invoke(CODEX_OK, 'resume', 'busy', str(self.brief))
        self.assertEqual(second.returncode, 2)
        self.assertIn('already running', second.stderr)
        self.assertEqual(self.status('busy')['attempt'], 2)
        self.invoke(CODEX_OK, 'kill', 'busy')
        first.wait(timeout=20)
        first.stdout.close()
        first.stderr.close()
        status = self.status('busy')
        self.assertEqual([(entry['attempt'], entry['state']) for entry in status['attempts']], [(1, 'succeeded'), (2, 'killed')])
        self.assertEqual(self.invoke(CODEX_OK, 'resume', 'nothing-here', str(self.brief)).returncode, 2)
        self.assertFalse((self.project / '.pstack/runs/nothing-here').exists())

    def test_role_binding_supplies_model_and_never_crosses_providers(self):
        config = self.project / '.pstack/config.json'
        config.parent.mkdir(exist_ok=True)
        config.write_text(json.dumps({'roles': {'bug-fix': {'provider': 'grok', 'model': 'g', 'effort': 'medium'},
                                                'panel': [{'provider': 'grok', 'model': 'g'}, {'provider': 'codex', 'model': 'astra', 'effort': 'high'}]},
                                      'host_bindings': {'claude-code': {'workers': {'codex': {'model': 'sol', 'effort': 'low'}}}}}))
        self.assertEqual(pstack_run.bindings(self.project, 'codex', None), ('sol', 'low'))
        self.assertEqual(pstack_run.bindings(self.project, 'codex', 'panel'), ('astra', 'high'))
        self.assertEqual(pstack_run.bindings(self.project, 'grok', 'bug-fix'), ('g', 'medium'))
        result = self.invoke(CODEX_OK, 'run', 'codex', 'wrong', str(self.brief), '--role', 'bug-fix')
        self.assertEqual(result.returncode, 2)
        self.assertIn('no silent fallback', result.stderr)
    def git(self, cwd, *arguments, env=None):
        return subprocess.run(['git', '-C', str(cwd), *arguments], capture_output=True, text=True, env=env)

    def test_usage_limit_is_a_limited_state_with_reset_and_the_session_stays_resumable(self):
        self.assertEqual(self.invoke(CODEX_LIMITED, 'run', 'codex', 'limit', str(self.brief)).returncode, 75)
        status = self.status('limit')
        self.assertEqual((status['state'], status['session_id']), ('limited', 'thread-6'))
        self.assertRegex(status['reset_at'], r'T03:10:00Z$')
        self.assertIn('hit your usage limit', status['error'])
        self.assertEqual(status['attempts'][-1]['reset_at'], status['reset_at'])
        self.assertEqual(self.invoke(CODEX_OK, 'resume', 'limit', str(self.brief)).returncode, 0)
        self.assertEqual(self.status('limit')['state'], 'succeeded')

    def test_hooks_confine_commits_to_the_task_branch_allow_branch_pushes_and_refuse_main_deletes_and_force_pushes(self):
        remote = self.root / 'remote.git'
        self.git(self.root, 'init', '-q', '--bare', str(remote))
        self.git(self.project, 'remote', 'add', 'origin', str(remote))
        marker = self.project / '.git/hooks/pre-commit'
        marker.write_text('#!/bin/sh\ntouch "$(git rev-parse --git-common-dir)/project-hook-ran"\n')
        marker.chmod(0o755)
        self.assertEqual(self.invoke(CODEX_OK, 'run', 'codex', 'guard', str(self.brief)).returncode, 0)
        status = self.status('guard')
        worktree = Path(status['cwd'])
        env = pstack_run.environment('codex', self.project / '.pstack/runs/guard/hooks', status['branch'])
        self.git(worktree, 'add', '-A', env=env)
        self.assertEqual(self.git(worktree, 'commit', '-qm', 'task', env=env).returncode, 0)
        self.assertTrue((self.project / '.git/project-hook-ran').is_file())
        (self.project / 'b.txt').write_text('b\n')
        self.git(self.project, 'add', 'b.txt', env=env)
        refused = self.git(self.project, 'commit', '-qm', 'elsewhere', env=env)
        self.assertIn('commit only on pstack/guard', refused.stderr)
        env = pstack_run.environment('codex', self.project / '.pstack/runs/guard/hooks', status['branch'])
        for refspec in ('pstack/guard:main',):
            refused = self.git(worktree, 'push', 'origin', refspec, env=env)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('refused push', refused.stderr)
        self.assertEqual(self.git(remote, 'rev-parse', '--verify', '--quiet', 'refs/heads/main').returncode, 1)
        self.assertEqual(self.git(worktree, 'push', 'origin', 'pstack/guard', env=env).returncode, 0)
        self.assertEqual(self.git(remote, 'rev-parse', '--verify', '--quiet', 'refs/heads/pstack/guard').returncode, 0)
        refused = self.git(worktree, 'push', 'origin', ':pstack/guard', env=env)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('no remote branch deletion', refused.stderr)
        self.git(worktree, 'commit', '-q', '--amend', '-m', 'rewritten', env=env)
        refused = self.git(worktree, 'push', '--force', 'origin', 'pstack/guard', env=env)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('no force-push', refused.stderr)
        self.assertIn('CHECKPOINT.guard.md', (self.project / '.git/info/exclude').read_text())

class ParserTests(unittest.TestCase):
    def test_grok_final_segment_cost_and_cancelled_turn(self):
        parser = pstack_run.Parser('grok', 'preset')
        for event in ({'type': 'text', 'data': 'I will '}, {'type': 'text', 'data': 'look.'}, {'type': 'tool_call'},
                      {'type': 'text', 'data': 'Final '}, {'type': 'text', 'data': 'answer.'},
                      {'type': 'end', 'stopReason': 'end_turn', 'sessionId': 's1', 'total_cost_usd': 0.5, 'usage': {'output_tokens': 3}}):
            parser.feed(event)
        self.assertEqual((parser.message, parser.session, parser.cost, parser.terminal), ('Final answer.', 's1', 0.5, True))
        parser = pstack_run.Parser('grok')
        parser.feed({'type': 'end', 'stopReason': 'cancelled', 'sessionId': 's2'})
        self.assertFalse(parser.terminal)
        self.assertEqual(parser.error, 'stopReason=cancelled')

    def test_claude_result_and_permission_flags(self):
        parser = pstack_run.Parser('claude')
        parser.feed({'type': 'system', 'subtype': 'init', 'session_id': 'c1'})
        parser.feed({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'ok', 'total_cost_usd': 0.1, 'session_id': 'c1'})
        self.assertEqual((parser.session, parser.message, parser.cost, parser.terminal), ('c1', 'ok', 0.1, True))
        run = Path('/run')
        bypass = {'codex': '--dangerously-bypass-approvals-and-sandbox', 'grok': '--always-approve',
                  'claude': '--dangerously-skip-permissions'}
        for provider in bypass:
            for mode in ('write', 'read'):
                argv, _ = pstack_run.command(provider, mode, Path('/w'), run, None, None, 'sid', None)
                self.assertIn(bypass[provider], argv)
                self.assertFalse({'--sandbox', '--disallowed-tools', '--disallowedTools', '--allowedTools', '--no-subagents'} & set(argv))
        lean = {'codex': ['--disable', 'plugins', '--disable', 'apps'], 'claude': ['--strict-mcp-config', '--disable-slash-commands']}
        for provider, flags in lean.items():
            for resume in (None, 'sid'):
                argv, _ = pstack_run.command(provider, 'write', Path('/w'), run, None, None, 'sid', resume)
                self.assertEqual([flag for flag in argv if flag in flags], flags)
                argv, _ = pstack_run.command(provider, 'write', Path('/w'), run, None, None, 'sid', resume, lean=False)
                self.assertFalse(set(flags) - {'--disable'} & set(argv))
        argv, _ = pstack_run.command('grok', 'write', Path('/w'), run, 'grok-4.7', 'low', 'sid', None)
        self.assertEqual(argv[argv.index('--permission-mode') + 1], 'bypassPermissions')
        argv, _ = pstack_run.command('claude', 'write', Path('/w'), run, None, None, 'sid', None, 'plan')
        self.assertEqual(argv[argv.index('--permission-mode') + 1], 'plan')
        self.assertNotIn('--dangerously-skip-permissions', argv)

    def test_environment_keeps_git_credentials_and_withholds_other_vendors(self):
        os.environ.update(GH_TOKEN='g', GITHUB_TOKEN='g', SSH_AUTH_SOCK='/s', XAI_API_KEY='x', OPENAI_API_KEY='o')
        self.addCleanup(lambda: [os.environ.pop(key) for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'SSH_AUTH_SOCK', 'XAI_API_KEY', 'OPENAI_API_KEY')])
        env = pstack_run.environment('codex', Path('/h'), 'pstack/t')
        self.assertEqual((env.get('OPENAI_API_KEY'), env.get('XAI_API_KEY')), ('o', None))
        self.assertEqual((env.get('GH_TOKEN'), env.get('SSH_AUTH_SOCK')), ('g', '/s'))
        config = {env[f'GIT_CONFIG_KEY_{i}']: env[f'GIT_CONFIG_VALUE_{i}'] for i in range(int(env['GIT_CONFIG_COUNT']))}
        self.assertEqual(config['core.hooksPath'], '/h')
        self.assertNotIn('credential.helper', config)

    def test_usage_limit_messages_set_the_limit_and_reset_time(self):
        parser = pstack_run.Parser('claude')
        parser.feed({'type': 'result', 'subtype': 'success', 'is_error': True, 'api_error_status': 429,
                     'result': "You've hit your session limit · resets 12:30pm (UTC)"})
        self.assertEqual((parser.limited, parser.terminal), (True, False))
        self.assertRegex(parser.reset_at, r'T12:30:00Z$')
        parser = pstack_run.Parser('claude')
        parser.feed({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'discussing a usage limit'})
        self.assertEqual((parser.limited, parser.terminal), (False, True))
        after = pstack_run.parse_reset('resets 3:10am (UTC)', __import__('datetime').datetime(2026, 10, 17, 3, 10, tzinfo=__import__('datetime').timezone.utc))
        self.assertEqual(after, '2026-10-18T03:10:00Z')
        self.assertIsNone(pstack_run.parse_reset('no reset here'))


if __name__ == '__main__':
    unittest.main()
