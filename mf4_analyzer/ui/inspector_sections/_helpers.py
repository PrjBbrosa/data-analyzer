"""Preset/unit helpers and form/axis-build helpers for inspector sections."""
import json
from html import escape

from PyQt5.QtCore import QSettings, QSize, Qt
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ...ui_kit.widgets.searchable_combo import SearchableComboBox
from ..widgets.compact_spinbox import CompactDoubleSpinBox, no_buttons
from .._axis_defaults import z_range_for


_PRESET_ORG = "MF4Analyzer"
_PRESET_APP = "DataAnalyzer"


def _preset_settings():
    return QSettings(_PRESET_ORG, _PRESET_APP)


# ---- Signal-type built-in presets (shared by FFT-1D / FFT-time / Order) ----
#
# The three analysis views share ONE set of three built-in presets, displayed
# as 频率优先 / 均衡 / 时间优先 on PresetBar slots 1/2/3. Slot order is a
# contract consumed by ``recommend_preset_for_unit`` (torque=1, vibration=2,
# transient=3) and the per-view ``set_recommended_for_unit`` wiring.
BUILTIN_PRESET_KEYS = ('torque', 'vibration', 'transient')
BUILTIN_PRESET_DISPLAY = {
    'torque': '频率优先',
    'vibration': '均衡',
    'transient': '时间优先',
}
# preset key -> PresetBar slot index (slots are 1-based: 1/2/3).
_PRESET_KEY_TO_SLOT = {'torque': 1, 'vibration': 2, 'transient': 3}
# Blurb text for builtin hover cards (view-agnostic).
BUILTIN_PRESET_BLURB = {
    'torque': '频率 / 幅值最准，时间偏粗 · 适合扭矩、压力等稳态量',
    'vibration': '时间-频率折中，宽动态 · 适合振动等通用诊断',
    'transient': '时间最细，频率偏粗 · 适合启停、冲击等瞬态',
}


def _normalize_unit(unit):
    """Normalize a channel-unit string for exact alias matching.

    Lower-cases, strips whitespace, and folds the Unicode superscript-two
    (``²``) into ``2`` so ``m/s²`` / ``m/s^2`` / ``m/s2`` all compare equal.
    The ``^`` and leftover whitespace inside the token are dropped too so the
    canonical form for "metre per second squared" is ``m/s2``.
    """
    if unit is None:
        return ''
    s = str(unit).strip().lower()
    # Fold superscripts to plain digits, then drop the ^ exponent marker so
    # m/s², m/s^2 and m/s2 all collapse to the same canonical token.
    s = (
        s.replace('²', '2')  # ² superscript two
         .replace('³', '3')  # ³ superscript three
         .replace('^', '')
    )
    # Collapse any internal whitespace (e.g. "n m" -> "nm").
    s = ''.join(s.split())
    return s


# Exact-match alias sets (already normalized via _normalize_unit). Exact match
# is intentional — substring matching would mis-route 'g' onto 'kg'/'deg' and
# 'pa' onto 'kpa'.
_TORQUE_UNITS = frozenset({
    'nm', 'n·m', 'n.m', 'n*m', 'mnm', 'knm', 'cnm',
    'bar', 'mbar', 'kpa', 'mpa', 'hpa', 'pa', 'psi',
    '°', 'deg', 'mm', 'µm', 'um', '%',
})
_VIBRATION_UNITS = frozenset({
    'g', 'mg', 'm/s2', 'mm/s', 'mm/s2', 'µm/s', 'um/s', 'in/s',
})


def _dynamic_to_floor(dynamic):
    """Parse a legacy ``dynamic`` token into a z-axis floor (negative dB).

    Accepts ``'Auto'`` (→ -80.0 default span) and any ``'NN dB'`` form
    (→ -NN). Generalizing the old hard-coded -80/-60 branch so an arbitrary
    span (e.g. '100 dB') maps to floor = -100 without a special case.
    """
    raw = str(dynamic).strip()
    if not raw or raw == 'Auto':
        return -80.0
    try:
        return -abs(float(raw.lower().replace('db', '').strip()))
    except ValueError:
        return -80.0


