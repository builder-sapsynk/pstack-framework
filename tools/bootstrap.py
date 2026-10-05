#!/usr/bin/env python3
"""Bind a project to an exact framework commit and optionally install it."""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
from build import VERSION
from install import (CLAUDE_PLUGIN, claude_marketplace, claude_package, codex_marketplace, install, install_claude,
                     managed_block, validate_managed_block)

UPSTREAM = '23e4138daa01c42d4969f7a5465f82704e64f798'
SOURCE = 'https://github.com/builder-sapsynk/pstack-framework.git'
HOSTS = ('codex', 'claude-code')

BOOTSTRAP_SCRIPT = '''#!/usr/bin/env python3
"""Restore this project's exact Sapsynk framework in a fresh environment."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HOSTS = ('codex', 'claude-code')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, help='Explicit offline source checkout; must match the exact pin')
parser.add_argument('--check', action='store_true', help='Check the active installed framework identity before a task')
parser.add_argument('--package', type=Path, help='Actual installed plugin directory')
parser.add_argument('--host', choices=HOSTS + ('auto', 'all'), default='auto',
                    help='Agent host to check or restore; auto follows PSTACK_HOST, the running host, then project config')
parser.add_argument('--print-package', action='store_true', help='Check, then print the active plugin directory')
args = parser.parse_args()
project = Path(__file__).resolve().parents[1]
lock = json.loads((project / '.pstack/framework.lock.json').read_text())
revision = lock['revision']
if len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):
    sys.exit('Invalid framework revision')
def detected_host():
    configured = os.environ.get('PSTACK_HOST')
    if not configured and os.environ.get('CLAUDECODE'):
        configured = 'claude-code'
    if not configured:
        config = project / '.pstack/config.json'
        configured = json.loads(config.read_text()).get('host') if config.is_file() else None
    return configured if configured in HOSTS else 'codex'
def check_package(package):
    identity = json.loads((package / 'framework.json').read_text())
    for key in ('version', 'source_digest'):
        if identity.get(key) != lock.get(key):
            sys.exit('Installed framework identity differs from project pin; bootstrap this project before continuing')
    if identity.get('upstream_commit') != lock.get('upstream_revision'):
        sys.exit('Installed framework upstream revision differs from project pin')
def active_package(host):
    if host == 'claude-code':
        result = subprocess.run(['claude', 'plugin', 'list', '--json'], check=True, capture_output=True, text=True)
        # A directory marketplace is loaded in place rather than from the cache copy. A project
        # that enables the plugin adds a project-scope entry beside the user one.
        folders = {entry.get('readFromFolder') or entry['installPath'] for entry in json.loads(result.stdout)
                   if entry.get('id') == lock.get('claude_plugin') and entry.get('enabled')}
        if len(folders) != 1:
            sys.exit('Cannot identify the active Claude Code package; run scripts/bootstrap-pstack --host claude-code')
        return Path(folders.pop())
    result = subprocess.run(['codex', 'plugin', 'list', '--json'], check=True, capture_output=True, text=True)
    matches = [entry for entry in json.loads(result.stdout).get('installed', [])
               if entry.get('pluginId') == lock['plugin'] and entry.get('installed') and entry.get('enabled')]
    if len(matches) != 1:
        sys.exit('Cannot identify the active package; supply --package with its actual directory')
    version = matches[0].get('version', '')
    if not version or '/' in version or chr(92) in version or version in ('.', '..'):
        sys.exit('Invalid installed version')
    home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    return home / 'plugins/cache/sapsynk-pstack/sapsynk-pstack' / version
if args.check or args.print_package:
    host = detected_host() if args.host in ('auto', 'all') else args.host
    try:
        package = args.package or active_package(host)
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        sys.exit('Cannot query the ' + host + ' plugin installation: ' + str(error))
    check_package(package)
    print(package if args.print_package else 'Installed project framework content pin verified (' + host + ')')
    sys.exit(0)
if args.host == 'all':
    hosts = [host for host in HOSTS if shutil.which('claude' if host == 'claude-code' else host)]
else:
    hosts = [detected_host() if args.host == 'auto' else args.host]
# Claude Code loads its directory marketplace in place, so the pinned checkout must persist.
cache = Path(os.environ.get('PSTACK_HOME', str(Path.home() / '.pstack'))) / 'framework'
source = args.source.resolve() if args.source else cache / revision
try:
    if not args.source and not (source / '.git').exists():
        partial = cache / (revision + '.partial')
        shutil.rmtree(partial, ignore_errors=True)
        cache.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', '--no-checkout', '--', lock['source'], str(partial)], check=True)
        if subprocess.run(['git', '-C', str(partial), 'checkout', '--detach', revision]).returncode:
            # The pin can sit on an unmerged branch or pull request head.
            subprocess.run(['git', '-C', str(partial), 'fetch', 'origin', revision], check=True)
            subprocess.run(['git', '-C', str(partial), 'checkout', '--detach', revision], check=True)
        partial.rename(source)
    actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != revision:
        sys.exit('Source checkout does not match exact framework pin')
    validate = [sys.executable, str(source / 'tools/validate.py')]
    if subprocess.run(validate, cwd=source, capture_output=True).returncode:
        # A fresh clone has no archive yet. Rebuild only then; a live host may be reading this folder.
        subprocess.run([sys.executable, str(source / 'tools/build.py')], check=True, cwd=source)
        subprocess.run(validate, check=True, cwd=source)
    check_package(source / 'plugins/sapsynk-pstack')
    command = [sys.executable, str(source / 'tools/bootstrap.py'), '--project', str(project), '--revision', revision,
               '--digest', lock['source_digest'], '--checkout', str(source)]
    for host in hosts:
        command += ['--host', host]
    if args.source:
        command += ['--local', str(source)]
    subprocess.run(command, check=True)
except subprocess.CalledProcessError as error:
    sys.exit('Framework bootstrap failed. Private repository access and the selected host CLI are required: ' + str(error))
'''

