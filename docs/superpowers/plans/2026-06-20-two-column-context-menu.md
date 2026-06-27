# 图表右键菜单 · 第三槽自定义动作按钮 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把图表右键菜单鼠标行的第三槽,从「pan 键盘快捷键入口」改成「可绑定单个执行型动作、点 ▾ 就地换绑」的快捷按钮。

**Architecture:** 在 `context_menu.py` 内新增动作注册表 + `_PgCustomActionButton` 组件,复用现有 `_PgContextInlinePanel`;7 个动作经 resolver 映射到现成 handler(controller / view_all / y_autofit / 新注入的 copy_image),绑定存 `QSettings`。`redesign_pg_context_menu` 链路新增一个 `copy_image_handler` 参数,由 `_ChartCard` 在创建 canvas 时注入。

**Tech Stack:** Python 3.12 / PyQt5 / pyqtgraph / pytest + pytest-qt;HTML prototype for visual review。

## Global Constraints

设计依据:`docs/superpowers/specs/2026-06-20-two-column-context-menu-design.md`。逐条遵守:

- 第三槽只绑**执行型**动作(点一下执行完);不收模式型(游标/分屏/标注)。
- v1 动作池固定 7 个:`copy_image`(默认) / `home` / `back` / `forward` / `y_fit` / `view_all` / `export`。
- 第三槽**不进** zoom/pan 的 `QButtonGroup`,**不做** checked 持久高亮。
- 绑定**全局一份**,`QSettings` key = `chartContext/customAction`,默认 `copy_image`。
- 换绑用**面板内就地展开**,**禁止**新 `QMenu` / 模态 `QInputDialog`/`QMessageBox`。
- 动作不可用时第三槽/列表项 **disabled**,位置保留不隐藏。
- 透明背景遵循项目铁律:外层 `WA_TranslucentBackground`,卡片背景由内层 QSS 子 widget 承载(参 quickref_panel),否则 `paintEvent` 兜底。
- **不**新增 `hints.py` shortcut resolver、**不**改 `chart_stack/_helpers.py` 的 QShortcut、**不**改数值算法 / toolbar 布局 / inspector / 已实现的四行。
- 当前工作树有无关脏项(多个 modified + `output/`);**只 stage 本计划明确列出的文件**,提交用 `git commit -- <路径>` 锁定。
- 每条 commit message 末尾保留项目要求的 trailer(Co-Authored-By / Claude-Session)。
- 测试命令前缀:`QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest`。

## File Map

- Modify: `mf4_analyzer/ui/pg_canvas/context_menu.py` — 动作注册表 + resolver + 持久化 helper + `_PgCustomActionButton` + `_build_mouse_row` 改造 + `copy_image_handler` 透传。
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py` — `register_copy_image_handler` + `self._copy_image_handler` + `_redesign_context_menu_for_viewbox` 传参。
- Modify: `mf4_analyzer/ui/chart_stack/cards.py` — 在 `register_mouse_mode_controller` 旁注入 copy handler(getattr-guarded,对三种 canvas 通用)。
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py` — `register_copy_image_handler` + `self._copy_image_handler` + redesign 传参(独立类,line 240/514/588)。
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py` — 同上(独立类,line 808/1355/1365)。
- Modify: `tests/ui/test_pg_timedomain_canvas.py` — 第三槽结构 / 行为测试。
- Modify: `tests/ui/test_pg_line_canvas.py` — FFT line 第三槽测试。
- Modify: `tests/ui/test_pg_heatmap_canvas.py` — heatmap 第三槽 + 不适用动作 disabled。
- Modify: `docs/analyzer/ui-prototypes/2026-06-20-inline-axis-grid-context-menu.html` — 原型第三槽更新。

---

### Task 1: 动作注册表 + resolver + 持久化 helper

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/context_menu.py`
- Test: `tests/ui/test_pg_timedomain_canvas.py`

**Interfaces:**
- Produces:
  - `_CUSTOM_ACTION_ORDER: list[str]`(7 个 id,顺序固定)
  - `_CUSTOM_ACTION_LABELS: dict[str,str]`、`_CUSTOM_ACTION_ICONS: dict[str,str]`
  - `_DEFAULT_CUSTOM_ACTION = "copy_image"`、`_CUSTOM_ACTION_SETTINGS_KEY = "chartContext/customAction"`
  - `_load_custom_action(settings=None) -> str`
  - `_save_custom_action(action_id, settings=None) -> None`
  - `_resolve_custom_action(action_id, *, controller, view_all_handler, y_autofit_handler, copy_image_handler) -> callable | None`

- [ ] **Step 1: 写失败测试**

Add near the other context-menu helpers in `tests/ui/test_pg_timedomain_canvas.py`:

