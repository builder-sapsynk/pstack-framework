import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('agent_parity',Path(__file__).resolve().parents[1]/'runtime/agent_parity.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class EvidenceTests(unittest.TestCase):
    def bundle(self, root):
        binding={'provider':'grok','transport':'subprocess-prompt-file','model':'grok-4.7','effort':'low','host':'fixture','harness':'unit'}
        native=[{'type':'system','subtype':'init','session_id':'x','model':'grok-4.7'},
                {'type':'assistant','session_id':'x','message':{'model':'grok-4.7','role':'assistant','content':[{'type':'tool_use','name':'read_file','input':{}}]}},
                {'type':'result','session_id':'x','subtype':'success','is_error':False,'stop_reason':'end_turn','result':'done'}]
        values={'task':'synthetic unit task','artifact':'observed example text','native':'\n'.join(map(json.dumps,native)),
                'receipt':json.dumps(dict(binding,status='complete',authVerified=True,modelVerified=True,confinement='managed-host'))}
        evidence={}
        for name,value in values.items():
            path=root/name;path.write_text(value);evidence[name]={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        check={'kind':'artifact-check','source':'independent-observation','verifier':'unit-checker','task':'example','taskDigest':evidence['task']['sha256'],
               'evidenceSha256':{name:v['sha256'] for name,v in evidence.items()},'workVerified':True,'criticalViolation':False,
               'capabilities':{'read':{'status':'verified','detail':'fixture call only','observations':['native','artifact']}}}
        path=root/'verification';path.write_text(json.dumps(check));evidence['verification']={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        return {'schemaVersion':1,'evidenceKind':'unit-fixture','runs':[{'candidate':'unit-worker','task':'example','binding':binding,'evidence':evidence}]}

    def test_fixture_cannot_establish_live_availability(self):
        with tempfile.TemporaryDirectory() as d:
            b=self.bundle(Path(d))
            with self.assertRaises(ValueError):p.summarize(b)
            result=p.summarize(b,allow_unit_fixtures=True)
            self.assertEqual(result['verdict'],'fixture-only');self.assertFalse(result['fullParity']);self.assertFalse(result['runs'][0]['available'])
            self.assertEqual(result['runs'][0]['capabilities']['read']['status'],'unknown')

    def test_mutated_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            b=self.bundle(Path(d));(Path(d)/'artifact').write_text('changed')
            with self.assertRaisesRegex(ValueError,'digest mismatch'):p.summarize(b,allow_unit_fixtures=True)

    def test_native_success_cannot_have_later_events(self):
        receipt={'model':'grok-4.7','status':'complete'}
        records=[{'type':'system','subtype':'init','model':'grok-4.7','session_id':'x'},
                 {'type':'assistant','session_id':'x','message':{'model':'grok-4.7','role':'assistant','content':[]}},
                 {'type':'result','session_id':'x','subtype':'success','is_error':False,'stop_reason':'end_turn','result':'ok'},
                 {'type':'assistant','session_id':'x','message':{'model':'grok-4.7','role':'assistant','content':[]}}]
        with self.assertRaisesRegex(ValueError,'after terminal'):p.grok_observation(records,receipt)

class RunnerReceiptTests(unittest.TestCase):
    EVENTS = {'grok': [{'type': 'tool_call', 'toolCallId': 'c1', 'toolName': 'read_file'}, {'type': 'tool_call_update', 'toolCallId': 'c1', 'status': 'completed'},
                       {'type': 'end', 'stopReason': 'end_turn', 'modelUsage': {'grok-4.7-build': {}}}],
              'claude': [{'type': 'assistant', 'message': {'model': 'claude-sonnet-5-5', 'content': [{'type': 'tool_use', 'id': 'u1', 'name': 'Read'}]}},
                         {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'u1'}]}}],
              'codex': [{'type': 'item.completed', 'item': {'type': 'command_execution', 'status': 'completed', 'exit_code': 0}}]}
    MODELS = {'grok': 'grok-4.7', 'claude': 'claude-sonnet-5-5', 'codex': 'gpt-6.1-sol'}

    def bundle(self, root, provider, state='succeeded', events=None, argv=None):
        model = self.MODELS[provider]
        status = {'task_id': 't', 'provider': provider, 'state': state, 'model': model, 'effort': 'low',
                  'argv': argv if argv is not None else ['codex', 'exec', '-m', model]}
        values = {'task': 'fix add', 'artifact': 'patch', 'receipt': json.dumps(status),
                  'native': '\n'.join(map(json.dumps, self.EVENTS[provider] if events is None else events))}
        evidence = {}
        for name, value in values.items():
            path = root / name; path.write_text(value)
            evidence[name] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        check = {'kind': 'artifact-check', 'source': 'independent-observation', 'verifier': 'coordinator', 'task': 'example',
                 'taskDigest': evidence['task']['sha256'], 'evidenceSha256': {name: v['sha256'] for name, v in evidence.items()},
                 'workVerified': state == 'succeeded', 'criticalViolation': False,
                 'capabilities': {'read': {'status': 'verified', 'detail': 'read the fixture', 'observations': ['native', 'artifact']}}}
        path = root / 'verification'; path.write_text(json.dumps(check))
        evidence['verification'] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        binding = {'provider': provider, 'transport': 'pstack-run', 'model': model, 'effort': 'low', 'host': 'h', 'harness': 'claude-code'}
        return {'schemaVersion': 1, 'evidenceKind': 'captured', 'runs': [{'candidate': 'w', 'task': 'example', 'binding': binding, 'evidence': evidence}]}

    def test_runner_status_counts_as_a_terminal_receipt_for_each_provider(self):
        for provider in self.EVENTS:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as directory:
                run = p.summarize(self.bundle(Path(directory), provider))['runs'][0]
                self.assertEqual((run['terminalStatus'], run['available'], run['capabilities']['read']['status']), ('complete', True, 'verified'))

    def test_runner_receipt_needs_served_model_and_real_tool_evidence(self):
        for provider, events, argv, message in (
            ('grok', self.EVENTS['grok'][:2] + [{'type': 'end', 'modelUsage': {'other-model': {}}}], None, 'model-verified'),
            ('grok', self.EVENTS['grok'][:2] + [{'type': 'end', 'modelUsage': {'grok-4.70': {}}}], None, 'model-verified'),
            ('grok', [self.EVENTS['grok'][0], {'type': 'tool_call_update', 'toolCallId': 'c1', 'status': 'failed'}, self.EVENTS['grok'][2]], None, 'genuine native tool use'),
            ('grok', self.EVENTS['grok'] + [{'type': 'pstack.started'}, {'type': 'end', 'modelUsage': {'other-model': {}}}], None, 'model-verified'),
            ('claude', [{'type': 'assistant', 'message': {'model': 'claude-sonnet-5-5', 'content': []}}], None, 'genuine native tool use'),
            ('claude', [self.EVENTS['claude'][0], {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'u1', 'is_error': True}]}}], None, 'genuine native tool use'),
            ('codex', [{'type': 'item.completed', 'item': {'type': 'command_execution', 'status': 'failed', 'exit_code': 1}}], None, 'genuine native tool use'),
            ('codex', None, ['codex', 'exec'], 'model-verified'),
        ):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, message):
                    p.summarize(self.bundle(Path(directory), provider, events=events, argv=argv))

    def test_killed_runner_receipt_is_cancelled_and_never_available(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.bundle(Path(directory), 'grok', state='killed')
            check = Path(bundle['runs'][0]['evidence']['verification']['path'])
            data = json.loads(check.read_text()); data['capabilities'] = {}; check.write_text(json.dumps(data))
            bundle['runs'][0]['evidence']['verification']['sha256'] = hashlib.sha256(check.read_bytes()).hexdigest()
            run = p.summarize(bundle)['runs'][0]
            self.assertEqual((run['terminalStatus'], run['available']), ('cancelled', False))

    def test_limited_runner_receipt_is_its_own_status_and_never_available(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.bundle(Path(directory), 'claude', state='limited')
            check = Path(bundle['runs'][0]['evidence']['verification']['path'])
            data = json.loads(check.read_text()); data['capabilities'] = {}; check.write_text(json.dumps(data))
            bundle['runs'][0]['evidence']['verification']['sha256'] = hashlib.sha256(check.read_bytes()).hexdigest()
            run = p.summarize(bundle)['runs'][0]
            self.assertEqual((run['terminalStatus'], run['available']), ('limited', False))


if __name__=='__main__':unittest.main()
