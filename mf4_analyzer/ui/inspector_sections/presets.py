"""Preset hover card and preset bar widgets."""
import copy
import json
import logging
from functools import partial
from html import escape

from PyQt5 import sip
from PyQt5.QtCore import QPoint, QRectF, QSettings, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...ui_kit.dialog_geometry import (
    FrameInsets,
    IntRect,
    SCREEN_MARGIN,
    apply_plan,
    client_budget,
    plan_geometry,
    resolve_available_rect,
)
from ...ui_kit.menus import apply_rounded_menu_chrome
from ...ui_kit.message_box_buttons import fit_message_box_buttons_to_text
from ..analysis_preset_slots import notify_slot_changed, preset_slot_bus
from .. import hints
from ._helpers import (
    BUILTIN_PRESET_BLURB,
    _PRESET_KEY_TO_SLOT,
    _preset_settings,
    _preset_value_text,
)
from .preset_state import (
    apply_keep_ranges,
    apply_preset_ranges,
    baseline_source_status,
    build_preset_baseline,
    comparable_params_match,
    diff_preset_state,
    incompatible_amplitude_axes,
    infer_preset_baseline,
    manual_axis_conflicts,
    resolve_preset_target,
    validate_preset_baseline,
)

_AXIS_LABELS = {
    "fft": {"x": "频率 X", "y": "幅值 Y"},
    "fft_time": {"x": "时间 X", "y": "频率 Y", "z": "色阶 Z"},
    "order": {"x": "时间 X", "y": "阶次 Y", "z": "色阶 Z"},
}
_DIFF_PURPLE = "#a28acb"
_DIFF_AMBER = "#e8ae48"
_DIFF_DOT_PX = 7
_DIFF_DOT_GAP = 4
logger = logging.getLogger(__name__)


class _PresetDiffDot(QWidget):
    """Painted circle. QSS ``border-radius`` on a 7px QLabel stays square."""

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self.setObjectName("presetDiffDot")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAutoFillBackground(False)
        self.setFixedSize(_DIFF_DOT_PX, _DIFF_DOT_PX)
        self._color = QColor(color)
        self.hide()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))