```python
def test_custom_action_registry_and_persistence(monkeypatch):
    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui.pg_canvas import context_menu as cm

    assert cm._CUSTOM_ACTION_ORDER == [
        "copy_image", "home", "back", "forward", "y_fit", "view_all", "export",
    ]
    assert cm._DEFAULT_CUSTOM_ACTION == "copy_image"
    assert set(cm._CUSTOM_ACTION_LABELS) == set(cm._CUSTOM_ACTION_ORDER)
    assert set(cm._CUSTOM_ACTION_ICONS) == set(cm._CUSTOM_ACTION_ORDER)

    settings = QSettings("MF4AnalyzerTest", "RegistryCase")
    settings.clear()
    # default when unset
    assert cm._load_custom_action(settings) == "copy_image"
    # round-trip
    cm._save_custom_action("home", settings)
    assert cm._load_custom_action(settings) == "home"
    # invalid id falls back to default
    settings.setValue(cm._CUSTOM_ACTION_SETTINGS_KEY, "bogus")
    assert cm._load_custom_action(settings) == "copy_image"
    settings.clear()


def test_resolve_custom_action_maps_to_handlers():
    from mf4_analyzer.ui.pg_canvas import context_menu as cm

    class _Ctl:
        def home(self): pass
        def back(self): pass
        def forward(self): pass
        def save_figure(self): pass

    ctl = _Ctl()
    va = lambda: None
    yf = lambda: None
    copy = lambda: None

    def resolve(aid):
        return cm._resolve_custom_action(
            aid, controller=ctl, view_all_handler=va,
            y_autofit_handler=yf, copy_image_handler=copy,
        )

    assert resolve("home") == ctl.home
    assert resolve("export") == ctl.save_figure
    assert resolve("view_all") is va
    assert resolve("y_fit") is yf
    assert resolve("copy_image") is copy
    # missing handler -> None (unavailable)
    assert cm._resolve_custom_action(
        "copy_image", controller=ctl, view_all_handler=va,
        y_autofit_handler=yf, copy_image_handler=None,
    ) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -k "custom_action_registry or resolve_custom_action" -q`
Expected: FAIL with `AttributeError: module ... has no attribute '_CUSTOM_ACTION_ORDER'`.

- [ ] **Step 3: Implement registry + helpers**

In `mf4_analyzer/ui/pg_canvas/context_menu.py`, add `from PyQt5.QtCore import QSettings` to the `PyQt5.QtCore` import line (currently `from PyQt5.QtCore import QSize, Qt`), then add after the `_INLINE_*` constants block (after line ~105):

```python
_DEFAULT_CUSTOM_ACTION = "copy_image"
_CUSTOM_ACTION_SETTINGS_KEY = "chartContext/customAction"
_CUSTOM_ACTION_ORDER = [
    "copy_image", "home", "back", "forward", "y_fit", "view_all", "export",
]
_CUSTOM_ACTION_LABELS = {
    "copy_image": "复制为图片",
    "home": "重置视图",
    "back": "上一步视图",
    "forward": "下一步视图",
    "y_fit": "Y适应",
    "view_all": "全图",
    "export": "导出图片",
}
_CUSTOM_ACTION_ICONS = {
    "copy_image": "mdi.content-copy",
    "home": "mdi.home",
    "back": "mdi.arrow-left",
    "forward": "mdi.arrow-right",
    "y_fit": "mdi.arrow-expand-vertical",
    "view_all": "mdi.fit-to-page-outline",
    "export": "mdi.content-save-outline",
}
_CUSTOM_ACTION_CONTROLLER_METHODS = {
    "home": "home",
    "back": "back",
    "forward": "forward",
    "export": "save_figure",
}


def _load_custom_action(settings=None):
    settings = settings if settings is not None else QSettings()
    value = settings.value(_CUSTOM_ACTION_SETTINGS_KEY, _DEFAULT_CUSTOM_ACTION)
    text = str(value or "").strip()
    if text not in _CUSTOM_ACTION_ORDER:
        return _DEFAULT_CUSTOM_ACTION
    return text


def _save_custom_action(action_id, settings=None):
    if action_id not in _CUSTOM_ACTION_ORDER:
        return
    settings = settings if settings is not None else QSettings()
    settings.setValue(_CUSTOM_ACTION_SETTINGS_KEY, action_id)


def _resolve_custom_action(
    action_id, *, controller, view_all_handler, y_autofit_handler, copy_image_handler
):
    """Return a 0-arg callable for ``action_id`` in this context, or None if unavailable."""
    if action_id == "copy_image":
        return copy_image_handler if callable(copy_image_handler) else None
    if action_id == "view_all":
        return view_all_handler if callable(view_all_handler) else None
    if action_id == "y_fit":
        return y_autofit_handler if callable(y_autofit_handler) else None
    method = _CUSTOM_ACTION_CONTROLLER_METHODS.get(action_id)
    if method is not None and controller is not None:
        fn = getattr(controller, method, None)
        return fn if callable(fn) else None
    return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -k "custom_action_registry or resolve_custom_action" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/context_menu.py tests/ui/test_pg_timedomain_canvas.py
git commit -- mf4_analyzer/ui/pg_canvas/context_menu.py tests/ui/test_pg_timedomain_canvas.py -m "feat(menu): add custom-action registry + persistence"
```

---

### Task 2: `_PgCustomActionButton` 组件(渲染当前绑定 + ▾ + disabled)

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/context_menu.py`
- Test: `tests/ui/test_pg_timedomain_canvas.py`

**Interfaces:**
- Consumes: Task 1 registry + `_resolve_custom_action`。
- Produces: `class _PgCustomActionButton(QWidget)`,objectName `pgContextCustomActionButton`,内含主体 `QToolButton#pgContextCustomActionMain` + 角标 `QToolButton#pgContextCustomActionCaret`。构造签名:
  `_PgCustomActionButton(parent, *, menu, controller, view_all_handler, y_autofit_handler, copy_image_handler, settings=None)`

- [ ] **Step 1: 写失败测试**

