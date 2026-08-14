# style.qss 瘦身与护栏 —— 实施 plan

- 日期：2026-08-15
- 上游 spec：`docs/analyzer/specs/2026-08-15-qss-consolidation-spec.md`
  （三分类死名清单、护栏设计、不做清单均在 spec §3/§5，本文不重复论证）
- 状态：**执行中（Task 1–6 已落盘，Task 7 全量对账进行中）**。

## §0 执行护栏（每个 Task 通用）

- 本机验证一律绝对 venv 路径：
  `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest …`
- 全量分两条命令（裸全量会在 `tests/acquisition_ui` 段交错 segfault）：
  主体 `--ignore=tests/acquisition_ui`，该目录另起一条单独跑。
- **动手前记当前失败数**，收尾对账；别把既有红算进本批。
- 禁区照旧：根 `conftest.py` pin 逻辑、状态所有权棘轮白名单、ink/AA 标定常量、
  性能门禁上限一律不碰。QSS 侧追加三条：**不重排既有块顺序**、不动
  `{{TOKEN}}` 模板机制语义（`control_style.py`/`stylesheet.py`/`icons.py` 的
  替换管线）、`test_qss_border_shorthand` 白名单只许缩小。
- Codex 可能并行改工作区：每个长验证前后 `git status` 对账，异常先分清
  提交态/在途态再动。
- 提交粒度：每个 Task 内的分组各自成提交，提交信息注明删除依据
  （spec §5.2 的类别 + 退役证据）。

## Task 0：前置门与基线记录

- [x] 门 1：从干净 local `main`（`3971d5a3`，UltraView A 收口）建 worktree
  分支 `codex/qss-consolidation`。该 HEAD 上 `style.qss` 无未提交改动。
- [x] 门 2：分支已建。动手前全量两条命令未跑完（Task 0 agent 中断）；
  收口数字以 Task 7 为准。
- [x] 聚焦回归集（`grep -rl style.qss tests` 补漏后）包括：
  `tests/ui_kit/test_qss_border_shorthand.py` · `test_selection_signature.py` ·
  `test_stylesheet_parses.py` · `tests/ui/test_compact_spinbox.py` ·
  `test_view_tabbar.py` · `test_batch_signal_picker.py` ·
  `test_batch_compact_contract.py` · `test_inspector.py` · `test_toolbar.py` ·
  `test_qmenu_density.py` · `test_message_box_buttons.py`。
  本批另增 `test_qss_selector_liveness.py` · `test_qss_palette_ratchet.py` ·
  `test_qss_duplicate_selectors.py`。
- [x] offscreen 截图脚本：`scripts/capture_qss_offscreen_baseline.py`，
  输出 `/tmp/qss-consolidation-baseline/`（7 张 PNG + sha256 manifest）。

## Task 1：liveness 护栏先行（先测后删）

**Files**: `tests/ui_kit/test_qss_selector_liveness.py`（新）·
`tests/ui_kit/_qss_parse.py`（新，Task 5 复用，禁止再写一份解析器）

- [x] 按 spec §3.2 实现提取与比对；两条实现红线（词边界防前缀吞并、按选择器
  文本扫而非花括号配对）直接抄 spec §5.1 的踩坑记录进 `_qss_parse.py` docstring。
- [x] 白名单初始 = 当前全部零命中名按三段归类 + A/B 暂留；MIGRATION 段回指 spec
  与 UltraView 收口 plan。
- [x] 断言 shrink-only：新死名、白名单里已有生产命中、白名单名已不在 QSS，均红。
- [x] 用本 HEAD（`3971d5a3`）重扫死名清单，与 spec §5.2 对账；以重扫为准。
- [x] 验证：新测试绿；聚焦回归 `test_qss_border_shorthand` /
  `test_stylesheet_parses` / `test_selection_signature` 绿（24 passed）。

**重扫旁注（HEAD `3971d5a3`，`style.qss` 4581 行 / 432 个 objectName；spec 盘点
来自脏 UltraView 工作区 4671 行 / 443 名，历史数字不改 spec 正文）**：死名 **34**
= A 28 + B 1 + DYNAMIC 4 + QT_INTERNAL 1。差异：

