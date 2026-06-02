# 全局 UI/UX 规则收敛与圆角弹层优化设计

日期：2026-06-02
分支：`plan/pyqtgraph-timedomain-migration`
审计报告：
- `docs/analyzer/reviews/2026-06-02-global-uiux-audit.md`
- `docs/analyzer/reviews/2026-06-02-global-uiux-audit.html`

## 背景

当前全局视觉基线已经存在：`mf4_analyzer/ui_kit/style.qss` 顶部定义了
`Precision Light` 的 surface、hairline、交互蓝和文字层级。问题不是缺风格，
而是部分弹层、菜单、内联 QSS 和旧入口没有一致执行这些规则。

用户明确指出：弹出的框在圆角背后仍有矩形阴影，尤其图片编辑器的颜色/线宽
弹出菜单仍能看到问题。该问题必须优先处理，并要做全局检查。

## 性能边界

本轮优化必须保持性能中性：

- 不改 pyqtgraph 绘图热路径、pan/zoom、cursor 重绘、实时 anti-aliasing。
- 不加全局毛玻璃、实时 blur、大面积动画或高频 hover repolish。
- 弹层修复只在点击打开菜单时生效，不进入每帧刷新路径。
- 只对低频 UI 外壳、QMenu flags、QSS 规则、测试断言做小范围改动。

## 锁定决策

| 决策 | 内容 | 理由 |
|---|---|---|
| Phase A 先做 | 只修图片标注编辑器的颜色/线宽菜单圆角阴影 | 用户点名且风险最小 |
| 不先做全局 helper | 本轮先补局部测试和最小实现，helper 放 Phase B | 避免一次迁移所有 QMenu 导致行为漂移 |
| 不碰图表性能路径 | 不改 `pg_canvases.py` 绘图和 `chart_stack.py` 抓图路径 | UI 外壳优化不应牺牲实时性能 |
| 真实 GUI 另设验证门槛 | offscreen test 只证明 flags；macOS 阴影必须靠真实 GUI/截图最终确认 | 历史上 offscreen Qt 不复现原生阴影 |

## Phase A：图片标注样式菜单圆角阴影

### 目标

修复 `MarkupEditor` 的 `markupStyleMenu`：

- 保留现有透明 `QMenu` shell。
- 保留内部 `markupStylePanel` 作为唯一可见圆角白底。
- 增加 `Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint`，与 pyqtgraph 右键菜单的 native-shadow 处理规则对齐。
- 增加测试断言，不再只检查 `WA_TranslucentBackground`。

执行状态：Phase A 已完成；已做最小 MarkupEditor 真实 macOS 截图验收，完整 TraceLab 业务流仍待执行。

### 文件

- 修改：`mf4_analyzer/ui/markup/editor.py`
- 修改：`tests/ui/test_markup_editor.py`
- 参考：`docs/lessons-learned/codex-rounded-qt-popups-need-translucent-shell.md`

### 审计时证据

`mf4_analyzer/ui/markup/editor.py` 中：

- `markupStyleMenu` 创建于 `_build_toolbar()`。
- 审计时只设置 `Qt.WA_TranslucentBackground`。
- QSS 已经把 `QMenu#markupStyleMenu` 变成透明 shell，并把圆角背景放在内部 panel。

`tests/ui/test_markup_editor.py` 中：

- 审计时 `test_style_menu_rounding_uses_translucent_background` 只断言透明背景。
- 审计时未断言 `Qt.NoDropShadowWindowHint` 和 `Qt.FramelessWindowHint`。

### 实现

在创建 `style_menu` 后、设置透明背景前后，追加窗口 flags：

```python
style_menu.setWindowFlags(
    style_menu.windowFlags()
    | Qt.FramelessWindowHint
    | Qt.NoDropShadowWindowHint
)
style_menu.setAttribute(Qt.WA_TranslucentBackground, True)
```

保留注释说明：圆角可见面在内部 panel，外层 menu 负责透明和抑制原生矩形阴影。

### 测试

更新 `test_style_menu_rounding_uses_translucent_background`：

- 继续断言 objectName 和 `WA_TranslucentBackground`。
- 新增断言：
  - `menu.windowFlags() & Qt.NoDropShadowWindowHint`
  - `menu.windowFlags() & Qt.FramelessWindowHint`

执行命令：

```bash
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_markup_editor.py::test_style_menu_rounding_uses_translucent_background -q
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

### 真机验收

offscreen 通过后，仍需要真实 GUI 验证：

1. 打开 TraceLab / Analyzer。
2. 触发复制图片并进入图片标注编辑器。
3. 点击“样式（颜色 / 线宽）”。
4. 观察弹出菜单四角外是否仍有矩形阴影或方形残影。

当前状态：最小 MarkupEditor 实例已截图到 `/tmp/markup_style_menu_real.png`，
未见明显方形阴影；完整 TraceLab / Analyzer 业务流待复核。

## Phase B：统一圆角 popup/menu helper

Phase A 稳定后再做。

建议新增 `mf4_analyzer/ui_kit/popup.py`：

```python
def style_popup_shell(widget, object_name=None, *, suppress_native_shadow=True):
    if object_name:
        widget.setObjectName(object_name)
    if suppress_native_shadow:
        widget.setWindowFlags(
            widget.windowFlags()
            | Qt.FramelessWindowHint
            | Qt.NoDropShadowWindowHint
        )
    widget.setAttribute(Qt.WA_TranslucentBackground, True)
    return widget
```

迁移候选：

- `markupStyleMenu`
- `SignalPickerPopup`
- Acquisition toolbar overflow menu
- Acquisition measurement list context menu
- Analyzer channel tree context menu
- File navigator kebab menu
- Inspector preset menu
- Batch “已加载”菜单

验收：新增结构测试，禁止新增圆角 QMenu 只靠 QSS `border-radius`。

## Phase C：全局视觉规则收敛

Phase B 后做。

- 通用按钮、popup surface、swatch、thumbnail 样式从内联 QSS 迁回 `style.qss` 或 UI kit。
- 旧入口中的 emoji/文本图标逐步替换为 `Icons` / `qtawesome`。
- 建立 MarkupEditor、Chart toolbar、Side panels、Acquisition toolbar 的截图/真机检查清单。

## 本轮验收标准

Phase A 完成时必须满足：

- 新测试先红后绿。
- `tests/ui/test_markup_editor.py` 通过。
- `docs/lessons-learned/codex-rounded-qt-popups-need-translucent-shell.md` 的规则仍与实现一致。
- 明确说明真实 GUI 是否已验证；如果没有，就标为未验证，不能声称视觉问题完全解决。