```python
def _make_custom_button(qapp, *, copy=lambda: None, settings=None):
    from PyQt5.QtWidgets import QMenu
    from mf4_analyzer.ui.pg_canvas import context_menu as cm

    class _Ctl:
        def home(self): pass
        def back(self): pass
        def forward(self): pass
        def save_figure(self): pass

    menu = QMenu()
    btn = cm._PgCustomActionButton(
        None, menu=menu, controller=_Ctl(),
        view_all_handler=lambda: None, y_autofit_handler=lambda: None,
        copy_image_handler=copy, settings=settings,
    )
    return menu, btn


def test_custom_button_default_binding_and_objectnames(qapp):
    from PyQt5.QtCore import QSettings, Qt
    settings = QSettings("MF4AnalyzerTest", "CustomBtnDefault")
    settings.clear()
    _menu, btn = _make_custom_button(qapp, settings=settings)
    assert btn.objectName() == "pgContextCustomActionButton"
    assert btn.findChild(object, "pgContextCustomActionMain") is not None
    assert btn.findChild(object, "pgContextCustomActionCaret") is not None
    assert btn.current_action_id() == "copy_image"
    assert btn.testAttribute(Qt.WA_TranslucentBackground)
    settings.clear()


def test_custom_button_disabled_when_handler_missing(qapp):
    from PyQt5.QtCore import QSettings
    settings = QSettings("MF4AnalyzerTest", "CustomBtnDisabled")
    settings.clear()
    # bind copy_image but provide no copy handler -> main disabled
    _menu, btn = _make_custom_button(qapp, copy=None, settings=settings)
    main = btn.findChild(object, "pgContextCustomActionMain")
    assert not main.isEnabled()
    settings.clear()
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -k "custom_button_default or custom_button_disabled" -q`
Expected: FAIL — `_PgCustomActionButton` undefined.

- [ ] **Step 3: Implement component skeleton**

Add a QSS constant after `_INLINE_PANEL_QSS` (keep it self-contained so the translucent shell never shows a grey backing):

```python
_CUSTOM_ACTION_QSS = (
    "QWidget#pgContextCustomActionButton { background: transparent; }"
    "QToolButton#pgContextCustomActionMain {"
    " border: 1px solid #d6e0ec; border-radius: 7px;"
    " background: #ffffff; padding: 0px; }"
    "QToolButton#pgContextCustomActionMain:hover { border-color: #0b7af3; background: #f3f7ff; }"
    "QToolButton#pgContextCustomActionMain:disabled { border-color: #e5eaf2; background: #f8fafc; }"
    "QToolButton#pgContextCustomActionCaret {"
    " border: none; background: transparent; color: #64748b; padding: 0px; }"
)
```

Then add the class (place it just before `_make_inline_context_panel_action`, after `_PgContextInlinePanel`):

```python
class _PgCustomActionButton(QWidget):
    """Third mouse-row slot: runs one bound execute-type action; ``▾`` rebinds."""

    def __init__(
        self, parent, *, menu, controller, view_all_handler,
        y_autofit_handler, copy_image_handler, settings=None,
    ):
        super().__init__(parent)
        self.setObjectName("pgContextCustomActionButton")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet(_CUSTOM_ACTION_QSS)
        self._menu = menu
        self._controller = controller
        self._view_all_handler = view_all_handler
        self._y_autofit_handler = y_autofit_handler
        self._copy_image_handler = copy_image_handler
        self._settings = settings
        self._action_id = _load_custom_action(settings)
        self._list_host = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._main = QToolButton(self)
        self._main.setObjectName("pgContextCustomActionMain")
        self._main.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._main.setIconSize(QSize(18, 18))
        self._main.setFixedSize(32, _INLINE_CONTROL_HEIGHT)
        self._main.setCursor(Qt.PointingHandCursor)
        self._main.clicked.connect(self._on_main_clicked)
        self._caret = QToolButton(self)
        self._caret.setObjectName("pgContextCustomActionCaret")
        self._caret.setText("▾")
        self._caret.setFixedSize(14, _INLINE_CONTROL_HEIGHT)
        self._caret.setCursor(Qt.PointingHandCursor)
        self._caret.setToolTip("更换动作")
        self._caret.clicked.connect(self._toggle_action_list)
        lay.addWidget(self._main)
        lay.addWidget(self._caret)
        self._refresh_main()

    def current_action_id(self):
        return self._action_id

    def _resolve(self, action_id):
        return _resolve_custom_action(
            action_id, controller=self._controller,
            view_all_handler=self._view_all_handler,
            y_autofit_handler=self._y_autofit_handler,
            copy_image_handler=self._copy_image_handler,
        )

    def _refresh_main(self):
        icon_name = _CUSTOM_ACTION_ICONS.get(self._action_id)
        label = _CUSTOM_ACTION_LABELS.get(self._action_id, "")
        handler = self._resolve(self._action_id)
        if icon_name:
            self._main.setIcon(qta.icon(icon_name, color=_PG_ICON_COLOR))
            self._main.setText("")
        else:
            self._main.setText("+")
        self._main.setToolTip(label)
        self._main.setEnabled(handler is not None)

    def _on_main_clicked(self, _checked=False):
        handler = self._resolve(self._action_id)
        if callable(handler):
            try:
                handler()
            except Exception:
                pass
        try:
            self._menu.close()
        except Exception:
            pass

    def _toggle_action_list(self, _checked=False):
        # Implemented in Task 4.
        pass
```

> Note: `current_action_id()` shows `+` only as a fallback — `_load_custom_action` already coerces unknown ids back to `copy_image`, so a normal session always renders an icon.

- [ ] **Step 4: Run to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -k "custom_button_default or custom_button_disabled" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/context_menu.py tests/ui/test_pg_timedomain_canvas.py
git commit -- mf4_analyzer/ui/pg_canvas/context_menu.py tests/ui/test_pg_timedomain_canvas.py -m "feat(menu): custom-action button shell + binding render"
```

---

### Task 3: 主体点击执行 + 关菜单

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/context_menu.py`(已在 Task 2 写入 `_on_main_clicked`,本任务补测试)
- Test: `tests/ui/test_pg_timedomain_canvas.py`

