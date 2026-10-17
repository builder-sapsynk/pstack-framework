from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'plugins-vendored/ponytail'


class PonytailVendorTests(unittest.TestCase):
    def test_no_executable_surface(self):
        suffixes = {p.suffix for p in VENDOR.rglob('*') if p.is_file()}
        self.assertLessEqual(suffixes, {'.md', ''})

    def test_only_ponytail_skill_vendored(self):
        self.assertEqual([p.name for p in (VENDOR / 'skills').iterdir()], ['ponytail'])

    def test_shortcut_convention_removed(self):
        for p in VENDOR.rglob('*.md'):
            text = p.read_text()
            self.assertNotIn('gets a code comment', text, str(p))
            self.assertNotIn('marked with a `shortcut:`', text, str(p))

    def test_symlinks_resolve_to_single_copy(self):
        source = (VENDOR / 'skills/ponytail/SKILL.md').resolve()
        for link in ('.agents/skills/ponytail', '.claude/skills/ponytail'):
            path = ROOT / link
            self.assertTrue(path.is_symlink(), link)
            self.assertEqual((path / 'SKILL.md').resolve(), source, link)
            self.assertIn('name: ponytail', (path / 'SKILL.md').read_text())

    def test_worker_loads_for_all_briefs_with_override(self):
        worker = (ROOT / 'host-agents/pstack-worker.md').read_text()
        self.assertIn('for every brief', worker)
        self.assertIn('no-workaround-comments', worker)
        self.assertNotIn('implementation task (it writes', worker)


if __name__ == '__main__':
    unittest.main()
