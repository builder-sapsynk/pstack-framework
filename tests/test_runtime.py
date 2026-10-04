import importlib.util
import fcntl
import copy
import hashlib
import json
import os
import sys
from pathlib import Path
import tempfile
import subprocess
import signal
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('runner', Path(__file__).resolve().parents[1] / 'runtime/cli.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
import grok_native as gn

class RuntimeTests(unittest.TestCase):
    def test_codex_credentials_survive_provider_filter(self):
        credentials = {'OPENAI_API_KEY': 'fixture-openai', 'CODEX_API_KEY': 'fixture-codex',
                       'CODEX_ACCESS_TOKEN': 'fixture-access', 'GH_TOKEN': 'fixture-github',
                       'ANTHROPIC_API_KEY': 'fixture-anthropic', 'HTTPS_PROXY': 'fixture-proxy'}
        with patch.dict(os.environ, credentials, clear=True):
            env = r.environment('codex')
        for name in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN', 'HTTPS_PROXY'):
            self.assertEqual(env[name], credentials[name])
        self.assertNotIn('GH_TOKEN', env)
        self.assertNotIn('ANTHROPIC_API_KEY', env)
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.binary = self.root / 'claude'
        self.binary.write_text('''#!/usr/bin/env python3
import sys,json,time
args=sys.argv[1:]
if '--version' in args: print('fixture 1')
elif '--help' in args: print('--model --permission-mode --output-format --setting-sources --strict-mcp-config --no-session-persistence --disable-slash-commands --tools --restricted --disallowedTools --effort')
elif args[:2]==['auth','status']: print(json.dumps({'loggedIn':True}))
else:
 brief=sys.stdin.read().split('\\n\\n', 1)[-1]
 if brief=='sleep': time.sleep(5)
 if brief=='nonzero':
  print('private failure output'); print('private stderr', file=sys.stderr); sys.exit(2)
 if brief=='malformed': print('bad')
 else: print(json.dumps({'type':'result','subtype':'success','result':'answer','model':'wrong' if brief=='mismatch' else 'exact'}))
''')
        self.binary.chmod(0o700)
        self.request = dict(provider='claude', model='exact', mode='read-only', project=str(self.root), cwd=str(self.root), brief='hello', executable=str(self.binary))
    def tearDown(self): self.tmp.cleanup()
    def test_success(self):
        receipt = r.run(self.request)
        self.assertEqual(receipt['status'], 'complete'); self.assertTrue(receipt['modelVerified'])
        self.assertEqual((Path(receipt['job']) / 'response.txt').read_text(), 'answer\n')
        self.assertEqual((Path(receipt['job']).stat().st_mode & 0o777), 0o700)
    def test_malformed_and_mismatch(self):
        for brief in ('malformed', 'mismatch'):
            self.assertEqual(r.run(dict(self.request, brief=brief))['status'], 'failed')
    def test_grok_explicit_dialect(self):
        dialect = {'auth_argv': ['auth', 'status'], 'run_argv': ['-p', '--model', '{model}', '--permission-mode', '{mode}'], 'required_flags': ['--model', '--permission-mode']}
        receipt = r.run(dict(self.request, provider='grok', dialect=dialect))
        self.assertEqual(receipt['status'], 'complete')
        self.assertTrue(receipt['authPreflight'])
        self.assertTrue(receipt['authVerified'])
    def test_codex_pinned_model(self):
        self.binary.write_text("""#!/usr/bin/env python3
import sys,json
args=sys.argv[1:]
if '--version' in args: print('fixture codex')
elif '--help' in args: print('--disable --model --sandbox --cd --ephemeral --json')
elif args[:2]==['features','list']: print('plugins stable true\\nmulti_agent stable true\\nhooks stable true\\nmemories stable false')
elif args[:2]==['login','status']: print('logged in')
else:
 sys.stdin.read()
 print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'answer'}}))
 print(json.dumps({'type':'turn.completed','usage':{'input_tokens':3}}))
""")
        receipt = r.run(dict(self.request, provider='codex'))
        self.assertEqual(receipt['status'], 'complete')
        self.assertEqual(receipt['modelEvidence'], 'pinned-argv')
        self.assertFalse(receipt['modelVerified'])
        argv = receipt['argv']
        self.assertEqual([argv[i + 1] for i, value in enumerate(argv) if value == '--disable'], ['plugins', 'multi_agent', 'hooks', 'memories'])
        self.assertIn('Do not activate a framework router', (Path(receipt['job']) / 'brief.txt').read_text())
    def test_auth_failure(self):
        self.binary.write_text(self.binary.read_text().replace("'loggedIn':True", "'loggedIn':False"))
        self.assertEqual(r.run(self.request)['status'], 'failed')
    def test_timeout(self): self.assertEqual(r.run(dict(self.request, brief='sleep', timeout=.5))['status'], 'timed-out')
    def test_writer(self):
        with self.assertRaisesRegex(ValueError, 'separate git worktree'):
            r.validate(dict(self.request, mode='isolated-write'))
    def test_owned_worktree(self):
        repo = self.root / 'repo'; repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-qm', 'initial'], check=True)
        work = self.root / 'work'
        subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '--detach', str(work)], check=True, capture_output=True)
        request = dict(self.request, mode='isolated-write', project=str(repo), cwd=str(work))
        self.assertEqual(r.validate(request)['cwd'], str(work))
        git_dir = subprocess.run(['git', '-C', str(work), 'rev-parse', '--absolute-git-dir'], capture_output=True, text=True, check=True).stdout.strip()
        with (Path(git_dir) / '.pstack-writer.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            receipt = r.run(request)
            self.assertEqual(receipt['status'], 'failed')
            self.assertIn('reserved', receipt['error'])
        self.assertEqual(r.run(request)['status'], 'complete')
        child = work / 'child'; child.mkdir()
        with self.assertRaises(ValueError): r.validate(dict(request, cwd=str(child)))
        unrelated = self.root / 'unrelated'; unrelated.mkdir()
        with self.assertRaises(ValueError): r.validate(dict(request, project=str(unrelated)))
    def test_cancellation(self):
        request_file = self.root / 'request.json'; request_file.write_text(json.dumps(dict(self.request, brief='sleep')))
        child = subprocess.Popen([sys.executable, str(Path(r.__file__)), 'run', '--request', str(request_file)], stdout=subprocess.PIPE, text=True)
        try:
            end = time.monotonic() + 3
            while time.monotonic() < end:
                paths = list(self.root.glob('.pstack/runs/*/receipt.json'))
                if paths:
                    receipt = json.loads(paths[0].read_text())
                    if receipt.get('argv'): break
                time.sleep(.02)
            child.send_signal(signal.SIGTERM)
            output, _ = child.communicate(timeout=3)
            self.assertEqual(json.loads(output.split('\n', 1)[1])['status'], 'cancelled')
        finally:
            if child.poll() is None: child.kill(); child.wait()
    def test_prompt_file_and_start_callback(self):
        prompt = self.root / 'prompt.txt'; prompt.write_text('hello')
        request = dict(self.request, prompt_file=str(prompt)); del request['brief']
        notices = []
        receipt = r.run(request, on_start=notices.append)
        self.assertEqual(notices[0]['status'], 'starting')
        self.assertEqual(receipt['status'], 'complete')
        self.assertEqual(len(receipt['promptDigest']), 64)
        with self.assertRaises(ValueError): r.validate(dict(request, prompt_file='relative'))
    def test_auth_shapes_terminal_receipts(self):
        original = self.binary.read_text()
        for value in ('null', '[]'):
            self.binary.write_text(original.replace("print(json.dumps({'loggedIn':True}))", 'print(' + repr(value) + ')'))
            receipt = r.run(self.request)
            self.assertEqual(receipt['status'], 'failed')
            self.assertEqual(json.loads((Path(receipt['job']) / 'receipt.json').read_text())['status'], 'failed')
    def test_auth_shapes(self):
        for value in ('null', '[]', '1', '{}', 'bad'):
            self.assertFalse(r.authenticated('claude', 0, value))
    def test_failed_evidence(self):
        for brief in ('malformed', 'mismatch', 'nonzero'):
            receipt = r.run(dict(self.request, brief=brief))
            self.assertEqual(receipt['status'], 'failed')
            for name in ('provider-stdout.txt', 'provider-stderr.txt', 'providerEvents'):
                path = Path(receipt['artifacts'][name])
                self.assertTrue(path.exists()); self.assertEqual(path.stat().st_mode & 0o777, 0o600)
    def test_bad_event_shapes(self):
        for record in ({'type':'item.completed','item':None}, {'type':'item.completed','item':{'type':'agent_message','text':3}}, {'type':'result','result':3}, {'modelUsage':[]}):
            with self.assertRaises(ValueError): r.parse_output('codex', json.dumps(record), 'exact')
    def test_codex_failure_after_completion(self):
        records = [{'type':'item.completed','item':{'type':'agent_message','text':'answer'}}, {'type':'turn.completed'}, {'type':'turn.failed'}]
        with self.assertRaises(ValueError): r.parse_output('codex', '\n'.join(map(json.dumps, records)), 'exact')
    def test_codex_requires_turn_completed(self):
        with self.assertRaises(ValueError): r.parse_output('codex', json.dumps({'type':'result','result':'answer','subtype':'success'}), 'exact')
    def test_fable_family(self):
        response, model, _ = r.parse_output('claude', json.dumps({'type':'result','result':'answer','model':'claude-fable-5'}), 'fable')
        self.assertEqual(model, 'claude-fable-5')
        with self.assertRaises(ValueError): r.parse_output('claude', json.dumps({'type':'result','result':'answer','model':'claude-opus-5'}), 'fable')
    def test_finite_timeout(self):
        for timeout in (float('nan'), float('inf')):
            with self.assertRaises(ValueError): r.validate(dict(self.request, timeout=timeout))
    def test_claude_writer_command_scope(self):
        _, _, args, _ = r.profile(dict(self.request, mode='isolated-write', allowed_commands=['python -m unittest']))
        self.assertIn('Bash(python -m unittest:*)', args)
        self.assertNotIn('Bash', args[args.index('--disallowedTools') + 1].split(','))
    def test_project_executable_doctor(self):
        config = self.root / '.pstack'; config.mkdir()
        (config / 'config.json').write_text(json.dumps({'providers': {'claude': {'executable': str(self.binary)}}}))
        self.assertTrue(r.doctor(str(self.root))['providers']['claude']['authPreflight'])
    def test_credentials(self):
        old = dict(os.environ)
        try:
            os.environ.update(GH_TOKEN='private', OPENAI_API_KEY='private', ANTHROPIC_API_KEY='needed', HTTPS_PROXY='proxy')
            env = r.environment('claude')
            self.assertNotIn('GH_TOKEN', env); self.assertNotIn('OPENAI_API_KEY', env)
            self.assertEqual(env['ANTHROPIC_API_KEY'], 'needed'); self.assertEqual(env['HTTPS_PROXY'], 'proxy')
        finally:
            os.environ.clear(); os.environ.update(old)
    def test_stale_identity(self): self.assertFalse(r.alive(os.getpid(), 'not-process-start'))
    def test_grok_requires_dialect(self):
        with self.assertRaisesRegex(ValueError, 'managed-host requires'):
            r.run(dict(self.request, provider='grok'))
        self.assertEqual(r.run(dict(self.request, provider='grok', dialect={}))['status'], 'failed')


def grok_events(model='grok-4.7', cwd='/fixture'):
    return [
        {'type': 'system', 'subtype': 'init', 'model': model, 'cwd': cwd, 'permissionMode': 'dontAsk', 'tools': [], 'mcp_servers': [], 'skills': ['code-review'], 'session_id': 'fixture-session'},
        {'type': 'assistant', 'message': {'role': 'assistant', 'model': model, 'content': [{'type': 'thinking', 'thinking': 'private reasoning', 'signature': 'fixture'}, {'type': 'text', 'text': 'answer'}], 'stop_reason': 'end_turn'}, 'session_id': 'fixture-session'},
        {'type': 'result', 'subtype': 'success', 'is_error': False, 'stop_reason': 'end_turn', 'result': 'answer', 'session_id': 'fixture-session', 'usage': {'input_tokens': 3, 'server_tool_use': {'web_search_requests': 0}}, 'modelUsage': {'grok-4.7-build': {'costUSD': .001, 'webSearchRequests': 0}}},
    ]


class GrokNativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.binary = self.root / 'grok'
        self.inspect = {'hooks': [], 'mcpServers': [], 'projectInstructions': [], 'plugins': [], 'skills': [], 'agents': [{'source': {'type': 'builtin'}, 'name': 'explore'}]}
        (self.root / 'inspect.json').write_text(json.dumps(self.inspect))
        self.binary.write_text('''#!/usr/bin/env python3
import sys,json,os,time,subprocess
from pathlib import Path
args=sys.argv[1:]
if '--version' in args: print('1.0.46 fixture')
elif '--help' in args: print('--model --cwd --permission-mode --sandbox --output-format --tools --disallowed-tools --no-subagents --disable-web-search --prompt-file --reasoning-effort --allow --no-plan')
elif args==['models']: print('You are logged in with grok.com.\\n\\nAvailable models:\\n  * grok-4.7 (default)\\n  - grok-4.7-build-fast')
elif args==['inspect','--json']: print(Path('inspect.json').read_text())
else:
 assert sys.stdin.read()==''
 assert args[args.index('--tools')+1]=='read_file'
 assert args[args.index('--disallowed-tools')+1]=='read_file,search_tool,use_tool'
 assert args[args.index('--sandbox')+1]=='off'
 for key in ('GROK_MEMORY','GROK_SUBAGENTS','GROK_TOOL_SEARCH','GROK_WRITE_FILE','GROK_CURSOR_HOOKS_ENABLED','GROK_CLAUDE_SKILLS_ENABLED'): assert os.environ[key]=='0'
 assert os.environ['GROK_DISABLE_AUTOUPDATER']=='1'
 prompt=Path(args[args.index('--prompt-file')+1])
 assert prompt.stat().st_mode & 0o777 == 0o600
 brief=prompt.read_text()
 if brief.endswith('sleep'):
  child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
  Path('descendant.pid').write_text(str(child.pid))
  time.sleep(5)
 events=json.loads(Path('events.json').read_text())
 for event in events: print(json.dumps(event))
''')
        self.binary.chmod(0o700)
        (self.root / 'events.json').write_text(json.dumps(grok_events(cwd=str(self.root))))
        self.request = dict(provider='grok', dialect=dict(r.GROK_DIALECT), model='grok-4.7', effort='medium', mode='read-only', project=str(self.root), cwd=str(self.root), brief='hello', executable=str(self.binary))

    def tearDown(self):
        self.tmp.cleanup()

    def parse(self, events):
        return r.parse_output('grok', '\n'.join(map(json.dumps, events)), 'grok-4.7', r.GROK_DIALECT, '/fixture')

    def test_native_schema_and_billing_label(self):
        response, model, metrics = self.parse(grok_events())
        self.assertEqual((response, model), ('answer', 'grok-4.7'))
        self.assertIn('grok-4.7-build', metrics['modelUsage'])
        self.assertNotIn('private reasoning', response)
        self.assertEqual(metrics['observedSkills'], ['code-review'])

    def test_session_models_tools_and_terminal_fail_closed(self):
        mutations = [
            (0, 'tools', ['read_file']), (0, 'tools', None), (0, 'mcp_servers', ['unexpected']),
            (0, 'model', 'grok-4.6'), (0, 'session_id', ''), (0, 'permissionMode', 'bypassPermissions'), (0, 'cwd', '/other'),
            (1, 'session_id', 'different'), (2, 'session_id', None), (2, 'subtype', 'error'),
            (2, 'is_error', True), (2, 'is_error', None), (2, 'result', ''), (2, 'result', 3),
            (2, 'stop_reason', 'max_tokens'), (2, 'modelUsage', []), (2, 'usage', []),
        ]
        for index, key, value in mutations:
            with self.subTest(index=index, key=key, value=value):
                events = grok_events(); events[index][key] = value
                with self.assertRaises(ValueError): self.parse(events)
        for key, value in [('model', 'grok-4.6'), ('stop_reason', 'tool_use'), ('content', [{'type': 'tool_use', 'name': 'read_file'}]), ('content', None)]:
            with self.subTest(key=key):
                events = grok_events(); events[1]['message'][key] = value
                with self.assertRaises(ValueError): self.parse(events)
        events = grok_events(); events[2]['usage']['server_tool_use']['web_search_requests'] = 1
        with self.assertRaises(ValueError): self.parse(events)
        events = grok_events(); events[2]['modelUsage']['grok-4.7-build']['webSearchRequests'] = 1
        with self.assertRaises(ValueError): self.parse(events)
        original = grok_events()
        for events in (original[1:], original[:2], [original[0], original[2]], original + [original[2]], [original[0], original[0]] + original[1:], original + [{'type': 'error'}], [original[0], {'type': 'user', 'session_id': 'fixture-session'}] + original[1:]):
            with self.assertRaises(ValueError): self.parse(events)

    def test_private_prompt_transport_and_receipt(self):
        prompt = self.root / 'source.txt'; prompt.write_text('private payload')
        receipt = r.run(dict(self.request, prompt_file=str(prompt), brief='ignored'))
        self.assertEqual(receipt['status'], 'complete')
        self.assertEqual(receipt['transport'], 'subprocess-prompt-file')
        self.assertEqual(receipt['confinement'], 'response-only')
        self.assertEqual(receipt['filesystemIsolation'], 'unavailable')
        self.assertTrue(receipt['authVerified']); self.assertTrue(receipt['configurationPreflight'])
        brief = (Path(receipt['job']) / 'brief.txt').read_text()
        self.assertEqual(brief, r.WORKER_HEADER + 'private payload')
        self.assertEqual(receipt['promptDigest'], hashlib.sha256(brief.encode()).hexdigest())
        self.assertNotIn('private payload', ' '.join(receipt['argv']))
        self.assertEqual((Path(receipt['job']) / 'response.txt').read_text(), 'answer\n')
        for artifact in receipt['artifacts'].values():
            if Path(artifact).exists(): self.assertEqual(Path(artifact).stat().st_mode & 0o777, 0o600)

    def test_named_profile_refuses_writes_and_extra_flags(self):
        for dialect in (dict(r.GROK_DIALECT, run_argv=['--yolo']), dict(r.GROK_DIALECT, confinement='tool-permissions'), dict(r.GROK_DIALECT, id='future')):
            with self.assertRaises(ValueError): r.profile(dict(self.request, dialect=dialect))
        with self.assertRaisesRegex(ValueError, 'isolated writing'): r.profile(dict(self.request, mode='isolated-write'))
        with self.assertRaises(ValueError): r.profile(dict(self.request, allowed_commands=['python tests.py']))
        project = self.root / 'project'; project.mkdir()
        scratch = self.root / 'scratch'; scratch.mkdir()
        receipt = r.run(dict(self.request, mode='isolated-write', project=str(project), cwd=str(scratch), isolated_scratch=True))
        self.assertEqual(receipt['status'], 'failed'); self.assertIn('isolated writing', receipt['error'])
        self.assertEqual(list(scratch.iterdir()), [])
        for flag in ('--always-approve', '--yolo', '--permission-mode=bypassPermissions', 'bypassPermissions'):
            legacy = {'auth_argv': ['auth', 'status'], 'run_argv': ['--model', '{model}', '--mode', '{mode}', flag], 'required_flags': ['--model']}
            with self.assertRaises(ValueError): r.profile(dict(self.request, dialect=legacy, effort=''))

    def test_discovery_rejection_prevents_dispatch(self):
        for key in ('hooks', 'mcpServers', 'projectInstructions', 'plugins', 'skills', 'agents'):
            discovery = copy.deepcopy(self.inspect); discovery[key] = [{'source': {'type': 'project'}}]
            (self.root / 'inspect.json').write_text(json.dumps(discovery))
            receipt = r.run(self.request)
            self.assertEqual(receipt['status'], 'failed'); self.assertIn(key, receipt['error'])
            self.assertNotIn('providerEvents', receipt['artifacts'])

    def test_actual_bundled_skill_shape_and_path_boundary(self):
        grok_home = self.root / 'grok-home'
        discovery = copy.deepcopy(self.inspect)
        discovery['skills'] = [{'name': 'build-with-ai', 'source': {'type': 'bundled', 'path': str(grok_home / 'bundled/skills/build-with-ai/SKILL.md')}, 'userInvocable': True}]
        self.assertEqual(r.inspect_grok(json.dumps(discovery), str(grok_home))['skills'][0]['name'], 'build-with-ai')
        (self.root / 'inspect.json').write_text(json.dumps(discovery))
        with patch.dict(os.environ, {'GROK_HOME': str(grok_home)}):
            self.assertEqual(r.run(self.request)['status'], 'complete')
        for path in (str(grok_home / 'skills/external/SKILL.md'), str(grok_home / 'bundled/skills/../../../outside/SKILL.md'), 'relative/SKILL.md'):
            discovery['skills'][0]['source']['path'] = path
            with self.assertRaises(ValueError): r.inspect_grok(json.dumps(discovery), str(grok_home))
        inside = grok_home / 'bundled/skills'; inside.mkdir(parents=True)
        (inside / 'escape').symlink_to(self.root, target_is_directory=True)
        discovery['skills'][0]['source']['path'] = str(inside / 'escape/SKILL.md')
        with self.assertRaises(ValueError): r.inspect_grok(json.dumps(discovery), str(grok_home))

    def test_catalog_exact_match_and_login_proof(self):
        original = self.binary.read_text()
        for replacement in ('You are logged out.', 'You are logged in with grok.com.extra'):
            self.binary.write_text(original.replace('You are logged in with grok.com.', replacement))
            receipt = r.run(self.request)
            self.assertEqual(receipt['status'], 'failed'); self.assertNotIn('argv', receipt)
        self.binary.write_text(original)
        self.assertEqual(r.run(dict(self.request, model='grok-4'))['status'], 'failed')
        self.assertEqual(r.grok_catalog('You are logged in with grok.com.\nAvailable models:\n * grok-4.7 (default)\n - grok-4.7-build-fast'), ['grok-4.7', 'grok-4.7-build-fast'])

    def test_doctor_named_preflights_are_not_live_proof(self):
        config = self.root / '.pstack'; config.mkdir()
        (config / 'config.json').write_text(json.dumps({'providers': {'grok': {'executable': str(self.binary), 'dialect': r.GROK_DIALECT}}}))
        item = r.doctor(str(self.root))['providers']['grok']
        for key in ('versionProbe', 'helpPreflight', 'authPreflight', 'catalogPreflight', 'configurationPreflight'): self.assertTrue(item[key])
        self.assertEqual(item['authenticatedExecution'], 'not verified')
        self.assertIn('response-only live execution probe', item['status'])
        self.assertEqual(item['toolAccess'], 'must be verified in live init')

    def test_native_timeout_and_failed_private_evidence(self):
        self.assertEqual(r.run(dict(self.request, brief='sleep', timeout=.5))['status'], 'timed-out')
        events = grok_events(cwd=str(self.root)); events[0]['tools'] = ['read_file']
        (self.root / 'events.json').write_text(json.dumps(events))
        receipt = r.run(self.request)
        self.assertEqual(receipt['status'], 'failed')
        self.assertFalse(receipt.get('authVerified', False))
        self.assertEqual(json.loads((Path(receipt['job']) / 'receipt.json').read_text())['status'], 'failed')
        self.assertTrue(Path(receipt['artifacts']['providerEvents']).exists())

    def test_native_cancel_preserves_terminal_receipt_and_stops_descendant(self):
        request_file = self.root / 'request.json'; request_file.write_text(json.dumps(dict(self.request, brief='sleep')))
        runner = subprocess.Popen([sys.executable, r.__file__, 'run', '--request', str(request_file)], stdout=subprocess.PIPE, text=True)
        try:
            end = time.monotonic() + 5
            while time.monotonic() < end and not (self.root / 'descendant.pid').exists(): time.sleep(.02)
            self.assertTrue((self.root / 'descendant.pid').exists())
            receipt_file = next(self.root.glob('.pstack/runs/*/receipt.json'))
            receipt = json.loads(receipt_file.read_text())
            cancel = subprocess.run([sys.executable, r.__file__, 'cancel', '--project', str(self.root), '--job', receipt['job_id']], capture_output=True, text=True)
            self.assertEqual(cancel.returncode, 0)
            output, _ = runner.communicate(timeout=5)
            self.assertEqual(json.loads(output.split('\n', 1)[1])['status'], 'cancelled')
            self.assertEqual(r.status(receipt['job'])['status'], 'cancelled')
            descendant = int((self.root / 'descendant.pid').read_text())
            stat = Path(f'/proc/{descendant}/stat')
            self.assertTrue(not stat.exists() or stat.read_text().rsplit(')', 1)[1].split()[0] == 'Z')
        finally:
            if runner.poll() is None: runner.kill(); runner.wait()

    def test_grok_environment_controls_preserve_transport(self):
        with patch.dict(os.environ, {'GROK_HOME': '/private/home', 'XAI_API_KEY': 'provider', 'OPENAI_API_KEY': 'other', 'HTTPS_PROXY': 'proxy', 'SSL_CERT_FILE': '/cert', 'GROK_MEMORY': '1', 'GROK_CURSOR_HOOKS_ENABLED': '1'}, clear=True):
            env = r.environment('grok')
        self.assertEqual(env['GROK_HOME'], '/private/home'); self.assertEqual(env['XAI_API_KEY'], 'provider')
        self.assertEqual(env['HTTPS_PROXY'], 'proxy'); self.assertEqual(env['SSL_CERT_FILE'], '/cert')
        self.assertNotIn('OPENAI_API_KEY', env)
        for vendor in ('CURSOR', 'CLAUDE'):
            for surface in ('SKILLS', 'RULES', 'AGENTS', 'MCPS', 'HOOKS', 'SESSIONS'):
                self.assertEqual(env[f'GROK_{vendor}_{surface}_ENABLED'], '0')

    def test_task_lane_accepts_web_usage_and_legacy_parser_does_not(self):
        events = grok_events()
        events[2]['usage']['server_tool_use']['web_search_requests'] = 2
        events[2]['modelUsage']['grok-4.7-build']['webSearchRequests'] = 2
        with self.assertRaises(ValueError): self.parse(events)
        response, _, metrics = r.parse_output('grok', '\n'.join(map(json.dumps, events)), 'grok-4.7', gn.TASK_DIALECT, '/fixture')
        self.assertEqual(response, 'answer')
        self.assertEqual(metrics['usage']['server_tool_use']['web_search_requests'], 2)
        self.assertEqual(metrics['modelUsage']['grok-4.7-build']['webSearchRequests'], 2)
        events[2]['usage']['server_tool_use']['web_fetch_requests'] = 1
        with self.assertRaises(ValueError): r.parse_output('grok', '\n'.join(map(json.dumps, events)), 'grok-4.7', gn.TASK_DIALECT, '/fixture')

    def test_task_profile_header_environment_inspect_and_doctor(self):
        request = dict(self.request, dialect=dict(gn.TASK_DIALECT), mode='read-only', capability_scope=gn.capability_scope('read-only'),
                       host_boundary={'host': 'codex-managed-exec', 'writable_roots': [str(self.root)], 'read_only_probe': '/proc'})
        with self.assertRaisesRegex(ValueError, 'explicit capability scope'): r.validate(dict(request, capability_scope={}))
        with self.assertRaisesRegex(ValueError, 'exact command grants'): r.validate(dict(request, allowed_commands=['python3 -m unittest discover -s tests -q']))
        _, _, args, _ = r.profile(dict(request, resume_session='11111111-1111-4111-8111-111111111111'))
        self.assertIn('--resume', args); self.assertNotIn('--tools', args); self.assertNotIn('--disable-web-search', args); self.assertNotIn('--no-subagents', args)
        self.assertNotIn('--yolo', args); self.assertIn('*', args); self.assertEqual(args[args.index('--permission-mode') + 1], 'dontAsk'); self.assertEqual(args[args.index('--sandbox') + 1], 'off')
        with patch.dict(os.environ, {'XAI_API_KEY': 'provider', 'OPENAI_API_KEY': 'other', 'GH_TOKEN': 'gh', 'HTTPS_PROXY': 'proxy'}, clear=True):
            env = r.environment('grok', gn.TASK_DIALECT, 'isolated-write')
        self.assertEqual(env['GROK_SUBAGENTS'], '1'); self.assertEqual(env['GROK_WEB_FETCH'], '1'); self.assertEqual(env['GROK_WRITE_FILE'], '1')
        self.assertEqual(env['GROK_MEMORY'], '1'); self.assertEqual(env['GROK_TOOL_SEARCH'], '1'); self.assertEqual(env['GROK_LSP_TOOLS'], '1'); self.assertEqual(env['XAI_API_KEY'], 'provider'); self.assertEqual(env['HTTPS_PROXY'], 'proxy')
        self.assertNotIn('OPENAI_API_KEY', env); self.assertNotIn('GH_TOKEN', env)
        self.assertEqual(r.environment('grok', gn.TASK_DIALECT, 'read-only')['GROK_WRITE_FILE'], '0')
        grok_home = self.root / 'grok-home'
        discovery = copy.deepcopy(self.inspect)
        discovery['agents'] = [{'name': 'explore', 'source': {'type': 'bundled', 'path': str(grok_home / 'bundled/agents/explore.md')}}]
        with self.assertRaises(ValueError): r.inspect_grok(json.dumps(discovery), str(grok_home), gn.DIALECT)
        self.assertEqual(r.inspect_grok(json.dumps(discovery), str(grok_home), gn.TASK_DIALECT)['agents'][0]['name'], 'explore')
        discovery['agents'][0]['source']['path'] = str(self.root / 'custom-agent.md')
        with self.assertRaises(ValueError): r.inspect_grok(json.dumps(discovery), str(grok_home), gn.TASK_DIALECT)
        config = self.root / '.pstack'; config.mkdir()
        (config / 'config.json').write_text(json.dumps({'providers': {'grok': {'executable': str(self.binary), 'dialect': gn.TASK_DIALECT}}}))
        item = r.doctor(str(self.root))['providers']['grok']
        self.assertEqual(item['profile'], 'grok-build-native-task-1')
        self.assertIn('managed-host task live execution probe', item['status'])
        self.assertEqual(item['toolAccess'], 'must be verified in live init')
        self.assertTrue(item['helpPreflight'])

    def test_task_run_discovers_inventory_and_keeps_web_usage(self):
        tools = ['grep', 'list_dir', 'read_file', 'run_terminal_command', 'spawn_subagent', 'todo_write', 'web_fetch', 'web_search']
        events = grok_events(cwd=str(self.root))
        events[0]['tools'] = tools
        events[2]['usage']['server_tool_use']['web_search_requests'] = 2
        events[2]['modelUsage']['grok-4.7-build']['webSearchRequests'] = 2
        (self.root / 'events.json').write_text(json.dumps(events))
        self.binary.write_text('''#!/usr/bin/env python3
import sys, json, os
from pathlib import Path
args=sys.argv[1:]
if '--version' in args: print('1.0.46 fixture')
elif '--help' in args: print('--model --cwd --permission-mode --sandbox --output-format --disallowed-tools --no-plan --allow --prompt-file --reasoning-effort')
elif args==['models']: print('You are logged in with grok.com.\\n\\nAvailable models:\\n  * grok-4.7 (default)')
elif args==['inspect','--json']: print(Path('inspect.json').read_text())
else:
 home=Path(os.environ['GROK_HOME'])
 config=(home/'config.toml').read_text()
 assert 'web_fetch = true' in config, config
 assert '[subagents]\\nenabled = true' in config, config
 assert os.environ['GROK_SUBAGENTS']=='1'
 assert os.environ['GROK_WEB_FETCH']=='1'
 assert os.environ['GROK_WRITE_FILE']=='0'
 assert os.environ['GROK_MEMORY']=='1'
 assert os.environ['GROK_CURSOR_HOOKS_ENABLED']=='0'
 assert 'OPENAI_API_KEY' not in os.environ
 assert os.environ['XAI_API_KEY']=='provider'
 assert '--disable-web-search' not in args
 assert '--no-subagents' not in args
 assert '--tools' not in args
 assert '--yolo' not in args and '--always-approve' not in args and 'bypassPermissions' not in args
 assert args[args.index('--permission-mode')+1]=='dontAsk'
 assert args[args.index('--sandbox')+1]=='off'
 assert '*' in args
 brief=Path(args[args.index('--prompt-file')+1]).read_text()
 assert 'Authorized native child agents are permitted' in brief
 assert 'launch subagents' not in brief
 assert 'trusted terminal can exceed user-authorized instructions' in brief
 for event in json.loads(Path('events.json').read_text()): print(json.dumps(event))
''')
        self.binary.chmod(0o700)
        oauth = self.root / 'oauth'; oauth.mkdir(); (oauth / 'auth.json').write_text('{}')
        request = dict(provider='grok', dialect=dict(gn.TASK_DIALECT), model='grok-4.7', effort='medium', mode='read-only',
                       project=str(self.root), cwd=str(self.root), brief='read the canonical docs', executable=str(self.binary),
                       capability_scope=gn.capability_scope('read-only'),
                       host_boundary={'host': 'codex-managed-exec', 'writable_roots': [str(self.root)], 'read_only_probe': '/proc'})
        with patch.dict(os.environ, {'GROK_HOME': str(oauth), 'XAI_API_KEY': 'provider', 'OPENAI_API_KEY': 'other', 'HTTPS_PROXY': 'proxy'}), patch.object(gn, 'probe_boundary', return_value={'kind': 'outside-write-denied', 'scope': 'fixture only'}):
            receipt = r.run(request)
        detail = receipt.get('error', '')
        stderr = receipt.get('artifacts', {}).get('provider-stderr.txt')
        if stderr and Path(stderr).exists(): detail += '\n' + Path(stderr).read_text()
        self.assertEqual(receipt['status'], 'complete', detail)
        self.assertEqual(receipt['confinement'], 'managed-host')
        self.assertEqual(receipt['metrics']['usage']['server_tool_use']['web_search_requests'], 2)
        self.assertEqual(receipt['metrics']['nativeTools'], sorted(tools))
        self.assertEqual(receipt['capabilityAvailability']['child_agents']['status'], 'observed-in-init')
        self.assertEqual(receipt['capabilityAvailability']['file_edit']['status'], 'unverified')
        self.assertTrue(all(item['status'] in ('observed-in-init', 'unverified') for item in receipt['capabilityAvailability'].values() if isinstance(item, dict)))
        self.assertIn('artifact verification separate', receipt['toolAccess'])
        self.assertIn('host sandbox', receipt['terminalReach'])
        self.assertIn('semantic enforcement of user-authorized scope', receipt['unsupportedCapabilities'])
        self.assertIn('native Codex collaboration API', receipt['unsupportedCapabilities'])
        self.assertNotIn('--tools', receipt['argv']); self.assertNotIn('--disable-web-search', receipt['argv'])
        brief = (Path(receipt['job']) / 'brief.txt').read_text()
        self.assertTrue(brief.startswith(gn.TASK_HEADER))
        self.assertNotIn('launch subagents', brief)

if __name__ == '__main__': unittest.main()