def recommend_preset_for_unit(unit):
    """Return the recommended built-in preset key for a channel unit.

    Returns one of ``'torque'`` / ``'vibration'`` / ``'transient'``.
    Unknown / unrecognized units fall back to ``'vibration'`` (the default).
    Matching is on the normalized form (see :func:`_normalize_unit`) with an
    EXACT alias lookup so 'kg' is not mistaken for 'g' nor 'kpa' for 'pa'.
    """
    norm = _normalize_unit(unit)
    if norm in _TORQUE_UNITS:
        return 'torque'
    if norm in _VIBRATION_UNITS:
        return 'vibration'
    return 'vibration'


def _no_buttons(spin):
    """Strip the up/down stepper from a Q(Double)SpinBox.

    Thin re-export of :func:`mf4_analyzer.ui.widgets.compact_spinbox.no_buttons`
    so all spinboxes — Inspector, batch ``method_buttons``, dialogs,
    popovers — go through one helper that pairs ``setButtonSymbols``
    with the ``compact=True`` dynamic property that opts the widget
    into the project's QSS subcontrol collapse rules. Kept private to
    preserve the existing 20+ call sites; new callers should import
    ``no_buttons`` directly. Returns ``spin`` for chaining.
    """
    return no_buttons(spin)


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


def _make_params_card(owner, object_name):
    """Build the lower 谱参数 / 时频参数 panel as a standalone tinted card.

    2026-06-13 分析信号/谱参数 split: the analysis-signal card and the
    spectrum-parameter groups used to share one tinted contextual surface
    (the green ``sig_card`` nested inside the contextual's own background).
    The user asked for two independent, vertically-separated panels each with
    its own border and backdrop. This frame hosts everything below the
    ``sig_card`` (params + axis settings + presets + compute button) so it
    renders as a second full-width card; the contextual widget itself is now
    a transparent host and an 8px gutter (root spacing) separates the cards.

    The inner padding (10px horizontal) mirrors the ``sig_card`` so the form
    field columns of both panels still share one width / right edge — the A1
    contract enforced by ``test_fft_contextual_fields_fill_column_under_qss``.

    Returns ``(card, layout)``; the caller adds its groups to ``layout`` and
    adds ``card`` to the contextual's root once, in place of the per-group
    ``root.addWidget`` calls.
    """
    card = QFrame(owner)
    card.setObjectName(object_name)
    card.setAttribute(Qt.WA_StyledBackground, True)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(10, 8, 10, 10)
    lay.setSpacing(6)
    return card, lay


def _settings_bool(settings, key, default):
    raw = settings.value(key, default)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(default)


