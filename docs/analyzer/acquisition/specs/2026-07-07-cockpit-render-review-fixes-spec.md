# Cockpit 渲染审查修复 Spec（P0/P1/P2）

Date: 2026-07-07
Status: Approved for implementation
Plan: `docs/analyzer/acquisition/plans/2026-07-07-cockpit-render-review-fixes-implementation.md`
Parent spec: `docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md`（本 spec 只做增量修复，不改父 spec 的状态机/持久化契约）

## 背景（2026-07-07 真机渲染审查实证）

用脚本驱动真实 `CockpitMainWindow`（demo 后端、on-screen grab、44 信号池）跑完
「打开 → 选通道 → 连接 → 空闲流 → 录制 → 复盘 → 设置 → 回放/历史 → 长时间空闲 →
窄窗口」全流程，17 张截图 + 每步 console 诊断双证。以下每条都有渲染证据，
不是静态推断：

- **F1 sparkline 全程空白（idle + recording 双态）**：卡片只有当前值在跳，趋势线
  永远空网格，μ/σ/max 恒 "—"（实测每张卡 buffer `n=0`）。根因：推入的样本时间戳
  是后端相对秒（`backends.py` `t = sample_monotonic - t_start`，0~n 秒量级），而
  `_polling_mixin._poll_live` 刷新时传 `now_ts=time.monotonic()`（数十万秒量级），
  `live_cards.py:380` 用 `now_ts - 60`（idle）或 `rec_start_ts`（monotonic，
  recording）做 `trim_to_window` 下限 → **每帧把全部样本裁光**。
- **F2 空闲态 ring buffer 无消费者 → ~14s 后锁死录制 + 幽灵复盘弹窗**：
  `_poll_live`（`_polling_mixin.py:100`）空闲时只 `ring.put()` 无人 drain（只有
  录制开始才 `_begin_capture_session` drain）。4096 容量在 ~300 evt/s 下 ~14s 满。
  实测：待机 24s `buf 98.5%` → REC chip 红 → **「● 采集」按钮被红健康规则禁用**；
  36s 弹出「复盘（无会话数据）」placeholder 弹窗。叠加根因：
  `ring_buffer._watermark_for` 在 fill ≥95% 时**直接**返回 `red_drop_sustained`
  （无 5s 持续判定——模块 docstring 自己写明 sustain 该由 controller 判），窗口端
  `_on_ring_watermark_changed`（`_polling_mixin.py:141`）把这个**瞬时水位**当持续
  告警立即 `_on_auto_stop_request("ring_buffer")`。而 controller 侧
  `_check_auto_stop`（`controller.py`）**已有正确的
  `red_drop_sustained_for() >= RING_BUFFER_AUTO_STOP_SUSTAIN_S` 5s 判定**——窗口端
  这条立即 auto-stop 路径是重复且错误的。
- **F3 勾一个通道 → 整列表重建 + 滚动跳顶**：`left_pane._refresh_list` 是
  clear+全量重建，实测勾选底部行后 scrollbar 34→0。真实 A2L 323 通道时每次勾选
  跳顶 + 重建 300+ 行 widget（卡顿）。
- **F4 `&` 被 Qt 当助记符吞**：录制态主按钮实显「Stop _复盘」（`window.py:400`
  `"■ Stop & 复盘"`）；设置 Transport 页「Seed&Key DLL」实显「Seed̲Key DLL」
  （`settings_dialog.py:344`）。
- **F5 空闲态新勾通道的卡片永远无数据**：`_on_selection_changed`（`window.py:796`）
  只 `set_signals` 加卡片，不重启后端流 → 新卡恒 "—"（实测 BattVolt），要等开始
  录制才有数据。附带：`_resume_idle_stream` / 录制往返后 `_stream_start_ts`、
  `_cumulative_rx_count` 不重置 → 状态栏 evt/s 统计基准漂移。
