# TraceLab 跨平台提示框与弹层布局实施 Plan

日期：2026-09-05 · 修订：R1 · 状态：**文档就绪；产品实现进行中。T5 批量消息框迁移需等 G3/G4 示范通过。**

目标合同：[配套 Spec](../specs/2026-09-05-cross-platform-dialog-layout-spec.md)。问题入口、源码定位与历史探针：[审查报告](../reviews/code-reviews/2026-09-05-windows-dialog-layout-audit.md)。当实现与旧审查不一致时，重新核对当前源码，不根据历史行号机械修改。

## 1. 执行边界与核心决策

1. 采用自有 `AppMessageDialog` 布局解决消息框比例，使用 QDialogButtonBox 保留平台顺序；不修改 Qt 私有网格、不全局替换 QMessageBox 类。
2. 共享屏幕几何计算只有一个所有者；内容滚动和窗口生命周期仍由各窗口负责。正常屏幕不做布局重设计，不批量删除固定尺寸。
3. 消息框从未保存项目这个示范入口开始，Cocoa/Windows 原生验证通过后再扩大迁移。已确定的 P1 窗口问题无需等待用户提供旧 Windows 包。
4. Windows 100% 是首个实机门禁；没有 Windows 环境时完成可验证代码和本地测试，明确停在跨平台验收前，不能用 Mac offscreen 填绿。
5. 不碰 Auto-NFFT、数值实现、无关 AGENTS.md/CLAUDE.md、历史资产删除；不顺带升级 Qt、改系统缩放或发布版本。

**台账与证据不是实施授权。** 用户后续要求按计划执行时才开始产品代码；本计划不创建任务、agent 或自动化。默认一个实施者按依赖执行，集成/全量验收由一个负责人持有，避免并发改共享 QSS 或重叠全量测试。

## 2. 所有者与新增文件

完整路径相对仓库根；省略包前缀的 `ui/`、`ui_kit/`、`app.py` 等路径相对 `mf4_analyzer/`，连续简写文件沿用前项目录。“新增”表示当前尚不存在，不应被当作现有能力。

| 所有者 | 文件范围 | 边界 |
|---|---|---|
| 几何核心 | 新增 `mf4_analyzer/ui_kit/dialog_geometry.py`；既有 `ui/drawers/batch/_geometry.py` | 可测试的预算/定位 + 薄 Qt 取屏层；保留旧 helper 导出，不移动独立工具窗的 z-order 逻辑 |
| 消息框核心 | 新增 `mf4_analyzer/ui_kit/message_dialog.py`；既有 `message_box_buttons.py`、`dialog_button_defaults.py` | 展示/结果所有者；业务动作仍在调用者 |
| 共享视觉 | `ui_kit/control_style.py`、`style.qss`、`stylesheet.py`，必要时 `ui_kit/__init__.py` | 复用现有 token/加载入口，新增选择器限定新组件，不覆盖通用 QDialog 下全部按钮 |
| 布局诊断 | 新增 `ui_kit/layout_diagnostics.py`、`ui/layout_probe.py`；`app.py` 的显式诊断入口 | ui_kit 不导入上层 UI；实际窗口探针工厂在 ui 层，Cockpit lazy import；现有 diagnostics logger 不反向依赖 Qt |
| 具体界面 | §5 中各所属文件 | 不跨入 MainWindow 业务状态/数据计算重构 |
| 冻结包 | `tools/build_windows_folder.ps1`、`tools/build_windows_folder_lite.ps1` | 同一构建来源、必要的新入口收集/元数据；不做无证据的 DPI manifest 改动 |
| 文档与验收 | 本 Spec/Plan；实现后新增 verify 记录和迁移台账 | 临时截图/JSON 在 `.state/`，不默认提交生成物 |

新模块只在责任确实分离时创建，不再添加第二个 prompt service、全局窗口管理器或平行字体策略。新增公开导出必须同步消费者、测试和必要的 frozen 收集规则。

## 3. 依赖图与阶段退出

```text
T0 当前入口/语义盘点与针对性失败用例
 └─ T1 几何核心、诊断及组件合同
     ├─ T2 三类 P1 窗口修复
     ├─ T3 AppMessageDialog + 未保存项目示范
     │    └─ G3/G4 示范真实双平台对照
     │         └─ T5 同步消息框迁移 → T6 Cockpit 非阻塞迁移
     └─ T4 其他弹层、表单与已有防护补齐
          （与 T5/T6 的共享文件变更顺序整合）
T2 + T4 + T5 + T6 → T7 Full/Lite 冻结验收与台账闭环
```

