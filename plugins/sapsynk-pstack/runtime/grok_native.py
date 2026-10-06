"""Direct Grok tools under an explicitly verified managed host boundary."""
import errno
import json
import os
from pathlib import Path
import shutil
import uuid

DIALECT = {'id': 'grok-build-native-1', 'confinement': 'managed-host'}
TASK_DIALECT = {'id': 'grok-build-native-task-1', 'confinement': 'managed-host'}
REMOVED = ('search_tool', 'use_tool', 'todo_write', 'monitor', 'workflow',
           'enter_plan_mode', 'exit_plan_mode', 'ask_user_question', 'send_feedback',
           'image_gen', 'image_edit', 'image_to_video', 'reference_to_video', 'write')
READ_TOOLS = {'read_file', 'list_dir', 'grep'}
WRITE_TOOLS = {'search_replace'}
# Official edit/create ids. The task profile does not treat this tuple as the init inventory.
EDIT_TOOLS = ('search_replace', 'write', 'write_file')
TERMINAL_REACH = 'trusted terminal can exceed user-authorized instructions unless the host sandbox enforces them'
WRITER_SCOPE = 'recorded direct file calls are checked against the worktree after execution; terminal, child and deferred tool dispatch are not confined by this check'
TASK_HEADER = ('You are the assigned external worker for this bounded request. Complete the brief below in your assigned role. Do not activate a framework router, reroute this task, or delegate to another provider. Role resolution and spawning remain coordinator-only. Respect the managed host sandbox and report unsupported capabilities.\n\n'
               'User-authorized scope is an instruction and is distinct from tool enforcement. A trusted terminal can exceed user-authorized instructions unless the host sandbox enforces them. Bash allow rules do not create semantic merge, push, or deploy restrictions. Read canonical paths inside the declared host boundary. Write files only in the assigned worktree. Credentials, private transcripts, and caller data stay excluded.\n\n')
LEGACY_HOME = '[cli]\nauto_update = false\n[session]\nload_envrc = false\n[memory]\nenabled = false\n[subagents]\nenabled = false\n[features]\nweb_fetch = false\nlsp_tools = false\n'


def validate_boundary(value, cwd):
    if not isinstance(value, dict) or set(value) != {'host', 'writable_roots', 'read_only_probe'}:
        raise ValueError('managed-host requires host, writable_roots and read_only_probe declaration')
    if value['host'] != 'codex-managed-exec':
        raise ValueError('direct native tools require a verified supported managed execution host')
    roots = value['writable_roots']
    probe = value['read_only_probe']
    if not isinstance(roots, list) or not roots or any(not isinstance(p, str) or not Path(p).is_absolute() for p in roots):
        raise ValueError('writable_roots requires absolute host-declared paths')
    if not isinstance(probe, str) or not Path(probe).is_absolute() or not Path(probe).is_dir():
        raise ValueError('read_only_probe requires an existing absolute directory')
    directory = Path(cwd).resolve()
    if not any(directory == Path(p).resolve() or Path(p).resolve() in directory.parents for p in roots):
        raise ValueError('cwd outside declared writable roots')
    if any(Path(probe).resolve() == Path(p).resolve() or Path(p).resolve() in Path(probe).resolve().parents for p in roots):
        raise ValueError('boundary probe must lie outside writable roots')
    return value


def probe_boundary(value):
    target = Path(value['read_only_probe']) / ('pstack-boundary-' + uuid.uuid4().hex)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        if error.errno not in (errno.EROFS, errno.EACCES, errno.EPERM):
            raise ValueError('host boundary probe failed unexpectedly') from error
        return {'kind': 'outside-write-denied', 'errno': error.errno,
                'directory': value['read_only_probe'], 'scope': 'one observed filesystem boundary; host declaration supplies remaining policy'}
    else:
        os.close(fd)
        target.unlink()
        raise ValueError('managed host filesystem boundary absent; direct tools refused')


def tools(req):
    selected = set(READ_TOOLS)
    if req['mode'] == 'isolated-write': selected.update(WRITE_TOOLS)
    if req.get('allowed_commands'): selected.add('run_terminal_command')
    return selected