**Interfaces:**
- Consumes: Task 2 component。

- [ ] **Step 1: 写失败测试**

```python
def test_custom_button_main_runs_handler_and_closes_menu(qapp):
    from PyQt5.QtCore import QSettings
    calls = {"copy": 0, "closed": 0}
    settings = QSettings("MF4AnalyzerTest", "CustomBtnRun")
    settings.clear()
    menu, btn = _make_custom_button(
        qapp, copy=lambda: calls.__setitem__("copy", calls["copy"] + 1),
        settings=settings,
    )
    menu.close = lambda: calls.__setitem__("closed", calls["closed"] + 1)
    main = btn.findChild(object, "pgContextCustomActionMain")
    main.click()
    assert calls["copy"] == 1
    assert calls["closed"] == 1
    settings.clear()
```

- [ ] **Step 2: Run to verify**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -k "main_runs_handler" -q`
Expected: PASS (logic already implemented in Task 2's `_on_main_clicked`). If it fails, fix `_on_main_clicked` to call the resolved handler then `self._menu.close()`.

- [ ] **Step 3: Commit**

```bash
git add tests/ui/test_pg_timedomain_canvas.py
git commit -- tests/ui/test_pg_timedomain_canvas.py -m "test(menu): custom-action main click runs handler + closes menu"
```

---

### Task 4: ▾ 就地展开动作列表 + 换绑 + 持久化

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/context_menu.py`
- Test: `tests/ui/test_pg_timedomain_canvas.py`

**Interfaces:**
- Consumes: Task 2/3。
- Produces: `_PgCustomActionButton._toggle_action_list` 展开/收起一个内联列表容器 `QWidget#pgContextActionList`,其中每个动作是 `QToolButton`,objectName `pgContextActionItem_<id>`;选中改绑后写 `QSettings` 并 `_refresh_main()`,列表收起,**不关菜单**,**不创建 QMenu**。

- [ ] **Step 1: 写失败测试**

```python
def test_custom_button_caret_expands_list_and_rebinds(qapp):
    from PyQt5.QtCore import QSettings
    from PyQt5.QtWidgets import QMenu, QToolButton
    settings = QSettings("MF4AnalyzerTest", "CustomBtnRebind")
    settings.clear()
    menu, btn = _make_custom_button(qapp, settings=settings)
    closed = {"n": 0}
    menu.close = lambda: closed.__setitem__("n", closed["n"] + 1)

    # no list before caret click
    assert btn.findChild(object, "pgContextActionList") is None
    btn.findChild(object, "pgContextCustomActionCaret").click()
    lst = btn.findChild(object, "pgContextActionList")
    assert lst is not None
    # 7 items, current bound is checked/marked
    items = [c for c in lst.findChildren(QToolButton)
             if c.objectName().startswith("pgContextActionItem_")]
    assert len(items) == 7
    # rebind to 'home'
    home_item = btn.findChild(object, "pgContextActionItem_home")
    home_item.click()
    assert btn.current_action_id() == "home"
    assert settings.value("chartContext/customAction") == "home"
    assert btn.findChild(object, "pgContextActionList") is None  # collapsed
    assert closed["n"] == 0  # menu NOT closed on rebind
    # no nested QMenu was created
    assert not btn.findChildren(QMenu)
    settings.clear()


def test_custom_button_list_item_disabled_when_unavailable(qapp):
    from PyQt5.QtCore import QSettings
    settings = QSettings("MF4AnalyzerTest", "CustomBtnItemDisabled")
    settings.clear()
    # no copy handler -> copy_image item disabled
    menu, btn = _make_custom_button(qapp, copy=None, settings=settings)
    btn.findChild(object, "pgContextCustomActionCaret").click()
    copy_item = btn.findChild(object, "pgContextActionItem_copy_image")
    assert not copy_item.isEnabled()
    home_item = btn.findChild(object, "pgContextActionItem_home")
    assert home_item.isEnabled()
    settings.clear()
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -k "caret_expands or list_item_disabled" -q`
Expected: FAIL — caret toggle is a no-op stub.

- [ ] **Step 3: Implement the inline list**

Replace the `_toggle_action_list` stub in `_PgCustomActionButton` and add helpers:

```python
    def _toggle_action_list(self, _checked=False):
        if self._list_host is not None:
            self._collapse_action_list()
            return
        self._expand_action_list()

    def _expand_action_list(self):
        host = QWidget(self.parent() or self)
        host.setObjectName("pgContextActionList")
        host.setAttribute(Qt.WA_TranslucentBackground, True)
        host.setAutoFillBackground(False)
        host.setStyleSheet(
            "QWidget#pgContextActionList { background: transparent; }"
            "QToolButton { border: 1px solid transparent; border-radius: 6px;"
            " background: #ffffff; color: #334155; text-align: left;"
            " padding: 4px 8px; font-size: 13px; }"
            "QToolButton:hover { background: #f3f7ff; }"
            "QToolButton:checked { color: #2563eb; }"
            "QToolButton:disabled { color: #b8c2d0; }"
        )
        col = QVBoxLayout(host)
        col.setContentsMargins(6, 6, 6, 6)
        col.setSpacing(2)
        for action_id in _CUSTOM_ACTION_ORDER:
            item = QToolButton(host)
            item.setObjectName(f"pgContextActionItem_{action_id}")
            item.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            icon_name = _CUSTOM_ACTION_ICONS.get(action_id)
            if icon_name:
                item.setIcon(qta.icon(icon_name, color=_PG_ICON_COLOR))
                item.setIconSize(QSize(16, 16))
            item.setText(_CUSTOM_ACTION_LABELS.get(action_id, action_id))
            item.setCheckable(True)
            item.setChecked(action_id == self._action_id)
            item.setEnabled(self._resolve(action_id) is not None)
            item.setCursor(Qt.PointingHandCursor)
            item.clicked.connect(
                lambda _c=False, aid=action_id: self._rebind(aid)
            )
            col.addWidget(item)
        self._list_host = host
        # Inline placement inside the panel's grid layout, directly under this
        # button's row, so no nested QMenu / popup is needed.
        self._insert_list_into_panel(host)
        host.show()

    def _insert_list_into_panel(self, host):
        panel = self.parent()
        layout = panel.layout() if panel is not None else None
        if layout is None:
            host.setParent(self)
            return
        # Span the operation columns (0..2) on a fresh row appended at the bottom.
        row = layout.rowCount()
        layout.addWidget(host, row, 0, 1, 3)

    def _collapse_action_list(self):
        if self._list_host is not None:
            self._list_host.setParent(None)
            self._list_host.deleteLater()
            self._list_host = None

    def _rebind(self, action_id):
        self._action_id = action_id
        _save_custom_action(action_id, self._settings)
        self._refresh_main()
        self._collapse_action_list()
```

