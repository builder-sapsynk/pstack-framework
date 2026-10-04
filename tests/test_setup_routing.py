import copy
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from setup_routing import BUDGETS, candidate_config, confirmation_table, create_plan, validate_plan


def discovery():
    return {'schema_version': 1, 'native_host': {'source': 'unit fixture native schema', 'models': [
        {'provider': 'codex', 'transport': 'native', 'model': 'gpt-6.1-sol',
         'efforts': ['low', 'medium', 'high'], 'available': True,
         'capabilities': ['respond', 'read_files', 'edit_files', 'verify']},
        {'provider': 'codex', 'transport': 'native', 'model': 'gpt-6-astra',
         'efforts': ['low', 'medium', 'high'], 'available': True,
         'capabilities': ['respond', 'read_files', 'edit_files', 'verify']}]},
        'external': {'source': 'unit fixture provider catalog', 'models': [
        {'provider': 'grok', 'transport': 'grok-build', 'model': 'grok-4.7',
         'efforts': ['low', 'medium', 'high', 'xhigh'], 'available': True,
         'confinement': 'response-only', 'capabilities': ['respond']}]}}


class SetupRoutingTests(unittest.TestCase):
    def setUp(self):
        self.catalog = discovery()
        self.registry = json.loads((ROOT / 'config/routing-layers.json').read_text())
        self.current = {'schema_version': 1, 'roles': {}, 'providers': {'private-setting': 'keep'},
                        'execution_policy': {'token_conservative': True}, 'other': {'preserve': [1, 2]}}
        for role, specs in self.registry['roles'].items():
            specs_list = specs if isinstance(specs, list) else [specs]
            entries = [copy.deepcopy(spec if 'alias' in spec else self.registry['layers'][spec.get('incumbent_layer', spec['layer'])]) for spec in specs_list]
            self.current['roles'][role] = entries if isinstance(specs, list) else entries[0]

    def test_layered_table_preserves_all_roles_preferences_and_visible_file_lane(self):
        plan = create_plan(self.catalog, self.current)
        self.assertEqual(len(plan['roles']), 17)
        routine = plan['roles']['feature, refactoring']
        self.assertEqual(routine['requested'], {'provider': 'grok', 'transport': 'grok-build', 'model': 'grok-4.7', 'effort': 'medium'})
        self.assertEqual(routine['effective'], {'provider': 'codex', 'transport': 'native', 'model': 'gpt-6.1-sol', 'effort': 'high'})
        self.assertEqual(routine['missing_capabilities'], ['edit_files', 'read_files', 'verify'])
        self.assertIn('needs-file-proof', routine['reason'])
        self.assertTrue(routine['effort_override'])
        self.assertEqual(plan['budget'], 'medium — high reasoning')
        self.assertEqual(plan['roles']['how explorer']['requested']['effort'], 'low')
        self.assertEqual(plan['roles']['perf-issue']['requested']['effort'], 'high')
        self.assertEqual(plan['roles']['judgment and prose']['effective']['effort'], 'medium')
        self.assertEqual(plan['roles']['how explainer']['effective']['effort'], 'low')
        for role, count in [('arena runners', 2), ('arena cross-judge pool', 1), ('architect runners', 2), ('interrogate reviewers', 2)]:
            self.assertEqual(len(plan['roles'][role]), count)
        table = confirmation_table(plan)
        for role in self.registry['roles']:
            self.assertIn(role, table)
        self.assertIn('grok/grok-build/grok-4.7/medium', table)
        self.assertIn('codex/native/gpt-6.1-sol/high', table)
        self.assertIn('candidate export does not apply configuration', table)
        self.assertEqual(validate_plan(plan, self.catalog, self.current), plan)

    def test_candidate_has_direct_effective_roles_and_preserves_unrelated_settings(self):
        before = copy.deepcopy(self.current)
        self.current['roles']['retired role'] = {'alias': 'auto'}
        plan = create_plan(self.catalog, self.current)
        candidate = candidate_config(plan, self.current)
        self.assertEqual(plan['dropped_roles'], ['retired role'])
        self.assertEqual(candidate['providers'], before['providers'])
        self.assertEqual(candidate['execution_policy'], before['execution_policy'])
        self.assertEqual(candidate['other'], before['other'])
        self.assertEqual(candidate['roles']['feature, refactoring']['model'], 'gpt-6.1-sol')
        self.assertEqual(candidate['routing_preferences']['roles']['feature, refactoring']['requested']['model'], 'grok-4.7')
        self.assertIn('retired role', self.current['roles'])
        self.assertNotIn('retired role', candidate['roles'])

    def test_aliases_user_family_effort_and_panel_entries_are_preserved(self):
        self.current['roles']['feature, refactoring'] = {'alias': 'auto'}
        self.current['roles']['bug-fix'] = {'provider': 'codex', 'transport': 'native', 'model': 'gpt-6-astra', 'effort': 'low'}
        self.current['roles']['arena runners'][0] = {'alias': 'inherit-parent'}
        plan = create_plan(self.catalog, self.current)
        self.assertEqual(plan['roles']['feature, refactoring'], {'alias': 'auto'})
        self.assertEqual(plan['roles']['bug-fix']['requested']['effort'], 'low')
        self.assertEqual(plan['roles']['bug-fix']['layer'], 'user-choice')
        self.assertEqual(plan['roles']['arena runners'][0], {'alias': 'inherit-parent'})
        self.assertEqual(plan['roles']['why investigators'], {'alias': 'inherit-parent'})
        self.assertEqual(len(candidate_config(plan, self.current)['roles']['arena runners']), 2)

    def test_every_astra_slot_has_task_sensitive_sol_high_alternative(self):
        plan = create_plan(self.catalog, self.current)
        expected = {'judgment and prose', 'hardest tasks', 'how explainer',
                    'reflect judgment, divergent, synthesizer', 'arena runners',
                    'arena cross-judge pool', 'architect runners', 'interrogate reviewers'}
        found = set()
        for role, choices in plan['roles'].items():
            choices = choices if isinstance(choices, list) else [choices]
            for choice in choices:
                if choice.get('requested', {}).get('model') != 'gpt-6-astra':
                    continue
                found.add(role)
                self.assertEqual(len(choice['alternatives']), 1)
                alternative = choice['alternatives'][0]
                self.assertEqual(alternative['binding'], {'provider': 'codex', 'transport': 'native',
                                                          'model': 'gpt-6.1-sol', 'effort': 'high'})
                self.assertTrue(alternative['available'])
                self.assertEqual(alternative['missing_capabilities'], [])
                self.assertEqual(alternative['selection_policy']['bounded_routine_judgment_prose'], 'prefer-sol-high')
                self.assertEqual(alternative['selection_policy']['difficult_or_ambiguous_tasks'], 'astra-when-task-evaluation-warrants-cost')
                self.assertEqual(alternative['selection_policy']['provider_failure'], 'stop-no-silent-fallback')
                self.assertEqual(choice['effective']['model'], 'gpt-6-astra')
        self.assertEqual(found, expected)
        candidate = candidate_config(plan, self.current)
        self.assertEqual(candidate['routing_preferences']['selection_policy'], plan['selection_policy'])
        self.assertEqual(candidate['roles']['how explainer']['effort'], 'low')
        for role, count in [('arena runners', 2), ('arena cross-judge pool', 1), ('architect runners', 2), ('interrogate reviewers', 2)]:
            self.assertEqual(len(candidate['roles'][role]), count)
        self.assertIn('Task-sensitive alternative', confirmation_table(plan))
        self.assertIn('prefer Sol/high for bounded routine judgment/prose', confirmation_table(plan))

    def test_alternative_never_advertises_unknown_effort_or_unmet_capabilities(self):
        for kind in ('effort', 'capability', 'available'):
            catalog = discovery()
            sol = catalog['native_host']['models'][0]
            if kind == 'effort':
                sol['efforts'] = ['low', 'medium']
            elif kind == 'capability':
                sol['capabilities'] = ['respond']
            else:
                sol['available'] = False
            plan = create_plan(catalog, self.current)
            alternative = plan['roles']['hardest tasks']['alternatives'][0]
            self.assertFalse(alternative['available'])
            self.assertEqual(alternative['missing_capabilities'], ['edit_files', 'read_files', 'verify'])
            self.assertEqual(plan['roles']['hardest tasks']['effective']['model'], 'gpt-6-astra')
            self.assertIn('UNAVAILABLE', confirmation_table(plan))

    def test_optional_high_xhigh_escalations_require_evaluation_and_real_lane(self):
        plan = create_plan(self.catalog, self.current)
        self.assertEqual(plan['selection_policy']['effort_escalation']['optional_efforts'], ['high', 'xhigh'])
        self.assertFalse(plan['selection_policy']['effort_escalation']['default_change'])
        judgment = plan['roles']['judgment and prose']['optional_escalations']
        self.assertEqual([choice['effort'] for choice in judgment], ['high', 'xhigh'])
        self.assertTrue(judgment[0]['available'])
        self.assertFalse(judgment[1]['available'])
        self.assertIn('task_evaluation_justifies_effort', judgment[0]['requires'])
        routine = plan['roles']['bug-fix']['optional_escalations']
        self.assertTrue(routine[1]['effort_discovered'])
        self.assertFalse(routine[1]['capabilities_satisfied'])
        self.assertFalse(routine[1]['available'])
        self.catalog['native_host']['models'][1]['efforts'].append('xhigh')
        plan = create_plan(self.catalog, self.current)
        self.assertTrue(plan['roles']['judgment and prose']['optional_escalations'][1]['available'])
        self.assertEqual(plan['roles']['judgment and prose']['requested']['effort'], 'medium')
        plan['selection_policy']['effort_escalation']['default_change'] = True
        with self.assertRaisesRegex(ValueError, 'differs'):
            validate_plan(plan, self.catalog, self.current)

    def test_rerun_preserves_user_preference_behind_effective_file_lane(self):
        self.current['roles']['bug-fix'] = {'provider': 'grok', 'transport': 'grok-build', 'model': 'grok-4.7', 'effort': 'low'}
        plan = create_plan(self.catalog, self.current)
        candidate = candidate_config(plan, self.current)
        rerun = create_plan(self.catalog, candidate)
        self.assertEqual(rerun['roles']['bug-fix']['requested']['effort'], 'low')
        self.assertEqual(rerun['roles']['bug-fix']['layer'], 'user-choice')

    def test_setup_preamble_preserves_upstream_body_and_other_skills(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        from build import adapted_skill, sha
        source = (ROOT / 'upstream/pstack/skills/setup-pstack/SKILL.md').read_bytes()
        frontmatter = re.match(rb'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)', source, re.S)
        body = source[frontmatter.end():]
        generated, body_hash = adapted_skill(source, 'skills/setup-pstack/SKILL.md')
        self.assertTrue(generated.endswith(body))
        self.assertEqual(body_hash, sha(body))
        self.assertIn(b'../../adapters/setup-pstack.md', generated)
        other = (ROOT / 'upstream/pstack/skills/how/SKILL.md').read_bytes()
        self.assertNotIn(b'Portable setup override', adapted_skill(other, 'skills/how/SKILL.md')[0])

    def test_exact_budget_labels_and_detected_effort_floor(self):
        for label, target in BUDGETS.items():
            plan = create_plan(self.catalog, self.current, budget=label)
            expected = target or 'medium'
            self.assertEqual(plan['roles']['feature, refactoring']['requested']['effort'], expected)
            self.assertEqual(plan['roles']['why synthesizer'], {'alias': 'inherit-parent'})
        large = create_plan(self.catalog, self.current, budget='large — xhigh reasoning')
        self.assertEqual(large['roles']['arena runners'][1]['requested']['effort'], 'high')
        self.assertFalse(large['roles']['arena runners'][1]['effort_override'])
        with self.assertRaisesRegex(ValueError, 'exact upstream'):
            create_plan(self.catalog, self.current, budget='medium')
        self.catalog['native_host']['models'][1]['efforts'] = ['high']
        with self.assertRaisesRegex(ValueError, 'at or below'):
            create_plan(self.catalog, self.current, budget='small — medium reasoning')

    def test_invalid_model_effort_alias_and_panel_are_rejected(self):
        for field, value, message in [('model', 'made-up-model', 'not discovered'), ('effort', 'ultra', 'Unsupported effort')]:
            current = copy.deepcopy(self.current)
            current['roles']['bug-fix'][field] = value
            with self.assertRaisesRegex(ValueError, message):
                create_plan(self.catalog, current)
        self.catalog['external']['models'][0]['efforts'] = ['high']
        with self.assertRaisesRegex(ValueError, 'Effort not discovered'):
            create_plan(self.catalog, self.current)
        self.current['roles']['why investigators'] = {'alias': 'made-up'}
        with self.assertRaisesRegex(ValueError, 'alias'):
            create_plan(discovery(), self.current)
        self.current['roles']['why investigators'] = {'alias': 'auto'}
        self.current['roles']['arena runners'].append({'alias': 'auto'})
        with self.assertRaisesRegex(ValueError, 'panel count'):
            create_plan(discovery(), self.current)

    def test_no_unverified_native_or_external_file_capabilities(self):
        grok = self.catalog['external']['models'][0]
        grok['capabilities'].append('read_files')
        with self.assertRaisesRegex(ValueError, 'Response-only'):
            create_plan(self.catalog, self.current)
        grok['confinement'] = 'verified-task-tool-lane'
        with self.assertRaisesRegex(ValueError, 'file_tool_proof'):
            create_plan(self.catalog, self.current)
        grok['file_tool_proof'] = 'unit fixture receipt; not actual proof'
        plan = create_plan(self.catalog, self.current)
        self.assertEqual(plan['roles']['how explorer']['effective']['model'], 'grok-4.7')
        self.assertEqual(plan['roles']['bug-fix']['effective']['model'], 'gpt-6.1-sol')
        self.catalog['native_host']['models'][0]['available'] = False
        plan = create_plan(self.catalog, self.current)
        self.assertIsNone(plan['roles']['bug-fix']['effective'])
        with self.assertRaisesRegex(ValueError, 'Unresolved'):
            candidate_config(plan, self.current)

    def test_native_schema_and_external_catalog_cannot_be_confused(self):
        self.catalog['external']['models'][0]['transport'] = 'native'
        with self.assertRaisesRegex(ValueError, 'stay separate'):
            create_plan(self.catalog, self.current)
        self.catalog = discovery()
        self.catalog['native_host']['source'] = ''
        with self.assertRaisesRegex(ValueError, 'discovery source'):
            create_plan(self.catalog, self.current)

    def test_stale_or_tampered_plan_and_implicit_substitution_are_rejected(self):
        plan = create_plan(self.catalog, self.current)
        tampered = copy.deepcopy(plan)
        tampered['roles']['bug-fix']['effective']['model'] = 'gpt-6-astra'
        with self.assertRaisesRegex(ValueError, 'differs'):
            validate_plan(tampered, self.catalog, self.current)
        changed_current = copy.deepcopy(self.current)
        changed_current['other'] = {'preserve': [3]}
        with self.assertRaisesRegex(ValueError, 'differs'):
            validate_plan(plan, self.catalog, changed_current)
        self.catalog['external']['models'][0]['source_revision'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'differs'):
            validate_plan(plan, self.catalog, self.current)

    def test_cli_dry_run_writes_nothing_and_export_never_applies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = root / 'current.json'
            catalog = root / 'catalog.json'
            current.write_text(json.dumps(self.current))
            catalog.write_text(json.dumps(self.catalog))
            before = {path.name: path.read_bytes() for path in root.iterdir()}
            command = [sys.executable, str(ROOT / 'runtime/setup_routing.py'), 'plan', '--catalog', str(catalog), '--current', str(current)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('interrogate reviewers [2]', result.stdout)
            self.assertEqual(before, {path.name: path.read_bytes() for path in root.iterdir()})
            candidate = root / 'candidate.json'
            plan = root / 'plan.json'
            result = subprocess.run(command + ['--output', str(candidate), '--plan-output', str(plan)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(current.read_bytes(), before['current.json'])
            validate = command.copy()
            validate[2] = 'validate'
            result = subprocess.run(validate + ['--plan', str(plan)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run(command + ['--output', str(current)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('cannot overwrite', result.stderr)
            self.assertEqual(current.read_bytes(), before['current.json'])
            hardlink = root / 'same-input.json'
            os.link(current, hardlink)
            result = subprocess.run(command + ['--output', str(hardlink)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(current.read_bytes(), before['current.json'])


if __name__ == '__main__':
    unittest.main()
