"""State-rule ``border:`` shorthand must not silently zero ``border-radius``.

Qt stylesheet cascade is **not** CSS: when a more specific rule redeclares the
``border:`` shorthand and omits ``border-radius``, the radius resets to 0 for
that rule — measured in ``f4a6b923`` (combo drop-down) and catalogued as E2 in
the 2026-08-12 guideline-hardening review. Team convention is to change only
``border-color`` / ``border-width`` / ``border-style`` in state rules, or to
restate ``border-radius`` when a shorthand is unavoidable.

This lint freezes the empty-violation set. The whitelist may only **shrink**.

F6 closed two matcher blind spots that let injected state rules leak:

* id-only ``#objectName[attr]`` / ``#objectName:pseudo`` against a *type*
  baseline (``#dbReferenceEditor`` is a ``QDoubleSpinBox``);
* ``::sub-control:state`` against the parent widget
  (``channelTree::item:selected`` vs ``QTreeWidget#channelTree``).
"""
from __future__ import annotations

import ast
import functools
import re
from collections.abc import Mapping
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_QSS_PATH = _REPO_ROOT / "mf4_analyzer" / "ui_kit" / "style.qss"
_PACKAGE_ROOT = _REPO_ROOT / "mf4_analyzer"

# Frozen at Task 14 (E2). THIS SET MAY ONLY SHRINK — a new entry means a state
# rule reintroduced ``border:`` shorthand over a radius-bearing baseline.
ALLOWED_BORDER_SHORTHAND_STATE_RULES: frozenset[str] = frozenset()

_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_TOKEN_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")
_BLOCK_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
_STATE_PSEUDO_RE = re.compile(
    r":(?:hover|pressed|checked|disabled|focus|selected|active|enabled|"
    r"indeterminate)\b"
)
_ATTR_RE = re.compile(r"\[[^\]]+\]")
_BORDER_SHORTHAND_RE = re.compile(r"(?<![\w-])border\s*:\s*([^;]+)")
_HAS_RADIUS_RE = re.compile(r"(?<![\w-])border-radius\s*:")
_TRAILING_PSEUDO_RE = re.compile(
    r"^(.*?)(?<![:]):(?:hover|pressed|checked|disabled|focus|selected|"
    r"active|enabled|indeterminate)$"
)
_TRAILING_ATTR_RE = re.compile(r"^(.*)(\[[^\]]+\])$")
_TRAILING_SUBCONTROL_RE = re.compile(
    r"^(.*)(::[\w-]+)(?::(?:horizontal|vertical))?$"
)
_ID_ONLY_SUBJECT_RE = re.compile(r"#([A-Za-z_][\w-]*)")
_TYPED_ID_RE = re.compile(r"^[\w]+#([A-Za-z_][\w-]*)$")

# Qt widget types that appear as QSS element selectors. Used to flatten
# ``setObjectName`` owners (``ScientificReferenceSpinBox(QDoubleSpinBox)``)
# onto the type baseline the cascade actually inherits from.
_QT_WIDGET_TYPES = frozenset(
    {
        "QWidget",
        "QFrame",
        "QLabel",
        "QLineEdit",
        "QPlainTextEdit",
        "QTextEdit",
        "QPushButton",
        "QToolButton",
        "QRadioButton",
        "QCheckBox",
        "QComboBox",
        "QSpinBox",
        "QDoubleSpinBox",
        "QAbstractSpinBox",
        "QAbstractButton",
        "QTreeWidget",
        "QTreeView",
        "QListWidget",
        "QListView",
        "QTableWidget",
        "QTableView",
        "QHeaderView",
        "QAbstractItemView",
        "QGroupBox",
        "QScrollArea",
        "QScrollBar",
        "QSlider",
        "QProgressBar",
        "QDialog",
        "QMainWindow",
        "QTabWidget",
        "QTabBar",
        "QStackedWidget",
        "QSplitter",
        "QMenu",
        "QMenuBar",
        "QStatusBar",
        "QDockWidget",
        "QToolBar",
        "QToolBox",
        "QGraphicsView",
        "QCalendarWidget",
        "QDateEdit",
        "QTimeEdit",
        "QDial",
    }
)

_PROBE_BORDER = "3px solid #ff00aa"