def argv(req):
    selected = tools(req)
    removed = set(REMOVED) | (READ_TOOLS | WRITE_TOOLS | {'run_terminal_command'} - selected)
    removed -= selected
    result = ['--tools', ','.join(sorted(selected)), '--disallowed-tools', ','.join(sorted(removed)),
              '--no-plan', '--allow', 'Read']
    if req['mode'] == 'isolated-write': result += ['--allow', 'Edit']
    for command in req.get('allowed_commands', []):
        if any(character in command for character in ';|&<>`$\\\n\r*?[]{}'):
            raise ValueError('native commands must be literal safe commands without shell metacharacters')
        result += ['--allow', 'Bash(' + command + ')']
    return result


def capability_scope(mode):
    if mode not in ('read-only', 'isolated-write'):
        raise ValueError('unsupported mode')
    return {
        'builtin_tools': 'official-discovered',
        'terminal': 'autonomous',
        'web': 'fetch-and-search',
        'files': 'create-and-edit' if mode == 'isolated-write' else 'read',
        'child_agents': 'where-available',
        'authorization': 'user-scope-distinct-from-tool-enforcement',
        'terminal_reach': 'trusted-terminal-broader-than-instruction-unless-host-enforced',
    }


def disallowed_tools(req):
    # Read-only file tools remain an optional lane; this is not an init inventory.
    names = []
    if req['mode'] != 'isolated-write': names += list(EDIT_TOOLS)
    return names


def validate_task(req):
    if req.get('capability_scope') != capability_scope(req['mode']):
        raise ValueError('native task profile requires the explicit capability scope for this mode')
    if req.get('allowed_commands'):
        raise ValueError('task profile does not use exact command grants; terminal reach follows the host sandbox')
    task_argv(req)
    return req['capability_scope']


def task_argv(req):
    # No --tools allowlist: a hardcoded list is not the trusted CLI inventory.
    # Wildcard is the documented rule for native tools such as spawn_subagent.
    # This is explicit task authority, not semantic command or data confinement.
    result = ['--allow', '*']
    removed = disallowed_tools(req)
    if removed: result += ['--disallowed-tools', ','.join(removed)]
    return result


def home_config(dialect, mode):
    if dialect == TASK_DIALECT:
        write = 'true' if mode == 'isolated-write' else 'false'
        text = '[cli]\nauto_update = false\n[session]\nload_envrc = false\n[memory]\nenabled = true\n[subagents]\nenabled = true\n[features]\nweb_fetch = true\nwrite_file = ' + write + '\nlsp_tools = true\n'
    else:
        text = LEGACY_HOME
    for vendor in ('cursor', 'claude'):
        text += '[compat.' + vendor + ']\n'
        for feature in ('skills', 'rules', 'agents', 'mcps', 'hooks'):
            text += feature + ' = false\n'
    return text


def availability(discovered):
    groups = {
        'file_read': {'read_file', 'list_dir', 'grep'},
        'file_edit': set(EDIT_TOOLS),
        'terminal': {'run_terminal_command'},
        'web_search': {'web_search'},
        'web_fetch': {'web_fetch'},
        'child_agents': {'spawn_subagent'},
    }
    known = set().union(*groups.values())
    report = {}
    for name, names in groups.items():
        present = sorted(names & discovered)
        report[name] = {'tools': present, 'status': 'observed-in-init' if present else 'unverified'}
    report['other_official_tools'] = sorted(discovered - known)
    return report


