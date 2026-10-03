#!/usr/bin/env python3
"""Install the native plugin without rewriting unrelated host settings."""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys

START = '<!-- sapsynk-pstack:start -->'
END = '<!-- sapsynk-pstack:end -->'


def codex_home(home=None):
    return pathlib.Path(home) / '.codex' if home else pathlib.Path(os.environ.get('CODEX_HOME', str(pathlib.Path.home() / '.codex')))


def installed_package(executable='codex', home=None):
    cli = shutil.which(executable)
    if not cli:
        raise RuntimeError('Codex CLI unavailable; cannot verify the active package')
    result = subprocess.run([cli, 'plugin', 'list', '--json'], check=True, capture_output=True, text=True)
    installed = json.loads(result.stdout).get('installed', [])
    matches = [entry for entry in installed if entry.get('pluginId') == 'sapsynk-pstack@sapsynk-pstack'
               and entry.get('installed') and entry.get('enabled')]
    if len(matches) != 1:
        raise ValueError('exactly one enabled installed Sapsynk pstack plugin is required')
    version = matches[0].get('version', '')
    if not version or '/' in version or '\\' in version or version in ('.', '..'):
        raise ValueError('native CLI returned an unsafe plugin version')
    package = codex_home(home) / 'plugins/cache/sapsynk-pstack/sapsynk-pstack' / version
    if not package.is_dir():
        raise ValueError('native cached package directory unavailable; supply --package explicitly')
    return package


def verify_package(package, digest, version='0.1.0', upstream_commit=None):
    """Check content identity of the actual installed package, independently of the lock."""
    identity = pathlib.Path(package) / 'framework.json'
    if not identity.is_file():
        raise ValueError(f'installed package identity missing: {identity}')
    actual = json.loads(identity.read_text())
    if actual.get('source_digest') != digest or actual.get('version') != version:
        raise ValueError('installed framework does not match project version/content pin; bootstrap this project before continuing')
    if upstream_commit and actual.get('upstream_commit') != upstream_commit:
        raise ValueError('installed framework upstream revision differs from the project pin')
    return actual


def validate_managed_block(path, start_marker=START, end_marker=END):
    path = pathlib.Path(path)
    old = path.read_text() if path.exists() else ''
    if old.count(start_marker) != old.count(end_marker) or old.count(start_marker) > 1:
        raise ValueError(f'malformed managed block: {path}')
    if start_marker in old and old.index(end_marker) < old.index(start_marker):
        raise ValueError(f'malformed managed block: {path}')
    return old


def managed_block(path, content, start_marker=START, end_marker=END):
    path = pathlib.Path(path)
    old = validate_managed_block(path, start_marker, end_marker)
    block = start_marker + '\n' + content.rstrip() + '\n' + end_marker
    if start_marker in old:
        start, end = old.index(start_marker), old.index(end_marker) + len(end_marker)
        if end < start:
            raise ValueError(f'malformed managed block: {path}')
        new = old[:start] + block + old[end:]
    else:
        new = old + ('\n\n' if old and not old.endswith('\n\n') else '') + block + '\n'
    if new != old:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new)


def install(source, revision=None, global_default=False, home=None, executable='codex', expected_digest=None, package=None):
    if global_default:
        validate_managed_block(codex_home(home) / 'AGENTS.md')
    cli = shutil.which(executable)
    if not cli:
        raise RuntimeError('Codex CLI unavailable; native installation was not performed')
    for command in [('plugin', '--help'), ('plugin', 'marketplace', 'add', '--help'), ('plugin', 'add', '--help')]:
        subprocess.run([cli, *command], check=True, capture_output=True, text=True)
    args = [cli, 'plugin', 'marketplace', 'add', str(source)]
    if revision:
        args += ['--ref', revision]
    subprocess.run(args, check=True)
    result = subprocess.run([cli, 'plugin', 'add', 'sapsynk-pstack@sapsynk-pstack'], check=True, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, end='', file=sys.stderr)
    roots = [line.partition('Installed plugin root: ')[2].strip() for line in result.stdout.splitlines()
             if line.startswith('Installed plugin root: ')]
    active_package = pathlib.Path(roots[0]) if len(roots) == 1 else package
    if expected_digest and not active_package:
        active_package = installed_package(cli, home)
    identity = verify_package(active_package, expected_digest) if expected_digest else None
    if global_default:
        managed_block(codex_home(home) / 'AGENTS.md',
                      'Use the installed sapsynk-pstack plugin as the default engineering framework.\n'
                      'Read its namespaced poteto-mode entrypoint before substantive work.\n'
                      'Honor each project .pstack/framework.lock.json exact pin. Run scripts/bootstrap-pstack --check\n'
                      'before each task; bootstrap on project switches. One host installation has one active content version.\n'
                      'Report missing or mismatched installation instead of silently using a different version.')
    return {'native_installation': 'completed', 'source': str(source), 'revision': revision,
            'installed_identity_verified': identity is not None,
            'installed_package': str(active_package) if active_package else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--local', type=pathlib.Path)
    source.add_argument('--remote')
    parser.add_argument('--revision')
    parser.add_argument('--global', dest='global_default', action='store_true')
    parser.add_argument('--home', type=pathlib.Path)
    parser.add_argument('--digest', help='Expected framework semantic SHA256')
    parser.add_argument('--package', type=pathlib.Path, help='Actual installed package directory to verify')
    args = parser.parse_args()
    if args.remote and (not args.revision or len(args.revision) != 40 or any(c not in '0123456789abcdef' for c in args.revision)):
        parser.error('remote installation requires an exact 40-character commit SHA')
    if args.local and not (args.local / '.agents/plugins/marketplace.json').exists():
        parser.error('local repository lacks .agents/plugins/marketplace.json')
    try:
        install(args.local or args.remote, args.revision, args.global_default, args.home, expected_digest=args.digest, package=args.package)
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f'Installation failed: {error}', file=sys.stderr)
        return 1
    print('Native installation completed; cloud publication and provider authentication are separate checks.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