- **F6 右栏 idle 预检显示错误**：「磁盘写速 235.88 GB」——标签写"写速"，值是磁盘
  剩余（`right_panel.py:330-334` 标题 vs `band_disk_remaining` 语义）；
  「输出 502529.9 min」——35 万分钟不换算单位（`right_panel.py:418-425`）。
- **F7 未连接时健康条语义混乱**：没点连接就显示 `HW offline` 红、`XCP --` 红、
  汇总「2 red」；同时 DAQ 无任何证据却**绿**（`health.py:139` `level_daq` 空快照
  返 green）、REC 绿 "ready"。父 spec §Health Strip 要求 no evidence → off。
- **F8 录制中关键写盘指标全 0**：状态栏「0.0 MB」（asammdf 落盘前文件 stat=0）、
  质量监控「write rate 0.0 kB/s」（`_probe_rec` 硬编码 `write_rate_bps=0.0`，
  `_connection_mixin.py:291`）——用户无法确认真的在写。
- **F9 复盘弹窗交互缺口**：无「关闭」按钮（保存后只能 Esc/标题栏 ✕）；「丢弃」
  直接删文件无确认；诊断行 `channels=6` 与所选 4 个对不上（含时间通道）易困惑。
- **F10 回放 tab 错用采集文案**：中央占位仍是「未连接 ECU · 使用上方工具栏
  「连接 ECU」」（`live_cards.py:446` 占位 canvas 写死采集文案被 ReplayTab 复用）；
  右栏默认停在「连接前检查」页（ReplayTab 构造的 `RightPanel` 默认
  PAGE_DISCONNECTED）——回放上下文完全错位。
- **F11 960 最小宽度下中央被压死**：左栏 `setFixedWidth(420)`（`left_pane.py:109`）
  不让位 + 右栏 min 280 → 中央卡片只剩 ~200px，当前值被裁掉。工具栏溢出把
  「采集/回放/历史」主导航**最先**降级进 ≡ 菜单（`_toolbar_overflow_items` 末位 =
  最先 demote，`_toolbar_mixin.py:192-199`）。
- **F12 搜索匹配高亮永远不可见**：`match_spans` 画在 `QListWidgetItem` 前景上
  （`left_pane.py:399-407`），但可见文本在覆盖其上的 row widget 里 → 蓝色高亮
  没有任何视觉效果（代码注释自己承认需要 delegate）。
- **F13 历史 tab 本地化不一致**：筛选行 label 全英文（vehicle/scenario/path_kind/
  set），`issue_tags` 孤空 label 悬在第二行。

数据落盘链路本身验证 OK（capture_*.mf4 + session_summary.json + preflight.json
三件套真实生成，复盘四动作 gating 正确），不在本 spec 范围内。

## 目标

按三波修复，每波独立可测可交付：

- **Wave 1（P0，必须）**：F1 sparkline 时基、F2 空闲 ring 锁死 + 瞬时 auto-stop、
  F3 列表增量更新 + 滚动保持、F5 空闲选择变更重启流（与 F1 的流重启不变量绑定）。
- **Wave 2（P1）**：F4 助记符、F6 预检标签/时长格式、F7 no-evidence 灰灯、
  F8 写盘指标真值化。
- **Wave 3（P2）**：F9 复盘弹窗、F10 回放文案、F11 窄宽布局 + 溢出优先级、
  F12 搜索高亮、F13 历史本地化。
- **验证工具**：渲染审查用的驱动脚本收编为 `scripts/cockpit_ui_tour.py`
  （offscreen 可跑、`--assert` 模式做端到端不变量校验），作为最终验收门。

## 非目标（明确不做）

- 字体族告警（QSS `Microsoft YaHei` 在 macOS 触发 66ms alias 填充）——跨平台
  font-family 排序取舍另议，本轮不动。
- 输出路径选择器的中段省略号（tooltip 已含全路径）。
- 回放 tab 的信息富化右栏（本轮只做「加载前隐藏」+文案修正；加载后的回放专属
  信息页标 later）。
