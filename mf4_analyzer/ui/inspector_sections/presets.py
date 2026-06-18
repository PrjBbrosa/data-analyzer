"""Preset hover card and preset bar widgets."""
import json
from html import escape

from PyQt5.QtCore import QEvent, QPoint, QSettings, Qt, pyqtSignal
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
    QVBoxLayout,
    QWidget,
)

from ...ui_kit.menus import apply_rounded_menu_chrome
from .. import hints
from ._helpers import (
    BUILTIN_PRESET_BLURB,
    _PRESET_KEY_TO_SLOT,
    _preset_settings,
    _preset_value_text,
)


class _PresetHoverCard(QFrame):
    """Custom preset hover card.

    Qt's native QToolTip supports only a tiny HTML subset, so chip-style
    parameter summaries must be rendered as real widgets.
    """

    WIDTH = 380

    def __init__(self):
        super().__init__(
            None,
            Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )
        self.setObjectName("presetHoverCard")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowOpacity(1.0)
        self.setFixedWidth(self.WIDTH)
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
            QLabel#presetChip[warn="true"] {
                border-color: #d9b56e;
            }
        """)

    def set_summary(self, *, name, params, kind, label_map, current_params=None,
                    builtin=False, blurb=''):
        self._clear()
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
        title_box.addWidget(title)
        sub_text = blurb if (builtin and blurb) else f"已保存参数快照 · 来源：{self._kind_label(kind)}"
        sub = QLabel(sub_text, self._panel)
        sub.setObjectName("presetHoverSub")
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

        status = self._status_specs(params, current_params)
        if status:
            self._root.addWidget(self._section("状态判断", status))

        footer = QLabel("左键加载 · 右键保存/重命名/清空        不保存信号与 Fs", self._panel)
        footer.setObjectName("presetHoverFooter")
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
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(5)
            for label, value, warn in row_specs:
                row.addWidget(self._chip(label, value, warn), 0)
            row.addStretch(1)
            lay.addLayout(row)
        return frame

    def _chip(self, label, value, warn=False):
        chip = QLabel(self._panel)
        chip.setObjectName("presetChip")
        chip.setProperty("warn", "true" if warn else "false")
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
                'window', 'nfft', 'overlap', 'avg_mode', 'avg_overlap',
                'amp_y',
            )
        elif kind == 'fft_time':
            keys = (
                'window', 'nfft', 'overlap', 'amplitude_mode', 'remove_mean',
                'db_reference', 'dynamic', 'cmap',
            )
        elif kind == 'order':
            keys = (
                'max_order', 'order_res', 'time_res', 'nfft',
                'samples_per_rev', 'amplitude_mode',
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

    def _status_specs(self, params, current_params):
        specs = []
        if current_params:
            axis_keys = {
                'x_auto', 'x_min', 'x_max', 'y_auto', 'y_min', 'y_max',
                'z_auto', 'z_floor', 'z_ceiling',
            }
            saved_analysis = {
                k: params[k] for k in params
                if k in current_params and k not in axis_keys
            }
            analysis_same = all(current_params.get(k) == v for k, v in saved_analysis.items())
            specs.append(("参数", "一致" if analysis_same else "有差异", not analysis_same))
            saved_axes = {k: params[k] for k in params if k in current_params and k in axis_keys}
            if saved_axes:
                axes_same = all(current_params.get(k) == v for k, v in saved_axes.items())
                specs.append(("坐标轴", "一致" if axes_same else "有差异", not axes_same))
        specs.append(("信号/Fs", "不切换", False))
        return specs

    def _kind_label(self, kind):
        return {
            'fft': 'FFT',
            'fft_time': 'FFT vs Time',
            'order': 'Order Time',
        }.get(kind, kind)


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
      no user override exists (for signal-type presets this reads as 频率优先 /
      均衡 / 时间优先 out of the box).
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
        self.setObjectName("inspectorPresetBar")
        self._kind = kind
        self._collect = collect_fn
        self._apply = apply_fn
        self._builtins = builtin_defaults  # None => legacy mode
        self._hover_card = _PresetHoverCard()
        self._hover_slot = None
        # Slot currently flagged as the unit-推荐 highlight (None => none).
        self._recommended_slot = None

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._load_btns = {}
        for n in self.SLOTS:
            ld = QPushButton(self._default_name(n), self)
            ld.setProperty("role", "preset-load")
            ld.setProperty("filled", "false")
            ld.setContextMenuPolicy(Qt.CustomContextMenu)
            ld.installEventFilter(self)
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
            btn.setToolTip("")
            if entry is None:
                # Empty slot. In builtin mode the slot still loads the
                # builtin, so it is enabled and shows the builtin display
                # name. In legacy mode the slot is enabled but reads as
                # "＋ 配置 N" — left-click will save current params.
                if self._builtins is not None:
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
            # Re-stamp the recommended flag on every refresh so the
            # unit-推荐 highlight survives an unpolish/polish cycle (the
            # property would otherwise reset to its last-written value, but
            # _refresh_states does not touch it — so it is preserved here for
            # clarity and to mirror the "★推荐" text prefix).
            recommended = self._recommended_slot == n
            btn.setProperty("recommended", "true" if recommended else "false")
            self._apply_recommended_text(n, recommended)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _apply_recommended_text(self, slot, recommended):
        """Prefix the recommended slot's label with a ★ marker (and strip it
        from non-recommended slots). Operates on whatever text the slot
        currently shows so it composes with builtin display names, user
        overrides, and the legacy "＋ 配置 N" placeholder.
        """
        btn = self._load_btns[slot]
        text = btn.text()
        marker = "★ "
        had_marker = text.startswith(marker)
        if recommended and not had_marker:
            btn.setText(marker + text)
        elif not recommended and had_marker:
            btn.setText(text[len(marker):])

    def set_recommended(self, slot):
        """Highlight ``slot`` as the unit-推荐 preset (green ★ accent).

        ``slot`` is 1-based (1/2/3) to match :data:`PresetBar.SLOTS`, or
        ``None`` to clear every highlight. Manual interaction is unaffected —
        this is a visual hint only. The highlight is driven by a QSS dynamic
        property (``recommended="true"``) + unpolish/polish so it composes
        with the project theme instead of overriding it via setStyleSheet.
        """
        if slot is not None and slot not in self.SLOTS:
            slot = None
        self._recommended_slot = slot
        self._refresh_states()

    def eventFilter(self, obj, event):
        slot = None
        for n, btn in self._load_btns.items():
            if obj is btn:
                slot = n
                break
        if slot is None:
            return super().eventFilter(obj, event)
        if event.type() == QEvent.Enter:
            self._show_hover(slot)
        elif event.type() in (QEvent.Leave, QEvent.MouseButtonPress):
            self._hide_hover()
        return super().eventFilter(obj, event)

    def _show_hover(self, slot):
        entry = self._read(slot)
        builtin = False
        if entry is None:
            params = self._builtin_params(slot)
            if params is None:
                self._hide_hover()
                return
            name = self._default_name(slot)
            builtin = True
        else:
            name, params = entry
        try:
            current_params = self._collect()
        except Exception:
            current_params = {}
        # Resolve blurb for builtin slots: reverse-map slot index → preset key.
        _SLOT_TO_KEY = {v: k for k, v in _PRESET_KEY_TO_SLOT.items()}
        builtin_blurb = (
            BUILTIN_PRESET_BLURB.get(_SLOT_TO_KEY.get(slot, ''), '')
            if builtin else ''
        )
        self._hover_slot = slot
        self._hover_card.set_summary(
            name=name,
            params=params,
            kind=self._kind,
            label_map=self._SUMMARY_LABELS,
            current_params=current_params,
            builtin=builtin,
            blurb=builtin_blurb,
        )
        self._place_hover(slot)
        self._hover_card.show()
        self._hover_card.raise_()

    def _place_hover(self, slot):
        btn = self._load_btns[slot]
        card = self._hover_card
        card.adjustSize()
        size = card.sizeHint()
        width = max(card.width(), size.width())
        height = max(card.height(), size.height())
        screen = QApplication.screenAt(btn.mapToGlobal(btn.rect().center()))
        available = screen.availableGeometry() if screen else QApplication.primaryScreen().availableGeometry()
        center = btn.mapToGlobal(btn.rect().center())
        x = center.x() - width // 2
        x = max(available.left() + 8, min(x, available.right() - width - 8))
        top = btn.mapToGlobal(btn.rect().topLeft())
        bottom = btn.mapToGlobal(btn.rect().bottomLeft())
        y = top.y() - height - 10
        if y < available.top() + 8:
            y = bottom.y() + 10
        card.move(QPoint(x, y))

    def _hide_hover(self):
        self._hover_slot = None
        if hasattr(self, '_hover_card') and self._hover_card is not None:
            self._hover_card.hide()

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
            "（右键可重命名 / 重置为默认）"
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
        self.set_recommended(slot)
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
