"""Inspector section widgets (Phase 2).

PersistentTop hosts the always-visible xaxis/range/tick-density controls.
TimeContextual / FFTContextual / OrderContextual host the mode-specific
parameter cards. Public getter/setter names are a contract consumed by
MainWindow's analysis methods — do not rename without updating callers.
"""
import json

from PyQt5.QtCore import QSettings, QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .icons import Icons
from .widgets.searchable_combo import SearchableComboBox


_PRESET_ORG = "MF4Analyzer"
_PRESET_APP = "DataAnalyzer"


def _preset_settings():
    return QSettings(_PRESET_ORG, _PRESET_APP)


def _make_group_header(title, action_button=None, parent=None):
    """Build a QFrame styled as a group title bar.

    Layout: [QLabel(title)] addStretch [optional action_button].

    Used in place of ``QGroupBox::title`` when a group needs an inline
    action button (R3 #9 — rebuild_time icon moved out of the Fs row).
    The frame carries ``objectName='inspectorGroupHeader'`` so the QSS
    rule defined in ``style.qss`` (Inspector QFrame#inspectorGroupHeader)
    paints the same hairline underline that ``QGroupBox::title`` uses
    for the rest of the Inspector — see R3 #3-B.
    """
    frame = QFrame(parent)
    frame.setObjectName("inspectorGroupHeader")
    frame.setAttribute(Qt.WA_StyledBackground, True)
    box = QHBoxLayout(frame)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(4)
    lbl = QLabel(title, frame)
    lbl.setObjectName("inspectorGroupTitle")
    box.addWidget(lbl, 0)
    box.addStretch(1)
    if action_button is not None:
        action_button.setParent(frame)
        box.addWidget(action_button, 0)
    return frame