# 12 selector shapes. Review measured 10 caught / 2 leaked before F6;
# p07 is the ``#id[attr]`` type-baseline miss and p08 is ``::sub-control:state``.
_INJECTED_SHAPES: tuple[tuple[str, str], ...] = (
    ("QPushButton#f6p01:hover", "QPushButton#f6p01"),
    ("QToolButton#f6p02:pressed", "QToolButton#f6p02"),
    ('QPushButton#f6p03[role="tool"]', "QPushButton#f6p03"),
    ("QLineEdit#f6p04:focus", "QLineEdit#f6p04"),
    ('QLineEdit#f6p05[error="true"]', "QLineEdit#f6p05"),
    ("#f6p06:hover", "QFrame#f6p06"),
    ('#f6p07[error="true"]', "QDoubleSpinBox"),
    ("QTreeWidget#f6p08::item:selected", "QTreeWidget#f6p08"),
    ("QComboBox#f6p09::drop-down:hover", "QComboBox#f6p09"),
    ("Inspector QPushButton#f6p10:hover", "QPushButton#f6p10"),
    ("QPushButton#f6p11:hover:pressed", "QPushButton#f6p11"),
    ('QWidget#f6p12[foo="true"]:hover', "QWidget#f6p12"),
)

_INJECTED_OBJECT_NAME_TYPES: dict[str, frozenset[str]] = {
    "f6p07": frozenset({"QDoubleSpinBox"}),
}


def _norm(sel: str) -> str:
    return " ".join(sel.split())


def _is_state_selector(sel: str) -> bool:
    """Pseudo-classes, ``[attr]``, and ``::sub-control:state`` count as state."""
    if _STATE_PSEUDO_RE.search(sel) or _ATTR_RE.search(sel):
        return True
    return bool(re.search(r"::[\w-]+:(?:hover|pressed|checked|disabled|focus|"
                          r"selected|active|enabled|indeterminate)\b", sel))


def _strip_states(sel: str) -> list[str]:
    """Peel trailing ``:pseudo`` / ``[attr]`` / ``::sub-control`` candidates.

    ``::sub-control`` is peeled only after a state pseudo was removed
    (``::item:selected`` → parent widget). Bare ``[attr]::up-button``
    rules must not inherit the parent's radius baseline — that subcontrol
    does not paint the parent's rounded frame.
    """
    out: list[str] = []
    cur = sel
    peeled_state_pseudo = False
    while True:
        out.append(cur)
        m = _TRAILING_PSEUDO_RE.search(cur)
        if m:
            cur = m.group(1)
            peeled_state_pseudo = True
            continue
        m = _TRAILING_ATTR_RE.search(cur)
        if m:
            cur = m.group(1)
            continue
        m = _TRAILING_SUBCONTROL_RE.search(cur)
        if m and m.group(1) and peeled_state_pseudo:
            cur = m.group(1)
            continue
        break
    return list(dict.fromkeys(out))


def _prepare_sheet(text: str) -> str:
    """Comments out; neutralize ``{{TOKEN}}`` so ``{``/``}`` block parsing works."""
    text = _COMMENT_RE.sub("", text)
    return _TOKEN_RE.sub("__TOKEN__", text)


def _parse_sheet() -> str:
    return _prepare_sheet(_QSS_PATH.read_text(encoding="utf-8"))


def _baseline_radius_selectors(text: str) -> set[str]:
    found: set[str] = set()
    for sels, body in _BLOCK_RE.findall(text):
        if not _HAS_RADIUS_RE.search(body):
            continue
        for raw in sels.split(","):
            sel = _norm(raw)
            if sel:
                found.add(sel)
    return found


def _id_only_object_name(sel: str) -> str | None:
    """Return objectName when the rule's subject is a pure ``#id`` selector."""
    subject = sel.split()[-1]
    m = _ID_ONLY_SUBJECT_RE.match(subject)
    return m.group(1) if m else None


def _match_typed_id_baseline(oid: str, baselines: set[str]) -> str | None:
    exact = f"#{oid}"
    if exact in baselines:
        return exact
    for baseline in baselines:
        last = baseline.split()[-1]
        m = _TYPED_ID_RE.match(last)
        if m and m.group(1) == oid:
            return baseline
    return None


def _match_baseline(
    sel: str,
    baselines: set[str],
    object_name_types: Mapping[str, frozenset[str]] | None = None,
) -> str | None:
    cands = _strip_states(sel)
    for cand in cands[1:]:
        if cand in baselines:
            return cand
    bare = cands[-1]
    if bare in baselines:
        return bare
    last = bare.split()[-1]
    if last in baselines:
        return last
    oid = _id_only_object_name(sel)
    if oid is None:
        return None
    typed = _match_typed_id_baseline(oid, baselines)
    if typed is not None:
        return typed
    if not object_name_types:
        return None
    for qt_cls in object_name_types.get(oid, ()):
        if qt_cls in baselines:
            return qt_cls
        for baseline in baselines:
            if baseline.split()[-1] == qt_cls:
                return baseline
    return None