- 搜索高亮的 QStyledItemDelegate 逐字符绘制（rich text 方案已满足需求）。
- writer 通道结构（时间通道计数）本身——只改复盘弹窗的显示口径。
- Vector/XCP 真机行为、`_read_dto_frame` 收紧（硬件波，用户自留）。

## 修复契约

### F1 卡片时间基准（P0）

**不变量：卡片缓冲与 trim 必须同一时间基准（流时间），trim 下限只能从缓冲自身
最新样本导出，禁止引用 wall clock；底层流每次 (re)start，卡片缓冲清零。**

- `LiveSignalCard.refresh()` 不再接受外部 `now_ts` 参与 trim：
  - idle（非 recording）：`t_min = 缓冲最新样本 ts − 60.0`；缓冲空则不 trim。
    60s 窗口语义不变（父 spec §State Machine `stats window`）。
  - recording：**不 trim**（cumulative since rec start 由「录制开始时清空缓冲」
    实现，见下）。
- `LiveSignalCard.set_recording(True, …)` 清空 sparkline 缓冲（录制起点即缓冲
  起点，同时消除 controller 重启后端导致的 ts 归零交错）。`set_recording(False)`
  不清空。
- `LiveCardGrid` 暴露 `reset_buffers()`；以下流重启点必须调用：
  `_resume_idle_stream`（review 关闭后）、F5 的空闲重启。`_begin_connection_attempt`
  的 `set_signals` 已重建卡片，无需额外调用。
- `refresh_all()` 去掉 `now_ts` 形参，所有调用点同步更新。
- 验收：idle 推入相对 ts 样本后 `sample_count > 0` 且 stats 显示数字；推入跨
  120s 流时间的样本，idle refresh 后只保留最后 60s；`set_recording(True)` 清空；
  渲染验收由 tour `--assert` 覆盖（idle 与 recording 态卡片缓冲非空）。

### F2 空闲 ring 与 auto-stop 权威（P0）

**不变量：ring buffer 是录制路径专属结构；auto-stop 的唯一权威 = controller 的
5s sustain 判定（录制中）+ 磁盘余量判定（录制中）。窗口端 watermark 信号只用于
降帧。**

- `_poll_live` 空闲路径**不再** `self._ring.put(...)`（卡片直接喂）；
  `_cumulative_dropped` 在空闲路径不再从 ring 同步（保持 0）。
- `_on_ring_watermark_changed` 删除 `red_drop_sustained → _on_auto_stop_request`
  分支，只保留 30/10 fps 降帧两臂（父 spec §Threshold Contract Watermark wiring
  的降帧行为不变）。
- `_on_auto_stop_request` 删除「非 Recording 态开 placeholder 弹窗」死臂
  （该臂只有被本 bug 触发过）；保留 RECORDING 态臂（磁盘判定
  `_check_recording_auto_stop` 仍走它）。`auto_stop_requested` 信号契约不变。
- 录制中 ring ≥95% 持续 5s 的 auto-stop 仍由 controller `_check_auto_stop` 负责
  （已实现，`_poll_live_recording` 检测 `not controller.running` →
  `request_stop_and_review(auto_stop=…)`——链路已在，不动）。
- 状态栏空闲态文案去掉 `buf x%` 段（空闲 ring 恒 0，显示无意义）：
  `streaming · {N} evt/s`。录制态文案保留 buf。
- **既有测试契约更新**：`tests/acquisition_ui/test_demo_smoke.py::
  test_red_drop_sustained_emits_auto_stop` 与 `tests/acquisition_ui/
  test_state_machine.py` 的 watermark auto-stop 段编码的是错误行为（瞬时水位 →
  立即停），按新契约重写：watermark 只降帧、不发 auto_stop_requested；
  auto-stop 断言改为 controller 驱动路径（`auto_stopped=True` + `running=False`
  → `request_stop_and_review(auto_stop=True)`）。
- 验收：连接后空闲静置（tour soak ≥30s 模拟），ring 恒 0%、REC chip 不红、
  「● 采集」保持可用、无任何弹窗。