class PresetBar(QWidget):
    """Three-slot preset bar: single row of slot buttons (R3 #8).

    Storage format (JSON per slot)::

        {"name": "<user-provided name>", "params": {...}}

    Legacy slots written by an earlier build store the params dict at the
    top level (no ``name``/``params`` envelope); :meth:`_read` upgrades them
    on first read so subsequent rename / save round-trips work uniformly.

    The owning contextual supplies ``collect_fn`` (returns a JSON-serializable
    params dict) and ``apply_fn`` (restore params from such a dict). The bar
    emits ``acknowledged(level, msg)`` so the host can surface a toast.

    The previous separate "存为 N" save row was removed — left-click on a
    slot loads the saved preset (or, when the slot is empty, prompts to
    save the current params), and right-click opens a menu with full
    save / rename / clear / reset operations.

    Builtin-aware mode (R3 C)
    -------------------------
    When ``builtin_defaults`` is supplied, each slot has a fallback dict of
    parameters that the bar treats as the slot's "default":

    - The slot button shows ``builtin_defaults[slot]['display_name']`` when
      no user override exists (so the FFT-vs-Time bar reads as 配置1 /
      配置2 / 配置3 out of the box).
    - Left-click loads either the user override (if any) or the builtin.
    - The right-click menu adds a "重置为默认" entry that removes the
      override and restores the builtin.

    Storage key in builtin mode: ``{kind}/preset_override/{slot}`` (so the
    namespace is independent from the legacy ``{kind}/preset/{slot}`` used
    by the FFT / Order bars).
    """

    SLOTS = (1, 2, 3)
    NAME_MAX_LEN = 12
    acknowledged = pyqtSignal(str, str)  # level, message

    def __init__(
        self, kind, collect_fn, apply_fn, parent=None, builtin_defaults=None,
    ):
        """Construct a preset bar.

        Parameters
        ----------
        kind : str
            Namespace (e.g. ``'fft'`` / ``'order'`` / ``'fft_time'``) used
            in the QSettings key.
        collect_fn : callable[[], dict]
            Returns the current params snapshot (JSON-serializable dict).
        apply_fn : callable[[dict], None]
            Restores a previously-saved params snapshot.
        builtin_defaults : dict[int, dict] | None
            Mapping ``slot -> {'display_name': str, 'params': dict}``.
            When provided, the bar runs in builtin-aware mode (see class
            docstring).
        """
        super().__init__(parent)
        self._kind = kind
        self._collect = collect_fn
        self._apply = apply_fn
        self._builtins = builtin_defaults  # None => legacy mode

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._load_btns = {}
        for n in self.SLOTS:
            ld = QPushButton(self._default_name(n), self)
            ld.setProperty("role", "preset-load")
            ld.setProperty("filled", "false")
            ld.setContextMenuPolicy(Qt.CustomContextMenu)
            ld.clicked.connect(lambda _=False, slot=n: self._on_left_click(slot))
            ld.customContextMenuRequested.connect(
                lambda pos, slot=n: self._show_menu(slot, pos)
            )
            row.addWidget(ld, 1)
            self._load_btns[n] = ld
        self._refresh_states()

    # ---- naming helpers ----
    def _default_name(self, slot):
        if self._builtins and slot in self._builtins:
            entry = self._builtins[slot]
            if isinstance(entry, dict) and entry.get('display_name'):
                return str(entry['display_name'])
        return f"配置 {slot}"

    # ---- persistence helpers ----
    def _key(self, slot):
        if self._builtins is not None:
            return f"{self._kind}/preset_override/{slot}"
        return f"{self._kind}/preset/{slot}"

    def _read(self, slot):
        """Return ``(name, params)`` or ``None`` for an empty slot.

        Tolerates the legacy flat-dict format by treating the whole payload
        as ``params`` and synthesising a default name.
        """
        raw = _preset_settings().value(self._key(slot), "")
        if not raw:
            return None
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(obj, dict):
            return None
        if 'params' in obj and isinstance(obj['params'], dict):
            name = obj.get('name') or self._default_name(slot)
            return str(name), obj['params']
        # legacy flat dict — entire payload is params
        return self._default_name(slot), obj

    def _write(self, slot, name, params):
        payload = {"name": name, "params": params}
        _preset_settings().setValue(self._key(slot), json.dumps(payload))

    def _delete(self, slot):
        _preset_settings().remove(self._key(slot))

    def _builtin_params(self, slot):
        if not self._builtins or slot not in self._builtins:
            return None
        entry = self._builtins[slot]
        if isinstance(entry, dict) and 'params' in entry:
            return entry['params']
        return None

    def _refresh_states(self):
        for n in self.SLOTS:
            entry = self._read(n)
            btn = self._load_btns[n]
            if entry is None:
                # Empty slot. In builtin mode the slot still loads the
                # builtin, so it is enabled and shows the builtin display
                # name. In legacy mode the slot is enabled but reads as
                # "＋ 配置 N" — left-click will save current params.
                if self._builtins is not None:
                    btn.setText(self._default_name(n))
                    btn.setEnabled(True)
                    btn.setProperty("filled", "false")
                    btn.setToolTip(
                        f"内置预设「{self._default_name(n)}」\n"
                        "左键加载 · 右键菜单可保存当前 / 重命名 / 重置为默认"
                    )
                else:
                    btn.setText(f"＋ {self._default_name(n)}")
                    btn.setEnabled(True)
                    btn.setProperty("filled", "false")
                    btn.setToolTip(
                        "空槽位 — 左键保存当前参数；右键菜单整合 "
                        "保存 / 重命名 / 清空"
                    )
            else:
                name, params = entry
                btn.setText(name)
                btn.setEnabled(True)
                btn.setProperty("filled", "true")
                btn.setToolTip(self._format_summary(name, params))
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _format_summary(self, name, params):
        if not isinstance(params, dict):
            return name
        items = []
        for k, v in params.items():
            if isinstance(v, float):
                items.append(f"{k}={v:g}")
            elif isinstance(v, bool):
                items.append(f"{k}={'是' if v else '否'}")
            else:
                items.append(f"{k}={v}")
        suffix = (
            "（右键可重命名 / 重置为默认）"
            if self._builtins is not None
            else "（右键可重命名 / 清空）"
        )
        return f"{name}\n{', '.join(items)}\n{suffix}"

    # ---- actions ----
    def _on_left_click(self, slot):
        """Slot left-click: load if filled, else save current (legacy
        mode) or load builtin (builtin mode).
        """
        entry = self._read(slot)
        if entry is None and self._builtins is None:
            # Legacy mode + empty slot → primary action is "save current".
            self._save(slot)
            return
        # Filled slot OR builtin fallback → load.
        self._load(slot)

    def _save(self, slot):
        try:
            params = self._collect()
        except Exception as e:  # pragma: no cover — defensive
            self.acknowledged.emit("error", f"保存失败: {e}")
            return
        existing = self._read(slot)
        name = existing[0] if existing else self._default_name(slot)
        self._write(slot, name, params)
        self._refresh_states()
        self.acknowledged.emit("success", f"已保存到「{name}」")

    def _load(self, slot):
        entry = self._read(slot)
        if entry is None:
            # In builtin mode, fall back to the builtin params.
            params = self._builtin_params(slot)
            if params is None:
                self.acknowledged.emit(
                    "warning", f"「{self._default_name(slot)}」是空的",
                )
                return
            name = self._default_name(slot)
        else:
            name, params = entry
        try:
            self._apply(params)
        except Exception as e:
            self.acknowledged.emit("error", f"加载失败: {e}")
            return
        self.acknowledged.emit("success", f"已加载「{name}」")

    def _rename(self, slot):
        entry = self._read(slot)
        if entry is None:
            # In builtin mode, allow rename of the builtin itself by
            # promoting the builtin params into a saved override.
            params = self._builtin_params(slot)
            if params is None:
                self.acknowledged.emit("warning", "请先保存参数再重命名")
                return
            current = self._default_name(slot)
        else:
            current, params = entry
        new_name, ok = QInputDialog.getText(
            self,
            "重命名配置",
            f"为槽位 {slot} 输入名称（最长 {self.NAME_MAX_LEN} 字符）：",
            QLineEdit.Normal,
            current,
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name:
            self.acknowledged.emit("warning", "名称不能为空")
            return
        if len(new_name) > self.NAME_MAX_LEN:
            new_name = new_name[: self.NAME_MAX_LEN]
        self._write(slot, new_name, params)
        self._refresh_states()
        self.acknowledged.emit("success", f"已重命名为「{new_name}」")

    def _clear(self, slot):
        entry = self._read(slot)
        if entry is None:
            return
        name = entry[0]
        ans = QMessageBox.question(
            self,
            "清空配置",
            f"确定清空「{name}」？该操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        self._delete(slot)
        self._refresh_states()
        self.acknowledged.emit("info", f"已清空「{name}」")

    def _reset_to_default(self, slot):
        """Builtin-aware reset: drop the user override, builtin restores
        as the slot's effective preset on the next load.
        """
        if self._builtins is None:
            return
        self._delete(slot)
        self._refresh_states()
        self.acknowledged.emit(
            "info", f"已重置为内置「{self._default_name(slot)}」",
        )

    def _show_menu(self, slot, pos):
        btn = self._load_btns[slot]
        menu = QMenu(self)
        act_save = menu.addAction("保存当前到本槽位")
        act_rename = menu.addAction("重命名…")
        if self._builtins is not None:
            act_reset = menu.addAction("重置为默认")
            act_clear = None
        else:
            act_reset = None
            act_clear = menu.addAction("清空")
        entry = self._read(slot)
        # Save is always allowed (it's the primary write path now).
        act_save.setEnabled(True)
        # Rename works if there's any preset — saved override OR builtin.
        rename_target = entry is not None or self._builtin_params(slot) is not None
        act_rename.setEnabled(rename_target)
        if act_clear is not None:
            act_clear.setEnabled(entry is not None)
        if act_reset is not None:
            # Reset only makes sense if a user override actually exists.
            act_reset.setEnabled(entry is not None)
        chosen = menu.exec_(btn.mapToGlobal(pos))
        if chosen is act_save:
            self._save(slot)
        elif chosen is act_rename:
            self._rename(slot)
        elif act_clear is not None and chosen is act_clear:
            self._clear(slot)
        elif act_reset is not None and chosen is act_reset:
            self._reset_to_default(slot)


def _configure_form(form):
    form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.DontWrapRows)
    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    form.setFormAlignment(Qt.AlignTop)
    form.setContentsMargins(0, 0, 0, 0)
    parent = form.parentWidget()
    if isinstance(parent, QGroupBox):
        margins = parent.contentsMargins()
        parent.setContentsMargins(
            margins.left(), margins.top(), 0, margins.bottom(),
        )
        # 2026-04-27 fix-4: the global ``Inspector QGroupBox { padding:
        # 12px 2px 6px; }`` rule wins over Python ``setContentsMargins``
        # during stylesheet polish, eating ~2px on each side and ~6px at
        # the bottom. An inline stylesheet on the specific QGroupBox
        # using ``padding-left/right/bottom`` (not the shorthand) zeros
        # those without disturbing ``padding-top`` (which still cascades
        # from the global rule and reserves room for the title baseline).
        # Without this, the form-layout cells inside the QGroupBox render
        # ~9px narrower than the matching sig_card cells, breaking A1
        # field-column alignment.
        parent.setStyleSheet(
            "QGroupBox { padding-left: 0; padding-right: 0; "
            "padding-bottom: 0; }"
        )
    # Compact rhythm: tightened from H=8 V=8 to H=6 V=4 (2026-04-26
    # 紧凑化 pass) so a typical Inspector card fits more rows without
    # scrolling on narrow screens.
    form.setHorizontalSpacing(6)
    form.setVerticalSpacing(4)


def _fit_field(widget, *, max_width=None, align_right=True):
    """Make ``widget`` happy in a ``QFormLayout`` field cell.

    Sets size-policy to Expanding/Fixed and clears any minimumWidth so the
    widget can shrink with the column. Optional ``max_width`` caps the
    widget's outer width — without a cap, Expanding controls grow
    unboundedly whenever the parent pane (splitter slot) widens, which is
    the root cause of the "toggle a checkbox → pane visually balloons"
    defect addressed in the 2026-04-26 紧凑化 fix-3 pass.

    In the A1 layout, the host fills the QFormLayout field cell and the
    input is aligned to the trailing edge. This makes fields from separate
    groups share a right edge even when their label columns differ.
    """
    widget.setMinimumWidth(0)
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    if max_width is not None:
        widget.setMaximumWidth(int(max_width))
    if not align_right:
        return widget

    host = QWidget()
    host.setProperty("inspectorFieldHost", True)
    host.setAttribute(Qt.WA_StyledBackground, False)
    host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    box = QHBoxLayout(host)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(0)
    box.addStretch(1)
    box.addWidget(widget, 100)
    return host


# 2026-04-26 R3 紧凑化 fix-3 / A1 follow-up:
# Default cap for inspector fields. The user chose the A1 layout: inputs
# should fill the form's field column instead of keeping short numeric
# values in visibly shorter boxes. Both regular and signal/source fields
# therefore share the same cap.
_SHORT_FIELD_MAX_WIDTH = 260
_LONG_FIELD_MAX_WIDTH = 260


def _pair_field(widget_a, label_b_text, widget_b):
    """Wrap two side-by-side controls into a single QFormLayout field.

    Returns a host ``QWidget`` whose internal QHBoxLayout lays out
    ``[widget_a, QLabel(label_b_text), widget_b]`` with tight margins, so
    the resulting "field" still satisfies the form's label+field row
    contract and ``QFormLayout.labelForField(host)`` resolves to the
    row's leading label.
    """
    host = QWidget()
    box = QHBoxLayout(host)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(6)
    box.addWidget(_fit_field(widget_a, align_right=False), 1)
    inline_label = QLabel(label_b_text)
    inline_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    box.addWidget(inline_label, 0)
    box.addWidget(_fit_field(widget_b, align_right=False), 1)
    return host


def _enforce_label_widths(widget, *, max_field_width=None, unify_columns=False):
    """Pin every QFormLayout label's minimumWidth to its sizeHint width
    and (optionally) cap every uncapped field's maximumWidth.

    R3 B fix for the OrderContextual case: long Chinese labels like
    "阶次分辨率:" were getting squeezed by greedy ``QSizePolicy.Expanding``
    fields when the Inspector pane was narrow, causing the visual label
    column to elide / wrap. We pin minimumWidth on every label so the
    QFormLayout's label column never shrinks below the natural label
    text, then cap the field column so the spinner / combo no longer
    swallows the slack.

    2026-04-26 R3 紧凑化 fix-3 amendment: only apply the cap to fields
    that are still at the default ``QWIDGETSIZE_MAX``. This lets callers
    set a *wider* cap (e.g. ``_LONG_FIELD_MAX_WIDTH`` for a signal-name
    combo) explicitly *before* invoking the helper, without having those
    intentional wide caps clobbered to the helper's narrower default.

    2026-04-27 fix-4 amendment: ``unify_columns=True`` extends the per-
    label minimum to the GLOBAL max sizeHint across every form in
    ``widget``. QFormLayout sizes its label column to ``max(label
    minimumWidth)`` *within its own form* — without this unification, a
    sig_card form (short labels like "Fs:") and a QGroupBox form (long
    labels like "窗函数:") render with different label-column widths,
    which cascades into different field-column widths and breaks the A1
    "every field shares the same width and right edge" contract enforced
    by ``test_fft_contextual_fields_fill_column_under_qss``.
    """
    from PyQt5.QtWidgets import QFormLayout, QLabel
    QWIDGETSIZE_MAX = 16777215
    forms = widget.findChildren(QFormLayout)
    global_max_lbl = 0
    if unify_columns:
        for fl in forms:
            for r in range(fl.rowCount()):
                lbl_item = fl.itemAt(r, QFormLayout.LabelRole)
                if lbl_item is None:
                    continue
                lbl = lbl_item.widget()
                if isinstance(lbl, QLabel) and lbl.text().strip():
                    global_max_lbl = max(global_max_lbl, lbl.sizeHint().width())
    for fl in forms:
        for r in range(fl.rowCount()):
            lbl_item = fl.itemAt(r, QFormLayout.LabelRole)
            fld_item = fl.itemAt(r, QFormLayout.FieldRole)
            if lbl_item is not None:
                lbl = lbl_item.widget()
                if isinstance(lbl, QLabel) and lbl.text().strip():
                    natural = lbl.sizeHint().width()
                    target = max(natural, global_max_lbl)
                    if lbl.minimumWidth() < target:
                        lbl.setMinimumWidth(target)
            if fld_item is not None and max_field_width is not None:
                fld = fld_item.widget()
                if fld is None:
                    continue
                targets = [fld]
                if bool(fld.property("inspectorFieldHost")):
                    targets = fld.findChildren(
                        QWidget, options=Qt.FindDirectChildrenOnly,
                    )
                for target in targets:
                    if target.maximumWidth() >= QWIDGETSIZE_MAX:
                        target.setMaximumWidth(int(max_field_width))


def _set_form_row_visible(form, field_widget, visible):
    """Hide/show a QFormLayout row by toggling both its label and field.

    Qt 5.13 added ``QFormLayout.setRowVisible`` but PyQt5 5.15.x does not
    bind it on this build; falling back to widget-level toggling keeps
    the row truly absent from the visual flow rather than just disabled.

    For paired-field rows (`_pair_field` hosts wrapping two spin boxes
    plus an inline label), toggling the wrapper alone leaves each inner
    widget's own ``WA_WState_Hidden`` flag untouched, so
    ``inner.isHidden()`` keeps returning False until the user fires the
    toggled signal. We therefore propagate the visibility flag down to
    the wrapper's direct child widgets so callers (and tests) see the
    expected hidden state on every individual control.
    """
    field_widget.setVisible(visible)
    for child in field_widget.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
        child.setVisible(visible)
    label = form.labelForField(field_widget)
    if label is not None:
        label.setVisible(visible)


class PersistentTop(QWidget):
    """Xaxis / Range / Ticks sections.

    R3 #6: the three sections live inside a collapsible container that
    defaults to collapsed (single-row affordance reading "▶ 图表设置 (时间轴
    · 范围 · 刻度)"). The collapsed state is persisted via QSettings under
    ``_SETTINGS_KEY`` so layouts survive between sessions.

    All public attributes / methods documented on the class remain
    reachable regardless of collapser state — programmatic getters / setters
    work even while the body widget is hidden.
    """

    _SETTINGS_KEY = "inspector/persistent_top/expanded"

    xaxis_apply_requested = pyqtSignal()
    tick_density_changed = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        # 紧凑化【3】: tightened from 10 → 6 (2026-04-26).
        root.setSpacing(6)
        root.setContentsMargins(0, 0, 0, 0)

        # ------- Collapser handle -------
        # R3 #6: single-row toggle that reveals the inner three groups.
        # We use QToolButton so the arrow icon is rendered natively (no
        # painter call into icons.py for an admin affordance) and so the
        # button gets a proper "checkable" semantics.
        self.btn_collapser = QToolButton(self)
        self.btn_collapser.setObjectName("inspectorCollapser")
        self.btn_collapser.setCheckable(True)
        self.btn_collapser.setAutoRaise(True)
        self.btn_collapser.setText("图表设置 (时间轴 · 范围 · 刻度)")
        self.btn_collapser.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_collapser.setArrowType(Qt.RightArrow)
        self.btn_collapser.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed,
        )
        # Stylistic tweak — left-align the text so the arrow + label hug
        # the leading edge as a normal collapser would.
        try:
            self.btn_collapser.setStyleSheet(
                "QToolButton#inspectorCollapser { "
                "  text-align: left; padding: 4px 6px; font-weight: 600; "
                "  border: none; background: transparent; "
                "}"
                "QToolButton#inspectorCollapser:hover { background: #eef2f7; }"
            )
        except Exception:  # pragma: no cover — defensive on Qt style failures
            pass
        root.addWidget(self.btn_collapser)

        # ------- Collapser body (the three groups live here) -------
        self._collapser_body = QFrame(self)
        body_lay = QVBoxLayout(self._collapser_body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(6)
        root.addWidget(self._collapser_body)

        # ------- Xaxis group -------
        g = QGroupBox("横坐标")
        fl = QFormLayout(g)
        _configure_form(fl)
        self._xaxis_form = fl
        self.combo_xaxis = QComboBox()
        self.combo_xaxis.addItems(['自动(时间)', '指定通道'])
        fl.addRow("来源:", _fit_field(self.combo_xaxis))
        self._combo_xaxis_ch = SearchableComboBox()
        self._combo_xaxis_ch.setEnabled(False)
        fl.addRow("通道:", _fit_field(self._combo_xaxis_ch))
        self.edit_xlabel = QLineEdit()
        self.edit_xlabel.setPlaceholderText("Time (s)")
        fl.addRow("标签:", _fit_field(self.edit_xlabel))
        self.btn_apply_xaxis = QPushButton("应用")
        self.btn_apply_xaxis.setProperty("role", "primary")
        fl.addRow(self.btn_apply_xaxis)
        body_lay.addWidget(g)

        # ------- Range group -------
        g = QGroupBox("范围")
        fl = QFormLayout(g)
        _configure_form(fl)
        self._range_form = fl
        self.chk_range = QCheckBox("使用选定范围")
        fl.addRow(self.chk_range)
        # 紧凑化【1】: 开始 / 结束 share one form row.
        self.spin_start = QDoubleSpinBox()
        self.spin_start.setDecimals(3)
        self.spin_start.setSuffix(" s")
        self.spin_start.setRange(0, 1e9)
        self.spin_end = QDoubleSpinBox()
        self.spin_end.setDecimals(3)
        self.spin_end.setSuffix(" s")
        self.spin_end.setRange(0, 1e9)
        self._range_row_host = _pair_field(
            self.spin_start, "– 结束", self.spin_end,
        )
        fl.addRow("开始:", self._range_row_host)
        body_lay.addWidget(g)

        # ------- Tick density group (§6.1 ▸ 刻度) -------
        g = QGroupBox("刻度")
        fl = QFormLayout(g)
        _configure_form(fl)
        # 紧凑化【1】: X / Y share one form row.
        self.spin_xt = QSpinBox()
        self.spin_xt.setRange(3, 30)
        self.spin_xt.setValue(10)
        self.spin_yt = QSpinBox()
        self.spin_yt.setRange(3, 20)
        self.spin_yt.setValue(6)
        self._tick_row_host = _pair_field(
            self.spin_xt, "Y:", self.spin_yt,
        )
        fl.addRow("X:", self._tick_row_host)
        body_lay.addWidget(g)

        self._wire()
        # Restore persisted collapser state (defaults to collapsed).
        try:
            persisted = _preset_settings().value(self._SETTINGS_KEY, False)
            # QSettings can return strings on some platforms.
            if isinstance(persisted, str):
                persisted = persisted.lower() in ("true", "1", "yes")
            initial_expanded = bool(persisted)
        except Exception:  # pragma: no cover
            initial_expanded = False
        self.btn_collapser.setChecked(initial_expanded)
        self._sync_collapser(initial_expanded)
        # 紧凑化【2】: apply initial conditional visibility once everything
        # is wired (so a programmatic reset before show() also lands).
        self._update_xaxis_channel_row_visible(self.combo_xaxis.currentIndex())
        self._update_range_rows_visible(self.chk_range.isChecked())

        # 2026-04-26 R3 紧凑化 fix-3: cap the short numeric fields so toggling
        # 使用选定范围 / 通道 visibility no longer makes the pane look wider.
        # The label / xlabel fields keep room for representative text.
        for sp in (self.spin_start, self.spin_end, self.spin_xt, self.spin_yt):
            sp.setMaximumWidth(_SHORT_FIELD_MAX_WIDTH)
        # Long-text fields: xaxis source combo + label LineEdit may host
        # representative text; keep a generous (but not unbounded) cap.
        for w in (self.combo_xaxis, self._combo_xaxis_ch, self.edit_xlabel):
            w.setMaximumWidth(_LONG_FIELD_MAX_WIDTH)

    def _wire(self):
        self.combo_xaxis.currentIndexChanged.connect(
            lambda i: self._combo_xaxis_ch.setEnabled(i == 1)
        )
        # 紧凑化【2】: hide (not just disable) the 通道 row when 自动(时间).
        self.combo_xaxis.currentIndexChanged.connect(
            self._update_xaxis_channel_row_visible
        )
        # 紧凑化【2】: hide 开始/结束 row entirely when range disabled.
        self.chk_range.toggled.connect(self._update_range_rows_visible)
        self.btn_apply_xaxis.clicked.connect(self.xaxis_apply_requested)
        self.spin_xt.valueChanged.connect(self._emit_ticks)
        self.spin_yt.valueChanged.connect(self._emit_ticks)
        # R3 #6: collapser toggle reveals/hides the inner three groups
        # and persists the choice via QSettings.
        self.btn_collapser.toggled.connect(self._sync_collapser)

    def _sync_collapser(self, expanded):
        """Apply the collapser state to the body widget and arrow icon,
        then persist the choice. Safe to call before show().
        """
        expanded = bool(expanded)
        self._collapser_body.setVisible(expanded)
        self.btn_collapser.setArrowType(
            Qt.DownArrow if expanded else Qt.RightArrow,
        )
        try:
            _preset_settings().setValue(self._SETTINGS_KEY, expanded)
        except Exception:  # pragma: no cover
            pass

    def _update_xaxis_channel_row_visible(self, index):
        _set_form_row_visible(self._xaxis_form, self._combo_xaxis_ch, index == 1)

    def _update_range_rows_visible(self, checked):
        _set_form_row_visible(self._range_form, self._range_row_host, bool(checked))

    def _emit_ticks(self):
        self.tick_density_changed.emit(self.spin_xt.value(), self.spin_yt.value())

    # ---- public getters/setters used by MainWindow ----
    def xaxis_mode(self):
        return 'channel' if self.combo_xaxis.currentIndex() == 1 else 'time'

    def set_xaxis_mode(self, mode):
        self.combo_xaxis.setCurrentIndex(1 if mode == 'channel' else 0)

    def xaxis_channel_data(self):
        """Return (fid, channel) tuple or None."""
        if self.combo_xaxis.currentIndex() != 1:
            return None
        return self._combo_xaxis_ch.currentData()

    def xaxis_label(self):
        return self.edit_xlabel.text().strip()

    def set_xaxis_candidates(self, candidates):
        """candidates: list of (display_text, (fid, ch)) tuples."""
        self._combo_xaxis_ch.clear()
        for text, data in candidates:
            self._combo_xaxis_ch.addItem(text, data)

    def range_enabled(self):
        return self.chk_range.isChecked()

    def range_values(self):
        return (self.spin_start.value(), self.spin_end.value())

    def set_range_from_span(self, xmin, xmax):
        self.spin_start.setValue(xmin)
        self.spin_end.setValue(xmax)
        self.chk_range.setChecked(True)

    def set_range_limits(self, lo, hi):
        for sp in (self.spin_start, self.spin_end):
            sp.setRange(lo, hi)

    def tick_density(self):
        return (self.spin_xt.value(), self.spin_yt.value())


class TimeContextual(QWidget):
    """Time-domain contextual: just the manual replot button.

    Plot-mode and cursor-mode controls have been relocated to the chart
    card toolbar (see chart_stack.TimeChartCard).
    """

    plot_time_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setSpacing(10)

        self.btn_plot = QPushButton("绘图")
        self.btn_plot.setIcon(Icons.plot())
        self.btn_plot.setIconSize(QSize(16, 16))
        self.btn_plot.setProperty("role", "primary")
        root.addWidget(self.btn_plot)
        self.btn_plot.clicked.connect(self.plot_time_requested)
        root.addStretch()


class FFTContextual(QWidget):
    """FFT contextual: signal/Fs/params/options + compute button."""

    fft_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object)
    remark_toggled = pyqtSignal(bool)
    signal_changed = pyqtSignal(object)  # emits (fid, ch) or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("fftContextual")
        self.setAttribute(Qt.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        # 紧凑化【3】: tightened from 10 → 6 (2026-04-26).
        root.setSpacing(6)

        # R3 #9: build btn_rebuild *before* the analyse-signal group so we
        # can hand it off to the group's header row instead of attaching
        # it to the Fs form field.
        # 2026-04-26 R3 紧凑化 fix-4: setFixedSize(24, 24) replaces the
        # earlier setMaximumWidth(30) — the icon stays 16x16 but the outer
        # chrome is no longer big enough to hold two icons side-by-side.
        self.btn_rebuild = QPushButton("")
        self.btn_rebuild.setIcon(Icons.rebuild_time())
        self.btn_rebuild.setIconSize(QSize(16, 16))
        self.btn_rebuild.setFixedSize(QSize(24, 24))
        self.btn_rebuild.setProperty("role", "tool")
        self.btn_rebuild.setToolTip("重建时间轴")

        # ---- 分析信号 (custom header so btn_rebuild docks top-right) ----
        # 2026-04-26 R3 紧凑化 fix-2: do NOT enable WA_StyledBackground on
        # this QFrame. Without a paired QSS rule it would render with the
        # default white QFrame fill and break the tinted contextual card
        # background bleed-through (see lesson
        # 2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md).
        sig_card = QFrame(self)
        sig_card.setObjectName("fftSignalCard")
        sig_lay = QVBoxLayout(sig_card)
        sig_lay.setContentsMargins(0, 0, 0, 0)
        sig_lay.setSpacing(4)
        sig_lay.addWidget(_make_group_header("分析信号", self.btn_rebuild))
        fl = QFormLayout()
        _configure_form(fl)
        self.combo_sig = SearchableComboBox()
        # combo_sig hosts long signal names — keep the long-text cap.
        fl.addRow("信号:", _fit_field(self.combo_sig, max_width=_LONG_FIELD_MAX_WIDTH))
        self.spin_fs = QDoubleSpinBox()
        self.spin_fs.setRange(1, 1e6)
        self.spin_fs.setValue(1000)
        self.spin_fs.setSuffix(" Hz")
        fl.addRow("Fs:", _fit_field(self.spin_fs, max_width=_SHORT_FIELD_MAX_WIDTH))
        sig_lay.addLayout(fl)
        root.addWidget(sig_card)

        g = QGroupBox("谱参数")
        fl = QFormLayout(g)
        _configure_form(fl)
        # R3 change A: revert R1's inline 窗函数+NFFT pair — three
        # independent rows match FFTTimeContextual's 时频参数 group.
        # 2026-04-26 R3 紧凑化 fix-3: cap each short field so the row
        # column never balloons when the splitter widens.
        self.combo_win = QComboBox()
        self.combo_win.addItems(
            ['hanning', 'hamming', 'blackman', 'bartlett', 'kaiser', 'flattop']
        )
        fl.addRow("窗函数:", _fit_field(self.combo_win, max_width=_SHORT_FIELD_MAX_WIDTH))
        self.combo_nfft = QComboBox()
        self.combo_nfft.addItems(
            ['自动', '512', '1024', '2048', '4096', '8192', '16384']
        )
        fl.addRow("NFFT:", _fit_field(self.combo_nfft, max_width=_SHORT_FIELD_MAX_WIDTH))
        self.spin_overlap = QSpinBox()
        self.spin_overlap.setRange(0, 90)
        self.spin_overlap.setValue(50)
        self.spin_overlap.setSuffix(" %")
        fl.addRow("重叠:", _fit_field(self.spin_overlap, max_width=_SHORT_FIELD_MAX_WIDTH))

        # --- Averaging (Welch / peak-hold) — Wave 2 / SP2 / Task 2.1 ---
        # 单帧 = single FFT snapshot (legacy default).
        # 线性平均 = Welch averaging (噪声地板下降).
        # 峰值保持 = per-frequency max across overlapping segments.
        self.combo_avg_mode = QComboBox()
        self.combo_avg_mode.addItems(['单帧', '线性平均', '峰值保持'])
        self.combo_avg_mode.setCurrentText('单帧')
        self.combo_avg_mode.setToolTip(
            "单帧：单次 FFT 快照；线性平均：Welch 多段平均（降噪）；"
            "峰值保持：每个频率取多段最大值（保留瞬态）。"
        )
        fl.addRow(
            "平均模式:",
            _fit_field(self.combo_avg_mode, max_width=_SHORT_FIELD_MAX_WIDTH),
        )

        self.spin_avg_overlap = QSpinBox()
        self.spin_avg_overlap.setRange(0, 95)
        self.spin_avg_overlap.setValue(50)
        self.spin_avg_overlap.setSuffix(" %")
        self.spin_avg_overlap.setEnabled(False)
        self.spin_avg_overlap.setToolTip("仅在平均/峰值保持模式下生效")
        fl.addRow(
            "重叠率:",
            _fit_field(self.spin_avg_overlap, max_width=_SHORT_FIELD_MAX_WIDTH),
        )

        self.combo_avg_mode.currentTextChanged.connect(
            lambda txt: self.spin_avg_overlap.setEnabled(txt != '单帧')
        )

        # --- Y-axis scale per subplot — Wave 2 / SP2 / Task 2.3 ---
        # Amplitude defaults Linear (legacy). PSD defaults dB (HEAD-parity).
        self.combo_amp_y = QComboBox()
        self.combo_amp_y.addItems(['Linear', 'dB'])
        self.combo_amp_y.setCurrentText('Linear')
        fl.addRow(
            "Amplitude 轴:",
            _fit_field(self.combo_amp_y, max_width=_SHORT_FIELD_MAX_WIDTH),
        )
        self.combo_psd_y = QComboBox()
        self.combo_psd_y.addItems(['Linear', 'dB'])
        self.combo_psd_y.setCurrentText('dB')
        fl.addRow(
            "PSD 轴:",
            _fit_field(self.combo_psd_y, max_width=_SHORT_FIELD_MAX_WIDTH),
        )
        root.addWidget(g)

        g = QGroupBox("选项")
        gl = QVBoxLayout(g)
        self.chk_autoscale = QCheckBox("自适应频率范围")
        self.chk_autoscale.setChecked(True)
        gl.addWidget(self.chk_autoscale)
        self.chk_remark = QCheckBox("点击标注")
        gl.addWidget(self.chk_remark)
        root.addWidget(g)

        g = QGroupBox("预设配置")
        gl = QVBoxLayout(g)
        gl.setSpacing(4)
        self.preset_bar = PresetBar(
            'fft', self._collect_preset, self._apply_preset, parent=self,
        )
        gl.addWidget(self.preset_bar)
        root.addWidget(g)

        self.btn_fft = QPushButton("计算 FFT")
        self.btn_fft.setIcon(Icons.mode_fft())
        self.btn_fft.setIconSize(QSize(16, 16))
        self.btn_fft.setProperty("role", "primary")
        root.addWidget(self.btn_fft)
        root.addStretch()

        # 2026-04-27 fix-4: unify the label-column width across the
        # sig_card form ("信号" / "Fs") and the 谱参数 QGroupBox form
        # ("窗函数" / "NFFT" / "重叠"). QFormLayout pins each form's label
        # column to the *form's own* max sizeHint, so without this call
        # sig_card labels render in a 36px column while the 谱参数 labels
        # use a 60px column, and the field columns drift apart by ~24px.
        # ``unify_columns=True`` pins every label to the global max so all
        # five fields share the same field-column width and right edge.
        _enforce_label_widths(self, unify_columns=True)

        self.btn_fft.clicked.connect(self.fft_requested)
        self.btn_rebuild.clicked.connect(
            lambda: self.rebuild_time_requested.emit(self.btn_rebuild)
        )
        self.chk_remark.toggled.connect(self.remark_toggled)
        # §6.3 Fs rule: spin_fs reflects selected signal's source file Fs.
        # MainWindow will call set_fs via the signal_changed relay.

    def _collect_preset(self):
        return dict(
            window=self.combo_win.currentText(),
            nfft=self.combo_nfft.currentText(),
            overlap=self.spin_overlap.value(),
            autoscale=self.chk_autoscale.isChecked(),
            remark=self.chk_remark.isChecked(),
        )

    def _apply_preset(self, d):
        if 'window' in d:
            i = self.combo_win.findText(str(d['window']))
            if i >= 0:
                self.combo_win.setCurrentIndex(i)
        if 'nfft' in d:
            i = self.combo_nfft.findText(str(d['nfft']))
            if i >= 0:
                self.combo_nfft.setCurrentIndex(i)
        if 'overlap' in d:
            self.spin_overlap.setValue(int(d['overlap']))
        if 'autoscale' in d:
            self.chk_autoscale.setChecked(bool(d['autoscale']))
        if 'remark' in d:
            self.chk_remark.setChecked(bool(d['remark']))

    def _on_sig_index_changed(self):
        self.signal_changed.emit(self.combo_sig.currentData())

    def set_signal_candidates(self, candidates):
        self.combo_sig.blockSignals(True)
        self.combo_sig.clear()
        for text, data in candidates:
            self.combo_sig.addItem(text, data)
        self.combo_sig.blockSignals(False)
        try:
            self.combo_sig.currentIndexChanged.disconnect(self._on_sig_index_changed)
        except TypeError:
            pass
        self.combo_sig.currentIndexChanged.connect(self._on_sig_index_changed)
        self._on_sig_index_changed()  # emit for newly-populated default

    def current_signal(self):
        return self.combo_sig.currentData()

    def get_params(self):
        nfft_text = self.combo_nfft.currentText()
        return dict(
            window=self.combo_win.currentText(),
            nfft=None if nfft_text == '自动' else int(nfft_text),
            overlap=self.spin_overlap.value() / 100.0,
            autoscale=self.chk_autoscale.isChecked(),
            remark=self.chk_remark.isChecked(),
        )

    def fs(self):
        return self.spin_fs.value()

    def set_fs(self, fs):
        self.spin_fs.blockSignals(True)
        self.spin_fs.setValue(fs)
        self.spin_fs.blockSignals(False)

    # --- Wave 2 / SP2 (Task 2.1): test-friendly param accessors ---
    # current_params/apply_params extend get_params/_apply_preset with the
    # newer Welch averaging + linear/dB axis toggles. Existing callers
    # (main_window, batch presets) continue to use get_params/_collect_preset
    # without change.
    def current_params(self):
        p = self.get_params()
        p['avg_mode'] = self.combo_avg_mode.currentText()
        p['avg_overlap'] = int(self.spin_avg_overlap.value())
        p['amp_y'] = self.combo_amp_y.currentText()
        p['psd_y'] = self.combo_psd_y.currentText()
        return p

    def apply_params(self, d):
        if 'window' in d:
            i = self.combo_win.findText(str(d['window']))
            if i >= 0:
                self.combo_win.setCurrentIndex(i)
        if 'nfft' in d:
            i = self.combo_nfft.findText(str(d['nfft']))
            if i >= 0:
                self.combo_nfft.setCurrentIndex(i)
        if 'overlap' in d:
            try:
                self.spin_overlap.setValue(int(d['overlap']))
            except (TypeError, ValueError):
                pass
        if 'autoscale' in d:
            self.chk_autoscale.setChecked(bool(d['autoscale']))
        if 'remark' in d:
            self.chk_remark.setChecked(bool(d['remark']))
        if 'avg_mode' in d:
            i = self.combo_avg_mode.findText(str(d['avg_mode']))
            if i >= 0:
                self.combo_avg_mode.setCurrentIndex(i)
        if 'avg_overlap' in d:
            try:
                self.spin_avg_overlap.setValue(int(d['avg_overlap']))
            except (TypeError, ValueError):
                pass
        for k, combo in (
            ('amp_y', self.combo_amp_y),
            ('psd_y', self.combo_psd_y),
        ):
            if k in d:
                i = combo.findText(str(d[k]))
                if i >= 0:
                    combo.setCurrentIndex(i)


class OrderContextual(QWidget):
    """Order-analysis contextual: source/params/3 compute btns + tracking sub-group."""

    order_time_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object)  # anchor widget
    signal_changed = pyqtSignal(object)  # (fid, ch) tuple or None
    # T6: cancel intent for the in-flight :class:`OrderWorker`. MainWindow
    # connects this to ``_cancel_order_compute``; the button at the bottom
    # of the layout drives it directly via ``clicked``. Disabled until a
    # worker is actually running (``_dispatch_order_worker`` enables; the
    # ``_on_order_*`` slots disable on completion / failure).
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("orderContextual")
        self.setAttribute(Qt.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        # 紧凑化【3】: tightened from 10 → 6 (2026-04-26).
        root.setSpacing(6)

        # R3 #9: build btn_rebuild before the signal-source group so we
        # can dock it on the group's header row.
        # 2026-04-26 R3 紧凑化 fix-4: setFixedSize(24, 24).
        self.btn_rebuild = QPushButton("")
        self.btn_rebuild.setIcon(Icons.rebuild_time())
        self.btn_rebuild.setIconSize(QSize(16, 16))
        self.btn_rebuild.setFixedSize(QSize(24, 24))
        self.btn_rebuild.setProperty("role", "tool")
        self.btn_rebuild.setToolTip("重建时间轴")
        self.btn_rebuild.clicked.connect(
            lambda: self.rebuild_time_requested.emit(self.btn_rebuild)
        )

        # ---- 信号源 (custom header w/ rebuild button) ----
        # 2026-04-26 R3 紧凑化 fix-2: WA_StyledBackground intentionally OFF.
        sig_card = QFrame(self)
        sig_card.setObjectName("orderSignalCard")
        sig_lay = QVBoxLayout(sig_card)
        sig_lay.setContentsMargins(0, 0, 0, 0)
        sig_lay.setSpacing(4)
        sig_lay.addWidget(_make_group_header("信号源", self.btn_rebuild))
        fl = QFormLayout()
        _configure_form(fl)
        self.combo_sig = SearchableComboBox()
        fl.addRow("信号:", _fit_field(self.combo_sig, max_width=_LONG_FIELD_MAX_WIDTH))
        self.combo_rpm = SearchableComboBox()
        fl.addRow("转速:", _fit_field(self.combo_rpm, max_width=_LONG_FIELD_MAX_WIDTH))
        self.spin_fs = QDoubleSpinBox()
        self.spin_fs.setRange(1, 1e6)
        self.spin_fs.setValue(1000)
        self.spin_fs.setSuffix(" Hz")
        fl.addRow("Fs:", _fit_field(self.spin_fs, max_width=_SHORT_FIELD_MAX_WIDTH))
        self.spin_rf = QDoubleSpinBox()
        self.spin_rf.setRange(0.0001, 10000)
        self.spin_rf.setDecimals(4)
        self.spin_rf.setValue(1)
        fl.addRow("RPM系数:", _fit_field(self.spin_rf, max_width=_SHORT_FIELD_MAX_WIDTH))
        sig_lay.addLayout(fl)
        root.addWidget(sig_card)

        g = QGroupBox("谱参数")
        fl = QFormLayout(g)
        _configure_form(fl)
        self.spin_mo = QSpinBox()
        self.spin_mo.setRange(1, 100)
        self.spin_mo.setValue(20)
        fl.addRow("最大阶次:", _fit_field(self.spin_mo))
        self.spin_order_res = QDoubleSpinBox()
        self.spin_order_res.setRange(0.01, 1.0)
        self.spin_order_res.setValue(0.1)
        self.spin_order_res.setSingleStep(0.05)
        fl.addRow("阶次分辨率:", _fit_field(self.spin_order_res))
        self.spin_time_res = QDoubleSpinBox()
        self.spin_time_res.setRange(0.01, 1.0)
        self.spin_time_res.setValue(0.05)
        self.spin_time_res.setSuffix(" s")
        fl.addRow("时间分辨率:", _fit_field(self.spin_time_res))
        self.combo_nfft = QComboBox()
        self.combo_nfft.addItems(['512', '1024', '2048', '4096', '8192'])
        self.combo_nfft.setCurrentText('1024')
        fl.addRow("FFT点数:", _fit_field(self.combo_nfft))

        # COT is now the only tracking algorithm (Wave 2 of the
        # 2026-04-28 axis-settings + COT migration plan removed the
        # frequency-domain branch). spin_samples_per_rev is therefore
        # always enabled — no companion algorithm picker gates it.
        self.spin_samples_per_rev = QSpinBox()
        self.spin_samples_per_rev.setRange(64, 2048)
        self.spin_samples_per_rev.setValue(256)
        self.spin_samples_per_rev.setToolTip("COT 每转角度采样数")
        fl.addRow(
            "每转样本数:",
            _fit_field(self.spin_samples_per_rev, max_width=_SHORT_FIELD_MAX_WIDTH),
        )

        # R3 B: pin label widths and cap field widths so long Chinese
        # labels (e.g. "阶次分辨率:") never wrap or get elided when the
        # Inspector pane is narrow. _enforce_label_widths walks every form
        # in this widget after construction.
        root.addWidget(g)

        # ---- 坐标轴设置 (Wave 3 of the 2026-04-28 plan) ----
        # Replaces the old combo_amp_mode + combo_dynamic combos. The Z
        # row carries the dB ↔ Linear unit dropdown; floor/ceiling spins
        # express the dB dynamic range explicitly. Defaults match the
        # legacy 30 dB behavior (z_auto off, floor=-30, ceiling=0).
        axis_g = QGroupBox("坐标轴设置")
        axis_lay = QVBoxLayout(axis_g)
        axis_lay.setContentsMargins(8, 8, 8, 8)
        axis_lay.setSpacing(4)

        # Time (X) row
        self.chk_x_auto = QCheckBox("自动")
        self.chk_x_auto.setChecked(True)
        self.spin_x_min = QDoubleSpinBox()
        self.spin_x_min.setRange(0.0, 1e6)
        self.spin_x_min.setDecimals(2)
        self.spin_x_min.setSuffix(' s')
        self.spin_x_max = QDoubleSpinBox()
        self.spin_x_max.setRange(0.0, 1e6)
        self.spin_x_max.setDecimals(2)
        self.spin_x_max.setSuffix(' s')
        axis_lay.addWidget(self._build_axis_row(
            "时间 (X):", self.chk_x_auto,
            self.spin_x_min, self.spin_x_max, None,
        ))

        # Order (Y) row — clamped to <= spin_mo
        self.chk_y_auto = QCheckBox("自动")
        self.chk_y_auto.setChecked(True)
        self.spin_y_min = QDoubleSpinBox()
        self.spin_y_min.setRange(0.0, 100.0)
        self.spin_y_min.setDecimals(2)
        self.spin_y_max = QDoubleSpinBox()
        self.spin_y_max.setRange(0.0, float(self.spin_mo.value()))
        self.spin_y_max.setDecimals(2)
        self.spin_y_max.setValue(float(self.spin_mo.value()))
        axis_lay.addWidget(self._build_axis_row(
            "阶次 (Y):", self.chk_y_auto,
            self.spin_y_min, self.spin_y_max, None,
        ))

        # Color scale (Z) row — has unit dropdown replacing combo_amp_mode
        self.chk_z_auto = QCheckBox("自动")
        self.chk_z_auto.setChecked(False)  # default: -30..0 dB (matches legacy 30 dB behavior)
        self.spin_z_floor = QDoubleSpinBox()
        self.spin_z_floor.setRange(-200.0, 200.0)
        self.spin_z_floor.setDecimals(2)
        self.spin_z_floor.setValue(-30.0)
        self.spin_z_ceiling = QDoubleSpinBox()
        self.spin_z_ceiling.setRange(-200.0, 200.0)
        self.spin_z_ceiling.setDecimals(2)
        self.spin_z_ceiling.setValue(0.0)
        self.combo_amp_unit = QComboBox()
        self.combo_amp_unit.addItems(['dB', 'Linear'])
        axis_lay.addWidget(self._build_axis_row(
            "色阶:", self.chk_z_auto,
            self.spin_z_floor, self.spin_z_ceiling, self.combo_amp_unit,
        ))

        root.addWidget(axis_g)

        # ---- wiring ----
        self.chk_x_auto.toggled.connect(self._sync_axis_enabled)
        self.chk_y_auto.toggled.connect(self._sync_axis_enabled)
        self.chk_z_auto.toggled.connect(self._sync_axis_enabled)
        self.combo_amp_unit.currentTextChanged.connect(self._on_amp_unit_changed)
        self.spin_mo.valueChanged.connect(self._on_max_order_changed)
        # Seed initial enabled state (per the 2026-04-26 init-sync lesson:
        # signal-only wiring leaves the spinbox enabled flags in their
        # constructor default until the user actually toggles a checkbox).
        self._sync_axis_enabled()

        self.btn_ot = QPushButton("时间-阶次")
        self.btn_ot.setProperty("role", "primary")
        self.btn_ot.setMinimumHeight(32)
        root.addWidget(self.btn_ot)

        g = QGroupBox("预设配置")
        gl = QVBoxLayout(g)
        gl.setSpacing(4)
        self.preset_bar = PresetBar(
            'order', self._collect_preset, self._apply_preset, parent=self,
        )
        gl.addWidget(self.preset_bar)
        root.addWidget(g)

        self.lbl_progress = QLabel("")
        root.addWidget(self.lbl_progress)

        # T6: cancel-compute button. Sits at the END of the layout so it
        # never crowds the primary "时间-阶次" button.
        # ``clicked.connect(cancel_requested)`` re-emits without arguments;
        # MainWindow listens to ``cancel_requested``, not the button.
        self.btn_cancel = QPushButton("取消计算", self)
        self.btn_cancel.setObjectName("orderCancelBtn")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_requested)
        root.addWidget(self.btn_cancel)

        root.addStretch()

        self.btn_ot.clicked.connect(self.order_time_requested)

        # R3 B + 2026-04-26 紧凑化 fix-3: pin labels & cap fields so
        # 阶次分辨率 / 时间分辨率 / RPM分辨率 never wrap when the Inspector
        # pane is narrow, AND short numeric spinners no longer balloon when
        # the splitter widens. _SHORT_FIELD_MAX_WIDTH is enough for a 6-digit
        # spinner with the suffix, and frees space for the long Chinese
        # label column. The signal-source combos in the sig_card retain
        # their _LONG_FIELD_MAX_WIDTH cap (set explicitly above) — the cap
        # below applies only to the spec-param form.
        _enforce_label_widths(
            self,
            max_field_width=_SHORT_FIELD_MAX_WIDTH,
            unify_columns=True,
        )

    # ---- 2026-04-28: axis settings group helpers (Wave 3) ----
    def _build_axis_row(self, label, chk, spin_min, spin_max, unit_widget):
        """Build one inline axis row: [label][chk][spin_min][→][spin_max][unit].

        Returns a wrapper QWidget; caller adds it to the parent layout.
        """
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lbl = QLabel(label)
        lbl.setMinimumWidth(56)
        lbl.setMaximumWidth(56)
        lay.addWidget(lbl)
        lay.addWidget(chk)
        spin_min.setMaximumWidth(72)
        spin_max.setMaximumWidth(72)
        lay.addWidget(spin_min, 1)
        lay.addWidget(QLabel('→'))
        lay.addWidget(spin_max, 1)
        if unit_widget is not None:
            lay.addWidget(unit_widget)
        return row

    def _sync_axis_enabled(self):
        """Toggle spin enabled state to match each chk_*_auto."""
        for chk, spins in (
            (self.chk_x_auto, (self.spin_x_min, self.spin_x_max)),
            (self.chk_y_auto, (self.spin_y_min, self.spin_y_max)),
            (self.chk_z_auto, (self.spin_z_floor, self.spin_z_ceiling)),
        ):
            enabled = not chk.isChecked()
            for s in spins:
                s.setEnabled(enabled)

    def _on_amp_unit_changed(self, _txt):
        """Switching dB↔Linear forces z_auto on to avoid stale range values
        in the new unit. Per the 2026-04-28 plan."""
        self.chk_z_auto.setChecked(True)
        self._sync_axis_enabled()

    def _on_max_order_changed(self, val):
        """Clamp spin_y_max upper bound to <= spin_mo (max calc order)."""
        self.spin_y_max.setMaximum(float(val))
        if self.spin_y_max.value() > float(val):
            self.spin_y_max.setValue(float(val))

    def _collect_preset(self):
        return dict(
            rpm_factor=self.spin_rf.value(),
            max_order=self.spin_mo.value(),
            order_res=self.spin_order_res.value(),
            time_res=self.spin_time_res.value(),
            nfft=self.combo_nfft.currentText(),
        )

    def _apply_preset(self, d):
        if 'rpm_factor' in d:
            self.spin_rf.setValue(float(d['rpm_factor']))
        if 'max_order' in d:
            self.spin_mo.setValue(int(d['max_order']))
        if 'order_res' in d:
            self.spin_order_res.setValue(float(d['order_res']))
        if 'time_res' in d:
            self.spin_time_res.setValue(float(d['time_res']))
        if 'nfft' in d:
            i = self.combo_nfft.findText(str(d['nfft']))
            if i >= 0:
                self.combo_nfft.setCurrentIndex(i)
        # ---- Wave 3 (2026-04-28 plan): legacy + new axis-key compat ----
        # Legacy 'dynamic' key compat — translate to z_floor/ceiling/auto.
        # Preferred path: explicit z_floor/ceiling/auto keys override the
        # legacy translation when both are present.
        if 'dynamic' in d and 'z_floor' not in d:
            raw = str(d['dynamic'])
            if raw == 'Auto':
                self.chk_z_auto.setChecked(True)
            else:
                try:
                    n = float(raw.replace('dB', '').strip())
                    self.chk_z_auto.setChecked(False)
                    self.spin_z_floor.setValue(-abs(n))
                    self.spin_z_ceiling.setValue(0.0)
                except ValueError:
                    pass
        # Legacy 'amplitude_mode' key compat — translate to combo_amp_unit.
        # blockSignals so this does NOT trip _on_amp_unit_changed and force
        # z_auto on (which would clobber the dynamic-derived floor/ceiling
        # we just set).
        if 'amplitude_mode' in d:
            val = str(d['amplitude_mode'])
            target = 'dB' if 'dB' in val else 'Linear'
            i = self.combo_amp_unit.findText(target)
            if i >= 0:
                self.combo_amp_unit.blockSignals(True)
                self.combo_amp_unit.setCurrentIndex(i)
                self.combo_amp_unit.blockSignals(False)
        # Apply new axis keys directly when present (preferred path).
        for key, attr in (
            ('z_auto', 'chk_z_auto'), ('y_auto', 'chk_y_auto'), ('x_auto', 'chk_x_auto'),
        ):
            if key in d:
                getattr(self, attr).setChecked(bool(d[key]))
        for key, attr in (
            ('z_floor', 'spin_z_floor'), ('z_ceiling', 'spin_z_ceiling'),
            ('y_min', 'spin_y_min'), ('y_max', 'spin_y_max'),
            ('x_min', 'spin_x_min'), ('x_max', 'spin_x_max'),
        ):
            if key in d:
                try:
                    getattr(self, attr).setValue(float(d[key]))
                except (TypeError, ValueError):
                    pass
        self._sync_axis_enabled()

    def _on_sig_index_changed(self):
        self.signal_changed.emit(self.combo_sig.currentData())

    def set_signal_candidates(self, candidates):
        self.combo_sig.blockSignals(True)
        self.combo_sig.clear()
        for text, data in candidates:
            self.combo_sig.addItem(text, data)
        self.combo_sig.blockSignals(False)
        try:
            self.combo_sig.currentIndexChanged.disconnect(self._on_sig_index_changed)
        except TypeError:
            pass
        self.combo_sig.currentIndexChanged.connect(self._on_sig_index_changed)
        self._on_sig_index_changed()

    def set_rpm_candidates(self, candidates):
        self.combo_rpm.clear()
        self.combo_rpm.addItem("None", None)
        for text, data in candidates:
            self.combo_rpm.addItem(text, data)

    def current_signal(self):
        return self.combo_sig.currentData()

    def current_rpm(self):
        return self.combo_rpm.currentData()

    def fs(self):
        return self.spin_fs.value()

    def set_fs(self, fs):
        self.spin_fs.blockSignals(True)
        self.spin_fs.setValue(fs)
        self.spin_fs.blockSignals(False)

    def rpm_factor(self):
        return self.spin_rf.value()

    def get_params(self):
        return dict(
            max_order=self.spin_mo.value(),
            order_res=self.spin_order_res.value(),
            time_res=self.spin_time_res.value(),
            nfft=int(self.combo_nfft.currentText()),
        )

    # --- Wave 3 (2026-04-28 plan): test-friendly param accessors ---
    # current_params/apply_params extend get_params/_apply_preset with the
    # new 坐标轴设置 group: x/y/z auto + min/max + amplitude unit. The
    # legacy 'amplitude_mode' key is still emitted (mapped from
    # combo_amp_unit) for backwards compatibility with downstream callers
    # that have not yet migrated; Wave 5 will switch the canvas render to
    # consume the explicit z_floor/z_ceiling keys directly.
    def current_params(self):
        p = self.get_params()
        # Map combo_amp_unit ('dB'/'Linear') back to the legacy mode string
        # so existing canvas code (Wave 5 will retire it) keeps working.
        p['amplitude_mode'] = (
            'Amplitude dB' if self.combo_amp_unit.currentText() == 'dB'
            else 'Amplitude'
        )
        # Wave 2 (2026-04-28 plan): combo_algorithm has been removed —
        # COT is the only tracking algorithm. ``samples_per_rev`` stays
        # in the param payload because COT consumes it.
        p['samples_per_rev'] = int(self.spin_samples_per_rev.value())
        # Axis controls (Wave 3): explicit X/Y/Z range + auto flags.
        p['x_auto'] = bool(self.chk_x_auto.isChecked())
        p['x_min'] = float(self.spin_x_min.value())
        p['x_max'] = float(self.spin_x_max.value())
        p['y_auto'] = bool(self.chk_y_auto.isChecked())
        p['y_min'] = float(self.spin_y_min.value())
        p['y_max'] = float(self.spin_y_max.value())
        p['z_auto'] = bool(self.chk_z_auto.isChecked())
        p['z_floor'] = float(self.spin_z_floor.value())
        p['z_ceiling'] = float(self.spin_z_ceiling.value())
        return p

    def apply_params(self, d):
        if 'max_order' in d:
            try:
                self.spin_mo.setValue(int(d['max_order']))
            except (TypeError, ValueError):
                pass
        if 'order_res' in d:
            try:
                self.spin_order_res.setValue(float(d['order_res']))
            except (TypeError, ValueError):
                pass
        if 'time_res' in d:
            try:
                self.spin_time_res.setValue(float(d['time_res']))
            except (TypeError, ValueError):
                pass
        if 'nfft' in d:
            i = self.combo_nfft.findText(str(d['nfft']))
            if i >= 0:
                self.combo_nfft.setCurrentIndex(i)
        # ---- Wave 3 (2026-04-28 plan): new axis fields (preferred path) ----
        for key, attr in (
            ('x_auto', 'chk_x_auto'),
            ('y_auto', 'chk_y_auto'),
            ('z_auto', 'chk_z_auto'),
        ):
            if key in d:
                getattr(self, attr).setChecked(bool(d[key]))
        for key, attr in (
            ('x_min', 'spin_x_min'), ('x_max', 'spin_x_max'),
            ('y_min', 'spin_y_min'), ('y_max', 'spin_y_max'),
            ('z_floor', 'spin_z_floor'), ('z_ceiling', 'spin_z_ceiling'),
        ):
            if key in d:
                try:
                    getattr(self, attr).setValue(float(d[key]))
                except (TypeError, ValueError):
                    pass

        # amplitude_mode → combo_amp_unit (blockSignals so the unit-toggle
        # handler does not flip z_auto on and stomp explicit z_floor/ceiling
        # values arriving in the same dict).
        if 'amplitude_mode' in d:
            val = str(d['amplitude_mode'])
            target = 'dB' if 'dB' in val else 'Linear'
            i = self.combo_amp_unit.findText(target)
            if i >= 0:
                self.combo_amp_unit.blockSignals(True)
                self.combo_amp_unit.setCurrentIndex(i)
                self.combo_amp_unit.blockSignals(False)

        # Legacy 'dynamic' key compat — translate to z_floor/ceiling/auto.
        # The new explicit z_floor key (already applied above) takes
        # precedence; we only fall through to dynamic when z_floor is
        # absent.
        if 'dynamic' in d and 'z_floor' not in d:
            raw = str(d['dynamic'])
            if raw == 'Auto':
                self.chk_z_auto.setChecked(True)
            else:
                try:
                    n = float(raw.replace('dB', '').strip())
                    self.chk_z_auto.setChecked(False)
                    self.spin_z_floor.setValue(-abs(n))
                    self.spin_z_ceiling.setValue(0.0)
                except ValueError:
                    pass

        # Wave 2 (2026-04-28 plan): the algorithm round-trip was dropped
        # along with combo_algorithm. Legacy presets carrying an
        # 'algorithm' key are silently ignored — Wave 6's preset-IO
        # migration covers the on-disk shape.
        if 'samples_per_rev' in d:
            try:
                self.spin_samples_per_rev.setValue(int(d['samples_per_rev']))
            except (TypeError, ValueError):
                pass

        self._sync_axis_enabled()

    def set_progress(self, text):
        self.lbl_progress.setText(text)


