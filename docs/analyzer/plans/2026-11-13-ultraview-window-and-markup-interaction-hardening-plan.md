# UltraView 窗口 / 交互与图片标注编辑器加固计划

- 日期：2026-11-13。
- 状态：**未开始。** 本计划只定义范围、顺序和门禁，没有任何产品代码改动。
- 编写基线：`0614559a`，`app_meta.py` 版本 `v8.4.7`。执行前重新记录 HEAD 与相关文件指纹；
  源码变化后，报告里的行号和数字只能作为参考。
- 设计：`docs/analyzer/specs/2026-11-13-ultraview-window-and-markup-interaction-hardening-spec.md`
  （下称 spec，设计项编号 D-W* / D-U* / D-M*，决策项 Q-*，验收门 G*）。
- 问题与证据：`docs/analyzer/reviews/2026-11-13-ultraview-and-markup-interaction-review.md`
  （下称报告，发现编号 W-* / U-* / M-*）。
- 用户观察：Windows 下 UltraView 打开成 mini 缩略窗口；UltraView 与图片标注很多操作不
  跟手；希望对标 Snipaste。
- 执行方式：默认单负责人顺序实施，每个 Task 独立提交、独立可回退。若并行，只能按 §3.3
  的文件归属拆分，全量门禁由协调者独占。

## 1. 目标、范围与完成口径

### 1.1 用户体验目标

1. UltraView、批处理、图片标注窗口不再以不可用的尺寸出现；再出现异常时日志能说明原因。
2. UltraView 里切走窗口再回来不会卡在平移状态；Shift+滚轮横向滚动；光标和手柄指哪打哪；
   卡片和自由对象拖动时本体跟着手走；自由对象能框选、能成组拖。
3. 24 张卡、几百条笔迹时，缩放、平移、画笔不明显变慢。
4. 图片标注里，绘制工具按下必然画新的；Esc 不会无确认丢掉标注；可以平移；预览与成品
   一致；快捷键提示正确。
5. 第二阶段补齐椭圆、马克笔、马赛克 / 模糊。

### 1.2 初始性能目标

与 spec §2.2 相同。Task 0 用 Windows 基线校准后写回 spec；校准要记录硬件和原因，不能在
不达标后悄悄放宽。

### 1.3 范围限制

- 不改 UltraView 的栅格模型、提交语义、智能布局、多 Board、View 库、导出。
- 不把 `content_minimum` 改回可突破工作区预算的硬 floor；`dialog_geometry.py` 的纯函数
  与两条既有合同测试不动。
- 不做卡片 + 自由对象的混合成组移动、文字旋转、橡皮擦、跨会话颜色记忆。
- 不升版本号；发版另行按版本同步清单处理。
- 历史 spec / plan / review 不回改。

## 2. 已有证据与待确认项

### 2.1 已确认

| 问题 | 证据等级 | 对应 Task |
|---|---|---|
| 0 尺寸的顶层窗口以 160×160 出现；设了 `minimumSize` 则用它（W-1 机制） | X11 真输入、Wine | Task 1 |
| 规划器和工具窗口没有任何下限（W-1、W-2） | 读码 + 实测 `minimumSize()==0×0` | Task 1 |
| 最小化后再打开不还原；不经 close 销毁带走 page（W-4、W-5） | X11 真输入 | Task 3 |
| `changeEvent` 收不到失焦事件，Space 卡住（U-1） | X11 真输入 | Task 4 |
| Shift+滚轮整页跳（U-3） | X11 真输入 | Task 5 |
| 手柄光标只在 1 px 边框更新（U-4） | X11 真输入 | Task 6 |
| 卡片幽灵按栅格跳（U-6） | X11 真输入 + offscreen | Task 7 |
| 自由对象不能框选 / 成组拖 / 拖笔迹与连线；本体不跟手（U-7、U-8） | X11 真输入，真实 coordinator | Task 8 |
| 标注：按在已有标注上变成移动（M-1）；Esc 丢弃（M-2）；无平移（M-3） | X11 真输入 | Task 10、11 |
| 标注：框选、提示、画完不选中、手柄、预览、按钮状态（M-4 … M-9） | X11 真输入 / 读码 | Task 10、12 |
| 标注：窗口固定尺寸、不销毁、可重复打开（M-11、M-12） | X11 真输入 | Task 13 |

