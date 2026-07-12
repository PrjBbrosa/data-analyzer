"""Versioned ``QSettings``-backed store for the user dB-reference catalog.

Spec: ``docs/analyzer/specs/2026-07-12-db-reference-defaults-and-labeling-spec.md``
section 12 (User Settings Schema). This is a thin persistence layer over the
pure domain module ``mf4_analyzer.db_reference`` -- it owns the two
``QSettings`` keys, the ``catalog_v1`` JSON delta schema, validate-before-write
atomicity, and an in-process monotonic revision counter. It does NOT fork any
resolver/formatter/validation logic from ``db_reference`` (normalization,
``validate_reference``, ``validate_catalog`` are all imported and reused as-is).

``db_reference``/``db_reference_mode``/catalog revision stay OUT of compute
cache keys everywhere in this project (see
``docs/lessons-learned/signal-processing/2026-06-21-cache-key-dataclass-field-binding-and-phantom-fields.md``);
this module has no compute involvement at all, it only persists the catalog
delta that :func:`mf4_analyzer.db_reference.resolve_db_reference` consumes.

The store never instantiates ``QSettings("MF4Analyzer", "DataAnalyzer")``
implicitly inside a test -- callers (production code) may omit ``settings``
to get the real default, but every test MUST inject an isolated
``QSettings(path, QSettings.IniFormat)`` under ``tmp_path``.
"""
from __future__ import annotations

from dataclasses import dataclass
import json

from PyQt5.QtCore import QSettings

from .. import db_reference


SETTINGS_ORG = "MF4Analyzer"
SETTINGS_APP = "DataAnalyzer"

KEY_CATALOG_V1 = "analysis/db_reference/catalog_v1"
KEY_PREFER_CHANNEL_METADATA = "analysis/db_reference/prefer_channel_metadata"

CATALOG_SCHEMA_VERSION = 1

_FALLBACK_WARNING = (
    "dB 参考默认值设置无法识别（未知版本或格式错误），已使用系统默认目录。"
)


# ---------------------------------------------------------------------------
# Plain, Qt-free result/snapshot types (Task 9 injects ``DbReferenceCatalogSnapshot``
# into Batch worker code, which must never import PyQt/QSettings).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DbReferenceCatalogSnapshot:
    """Immutable effective-catalog snapshot for one point in time.

    ``system_catalog`` holds unmodified, unhidden factory builtins (resolver
    tags these ``system``); ``user_catalog`` holds overridden builtins AND
    custom user entries (resolver tags these ``user``) -- this split is what
    lets :func:`db_reference.resolve_db_reference` report a modified builtin
    as ``source="user"`` while an untouched one stays ``source="system"``.
    """

    system_catalog: tuple  # tuple[db_reference.DbReferenceEntry, ...]
    user_catalog: tuple    # tuple[db_reference.DbReferenceEntry, ...]
    prefer_channel_metadata: bool
    revision: int


@dataclass(frozen=True)
class DbReferenceSaveResult:
    """Outcome of a :meth:`DbReferenceSettingsStore.save` /
    ``restore_factory_defaults`` call. ``error`` is non-empty iff ``ok`` is
    ``False``."""

    ok: bool
    error: str = ""


class _MalformedCatalogDelta(Exception):
    """Internal: raised when a catalog_v1 delta fails structural validation.

    Caught at the load/save boundary and turned into either a factory-catalog
    fallback (load) or a :class:`DbReferenceSaveResult` failure (save) --
    never propagated to callers.
    """


# ---------------------------------------------------------------------------
# Structural field validation (shape-level: wrong type / missing required
# key). Distinct from "unknown built-in id", which is a SEMANTIC mismatch
# handled inertly in ``_compute_effective_catalog`` -- see module docstring
# and spec S12 "unknown fields 可忽略；unknown built-in IDs 不激活".
# ---------------------------------------------------------------------------

