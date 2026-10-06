"""Canonical resource pointers for scoped workers, without coordinator dispatch."""
import hashlib
import json
import os
from pathlib import Path
import re


WORKFLOW = ('Load and apply Poteto Mode, its applicable principles, the matched playbook, and named leaf skills '
            'from the exact canonical paths in the worker resource manifest. Read required_paths in full before work. '
            'The sapsynk-pstack entry supplies engineering guidance; router dispatch, role resolution, task rerouting, '
            'and spawning remain coordinator-only. Preserve bootstrap checks, verification duties, review requirements, '
            'and owner gates. If a required resource cannot be read through your actual tools, stop and report that '
            'capability unavailable. Report prohibited or unsupported workflow steps explicitly. Readable host files '
            'do not prove provider tool access. Do not copy canonical sources, broaden permissions, activate hooks, '
            'or promote learning automatically.\n')
NAMED_PATH = re.compile(r'''[`"'](/[^`"'\n]+(?:/SKILL\.md|/playbooks/[^/`"'\n]+\.md|/agents/[^/`"'\n]+\.md))[`"']|(?<![\w:/])(/[^\s`"'<>]*?(?:/SKILL\.md|/playbooks/[^\s`"'<>]+\.md|/agents/[^\s`"'<>]+\.md))(?=$|[\s`"'<>.,;)])''')


def readable(path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('worker resource requires an absolute path: ' + str(path))
    try:
        if not path.is_file() or not path.stat().st_mode & 0o444:
            raise OSError('missing or unreadable file')
        return path.read_bytes()
    except OSError as error:
        raise ValueError(f'worker resource unavailable: {path}: {error}') from None


def document(path):
    return json.loads(readable(path))


def package_root():
    root = Path(__file__).resolve().parents[1]
    return root if (root / 'framework.json').is_file() else root / 'plugins/sapsynk-pstack'


def plugin_root(name, plugin, lock, named):
    leaves = set(plugin['files'])
    explicit = {path.parents[2] for path in named if path.name == 'SKILL.md'
                and path.parent.parent.name == 'skills'
                and path.relative_to(path.parents[2]).as_posix() in leaves}
    if len(explicit) > 1:
        raise ValueError('worker resource has ambiguous canonical plugin paths: ' + name)
    candidates = sorted(explicit)
    if not candidates:
        home = Path(os.environ.get('PSTACK_HOME', str(Path.home() / '.pstack')))
        candidates.append(home / 'plugins' / lock['source_revision'] / 'plugins' / name)
        version = plugin['version']
        for identifier, cache in (
            (plugin.get('native_plugin_id'), Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'plugins/cache'),
            (plugin.get('claude_plugin_id'), Path.home() / '.claude/plugins/cache'),
        ):
            if identifier:
                slug, _, marketplace = identifier.partition('@')
                candidates.append(cache / marketplace / slug / version)
    errors = []
    for root in candidates:
        try:
            for relative, digest in plugin['files'].items():
                if Path(relative).is_absolute() or '..' in Path(relative).parts:
                    raise ValueError('invalid plugin lock path: ' + relative)
                if hashlib.sha256(readable(root / relative)).hexdigest() != digest:
                    raise ValueError('worker resource differs from plugin lock: ' + str(root / relative))
            return root.resolve()
        except ValueError as error:
            errors.append(str(error))
    raise ValueError('worker resource plugin lock unresolved for ' + name + ': ' + '; '.join(errors))


def resolve(project, brief):
    project, package = Path(project).resolve(), package_root()
    identity_path = package / 'framework.json'
    identity = document(identity_path)
    pin_path = project / '.pstack/framework.lock.json'
    pin = document(pin_path) if pin_path.exists() else None
    if pin is not None:
        for key in ('version', 'source_digest'):
            if identity.get(key) != pin.get(key):
                raise ValueError('worker resource framework differs from project pin: ' + key)
        if identity.get('upstream_commit') != pin.get('upstream_revision'):
            raise ValueError('worker resource upstream differs from project pin')
    named = [Path(quoted or bare) for quoted, bare in NAMED_PATH.findall(brief)]
    required = [identity_path, package / 'adapters/CONTRACT.md', package / 'skills/sapsynk-pstack/SKILL.md',
                package / 'skills/poteto-mode/SKILL.md']
    config_path = project / '.pstack/config.json'
    config = document(config_path) if config_path.exists() else document(package / 'config/defaults.json')
    host = config.get('host', config.get('default_host', 'codex'))
    required.append(package / 'adapters' / ('claude-code.md' if host == 'claude-code' else 'codex.md'))
    required.append(config_path if config_path.exists() else package / 'config/defaults.json')
    if pin is not None:
        required.append(pin_path)
    if (project / 'AGENTS.md').exists():
        required.append(project / 'AGENTS.md')
    project_skills = project / '.agents/skills'
    verification = sorted(project_skills.glob('verify-*/SKILL.md'))
    if (project_skills / 'sapsynk-project/SKILL.md').exists():
        required.append(project_skills / 'sapsynk-project/SKILL.md')
    required.extend(verification)
    plugins = {}
    lock_path = project / '.pstack/plugins.lock.json'
    if lock_path.exists():
        lock = document(lock_path)
        if not re.fullmatch('[0-9a-f]{40}', lock['source_revision']):
            raise ValueError('worker resource plugin lock requires an exact source_revision')
        required.append(lock_path)
        for name, plugin in sorted(lock['plugins'].items()):
            root = plugin_root(name, plugin, lock, named)
            skills = [root / relative for relative in sorted(plugin['files']) if relative.endswith('/SKILL.md')]
            required.extend(skills)
            plugins[name] = {'root': str(root), 'version': plugin['version'],
                             'source_revision': lock['source_revision'], 'required_paths': list(map(str, skills))}
    required.extend(named)
    required = list(dict.fromkeys(map(str, required)))
    for path in required:
        readable(path)
    playbooks = sorted((package / 'skills/poteto-mode/playbooks').glob('*.md'))
    for path in playbooks:
        readable(path)
    return {'schema_version': 1, 'dispatch_owner': 'coordinator', 'required_paths': required,
            'framework': {'root': str(package), 'identity_path': str(identity_path), 'identity': identity},
            'project': {'root': str(project), 'pin_path': str(pin_path) if pin is not None else None,
                        'pin': pin, 'verification_paths': list(map(str, verification))},
            'plugins': plugins, 'playbooks': {path.stem: str(path) for path in playbooks}}


def prompt(manifest, brief):
    return WORKFLOW + '\n--- WORKER RESOURCES ---\n' + json.dumps(manifest, indent=2) + '\n--- BRIEF ---\n' + brief
