"""Versioned ``QSettings``-backed store for the batch panel's display prefs.

Plan: ``docs/analyzer/plans/2026-08-02-batch-settings-persistence-plan.md``
(section 2.1). Structure follows :mod:`mf4_analyzer.ui.db_reference_settings`
-- one owned key, a schema version, validate-before-write, and an injectable
``QSettings`` backend.

**Two layers, and the boundary is the whole point.** This store remembers
only how the user likes an export to *look* -- tick density, text scale, the
export toggles/format block, and the output directory. It never remembers
what an export is *bound to*: file list, target signals, RPM channel and its
coefficient, axis ranges (``axes``), or the analysis method and its
parameters. A signal name carried into a new session only produces "目标信号
在所选来源中不可用" against a fresh source, and an axis range is a function of
the data's scale, not of the user's taste. The dB reference is excluded for a
different reason: :mod:`mf4_analyzer.ui.db_reference_settings` already owns
it, and a second copy would be a second truth.

``BatchOutput.requested_image_format`` / ``BatchOutput.migration_warnings``
are runtime diagnostics and ``resume_policy`` is a single-run intent, so the
output whitelist below is spelled out by hand rather than derived from
``dataclasses.asdict(BatchOutput(...))`` -- that way none of the three can
ever reach a user's config file, not even by accident when the dataclass
grows a field.

Out-of-range numbers are clamped rather than rejected: ``RenderStyle`` already
owns that policy for tick density and font scale (``batch_render_style``), and
a preference file must never be able to block the panel from opening. Anything
this module cannot make sense of -- unknown schema, corrupt JSON, wrong types
-- collapses silently to the hard-coded defaults.

The store never instantiates ``QSettings("MF4Analyzer", "DataAnalyzer")``
implicitly inside a test -- production callers may omit ``settings`` to get
the real default, but every test MUST inject an isolated
``QSettings(path, QSettings.IniFormat)`` under ``tmp_path``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json

from PyQt5.QtCore import QSettings

from ..batch import BatchOutput
from ..batch_render_style import render_style_from_params


SETTINGS_ORG = "MF4Analyzer"
SETTINGS_APP = "DataAnalyzer"

KEY_PANEL_PREFS_V1 = "batch/panel_prefs_v1"

PREFS_SCHEMA_VERSION = 1


#: Serializable ``BatchOutput`` fields, by coercion kind. Runtime-only fields
#: (``resume_policy``, ``requested_image_format``, ``migration_warnings``) are
#: deliberately absent -- see the module docstring.
_BOOL_OUTPUT_FIELDS = ("export_data", "export_image", "write_manifest")
_STR_OUTPUT_FIELDS = (
    "data_format", "image_format", "image_size", "image_background",
    "conflict_policy",
)
_INT_OUTPUT_FIELDS = ("image_width", "image_height", "image_dpi")
_FLOAT_OUTPUT_FIELDS = ("image_line_width",)

#: Every output key this store will ever read or write.
OUTPUT_FIELDS = (
    _BOOL_OUTPUT_FIELDS
    + _STR_OUTPUT_FIELDS
    + _INT_OUTPUT_FIELDS
    + _FLOAT_OUTPUT_FIELDS
)

#: Runtime-only ``BatchOutput`` fields, named here so the negative guard in
#: ``tests/ui/test_batch_settings.py`` can assert against one shared list.
RUNTIME_OUTPUT_FIELDS = (
    "resume_policy", "requested_image_format", "migration_warnings",
)


def _default_settings() -> QSettings:
    """The real user store.

    A named seam rather than an inline constructor call so ``tests/ui``
    can redirect every implicitly-constructed store to a throwaway INI (see
    ``tests/ui/conftest.py``); dozens of existing ``BatchSheet(...)`` tests
    predate this store and cannot all inject one by hand.
    """
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def _coerce_bool(value, default: bool) -> bool:
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


def _coerce_str(value, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return default


def _coerce_int(value, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def normalize_render_style(raw) -> dict:
    """Return the three render-style params, clamped to their legal span.

    Delegates to ``render_style_from_params`` so this module never forks
    ``RenderStyle``'s clamp/default policy.
    """
    values = dict(raw) if isinstance(raw, dict) else {}
    return render_style_from_params(values).as_params()


def normalize_outputs(raw) -> dict:
    """Return the whitelisted output fields, defaults filled in.

    Unknown keys are dropped and unusable values fall back per field, so a
    hand-edited or newer-UI payload can never reach ``BatchOutput(**...)``
    as an unexpected keyword.
    """
    values = dict(raw) if isinstance(raw, dict) else {}
    defaults = BatchOutput()
    out: dict = {}
    for name in _BOOL_OUTPUT_FIELDS:
        out[name] = _coerce_bool(values.get(name), getattr(defaults, name))
    for name in _STR_OUTPUT_FIELDS:
        out[name] = _coerce_str(values.get(name), getattr(defaults, name))
    for name in _INT_OUTPUT_FIELDS:
        out[name] = _coerce_int(values.get(name), getattr(defaults, name))
    for name in _FLOAT_OUTPUT_FIELDS:
        out[name] = _coerce_float(values.get(name), getattr(defaults, name))
    return out


def normalize_directory(raw) -> str:
    return raw.strip() if isinstance(raw, str) else ""


@dataclass(frozen=True)
class BatchPanelPrefs:
    """One snapshot of the batch panel's remembered display preferences.

    Normalizes on construction so an instance built by hand (tests, a caller
    passing a partial dict) carries exactly the same shape as one that made a
    round trip through ``QSettings``.
    """

    directory: str = ""
    render_style: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    #: 「完成后打开输出文件夹」-- a panel-level UI preference, not part of
    #: ``BatchOutput`` (the runner never sees it). Defaults to on, and a
    #: payload written before this field existed lacks the key entirely, so
    #: the schema version does not need to move for it.
    open_folder_after_run: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "directory", normalize_directory(self.directory))
        object.__setattr__(
            self, "render_style", normalize_render_style(self.render_style)
        )
        object.__setattr__(self, "outputs", normalize_outputs(self.outputs))
        object.__setattr__(
            self,
            "open_folder_after_run",
            _coerce_bool(self.open_folder_after_run, True),
        )

    def as_output(self) -> BatchOutput:
        """Build a ``BatchOutput`` from the remembered fields only.

        Runtime fields keep their dataclass defaults; this never resurrects a
        stale ``migration_warnings`` or a previous run's ``resume_policy``.
        """
        return BatchOutput(**self.outputs)

    def as_payload(self) -> dict:
        return {
            "schema": PREFS_SCHEMA_VERSION,
            "directory": self.directory,
            "render_style": dict(self.render_style),
            "outputs": dict(self.outputs),
            "open_folder_after_run": self.open_folder_after_run,
        }


class BatchPanelPrefsStore:
    """Owns ``batch/panel_prefs_v1`` in one ``QSettings`` backend.

    Pass an isolated ``QSettings(path, QSettings.IniFormat)`` in tests; the
    real application uses ``QSettings("MF4Analyzer", "DataAnalyzer")`` when
    ``settings`` is omitted.
    """

    def __init__(self, settings=None):
        self._settings = settings if settings is not None else _default_settings()

    def load(self) -> BatchPanelPrefs:
        """Return the stored preferences, or hard-coded defaults.

        Never raises and never rewrites the key: an unreadable payload is
        left in place (a future schema may understand it) while this session
        runs on defaults.
        """
        try:
            raw = self._settings.value(KEY_PANEL_PREFS_V1, None)
        except Exception:
            return BatchPanelPrefs()
        if not isinstance(raw, str) or not raw.strip():
            return BatchPanelPrefs()
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return BatchPanelPrefs()
        if not isinstance(data, dict):
            return BatchPanelPrefs()
        if data.get("schema") != PREFS_SCHEMA_VERSION:
            return BatchPanelPrefs()
        try:
            return BatchPanelPrefs(
                directory=data.get("directory", ""),
                render_style=data.get("render_style"),
                outputs=data.get("outputs"),
                open_folder_after_run=data.get("open_folder_after_run", True),
            )
        except Exception:
            return BatchPanelPrefs()

    def save(self, prefs: BatchPanelPrefs) -> None:
        """Normalize, then write. A payload that cannot be built is dropped.

        Returns nothing on purpose: persisting a display preference must
        never be able to fail the dialog close or the run start that
        triggered it.
        """
        if prefs is None:
            return
        try:
            payload = json.dumps(
                BatchPanelPrefs(
                    directory=getattr(prefs, "directory", ""),
                    render_style=getattr(prefs, "render_style", None),
                    outputs=getattr(prefs, "outputs", None),
                    open_folder_after_run=getattr(
                        prefs, "open_folder_after_run", True
                    ),
                ).as_payload(),
                ensure_ascii=False,
                sort_keys=True,
            )
        except (TypeError, ValueError):
            return
        try:
            self._settings.setValue(KEY_PANEL_PREFS_V1, payload)
            self._settings.sync()
        except Exception:
            return

    def clear(self) -> None:
        """Forget everything this store persisted (the 恢复默认 escape hatch)."""
        try:
            self._settings.remove(KEY_PANEL_PREFS_V1)
            self._settings.sync()
        except Exception:
            return


__all__ = [
    "KEY_PANEL_PREFS_V1",
    "OUTPUT_FIELDS",
    "PREFS_SCHEMA_VERSION",
    "RUNTIME_OUTPUT_FIELDS",
    "SETTINGS_APP",
    "SETTINGS_ORG",
    "BatchPanelPrefs",
    "BatchPanelPrefsStore",
    "normalize_directory",
    "normalize_outputs",
    "normalize_render_style",
]