Add `QVBoxLayout` to the `PyQt5.QtWidgets` import block at the top of the file.

> **▾ 展开方案 + 真机决定(spec §4):** 主方案是把列表作为面板 grid 的新一行(`_insert_list_into_panel`)。若 Task 9 真机验证发现 `QWidgetAction` 内动态加行导致 `QMenu` 不重布局/列表不可见,改 `_insert_list_into_panel` 为:`host.setParent(self._main.window())`、`host.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)`、`host.move(self._caret.mapToGlobal(QPoint(0, self._caret.height())))`、`host.show()`(需 `from PyQt5.QtCore import QPoint`)。仍不走 `QMenu`、不模态。测试断言用 objectName,两种实现都通过。

- [ ] **Step 4: Run to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -k "caret_expands or list_item_disabled" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/context_menu.py tests/ui/test_pg_timedomain_canvas.py
git commit -- mf4_analyzer/ui/pg_canvas/context_menu.py tests/ui/test_pg_timedomain_canvas.py -m "feat(menu): inline action-list rebind for custom slot"
```

---

### Task 5: 接入鼠标行(zoom/pan/custom 三槽,pan 移中槽)+ handler 透传

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/context_menu.py`
- Test: `tests/ui/test_pg_timedomain_canvas.py`

**Interfaces:**
- Consumes: Task 2–4。
- Produces: `_PgContextInlinePanel.__init__` / `_make_inline_context_panel_action` / `redesign_pg_context_menu` 新增关键字参数 `copy_image_handler=None`;鼠标行第三槽为 `_PgCustomActionButton`,pan 居中,自定义按钮**不在** zoom/pan 的 `QButtonGroup`。

- [ ] **Step 1: 写失败测试**

```python
def test_inline_mouse_row_slot_order_zoom_pan_custom(qapp, monkeypatch):
    from PyQt5.QtCore import QSettings
    from PyQt5.QtWidgets import QToolButton
    settings = QSettings("MF4AnalyzerTest", "MouseRowOrder")
    settings.clear()
    canvas = _pg_canvas(qapp)
    canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
    vb = canvas.axes_list[0].view_box
    menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
    panel = _inline_panel(menu)

    custom = panel.findChild(object, "pgContextCustomActionButton")
    assert custom is not None
    zoom = _panel_button(panel, "pgContextZoomButton")
    pan = _panel_button(panel, "pgContextPanButton")
    # custom slot is NOT a member of the zoom/pan exclusive group
    from PyQt5.QtWidgets import QButtonGroup
    groups = panel.findChildren(QButtonGroup)
    for g in groups:
        assert custom.findChild(object, "pgContextCustomActionMain") not in g.buttons()
    # left-to-right x order: zoom < pan < custom
    assert zoom.mapToGlobal(zoom.rect().center()).x() \
        < pan.mapToGlobal(pan.rect().center()).x() \
        < custom.mapToGlobal(custom.rect().center()).x()
    settings.clear()
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -k "mouse_row_slot_order" -q`
Expected: FAIL — no custom button in the row; pan still in right slot.

- [ ] **Step 3: Thread `copy_image_handler` through the panel chain**

Edit `_PgContextInlinePanel.__init__` signature (line ~336) to add `copy_image_handler=None` after `y_autofit_handler=None`, and store it:

```python
        self._copy_image_handler = copy_image_handler
```

Edit `_make_inline_context_panel_action` (line ~617) to accept and forward `copy_image_handler=None`:

```python
def _make_inline_context_panel_action(
    menu, plot_item, controller, *,
    view_all_handler=None, y_autofit_handler=None,
    copy_image_handler=None, allow_y_grid=True, view_box=None,
):
    panel = _PgContextInlinePanel(
        menu, plot_item, controller,
        view_all_handler=view_all_handler,
        y_autofit_handler=y_autofit_handler,
        copy_image_handler=copy_image_handler,
        allow_y_grid=allow_y_grid, view_box=view_box,
    )
    action = QWidgetAction(menu)
    action.setDefaultWidget(panel)
    return action
```

Edit `redesign_pg_context_menu` (line ~850) to accept `copy_image_handler=None` and forward it in the `_make_inline_context_panel_action(...)` call (line ~875).

- [ ] **Step 4: Rebuild the mouse row with three slots**

Replace `_build_mouse_row` (lines ~428-454) with:

