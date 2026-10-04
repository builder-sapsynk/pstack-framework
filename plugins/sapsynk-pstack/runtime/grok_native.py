"""Direct Grok tools under an explicitly verified managed host boundary."""
import errno
import json
import os
from pathlib import Path
import shutil
import uuid

DIALECT = {'id': 'grok-build-native-1', 'confinement': 'managed-host'}
REMOVED = ('search_tool', 'use_tool', 'todo_write', 'monitor', 'workflow',
           'enter_plan_mode', 'exit_plan_mode', 'ask_user_question', 'send_feedback',
           'image_gen', 'image_edit', 'image_to_video', 'reference_to_video', 'write')
READ_TOOLS = {'read_file', 'list_dir', 'grep'}
WRITE_TOOLS = {'search_replace'}


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


def prepare_home(job, req, env):
    if req.get('resume_job'):
        previous = Path(req['resume_job']).resolve()
        base = (Path(req['project']) / '.pstack/runs').resolve()
        if previous.parent != base or not previous.is_dir():
            raise ValueError('resume_job must be an owned durable job in this project')
        receipt = json.loads((previous / 'receipt.json').read_text())
        if receipt.get('status') != 'complete' or receipt.get('request', {}).get('dialect') != DIALECT:
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
        if owner_receipt.get('request', {}).get('dialect') != DIALECT or any(owner_receipt.get(key) != req.get(key) for key in ('provider', 'model', 'cwd', 'mode')):
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
    text = '[cli]\nauto_update = false\n[session]\nload_envrc = false\n[memory]\nenabled = false\n[subagents]\nenabled = false\n[features]\nweb_fetch = false\nlsp_tools = false\n'
    for vendor in ('cursor', 'claude'):
        text += '[compat.' + vendor + ']\n'
        for feature in ('skills', 'rules', 'agents', 'mcps', 'hooks'):
            text += feature + ' = false\n'
    (home / 'config.toml').write_text(text)
    os.chmod(home / 'config.toml', 0o600)
    return str(home), None


def normalize(output, req):
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
