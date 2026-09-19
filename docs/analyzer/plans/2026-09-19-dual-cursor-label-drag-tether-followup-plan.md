# 双游标标签、快速拖放与面板牵引 · Follow-up Plan

- 日期：2026-09-19
- 状态：**partial，用户验收失败**（2026-09-19 复审）。已落入源码的修改未满足牵引可见性、拖动稳定性和实际尺寸闭环。历史测试结果保留，不能作为完成证明；后续按 [复审及优化计划](2026-09-19-pin-interaction-visibility-remediation-plan.md) 执行。Cocoa 带数据交互及 Windows source/Full/Lite frozen 验收仍为 `UNVERIFIED`。
- 前置计划：[底部 Pin、多面板与闪退修复计划](2026-09-19-pin-bottom-handles-and-crash-fix-plan.md)。本文件只补其 T3/T4 未细化的三个用户可见问题，不重开状态模型、P 路由、面板展开/收起或原生映射修复。
- 执行记录：在当前稳定的 Pin 基线实施；仅触及 `controller`、`presentation`、`overlay` 及其聚焦测试。未改动其他未跟踪计划或工作树内容。

## 1. 决策、范围与非目标

### 决策

采用原型的 **方案 A：接口牵引**：仅当一个固定 Cursor 面板展开时，从面板边缘的一个小圆接口画一条低对比度折线，落到其对应的位置线。它是关联提示，不是第三条数据线；不得替代 A/B 的既有颜色、虚线和选中状态。

### 范围

1. Pn、`Pn·A`、`Pn·B` 标签的外框按实际 caption、layout margin、frame pen 与 DPR 后的最小外尺寸布局；密集避让仍以同一尺寸来源计算。
2. 底部标签即使没有收到中间 `MouseMove`，只要 release 与 press 的横向距离超过平台 `QApplication.startDragDistance()`，也必须按拖动提交最终 release 坐标；不能回退为 click/toggle。
3. 展开的固定面板与位置线建立上述牵引关系；用户拖动面板、拖动底部标签、缩放、重排或切换 A/B 目标时，牵引同步更新。

### 非目标

- 不修改 DSP、插值、FFT/FRF 吸附或 A/B 数据坐标语义。
- 不新增全局快捷键、额外 Pin 工具条、持久化 schema 或第二份 Pin 状态。
- 不把面板的临时牵引目标写入工程；它是 presenter/overlay 的短生命周期显示状态。
- 不把 HTML 原型或 offscreen 截图当作 macOS Cocoa、Windows source 或 frozen 验收。

## 2. 已确认的实现缺口

| 项目 | 现状证据 | Follow-up 合同 |
| --- | --- | --- |
| 标签外框 | `_label_width()` 只有裸文本 advance + 8；`PinnedAxisLabel` 另有 layout margin，之后又固定尺寸。 | layout 和实际 widget 使用同一 outer-size 计算；每个可见字形在 content rect 内。 |
| 快速拖放 | `_dragged` 仅在 move 事件超过阈值后变真；release 依据该 flag 决定提交或取消。 | release 以最终 pointer 坐标补判阈值、同步消费最后坐标、只提交一次。 |
| 面板牵引 | 既有 leader 只取 `PinnedLabelGeom.leader`，用于底部标签避让；没有 panel port 输入。 | panel tether 是独立投影，关闭/收起/销毁时对称清理，不混入 label leader。 |

## 3. 分三波实施

### F0 — 先冻结三个失败路径

Owner：`tests/ui/test_pinned_cursor_geometry.py`、`tests/ui/test_pinned_cursor_interaction.py`、`tests/ui/test_pinned_cursor_panels.py`。

先写失败用例，不修改生产实现：

1. 用实际 `PinnedAxisLabel` 和生产字体/样式，覆盖 `P12·A`、`P12·B`、`P12·A/B`、中文/长文本、常规和高 DPI 渲染；断言文字绘制区域不越界，密集标签不重叠，命中热区与画出的外框一致。
2. 发出 press 后直接在新 X release、**不发 `MouseMove`**。断言 collection 的目标 endpoint 使用 release 坐标、`intent_changed` 恰好一次、没有 toggle 面板、没有旧坐标回投。
3. single、dual-A、dual-B 都覆盖；双游标的 A=B、A>B、聚合标签展开成员、边界和 offscreen 标签仍保持既有合同。
4. 由展开面板生成 tether：single 一条；从 `Pn·A/B` 打开的 dual 面板指向对应端点；从聚合标签/恢复路径打开而无活动端点时，显示中性分叉到 A/B，不能暗示某个端点被选中。收起、close、unpin、owner clear、view switch 后无残留 scene item。

### F1 — 标签尺寸与 release 事务

Owner：`mf4_analyzer/ui/pg_canvas/pinned_cursor_overlay.py`、`mf4_analyzer/ui/chart_stack/pinned_cursor_controller.py`。