def prepare_home(job, req, env):
    expected = req.get('dialect', DIALECT)
    if expected not in (DIALECT, TASK_DIALECT):
        raise ValueError('unsupported native dialect')
    if req.get('resume_job'):
        previous = Path(req['resume_job']).resolve()
        base = (Path(req['project']) / '.pstack/runs').resolve()
        if previous.parent != base or not previous.is_dir():
            raise ValueError('resume_job must be an owned durable job in this project')
        receipt = json.loads((previous / 'receipt.json').read_text())
        if receipt.get('status') != 'complete' or receipt.get('request', {}).get('dialect') != expected:
            raise ValueError('only a complete managed-host job can be resumed')
        if any(receipt.get(key) != req.get(key) for key in ('provider', 'model', 'cwd', 'mode')):
            raise ValueError('resumption must preserve provider/model/cwd/mode')
        session = receipt.get('metrics', {}).get('session_id')
        uuid.UUID(session)
        home = Path(receipt['grokHome'])
        home = home.resolve()
        owner = home.parent
        if owner.parent != base or home.name != 'grok-home' or not home.is_dir():
            raise ValueError('untrusted persisted Grok home')
        owner_receipt = json.loads((owner / 'receipt.json').read_text())
        if owner_receipt.get('request', {}).get('dialect') != expected or any(owner_receipt.get(key) != req.get(key) for key in ('provider', 'model', 'cwd', 'mode')):
            raise ValueError('persisted session owner mismatch')
        return str(home), session
    home = job / 'grok-home'
    home.mkdir(mode=0o700)
    original = Path(env.get('GROK_HOME', str(Path.home() / '.grok'))).resolve()
    auth = original / 'auth.json'
    if not auth.is_file(): raise ValueError('existing Grok OAuth profile unavailable')
    (home / 'auth.json').symlink_to(auth)
    catalog = original / 'models_cache.json'
    if catalog.is_file(): shutil.copyfile(catalog, home / 'models_cache.json')
    text = home_config(expected, req.get('mode'))
    (home / 'config.toml').write_text(text)
    os.chmod(home / 'config.toml', 0o600)
    return str(home), None


def _within(path, root):
    return path == root or root in path.parents


def _resolve_in(cwd, path):
    candidate = Path(path)
    if not candidate.is_absolute(): candidate = Path(cwd) / candidate
    return candidate.resolve()


def _argument_paths(arguments):
    paths = []
    for key in ('path', 'target_file', 'file_path', 'directory', 'target_directory', 'file', 'paths'):
        if key not in arguments: continue
        value = arguments[key]
        items = value if isinstance(value, list) else [value]
        if key == 'paths' and not isinstance(value, list):
            raise ValueError('file tool path absent')
        for item in items:
            if not isinstance(item, str) or not item.strip():
                raise ValueError('file tool path absent')
            paths.append(item)
    return paths


def _task_payload(content):
    if isinstance(content, str):
        try: content = json.loads(content)
        except json.JSONDecodeError: return content
    if not isinstance(content, (dict, list, str, int, float, bool)):
        raise ValueError('native tool payload must use a native result format')
    return content


def _check_task_paths(req, name, arguments):
    paths = _argument_paths(arguments)
    cwd = Path(req['cwd']).resolve()
    if name in set(EDIT_TOOLS):
        if not paths: raise ValueError('file tool path absent')
        for path in paths:
            if not _within(_resolve_in(cwd, path), cwd):
                raise ValueError('native file write outside assigned worktree')
        return
    if name not in READ_TOOLS: return
    if not paths: return
    boundary = req.get('host_boundary') if isinstance(req.get('host_boundary'), dict) else {}
    roots = []
    for root in boundary.get('writable_roots') or []:
        if isinstance(root, str): roots.append(Path(root).resolve())
    for path in paths:
        resolved = _resolve_in(cwd, path)
        if not any(_within(resolved, root) for root in roots):
            raise ValueError('native file read outside declared host boundary')


