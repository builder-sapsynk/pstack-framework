import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from bootstrap import bootstrap
from install import install, managed_block, verify_package, installed_package


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
        identity = {'version': '0.1.3', 'source_digest': 'd' * 64,
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
        (package / 'framework.json').write_text(json.dumps({'version': '0.1.3', 'source_digest': 'd' * 64, 'upstream_commit': '23e4138daa01c42d4969f7a5465f82704e64f798'}))
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
        subprocess.run([sys.executable, str(script)], check=True, capture_output=True)
        self.assertTrue((self.root / 'restored').exists())


if __name__ == '__main__':
    unittest.main()
