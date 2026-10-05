#!/usr/bin/env python3
"""Decide where one unit of work runs: inline, a cheap native subagent, a worker, or a panel."""
import json
from pathlib import Path
import time

# A CLI worker costs about 15k input tokens per turn before it reads the brief (measured on a
# trivial prompt: Grok 14k, lean Codex 15k, lean Claude 15k), so smaller work is cheaper inline.
THRESHOLDS = {'inline_max_steps': 3, 'inline_max_files': 2, 'inline_max_lines': 30, 'inline_max_tokens': 15000,
              'inline_max_minutes': 5, 'subagent_max_tokens': 60000, 'small_subject_lines': 150,
              'small_subject_effort': 'low', 'small_subject_timeout_s': 300}
ROUTES = ('inline', 'native-subagent', 'worker', 'panel')
OBLIGATIONS = ('work on a feature branch, never on main; no push to main, merge or force-push',
               'run the project verifier or the narrowest real check and keep its output',
               'state the evidence for every claim in the reply',
               'keep this decision line in .pstack/state/dispatch.jsonl')
FACTS = {'steps': 1, 'files': 0, 'lines': 0, 'tokens': 0, 'minutes': 1, 'units': 1, 'subject_lines': 0}
FLAGS = ('read_only', 'judgment', 'panel', 'risky')


def thresholds(project=None):
    """Framework defaults overlaid by the project's `dispatch_policy` table."""
    path = Path(project) / '.pstack/config.json' if project else None
    overrides = json.loads(path.read_text()).get('dispatch_policy', {}) if path and path.is_file() else {}
    unknown = set(overrides) - set(THRESHOLDS)
    if unknown:
        raise ValueError('unknown dispatch_policy keys: ' + ', '.join(sorted(unknown)))
    return {**THRESHOLDS, **overrides}


def decide(facts, limits=None, override=None, reason=None):
    """Return the route for one unit of work. Rules run in order and the first match wins."""
    limits = limits or THRESHOLDS
    facts = {**FACTS, **{flag: False for flag in FLAGS}, **facts}
    small = facts['subject_lines'] <= limits['small_subject_lines'] and not facts['risky']
    caps = {'effort': limits['small_subject_effort'], 'timeout_s': limits['small_subject_timeout_s']} if small else None
    over = [name for name, limit in (('steps', 'inline_max_steps'), ('files', 'inline_max_files'),
                                     ('lines', 'inline_max_lines'), ('tokens', 'inline_max_tokens'),
                                     ('minutes', 'inline_max_minutes')) if facts[name] > limits[limit]]
    if override:
        if override not in ROUTES:
            raise ValueError('override must be one of ' + ', '.join(ROUTES))
        if not (reason or '').strip():
            raise ValueError('an override needs --reason')
        route, why, rule = override, reason.strip(), 'override'
    elif facts['panel']:
        route, why, rule = 'panel', 'the playbook or the owner requires this panel; keep every seat', 'required-panel'
    elif facts['judgment']:
        route, why, rule = 'worker', 'independent judgment needs a reviewer that is not the author', 'independent-judgment'
    elif facts['units'] > 1:
        route, why, rule = 'worker', f'{facts["units"]} independent units run in parallel, one worker each', 'parallel'
    elif facts['risky'] and not facts['read_only']:
        route, why, rule = 'worker', 'a guardrail, security or irreversible change gets its own worktree and review', 'risky'
    elif not over:
        route, why, rule = 'inline', 'under every inline threshold; a worker would cost more than the work', 'trivial'
    elif facts['read_only'] and over == ['tokens'] and facts['tokens'] <= limits['subagent_max_tokens']:
        route, why, rule = 'native-subagent', 'bulk reading stays out of the coordinator context', 'bulk-read'
    else:
        route, why, rule = 'worker', 'over the inline threshold for ' + ', '.join(over), 'substantial'
    result = {'route': route, 'rule': rule, 'reason': why, 'facts': facts}
    if route in ('worker', 'panel') and caps:
        result['caps'] = caps
    if route in ('inline', 'native-subagent'):
        result['obligations'] = list(OBLIGATIONS)
    return result


def record(project, task, decision):
    """Append the decision to the project's private dispatch log and return it."""
    entry = {'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'task': task, **decision}
    log = Path(project) / '.pstack/state/dispatch.jsonl'
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a') as handle:
        handle.write(json.dumps(entry) + '\n')
    return entry


def arguments(sub):
    sub.add_argument('task', help='Short label for the unit of work')
    for name, default in FACTS.items():
        sub.add_argument('--' + name.replace('_', '-'), type=int, default=default)
    for flag in FLAGS:
        sub.add_argument('--' + flag.replace('_', '-'), action='store_true')
    sub.add_argument('--override', choices=ROUTES, help='Escape hatch: force a route; requires --reason')
    sub.add_argument('--reason')
    sub.add_argument('--no-log', action='store_true', help='Print the decision without recording it')


def main(args, project):
    facts = {name: getattr(args, name) for name in (*FACTS, *FLAGS)}
    decision = decide(facts, thresholds(project), args.override, args.reason)
    print(json.dumps(decision if args.no_log else record(project, args.task, decision)))
    return 0
