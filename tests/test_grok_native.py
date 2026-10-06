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

class TaskProfileTests(unittest.TestCase):
    def request(self, mode='isolated-write', cwd='/workspace/proj'):
        return {'dialect':g.TASK_DIALECT,'mode':mode,'model':'grok-4.7','cwd':cwd,
                'capability_scope':g.capability_scope(mode),
                'host_boundary':{'host':'codex-managed-exec','writable_roots':['/workspace','/tmp'],'read_only_probe':'/'}}

    def test_scope_and_argv_keep_enforcement_honest(self):
        req=self.request()
        with self.assertRaisesRegex(ValueError,'explicit capability scope'):g.validate_task(dict(req,capability_scope={'terminal':'autonomous'}))
        with self.assertRaisesRegex(ValueError,'exact command grants'):g.validate_task(dict(req,allowed_commands=['git status']))
        args=g.task_argv(req)
        self.assertNotIn('--tools',args);self.assertNotIn('--disable-web-search',args);self.assertIn('--no-subagents',args)
        self.assertNotIn('--yolo',args);self.assertNotIn('--always-approve',args)
        self.assertIn('*',args)
        self.assertEqual(args[args.index('--disallowed-tools')+1], 'spawn_subagent')
        self.assertEqual(req['capability_scope']['child_agents'], 'coordinator-only')
        removed=g.task_argv(self.request('read-only'))
        removed=removed[removed.index('--disallowed-tools')+1].split(',')
        self.assertEqual(removed, ['spawn_subagent', 'search_replace', 'write', 'write_file'])
        self.assertNotIn('bypassPermissions',' '.join(args))

    def stream(self, tools=None, command='git push origin HEAD && git merge main', read_path='../canonical/AGENTS.md', write_path='a.py'):
        tools=tools or ['grep','image_gen','list_dir','memory_search','read_file','run_terminal_command','search_replace','todo_write','web_fetch','web_search','write_file']
        return [
            {'type':'system','subtype':'init','session_id':'abc','model':'grok-4.7','tools':tools,'mcp_servers':[]},
            {'type':'assistant','session_id':'abc','message':{'model':'grok-4.7','role':'assistant','stop_reason':'tool_use','content':[
                {'type':'tool_use','id':'t','name':'run_terminal_command','input':{'command':command}},
                {'type':'tool_use','id':'r','name':'read_file','input':{'path':read_path}},
                {'type':'tool_use','id':'w','name':'search_replace','input':{'file_path':write_path,'old_string':'a','new_string':'b'}},
            ]}},
            {'type':'user','session_id':'abc','message':{'role':'user','content':[
                {'type':'tool_result','tool_use_id':'t','is_error':False,'content':'pushed'},
                {'type':'tool_result','tool_use_id':'r','is_error':True,'content':'missing'},
                {'type':'tool_result','tool_use_id':'w','is_error':False,'content':['edited']},
            ]}},
            {'type':'assistant','session_id':'abc','message':{'model':'grok-4.7','role':'assistant','stop_reason':'end_turn','content':[
                {'type':'server_tool_use','id':'s','name':'web_search','input':{'query':'docs'}},
                {'type':'web_search_tool_result','tool_use_id':'s','content':[{'type':'web_search_result','url':'https://docs.x.ai','title':'Docs'}]},
                {'type':'text','text':'done'},
            ]}},
            {'type':'result','session_id':'abc','subtype':'success','is_error':False,'stop_reason':'end_turn','result':'done'},
        ]

    def test_discovered_inventory_canonical_reads_and_recoverable_results(self):
        output,metrics=g.normalize('\n'.join(map(json.dumps,self.stream())),self.request())
        self.assertEqual(metrics['toolCalls'][0]['input']['command'],'git push origin HEAD && git merge main')
        self.assertEqual(metrics['toolOutcomes'][0]['result'],'pushed')
        self.assertTrue(metrics['toolOutcomes'][1]['is_error'])
        self.assertEqual(metrics['toolOutcomes'][2]['result'],['edited'])
        self.assertEqual(metrics['toolOutcomes'][3]['result'][0]['url'],'https://docs.x.ai')
        self.assertIn('image_gen',metrics['nativeTools'])
        self.assertIn('todo_write',metrics['capabilityAvailability']['other_official_tools'])
        self.assertEqual(metrics['capabilityAvailability']['child_agents']['status'],'unverified')
        self.assertTrue(all(item['status'] in ('observed-in-init', 'unverified') for item in metrics['capabilityAvailability'].values() if isinstance(item, dict)))
        self.assertEqual(metrics['artifactVerification'],'separate')
        self.assertIn('host sandbox',metrics['terminalReach'])
        self.assertEqual(json.loads(output.splitlines()[0])['tools'],[])
        self.assertEqual([block['type'] for block in json.loads(output.splitlines()[1])['message']['content']],['text'])
        deploy=self.stream(command='deploy production')
        g.normalize('\n'.join(map(json.dumps,deploy)),self.request())

    def test_worker_inventory_and_calls_reject_spawning_in_both_modes(self):
        for mode in ('read-only', 'isolated-write'):
            with self.subTest(mode=mode):
                events = self.stream(tools=['read_file', 'run_terminal_command', 'web_fetch', 'web_search', 'spawn_subagent'])
                events = [events[0], events[-1]]
                with self.assertRaisesRegex(ValueError, 'disallowed tool remained'):
                    g.normalize('\n'.join(map(json.dumps, events)), self.request(mode))
                events[0]['tools'].remove('spawn_subagent')
                _, metrics = g.normalize('\n'.join(map(json.dumps, events)), self.request(mode))
                self.assertEqual(metrics['nativeTools'], ['read_file', 'run_terminal_command', 'web_fetch', 'web_search'])
                events.insert(1, {'type': 'assistant', 'session_id': 'abc', 'message': {'model': 'grok-4.7', 'role': 'assistant', 'stop_reason': 'tool_use', 'content': [{'type': 'tool_use', 'id': 'spawn', 'name': 'spawn_subagent', 'input': {'prompt': 'delegate'}}]}})
                with self.assertRaisesRegex(ValueError, 'ungranted or malformed native tool use'):
                    g.normalize('\n'.join(map(json.dumps, events)), self.request(mode))

    def test_missing_tools_stay_unverified_and_legacy_web_blocks_stay_rejected(self):
        tools=['grep','list_dir','read_file','run_terminal_command','search_replace','web_search']
        _,metrics=g.normalize('\n'.join(map(json.dumps,self.stream(tools=tools))),self.request())
        self.assertEqual(metrics['capabilityAvailability']['child_agents']['status'],'unverified')
        self.assertEqual(metrics['capabilityAvailability']['web_fetch']['status'],'unverified')
        self.assertEqual(metrics['nativeTools'],sorted(tools))
        legacy=[
            {'type':'system','subtype':'init','session_id':'abc','model':'grok-4.7','tools':sorted(g.tools({'mode':'isolated-write','allowed_commands':['python3 check.py']})),'mcp_servers':[]},
            {'type':'assistant','session_id':'abc','message':{'model':'grok-4.7','role':'assistant','stop_reason':'end_turn','content':[{'type':'server_tool_use','id':'s','name':'web_search','input':{'query':'q'}}]}},
        ]
        with self.assertRaisesRegex(ValueError,'unknown native content'):
            g.normalize('\n'.join(map(json.dumps,legacy)),{'mode':'isolated-write','model':'grok-4.7','cwd':'/workspace','allowed_commands':['python3 check.py']})

    def test_interleaved_native_calls_require_all_results_before_terminal(self):
        events = self.stream()
        delayed = events[2]['message']['content'].pop(1)
        extra = {'type': 'assistant', 'session_id': 'abc', 'message': {'model': 'grok-4.7', 'role': 'assistant', 'stop_reason': 'tool_use', 'content': [{'type': 'tool_use', 'id': 'f', 'name': 'web_fetch', 'input': {'url': 'https://docs.x.ai'}}]}}
        results = {'type': 'user', 'session_id': 'abc', 'message': {'role': 'user', 'content': [delayed, {'type': 'tool_result', 'tool_use_id': 'f', 'is_error': False, 'content': 'public docs'}]}}
        events[3:3] = [extra, results]
        _, metrics = g.normalize('\n'.join(map(json.dumps, events)), self.request())
        self.assertEqual({call['id'] for call in metrics['toolCalls']}, {'t', 'r', 'w', 'f', 's'})
        self.assertEqual(len(metrics['toolOutcomes']), 5)
        results['message']['content'].pop(0)
        with self.assertRaises(ValueError):
            g.normalize('\n'.join(map(json.dumps, events)), self.request())

    def test_path_inventory_and_match_failures(self):
        req=self.request()
        cases=[
            self.stream(read_path='/etc/passwd'),
            self.stream(write_path='/workspace/other/a.py'),
            self.stream(write_path='/tmp/a.py'),
            self.stream(tools=['read_file','bad__mcp','run_terminal_command']),
            self.stream(),
        ]
        cases[4][0]['mcp_servers']=['local']
        for stream in cases:
            with self.assertRaises(ValueError):g.normalize('\n'.join(map(json.dumps,stream)),req)
        read_only=self.stream(tools=['read_file','search_replace','run_terminal_command'])
        with self.assertRaisesRegex(ValueError,'disallowed'):g.normalize('\n'.join(map(json.dumps,read_only)),self.request('read-only'))
        for mutation in ('id','session','model','terminal','duplicate'):
            stream=self.stream()
            if mutation=='id':stream[2]['message']['content'][0]['tool_use_id']='other'
            if mutation=='session':stream[2]['session_id']='other'
            if mutation=='model':stream[1]['message']['model']='other'
            if mutation=='terminal':stream += [stream[1]]
            if mutation=='duplicate':stream[1]['message']['content'][2]['id']='t'
            with self.assertRaises(ValueError):g.normalize('\n'.join(map(json.dumps,stream)),req)

    def test_home_and_resume_follow_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);original=folder/'orig';original.mkdir();(original/'auth.json').write_text('{}')
            legacy=folder/'legacy';legacy.mkdir()
            home,_=g.prepare_home(legacy,{'mode':'read-only'},{'GROK_HOME':str(original)})
            text=(Path(home)/'config.toml').read_text()
            self.assertIn('[subagents]\nenabled = false\n',text);self.assertIn('web_fetch = false\n',text);self.assertIn('mcps = false\n',text)
            task=folder/'task';task.mkdir()
            home,_=g.prepare_home(task,{'dialect':g.TASK_DIALECT,'mode':'isolated-write'},{'GROK_HOME':str(original)})
            text=(Path(home)/'config.toml').read_text()
            self.assertIn('[subagents]\nenabled = false\n',text);self.assertIn('web_fetch = true\n',text);self.assertIn('write_file = true\n',text)
            read_job=folder/'read';read_job.mkdir()
            home,_=g.prepare_home(read_job,{'dialect':g.TASK_DIALECT,'mode':'read-only'},{'GROK_HOME':str(original)})
            self.assertIn('write_file = false\n',(Path(home)/'config.toml').read_text())
            project=folder/'project';base=project/'.pstack/runs';base.mkdir(parents=True)
            first=base/'first';first.mkdir();owned=first/'grok-home';owned.mkdir();following=base/'following';following.mkdir()
            binding={'provider':'grok','model':'grok-4.7','mode':'read-only','cwd':str(project)}
            receipt=dict(binding,status='complete',request={'dialect':g.TASK_DIALECT},grokHome=str(owned),metrics={'session_id':'11111111-1111-4111-8111-111111111111'})
            (first/'receipt.json').write_text(json.dumps(receipt));(following/'receipt.json').write_text(json.dumps(receipt))
            resumed=g.prepare_home(base/'third',dict(binding,dialect=g.TASK_DIALECT,project=str(project),resume_job=str(following)),{})
            self.assertEqual(resumed[1],'11111111-1111-4111-8111-111111111111')
            with self.assertRaisesRegex(ValueError,'managed-host job'):
                g.prepare_home(base/'third',dict(binding,project=str(project),resume_job=str(following)),{})

    def test_resumed_task_home_disables_previously_enabled_subagents(self):
        for mode in ('read-only', 'isolated-write'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                project = Path(folder); base = project / '.pstack/runs'; first = base / 'first'
                home = first / 'grok-home'; home.mkdir(parents=True)
                (home / 'config.toml').write_text('[subagents]\nenabled = true\n')
                binding = {'provider': 'grok', 'model': 'grok-4.7', 'mode': mode, 'cwd': str(project)}
                receipt = dict(binding, status='complete', request={'dialect': g.TASK_DIALECT}, grokHome=str(home), metrics={'session_id': '11111111-1111-4111-8111-111111111111'})
                (first / 'receipt.json').write_text(json.dumps(receipt))
                result = g.prepare_home(base / 'next', dict(binding, dialect=g.TASK_DIALECT, project=str(project), resume_job=str(first)), {})
                self.assertEqual(result, (str(home), '11111111-1111-4111-8111-111111111111'))
                config = (Path(result[0]) / 'config.toml').read_text()
                self.assertIn('[subagents]\nenabled = false\n', config)
                self.assertIn('web_fetch = true\n', config)
                self.assertIn('[memory]\nenabled = true\n', config)
                self.assertIn('write_file = ' + ('true' if mode == 'isolated-write' else 'false') + '\n', config)
                self.assertEqual((home / 'config.toml').stat().st_mode & 0o777, 0o600)


if __name__=='__main__':unittest.main()
