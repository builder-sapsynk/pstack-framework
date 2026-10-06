#!/usr/bin/env python3
"""Local-host CLI worker runner: one task, one worktree, one run directory, one receipt."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dispatch_policy
import panel_divergence
import worker_resources

PROVIDERS = ('codex', 'grok', 'claude')
MODES = ('write', 'read')
TASK = re.compile(r'^[a-z0-9][a-z0-9._-]{0,63}$')
KEYS = {'claude': {'ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN'}, 'grok': {'XAI_API_KEY', 'GROK_API_KEY'},
        'codex': {'OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN'}}
TERMINAL = ('succeeded', 'failed', 'killed', 'timeout', 'startup_timeout', 'stalled', 'lost')
EXIT = {'succeeded': 0, 'timeout': 124, 'startup_timeout': 124, 'stalled': 124, 'killed': 130}
DEFAULTS = {'startup_timeout': 120.0, 'idle_timeout': 900.0, 'timeout': 3600.0}
SUMMARY_LIMIT = 2000
ATTEMPT_KEYS = ('attempt', 'state', 'exit_code', 'session_id', 'model', 'effort', 'cost_usd', 'usage', 'duration_s',
                'started_at', 'ended_at', 'error')
HEADER = ('You are pstack worker `{task}` running as an external {provider} CLI agent in {mode} mode.\n'
          'Your working directory is {where}.\n'
          'You run unattended with full autonomy on a dedicated machine: no sandbox, no approval prompts, '
          'full shell, tools and network. Use whatever the task needs.\n'
          'You are a worker, not the coordinator. Do the brief directly. Router dispatch, role resolution, '
          'and spawning are coordinator-only.\n'
          '{writes}'
          'Hard limits: never push to main, merge, force-push, deploy, send customer-facing messages, '
          'or print or copy credentials. The coordinator integrates your branch.\n'
          'End with a final message of at most 10 lines: outcome, files touched, commits, '
          'verification you ran with its result, and open issues.\n\n')
PRE_COMMIT = ('#!/bin/sh\n# pstack worker guard: commits stay on the task branch.\n'
              'branch=$(git symbolic-ref --quiet --short HEAD || echo detached)\n'
              'if [ "$branch" != "$PSTACK_TASK_BRANCH" ]; then\n'
              '  echo "pstack: commit only on $PSTACK_TASK_BRANCH, not $branch" >&2\n  exit 1\nfi\n')
PRE_PUSH = ('#!/bin/sh\n# pstack worker guard: no push to main, no deletion, no force-push.\n'
            'input=$(cat)\n'
            'deny() { echo "pstack: refused $1" >&2; exit 1; }\n'
            'while read -r local_ref local_sha remote_ref remote_sha; do\n'
            '  [ -n "$remote_ref" ] || continue\n'
            '  case "$remote_ref" in refs/heads/main|refs/heads/master) deny "push to $remote_ref";; esac\n'
            '  case "$local_sha" in *[!0]*) ;; *) deny "deletion of $remote_ref";; esac\n'
            '  case "$remote_sha" in *[!0]*) git merge-base --is-ancestor "$remote_sha" "$local_sha" 2>/dev/null '
            '|| deny "force-push to $remote_ref";; esac\n'
            'done <<EOF\n$input\nEOF\n')
CHAIN = 'if [ -x "{hook}" ]; then printf \'%s\\n\' "${{input:-}}" | "{hook}" "$@" || exit $?; fi\n'


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def save(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(temporary, path)


def git(cwd, *args, check=True):
    result = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError('git ' + ' '.join(args) + ': ' + result.stderr.strip())
    return result.stdout.strip()


def start_identity(pid):
    """Kernel start time distinguishes a live owner from a recycled PID."""
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def environment(provider, hooks=None, branch=None):
    # The worker inherits the host environment; only other model vendors' keys are withheld.
    foreign = set().union(*KEYS.values()) - KEYS[provider]
    env = {k: v for k, v in os.environ.items() if k not in foreign}
    if hooks:
        count = int(env.get('GIT_CONFIG_COUNT') or 0)
        env.update({'GIT_CONFIG_COUNT': str(count + 1), f'GIT_CONFIG_KEY_{count}': 'core.hooksPath',
                    f'GIT_CONFIG_VALUE_{count}': str(hooks), 'PSTACK_TASK_BRANCH': branch or ''})
    if provider == 'grok':
        env['GROK_DISABLE_AUTOUPDATER'] = '1'
        for vendor in ('CURSOR', 'CLAUDE'):
            for surface in ('SKILLS', 'RULES', 'AGENTS', 'MCPS', 'HOOKS', 'SESSIONS'):
                env[f'GROK_{vendor}_{surface}_ENABLED'] = '0'
    return env


def project_root(value):
    start = Path(value).resolve() if value else Path.cwd()
    # The common directory maps a linked worktree back to the project that owns the runs.
    common = git(start, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    return Path(common).parent if Path(common).name == '.git' else Path(git(start, 'rev-parse', '--show-toplevel'))


def run_directory(project, task):
    if not TASK.match(task):
        raise ValueError('task id must match ' + TASK.pattern)
    return project / '.pstack/runs' / task


def worktree_root(project):
    override = os.environ.get('PSTACK_WORKTREE_ROOT')
    return Path(override).resolve() if override else project.parent / '.pstack-worktrees' / project.name


def ensure_worktree(project, task, base):
    """Create or reuse the task's own worktree; return (path, branch, base commit)."""
    path, branch = worktree_root(project) / task, 'pstack/' + task
    registered = {line[9:] for line in git(project, 'worktree', 'list', '--porcelain').splitlines()
                  if line.startswith('worktree ')}
    if str(path) in registered:
        return path, branch, git(path, 'merge-base', 'HEAD', base or 'HEAD')
    if path.exists():
        raise RuntimeError(f'{path} exists but is not a registered worktree of this project')
    commit = git(project, 'rev-parse', '--verify', (base or 'HEAD') + '^{commit}')
    path.parent.mkdir(parents=True, exist_ok=True)
    if git(project, 'rev-parse', '--verify', '--quiet', 'refs/heads/' + branch, check=False):
        git(project, 'worktree', 'add', str(path), branch)
    else:
        git(project, 'worktree', 'add', '-b', branch, str(path), commit)
    return path, branch, commit


