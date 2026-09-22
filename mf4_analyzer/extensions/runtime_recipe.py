"""Version-controlled runtime recipe used to mint ``runtime_id``.

The recipe names the ABI-affecting dimensions of the shared core.  It must
not include product version, arbitrary source hashes, build timestamps, or
the whole EXE hash — those change on ordinary UI releases without breaking
native extension compatibility.

Shared-library entries bind *content* identity (basename + SHA-256), not
package names.  Names alone cannot mint a runtime_id.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import platform
import sys
import sysconfig
from typing import Any, Mapping, Sequence

from mf4_analyzer.extensions.native_identity import (
    REQUIRED_CORE_SHARED_LIBRARY_NAMES,
    SharedLibraryIdentity,
    collect_core_shared_libraries,
    require_sha256,
    shared_library_from_mapping,
)


RECIPE_VERSION = 1
LOADER_CONTRACT_VERSION = 1
RUNTIME_ID_PREFIX = "rt1-"
PYTHON_BUILD_ID_PREFIX = "cpy-"
MATCH_POLICY_EXACT = "exact"

# Identity fields hashed into runtime_id.  Order is documentary; the digest
# always uses sorted canonical JSON.
RUNTIME_IDENTITY_FIELDS = (
    "recipe_version",
    "loader_contract_version",
    "python_implementation",
    "python_version",
    "python_build_id",
    "python_abi",
    "arch",
    "numpy_version",
    "numpy_abi",
    "core_shared_libraries",
)

# Accepted as keyword arguments for callers/tests, then discarded.
RUNTIME_EXCLUDED_FIELDS = (
    "app_version",
    "source_hash",
    "build_timestamp",
    "exe_sha256",
    "core_build_id",
)

RUNTIME_RECIPE: dict[str, Any] = {
    "recipe_version": RECIPE_VERSION,
    "loader_contract_version": LOADER_CONTRACT_VERSION,
    "match_policy": MATCH_POLICY_EXACT,
    "identity_fields": list(RUNTIME_IDENTITY_FIELDS),
    "excluded_fields": list(RUNTIME_EXCLUDED_FIELDS),
    "core_shared_libraries": [
        {
            "name": "python",
            "role": "cpython_shared",
            "identity": "content_sha256",
            "basename_patterns": [
                "python3*.dll",
                "libpython3*.so*",
                "libpython3*.dylib",
            ],
        },
        {
            "name": "numpy",
            "role": "capi",
            "identity": "content_sha256",
            "basename_patterns": ["*openblas*"],
        },
        {
            "name": "msvc_runtime",
            "role": "ucrt",
            "identity": "content_sha256",
            "required": False,
            "basename_patterns": ["vcruntime*.dll", "msvcp140*.dll"],
        },
    ],
}


def runtime_recipe_json_path() -> Path:
    """Published copy next to the installer sources; not required at import."""
    return (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "extension_manager"
        / "runtime_recipe.json"
    )


def load_runtime_recipe() -> dict[str, Any]:
    """Return a shallow copy of the version-controlled recipe."""
    return json.loads(json.dumps(RUNTIME_RECIPE))


@dataclass(frozen=True)
class RuntimeInputs:
    """ABI snapshot of one core.  Exact match is required in the first version."""

    python_implementation: str
    python_version: str
    python_abi: str
    python_build_id: str
    arch: str
    numpy_version: str
    numpy_abi: str
    core_shared_libraries: tuple[SharedLibraryIdentity, ...]
    loader_contract_version: int = LOADER_CONTRACT_VERSION


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def compute_python_build_id(
    *,
    implementation_name: str,
    hexversion: int,
    soabi: str,
    compiler: str,
) -> str:
    """Fingerprint the actual CPython build, not the TraceLab app build.

    Compile date is omitted: two rebuilds of the same CPython source with the
    same compiler/ABI must not mint a new runtime.  Compiler, SOABI, and
    ``hexversion`` catch compatible-looking but different CPython artifacts.
    """
    payload = {
        "compiler": str(compiler).strip(),
        "hexversion": int(hexversion),
        "implementation": str(implementation_name).strip(),
        "soabi": str(soabi).strip(),
    }
    for key, value in payload.items():
        if value in ("", None):
            raise ValueError(f"python_build_id field {key} must not be empty")
    digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    return f"{PYTHON_BUILD_ID_PREFIX}{digest[:32]}"


def collect_live_python_build_id() -> str:
    soabi = sysconfig.get_config_var("SOABI") or sys.implementation.cache_tag
    return compute_python_build_id(
        implementation_name=sys.implementation.name,
        hexversion=sys.hexversion,
        soabi=str(soabi),
        compiler=platform.python_compiler(),
    )


def _normalize_libraries(
    libraries: Sequence[SharedLibraryIdentity | Mapping[str, Any] | str] | None,
) -> tuple[dict[str, str], ...]:
    if libraries is None:
        raise ValueError(
            "core_shared_libraries must bind content identity (basename + sha256); "
            "omitting the field refuses to mint runtime_id"
        )
    payloads: list[dict[str, str]] = []
    for item in libraries:
        if isinstance(item, str):
            raise ValueError(
                "core_shared_libraries cannot mint runtime_id from names alone; "
                f"refusing library name {item!r} without sha256 content identity"
            )
        if isinstance(item, SharedLibraryIdentity):
            parsed = item
        elif isinstance(item, Mapping):
            parsed = shared_library_from_mapping(item)
        else:
            raise TypeError(
                "core_shared_libraries entries must be SharedLibraryIdentity "
                f"or mappings, not {type(item).__name__}"
            )
        if not parsed.name or not parsed.role or not parsed.basename:
            raise ValueError("shared library name, role, and basename must not be empty")
        digest = require_sha256(parsed.sha256, what="shared library sha256")
        payloads.append(
            {
                "basename": parsed.basename,
                "name": parsed.name,
                "role": parsed.role,
                "sha256": digest,
            }
        )
    if not payloads:
        raise ValueError("core_shared_libraries must bind at least one shared library")
    present = {item["name"] for item in payloads}
    missing = sorted(REQUIRED_CORE_SHARED_LIBRARY_NAMES - present)
    if missing:
        raise ValueError(
            "core_shared_libraries missing required content identity for: "
            + ", ".join(missing)
        )
    by_key: dict[tuple[str, str], str] = {}
    for item in payloads:
        key = (item["name"], item["basename"].lower())
        previous = by_key.get(key)
        if previous is not None and previous != item["sha256"]:
            raise ValueError(
                "refusing to mint runtime_id: same-name shared library "
                f"{item['basename']} has conflicting sha256 content identities"
            )
        by_key[key] = item["sha256"]
    payloads.sort(key=lambda item: (item["name"], item["basename"], item["sha256"]))
    return tuple(payloads)


def compute_runtime_id(
    *,
    python_implementation: str,
    python_version: str,
    python_abi: str,
    arch: str,
    numpy_version: str,
    numpy_abi: str,
    python_build_id: str,
    core_shared_libraries: Sequence[SharedLibraryIdentity | Mapping[str, Any] | str],
    loader_contract_version: int = LOADER_CONTRACT_VERSION,
    **ignored: Any,
) -> str:
    """Return the exact-match runtime fingerprint for a core ABI snapshot.

    Extra keyword arguments such as ``app_version`` or ``build_timestamp`` are
    accepted and discarded so callers cannot accidentally fold them in.
    """
    for name in ignored:
        if name not in RUNTIME_EXCLUDED_FIELDS:
            raise TypeError(f"unexpected runtime_id argument: {name}")
    payload = {
        "arch": str(arch).strip(),
        "core_shared_libraries": list(_normalize_libraries(core_shared_libraries)),
        "loader_contract_version": int(loader_contract_version),
        "numpy_abi": str(numpy_abi).strip(),
        "numpy_version": str(numpy_version).strip(),
        "python_abi": str(python_abi).strip(),
        "python_build_id": str(python_build_id).strip(),
        "python_implementation": str(python_implementation).strip(),
        "python_version": str(python_version).strip(),
        "recipe_version": RECIPE_VERSION,
    }
    for key, value in payload.items():
        if value in ("", None):
            raise ValueError(f"runtime identity field {key} must not be empty")
    digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    return f"{RUNTIME_ID_PREFIX}{digest[:32]}"


def runtime_id_from_inputs(inputs: RuntimeInputs, **ignored: Any) -> str:
    return compute_runtime_id(
        python_implementation=inputs.python_implementation,
        python_version=inputs.python_version,
        python_abi=inputs.python_abi,
        python_build_id=inputs.python_build_id,
        arch=inputs.arch,
        numpy_version=inputs.numpy_version,
        numpy_abi=inputs.numpy_abi,
        core_shared_libraries=inputs.core_shared_libraries,
        loader_contract_version=inputs.loader_contract_version,
        **ignored,
    )


def runtime_inputs_from_base_tree(
    root: Path,
    *,
    python_implementation: str,
    python_version: str,
    python_abi: str,
    python_build_id: str,
    arch: str,
    numpy_version: str,
    numpy_abi: str,
    loader_contract_version: int = LOADER_CONTRACT_VERSION,
) -> RuntimeInputs:
    """Collect core shared-library hashes from a real frozen-style file tree."""
    libraries = collect_core_shared_libraries(root)
    return RuntimeInputs(
        python_implementation=python_implementation,
        python_version=python_version,
        python_abi=python_abi,
        python_build_id=python_build_id,
        arch=arch,
        numpy_version=numpy_version,
        numpy_abi=numpy_abi,
        core_shared_libraries=libraries,
        loader_contract_version=loader_contract_version,
    )


def runtimes_match(left: str, right: str) -> bool:
    """First version: exact equality.  No 'same Python 3.x' fuzz."""
    return str(left) == str(right)


def assert_recipe_json_matches_embedded(path: Path | None = None) -> None:
    """Keep the published JSON copy aligned with the importable recipe."""
    target = path or runtime_recipe_json_path()
    published = json.loads(target.read_text(encoding="utf-8"))
    if published != RUNTIME_RECIPE:
        raise AssertionError(f"{target} diverges from RUNTIME_RECIPE")


def recipe_excludes_field(name: str) -> bool:
    return name in RUNTIME_EXCLUDED_FIELDS


def identity_payload_for_tests(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Project an arbitrary mapping onto identity fields only."""
    return {key: raw[key] for key in RUNTIME_IDENTITY_FIELDS if key in raw}
