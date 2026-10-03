import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from build import ROOT, build, sha, source_digest
from validate import validate

class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for directory in ('upstream', 'adapters', 'runtime', 'config', 'extra-skills', 'tools'):
            shutil.copytree(ROOT / directory, self.root / directory, ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('upstream.lock.json', 'NOTICE.md', 'LICENSE-cursor-team-kit', 'LICENSE'):
            shutil.copy2(ROOT / name, self.root)
    def tearDown(self):
        self.temp.cleanup()
    def test_complete_and_reproducible(self):
        plugin, archive = build(self.root)
        report = validate(self.root)
        self.assertEqual(report['original_files'], 160)
        self.assertEqual(report['upstream_skills'], 49)
        self.assertEqual(report['playbooks'], 23)
        digest = sha(archive.read_bytes())
        build(self.root)
        self.assertEqual(digest, sha(archive.read_bytes()))
    def test_framework_identity_and_attribution(self):
        plugin, _ = build(self.root)
        identity = json.loads((plugin / 'framework.json').read_text())
        self.assertEqual(identity['source_digest'], source_digest(self.root))
        for name in ('NOTICE.md', 'LICENSE-cursor-team-kit'):
            self.assertEqual((plugin / name).read_bytes(), (self.root / name).read_bytes())
        (self.root / 'config/new.json').write_text('{}')
        self.assertNotEqual(identity['source_digest'], source_digest(self.root))
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            validate(self.root)
    def test_generated_outputs_do_not_change_identity(self):
        before = source_digest(self.root)
        build(self.root)
        self.assertEqual(before, source_digest(self.root))
    def test_portable_manifest(self):
        plugin, _ = build(self.root)
        portable = json.loads((plugin / 'plugin.json').read_text())
        compat = json.loads((plugin / '.codex-plugin/plugin.json').read_text())
        self.assertEqual(portable['name'], compat['name'])
        self.assertEqual(portable['version'], compat['version'])
        presentation = portable['extensions']['com.openai']['interface']
        self.assertEqual(presentation, compat['interface'])
        self.assertLessEqual(len(presentation['shortDescription']), 30)
        self.assertFalse(set(portable) & {'skills', 'mcpServers', 'apps', 'interface'})
        portable['skills'] = './skills/'
        (plugin / 'plugin.json').write_text(json.dumps(portable))
        with self.assertRaisesRegex(ValueError, 'Unsupported portable'):
            validate(self.root)
    def test_source_tamper_rejected(self):
        (self.root / 'upstream/pstack/README.md').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            build(self.root)
    def test_extra_source_rejected(self):
        (self.root / 'upstream/pstack/new.txt').write_text('extra')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            build(self.root)
    def test_missing_adapter_rejected(self):
        (self.root / 'adapters/CONTRACT.md').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing required'):
            build(self.root)
    def test_missing_resource_rejected(self):
        plugin, _ = build(self.root)
        (plugin / 'adapters/CONTRACT.md').unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            validate(self.root)
    def test_generated_change_rejected(self):
        plugin, _ = build(self.root)
        (plugin / 'skills/poteto-mode/SKILL.md').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'parity'):
            validate(self.root)

if __name__ == '__main__':
    unittest.main()