T1–T4 可在未获取旧异常包时推进。没有 Windows 实机时，T3 的代码可准备好，但不能跨过 G4 批量迁移消息框；仍可推进独立的 T2/T4。一个稳定集成里程碑只跑一次全量门禁；出现新代码/失败/污染证据后才决定是否重跑。

## 4. 详细任务

### T0 — 核对当前调用者，冻结语义并补失败条件

**输入**：Spec C01–C12、审查报告、当前 git/worktree；参考 lessons：

- `docs/lessons-learned/codex-qmessagebox-qss-content-width.md`
- `docs/lessons-learned/pyqt-dialog-scroll-keeps-actions-visible.md`
- `docs/lessons-learned/codex-dialog-toolbutton-chrome-spares-search-field.md`

**产出**：实现时新增 `docs/analyzer/verify/2026-09-05-cross-platform-dialog-layout/migration-ledger.md`，记录每个 `module/owner/prompt_id`、同步/异步方式、按钮角色与返回映射、默认/退出动作、checkbox/详情、原测试注入点、目标阶段、状态和证据。原先 77 个消息入口按附录 A 的模块清单重新发现；文件/输入/弹层另行登记。

先记录 HEAD、dirty scope 与相关文件 fingerprint。共享工作区存在其他任务时，不用未提交总数判断本任务范围，不覆盖它们的修改；若目标文件正被修改，先隔离已知快照或等待该文件稳定再编辑/验收。

将审查临时探针中的失败输入转为所属模块的回归用例；只跑该用例及所需 owner 基线，不跑全量预检。必要失败用例：

- 12px 初测按钮后变 24px；检查实际文字需求与外框 padding/border，不能只比较 contentsRect。
- 64 字符主体、180 UTF-8 字节的中文文件名；长英文无空格路径也要测。
- BatchPreview 0/1/30/100 条不同警告，内容更新后 footer 不被推走。
- 配置管理器在 800×600、640×360 的可用工作区，正文可滚动且保存/关闭可达。
- CursorDisplayPopover 在工作区右下角，首次与延迟 refit 后都在屏内。
- 核对未保存项目的 Enter/Escape/关闭/保存失败/重复关闭，以及 Cockpit 的非阻塞 open。

**退出**：核心失败有确定性 probe 或红测试；每个计划迁移的业务返回合同可追踪。没有 Windows 用户包只登记外部证据缺失，不阻塞这些本地工作。

### T1 — 共同几何、诊断与可测试的 UI 合同

**文件**：§2 中几何核心、布局诊断；新增 `tests/ui_kit/test_dialog_geometry.py`、`tests/ui_kit/test_layout_diagnostics.py`、`tests/ui/test_layout_probe.py`。

1. 实现纯矩形预算与定位部分：锚点屏/parent 屏/自身屏、负坐标、框架边距、宽高 cap、上下翻转、最终 frame containment；异常空 rect 不产生负宽高。
2. 建立明确的窗口 fit 调用协议。先让 owner 把内容变得可滚动/换行，再设置尺寸；兼容 batch helper 的原签名和可调整窗口语义。旧 helper 只转发共同计算，原 transient-parent 清理仍留在原处。
3. 设置实例级合并重排，测试销毁前挂起回调、断屏、反复开关与静止收敛。不要添加全局 resize filter；不要在 helper 中用 broad except 隐藏编程错误。
4. 诊断值由 ui_kit 收集后交给现有 logger，使用 prompt_id 而非完整业务文案。元数据打印一次；详细布局需显式启用，不改变普通启动流程。
5. 增加 `TRACELAB_LAYOUT_PROBE=1` 诊断模式：在已有 QApplication/Fusion/QSS 完成后，调用 `ui/layout_probe.py` 的演示工厂；独立临时设置命名空间、合成数据，不打开用户项目、不执行真实保存/删除/采集。从源码和 Full/Lite exe 均能生成 JSON/截图；Lite 不导入 acquisition_ui。完整字体或截图信息只在这个显式模式收集。

**测试**：注入 `QRect(0,0,800,600)`、`QRect(-1280,0,1280,680)`、有标题栏和无边框、parent 部分离屏；验证同一输入稳定。真实 shown widget 再验证 frame 校正，区分 offscreen 装饰和 Windows 装饰。诊断序列化失败不能阻断正常应用；程序错误不能悄悄吞掉。