### F3 左栏增量更新 + 滚动保持（P0）

**不变量：勾选/事件变更不重建列表、不移动滚动条、不更换 row widget 实例；
全量重建仅限 pool/搜索/过滤变更，且必须保存并恢复滚动位置。**

- `LeftPane` 维护 `self._row_items: dict[str, QListWidgetItem]`（`_refresh_list`
  重建时填充）。新增 `_update_row_for(name)`：原地更新该行 item 背景
  （`_SELECTED_ROW_BG`）、row widget 的 checkbox 状态与事件 combo 当前项
  （均 blockSignals 包裹）。
- `_set_measurement_selected` / `_on_row_event_changed` / `_on_batch_event_changed`
  改走 `_update_row_for`（批量事件变更逐行更新所有选中行）+
  `_refresh_summary/_refresh_footer`（footer 内含 batch bar 刷新，现状保留）。
- 例外：「只看已选」chip 开启时取消勾选 → 行要消失，走全量 `_refresh_list`，
  但重建前保存 `verticalScrollBar().value()`，重建后恢复（clamp 到新 max）。
  搜索/过滤触发的重建同样恢复滚动。
- `set_frozen` 原地遍历现有行，切换 checkbox/combo 的 enabled（含 batch bar
  combo），不等用户交互才回弹（连带修复 P2「冻结无视觉反馈」）。
- 验收：50 行池滚到底勾选最后一行 → scrollbar 值不变、`itemWidget` 对象身份
  不变、选中生效；批量事件切换后各行 combo 已更新且 widget 身份不变；frozen
  后所有行控件立即置灰。

### F4 助记符转义（P1）

- `window.py:400` `"■ Stop & 复盘"` → `"■ Stop && 复盘"`；
  `settings_dialog.py:344` `"Seed&Key DLL"` → `"Seed&&Key DLL"`。
- 验收：`main_button.text() == "■ Stop && 复盘"`（RECORDING 态）；表单 label
  原文含 `&&`。渲染上按钮/label 显示单个 `&` 且无下划线。

### F5 空闲选择变更重启流（P1，依赖 F1 的 reset_buffers）

- `_on_selection_changed` 在 CONNECTED_IDLE 态：现有 set_signals/右栏刷新之外，
  启动/重置一个 300ms 单发 debounce QTimer；超时后若仍在 CONNECTED_IDLE 且
  `_capture_controller is None`：best-effort `self._backend.start(当前选择或
  DemoSignal 兜底)` + `_center.reset_buffers()` + 重置 `_stream_start_ts =
  time.monotonic()`、`_cumulative_rx_count = 0`。失败走状态栏消息，不弹窗。
- `_resume_idle_stream` 同步补上述计数重置 + `reset_buffers()`（修 evt/s 漂移）。
- 验收：空闲态新勾通道，debounce 到期 + 下一次 poll 后新卡片 `sample_count > 0`；
  backend spy 收到含新通道的 `start(selection)`。

### F6 右栏 idle 预检显示（P1）

- 「磁盘写速」标题 → **「磁盘剩余」**（值/色带不变，与录制页 disk remaining 一致）。
- 「输出」行标题 → **「预计可录时长」**，值人性化：`inf → "∞"`；`< 90 min →
  "{x:.1f} min"`；`< 48 h → "{x:.1f} h"`；否则 `"{x:.1f} d"`。色带仍走
  `band_record_duration_s`（阈值判定用秒，不受显示单位影响）。
- 验收：单测覆盖四档格式 + 标题文案。

### F7 no-evidence 灰灯（P1）

**规则：无证据 → off（灰），报警色只给「尝试过且失败」。**（父 spec
§Health Strip 原话："None-shaped snapshots … the chip stays off"。）