1. 提取单一标签 outer-size helper：输入实际 caption font、caption、layout contents margins、frame/pen allowance 和高度；`layout_pinned_axis_labels()` 与 `PinnedAxisLabel.apply_geom()` 共用它。禁止“布局按裸文本、控件按另一套 sizeHint”的双重算法。
2. 维持当前捕获保护：按下后 layout 不得把 target identity 换成另一 Pn；geometry refresh 只能在 release/cancel 后应用。
3. 在 `_release_pointer()` 取得 release global position，若尚未标记 drag 但 press/release 横向距离超过平台阈值，则切换为 drag 并发出 `edit_committed`。controller 的 `commit_axis_edit()` 必须同步 flush 最后位置后再修改 collection。
4. 明确静态 click、轻微抖动、Esc、focus out、hide、data revision 变化都是 cancel；它们不改坐标、不 dirty、不展开/收起其他面板。

### F2 — 接口牵引投影

Owner：`mf4_analyzer/ui/chart_stack/pinning/presentation.py`、`mf4_analyzer/ui/pg_canvas/pinned_cursor_overlay.py`；controller 只接收窄的 presenter 事件，不新增另一套 collection 写入。

1. Presenter 计算已展开 pill 的接口位置，映射为 canvas/viewport 坐标后向 overlay 交付不可变 tether DTO：`record_id`、目标 endpoint(s)、panel port、可见性和 highlight。DTO 不含 QWidget、HTML、持久化 anchor 或临时鼠标对象。
2. Overlay 独占 tether graphics item 的创建、复用、z-order、坐标更新与销毁；label-avoidance leader 继续只服务 `PinnedLabelGeom`。两类 item 分开列表和清理入口。
3. 路由规则：从面板距目标线最近的底/侧边 port 出发，先走短垂直段再折向位置线；不穿过标题或按钮，低 alpha、细虚线、无箭头。single 只落一条线；dual 依据活动 endpoint 落 A 或 B；没有活动 endpoint 时用小中性分叉连到 A/B。
4. tether 仅在 `panel_expanded=True` 且有可表示 endpoint 时显示。不可用/视野外时改为端口加状态 tooltip，不向边缘方向标签画一根假数据线。用户拖动面板和安全区 clamp 后在同一 GUI turn 更新；不重新采样、不写 collection、不触发 intent_changed。
5. 若用户可见文案新增“点击 Pn 打开面板并拖动定位”，同步 `ui/hints.py`、`ui/quickref.py`；没有新增动作则不制造文案改动。

## 4. 验证门

实现时按 F0 → F1 → F2 运行，不做无理由全量 baseline：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_pinned_cursor_geometry.py \
  tests/ui/test_pinned_cursor_interaction.py \
  tests/ui/test_pinned_cursor_panels.py \
  tests/ui/test_pinned_cursor_capture.py -q
```

- 若新增/修改 overlay item owner，追加 `tests/ui/test_pg_canvas_backref_invariants.py`；若触及 QSS，追加 `tests/ui_kit/test_qss_border_shorthand.py`。
- 对标签和面板做真实 Qt 绘制像素检查：常规与高 DPI、单/双游标、full/mini、长名与中文、边缘/密集位置；不能只检查 `QTextDocument` 或 CSS token。
- Focused/offscreen 通过后，补一次 macOS Cocoa 前台截图/拖放检查。Windows source 与 Full/Lite frozen 在对应环境分别记录，未运行即为 `UNVERIFIED`。
- 文档阶段仅检查本计划引用、`git diff --check`；本文件不运行产品测试，也不修改产品代码。

## 5. 完成标准

1. `P12·A/B` 不裁字，外框、点击热区、避让宽度一致。
2. 快速 press→release 后位置立即稳定在 release 坐标；没有 panel toggle、回跳、重复求值或重复 dirty。
3. 展开面板的牵引只表明其记录/端点与位置线的关联；双游标无端点歧义；收起或销毁不留图元。
4. 已有 Pin 独立性、full/mini、捕获、身份、View/分屏和数据坐标合同不回退。

## 6. 实施证据

- 已完成 F1/F2：`axis_label_outer_size()` 成为布局和实际标签的共同外框度量；快速 press→release 以 release 坐标补判拖动；展开面板以短生命周期 `PinnedPanelTether` scene item 投影到单端点或中性 A/B 分叉。
- 聚焦回归：`tests/ui/test_pinned_cursor_geometry.py`、`test_pinned_cursor_interaction.py`、`test_pinned_cursor_panels.py`、`test_pinned_cursor_capture.py` 共 **66 passed**。`test_pg_canvas_backref_invariants.py` 与 `test_pinned_cursor_architecture.py` 共 **13 passed**。
- 高 DPI offscreen：`QT_SCALE_FACTOR=2` 下标签外框和 tether 的两项定向用例 **2 passed**。这不是 Cocoa 前台验收的替代品。