```python
    def _build_mouse_row(self, layout, row):
        host = QWidget(self)
        host.setObjectName("pgContextMouseControls")
        host.setAttribute(Qt.WA_TranslucentBackground, True)
        host.setAutoFillBackground(False)
        hbox = QHBoxLayout(host)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(8)

        zoom_button = self._make_tool_button(_PG_MOUSE_MODE_ZOOM)
        pan_button = self._make_tool_button(_PG_MOUSE_MODE_PAN)
        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(zoom_button)
        group.addButton(pan_button)
        try:
            current = self._controller.current_mouse_mode()
        except Exception:
            current = None
        _sync_mouse_mode_toggle_buttons([zoom_button, pan_button], current)
        zoom_button.clicked.connect(
            lambda _checked=False: self._select_mouse_mode(_PG_MOUSE_MODE_ZOOM)
        )
        pan_button.clicked.connect(
            lambda _checked=False: self._select_mouse_mode(_PG_MOUSE_MODE_PAN)
        )
        if self._controller is None:
            zoom_button.setEnabled(False)
            pan_button.setEnabled(False)

        custom_button = _PgCustomActionButton(
            self, menu=self._menu, controller=self._controller,
            view_all_handler=self._view_all_handler,
            y_autofit_handler=self._y_autofit_handler,
            copy_image_handler=self._copy_image_handler,
        )

        hbox.addStretch(1)
        hbox.addWidget(zoom_button)
        hbox.addWidget(pan_button)
        hbox.addWidget(custom_button)
        hbox.addStretch(1)
        layout.addWidget(host, row, 0, 1, 3)
        self._add_label(layout, row, "鼠标")
```

(The custom button is never added to `group`, satisfying the "not in exclusive group" requirement.)

- [ ] **Step 5: Run to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -k "mouse_row_slot_order or custom_action_registry or resolve_custom_action or custom_button or caret_expands or list_item_disabled" -q`
Expected: PASS.

- [ ] **Step 6: Run the existing context-menu suite for regressions**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -k "context_menu or inline or grid or range or mouse" -q`
Expected: PASS (existing four-row tests still green).

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/context_menu.py tests/ui/test_pg_timedomain_canvas.py
git commit -- mf4_analyzer/ui/pg_canvas/context_menu.py tests/ui/test_pg_timedomain_canvas.py -m "feat(menu): wire custom slot into mouse row, center pan"
```

---

### Task 6: copy_image 注入链(canvas + cards)

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py`
- Modify: `mf4_analyzer/ui/chart_stack/cards.py`
- Test: `tests/ui/test_pg_timedomain_canvas.py`

**Interfaces:**
- Produces: `TimeDomainCanvasPG.register_copy_image_handler(handler)` + `self._copy_image_handler`;其 `_redesign_context_menu_for_viewbox`(canvas.py:1244)传 `copy_image_handler=self._copy_image_handler`。**注:`PgLineCanvas` / `PgHeatmapCanvas` 是独立类,各自的同名 hook 在 Task 7 加。**

- [ ] **Step 1: 写失败测试**

```python
def test_copy_image_handler_injected_and_invoked(qapp, monkeypatch):
    from PyQt5.QtCore import QSettings
    settings = QSettings("MF4AnalyzerTest", "CopyInject")
    settings.clear()
    fired = {"n": 0}
    canvas = _pg_canvas(qapp)
    canvas.register_copy_image_handler(lambda: fired.__setitem__("n", fired["n"] + 1))
    canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
    vb = canvas.axes_list[0].view_box
    menu = _assemble_and_redesign_menu(qapp, canvas, vb, monkeypatch)
    panel = _inline_panel(menu)
    custom = panel.findChild(object, "pgContextCustomActionButton")
    assert custom.current_action_id() == "copy_image"
    main = custom.findChild(object, "pgContextCustomActionMain")
    assert main.isEnabled()
    main.click()
    assert fired["n"] == 1
    settings.clear()
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -k "copy_image_handler_injected" -q`
Expected: FAIL — `register_copy_image_handler` undefined.

- [ ] **Step 3: Add the canvas hook**

In `mf4_analyzer/ui/pg_canvas/canvas.py`, beside `self._mouse_mode_controller = None` (line ~419) add:

```python
        self._copy_image_handler = None
```

After `register_mouse_mode_controller` (ends line ~1215) add:

```python
    def register_copy_image_handler(self, handler):
        """Register a 0-arg callable that copies the focused chart image.

        ``_ChartCard`` injects ``card.copy_image_requested.emit`` here so the
        right-click custom-action slot can trigger the same copy path as the
        toolbar button.
        """
        self._copy_image_handler = handler
```

In `_redesign_context_menu_for_viewbox` (the `redesign_pg_context_menu(...)` call at line ~1245) add the argument:

```python
            copy_image_handler=self._copy_image_handler,
```

- [ ] **Step 4: Inject from the card**

In `mf4_analyzer/ui/chart_stack/cards.py`, right after the mouse-mode registration block (lines 90-92):

```python
            reg_mode = getattr(canvas, 'register_mouse_mode_controller', None)
            if callable(reg_mode):
                reg_mode(self.toolbar)
```

append:

```python
            reg_copy = getattr(canvas, 'register_copy_image_handler', None)
            if callable(reg_copy):
                reg_copy(self.copy_image_requested.emit)
```

