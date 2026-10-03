#!/usr/bin/env python3
"""Private, durable external CLI boundary. No fallback and no shell evaluation."""
import argparse
import hashlib
import math
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid

PROVIDERS = ('claude', 'grok', 'codex')
KEYS = {'claude': {'ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN'}, 'grok': {'XAI_API_KEY', 'GROK_API_KEY'}, 'codex': {'OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN'}}


def environment(provider):
    # Keep proxy, certificate and host settings. Remove credential-bearing variables
    # belonging to other services; disk credentials remain accessible to the CLI.
    allowed = KEYS[provider]
    return {k: v for k, v in os.environ.items() if k in allowed or not (any(s in k.upper() for s in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY')) or k in {'GH_TOKEN', 'GITHUB_TOKEN'})}


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
    return start is not None and identity(pid) == start


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
    if any('bypass' in x or 'dangerously' in x for x in args + auth):
        raise ValueError('permission bypass is prohibited')
    return command, auth, args, required


def parse_output(provider, output, model):
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


def run(raw, on_start=None):
    started = time.monotonic()
    req = validate(resolve_config(raw))
    if req['provider'] == 'codex':
        req['brief'] = ('You are the assigned external worker for this bounded request. Complete the brief below in your assigned role. Do not activate a framework router, reroute this task, launch subagents, or delegate to another provider. Respect the selected sandbox and report unsupported capabilities.\n\n' + req['brief'])
    base = Path(req['project']) / '.pstack' / 'runs'
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    job = base / uuid.uuid4().hex
    job.mkdir(mode=0o700)
    receipt = {'job': str(job), 'job_id': job.name, 'artifacts': {'receipt': str(job / 'receipt.json'), 'response': str(job / 'response.txt')}, 'provider': req['provider'], 'model': req['model'], 'effort': req.get('effort'), 'mode': req['mode'], 'cwd': req['cwd'], 'status': 'starting', 'credentialIsolation': 'filtered environment; provider on-disk credentials remain accessible', 'runnerPid': os.getpid(), 'runnerStart': identity(os.getpid()), 'reportedModel': None, 'modelVerified': False, 'modelEvidence': 'pinned-argv'}
    receipt.update(promptDigest=hashlib.sha256(req['brief'].encode()).hexdigest(), request={k: req[k] for k in ('provider', 'model', 'effort', 'mode', 'project', 'cwd', 'prompt_file', 'executable', 'dialect', 'timeout', 'allowed_commands', 'isolated_scratch') if k in req}, transport='subprocess-stdin')
    for key in ('host', 'source_pin'):
        if key in req: receipt[key] = req[key]
    save(job / 'receipt.json', receipt)
    if on_start: on_start(dict(receipt))
    (job / 'brief.txt').write_text(req['brief'])
    os.chmod(job / 'brief.txt', 0o600)
    lock = None
    process = None
    cancelled = False
    def stop(signum, frame):
        nonlocal cancelled
        cancelled = True
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
    old = {s: signal.signal(s, stop) for s in (signal.SIGTERM, signal.SIGINT)}
    deadline = started + req['timeout'] if 'timeout' in req else None
    def execute(argv, stdin=None, stage='probe'):
        nonlocal process
        if cancelled:
            raise InterruptedError('cancelled')
        process = subprocess.Popen(argv, cwd=req['cwd'], env=environment(req['provider']), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
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
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe and not pipe.closed: pipe.close()
    try:
        if req['mode'] == 'isolated-write':
            git_dir = subprocess.run(['git', '-C', req['cwd'], 'rev-parse', '--absolute-git-dir'], capture_output=True, text=True)
            lock_path = (Path(git_dir.stdout.strip()) if git_dir.returncode == 0 else Path(req['cwd'])) / '.pstack-writer.lock'
            lock = lock_path.open('a')
            os.chmod(lock_path, 0o600)
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError('isolated worktree already reserved by another writer')
        command, auth, args, required = profile(req)
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
        code, auth_text, _ = execute([command] + auth)
        if not authenticated(req['provider'], code, auth_text):
            raise ValueError('provider authentication preflight failed')
        receipt['authPreflight'] = True
        receipt['argv'] = [command] + args
        code, output, _ = execute([command] + args, req['brief'], stage='provider')
        if code:
            raise ValueError(f'provider exited {code}')
        response, reported, metrics = parse_output(req['provider'], output, req['model'])
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
        receipt['elapsedSeconds'] = round(time.monotonic() - started, 3)
        save(job / 'receipt.json', receipt)
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
            item['status'] = 'blocked: explicit dialect and authenticated structured-output probe required'
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