def _preset_value_text(value):
    if isinstance(value, bool):
        return '是' if value else '否'
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


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
        # 18px 2px 8px; }`` rule wins over Python ``setContentsMargins``
        # during stylesheet polish, eating ~2px on each side and ~6px at
        # the bottom. A local stylesheet on the specific QGroupBox zeros
        # the horizontal/bottom padding while explicitly preserving the
        # extra title-to-content air requested for the persistent top
        # groups.
        # Without this, the form-layout cells inside the QGroupBox render
        # ~9px narrower than the matching sig_card cells, breaking A1
        # field-column alignment.
        parent.setStyleSheet(
            "QGroupBox { padding-top: 22px; "
            "padding-left: 0; padding-right: 0; "
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
    if isinstance(widget, QAbstractSpinBox):
        widget.setButtonSymbols(QAbstractSpinBox.NoButtons)
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
    form_field = field_widget
    label = form.labelForField(form_field)
    if label is None:
        parent = field_widget.parentWidget()
        while parent is not None:
            label = form.labelForField(parent)
            if label is not None:
                form_field = parent
                break
            parent = parent.parentWidget()

    form_field.setVisible(visible)
    if form_field is not field_widget:
        field_widget.setVisible(visible)
    for child in form_field.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
        child.setVisible(visible)
    if label is not None:
        label.setVisible(visible)


# ---- 2026-04-28 (axis-settings + COT migration plan, Wave 4) ----
#
# Both OrderContextual and FFTTimeContextual host an identical "坐标轴设置"
# group: three inline rows (X / Y / Z) of `[label][chk_auto][spin_min][→]
# [spin_max][optional unit]`. Wave 3 inlined the implementation as instance
# methods on OrderContextual; Wave 4 lifts the row-builder and group
# assembly to module level so FFTTimeContextual can reuse it without the
# instance-method duplication that triggered the audit S7 fix.
#
# Caller responsibilities (NOT folded into the helper because they read
# class-specific attributes):
#   1. ``_sync_axis_enabled`` — declared as an instance method on each
#      contextual; the helper wires the chk_*_auto.toggled →
#      owner._sync_axis_enabled signal but the implementation walks
#      owner.chk_*_auto + owner.spin_*_min/max which is identical across
#      classes (same widget names).
#   2. ``_on_amp_unit_changed`` — same: instance method, but trivially
#      identical across both classes (force chk_z_auto.setChecked(True)
#      and re-sync). Could also have been a module helper; keeping it as
#      an instance method preserves overrideability and matches the
#      Wave 3 surface tests.
#   3. Order-specific spin_y_max ↔ spin_mo clamp (``_on_max_order_changed``)
#      stays on OrderContextual only; the helper is order-agnostic.


class _AxisRangeHost(QWidget):
    def __init__(self, reserved_width, parent=None):
        super().__init__(parent)
        self._reserved_width = int(reserved_width)
        self._reserved_height = 0

    def set_reserved_height(self, height):
        self._reserved_height = max(self._reserved_height, int(height))

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(
            max(hint.width(), self._reserved_width),
            max(hint.height(), self._reserved_height),
        )

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(
            max(hint.width(), self._reserved_width),
            max(hint.height(), self._reserved_height),
        )


# 2026-06-05 narrow-pane: shared column geometry so the 自动 / 最小 / 最大
# header row (built by _build_axis_header) lines up pixel-for-pixel with the
# per-axis rows. The 自动 column is now a bare checkbox (the header labels it
# once) instead of three repeated "自动" texts — that frees ~24px which the
# fluid min→max editors absorb.
_AXIS_LABEL_W = 56
_AXIS_CHK_W = 30
_AXIS_ROW_GAP = 4
_AXIS_ARROW_W = 12
_AXIS_MANUAL_GAP = 3


def _build_axis_row(label, chk, spin_min, spin_max, unit_widget, summary_label):
    """Build one inline axis row.

    Visual states (columns line up under the 自动/最小/最大 header):
    - auto checked: [label][✓][summary][unit]
    - manual:       [label][✓][spin_min][→][spin_max][unit]

    Returns ``(row, parts)``; caller stores ``parts`` so _sync_axis_enabled
    can toggle summary vs. editable bounds.
    """
    row_gap = _AXIS_ROW_GAP
    arrow_width = _AXIS_ARROW_W
    manual_gap = _AXIS_MANUAL_GAP
    unit_width = 64
    # 2026-06-05 narrow-pane: the range editors are now fluid (Expanding) so
    # the whole group shrinks with the 288px pane instead of forcing a
    # horizontal scrollbar. ``range_floor`` is the smallest the min→max area
    # ever collapses to; the pane is wide enough that it normally renders
    # ~120px, giving ~52px per spin. The dB/Linear unit (色阶 row only) no
    # longer steals inline width — it wraps to its own right-aligned line so
    # X / Y / Z editors all settle at the same width.
    range_floor = 104
    spin_floor = 42

    # ``container`` is the widget added to the group: line 1 holds
    # [label][auto][min → max]; an optional line 2 carries the unit combo
    # right-aligned beneath the editors.
    container = QWidget()
    container.setObjectName("axisRow")
    container.setAttribute(Qt.WA_StyledBackground, True)
    container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    outer = QVBoxLayout(container)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(2)

    line1 = QWidget(container)
    line1.setObjectName("axisRowLine")
    line1.setAttribute(Qt.WA_StyledBackground, True)
    lay = QHBoxLayout(line1)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(row_gap)
    lbl = QLabel(label)
    lbl.setMinimumWidth(_AXIS_LABEL_W)
    lbl.setMaximumWidth(_AXIS_LABEL_W)
    lay.addWidget(lbl)
    # Bare checkbox centred in the 自动 column (the header labels it once).
    chk_cell = QWidget(line1)
    chk_cell.setObjectName("axisAutoCell")
    chk_cell.setAttribute(Qt.WA_StyledBackground, True)
    chk_cell.setFixedWidth(_AXIS_CHK_W)
    chk_lay = QHBoxLayout(chk_cell)
    chk_lay.setContentsMargins(0, 0, 0, 0)
    chk_lay.setSpacing(0)
    chk_lay.addStretch(1)
    chk_lay.addWidget(chk)
    chk_lay.addStretch(1)
    lay.addWidget(chk_cell)

    range_host = _AxisRangeHost(range_floor, line1)
    range_host.setObjectName("axisRangeHost")
    range_host.setAttribute(Qt.WA_StyledBackground, True)
    range_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    stack = QStackedLayout(range_host)
    stack.setContentsMargins(0, 0, 0, 0)
    stack.setSpacing(0)

    summary_page = QWidget(range_host)
    summary_page.setObjectName("axisRangeSummaryPage")
    summary_page.setAttribute(Qt.WA_StyledBackground, False)
    summary_lay = QHBoxLayout(summary_page)
    summary_lay.setContentsMargins(0, 0, 0, 0)
    summary_lay.setSpacing(0)
    summary_label.setProperty("axisSummary", True)
    summary_label.setMinimumWidth(0)
    summary_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    summary_lay.addWidget(summary_label, 1)

    manual_page = QWidget(range_host)
    manual_page.setObjectName("axisManualRangePage")
    manual_page.setAttribute(Qt.WA_StyledBackground, False)
    manual_lay = QHBoxLayout(manual_page)
    manual_lay.setContentsMargins(0, 0, 0, 0)
    manual_lay.setSpacing(manual_gap)
    for sp in (spin_min, spin_max):
        sp.setButtonSymbols(QAbstractSpinBox.NoButtons)
        sp.setMinimumWidth(spin_floor)
        sp.setMaximumWidth(120)
        sp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    manual_lay.addWidget(spin_min, 1)
    arrow = QLabel('→')
    arrow.setAlignment(Qt.AlignCenter)
    arrow.setFixedWidth(arrow_width)
    manual_lay.addWidget(arrow)
    manual_lay.addWidget(spin_max, 1)
    QWidget.setTabOrder(spin_min, spin_max)
    reserved_height = max(spin_min.sizeHint().height(), spin_max.sizeHint().height())
    if unit_widget is not None:
        reserved_height = max(reserved_height, unit_widget.sizeHint().height())
    range_host.set_reserved_height(reserved_height)
    summary_page.setMinimumHeight(reserved_height)
    manual_page.setMinimumHeight(reserved_height)
    stack.addWidget(summary_page)
    stack.addWidget(manual_page)
    lay.addWidget(range_host, 1)
    outer.addWidget(line1)

    if unit_widget is not None:
        unit_line = QWidget(container)
        unit_line.setObjectName("axisUnitLine")
        unit_line.setAttribute(Qt.WA_StyledBackground, True)
        unit_lay = QHBoxLayout(unit_line)
        unit_lay.setContentsMargins(0, 0, 0, 0)
        unit_lay.setSpacing(0)
        unit_lay.addStretch(1)
        unit_widget.setMinimumWidth(unit_width)
        unit_widget.setMaximumWidth(unit_width)
        unit_lay.addWidget(unit_widget)
        outer.addWidget(unit_line)

    return container, dict(
        label=lbl,
        checkbox=chk,
        range_host=range_host,
        stack=stack,
        summary_page=summary_page,
        manual_page=manual_page,
        summary=summary_label,
        spin_min=spin_min,
        arrow=arrow,
        spin_max=spin_max,
        unit=unit_widget,
    )


def _build_axis_header():
    """Column header row for the 坐标轴设置 grid: 自动 / 最小 / 最大.

    Mirrors the per-axis row column widths (_AXIS_* constants) so the
    headers sit exactly above the checkbox and the two range editors.
    """
    row = QWidget()
    row.setObjectName("axisHeaderRow")
    row.setAttribute(Qt.WA_StyledBackground, True)
    row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(_AXIS_ROW_GAP)

    lay.addSpacing(_AXIS_LABEL_W)

    auto_hdr = QLabel("自动")
    auto_hdr.setProperty("axisHeader", True)
    auto_hdr.setAlignment(Qt.AlignCenter)
    auto_hdr.setFixedWidth(_AXIS_CHK_W)
    lay.addWidget(auto_hdr)

    rng = QWidget(row)
    rng.setObjectName("axisHeaderRange")
    rng.setAttribute(Qt.WA_StyledBackground, True)
    rng.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    rl = QHBoxLayout(rng)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.setSpacing(_AXIS_MANUAL_GAP)
    min_hdr = QLabel("最小")
    min_hdr.setProperty("axisHeader", True)
    min_hdr.setAlignment(Qt.AlignCenter)
    rl.addWidget(min_hdr, 1)
    rl.addSpacing(_AXIS_ARROW_W)
    max_hdr = QLabel("最大")
    max_hdr.setProperty("axisHeader", True)
    max_hdr.setAlignment(Qt.AlignCenter)
    rl.addWidget(max_hdr, 1)
    lay.addWidget(rng, 1)
    return row


def _make_axis_settings_group(
    owner,
    *,
    x_label,
    x_unit,
    x_default_min,
    x_default_max,
    y_label,
    y_unit,
    y_default_min,
    y_default_max,
    z_default_floor=-30.0,
    z_default_ceiling=0.0,
    z_default_auto=False,
    x_default_auto=True,
    y_default_auto=True,
    x_auto_summary="全时段",
    y_auto_summary="自动范围",
    z_auto_summary="自动色阶",
    include_z=True,
):
    """Build the "坐标轴设置" QGroupBox and attach widgets to ``owner``.

    Attaches the following attributes on ``owner``::

        chk_x_auto, spin_x_min, spin_x_max
        chk_y_auto, spin_y_min, spin_y_max
        chk_z_auto, spin_z_floor, spin_z_ceiling  (when include_z=True)
        combo_amp_unit  (the dB ↔ Linear dropdown on the Z row, when present)

    Wires::

        chk_*_auto.toggled → owner._sync_axis_enabled
        combo_amp_unit.currentTextChanged → owner._on_amp_unit_changed
        (when include_z=True)

    Initial values (setValue / setCurrentIndex) are applied with
    blockSignals() so the wired slots do NOT fire during construction —
    otherwise ``_on_amp_unit_changed`` would force ``chk_z_auto`` ON
    regardless of the ``z_default_auto`` argument the caller passed.

    The caller is responsible for declaring ``_sync_axis_enabled`` and
    ``_on_amp_unit_changed`` as methods on its own class — both are
    trivially identical across OrderContextual and FFTTimeContextual,
    but staying instance-method keeps overrideability and matches the
    surface assumed by the Wave 3 OrderContextual tests.
    """
    g = QGroupBox("坐标轴设置")
    # 2026-06-05 narrow-pane: zero the group's right padding (base Inspector
    # QGroupBox carries 2px) so the now-fluid range editors reach the same
    # right edge as the card's form fields (色图 etc.) instead of stopping
    # 2px short. Scoped by objectName so other groups keep their padding.
    g.setObjectName("axisSettingsGroup")
    lay = QVBoxLayout(g)
    lay.setContentsMargins(8, 8, 0, 8)
    lay.setSpacing(4)
    owner._axis_row_parts = {}

    # ---- column header: 自动 / 最小 / 最大 (labels the checkbox + editors
    # once instead of repeating "自动" on all three rows) ----
    lay.addWidget(_build_axis_header())

    # ---- X row ----
    owner.chk_x_auto = QCheckBox()
    owner.spin_x_min = _no_buttons(CompactDoubleSpinBox())
    owner.spin_x_min.setRange(0.0, 1e9)
    owner.spin_x_min.setDecimals(2)
    if x_unit:
        owner.spin_x_min.setSuffix(f" {x_unit}")
    owner.spin_x_max = _no_buttons(CompactDoubleSpinBox())
    owner.spin_x_max.setRange(0.0, 1e9)
    owner.spin_x_max.setDecimals(2)
    if x_unit:
        owner.spin_x_max.setSuffix(f" {x_unit}")
    # Block signals while seeding initial state — see docstring.
    for w, v in (
        (owner.chk_x_auto, x_default_auto),
        (owner.spin_x_min, x_default_min),
        (owner.spin_x_max, x_default_max),
    ):
        w.blockSignals(True)
    owner.chk_x_auto.setChecked(bool(x_default_auto))
    owner.spin_x_min.setValue(float(x_default_min))
    owner.spin_x_max.setValue(float(x_default_max))
    for w in (owner.chk_x_auto, owner.spin_x_min, owner.spin_x_max):
        w.blockSignals(False)
    owner.lbl_x_summary = QLabel(x_auto_summary)
    x_row, x_parts = _build_axis_row(
        x_label, owner.chk_x_auto,
        owner.spin_x_min, owner.spin_x_max, None, owner.lbl_x_summary,
    )
    owner._axis_row_parts['x'] = x_parts
    owner.axis_x_range_host = x_parts['range_host']
    lay.addWidget(x_row)

    # ---- Y row ----
    owner.chk_y_auto = QCheckBox()
    owner.spin_y_min = _no_buttons(CompactDoubleSpinBox())
    owner.spin_y_min.setRange(0.0, 1e9)
    owner.spin_y_min.setDecimals(2)
    if y_unit:
        owner.spin_y_min.setSuffix(f" {y_unit}")
    owner.spin_y_max = _no_buttons(CompactDoubleSpinBox())
    owner.spin_y_max.setRange(0.0, 1e9)
    owner.spin_y_max.setDecimals(2)
    if y_unit:
        owner.spin_y_max.setSuffix(f" {y_unit}")
    for w in (owner.chk_y_auto, owner.spin_y_min, owner.spin_y_max):
        w.blockSignals(True)
    owner.chk_y_auto.setChecked(bool(y_default_auto))
    owner.spin_y_min.setValue(float(y_default_min))
    owner.spin_y_max.setValue(float(y_default_max))
    for w in (owner.chk_y_auto, owner.spin_y_min, owner.spin_y_max):
        w.blockSignals(False)
    owner.lbl_y_summary = QLabel(y_auto_summary)
    y_row, y_parts = _build_axis_row(
        y_label, owner.chk_y_auto,
        owner.spin_y_min, owner.spin_y_max, None, owner.lbl_y_summary,
    )
    owner._axis_row_parts['y'] = y_parts
    owner.axis_y_range_host = y_parts['range_host']
    lay.addWidget(y_row)

    # ---- Z (color scale) row ----
    if include_z:
        owner.chk_z_auto = QCheckBox()
        owner.spin_z_floor = _no_buttons(CompactDoubleSpinBox())
        owner.spin_z_floor.setRange(-200.0, 200.0)
        owner.spin_z_floor.setDecimals(2)
        owner.spin_z_ceiling = _no_buttons(CompactDoubleSpinBox())
        owner.spin_z_ceiling.setRange(-200.0, 200.0)
        owner.spin_z_ceiling.setDecimals(2)
        owner.combo_amp_unit = QComboBox()
        owner.combo_amp_unit.addItems(['dB', 'Linear'])
        for w in (
            owner.chk_z_auto, owner.spin_z_floor,
            owner.spin_z_ceiling, owner.combo_amp_unit,
        ):
            w.blockSignals(True)
        owner.chk_z_auto.setChecked(bool(z_default_auto))
        owner.spin_z_floor.setValue(float(z_default_floor))
        owner.spin_z_ceiling.setValue(float(z_default_ceiling))
        owner.combo_amp_unit.setCurrentIndex(0)
        for w in (
            owner.chk_z_auto, owner.spin_z_floor,
            owner.spin_z_ceiling, owner.combo_amp_unit,
        ):
            w.blockSignals(False)
        owner.lbl_z_summary = QLabel(z_auto_summary)
        z_row, z_parts = _build_axis_row(
            "色阶:", owner.chk_z_auto,
            owner.spin_z_floor, owner.spin_z_ceiling,
            owner.combo_amp_unit, owner.lbl_z_summary,
        )
        owner._axis_row_parts['z'] = z_parts
        owner.axis_z_range_host = z_parts['range_host']
        lay.addWidget(z_row)

    # ---- wire signals AFTER seeding initial values ----
    owner.chk_x_auto.toggled.connect(owner._sync_axis_enabled)
    owner.chk_y_auto.toggled.connect(owner._sync_axis_enabled)
    if include_z:
        owner.chk_z_auto.toggled.connect(owner._sync_axis_enabled)
        owner.combo_amp_unit.currentTextChanged.connect(owner._on_amp_unit_changed)
    return g
