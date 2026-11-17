# TraceLab asammdf build

The official 8.8.32 sdist already contains the C bounds fixes from
[e79453d6650c9f5d716447bdeac363fe3bb9e9a0](https://github.com/danielhrisca/asammdf/commit/e79453d6650c9f5d716447bdeac363fe3bb9e9a0)
and [1d6e3cb6a9a1db2548420018725be1841857926d](https://github.com/danielhrisca/asammdf/commit/1d6e3cb6a9a1db2548420018725be1841857926d),
including the parallel and complete readers. Its Python array stride algorithm
is still incorrect. Patch 0001 backports the missing Python hunk. Patch 0002
gives this artifact a local version and a C extension safety revision, so a
mixed installation cannot pass the runtime array gate.

From the repository root, with Python 3.12+, git and a platform C compiler:

```sh
python tools/dependency_patches/asammdf/build_wheel.py --output .state/dependency-wheels
python -m pip install --find-links .state/dependency-wheels -r requirements.txt
```

The helper creates its own build venv, verifies the sdist and patch hashes,
installs hash-locked build dependencies, and writes the platform wheel, build
manifest (Python/platform, source and wheel SHA-256), and modified source archive.
Patch hashes are the LF bytes in `source.lock.json`. A Windows checkout may
rewrite those files to CRLF; the helper normalizes line endings before the
check and before `git apply`.
It never installs into the calling interpreter. Use a separate output directory
for each build target. Windows Full and Lite must use this same requirement and
wheelhouse; an unpatched public release does not satisfy it.

The sdist includes the upstream LGPLv3+ license and native library licenses.
Retain/distribute the modified source archive and its license files with any
redistribution of this wheel. This directory contains only our small patches,
locked provenance and build helper; customer files and generated binaries are
not checked in.

This is a reproducible source/build recipe, not a claim of byte-for-byte wheels
across different compilers/SDKs. SOURCE_DATE_EPOCH is fixed; each actual binary
has its own recorded hash. macOS arm64 has been built and tested in a source
child process. Other macOS targets, Windows/Linux builds, fresh Full/Lite EXEs,
and frozen module identity remain separate acceptance gates.

Regression commands (from the project runtime):

```sh
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/test_mdf_reader_safety.py tests/test_mf4_loader.py -q
```

The safety suite supervises risky native reads in timed child processes. Its
rectangular and three-dimensional arrays include wrong-but-in-bounds layouts;
bounds checks alone cannot certify their values. Runtime metadata validation
does not decompress every block and is not payload integrity certification.