- spec C 类 9 名已不在本 HEAD 的 `style.qss`（`3971d5a3` UltraView A 已 prune
  source-proven dead selectors；见
  `docs/analyzer/plans/2026-08-14-ultraview-a-edge-rhythm-implementation.md`）。
  生产代码亦零命中。`MIGRATION_OBJECT_NAMES` 因此为空，不把已删除的选择器挂回白名单。
- `channelDeleteList` 仅存注释，提取器先剥注释故不计入选择器；不进白名单
  （Task 2 组 4 仍会清那条注释）。
- DYNAMIC 拼接点以本 HEAD 为准：`contextual_frf.py:479` `f"{role}Dot"`；
  `ultraview/chrome.py:416/427` `f"ultraViewRail{short_name}…"`（spec 盘点为
  `:420/:431`）。

## Task 2：A 类死规则删除（四组提交，每组独立可回退）
（执行时漏勾，2026-08-15 review 对账后补记，见 post-v8-batch-review §4.4）

**Files**: `mf4_analyzer/ui_kit/style.qss` · `tests/ui_kit/test_qss_selector_liveness.py`

每组的固定流程：删规则 → liveness 白名单同步缩 → 聚焦回归集 →
offscreen 截图与 Task 0 基线逐像素比对（**预期完全等同**，任何 diff 都是
误删活规则的信号，先查再继续）。

- [x] 组 1：channelConfigManager 老 QDialog 家族 19 名（词边界重扫定位，
  盘点时为 260–353 整段）。**保留** `channelConfigManagerHtml` /
  `channelConfigHtml*` 现行段。删前 `git log -S channelConfigManagerTable`
  考古退役点（预期指向 `2026-07-24-channel-config-manager-v2` 批次），
  提交信息引用。
- [x] 组 2：chartHint + chartHintPersistent 全部块。注意 `chartHintBar` 家族
  是活的，逐块核对选择器再删。`tests/ui/test_chart_stack.py` 三处按
  `"chartHint"` 断言 absence 的谓词**保留**（它们是退役回归守卫，与删规则
  不冲突）。
- [x] 组 3：BatchPresetSourceNote · BatchToolbarMeta · BatchAnalysisPresetOption
  （七块）。absence 测试 `test_batch_method_buttons.py:546` 保留。
- [x] 组 4：versionTag · healthDisconnectButton · rightMetricValue /
  rightMetricDetail 各块；`channelDeleteList` 只剩注释,连注释一并清。
- [x] 收尾：liveness 白名单应只剩 QT_INTERNAL + DYNAMIC + MIGRATION 三段。

## Task 3：B 类 frfSegmentChoice 成对裁决

**Files**: `mf4_analyzer/ui_kit/style.qss` · `tests/ui_kit/test_selection_signature.py`

- [x] `git log -S frfSegmentChoice` + `git log -S 'frf-segment'` 考古：确认该
  segmented 控件是「做过又退役」还是「预留未接线」。
- [x] 若退役：QSS 四块（盘点时 2224–2247）与 `test_selection_signature.py`
  表中 `("frf", …, "frfSegmentChoice", …)` 行**同一提交**删除；liveness
  白名单同步缩。
- [x] 若预留：两侧都保留，QSS 块上方加注释写明预期消费方与引入 spec，
  liveness 白名单为它加 PLANNED 注记（仍计入 shrink-only 总数）。
- [x] 验证：`test_selection_signature.py` 全绿。

## Task 4：色板收敛第一批（蓝系）+ distinct-hex 棘轮

**Files**: `mf4_analyzer/ui_kit/style.qss` · `mf4_analyzer/ui_kit/control_style.py` ·
`tests/ui_kit/test_qss_palette_ratchet.py`（新）

- [x] 蓝系盘点表先行：`#1769e0`(=CONTROL_ACCENT) 与 `#2d7ff9` / `#2563eb` /
  `#145fc8` / `#0f3f8f` 及其它蓝系值，逐色列出现处与语义（rest/hover/dark/
  wash），产出「归并到既有 token / 新增 token / 保留字面量」三栏裁决表，
  附在本文末尾再动手（token 化判据见 spec §3.3：≥3 处或交互态成组）。
