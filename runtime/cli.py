#!/usr/bin/env python3
"""Private, durable external CLI boundary. No fallback and no shell evaluation."""
import argparse
import hashlib
import math
import fcntl
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grok_native as gn
import workflow_metrics as wm

PROVIDERS = ('claude', 'grok', 'codex')
KEYS = {'claude': {'ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN'}, 'grok': {'XAI_API_KEY', 'GROK_API_KEY'}, 'codex': {'OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN'}}
GROK_DIALECT = {'id': 'grok-build-1', 'confinement': 'response-only'}
WORKER_HEADER = ('You are the assigned external worker for this bounded request. Complete the brief below in your assigned role. Do not activate a framework router, reroute this task, launch subagents, or delegate to another provider. Respect the selected sandbox and report unsupported capabilities.\n\n')


def environment(provider):
    # Keep proxy, certificate and host settings. Remove credential-bearing variables
    # belonging to other services; disk credentials remain accessible to the CLI.
    allowed = KEYS[provider]
    env = {k: v for k, v in os.environ.items() if k in allowed or not (any(s in k.upper() for s in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY')) or k in {'GH_TOKEN', 'GITHUB_TOKEN'})}
    if provider == 'grok':
        env.update({key: '0' for key in ('GROK_MEMORY', 'GROK_SUBAGENTS', 'GROK_TOOL_SEARCH', 'GROK_WRITE_FILE', 'GROK_WEB_FETCH', 'GROK_LSP_TOOLS')})
        env['GROK_DISABLE_AUTOUPDATER'] = '1'
        for vendor in ('CURSOR', 'CLAUDE'):
            for surface in ('SKILLS', 'RULES', 'AGENTS', 'MCPS', 'HOOKS', 'SESSIONS'):
                env[f'GROK_{vendor}_{surface}_ENABLED'] = '0'
    return env


def save(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    os.chmod(temp, 0o600)
    temp.replace(path)


def identity(pid):
    try:
        # comm can contain spaces/parentheses; fields after final ')' start at 3.
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def alive(pid, start):
    if start is None or identity(pid) != start: return False
    try: return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except (OSError, IndexError): return False


def descendants(pid):
    parents = {}
    for entry in Path('/proc').iterdir():
        if entry.name.isdigit():
            try:
                fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
                parents[int(entry.name)] = int(fields[1])
            except (OSError, ValueError, IndexError): pass
    owned, frontier = {}, [pid]
    while frontier:
        parent = frontier.pop()
        for child, ancestor in parents.items():
            if ancestor == parent and child not in owned:
                owned[child] = identity(child)
                frontier.append(child)
    return owned


def stop_owned(process, signum):
    owned = descendants(process.pid)
    if process.poll() is None:
        try: os.killpg(process.pid, signum)
        except ProcessLookupError: pass
    for pid, start in owned.items():
        if alive(pid, start):
            try: os.kill(pid, signum)
            except ProcessLookupError: pass
    return owned


def validate(raw):
    if not isinstance(raw, dict):
        raise ValueError('request must be an object')
    for key in ('provider', 'model', 'mode', 'project', 'cwd'):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise ValueError(f'{key} must be a nonempty string')
    raw = dict(raw)
    if 'prompt_file' in raw:
        prompt = Path(raw['prompt_file']) if isinstance(raw['prompt_file'], str) else None
        if prompt is None or not prompt.is_absolute() or not prompt.is_file() or prompt.stat().st_size > 1048576:
            raise ValueError('prompt_file must be an absolute real file of at most 1 MiB')
        with prompt.open('rb') as source:
            content = source.read(1048577)
        if len(content) > 1048576:
            raise ValueError('prompt_file exceeds 1 MiB')
        raw['brief'] = content.decode('utf-8')
    if not isinstance(raw.get('brief'), str) or not raw['brief'].strip() or len(raw['brief'].encode()) > 1048576:
        raise ValueError('brief must be nonempty text of at most 1 MiB')
    if 'allowed_commands' in raw and (not isinstance(raw['allowed_commands'], list) or not all(isinstance(x, str) and x.strip() and not any(c in x for c in '\n\r*()') for x in raw['allowed_commands'])):
        raise ValueError('allowed_commands must be literal command prefixes without wildcards or permission syntax')
    if raw['provider'] not in PROVIDERS or raw['mode'] not in ('read-only', 'isolated-write'):
        raise ValueError('unsupported provider or mode')
    if raw['provider'] == 'grok' and raw.get('dialect') == gn.DIALECT:
        gn.validate_boundary(raw.get('host_boundary'), raw['cwd'])
        gn.argv(raw)
    if 'resume_job' in raw and (not isinstance(raw['resume_job'], str) or not Path(raw['resume_job']).is_absolute()):
        raise ValueError('resume_job requires an absolute owned job path')
    if 'workflow' in raw and (not isinstance(raw['workflow'], str) or not Path(raw['workflow']).is_absolute()):
        raise ValueError('workflow requires an absolute private evidence directory')
    if 'effort' in raw and (not isinstance(raw['effort'], str) or not raw['effort']):
        raise ValueError('effort must be a nonempty string')
    if 'timeout' in raw and (isinstance(raw['timeout'], bool) or not isinstance(raw['timeout'], (int, float)) or not math.isfinite(raw['timeout']) or raw['timeout'] <= 0):
        raise ValueError('timeout must be positive seconds')
    project, cwd = Path(raw['project']).resolve(), Path(raw['cwd']).resolve()
    if not project.is_dir() or not cwd.is_dir():
        raise ValueError('project and cwd must exist')
    if raw['mode'] == 'isolated-write':
        git = subprocess.run(['git', '-C', str(cwd), 'rev-parse', '--git-dir', '--git-common-dir'], capture_output=True, text=True)
        lines = git.stdout.splitlines()
        owned = git.returncode == 0 and len(lines) == 2 and Path(cwd / lines[0]).resolve() != Path(cwd / lines[1]).resolve()
        project_git = subprocess.run(['git', '-C', str(project), 'rev-parse', '--git-common-dir'], capture_output=True, text=True)
        root_git = subprocess.run(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
        owned = owned and project_git.returncode == 0 and Path(project / project_git.stdout.strip()).resolve() == Path(cwd / lines[1]).resolve() and root_git.returncode == 0 and Path(root_git.stdout.strip()).resolve() == cwd
        scratch = raw.get('isolated_scratch') is True and cwd != project and project not in cwd.parents and not any(cwd.iterdir())
        if cwd == project or not (owned or scratch):
            raise ValueError('writer requires a separate git worktree or empty explicit isolated scratch outside project')
    raw = dict(raw, project=str(project), cwd=str(cwd))
    return raw


def profile(req):
    provider = req['provider']
    command = req.get('executable', provider)
    if not isinstance(command, str):
        raise ValueError('executable must be a path or command')
    if provider == 'grok':
        # Grok Build dialects vary. Only an explicit reviewed profile is accepted.
        dialect = req.get('dialect')
        if not isinstance(dialect, dict):
            raise ValueError('Grok requires an explicit dialect with auth_argv, run_argv and required_flags')
        if 'id' in dialect:
            if dialect not in (GROK_DIALECT, gn.DIALECT):
                raise ValueError('unsupported named Grok dialect or confinement')
            if dialect == GROK_DIALECT and (req['mode'] != 'read-only' or req.get('allowed_commands')):
                raise ValueError('response-only Grok supports read-only mode without commands; isolated writing is unavailable')
            auth = ['models']
            args = ['--model', req['model'], '--cwd', req['cwd'], '--permission-mode', 'dontAsk', '--sandbox', 'off', '--output-format', 'streaming-messages-json', '--tools', 'read_file', '--disallowed-tools', 'read_file,search_tool,use_tool', '--no-subagents', '--disable-web-search']
            if dialect == gn.DIALECT:
                args = args[:args.index('--tools')] + ['--no-subagents', '--disable-web-search'] + gn.argv(req)
                if req.get('resume_session'):
                    args += ['--resume', req['resume_session']]
            if req.get('effort'):
                args += ['--reasoning-effort', req['effort']]
            required = [x for x in args if x.startswith('--')] + ['--prompt-file']
        else:
            auth, args, required = dialect.get('auth_argv'), dialect.get('run_argv'), dialect.get('required_flags')
            if not all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in (auth, args, required)):
                raise ValueError('dialect argv and required_flags must be string arrays')
            if not required or not any('{model}' in x for x in args) or not any('{mode}' in x for x in args):
                raise ValueError('dialect must pin model and access mode and declare help capabilities')
            if req.get('effort') and not any('{effort}' in x for x in args):
                raise ValueError('dialect cannot honor effort')
            substitutions = {'model': req['model'], 'effort': req.get('effort', ''), 'mode': req['mode'], 'cwd': req['cwd']}
            args = [x.format(**substitutions) for x in args]
    elif provider == 'claude':
        auth = ['auth', 'status', '--json']
        args = ['-p', '--model', req['model'], '--permission-mode', 'plan' if req['mode'] == 'read-only' else 'acceptEdits', '--output-format', 'json', '--setting-sources', 'project', '--strict-mcp-config', '--no-session-persistence', '--disable-slash-commands', '--tools', 'Read,Grep,Glob' if req['mode'] == 'read-only' else 'Read,Write,Edit,Grep,Glob', '--restricted', '--disallowedTools', 'Agent,Task,WebSearch,WebFetch,Bash']
        if req['mode'] == 'isolated-write' and req.get('allowed_commands'):
            args[args.index('--tools') + 1] += ',Bash'
            args[args.index('--disallowedTools') + 1] = 'Agent,Task,WebSearch,WebFetch'
            args += ['--allowedTools'] + ['Bash(' + command + ':*)' for command in req['allowed_commands']]
        if req.get('effort'):
            args += ['--effort', req['effort']]
        required = [x for x in args if x.startswith('--')]
    else:
        auth = ['login', 'status']
        args = ['exec', '--disable', 'plugins', '--disable', 'multi_agent', '--disable', 'hooks', '--disable', 'memories', '--model', req['model'], '--sandbox', req['mode'] if req['mode'] == 'read-only' else 'workspace-write', '--cd', req['cwd'], '--ephemeral', '--json', '-']
        if req.get('effort'):
            args += ['--config', 'model_reasoning_effort=' + json.dumps(req['effort'])]
        required = ['--disable', '--model', '--sandbox', '--cd', '--ephemeral', '--json']
    if any(any(unsafe in x.lower() for unsafe in ('bypass', 'dangerously', '--always-approve', '--yolo')) for x in args + auth):
        raise ValueError('permission bypass is prohibited')
    return command, auth, args, required


def parse_grok_output(output, model, cwd=None):
    try:
        records = [json.loads(line) for line in output.splitlines() if line.strip()]
    except json.JSONDecodeError:
        raise ValueError('malformed provider JSON')
    session, assistant_seen, result, metrics = None, False, None, {}
    for record in records:
        if not isinstance(record, dict) or result is not None:
            raise ValueError('invalid Grok event or event after terminal result')
        kind = record.get('type')
        if record.get('is_error') is True or kind in ('error', 'turn.failed'):
            raise ValueError('Grok reported an error')
        if session is None:
            if kind != 'system' or record.get('subtype') != 'init':
                raise ValueError('Grok init must be the first event')
            session = record.get('session_id')
            if not isinstance(session, str) or not session.strip() or record.get('model') != model:
                raise ValueError('Grok init session or served model mismatch')
            if record.get('tools') != [] or record.get('mcp_servers') != []:
                raise ValueError('response-only Grok init must report no tools or MCP servers')
            if record.get('permissionMode') != 'dontAsk' or (cwd is not None and record.get('cwd') != cwd):
                raise ValueError('Grok init permission mode or cwd mismatch')
            metrics['session_id'] = session
            metrics['observedSkills'] = record.get('skills', [])
            metrics['observedSlashCommands'] = record.get('slash_commands', [])
            continue
        if record.get('session_id') != session:
            raise ValueError('Grok session changed or is missing')
        if kind == 'assistant':
            message = record.get('message')
            if not isinstance(message, dict) or message.get('model') != model or message.get('role') != 'assistant':
                raise ValueError('Grok assistant served model or message mismatch')
            content = message.get('content')
            if not isinstance(content, list) or not content:
                raise ValueError('Grok assistant content must be nonempty blocks')
            for block in content:
                if not isinstance(block, dict) or block.get('type') not in ('text', 'thinking'):
                    raise ValueError('response-only Grok reported a tool or unknown content block')
                if not isinstance(block.get(block['type']), str):
                    raise ValueError('Grok assistant block must contain text')
            if message.get('stop_reason') not in ('end_turn', None):
                raise ValueError('Grok assistant ended unexpectedly')
            assistant_seen = True
        elif kind == 'result':
            if not assistant_seen or record.get('subtype') != 'success' or record.get('is_error') is not False:
                raise ValueError('successful Grok terminal result required')
            if record.get('stop_reason') != 'end_turn' or not isinstance(record.get('result'), str) or not record['result'].strip():
                raise ValueError('nonempty completed Grok result required')
            result = record['result'].strip()
            for key in ('usage', 'modelUsage', 'total_cost_usd', 'duration_ms', 'duration_api_ms'):
                if key in record:
                    metrics[key] = record[key]
            billing = record.get('modelUsage', {})
            if not isinstance(billing, dict) or not all(isinstance(k, str) and isinstance(v, dict) for k, v in billing.items()):
                raise ValueError('modelUsage must map billing labels to objects')
            usage = record.get('usage', {})
            if not isinstance(usage, dict):
                raise ValueError('Grok usage must be an object')
            server_tools = usage.get('server_tool_use', {})
            if not isinstance(server_tools, dict) or any(value != 0 for value in server_tools.values()):
                raise ValueError('response-only Grok reported server tool use')
            for entry in billing.values():
                if entry.get('webSearchRequests', 0) != 0:
                    raise ValueError('response-only Grok reported web tool use')
        else:
            raise ValueError('unexpected Grok event in response-only profile')
    if result is None:
        raise ValueError('successful Grok terminal result required')
    return result, model, metrics


def parse_output(provider, output, model, dialect=None, cwd=None):
    if provider == 'grok' and dialect == GROK_DIALECT:
        return parse_grok_output(output, model, cwd)
    try:
        records = [json.loads(output)] if provider == 'claude' else [json.loads(line) for line in output.splitlines() if line.strip()]
    except json.JSONDecodeError:
        raise ValueError('malformed provider JSON')
    text, reported, terminal, metrics = [], None, False, {}
    failed = False
    for record in records:
        if not isinstance(record, dict):
            raise ValueError('provider event must be an object')
        kind = record.get('type')
        if 'model' in record and not isinstance(record['model'], str):
            raise ValueError('provider model must be text')
        if kind in ('turn.failed', 'error') or record.get('is_error') is True:
            failed = True
        if record.get('model'):
            reported = record['model']
        if 'modelUsage' in record and (not isinstance(record['modelUsage'], dict) or not all(isinstance(k, str) and isinstance(v, dict) for k, v in record['modelUsage'].items())):
            raise ValueError('modelUsage must map model names to objects')
        if kind == 'result' and 'result' in record and not isinstance(record['result'], str):
            raise ValueError('provider result must be text')
        if isinstance(record.get('modelUsage'), dict) and len(record['modelUsage']) == 1:
            reported = next(iter(record['modelUsage']))
        if kind == 'result' and provider != 'codex':
            terminal = record.get('subtype', 'success') == 'success' and not record.get('is_error', False)
            if isinstance(record.get('result'), str):
                text.append(record['result'])
        if kind == 'item.completed':
            item = record.get('item')
            if not isinstance(item, dict):
                raise ValueError('provider item must be an object')
            if item.get('type') == 'agent_message':
                if not isinstance(item.get('text'), str):
                    raise ValueError('agent message must be text')
                text.append(item['text'])
        if kind == 'thread.started' and record.get('model'):
            reported = record['model']
        if kind == 'turn.completed':
            terminal = True
        for key in ('usage', 'total_cost_usd', 'duration_ms', 'duration_api_ms'):
            if key in record:
                metrics[key] = record[key]
    result = '\n'.join(text).strip()
    if failed or not terminal or not result:
        raise ValueError('nonempty response and successful terminal provider event required')
    if provider != 'codex' and not reported:
        raise ValueError('provider did not report served model')
    if reported and reported != model:
        aliases = {'opus': 'claude-opus-', 'sonnet': 'claude-sonnet-', 'haiku': 'claude-haiku-', 'fable': 'claude-fable-'}
        if model not in aliases or not str(reported).startswith(aliases[model]):
            raise ValueError('provider-reported model differs from requested model')
    return result, reported, metrics


def resolve_config(raw):
    if not isinstance(raw, dict):
        raise ValueError('request must be an object')
    project = Path(raw.get('project', '.')).resolve()
    defaults = {}
    for config in (Path(__file__).resolve().parent.parent / 'config' / 'defaults.json', project / '.pstack' / 'config.json'):
        if config.is_file():
            loaded = json.loads(config.read_text())
            if not isinstance(loaded, dict) or not isinstance(loaded.get('providers', {}), dict):
                raise ValueError('provider configuration must be an object')
            settings = loaded.get('providers', {}).get(raw.get('provider'), {})
            if not isinstance(settings, dict):
                raise ValueError('provider settings must be an object')
            defaults.update({k: v for k, v in settings.items() if k in ('executable', 'dialect')})
    binary = os.environ.get(str(raw.get('provider', '')).upper() + '_BINARY')
    if binary:
        defaults['executable'] = binary
    return dict(defaults, **raw)


def authenticated(provider, code, output):
    if code:
        return False
    if provider != 'claude':
        return True
    try:
        data = json.loads(output)
        return isinstance(data, dict) and data.get('loggedIn') is True
    except (ValueError, TypeError):
        return False


def grok_catalog(output):
    if 'You are logged in with grok.com.' not in output.splitlines() or 'Available models:' not in output.splitlines():
        raise ValueError('Grok models did not confirm authenticated catalog')
    available = output.split('Available models:', 1)[1]
    models = re.findall(r'^\s*[-*]\s+(\S+)(?:\s+\(default\))?\s*$', available, re.MULTILINE)
    if not models:
        raise ValueError('Grok authenticated model catalog is empty')
    return models


def inspect_grok(output, grok_home=None):
    data = json.loads(output)
    if not isinstance(data, dict):
        raise ValueError('Grok inspect must be an object')
    for key in ('hooks', 'mcpServers', 'projectInstructions', 'plugins'):
        if data.get(key) != []:
            raise ValueError(f'Grok inspect discovered unsupported {key}')
    bundled_root = (Path(grok_home or os.environ.get('GROK_HOME') or Path.home() / '.grok') / 'bundled' / 'skills').resolve()
    for key in ('skills', 'agents'):
        entries = data.get(key)
        if not isinstance(entries, list):
            raise ValueError(f'Grok inspect discovered unsupported {key}')
        for entry in entries:
            source = entry.get('source') if isinstance(entry, dict) else None
            if not isinstance(source, dict):
                raise ValueError(f'Grok inspect discovered unsupported {key}')
            if source.get('type') == 'builtin':
                continue
            path = source.get('path')
            if key == 'skills' and source.get('type') == 'bundled' and isinstance(path, str) and Path(path).is_absolute() and bundled_root in Path(path).resolve().parents:
                continue
            raise ValueError(f'Grok inspect discovered unsupported {key}')
    return data


def run(raw, on_start=None):
    started = time.monotonic()
    req = validate(resolve_config(raw))
    req['brief'] = WORKER_HEADER + req['brief']
    native_grok = req['provider'] == 'grok' and req.get('dialect') == gn.DIALECT
    child_env = environment(req['provider'])
    named_grok = req['provider'] == 'grok' and isinstance(req.get('dialect'), dict) and 'id' in req['dialect']
    base = Path(req['project']) / '.pstack' / 'runs'
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    job = base / uuid.uuid4().hex
    job.mkdir(mode=0o700)
    receipt = {'job': str(job), 'job_id': job.name, 'artifacts': {'receipt': str(job / 'receipt.json'), 'response': str(job / 'response.txt')}, 'provider': req['provider'], 'model': req['model'], 'effort': req.get('effort'), 'mode': req['mode'], 'cwd': req['cwd'], 'status': 'starting', 'credentialIsolation': 'filtered environment; provider on-disk credentials remain accessible', 'runnerPid': os.getpid(), 'runnerStart': identity(os.getpid()), 'reportedModel': None, 'modelVerified': False, 'modelEvidence': 'pinned-argv'}
    receipt.update(promptDigest=hashlib.sha256(req['brief'].encode()).hexdigest(), request={k: req[k] for k in ('provider', 'model', 'effort', 'mode', 'project', 'cwd', 'prompt_file', 'executable', 'dialect', 'timeout', 'allowed_commands', 'isolated_scratch', 'host_boundary', 'resume_job') if k in req}, transport='subprocess-stdin')
    if named_grok:
        receipt.update(transport='subprocess-prompt-file', confinement='response-only', filesystemSandbox='off', filesystemIsolation='unavailable', toolAccess='disabled by profile; live init pending', effortEvidence='pinned-argv' if req.get('effort') else 'provider-default', unsupportedCapabilities=['isolated-write', 'native file tools', 'filesystem and credential isolation'])
    if native_grok:
        receipt.update(confinement='managed-host', filesystemIsolation='host-declared; per-launch boundary probe required', unsupportedCapabilities=['per-job VM and credential isolation', 'native Codex collaboration API'], toolAccess='native tools; live init pending')
    workflow = req.get('workflow')
    def metric(kind, metadata=None, stage=None):
        if workflow:
            details = dict(metadata or {})
            if stage: details.update(stage=stage, phaseId=stage)
            wm.record_event(workflow, job.name, kind, details, attempt=job.name, parent_worker=req.get('parent_worker'), source='external-runtime')
    metric('requested', {'provider':req['provider'], 'model':req['model'], 'effort':req.get('effort'), 'briefBytes':len(req['brief'].encode())})
    metric('started')
    for key in ('host', 'source_pin'):
        if key in req: receipt[key] = req[key]
    save(job / 'receipt.json', receipt)
    if on_start: on_start(dict(receipt))
    (job / 'brief.txt').write_text(req['brief'])
    os.chmod(job / 'brief.txt', 0o600)
    lock = None
    session_lock = None
    owned_children = {}
    process = None
    cancelled = False
    def stop(signum, frame):
        nonlocal cancelled
        cancelled = True
        if process is not None and process.poll() is None:
            owned_children.update(stop_owned(process, signal.SIGTERM))
    old = {s: signal.signal(s, stop) for s in (signal.SIGTERM, signal.SIGINT)}
    deadline = started + req['timeout'] if 'timeout' in req else None
    def execute(argv, stdin=None, stage='probe'):
        nonlocal process
        if cancelled:
            raise InterruptedError('cancelled')
        metric('phase-start', stage=stage)
        process = subprocess.Popen(argv, cwd=req['cwd'], env=child_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        receipt.update(childPid=process.pid, childStart=identity(process.pid), status='running')
        save(job / 'receipt.json', receipt)
        try:
            while True:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError('explicit deadline exceeded')
                try:
                    out, err = process.communicate(stdin, timeout=min(0.2, remaining) if remaining is not None else 0.2)
                    if cancelled:
                        raise InterruptedError('cancelled')
                    for name, content in ((stage + '-stdout.txt', out), (stage + '-stderr.txt', err)):
                        artifact = job / name
                        artifact.write_text(content); os.chmod(artifact, 0o600)
                        receipt['artifacts'][name] = str(artifact)
                    if stage == 'provider':
                        save(job / 'provider-events.json', {'stdout': out, 'stderr': err})
                        receipt['artifacts']['providerEvents'] = str(job / 'provider-events.json')
                    return process.returncode, out, err
                except subprocess.TimeoutExpired:
                    stdin = None
                    if cancelled:
                        raise InterruptedError('cancelled')
        finally:
            if process.poll() is None:
                owned_children.update(stop_owned(process, signal.SIGKILL))
                process.wait()
            if cancelled or (deadline is not None and time.monotonic() >= deadline):
                for pid, start in owned_children.items():
                    if alive(pid, start):
                        try: os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError: pass
            if cancelled or (deadline is not None and time.monotonic() >= deadline):
                try: out, err = process.communicate(timeout=1)
                except subprocess.TimeoutExpired as error:
                    out, err = error.output or '', error.stderr or ''
                    out = out.decode(errors='replace') if isinstance(out, bytes) else out
                    err = err.decode(errors='replace') if isinstance(err, bytes) else err
                    receipt['pipeDrain'] = 'partial; bounded cleanup timeout'
                for name, content in ((stage + '-stdout.txt', out), (stage + '-stderr.txt', err)):
                    artifact = job / name
                    artifact.write_text(content); os.chmod(artifact, 0o600)
                    receipt['artifacts'][name] = str(artifact)
            metric('phase-end', stage=stage)
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe and not pipe.closed: pipe.close()
    try:
        if native_grok:
            receipt['hostBoundary'] = gn.probe_boundary(req['host_boundary'])
            receipt['grokHome'], session = gn.prepare_home(job, req, child_env)
            child_env['GROK_HOME'] = receipt['grokHome']
            session_lock = (Path(receipt['grokHome']) / '.pstack-session.lock').open('a')
            os.chmod(Path(receipt['grokHome']) / '.pstack-session.lock', 0o600)
            try: fcntl.flock(session_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError('native session already reserved by another request')
            if session: req['resume_session'] = session
        command, auth, args, required = profile(req)
        if named_grok:
            args += ['--prompt-file', str(job / 'brief.txt')]
        if req['mode'] == 'isolated-write':
            git_dir = subprocess.run(['git', '-C', req['cwd'], 'rev-parse', '--absolute-git-dir'], capture_output=True, text=True)
            lock_path = (Path(git_dir.stdout.strip()) if git_dir.returncode == 0 else Path(req['cwd'])) / '.pstack-writer.lock'
            lock = lock_path.open('a')
            os.chmod(lock_path, 0o600)
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError('isolated worktree already reserved by another writer')
        if not shutil.which(command):
            raise ValueError('provider CLI unavailable')
        code, version, _ = execute([command, '--version'])
        if code:
            raise ValueError('version probe failed')
        receipt['cliVersion'] = version.strip()[:300]
        if req['provider'] == 'codex':
            code, feature_text, _ = execute([command, 'features', 'list'])
            features = {line.split()[0] for line in feature_text.splitlines() if line.split()}
            if code or not {'plugins', 'multi_agent', 'hooks', 'memories'}.issubset(features):
                raise ValueError('Codex does not confirm recursive-execution feature controls')
        code, help_text, _ = execute([command, 'exec', '--help'] if req['provider'] == 'codex' else [command, '--help'])
        if code or any(flag not in help_text for flag in required):
            raise ValueError('CLI help does not confirm required capabilities')
        code, auth_text, _ = execute([command] + auth, stage='auth')
        if not authenticated(req['provider'], code, auth_text):
            raise ValueError('provider authentication preflight failed')
        if named_grok:
            receipt['availableModels'] = grok_catalog(auth_text)
            if req['model'] not in receipt['availableModels']:
                raise ValueError('requested Grok model is absent from authenticated catalog')
            code, discovery, _ = execute([command, 'inspect', '--json'], stage='inspect')
            if code:
                raise ValueError('Grok inspect failed')
            inspected = inspect_grok(discovery, child_env.get('GROK_HOME'))
            receipt['configurationPreflight'] = True
            receipt['observedDiscovery'] = {key: inspected.get(key) for key in ('skills', 'agents', 'externalCompat')}
        receipt['authPreflight'] = True
        receipt['argv'] = [command] + args
        code, output, _ = execute([command] + args, None if named_grok else req['brief'], stage='provider')
        if code:
            raise ValueError(f'provider exited {code}')
        native_metrics = {}
        if native_grok:
            output, native_metrics = gn.normalize(output, req)
        response, reported, metrics = parse_output(req['provider'], output, req['model'], GROK_DIALECT if native_grok else req.get('dialect'), req['cwd'])
        metrics.update(native_metrics)
        if named_grok:
            receipt['toolAccess'] = 'native tools; verified in init and matched results' if native_grok else 'none; verified in native init'
        (job / 'response.txt').write_text(response + '\n')
        os.chmod(job / 'response.txt', 0o600)
        receipt.update(status='complete', authVerified=True, reportedModel=reported, modelVerified=reported is not None, modelEvidence='provider-report' if reported else 'pinned-argv', metrics=metrics)
    except TimeoutError:
        receipt.update(status='timed-out', error='explicit deadline exceeded')
    except InterruptedError:
        receipt.update(status='cancelled')
    except (ValueError, OSError, json.JSONDecodeError) as error:
        receipt.update(status='failed', error=str(error))
    finally:
        receipt['ownedChildren'] = [{'pid':pid,'start':start,'alive':alive(pid,start)} for pid,start in owned_children.items()]
        receipt['elapsedSeconds'] = round(time.monotonic() - started, 3)
        save(job / 'receipt.json', receipt)
        if workflow:
            wm.import_receipt(workflow, job / 'receipt.json', parent_worker=req.get('parent_worker'))
            receipt['summaryLines'] = wm.format_summary(wm.summarize(workflow)).splitlines()
            save(job / 'receipt.json', receipt)
        if session_lock is not None: session_lock.close()
        if lock is not None: lock.close()
        for s, handler in old.items():
            signal.signal(s, handler)
    return receipt


def status(job):
    receipt = json.loads((Path(job) / 'receipt.json').read_text())
    if receipt['status'] in ('starting', 'running') and not alive(receipt.get('runnerPid'), receipt.get('runnerStart')):
        receipt['observedStatus'] = 'interrupted; runner no longer alive'
    return receipt



def doctor(project=None):
    result = {'providers': {}, 'authenticatedExecution': 'not verified by probes'}
    for provider in PROVIDERS:
        settings = resolve_config({'provider': provider, 'project': project or '.'})
        binary = settings.get('executable', provider)
        item = {'executable': shutil.which(binary), 'authenticatedExecution': 'not verified'}
        result['providers'][provider] = item
        if not item['executable']:
            item['status'] = 'blocked: CLI unavailable'
            continue
        command = subprocess.run([binary, '--version'], capture_output=True, text=True, env=environment(provider))
        item['version'] = command.stdout.strip()[:300]
        item['versionProbe'] = command.returncode == 0
        if provider == 'grok':
            item['dialectConfigured'] = isinstance(settings.get('dialect'), dict)
            if settings.get('dialect') not in (GROK_DIALECT, gn.DIALECT):
                item['status'] = 'blocked: reviewed named response-only dialect required for native preflight'
                continue
            native = settings.get('dialect') == gn.DIALECT
            item.update(confinement='managed-host' if native else 'response-only', filesystemSandbox='off', filesystemIsolation='requires qualified outer host boundary' if native else 'unavailable', toolAccess='must be verified in live init')
            try:
                cwd = str(Path(project or '.').resolve())
                _, auth, _, required = profile(dict(settings, provider='grok', model='catalog-preflight', mode='read-only', cwd=cwd))
                help_probe = subprocess.run([binary, '--help'], cwd=cwd, capture_output=True, text=True, env=environment(provider))
                item['helpPreflight'] = help_probe.returncode == 0 and all(flag in help_probe.stdout for flag in required)
                if not item['versionProbe'] or not item['helpPreflight']:
                    raise ValueError('version or required native help capability unavailable')
                catalog = subprocess.run([binary] + auth, cwd=cwd, capture_output=True, text=True, env=environment(provider))
                if catalog.returncode:
                    raise ValueError('Grok authenticated model catalog failed')
                item['availableModels'] = grok_catalog(catalog.stdout)
                item['authPreflight'] = True
                item['catalogPreflight'] = True
                discovery = subprocess.run([binary, 'inspect', '--json'], cwd=cwd, capture_output=True, text=True, env=environment(provider))
                if discovery.returncode:
                    raise ValueError('Grok inspect failed')
                inspect_grok(discovery.stdout)
                item['configurationPreflight'] = True
                item['status'] = 'ready for managed-host live execution probe' if native else 'ready for response-only live execution probe'
            except (ValueError, OSError) as error:
                item['status'] = 'blocked: ' + str(error)
            continue
        args = ['auth', 'status', '--json'] if provider == 'claude' else ['login', 'status']
        probe = subprocess.run([binary] + args, capture_output=True, text=True, env=environment(provider))
        auth_ok = authenticated(provider, probe.returncode, probe.stdout)
        item['authPreflight'] = auth_ok
        item['status'] = 'ready for live execution probe' if auth_ok else 'blocked: authentication preflight failed'
    return result


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('doctor'); p.add_argument('--project'); p.add_argument('--json', action='store_true')
    p = sub.add_parser('run'); p.add_argument('--request', required=True); p.add_argument('--project')
    for command in ('status', 'cancel', 'checkpoint'):
        p = sub.add_parser(command); p.add_argument('--job', required=True); p.add_argument('--project')
        if command == 'checkpoint': p.add_argument('file')
    options = parser.parse_args()
    if getattr(options, 'job', None) and getattr(options, 'project', None) and not Path(options.job).is_absolute():
        options.job = str(Path(options.project) / '.pstack' / 'runs' / options.job)
    try:
        if options.command == 'run':
            request = json.loads(Path(options.request).read_text())
            if options.project: request['project'] = options.project
            result = run(request, on_start=lambda receipt: print(json.dumps({'event': 'job.started', 'job_id': receipt['job_id'], 'job': receipt['job']}), flush=True))
        elif options.command == 'doctor':
            result = doctor(options.project)
        elif options.command == 'status':
            result = status(options.job)
        elif options.command == 'checkpoint':
            value = json.loads(Path(options.file).read_text())
            save(Path(options.job) / 'checkpoint.json', value)
            result = {'checkpoint': 'saved'}
        else:
            result = status(options.job)
            if result['status'] not in ('starting', 'running') or not alive(result.get('runnerPid'), result.get('runnerStart')):
                raise ValueError('no live runner with matching process identity')
            os.kill(result['runnerPid'], signal.SIGTERM)
            result = {'cancellation': 'requested; poll receipt for final result'}
        print(json.dumps(result, indent=2))
        return 0 if result.get('status', 'complete') == 'complete' and options.command != 'doctor' else (0 if options.command != 'run' and options.command != 'doctor' else 1)
    except (ValueError, OSError) as error:
        print(json.dumps({'error': str(error)})); return 1

if __name__ == '__main__':
    sys.exit(main())
