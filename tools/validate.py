#!/usr/bin/env python3
"""Validate provenance, generated parity, native metadata and Markdown resources."""
import argparse
import json
from pathlib import Path
import re
import sys
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import ROOT, NAME, VERSION, adapted_skill, files, sha, verify_source, source_digest

LINK = re.compile(r'!?\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)')

def unresolved(root):
    result = set()
    for path, source in files(root).items():
        if not path.endswith('.md'):
            continue
        for target in LINK.findall(source.read_text()):
            if re.match(r'^[a-zA-Z][\w+.-]*:', target) or target.startswith(('#', '/')):
                continue
            target = target.split('#')[0].split('?')[0]
            if target and not (source.parent / target).exists():
                result.add((path, target))
    return result

def validate(root=ROOT):
    root = Path(root)
    lock, original = verify_source(root)
    package = root / 'plugins' / NAME
    identity = json.loads((package / 'framework.json').read_text())
    if identity.get('source_digest') != source_digest(root) or identity.get('version') != VERSION:
        raise ValueError('Framework semantic source identity mismatch')
    for name in ('NOTICE.md', 'LICENSE-cursor-team-kit', 'upstream.lock.json'):
        if (package / name).read_bytes() != (root / name).read_bytes():
            raise ValueError('Missing or changed provenance file: ' + name)
    parity = json.loads((package / 'parity.json').read_text())
    if parity.get('framework_source_digest') != identity['source_digest']:
        raise ValueError('Parity identity mismatch')
    rows = {row['path']: row for row in parity['files']}
    if set(rows) != set(original) or parity['original_files'] != len(original):
        raise ValueError('Incomplete parity inventory')
    for path, source in original.items():
        expected = source.read_bytes()
        if path.endswith('/SKILL.md'):
            expected, body_hash = adapted_skill(expected, path)
            if rows[path].get('original_body_sha256') != body_hash:
                raise ValueError('Original body provenance mismatch: ' + path)
            policy = package / Path(path).parent / 'agents/openai.yaml'
            if policy.read_text() != 'policy:\n  allow_implicit_invocation: false\n':
                raise ValueError('Invalid native invocation policy: ' + path)
        actual = (package / path).read_bytes()
        if actual != expected or rows[path]['package_sha256'] != sha(actual) or rows[path]['source_sha256'] != lock['files'][path]:
            raise ValueError('Package parity mismatch: ' + path)
    manifest = json.loads((package / '.codex-plugin/plugin.json').read_text())
    if manifest['name'] != NAME or manifest['version'] != VERSION or manifest['skills'] != './skills/':
        raise ValueError('Invalid native plugin manifest')
    portable = json.loads((package / 'plugin.json').read_text())
    if portable.get('$schema') != 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json':
        raise ValueError('Invalid portable manifest schema')
    if any(key in portable for key in ('skills', 'mcpServers', 'apps', 'interface')):
        raise ValueError('Unsupported portable manifest field')
    if portable['name'] != manifest['name'] or portable['version'] != manifest['version']:
        raise ValueError('Portable and compatibility identities differ')
    presentation = portable['extensions']['com.openai']['interface']
    if presentation != manifest['interface'] or len(presentation['shortDescription']) > 30:
        raise ValueError('Portable presentation mismatch or subtitle exceeds 30 characters')
    marketplace = json.loads((root / '.agents/plugins/marketplace.json').read_text())
    if marketplace['plugins'][0]['source'] != {'source': 'local', 'path': './plugins/' + NAME}:
        raise ValueError('Invalid native marketplace source')
    for skill in (package / 'skills').rglob('SKILL.md'):
        metadata = skill.read_text().split('---', 2)[1]
        if not re.search(r'^name: ' + re.escape(skill.parent.name) + r'$', metadata, re.M):
            raise ValueError('Invalid native skill name: ' + str(skill))
        policy = skill.parent / 'agents/openai.yaml'
        if not policy.is_file() or not re.search(r'allow_implicit_invocation: (true|false)', policy.read_text()):
            raise ValueError('Missing native skill policy: ' + str(skill))
    for key in ('logo', 'composerIcon'):
        if not (package / manifest['interface'][key]).is_file():
            raise ValueError('Missing manifest asset')
    for directory in ('adapters', 'runtime', 'config'):
        for path, source in files(root / directory).items():
            if '__pycache__' in Path(path).parts:
                continue
            if (package / directory / path).read_bytes() != source.read_bytes():
                raise ValueError('Missing or changed support resource: ' + directory + '/' + path)
    for path, source in files(root / 'extra-skills').items():
        if (package / 'skills' / path).read_bytes() != source.read_bytes():
            raise ValueError('Missing extra skill: ' + path)
    baseline = unresolved(root / 'upstream/pstack')
    introduced = unresolved(package) - baseline
    if introduced:
        raise ValueError('Introduced unresolved Markdown references: ' + repr(sorted(introduced)))
    archive = root / 'dist' / (NAME + '-' + VERSION + '.zip')
    with zipfile.ZipFile(archive) as bundle:
        expected = {NAME + '/' + path: source.read_bytes() for path, source in files(package).items()}
        if set(bundle.namelist()) != set(expected) or len(bundle.namelist()) != len(expected):
            raise ValueError('Archive inventory mismatch')
        for path, data in expected.items():
            if bundle.read(path) != data:
                raise ValueError('Archive bytes mismatch: ' + path)
    return {'original_files': len(original), 'upstream_skills': sum(p.startswith('skills/') and p.endswith('/SKILL.md') for p in original),
        'playbooks': sum('/playbooks/' in p and p.endswith('.md') for p in original),
        'known_upstream_unresolved_links': [list(x) for x in sorted(baseline)], 'introduced_unresolved_links': []}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(validate(args.root), indent=2))
