#!/usr/bin/env python3
"""Materialize a reviewable setup plan from caller-discovered model capabilities."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

REGISTRY = Path(__file__).resolve().parents[1] / 'config/routing-layers.json'
BUDGETS = {'unlimited — keep max': None, 'large — xhigh reasoning': 'xhigh',
           'medium — high reasoning': 'high', 'small — medium reasoning': 'medium'}
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
FIELDS = ('provider', 'transport', 'model', 'effort')
FILE_CAPABILITIES = {'read_files', 'edit_files', 'verify'}
ROLES = ('feature, refactoring', 'bug-fix', 'perf-issue', 'hillclimb', 'judgment and prose',
         'hardest tasks', 'how explorer', 'how explainer', 'why investigators', 'why synthesizer',
         'reflect tooling', 'reflect judgment, divergent, synthesizer', 'arena runners',
         'arena cross-judge pool', 'swarm workers', 'architect runners', 'interrogate reviewers')
PANELS = {'arena runners': 2, 'arena cross-judge pool': 1, 'architect runners': 2,
          'interrogate reviewers': 2}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def binding(value):
    if not isinstance(value, dict) or set(value) != set(FIELDS):
        raise ValueError('Binding requires provider, transport, model and effort only')
    if any(not isinstance(value[key], str) or not value[key].strip() for key in FIELDS):
        raise ValueError('Binding fields must be nonempty strings')
    if value['effort'] not in EFFORTS:
        raise ValueError('Unsupported effort: ' + value['effort'])
    return dict(value)


def alias(value):
    if isinstance(value, dict) and set(value) == {'alias'}:
        if value['alias'] not in ('auto', 'inherit-parent'):
            raise ValueError('Unsupported alias')
        return dict(value)
    return None


def catalog_entries(catalog):
    if not isinstance(catalog, dict) or catalog.get('schema_version') != 1:
        raise ValueError('Catalog requires schema_version 1')
    entries = {}
    for section in ('native_host', 'external'):
        group = catalog.get(section)
        if not isinstance(group, dict) or not isinstance(group.get('source'), str) or not group['source'].strip():
            raise ValueError('Catalog requires discovery source for ' + section)
        if not isinstance(group.get('models'), list):
            raise ValueError('Catalog models must be a list')
        for entry in group['models']:
            if not isinstance(entry, dict):
                raise ValueError('Catalog entry must be an object')
            key = tuple(entry.get(name) for name in FIELDS[:3])
            if any(not isinstance(item, str) or not item.strip() for item in key):
                raise ValueError('Catalog entry requires provider/transport/model')
            if (section == 'native_host') != (entry['transport'] == 'native'):
                raise ValueError('Native host schemas and external catalogs must stay separate')
            efforts = entry.get('efforts')
            capabilities = entry.get('capabilities')
            if not isinstance(efforts, list) or not efforts or any(item not in EFFORTS for item in efforts):
                raise ValueError('Invalid catalog efforts')
            if not isinstance(capabilities, list) or any(item not in FILE_CAPABILITIES | {'respond'} for item in capabilities):
                raise ValueError('Invalid catalog capabilities')
            if not isinstance(entry.get('available'), bool):
                raise ValueError('Catalog entry requires observed available boolean')
            if key in entries:
                raise ValueError('Duplicate catalog model tuple')
            if section == 'external' and entry.get('confinement') == 'response-only' and FILE_CAPABILITIES.intersection(capabilities):
                raise ValueError('Response-only external lane cannot read/edit/verify files')
            if section == 'external' and FILE_CAPABILITIES.intersection(capabilities) and (not isinstance(entry.get('file_tool_proof'), str) or not entry['file_tool_proof'].strip()):
                raise ValueError('External file capabilities require task-relevant file_tool_proof')
            entries[key] = dict(entry, discovery_source=group['source'])
    return entries


def discovered(value, entries, transform=None):
    value = binding(value)
    entry = entries.get(tuple(value[key] for key in FIELDS[:3]))
    if entry is None or not entry['available']:
        raise ValueError('Model tuple not discovered available: ' + '/'.join(value[key] for key in FIELDS[:3]))
    if transform is not None:
        eligible = [effort for effort in entry['efforts'] if EFFORTS.index(effort) <= EFFORTS.index(transform)]
        if not eligible:
            raise ValueError('No discovered effort at or below budget target')
        value['effort'] = max(eligible, key=EFFORTS.index)
    if value['effort'] not in entry['efforts']:
        raise ValueError('Effort not discovered for model: ' + value['model'] + '/' + value['effort'])
    return value, entry


def role_shape(roles, label):
    if not isinstance(roles, dict) or set(roles) != set(ROLES):
        raise ValueError(label + ' must contain exactly the 17 upstream roles')
    for role, value in roles.items():
        if role in PANELS:
            if not isinstance(value, list) or len(value) != PANELS[role]:
                raise ValueError(role + ' panel count must be ' + str(PANELS[role]))
        elif isinstance(value, list):
            raise ValueError(role + ' is not a panel')


def create_plan(catalog, current, registry=None, budget=None):
    registry = json.loads(REGISTRY.read_text()) if registry is None else registry
    if not isinstance(registry, dict) or registry.get('schema_version') != 1 or not isinstance(registry.get('layers'), dict):
        raise ValueError('Routing registry requires schema_version 1 and layers')
    role_shape(registry['roles'], 'Registry roles')
    policy = registry.get('selection_policy')
    if (not isinstance(policy, dict) or not isinstance(policy.get('astra'), dict)
            or not isinstance(policy.get('effort_escalation'), dict)
            or policy['astra'].get('alternative_layer') not in registry['layers']
            or policy['effort_escalation'].get('optional_efforts') != ['high', 'xhigh']):
        raise ValueError('Routing registry requires task-sensitive Astra alternatives and optional high/xhigh escalation policy')
    if not isinstance(current, dict) or not isinstance(current.get('roles', {}), dict):
        raise ValueError('Current configuration and roles must be objects')
    current_roles = current.get('roles', {})
    for role in set(current_roles).intersection(ROLES):
        value = current_roles[role]
        if role in PANELS and (not isinstance(value, list) or len(value) != PANELS[role]):
            raise ValueError(role + ' panel count must be ' + str(PANELS[role]))
        if role not in PANELS and isinstance(value, list):
            raise ValueError(role + ' is not a panel')
    selected_budget = budget if budget is not None else current.get('budget', registry['budget'])
    if selected_budget not in BUDGETS:
        raise ValueError('Use an exact upstream budget label')
    target = BUDGETS[selected_budget] if budget is not None else None
    entries = catalog_entries(catalog)
    layers = {name: binding(value) for name, value in registry['layers'].items()}
    preference_state = current.get('routing_preferences', {})
    if not isinstance(preference_state, dict):
        raise ValueError('Stored routing preferences must be an object')
    preferences = preference_state.get('roles', {})
    if not isinstance(preferences, dict):
        raise ValueError('Stored routing preferences must be an object')
    roles = {}
    for role in ROLES:
        specs = registry['roles'][role]
        specs = specs if isinstance(specs, list) else [specs]
        prior = current_roles.get(role)
        priors = prior if isinstance(prior, list) else [prior] * len(specs)
        stored = preferences.get(role)
        stored_choices = stored if isinstance(stored, list) else [stored] * len(specs)
        if len(stored_choices) != len(specs):
            raise ValueError(role + ' stored preference panel count changed')
        choices = []
        for spec, previous, stored_choice in zip(specs, priors, stored_choices):
            if (isinstance(stored_choice, dict) and stored_choice.get('layer') == 'user-choice'
                    and stored_choice.get('effective') == previous):
                previous = binding(stored_choice['requested'])
            prior_alias = alias(previous)
            if prior_alias is not None:
                choices.append(prior_alias)
                continue
            default_alias = alias(spec)
            if default_alias is not None and previous is None:
                choices.append(default_alias)
                continue
            if default_alias is not None:
                requested = binding(previous)
                layer = 'user-choice'
                required = ['read_files'] if role == 'why investigators' else ['respond']
            else:
                layer = spec['layer']
                requested = layers[layer]
                required = spec['requires']
                incumbent = layers[spec.get('incumbent_layer', layer)]
                if previous is not None and binding(previous) != incumbent:
                    requested = binding(previous)
                    layer = 'user-choice'
            requested, entry = discovered(requested, entries, target)
            missing = sorted(set(required) - set(entry['capabilities']))
            effective = requested
            effective_entry = entry
            reason = 'requested-capabilities-available'
            if missing:
                effective = None
                effective_entry = None
                reason = 'needs-file-proof: ' + ', '.join(missing)
                if requested['provider'] == 'grok':
                    try:
                        file_lane, file_entry = discovered(layers['native_file_lane'], entries)
                    except ValueError:
                        pass
                    else:
                        if set(required) <= set(file_entry['capabilities']):
                            effective, effective_entry = file_lane, file_entry
                            reason += '; proposed native file lane requires host confirmation'
            alternatives = []
            if requested['model'] == policy['astra']['model']:
                alternative_layer = policy['astra']['alternative_layer']
                alternative_binding = layers[alternative_layer]
                alternative_entry = entries.get(tuple(alternative_binding[key] for key in FIELDS[:3]))
                alternative_available = (alternative_entry is not None and alternative_entry['available']
                                         and alternative_binding['effort'] in alternative_entry['efforts'])
                alternative_capabilities = sorted(alternative_entry['capabilities']) if alternative_available else []
                alternative_missing = sorted(set(required) - set(alternative_capabilities))
                alternatives.append({'layer': alternative_layer, 'binding': alternative_binding,
                                     'available': alternative_available and not alternative_missing,
                                     'capabilities': alternative_capabilities, 'missing_capabilities': alternative_missing,
                                     'reason': ('task-sensitive alternative; prefer for bounded routine judgment/prose'
                                                if alternative_available and not alternative_missing else
                                                'unavailable alternative; requires discovered tuple, effort and role capabilities'),
                                     'selection_policy': copy.deepcopy(policy['astra'])})
            optional_escalations = [{'effort': effort, 'effort_discovered': effort in entry['efforts'],
                                     'capabilities_satisfied': not missing,
                                     'available': effort in entry['efforts'] and not missing,
                                     'requires': list(policy['effort_escalation']['requires'])}
                                    for effort in policy['effort_escalation']['optional_efforts']
                                    if EFFORTS.index(effort) > EFFORTS.index(requested['effort'])]
            choices.append({'layer': layer, 'requested': requested, 'effective': effective,
                            'alternatives': alternatives, 'optional_escalations': optional_escalations,
                            'requires': list(required), 'requested_capabilities': sorted(entry['capabilities']),
                            'effective_capabilities': sorted(effective_entry['capabilities']) if effective_entry else [],
                            'missing_capabilities': missing, 'reason': reason,
                            'effort_override': target is None and BUDGETS[selected_budget] is not None and requested['effort'] != BUDGETS[selected_budget]})
        roles[role] = choices if role in PANELS else choices[0]
    plan = {'schema_version': 1, 'budget': selected_budget,
            'budget_mode': 'explicit-transform' if budget is not None else 'layered-role-overrides',
            'layers': layers, 'selection_policy': copy.deepcopy(policy),
            'catalog': catalog, 'current_digest': digest(current),
            'dropped_roles': sorted(set(current_roles) - set(ROLES)), 'roles': roles,
            'confirmation': 'host-required; candidate export does not apply configuration',
            'provider_failure_policy': 'stop; no implicit fallback'}
    plan['plan_digest'] = digest(plan)
    return plan


def validate_plan(plan, catalog, current, registry=None):
    if not isinstance(plan, dict) or plan.get('schema_version') != 1:
        raise ValueError('Plan requires schema_version 1')
    role_shape(plan.get('roles'), 'Plan roles')
    expected = create_plan(catalog, current, registry,
                           plan.get('budget') if plan.get('budget_mode') == 'explicit-transform' else None)
    if plan != expected:
        raise ValueError('Plan differs from discovered capabilities, approved layers or current state; regenerate before confirmation')
    return plan


def candidate_config(plan, current):
    if plan.get('current_digest') != digest(current):
        raise ValueError('Current configuration changed; regenerate before confirmation')
    candidate = copy.deepcopy(current)
    roles = {}
    for role, value in plan['roles'].items():
        choices = value if isinstance(value, list) else [value]
        bindings = []
        for choice in choices:
            selected = alias(choice) or choice.get('effective')
            if selected is None:
                raise ValueError('Unresolved effective binding: ' + role)
            bindings.append(selected)
        roles[role] = bindings if role in PANELS else bindings[0]
    candidate.update(roles=roles, budget=plan['budget'])
    preferences = {}
    for role, value in plan['roles'].items():
        choices = value if isinstance(value, list) else [value]
        saved = [alias(choice) or {key: choice[key] for key in ('layer', 'requested', 'effective')} for choice in choices]
        preferences[role] = saved if role in PANELS else saved[0]
    candidate['routing_preferences'] = {'schema_version': 1, 'plan_digest': plan['plan_digest'],
        'budget_mode': plan['budget_mode'], 'selection_policy': copy.deepcopy(plan['selection_policy']), 'roles': preferences}
    return candidate


def confirmation_table(plan):
    rows = ['Budget: ' + plan['budget'] + ' (' + plan['budget_mode'] + ')',
            'Plan digest: ' + plan['plan_digest'],
            'Task selection: prefer Sol/high for bounded routine judgment/prose; use Astra when task evaluation warrants its cost.',
            'Optional effort escalation: high/xhigh require task evaluation, discovered support, capabilities and explicit selection.',
            '| Role | Panel count | Layer | Requested provider/transport/model/effort | Effective provider/transport/model/effort | Capabilities requested / effective | Unmet requirements and reason | Effort override | Task-sensitive alternative | Optional escalation |',
            '|---|---:|---|---|---|---|---|---|---|---|']
    def describe(value):
        return '/'.join(value[key] for key in FIELDS) if value else 'NEEDS CHOICE'
    for role in ROLES:
        value = plan['roles'][role]
        choices = value if isinstance(value, list) else [value]
        for index, choice in enumerate(choices):
            label = role + (' [' + str(index + 1) + ']' if role in PANELS else '')
            if alias(choice):
                cells = [label, str(len(choices)), 'inherited', choice['alias'], choice['alias'], 'parent host', 'omit model and effort overrides', 'unchanged', 'parent host', 'parent host']
            else:
                cells = [label, str(len(choices)), choice['layer'], describe(choice['requested']), describe(choice['effective']),
                         ', '.join(choice['requested_capabilities']) + ' / ' + ', '.join(choice['effective_capabilities']),
                         choice['reason'], str(choice['effort_override']).lower(),
                         '; '.join(describe(option['binding']) + (' available' if option['available'] else ' UNAVAILABLE')
                                   + ' (' + option['reason'] + '; capabilities ' + ', '.join(option['capabilities'])
                                   + '; missing ' + (', '.join(option['missing_capabilities']) or 'none') + ')'
                                   for option in choice['alternatives']) or 'none',
                         ', '.join(option['effort'] + (' discovered; evaluation required' if option['available']
                                                              else ' discovered; unmet capabilities' if option['effort_discovered']
                                                              else ' unavailable')
                                   for option in choice['optional_escalations']) or 'none']
            rows.append('| ' + ' | '.join(cells) + ' |')
    rows.append('Dropped retired roles: ' + (', '.join(plan['dropped_roles']) or 'none'))
    rows.append(plan['confirmation'])
    return '\n'.join(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('plan', 'validate'))
    parser.add_argument('--catalog', type=Path, required=True, help='Actual caller discovery JSON; never inferred from model names')
    parser.add_argument('--current', '--config', type=Path, required=True)
    parser.add_argument('--layers', type=Path, default=REGISTRY)
    parser.add_argument('--budget', choices=tuple(BUDGETS), help='Explicit uniform effort transformation; omitted preserves layered overrides')
    parser.add_argument('--plan', type=Path, help='Saved proposal for validate')
    parser.add_argument('--plan-output', type=Path, help='Export reviewable proposal; does not apply it')
    parser.add_argument('--output', type=Path, help='Export candidate effective configuration; host confirmation and write remain separate')
    args = parser.parse_args(argv)
    try:
        input_paths = [args.current, args.catalog, args.layers] + ([args.plan] if args.plan else [])
        outputs = [path for path in (args.output, args.plan_output) if path]
        if any(path.resolve() == source.resolve() or (path.exists() and source.exists() and path.samefile(source))
               for path in outputs for source in input_paths):
            raise ValueError('Export cannot overwrite current configuration or input files')
        if len({path.resolve() for path in outputs}) != len(outputs) or (len(outputs) == 2 and all(path.exists() for path in outputs) and outputs[0].samefile(outputs[1])):
            raise ValueError('Plan and candidate exports require distinct files')
        current, catalog, registry = (json.loads(path.read_text()) for path in (args.current, args.catalog, args.layers))
        if args.command == 'validate':
            if args.plan is None or args.budget is not None:
                raise ValueError('validate requires --plan and no --budget')
            plan = validate_plan(json.loads(args.plan.read_text()), catalog, current, registry)
        else:
            if args.plan is not None:
                raise ValueError('plan creates a proposal; use validate for --plan')
            plan = create_plan(catalog, current, registry, args.budget)
        print(confirmation_table(plan))
        candidate = candidate_config(plan, current) if args.output else None
        for path, data in ((args.plan_output, plan), (args.output, candidate)):
            if path:
                path.write_text(json.dumps(data, indent=2) + '\n')
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print('Setup routing error: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
