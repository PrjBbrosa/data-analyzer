# 文件卡片「加入当前 View」按钮小计划

状态：待执行，仅文档；2026-09-12。
交互参考：[已确认的 HTML Demo](../ui-prototypes/2026-09-12-file-attach-button.html)。

## 目标与范围

在每张已打开文件卡片的红色 × 下方、元信息行右侧增加加入按钮，补充「自动加入、拖入、点击 ＋」三个入口。当前 View 已有文件时，其他未加入文件仍可点击 ＋。

本次只增加入口和附件状态展示。复用现有附件处理语义，不增加分析重算、通道自动勾选或持久化字段。Demo 的关闭确认、撤销及右侧附件管理区是演示辅助，不作为本次新增功能；现有关闭和移出行为保持原契约。

## 按钮状态

| 当前卡片相对接收 View 的状态 | 展示与行为 |
| --- | --- |
| 未加入 | 蓝色 ＋；点击加入该卡片全部逻辑来源 |
| 部分加入 | 蓝色 ＋，元信息显示「已加入 2/4 轨」；仅补齐缺失来源 |
| 全部已加入 | 原位淡色 ✓；仅状态展示，不点击移除 |
| 没有可接收的 View | 灰色 ＋ 禁用；提示先选择目标 View |

- 提示与无障碍名称写明目标 Section、View；时域分屏补充主栏/副栏焦点。切换焦点后同步更新。
- 保留文件卡片现有紧凑高度和文本对齐，按钮与 × 同列；长元信息省略并保留完整提示，不挤掉加入数量。
- 点击按钮不触发卡片激活、文件关闭或拖动。重复点击不重复加入。
- 正常同步加入直接显示最终状态，不人为延迟。仅当实际接入已有异步操作时展示「加入中」并防重复；不为复刻 Demo 的转圈新建异步流程。
- 空 View 提示增加「点击上方文件的 ＋」；无打开文件时保留打开文件引导。

## 实施步骤

1. **卡片展示与请求信号** — `mf4_analyzer/ui/file_navigator.py`。
   在 `_FileRow` 元信息行增加按钮，通过明确槽函数发出整组 `_fids` 的加入请求；不得只传 primary fid 或使用文件名作为身份。Navigator 转发请求，并按当前附件投影派生未加入/部分/全部状态。组件只接收展示上下文，不读取 MainWindow 会话状态。
2. **接入现有附件路径与状态刷新** — `ui/main_window/window.py`、`_channel_scope_mixin.py` 及现有 View 投影入口。
   新信号复用 `_attach_files_from_drop()`，由现有 `_attach_files_to_active_context` 同族路径确定有效目标、去重并完成反馈，不复制一套加入逻辑。`file_navigator.py:set_attached_file_ids()` 当前只转发到通道列表，需让卡片状态随同一附件投影刷新；时域还需核对直接投影通道列表的路径。覆盖 Section/View/分屏焦点切换、移出、关闭、分组增减、项目恢复和无目标清空。目标名称与附件集合应来自同一上下文，避免旧 View 的 ✓ 残留；更新卡片不触发整次 View 恢复或额外计算。
3. **帮助与定向验证** — 同步 `mf4_analyzer/ui/hints.py`、`ui/quickref.py`，补充按钮含义及空状态指引，运行下面的验收。

现有接入依据：`file_navigator.py:_FileRow` 已保存分组 `_fids`；`_channel_scope_mixin.py:_attach_files_from_drop` 已区分时域焦点和分析 View；`_analysis_mixin.py:_project_analysis_attachments` 已向 Navigator 投影分析附件。实现时沿这些 owner 扩展，Navigator 中只保留可重建展示上下文，ViewState 继续拥有附件事实。

## 验收与检查

- 在 `tests/ui/test_file_navigator.py` 增加按钮信号、四种状态、2/4 补齐、分组成员变化、按钮不激活卡片的定向用例。
- 在 `tests/ui/test_view_channel_scope.py` 与 `tests/ui/test_analysis_multiview_integration.py` 增加或选择相关用例：点击和拖入结果一致；只影响目标 View；时域主副栏焦点正确；所有支持附件的分析 Section 状态正确；移出/关闭/恢复后状态刷新；未额外勾选通道或触发分析计算。
- 运行 `tests/ui/test_file_scope_follow.py`，确认自动加入仍只作用于新打开文件；按实际文案变更运行 `test_hints.py`、`test_quickref.py`。边界检查：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`；如修改 QSS，补 `tests/ui_kit/test_qss_border_shorthand.py`。
- 使用项目 `.venv` 和 offscreen 环境跑上述定向测试；不安排全量测试。真实 macOS TraceLab 检查按钮纵向对齐、卡片高度、长文件名/多轨元信息、hover/禁用提示，以及快速切换 View 时状态是否正确。offscreen 结果与前台外观验收分别记录。

完成标准：三个入口使用一致的附件规则；新增按钮不干扰现有文件操作、通道选择和分析流程；定向测试通过，前台外观验收完成或明确标为未验证。

本轮只新增本计划：检查引用、范围、一致性及 `git diff --check`，不运行产品测试；HTML Demo 已完成的浏览器验证不替代后续 PyQt 验收。