**退出**：C04/C06/C07 的 owner 测试通过；诊断模式不读取真实 QSettings、不改变普通用户缩放。当前 `app.py` 高 DPI 策略不变。

### T2 — 优先修复操作不可达的 P1

**T2a BatchPreviewDialog**：将 facts/warnings/status 从无界顶部堆叠改成有限可滚动正文；图片区域仍可正确缩放/查看，动作区独立。不能通过删除警告或减小字体使测试通过。0→100→0 的变化必须释放旧 minimum，窗口回到可用范围且不反复跳动。

**T2b ChannelConfigManagerDialog**：保留正常工作区的 1180×680 偏好，解除超屏 940×680 硬 floor；适配外壳与正文/表格可滚动约束，不重写配置业务。将三个内联框纳入同一预算；复用既有默认键 helper、搜索图标特例。保存更改、关闭在紧凑布局仍可见；草稿保存一次/取消不写入的合同不变。

**T2c CursorDisplayPopover**：位置依据当前锚点和最终内容高度；先下方、再上方、再 clamp。现有延迟 refit 必须触发位置修正，不再只 resize；宿主消失时不留悬空弹层。

**聚焦测试**：

- `tests/ui/test_batch_preview_dialog.py`
- `tests/ui/test_channel_config_manager.py`、`tests/ui/test_channel_config_transfer.py`
- `tests/ui/test_cursor_display_settings.py`
- `tests/ui_kit/test_search_field.py`（管理器 QSS/外壳变化时）

**退出**：生产 QSS 的实际 widget 几何/截图证明 P1 失败输入已关闭；正常工作区结构无回归；Spec S02/S03/S07 的对应部分有证据。

### T3 — 新消息框组件与未保存项目示范

**文件**：`ui_kit/message_dialog.py`、相关局部 token/QSS、`ui/main_window/_project_io_mixin.py` 中示范入口；新增 `tests/ui_kit/test_message_dialog.py`。

1. 落实 Spec §3 的字段、动作映射、默认/退出、滚动正文、横/纵动作与多行标签。非关闭动作和终态结果走分开的通知路径；一个关闭动作只能提交一次结果。结果构造错误直接报错，不变成默认同意；默认动作禁用时 Enter 不自动选择其他动作。
2. 用现有 base=32 轨道做同排高度；主文案加粗、局部留白及警告/危险/中性颜色符合 Spec。新的选择器不影响普通 QMessageBox、搜索 18×18 图标、View 28×28 控件或 Batch 原有 CTA。
3. `_prompt_unsaved_project()` 仍对 dirty guard 返回 `save/discard/cancel`。仅在展示边界适配新组件，不改项目保存函数、dirty holder 或关闭事务。原 builder 若仍被消费，保留其可验证 seam 或在同一补丁迁移全部消费者。
4. 覆盖真实 Enter、Escape、标题栏关闭、点击各按钮、保存失败/另存为取消、重复 close。断言安全结果与业务调用次数，不用按钮索引或 bool 来判断。
5. 保留的 QMessageBox helper 单独补 polish 后测宽、字体变化后的几何失效与 stylesheet 保留测试；它的修复不当作新消息框的跨平台外观验收。

**聚焦测试**：新 message_dialog/geometry；`tests/ui/test_message_box_buttons.py`；`tests/ui/test_project_dirty_guard.py`（优先对应 prompt/close/save-failure 测试，集成后跑该 owner 文件）；`tests/ui/test_project_session.py` 的相关 guard 用例。QSS 改动还跑 §7 的共同门禁。

**示范实机门禁**：同一文案、3 按钮、普通字体及 24px 压力，各捕获真实 Cocoa 与一个 Windows 10 或 11 原生 100% 环境的客户区/frame/按钮 rect 和截图。验收留白协调、文字完整、主操作不贴边，不要求 Mac/Windows 原生标题栏和按钮顺序像素一致。这个示范子集通过允许扩大迁移，但不能标记全部 G3/G4 矩阵通过。没有 Windows 时标为 `示范代码完成，G4 UNVERIFIED`，不继续批量消息框迁移。

### T4 — 其他窗口/弹层及已有防护补齐

按 §5 的 S04–S15 分组实施，每组先有失败探针或明确合同检查。不能为了复用强迫所有 owner 使用同一种显示/关闭策略。