- 数据类加显式证据位（frozen dataclass 追加带默认值字段，既有构造点零改动）：
  - `HwHealth.probed: bool = True`；`level_hw`：`not probed → "off"`（最先判）。
  - `XcpHealth.attempted: bool = True`；`level_xcp`：`not connected and not
    attempted → "off"`（连接失败/掉线仍红）。
  - `RecHealth.evidence: bool = True`；`level_rec`：`state == "off" and not
    evidence → "off"`（最先判）。
  - `level_daq`：`not event_capacity and not overflow → "off"`（现状空快照返
    green 是 bug）。
- Cockpit 探针置位：`_probe_hw` 在 `transport is None` 且未发起连接尝试时返回
  `probed=False`（error 字符串保留原文供 tooltip 引用，**不改**
  `vector_hw_probe` 的英文错误串——测试契约在用）；`_probe_xcp` 在从未发起连接
  尝试时 `attempted=False`；`_probe_rec` 在从未收到帧且非录制时 `evidence=False`。
- 右栏 DisconnectedPage 的 UI 自有文案本地化：`ok→正常`、`connected→已连接`、
  `断开→未连接`（该串是 UI 层的，probe error 原样引用不翻译）。
- 验收：新开窗口（未点连接）五 chip 全灰 "--"，汇总 "5 off"；点连接进 idle 后
  恢复绿；连接超时失败后 XCP 红（attempted=True）。

### F8 录制写盘指标真值化（P2）

- 质量监控「write rate」行：标题 → **「写入速率」**；值 = `writer.write_count`
  的每秒增量（窗口在 `_probe_rec` 用 `(上次 count, 上次 monotonic)` 差分），
  格式 `"{n:.0f} 样本/s"`；无 controller（demo 空闲/未录制）显示 "—"。
  `RecHealth.write_rate_bps` 字段承载该 样本/s 数值（字段名不改，语义注释更新）。
- 状态栏录制态：文件 stat 尺寸为 0 时该段显示 **「缓冲中」**，>0 后恢复
  `"{mb:.1f} MB"`。
- 验收：注入 spy controller 且 write_count 递增 → 行显示非零 样本/s；文件未落盘
  时状态栏含「缓冲中」。

### F9 复盘弹窗（P2）

- 增加第五个按钮 **「关闭」**（最右侧，永远可用，走 `reject()`；不改
  save-must-not-close 契约——`2026-05-15-save-action-must-not-close-gating-modal`
  教训仍成立）。
- 「丢弃（不归档）」加确认：受管 window-modal `QMessageBox`（`open()` +
  `isVisible()` gating + 实例引用持有，仿 `_warn_a2l_load_problems` 模式），
  确认后才执行现有删除逻辑。测试可直接调 `do_discard(confirmed=True)` 绕过弹窗
  （新增关键字参数，默认 False 走确认）。
- 诊断行显示口径：`"诊断: rows={rows} · 已选通道 {len(expected_channels)} ·
  缺失 {len(missing)} · fs≈{fs:.1f} Hz"`；MDF 原始通道总数移入该 label 的
  tooltip（`"MDF 通道总数 {len(pf.channels)}（含时间通道）"`）。
- 验收：关闭按钮 reject 且 `chosen_action` 保持既有语义（关闭 = None 除非先点过
  动作）；丢弃需确认；已选/缺失计数与 `expected_channels` 一致。

### F10 回放 tab 文案（P2）

- `LiveCardGrid._build_disconnected_canvas` 文案参数化：新增
  `set_placeholder_copy(title, body, action)` API（默认值 = 现采集文案，采集页
  零改动）。
- `ReplayTab` 构造后调用：title「未加载 MF4」、body「回放会在这里显示信号趋势与
  当前值。」、action「使用左上「选择 MF4」打开录制文件」。
- `ReplayTab` 的右栏加载前隐藏（`_right_panel.setVisible(False)`），载入 source
  后再显示（现有 `show_idle/show_recording` 调用点不动）。
- 验收：回放 tab 初始不出现「连接 ECU」「连接前检查」字样；载入后右栏可见。

### F11 窄宽布局 + 溢出优先级（P2）

- `LeftPane`：`setFixedWidth(420)` → `setMinimumWidth(320)` +
  `setMaximumWidth(460)`；`_build_acquisition_page` 里 `splitter.setSizes(
  [420, 剩余, 300])` 维持 1280 默认渲染不变。
