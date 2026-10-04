#!/usr/bin/env python3
"""Summarize locally checked run evidence. This module never calls a provider."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

RUBRIC = {'correctness': 45, 'scope': 20, 'verification': 20, 'completeness': 15}
WEIGHTS = {'quality': .70, 'latency': .15, 'cost': .15}
CHECKLIST = ('limiter', 'tuning', 'limits', 'errors', 'repeatability', 'relevance', 'workHappened')
BINDING = ('model', 'provider', 'transport', 'effort', 'host', 'harness')
REQUIRED = {'candidate', *BINDING, 'task', 'taskDigest', 'repeat', 'success', 'workVerified',
            'criteriaScores', 'elapsedSeconds', 'criticalViolation', 'evidence'}
OPTIONAL = {'nativeCostUSD', 'estimatedCostUSD', 'tokens'}


def fail(message):
    raise ValueError(message)


def number(value, name, low=0, high=None):
    try:
        finite = math.isfinite(value) if isinstance(value, (int, float)) else False
    except OverflowError:
        finite = False
    if isinstance(value, bool) or not finite:
        fail(name + ' must be a finite number')
    if value < low or (high is not None and value > high):
        fail(name + ' is outside its permitted range')
    return value


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        fail(name + ' must be nonempty text')
    return value


def boolean(value, name):
    if type(value) is not bool:
        fail(name + ' must be boolean')


def digest(value, name):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        fail(name + ' must be a lowercase SHA-256 digest')


def scores(value):
    if not isinstance(value, dict) or set(value) != set(RUBRIC):
        fail('criteriaScores must contain exactly the four rubric criteria')
    for key, maximum in RUBRIC.items():
        number(value[key], key, high=maximum)


def read_json(path):
    def invalid_constant(value):
        fail('JSON nonfinite number: ' + value)
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                fail('duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=invalid_constant,
                      object_pairs_hook=unique_pairs)


def evidence_file(evidence, name, base):
    path = Path(text(evidence.get(name + 'Path'), name + 'Path'))
    path = (base / path).resolve() if not path.is_absolute() else path.resolve()
    expected = evidence.get(name + 'Sha256')
    digest(expected, name + 'Sha256')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        fail(name + ' artifact digest mismatch')
    return path


def validate_run(run, base):
    if not isinstance(run, dict) or not REQUIRED <= set(run) or set(run) - REQUIRED - OPTIONAL:
        fail('run fields do not match the documented record shape')
    for key in ('candidate', 'task', *BINDING):
        if key == 'effort' and run[key] is None:
            continue
        text(run[key], key)
    digest(run['taskDigest'], 'taskDigest')
    if type(run['repeat']) is not int or run['repeat'] < 1:
        fail('repeat must be a positive integer')
    for key in ('success', 'workVerified', 'criticalViolation'):
        boolean(run[key], key)
    scores(run['criteriaScores'])
    number(run['elapsedSeconds'], 'elapsedSeconds', low=0.000000001)
    for key in ('nativeCostUSD', 'estimatedCostUSD'):
        if run.get(key) is not None:
            number(run[key], key)
    if 'tokens' in run:
        if not isinstance(run['tokens'], dict) or set(run['tokens']) - {'input', 'output', 'total'}:
            fail('tokens permits only input/output/total')
        for key, value in run['tokens'].items():
            if type(value) is not int or value < 0:
                fail('token counts must be nonnegative integers')
    evidence = run['evidence']
    expected = {name + suffix for name in ('receipt', 'artifact', 'verification') for suffix in ('Path', 'Sha256')}
    if not isinstance(evidence, dict) or set(evidence) != expected:
        fail('evidence must contain receipt/artifact/verification paths and digests')
    paths = {name: evidence_file(evidence, name, base) for name in ('receipt', 'artifact', 'verification')}
    receipt, check = read_json(paths['receipt']), read_json(paths['verification'])
    if not isinstance(receipt, dict) or not isinstance(check, dict):
        fail('receipt and verification must be JSON objects')
    for key in ('provider', 'model', 'effort', 'transport'):
        if receipt.get(key) != run[key]:
            fail('receipt binding mismatch: ' + key)
    if receipt.get('status') not in ('complete', 'failed', 'cancelled', 'timed-out'):
        fail('receipt requires a terminal outcome')
    if (receipt['status'] == 'complete') != run['success']:
        fail('success differs from terminal receipt')
    number(receipt.get('elapsedSeconds'), 'receipt elapsedSeconds', low=0.000000001)
    if receipt.get('elapsedSeconds') != run['elapsedSeconds']:
        fail('elapsedSeconds differs from terminal receipt')
    if run['success'] and receipt.get('authVerified') is not True:
        fail('successful receipt lacks authenticated execution evidence')
    if run['success'] and receipt.get('modelVerified') is not True:
        fail('successful receipt lacks verified model identity')
    if check.get('kind') != 'artifact-check' or check.get('source') != 'independent-observation':
        fail('verification must be an independent artifact check, not a worker self-report')
    scores(check.get('criteriaScores'))
    for key in ('workVerified', 'criticalViolation'):
        boolean(check.get(key), 'verification ' + key)
    text(check.get('verifier'), 'verifier')
    if check['verifier'] == run['candidate']:
        fail('candidate cannot verify its own result')
    for key in ('taskDigest', 'criteriaScores', 'criticalViolation', 'workVerified'):
        if check.get(key) != run[key]:
            fail('verification mismatch: ' + key)
    if check.get('artifactSha256') != evidence['artifactSha256']:
        fail('verification is not bound to the observed artifact')
    if check.get('receiptSha256') != evidence['receiptSha256']:
        fail('verification is not bound to the terminal receipt')
    if run['workVerified'] and (not run['success'] or not paths['artifact'].stat().st_size):
        fail('verified work requires a successful receipt and nonempty artifact')
    if not run['workVerified'] and any(run['criteriaScores'].values()):
        fail('unverified work cannot receive quality points')
    if run.get('nativeCostUSD') is not None:
        number(check.get('nativeCostUSD'), 'verification nativeCostUSD')
        if check.get('nativeCostUSD') != run['nativeCostUSD'] or check.get('costSource') != 'native-measured':
            fail('native cost requires independently observed native measurement')
    return paths['receipt']


def distribution(values):
    return {'median': statistics.median(values), 'range': [min(values), max(values)],
            'mean': statistics.mean(values)}


def ratio(best, value):
    return 1.0 if value == 0 else best / value


def summarize(document, base=Path('.'), mode='smoke', allow_unit_fixtures=False):
    if not isinstance(document, dict) or set(document) != {'schemaVersion', 'evidenceKind', 'policy', 'runs'}:
        fail('document requires exactly schemaVersion/evidenceKind/policy/runs')
    if type(document['schemaVersion']) is not int or document['schemaVersion'] != 1:
        fail('unsupported schemaVersion')
    synthetic = document['evidenceKind'] == 'unit-fixture'
    if document['evidenceKind'] != 'captured' and not (synthetic and allow_unit_fixtures):
        fail('fabricated, unknown or unit-fixture evidence cannot establish real routing')
    policy, runs = document['policy'], document['runs']
    if not isinstance(policy, dict) or set(policy) - {'weights', 'incumbent', 'checklist'}:
        fail('policy permits only weights/incumbent/checklist')
    weights = policy.get('weights', WEIGHTS)
    if not isinstance(weights, dict) or set(weights) != set(WEIGHTS):
        fail('weights requires quality/latency/cost')
    for key, value in weights.items():
        number(value, 'weight ' + key, high=1)
    if not math.isclose(sum(weights.values()), 1, abs_tol=1e-9):
        fail('declared weights must sum to one')
    incumbent = policy.get('incumbent')
    if incumbent is not None:
        text(incumbent, 'incumbent')
    checklist = policy.get('checklist', {})
    if not isinstance(checklist, dict) or set(checklist) - set(CHECKLIST):
        fail('invalid benchmark checklist')
    if not isinstance(runs, list) or not runs:
        fail('at least one run is required')
    groups, receipts, receipt_digests, attempts, task_digests = {}, set(), set(), set(), {}
    for run in runs:
        receipt = validate_run(run, Path(base))
        receipt_digest = run['evidence']['receiptSha256']
        if receipt in receipts or receipt_digest in receipt_digests:
            fail('reused receipt cannot count as another run')
        receipts.add(receipt)
        receipt_digests.add(receipt_digest)
        identity = (run['candidate'], run['task'], run['repeat'])
        if identity in attempts:
            fail('duplicate candidate/task/repeat')
        attempts.add(identity)
        group = groups.setdefault(run['candidate'], [])
        if group and any(group[0][key] != run[key] for key in BINDING):
            fail('candidate binding changed between attempts')
        group.append(run)
        if run['task'] in task_digests and task_digests[run['task']] != run['taskDigest']:
            fail('task specification changed between attempts')
        task_digests[run['task']] = run['taskDigest']
    report = {'mode': mode, 'evidenceKind': document['evidenceKind'], 'policyLabel': 'local numerical rubric, not a capability benchmark',
              'weights': weights, 'qualityGate': {'perTaskMeanAtLeast': 85, 'criticalViolations': 0},
              'candidates': {}, 'selected': None, 'incumbent': incumbent, 'preserveIncumbent': True, 'reasons': []}
    for candidate, group in groups.items():
        quality = [sum(run['criteriaScores'].values()) if run['success'] and run['workVerified'] else 0 for run in group]
        per_task = {task: distribution([quality[i] for i, run in enumerate(group) if run['task'] == task])
                    for task in sorted({run['task'] for run in group})}
        eligible = all(item['mean'] >= 85 for item in per_task.values()) and not any(run['criticalViolation'] for run in group)
        costs = [run['nativeCostUSD'] for run in group if run.get('nativeCostUSD') is not None]
        estimates = [run['estimatedCostUSD'] for run in group if run.get('estimatedCostUSD') is not None]
        report['candidates'][candidate] = {'binding': {key: group[0][key] for key in BINDING},
            'runs': len(group), 'successes': sum(run['success'] for run in group),
            'verifiedWork': sum(run['success'] and run['workVerified'] for run in group),
            'failures': sum(not run['success'] for run in group), 'quality': distribution(quality),
            'terminalFailures': sum(not run['success'] for run in group),
            'verificationFailures': sum(run['success'] and not run['workVerified'] for run in group),
            'outcomeFailures': sum(not run['success'] or not run['workVerified'] for run in group),
            'criticalViolations': sum(run['criticalViolation'] for run in group),
            'qualityGateFailures': [task for task, values in per_task.items() if values['mean'] < 85],
            'qualityByTask': per_task, 'elapsedSeconds': distribution([run['elapsedSeconds'] for run in group]),
            'nativeCostUSD': distribution(costs) if len(costs) == len(group) else None,
            'estimatedCostUSD': distribution(estimates) if estimates else None,
            'costEvidence': {'measuredRuns': len(costs), 'estimatedRuns': len(estimates), 'estimatesUsedForSelection': False},
            'tokens': {key: distribution([run['tokens'][key] for run in group if key in run.get('tokens', {})])
                       for key in ('input', 'output', 'total') if any(key in run.get('tokens', {}) for run in group)},
            'eligible': eligible}
    reasons = report['reasons']
    if synthetic:
        reasons.append('synthetic unit fixtures never establish availability or select a model')
    if mode == 'smoke':
        report['verdict'] = 'fixture-only' if synthetic else 'availability-only'
        report['availability'] = {candidate: not synthetic and any(run['success'] and run['workVerified'] for run in group)
                                  for candidate, group in groups.items()}
        reasons.append('smoke establishes observed availability only; one run cannot choose a winner')
        return report
    if mode != 'selection':
        fail('mode must be smoke or selection')
    if len(groups) < 2:
        reasons.append('selection requires at least two options')
    if incumbent is not None and incumbent not in groups:
        reasons.append('incumbent has no comparable observed runs')
    missing = [key for key in CHECKLIST if not isinstance(checklist.get(key), str) or not checklist[key].strip()]
    if missing:
        reasons.append('benchmark checklist lacks evidence: ' + ', '.join(missing))
    candidates = set(groups)
    for task in task_digests:
        task_runs = [run for run in runs if run['task'] == task]
        counts = [sum(run['task'] == task for run in group) for group in groups.values()]
        if min(counts) < 5 or len(set(counts)) != 1:
            reasons.append('task ' + task + ' needs at least five equal repeats per option')
            continue
        for index in range(0, len(task_runs), len(candidates)):
            batch = task_runs[index:index + len(candidates)]
            repeat = index // len(candidates) + 1
            if {run['candidate'] for run in batch} != candidates or any(run['repeat'] != repeat for run in batch):
                reasons.append('task ' + task + ' was not interleaved in complete numbered rounds')
                break
    eligible = [candidate for candidate, result in report['candidates'].items() if result['eligible']]
    if not eligible:
        reasons.append('no option meets the quality gate for every task')
    if weights['cost'] and any(run.get('nativeCostUSD') is None for candidate in eligible for run in groups[candidate]):
        reasons.append('comparable native cost is unknown; estimates cannot resolve the choice')
    if reasons:
        report['verdict'] = 'inconclusive'
        return report
    for candidate in eligible:
        task_utilities, task_ranges = [], []
        for task in task_digests:
            task_groups = {option: [run for run in groups[option] if run['task'] == task] for option in eligible}
            best_latency = min(statistics.median(run['elapsedSeconds'] for run in group) for group in task_groups.values())
            best_cost = min(statistics.mean(run['nativeCostUSD'] for run in group) for group in task_groups.values()) if weights['cost'] else 0
            group = task_groups[candidate]
            utilities = [weights['quality'] * sum(run['criteriaScores'].values()) / 100 +
                         weights['latency'] * min(1, ratio(best_latency, run['elapsedSeconds'])) +
                         (weights['cost'] * min(1, ratio(best_cost, run['nativeCostUSD'])) if weights['cost'] else 0) for run in group]
            q = statistics.mean(sum(run['criteriaScores'].values()) for run in group)
            task_utilities.append(weights['quality'] * q / 100 +
                                  weights['latency'] * ratio(best_latency, statistics.median(run['elapsedSeconds'] for run in group)) +
                                  (weights['cost'] * ratio(best_cost, statistics.mean(run['nativeCostUSD'] for run in group)) if weights['cost'] else 0))
            task_ranges.append([min(utilities), max(utilities)])
        result = report['candidates'][candidate]
        result['utility'] = statistics.mean(task_utilities)
        result['utilityRange'] = [statistics.mean(item[i] for item in task_ranges) for i in (0, 1)]
    ranked = sorted(eligible, key=lambda key: report['candidates'][key]['utility'], reverse=True)
    winner = ranked[0]
    if len(ranked) > 1:
        runner_up = ranked[1]
        gap = report['candidates'][winner]['utility'] - report['candidates'][runner_up]['utility']
        report['utilityGap'] = gap
        if any(report['candidates'][winner]['utilityRange'][0] <= report['candidates'][other]['utilityRange'][1]
               for other in ranked[1:]):
            reasons.append('utility gap overlaps observed run variation; no measurable difference')
            report['verdict'] = 'inconclusive'
            return report
    report.update(verdict='selected', selected=winner, preserveIncumbent=winner == incumbent)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--mode', choices=('smoke', 'selection'), default='smoke')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--allow-unit-fixtures', action='store_true', help='exercise parser only; never select a real model')
    args = parser.parse_args(argv)
    try:
        report = summarize(read_json(args.input), args.input.resolve().parent, args.mode, args.allow_unit_fixtures)
        output = json.dumps(report, indent=2, allow_nan=False) + '\n'
        if args.output:
            args.output.write_text(output, encoding='utf-8')
        else:
            sys.stdout.write(output)
        return 0
    except (ValueError, OSError, TypeError) as error:
        print('invalid evidence: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