- Batch/UltraView 工具窗：采用共同几何，保留非模态、清理 transient-parent 及 Board 自己的 fit。测试常规打开只触发必要的一次页面 fit，不因窗口校正重复计算 Board 布局。
- 重建时间轴：目标名换行/完整访问、动作同高，外层适配；保留 `Qt.Dialog` 和 accept/WindowDeactivate race 防护，不能换成 Qt.Popup 省事。
- 导出与通道编辑 drawer：屏幕约束在外层，滚动在内层；原内层接受/拒绝信号转发一次。
- 帮助/QuickRef/Cockpit 表单：正文滚动、头尾可见；紧凑模式不把关闭按钮滚走。
- tooltip/hovercard：宽度先受限再计算高度，最后屏边定位；摘要不能覆盖原完整 toolTip 数据，唯一全文需有交互访问位置。普通路径不随意截掉，只在预算确实不足时降级。
- 刻度密度与菜单内列表：使用最终几何翻转、列表滚动；验证点击外部、Esc、菜单嵌套与父关闭，不能留 stale popup。
- 已有 Recent/View/SignalPicker/RenderStyle/Flyout 防护：添加针对性用例，失败才修改。内嵌 flyout 单独按宿主局部坐标测试。
- 输入/文件选择/系统菜单/主窗口：作实际小屏/多屏检查，若通过登记 `retained_verified`；若失败，补所属模块测试再做最小修复。不能仅凭初始 resize 数字扩大到主窗口重构。

**退出**：S04–S15 每行有通过/保留/外部阻塞的明确结论；只能把有证据关闭的条目标完成。

### T5 — 同步应用消息框迁移

**前置**：T3 示范的 G3/G4 通过。按附录 A 的 M1–M4 分小批迁移，不机械全局替换字符串。

每个入口步骤一致：确认旧角色/按钮值/返回分支 → 用新组件构建 → 在原业务封装边界转换结果 → 更新该入口真实测试及注入 seam → 生产 QSS 渲染/owner 回归 → 台账附证据。保持业务文案、条件和副作用不变；字符串不能替代 composite file/channel identity。

优先迁移文件关闭/解绑/配置覆盖/BLF-DBC 多选确认，再处理普通通知与错误提示。所有标准结果显式映射，不能用 `QDialog.Accepted` 代替原 QMessageBox 标准值。需要详情、多个接受动作或不同退出映射的入口单独测试。

**门禁**：相应 owner 的测试见附录 A。新增 `tests/ui/test_message_dialog_migration.py` 做 AST 调用台账检查：已迁移 owner 不得重新引入裸 QMessageBox；保留项需精确到 owner 并有理由。禁止宽泛目录豁免、魔法总数量白名单或因数字少了就视为迁移完成。

**退出**：M1–M4 所有入口的组件与业务返回合同有对应证据；没有隐藏 pending。

### T6 — Cockpit 非阻塞消息与输入兼容

**前置**：T3 示范通过，组件的 `open()`、一次性结果提交和父销毁测试通过。见附录 A 的 M5。

保留 connection/A2L/dropped-frame/review 的 window-modal `open()`、持有引用和替换策略；不使用 `exec_()` 阻塞采集线程交互。尤其覆盖：确认删除点击导致父 review 关闭、A2L 连续打开替换旧框、停止录制/父窗口关闭期间消息框仍在、dropped-frame 点击回调只执行一次。`finished` 和 clicked 不得各触发一遍业务动作。

完整检查原 `mf4_analyzer.acquisition_ui.main_window.QMessageBox` monkeypatch seam 的测试消费者；保留受支持 seam 或同补丁明确迁移，禁止在生产添加 mock 检测分支。Full 中复用 QApplication；独立 demo 的高 DPI 初始化若需统一，单独放在入口函数，不能引入 Analyzer MainWindow 依赖。

**聚焦测试（独立进程）**：`tests/acquisition_ui/test_connection_messages.py`、`test_pick_a2l_warnings.py`、`test_dropped_frame_prompt.py`、`test_review_handoff.py`、`test_settings_dialog.py`、`test_message_box_button_fit.py`。API 迁移后调整检查对象但保留实际行为断言，不能只删除原 fit 检查。

**退出**：非阻塞 UI 和采集相关副作用次数保持；Lite 中无 acquisition 导入回归；剩余输入框按 S14 记录保留/修复结果。