class FFTTimeContextual(QWidget):
    """FFT vs Time contextual: signal / time-frequency params / amplitude /
    range-and-color / presets / actions.

    Public surface consumed by ``Inspector`` and ``MainWindow``:

    Signals
    -------
    - ``fft_time_requested`` — primary "compute" button click.
    - ``force_recompute_requested`` — force-recompute (cache bypass) button.
    - ``export_full_requested`` — export full view (spectrogram + slice).
    - ``export_main_requested`` — export main spectrogram only.

    Widgets (referenced by name from MainWindow / tests)
    ---------------------------------------------------
    - ``combo_sig`` — analysis signal candidate (``(fid, ch)`` userData).
    - ``spin_fs`` — sampling frequency (Hz).
    - ``btn_rebuild`` — relay anchor for "rebuild time axis" host action.
    - ``combo_nfft`` / ``combo_win`` / ``spin_overlap`` /
      ``chk_remove_mean`` — analysis parameters.
    - ``combo_amp_mode`` — Amplitude / Amplitude dB mode.
    - ``chk_freq_auto`` / ``spin_freq_min`` / ``spin_freq_max`` —
      frequency range; ``spin_freq_max == 0.0`` means "use Nyquist".
    - ``combo_dynamic`` — dynamic range (dB) selector.
    - ``combo_cmap`` — color map selector.
    - ``btn_compute`` — primary action; disabled iff no candidate.
    - ``btn_force`` / ``btn_export_full`` / ``btn_export_main`` — secondary
      actions.

    ``get_params()`` returns a dict whose keys match exactly what
    ``MainWindow._fft_time_cache_key`` expects: ``signal``, ``fs``,
    ``nfft``, ``window``, ``overlap``, ``remove_mean``, ``amplitude_mode``,
    ``db_reference``, ``freq_auto``, ``freq_min``, ``freq_max``,
    ``dynamic``, ``cmap``.

    Built-in presets (per design §7): ``diagnostic``, ``amplitude_accuracy``,
    ``high_frequency``.
    """

    fft_time_requested = pyqtSignal()
    force_recompute_requested = pyqtSignal()
    export_full_requested = pyqtSignal()
    export_main_requested = pyqtSignal()
    rebuild_time_requested = pyqtSignal(object)  # anchor widget
    signal_changed = pyqtSignal(object)  # emits (fid, ch) or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("fftTimeContextual")
        self.setAttribute(Qt.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        # 紧凑化【3】: tightened from 10 → 6 (2026-04-26).
        root.setSpacing(6)

        # ---- 分析信号 (R3 #9: btn_rebuild docked on header bar) ----
        # 2026-04-26 R3 紧凑化 fix-4: setFixedSize(24, 24).
        self.btn_rebuild = QPushButton("")
        self.btn_rebuild.setIcon(Icons.rebuild_time())
        self.btn_rebuild.setIconSize(QSize(16, 16))
        self.btn_rebuild.setFixedSize(QSize(24, 24))
        self.btn_rebuild.setProperty("role", "tool")
        self.btn_rebuild.setToolTip("重建时间轴")
        self.btn_rebuild.clicked.connect(
            lambda: self.rebuild_time_requested.emit(self.btn_rebuild)
        )
        # 2026-04-26 R3 紧凑化 fix-2: WA_StyledBackground intentionally OFF.
        sig_card = QFrame(self)
        sig_card.setObjectName("fftTimeSignalCard")
        sig_lay = QVBoxLayout(sig_card)
        sig_lay.setContentsMargins(0, 0, 0, 0)
        sig_lay.setSpacing(4)
        sig_lay.addWidget(_make_group_header("分析信号", self.btn_rebuild))
        fl = QFormLayout()
        _configure_form(fl)
        self.combo_sig = SearchableComboBox()
        fl.addRow("信号:", _fit_field(self.combo_sig, max_width=_LONG_FIELD_MAX_WIDTH))
        self.spin_fs = QDoubleSpinBox()
        self.spin_fs.setRange(1, 1e6)
        self.spin_fs.setValue(1000)
        self.spin_fs.setSuffix(" Hz")
        fl.addRow("Fs:", _fit_field(self.spin_fs, max_width=_SHORT_FIELD_MAX_WIDTH))
        sig_lay.addLayout(fl)
        root.addWidget(sig_card)

        # ---- 时频参数 ----
        # 2026-04-26 R3 紧凑化 fix-3: cap each short field.
        g = QGroupBox("时频参数")
        fl = QFormLayout(g)
        _configure_form(fl)
        self.combo_nfft = QComboBox()
        self.combo_nfft.addItems(['512', '1024', '2048', '4096', '8192'])
        self.combo_nfft.setCurrentText('2048')
        fl.addRow("FFT 点数:", _fit_field(self.combo_nfft, max_width=_SHORT_FIELD_MAX_WIDTH))
        self.combo_win = QComboBox()
        self.combo_win.addItems(
            ['hanning', 'flattop', 'hamming', 'blackman', 'kaiser', 'bartlett']
        )
        fl.addRow("窗函数:", _fit_field(self.combo_win, max_width=_SHORT_FIELD_MAX_WIDTH))
        self.spin_overlap = QSpinBox()
        # HEAD-style smoothness defaults: 88% (closest integer to the 87.5%
        # spectrogram-smoothness target documented in the FFT-vs-Time
        # integration plan) with a 95% ceiling so users can dial up the
        # COLA-safe high-overlap region. The QSpinBox stays integer-percent
        # so existing presets (overlap=75, 50) and getter/setter int paths
        # remain untouched.
        self.spin_overlap.setRange(0, 95)
        self.spin_overlap.setValue(88)
        self.spin_overlap.setSuffix(" %")
        fl.addRow("重叠:", _fit_field(self.spin_overlap, max_width=_SHORT_FIELD_MAX_WIDTH))
        self.chk_remove_mean = QCheckBox("去均值")
        self.chk_remove_mean.setChecked(True)
        fl.addRow(self.chk_remove_mean)
        root.addWidget(g)

        # ---- 幅值 ----
        g = QGroupBox("幅值")
        fl = QFormLayout(g)
        _configure_form(fl)
        self.combo_amp_mode = QComboBox()
        self.combo_amp_mode.addItems(['Amplitude dB', 'Amplitude'])
        fl.addRow("模式:", _fit_field(self.combo_amp_mode, max_width=_SHORT_FIELD_MAX_WIDTH))
        self.spin_db_ref = QDoubleSpinBox()
        self.spin_db_ref.setRange(1e-9, 1e9)
        self.spin_db_ref.setDecimals(6)
        self.spin_db_ref.setValue(1.0)
        fl.addRow("dB 参考:", _fit_field(self.spin_db_ref, max_width=_SHORT_FIELD_MAX_WIDTH))
        root.addWidget(g)

        # ---- 范围与色标 ----
        g = QGroupBox("范围与色标")
        fl = QFormLayout(g)
        _configure_form(fl)
        self._freq_form = fl
        self.chk_freq_auto = QCheckBox("自动频率范围")
        self.chk_freq_auto.setChecked(True)
        fl.addRow(self.chk_freq_auto)
        # 紧凑化【1】: 频率下限 + 上限 share one form row (label-prefix
        # "下限:" with inline "上限:" between the two spins).
        self.spin_freq_min = QDoubleSpinBox()
        self.spin_freq_min.setRange(0, 1e9)
        self.spin_freq_min.setDecimals(2)
        self.spin_freq_min.setSuffix(" Hz")
        self.spin_freq_min.setMaximumWidth(_SHORT_FIELD_MAX_WIDTH)
        self.spin_freq_max = QDoubleSpinBox()
        self.spin_freq_max.setRange(0, 1e9)
        self.spin_freq_max.setDecimals(2)
        self.spin_freq_max.setSuffix(" Hz")
        # 0.0 means "use Nyquist" — see consumer in MainWindow.
        self.spin_freq_max.setValue(0.0)
        self.spin_freq_max.setMaximumWidth(_SHORT_FIELD_MAX_WIDTH)
        self._freq_row_host = _pair_field(
            self.spin_freq_min, "上限:", self.spin_freq_max,
        )
        fl.addRow("下限:", self._freq_row_host)
        self.combo_dynamic = QComboBox()
        self.combo_dynamic.addItems(['80 dB', '60 dB', 'Auto'])
        fl.addRow("动态范围:", _fit_field(self.combo_dynamic, max_width=_SHORT_FIELD_MAX_WIDTH))
        self.combo_cmap = QComboBox()
        self.combo_cmap.addItems(['turbo', 'viridis', 'gray'])
        fl.addRow("色图:", _fit_field(self.combo_cmap, max_width=_SHORT_FIELD_MAX_WIDTH))
        root.addWidget(g)

        # ---- 预设 (R3 C: builtin-aware PresetBar) ----
        g = QGroupBox("预设")
        gl = QVBoxLayout(g)
        gl.setSpacing(4)
        # The preset_bar is single-row, builtin-aware: each slot starts with
        # its builtin display name (配置1 / 配置2 / 配置3), left-click
        # loads (override-or-builtin), right-click menu integrates 保存当前 /
        # 重命名 / 重置为默认.
        builtin_defaults = {
            slot: {
                'display_name': self._BUILTIN_PRESET_DISPLAY[name],
                'params': self._builtin_preset_full_params(name),
            }
            for slot, name in zip(
                (1, 2, 3),
                ('diagnostic', 'amplitude_accuracy', 'high_frequency'),
            )
        }
        self.preset_bar = PresetBar(
            'fft_time',
            self._collect_preset,
            self._apply_preset,
            parent=self,
            builtin_defaults=builtin_defaults,
        )
        gl.addWidget(self.preset_bar)
        root.addWidget(g)

        # ---- 操作 ----
        self.btn_compute = QPushButton("计算时频图")
        self.btn_compute.setProperty("role", "primary")
        # Disabled until a signal candidate is provided. The
        # ``set_signal_candidates`` hook keeps this in sync with the
        # candidate list.
        self.btn_compute.setEnabled(False)
        root.addWidget(self.btn_compute)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self.btn_force = QPushButton("强制重算")
        self.btn_force.setProperty("role", "tool")
        self.btn_force.setToolTip("绕过缓存并重新计算")
        action_row.addWidget(self.btn_force)
        self.btn_export_full = QPushButton("导出完整视图")
        self.btn_export_full.setIcon(Icons.export())
        self.btn_export_full.setIconSize(QSize(14, 14))
        self.btn_export_full.setProperty("role", "tool")
        action_row.addWidget(self.btn_export_full)
        self.btn_export_main = QPushButton("导出主图")
        self.btn_export_main.setIcon(Icons.export())
        self.btn_export_main.setIconSize(QSize(14, 14))
        self.btn_export_main.setProperty("role", "tool")
        action_row.addWidget(self.btn_export_main)
        root.addLayout(action_row)
        root.addStretch()

        # 2026-04-27 fix-4: unify label-column width across the sig_card
        # form and every QGroupBox form so all field columns share the
        # same width and right edge (see FFTContextual for rationale).
        _enforce_label_widths(self, unify_columns=True)

        # ---- wiring ----
        self.btn_compute.clicked.connect(self.fft_time_requested)
        self.btn_force.clicked.connect(self.force_recompute_requested)
        self.btn_export_full.clicked.connect(self.export_full_requested)
        self.btn_export_main.clicked.connect(self.export_main_requested)
        # Auto-disable manual freq range fields when "auto" is checked.
        self.chk_freq_auto.toggled.connect(self._update_freq_fields_enabled)
        # 紧凑化【2】: also hide the row entirely when in auto mode.
        self.chk_freq_auto.toggled.connect(self._update_freq_row_visible)
        self._update_freq_fields_enabled(self.chk_freq_auto.isChecked())
        self._update_freq_row_visible(self.chk_freq_auto.isChecked())

    # ---- helpers ----
    def _update_freq_fields_enabled(self, auto_checked):
        manual = not bool(auto_checked)
        self.spin_freq_min.setEnabled(manual)
        self.spin_freq_max.setEnabled(manual)

    def _update_freq_row_visible(self, auto_checked):
        # auto checked → row hidden; manual → visible.
        _set_form_row_visible(
            self._freq_form, self._freq_row_host, not bool(auto_checked),
        )

    def _on_sig_index_changed(self):
        self.signal_changed.emit(self.combo_sig.currentData())

    # ---- public API consumed by MainWindow / tests ----
    def set_signal_candidates(self, candidates):
        """Repopulate the signal combo, preserving an existing selection
        (matched by userData) when it remains in the new candidate list.

        The compute button is enabled iff the combo ends with at least one
        item — this hook is part of the contract verified by
        ``test_fft_time_compute_button_tracks_signal_candidates``.
        """
        prev = self.combo_sig.currentData()
        self.combo_sig.blockSignals(True)
        self.combo_sig.clear()
        keep_idx = -1
        for i, (text, data) in enumerate(candidates):
            self.combo_sig.addItem(text, data)
            if prev is not None and data == prev:
                keep_idx = i
        if keep_idx >= 0:
            self.combo_sig.setCurrentIndex(keep_idx)
        self.combo_sig.blockSignals(False)
        # Re-attach signal_changed listener exactly once.
        try:
            self.combo_sig.currentIndexChanged.disconnect(
                self._on_sig_index_changed
            )
        except TypeError:
            pass
        self.combo_sig.currentIndexChanged.connect(self._on_sig_index_changed)
        # Compute is enabled iff there is a valid candidate. This is the
        # T2 hook the mode-plumbing tests rely on — keep it as the LAST
        # statement so it always reflects the final combo state.
        self.btn_compute.setEnabled(self.combo_sig.count() > 0)

    def current_signal(self):
        return self.combo_sig.currentData()

    def fs(self):
        return self.spin_fs.value()

    def set_fs(self, fs):
        self.spin_fs.blockSignals(True)
        self.spin_fs.setValue(float(fs))
        self.spin_fs.blockSignals(False)

    def get_params(self):
        mode = self.combo_amp_mode.currentText()
        return dict(
            signal=self.combo_sig.currentData(),
            fs=self.spin_fs.value(),
            nfft=int(self.combo_nfft.currentText()),
            window=self.combo_win.currentText(),
            overlap=self.spin_overlap.value() / 100.0,
            remove_mean=self.chk_remove_mean.isChecked(),
            amplitude_mode='amplitude_db' if 'dB' in mode else 'amplitude',
            db_reference=self.spin_db_ref.value(),
            freq_auto=self.chk_freq_auto.isChecked(),
            freq_min=self.spin_freq_min.value(),
            freq_max=self.spin_freq_max.value(),
            dynamic=self.combo_dynamic.currentText(),
            cmap=self.combo_cmap.currentText(),
        )

    # ---- built-in presets (design §7) ----
    _BUILTIN_PRESETS = {
        'diagnostic': dict(
            window='hanning',
            nfft=2048,
            overlap=75,
            amplitude_mode='Amplitude dB',
            freq_auto=True,
            dynamic='80 dB',
            cmap='turbo',
        ),
        'amplitude_accuracy': dict(
            window='flattop',
            nfft=4096,
            overlap=75,
            amplitude_mode='Amplitude',
            freq_auto=True,
            dynamic='Auto',
            cmap='viridis',
        ),
        'high_frequency': dict(
            window='hanning',
            nfft=4096,
            overlap=50,
            amplitude_mode='Amplitude dB',
            freq_auto=True,
            dynamic='60 dB',
            cmap='turbo',
        ),
    }

    # User-facing display names for the three builtin slots (R3 C —
    # what the PresetBar shows on the slot button when no override exists).
    _BUILTIN_PRESET_DISPLAY = {
        'diagnostic': '配置1',
        'amplitude_accuracy': '配置2',
        'high_frequency': '配置3',
    }

    def _builtin_preset_full_params(self, name):
        """Return a JSON-serializable param dict for a builtin preset.

        Mirrors the keys we collect in ``_collect_preset`` so the
        builtin-aware PresetBar can save / reset / load the same shape
        round-trip.
        """
        cfg = self._BUILTIN_PRESETS.get(name, {})
        # Spread the legacy compact dict to the full collect_preset shape
        # — fields we don't override default to "the same value the
        # widget has at construction time" so an unspecified field doesn't
        # silently mutate.
        return {
            'window': cfg.get('window', 'hanning'),
            'nfft': cfg.get('nfft', 2048),
            'overlap': cfg.get('overlap', 75),
            'amplitude_mode': cfg.get('amplitude_mode', 'Amplitude dB'),
            'remove_mean': True,
            'db_reference': 1.0,
            'freq_auto': cfg.get('freq_auto', True),
            'freq_min': 0.0,
            'freq_max': 0.0,
            'dynamic': cfg.get('dynamic', '80 dB'),
            'cmap': cfg.get('cmap', 'turbo'),
        }

    def _collect_preset(self):
        """Snapshot the current time-frequency params for PresetBar save."""
        return dict(
            window=self.combo_win.currentText(),
            nfft=self.combo_nfft.currentText(),
            overlap=self.spin_overlap.value(),
            amplitude_mode=self.combo_amp_mode.currentText(),
            remove_mean=self.chk_remove_mean.isChecked(),
            db_reference=self.spin_db_ref.value(),
            freq_auto=self.chk_freq_auto.isChecked(),
            freq_min=self.spin_freq_min.value(),
            freq_max=self.spin_freq_max.value(),
            dynamic=self.combo_dynamic.currentText(),
            cmap=self.combo_cmap.currentText(),
        )

    def _apply_preset(self, d):
        """Restore previously-saved params from PresetBar load (R3 C).

        Tolerates absent keys so legacy / partial dicts (and the compact
        builtin shape) all round-trip safely.
        """
        if 'window' in d:
            i = self.combo_win.findText(str(d['window']))
            if i >= 0:
                self.combo_win.setCurrentIndex(i)
        if 'nfft' in d:
            i = self.combo_nfft.findText(str(d['nfft']))
            if i >= 0:
                self.combo_nfft.setCurrentIndex(i)
        if 'overlap' in d:
            try:
                self.spin_overlap.setValue(int(d['overlap']))
            except (TypeError, ValueError):
                pass
        if 'amplitude_mode' in d:
            i = self.combo_amp_mode.findText(str(d['amplitude_mode']))
            if i >= 0:
                self.combo_amp_mode.setCurrentIndex(i)
        if 'remove_mean' in d:
            self.chk_remove_mean.setChecked(bool(d['remove_mean']))
        if 'db_reference' in d:
            try:
                self.spin_db_ref.setValue(float(d['db_reference']))
            except (TypeError, ValueError):
                pass
        if 'freq_auto' in d:
            self.chk_freq_auto.setChecked(bool(d['freq_auto']))
        if 'freq_min' in d:
            try:
                self.spin_freq_min.setValue(float(d['freq_min']))
            except (TypeError, ValueError):
                pass
        if 'freq_max' in d:
            try:
                self.spin_freq_max.setValue(float(d['freq_max']))
            except (TypeError, ValueError):
                pass
        if 'dynamic' in d:
            i = self.combo_dynamic.findText(str(d['dynamic']))
            if i >= 0:
                self.combo_dynamic.setCurrentIndex(i)
        if 'cmap' in d:
            i = self.combo_cmap.findText(str(d['cmap']))
            if i >= 0:
                self.combo_cmap.setCurrentIndex(i)

    def apply_builtin_preset(self, name):
        """Apply one of the built-in presets (``'diagnostic'``,
        ``'amplitude_accuracy'``, ``'high_frequency'``).

        Retained for backward compatibility with regression tests and
        any external regression harness — internally this delegates to
        the PresetBar's full-params dict so the builtin-aware path and
        the legacy method stay in sync.
        """
        cfg = self._BUILTIN_PRESETS.get(name)
        if not cfg:
            return
        self._apply_preset(self._builtin_preset_full_params(name))