### 2.2 只有代理证据，实施前要先复核

| 问题 | 现有证据 | 复核方式 |
|---|---|---|
| 缩放 / 画笔成本（U-10、U-12） | offscreen CPU 代理 | Task 0 在 Windows 真机用 `scripts/probe_ultraview_zoom_spike.py` 及其扩展测帧时间 |
| 平移撞墙（U-11） | offscreen | Task 0 真输入复现 |
| 丢失 release 的残留（U-13）、小文字框手柄（U-14） | 合成事件 / 测试夹具 | Task 5、Task 8 开始前用真输入复现；复现不了就降级为「只加防御性检查」 |
| 另外 3 处 `changeEvent` 同类写法（U-15） | 读码 | Task 4 逐处用 `sendEvent` 验证 |

### 2.3 Task 0 / Task 2 必须补齐

1. mini 窗口在 Windows 上的触发条件（报告 §2.2 的 5 个假设）。
2. Windows 隐藏窗口的真实窗框值，用于 D-W2 的平台估算。
3. Windows 上 24 卡缩放、平移、卡片拖动、画笔的帧时间基线。
4. `camera_settled` 的全部消费者清单（Task 9 的前提）。
5. 在真实 Snipaste 上核对报告 §5 表里涉及手感的条目。
6. 用户对 spec §5 六个决策（Q-1 … Q-6）的选择，以及截图 2 里白色画布对应的源图是什么。

## 3. 必须保持的合同

### 3.1 几何与窗口

- 2026-09-05 spec 的 C04：先内容最小尺寸，再按工作区约束，窗框不出工作区。
- `test_client_budget_never_negative_on_empty_or_tiny_work_area` 与
  `test_constrain_does_not_use_max_of_floor_and_cap` 原样通过。
- Board page 任一时刻只有一个 owner；cached Qt wrapper 复用前检查 `sip.isdeleted()`。

### 3.2 UltraView 交互

- 卡片移动 / 缩放的提交语义、planner 调用条件、overlay 脏区规则不变。
- 身份用复合 source / channel 或对象 id，不用显示名。
- 停手后的画质不降低；不引入固定延时。

### 3.3 状态、分层与并行时的文件归属

- 状态所有权棘轮、`.connect(lambda` 棘轮、UI 三层分层、QSS border 简写、UltraView 生命周期
  棘轮的白名单都不扩大。
- 需要并行时按下表拆分，`page.py`、`free_grid_board.py`、`markup/editor.py` 各自只归一个
  执行者，按 Task 顺序串行交接：

| 文件组 | Task |
|---|---|
| `ui_kit/dialog_geometry.py`、`ui_kit/layout_diagnostics.py`、`drawers/batch/_geometry.py`、`drawers/ultraview/sheet.py` | 1、3 |
| `chart_stack/ultraview/page.py`、`viewport_router.py`、`viewport_controller.py` | 4、5、9 |
| `chart_stack/ultraview/free_grid*.py`、`gesture.py`、`ghost_overlay.py`、`card_widgets.py` | 6、7 |
| `chart_stack/ultraview/free_grid_author_controller.py`、`author_*.py` | 8、9（笔迹缓存） |
| `ui/markup/*`、`ui_kit/style.qss` 的标注段 | 10 … 14 |

### 3.4 测试命令与门禁口径