- [x] 按表归并。**每归并一个色值单独提交**，便于视觉回归二分。
  （本 Task 工作区禁止 commit，归并留在未提交 diff。）
- [ ] 真机验收（非 offscreen）：对比脚本两侧截图 + 哈希 + diff 图输出，
  像素变化逐项人工裁决后在提交信息记录「预期变化」清单。参考
  `tools/verify_batch_qt_render_parity.py` 的证据组织方式（注意它的
  `--output-dir` 教训：证据输出走临时目录）。**Cocoa 真机未做，剩余门禁。**
- [x] 新增 `test_qss_palette_ratchet.py`：distinct 6 位 hex 计数 shrink-only，
  起点 = 归并后实测值（243）。只这一个计数断言，不做 per-family 细分。
- [x] 验证：`test_selection_signature.py`（token 家族契约）与聚焦回归集绿。

Task 4 短裁决（完整表见执行回复；n = 剥注释后字面量次数）：

| hex | n | 裁决 |
| --- | --- | --- |
| `#1769e0` | 41 | 既有 `CONTROL_ACCENT` |
| `#2d7ff9` | 12 | 既有 `CONTROL_ACCENT_HI` |
| `#edf5ff` | 5 | 既有 `CONTROL_ACCENT_WASH` |
| `#0f3f8f` | 8 | **新增** `CONTROL_ACCENT_INK`（≠ `CONTROL_TEXT_ON_SELECT`） |
| `#2563eb` | 9 | 保留字面量（tab 下划线/swatch/link 混用，不并进 ACCENT） |
| `#145fc8` | 3 | 保留字面量（≠ `CONTROL_ACCENT_DARK` `#135ABD`） |
| `#0a6de7` / `#0b73e7` | 5 / 4 | 保留（channelConfigHtml / preset 专属，后者与 Python `_HIGHLIGHT_COLOR` 对齐） |
| `#135abd` / `#0f5fd2` / `#12437f` | 0 | 已全是 token，无残留字面量 |
| 其余蓝（wash/viewTab/UltraView hover 等） | — | 保留字面量（非 ACCENT 近似群或 <3 / 控件专属） |

distinct 6-hex：247 → **243**。新增 token：`CONTROL_ACCENT_INK=#0F3F8F`。

## Task 5：重复定义 lint + 白名单

**Files**: `tests/ui_kit/test_qss_duplicate_selectors.py`（新）·
`tests/ui_kit/_qss_parse.py`（复用，新增 `iter_qss_rule_blocks` /
`duplicate_selector_counts`）

- [x] 实现 spec §3.4 的 lint（选择器逗号拆分、空白归一、注释与括号先遮罩——
  复用 `_qss_parse.py`，禁止第二份解析器）。
- [x] 当前 44 个重复选择器（46 次额外出现）全部进白名单并附一句话理由。
  无一满足「声明完全相同 / 无冲突严格子集，且两块之间无其它命中同一
  widget 的规则」；token 中和会把不同 `{{CONTROL_*}}` 当成相同，逗号组
  归并会泄漏属性。`style.qss` 本步未改。
- [x] 未改 QSS，与 Task 4 offscreen 基线哈希等同。
- [x] 验证：聚焦契约 41 passed（含新 lint）。

## Task 6：UltraView C 类挂钩（本批只留指针）

- [x] 在 UltraView 收口 plan（执行时以在途最新一份为准）的验收清单加一条：
  「迁移完成后删除 spec §5.2 C 类 9 名的 QSS 块，并把
  `test_qss_selector_liveness.py` MIGRATION 段清空」。
  已挂钩到 `docs/analyzer/plans/2026-08-14-ultraview-a-edge-rhythm-implementation.md`
  §8 Verification and acceptance 与 §9 Done means（九名已列出）。
- [x] 本批不删任何 `ultraView*` 规则。

## Task 7：收尾对账

- [ ] 两条命令全量，与 Task 0 基线失败数对账；本批必须零新增失败。
- [ ] 汇总本批数字（删除行数、白名单余量、distinct hex 终值）回填 spec §2
  旁注；本文状态改「已完成」。
- [ ] 若 CLAUDE.md 基线段落数字因此过期，同步订正（只改数字，不改叙述）。
