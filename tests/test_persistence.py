import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from bootstrap import bootstrap, restore_plugins
from build import VERSION
from install import install, install_claude, claude_package, managed_block, verify_package, installed_package


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_idempotent_pin_identity_and_existing_content(self):
        (self.root / 'AGENTS.md').write_text('Existing rules.\n')
        for _ in range(2):
            receipt = bootstrap(self.root, 'a' * 40, name='Builder', email='builder@sapsynk.com', do_install=False, digest='d' * 64)
        self.assertTrue(receipt['project_lock_written'])
        self.assertEqual(receipt['native_installation'], 'not_requested')
        lock = json.loads((self.root / '.pstack/framework.lock.json').read_text())
        self.assertEqual(lock['version'], VERSION)
        text = (self.root / 'AGENTS.md').read_text()
        self.assertTrue(text.startswith('Existing rules.\n'))
        self.assertEqual(text.count('<!-- sapsynk-pstack:start -->'), 1)
        email = subprocess.check_output(['git', '-C', str(self.root), 'config', '--local', 'user.email'], text=True).strip()
        self.assertEqual(email, 'builder@sapsynk.com')
        with self.assertRaises(ValueError):
            bootstrap(self.root, 'b' * 40, do_install=False, digest='d' * 64)

    def test_failed_install_does_not_write_pin(self):
        with patch('bootstrap.install', side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                bootstrap(self.root, 'a' * 40, digest='d' * 64)
        self.assertFalse((self.root / '.pstack/framework.lock.json').exists())

    def test_cli_contract_and_global_preservation(self):
        cli = self.root / 'fake-codex'
        log = self.root / 'calls'
        cli.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "' + str(log) + '"\n')
        cli.chmod(0o755)
        instructions = self.root / '.codex/AGENTS.md'
        instructions.parent.mkdir()
        instructions.write_text('Other instructions\n')
        install('sapsynk/pstack-framework', 'c' * 40, True, self.root, str(cli))
        self.assertIn('marketplace add sapsynk/pstack-framework --ref ' + 'c' * 40, log.read_text())
        self.assertIn('plugin add sapsynk-pstack@sapsynk-pstack', log.read_text())
        self.assertTrue(instructions.read_text().startswith('Other instructions\n'))

    def test_native_install_receipt_verifies_cached_artifact_and_codex_home(self):
        cache = self.root / 'plugins/cache/sapsynk-pstack/sapsynk-pstack/0.1.3'
        cache.mkdir(parents=True)
        (cache / 'framework.json').write_text(json.dumps({'version': '0.1.3', 'source_digest': 'd' * 64}))
        cli = self.root / 'codex-fixture'
        cli.write_text('#!/bin/sh\nif [ "$2" = "add" ]; then\n  echo "Installed plugin root: ' + str(cache) + '"\nfi\n')
        cli.chmod(0o755)
        with patch.dict(os.environ, {'CODEX_HOME': str(self.root)}):
            receipt = install('fixture', executable=str(cli), global_default=True, expected_digest='d' * 64)
        self.assertTrue(receipt['installed_identity_verified'])
        self.assertEqual(receipt['installed_package'], str(cache))
        self.assertTrue((self.root / 'AGENTS.md').is_file())
        with self.assertRaises(ValueError):
            install('fixture', executable=str(cli), expected_digest='e' * 64)

    def test_cached_discovery_ignores_live_source_metadata(self):
        cache = self.root / 'plugins/cache/sapsynk-pstack/sapsynk-pstack/0.1.3'
        cache.mkdir(parents=True)
        cli = self.root / 'codex'
        metadata = {'installed': [{'pluginId': 'sapsynk-pstack@sapsynk-pstack', 'installed': True,
                                  'enabled': True, 'version': '0.1.3', 'source': {'path': '/incorrect-live-source'}}]}
        cli.write_text('#!/bin/sh\ncat <<\'JSON\'\n' + json.dumps(metadata) + '\nJSON\n')
        cli.chmod(0o755)
        with patch.dict(os.environ, {'CODEX_HOME': str(self.root)}):
            self.assertEqual(installed_package(str(cli)), cache)

    def test_malformed_block_is_rejected(self):
        path = self.root / 'AGENTS.md'
        path.write_text('<!-- sapsynk-pstack:start -->')
        with self.assertRaises(ValueError):
            managed_block(path, 'New')

    def test_active_package_content_must_match_each_project(self):
        bootstrap(self.root, 'a' * 40, do_install=False, digest='d' * 64)
        package = self.root / 'installed-plugin'
        package.mkdir()
        identity = {'version': VERSION, 'source_digest': 'd' * 64,
                    'upstream_commit': '23e4138daa01c42d4969f7a5465f82704e64f798'}
        (package / 'framework.json').write_text(json.dumps(identity))
        verify_package(package, 'd' * 64)
        script = self.root / 'scripts/bootstrap-pstack'
        subprocess.run([sys.executable, str(script), '--check', '--package', str(package)], check=True, capture_output=True)
        # Another project switched the shared host to different framework content.
        identity['source_digest'] = 'e' * 64
        (package / 'framework.json').write_text(json.dumps(identity))
        with self.assertRaises(ValueError):
            verify_package(package, 'd' * 64)
        result = subprocess.run([sys.executable, str(script), '--check', '--package', str(package)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_generated_bootstrap_uses_exact_offline_pin(self):
        source = self.root / 'source'
        source.mkdir()
        subprocess.run(['git', 'init', '-q', str(source)], check=True)
        tools = source / 'tools'
        tools.mkdir()
        for filename in ('build.py', 'validate.py'):
            (tools / filename).write_text('pass\n')
        (tools / 'bootstrap.py').write_text('from pathlib import Path\nPath("' + str(self.root / 'restored') + '").write_text("verified")\n')
        subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.com', 'commit', '-qm', 'fixture'], check=True)
        package = source / 'plugins/sapsynk-pstack'
        package.mkdir(parents=True)
        (package / 'framework.json').write_text(json.dumps({'version': VERSION, 'source_digest': 'd' * 64, 'upstream_commit': '23e4138daa01c42d4969f7a5465f82704e64f798'}))
        subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.com', 'commit', '-qm', 'identity'], check=True)
        revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        bootstrap(self.root, revision, do_install=False, digest='d' * 64)
        script = self.root / 'scripts/bootstrap-pstack'
        subprocess.run([sys.executable, str(script), '--source', str(source)], check=True)
        self.assertTrue((self.root / 'restored').exists())
        (source / 'later').write_text('changed')
        subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.com', 'commit', '-qm', 'later'], check=True)
        result = subprocess.run([sys.executable, str(script), '--source', str(source)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        # Remote mode fetches the pinned older commit even when the remote branch moved.
        lockpath = self.root / '.pstack/framework.lock.json'
        lock = json.loads(lockpath.read_text())
        lock['source'] = str(source)
        lockpath.write_text(json.dumps(lock))
        (self.root / 'restored').unlink()
        home = self.root / 'pstack-home'
        subprocess.run([sys.executable, str(script)], check=True, capture_output=True, env={**os.environ, 'PSTACK_HOME': str(home)})
        self.assertTrue((self.root / 'restored').exists())
        # The pinned checkout persists because Claude Code loads its marketplace directory in place.
        kept = home / 'framework' / revision
        self.assertEqual(subprocess.check_output(['git', '-C', str(kept), 'rev-parse', 'HEAD'], text=True).strip(), revision)

    def claude_fixture(self, state):
        """Fake Claude Code plugin CLI whose marketplace and plugin state live in one JSON file."""
        cli = self.root / 'claude'
        cli.write_text('''#!/usr/bin/env python3
import json, pathlib, sys
path = pathlib.Path(%r)
state = json.loads(path.read_text())
args = [a for a in sys.argv[2:] if a not in ('--json', '--scope', 'user')]
state['calls'].append(' '.join(args))
if args == ['marketplace', 'list']:
    print(json.dumps(state['markets']))
elif args == ['list']:
    print(json.dumps(state['plugins']))
elif args[:2] == ['marketplace', 'add']:
    state['markets'] = [{'name': 'sapsynk', 'source': 'directory', 'path': args[2]}]
elif args[:2] == ['marketplace', 'remove']:
    state['markets'] = []
elif args[0] == 'install':
    folder = state['markets'][0]['path'] + '/plugins/sapsynk-pstack'
    state['plugins'] = [{'id': args[1], 'enabled': True, 'installPath': '/stale-cache', 'readFromFolder': folder}]
elif args[0] == 'uninstall':
    state['plugins'] = []
path.write_text(json.dumps(state))
''' % str(state))
        cli.chmod(0o755)
        return cli

    def pinned_checkout(self, name, digest):
        checkout = self.root / name
        (checkout / '.claude-plugin').mkdir(parents=True)
        (checkout / '.claude-plugin/marketplace.json').write_text('{}')
        package = checkout / 'plugins/sapsynk-pstack'
        package.mkdir(parents=True)
        (package / 'framework.json').write_text(json.dumps({'version': VERSION, 'source_digest': digest}))
        return checkout

    def test_claude_code_install_loads_the_pinned_checkout_and_replaces_another_pin(self):
        state = self.root / 'claude-state.json'
        state.write_text(json.dumps({'markets': [], 'plugins': [], 'calls': []}))
        cli = self.claude_fixture(state)
        first, second = self.pinned_checkout('first', 'd' * 64), self.pinned_checkout('second', 'e' * 64)
        receipt = install_claude(first, 'd' * 64, VERSION, executable=str(cli))
        self.assertTrue(receipt['claude_code_identity_verified'])
        self.assertEqual(receipt['claude_code_package'], str(first / 'plugins/sapsynk-pstack'))
        self.assertEqual(claude_package(str(cli)), first / 'plugins/sapsynk-pstack')
        # Same pin again: nothing is reinstalled.
        before = len(json.loads(state.read_text())['calls'])
        install_claude(first, 'd' * 64, VERSION, executable=str(cli))
        self.assertEqual(json.loads(state.read_text())['calls'][before:], ['marketplace list', 'list', 'list'])
        with self.assertRaises(ValueError):
            install_claude(first, 'e' * 64, VERSION, executable=str(cli))
        install_claude(second, 'e' * 64, VERSION, executable=str(cli))
        calls = json.loads(state.read_text())['calls']
        self.assertIn('uninstall sapsynk-pstack@sapsynk', calls)
        self.assertIn('marketplace remove sapsynk', calls)
        self.assertEqual(claude_package(str(cli)), second / 'plugins/sapsynk-pstack')

    def test_optional_plugins_restore_from_the_locked_commit_and_digests(self):
        import hashlib
        source = self.root / 'optional'
        skill = source / 'plugins/extra/skills/extra/SKILL.md'
        skill.parent.mkdir(parents=True)
        skill.write_text('locked skill')
        (source / '.claude-plugin').mkdir()
        (source / '.claude-plugin/marketplace.json').write_text('{}')
        subprocess.run(['git', 'init', '-q', str(source)], check=True)
        subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.com', 'commit', '-qm', 'pinned'], check=True)
        revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        skill.write_text('later unpinned edit')
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.com', 'commit', '-qam', 'later'], check=True)
        state = self.root / 'claude-state.json'
        state.write_text(json.dumps({'markets': [], 'plugins': [], 'calls': []}))
        cli = self.claude_fixture(state)
        text = cli.read_text().replace("folder = state['markets'][0]['path'] + '/plugins/sapsynk-pstack'",
                                       "folder = state['markets'][0]['path'] + '/plugins/extra'")
        cli.write_text(text.replace("state['plugins'] = [{'id'", "state['plugins'] += [{'id'"))
        lock = {'source': str(source), 'source_revision': revision, 'plugins': {'extra': {
            'claude_plugin_id': 'extra@tools', 'files': {'skills/extra/SKILL.md': hashlib.sha256(b'locked skill').hexdigest()}}}}
        (self.root / '.pstack').mkdir()
        (self.root / '.pstack/plugins.lock.json').write_text(json.dumps(lock))
        with patch.dict(os.environ, {'PATH': str(self.root) + os.pathsep + os.environ['PATH']}):
            receipt = restore_plugins(self.root, ('claude-code',), home=self.root / 'home')
            self.assertEqual(receipt, {'claude_code_optional_plugins': ['extra@tools']})
            self.assertEqual(json.loads(state.read_text())['markets'][0]['path'], str(self.root / 'home/plugins' / revision))
            lock['plugins']['extra']['files']['skills/extra/SKILL.md'] = 'f' * 64
            (self.root / '.pstack/plugins.lock.json').write_text(json.dumps(lock))
            with self.assertRaisesRegex(ValueError, 'differs from the project lock'):
                restore_plugins(self.root, ('claude-code',), home=self.root / 'home')

    def test_project_binding_adds_claude_code_entry_without_losing_settings(self):
        settings = self.root / '.claude/settings.json'
        settings.parent.mkdir()
        settings.write_text(json.dumps({'permissions': {'allow': ['Bash(npm test:*)'], 'deny': ['Read(.env)']}, 'model': 'opus'}))
        (self.root / 'CLAUDE.md').write_text('Local notes.\n')
        for _ in range(2):
            bootstrap(self.root, 'a' * 40, do_install=False, digest='d' * 64)
        saved = json.loads(settings.read_text())
        self.assertEqual(saved['model'], 'opus')
        self.assertEqual(saved['permissions']['deny'], ['Read(.env)'])
        self.assertEqual(saved['permissions']['allow'], ['Bash(npm test:*)', 'Bash(scripts/pstack-run:*)', 'Bash(scripts/bootstrap-pstack:*)'])
        self.assertTrue(saved['enabledPlugins']['sapsynk-pstack@sapsynk'])
        self.assertEqual(len(saved['hooks']['SessionStart']), 1)
        text = (self.root / 'CLAUDE.md').read_text()
        self.assertTrue(text.startswith('Local notes.\n'))
        self.assertEqual(text.count('@AGENTS.md'), 1)
        runner = self.root / 'scripts/pstack-run'
        self.assertTrue(os.access(runner, os.X_OK))
        self.assertEqual(json.loads((self.root / '.pstack/framework.lock.json').read_text())['claude_plugin'], 'sapsynk-pstack@sapsynk')
        # The project runner resolves the checked package and hands over to its runtime.
        package = self.root / 'installed-plugin'
        (package / 'runtime').mkdir(parents=True)
        (package / 'framework.json').write_text(json.dumps({'version': VERSION, 'source_digest': 'd' * 64,
                                                            'upstream_commit': '23e4138daa01c42d4969f7a5465f82704e64f798'}))
        script = self.root / 'scripts/bootstrap-pstack'
        printed = subprocess.run([sys.executable, str(script), '--print-package', '--package', str(package)], check=True, capture_output=True, text=True)
        self.assertEqual(printed.stdout.strip(), str(package))

    def test_check_follows_the_running_host(self):
        bootstrap(self.root, 'a' * 40, do_install=False, digest='d' * 64)
        state = self.root / 'claude-state.json'
        checkout = self.pinned_checkout('pinned', 'd' * 64)
        identity = checkout / 'plugins/sapsynk-pstack/framework.json'
        identity.write_text(json.dumps({'version': VERSION, 'source_digest': 'd' * 64, 'upstream_commit': '23e4138daa01c42d4969f7a5465f82704e64f798'}))
        state.write_text(json.dumps({'markets': [], 'calls': [], 'plugins': [
            {'id': 'sapsynk-pstack@sapsynk', 'enabled': True, 'installPath': '/stale-cache', 'readFromFolder': str(identity.parent)}]}))
        self.claude_fixture(state)
        env = {**os.environ, 'PATH': str(self.root) + os.pathsep + os.environ['PATH'], 'CLAUDECODE': '1'}
        env.pop('PSTACK_HOST', None)
        script = self.root / 'scripts/bootstrap-pstack'
        result = subprocess.run([sys.executable, str(script), '--check'], capture_output=True, text=True, env=env)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, 'Installed project framework content pin verified (claude-code)'))
        identity.write_text(json.dumps({'version': VERSION, 'source_digest': 'e' * 64}))
        self.assertNotEqual(subprocess.run([sys.executable, str(script), '--check'], capture_output=True, env=env).returncode, 0)

    def test_explicit_version_is_exact_and_legacy_callers_skip_it(self):
        package = self.root / 'installed-plugin'
        package.mkdir()
        upstream = '23e4138daa01c42d4969f7a5465f82704e64f798'
        identity = {'version': VERSION, 'source_digest': 'd' * 64, 'upstream_commit': upstream}
        (package / 'framework.json').write_text(json.dumps(identity))
        verify_package(package, 'd' * 64)
        verify_package(package, 'd' * 64, VERSION, upstream)
        with self.assertRaises(ValueError):
            verify_package(package, 'd' * 64, '0.1.3', upstream)
        cli = self.root / 'codex-fixture'
        cli.write_text('#!/bin/sh\nif [ "$2" = "add" ]; then\n  echo "Installed plugin root: ' + str(package) + '"\nfi\n')
        cli.chmod(0o755)
        receipt = install('fixture', executable=str(cli), expected_digest='d' * 64)
        self.assertTrue(receipt['installed_identity_verified'])
        receipt = install('fixture', executable=str(cli), expected_digest='d' * 64, expected_version=VERSION)
        self.assertTrue(receipt['installed_identity_verified'])
        with self.assertRaises(ValueError):
            install('fixture', executable=str(cli), expected_digest='d' * 64, expected_version='0.1.3')


if __name__ == '__main__':
    unittest.main()
