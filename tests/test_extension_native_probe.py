"""Native probe correctness, independent of transaction protocol doubles."""
from pathlib import Path

import pytest

from mf4_analyzer.extensions.probe import evaluate_staging_probe
from mf4_analyzer.extensions.runtime import identify_core
from tests.test_extension_transaction import _write_core
from tools.extension_manager.transaction import InstallTransaction
from tests.test_extension_transaction import _make_verified_zip


def test_a_marker_file_is_not_native_import_evidence(tmp_path):
    marker = tmp_path / 'media' / 'site-packages' / 'av' / '__init__.py'
    marker.parent.mkdir(parents=True)
    marker.write_text("raise RuntimeError('broken native import')\n")
    result = evaluate_staging_probe({'components': ['media'], 'probe_types': ['media_wav_mp4_v1']}, tmp_path)
    assert result['ok'] is False


def test_default_transaction_probe_is_identified_target_exe(tmp_path):
    root = tmp_path / 'TraceLab'
    _write_core(root)
    transaction = InstallTransaction(root, [_make_verified_zip(tmp_path, 'media')])
    assert transaction.probe_executable == [str(root / identify_core(root).exe_relpath)]


@pytest.mark.parametrize("components", [("media",), ("matlab",), ("media", "matlab")])
def test_real_source_child_reads_media_from_selected_tree(tmp_path, components):
    """Real PyAV decoding and inherited grant; not a Windows frozen claim."""
    import hashlib
    import importlib.util
    import json
    import os
    import shutil
    from mf4_analyzer.extensions.contract import generate_package_manifest
    from mf4_analyzer.extensions.locking import write_staging_auth
    from mf4_analyzer.extensions.probe import (
        build_probe_request, probe_command, run_authorized_probe, standin_executable,
    )
    from tests.test_extension_transaction import RUNTIME_ID

    root = tmp_path / 'TraceLab'
    _write_core(root)
    staging = root / 'extensions' / '.staging' / 'native'
    targets = {}
    for component in components:
        package_root = staging / component
        module_names = ('av',) if component == 'media' else ('scipy', 'h5py')
        for name in module_names:
            source = Path(importlib.util.find_spec(name).origin).parent
            target = package_root / 'site-packages' / name
            shutil.copytree(source, target, copy_function=os.link,
                            ignore=shutil.ignore_patterns('__pycache__', 'tests', 'test'))
            targets[name] = target
            libs = source.parent / (name + '.libs')
            if libs.is_dir():
                shutil.copytree(libs, target.parent / libs.name, copy_function=os.link)
        files = [{'relpath': p.relative_to(package_root).as_posix(), 'size': p.stat().st_size,
                  'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                 for p in package_root.rglob('*') if p.is_file()]
        manifest = generate_package_manifest(component=component, package_revision=1, runtime_id=RUNTIME_ID,
            component_api='1', min_manager_version='1.0.0', python_tag='cp311', platform_tag='win_amd64',
            module_roots=['site-packages/' + name for name in module_names], dll_directories=[],
            dependency_ownership={name: component for name in module_names},
            files=files, max_extract_bytes=sum(f['size'] for f in files),
            probe_type='media_wav_mp4_v1' if component == 'media' else 'matlab_mat_v73_v1',
            required_features=['store_layout_v1', 'native_probe_v1', 'file_manifest_sha256'])
        (package_root / 'package.json').write_text(json.dumps(manifest))
    write_staging_auth(staging, 'native-nonce')
    request = build_probe_request(core_build_id=identify_core(root).core_build_id, runtime_id=RUNTIME_ID,
        transaction_id='native', components=components, package_hashes=['aa' * 32] * len(components),
        staging_relpath='.staging/native', staging_nonce='native-nonce')
    request['app_root'] = str(root)
    request_path, result_path = staging / 'request.json', staging / 'result.json'
    request_path.write_text(json.dumps(request))
    command = probe_command(standin_executable(), request_path=request_path, result_path=result_path,
                            staging_dir=staging, staging_nonce='native-nonce')
    result = run_authorized_probe(command, timeout_seconds=30, result_path=result_path, app_root=root)
    assert result['native_reads'] is True
    expected = set()
    if 'media' in components:
        expected.update({'sample.wav', 'sample.mp4'})
    if 'matlab' in components:
        expected.update({'legacy.mat', 'sample-v73.mat'})
    assert {entry['name'] for entry in result['files']} == expected
    for name, target in targets.items():
        assert Path(result['module_origins'][name]).is_relative_to(target)


def test_ungranted_child_cannot_overwrite_protected_target(tmp_path):
    from mf4_analyzer.extensions.probe import child_main
    root = tmp_path / 'TraceLab'
    _write_core(root)
    request = tmp_path / 'request.json'
    import json
    request.write_text(json.dumps({'schema': 1, 'components': ['media'],
        'probe_types': ['media_wav_mp4_v1'], 'app_root': str(root)}))
    target = root / 'core.json'
    before = target.read_bytes()
    code = child_main(['--extension-probe-request', str(request), '--extension-probe-result', str(target)])
    assert code != 0
    assert target.read_bytes() == before


def test_core_update_invalidates_health_evidence(tmp_path):
    from dataclasses import replace
    from mf4_analyzer.extensions.health import ensure_runtime_health
    from tests.test_extension_transaction import _engine, _make_verified_zip
    from mf4_analyzer.extensions.locking import MemoryLockBackend
    from mf4_analyzer.extensions.runtime import load_runtime
    root = tmp_path / 'TraceLab'
    _write_core(root)
    backend = MemoryLockBackend()
    _engine(root, backend).install([_make_verified_zip(tmp_path, 'media')])
    snapshot = load_runtime(root, frozen=True, lock_backend=backend)
    calls = []
    def runner(*args, **kwargs):
        calls.append(args)
        return {'ok': True, 'native_reads': True}
    try:
        ensure_runtime_health(snapshot, runner=runner)
        ensure_runtime_health(snapshot, runner=runner)
        assert len(calls) == 1
        cache = next((root / 'extensions/health').glob('*.json'))
        cache.write_text('["malformed-cache"]', encoding='utf-8')
        ensure_runtime_health(snapshot, runner=runner)
        assert len(calls) == 2
        snapshot.core = replace(snapshot.core, envelope=replace(snapshot.core.envelope, core_build_id='new-core'))
        ensure_runtime_health(snapshot, runner=runner)
        assert len(calls) == 3
    finally:
        snapshot.lease.release()