- [ ] **Step 5: Run to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -k "copy_image_handler_injected" -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/canvas.py mf4_analyzer/ui/chart_stack/cards.py tests/ui/test_pg_timedomain_canvas.py
git commit -- mf4_analyzer/ui/pg_canvas/canvas.py mf4_analyzer/ui/chart_stack/cards.py tests/ui/test_pg_timedomain_canvas.py -m "feat(menu): inject copy-image handler into chart canvas"
```

---

### Task 7: FFT line / heatmap 第三槽 + 不适用动作 disabled

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`(init line 240、register line 514、redesign line 588)
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`(init line 808、register line 1355、redesign line 1365)
- Modify: `tests/ui/test_pg_line_canvas.py`
- Modify: `tests/ui/test_pg_heatmap_canvas.py`

**Interfaces:**
- Consumes: Task 5/6。三个 canvas 类各自独立定义 `register_mouse_mode_controller` / `_redesign_context_menu_for_viewbox`,故 `register_copy_image_handler` + `self._copy_image_handler` 必须在 line/heatmap 各加一份(Task 6 只覆盖 `TimeDomainCanvasPG`)。

- [ ] **Step 1: Add copy-image hook to line + heatmap canvases**

In `mf4_analyzer/ui/pg_canvas/line_canvas.py`, beside `self._mouse_mode_controller = None` (line 240) add:

```python
        self._copy_image_handler = None
```

After `register_mouse_mode_controller` (line 514-515) add:

```python
    def register_copy_image_handler(self, handler) -> None:
        self._copy_image_handler = handler
```

In `_redesign_context_menu_for_viewbox` (the `redesign_pg_context_menu(...)` call at line 588) add the argument (e.g. after `y_autofit_handler=...`):

```python
            copy_image_handler=self._copy_image_handler,
```

Repeat the same three edits in `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`: `self._copy_image_handler = None` beside line 808; the `register_copy_image_handler` method after line 1356; and `copy_image_handler=self._copy_image_handler,` in the `redesign_pg_context_menu(...)` call at line 1365.

Sanity-grep after editing: `grep -n "copy_image_handler" mf4_analyzer/ui/pg_canvas/line_canvas.py mf4_analyzer/ui/pg_canvas/heatmap_canvas.py` — expect the new lines in both.

- [ ] **Step 2: Line canvas test — third slot present, copy default usable**

In `tests/ui/test_pg_line_canvas.py` (verified helpers: `_open_context_menu(view_box, monkeypatch)` at line 78, `_inline_panel(menu)` at line 114, pytest fixture `canvas`, time-preview ViewBox `canvas._plot_time.vb`), add:

```python
def test_fft_line_context_menu_has_custom_action_slot(canvas, monkeypatch):
    from PyQt5.QtCore import QSettings
    settings = QSettings("MF4AnalyzerTest", "LineCustomSlot")
    settings.clear()
    canvas.register_copy_image_handler(lambda: None)
    menu = _open_context_menu(canvas._plot_time.vb, monkeypatch)
    panel = _inline_panel(menu)
    custom = panel.findChild(object, "pgContextCustomActionButton")
    assert custom is not None
    assert custom.current_action_id() == "copy_image"
    main = custom.findChild(object, "pgContextCustomActionMain")
    assert main.isEnabled()  # copy handler injected -> usable
    settings.clear()
```

- [ ] **Step 3: Heatmap test — third slot present, `y_fit` item disabled**

In `tests/ui/test_pg_heatmap_canvas.py` (verified helpers: `_open_context_menu(view_box, monkeypatch)` at line 84, `_inline_panel` at line 105, `_panel_button` at line 119, pytest fixture `canvas`, main ViewBox `canvas._plot.vb`):

```python
def test_heatmap_context_menu_custom_slot_yfit_disabled(canvas, monkeypatch):
    from PyQt5.QtCore import QSettings
    settings = QSettings("MF4AnalyzerTest", "HeatmapCustomSlot")
    settings.clear()
    canvas.register_copy_image_handler(lambda: None)
    menu = _open_context_menu(canvas._plot.vb, monkeypatch)
    panel = _inline_panel(menu)
    custom = panel.findChild(object, "pgContextCustomActionButton")
    custom.findChild(object, "pgContextCustomActionCaret").click()
    # copy usable (handler injected); y_fit disabled (heatmap passes y_autofit_handler=None, heatmap_canvas.py:1370)
    assert custom.findChild(object, "pgContextActionItem_copy_image").isEnabled()
    assert not custom.findChild(object, "pgContextActionItem_y_fit").isEnabled()
    settings.clear()
```

> Note: `home`/`back`/`forward`/`export` items resolve through the mouse-mode controller; the bare `canvas` fixture registers none, so they'd be disabled too — don't assert their state here. `copy_image` (injected) + `y_fit` (forced None) are the meaningful checks.

- [ ] **Step 4: Run line + heatmap context-menu tests**

Run:
```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_line_canvas.py -k "context_menu or custom_action_slot" \
  tests/ui/test_pg_heatmap_canvas.py -k "context_menu or custom_slot" -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/line_canvas.py mf4_analyzer/ui/pg_canvas/heatmap_canvas.py tests/ui/test_pg_line_canvas.py tests/ui/test_pg_heatmap_canvas.py
git commit -- mf4_analyzer/ui/pg_canvas/line_canvas.py mf4_analyzer/ui/pg_canvas/heatmap_canvas.py tests/ui/test_pg_line_canvas.py tests/ui/test_pg_heatmap_canvas.py -m "feat(menu): custom slot copy-handler on FFT line + heatmap"
```

---

### Task 8: 更新 HTML 原型

**Files:**
- Modify: `docs/analyzer/ui-prototypes/2026-06-20-inline-axis-grid-context-menu.html`

- [ ] **Step 1: Replace the mouse-row markup**

Find the mouse row (the `panel-row` whose `row-label` is `鼠标`) and set its control group to three slots — zoom / pan / custom-action — replacing any old `自定义平移快捷键 +` key button:

```html
<div class="panel-row">
  <div class="control-group mouse-group">
    <div class="icon-btn" title="框选">⌕</div>
    <div class="icon-btn active" title="平移">✣</div>
    <button class="action-btn" type="button" title="复制为图片">⧉<span class="caret">▾</span></button>
  </div>
  <div class="row-label">鼠标</div>