def guard_hooks(run, cwd, branch):
    """Per-run Git hooks holding the cheap guardrails; the project's own hooks still run."""
    hooks = run / 'hooks'
    shutil.rmtree(hooks, ignore_errors=True)
    hooks.mkdir()
    own = git(cwd, 'rev-parse', '--path-format=absolute', '--git-path', 'hooks', check=False)
    guards = {'pre-push': PRE_PUSH, **({'pre-commit': PRE_COMMIT} if branch else {})}
    for existing in sorted(Path(own).iterdir()) if own and Path(own).is_dir() else []:
        if existing.name not in guards and not existing.name.endswith('.sample'):
            (hooks / existing.name).symlink_to(existing)
    for name, body in guards.items():
        (hooks / name).write_text(body + CHAIN.format(hook=Path(own) / name if own else ''))
        (hooks / name).chmod(0o755)
    return hooks


def diffstat(cwd, base):
    """Committed plus uncommitted change against the task base, untracked files included."""
    try:
        git(cwd, 'add', '-A', '-N', '.')
        lines = git(cwd, 'diff', '--stat=100', base).splitlines()
    except RuntimeError as error:
        return {'error': str(error)}
    return {'summary': lines[-1].strip() if lines else 'no changes', 'files': [line.strip() for line in lines[:-1]][:40]}


def bindings(project, provider, role):
    """Model and effort from project config; a role must actually name this provider."""
    path = project / '.pstack/config.json'
    config = json.loads(path.read_text()) if path.is_file() else {}
    host = config.get('host_bindings', {}).get('claude-code', {})
    chosen = dict(host.get('workers', {}).get(provider, {}))
    if role:
        binding = config.get('roles', {}).get(role)
        entries = binding if isinstance(binding, list) else [binding]
        matches = [e for e in entries if isinstance(e, dict) and e.get('provider') == provider]
        if not matches:
            raise ValueError(f'role {role!r} has no {provider} binding in .pstack/config.json; no silent fallback')
        chosen.update({k: matches[0][k] for k in ('model', 'effort') if matches[0].get(k)})
    return chosen.get('model'), chosen.get('effort')


