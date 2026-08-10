# 文件范围跟随 · 链接菜单实施计划

- 日期：2026-08-11
- 对应 spec：
  [`2026-08-11-file-scope-follow-link-menu-spec.md`](../specs/2026-08-11-file-scope-follow-link-menu-spec.md)
- 基线分支：`codex/analysis-view-source-isolation-pilot`
- 原则：每个 Task 一个可独立回退的 commit；全程不动项目 schema、不动
  `signal/` 与 batch；三项全关时行为与基线逐字节一致。

## Task 0 — 基线对账（不改代码）

1. `git status` 快照留档（Codex 会话可能并行改工作区，动手前后各对一次账）。
2. 记录当前失败数：
   `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui -q`
   （全量按 CLAUDE.md 分两条命令跑，主体 `--ignore=tests/acquisition_ui`）。
3. 确认 `tests/ui/test_analysis_source_scope.py` 等在途改动的归属，别把并行改动
   算进本任务。

验收：留有基线数字；后续每个 Task 只与该数字比较。

## Task 1 — 跟随决策纯函数 + 偏好持有

新文件 `mf4_analyzer/ui/main_window/file_scope_follow.py`：

- `FollowPrefs` dataclass：`attach_on_load` / `inherit_on_new_view` /
  `fill_on_mode_entry` 三个 bool；`any_enabled()`；`enabled_count()`。
- `load_follow_prefs(settings)` / `save_follow_prefs(settings, prefs)`：
  项 1 复用 `AUTO_ATTACH_SETTINGS_KEY`（默认 True，沿用现有字符串/布尔宽松解析），
  项 2/3 新 key 默认 False。
- 纯决策函数（不 import PyQt5 之外的 UI 对象，输入全是普通数据）：
  - `resolve_new_view_template(section_attachment, time_attachment, files)`
    → 返回要拷贝的 fid 列表（保序去重、过滤不在 files 的 fid；两级回退；空则 `[]`）。
  - `resolve_mode_entry_fill(target_attachment, time_attachment, files)`
    → 目标非空返回 `None`（不动），否则返回过滤后的时域范围。

测试：`tests/ui/test_file_scope_follow.py`（纯函数级，覆盖回退链、去重、
过滤失效 fid、目标非空返回 None、settings 读写往返 + 旧 key 兼容）。

验收：新测试绿；不触碰任何现有文件 → 棘轮/边界测试不可能红。

## Task 2 — 链接按钮 → 勾选菜单（file_navigator）

`mf4_analyzer/ui/file_navigator.py`：

- `btn_auto_attach` 改 `InstantPopup` 菜单按钮，挂三个 checkable QAction；
  移除 `setCheckable(True)` 的单击 toggle 语义。
- 新信号 `follow_prefs_changed(object)`（携带 `FollowPrefs`）；保留
  `auto_attach_changed(bool)` 与 `auto_attach_enabled()` 作为项 1 的兼容 shim
  （`_on_source_load_finished` 与既有测试都在用）。
- `set_follow_prefs(prefs)` / `follow_prefs()`；`_sync_auto_attach_button()` 改为
  按「任一勾选」切图标（`mdi.link-variant` / `-off`）+ 新 tooltip 文案
  （`未启用文件范围跟随` / `已启用 N 项文件范围跟随 · 点击调整`）。
- 嵌入菜单若用自定义 widget，遵守 CLAUDE.md 透明背景 gotcha；纯 QMenu 则无此问题
  （首选纯 QMenu + QAction，省事）。

`mf4_analyzer/ui/main_window/_channel_scope_mixin.py`：

- `_init_channel_scope` 改为 `load_follow_prefs` → `navigator.set_follow_prefs`；
  `_on_follow_prefs_changed` 持久化（替代/包装 `_on_auto_attach_changed`）。
- `window.py` 接线改为连 `follow_prefs_changed`。

测试：`tests/ui/test_channel_widget.py` / navigator 相关用例更新——菜单三项勾选
状态与图标/tooltip 联动；QSettings 往返；旧 key False 时项 1 起始为关。