聚焦用例统一用：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <owner 用例> -q
```

- 每个 Task 的改前基线 = 该 Task 列出的 owner 用例，**不跑全量**。
- 全量只在 Task 15 的合并验收跑一次，由协调者独占：先 `pgrep -fl pytest`，记录 HEAD 与
  脏文件范围，主体 `--ignore=tests/acquisition_ui` 跑完后另起进程单跑该目录，串行、前台。
- offscreen 通过不等于交互验收通过；每个交互 Task 都有一条真输入复核。

## 4. Task 0：准备（不改产品代码）

**内容：**

1. 把本轮一次性探针整理入库：`scripts/probe_tool_window_geometry.py`（打开 UltraView /
   Batch / 标注窗口并输出各时刻尺寸与屏幕事实，可在 Windows 源码环境和冻结包旁运行）、
   `scripts/probe_ultraview_interaction.py`（真输入场景：失焦、滚轮、手柄光标、卡片拖动、
   自由对象选择）、`scripts/probe_markup_interaction.py`。探针不是产品代码，写清适用的
   证据等级。
2. 盘点 `camera_settled` 消费者、`_apply_lod_chrome` 的调用点、标注编辑器的全部入口。
3. 在真实 Snipaste 上核对报告 §5；把与文档不一致的条目回写到报告。
4. 向用户确认 Q-1 … Q-6 与截图 2 的源图。未确认的项按 spec 默认方案执行，并在提交说明里
   写明。

**验证：** 纯探针与文档，不改变运行时行为，不需要运行时测试；探针各自带 `--help` 与一次
offscreen 自检即可。`git diff --check`。

## 5. Task 1：工具窗口下限与几何诊断（D-W1、D-W3）

**先做这一项，可以单独发布。** 它不依赖 Windows 触发条件。

**改动：** `ui_kit/dialog_geometry.py`（不可信工作区回退、`apply_plan` 拒绝退化规划、
`_shrink_unaccounted_frame` 下限）、`ui/drawers/batch/_geometry.py`（规划后设
`minimumSize`、被拒绝时的回退尺寸）、`ui/drawers/ultraview/sheet.py` 与 `BatchSheet`
（显示后校验一次）、`ui_kit/layout_diagnostics.py`（工具窗口规划记录）。

**先写失败用例：**

- 可用矩形为 0×0、10×10、319×239 时，`UltraViewSheet` 显示后客户区 ≥ 下限（改前得到
  160×160 或更小）。
- `apply_plan` 对带标题栏的顶层窗口不应用任一维 < 200 的规划；对 popover / 内嵌浮层
  照常应用。
- 显示后 `minimumSize()` 非零，窗口不能被 `resize(50, 50)` 缩到下限以下。
- 强制把窗口在显示前置为 0×0，显示后的校验把它恢复并留下 `recovered` 日志。

**Owner 用例：** `tests/ui_kit/test_dialog_geometry.py`、
`tests/ui/test_tool_window_screen_fit.py`、`tests/ui/test_dialogs.py` 中与 Batch / UltraView
相关的用例。

**边界护栏：** `tests/ui/test_import_boundaries.py`（`ui_kit` 不得 import `ui`）、
`tests/ui/test_no_lambda_signal_connections.py`。

**真输入复核：** X11 下 `probe_tool_window_geometry.py` 打开 20 次；Wine 下复跑报告 §2.1
的四行表，确认设了 `minimumSize` 后 0 尺寸创建也得到下限尺寸。Windows 真机留给 Task 2。

**完成口径：** 上述用例通过；两条既有合同测试未改动且通过。

## 6. Task 2：Windows 真机诊断与标定

**前提：** Task 1 的构建。**这一项需要 Windows 机器，执行环境没有时如实记为未做。**

1. 用户机器（或同配置机器）设 `TRACELAB_LAYOUT_DIAGNOSTICS=1` 运行，按 spec G3 的矩阵
   打开窗口，收集诊断日志；重点看是否出现「不可信工作区」「退化规划」「recovered」。
2. 按报告 §2.2 的 5 个假设逐个构造：显示器热插拔、远程桌面重连、休眠唤醒、双屏不同
   缩放、父窗口最小化 / 最大化。记录每种情况下的规划输入。
3. 测 Windows 100% / 125% / 150% 下隐藏窗口与显示后窗口的窗框值。
4. 测 24 卡缩放、平移、卡片拖动、画笔的帧时间基线，写回 spec §2.2。

**交付：** `docs/analyzer/verify/` 下一份诊断记录（环境、日志摘录、结论）。找到触发条件
就把它补进报告 §2 并加一条对应的回归用例；找不到也要记录已排除的假设。

**验证：** 纯测量与文档，不需要运行时测试。

## 7. Task 3：显示、还原与销毁（D-W2）

**改动：** `sheet.py`（nudge 条件、`release_page`、`DeferredDelete`）、
`batch/_geometry.py`（再次打开清最小化）、`dialog_geometry.py::frame_insets_of`
（平台估算，用 Task 2 的数值）、`ui/main_window/window.py::_alive_tool_dialog`。

**先写失败用例：** spontaneous 的 `showEvent` 不调用 nudge；最大化状态不被 nudge 改尺寸；
最小化后再次 `open_ultraview()` 窗口不再是最小化；sheet 经 `deleteLater`（不经 close）
销毁后，page 存活并回到 stack；归还失败时有 warning。

**Owner 用例：** `tests/ui/test_tool_window_screen_fit.py`、
`tests/ui/test_ultraview_mode_integration.py`。

**边界护栏：** `tests/ui/test_main_window_state_ownership.py`、
`tests/ui/test_ultraview_lifecycle_ratchet.py`、`tests/ui/test_no_lambda_signal_connections.py`。

**真输入复核：** X11 下最小化 → 再打开；Windows 真机进 G3。

## 8. Task 4：失焦清理走真实事件路径（D-U1）

**改动：** `page.py`（清理函数、删除 `changeEvent` 分支、修注释）、`viewport_router.py`
（生效判定加窗口激活）、`viewport_controller.py`、以及 `segmented_choice.py`、
`view_tabbar.py`、`motion_demo.py` 三处同类写法。

**先写失败用例：** 用 `QApplication.sendEvent(page, QEvent(QEvent.WindowDeactivate))`：
Space 按下状态被清、平移 / 拖动 / 框选被取消、光标复位。把
`tests/ui/test_ultraview_page.py` 里直接调 `changeEvent` 的用例改成同样的投递方式（改前
应当失败）。新增源码扫描用例：`mf4_analyzer/` 内 `changeEvent` 函数体不得出现
`WindowActivate` / `WindowDeactivate`。

**Owner 用例：** `tests/ui/test_ultraview_page.py`、`tests/ui/test_ultraview_viewport_router.py`、
`tests/ui/test_ultraview_viewport_controller.py`、`tests/ui/test_ultraview_author_text_slice.py`
（已有的 `sendEvent` 失焦用例）、三处同类控件各自的用例。

**边界护栏：** `tests/ui/test_ultraview_lifecycle_ratchet.py`、
`tests/ui/test_import_boundaries.py`（动了 `ui_kit` 控件）。

**真输入复核：** 报告 U-1 的步骤（按住 Space → 切窗口 → 松开 → 切回 → 空白处左键拖动）
得到框选而不是平移。

## 9. Task 5：滚轮语义与手势健壮性（D-U2、D-U7）

**改动：** `viewport_router.py`、`viewport_controller.py`、`gesture.py`、`card_widgets.py`、
`pointer_router.py`。

**先做：** 用真输入复现 U-13 的四种情况；复现不了的只加「移动时检查按键」的防御，不扩大
改动。

**先写失败用例：** Shift+滚轮改变横向滚动条、纵向不变；触控板像素增量双向滚动；手势中
收到无按键的移动事件后手势被取消、模型未改变；左键手势中右键按下取消手势。

**Owner 用例：** `tests/ui/test_ultraview_viewport_router.py`、
`tests/ui/test_ultraview_viewport_controller.py`、`tests/ui/test_ultraview_gesture_preview.py`、
`tests/ui/test_ultraview_card_actions.py`。

**边界护栏：** `tests/ui/test_ultraview_lifecycle_ratchet.py`。

**真输入复核：** X11 下 Shift+滚轮一格的横向位移等于普通滚轮一格的纵向位移。

**同步：** `ui/hints.py`、`ui/quickref.py` 增加 Shift+滚轮；跑 `tests/ui/test_hints.py`、
`tests/ui/test_quickref.py`。

## 10. Task 6：手柄与悬停光标（D-U3）

**改动：** `free_grid.py`（命中带几何）、`free_grid_board.py`（悬停解析、光标单点设置）、
`ghost_overlay.py`（手柄位置）、`viewport_router.py`（转发无按键移动）。

**先写失败用例：** 指针直接出现在选中卡片边缘内侧 4 px（不经过边框）时光标为对应的缩放
光标；移到卡片中心后恢复；可见手柄矩形的四个角点都命中缩放；选中卡片外侧 6 px 内按下
开始缩放而不是框选；缩放 0.25 下角点仍可命中。

**Owner 用例：** `tests/ui/test_ultraview_free_grid.py`、`tests/ui/test_ultraview_card_actions.py`、
`tests/ui/test_ultraview_feedback.py`。

**边界护栏：** `tests/ui/test_ultraview_lifecycle_ratchet.py`。

**真输入复核：** 报告 U-4 的步骤，八个方向各一次。

## 11. Task 7：卡片拖动的两层反馈（D-U4）

**前提：** Q-3 已确认或采用默认方案。

**改动：** `free_grid_feedback.py`、`gesture.py`、`ghost_overlay.py`。

**先写失败用例：** 以 1 px 步长拖 60 px，幽灵位置序列逐像素变化且与指针的偏移恒定；
落点轮廓仍按栅格变化；越过阈值的第一帧幽灵位置 = 卡片原位置 + 已移动量；松手后的
提交结果与改前一致（用改前的行为快照冻结）。

**Owner 用例：** `tests/ui/test_ultraview_feedback_pipeline.py`、
`tests/ui/test_ultraview_gesture_coalesce.py`、`tests/ui/test_ultraview_gesture_preview.py`、
`tests/ui/test_ultraview_free_grid.py`。

**边界护栏：** `tests/ui/test_ultraview_lifecycle_ratchet.py`。

**真输入复核：** X11 下报告 U-6 的测量，幽灵与指针距离 ≤ 1 px；真机帧时间进 G4。

## 12. Task 8：自由对象的选择与移动（D-U5）

**前提：** Q-4、Q-5 已确认或采用默认方案；U-14 先用真输入复现。

**改动：** `free_grid_author_controller.py`、`author_tools.py`、`gesture.py`、
`author_layer.py`、`author_geometry.py`（容差）、`ui/main_window/ultraview_coordinator.py`
（成组提交为一个撤销步）。分四个可独立提交的小步：框选 → 成组移动 → 笔迹 / 连线移动 →
本体跟手与容差。

**先写失败用例：** 框选圈住 5 个自由对象后全部选中；多选后拖其中一个，全部移动相同
位移、选择不塌、撤销一次全部回位；笔迹主体拖动后全部点平移；有吸附端点的连线拖主体
不移动并发出反馈；拖动中绘制层拿到的预览几何随指针逐像素变化；缩放 0.5 / 1 / 2 / 3 下
拾取容差相同（±1 px）。

**Owner 用例：** `tests/ui/test_ultraview_author_multiselect.py`、
`tests/ui/test_ultraview_author_tools.py`、`tests/ui/test_ultraview_author_draw_slice.py`、
`tests/ui/test_ultraview_author_connector_slice.py`、`tests/ui/test_ultraview_author_geometry.py`、
`tests/ui/test_ultraview_author_layer.py`、`tests/ui/test_ultraview_author_integration.py`。

**边界护栏：** `tests/ui/test_main_window_state_ownership.py`、
`tests/ui/test_ultraview_lifecycle_ratchet.py`、`tests/ui/test_no_lambda_signal_connections.py`。

**真输入复核：** 报告 U-7、U-8、U-9 的步骤，使用真实 `MainWindow` 与真实 coordinator
（测试夹具里的假 sink 不算）。

**同步：** `ui/hints.py`、`ui/quickref.py`。

## 13. Task 9：每个输入事件的工作量有界（D-U6）

**前提：** Task 0 的消费者清单、Task 2 的 Windows 基线。没有 Windows 基线时只做有明确
逻辑依据的三项（`persist` 合并、`_sync_metrics` 去重、LOD 按档位），其余等基线。

**改动：** `viewport_controller.py`、`page.py`、`free_grid_board.py`、`author_layer.py` /
`author_render.py`。分五个可独立提交的小步，对应 spec §3.9 的五条。

**先写失败用例：** 一次缩放手势（N 个滚轮事件 + 停手）中 `camera_settled` 恰好发 1 次、
`persist` 恰好 1 次、每个事件 `_sync_metrics` ≤ 1 次；LOD 档位不变时 `_apply_lod_chrome`
不遍历卡片；连续平移 3000 px 不撞墙且原点稳定；已提交笔迹不变时重绘不重新投影（按调用
计数断言，不按耗时）。

**Owner 用例：** `tests/ui/test_ultraview_viewport_controller.py`、
`tests/ui/test_ultraview_page.py` 的缩放与 LOD 段、`tests/ui/test_ultraview_author_layer.py`、
`tests/ui/test_ultraview_author_render.py`、`tests/ui/test_ultraview_author_draw_slice.py`。

**边界护栏：** `tests/ui/test_ultraview_lifecycle_ratchet.py`、
`tests/ui/test_main_window_state_ownership.py`（动了 coordinator 接线时）。

**真机复核：** `scripts/probe_ultraview_zoom_spike.py` 及 Task 0 的扩展，在 Windows 与
Cocoa 上对比改前改后；offscreen 的计数用例只证明「工作量有界」，不证明帧时间。

## 14. Task 10：标注按下分派、活动项与 Esc（D-M1、D-M2）

**前提：** Q-2 已确认或采用默认方案。

**改动：** `ui/markup/view.py`、`ui/markup/editor.py`、`ui/markup/toolbar.py`（关闭按钮
提示）。

**先写失败用例（都用视口坐标的真实鼠标 / 键盘事件驱动）：** spec §3.11 的表逐格断言，
重点是箭头 / 序号 / 文字 / 画笔在空心矩形内部按下会产生新标注且矩形不动；选择工具在
空白处拖动能框选；画完的项自动选中并有手柄，下一次按下画新的；右键结束活动项。Esc
逐级退出；有标注时 Esc 到最后一级出现确认，选「取消」标注仍在，选「放弃」`on_done`
不被调用，选「完成复制」`on_done` 被调用一次；无标注时 Esc 直接关闭；Ctrl+Enter 完成
复制；单独 Enter 仍只确认裁剪。

**Owner 用例：** `tests/ui/test_markup_editor.py`、`tests/ui/test_markup_handles.py`、
`tests/ui/test_markup_toolbar_wiring.py`。

**边界护栏：** `tests/ui/test_import_boundaries.py`、
`tests/ui/test_no_lambda_signal_connections.py`。

**真输入复核：** 报告 M-1、M-2、M-4、M-6 的步骤。

**同步：** `ui/hints.py`（`markup.capabilities`）、`ui/quickref.py` 的标注段。

## 15. Task 11：标注缩放与平移（D-M3）

**前提：** Q-1 已确认或采用默认方案。

**改动：** `ui/markup/view.py`。

**先写失败用例：** 中键拖动与 Space+左键拖动的滚动量等于指针位移；Space 按下时左键不
创建标注；Shift+滚轮横向平移；放大到有滚动余量后，每格滚轮前后指针下的场景点屏幕位置
偏差 ≤ 1 px。先单独测「适应窗口」状态下的漂移是否来自滚动范围钳制，结论写进提交说明。

**Owner 用例：** `tests/ui/test_markup_editor.py`。

**真输入复核：** 报告 M-3 的步骤。

**同步：** `ui/hints.py`、`ui/quickref.py`。

## 16. Task 12：标注提示、手柄、预览、按钮状态与样式（D-M4）

**改动：** `ui/markup/toolbar.py`、`editor.py`、`view.py`、`handles.py`、`ui_kit/style.qss`。

**先写失败用例：** 每个工具的提示按键 == 实际切换到该工具的按键（改前「选择」失败）；
缩放 0.25 / 1 / 4 下手柄的屏幕尺寸相同；箭头预览带箭头头部、预览笔为实线且线宽颜色
等于成品；选中与悬停按钮的渲染像素不同；线宽被限制在 1–24；自定义颜色应用到新标注。

**Owner 用例：** `tests/ui/test_markup_toolbar_wiring.py`、`tests/ui/test_markup_handles.py`、
`tests/ui/test_markup_editor.py`。

**边界护栏：** `tests/ui_kit/test_qss_border_shorthand.py`、
`tests/ui/test_no_lambda_signal_connections.py`。

**真输入复核：** 真实渲染截图对比选中 / 悬停 / 普通三态；offscreen 像素断言不能当作
前台外观验收。

## 17. Task 13：标注窗口与生命周期（D-M5）

**改动：** `ui/markup/editor.py`、`ui/main_window/window.py`（`_open_markup_editor`）。

**先写失败用例：** 400×300 的图打开后缩放为 1.0；3840×2160 的图打开后窗口不超出工作区
且缩放为适应值；关闭后编辑器被销毁、`MainWindow` 句柄清空；已有编辑器且有未完成标注
时再次进入先出现确认；窗口获得 Task 1 的最小尺寸。

**Owner 用例：** `tests/ui/test_markup_editor.py`、`tests/ui/test_tool_window_screen_fit.py`。

**边界护栏：** `tests/ui/test_main_window_state_ownership.py`、
`tests/ui/test_no_lambda_signal_connections.py`。

## 18. Task 14：对标 Snipaste 的工具补齐（D-M6，第二阶段）

**前提：** Task 10 … 13 已验收；Q-6 已确认；Task 0 的 Snipaste 实机核对已完成。

**改动：** `ui/markup/items.py`、`commands.py`、`serialization.py`、`thumbnail.py`、
`toolbar.py`、`view.py`。每个工具一个提交：椭圆 → 马克笔 → 马赛克 / 模糊。

**每个工具的用例：** 绘制、选中、调整、撤销 / 重做、序列化往返、缩略图、导出像素、
快捷键表条目。

**Owner 用例：** `tests/ui/test_markup_editor.py`、`tests/ui/test_markup_serialization.py`、
`tests/ui/test_markup_toolbar_wiring.py`、`tests/ui/test_markup_handles.py`。

**边界护栏：** `tests/ui_kit/test_qss_border_shorthand.py`、`tests/test_packaging_imports.py`
（新增模块时）。

**同步：** `ui/hints.py`、`ui/quickref.py`，以及帮助页里标注相关的说明。

## 19. Task 15：最终验收与文档

1. 复跑各 Task 的 owner 用例与触及的边界护栏。
2. 按 spec §6 逐门记录：G1（offscreen）、G2（真输入）、G3 / G4（Windows 真机）、
   G5（Windows frozen）、G6（用户确认）。没做的门记 `UNVERIFIED`，不能用别的门替代。
3. 合并验收需要全量时，由协调者按 §3.4 跑一次；见红先对照
   `docs/analyzer/reviews/2026-08-15-post-v8-batch-review.md` §6 的既有红清单。
4. 把执行结果、真机读数和未完成项写到 `docs/analyzer/verify/`，并更新 spec 状态行与
   本计划状态行。

**验证：** 文档部分只做范围、引用、一致性和 `git diff --check`。

## 20. 实施顺序与回退

推荐顺序：Task 0 → 1 →（2 与 4 可并行，2 需要 Windows）→ 3 → 5 → 6 → 10 → 11 → 12 →
13 → 7 → 8 → 9 → 14 → 15。

- Task 1 最先，它直接针对用户报告的 mini 窗口，且不依赖任何未知条件。
- Task 4、5、6、10 是逻辑缺陷，改动小、收益确定，排在跟手性重构（7、8、9）之前。
- Task 7、8、9 改的是热路径，各自需要真机帧时间，放在逻辑缺陷之后。
- 每个 Task（以及 Task 8、9、14 内的每个小步）单独提交，出问题按提交回退。

## 21. 交付物与依据

- 报告、spec、本计划（本次提交）。
- Task 0 的三个探针脚本；Task 2 的 Windows 诊断记录；Task 15 的验收记录。
- 本计划自身是纯文档，只做范围、引用、一致性和 `git diff --check` 检查，不因文档新增
  运行 runtime suite。
