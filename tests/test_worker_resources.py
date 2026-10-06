import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
import cli


FAKE = '''#!/usr/bin/env python3
import json, sys
from pathlib import Path
args = sys.argv[1:]
if '--version' in args: print('fixture')
elif '--help' in args:
 print('--disable --model --sandbox --cd --ephemeral --json --permission-mode --output-format --setting-sources --strict-mcp-config --no-session-persistence --disable-slash-commands --tools --restricted --disallowedTools')
elif args[:2] == ['features', 'list']: print('plugins stable true\\nmulti_agent stable true\\nhooks stable true\\nmemories stable false')
elif args[:2] == ['login', 'status']: print('logged in')
elif args[:2] == ['auth', 'status']: print(json.dumps({'loggedIn': True}))
else:
 prompt = Path(args[args.index('--prompt-file') + 1]).read_text() if '--prompt-file' in args else sys.stdin.read()
 Path(sys.argv[0] + '.prompt').write_text(prompt)
 if 'exec' in args:
  print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'fixture answer'}}))
  print(json.dumps({'type': 'turn.completed'}))
 elif '--prompt-file' in args:
  print(json.dumps({'type': 'text', 'data': 'fixture answer'}))
  print(json.dumps({'type': 'end', 'stopReason': 'end_turn'}))
 else:
  print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'fixture answer', 'model': 'fixture'}))
'''


class WorkerResourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
        subprocess.run(['git', '-C', str(self.project), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-qm', 'base'], check=True)
        self.binary = self.root / 'fixture-cli'
        self.binary.write_text(FAKE)
        self.binary.chmod(0o700)
        self.leaf = ROOT / 'plugins/sapsynk-pstack/skills/principle-prove-it-works/SKILL.md'
        self.brief = self.root / 'brief.md'
        self.brief.write_text(f'Apply `{self.leaf}`. Verify the fixture.\n')
        self.request = dict(provider='codex', model='fixture', mode='read-only',
                            project=str(self.project), cwd=str(self.project),
                            brief=self.brief.read_text(), executable=str(self.binary))

    def local(self, provider, task='resources', *extra, runner=None):
        env = {**os.environ, provider.upper() + '_BINARY': str(self.binary)}
        return subprocess.run([sys.executable, str(runner or ROOT / 'runtime/pstack_run.py'), '--project',
                               str(self.project), 'run', provider, task, str(self.brief),
                               '--mode', 'read', *extra], env=env, capture_output=True, text=True, timeout=15)

    def manifest(self, prompt):
        return json.loads(prompt.split('--- WORKER RESOURCES ---\n', 1)[1].split('\n--- BRIEF ---\n', 1)[0])

    def test_local_emits_same_exact_resources_for_all_provider_launches(self):
        for provider in ('codex', 'grok', 'claude'):
            with self.subTest(provider=provider):
                result = self.local(provider, provider)
                self.assertEqual(result.returncode, 0, result.stderr)
                run = self.project / '.pstack/runs' / provider
                prompt = (run / 'prompt.txt').read_text()
                self.assertEqual(Path(str(self.binary) + '.prompt').read_text(), prompt)
                manifest = self.manifest(prompt)
                self.assertEqual(manifest['dispatch_owner'], 'coordinator')
                self.assertIn(str(ROOT / 'plugins/sapsynk-pstack/skills/poteto-mode/SKILL.md'), manifest['required_paths'])
                self.assertIn(str(self.leaf), manifest['required_paths'])
                self.assertEqual(manifest['plugins'], {})
                self.assertEqual(manifest['project']['pin'], None)
                self.assertEqual(manifest, json.loads((run / 'resources.json').read_text()))
                self.assertIn('bootstrap', prompt)
                self.assertNotIn('Do not load the pstack router, poteto-mode', prompt)

    def test_generated_package_runner_uses_its_own_installed_resources(self):
        package = ROOT / 'plugins/sapsynk-pstack'
        result = self.local('codex', runner=package / 'runtime/pstack_run.py')
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = self.manifest((self.project / '.pstack/runs/resources/prompt.txt').read_text())
        self.assertEqual(manifest['framework']['root'], str(package))
        self.assertIn(str(package / 'skills/poteto-mode/SKILL.md'), manifest['required_paths'])

    def test_quoted_named_paths_preserve_spaces_and_matched_playbook(self):
        leaf = self.root / 'resource directory/skills/custom/SKILL.md'
        leaf.parent.mkdir(parents=True)
        leaf.write_text('fixture skill')
        playbook = ROOT / 'plugins/sapsynk-pstack/skills/poteto-mode/playbooks/bug-fix.md'
        self.brief.write_text(f'Read `{leaf}` and `{playbook}`.\n')
        result = self.local('codex')
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = self.manifest((self.project / '.pstack/runs/resources/prompt.txt').read_text())
        self.assertIn(str(leaf), manifest['required_paths'])
        self.assertIn(str(playbook), manifest['required_paths'])
        self.assertEqual(manifest['playbooks']['bug-fix'], str(playbook))

    def test_urls_and_relative_references_are_not_absolute_resources(self):
        self.brief.write_text(f'Review https://example.invalid/skills/example/SKILL.md and '
                              f'skills/example/SKILL.md. Read `{self.leaf}`.\n')
        result = self.local('codex')
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = self.manifest((self.project / '.pstack/runs/resources/prompt.txt').read_text())
        self.assertIn(str(self.leaf), manifest['required_paths'])

    def test_managed_prompt_digest_covers_manifest_for_all_providers(self):
        for provider in ('codex', 'claude', 'grok'):
            request = dict(self.request, provider=provider)
            if provider == 'grok':
                request['dialect'] = {'auth_argv': ['auth', 'status'],
                                      'run_argv': ['-p', '--model', '{model}', '--permission-mode', '{mode}'],
                                      'required_flags': ['--model', '--permission-mode']}
            with self.subTest(provider=provider):
                receipt = cli.run(request)
                self.assertEqual(receipt['status'], 'complete', receipt.get('error'))
                run = Path(receipt['job'])
                prompt = (run / 'brief.txt').read_text()
                self.assertEqual(Path(str(self.binary) + '.prompt').read_text(), prompt)
                manifest = self.manifest(prompt)
                self.assertIn(str(self.leaf), manifest['required_paths'])
                self.assertEqual(manifest, json.loads((run / 'resources.json').read_text()))
                self.assertEqual(receipt['promptDigest'], hashlib.sha256(prompt.encode()).hexdigest())
                self.assertEqual(Path(receipt['artifacts']['resources']).stat().st_mode & 0o777, 0o600)

    def test_missing_and_unreadable_named_paths_prevent_launch(self):
        leaf = self.root / 'skills/custom/SKILL.md'
        for state in ('missing', 'unreadable'):
            with self.subTest(state=state):
                if state == 'unreadable':
                    leaf.parent.mkdir(parents=True)
                    leaf.write_text('fixture leaf')
                    leaf.chmod(0)
                self.brief.write_text(f'Apply `{leaf}`.\n')
                result = self.local('codex', state)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn(str(leaf), result.stderr)
                with self.assertRaisesRegex(ValueError, 'worker resource'):
                    cli.run(dict(self.request, brief=self.brief.read_text()))
                self.assertFalse(Path(str(self.binary) + '.prompt').exists())
        leaf.chmod(0o600)

    def test_project_pin_mismatch_prevents_launch(self):
        config = self.project / '.pstack'
        config.mkdir()
        pin = json.loads((ROOT / 'plugins/sapsynk-pstack/framework.json').read_text())
        pin.update(source_digest='0' * 64, upstream_revision=pin['upstream_commit'], revision='1' * 40)
        (config / 'framework.lock.json').write_text(json.dumps(pin))
        result = self.local('codex')
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('pin', result.stderr)
        with self.assertRaisesRegex(ValueError, 'pin'):
            cli.run(self.request)

    def test_locked_plugins_and_project_skills_use_canonical_paths(self):
        config = self.project / '.pstack'
        config.mkdir()
        installed = self.root / 'installed'
        plugins = {}
        for name, skills in [('sapsynk-dyl', ['dyl-review', 'principle-the-algorithm']),
                             ('sapsynk-learning', ['continual-learning']), ('sapsynk-teamkit', ['verify-this'])]:
            package = installed / name
            files = {}
            for skill in skills:
                path = package / 'skills' / skill / 'SKILL.md'
                path.parent.mkdir(parents=True)
                path.write_text('fixture ' + skill)
                files[str(path.relative_to(package))] = hashlib.sha256(path.read_bytes()).hexdigest()
                self.brief.write_text(self.brief.read_text() + f'Read {path}\n')
            plugins[name] = dict(version='0.1.1', native_plugin_id=name + '@fixture', files=files)
        (config / 'plugins.lock.json').write_text(json.dumps(dict(source_revision='2' * 40, plugins=plugins)))
        for skill in ('sapsynk-project', 'verify-fixture'):
            path = self.project / '.agents/skills' / skill / 'SKILL.md'
            path.parent.mkdir(parents=True)
            path.write_text('project verification fixture')
        result = self.local('codex')
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = self.manifest((self.project / '.pstack/runs/resources/prompt.txt').read_text())
        self.assertEqual(manifest['plugins']['sapsynk-dyl']['root'], str(installed / 'sapsynk-dyl'))
        self.assertIn(str(self.project / '.agents/skills/verify-fixture/SKILL.md'), manifest['required_paths'])
        self.assertIn(str(installed / 'sapsynk-teamkit/skills/verify-this/SKILL.md'), manifest['required_paths'])
        self.brief.write_text('Verify the fixture.\n')
        cache = self.root / 'codex-home'
        for name in plugins:
            target = cache / 'plugins/cache/fixture' / name
            target.mkdir(parents=True)
            (target / '0.1.1').symlink_to(installed / name, target_is_directory=True)
        with patch.dict(os.environ, {'CODEX_HOME': str(cache)}):
            result = self.local('codex', 'from-lock')
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = cli.run(dict(self.request, brief=self.brief.read_text()))
            self.assertEqual(receipt['status'], 'complete', receipt.get('error'))
            resolved = self.manifest((Path(receipt['job']) / 'brief.txt').read_text())
            self.assertEqual(resolved['plugins']['sapsynk-dyl']['root'], str(installed / 'sapsynk-dyl'))
        self.brief.write_text(f'Read {installed / "sapsynk-dyl/skills/dyl-review/SKILL.md"}\n')
        leaf = installed / 'sapsynk-dyl/skills/dyl-review/SKILL.md'
        leaf.write_text('changed locked resource')
        result = self.local('codex', 'changed')
        self.assertEqual(result.returncode, 2)
        self.assertIn('lock', result.stderr)


if __name__ == '__main__':
    unittest.main()