def command(provider, mode, cwd, run, model, effort, session, resume, permission=None, lean=True):
    """Full-autonomy flags per CLI: no sandbox, no approvals. Returns (argv, stdin path or None).

    Isolation is the task worktree; read mode is a brief contract, not a tool restriction.
    A lean worker skips the host's plugins, skills and MCP connectors: a scoped brief names its
    resources by path, and the connectors roughly double the fixed token cost of every turn.
    """
    prompt = run / 'prompt.txt'
    if provider == 'codex':
        argv = ['codex', 'exec'] + (['resume', resume] if resume else [])
        argv += ['--json', '--skip-git-repo-check', '-o', str(run / 'last-message.txt'),
                 '--dangerously-bypass-approvals-and-sandbox']
        argv += [] if resume else ['-C', str(cwd)]
        argv += ['--disable', 'plugins', '--disable', 'apps'] if lean else []
        if model:
            argv += ['-m', model]
        if effort:
            argv += ['-c', f'model_reasoning_effort="{effort}"']
        return argv + ['-'], prompt
    if provider == 'grok':
        argv = ['grok', '--prompt-file', str(prompt), '--output-format', 'streaming-json', '--cwd', str(cwd),
                '--permission-mode', permission or 'bypassPermissions']
        argv += [] if permission else ['--always-approve']
        argv += ['--resume', resume] if resume else ['--session-id', session]
        if model:
            argv += ['-m', model]
        if effort:
            argv += ['--reasoning-effort', effort]
        return argv, None
    argv = ['claude', '-p', '--output-format', 'stream-json', '--verbose']
    argv += ['--resume', resume] if resume else ['--session-id', session]
    argv += ['--permission-mode', permission] if permission else ['--dangerously-skip-permissions']
    argv += ['--strict-mcp-config', '--disable-slash-commands'] if lean else []
    if model:
        argv += ['--model', model]
    if effort:
        argv += ['--effort', effort]
    return argv, prompt


class Parser:
    """Reduce a provider event stream to session, final message, usage, cost and terminal state."""

    def __init__(self, provider, session=None):
        self.provider, self.session, self.message, self.buffer = provider, session, '', ''
        self.usage, self.cost, self.terminal, self.error = None, None, False, None

    def feed(self, event):
        kind = event.get('type')
        if self.provider == 'codex':
            item = event.get('item') or {}
            if kind == 'thread.started':
                self.session = event.get('thread_id') or self.session
            elif kind == 'item.completed' and item.get('type') == 'agent_message':
                self.message = item.get('text') or self.message
            elif kind == 'turn.completed':
                self.usage, self.terminal = event.get('usage'), True
            elif kind in ('error', 'turn.failed'):
                self.error = json.dumps(event.get('error') or event.get('message') or event)[:400]
        elif self.provider == 'grok':
            if kind == 'text':
                self.buffer += event.get('data') or ''
            elif kind == 'end':
                self.flush()
                self.session = event.get('sessionId') or self.session
                self.usage, self.cost = event.get('usage'), event.get('total_cost_usd')
                self.terminal = event.get('stopReason') == 'end_turn'
                if not self.terminal:
                    self.error = 'stopReason=' + str(event.get('stopReason'))
            elif kind == 'error':
                self.error = json.dumps(event)[:400]
            elif kind == 'tool_call':
                # A tool call ends the current text segment; the last segment is the answer.
                self.flush()
        else:
            if kind == 'system' and event.get('subtype') == 'init':
                self.session = event.get('session_id') or self.session
            elif kind == 'result':
                self.session = event.get('session_id') or self.session
                self.message = event.get('result') or self.message
                self.usage, self.cost = event.get('usage'), event.get('total_cost_usd')
                self.terminal = not event.get('is_error') and event.get('subtype') == 'success'
                if not self.terminal:
                    self.error = 'result subtype=' + str(event.get('subtype'))

    def flush(self):
        if self.buffer.strip():
            self.message = self.buffer.strip()
        self.buffer = ''


def stop_group(process, grace=5.0):
    for signum in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            continue


