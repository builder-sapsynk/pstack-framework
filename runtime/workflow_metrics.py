#!/usr/bin/env python3
"""Private lifecycle evidence and conservative, replayable workflow snapshots."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import time
import uuid

KINDS = {'registered', 'requested', 'started', 'observed-running', 'progress',
         'phase-start', 'phase-end', 'complete', 'failed', 'cancellation-requested',
         'cancelled', 'usage', 'context', 'workflow-start', 'workflow-end'}
TERMINAL = {'complete', 'failed', 'cancelled'}
STATE = {'registered': 'requested', 'requested': 'requested', 'started': 'active',
         'observed-running': 'active', 'complete': 'complete', 'failed': 'failed',
         'cancelled': 'cancelled'}
METADATA = {'role', 'host', 'provider', 'transport', 'model', 'effort', 'requested',
            'resolved', 'bindingEvidence', 'nativeAgentId', 'job_id', 'stage',
            'phaseId', 'elapsedSeconds', 'modelSeconds', 'apiSeconds', 'toolSeconds',
            'usage', 'context', 'fork_turns', 'briefBytes', 'failureCode',
            'root', 'sessionId', 'manifest', 'clockStart', 'clockEnd'}


def timestamp(value=None):
    if value is None:
        return dt.datetime.now(dt.timezone.utc).isoformat(timespec='microseconds')
    if not isinstance(value, str):
        raise ValueError('observedAt must be an ISO timestamp with timezone')
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('observedAt requires a timezone')
    return parsed.astimezone(dt.timezone.utc).isoformat(timespec='microseconds')


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def local_clock():
    try:
        return 'boot:' + Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        return 'process:' + str(os.getpid())


def private_directory(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('event directory cannot be a symlink')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def validate_metadata(metadata):
    if not isinstance(metadata, dict) or set(metadata) - METADATA:
        raise ValueError('unsupported metadata field; save only lifecycle and measurement facts')
    for key in ('elapsedSeconds', 'modelSeconds', 'apiSeconds', 'toolSeconds', 'briefBytes'):
        if key in metadata and not number(metadata[key]):
            raise ValueError(key + ' must be a finite nonnegative number')
    for key in ('requested', 'resolved'):
        if key in metadata and (not isinstance(metadata[key], dict) or set(metadata[key]) - {'provider', 'transport', 'model', 'effort', 'configuration'}):
            raise ValueError(key + ' must contain only binding fields')
    usage = metadata.get('usage')
    if usage is not None:
        allowed = {'input', 'output', 'cacheRead', 'cacheWrite', 'inputDefinition',
                   'source', 'quality', 'sampleId', 'scope', 'sessionId', 'raw', 'volumeScope'}
        if not isinstance(usage, dict) or set(usage) - allowed:
            raise ValueError('unsupported usage field')
        for key in ('input', 'output', 'cacheRead', 'cacheWrite'):
            if key in usage and usage[key] is not None and not number(usage[key]):
                raise ValueError('usage counter must be a nonnegative number')
        raw = usage.get('raw', {})
        if not isinstance(raw, dict) or not all(isinstance(k, str) and number(v) for k, v in raw.items()):
            raise ValueError('raw usage must contain numerical counters only')
        if usage.get('scope', 'attempt') not in ('attempt', 'session'):
            raise ValueError('usage scope must be attempt or session')
    context = metadata.get('context')
    if context is not None:
        allowed = {'tokens', 'capacity', 'model', 'configuration', 'observedAt', 'validForSeconds', 'source', 'quality'}
        if not isinstance(context, dict) or set(context) - allowed:
            raise ValueError('unsupported context field')
        for key in ('tokens', 'capacity', 'validForSeconds'):
            if key in context and not number(context[key]):
                raise ValueError('context measurement must be nonnegative')
        if 'observedAt' in context:
            timestamp(context['observedAt'])
    return metadata


def validate_event(event):
    required = {'schemaVersion', 'workflowId', 'workerId', 'parentWorkerId', 'attemptId',
                'eventId', 'seq', 'kind', 'observedAt', 'source', 'evidenceRef', 'metadata'}
    if not isinstance(event, dict) or not required <= set(event) or event['schemaVersion'] != 1:
        raise ValueError('invalid event schema')
    if event['kind'] not in KINDS or not isinstance(event['seq'], int) or event['seq'] < 1:
        raise ValueError('invalid lifecycle kind or sequence')
    for key in ('workflowId', 'workerId', 'attemptId', 'eventId', 'source'):
        if not isinstance(event[key], str) or not event[key].strip():
            raise ValueError(key + ' must be nonempty text')
    event['observedAt'] = timestamp(event['observedAt'])
    if 'monotonicSeconds' in event and (not number(event['monotonicSeconds']) or not event.get('clockId')):
        raise ValueError('monotonicSeconds requires a clockId')
    validate_metadata(event['metadata'])
    return event


def record_event(workflow, worker, kind, metadata=None, *, parent_worker=None,
                 attempt='1', source='coordinator', evidence_ref=None,
                 observed_at=None, clock_id=None, monotonic_seconds=None, event_id=None):
    """Append one fact. A worker stream has one owner; imports are idempotent."""
    directory = private_directory(workflow)
    events_dir = private_directory(directory / 'events')
    filename = hashlib.sha256(str(worker).encode()).hexdigest() + '.jsonl'
    path = events_dir / filename
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags, 0o600), 'r+', encoding='utf-8') as stream:
        os.fchmod(stream.fileno(), 0o600)
        fcntl.flock(stream, fcntl.LOCK_EX)
        records = [validate_event(json.loads(line)) for line in stream if line.strip()]
        identity = event_id or str(uuid.uuid4())
        matching = [event for event in records if event['eventId'] == identity]
        event = dict(schemaVersion=1, workflowId=directory.name, workerId=worker,
                     parentWorkerId=parent_worker, attemptId=str(attempt), eventId=identity,
                     seq=max((item['seq'] for item in records), default=0) + 1,
                     kind=kind, observedAt=timestamp(observed_at), source=source,
                     evidenceRef=evidence_ref, metadata={} if metadata is None else metadata)
        if clock_id is None and monotonic_seconds is None:
            clock_id, monotonic_seconds = local_clock(), time.monotonic()
        if monotonic_seconds is not None:
            event.update(clockId=clock_id, monotonicSeconds=monotonic_seconds)
        validate_event(event)
        if matching:
            previous = matching[0]
            for key in ('workerId', 'parentWorkerId', 'attemptId', 'kind', 'source', 'evidenceRef', 'metadata'):
                if event[key] != previous[key]:
                    raise ValueError('eventId already exists with different evidence')
            return previous
        stream.write(json.dumps(event, sort_keys=True, separators=(',', ':')) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    return event


def read_events(workflow, cutoff=None):
    cutoff = timestamp(cutoff)
    found = {}
    for path in sorted((Path(workflow) / 'events').glob('*.jsonl')):
        if path.is_symlink():
            raise ValueError('event file cannot be a symlink')
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            event = validate_event(json.loads(line))
            if event['workflowId'] != Path(workflow).name:
                raise ValueError('event belongs to a different workflow')
            if event['observedAt'] > cutoff:
                continue
            if event['eventId'] in found and found[event['eventId']] != event:
                raise ValueError('conflicting duplicate eventId')
            found[event['eventId']] = event
    return sorted(found.values(), key=lambda event: (event['observedAt'], event['workerId'], event['seq'], event['eventId'])), cutoff


def normalize_runner_receipt(receipt):
    """Map a pstack-run status.json object onto the request-file receipt shape."""
    if (not isinstance(receipt, dict) or receipt.get('job_id') or
            not isinstance(receipt.get('task_id'), str) or 'state' not in receipt):
        return receipt
    state = receipt.get('state')
    status = {'running': 'running', 'succeeded': 'complete', 'killed': 'cancelled',
              'timeout': 'timed-out', 'failed': 'failed', 'startup_timeout': 'failed',
              'stalled': 'failed', 'lost': 'failed', 'limited': 'failed'}.get(state)
    normalized = {'job_id': receipt['task_id']}
    if status is not None:
        normalized['status'] = status
    for key in ('provider', 'model', 'effort'):
        if receipt.get(key) is not None:
            normalized[key] = receipt[key]
    if receipt.get('duration_s') is not None:
        normalized['elapsedSeconds'] = receipt['duration_s']
    if isinstance(receipt.get('usage'), dict):
        usage = dict(receipt['usage'])
        usage.setdefault('cache_read_input_tokens', usage.get('cached_input_tokens'))
        usage.setdefault('cache_creation_input_tokens', usage.get('cache_write_input_tokens'))
        normalized['metrics'] = {'usage': usage}
    if status == 'failed':
        normalized['failureCode'] = state
    return normalized


def import_receipt(workflow, receipt, *, worker=None, parent_worker=None):
    """Import safe terminal metadata, deduplicated by durable job and status."""
    reference = None
    if not isinstance(receipt, dict):
        reference = str(Path(receipt).resolve())
        receipt = json.loads(Path(receipt).read_text())
    receipt = normalize_runner_receipt(receipt)
    job_id = receipt.get('job_id')
    if not isinstance(job_id, str) or not job_id:
        raise ValueError('receipt requires stable job_id')
    worker = worker or job_id
    status = {'starting': 'requested', 'running': 'observed-running', 'complete': 'complete',
              'failed': 'failed', 'timed-out': 'failed', 'cancelled': 'cancelled'}.get(receipt.get('status'))
    if status is None:
        raise ValueError('unsupported receipt status')
    metadata = {key: receipt[key] for key in ('provider', 'transport', 'model', 'effort', 'elapsedSeconds') if key in receipt}
    metadata.update(job_id=job_id, resolved={'model': receipt.get('reportedModel')},
                    bindingEvidence=receipt.get('modelEvidence', 'unknown'))
    metrics = receipt.get('metrics') or {}
    for origin, target in (('duration_ms', 'modelSeconds'), ('duration_api_ms', 'apiSeconds')):
        if number(metrics.get(origin)):
            metadata[target] = metrics[origin] / 1000
    if receipt.get('status') == 'timed-out':
        metadata['failureCode'] = 'timed-out'
    elif 'failureCode' in receipt:
        metadata['failureCode'] = receipt['failureCode']
    usage = metrics.get('usage')
    if isinstance(usage, dict):
        definition = metrics.get('inputTokenDefinition', receipt.get('inputTokenDefinition', 'unknown'))
        counters = {'input': usage.get('input_tokens'), 'output': usage.get('output_tokens'),
                    'cacheRead': usage.get('cache_read_input_tokens'), 'cacheWrite': usage.get('cache_creation_input_tokens')}
        metadata['usage'] = dict(counters, inputDefinition=definition, source='receipt:metrics.usage',
                                 quality='reported', sampleId=job_id, scope='attempt',
                                 raw={key: value for key, value in usage.items() if number(value)})
    digest = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    return record_event(workflow, worker, status, metadata, parent_worker=parent_worker,
                        attempt=job_id, source='runtime-receipt', evidence_ref=reference,
                        event_id='receipt:' + job_id + ':' + status + ':' + digest)


def duration(first, last):
    if not first or not last or first.get('clockId') != last.get('clockId'):
        return None
    start, end = first.get('monotonicSeconds'), last.get('monotonicSeconds')
    return end - start if number(start) and number(end) and end >= start else None


def age(cutoff, observed):
    return max(0, (dt.datetime.fromisoformat(cutoff) - dt.datetime.fromisoformat(observed)).total_seconds())


def normalize_usage(usage):
    trusted = usage.get('quality') in ('reported', 'measured') and bool(usage.get('source'))
    result = {key: usage.get(key) if trusted and number(usage.get(key)) else None
              for key in ('input', 'output', 'cacheRead', 'cacheWrite')}
    definition = usage.get('inputDefinition')
    if definition == 'excludes_cache':
        parts = [result[key] for key in ('input', 'cacheRead', 'cacheWrite')]
        result['inputTotal'] = sum(parts) if all(part is not None for part in parts) else None
    elif definition == 'includes_cache':
        result['inputTotal'] = result['input']
    else:
        result['inputTotal'] = None
    result['inputDefinition'] = definition or 'unknown'
    result['source'] = usage.get('source') or 'unknown'
    result['quality'] = usage.get('quality') or 'unknown'
    return result


def summarize(workflow, *, cutoff=None, manifest=None, stale_after=300):
    """Reduce a timestamp-scoped snapshot without estimating missing evidence."""
    events, cutoff = read_events(workflow, cutoff)
    if not number(stale_after):
        raise ValueError('stale_after must be nonnegative')
    groups, roots = {}, []
    for event in events:
        if event['kind'].startswith('workflow-') or event['metadata'].get('root') is True:
            roots.append(event)
        else:
            groups.setdefault(event['workerId'], []).append(event)
    counts = dict(spawned=len(groups), active=0, requested=0, complete=0, failed=0, cancelled=0)
    workers, usages, sample_keys, elapsed, models, tools = {}, {}, {}, [], [], []
    for worker, records in groups.items():
        records.sort(key=lambda event: event['seq'])
        attempts = {}
        for event in records:
            attempts.setdefault(event['attemptId'], []).append(event)
        states, worker_elapsed, lifecycle_coverage = [], [], []
        for attempt, items in attempts.items():
            state = 'requested'
            for event in items:
                state = STATE.get(event['kind'], state)
            states.append(state)
            terminal = next((event for event in reversed(items) if event['kind'] in TERMINAL), None)
            start = next((event for event in items if event['kind'] == 'started'), None)
            lifecycle_coverage.append(terminal is not None and start is not None and any(event['kind'] in ('registered', 'requested') for event in items))
            measured = terminal['metadata'].get('elapsedSeconds') if terminal else None
            measured = measured if number(measured) else duration(start, terminal)
            worker_elapsed.append(measured)
            for label, target in (('modelSeconds', models), ('toolSeconds', tools)):
                values = [event['metadata'][label] for event in items if label in event['metadata']]
                target.append(values[-1] if values else None)
        current = states[-1]
        counts[current] += 1
        progress = next((event for event in reversed(records) if event['kind'] in ('started', 'progress', 'phase-end') or event['kind'] in TERMINAL), None)
        open_phases, phases, identity_metadata = {}, [], {}
        for event in records:
            identity_metadata.update(event['metadata'])
            phase_key = (event['attemptId'], event['metadata'].get('phaseId', event['metadata'].get('stage', 'unknown')))
            if event['kind'] == 'phase-start':
                open_phases[phase_key] = event
            elif event['kind'] == 'phase-end':
                first = open_phases.pop(phase_key, None)
                phases.append({'stage': event['metadata'].get('stage', first['metadata'].get('stage', 'unknown') if first else 'unknown'),
                               'attempt': event['attemptId'], 'elapsedSeconds': duration(first, event)})
            usage = event['metadata'].get('usage')
            if usage:
                scope = usage.get('scope', 'attempt')
                key = (worker, scope, usage.get('sessionId') if scope == 'session' else event['attemptId'])
                if scope == 'session' and not usage.get('sessionId'):
                    raise ValueError('session usage requires sessionId')
                sample = (worker, usage.get('sampleId'))
                if sample[1] and sample in sample_keys:
                    usages.pop(sample_keys[sample], None)
                if sample[1]:
                    sample_keys[sample] = key
                usages[key] = normalize_usage(usage)
        elapsed.extend(worker_elapsed)
        workers[worker] = {'state': current, 'attempts': len(attempts), 'failedAttempts': states.count('failed'),
                           'lifecycleCoverage': all(lifecycle_coverage),
                           'lastObservationAgeSeconds': age(cutoff, records[-1]['observedAt']),
                           'lastProgressAgeSeconds': age(cutoff, progress['observedAt']) if progress else None,
                           'staleObservation': current in ('requested', 'active') and age(cutoff, records[-1]['observedAt']) > stale_after,
                           'openStages': sorted({event['metadata'].get('stage', 'unknown') for event in open_phases.values()}),
                           'phases': phases, 'metadata': identity_metadata}
        contexts = [event for event in records if event['metadata'].get('context')]
        occupancy = None
        if contexts:
            event = contexts[-1]
            context = event['metadata']['context']
            binding = next((item['metadata'].get('resolved') for item in reversed(records) if item['metadata'].get('resolved')), {})
            if (context.get('quality') in ('reported', 'measured') and context.get('source') and
                    context.get('model') and context.get('configuration') and binding.get('model') == context['model'] and
                    binding.get('configuration') == context['configuration'] and
                    number(context.get('tokens')) and number(context.get('capacity')) and context['capacity'] > 0 and
                    context['tokens'] <= context['capacity'] and number(context.get('validForSeconds')) and
                    context.get('observedAt') and timestamp(context['observedAt']) <= cutoff and
                    age(cutoff, timestamp(context['observedAt'])) <= context['validForSeconds']):
                occupancy = {'tokens': context['tokens'], 'capacity': context['capacity'], 'source': context['source']}
        workers[worker]['contextOccupancy'] = occupancy
    def total(values):
        return sum(values) if values and all(value is not None for value in values) else None
    tokens = {key: total([entry[key] for entry in usages.values()]) for key in ('input', 'inputTotal', 'output', 'cacheRead', 'cacheWrite')}
    ambiguous = any(len({key[1] for key in usages if key[0] == worker}) > 1 for worker in workers)
    if ambiguous:
        tokens.update({key: None for key in ('input', 'inputTotal', 'output', 'cacheRead', 'cacheWrite')})
    tokens['overlapUnknown'] = ambiguous
    tokens['samples'] = len(usages)
    tokens['inputDefinitions'] = sorted({entry['inputDefinition'] for entry in usages.values()})
    tokens['sources'] = sorted({entry['source'] for entry in usages.values()})
    tokens['qualities'] = sorted({entry['quality'] for entry in usages.values()})
    tokens['coverage'] = 'observed samples only'
    starts = [event for event in roots if event['kind'] == 'workflow-start']
    ends = [event for event in roots if event['kind'] == 'workflow-end']
    wall = duration(starts[0] if starts else None, ends[-1] if ends else None)
    if manifest is None:
        declared = [event['metadata'].get('manifest') for event in roots if 'manifest' in event['metadata']]
        manifest = declared[-1] if declared else None
    if manifest is not None and (not isinstance(manifest, dict) or set(manifest) - {'complete', 'workers'} or
                                 not isinstance(manifest.get('workers'), list) or not all(isinstance(item, str) for item in manifest['workers'])):
        raise ValueError('manifest requires workers and explicit complete declaration')
    complete = bool(manifest and manifest.get('complete') is True and set(manifest['workers']) == set(groups) and
                    all(worker['state'] in TERMINAL and worker['lifecycleCoverage'] for worker in workers.values()))
    return {'schemaVersion': 1, 'workflowId': Path(workflow).name, 'cutoff': cutoff,
            'scope': 'observed', 'coverage': 'complete' if complete else 'partial', 'counts': counts,
            'failedAttempts': sum(worker['failedAttempts'] for worker in workers.values()),
            'attempts': sum(worker['attempts'] for worker in workers.values()), 'workers': workers,
            'wallSeconds': wall, 'workerElapsedSeconds': total(elapsed),
            'knownWorkerElapsedSeconds': sum(value for value in elapsed if value is not None),
            'workerTimingCoverage': sum(value is not None for value in elapsed),
            'modelSeconds': total(models), 'toolSeconds': total(tools), 'tokens': tokens,
            'contextCoverage': sum(worker['contextOccupancy'] is not None for worker in workers.values()),
            'evidenceDirectory': str(Path(workflow).resolve())}


def format_summary(summary):
    def value(item, suffix=''):
        return 'unknown' if item is None else format(item, '.3f').rstrip('0').rstrip('.') + suffix
    counts, tokens = summary['counts'], summary['tokens']
    line1 = ('Agents: spawned {spawned} active {active} requested {requested} complete {complete} failed {failed} cancelled {cancelled}'
             .format(**counts) + ' | wall ' + value(summary['wallSeconds'], 's') +
             ' | worker elapsed ' + value(summary['workerElapsedSeconds'], 's') +
             ' (measured ' + value(summary.get('knownWorkerElapsedSeconds'), 's') + ' across ' + str(summary.get('workerTimingCoverage', 0)) + ' attempts)')
    occupancies = [worker['contextOccupancy'] for worker in summary['workers'].values()]
    occupancy = 'unknown'
    if occupancies and all(item is not None for item in occupancies):
        occupancy = '; '.join(worker + '=' + value(item['contextOccupancy']['tokens']) + '/' + value(item['contextOccupancy']['capacity'])
                              for worker, item in sorted(summary['workers'].items()))
    line2 = ('Tokens: input total ' + value(tokens['inputTotal']) + ' output ' + value(tokens['output']) +
             ' cache read ' + value(tokens['cacheRead']) + ' write ' + value(tokens['cacheWrite']) +
             ' [observed call volume; reported input ' + value(tokens['input']) + '; ' +
             ','.join(tokens['inputDefinitions'] or ['unknown input definition']) +
             '; source ' + ','.join(tokens['sources'] or ['unknown']) + ']' +
             ' | context occupancy ' + occupancy + ' | scope observed ' + summary['coverage'] +
             ' usage ' + str(tokens['samples']) + ' samples')
    return line1 + '\n' + line2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    record = commands.add_parser('record')
    record.add_argument('--workflow', required=True)
    record.add_argument('--worker', required=True)
    record.add_argument('--event', choices=sorted(KINDS), required=True)
    record.add_argument('--metadata', default='{}', help='JSON object or @absolute-file')
    record.add_argument('--parent-worker')
    record.add_argument('--attempt', default='1')
    record.add_argument('--source', default='coordinator')
    record.add_argument('--evidence-ref')
    record.add_argument('--observed-at')
    record.add_argument('--clock-id')
    record.add_argument('--monotonic-seconds', type=float)
    record.add_argument('--event-id')
    summary = commands.add_parser('summary')
    summary.add_argument('--workflow', required=True)
    summary.add_argument('--cutoff')
    summary.add_argument('--manifest', help='JSON file declaring the complete descendant set')
    summary.add_argument('--import-receipt', action='append', default=[])
    summary.add_argument('--json', action='store_true')
    summary.add_argument('--stale-after', type=float, default=300)
    imported = commands.add_parser('import-receipt')
    imported.add_argument('--workflow', required=True)
    imported.add_argument('--receipt', required=True)
    imported.add_argument('--worker')
    imported.add_argument('--parent-worker')
    args = parser.parse_args(argv)
    try:
        if args.command == 'record':
            raw = Path(args.metadata[1:]).read_text() if args.metadata.startswith('@') else args.metadata
            result = record_event(args.workflow, args.worker, args.event, json.loads(raw),
                                  parent_worker=args.parent_worker, attempt=args.attempt, source=args.source,
                                  evidence_ref=args.evidence_ref, observed_at=args.observed_at,
                                  clock_id=args.clock_id, monotonic_seconds=args.monotonic_seconds, event_id=args.event_id)
        elif args.command == 'import-receipt':
            result = import_receipt(args.workflow, args.receipt, worker=args.worker, parent_worker=args.parent_worker)
        else:
            for receipt in args.import_receipt:
                import_receipt(args.workflow, receipt)
            manifest = json.loads(Path(args.manifest).read_text()) if args.manifest else None
            result = summarize(args.workflow, cutoff=args.cutoff, manifest=manifest, stale_after=args.stale_after)
            if not args.json:
                print(format_summary(result))
                return 0
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, KeyError) as error:
        parser.exit(2, 'workflow metrics: ' + str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
