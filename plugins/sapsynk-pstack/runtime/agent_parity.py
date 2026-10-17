#!/usr/bin/env python3
"""Summarize hash-bound capability evidence; never launch workers or certify parity."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

CAPABILITIES = ('read', 'edit', 'verify', 'broker-confinement', 'status', 'cancel',
                'concurrent-isolated', 'logs', 'messaging', 'os-isolation', 'context-metrics')
STATUSES = ('verified', 'partial', 'blocked', 'unknown')
BINDING = ('provider', 'transport', 'model', 'effort', 'host', 'harness')
CORE_TOOLS = {'read': 'read_text', 'edit': 'write_text', 'verify': 'check'}
NATIVE_TOOLS = {'read': {'read_file'}, 'edit': {'search_replace', 'write'}, 'verify': {'run_terminal_command'}}
# Tool names in a pstack-run event log, per provider CLI.
RUNNER_TOOLS = {'grok': NATIVE_TOOLS,
                'claude': {'read': {'Read'}, 'edit': {'Edit', 'Write'}, 'verify': {'Bash'}},
                'codex': {'read': {'command_execution'}, 'edit': {'file_change'}, 'verify': {'command_execution'}}}
RUNNER_STATES = {'succeeded': 'complete', 'failed': 'failed', 'lost': 'failed', 'killed': 'cancelled',
                 'timeout': 'timed-out', 'startup_timeout': 'timed-out', 'stalled': 'timed-out', 'limited': 'failed'}


def fail(message):
    raise ValueError(message)


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        fail(name + ' must be nonempty text')
    return value


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail('duplicate JSON key: ' + key)
            result[key] = value
        return result
    def constant(value):
        fail('nonfinite JSON number: ' + value)
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=constant)


def evidence_files(evidence, base):
    required = {'task', 'receipt', 'native', 'artifact', 'verification'}
    if not isinstance(evidence, dict) or not required <= set(evidence):
        fail('evidence requires task/receipt/native/artifact/verification file references')
    paths, hashes = {}, {}
    for name, reference in evidence.items():
        text(name, 'evidence name')
        if not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}:
            fail('evidence references require exactly path/sha256')
        digest = reference['sha256']
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            fail('evidence sha256 must be a lowercase SHA-256 digest')
        path = Path(text(reference['path'], 'evidence path'))
        path = (base / path).resolve() if not path.is_absolute() else path.resolve()
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            fail('evidence digest mismatch: ' + name)
        paths[name], hashes[name] = path, digest
    if len(set(paths.values())) != len(paths):
        fail('distinct evidence names must refer to distinct files')
    return paths, hashes


def native_records(path):
    raw = path.read_text(encoding='utf-8')
    try:
        value = read_json(path)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, dict) and isinstance(value.get('stdout'), str):
        raw = value['stdout']
    elif isinstance(value, list):
        return value
    elif isinstance(value, dict):
        return [value]
    records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if not records or not all(isinstance(item, dict) for item in records):
        fail('native evidence must contain event objects')
    return records


def grok_observation(records, receipt):
    init = [item for item in records if item.get('type') == 'system' and item.get('subtype') == 'init']
    if len(init) != 1 or init[0].get('model') != receipt['model']:
        fail('Grok native init must identify the requested model exactly once')
    session = text(init[0].get('session_id'), 'native session_id')
    targets, assistant_seen, terminal = set(), False, False
    terminal_seen = False
    for item in records:
        if terminal_seen: fail('native event after terminal')
        if item.get('session_id') != session:
            fail('native session changed or is absent')
        if item.get('type') == 'assistant':
            message = item.get('message', {})
            if message.get('model') != receipt['model'] or message.get('role') != 'assistant':
                fail('native assistant model/role mismatch')
            assistant_seen = True
            for block in message.get('content', []):
                if block.get('type') == 'tool_use':
                    target = block.get('input', {}).get('tool_name') if block.get('name') == 'use_tool' else block.get('name')
                    if isinstance(target, str):
                        targets.add(target)
        if item.get('type') == 'result':
            terminal_seen = True
            terminal = item.get('subtype') == 'success' and item.get('is_error') is False and item.get('stop_reason') == 'end_turn' and isinstance(item.get('result'), str) and bool(item['result'].strip())
    if receipt['status'] == 'complete' and not (assistant_seen and terminal):
        fail('complete receipt lacks successful native assistant/result evidence')
    return targets


def runner_observation(status, records):
    """Read a pstack-run status.json and its event log as a terminal receipt plus the tools actually used."""
    provider, model = status.get('provider'), status.get('model')
    if provider not in RUNNER_TOOLS or status.get('state') not in RUNNER_STATES:
        fail('runner receipt needs a known provider and a terminal state')
    starts = [index for index, item in enumerate(records) if item.get('type') == 'pstack.started']
    # The log holds every attempt; only the receipt's own attempt is evidence for it.
    records = records[starts[-1]:] if starts else records
    served, targets, calls = set(), set(), {}
    for item in records:
        kind = item.get('type')
        if provider == 'grok':
            if kind == 'tool_call':
                calls[item.get('toolCallId')] = item.get('toolName')
            if kind == 'tool_call_update' and item.get('status') in ('failed', 'error', 'cancelled'):
                # Grok marks only terminal commands `completed`; file tools just stop updating.
                calls.pop(item.get('toolCallId'), None)
            if kind == 'end':
                served.update(item.get('modelUsage') or {})
        elif provider == 'claude' and kind in ('assistant', 'user'):
            message = item.get('message') or {}
            if kind == 'assistant':
                served.add(message.get('model'))
            for block in message.get('content') or []:
                if not isinstance(block, dict):
                    continue
                if block.get('type') == 'tool_use':
                    calls[block.get('id')] = block.get('name')
                if block.get('type') == 'tool_result' and not block.get('is_error'):
                    targets.add(calls.get(block.get('tool_use_id')))
        elif provider == 'codex' and kind == 'item.completed':
            done = item.get('item') or {}
            if done.get('status') == 'completed' and done.get('exit_code') in (None, 0):
                targets.add(done.get('type'))
    if provider == 'grok':
        targets = set(calls.values())
    targets.discard(None)
    argv = status.get('argv') or []
    # Codex reports no served model; the pinned argv is its evidence, as in the request-file lane.
    pinned = provider == 'codex' and '-m' in argv and argv[argv.index('-m') + 1] == model
    verified = bool(model) and (pinned or any(isinstance(name, str) and (name == model or name.startswith(model + '-')) for name in served))
    complete = status['state'] == 'succeeded'
    receipt = {'provider': provider, 'transport': 'pstack-run', 'model': model, 'effort': status.get('effort'),
               'status': RUNNER_STATES[status['state']], 'authVerified': complete, 'modelVerified': complete and verified,
               'confinement': 'worktree', 'filesystemIsolation': 'off'}
    return receipt, targets


def broker_observation(path):
    records = native_records(path)
    successful = set()
    for item in records:
        call, result = item.get('call'), item.get('result')
        if not isinstance(call, dict) or not isinstance(result, dict):
            fail('broker log requires actual call/result objects')
        name = text(call.get('name'), 'broker call name')
        if type(result.get('isError')) is not bool:
            fail('broker result requires boolean isError')
        if result['isError'] is False:
            successful.add(name)
    return successful


def summarize(document, base=Path('.'), allow_unit_fixtures=False):
    if not isinstance(document, dict) or set(document) != {'schemaVersion', 'evidenceKind', 'runs'}:
        fail('document requires exactly schemaVersion/evidenceKind/runs')
    if type(document['schemaVersion']) is not int or document['schemaVersion'] != 1:
        fail('unsupported schemaVersion')
    fixture = document['evidenceKind'] == 'unit-fixture'
    if document['evidenceKind'] != 'captured' and not (fixture and allow_unit_fixtures):
        fail('unit-fixture evidence needs --allow-unit-fixtures; unknown evidence kinds are rejected')
    runs = document['runs']
    if not isinstance(runs, list) or not runs:
        fail('at least one observed run is required')
    report = {'schemaVersion': 1, 'verdict': 'fixture-only' if fixture else 'observed-capabilities',
              'fullParity': False, 'runs': [], 'limitations': [
                  'Scoped observations cannot certify full native agent parity.',
                  'Hashes detect changed artifacts; the coordinator must inspect honest captures and adequate checks.',
                  'Usage tokens are not context-window, compaction or remaining-budget verification.',
                  'Broker path restrictions are not OS filesystem/process/network or credential isolation.',
                  'Local cancellation does not establish remote API cancellation.']}
    seen_receipts, seen_identities = set(), set()
    for run in runs:
        if not isinstance(run, dict) or set(run) != {'candidate', 'task', 'binding', 'evidence'}:
            fail('run requires exactly candidate/task/binding/evidence')
        candidate, task = text(run['candidate'], 'candidate'), text(run['task'], 'task')
        binding = run['binding']
        if not isinstance(binding, dict) or set(binding) != set(BINDING):
            fail('binding requires provider/transport/model/effort/host/harness')
        for key, value in binding.items():
            if key != 'effort' or value is not None:
                text(value, 'binding ' + key)
        identity = (candidate, task)
        if identity in seen_identities:
            fail('duplicate candidate/task; name separate attempts explicitly')
        seen_identities.add(identity)
        paths, hashes = evidence_files(run['evidence'], Path(base))
        if hashes['receipt'] in seen_receipts:
            fail('reused receipt cannot count as another observation')
        seen_receipts.add(hashes['receipt'])
        receipt, check = read_json(paths['receipt']), read_json(paths['verification'])
        if not isinstance(receipt, dict) or not isinstance(check, dict):
            fail('receipt and independent check must be JSON objects')
        runner = 'task_id' in receipt and 'state' in receipt
        if runner:
            receipt, runner_targets = runner_observation(receipt, native_records(paths['native']))
        for key in ('provider', 'transport', 'model', 'effort'):
            if receipt.get(key) != binding[key]:
                fail('receipt binding mismatch: ' + key)
        if receipt.get('status') not in ('complete', 'failed', 'cancelled', 'timed-out'):
            fail('receipt must record a terminal outcome')
        complete = receipt['status'] == 'complete'
        if complete and (receipt.get('authVerified') is not True or receipt.get('modelVerified') is not True):
            fail('complete receipt lacks authenticated/model-verified execution')
        if check.get('kind') != 'artifact-check' or check.get('source') != 'independent-observation':
            fail('independent artifact check required; worker self-reports do not count')
        if text(check.get('verifier'), 'verifier') == candidate:
            fail('candidate cannot verify its own work')
        if check.get('task') != task or check.get('taskDigest') != hashes['task']:
            fail('check is not bound to this immutable task')
        if check.get('evidenceSha256') != {key: value for key, value in hashes.items() if key != 'verification'}:
            fail('check must bind every evidence file except itself by exact digest')
        if type(check.get('workVerified')) is not bool or type(check.get('criticalViolation')) is not bool:
            fail('check requires boolean workVerified/criticalViolation')
        if check['workVerified'] and (not complete or not paths['artifact'].stat().st_size or check['criticalViolation']):
            fail('verified work requires complete nonempty artifact without critical violation')
        records = native_records(paths['native'])
        targets = runner_targets if runner else grok_observation(records, receipt) if binding['provider'] == 'grok' else set()
        broker_calls = broker_observation(paths['broker']) if 'broker' in paths else set()
        capabilities = check.get('capabilities')
        if not isinstance(capabilities, dict) or set(capabilities) - set(CAPABILITIES):
            fail('check capabilities contains an unknown capability')
        matrix = {}
        for name in CAPABILITIES:
            item = capabilities.get(name, {'status': 'unknown', 'detail': 'No observation supplied.', 'observations': []})
            if not isinstance(item, dict) or set(item) != {'status', 'detail', 'observations'} or item['status'] not in STATUSES:
                fail('capability requires status/detail/observations')
            text(item['detail'], 'capability detail')
            observations = item['observations']
            if not isinstance(observations, list) or not all(isinstance(key, str) and key in paths and key != 'verification' for key in observations):
                fail('capability observations must name hash-bound evidence files')
            if item['status'] in ('verified', 'partial', 'blocked') and not observations:
                fail('observed capability status requires concrete evidence references')
            if item['status'] == 'verified' and name in CORE_TOOLS:
                tool = CORE_TOOLS[name]
                direct = receipt.get('confinement') == 'managed-host'
                matched = bool(targets & NATIVE_TOOLS[name]) if direct else tool in broker_calls and any(target.endswith('__' + tool) for target in targets)
                if runner:
                    matched = bool(targets & RUNNER_TOOLS[binding['provider']][name])
                if (runner or binding['provider'] == 'grok') and not matched:
                    fail(name + ' requires matching genuine native tool use' + ('' if runner else ' and successful broker call'))
                if not check['workVerified'] or not {'native', 'artifact'} <= set(observations):
                    fail(name + ' requires independently checked actual work and native/artifact observations')
                if binding['provider'] == 'grok' and not direct and not runner and 'broker' not in observations:
                    fail(name + ' requires broker observation')
            if item['status'] == 'verified' and name == 'os-isolation' and receipt.get('filesystemIsolation') in ('unavailable', 'off'):
                fail('OS isolation claim contradicts terminal receipt')
            matrix[name] = dict(item, status='unknown' if fixture else item['status'])
        report['runs'].append({'candidate': candidate, 'task': task, 'binding': binding,
                               'terminalStatus': receipt['status'], 'available': not fixture and complete and check['workVerified'],
                               'nativeLikeReadEditVerify': not fixture and all(matrix[key]['status'] == 'verified' for key in CORE_TOOLS),
                               'criticalViolation': check['criticalViolation'], 'capabilities': matrix,
                               'evidenceSha256': hashes})
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--allow-unit-fixtures', action='store_true')
    args = parser.parse_args(argv)
    try:
        report = summarize(read_json(args.input), args.input.resolve().parent, args.allow_unit_fixtures)
        output = json.dumps(report, indent=2, allow_nan=False) + '\n'
        if args.output:
            args.output.write_text(output, encoding='utf-8')
        else:
            sys.stdout.write(output)
        return 0
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as error:
        print('invalid evidence: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
