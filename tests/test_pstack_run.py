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
SILENT = '#!/bin/sh\nexec sleep 60\n'
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
        self.assertEqual(argv[argv.index('--sandbox') + 1], 'workspace-write')
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
        patch = self.invoke(CODEX_OK, 'diff', 'task-1', '--patch').stdout
        self.assertIn('+resumed', patch)
        self.assertEqual(self.invoke(CODEX_OK, 'clean', 'task-1', '--force').returncode, 0)
        self.assertFalse(worktree.exists())

    def test_read_task_runs_in_project_without_worktree(self):
        result = self.invoke(CODEX_NO_TERMINAL, 'run', 'codex', 'reader', str(self.brief), '--mode', 'read')
        status = self.status('reader')
        self.assertEqual((result.returncode, status['state'], status['cwd']), (1, 'failed', str(self.project)))
        self.assertEqual(status['error'], 'no successful terminal event')
        self.assertIsNone(status['branch'])
        argv = status['argv']
        self.assertEqual(argv[argv.index('--sandbox') + 1], 'read-only')
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
        for provider, mode in (('grok', 'write'), ('grok', 'read'), ('claude', 'write'), ('claude', 'read'), ('codex', 'write')):
            argv, _ = pstack_run.command(provider, mode, Path('/w'), run, None, None, 'sid', None)
            self.assertFalse([part for part in argv if 'bypass' in part.lower() or part in ('--always-approve', '--yolo')])
        argv, _ = pstack_run.command('grok', 'read', Path('/w'), run, 'grok-4.7', 'low', 'sid', None)
        self.assertEqual(argv[argv.index('--disallowed-tools') + 1], 'write,search_replace')
        self.assertEqual(argv[argv.index('--permission-mode') + 1], 'auto')


if __name__ == '__main__':
    unittest.main()