def _base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _call_ctor_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        return _base_name(node.func)
    return None


def _assignment_types(func: ast.AST) -> dict[str, str]:
    types: dict[str, str] = {}
    for node in ast.walk(func):
        ctor = None
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign):
            ctor = _call_ctor_name(node.value)
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            ctor = _call_ctor_name(node.value)
            targets = [node.target]
        if not ctor:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                types[target.id] = ctor
            elif (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                types[f"self.{target.attr}"] = ctor
    return types


def _object_name_arg(call: ast.Call) -> str | None:
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "setObjectName"):
        return None
    if not call.args:
        return None
    return _const_str(call.args[0])


def _qt_types_of(name: str, class_bases: dict[str, tuple[str, ...]]) -> set[str]:
    seen: set[str] = set()
    out: set[str] = set()

    def walk(cur: str) -> None:
        if cur in seen:
            return
        seen.add(cur)
        if cur in _QT_WIDGET_TYPES:
            out.add(cur)
        for base in class_bases.get(cur, ()):
            walk(base)

    walk(name)
    return out


@functools.lru_cache(maxsize=1)
def collect_object_name_qt_types() -> dict[str, frozenset[str]]:
    """Map ``objectName`` → Qt widget types via ``setObjectName`` owners."""
    class_bases: dict[str, tuple[str, ...]] = {}
    raw: dict[str, set[str]] = {}
    for path in _PACKAGE_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            class_bases[cls.name] = tuple(
                name for name in (_base_name(base) for base in cls.bases) if name
            )
            for node in cls.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                local_types = _assignment_types(node)
                for call in ast.walk(node):
                    if not isinstance(call, ast.Call):
                        continue
                    oid = _object_name_arg(call)
                    if oid is None:
                        continue
                    recv = call.func.value
                    owners: list[str] = []
                    if isinstance(recv, ast.Name) and recv.id == "self":
                        owners.append(cls.name)
                    elif isinstance(recv, ast.Name) and recv.id in local_types:
                        owners.append(local_types[recv.id])
                    elif (
                        isinstance(recv, ast.Attribute)
                        and isinstance(recv.value, ast.Name)
                        and recv.value.id == "self"
                    ):
                        key = f"self.{recv.attr}"
                        if key in local_types:
                            owners.append(local_types[key])
                    raw.setdefault(oid, set()).update(owners)
    resolved: dict[str, frozenset[str]] = {}
    for oid, owners in raw.items():
        types: set[str] = set()
        for owner in owners:
            types |= _qt_types_of(owner, class_bases)
        if types:
            resolved[oid] = frozenset(types)
    return resolved


def find_border_shorthand_state_violations(
    text: str | None = None,
    *,
    object_name_types: Mapping[str, frozenset[str]] | None = None,
) -> list[tuple[str, str, str]]:
    """Return ``(selector, border_value, baseline_selector)`` violations."""
    if text is None:
        text = _parse_sheet()
    else:
        text = _prepare_sheet(text)
    if object_name_types is None:
        object_name_types = collect_object_name_qt_types()
    baselines = _baseline_radius_selectors(text)
    violations: list[tuple[str, str, str]] = []
    for sels, body in _BLOCK_RE.findall(text):
        shorthand = _BORDER_SHORTHAND_RE.search(body)
        if not shorthand:
            continue
        # Restating radius alongside shorthand is the approved escape hatch
        # (see autoAttachFiles / combo item:selected).
        if _HAS_RADIUS_RE.search(body):
            continue
        for raw in sels.split(","):
            sel = _norm(raw)
            if not sel or not _is_state_selector(sel):
                continue
            baseline = _match_baseline(sel, baselines, object_name_types)
            if baseline is None:
                continue
            violations.append((sel, shorthand.group(1).strip(), baseline))
    return violations


def _injected_sheet(base: str) -> str:
    chunks = [base, "\n/* F6 probe shapes — not production QSS */\n"]
    seen_baselines: set[str] = set()
    for state_sel, baseline_sel in _INJECTED_SHAPES:
        if baseline_sel not in seen_baselines:
            chunks.append(f"{baseline_sel} {{ border-radius: 9px; }}\n")
            seen_baselines.add(baseline_sel)
        chunks.append(f"{state_sel} {{ border: {_PROBE_BORDER}; }}\n")
    return "".join(chunks)