### T7 — 冻结包、完整台账与最终验收

1. 用同一稳定源码与已验证 UI 依赖环境生成 Windows Full/Lite；记录 Qt/PyQt/构建工具版本、平台插件、QSS 校验及源码 fingerprint。新增探针入口必须实际包含在 exe，不依赖开发机 `.state`。
2. 在 §6 矩阵运行生产入口与合成压力探针，分别记录 Full/Lite 结果。实际用户环境拿到后加一行真实复现；没有旧包则不宣称已精确还原旧故障。
3. 验证菜单/下拉圆角、图标清晰度、无重复 DPR 缩放与 frame containment。只有观测到 DPI manifest/兼容覆盖问题才修改对应构建项，再回测；不采用全局强制缩放。
4. 若交互新增了详情展开、复制完整信息等可见操作，同步更新 `ui/hints.py`、`ui/quickref.py` 及相关测试；只是替换布局且已有操作不变则在记录中说明无需更新。不能把开发者诊断字段显示为普通用户提示。
5. 当前台账无未解释调用、所有 P1 已关闭、各平台门禁对应稳定快照后，执行一次有理由的集成全量门禁，按 §7 分进程。发布版本或 commit/push 不由本计划自动触发。

**最终交付**：源码/聚焦回归、真实两平台截图与几何摘要、Full/Lite 产物元数据、迁移台账和 verify 结论。任何 G3–G5 未运行，交付标为 partial，列出确切缺口，不能填“跨平台完成”。

## 5. 窗口与弹层的实施/测试映射

下表路径省略 `mf4_analyzer/`。测试列省略 `tests/`；标注“新增”的是计划中的测试文件。共同 geometry/message 测试由 T1/T3 持有，不在每个 owner 复制 helper 测试。

| Spec | 所属文件/入口 | 阶段 | 主要聚焦测试 |
|---|---|---|---|
| S01 | 消息框详见附录 A | T3/T5/T6 | `ui/test_message_box_buttons.py`；新增 `ui_kit/test_message_dialog.py`、`ui/test_message_dialog_migration.py` |
| S02 | `ui/drawers/batch/preview_dialog.py` | T2a | `ui/test_batch_preview_dialog.py` |
| S03 | `ui/widgets/channel_config_manager.py`（主框+3内联） | T2b | `ui/test_channel_config_manager.py`、`ui/test_channel_config_transfer.py` |
| S04 | `ui/drawers/batch/_geometry.py`、`batch/sheet.py`、`ultraview/sheet.py` | T1/T4 | `ui/test_batch_smoke.py`、`ui/test_batch_close_guard_subprocess.py`；新增 `ui/test_tool_window_screen_fit.py` |
| S05 | `ui/drawers/channel_editor_drawer.py`、`export_sheet.py`；内层 `ui/dialogs/channel_editor.py`、`export.py` | T4 | `ui/test_channel_editor_export.py`；新增 `ui/test_drawer_screen_fit.py` |
| S06 | `ui/drawers/rebuild_time_popover.py` | T4 | `ui/test_rebuild_popover_geometry.py`、`ui/test_rebuild_popover_accept_race.py` |
| S07 | `ui/chart_stack/cursor_display.py`、`toolbar.py`、`cards.py`；`ui/pg_canvas/context_menu.py` | T2c/T4 | `ui/test_cursor_display_settings.py`；新增 `ui/test_anchored_popover_screen_fit.py` |
| S08 | `ui/quickref_panel.py`、`ui/expression_help.py` | T4 | `ui/test_quickref_panel.py`、`ui/test_expression_help_popup.py`、`ui/test_single_param_help_popup.py` |
| S09 | `ui_kit/glass_tooltip.py`、`ui/inspector_sections/presets.py` 的 HoverCard | T4 | `ui/test_glass_tooltip.py`；新增 `ui/test_hover_card_screen_fit.py` |
| S10 | `acquisition_ui/settings_dialog.py`、`review_modal.py` | T4/T6 | `acquisition_ui/test_settings_dialog.py`、`acquisition_ui/test_review_handoff.py` |
| S11 | `ui/dialogs/chart_options.py`、`ui/db_reference_dialog.py` | T4 | `ui/test_dialog_with_handle.py`、`ui/test_dialogs.py`、`ui/test_db_reference_controls.py` |
| S12 | `ui/widgets/recent_open_popup.py`、`view_overflow_popup.py`；`ui/drawers/batch/signal_picker.py`、`render_style_popover.py` | T4 | `ui/test_recent_open_popup.py`、`ui/test_view_tabbar.py`、`ui/test_batch_signal_picker.py`、`ui/test_batch_toolbar.py` |
| S13 | `ui/chart_stack/ultraview/author_chrome.py` | T4 | `ui/test_ultraview_author_geometry.py` |
| S14 | 审查报告列出的输入/文件调用；QMenu/QComboBox；两个 MainWindow 启动 | T4/T7 | `ui/test_combo_popup_shell.py`、`ui/test_main_window_smoke.py` 相关用例；新增 `ui/test_window_startup_screen_fit.py` 仅在失败需要修复时创建 |
| S15 | `ui_kit/style.qss` 特例与原所属控件 | T1–T7 | `ui_kit/test_search_field.py`、`ui_kit/test_control_height_scale.py`、`ui/test_view_tabbar_mount.py` |