class _PresetHoverCard(QFrame):
    """Custom preset hover card.

    Qt's native QToolTip supports only a tiny HTML subset, so chip-style
    parameter summaries must be rendered as real widgets.
    """

    WIDTH = 380

    def __init__(self):
        super().__init__(
            None,
            Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
            | Qt.WindowTransparentForInput,
        )
        self.setObjectName("presetHoverCard")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # This summary has no interactive controls. Even if a tiny screen
        # forces overlap, it must not steal hover from its trigger button.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowOpacity(1.0)
        self.setFixedWidth(self.WIDTH)
        self._chip_rows = []
        self._overflow = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 14)
        outer.setSpacing(0)
        self._panel = QFrame(self)
        self._panel.setObjectName("presetHoverPanel")
        self._panel.setAttribute(Qt.WA_StyledBackground, True)
        outer.addWidget(self._panel)
        self._root = QVBoxLayout(self._panel)
        self._root.setContentsMargins(12, 11, 12, 10)
        self._root.setSpacing(8)
        # NOTE: no QGraphicsDropShadowEffect here. QGraphicsEffect ignores the
        # screen devicePixelRatio (QTBUG-65035 and friends), so on fractional
        # display scaling (125% / 150%, common on Windows) it renders the whole
        # panel — text included — to a 1x offscreen pixmap and upscales it. That
        # blurs the card and visually merges adjacent lines (title + subtitle
        # piling on top of each other). The card's elevation now comes from the
        # panel border alone, which is DPR-correct.
        self.setStyleSheet("""
            QFrame#presetHoverCard {
                border: none;
                background: transparent;
            }
            QFrame#presetHoverPanel {
                border: 1px solid rgba(160, 177, 200, 245);
                border-radius: 8px;
                background-color: #ffffff;
            }
            QFrame#presetHoverSection {
                border: 1px solid #d5dfeb;
                border-radius: 7px;
                background-color: rgba(248, 251, 255, 232);
            }
            QLabel#presetHoverTitle {
                color: #172033;
                font-size: 15px;
                font-weight: 800;
                background: transparent;
            }
            QLabel#presetHoverSub,
            QLabel#presetHoverFooter {
                color: #647086;
                font-size: 12px;
                background: transparent;
            }
            QLabel#presetHoverBadge {
                padding: 3px 8px;
                border-radius: 11px;
                color: #047857;
                background-color: #e9f9f1;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#presetHoverSectionTitle {
                color: #1f3b63;
                font-size: 12px;
                font-weight: 800;
                background: transparent;
            }
            QLabel#presetChip {
                padding: 3px 7px;
                border: 1px solid #d5dfeb;
                border-radius: 10px;
                background-color: #f1f6fc;
                font-size: 12px;
            }
            QLabel#presetChip[diff="param"] {
                border-width: 1px;
                border-style: solid;
                border-color: #a28acb;
            }
            QLabel#presetChip[diff="axis"] {
                border-width: 1px;
                border-style: solid;
                border-color: #e8ae48;
            }
        """)

    def set_summary(self, *, name, params, kind, label_map, current_params=None,
                    builtin=False, blurb='', status_note='', owned_only=True):
        self._clear()
        self._chip_rows = []
        self.setFixedWidth(self.WIDTH)
        self.setMaximumHeight(16777215)
        params = params if isinstance(params, dict) else {}
        current_params = current_params if isinstance(current_params, dict) else {}

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)
        title = QLabel(str(name), self._panel)
        title.setObjectName("presetHoverTitle")
        title.setWordWrap(True)
        title_box.addWidget(title)
        sub_text = blurb if (builtin and blurb) else f"已保存参数快照 · 来源：{self._kind_label(kind)}"
        sub = QLabel(sub_text, self._panel)
        sub.setObjectName("presetHoverSub")
        sub.setWordWrap(True)
        title_box.addWidget(sub)
        head.addLayout(title_box, 1)
        badge = QLabel("内置" if builtin else "已保存", self._panel)
        badge.setObjectName("presetHoverBadge")
        badge.setAlignment(Qt.AlignCenter)
        head.addWidget(badge, 0, Qt.AlignTop)
        self._root.addLayout(head)

        analysis = self._analysis_specs(params, kind, label_map)
        if analysis:
            self._root.addWidget(self._section("分析参数", analysis))

        axes = self._axis_specs(params)
        if axes:
            self._root.addWidget(self._section("坐标轴快照", axes))

        status = self._status_specs(
            params, current_params, kind, owned_only=owned_only,
        )
        if status_note:
            note = QLabel(status_note, self._panel)
            note.setObjectName("presetHoverSub")
            note.setWordWrap(True)
            self._root.addWidget(note)
        if status:
            self._root.addWidget(self._section("状态判断", status))

        self._overflow = QLabel("", self._panel)
        self._overflow.setObjectName("presetHoverOverflow")
        self._overflow.setWordWrap(True)
        self._overflow.hide()
        self._root.addWidget(self._overflow)

        footer = QLabel("左键加载 · 右键保存/重命名/重置或清空        不保存信号与 Fs", self._panel)
        footer.setObjectName("presetHoverFooter")
        footer.setWordWrap(True)
        self._root.addWidget(footer)
        self.adjustSize()

    def _clear(self):
        while self._root.count():
            item = self._root.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())
        layout.deleteLater()

    def _section(self, title, chips):
        frame = QFrame(self._panel)
        frame.setObjectName("presetHoverSection")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(9, 8, 9, 8)
        lay.setSpacing(6)
        lbl = QLabel(title, frame)
        lbl.setObjectName("presetHoverSectionTitle")
        lay.addWidget(lbl)
        for row_specs in self._rows(chips):
            row_host = QWidget(frame)
            row = QHBoxLayout(row_host)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(5)
            for spec in row_specs:
                label, value, tone = spec[0], spec[1], spec[2]
                row.addWidget(self._chip(label, value, tone), 0)
            row.addStretch(1)
            lay.addWidget(row_host)
            self._chip_rows.append((row_host, len(row_specs)))
        return frame

    def _chip(self, label, value, tone=False):
        chip = QLabel(self._panel)
        chip.setObjectName("presetChip")
        if tone == "param":
            chip.setProperty("diff", "param")
        elif tone == "axis":
            chip.setProperty("diff", "axis")
        chip.style().unpolish(chip)
        chip.style().polish(chip)
        chip.setTextFormat(Qt.RichText)
        chip.setText(
            f'<span style="color:#61708a;font-weight:600;">{escape(str(label))}</span> '
            f'<span style="color:#0b73e7;font-weight:800;">{escape(str(value))}</span>'
        )
        return chip

    def _rows(self, chips):
        rows = []
        row = []
        used = 0
        for spec in chips:
            label, value, _warn = spec
            weight = len(str(label)) + len(str(value)) + 3
            if row and used + weight > 28:
                rows.append(row)
                row = []
                used = 0
            row.append(spec)
            used += weight
        if row:
            rows.append(row)
        return rows

    def _analysis_specs(self, params, kind, label_map):
        axis_keys = {
            'x_auto', 'x_min', 'x_max', 'y_auto', 'y_min', 'y_max',
            'z_auto', 'z_floor', 'z_ceiling',
        }
        if kind == 'fft':
            keys = (
                'window', 'nfft', 'nfft_mode', 't_win_s', 'overlap',
                'avg_mode', 'avg_overlap', 'amp_y', 'db_reference_mode',
                'db_reference',
            )
        elif kind == 'fft_time':
            keys = (
                # 不列 ``cmap``：色图不由预设决定（面板恒定发 _FIXED_CMAP，
                # 应用预设时显式跳过），列出来只会让用户以为改了预设就能换色图。
                'window', 'nfft', 'nfft_mode', 't_win_s', 'overlap',
                'amplitude_mode', 'db_reference_mode', 'db_reference',
            )
        elif kind == 'order':
            keys = (
                'max_order', 'order_res', 'time_res', 'window', 'nfft',
                'nfft_mode', 'samples_per_rev', 'amplitude_mode',
                'rpm_factor', 'rpm_mode', 'manual_rpm',
                'db_reference_mode', 'db_reference',
            )
        else:
            keys = tuple(k for k in params if k not in axis_keys)
        specs = []
        for key in keys:
            if key in params:
                specs.append((label_map.get(key, key), _preset_value_text(params[key]), False))
        return specs

    def _axis_specs(self, params):
        specs = []
        for axis in ('x', 'y', 'z'):
            auto_key = f'{axis}_auto'
            min_key = f'{axis}_min' if axis != 'z' else 'z_floor'
            max_key = f'{axis}_max' if axis != 'z' else 'z_ceiling'
            if auto_key not in params:
                continue
            if bool(params.get(auto_key)):
                value = "自动"
            elif min_key in params and max_key in params:
                value = (
                    f"{_preset_value_text(params[min_key])} → "
                    f"{_preset_value_text(params[max_key])}"
                )
            else:
                value = "手动"
            specs.append((axis.upper(), value, False))
        return specs

    def _status_specs(self, params, current_params, kind, *, owned_only=True):
        specs = []
        if current_params:
            diff = diff_preset_state(
                kind, params, current_params, owned_only=owned_only,
            )
            param_tone = "param" if diff.params_differ else False
            specs.append((
                "参数", "有差异" if diff.params_differ else "一致", param_tone,
            ))
            if kind != "frf":
                axis_tone = "axis" if diff.axes_differ else False
                specs.append((
                    "坐标轴",
                    "有差异" if diff.axes_differ else "一致",
                    axis_tone,
                ))
        specs.append(("信号/Fs", "不切换", False))
        return specs

    def _kind_label(self, kind):
        return {
            'fft': 'FFT',
            'fft_time': 'FFT vs Time',
            'frf': '频响（FRF）',
            'order': 'Order Time',
        }.get(kind, kind)

    def _fit_to_budget(self, available):
        """Cap width/height to the work area; summarize chips that no longer fit."""
        work = available if isinstance(available, IntRect) else IntRect(
            int(available.x()), int(available.y()),
            int(available.width()), int(available.height()),
        )
        budget = client_budget(work, FrameInsets(), SCREEN_MARGIN)
        width = min(self.WIDTH, max(1, budget.width))
        self.setFixedWidth(width)
        if self.layout() is not None:
            self.layout().activate()
        self.adjustSize()
        omitted = 0
        while self.sizeHint().height() > budget.height and self._chip_rows:
            host, count = self._chip_rows.pop()
            host.hide()
            omitted += count
            if self.layout() is not None:
                self.layout().activate()
            self.adjustSize()
        if omitted and self._overflow is not None:
            self._overflow.setText(f"另有 {omitted} 项")
            self._overflow.show()
            if self.layout() is not None:
                self.layout().activate()
            self.adjustSize()
            while self.sizeHint().height() > budget.height and self._chip_rows:
                host, count = self._chip_rows.pop()
                host.hide()
                omitted += count
                self._overflow.setText(f"另有 {omitted} 项")
                if self.layout() is not None:
                    self.layout().activate()
                self.adjustSize()
        target_h = min(max(1, self.sizeHint().height()), max(1, budget.height))
        self.setMaximumHeight(max(1, budget.height))
        self.resize(width, target_h)