def _require_str(value, field):
    if not isinstance(value, str) or not value.strip():
        raise _MalformedCatalogDelta(f"{field} must be a non-empty string")
    return value


def _require_aliases(value, field):
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(a, str) and a for a in value
    ):
        raise _MalformedCatalogDelta(f"{field} must be a list of non-empty strings")
    return tuple(value)


def _require_reference(value, field):
    if not db_reference.validate_reference(value):
        raise _MalformedCatalogDelta(f"{field} must be a finite positive number")
    return float(value)


def _normalize_override_entry(raw):
    if not isinstance(raw, dict):
        raise _MalformedCatalogDelta("override entry must be an object")
    return {
        "builtin_id": _require_str(raw.get("builtin_id"), "builtin_id"),
        "label": _require_str(raw.get("label"), "label"),
        "unit": _require_str(raw.get("unit"), "unit"),
        "aliases": list(_require_aliases(raw.get("aliases"), "aliases")),
        "reference": _require_reference(raw.get("reference"), "reference"),
    }


def _normalize_custom_entry(raw):
    if not isinstance(raw, dict):
        raise _MalformedCatalogDelta("custom entry must be an object")
    return {
        "id": _require_str(raw.get("id"), "id"),
        "quantity": _require_str(raw.get("quantity"), "quantity"),
        "label": _require_str(raw.get("label"), "label"),
        "unit": _require_str(raw.get("unit"), "unit"),
        "aliases": list(_require_aliases(raw.get("aliases"), "aliases")),
        "reference": _require_reference(raw.get("reference"), "reference"),
    }


def _normalize_hidden_ids(raw):
    if not isinstance(raw, (list, tuple)):
        raise _MalformedCatalogDelta("hidden_builtin_ids must be a list")
    out = []
    for item in raw:
        if not isinstance(item, str) or not item:
            raise _MalformedCatalogDelta(
                "hidden_builtin_ids entries must be non-empty strings"
            )
        out.append(item)
    return out


def _ensure_unique_custom_ids(custom):
    seen = set()
    for entry in custom:
        if entry["id"] in seen:
            raise _MalformedCatalogDelta(f"duplicate custom id: {entry['id']!r}")
        seen.add(entry["id"])


def _coerce_bool(value, default=True):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
        return default
    if isinstance(value, int):
        return bool(value)
    return default


# ---------------------------------------------------------------------------
# Effective-catalog computation (pure; shared by load-time validation and
# ``snapshot()``). Unknown builtin ids in ``overrides``/``hidden_builtin_ids``
# are silently INERT here -- never an error (spec S12).
# ---------------------------------------------------------------------------

def _compute_effective_catalog(overrides, custom, hidden_builtin_ids):
    factory_by_id = {e.builtin_id: e for e in db_reference.FACTORY_CATALOG_V1}
    hidden = set(hidden_builtin_ids)
    overridden_ids = set()
    user = []

    for override in overrides:
        builtin_id = override["builtin_id"]
        base = factory_by_id.get(builtin_id)
        if base is None or builtin_id in hidden:
            # Unknown builtin id -> inert; hidden builtin -> excluded
            # entirely (hidden wins over an override of the same id).
            continue
        merged = base.__class__(
            id=base.id,
            quantity=base.quantity,
            label=override["label"],
            unit=override["unit"],
            aliases=tuple(override["aliases"]),
            reference=override["reference"],
            builtin_id=base.builtin_id,
        )
        user.append(merged)
        overridden_ids.add(builtin_id)

    system = tuple(
        entry
        for builtin_id, entry in factory_by_id.items()
        if builtin_id not in hidden and builtin_id not in overridden_ids
    )

    for entry in custom:
        user.append(
            db_reference.DbReferenceEntry(
                id=entry["id"],
                quantity=entry["quantity"],
                label=entry["label"],
                unit=entry["unit"],
                aliases=tuple(entry["aliases"]),
                reference=entry["reference"],
                builtin_id=None,
            )
        )

    return system, tuple(user)


