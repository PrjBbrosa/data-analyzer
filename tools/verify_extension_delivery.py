"""Four real frozen combinations in a disposable copy of a just-built delivery.

Inputs are local build artifacts, not a user-facing bypass for unsigned downloads.
Published installation uses the repository/TUF path. The original base is not changed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mf4_analyzer.extensions.contract import bind_verified_package, parse_package_manifest
from mf4_analyzer.extensions.native_identity import sha256_file
from tools.extension_manager.engine import InstallEngine
from tools.extension_manager.transaction import PackageSource
from tools.verify_extension_installation import verify, reject_evidence_target, write_json


def build_sources(delivery: dict) -> dict[str, PackageSource]:
    result = {}
    for item in delivery['components']:
        archive, manifest = Path(item['zip']), Path(item['package_json'])
        if sha256_file(archive) != item['sha256'] or archive.stat().st_size != item['size']:
            raise ValueError('build ZIP changed after emission')
        data = manifest.read_bytes()
        package = parse_package_manifest(data)
        verified = bind_verified_package(snapshot_id='local-build-validation', component=package.component,
            runtime_id=package.runtime_id, package_revision=package.package_revision,
            component_api=package.component_api, min_manager_version=package.min_manager_version,
            zip_target=archive.name, zip_sha256=item['sha256'], zip_length=item['size'],
            manifest_target=archive.stem + '.package.json', manifest_sha256=sha256_file(manifest),
            manifest_length=len(data), package_json_bytes=data)
        result[package.component] = PackageSource(verified=verified, zip_path=archive)
    if set(result) != {'media', 'matlab'}:
        raise ValueError('both component artifacts are required')
    return result


def run_matrix(app_root: Path, delivery: dict) -> dict:
    sources = build_sources(delivery)
    records = []
    # Same volume as the generated base (NTFS gate lives in the engine).
    with tempfile.TemporaryDirectory(prefix='tracelab-combinations-', dir=app_root.parent) as directory:
        for names in ((), ('media',), ('matlab',), ('media', 'matlab')):
            target = Path(directory) / ('-'.join(names) or 'base')
            shutil.copytree(app_root, target)
            engine = InstallEngine(target)
            if names:
                engine.install([sources[name] for name in names])
            core = json.loads((target / 'core.json').read_bytes())
            exe = target / core['exe_relpath']
            code, payload = verify(mode='installed-available' if names else 'base-expected-missing',
                                   exe=exe, app_root=target)
            records.append({'components': names, 'exit_code': code, 'evidence': payload})
            if code:
                return {'ok': False, 'combinations': records}
            if len(names) == 2:
                engine.uninstall(['matlab'])
                code, payload = verify(mode='installed-available', exe=exe, app_root=target)
                records.append({'components': ['media'], 'after_uninstall': 'matlab',
                                'exit_code': code, 'evidence': payload})
                if code:
                    return {'ok': False, 'combinations': records}
    return {'ok': True, 'combinations': records}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--app-root', required=True, type=Path)
    parser.add_argument('--delivery-audit', required=True, type=Path)
    parser.add_argument('--evidence-json', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        reject_evidence_target(args.evidence_json, app_root=args.app_root,
                               extra=(args.delivery_audit,))
    except ValueError as exc:
        parser.error(str(exc))
    try:
        result = run_matrix(args.app_root, json.loads(args.delivery_audit.read_bytes()))
    except Exception as exc:
        result = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
    write_json(args.evidence_json, result)
    return 0 if result['ok'] else 14


if __name__ == '__main__':
    raise SystemExit(main())