class _PresetLoadButton(QPushButton):
    """Preset button that owns its hover lifecycle without an event filter."""

    def __init__(self, slot, parent=None):
        super().__init__(parent)
        self._slot = slot

    def _preset_bar(self):
        parent = self.parentWidget()
        return parent if isinstance(parent, PresetBar) else None

    def enterEvent(self, event):
        bar = self._preset_bar()
        if bar is not None and bar.isVisible():
            bar._show_hover(self._slot)
        super().enterEvent(event)

    def leaveEvent(self, event):
        bar = self._preset_bar()
        if bar is not None:
            bar._hide_hover()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        bar = self._preset_bar()
        if bar is not None:
            bar._hide_hover()
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        bar = self._preset_bar()
        if bar is not None and bar.isVisible():
            bar._position_recommend_badge(self._slot)
            bar._position_diff_dots(self._slot)
        super().resizeEvent(event)


class PresetBar(QWidget):
    """Preset bar with built-in slots and optional user-owned custom slots.

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
      no user override exists (for signal-type presets this reads as 频率 /
      均衡 / 时间 out of the box).
    - Left-click loads either the user override (if any) or the builtin.
    - The right-click menu adds "重置此槽为内置" (drop the override) and
      "恢复面板默认参数" (apply construction defaults and clear the baseline).

    Storage key in builtin mode: ``{kind}/preset_override/{slot}`` (so the
    namespace is independent from the legacy ``{kind}/preset/{slot}`` used
    by the FFT / Order bars).

    Baseline projection
    -------------------
    The highlighted slot is the current adjustment baseline, not a reverse
    match of live parameters onto a slot name. :meth:`sync_match` projects
    that baseline (blue highlight plus difference dots) after parameter
    edits and programmatic ``apply_params`` restores. Unmatched states do
    not light 自定义. Owners still call it after every change they suppress
    with an ``_applying_preset`` guard.
    """

    SLOTS = (1, 2, 3)
    NAME_MAX_LEN = 12
    acknowledged = pyqtSignal(str, str)  # level, message
    preset_committed = pyqtSignal(object)  # successful baseline, or None

    def __init__(
        self, kind, collect_fn, apply_fn, parent=None, builtin_defaults=None,
        default_params=None, custom_slots=None,
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
        default_params : dict | None
            Construction-time panel defaults restored by the explicit
            「恢复面板默认参数」 menu action. Distinct from resetting a
            builtin slot's QSettings override.
        custom_slots : dict[int, str] | None
            Additional user-owned slots. An empty custom slot saves the current
            parameters on left-click; unlike a builtin slot it never receives a
            unit recommendation and its right-click menu offers ``清空``.
        """
        super().__init__(parent)
        self.setObjectName("inspectorPresetBar")
        self._kind = kind
        self._collect = collect_fn
        self._apply = apply_fn
        self._builtins = builtin_defaults  # None => legacy mode
        self._custom_slots = {
            int(slot): str(name)
            for slot, name in (custom_slots or {}).items()
            if int(slot) not in self.SLOTS
        }
        self._slots = self.SLOTS + tuple(self._custom_slots)
        self._default_params = (
            dict(default_params) if isinstance(default_params, dict) else None
        )
        self._hover_card = _PresetHoverCard()
        self._hover_card.destroyed.connect(self._on_hover_card_destroyed)
        self._hover_slot = None
        # Slot currently flagged as the unit-推荐 highlight (None => none).
        self._recommended_slot = None
        # Display-only unit cited on the recommended button tooltip.
        self._recommended_unit = None
        # Slot currently projected from the View baseline (None = no baseline
        # or the source slot is empty). Not a reverse-match of live params.
        self._selected_slot = None
        self._baseline = None
        self._loaded_slot_payload = None
        self._live_diff = diff_preset_state(self._kind, {}, {})
        self._transaction_open = False
        # slot -> effective payload dict (or None), lazily filled by
        # _slot_payloads(). project_baseline runs on every keystroke-level
        # parameter edit, so it must not re-read four QSettings keys each time.
        self._payload_cache = None

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._load_btns = {}
        self._recommend_badges = {}
        for n in self._slots:
            ld = _PresetLoadButton(n, self)
            ld.setProperty("role", "preset-load")
            ld.setProperty("filled", "false")
            # Four equal-width slots must not raise the Inspector's minimum
            # width above a narrow pane. The layout still gives each slot its
            # equal stretch at normal widths; this only allows compaction.
            ld.setMinimumWidth(0)
            ld.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            ld.setContextMenuPolicy(Qt.CustomContextMenu)
            ld.clicked.connect(partial(self._on_load_clicked, n))
            ld.customContextMenuRequested.connect(partial(self._on_slot_menu, n))
            row.addWidget(ld, 1)
            self._load_btns[n] = ld
            badge = QLabel("荐", ld)
            badge.setObjectName("presetRecommendBadge")
            badge.setAlignment(Qt.AlignCenter)
            badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            badge.setFixedSize(14, 14)
            badge.hide()
            self._recommend_badges[n] = badge
        self._param_dots = {}
        self._axis_dots = {}
        for n, ld in self._load_btns.items():
            self._param_dots[n] = self._make_diff_dot(ld, _DIFF_PURPLE)
            self._axis_dots[n] = self._make_diff_dot(ld, _DIFF_AMBER)
        self._refresh_states()
        preset_slot_bus().changed.connect(self._on_shared_slot_changed)

    # ---- naming helpers ----
    def _default_name(self, slot):
        if slot in self._custom_slots:
            return self._custom_slots[slot]
        if self._builtins and slot in self._builtins:
            entry = self._builtins[slot]
            if isinstance(entry, dict) and entry.get('display_name'):
                return str(entry['display_name'])
        return f"配置 {slot}"

    # ---- persistence helpers ----
    def _key(self, slot):
        if self._is_builtin_slot(slot):
            return f"{self._kind}/preset_override/{slot}"
        if self._builtins is not None and slot in self._custom_slots:
            return f"{self._kind}/preset_custom/{slot}"
        return f"{self._kind}/preset/{slot}"

    def _is_builtin_slot(self, slot):
        return self._builtins is not None and self._builtin_params(slot) is not None

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
        self._invalidate_payload_cache()
        notify_slot_changed(self._kind, slot)

    def _delete(self, slot):
        _preset_settings().remove(self._key(slot))
        self._invalidate_payload_cache()
        notify_slot_changed(self._kind, slot)

    # ---- baseline projection ----------------------------------------------
    def _invalidate_payload_cache(self):
        self._payload_cache = None

    def _on_shared_slot_changed(self, kind, _slot):
        """Drop the cache when ANY bar of this kind rewrites a slot.

        Two bars of the same kind can be alive at once (the Inspector's and a
        second one in a detached window), and the batch sheet reads the same
        keys. The bus is the existing cross-widget notification for that, so
        the cache follows it rather than inventing a second channel.
        """
        if str(kind) == self._kind:
            self._invalidate_payload_cache()
            if getattr(self, "_load_btns", None):
                self.sync_match()

    def _on_load_clicked(self, slot, _checked=False):
        self._on_left_click(slot)

    def _on_slot_menu(self, slot, pos):
        self._show_menu(slot, pos)

    def _make_diff_dot(self, parent, color):
        return _PresetDiffDot(color, parent)

    def _slot_payloads(self):
        """Return ``{slot: effective params or None}`` for every slot.

        "Effective" is the same resolution order the left-click load uses:
        the QSettings override wins, otherwise the builtin patch, otherwise
        nothing (an empty custom slot describes no state at all).
        """
        if self._payload_cache is None:
            payloads = {}
            for slot in self._slots:
                entry = self._read(slot)
                payloads[slot] = (
                    entry[1] if entry is not None else self._builtin_params(slot)
                )
            self._payload_cache = payloads
        return self._payload_cache

    def _effective_payload(self, slot):
        return self._slot_payloads().get(slot)

    def _slot_display_name(self, slot):
        entry = self._read(slot)
        if entry is not None:
            return entry[0]
        return self._default_name(slot)

    def _collect_safe(self):
        """Presentation-only collect. Never use an empty result as a commit."""
        try:
            current = self._collect()
        except Exception:
            return {}
        return current if isinstance(current, dict) else {}

    def _slot_is_available(self, slot):
        if slot not in self._slots:
            return False
        if self._is_builtin_slot(slot):
            return True
        return self._read(slot) is not None

    def _slot_source_changed(self, slot):
        return bool(self._baseline_source_note(slot))

    def _baseline_source_note(self, slot):
        baseline = self._baseline
        if not isinstance(baseline, dict) or baseline.get("slot") != slot:
            return ""
        return baseline_source_status(
            baseline,
            kind=self._kind,
            slot_available=self._slot_is_available(slot),
            current_payload=self._effective_payload(slot),
            current_name=self._slot_display_name(slot),
        )

    def baseline(self):
        return copy.deepcopy(self._baseline) if isinstance(self._baseline, dict) else None

    def set_baseline(self, value):
        """Install a View baseline and project highlight / dots from it."""
        validated = validate_preset_baseline(value, expected_kind=self._kind)
        self._baseline = validated
        if validated is None:
            self._loaded_slot_payload = None
        elif validated.get("version") == 2 and isinstance(
            validated.get("source_payload"), dict
        ):
            self._loaded_slot_payload = copy.deepcopy(validated["source_payload"])
        else:
            # v1 / unknown: do not backfill from the current global slot.
            self._loaded_slot_payload = None
        self.sync_match()

    def infer_baseline_from_current(self):
        """Return a baseline only for a complete comparable match, or None."""
        current = self._collect_safe()
        if not current:
            return None
        names = {slot: self._slot_display_name(slot) for slot in self._slots}
        return infer_preset_baseline(
            self._kind, current, self._slot_payloads(), names,
        )

    def _matching_slot(self):
        """Return the projected baseline slot, or None when unmatched.

        Kept as a compatibility alias for tests. Unmatched states no longer
        fall through to 自定义.
        """
        if not isinstance(self._baseline, dict):
            return None
        slot = self._baseline.get("slot")
        if self._slot_is_available(slot):
            return slot
        return None

    def _custom_slot(self):
        return next(iter(self._custom_slots), None)

    def sync_match(self, *, clear_recommendation=False):
        """Project the current baseline onto highlight and difference dots.

        Call this after a user edit, a preset load, or a programmatic
        ``apply_params`` restore. It does not reverse-match live parameters
        onto another slot.

        ``clear_recommendation`` drops the unit-推荐 corner badge; user edits
        pass it (the recommendation was made for the untouched signal), while
        programmatic restores leave the badge alone.
        """
        if clear_recommendation:
            self._recommended_slot = None
            self._recommended_unit = None
        self._project_baseline()
        self._refresh_states()

    def _project_baseline(self):
        current = self._collect_safe()
        baseline = self._baseline if isinstance(self._baseline, dict) else None
        if baseline is None:
            self._selected_slot = None
            self._live_diff = diff_preset_state(self._kind, {}, current)
            return
        slot = baseline.get("slot")
        self._selected_slot = slot if self._slot_is_available(slot) else None
        self._live_diff = diff_preset_state(
            self._kind, baseline.get("params") or {}, current,
        )

    @property
    def is_transaction_open(self):
        return bool(self._transaction_open)

    def _run_user_transaction(self, work):
        """Run one user load/save. Emit ``preset_committed`` only on success."""
        self._transaction_open = True
        ok = False
        try:
            ok = bool(work())
        finally:
            self._transaction_open = False
        if ok:
            self.preset_committed.emit(self.baseline())
        return ok

    def _snapshot_collect_and_baseline(self):
        return (
            self._collect_safe() or None,
            copy.deepcopy(self._baseline),
            copy.deepcopy(self._loaded_slot_payload),
        )

    def _restore_collect_and_baseline(self, snapshot):
        before, before_baseline, before_loaded = snapshot
        if before:
            try:
                self._apply(before)
            except Exception:
                logger.exception(
                    "failed to restore preset params after apply error"
                )
        self._baseline = before_baseline
        self._loaded_slot_payload = before_loaded
        self.sync_match()

    def _commit_loaded_slot(self, slot, target_params, source_payload):
        """Commit the resolved target and the loaded slot patch, not applied."""
        if not isinstance(target_params, dict) or not target_params:
            logger.warning(
                "refusing empty preset baseline commit for kind=%s slot=%s",
                self._kind, slot,
            )
            return False
        if not isinstance(source_payload, dict) or not source_payload:
            logger.warning(
                "refusing preset baseline commit without source payload "
                "for kind=%s slot=%s",
                self._kind, slot,
            )
            return False
        name = self._slot_display_name(slot)
        built = build_preset_baseline(
            self._kind, slot, name, target_params, source_payload=source_payload,
        )
        validated = validate_preset_baseline(built, expected_kind=self._kind)
        if validated is None:
            logger.warning(
                "refusing invalid preset baseline commit for kind=%s slot=%s",
                self._kind, slot,
            )
            return False
        self._baseline = validated
        self._loaded_slot_payload = copy.deepcopy(validated["source_payload"])
        self.sync_match()
        return True

    def _clear_baseline(self):
        self._baseline = None
        self._loaded_slot_payload = None
        self._selected_slot = None
        self.sync_match()

    def _builtin_params(self, slot):
        if not self._builtins or slot not in self._builtins:
            return None
        entry = self._builtins[slot]
        if isinstance(entry, dict) and 'params' in entry:
            return entry['params']
        return None

    def _refresh_states(self):
        for n in self._slots:
            entry = self._read(n)
            btn = self._load_btns[n]
            btn.setToolTip("")
            if entry is None:
                # Empty slot. In builtin mode the slot still loads the
                # builtin, so it is enabled and shows the builtin display
                # name. In legacy mode the slot is enabled but reads as
                # "＋ 配置 N" — left-click will save current params.
                if self._is_builtin_slot(n):
                    btn.setText(self._default_name(n))
                    btn.setEnabled(True)
                    btn.setProperty("filled", "false")
                elif n in self._custom_slots:
                    btn.setText(self._default_name(n))
                    btn.setEnabled(True)
                    btn.setProperty("filled", "false")
                else:
                    btn.setText(f"＋ {self._default_name(n)}")
                    btn.setEnabled(True)
                    btn.setProperty("filled", "false")
            else:
                name, params = entry
                btn.setText(name)
                btn.setEnabled(True)
                btn.setProperty("filled", "true")
            applied = self._selected_slot == n
            recommended = self._recommended_slot == n and not applied
            btn.setProperty("recommended", "true" if recommended else "false")
            btn.setProperty("applied", "true" if applied else "false")
            if recommended and self._recommended_unit:
                btn.setToolTip(f"按单位「{self._recommended_unit}」推荐")
            self._set_recommend_badge(n, recommended)
            self._position_diff_dots(n)
            self._update_slot_accessible(n, applied)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _position_recommend_badge(self, slot):
        load_btns = getattr(self, "_load_btns", None) or {}
        badges = getattr(self, "_recommend_badges", None) or {}
        btn = load_btns.get(slot)
        badge = badges.get(slot)
        if btn is None or badge is None:
            return
        badge.move(max(0, btn.width() - badge.width() - 4), 2)

    def _position_diff_dots(self, slot):
        load_btns = getattr(self, "_load_btns", None) or {}
        param_dots = getattr(self, "_param_dots", None) or {}
        axis_dots = getattr(self, "_axis_dots", None) or {}
        btn = load_btns.get(slot)
        param = param_dots.get(slot)
        axis = axis_dots.get(slot)
        if btn is None or param is None or axis is None:
            return
        diff = getattr(self, "_live_diff", None)
        show_param = (
            self._selected_slot == slot
            and diff is not None
            and diff.params_differ
        )
        show_axis = (
            self._selected_slot == slot
            and self._kind != "frf"
            and diff is not None
            and diff.axes_differ
        )
        param.setVisible(show_param)
        axis.setVisible(show_axis)
        y = 4
        right = max(_DIFF_DOT_PX, btn.width() - 4)
        if show_param and show_axis:
            axis.move(right - _DIFF_DOT_PX, y)
            param.move(right - (2 * _DIFF_DOT_PX) - _DIFF_DOT_GAP, y)
        elif show_axis:
            axis.move(right - _DIFF_DOT_PX, y)
        elif show_param:
            param.move(right - _DIFF_DOT_PX, y)
        param.raise_()
        axis.raise_()

    def _update_slot_accessible(self, slot, applied):
        btn = self._load_btns.get(slot)
        if btn is None:
            return
        name = btn.text()
        btn.setAccessibleName(name)
        parts = []
        if applied:
            parts.append(f"当前预设基准 {name}")
        if applied and getattr(self, "_live_diff", None) is not None:
            if self._live_diff.params_differ:
                parts.append("分析参数有差异")
            if self._kind != "frf" and self._live_diff.axes_differ:
                parts.append("坐标有差异")
        note = self._baseline_source_note(slot) if applied else ""
        if note:
            parts.append(note)
        btn.setAccessibleDescription("，".join(parts))

    def _set_recommend_badge(self, slot, recommended):
        """Show recommendation as a small corner badge, not as button body state."""
        badges = getattr(self, "_recommend_badges", None) or {}
        badge = badges.get(slot)
        if badge is None:
            return
        badge.setVisible(bool(recommended))
        if recommended:
            self._position_recommend_badge(slot)
            badge.raise_()

    def set_recommended(self, slot, *, unit=None):
        """Mark ``slot`` as the unit-推荐 preset (corner badge only).

        ``slot`` is 1-based to match the visible preset slots, or
        ``None`` to clear every highlight. ``unit`` is display-only and is
        cited on the recommended button tooltip; the badge itself has no
        tooltip. Manual interaction is unaffected — this is a visual hint
        only. The recommendation badge is separate from the ``applied``
        property that marks the current baseline. The baseline slot hides
        the badge so it does not cover difference dots.
        """
        if slot is not None and slot not in self._slots:
            slot = None
        if self._builtins is not None and slot is not None and not self._is_builtin_slot(slot):
            slot = None
        self._recommended_slot = slot
        self._recommended_unit = None if slot is None else unit
        self._refresh_states()

    def set_custom_active(self):
        """Retired unnamed-state sink. Custom is a saveable slot, not a dump."""
        return

    def hideEvent(self, event):
        self._hide_hover()
        super().hideEvent(event)

    def _on_hover_card_destroyed(self, _destroyed_card=None):
        """Drop the Python wrapper when Qt tears down the popup window."""
        self._hover_card = None
        self._hover_slot = None

    def _live_hover_card(self):
        """Return the cached card only while its C++ object still exists."""
        card = getattr(self, "_hover_card", None)
        if card is None:
            return None
        if sip.isdeleted(card):
            self._on_hover_card_destroyed()
            return None
        return card

    def _show_hover(self, slot):
        baseline = self._baseline if isinstance(self._baseline, dict) else None
        is_baseline = baseline is not None and baseline.get("slot") == slot
        status_note = self._baseline_source_note(slot) if is_baseline else ""
        entry = self._read(slot)
        builtin = False
        if entry is None:
            params = self._builtin_params(slot)
            if params is None:
                if is_baseline:
                    name = baseline.get("display_name") or self._default_name(slot)
                    params = baseline.get("params") or {}
                    if not status_note:
                        status_note = "原基准已不可用"
                else:
                    self._hide_hover()
                    return
            else:
                name = self._default_name(slot)
                builtin = True
        else:
            name, params = entry
        try:
            current_params = self._collect()
        except Exception:
            current_params = {}
        if not isinstance(current_params, dict):
            current_params = {}
        display_params = params
        owned_only = True
        if is_baseline:
            display_params = baseline.get("params") or params
            owned_only = False
        # Resolve blurb for builtin slots: reverse-map slot index → preset key.
        _SLOT_TO_KEY = {v: k for k, v in _PRESET_KEY_TO_SLOT.items()}
        builtin_blurb = ''
        if builtin:
            builtin_entry = (
                self._builtins.get(slot, {}) if self._builtins else {}
            )
            if isinstance(builtin_entry, dict):
                builtin_blurb = str(builtin_entry.get('blurb') or '')
            if not builtin_blurb:
                builtin_blurb = BUILTIN_PRESET_BLURB.get(
                    _SLOT_TO_KEY.get(slot, ''), '')
        card = self._live_hover_card()
        if card is None:
            return
        self._hover_slot = slot
        card.set_summary(
            name=name,
            params=display_params,
            kind=self._kind,
            label_map=self._SUMMARY_LABELS,
            current_params=current_params,
            builtin=builtin,
            blurb=builtin_blurb,
            status_note=status_note,
            owned_only=owned_only,
        )
        if sip.isdeleted(card):
            self._on_hover_card_destroyed()
            return
        self._place_hover(slot, card)
        if sip.isdeleted(card):
            self._on_hover_card_destroyed()
            return
        card.show()
        card.raise_()

    def _place_hover(self, slot, card=None):
        btn = self._load_btns[slot]
        if card is None:
            card = self._live_hover_card()
        if card is None:
            return
        try:
            center = btn.mapToGlobal(btn.rect().center())
            top_left = btn.mapToGlobal(btn.rect().topLeft())
            anchor_h = max(1, btn.height())
        except RuntimeError:
            return
        available = resolve_available_rect(
            anchor_global=center, widget=card, parent=btn,
        )
        card._fit_to_budget(available)
        width = max(1, card.width())
        height = max(1, card.height())
        anchor = IntRect(
            center.x() - width // 2, top_left.y(), width, anchor_h,
        )
        plan = plan_geometry(
            available,
            (width, height),
            frame=FrameInsets(),
            margin=SCREEN_MARGIN,
            anchor=anchor,
            position="above",
            gap=10,
        )
        row = self.rect().translated(self.mapToGlobal(self.rect().topLeft()))
        if plan.frame.to_qrect().intersects(row):
            # Neither vertical side fits a full summary. Keep the whole
            # preset row accessible by trying its left and right sides.
            for x in (row.left() - width - 10, row.right() + 1 + 10):
                side = plan_geometry(
                    available, (width, height), frame=FrameInsets(),
                    margin=SCREEN_MARGIN,
                    host=IntRect(x, center.y() - height // 2, width, height),
                    position="center",
                )
                if not side.frame.to_qrect().intersects(row):
                    plan = side
                    break
        apply_plan(card, plan)

    def _hide_hover(self):
        self._hover_slot = None
        card = self._live_hover_card()
        if card is not None:
            card.hide()

    _SUMMARY_LABELS = {
        'window': '窗函数',
        'nfft': 'NFFT',
        'overlap': '重叠',
        'avg_mode': '平均模式',
        'avg_overlap': '平均重叠',
        'amp_y': 'Amplitude 轴',
        'amplitude_mode': 'Amplitude 轴',
        'remove_mean': '去均值',
        'db_reference': 'dB 参考',
        'freq_auto': '频率自动',
        'freq_min': '频率最小',
        'freq_max': '频率最大',
        'dynamic': '动态范围',
        'cmap': '色图',
        'x_auto': 'X 自动',
        'x_min': 'X 最小',
        'x_max': 'X 最大',
        'y_auto': 'Y 自动',
        'y_min': 'Y 最小',
        'y_max': 'Y 最大',
        'z_auto': 'Z 自动',
        'z_floor': 'Z 下限',
        'z_ceiling': 'Z 上限',
        'autoscale': '自适应频率',
        'remark': '标注',
        'rpm_factor': 'RPM 系数',
        'max_order': '最大阶次',
        'order_res': '阶次分辨率',
        'time_res': '时间分辨率',
        'samples_per_rev': '每转样本数',
        'estimator': '估计器',
        'periodic_window': '周期窗',
        't_win_s': '段长',
        'nfft_mode': 'NFFT 模式',
        'db_reference_mode': 'dB 参考模式',
        'rpm_mode': 'RPM 模式',
        'manual_rpm': '手动 RPM',
        'detrend': '去趋势',
        'magnitude_scale': '幅值',
        'frequency_scale': '频率',
        'phase_mode': '相位',
        'coherence_threshold': '相干阈值',
        'fade_low_coherence': '低相干淡化',
    }

    def _format_summary(self, name, params):
        if not isinstance(params, dict):
            return name
        items = []
        for k, v in params.items():
            if isinstance(v, float):
                val = f"{v:g}"
            elif isinstance(v, bool):
                val = '是' if v else '否'
            else:
                val = str(v)
            label = self._SUMMARY_LABELS.get(k, str(k))
            items.append(
                '<span style="display:inline-block;margin:2px 4px 2px 0;'
                'padding:2px 6px;border:1px solid #d5dfeb;'
                'border-radius:8px;background:#f1f6fc;">'
                f'<span style="color:#61708a;">{escape(label)}</span> '
                f'<span style="color:#0b73e7;font-weight:700;">{escape(val)}</span>'
                '</span>'
            )
        suffix = (
            "（右键可重命名 / 重置此槽为内置）"
            if self._builtins is not None
            else "（右键可重命名 / 清空）"
        )
        return (
            '<html><body style="font-family:Microsoft YaHei UI, PingFang SC, sans-serif;'
            'font-size:12px;line-height:1.55;color:#172033;">'
            f'<div style="font-weight:700;font-size:13px;margin-bottom:3px;">{escape(name)}</div>'
            '<div style="color:#647086;margin-bottom:6px;">已保存参数快照 · 不保存信号与 Fs</div>'
            f'<div>{"".join(items)}</div>'
            f'<div style="color:#647086;margin-top:6px;">{escape(suffix)}</div>'
            '</body></html>'
        )

    # ---- actions ----
    def _confirm_axis_preservation(
        self, labels, incompatible, keep_enabled=True, title=None,
    ):
        box = QMessageBox(self)
        restore = title == "恢复默认参数"
        box.setWindowTitle(title or "切换预设")
        box.setProperty("messageBoxConfirmRole", "primary")
        box.setIcon(QMessageBox.Question)
        box.setText(
            "恢复默认参数时保留手动坐标范围？"
            if restore else
            "切换预设时保留手动坐标范围？"
        )
        rest = "面板默认" if restore else "新预设"
        detail = (
            "将覆盖：" + "、".join(labels)
            + f"。\n其余参数按{rest}更新；本次选择仅对这次操作有效。"
        )
        if incompatible:
            detail += (
                "\n幅值单位或 dB 参考改变，"
                + "、".join(incompatible)
                + "将自动调整，不能沿用原数值。"
            )
        box.setInformativeText(detail)
        keep = box.addButton("保留手动范围", QMessageBox.AcceptRole)
        preset = box.addButton("使用预设范围", QMessageBox.ActionRole)
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        keep.setEnabled(bool(keep_enabled))
        box.setDefaultButton(keep if keep_enabled else preset)
        box.setEscapeButton(cancel)
        box.ensurePolished()
        for button in box.buttons():
            button.ensurePolished()
        fit_message_box_buttons_to_text(box)
        box.exec_()
        clicked = box.clickedButton()
        box.deleteLater()
        return 'keep' if clicked is keep else 'preset' if clicked is preset else 'cancel'

    def _axis_label(self, axis):
        return _AXIS_LABELS.get(self._kind, {}).get(axis, axis.upper())

    def _prepare_user_preset(self, params, *, purpose="switch", current=None):
        """Protect ranges at user entry points only, never during View restore."""
        target = dict(params)
        if current is None:
            current = self._collect_safe()
        conflict_axes = manual_axis_conflicts(self._kind, current, target)
        incompat_axes = incompatible_amplitude_axes(self._kind, current, target)
        keepable = [axis for axis in conflict_axes if axis not in incompat_axes]
        if not conflict_axes:
            return apply_preset_ranges(self._kind, current, target)
        labels = [self._axis_label(axis) for axis in conflict_axes]
        incompat_labels = [self._axis_label(axis) for axis in incompat_axes]
        choice = self._confirm_axis_preservation(
            labels,
            incompat_labels,
            keep_enabled=bool(keepable),
            title="恢复默认参数" if purpose == "restore_defaults" else None,
        )
        if choice == 'cancel':
            return None
        if choice == 'keep':
            return apply_keep_ranges(self._kind, current, target)
        return apply_preset_ranges(self._kind, current, target)

    def _is_noop_reapply(self, slot):
        if self._selected_slot != slot or not isinstance(self._baseline, dict):
            return False
        if self._slot_source_changed(slot):
            return False
        return comparable_params_match(
            self._kind,
            self._baseline.get("params") or {},
            self._collect_safe(),
        )

    def _apply_with_rollback(self, params, *, error_prefix, snapshot=None):
        snapshot = snapshot or self._snapshot_collect_and_baseline()
        try:
            self._apply(params)
        except Exception as e:
            self._restore_collect_and_baseline(snapshot)
            self.acknowledged.emit("error", f"{error_prefix}: {e}")
            return False
        return True

    def _on_left_click(self, slot):
        """Load a filled/builtin slot, or save into an empty custom slot.

        Clicking the current baseline again re-applies it. Completely
        consistent and unchanged slots are a no-op.
        """
        if self._is_noop_reapply(slot):
            return
        entry = self._read(slot)
        if entry is None and not self._is_builtin_slot(slot):
            self._save(slot)
            return
        self._load(slot)

    def _save(self, slot):
        try:
            params = self._collect()
        except Exception as e:
            logger.exception("preset collect failed during save")
            self.acknowledged.emit("error", f"保存失败: {e}")
            return
        if not isinstance(params, dict) or not params:
            self.acknowledged.emit("error", "保存失败: 当前预设参数不可用")
            return
        existing = self._read(slot)
        name = existing[0] if existing else self._default_name(slot)

        def work():
            self._write(slot, name, params)
            if not self._commit_loaded_slot(slot, params, params):
                self.acknowledged.emit("error", "保存失败: 无法建立预设基准")
                return False
            return True

        if self._run_user_transaction(work):
            self.acknowledged.emit("success", f"已保存到「{name}」")

    def _load(self, slot):
        entry = self._read(slot)
        if entry is None:
            params = self._builtin_params(slot)
            if params is None:
                self.acknowledged.emit(
                    "warning", f"「{self._default_name(slot)}」是空的",
                )
                return
            name = self._default_name(slot)
        else:
            name, params = entry
        if not isinstance(params, dict) or not params:
            self.acknowledged.emit("error", f"加载失败: 「{name}」没有有效补丁")
            return
        before = self._collect()
        if not isinstance(before, dict) or not before:
            self.acknowledged.emit("error", "加载失败: 当前预设参数不可用")
            return
        target = resolve_preset_target(self._kind, before, params)
        if not target:
            self.acknowledged.emit("error", "加载失败: 无法解析预设目标")
            return
        prepared = self._prepare_user_preset(target, current=before)
        if prepared is None:
            return
        snapshot = (
            copy.deepcopy(before),
            copy.deepcopy(self._baseline),
            copy.deepcopy(self._loaded_slot_payload),
        )

        def work():
            if not self._apply_with_rollback(
                prepared, error_prefix="加载失败", snapshot=snapshot,
            ):
                return False
            if not self._commit_loaded_slot(slot, target, params):
                self._restore_collect_and_baseline(snapshot)
                self.acknowledged.emit("error", "加载失败: 无法建立预设基准")
                return False
            return True

        if self._run_user_transaction(work):
            self.acknowledged.emit("success", f"已加载「{name}」")

    def _restore_default_params(self, slot=None):
        """Menu path: apply construction defaults and clear the baseline."""
        params = self._default_params
        if not isinstance(params, dict):
            self.acknowledged.emit("info", "没有可恢复的面板默认参数")
            return
        prepared = self._prepare_user_preset(
            dict(params), purpose="restore_defaults",
        )
        if prepared is None:
            return
        snapshot = self._snapshot_collect_and_baseline()

        def work():
            if not self._apply_with_rollback(
                prepared, error_prefix="恢复默认失败", snapshot=snapshot,
            ):
                return False
            self._clear_baseline()
            return True

        if self._run_user_transaction(work):
            self.acknowledged.emit("info", "已恢复面板默认参数")

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
        # The set of available names just changed, so the answer to "which
        # name is this state?" can change even though no parameter moved.
        self.sync_match()
        self.acknowledged.emit("info", f"已清空「{name}」")

    def _reset_to_default(self, slot):
        """Builtin-aware reset: drop the user override, builtin restores
        as the slot's effective preset on the next load.
        """
        if not self._is_builtin_slot(slot):
            return
        self._delete(slot)
        # Dropping the override restores the builtin patch as the slot's
        # payload — a different payload to match against (see _clear).
        self.sync_match()
        self.acknowledged.emit(
            "info", f"已重置此槽为内置「{self._default_name(slot)}」",
        )

    def _show_menu(self, slot, pos):
        # Record the preset right-click as a discovered gesture (shared default
        # QSettings, the same set the chart-card hint system reads), so the hint
        # system can treat "right-click a preset slot" as a learned interaction.
        hints.mark_discovered(QSettings(), "preset.right_click")
        btn = self._load_btns[slot]
        # Resolve QMenu through the package namespace at call time so that
        # tests can monkeypatch "mf4_analyzer.ui.inspector_sections.QMenu" and
        # have the patch seen here (the monolithic module had QMenu in the same
        # namespace as PresetBar; the package design preserves that contract by
        # deferring the lookup to __call__ time via sys.modules).
        import sys as _sys
        _pkg = _sys.modules.get('mf4_analyzer.ui.inspector_sections')
        _QMenu = getattr(_pkg, 'QMenu', QMenu) if _pkg is not None else QMenu
        menu = apply_rounded_menu_chrome(_QMenu(self))
        act_save = menu.addAction("保存当前到本槽位")
        act_rename = menu.addAction("重命名…")
        if self._is_builtin_slot(slot):
            act_reset = menu.addAction("重置此槽为内置")
            act_clear = None
        else:
            act_reset = None
            act_clear = menu.addAction("清空")
        act_restore = None
        if isinstance(self._default_params, dict):
            act_restore = menu.addAction("恢复面板默认参数")
        entry = self._read(slot)
        act_save.setEnabled(True)
        rename_target = entry is not None or self._builtin_params(slot) is not None
        act_rename.setEnabled(rename_target)
        if act_clear is not None:
            act_clear.setEnabled(entry is not None)
        if act_reset is not None:
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
        elif act_restore is not None and chosen is act_restore:
            self._restore_default_params(slot)