def _parse_catalog_delta(raw_value):
    """Return ``(overrides, custom, hidden_ids)`` (normalized dict lists) or
    ``None`` when ``raw_value`` is structurally unusable: not valid JSON, not
    schema ``1``, an entry with a wrong-typed/missing required field, or a
    resulting catalog with a duplicate ``(quantity, alias)`` pair. All of
    these collapse to the SAME safe fallback (spec S12: "malformed JSON/entry
    同样安全回退并警告") -- there is no partial-merge of a structurally broken
    delta.
    """
    if not isinstance(raw_value, str) or not raw_value.strip():
        return None
    try:
        data = json.loads(raw_value)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != CATALOG_SCHEMA_VERSION:
        return None

    try:
        raw_overrides = data.get("overrides", [])
        raw_custom = data.get("custom", [])
        raw_hidden = data.get("hidden_builtin_ids", [])
        if not isinstance(raw_overrides, list) or not isinstance(raw_custom, list):
            raise _MalformedCatalogDelta("overrides/custom must be lists")
        overrides = [_normalize_override_entry(o) for o in raw_overrides]
        custom = [_normalize_custom_entry(c) for c in raw_custom]
        _ensure_unique_custom_ids(custom)
        hidden = _normalize_hidden_ids(raw_hidden)
    except _MalformedCatalogDelta:
        return None

    system, user = _compute_effective_catalog(overrides, custom, hidden)
    try:
        db_reference.validate_catalog(list(system) + list(user))
    except db_reference.DuplicateAliasError:
        return None

    return overrides, custom, hidden


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

