import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('grok_native', Path(__file__).resolve().parents[1] / 'runtime/grok_native.py')
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)

class NativeBoundaryTests(unittest.TestCase):
    def request(self, cwd='/workspace'):
        return {'mode':'isolated-write','model':'grok-4.7','cwd':cwd,'allowed_commands':['python3 check.py']}

    def test_command_grants_reject_shell_expressions(self):
        for command in ('python3 check.py; touch /tmp/x', 'echo $(id)', 'git *', 'echo x | sh'):
            req=self.request();req['allowed_commands']=[command]
            with self.assertRaises(ValueError):g.argv(req)
        args=g.argv(self.request());self.assertIn('Bash(python3 check.py)',args)

    def test_absent_boundary_refuses_tools(self):
        with tempfile.TemporaryDirectory() as root:
            declaration={'host':'codex-managed-exec','writable_roots':['/workspace'],'read_only_probe':root}
            with self.assertRaisesRegex(ValueError,'boundary absent'):g.probe_boundary(declaration)
            self.assertEqual(list(Path(root).iterdir()),[])

    def test_unknown_host_and_outside_cwd_rejected(self):
        declaration={'host':'unsupported','writable_roots':['/workspace'],'read_only_probe':'/'}
        with self.assertRaises(ValueError):g.validate_boundary(declaration,'/workspace')
        declaration['host']='codex-managed-exec'
        with self.assertRaises(ValueError):g.validate_boundary(declaration,'/etc')

    def stream(self):
        init={'type':'system','subtype':'init','session_id':'abc','model':'grok-4.7','tools':sorted(g.tools(self.request())),'mcp_servers':[]}
        assistant={'type':'assistant','session_id':'abc','message':{'model':'grok-4.7','role':'assistant','stop_reason':'tool_use','content':[{'type':'tool_use','id':'a','name':'run_terminal_command','input':{'command':'python3 check.py'}}]}}
        user={'type':'user','session_id':'abc','message':{'role':'user','content':[{'type':'tool_result','tool_use_id':'a','is_error':False,'content':json.dumps({'exit_code':0})}]}}
        final={'type':'assistant','session_id':'abc','message':{'model':'grok-4.7','role':'assistant','stop_reason':'end_turn','content':[{'type':'text','text':'passed'}]}}
        result={'type':'result','session_id':'abc','subtype':'success','result':'passed'}
        return [init,assistant,user,final,result]

    def test_matched_native_execution_and_inventory(self):
        stream=self.stream();output,metrics=g.normalize('\n'.join(map(json.dumps,stream)),self.request())
        self.assertEqual(metrics['toolOutcomes'][0]['result']['exit_code'],0)
        self.assertEqual(json.loads(output.splitlines()[0])['tools'],[])
        stream[0]['tools'].append('image_gen')
        with self.assertRaises(ValueError):g.normalize('\n'.join(map(json.dumps,stream)),self.request())

    def test_failed_unmatched_or_ungranted_execution(self):
        for mutation in ('error','id','command','session'):
            stream=self.stream()
            if mutation=='error':stream[2]['message']['content'][0]['is_error']=True
            if mutation=='id':stream[2]['message']['content'][0]['tool_use_id']='other'
            if mutation=='command':stream[1]['message']['content'][0]['input']['command']='rm -rf /workspace'
            if mutation=='session':stream[2]['session_id']='other'
            with self.assertRaises(ValueError):g.normalize('\n'.join(map(json.dumps,stream)),self.request())

    def test_no_events_allowed_after_terminal(self):
        stream=self.stream()
        stream += [stream[1],stream[2]]
        with self.assertRaisesRegex(ValueError,'after terminal'):
            g.normalize('\n'.join(map(json.dumps,stream)),self.request())

    def test_resume_chain_keeps_validated_original_home(self):
        with tempfile.TemporaryDirectory() as folder:
            project=Path(folder);base=project/'.pstack/runs';base.mkdir(parents=True)
            first=base/'first';first.mkdir();home=first/'grok-home';home.mkdir()
            following=base/'following';following.mkdir()
            binding={'provider':'grok','model':'grok-4.7','mode':'read-only','cwd':str(project)}
            receipt=dict(binding,status='complete',request={'dialect':g.DIALECT},grokHome=str(home),metrics={'session_id':'11111111-1111-4111-8111-111111111111'})
            (first/'receipt.json').write_text(json.dumps(receipt));(following/'receipt.json').write_text(json.dumps(receipt))
            result=g.prepare_home(base/'third',dict(binding,project=str(project),resume_job=str(following)),{})
            self.assertEqual(result,(str(home),'11111111-1111-4111-8111-111111111111'))
            receipt['model']='other';(first/'receipt.json').write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError,'owner mismatch'):
                g.prepare_home(base/'third',dict(binding,project=str(project),resume_job=str(following)),{})

if __name__=='__main__':unittest.main()
