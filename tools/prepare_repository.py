"""Prepare a clean review checkout and ZIP, without creating/pushing a remote.

Explicit source selection excludes household data, private deployment history,
model/runtime caches, local environments, HA config and old transfer bundles.
"""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = [
    'README.md', 'README.zh-CN.md', 'CONTRIBUTING.md', 'pyproject.toml', '.gitignore', '.gitattributes',
    'config.example.json', 'safety-policy.example.json',
    'docs/framework.md', 'docs/playground.md', 'docs/voice-acceptance.md', 'docs/release-review.md',
    'playground/index.template.html', 'examples/adapter.py', 'examples/observation.json',
    'deploy/Dockerfile', 'deploy/compose.yaml', 'deploy/preflight.sh', 'deploy/prepare-itx.sh',
    '.github/workflows/tests.yml', '.github/ISSUE_TEMPLATE/bug.md', '.github/ISSUE_TEMPLATE/device-adapter.md',
    'tools/build_playground.py', 'tools/check_playground.mjs', 'tools/check_wasm.mjs',
    'tools/fetch_pyodide.mjs', 'tools/prepare_repository.py',
]


def selection():
    files = PUBLIC_FILES + [p.relative_to(ROOT).as_posix() for folder in ('moqi', 'tests')
                            for p in sorted((ROOT/folder).glob('*.py'))]
    if (ROOT/'LICENSE').is_file(): files.append('LICENSE')
    for name in files:
        source = (ROOT/name).resolve()
        if not source.is_relative_to(ROOT) or not source.is_file():
            raise ValueError('Missing or unsafe public source: '+name)
    return sorted(files)


def prepare(destination):
    destination = Path(destination).resolve()
    archive = destination.with_suffix('.zip')
    if destination.exists() or archive.exists():
        raise FileExistsError('Review destination/ZIP already exists; use a new name')
    files = selection()
    destination.mkdir(parents=True)
    for name in files:
        target = destination/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT/name).read_text(encoding='utf-8-sig').replace('\r\n','\n').encode('utf-8'))
    preview = ROOT/'dist/playground/index.html'
    if not preview.is_file(): raise ValueError('Build the playground before preparing the review')
    target = destination/'dist/playground/index.html'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(preview.read_bytes())
    hashes = {p.relative_to(destination).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(destination.rglob('*')) if p.is_file()}
    manifest = {'publication_status': 'local_review_only', 'proposed_repository': 'moqi-home',
                'owner_kind': 'personal', 'household_data_included': False,
                'license_status': 'selected' if 'LICENSE' in files else 'pending_user_choice',
                'browser_acceptance': 'pending', 'files': hashes}
    (destination/'REVIEW-MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n',encoding='utf-8',newline='\n')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(destination.rglob('*')):
            if p.is_file(): z.write(p, f'{destination.name}/{p.relative_to(destination).as_posix()}')
    print(f'Review folder: {destination}\nZIP: {archive}\nSelected files: {len(hashes)}\nNo remote created or pushed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination')
    prepare(parser.parse_args().destination)