class DbReferenceSettingsStore:
    """Owns ``analysis/db_reference/catalog_v1`` and
    ``analysis/db_reference/prefer_channel_metadata`` in one ``QSettings``
    backend, plus an in-process monotonic ``revision`` counter that only
    advances after a successful :meth:`save` / :meth:`restore_factory_defaults`.

    Pass an isolated ``QSettings(path, QSettings.IniFormat)`` in tests; the
    real application uses the default ``QSettings("MF4Analyzer",
    "DataAnalyzer")`` when ``settings`` is omitted.
    """

    def __init__(self, settings=None):
        self._settings = settings if settings is not None else QSettings(
            SETTINGS_ORG, SETTINGS_APP
        )
        self._revision = 0
        self._warning = ""
        self._overrides = []
        self._custom = []
        self._hidden_builtin_ids = []
        self._prefer_channel_metadata = True
        self._load()

    # -- load ----------------------------------------------------------

    def _load(self):
        self._warning = ""
        raw_pref = self._settings.value(KEY_PREFER_CHANNEL_METADATA, True)
        self._prefer_channel_metadata = _coerce_bool(raw_pref, default=True)

        raw_catalog = self._settings.value(KEY_CATALOG_V1, None)
        if raw_catalog in (None, ""):
            self._overrides, self._custom, self._hidden_builtin_ids = [], [], []
            return

        parsed = _parse_catalog_delta(raw_catalog)
        if parsed is None:
            # Never overwrite the raw key -- surface a non-blocking warning
            # and run on the factory catalog instead (spec S12).
            self._overrides, self._custom, self._hidden_builtin_ids = [], [], []
            self._warning = _FALLBACK_WARNING
            return

        self._overrides, self._custom, self._hidden_builtin_ids = parsed

    # -- read API --------------------------------------------------------

    @property
    def revision(self):
        return self._revision

    @property
    def prefer_channel_metadata(self):
        return self._prefer_channel_metadata

    @property
    def warning(self):
        """Non-blocking warning message from the last load/save, or ``""``.

        Set when a stored ``catalog_v1`` value was structurally unusable;
        cleared on any subsequent successful :meth:`save`/
        :meth:`restore_factory_defaults`.
        """
        return self._warning

    def snapshot(self):
        """An immutable, Qt-free :class:`DbReferenceCatalogSnapshot` safe to
        inject into worker/Batch code (Task 9)."""
        system, user = _compute_effective_catalog(
            self._overrides, self._custom, self._hidden_builtin_ids
        )
        return DbReferenceCatalogSnapshot(
            system_catalog=system,
            user_catalog=user,
            prefer_channel_metadata=self._prefer_channel_metadata,
            revision=self._revision,
        )

    # -- write API ---------------------------------------------------------

    def save(self, *, overrides, custom, hidden_builtin_ids, prefer_channel_metadata):
        """Validate the FULL new catalog delta + preference, then write it
        atomically: nothing is persisted (and no in-memory state changes)
        unless every entry validates AND the resulting merged catalog has no
        duplicate ``(quantity, alias)`` pair.
        """
        try:
            norm_overrides = [_normalize_override_entry(o) for o in overrides]
            norm_custom = [_normalize_custom_entry(c) for c in custom]
            _ensure_unique_custom_ids(norm_custom)
            norm_hidden = _normalize_hidden_ids(list(hidden_builtin_ids))
        except _MalformedCatalogDelta as exc:
            return DbReferenceSaveResult(ok=False, error=str(exc))

        system, user = _compute_effective_catalog(norm_overrides, norm_custom, norm_hidden)
        try:
            db_reference.validate_catalog(list(system) + list(user))
        except db_reference.DuplicateAliasError as exc:
            return DbReferenceSaveResult(ok=False, error=str(exc))

        payload = json.dumps(
            {
                "schema": CATALOG_SCHEMA_VERSION,
                "overrides": norm_overrides,
                "custom": norm_custom,
                "hidden_builtin_ids": norm_hidden,
            },
            ensure_ascii=False,
        )

        prev_catalog_raw = self._settings.value(KEY_CATALOG_V1, None)
        prev_pref_raw = self._settings.value(KEY_PREFER_CHANNEL_METADATA, None)

        self._settings.setValue(KEY_CATALOG_V1, payload)
        self._settings.setValue(KEY_PREFER_CHANNEL_METADATA, bool(prefer_channel_metadata))
        self._settings.sync()
        if self._settings.status() != QSettings.NoError:
            self._rollback_key(KEY_CATALOG_V1, prev_catalog_raw)
            self._rollback_key(KEY_PREFER_CHANNEL_METADATA, prev_pref_raw)
            self._settings.sync()
            return DbReferenceSaveResult(ok=False, error="settings sync failed")

        self._overrides = norm_overrides
        self._custom = norm_custom
        self._hidden_builtin_ids = norm_hidden
        self._prefer_channel_metadata = bool(prefer_channel_metadata)
        self._warning = ""
        self._revision += 1
        return DbReferenceSaveResult(ok=True)

    def restore_factory_defaults(self):
        """Delete the user catalog delta. ``prefer_channel_metadata`` is left
        untouched -- restore never implicitly toggles it. The immutable
        factory constant (``db_reference.FACTORY_CATALOG_V1``) is never
        mutated; this only clears what THIS store persisted on top of it.
        """
        prev_catalog_raw = self._settings.value(KEY_CATALOG_V1, None)
        self._settings.remove(KEY_CATALOG_V1)
        self._settings.sync()
        if self._settings.status() != QSettings.NoError:
            self._rollback_key(KEY_CATALOG_V1, prev_catalog_raw)
            self._settings.sync()
            return DbReferenceSaveResult(ok=False, error="settings sync failed")

        self._overrides = []
        self._custom = []
        self._hidden_builtin_ids = []
        self._warning = ""
        self._revision += 1
        return DbReferenceSaveResult(ok=True)

    def _rollback_key(self, key, prev_value):
        if prev_value is None:
            self._settings.remove(key)
        else:
            self._settings.setValue(key, prev_value)
