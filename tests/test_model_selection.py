import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('model_selection', ROOT / 'runtime/model_selection.py')
selection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selection)


class ModelSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.serial = 0

    def tearDown(self):
        self.temp.cleanup()

    def save(self, name, value):
        path = self.base / name
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
        return path.name, hashlib.sha256(path.read_bytes()).hexdigest()

    def run_record(self, candidate='A', repeat=1, task='toy', elapsed=10, cost=.1,
                   quality=None, success=True, critical=False, verified=None):
        self.serial += 1
        stem = str(self.serial)
        quality = quality or {'correctness': 45, 'scope': 20, 'verification': 20, 'completeness': 15}
        verified = success if verified is None else verified
        if not verified:
            quality = dict.fromkeys(selection.RUBRIC, 0)
        run = {'candidate': candidate, 'model': 'unit-' + candidate, 'provider': 'fixture',
               'transport': 'fixture', 'effort': 'medium', 'host': 'unit', 'harness': 'unittest',
               'task': task, 'taskDigest': hashlib.sha256(task.encode()).hexdigest(),
               'repeat': repeat, 'success': success, 'workVerified': verified,
               'criteriaScores': quality, 'elapsedSeconds': elapsed, 'criticalViolation': critical}
        receipt = {key: run[key] for key in ('model', 'provider', 'effort', 'transport', 'elapsedSeconds')}
        receipt.update(job_id='unit-' + stem, status='complete' if success else 'failed', authVerified=success, modelVerified=success)
        evidence = {}
        for name, value in [('receipt', receipt), ('artifact', b'fabricated unit-test artifact' if success else b'')]:
            path, sha = self.save(stem + '-' + name + ('.json' if name == 'receipt' else '.txt'), value)
            evidence[name + 'Path'], evidence[name + 'Sha256'] = path, sha
        check = {key: run[key] for key in ('taskDigest', 'criteriaScores', 'criticalViolation', 'workVerified')}
        check.update(kind='artifact-check', source='independent-observation', verifier='unit-checker',
                     receiptSha256=evidence['receiptSha256'], artifactSha256=evidence['artifactSha256'])
        if cost is not None:
            run['nativeCostUSD'] = cost
            check.update(nativeCostUSD=cost, costSource='native-measured')
        path, sha = self.save(stem + '-check.json', check)
        evidence.update(verificationPath=path, verificationSha256=sha)
        run['evidence'] = evidence
        return run

    def document(self, runs, **policy):
        return {'schemaVersion': 1, 'evidenceKind': 'unit-fixture',
                'policy': {'incumbent': 'A', 'checklist': {key: 'unit fixture only' for key in selection.CHECKLIST}, **policy},
                'runs': runs}

    def evaluate(self, document, mode='selection'):
        return selection.summarize(document, self.base, mode, allow_unit_fixtures=True)

    def captured_simulation(self, document):
        document = copy.deepcopy(document)
        document['evidenceKind'] = 'captured'
        return document

    def test_smoke_cannot_pick_fast_single_run(self):
        report = self.evaluate(self.document([self.run_record(elapsed=1)]), 'smoke')
        self.assertEqual(report['verdict'], 'fixture-only')
        self.assertIsNone(report['selected'])
        self.assertTrue(report['preserveIncumbent'])
        self.assertEqual(report['availability'], {'A': False})
        self.assertEqual(report['candidates']['A']['quality']['median'], 100)

    def test_unit_fixtures_are_rejected_by_default_and_never_win(self):
        doc = self.document([self.run_record()])
        with self.assertRaisesRegex(ValueError, 'fabricated'):
            selection.summarize(doc, self.base)
        self.assertEqual(self.evaluate(doc)['verdict'], 'inconclusive')
        doc['evidenceKind'] = 'fabricated'
        with self.assertRaises(ValueError):
            self.evaluate(doc)

    def test_unknown_cost_blocks_even_with_full_fair_repeats(self):
        runs = [self.run_record(candidate, repeat, elapsed=elapsed, cost=None)
                for repeat in range(1, 6) for candidate, elapsed in [('A', 10), ('B', 2)]]
        report = self.evaluate(self.captured_simulation(self.document(runs)))
        self.assertEqual(report['verdict'], 'inconclusive')
        self.assertIsNone(report['selected'])
        self.assertTrue(any('cost is unknown' in reason for reason in report['reasons']))

    def test_fair_repeated_known_cost_observations_can_select(self):
        runs = [self.run_record(candidate, repeat, elapsed=elapsed, cost=cost)
                for repeat in range(1, 6) for candidate, elapsed, cost in [('A', 10, .2), ('B', 2, .1)]]
        report = self.evaluate(self.captured_simulation(self.document(runs)))
        self.assertEqual(report['selected'], 'B')
        self.assertEqual(report['verdict'], 'selected')
        self.assertEqual(report['candidates']['A']['elapsedSeconds']['range'], [10, 10])
        self.assertGreater(report['utilityGap'], 0)

    def test_failures_count_in_quality_denominator(self):
        runs = [self.run_record('A', repeat, success=repeat != 1) for repeat in range(1, 6)]
        report = self.evaluate(self.document(runs))
        result = report['candidates']['A']
        self.assertEqual(result['quality']['mean'], 80)
        self.assertEqual(result['quality']['range'], [0, 100])
        self.assertEqual(result['failures'], 1)
        self.assertEqual(result['terminalFailures'], 1)
        self.assertEqual(result['outcomeFailures'], 1)
        self.assertFalse(result['eligible'])

    def test_every_task_and_critical_violation_gate(self):
        low = {'correctness': 40, 'scope': 10, 'verification': 10, 'completeness': 10}
        doc = self.document([self.run_record(task='easy'), self.run_record(task='hard', quality=low)])
        self.assertFalse(self.evaluate(doc)['candidates']['A']['eligible'])
        doc = self.document([self.run_record(critical=True)])
        self.assertFalse(self.evaluate(doc)['candidates']['A']['eligible'])
        self.assertEqual(self.evaluate(doc)['candidates']['A']['criticalViolations'], 1)

    def test_successful_terminal_with_unverified_artifact_is_an_outcome_failure(self):
        doc = self.document([self.run_record(verified=False)])
        report = self.evaluate(self.captured_simulation(doc), 'smoke')
        result = report['candidates']['A']
        self.assertEqual(result['terminalFailures'], 0)
        self.assertEqual(result['verificationFailures'], 1)
        self.assertEqual(result['outcomeFailures'], 1)
        self.assertEqual(result['quality']['mean'], 0)
        self.assertFalse(report['availability']['A'])

    def test_serial_or_missing_repeat_measurements_are_inconclusive(self):
        for runs in ([self.run_record(c, r) for c in ('A', 'B') for r in range(1, 6)],
                     [self.run_record(c, r) for r in range(1, 5) for c in ('A', 'B')]):
            report = self.evaluate(self.captured_simulation(self.document(runs)))
            self.assertEqual(report['verdict'], 'inconclusive')
            self.assertTrue(any('interleaved' in reason or 'five equal' in reason for reason in report['reasons']))

    def test_variation_and_missing_limiter_block_winner(self):
        runs = [self.run_record(candidate, repeat, elapsed=elapsed)
                for repeat in range(1, 6) for candidate, elapsed in [('A', [5, 10, 15, 10, 10][repeat-1]), ('B', 9)]]
        doc = self.captured_simulation(self.document(runs))
        report = self.evaluate(doc)
        self.assertEqual(report['verdict'], 'inconclusive')
        self.assertTrue(any('variation' in reason for reason in report['reasons']))
        del doc['policy']['checklist']['limiter']
        self.assertTrue(any('limiter' in reason for reason in self.evaluate(doc)['reasons']))

    def test_tampering_self_report_and_reused_receipt_rejected(self):
        run = self.run_record()
        self.base.joinpath(run['evidence']['artifactPath']).write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            self.evaluate(self.document([run]))
        run = self.run_record()
        check = selection.read_json(self.base / run['evidence']['verificationPath'])
        check['source'] = 'worker-self-report'
        _, sha = self.save(run['evidence']['verificationPath'], check)
        run['evidence']['verificationSha256'] = sha
        with self.assertRaisesRegex(ValueError, 'self-report'):
            self.evaluate(self.document([run]))
        run = self.run_record()
        duplicate = copy.deepcopy(run)
        duplicate['repeat'] = 2
        with self.assertRaisesRegex(ValueError, 'reused receipt'):
            self.evaluate(self.document([run, duplicate]))
        original_path = self.base / run['evidence']['receiptPath']
        copied_path = self.base / 'copied-receipt.json'
        copied_path.write_bytes(original_path.read_bytes())
        duplicate['evidence']['receiptPath'] = copied_path.name
        with self.assertRaisesRegex(ValueError, 'reused receipt'):
            self.evaluate(self.document([run, duplicate]))

    def test_malformed_numeric_and_missing_fields_rejected(self):
        for key, value in [('elapsedSeconds', float('nan')), ('elapsedSeconds', -1),
                           ('elapsedSeconds', True), ('nativeCostUSD', -1), ('repeat', True)]:
            run = self.run_record()
            run[key] = value
            with self.assertRaises(ValueError, msg=key):
                self.evaluate(self.document([run]))
        for key, value in [('correctness', 46), ('scope', float('inf')), ('verification', True)]:
            run = self.run_record()
            run['criteriaScores'][key] = value
            with self.assertRaises(ValueError, msg=key):
                self.evaluate(self.document([run]))
        run = self.run_record()
        del run['workVerified']
        with self.assertRaises(ValueError):
            self.evaluate(self.document([run]))

    def test_cli_rejects_nonfinite_and_duplicate_json(self):
        for source in ('{"schemaVersion":NaN}', '{"schemaVersion":1,"schemaVersion":1}'):
            path = self.base / 'invalid.json'
            path.write_text(source)
            process = subprocess.run([sys.executable, str(ROOT / 'runtime/model_selection.py'), '--input', str(path)], capture_output=True, text=True)
            self.assertEqual(process.returncode, 2)
            self.assertIn('invalid evidence:', process.stderr)

    def test_declared_weights_and_estimates_do_not_replace_measured_cost(self):
        runs = [self.run_record(c, r, cost=None) for r in range(1, 6) for c in ('A', 'B')]
        for run in runs:
            run['estimatedCostUSD'] = 0
        doc = self.captured_simulation(self.document(runs))
        self.assertEqual(self.evaluate(doc)['verdict'], 'inconclusive')
        doc['policy']['weights'] = {'quality': .5, 'latency': 0, 'cost': 0}
        with self.assertRaisesRegex(ValueError, 'sum to one'):
            self.evaluate(doc)

    def test_explicit_zero_cost_and_latency_weights_allow_quality_only_selection(self):
        weaker = {'correctness': 40, 'scope': 20, 'verification': 20, 'completeness': 10}
        runs = [self.run_record(candidate, repeat, cost=None, quality=weaker if candidate == 'A' else None)
                for repeat in range(1, 6) for candidate in ('A', 'B')]
        doc = self.captured_simulation(self.document(runs, weights={'quality': 1, 'latency': 0, 'cost': 0}))
        report = self.evaluate(doc)
        self.assertEqual(report['selected'], 'B')
        self.assertEqual(report['candidates']['B']['utility'], 1)


if __name__ == '__main__':
    unittest.main()
