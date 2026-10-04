import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'runtime/workflow_metrics.py'
spec = importlib.util.spec_from_file_location('workflow_metrics', SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class WorkflowMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workflow = Path(self.tmp.name) / 'unit-workflow'
        self.time = 0

    def tearDown(self):
        self.tmp.cleanup()

    def event(self, worker, kind, metadata=None, **kwargs):
        self.time += 1
        return m.record_event(self.workflow, worker, kind, metadata,
                              observed_at='2026-10-04T00:00:' + format(self.time, '02d') + 'Z',
                              clock_id=kwargs.pop('clock_id', 'fixture-clock'),
                              monotonic_seconds=kwargs.pop('monotonic_seconds', self.time), **kwargs)

    def summary(self, **kwargs):
        return m.summarize(self.workflow, cutoff='2026-10-04T00:01:00Z', **kwargs)

    def usage(self, definition='unknown', **kwargs):
        result = dict(input=100, output=20, cacheRead=40, cacheWrite=10,
                      inputDefinition=definition, source='unit counters', quality='reported',
                      sampleId='sample-one', scope='attempt')
        result.update(kwargs)
        return result

    def test_native_usage_unknown_is_not_zero(self):
        self.event('native-child', 'requested', {'nativeAgentId': 'actual-id', 'role': 'implementation', 'fork_turns': 'none'})
        self.event('native-child', 'started')
        self.event('native-child', 'complete')
        summary = self.summary()
        self.assertEqual(summary['counts'], dict(spawned=1, active=0, requested=0, complete=1, failed=0, cancelled=0))
        self.assertIsNone(summary['tokens']['inputTotal'])
        self.assertIsNone(summary['tokens']['output'])
        self.assertIsNone(summary['workers']['native-child']['contextOccupancy'])
        self.assertEqual(summary['workers']['native-child']['metadata']['nativeAgentId'], 'actual-id')
        self.assertEqual(summary['coverage'], 'partial')
        lines = m.format_summary(summary).splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith('Agents: spawned 1'))
        self.assertIn('input total unknown output unknown', lines[1])
        self.assertIn('context occupancy unknown', lines[1])

    def test_cache_counter_definitions(self):
        expected = {'unknown': None, 'includes_cache': 100, 'excludes_cache': 150}
        for worker, definition in enumerate(expected):
            with self.subTest(definition=definition):
                normalized = m.normalize_usage(self.usage(definition))
                self.assertEqual(normalized['inputTotal'], expected[definition])
                self.assertEqual(normalized['cacheRead'], 40)
        self.assertIsNone(m.normalize_usage(self.usage('excludes_cache', cacheWrite=None))['inputTotal'])
        self.assertIsNone(m.normalize_usage(self.usage('includes_cache', quality='estimated'))['inputTotal'])

    def test_cumulative_usage_and_duplicate_sample_not_added(self):
        self.event('worker', 'started', {'usage': self.usage('includes_cache', input=50)})
        self.event('worker', 'usage', {'usage': self.usage('includes_cache')})
        self.event('worker', 'usage', {'usage': self.usage('includes_cache', scope='session', sessionId='session-one')})
        summary = self.summary()
        self.assertEqual(summary['tokens']['inputTotal'], 100)
        self.assertEqual(summary['tokens']['output'], 20)
        self.assertEqual(summary['tokens']['samples'], 1)

    def test_overlapping_aggregate_scopes_are_unknown(self):
        self.event('worker', 'usage', {'usage': self.usage('includes_cache', sampleId='attempt')})
        self.event('worker', 'usage', {'usage': self.usage('includes_cache', sampleId='session', scope='session', sessionId='s')})
        summary = self.summary()
        self.assertTrue(summary['tokens']['overlapUnknown'])
        self.assertIsNone(summary['tokens']['inputTotal'])
        self.assertIsNone(summary['tokens']['output'])

    def test_receipt_import_idempotent_and_no_modelusage_double_count(self):
        receipt = dict(job_id='durable-job', status='complete', provider='grok', model='grok-4.7',
                       reportedModel='grok-4.7', elapsedSeconds=4.717,
                       metrics={'usage': {'input_tokens': 100, 'output_tokens': 20, 'cache_read_input_tokens': 40,
                                          'cache_creation_input_tokens': 10},
                                'modelUsage': {'billing-label': {'inputTokens': 100, 'outputTokens': 20}},
                                'duration_ms': 3208, 'duration_api_ms': 3159})
        first = m.import_receipt(self.workflow, receipt)
        second = m.import_receipt(self.workflow, receipt)
        self.assertEqual(first, second)
        summary = m.summarize(self.workflow)
        self.assertEqual(summary['counts']['spawned'], 1)
        self.assertEqual(summary['attempts'], 1)
        self.assertEqual(summary['workerElapsedSeconds'], 4.717)
        self.assertEqual(summary['modelSeconds'], 3.208)
        self.assertEqual(summary['tokens']['samples'], 1)
        self.assertIsNone(summary['tokens']['inputTotal'])
        self.assertEqual(summary['tokens']['output'], 20)
        self.assertEqual(summary['tokens']['cacheRead'], 40)
        self.assertEqual(summary['tokens']['cacheWrite'], 10)
        self.assertEqual(summary['coverage'], 'partial')

    def test_failures_cancellation_and_attempts(self):
        self.event('retry', 'requested', attempt='first')
        self.event('retry', 'started', attempt='first')
        self.event('retry', 'failed', {'failureCode': 'preflight'}, attempt='first')
        self.event('retry', 'requested', attempt='second')
        self.event('retry', 'started', attempt='second')
        self.event('retry', 'complete', attempt='second')
        self.event('broken', 'requested')
        self.event('broken', 'failed')
        self.event('cancel-request-only', 'started')
        self.event('cancel-request-only', 'cancellation-requested')
        self.event('cancelled', 'requested')
        self.event('cancelled', 'started')
        self.event('cancelled', 'cancelled')
        summary = self.summary()
        self.assertEqual(summary['counts'], dict(spawned=4, active=1, requested=0, complete=1, failed=1, cancelled=1))
        self.assertEqual(summary['attempts'], 5)
        self.assertEqual(summary['failedAttempts'], 2)

    def test_overlap_wall_and_worker_elapsed_are_distinct(self):
        self.event('coordinator', 'workflow-start', monotonic_seconds=0)
        self.event('first', 'requested')
        self.event('first', 'started', monotonic_seconds=0)
        self.event('second', 'requested')
        self.event('second', 'started', monotonic_seconds=0)
        self.event('first', 'complete', monotonic_seconds=10)
        self.event('second', 'complete', monotonic_seconds=10)
        self.event('coordinator', 'workflow-end', monotonic_seconds=10)
        summary = self.summary(manifest={'complete': True, 'workers': ['first', 'second']})
        self.assertEqual(summary['wallSeconds'], 10)
        self.assertEqual(summary['workerElapsedSeconds'], 20)
        self.assertEqual(summary['coverage'], 'complete')
        self.assertEqual(summary['counts']['spawned'], 2)
        self.assertNotIn('cpu', json.dumps(summary).lower())
        self.assertNotIn('utilization', json.dumps(summary).lower())

    def test_mixed_clocks_do_not_imply_elapsed(self):
        self.event('coordinator', 'workflow-start', monotonic_seconds=1, clock_id='machine-a')
        self.event('worker', 'requested')
        self.event('worker', 'started', monotonic_seconds=2, clock_id='machine-a')
        self.event('worker', 'complete', monotonic_seconds=100, clock_id='machine-b')
        self.event('coordinator', 'workflow-end', monotonic_seconds=101, clock_id='machine-b')
        summary = self.summary()
        self.assertIsNone(summary['wallSeconds'])
        self.assertIsNone(summary['workerElapsedSeconds'])

    def test_manifest_cannot_hide_missing_descendants_or_lifecycles(self):
        self.event('known', 'complete', {'elapsedSeconds': 1})
        summary = self.summary(manifest={'complete': True, 'workers': ['known']})
        self.assertEqual(summary['coverage'], 'partial')
        self.event('missing-descendant', 'requested', parent_worker='known')
        self.assertEqual(self.summary(manifest={'complete': True, 'workers': ['known']})['coverage'], 'partial')

    def test_context_requires_contemporary_served_binding_and_capacity(self):
        context = dict(tokens=2000, capacity=256000, model='grok-4.7', configuration='default256k',
                       observedAt='2026-10-04T00:00:05Z', validForSeconds=60,
                       quality='reported', source='unit current context measurement')
        self.event('worker', 'registered', {'resolved': {'model': 'grok-4.7', 'configuration': 'default256k'}})
        self.event('worker', 'context', {'context': context})
        summary = self.summary()
        self.assertEqual(summary['workers']['worker']['contextOccupancy']['capacity'], 256000)
        expired = m.summarize(self.workflow, cutoff='2026-10-04T00:03:00Z')
        self.assertIsNone(expired['workers']['worker']['contextOccupancy'])
        self.event('other-configuration', 'registered', {'resolved': {'model': 'grok-4.7', 'configuration': 'optional500k'}})
        self.event('other-configuration', 'context', {'context': context})
        self.assertIsNone(self.summary()['workers']['other-configuration']['contextOccupancy'])
        self.assertIn('context occupancy unknown', m.format_summary(self.summary()))

    def test_stage_progress_age_is_not_idle_time(self):
        self.event('worker', 'requested')
        self.event('worker', 'started')
        self.event('worker', 'phase-start', {'stage': 'preflight'}, monotonic_seconds=2)
        self.event('worker', 'phase-end', {'stage': 'preflight'}, monotonic_seconds=4)
        self.event('worker', 'phase-start', {'stage': 'provider-request'}, monotonic_seconds=4)
        self.event('worker', 'observed-running')
        summary = self.summary(stale_after=10)
        worker = summary['workers']['worker']
        self.assertEqual(worker['phases'], [{'stage': 'preflight', 'attempt': '1', 'elapsedSeconds': 2}])
        self.assertEqual(worker['openStages'], ['provider-request'])
        self.assertEqual(worker['lastProgressAgeSeconds'], 56)
        self.assertEqual(worker['lastObservationAgeSeconds'], 54)
        self.assertTrue(worker['staleObservation'])
        self.assertIsNone(summary['toolSeconds'])

    def test_duplicate_identity_conflicts_and_cutoff_replay(self):
        event = self.event('worker', 'requested', event_id='dedup-id')
        duplicated = self.event('worker', 'requested', event_id='dedup-id')
        self.assertEqual(event, duplicated)
        with self.assertRaisesRegex(ValueError, 'different evidence'):
            self.event('worker', 'failed', event_id='dedup-id')
        self.event('worker', 'started')
        old = m.summarize(self.workflow, cutoff='2026-10-04T00:00:01Z')
        self.assertEqual(old['counts']['requested'], 1)
        self.assertEqual(old['counts']['active'], 0)
        self.assertEqual(self.summary()['counts']['active'], 1)

    def test_private_files_persist_and_sensitive_metadata_is_rejected(self):
        self.event('worker/unsafe-filename', 'requested', {'briefBytes': 100})
        self.assertEqual(os.stat(self.workflow).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(self.workflow / 'events').st_mode & 0o777, 0o700)
        files = list((self.workflow / 'events').glob('*.jsonl'))
        self.assertEqual(len(files), 1)
        self.assertEqual(os.stat(files[0]).st_mode & 0o777, 0o600)
        self.summary()
        self.assertTrue(files[0].read_text())
        with self.assertRaisesRegex(ValueError, 'unsupported metadata'):
            self.event('worker', 'requested', {'prompt': 'private prompt'})
        with self.assertRaisesRegex(ValueError, 'binding fields'):
            self.event('worker', 'requested', {'requested': {'credential': 'private'}})

    def test_cli_produces_two_line_snapshot_and_json_evidence(self):
        arguments = [sys.executable, str(SOURCE), 'record', '--workflow', str(self.workflow), '--worker', 'actual-cli-worker',
                     '--event', 'requested', '--metadata', '{"role":"unit-proof","fork_turns":"none"}']
        recorded = subprocess.run(arguments, capture_output=True, text=True, check=True)
        event = json.loads(recorded.stdout)
        self.assertEqual(event['workerId'], 'actual-cli-worker')
        result = subprocess.run([sys.executable, str(SOURCE), 'summary', '--workflow', str(self.workflow)],
                                capture_output=True, text=True, check=True)
        self.assertEqual(len(result.stdout.splitlines()), 2)
        self.assertIn('spawned 1 active 0 requested 1', result.stdout)
        self.assertIn('scope observed partial', result.stdout)
        self.assertTrue(list((self.workflow / 'events').glob('*.jsonl')))


if __name__ == '__main__':
    unittest.main()