每行可以有多个 owner，但共享 QSS/geometry 只由核心所有者整合。`_PlaceholderReviewModal` 需在台账标明占位/实际可达性，不以其类名存在就重写。

## 6. 可执行验收矩阵

### 6.1 自动化输入与断言

| 维度 | 输入 | 必须断言 |
|---|---|---|
| 工作区 | 800×600、960×540、1366×728、640×360；480×320 压力 | 支持区 frame 包含、footer 可见可点；压力区无崩溃/误确认且可安全退出 |
| 位置 | 四角、锚点/parent 部分离屏、负坐标副屏 | 坐标系正确，最终矩形包含；新屏不是复用旧 screen |
| 字体 | 12/16/24px；先 show/fit 再换字体；字体回退 | glyph 容量加 padding/border、按钮同高、正文与完整标签可访问 |
| 文案 | 短/多段中文，长英文无空格，`<...>`/`&`，长路径 | 不误解析、不截身份、完整内容可复制/访问 |
| 动作 | 1/2/3/4 个按钮、多 Accept/Reject、长标签、默认禁用 | 明确结果/退出动作，横转纵时不改变语义或制造默认同意 |
| 内容更新 | 警告 0→100→0；详情开/合；tooltip 长→短 | 不保留旧 minimum，不推走 footer，不静默丢原文 |
| 生命周期 | 反复开关、open非阻塞、父销毁、挂起refit、失活竞态 | 单次结果/业务副作用，无悬空 wrapper、重复连接与无限布局 |
| 实际绘制 | 生产 QSS + 实际字体 + show 后 grab | 文字和圆角真实正确；不能只断言 CSS token 或 widget.contentsRect |

空白窗口和尺寸 hint 不足以证明可达性：按钮要映射到屏幕坐标核对，并通过 Qt 鼠标/键盘触发到一个无业务副作用的计数器。对保存/删除真正业务行为使用原 owner 的隔离 fixture；探针不能执行用户项目上的破坏性动作。

### 6.2 真实平台组合

| 门禁 | 必须覆盖 | 记录 |
|---|---|---|
| G3 Cocoa | 正常 Retina、普通字号与24px压力、未保存项目和长标签、关键弹层、既有紧凑控件 | 原始截图 + DPR/客户区/frame/按钮几何 |
| G4 Windows 原生 | Windows 10/11 各至少一个实际环境；100% 必测；1366×768 或1280×720小屏、1920×1080 | OS/Qt/字体/工作区事实；同输入示范对照 |
| G5 Full/Lite 核心 | 两个包均在100%及至少一个125%/150%组合，生产入口+长内容 | 包名/hash/HEAD/依赖/QSS记录，不能互相代验 |
| G5 补充 | 200%高分屏、100%↔150%双屏、负坐标、任务栏/外屏移除、文本放大 | 先一包覆盖；另一包环境和UI依赖一致且核心通过才可复用共有屏幕机制证据，明确复用理由 |

不跑分辨率×缩放的全部笛卡尔积。屏幕的实际 `availableGeometry` 必须入记录，不把物理分辨率直接当客户区预算。Windows 字体替代、输入法和系统文件框要在真实平台检查；Mac 模拟 WinLayout 只能作为算法单测，不能算 G4。

## 7. 测试命令与集成纪律

