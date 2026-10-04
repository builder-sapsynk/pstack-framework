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

if __name__=='__main__':unittest.main()