- `LiveCardGrid.setMinimumWidth(300)`（三栏 min 之和 320+300+280=900 < 960
  最小窗宽，中央不再被压死）。
- 工具栏溢出降级顺序与菜单显示顺序解耦：`_toolbar_overflow_items` 保持 L→R
  菜单序；新增显式 demote 序（先→后）：`transport_chip → output → settings →
  segment_marker → a2l → mode_segment`（主导航最后降级）。
- 验收：960×600 下中央 ≥300px 且模式段仍在工具栏（transport chip 先进 ≡）；
  1280 默认布局与现状像素级一致（左 420）。

### F12 搜索高亮（P2）

- `match_spans`（半开区间，仅针对 `measurement.name`，见 `search.py:77-88`
  docstring）改渲染进 row widget 的 name QLabel：命中段包
  `<span style="color:#1769E0;font-weight:600">`，name 先做 HTML escape；
  spans 为空（unit/address 命中）不高亮。
- 删除 `_build_row` 里的 item foreground/`"匹配: spans"` tooltip 死代码。
- 验收：搜索 "Mot" 后可见行的 name label text 含高亮 span；清空搜索恢复纯文本。

### F13 历史 tab 本地化（P2）

- 筛选 label：`vehicle→车辆`、`scenario→场景`、`path_kind→存储`、`set→数据集`、
  `issue_tags→问题标签`；`issue_tags` 行仅在存在至少一个 tag 时显示（现状空态
  孤 label 悬空）。
- 验收：空 manifest 时不出现 `issue_tags` 字样；四个筛选 label 为中文。

### 验证工具：`scripts/cockpit_ui_tour.py`

渲染审查驱动脚本收编进仓库，作为端到端验收门：

- 参数：`--shots DIR`（截图输出，缺省不截图）、`--out DIR`（录制文件输出，缺省
  临时目录）、`--assert`（不变量校验模式，违例 exit 1）、缺省
  `QT_QPA_PLATFORM=offscreen`（`--onscreen` 覆盖）。
- 流程复刻审查脚本：选通道（含滚动底部勾选）→ 连接 → idle → 空闲加通道 →
  录制 → 停止复盘 → 仅保存 → 关闭 → 空闲 soak（加速：临时把 ring 容量或
  soak 时长压小不可行——ring 已不入队，soak 只需 ~5s 验证 ring 恒 0）→ 窄宽。
- `--assert` 校验不变量（全部来自本 spec 验收条目）：
  1. idle 态每张卡 `sample_count > 0`（F1）；
  2. recording 态每张卡 `sample_count > 0`（F1）；
  3. soak 后 `ring.level_pct == 0`、REC chip 非 red、主按钮 enabled、
     `_review_modal is None`（F2）；
  4. 底部勾选后 scrollbar 值不变（F3）；
  5. 空闲新增通道在重启后收到样本（F5）；
  6. RECORDING 态 `main_button.text() == "■ Stop && 复盘"`（F4）；
  7. 复盘产物三件套存在于 `--out`（回归护栏）。
- CI/codex 验收命令：`.venv/bin/python scripts/cockpit_ui_tour.py --assert`
  期望 exit 0。

## 风险与兼容

- F2 改变了两个既有测试编码的（错误）契约，spec 已明确重写方向；除此之外
  watermark 降帧、controller auto-stop、磁盘 auto-stop 契约全部不变。
- F7 是 frozen dataclass 追加默认字段，构造点零改动；level 函数新增分支全部
  「最先判 no-evidence」，报警路径行为不变。
- F1 去掉 `refresh_all(now_ts=…)` 形参会碰 `tests/acquisition_ui/test_live_cards.py`
  既有调用，随任务同步更新。
- F11 改 LeftPane 宽度模型，1280 默认布局用 `setSizes` 锚定，像素回归靠 tour
  截图人工比对（自动像素 diff 不做）。