RUNNER_SCRIPT = '''#!/bin/sh
# Start, resume, inspect or stop a pstack CLI worker with this project's pinned runner.
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
package=$(python3 "$project/scripts/bootstrap-pstack" --print-package)
exec python3 "$package/runtime/pstack_run.py" --project "$project" "$@"
'''

PROJECT_SKILL = ('---\nname: sapsynk-project\ndescription: Load the pinned Sapsynk pstack project framework before engineering work.\n---\n\n'
                 'Run scripts/bootstrap-pstack --check before each task (or --package with the actual installed plugin directory).\n'
                 'Read .pstack/framework.lock.json and load the installed sapsynk-pstack poteto-mode skill.\n'
                 'One host has one active framework version. Bootstrap this project on switches if the content digest differs.\n'
                 'Report a missing installation or pin mismatch; do not weaken upstream requirements.\n')

AGENTS_BLOCK = ('Use sapsynk-pstack as this project engineering framework. Read the installed\n'
                'sapsynk-pstack poteto-mode entrypoint before substantive work.\n'
                'Honor .pstack/framework.lock.json; never silently change its pin.\n'
                'Before each task run scripts/bootstrap-pstack --check (or --package with the actual installed plugin directory).\n'
                'Before substantive work read the pinned poteto-mode entrypoint, applicable playbook and required leaf skills; apply them rather than only announcing activation.\n'
                'Resolve roles from .pstack/config.json and retain actual worker receipts; a configured route is not proof of dispatch.\n'
                'One host has one active version: bootstrap this project when switching from a different content pin.\n'
                'Fresh environments: run scripts/bootstrap-pstack to restore the exact framework revision.\n'
                'Keep repository-local commit identity unless the user explicitly changes it.')

CLAUDE_BLOCK = ('@AGENTS.md\n\n'
                'Claude Code coordinates pstack in this project. AGENTS.md above is the shared policy for every host.\n'
                'The `' + CLAUDE_PLUGIN + '` plugin supplies the skills, the `pstack-worker` subagent and the worker runner.\n'
                'A session-start hook checks the plugin against `.pstack/framework.lock.json`; when it reports a missing or\n'
                'different installation, run `scripts/bootstrap-pstack --host claude-code` and start a new session.\n\n'
                'Before substantive work invoke the `sapsynk-pstack:sapsynk-pstack` skill and read `adapters/claude-code.md`\n'
                'under the directory printed by `scripts/bootstrap-pstack --print-package`.\n\n'
                'Resolve each role from `.pstack/config.json` and its `host_bindings.claude-code` map, then dispatch:\n\n'
                '- Claude and `inherit-parent` roles: the Agent tool with `sapsynk-pstack:pstack-worker` (own worktree).\n'
                '- Grok and Codex roles: `scripts/pstack-run run <grok|codex> <task-id> <brief-file> --role "<role>"`,\n'
                '  each as its own background Bash task so every worker reports one completion.\n\n'
                'Start independent workers in one message. Read only each receipt line and `scripts/pstack-run diff <task-id>`;\n'
                'open a worker event log only to diagnose a failure. A failed or missing receipt is never a passing vote.')

SESSION_HOOK = ('python3 "$CLAUDE_PROJECT_DIR/scripts/bootstrap-pstack" --check --host claude-code 2>&1 || '
                'echo "pstack is not installed at this project pin. Run scripts/bootstrap-pstack --host claude-code, then start a new session."')
PERMISSIONS = ('Bash(scripts/pstack-run:*)', 'Bash(scripts/bootstrap-pstack:*)')