def normalize_task(output, req):
    if req.get('capability_scope') != capability_scope(req['mode']):
        raise ValueError('native task profile requires the explicit capability scope for this mode')
    records = [json.loads(line) for line in output.splitlines() if line.strip()]
    if not records or not isinstance(records[0], dict): raise ValueError('native init required')
    init = records[0]
    advertised = init.get('tools')
    forbidden = set(disallowed_tools(req))
    if not isinstance(advertised, list) or not advertised or any(not isinstance(name, str) for name in advertised) or len(advertised) != len(set(advertised)) or init.get('mcp_servers') != []:
        raise ValueError('native tool inventory differs from the explicit profile')
    if any(not isinstance(name, str) or not name or '__' in name or name in forbidden for name in advertised):
        raise ValueError('disallowed tool remained in native inventory')
    expected = set(advertised)
    normalized = [dict(init, tools=[])]
    pending, seen, calls, outcomes = {}, set(), [], []
    terminal = False
    for record in records[1:]:
        if terminal: raise ValueError('native event after terminal result')
        if not isinstance(record, dict) or record.get('session_id') != init.get('session_id'):
            raise ValueError('native session changed')
        if record.get('type') == 'assistant':
            message = record.get('message', {})
            if not isinstance(message, dict): raise ValueError('native message must be an object')
            if message.get('model') != req['model'] or message.get('role') != 'assistant':
                raise ValueError('native model mismatch')
            content = message.get('content')
            if not isinstance(content, list) or not content: raise ValueError('empty native content')
            plain, inline = [], None
            for block in content:
                if not isinstance(block, dict): raise ValueError('native content must be an object')
                if block.get('type') == 'tool_use':
                    name, identity, arguments = block.get('name'), block.get('id'), block.get('input')
                    if name not in expected or not isinstance(identity, str) or not identity or identity in seen or not isinstance(arguments, dict):
                        raise ValueError('ungranted or malformed native tool use')
                    if name == 'run_terminal_command':
                        command = arguments.get('command')
                        if not isinstance(command, str) or not command.strip():
                            raise ValueError('native command malformed')
                    if name in set(EDIT_TOOLS) or name in READ_TOOLS:
                        _check_task_paths(req, name, arguments)
                    pending[identity] = name; seen.add(identity)
                    calls.append({'id': identity, 'name': name, 'input': arguments})
                elif block.get('type') == 'server_tool_use':
                    if inline: raise ValueError('unmatched web search result')
                    name, identity, arguments = block.get('name'), block.get('id'), block.get('input')
                    if name != 'web_search' or not isinstance(identity, str) or not identity or identity in seen or not isinstance(arguments, dict):
                        raise ValueError('ungranted or malformed native tool use')
                    seen.add(identity); inline = identity
                    calls.append({'id': identity, 'name': name, 'input': arguments})
                elif block.get('type') == 'web_search_tool_result':
                    identity = block.get('tool_use_id')
                    if identity != inline: raise ValueError('unmatched web search result')
                    payload = block.get('content')
                    if payload is None: raise ValueError('native tool payload must use a native result format')
                    errored = isinstance(payload, dict) and payload.get('type') == 'web_search_tool_result_error'
                    outcomes.append({'id': identity, 'name': 'web_search', 'is_error': errored, 'result': payload})
                    inline = None
                elif block.get('type') in ('text', 'thinking') and isinstance(block.get(block['type']), str): plain.append(block)
                else: raise ValueError('unknown native content block')
            if inline: raise ValueError('unmatched web search result')
            if pending:
                if message.get('stop_reason') != 'tool_use': raise ValueError('invalid tool stop reason')
            elif message.get('stop_reason') == 'tool_use':
                raise ValueError('invalid tool stop reason')
            elif plain:
                normalized.append(dict(record, message=dict(message, content=plain)))
        elif record.get('type') == 'user':
            message = record.get('message', {})
            if not isinstance(message, dict) or message.get('role') != 'user' or not isinstance(message.get('content'), list) or not message['content']:
                raise ValueError('native tool results required')
            for block in message['content']:
                if not isinstance(block, dict): raise ValueError('native result must be an object')
                identity = block.get('tool_use_id')
                if block.get('type') != 'tool_result' or identity not in pending or not isinstance(block.get('is_error'), bool):
                    raise ValueError('failed or unmatched native tool result')
                name = pending.pop(identity)
                if 'content' not in block: raise ValueError('native tool payload must use a native result format')
                outcomes.append({'id': identity, 'name': name, 'is_error': block['is_error'], 'result': _task_payload(block['content'])})
        else:
            if pending: raise ValueError('terminal before native tool completion')
            if record.get('type') == 'result': terminal = True
            normalized.append(record)
    if pending: raise ValueError('unresolved native calls')
    report = availability(expected)
    return '\n'.join(json.dumps(record) for record in normalized), {
        'toolCalls': calls, 'toolOutcomes': outcomes, 'nativeTools': sorted(expected),
        'capabilityAvailability': report, 'terminalReach': TERMINAL_REACH, 'writerScope': WRITER_SCOPE,
        'artifactVerification': 'separate'}


