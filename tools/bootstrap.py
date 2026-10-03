#!/usr/bin/env python3
"""Bind a project to an exact framework commit and optionally install it."""
import argparse
import json
import pathlib
import subprocess
import sys
from install import install, managed_block, validate_managed_block

UPSTREAM = '23e4138daa01c42d4969f7a5465f82704e64f798'
SOURCE = 'https://github.com/builder-sapsynk/pstack-framework.git'

BOOTSTRAP_SCRIPT = '''#!/usr/bin/env python3
"""Restore this project's exact Sapsynk framework in a fresh environment."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, help='Explicit offline source checkout; must match the exact pin')
parser.add_argument('--check', action='store_true', help='Check the active installed framework identity before a task')
parser.add_argument('--package', type=Path, help='Actual installed plugin directory')
args = parser.parse_args()
project = Path(__file__).resolve().parents[1]
lock = json.loads((project / '.pstack/framework.lock.json').read_text())
revision = lock['revision']
if len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):
    sys.exit('Invalid framework revision')
def check_package(package):
    identity = json.loads((package / 'framework.json').read_text())
    for key in ('version', 'source_digest'):
        if identity.get(key) != lock.get(key):
            sys.exit('Installed framework identity differs from project pin; bootstrap this project before continuing')
    if identity.get('upstream_commit') != lock.get('upstream_revision'):
        sys.exit('Installed framework upstream revision differs from project pin')
if args.check:
    if not args.package:
        result = subprocess.run(['codex', 'plugin', 'list', '--json'], check=True, capture_output=True, text=True)
        matches = [entry for entry in json.loads(result.stdout).get('installed', [])
                   if entry.get('pluginId') == lock['plugin'] and entry.get('installed') and entry.get('enabled')]
        if len(matches) != 1:
            sys.exit('Cannot identify the active package; supply --package with its actual directory')
        version = matches[0].get('version', '')
        if not version or '/' in version or chr(92) in version or version in ('.', '..'):
            sys.exit('Invalid installed version')
        home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
        args.package = home / 'plugins/cache/sapsynk-pstack/sapsynk-pstack' / version
    check_package(args.package)
    print('Installed project framework content pin verified')
    sys.exit(0)
with tempfile.TemporaryDirectory(prefix='sapsynk-framework-') as temporary:
    source = args.source.resolve() if args.source else Path(temporary) / 'framework'
    try:
        if not args.source:
            subprocess.run(['git', 'clone', '--no-checkout', '--', lock['source'], str(source)], check=True)
            subprocess.run(['git', '-C', str(source), 'checkout', '--detach', revision], check=True)
        actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != revision:
            sys.exit('Source checkout does not match exact framework pin')
        subprocess.run([sys.executable, str(source / 'tools/build.py')], check=True, cwd=source)
        subprocess.run([sys.executable, str(source / 'tools/validate.py')], check=True, cwd=source)
        check_package(source / 'plugins/sapsynk-pstack')
        command = [sys.executable, str(source / 'tools/bootstrap.py'), '--project', str(project), '--revision', revision,
                   '--digest', lock['source_digest']]
        if args.source:
            command += ['--local', str(source)]
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        sys.exit('Framework bootstrap failed. Private repository access and native Codex CLI installation are required: ' + str(error))
'''


def bootstrap(project, revision, update=False, name=None, email=None, do_install=True, local=None, digest=None, package=None):
    if len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):
        raise ValueError('revision must be an exact commit SHA')
    project = pathlib.Path(project).resolve()
    subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-toplevel'], check=True, capture_output=True)
    validate_managed_block(project / 'AGENTS.md')
    validate_managed_block(project / '.gitignore', '# sapsynk-pstack:start', '# sapsynk-pstack:end')
    skill = project / '.agents/skills/sapsynk-project/SKILL.md'
    expected = ('---\nname: sapsynk-project\ndescription: Load the pinned Sapsynk pstack project framework before engineering work.\n---\n\n'
                'Run scripts/bootstrap-pstack --check before each task (or --package with the actual installed plugin directory).\n'
                'Read .pstack/framework.lock.json and load the installed sapsynk-pstack poteto-mode skill.\n'
                'One host has one active framework version. Bootstrap this project on switches if the content digest differs.\n'
                'Report a missing installation or pin mismatch; do not weaken upstream requirements.\n')
    if skill.exists() and skill.read_text() != expected:
        raise ValueError(f'existing skill would be overwritten: {skill}')
    script = project / 'scripts/bootstrap-pstack'
    if script.exists() and script.read_text() != BOOTSTRAP_SCRIPT:
        raise ValueError(f'existing bootstrap script would be overwritten: {script}')
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
    lock = {'schema_version': 1, 'version': '0.1.1', 'source': SOURCE, 'revision': revision,
            'upstream_revision': UPSTREAM, 'source_digest': digest, 'plugin': 'sapsynk-pstack@sapsynk-pstack'}
    lockpath = project / '.pstack/framework.lock.json'
    if lockpath.exists() and json.loads(lockpath.read_text()) != lock and not update:
        raise ValueError('framework pin differs; use --update to change it explicitly')
    # Install first: failed installation must not claim a successfully bound project.
    receipt = install(local or SOURCE, None if local else revision, expected_digest=digest, package=package) if do_install else {'native_installation': 'not_requested', 'installed_identity_verified': False}
    config = project / '.pstack/config.json'
    settings = json.loads(config.read_text()) if config.exists() else {'schema_version': 1, 'host': 'codex'}
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
    managed_block(project / 'AGENTS.md',
                  'Use sapsynk-pstack as this project engineering framework. Read the installed\n'
                  'sapsynk-pstack poteto-mode entrypoint before substantive work.\n'
                  'Honor .pstack/framework.lock.json; never silently change its pin.\n'
                  'Before each task run scripts/bootstrap-pstack --check (or --package with the actual installed plugin directory).\n'
                  'One host has one active version: bootstrap this project when switching from a different content pin.\n'
                  'Fresh environments: run scripts/bootstrap-pstack to restore the exact framework revision.\n'
                  'Keep repository-local commit identity unless the user explicitly changes it.')
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(expected)
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(BOOTSTRAP_SCRIPT)
    script.chmod(0o755)
    managed_block(project / '.gitignore', '.pstack/runs/\n.pstack/cache/\n.pstack/state/', '# sapsynk-pstack:start', '# sapsynk-pstack:end')
    return {'project_lock_written': json.loads(lockpath.read_text()) == lock, **receipt}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=pathlib.Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--local', type=pathlib.Path)
    parser.add_argument('--digest', help='Expected pinned semantic source SHA256')
    parser.add_argument('--package', type=pathlib.Path, help='Actual installed package to verify')
    parser.add_argument('--update', action='store_true')
    parser.add_argument('--name')
    parser.add_argument('--email')
    parser.add_argument('--no-install', action='store_true', help='write the pin without claiming installation')
    args = parser.parse_args()
    try:
        print(json.dumps(bootstrap(args.project, args.revision, args.update, args.name, args.email, not args.no_install, args.local, args.digest, args.package)))
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'Bootstrap failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
