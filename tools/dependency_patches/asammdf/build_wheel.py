"""Build the pinned TraceLab MDF reader without modifying the caller's runtime.

Usage: python tools/dependency_patches/asammdf/build_wheel.py --output DIR
Requires git and a native C compiler. Install the resulting wheel separately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import venv


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).resolve().parent
    lock = json.loads((here / 'source.lock.json').read_text())
    env = {**os.environ, 'SOURCE_DATE_EPOCH': '1792195200'}
    with tempfile.TemporaryDirectory(prefix='tracelab-mdf-build-') as tmp:
        tmp = Path(tmp)
        archive = tmp / 'source.tar.gz'
        urllib.request.urlretrieve(lock['source']['url'], archive)
        if digest(archive) != lock['source']['sha256']:
            raise RuntimeError('asammdf source hash mismatch')
        with tarfile.open(archive) as tar:
            tar.extractall(tmp / 'source', filter='data')
        source, = (tmp / 'source').iterdir()
        for name, expected in lock['source_files'].items():
            if digest(source / name) != expected:
                raise RuntimeError(f'Unreviewed source: {name}')
        for name, expected in lock['patches'].items():
            patch = here / name
            if digest(patch) != expected:
                raise RuntimeError(f'Patch hash mismatch: {name}')
            # Zero-context patches avoid whitespace-only context lines in Git.
            # Exact source hashes above prevent applying to a shifted source.
            subprocess.run(['git', 'apply', '--unidiff-zero', '--check', str(patch)], cwd=source, check=True)
            subprocess.run(['git', 'apply', '--unidiff-zero', str(patch)], cwd=source, check=True)
        build_env = tmp / 'venv'
        venv.EnvBuilder(with_pip=True).create(build_env)
        python = build_env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        subprocess.run([str(python), '-m', 'pip', 'install', '--require-hashes',
                        '--only-binary=:all:', '-r', str(here / 'build-requirements.lock')], check=True)
        subprocess.run([str(python), '-m', 'pip', 'wheel', '--no-deps',
                        '--no-build-isolation', '--wheel-dir', str(output), str(source)],
                       env=env, check=True)
        wheels = list(output.glob('asammdf-8.8.32+tracelab.1-*.whl'))
        if len(wheels) != 1:
            raise RuntimeError('Use a separate output directory per Python/platform build')
        wheel = wheels[0]
        report = {'wheel': wheel.name, 'sha256': digest(wheel), 'source': lock,
                  'python': sys.version, 'platform': platform.platform(),
                  'machine': platform.machine(), 'source_date_epoch': env['SOURCE_DATE_EPOCH'],
                  'build_lock_sha256': digest(here / 'build-requirements.lock'),
                  'patched_files': {name: digest(source / name) for name in lock['source_files']},
                  'build_packages': subprocess.check_output(
                      [str(python), '-m', 'pip', 'freeze'], text=True).splitlines()}
        (output / (wheel.name + '.json')).write_text(json.dumps(report, indent=2) + '\n')
        # Retain the exact modified LGPL source and license for distribution.
        with tarfile.open(output / 'asammdf-8.8.32+tracelab.1-source.tar.gz', 'w:gz') as tar:
            tar.add(source, arcname='asammdf-8.8.32+tracelab.1',
                    filter=lambda info: None if '/build/' in info.name else info)
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