验收：全关时图标呈灰断链，与基线视觉状态一致；`tests/ui` 相关子集绿。

## Task 3 — 项 1 作用域：加载 → 当前焦点上下文

`_channel_scope_mixin._on_source_load_finished`：

- 守卫不变（`_restoring_project`、空 fids、项 1 关）；
- 主体从 `_attach_files_to_focused_view(new_fids)` 改为
  `_attach_files_to_active_context(new_fids)`；
- 分析侧追加成功时 toast `已加入 <section 标签> · <View 名> · N 个文件`
  （复用 `_attach_files_from_drop` 的文案函数，抽公共小 helper，别复制字符串）。

测试：更新既有「加载自动加入」用例 + 新增「FFT 页加载 → FFT active View 收到、
时域 View 不变」「分析页加载且项 1 关 → 无副作用」。

验收：spec §6.2；删掉旧「Auto-attach remains Time-only (Stage 1 non-goal)」注释，
在 spec 引用处留一句指向本 spec。

## Task 4 — 项 2：`+` 新建继承文件范围

- `_view_mixin._on_view_new`：capture → 记录模板（时域焦点 View attachment）→
  `new_view()`；返回 `-1` 则整体 no-op；成功且项 2 开 →
  `resolve_new_view_template` → 写入新 state 的 `attached_file_ids` →
  `_project_view_controls(new_idx)` 重投影 → toast。
- `_analysis_mixin._on_analysis_new`：同构——capture → 记录「当前 active View
  attachment + 时域焦点 attachment」→ `new_view()` → 决策 → 写入 →
  `_project_analysis_attachments` + `_refresh_analysis_candidates` → toast。
- 写入一律经既有 attach helper 或直接对新建 state 赋值一次（新建 state 尚无任何
  归属争议；若走 helper 需注意此刻 active 已是新 View，两条路径都可，取更短的）。

测试：只开 2 时时域/分析 `+` 继承；模板为空回退时域；两级皆空保持空；满员
`+` 无副作用；项目恢复期间新建（若有此路径）不继承；toast 计数。

验收：spec §6.3。

## Task 5 — 项 3：模式进入填充空 View

- `_on_mode_changed` 分析分支（`window.py:1513` 起），在
  `_apply_active_analysis_context` / `_enter_fft_mode` 排程**之前**：
  项 3 开 且 非 `_opening_project` → 取目标 section active state →
  `resolve_mode_entry_fill` → 非 None 则写入 attachment → 后续既有投影管线
  自动呈现填充结果 → toast。
- **不**在 `_on_analysis_view_switched` 里加任何钩子（程序化管线，项目恢复也走）。

测试：只开 3 时 time→fft 空 View 被填充、已配置 View 不动；fft 内 tab 切空 View
不填充；fft→order 来源仍是时域焦点 View；时域也空则保持空且无 toast；
`_opening_project` 期间模式切换零跟随（复用项目恢复测试骨架）；填充不触发计算
（画布仍空/仍显示点击计算）。

验收：spec §6.4 / §6.5。

## Task 6 — 发现性与收尾

1. `/update-hints`：hints 滚动条目 + quickref 面板补「链接菜单 = 文件范围跟随」。
2. 空态次级文案：`set_empty_state_context` 输出追加引导行（spec §3.2）。
3. 帮助 changelog 草稿一条（随下次升版本入 `mf4_analyzer/help/`，本 Task 只留
   草稿文字于 PR 描述，不动版本扇出面）。
4. 全量两条命令跑主体 + `tests/acquisition_ui`，与 Task 0 基线对账；
   `git status` 与并行会话对账。

验收：主体与 acquisition_ui 均不劣于基线；hints/quickref 测试绿。

## 顺序与依赖

Task 1 → 2 → 3/4/5（三者相互独立，可并行或任意顺序）→ 6。
任何一个跟随项想砍，都只影响自己的 Task，不阻塞其余。
