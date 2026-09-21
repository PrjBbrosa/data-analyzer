"""Version-controlled runtime recipe used to mint ``runtime_id``.

The recipe names the ABI-affecting dimensions of the shared core.  It must
not include product version, arbitrary source hashes, build timestamps, or
the whole EXE hash — those change on ordinary UI releases without breaking
native extension compatibility.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


RECIPE_VERSION = 1
LOADER_CONTRACT_VERSION = 1
RUNTIME_ID_PREFIX = "rt1-"
MATCH_POLICY_EXACT = "exact"

# Identity fields hashed into runtime_id.  Order is documentary; the digest
# always uses sorted canonical JSON.
RUNTIME_IDENTITY_FIELDS = (
    "recipe_version",
    "loader_contract_version",
    "python_implementation",
    "python_version",
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

DEFAULT_CORE_SHARED_LIBRARIES = (
    "python",
    "numpy",
)

RUNTIME_RECIPE: dict[str, Any] = {
    "recipe_version": RECIPE_VERSION,
    "loader_contract_version": LOADER_CONTRACT_VERSION,
    "match_policy": MATCH_POLICY_EXACT,
    "identity_fields": list(RUNTIME_IDENTITY_FIELDS),
    "excluded_fields": list(RUNTIME_EXCLUDED_FIELDS),
    "core_shared_libraries": [
        {"name": "python", "role": "cpython_shared"},
        {"name": "numpy", "role": "capi"},
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
    arch: str
    numpy_version: str
    numpy_abi: str
    core_shared_libraries: tuple[str, ...] = DEFAULT_CORE_SHARED_LIBRARIES
    loader_contract_version: int = LOADER_CONTRACT_VERSION


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _normalize_libraries(libraries: Sequence[str] | None) -> tuple[str, ...]:
    if libraries is None:
        libraries = DEFAULT_CORE_SHARED_LIBRARIES
    normalized = tuple(sorted({str(item).strip() for item in libraries if str(item).strip()}))
    if not normalized:
        raise ValueError("core_shared_libraries must name at least one shared library")
    return normalized


def compute_runtime_id(
    *,
    python_implementation: str,
    python_version: str,
    python_abi: str,
    arch: str,
    numpy_version: str,
    numpy_abi: str,
    core_shared_libraries: Sequence[str] | None = None,
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
        arch=inputs.arch,
        numpy_version=inputs.numpy_version,
        numpy_abi=inputs.numpy_abi,
        core_shared_libraries=inputs.core_shared_libraries,
        loader_contract_version=inputs.loader_contract_version,
        **ignored,
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
