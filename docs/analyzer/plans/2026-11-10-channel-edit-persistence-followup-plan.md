# 通道编辑随项目保存：验收结论与补丁 plan（followup）

- 日期：2026-11-10。
- 状态：**待执行。** 本文只记录验收结论与补丁范围，未改任何产品代码。
- 验收对象：`689edbc3`（`feat(project): replay channel-editor recipes when a project reopens`），对照 `docs/analyzer/plans/2026-11-10-channel-edit-project-persistence-plan.md`。
- 对照基线：`a8844727`（该提交的父提交，干净 worktree）。
- 验收方法：读 diff 与 HEAD 调用点；在 HEAD 与基线上各跑一次同一份探针脚本；在 HEAD 与基线上各跑一次同一份聚焦门禁（offscreen Qt，Linux 云端，`-X faulthandler`）。未跑全量套件。

## 1. 结论

主路径成立，可以收下：创建 → 保存 → 重开后派生通道存在且逐点相等；无编辑的项目仍写 schema 4；回放失败在恢复时逐条可见；`signal/` 无 GUI、import 边界、状态所有权棘轮、lambda 连接棘轮都没被放宽。

但有两处需要补：一处是本次改动引入的行为回归（F1），一处是它暴露出的静默失败（F2）。另外上一份 plan 的验证措辞比证据强，本文一并订正（§3）。

## 2. 发现

| 编号 | 级别 | 内容 | 证据 |
| --- | --- | --- | --- |
| F1 | 回归 | 同一次打开通道编辑时，先删除通道 `X`，再用单通道或双通道运算从 `X` 派生，点确定后派生通道**没有被创建**。基线会先加后删，派生通道存在。 | 探针：HEAD 结果通道 `['time','torque']`，基线 `['time','torque','d_dt_rpm']` |
| F2 | 静默失败 | 上述情况下 toast 仍是成功样式的「通道已更新: 新增 1 · 删除 1」，状态栏「编辑: +1 -1」。跳过原因只进日志，用户看不到。 | 同一探针；`window.py` 的 `_apply_channel_edits` 丢弃了 `replay()` 的 skipped 结果，计数取自对话框的字典长度 |
| F3 | 可见性 | 不带配方的三参路径在保存时发的「部分通道未随项目保存」会被紧随其后的「已保存项目」顶掉（toast 是单槽）。屏幕上最终只剩「已保存项目」。 | 探针读 toast 文本；`_project_io_mixin.py` 的 `_warn_session_only_channels` 在成功 toast 之前调用 |
| F4 | 既有，非回归 | 源列不是数值时，单通道 / 双通道创建抛未捕获的 `ValueError`。HEAD 与基线行为相同。 | 探针在两侧都复现；CSV 加载器会丢弃文本列，真实加载器是否可达未证实 |
| F5 | 轻微 | 派生通道及其下游都被删除后，日志里可能留下一对互相抵消的「派生 a … 删除 a」，使项目停在 schema 5。回放结果正确。 | 读 `record_remove` 的压缩规则 |

F1 的成因：对话框的暂存日志按操作顺序记成「删除 X → 派生(src=X)」，应用路径严格按日志顺序回放，派生时 `X` 已不存在。对话框自身没拦住，是因为 `_remove` 只把名字记进 `removed_channels`，没有从 `combo_src` / `combo_a` / `combo_b` 移除；单通道和双通道的存在性检查只看 `fd.data.columns`，而暂存期间 `fd.data` 还没变。表达式路径已经按 `removed_channels` 拒绝（「通道A 不存在」），三条创建路径在这点上本来就不一致。

F3 的三参路径目前从界面走不到（抽屉总是带配方），所以用户今天不会遇到；但上一份 plan 的 D8 与 PR 描述都写了「保存时会警告」，按现状这句话不成立。

检查过、没有问题的：HDF 旧采样率恢复路径不受影响；没有交互式时间轴重建，回放时用的时间轴与创建时一致；`self.files[fid] =` 只有一处，不存在会丢日志的重载路径；`mf4_analyzer/help`、README、用户指南里没有残留「派生通道不随项目保存」的旧说法；旧版本拒绝打开 schema 5 时给用户的提示文案正确。

## 3. 验证记录订正

上一份 plan 的状态行与 §10、以及 PR 描述，写的是聚焦测试与边界护栏「已通过」。实际情况：

- 实施当时的合并聚焦门禁是 `1 failed, 471 passed`，随后进程以 139 退出。那条失败的用例修好后只重跑了两个节点，没有重跑整份门禁。
- 本次验收在 `689edbc3` 上重跑同一份门禁：`472 passed`，随后解释器退出阶段 `Fatal Python error: Segmentation fault`（`<no Python frame>`），退出码 139。
- 同一份文件清单（去掉本次新增的三个测试文件）在基线 `a8844727` 上：`440 passed`，同样在退出阶段段错误，退出码 139。

所以：用例全部通过；进程非零退出在基线上就存在，不是这次改动引入的；但按仓库的门禁规则，异常退出的那次运行不能记成干净通过。另外 `tests/test_packaging_imports.py`、`tests/test_native_import_boundaries.py`、`tests/test_batch_render_import_boundary.py` 在提交前没跑，本次补跑为 `15 passed, 1 skipped`，退出码 0。

退出阶段段错误的定位不在本补丁范围内（见 §5）。