def test_state_border_shorthand_whitelist_is_honored():
    violations = find_border_shorthand_state_violations()
    found = {sel for sel, _val, _base in violations}
    unexpected = sorted(found - ALLOWED_BORDER_SHORTHAND_STATE_RULES)
    stale = sorted(ALLOWED_BORDER_SHORTHAND_STATE_RULES - found)
    assert unexpected == [], (
        "state rule(s) use border: shorthand over a radius-bearing baseline "
        f"without restating border-radius (fix with border-color/width/style, "
        f"or restate radius): {unexpected}"
    )
    assert stale == [], (
        "ALLOWED_BORDER_SHORTHAND_STATE_RULES has stale entries — shrink the "
        f"whitelist, do not keep ghosts: {stale}"
    )


def test_channel_tree_selected_restates_border_radius():
    """E1: opaque selected fill must carry its own radius (parent 9 − border 1)."""
    text = _parse_sheet()
    item_radius = None
    branch_radius = None
    for sels, body in _BLOCK_RE.findall(text):
        for raw in sels.split(","):
            sel = _norm(raw)
            if sel == "QTreeWidget#channelTree::item:selected":
                m = re.search(r"(?<![\w-])border-radius\s*:\s*(\d+)px", body)
                item_radius = int(m.group(1)) if m else None
            if sel == "QTreeWidget#channelTree::branch:selected":
                m = re.search(r"(?<![\w-])border-radius\s*:\s*(\d+)px", body)
                branch_radius = int(m.group(1)) if m else None
    assert item_radius in {6, 8}, (
        f"channelTree::item:selected must declare border-radius 6 or 8 "
        f"(parent 9 − border 1), got {item_radius!r}"
    )
    assert branch_radius == item_radius, (
        f"branch:selected radius {branch_radius!r} must match item:selected "
        f"{item_radius!r}"
    )


def test_id_only_attr_state_matches_objectname_type_baseline():
    """Blind spot ①: ``#id[attr]`` must see the widget type's radius baseline."""
    text = (
        "QDoubleSpinBox { border-radius: 7px; }\n"
        '#dbReferenceEditor[error="true"] { border: 1px solid #dc2626; }\n'
    )
    types = {"dbReferenceEditor": frozenset({"QDoubleSpinBox"})}
    found = find_border_shorthand_state_violations(text, object_name_types=types)
    assert found == [
        ('#dbReferenceEditor[error="true"]', "1px solid #dc2626", "QDoubleSpinBox")
    ]


def test_subcontrol_state_matches_parent_widget_baseline():
    """Blind spot ②: ``::item:selected`` must see the parent widget radius."""
    text = (
        "QTreeWidget#channelTree { border-radius: 9px; }\n"
        "QTreeWidget#channelTree::item:selected { border: 1px solid #000; }\n"
    )
    found = find_border_shorthand_state_violations(text, object_name_types={})
    assert found == [
        (
            "QTreeWidget#channelTree::item:selected",
            "1px solid #000",
            "QTreeWidget#channelTree",
        )
    ]


def test_injected_state_shapes_are_all_detected():
    """Twelve selector shapes; F6 requires the two former leaks to be caught."""
    text = _injected_sheet(_parse_sheet())
    types = dict(collect_object_name_qt_types())
    types.update(_INJECTED_OBJECT_NAME_TYPES)
    found = {
        sel
        for sel, val, _base in find_border_shorthand_state_violations(
            text, object_name_types=types
        )
        if val == _PROBE_BORDER
    }
    expected = {_norm(sel) for sel, _baseline in _INJECTED_SHAPES}
    missing = sorted(expected - found)
    assert missing == [], (
        "injected border: shorthand state rule(s) leaked past the lint: "
        f"{missing}"
    )
    assert len(expected) == 12


def test_compact_spinbox_subcontrols_do_not_inherit_parent_radius_baseline():
    """``[compact]::up-button { border: none }`` is not E1; do not flag it."""
    violations = find_border_shorthand_state_violations()
    found = {sel for sel, _val, _base in violations}
    leaked = [sel for sel in found if "::up-button" in sel or "::down-button" in sel]
    assert leaked == []
    types = collect_object_name_qt_types()
    assert "QDoubleSpinBox" in types.get("dbReferenceEditor", frozenset())


def test_real_id_attr_and_subcontrol_shapes_caught_against_production_baselines():
    """Inject the two review-measured leak shapes into the live sheet."""
    text = _parse_sheet() + (
        '\n#dbReferenceEditor[f6probe="true"] { border: 3px solid #ff00aa; }\n'
        "QTreeWidget#channelTree::branch:hover { border: 3px solid #ff00aa; }\n"
    )
    found = {
        sel
        for sel, val, _base in find_border_shorthand_state_violations(text)
        if val == "3px solid #ff00aa"
    }
    assert '#dbReferenceEditor[f6probe="true"]' in found
    assert "QTreeWidget#channelTree::branch:hover" in found