</div>
```

Add CSS near the existing button styles:

```css
.mouse-group { grid-template-columns: 48px 48px 64px; column-gap: 12px; }
.action-btn {
  display: inline-flex; align-items: center; gap: 2px;
  height: 30px; padding: 0 6px;
  border: 1px solid #d6e0ec; border-radius: 7px;
  background: #fff; color: #334155; font-size: 16px;
}
.action-btn .caret { font-size: 11px; color: #64748b; }
```

- [ ] **Step 2: Add a static mock of the expanded action list**

Below the menu section, add a commented or sibling block showing the 7-item list (复制为图片 ✓ / 重置视图 / 上一步视图 / 下一步视图 / Y适应 / 全图 / 导出图片) so reviewers see the rebind affordance. Keep it visually consistent with the inline panel card.

- [ ] **Step 3: Manual open check**

Run: `open docs/analyzer/ui-prototypes/2026-06-20-inline-axis-grid-context-menu.html`
Expected: mouse row reads `[框选] [平移] [复制为图片▾]`; no old `自定义平移快捷键` key button remains.

- [ ] **Step 4: Commit**

```bash
git add docs/analyzer/ui-prototypes/2026-06-20-inline-axis-grid-context-menu.html
git commit -- docs/analyzer/ui-prototypes/2026-06-20-inline-axis-grid-context-menu.html -m "docs(menu): prototype shows custom-action third slot"
```

---

### Task 9: 真机渲染验证 + 回归 + 收尾

**Files:**
- No new modifications expected (fix forward only if a check fails).

- [ ] **Step 1: Full context-menu regression**

Run:
```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_timedomain_canvas.py \
  tests/ui/test_pg_line_canvas.py \
  tests/ui/test_pg_heatmap_canvas.py -q
```
Expected: PASS (pre-existing unrelated failures, if any, unchanged from baseline — note them, don't fix here).

- [ ] **Step 2: 真机/objc 渲染验证(项目铁律,不可省)**

Launch the app, right-click each section and verify by ACTUAL render (screenshot / objc 属性), not "属性设上了 + 单测过":
- TimeDomain subplot/overlay、FFT line/time preview、FFT-vs-Time heatmap、Order heatmap。
检查:
  - 鼠标行三槽 `[框选] [平移] [自定义▾]`,pan 居中、自定义在右。
  - 默认显示「复制为图片」图标,点主体真把图片放进剪贴板(粘贴验证)。
  - 点 ▾ 在面板内就地展开 7 项列表,**无**独立方框/灰底,圆角透明正确;选「重置视图」后图标变 home、列表收起、菜单未关。
  - heatmap 上 `Y适应` 列表项 disabled。
  - 重启应用后绑定保持(读 QSettings)。

  若 ▾ 就地展开在真机不可见/QMenu 不重布局 → 按 Task 4 Step 3 的备选 `Qt.Popup` 方案切换,再重验。

- [ ] **Step 3: diff check**

Run:
```bash
git diff --check -- \
  mf4_analyzer/ui/pg_canvas/context_menu.py \
  mf4_analyzer/ui/pg_canvas/canvas.py \
  mf4_analyzer/ui/chart_stack/cards.py \
  tests/ui/test_pg_timedomain_canvas.py \
  tests/ui/test_pg_line_canvas.py \
  tests/ui/test_pg_heatmap_canvas.py \
  docs/analyzer/ui-prototypes/2026-06-20-inline-axis-grid-context-menu.html
```
Expected: no output.

- [ ] **Step 4: 发现性(项目命令)**

Run the project command `/update-hints` to evaluate adding a footer hint + quickref row for「▾ 可换绑自定义动作」(non-self-evident interaction). Land whatever it proposes in a follow-up commit if appropriate.

- [ ] **Step 5: Final commit (if Step 2 fixes were needed)**

```bash
git add mf4_analyzer/ui/pg_canvas/context_menu.py
git commit -- mf4_analyzer/ui/pg_canvas/context_menu.py -m "fix(menu): real-render adjustments for custom slot"
```

---

## Self-Review notes

- Spec §2.6 动作池 7 个 → Task 1 注册表 + Task 4 列表;默认 copy_image → Task 1/2;点主体执行+关菜单 → Task 3;▾ 就地展开+换绑+持久化+不关菜单+无 QMenu → Task 4;不进 button group/不持久高亮/pan 居中 → Task 5;全局 QSettings 持久化 → Task 1;copy 注入 + 所有图表覆盖 → Task 6/7;不适用 disabled → Task 2/4/7;透明背景 → Task 2/4 QSS;真机验证 → Task 9;原型 → Task 8;废弃 pan 快捷键 → 本 plan 不含任何 hints resolver/QShortcut 步骤。
- 类型一致:`_resolve_custom_action` 签名、`current_action_id()`、objectName(`pgContextCustomActionButton` / `pgContextCustomActionMain` / `pgContextCustomActionCaret` / `pgContextActionList` / `pgContextActionItem_<id>`)在 Task 2/4/5/6/7 全程一致。
- 无 placeholder:每个写代码步骤均含真实代码。Task 7 的 line/heatmap helper 名(`_open_context_menu(view_box)`、fixture `canvas`、`canvas._plot_time.vb` / `canvas._plot.vb`)及三处独立 redesign 调用点(canvas.py:1244 / line_canvas.py:588 / heatmap_canvas.py:1365)均已逐字核验。