def claude_settings(path):
    """Enable the plugin, the pin check and the runner without touching other settings."""
    settings = json.loads(path.read_text()) if path.exists() else {}
    before = json.dumps(settings, sort_keys=True)
    settings.setdefault('enabledPlugins', {})[CLAUDE_PLUGIN] = True
    allowed = settings.setdefault('permissions', {}).setdefault('allow', [])
    allowed.extend(rule for rule in PERMISSIONS if rule not in allowed)
    groups = settings.setdefault('hooks', {}).setdefault('SessionStart', [])
    if not any(hook.get('command') == SESSION_HOOK for group in groups for hook in group.get('hooks', [])):
        groups.append({'hooks': [{'type': 'command', 'command': SESSION_HOOK, 'timeout': 30}]})
    if json.dumps(settings, sort_keys=True) != before:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + '\n')


def pinned_checkout(source, revision, directory):
    """Persistent clone of one exact commit; reused when it already holds that commit."""
    target = pathlib.Path(directory) / revision
    if not (target / '.git').exists():
        partial = target.with_name(revision + '.partial')
        shutil.rmtree(partial, ignore_errors=True)
        partial.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', '--quiet', '--no-checkout', '--', source, str(partial)], check=True)
        if subprocess.run(['git', '-C', str(partial), 'checkout', '--quiet', '--detach', revision], capture_output=True).returncode:
            # The pin can sit on an unmerged branch or pull request head.
            subprocess.run(['git', '-C', str(partial), 'fetch', '--quiet', 'origin', revision], check=True)
            subprocess.run(['git', '-C', str(partial), 'checkout', '--quiet', '--detach', revision], check=True)
        partial.rename(target)
    if subprocess.check_output(['git', '-C', str(target), 'rev-parse', 'HEAD'], text=True).strip() != revision:
        raise ValueError(f'pinned checkout is not at {revision}: {target}')
    if subprocess.check_output(['git', '-C', str(target), 'status', '--porcelain'], text=True):
        raise ValueError(f'pinned checkout was modified: {target}')
    return target


def restore_plugins(project, hosts, home=None):
    """Install the optional plugins a project locks and verify their locked file digests."""
    lockpath = pathlib.Path(project) / '.pstack/plugins.lock.json'
    if not lockpath.is_file():
        return {}
    lock = json.loads(lockpath.read_text())
    revision = lock['source_revision']
    if len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):
        raise ValueError('optional plugin source_revision must be an exact commit SHA')
    receipt = {}
    if 'claude-code' in hosts:
        selected = {plugin['claude_plugin_id']: plugin for plugin in lock['plugins'].values() if plugin.get('claude_plugin_id')}
        cli = shutil.which('claude')
        if selected and not cli:
            raise RuntimeError('Claude Code CLI unavailable; optional plugins were not installed')
        home = pathlib.Path(home or os.environ.get('PSTACK_HOME') or pathlib.Path.home() / '.pstack')
        marketplaces = {identifier.partition('@')[2] for identifier in selected}
        if len(marketplaces) > 1:
            raise ValueError('one optional plugin source serves one Claude Code marketplace')
        if selected:
            claude_marketplace(cli, marketplaces.pop(), pinned_checkout(lock['source'], revision, home / 'plugins'), list(selected))
        for identifier, plugin in selected.items():
            package = claude_package(cli, identifier)
            for relative, digest in plugin['files'].items():
                if hashlib.sha256((package / relative).read_bytes()).hexdigest() != digest:
                    raise ValueError(f'{identifier} differs from the project lock: {relative}')
        receipt['claude_code_optional_plugins'] = sorted(selected)
    if 'codex' in hosts:
        selected = [plugin['native_plugin_id'] for plugin in lock['plugins'].values() if plugin.get('native_plugin_id')]
        cli = shutil.which('codex')
        if selected and not cli:
            raise RuntimeError('Codex CLI unavailable; optional plugins were not installed')
        if selected:
            codex_marketplace(cli, selected[0].partition('@')[2], lock['source'], revision)
        for identifier in selected:
            subprocess.run([cli, 'plugin', 'add', identifier], check=True, capture_output=True, text=True)
        receipt['codex_optional_plugins'] = sorted(selected)
    return receipt


