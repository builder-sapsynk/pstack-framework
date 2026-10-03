#!/usr/bin/env python3
"""Build the complete pinned pstack distribution without editing upstream."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = 'sapsynk-pstack'
VERSION = '0.1.3'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def files(root):
    return {p.relative_to(root).as_posix(): p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}

def semantic_inputs(root):
    """Inputs that determine installed behavior; never include generated artifacts."""
    root = Path(root)
    selected = {}
    for name in ('upstream.lock.json', 'LICENSE', 'NOTICE.md', 'LICENSE-cursor-team-kit'):
        source = root / name
        if not source.is_file():
            raise ValueError('Missing semantic source: ' + name)
        selected[name] = source
    for directory in ('runtime', 'adapters', 'config', 'extra-skills', 'tools'):
        for path, source in files(root / directory).items():
            if any(part in ('node_modules', '.git', '.pstack', '__pycache__') for part in Path(path).parts):
                continue
            if directory == 'tools' and source.suffix != '.py':
                continue
            selected[directory + '/' + path] = source
    return selected

def source_digest(root=ROOT):
    # Framed names and lengths prevent ambiguous concatenations.
    digest = hashlib.sha256()
    for path, source in sorted(semantic_inputs(root).items()):
        data = source.read_bytes()
        digest.update(path.encode('utf-8') + b'\0' + str(len(data)).encode('ascii') + b'\0' + data)
    return digest.hexdigest()

def verify_source(root):
    lock = json.loads((root / 'upstream.lock.json').read_text())
    actual = files(root / 'upstream/pstack')
    if set(actual) != set(lock['files']):
        raise ValueError('Upstream inventory differs from lock')
    for path, expected in lock['files'].items():
        if sha(actual[path].read_bytes()) != expected:
            raise ValueError('Upstream source changed: ' + path)
    return lock, actual

def adapted_skill(data, path):
    text = data.decode('utf-8')
    match = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)', text, re.S)
    if not match:
        raise ValueError('Missing skill frontmatter: ' + path)
    metadata = match.group(1)
    description = re.search(r'^description:(.*?)(?=^[A-Za-z][\w-]*:|\Z)', metadata, re.M | re.S)
    if not description:
        raise ValueError('Missing description: ' + path)
    slug = Path(path).parent.name
    prefix = os.path.relpath('.', Path(path).parent).replace(os.sep, '/')
    preamble = ('\n> Sapsynk host adapter: Read ['
                'the portable contract](' + prefix + '/adapters/CONTRACT.md) and the '
                '[Codex mapping](' + prefix + '/adapters/codex.md) before executing this '
                'workflow. Select the matching host adapter when running elsewhere; preserve '
                'the original requirements and report unavailable capabilities. Verify the pinned '
                '[framework identity](' + prefix + '/framework.json) before relying on this installation.\n')
    # The original body begins immediately after the closing frontmatter line.
    body = text[match.end():]
    output = '---\nname: ' + slug + '\ndescription:' + description.group(1).rstrip() + '\n---\n' + preamble + body
    return output.encode(), sha(body.encode())

def build(root=ROOT):
    root = Path(root)
    lock, original = verify_source(root)
    identity_digest = source_digest(root)
    for required in ('adapters/CONTRACT.md', 'adapters/codex.md'):
        if not (root / required).is_file():
            raise ValueError('Missing required resource: ' + required)
    for directory in ('runtime', 'config', 'extra-skills'):
        if not (root / directory).is_dir():
            raise ValueError('Missing source directory: ' + directory)
    output = root / 'plugins' / NAME
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    parity = []
    for path, source in sorted(original.items()):
        data = source.read_bytes()
        row = {'path': path, 'source_sha256': sha(data), 'status': 'retained'}
        if path.endswith('/SKILL.md'):
            data, body_hash = adapted_skill(data, path)
            row.update(status='adapted', original_body_sha256=body_hash,
                       changes=['native frontmatter', 'host adapter preamble'])
        destination = output / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        destination.chmod(source.stat().st_mode & 0o777)
        row['package_sha256'] = sha(data)
        parity.append(row)
        if path.endswith('/SKILL.md'):
            policy = destination.parent / 'agents/openai.yaml'
            policy.parent.mkdir(exist_ok=True)
            override = root / 'config/skill-metadata' / destination.parent.name / 'openai.yaml'
            policy.write_bytes(override.read_bytes() if override.is_file() else b'policy:\n  allow_implicit_invocation: false\n')
    for directory in ('adapters', 'runtime', 'config'):
        for path, source in files(root / directory).items():
            if any(part in ('node_modules', '.git', '.pstack', '__pycache__') for part in Path(path).parts):
                continue
            target = output / directory / path
            if target.exists():
                raise ValueError('Package collision: ' + str(target))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    for path, source in files(root / 'extra-skills').items():
        target = output / 'skills' / path
        if target.exists():
            raise ValueError('Extra skill collision: ' + path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for skill in (output / 'skills').rglob('SKILL.md'):
        policy = skill.parent / 'agents/openai.yaml'
        if not policy.exists():
            policy.parent.mkdir(exist_ok=True)
            policy.write_text('policy:\n  allow_implicit_invocation: false\n')
    for name in ('upstream.lock.json', 'NOTICE.md', 'LICENSE-cursor-team-kit'):
        shutil.copy2(root / name, output / name)
    write_json(output / 'framework.json', {'schema_version': 1, 'name': NAME, 'version': VERSION,
        'source_digest': identity_digest, 'upstream_commit': lock['commit']})
    manifest = {'name': NAME, 'version': VERSION,
        'description': 'Complete portable Sapsynk distribution of pinned pstack workflows.',
        'author': {'name': 'Sapsynk'}, 'license': 'MIT', 'skills': './skills/',
        'homepage': 'https://github.com/builder-sapsynk/pstack-framework',
        'keywords': ['pstack', 'engineering', 'codex', 'portable'],
        'interface': {'displayName': 'Sapsynk pstack', 'shortDescription': 'Portable engineering workflows',
            'longDescription': 'Pinned upstream pstack with portable host adapters and external agent tools.',
            'developerName': 'Sapsynk', 'category': 'Developer Tools',
            'composerIcon': './assets/logo.png', 'logo': './assets/logo.png'}}
    portable = {k: v for k, v in manifest.items() if k not in ('skills', 'interface')}
    portable['$schema'] = 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json'
    portable['extensions'] = {'com.openai': {'interface': manifest['interface']}}
    write_json(output / 'plugin.json', portable)
    write_json(output / '.codex-plugin/plugin.json', manifest)
    write_json(output / '.claude-plugin/plugin.json', {k: v for k, v in manifest.items() if k != 'interface'})
    write_json(output / 'parity.json', {'schema_version': 1, 'upstream_commit': lock['commit'],
        'original_files': len(original), 'framework_source_digest': identity_digest, 'files': parity})
    marketplace = {'name': 'sapsynk', 'owner': {'name': 'Sapsynk'},
        'plugins': [{'name': NAME, 'source': './plugins/' + NAME, 'description': manifest['description']}]}
    native_marketplace = {'name': NAME, 'interface': {'displayName': 'Sapsynk pstack'},
        'plugins': [{'name': NAME, 'source': {'source': 'local', 'path': './plugins/' + NAME},
            'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'},
            'category': 'Productivity'}]}
    write_json(root / '.agents/plugins/marketplace.json', native_marketplace)
    write_json(root / '.claude-plugin/marketplace.json', marketplace)
    archive = root / 'dist' / (NAME + '-' + VERSION + '.zip')
    archive.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path, source in sorted(files(output).items()):
            info = zipfile.ZipInfo(NAME + '/' + path, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100000 | (source.stat().st_mode & 0o777)) << 16
            bundle.writestr(info, source.read_bytes())
    return output, archive

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    output, archive = build(args.root)
    print(json.dumps({'plugin': str(output), 'archive': str(archive)}))
