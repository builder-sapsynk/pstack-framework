import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
import dispatch_policy
import panel_divergence

# (facts, expected route, expected rule)
CASES = (
    ({'read_only': True}, 'inline', 'trivial'),
    ({'steps': 3, 'files': 2, 'lines': 30, 'tokens': 15000, 'minutes': 5}, 'inline', 'trivial'),
    ({'lines': 31, 'files': 1}, 'worker', 'substantial'),
    ({'files': 3}, 'worker', 'substantial'),
    ({'steps': 4}, 'worker', 'substantial'),
    ({'minutes': 6}, 'worker', 'substantial'),
    ({'read_only': True, 'tokens': 40000}, 'native-subagent', 'bulk-read'),
    ({'read_only': True, 'tokens': 60001}, 'worker', 'substantial'),
    ({'tokens': 40000}, 'worker', 'substantial'),
    ({'read_only': True, 'tokens': 40000, 'steps': 4}, 'worker', 'substantial'),
    ({'units': 2}, 'worker', 'parallel'),
    ({'judgment': True, 'read_only': True, 'subject_lines': 30}, 'worker', 'independent-judgment'),
    ({'panel': True, 'subject_lines': 30}, 'panel', 'required-panel'),
    ({'risky': True, 'lines': 2, 'files': 1}, 'worker', 'risky'),
    ({'risky': True, 'read_only': True}, 'inline', 'trivial'),
)