def bootstrap(project, revision, update=False, name=None, email=None, do_install=True, local=None, digest=None, package=None,
              hosts=('codex',), checkout=None):
    if len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):
        raise ValueError('revision must be an exact commit SHA')
    project = pathlib.Path(project).resolve()
    subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-toplevel'], check=True, capture_output=True)
    validate_managed_block(project / 'AGENTS.md')
    validate_managed_block(project / 'CLAUDE.md')
    validate_managed_block(project / '.gitignore', '# sapsynk-pstack:start', '# sapsynk-pstack:end')
    skill = project / '.agents/skills/sapsynk-project/SKILL.md'
    if skill.exists() and skill.read_text() != PROJECT_SKILL:
        raise ValueError(f'existing skill would be overwritten: {skill}')
    script = project / 'scripts/bootstrap-pstack'
    if script.exists() and script.read_text() != BOOTSTRAP_SCRIPT and not update:
        raise ValueError(f'existing bootstrap script would be overwritten; use --update to replace it: {script}')
    runner = project / 'scripts/pstack-run'
    if runner.exists() and runner.read_text() != RUNNER_SCRIPT:
        raise ValueError(f'existing worker runner would be overwritten: {runner}')
    if local:
        actual = subprocess.check_output(['git', '-C', str(local), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != revision:
            raise ValueError('local source HEAD does not match project revision')
        dirty = subprocess.check_output(['git', '-C', str(local), 'status', '--porcelain'], text=True)
        if dirty:
            raise ValueError('local source is dirty; commit it before installing a pinned project')
        from build import source_digest
        computed = source_digest(pathlib.Path(local))
        if digest and digest != computed:
            raise ValueError('expected source digest differs from pinned local checkout')
        digest = computed
    if not digest or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('an exact semantic content digest is required; supply a pinned --local checkout or --digest')
    lock = {'schema_version': 1, 'version': VERSION, 'source': SOURCE, 'revision': revision,
            'upstream_revision': UPSTREAM, 'source_digest': digest, 'plugin': 'sapsynk-pstack@sapsynk-pstack',
            'claude_plugin': CLAUDE_PLUGIN}
    lockpath = project / '.pstack/framework.lock.json'
    if lockpath.exists() and json.loads(lockpath.read_text()) != lock and not update:
        raise ValueError('framework pin differs; use --update to change it explicitly')
    # Install first: failed installation must not claim a successfully bound project.
    receipt = {} if do_install else {'native_installation': 'not_requested', 'installed_identity_verified': False}
    if do_install:
        for host in hosts:
            if host == 'claude-code':
                if not (checkout or local):
                    raise ValueError('Claude Code installs from a verified pinned checkout; supply --checkout or --local')
                receipt.update(install_claude(checkout or local, digest, VERSION))
            else:
                receipt.update(install(local or SOURCE, None if local else revision, expected_digest=digest,
                                       package=package, expected_version=VERSION))
        receipt.update(restore_plugins(project, hosts))
    config = project / '.pstack/config.json'
    settings = json.loads(config.read_text()) if config.exists() else {'schema_version': 1, 'host': hosts[0]}
    identity = settings.get('commit_identity', {})
    name = name or identity.get('name')
    email = email or identity.get('email')
    if name:
        subprocess.run(['git', '-C', str(project), 'config', '--local', 'user.name', name], check=True)
    if email:
        subprocess.run(['git', '-C', str(project), 'config', '--local', 'user.email', email], check=True)
    lockpath.parent.mkdir(parents=True, exist_ok=True)
    lockpath.write_text(json.dumps(lock, indent=2) + '\n')
    if name or email:
        settings['commit_identity'] = {**identity, **({'name': name} if name else {}), **({'email': email} if email else {})}
    config.write_text(json.dumps(settings, indent=2) + '\n')
    managed_block(project / 'AGENTS.md', AGENTS_BLOCK)
    managed_block(project / 'CLAUDE.md', CLAUDE_BLOCK)
    claude_settings(project / '.claude/settings.json')
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(PROJECT_SKILL)
    script.parent.mkdir(parents=True, exist_ok=True)
    for path, content in ((script, BOOTSTRAP_SCRIPT), (runner, RUNNER_SCRIPT)):
        path.write_text(content)
        path.chmod(0o755)
    managed_block(project / '.gitignore', '.pstack/runs/\n.pstack/cache/\n.pstack/state/\n.claude/settings.local.json\n.claude/worktrees/',
                  '# sapsynk-pstack:start', '# sapsynk-pstack:end')
    return {'project_lock_written': json.loads(lockpath.read_text()) == lock, **receipt}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=pathlib.Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--local', type=pathlib.Path)
    parser.add_argument('--checkout', type=pathlib.Path, help='Verified pinned checkout that Claude Code loads in place')
    parser.add_argument('--host', action='append', choices=HOSTS, help='Host to install into; repeatable, default codex')
    parser.add_argument('--digest', help='Expected pinned semantic source SHA256')
    parser.add_argument('--package', type=pathlib.Path, help='Actual installed package to verify')
    parser.add_argument('--update', action='store_true')
    parser.add_argument('--name')
    parser.add_argument('--email')
    parser.add_argument('--no-install', action='store_true', help='write the pin without claiming installation')
    args = parser.parse_args()
    try:
        print(json.dumps(bootstrap(args.project, args.revision, args.update, args.name, args.email, not args.no_install,
                                   args.local, args.digest, args.package, tuple(args.host or ('codex',)), args.checkout)))
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'Bootstrap failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