日常命令模板，填写当前任务对应的文件；新增测试只能在实现后执行：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q <本任务的聚焦测试>
```

需要严格 100% 合成条件的独立进程加 `QT_FONT_DPI=96 QT_SCALE_FACTOR=1`；这些变量只用于测试，不进入发行启动脚本。不同 scale 用不同进程，不能在已有 QApplication 上改环境后声称生效。Qt 测试显式 ownership、使用隔离 QSettings、最后排空 DeferredDelete；不要把真实模态框留在后台导致 suite 等待。

共同变更对应门禁：

- QSS/token：`tests/ui_kit/test_control_height_scale.py`、`test_control_button_render.py`、`test_stylesheet_parses.py`、`test_qss_border_shorthand.py`；按实际新增选择器补 palette/selector liveness 检查，不增加无理由白名单。
- 新 UI 导入/打包：`tests/ui/test_import_boundaries.py`、`tests/test_packaging_imports.py`、`tests/test_windows_build_script.py`、`tests/test_native_import_boundaries.py`；保护 `tests/test_signal_no_gui_import.py`、`tests/test_batch_render_import_boundary.py` 的中性边界。
- 新信号连接和 MainWindow 调用者：`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui/test_main_window_state_ownership.py`，不扩大 ratchet 来容纳新违规。
- diagnostics 共享函数若改动：`tests/test_diagnostics.py`；仅新 UI 收集模块变更则运行新增 layout_diagnostics owner 测试。
- 用户可见说明如有修改：相关 hints/quickref owner 测试。Batch 数值/runner 不在此范围，不为了 UI 布局跑整套数值基线。

最终跨模块集成如需全量，由唯一集成负责人先确认没有同 checkout 的另一全量 pytest，记录 HEAD 和相关 dirty fingerprint，再用两个**顺序的新进程**：主套件 `--ignore=tests/acquisition_ui` 完成后运行 `tests/acquisition_ui`。完成后再次记录快照；相关源码中途变化或异常退出则 UNVERIFIED。历史通过数不写为当前应有数量。

本次 T0–T4 产品代码已落地。G1/G2 只跑本任务聚焦 owner 与适用边界护栏，不跑产品全量套件，也不把历史审查的 24 项填成新实现验收。G3–G5 未跑。

## 8. 完成状态与证据模板

实现时 verify 记录必须含：阶段/Spec ID、当前 source fingerprint、调用者/界面、输入、期望、实际数值/截图路径、测试命令与退出码、平台/包类型、是否复用历史证据、遗留项/所有者。

| 项目 | 当前状态 | 关闭条件 |
|---|---|---|
| G0 Spec/Plan 文档检查 | PASS，2026-09-05 | 已完整读回；12合同/15范围/8阶段一致，23模块77入口复核；链接、测试名称及差异/空白检查通过 |
| T0–T7 产品任务 | T0–T4 代码已落地；T5/T6 未开始（G4 UNVERIFIED）；T7 未开始 | 按各阶段的退出条件提供证据 |
| G1/G2 自动化实现门禁 | G1 PASS（offscreen）；G2 PARTIAL（T4 表面有结论，T5 台账仍 pending） | 当前实现的 owner/boundary 通过；T5 不得在 G3/G4 前开始 |
| G3/G4 实机示范与回归 | UNVERIFIED | Cocoa、Windows分别记录；无 Windows 实机则保持 UNVERIFIED |
| G5 Full/Lite | UNVERIFIED | 新鲜同快照产物通过 |

T4 表面结论（offscreen；实机仍归 G3/G4）：

| Spec | 结论 |
|---|---|
| S01 | T3 示范代码完成（`unsaved_project`）；其余 76 个消息入口 pending，待 G3/G4 |
| S02–S03 / S07 | T2a/T2b/T2c owner 测试通过 |
| S04–S09 / S11–S13 / S15 | 代码补齐 + 既有/新增 owner 通过；S12/S13 既有防护未红 |
| S10 | Cockpit 表单未改；`fit_message_box_buttons` 消费者测试通过。完整非阻塞迁移属 T6，未开始 |
| S14 | 未做主窗口/系统框实机小屏新探针；无失败证据，不扩大到主窗口重构 |

G0 通过只表示文档完成。无相关源码修改时不创建重复 lessons；实现中关闭本审查的回归缺口后，按 project-lessons 流程判断是否补充既有 lesson 或新建必要条目。既有 QMessageBox QSS 测宽、dialog scroll footer、SearchField 图标特例仍适用；本轮未新增 lesson。

## 附录 A：77 个消息框的模块级迁移归属

以下计数已在写文档时重新扫描当前源码。台账需进一步展开到 owner/prompt_id，不能只按模块总数勾选。M0 包含在 M1 的15个入口内，不另加到77。原有5个输入框和20个文件选择调用归 S14，不进入消息框替换计数。

| 批次 | 模块（相对 `mf4_analyzer/`） | 数量 | 聚焦行为/测试锚点 |
|---|---|---|---|
| M0 | `ui/main_window/_project_io_mixin.py` 中未保存项目示范 | 1（M1子集） | `test_project_dirty_guard.py`：三态、默认Save、关闭重入、失败保存 |
| M1 | `ui/main_window/_project_io_mixin.py` | 15 | `test_project_dirty_guard.py`、`test_blf_batch_import.py`、`test_project_session.py`；包含BLF/DBC多动作和错误提示 |
| M1 | `ui/main_window/_channel_scope_mixin.py` | 3 | `test_view_channel_scope.py`、`test_file_scope_follow.py`；解绑/覆盖取消 |
| M1 | `ui/main_window/_view_mixin.py` | 3 | `test_view_tabbar.py`、View关闭所属用例；View身份与取消 |
| M1 | `ui/main_window/window.py` | 9 | 文件关闭、Excel/WWT错误、Cockpit入口；选对应 `test_main_window_smoke.py` 用例，不扩大到整个window重构 |
| M1 | `ui/main_window/wwt_import_coordinator.py` | 1 | `test_wwt_open_batch_choice.py` |
| M2 | `ui/dialogs/channel_editor.py` | 18 | `test_channel_editor_expression.py`、`test_channel_editor_create_labels.py`、`test_channel_editor_export.py`；不改表达式算法 |
| M2 | `ui/dialogs/chart_options.py` | 1 | `test_dialog_with_handle.py`；校验失败仍留在原表单 |
| M2 | `ui/drawers/batch/sheet.py` | 6 | `test_batch_smoke.py`、`test_batch_close_guard_subprocess.py`；停止确认/结果详情 |
| M2 | `ui/widgets/channel_tree.py` | 3 | 通道勾选/全选/阈值确认所属用例；新增精确调用者回归而非只stub提示 |
| M2 | `ui/inspector_sections/presets.py` | 1 | preset清空确认所属用例，保留取消 |
| M3 | `ui/chart_stack/cards.py` | 1 | 注释清空确认所属用例 |
| M3 | `ui/chart_stack/toolbar.py` | 1 | 保存图失败提示所属用例 |
| M3 | `ui/chart_stack/ultraview/board_switcher.py` | 1 | Board删除确认所属用例 |
| M3 | `ui/chart_stack/ultraview/board_toolbar.py` | 1 | free-grid切换确认所属用例 |
| M3 | `ui/chart_stack/ultraview/page.py` | 2 | `test_ultraview_project_session.py` 及对应离开/删除行为 |
| M3 | `ui/view_tabbar.py` | 1 | `test_view_tabbar.py`；批量关闭确认 |
| M4 | `ui/main_window/_analysis_mixin.py` | 1 | 局部时间范围选择所属用例；不改分析范围计算 |
| M4 | `ui/main_window/_fft_mixin.py` | 2 | FFT失败展示所属用例；不改FFT实现 |
| M4 | `ui/main_window/_order_mixin.py` | 1 | Order失败展示所属用例；不改Order实现 |
| M5 | `acquisition_ui/main_window/_connection_mixin.py` | 1 | `acquisition_ui/test_connection_messages.py` |
| M5 | `acquisition_ui/main_window/_settings_mixin.py` | 2 | `acquisition_ui/test_pick_a2l_warnings.py`、`test_dropped_frame_prompt.py` |
| M5 | `acquisition_ui/review_modal.py` | 2 | `acquisition_ui/test_review_handoff.py`：discard、archive failure、父销毁 |
| M5 | `acquisition_ui/settings_dialog.py` | 1 | `acquisition_ui/test_settings_dialog.py`、`test_message_box_button_fit.py` |

“所属用例”必须在 T0 从当前测试中定位或新增明确的失败回归，然后将实际 node ID 写入台账；这些行不是可直接运行的伪测试路径。无法证明某入口的退出语义时保留该入口并标 pending，不能用一次统一的 `accepted/rejected` 连接替代分析。
