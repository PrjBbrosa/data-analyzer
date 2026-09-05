"""``DbReferenceDefaultsDialog`` — spec §11 shared default-catalog manager.

Working-copy semantics (spec §11.3): every edit — catalog rows, the current
View's Auto/Manual toggle, the "优先使用通道 metadata" preference — lives in
an in-memory working copy until "保存更改" is clicked. Cancel / Esc / the
title-bar close button write NOTHING to the injected
:class:`~mf4_analyzer.ui.db_reference_settings.DbReferenceSettingsStore` and
never emit ``catalog_saved`` / ``view_mode_committed``. "恢复系统默认" only
resets the working copy back to the immutable factory table — it does not
call ``store.restore_factory_defaults()`` directly; the effect is achieved
because the next "保存更改" persists an empty overrides/custom/hidden delta,
which is exactly what ``restore_factory_defaults()`` would have produced.

Spec: ``docs/analyzer/specs/2026-07-12-db-reference-defaults-and-labeling-spec.md``
section 11. Plan Task 3:
``docs/analyzer/plans/2026-07-12-db-reference-defaults-and-labeling-implementation.md``.
The demo-only 模拟通道/计权/HDF controls from the approved HTML draft
(``docs/analyzer/reviews/reports/2026-07-12-db-reference-defaults-draft.html``)
do NOT enter this dialog — the "当前 View" toggle below is the real product
entry point that stands in for the HTML's separate lab-strip Auto/Manual
switch.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import count

import qtawesome as qta
from PyQt5 import sip
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import db_reference
from ..list_text import split_list_text
from .widgets.db_reference import ScientificReferenceSpinBox
from .widgets.pill_switch import PillSwitch, PillSwitchLabel


_COL_QUANTITY, _COL_UNIT, _COL_REFERENCE, _COL_SOURCE, _COL_DELETE = range(5)
_HEADERS = ("物理量", "单位 / 别名", "0 dB reference", "来源", "")

_TABLE_UNIT_WIDTH = 150
_TABLE_REFERENCE_WIDTH = 150
_TABLE_SOURCE_WIDTH = 60
_TABLE_DELETE_WIDTH = 78
_TABLE_ROW_HEIGHT = 40

_CLOSE_ICON_COLOR = "#5b6472"
_ERROR_CELL_BG = QColor("#fdf2f2")

_custom_id_seq = count(1)


def _split_aliases(text):
    """Split a "单位 / 别名" cell into a non-empty, stripped alias list.

    Accepts ASCII/Chinese commas and semicolons (see ``split_list_text``).
    """
    return [p for p in split_list_text(text) if p]


@dataclass
class _Row:
    """One editable catalog row in the dialog's working copy.

    ``label`` is the "物理量" table column (a human display name — spec
    calls this "Product wording"); ``quantity`` is the internal matching
    token consumed by :func:`db_reference.resolve_db_reference`. Builtin
    rows can never change ``quantity`` (the override schema has no such
    field — spec §12's ``catalog_v1.overrides`` entries are
    ``builtin_id``/``label``/``unit``/``aliases``/``reference`` only), so
    for builtin rows the table only ever edits ``label``. Custom rows have
    no separate quantity input in the table; their ``quantity`` mirrors
    whatever the user types into "物理量" (see ``_collect_working_values``).
    """

    builtin_id: str | None
    custom_id: str | None
    quantity: str
    label: str
    unit: str
    aliases: list
    reference: float
    origin: str  # 'system' | 'user' — display-only provenance for 来源


class _CatalogItemDelegate(QStyledItemDelegate):
    """Give text cells a real horizontal gutter across Qt styles."""

    _HORIZONTAL_INSET = 8

    @classmethod
    def _inset_option(cls, option):
        inset = QStyleOptionViewItem(option)
        inset.rect = inset.rect.adjusted(
            cls._HORIZONTAL_INSET, 0, -cls._HORIZONTAL_INSET, 0,
        )
        return inset

    def paint(self, painter, option, index):
        super().paint(painter, self._inset_option(option), index)

    def updateEditorGeometry(self, editor, option, index):
        if editor is None or sip.isdeleted(editor):
            return
        try:
            editor.setGeometry(self._inset_option(option).rect)
        except RuntimeError:
            # Qt can dispatch a queued delegate geometry update after the
            # ScientificReferenceSpinBox cell wrapper was deleted.  Suppress
            # only that lifecycle race; any other RuntimeError stays visible.
            if sip.isdeleted(editor):
                return
            raise


def _rows_from_store(store):
    """Rebuild the working-copy rows from the store's CURRENT snapshot.

    The store does not expose its raw override/custom/hidden delta lists
    directly (only the merged, effective ``snapshot()``) — but every
    builtin id is in EXACTLY one of three states (unmodified-and-visible,
    overridden, or hidden), so partitioning ``FACTORY_CATALOG_V1`` against
    ``snapshot().system_catalog`` / ``snapshot().user_catalog`` recovers the
    hidden set without the store needing a separate accessor.
    """
    snapshot = store.snapshot()
    system_ids = {e.builtin_id for e in snapshot.system_catalog}
    overridden = {e.builtin_id: e for e in snapshot.user_catalog if e.builtin_id is not None}

    rows = []
    hidden_ids = []
    for factory_entry in db_reference.FACTORY_CATALOG_V1:
        bid = factory_entry.builtin_id
        if bid in overridden:
            eff = overridden[bid]
            rows.append(_Row(
                builtin_id=bid, custom_id=None, quantity=eff.quantity, label=eff.label,
                unit=eff.unit, aliases=list(eff.aliases), reference=eff.reference,
                origin="user",
            ))
        elif bid in system_ids:
            rows.append(_Row(
                builtin_id=bid, custom_id=None, quantity=factory_entry.quantity,
                label=factory_entry.label, unit=factory_entry.unit,
                aliases=list(factory_entry.aliases), reference=factory_entry.reference,
                origin="system",
            ))
        else:
            hidden_ids.append(bid)

    for entry in snapshot.user_catalog:
        if entry.builtin_id is None:
            rows.append(_Row(
                builtin_id=None, custom_id=entry.id, quantity=entry.quantity,
                label=entry.label, unit=entry.unit, aliases=list(entry.aliases),
                reference=entry.reference, origin="user",
            ))

    return rows, hidden_ids


def _rows_from_factory():
    """The pure "恢复系统默认" working copy: every builtin at its immutable
    factory value, no custom entries, nothing hidden."""
    rows = [
        _Row(
            builtin_id=e.builtin_id, custom_id=None, quantity=e.quantity, label=e.label,
            unit=e.unit, aliases=list(e.aliases), reference=e.reference, origin="system",
        )
        for e in db_reference.FACTORY_CATALOG_V1
    ]
    return rows, []


class DbReferenceDefaultsDialog(QDialog):
    """Spec §11 default-values manager, shared by all three Inspector manage
    buttons — one :class:`DbReferenceSettingsStore` instance is injected by
    the caller (Task 5 wires MainWindow's single shared service); this
    dialog never constructs its own ``QSettings``."""

    #: Emitted once, only after a successful "保存更改" commit.
    catalog_saved = pyqtSignal()
    #: Emitted with ``'auto'``/``'manual'`` once, only after a successful
    #: "保存更改" commit — reflects the (also working-copy-until-save)
    #: "当前 View" toggle.
    view_mode_committed = pyqtSignal(str)

    def __init__(self, parent, store, *, current_mode="auto", current_effective_summary=""):
        super().__init__(parent)
        self.setObjectName("DbReferenceDefaultsDialog")
        self.setWindowTitle("dB reference 默认值")
        self.setModal(True)
        self._store = store
        self._rows, self._hidden_builtin_ids = _rows_from_store(store)
        self._reference_editors = []
        self._row_errors = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # -- header: title + description + close --------------------------
        header = QHBoxLayout()
        header.setSpacing(8)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("dB reference 默认值", self)
        title.setObjectName("dbReferenceDialogTitle")
        subtitle = QLabel(
            "自动模式按精确单位别名匹配；改动仅在点击“保存更改”后生效。", self,
        )
        subtitle.setObjectName("dbReferenceDialogSubtitle")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)
        self._btn_close = QToolButton(self)
        self._btn_close.setObjectName("dbReferenceDialogClose")
        self._btn_close.setIcon(qta.icon("mdi.close", color=_CLOSE_ICON_COLOR))
        self._btn_close.setAutoRaise(True)
        self._btn_close.setToolTip("关闭")
        self._btn_close.setAccessibleName("关闭")
        self._btn_close.clicked.connect(self.reject)
        header.addWidget(self._btn_close, 0, Qt.AlignTop)
        root.addLayout(header)

        # -- "当前 View" row (spec §11.2 item 2) -----------------------------
        self._mode_switch = PillSwitch(
            self, object_name="dbReferenceViewModeSwitch",
            accessible_name="随通道自动选择",
        )
        self._mode_switch.setChecked(current_mode != "manual")
        root.addWidget(self._toggle_row(
            "随通道自动选择",
            "当前 View 按通道 metadata / 单位自动选择 reference；关闭后使用手动值。",
            self._mode_switch,
        ))
        self._effective_label = QLabel(current_effective_summary, self)
        self._effective_label.setObjectName("dbReferenceDialogEffective")
        self._effective_label.setWordWrap(True)
        # An empty QLabel still contributes its height and the surrounding
        # layout spacing.  Do not leave a blank visual canyon between the two
        # related toggle rows when the current View has no source summary yet.
        if current_effective_summary:
            root.addWidget(self._effective_label)
        else:
            self._effective_label.hide()

        # -- "优先使用通道 metadata" row (item 3) -----------------------------
        self._prefer_switch = PillSwitch(
            self, object_name="dbReferencePreferMetadataSwitch",
            accessible_name="优先使用通道 metadata",
        )
        self._prefer_switch.setChecked(bool(store.prefer_channel_metadata))
        root.addWidget(self._toggle_row(
            "优先使用通道 metadata",
            "HEAD HDF 等文件显式携带合法 dB reference 时，优先于单位默认。",
            self._prefer_switch,
        ))

        # -- catalog table (item 4) -----------------------------------------
        self.table = QTableWidget(self)
        self.table.setObjectName("dbReferenceDialogTable")
        self.table.setItemDelegate(_CatalogItemDelegate(self.table))
        self.table.setColumnCount(len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        vertical_header = self.table.verticalHeader()
        vertical_header.setVisible(False)
        # The delete-cell host contains a real button plus vertical gutters;
        # the platform default table row is too short and clips it across row
        # boundaries.  Keep every catalog row comfortably taller than that
        # control instead of relying on style-dependent size hints.
        vertical_header.setDefaultSectionSize(_TABLE_ROW_HEIGHT)
        vertical_header.setMinimumSectionSize(_TABLE_ROW_HEIGHT)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed
        )
        header_view = self.table.horizontalHeader()
        # Keep the compact unit/alias input bounded.  The quantity label is
        # the only field that benefits from the remaining width, so let it
        # stretch instead of letting 单位 / 别名 swallow the table.
        header_view.setSectionResizeMode(_COL_QUANTITY, QHeaderView.Stretch)
        header_view.setSectionResizeMode(_COL_UNIT, QHeaderView.Interactive)
        header_view.resizeSection(_COL_UNIT, _TABLE_UNIT_WIDTH)
        # 2026-07-12 Task 10 visual-tour finding: ``ResizeToContents`` sizes
        # this column from the CELL WIDGET's generic ``sizeHint()`` (a
        # ``ScientificReferenceSpinBox`` reports ~56px regardless of its
        # current text), not from the actual displayed scientific-notation
        # string -- the factory ``acceleration.g`` row's compact text
        # ("1.019716213e-7", the exact 17-significant-digit value the
        # widget's own ``setDecimals(30)`` docstring cites as its reason for
        # existing) measured ~120px, 4px WIDER than the resulting 116px
        # line-edit content area, silently clipping the last character.
        # Keep this fixed-width editor independent from the stretching
        # quantity-label column above.
        header_view.setSectionResizeMode(_COL_REFERENCE, QHeaderView.Interactive)
        header_view.resizeSection(_COL_REFERENCE, _TABLE_REFERENCE_WIDTH)
        header_view.setSectionResizeMode(_COL_SOURCE, QHeaderView.Interactive)
        header_view.resizeSection(_COL_SOURCE, _TABLE_SOURCE_WIDTH)
        header_view.setSectionResizeMode(_COL_DELETE, QHeaderView.Interactive)
        header_view.resizeSection(_COL_DELETE, _TABLE_DELETE_WIDTH)
        header_view.setStretchLastSection(False)
        self.table.setMinimumHeight(220)
        root.addWidget(self.table, 1)

        self._error_label = QLabel("", self)
        self._error_label.setObjectName("dbReferenceDialogError")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        root.addWidget(self._error_label)

        # -- footer (item 5) --------------------------------------------------
        footer = QHBoxLayout()
        footer.setSpacing(8)
        self._btn_add = QPushButton("＋ 添加默认值", self)
        self._btn_add.setAutoDefault(False)
        self._btn_add.clicked.connect(self._add_custom_row)
        footer.addWidget(self._btn_add)
        self._btn_restore = QPushButton("恢复系统默认", self)
        self._btn_restore.setAutoDefault(False)
        self._btn_restore.clicked.connect(self._restore_factory_working_copy)
        footer.addWidget(self._btn_restore)
        footer.addStretch(1)
        self._btn_cancel = QPushButton("取消", self)
        self._btn_cancel.setAutoDefault(False)
        self._btn_cancel.clicked.connect(self.reject)
        footer.addWidget(self._btn_cancel)
        self._btn_save = QPushButton("保存更改", self)
        self._btn_save.setProperty("role", "primary")
        # Enter-in-a-table-cell must only commit the cell, never the whole
        # dialog (spec §11.4) — disabling autoDefault on every footer button
        # means Qt's default-button-on-Enter fallback has nothing to trigger.
        self._btn_save.setAutoDefault(False)
        self._btn_save.clicked.connect(self._collect_and_save)
        footer.addWidget(self._btn_save)
        root.addLayout(footer)

        self._rebuild_table()
        self._fit_to_available_screen(parent, 860, 560)

    # -- layout helpers ----------------------------------------------------

    def _fit_to_available_screen(self, parent, target_w, target_h):
        """Clamp the ~800-880px target to the shared work-area budget."""
        from mf4_analyzer.ui_kit.dialog_geometry import fit_window

        fit_window(
            self,
            (int(target_w), int(target_h)),
            parent=parent,
            content_minimum=(280, 240),
            clamp_width_to_parent=True,
        )

    def _toggle_row(self, title, description, switch):
        row = QWidget(self)
        row.setObjectName("dbReferenceDialogToggleRow")
        lay = QHBoxLayout(row)
        # QSS padding paints the card but does not inset a child QLayout.
        # Keep the text and switch clear of the border through real margins.
        lay.setContentsMargins(12, 5, 12, 5)
        lay.setSpacing(10)
        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        title_label = PillSwitchLabel(
            title, switch, row, object_name="dbReferenceDialogToggleTitle",
        )
        desc_label = QLabel(description, row)
        desc_label.setObjectName("dbReferenceDialogToggleDesc")
        desc_label.setWordWrap(True)
        text_box.addWidget(title_label)
        text_box.addWidget(desc_label)
        lay.addLayout(text_box, 1)
        lay.addWidget(switch, 0, Qt.AlignRight | Qt.AlignVCenter)
        return row

    # -- table population ----------------------------------------------------

    def _rebuild_table(self):
        self.table.setRowCount(0)
        self._reference_editors = []
        for row in self._rows:
            self._append_table_row(row)
        self._clear_errors()

    def _append_table_row(self, row):
        i = self.table.rowCount()
        self.table.insertRow(i)
        self.table.setRowHeight(i, _TABLE_ROW_HEIGHT)

        quantity_item = QTableWidgetItem(row.label)
        # The column is Interactive-width-capped (see table setup above) so
        # long labels ellide — surface the full text via tooltip. Builtins
        # can never rename their matching quantity (spec §12's override
        # schema has no quantity field), only 物理量 (label), but the cell
        # stays editable either way.
        quantity_item.setToolTip(row.label)
        self.table.setItem(i, _COL_QUANTITY, quantity_item)

        unit_item = QTableWidgetItem(", ".join(row.aliases) if row.aliases else row.unit)
        self.table.setItem(i, _COL_UNIT, unit_item)

        spin = ScientificReferenceSpinBox(self.table)
        spin.setValue(row.reference)
        self.table.setCellWidget(i, _COL_REFERENCE, spin)
        self._reference_editors.append(spin)

        source_item = QTableWidgetItem("系统" if row.origin == "system" else "用户")
        source_item.setFlags(source_item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(i, _COL_SOURCE, source_item)

        delete_cell = QWidget(self.table)
        delete_layout = QHBoxLayout(delete_cell)
        delete_layout.setContentsMargins(6, 4, 6, 4)
        delete_layout.setSpacing(0)
        delete_btn = QPushButton("删除", delete_cell)
        delete_btn.setProperty("role", "danger")
        delete_btn.setAccessibleName(f"删除 {row.label or row.quantity} / {row.unit} 默认值")
        delete_btn.setAutoDefault(False)
        delete_btn.clicked.connect(lambda _checked=False, r=row: self._delete_row(r))
        delete_layout.addWidget(delete_btn)
        self.table.setCellWidget(i, _COL_DELETE, delete_cell)

    def _add_custom_row(self):
        new_id = f"user.custom_{next(_custom_id_seq)}"
        row = _Row(
            builtin_id=None, custom_id=new_id, quantity="", label="", unit="",
            aliases=[], reference=1.0, origin="user",
        )
        self._rows.append(row)
        self._append_table_row(row)

    def _delete_row(self, row):
        try:
            idx = next(i for i, r in enumerate(self._rows) if r is row)
        except StopIteration:
            return
        if row.builtin_id is not None:
            self._hidden_builtin_ids.append(row.builtin_id)
        del self._rows[idx]
        self._rebuild_table()

    def _restore_factory_working_copy(self):
        """§11.3: mutates ONLY the working copy — no store call here. The
        store keeps whatever was last saved until "保存更改" is clicked."""
        self._rows, self._hidden_builtin_ids = _rows_from_factory()
        self._rebuild_table()

    # -- save / validate ------------------------------------------------------

    def _collect_working_values(self):
        """Read the CURRENT table cell contents back into fresh row values.
        Index-aligned with ``self._rows``/``self.table`` (both are kept in
        lockstep by ``_rebuild_table``/``_append_table_row``/``_delete_row``)."""
        out = []
        for i, row in enumerate(self._rows):
            quantity_item = self.table.item(i, _COL_QUANTITY)
            unit_item = self.table.item(i, _COL_UNIT)
            label_text = (quantity_item.text() if quantity_item else row.label).strip()
            aliases = _split_aliases(unit_item.text() if unit_item else "")
            unit = aliases[0] if aliases else ""
            reference = self._reference_editors[i].value()
            if row.builtin_id is not None:
                quantity = row.quantity  # immutable for builtin overrides
            else:
                # Custom rows have no separate quantity input in the table —
                # the matching token mirrors whatever "物理量" currently reads.
                quantity = label_text
            out.append(replace(
                row, label=label_text, quantity=quantity, unit=unit,
                aliases=aliases, reference=reference,
            ))
        return out

    def _find_duplicate_rows(self, working):
        """Row-attributed mirror of ``db_reference.validate_catalog``'s
        (quantity, alias) collision check — flags BOTH the earlier and the
        later row so the inline error highlights every offender, not just
        the second one.

        Aliases are deduped PER ROW first (a ``set``, not the raw list)
        before the cross-row check: a single row's own multi-spelling
        aliases (e.g. ``m/s²``/``m/s^2``/``m/s2``, all normalizing to the
        same token) must never collide with THEMSELVES — see lesson
        ``signal-processing/2026-07-12-duplicate-alias-validator-self-collision.md``,
        the exact same trap in ``db_reference.validate_catalog`` that this
        dialog-local mirror must not reintroduce.
        """
        seen = {}
        dup = {}
        for i, row in enumerate(working):
            q_norm = db_reference.normalize_quantity(row.quantity)
            alias_norms = {
                db_reference.normalize_unit(a) for a in row.aliases
                if db_reference.normalize_unit(a)
            }
            for a_norm in alias_norms:
                key = (q_norm, a_norm)
                if key in seen:
                    dup[i] = "单位/别名与其他条目重复"
                    dup.setdefault(seen[key], "单位/别名与其他条目重复")
                else:
                    seen[key] = i
        return dup

    def _collect_and_save(self):
        working = self._collect_working_values()
        errors = {}
        for i, row in enumerate(working):
            if not row.label.strip():
                errors[i] = "物理量不能为空"
                continue
            if row.builtin_id is None and not row.quantity.strip():
                errors[i] = "物理量不能为空"
                continue
            if not row.unit or not row.aliases:
                errors[i] = "单位/别名不能为空"
                continue
            if not db_reference.validate_reference(row.reference):
                errors[i] = "reference 必须是有限正数"

        for i, msg in self._find_duplicate_rows(working).items():
            errors.setdefault(i, msg)

        if errors:
            self._show_row_errors(errors)
            return

        factory_by_id = {e.builtin_id: e for e in db_reference.FACTORY_CATALOG_V1}
        overrides = []
        custom = []
        for row in working:
            if row.builtin_id is not None:
                factory = factory_by_id[row.builtin_id]
                current = (row.label, row.unit, tuple(row.aliases), float(row.reference))
                original = (
                    factory.label, factory.unit, tuple(factory.aliases), factory.reference,
                )
                if current != original:
                    overrides.append({
                        "builtin_id": row.builtin_id, "label": row.label,
                        "unit": row.unit, "aliases": list(row.aliases),
                        "reference": float(row.reference),
                    })
            else:
                custom.append({
                    "id": row.custom_id, "quantity": row.quantity, "label": row.label,
                    "unit": row.unit, "aliases": list(row.aliases),
                    "reference": float(row.reference),
                })

        result = self._store.save(
            overrides=overrides,
            custom=custom,
            hidden_builtin_ids=list(self._hidden_builtin_ids),
            prefer_channel_metadata=self._prefer_switch.isChecked(),
        )
        if not result.ok:
            self._error_label.setText(result.error or "保存失败，请检查输入。")
            self._error_label.setVisible(True)
            return

        self._rows, self._hidden_builtin_ids = _rows_from_store(self._store)
        self._rebuild_table()
        new_mode = "auto" if self._mode_switch.isChecked() else "manual"
        self.catalog_saved.emit()
        self.view_mode_committed.emit(new_mode)
        self.accept()

    def _show_row_errors(self, errors):
        self._row_errors = dict(errors)
        lines = []
        for i in sorted(errors):
            row = self._rows[i]
            name = row.label or row.quantity or f"第 {i + 1} 行"
            lines.append(f"{name}：{errors[i]}")
            for col in (_COL_QUANTITY, _COL_UNIT):
                item = self.table.item(i, col)
                if item is not None:
                    item.setBackground(QBrush(_ERROR_CELL_BG))
                    item.setToolTip(errors[i])
            spin = self._reference_editors[i] if i < len(self._reference_editors) else None
            if spin is not None:
                spin.setToolTip(errors[i])
        self._error_label.setText("；".join(lines))
        self._error_label.setVisible(True)

    def _clear_errors(self):
        self._row_errors = {}
        self._error_label.setVisible(False)
        self._error_label.setText("")
        for i in range(self.table.rowCount()):
            for col in (_COL_QUANTITY, _COL_UNIT):
                item = self.table.item(i, col)
                if item is not None:
                    item.setBackground(QBrush())
                    item.setToolTip("")