def normalize(output, req):
    if req.get('dialect') == TASK_DIALECT: return normalize_task(output, req)
    records = [json.loads(line) for line in output.splitlines() if line.strip()]
    if not records or not isinstance(records[0], dict): raise ValueError('native init required')
    init = records[0]
    expected = tools(req)
    if not isinstance(init.get('tools'), list) or set(init['tools']) != expected or len(init['tools']) != len(expected) or init.get('mcp_servers') != []:
        raise ValueError('native tool inventory differs from the explicit profile')
    normalized = [dict(init, tools=[])]
    pending, seen, calls, outcomes = {}, set(), [], []
    terminal = False
    for record in records[1:]:
        if terminal: raise ValueError('native event after terminal result')
        if not isinstance(record, dict) or record.get('session_id') != init.get('session_id'):
            raise ValueError('native session changed')
        if record.get('type') == 'assistant':
            if pending: raise ValueError('assistant before pending tool completion')
            message = record.get('message', {})
            if not isinstance(message, dict): raise ValueError('native message must be an object')
            if message.get('model') != req['model'] or message.get('role') != 'assistant':
                raise ValueError('native model mismatch')
            content = message.get('content')
            if not isinstance(content, list) or not content: raise ValueError('empty native content')
            plain = []
            for block in content:
                if not isinstance(block, dict): raise ValueError('native content must be an object')
                if block.get('type') == 'tool_use':
                    name, identity, arguments = block.get('name'), block.get('id'), block.get('input')
                    if name not in expected or not isinstance(identity, str) or not identity or identity in seen or not isinstance(arguments, dict):
                        raise ValueError('ungranted or malformed native tool use')
                    if name == 'run_terminal_command' and arguments.get('command') not in req.get('allowed_commands', []):
                        raise ValueError('native command outside exact grant')
                    if name in ('read_file', 'search_replace'):
                        path = arguments.get('target_file', arguments.get('file_path'))
                        if not isinstance(path, str): raise ValueError('file tool path absent')
                        resolved = (Path(req['cwd']) / path).resolve()
                        if Path(req['cwd']).resolve() not in resolved.parents:
                            raise ValueError('native file access outside assigned cwd')
                    pending[identity] = name; seen.add(identity)
                    calls.append({'id': identity, 'name': name, 'input': arguments})
                elif block.get('type') in ('text', 'thinking') and isinstance(block.get(block['type']), str): plain.append(block)
                else: raise ValueError('unknown native content block')
            if pending:
                if message.get('stop_reason') != 'tool_use': raise ValueError('invalid tool stop reason')
            elif plain:
                normalized.append(dict(record, message=dict(message, content=plain)))
        elif record.get('type') == 'user':
            message = record.get('message', {})
            if not isinstance(message, dict) or message.get('role') != 'user' or not isinstance(message.get('content'), list) or not message['content']:
                raise ValueError('native tool results required')
            for block in message['content']:
                if not isinstance(block, dict): raise ValueError('native result must be an object')
                identity = block.get('tool_use_id')
                if block.get('type') != 'tool_result' or identity not in pending or block.get('is_error') is not False:
                    raise ValueError('failed or unmatched native tool result')
                name = pending.pop(identity)
                payload = json.loads(block['content']) if isinstance(block.get('content'), str) else None
                if not isinstance(payload, dict): raise ValueError('native tool payload must be structured')
                outcomes.append({'id': identity, 'name': name, 'result': payload})
        else:
            if pending: raise ValueError('terminal before native tool completion')
            if record.get('type') == 'result': terminal = True
            normalized.append(record)
    if pending: raise ValueError('unresolved native calls')
    return '\n'.join(json.dumps(record) for record in normalized), {'toolCalls': calls, 'toolOutcomes': outcomes, 'nativeTools': sorted(expected)}