def reap(previous):
    """Stop a worker whose runner died; the next attempt must not share the worktree with it."""
    pid = (previous or {}).get('pid')
    if not pid or previous.get('state') in TERMINAL:
        return
    try:
        # The recorded cwd tells this worker from an unrelated process that reused the PID.
        if os.readlink(f'/proc/{pid}/cwd') == previous.get('cwd'):
            os.killpg(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


def execute(args, project, resume=False):
    run = run_directory(project, args.task)
    status_path = run / 'status.json'
    if resume and not status_path.is_file():
        raise ValueError('nothing to resume: no recorded session for ' + args.task)
    run.mkdir(parents=True, exist_ok=True)
    os.chmod(run, 0o700)
    lock = open(run / 'lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise ValueError(f'task {args.task} is already running') from None
    # Status is read under the lock so a second resume sees the attempt the first one recorded.
    previous = json.loads(status_path.read_text()) if status_path.is_file() else None
    if resume:
        if not previous or not previous.get('session_id'):
            raise ValueError('nothing to resume: no recorded session for ' + args.task)
        provider, mode = previous['provider'], args.mode or previous['mode']
    else:
        if previous and not args.force:
            raise ValueError(f'task {args.task} already has a run ({previous["state"]}); use resume, or run --force')
        provider, mode = args.provider, args.mode or 'write'
    brief = Path(args.brief).resolve()
    text = brief.read_text()
    if not text.strip():
        raise ValueError('brief is empty: ' + str(brief))
    resources = worker_resources.resolve(project, text)
    reap(previous)
    if resume:
        cwd, branch, base = Path(previous['cwd']), previous.get('branch'), previous.get('base')
        model, effort = args.model or previous.get('model'), args.effort or previous.get('effort')
        session, attempt = previous['session_id'], previous.get('attempt', 1) + 1
    else:
        model, effort = bindings(project, provider, args.role)
        model, effort = args.model or model, args.effort or effort
        session, attempt = str(uuid.uuid4()), (previous or {}).get('attempt', 0) + 1
        if args.cwd:
            cwd, branch = Path(args.cwd).resolve(), None
            base = git(cwd, 'rev-parse', 'HEAD', check=False) or None
        elif mode == 'read' and not args.worktree:
            cwd, branch, base = project, None, git(project, 'rev-parse', 'HEAD')
        else:
            cwd, branch, base = ensure_worktree(project, args.task, args.base)
    if not cwd.is_dir():
        raise ValueError('working directory is gone: ' + str(cwd))

    where = f'a dedicated git worktree on branch `{branch}`' if branch else f'`{cwd}`'
    if mode == 'read':
        writes = 'This is a read-only task: do not edit tracked files or commit.\n'
    elif branch:
        writes = (f'Commit your finished work on `{branch}` in this worktree, and only there. '
                  'Do not touch other branches or worktrees.\n')
    else:
        writes = 'Leave your changes uncommitted in this directory.\n'
    (run / 'brief.md').write_text(text)
    save(run / 'resources.json', resources)
    (run / 'prompt.txt').write_text(HEADER.format(task=args.task, provider=provider, mode=mode, where=where, writes=writes)
                                    + worker_resources.prompt(resources, text))
    for name in ('brief.md', 'prompt.txt', 'resources.json'):
        os.chmod(run / name, 0o600)
    if args.permission_mode and provider == 'codex':
        raise ValueError('--permission-mode applies to grok and claude; codex always runs with full access')
    lean = not args.full_context if args.full_context is not None else (previous or {}).get('lean', True) if resume else True
    argv, stdin_path = command(provider, mode, cwd, run, model, effort, session, session if resume else None,
                               args.permission_mode, lean)
    executable = shutil.which(os.environ.get(provider.upper() + '_BINARY') or argv[0])
    if not executable:
        raise ValueError(provider + ' CLI is not installed')
    argv[0] = executable
    limits = {key: getattr(args, key) if getattr(args, key) is not None else DEFAULTS[key] for key in DEFAULTS}
    status = {'schema_version': 1, 'task_id': args.task, 'provider': provider, 'mode': mode, 'state': 'starting',
              'attempt': attempt, 'attempts': history(previous),
              'totals': None, 'lean': lean, 'role': getattr(args, 'role', None) or (previous or {}).get('role'),
              'model': model, 'effort': effort, 'session_id': session if provider != 'codex' or resume else None,
              'pid': None, 'runner_pid': os.getpid(), 'runner_start': start_identity(os.getpid()),
              'exit_code': None, 'cost_usd': None, 'usage': None, 'summary': None, 'error': None,
              'project': str(project), 'cwd': str(cwd), 'branch': branch, 'base': base, 'diffstat': None,
              'started_at': now(), 'ended_at': None, 'duration_s': None, 'limits': limits, 'argv': argv,
              'events': str(run / 'events.jsonl'), 'stderr': str(run / 'stderr.log'),
              'last_message': str(run / 'last-message.txt')}
    final = run / 'last-message.txt'
    if final.is_file() and status['attempts']:
        # The earlier attempt's full answer stays readable beside its cost and duration.
        kept = run / f'last-message.{status["attempts"][-1]["attempt"]}.txt'
        final.replace(kept)
        status['attempts'][-1]['last_message'] = str(kept)
    final.unlink(missing_ok=True)
    save(status_path, status)

    events = open(run / 'events.jsonl', 'a')

    def log(kind, **fields):
        events.write(json.dumps({'type': 'pstack.' + kind, 'at': now(), 'attempt': attempt, **fields}) + '\n')
        events.flush()

    started = time.monotonic()
    process = subprocess.Popen(argv, cwd=cwd, env=environment(provider, guard_hooks(run, cwd, branch), branch),
                               start_new_session=True,
                               stdin=open(stdin_path) if stdin_path else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=open(run / 'stderr.log', 'a'), text=True, errors='replace')
    status.update(pid=process.pid)
    save(status_path, status)
    log('started', provider=provider, pid=process.pid, mode=mode, model=model, effort=effort, cwd=str(cwd))
    print(json.dumps({'event': 'pstack.started', 'task_id': args.task, 'provider': provider, 'pid': process.pid,
                      'run': str(run)}), flush=True)

    lines = queue.Queue()

    def pump():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)
    threading.Thread(target=pump, daemon=True).start()
    stop = {'state': None}

    def interrupted(signum, frame):
        stop['state'] = 'killed'
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)

    parser = Parser(provider, status['session_id'])
    seen, last = 0, started
    while True:
        try:
            line = lines.get(timeout=0.5)
        except queue.Empty:
            line = ''
        if line is None:
            break
        clock = time.monotonic()
        if line:
            seen, last = seen + 1, clock
            try:
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError
                events.write(line if line.endswith('\n') else line + '\n')
                parser.feed(event)
            except ValueError:
                events.write(json.dumps({'type': 'pstack.raw', 'line': line.rstrip('\n')[:2000]}) + '\n')
            reported = (parser.cost, parser.usage) != (status['cost_usd'], status['usage'])
            if status['state'] == 'starting' or parser.session != status['session_id'] or reported:
                # Cost and usage are saved as reported, so a runner killed after the answer still accounts for it.
                status.update(state='running', session_id=parser.session, cost_usd=parser.cost, usage=parser.usage,
                              duration_s=round(clock - started, 1))
                save(status_path, status)
        if not stop['state']:
            if not seen and limits['startup_timeout'] and clock - started > limits['startup_timeout']:
                stop['state'] = 'startup_timeout'
            elif seen and limits['idle_timeout'] and clock - last > limits['idle_timeout']:
                stop['state'] = 'stalled'
            elif limits['timeout'] and clock - started > limits['timeout']:
                stop['state'] = 'timeout'
        if stop['state']:
            log('stopping', reason=stop['state'])
            stop_group(process)
            break
    while not stop['state']:
        # A worker can close its output and keep running; the whole-run deadline still applies.
        try:
            process.wait(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            if limits['timeout'] and time.monotonic() - started > limits['timeout']:
                stop['state'] = 'timeout'
                log('stopping', reason='timeout')
                stop_group(process)
    code = process.wait()
    stop_group(process, grace=1.0)
    parser.flush()
    events.flush()

    message = parser.message
    if provider == 'codex' and final.is_file() and final.read_text().strip():
        message = final.read_text().strip()
    else:
        final.write_text(message + ('\n' if message else ''))
    if stop['state']:
        state = stop['state']
    elif code == 0 and parser.terminal and message.strip():
        state = 'succeeded'
    else:
        state = 'failed'
    error = None
    if state != 'succeeded':
        tail = (run / 'stderr.log').read_text(errors='replace').strip().splitlines()[-3:]
        error = parser.error or ('no successful terminal event' if code == 0 else ' | '.join(tail)[:400] or f'exit {code}')
    summary = message.strip()
    truncated = len(summary) > SUMMARY_LIMIT
    if truncated:
        summary = summary[:SUMMARY_LIMIT].rstrip() + ' …'
    status.update(state=state, exit_code=code, session_id=parser.session, cost_usd=parser.cost, usage=parser.usage,
                  summary=summary or None, summary_truncated=truncated, error=error, ended_at=now(),
                  duration_s=round(time.monotonic() - started, 1),
                  diffstat=diffstat(cwd, base) if base and (branch or mode == 'write') else None)
    status['attempts'].append({key: status.get(key) for key in ATTEMPT_KEYS})
    status['totals'] = totals(status['attempts'])
    save(status_path, status)
    log('finished', state=state, exit_code=code)
    events.close()
    print(json.dumps(receipt(status)), flush=True)
    return EXIT.get(state, 1)


def history(previous):
    """Earlier attempts of a task; a status written before attempts were kept counts as one."""
    if not previous:
        return []
    attempts = list(previous.get('attempts') or [])
    if not any(entry.get('attempt') == previous.get('attempt') for entry in attempts):
        entry = {key: previous.get(key) for key in ATTEMPT_KEYS}
        if entry['state'] not in TERMINAL:
            entry['state'] = 'lost'
        attempts.append(entry)
    return attempts


def totals(attempts):
    """Sums over every attempt; cost stays null when no attempt reported one."""
    costs = [entry['cost_usd'] for entry in attempts if entry.get('cost_usd') is not None]
    return {'attempts': len(attempts), 'cost_usd': round(sum(costs), 6) if costs else None,
            'duration_s': round(sum(entry.get('duration_s') or 0 for entry in attempts), 1)}


def receipt(status):
    """One line for the coordinator: cost_usd and duration_s are this attempt, total_* cover the task."""
    keys = ('task_id', 'provider', 'state', 'exit_code', 'model', 'effort', 'session_id', 'attempt', 'cost_usd',
            'duration_s', 'summary', 'summary_truncated', 'last_message', 'error', 'cwd', 'branch')
    result = {key: status.get(key) for key in keys}
    overall = status.get('totals') or {}
    result.update(total_cost_usd=overall.get('cost_usd'), total_duration_s=overall.get('duration_s'))
    result['diffstat'] = (status.get('diffstat') or {}).get('summary')
    return result


def load(project, task):
    """Stored status, with a dead owner reported as lost rather than running forever."""
    path = run_directory(project, task) / 'status.json'
    if not path.is_file():
        raise ValueError('no run for task ' + task)
    status = json.loads(path.read_text())
    if status['state'] not in TERMINAL and start_identity(status['runner_pid']) != status['runner_start']:
        status.update(state='lost', error='runner exited without a terminal receipt')
    return status


def kill(project, task):
    status = load(project, task)
    if status['state'] in TERMINAL:
        return status
    os.kill(status['runner_pid'], signal.SIGTERM)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and start_identity(status['runner_pid']) == status['runner_start']:
        time.sleep(0.2)
    if status.get('pid'):
        # The worker leads its own process group; clear anything the runner left behind.
        try:
            os.killpg(status['pid'], signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return load(project, task)


def clean(project, task, force):
    status = load(project, task)
    if status['state'] not in TERMINAL:
        raise ValueError('task is still running; kill it first')
    if not status.get('branch'):
        return {'task_id': task, 'removed': None}
    git(project, 'worktree', 'remove', *(['--force'] if force else []), status['cwd'])
    git(project, 'branch', '-D' if force else '-d', status['branch'], check=False)
    return {'task_id': task, 'removed': status['cwd']}


def doctor():
    report = {}
    for provider, probe in (('codex', ['login', 'status']), ('grok', ['models']), ('claude', ['auth', 'status'])):
        executable = shutil.which(os.environ.get(provider.upper() + '_BINARY') or provider)
        entry = {'executable': executable, 'version': None, 'login': 'unknown'}
        if executable:
            try:
                version = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=30)
                entry['version'] = (version.stdout or version.stderr).strip().splitlines()[0]
                login = subprocess.run([executable, *probe], capture_output=True, text=True, timeout=60,
                                       stdin=subprocess.DEVNULL, env=environment(provider))
                entry['login'] = 'ok' if login.returncode == 0 else 'failed'
            except (OSError, subprocess.TimeoutExpired, IndexError) as error:
                entry['login'] = 'probe failed: ' + type(error).__name__
        report[provider] = entry
    # Login preflight is cached credential availability, not a live model run.
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog='pstack-run', description=__doc__)
    parser.add_argument('--project', help='Project checkout; default is the Git project of the current directory')
    commands = parser.add_subparsers(dest='action', required=True)

    def limits(sub):
        sub.add_argument('--mode', choices=MODES)
        sub.add_argument('--model')
        sub.add_argument('--effort')
        sub.add_argument('--permission-mode', choices=('bypassPermissions', 'auto', 'acceptEdits', 'dontAsk', 'plan', 'default'),
                         help='Narrow the grok or claude permission mode for one run; the default is full bypass')
        sub.add_argument('--timeout', type=float, help='Whole-run deadline in seconds; 0 disables')
        sub.add_argument('--startup-timeout', type=float, help='Seconds allowed before the first event; 0 disables')
        sub.add_argument('--idle-timeout', type=float, help='Seconds allowed between events; 0 disables')
        sub.add_argument('--full-context', action='store_true', default=None,
                         help='Load the host plugins, skills and MCP connectors into the worker; default is lean')

    run = commands.add_parser('run', help='Start a worker and wait for its terminal receipt')
    run.add_argument('provider', choices=PROVIDERS)
    run.add_argument('task')
    run.add_argument('brief')
    run.add_argument('--role', help='Role label in .pstack/config.json supplying model and effort')
    run.add_argument('--base', help='Commit the task worktree starts from; default HEAD')
    run.add_argument('--cwd', help='Run in this existing directory instead of a task worktree')
    run.add_argument('--worktree', action='store_true', help='Give a read task its own worktree too')
    run.add_argument('--force', action='store_true', help='Start over on a task id that already has a run')
    limits(run)
    again = commands.add_parser('resume', help='Continue the recorded session with a follow-up brief')
    again.add_argument('task')
    again.add_argument('brief')
    limits(again)
    for name, text in (('status', 'Print one receipt, or every task without an id'), ('kill', 'Stop a running worker'),
                       ('diff', 'Show the task change against its base'), ('clean', 'Remove a finished task worktree')):
        sub = commands.add_parser(name, help=text)
        sub.add_argument('task', nargs='?' if name == 'status' else None)
        if name == 'status':
            sub.add_argument('--full', action='store_true', help='Whole status.json instead of the receipt')
        if name == 'diff':
            sub.add_argument('--patch', action='store_true', help='Full patch suitable for git apply')
        if name == 'clean':
            sub.add_argument('--force', action='store_true', help='Discard uncommitted worker changes and the branch')
    commands.add_parser('doctor', help='Report installed CLIs and cached logins')
    dispatch_policy.arguments(commands.add_parser('decide', help='Route one unit of work and log the decision'))
    panel_divergence.arguments(commands.add_parser('divergence', help='Check panel candidates are independent and distinct'))
    args = parser.parse_args(argv)
    try:
        if args.action == 'doctor':
            print(json.dumps(doctor(), indent=2))
            return 0
        project = project_root(args.project)
        if args.action == 'decide':
            return dispatch_policy.main(args, project)
        if args.action == 'divergence':
            return panel_divergence.main(args, project)
        if args.action == 'run':
            return execute(args, project)
        if args.action == 'resume':
            return execute(args, project, resume=True)
        if args.action == 'status':
            if args.task:
                status = load(project, args.task)
                print(json.dumps(status if args.full else receipt(status), indent=2))
            else:
                runs = project / '.pstack/runs'
                for path in sorted(runs.glob('*/status.json')) if runs.is_dir() else []:
                    print(json.dumps(receipt(load(project, path.parent.name))))
            return 0
        if args.action == 'kill':
            print(json.dumps(receipt(kill(project, args.task))))
            return 0
        if args.action == 'diff':
            status = load(project, args.task)
            if not status.get('base'):
                raise ValueError('task has no recorded base commit')
            git(status['cwd'], 'add', '-A', '-N', '.')
            sys.stdout.write(subprocess.run(['git', '-C', status['cwd'], 'diff', '--binary' if args.patch else '--stat=100',
                                             status['base']], capture_output=True, text=True, check=True).stdout)
            return 0
        print(json.dumps(clean(project, args.task, args.force)))
        return 0
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print('pstack-run: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