## 4. 补丁 Task

范围只到 F1、F2、F3。不升版本号，不动 schema，不动回放顺序语义，不放宽任何棘轮。

### T1 已标记删除的通道不能再当输入（F1）

- owner：`mf4_analyzer/ui/dialogs/channel_editor.py`。
- 做法：
  1. `_create_single` 与 `_create_dual` 的存在性检查加上「不在 `removed_channels` 里」，与表达式路径同一规则。提示写明原因和做法，例如「通道 X 已标记删除，请先创建派生通道，再删除源通道」，不要沿用笼统的「源通道不存在或参数越界」。
  2. `_remove` 把被删的名字从 `combo_src` / `combo_a` / `combo_b` 移除，让用户一开始就选不到。重新打开或切换文件时三个下拉框本来就会重建，不需要另加恢复逻辑。
- 取舍：基线允许「先删后派生」是因为它先加后删。保留这个顺序需要改写日志顺序，会破坏「日志顺序即回放顺序」这条设计（上一份 plan 的 D2）。这里选择在入口拒绝，代价是用户要先派生再删除。
- 先写失败用例（`tests/ui/test_channel_editor_recipes.py`）：
  - 删除 `X` 后单通道从 `X` 创建：被拒绝，`new_channels` 与暂存日志都不增加。
  - 删除 `X` 后双通道以 `X` 为 A 或 B 创建：同上。
  - 删除后三个下拉框里不再有 `X`；删除暂存的新通道同理。
  - 先派生再删除源通道：派生通道保留，确定后存在（保住合法顺序）。
- 边界护栏：`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui/test_import_boundaries.py`。

### T2 应用路径按实际结果报告（F2）

- owner：`mf4_analyzer/ui/main_window/window.py` 的 `_apply_channel_edits`。不新增窗口状态。
- 做法：
  1. toast 与状态栏的「新增 / 删除」计数改为取自 `replay()` 实际应用的条目，不再取对话框字典的长度。三参路径没有回放结果，继续用传入的集合。
  2. 有 skipped 结果时，只发**一条** toast（单槽，分两条会互相顶掉），样式为 warning，带未应用的通道名与原因（复用 `REASON_TEXT` 的中文原因；条数多时截断并给出总数）。同时 `logger.warning` 留痕。
  3. 是否标记项目变脏，改为看是否真的有条目被应用，而不是对话框有没有传东西。
- 先写失败用例（`tests/ui/test_project_session.py` 或 `tests/ui/test_project_dirty_guard.py`，直接调 `_apply_channel_edits` 传一条必然跳过的配方）：
  - toast 为 warning 且包含通道名和原因；计数为实际值。
  - 全部条目被跳过时项目不变脏。
  - 全部应用时文案与样式与现在一致（保住正常路径）。
- 边界护栏：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`。
- 说明：T1 做完后界面已走不到 F1 那条路，T2 是给同一失败模式兜底——以后再有配方在应用时算不出来，用户能看到。

### T3 「未随项目保存」的提示要留得住（F3）

- owner：`mf4_analyzer/ui/main_window/_project_io_mixin.py` 的保存路径。
- 做法：有会话内通道时，把保存成功与警告并成一条 warning toast（例如「已保存项目 · N 个通道未随项目保存」），没有时保持现在的「已保存项目」。日志行保留。
- 用例（`tests/ui/test_project_dirty_guard.py` 或 `tests/ui/test_project_session.py`）：三参路径加通道后保存，最终留在 toast 上的文本包含「未随项目保存」；没有会话内通道时仍是「已保存项目」。
- 边界护栏：`tests/ui/test_main_window_state_ownership.py`。
- 这条路径从界面走不到，优先级最低；如果不想为不可达路径加代码，替代做法是删掉 D8 与 PR 描述里「保存时会警告」那句，改成「只写日志」。二选一，不要保持现状。

### T4 收口

- 跑 T1–T3 的 owner 用例和各自的边界护栏，再跑 `tests/ui/test_channel_editor_recipes.py`、`tests/test_channel_edit_log.py`、`tests/ui/test_project_session.py`、`tests/ui/test_project_dirty_guard.py` 各一次。记录每个进程的**退出码**，不只记 pass 数；非零退出按 `UNVERIFIED` 报告。
- `git diff --check`。
- 文档：界面交互没有增删（只是多了一条拒绝提示和一种 toast 文案），`ui/hints.py` 与 `ui/quickref.py` 不需要改。用户指南 FAQ 如果提到「先删后派生」再补一句，否则不动。
- 不跑全量套件：改动限于一个对话框和两个应用 / 保存路径的反馈文案，没有跨边界重构。

## 5. 不在本补丁内

- **F4**（非数值源列的未捕获异常）：既有行为，且真实加载器是否能产生这种列尚未证实。先确认可达再决定是否映射成 `RecipeError("non_numeric")`。
- **F5**（日志里互相抵消的条目）：不影响回放结果，只是让个别项目多停留在 schema 5。
- **聚焦门禁退出阶段的段错误**：基线就有，不是本功能引入的。成因未定位（可能与仓库已记录的 Qt teardown 问题同类，但没有证据），应走专项排查，不在这里顺手处理。
- macOS 前台与 Windows 冻结包的真机验收：仍未执行，沿用上一份 plan §6 的清单。