class DispatchPolicyTests(unittest.TestCase):
    def test_routes(self):
        for facts, route, rule in CASES:
            with self.subTest(facts=facts):
                decision = dispatch_policy.decide(facts)
                self.assertEqual((decision['route'], decision['rule']), (route, rule))

    def test_small_subject_caps_reviewers_and_inline_work_keeps_obligations(self):
        small = dispatch_policy.decide({'judgment': True, 'subject_lines': 30})
        self.assertEqual(small['caps'], {'effort': 'low', 'timeout_s': 300})
        self.assertNotIn('caps', dispatch_policy.decide({'judgment': True, 'subject_lines': 151}))
        self.assertNotIn('caps', dispatch_policy.decide({'judgment': True, 'subject_lines': 30, 'risky': True}))
        inline = dispatch_policy.decide({'lines': 3, 'files': 1})
        self.assertEqual(len(inline['obligations']), 4)
        self.assertIn('never on main', inline['obligations'][0])
        self.assertNotIn('obligations', dispatch_policy.decide({'units': 3}))

    def test_override_needs_a_reason_and_is_recorded_as_one(self):
        with self.assertRaises(ValueError):
            dispatch_policy.decide({}, override='worker')
        decision = dispatch_policy.decide({}, override='worker', reason='owner asked for a second opinion')
        self.assertEqual((decision['route'], decision['rule'], decision['reason']),
                         ('worker', 'override', 'owner asked for a second opinion'))

    def test_cli_logs_the_decision_and_honors_project_thresholds(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            subprocess.run(['git', 'init', '-q', str(project)], check=True)
            runner = [sys.executable, str(ROOT / 'runtime/pstack_run.py'), '--project', str(project), 'decide']
            first = subprocess.run(runner + ['count lines', '--read-only'], capture_output=True, text=True)
            self.assertEqual(json.loads(first.stdout)['route'], 'inline')
            (project / '.pstack/config.json').write_text(json.dumps({'dispatch_policy': {'inline_max_lines': 5}}))
            second = subprocess.run(runner + ['edit', '--lines', '6', '--files', '1'], capture_output=True, text=True)
            self.assertEqual(json.loads(second.stdout)['route'], 'worker')
            logged = [json.loads(line) for line in (project / '.pstack/state/dispatch.jsonl').read_text().splitlines()]
            self.assertEqual([(entry['task'], entry['route']) for entry in logged], [('count lines', 'inline'), ('edit', 'worker')])
            (project / '.pstack/config.json').write_text(json.dumps({'dispatch_policy': {'typo': 1}}))
            self.assertEqual(subprocess.run(runner + ['x'], capture_output=True, text=True).returncode, 2)

    def test_documented_thresholds_match_the_code(self):
        text = (ROOT / 'adapters/dispatch-policy.md').read_text()
        documented = dict(re.findall(r'^\| `(\w+)` \| `?([\w.]+)`? \|', text, re.MULTILINE))
        self.assertEqual(documented, {key: str(value) for key, value in dispatch_policy.THRESHOLDS.items()})
        for adapter in ('claude-code.md', 'codex.md', 'CONTRACT.md'):
            self.assertIn('dispatch-policy.md', (ROOT / 'adapters' / adapter).read_text(), adapter)


def candidate(task, lens, shape, body='', state='succeeded', session=None, brief_extra=''):
    brief = 'Sketch one design.\n' + (f'Lens: {lens}\n' if lens else '') + brief_extra
    return {'task': task, 'state': state, 'session': session or task, 'brief': brief,
            'message': (f'Shape: {shape}\n' if shape else '') + body}


class PanelDivergenceTests(unittest.TestCase):
    def test_distinct_lenses_and_shapes_pass(self):
        verdict = panel_divergence.check([
            candidate('a', panel_divergence.LENSES['architect'][0], 'PushPlan record', 'parse argv into refspecs and flags'),
            candidate('b', panel_divergence.LENSES['architect'][1], 'server-side hook', 'reject protected updates in the remote pre-receive step')])
        self.assertTrue(verdict['distinct'], verdict['problems'])

    def test_identical_briefs_without_a_lens_are_not_two_candidates(self):
        verdict = panel_divergence.check([candidate('a', None, 'PushPlan {cwd, flags}'), candidate('b', None, 'PushIntent {cwd, argv}')])
        self.assertFalse(verdict['distinct'])
        self.assertEqual(sum('no `Lens:` line' in problem for problem in verdict['problems']), 2)

    def test_each_violation_is_reported(self):
        for candidates, expected in (
            ([candidate('a', 'one', 'X'), candidate('b', 'one', 'Y')], 'same lens'),
            ([candidate('a', 'one', 'Push Plan'), candidate('b', 'two', 'push-plan')], 'same declared shape'),
            ([candidate('a', 'one', 'X', 'alpha beta gamma delta'), candidate('b', 'two', 'Y', 'alpha beta gamma delta')], 'answers overlap'),
            ([candidate('a', 'one', 'X'), candidate('b', 'two', 'Y', state='failed')], 'state failed is not a candidate'),
            ([candidate('a', 'one', 'X', session='s'), candidate('b', 'two', 'Y', session='s')], 'same session'),
            ([candidate('a', 'one', 'X'), candidate('b', 'two', None)], 'no `Shape:` line'),
            ([candidate('arch-a', 'one', 'X'), candidate('arch-b', 'two', 'Y', brief_extra='See .pstack/runs/arch-a/last-message.txt\n')], 'must not see each other'),
            ([candidate('a', 'one', 'X', 'The decision moves into a pre-receive hook on the remote.'),
              candidate('b', 'two', 'Y', brief_extra='Context: The decision moves into a pre-receive hook on the remote.\n')], 'quotes the answer'),
            ([candidate('a', 'one', 'X')], 'at least two candidates'),
        ):
            with self.subTest(expected=expected):
                verdict = panel_divergence.check(candidates)
                self.assertFalse(verdict['distinct'])
                self.assertTrue(any(expected in problem for problem in verdict['problems']), verdict['problems'])

    def test_cli_reads_run_directories_and_exits_nonzero_on_convergence(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            subprocess.run(['git', 'init', '-q', str(project)], check=True)
            for task, lens, shape in (('arch-a', 'one', 'record'), ('arch-b', 'two', 'hook'), ('arch-c', None, 'record')):
                run = project / '.pstack/runs' / task
                run.mkdir(parents=True)
                entry = candidate(task, lens, shape)
                (run / 'brief.md').write_text(entry['brief'])
                (run / 'last-message.txt').write_text(entry['message'])
                (run / 'status.json').write_text(json.dumps({'state': 'succeeded', 'session_id': task}))
            runner = [sys.executable, str(ROOT / 'runtime/pstack_run.py'), '--project', str(project), 'divergence']
            self.assertEqual(subprocess.run(runner + ['arch-a', 'arch-b'], capture_output=True).returncode, 0)
            self.assertEqual(subprocess.run(runner + ['arch-a', 'arch-c'], capture_output=True).returncode, 1)


if __name__ == '__main__':
    unittest.main()
