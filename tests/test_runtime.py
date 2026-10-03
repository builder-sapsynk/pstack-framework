import importlib.util
import fcntl
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
 brief=sys.stdin.read()
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
        self.assertEqual(r.run(dict(self.request, provider='grok'))['status'], 'failed')

if __name__ == '__main__': unittest.main()
