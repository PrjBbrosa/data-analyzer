# UltraView P0 补完与加固实施计划

- 日期：2026-08-13
- 状态：**READY TO EXECUTE FROM TASK 1**
- 目标分支：`feat/ultraview-p0`
- 当前实现基线：`8d6d80f1f67b13ba149fd6ff6ca141c1886822af`
- 已集成主线：`main@8cdc095c4143402d586671bb7e9bb2079e7d9d05`
- 关联规格：
  `docs/analyzer/specs/2026-08-13-ultraview-p0-completion-hardening-spec.md`
- Supersedes（未完成与修复部分）：
  `docs/analyzer/plans/2026-08-12-ultraview-p0-implementation.md`

## 0. 执行结论

不要继续按旧 plan 从 Task 6 往后机械补功能。当前实现有 P0 生命周期和项目语义缺陷。
Task 0 已于 2026-08-13 完成：分支已 rebase 到 `origin/main@8cdc095c`，当前可直接从
Task 1 的子进程红测开始，再分开完成 reset/persistence、per-ref digest、
compositor/信号、帮助与综合验收。

推荐 8 个窄提交，每个提交只承担一个 owner：

```text
Task 0 主线集成与基线（已完成）
  └─ Task 1 析构安全
      └─ Task 2 reset / shutdown / close-all
          ├─ Task 3 project round-trip
          ├─ Task 4 per-ref digest
          └─ Task 5 compositor / copy / export / UI options
                └─ Task 6 help / visual harness
                      └─ Task 7 全量门禁与验收报告
```

Task 3/4/5 的主要文件不同，在 Task 2 合同稳定后可以分别实现，但涉及
`ultraview_coordinator.py` 的改动必须串行集成，不能让多个 writer 同时编辑。

## 通用执行纪律

- 使用仓库运行时：
  `"/Users/donghang/Downloads/data analyzer/.venv/bin/python"`；
- Qt 测试前缀：
  `TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=.`；
- 每个行为修复先让精准断言在旧实现上失败；进程 abort 用 subprocess 测试，不用
  `pytest.raises` 伪装；
- 不扩大 `tests/ui/test_main_window_state_ownership.py` 白名单；
- 不增加 broad `except Exception: pass`，Qt cleanup 只捕获明确 TypeError/RuntimeError；
- 不把 source View 名称、下标或显示文本当身份；
- 不用 QWidget screenshot 实现整板导出；
- 不把当前 branch 的历史 pass 数当新基线；Task 0 的实测结果见下文完成记录；
- 每个 Task 完成后运行列出的聚焦测试与 `git diff --check`；
- 如果一次 pytest abnormal exit、segfault、timeout 或中断，结果写 `UNVERIFIED/FAIL`；
- 自动化、offscreen、Cocoa、Windows frozen 是不同证据层。

## Task 0：rebase main、复核重叠文件并冻结基线（已完成）

**Owner**：集成。此 Task 不修 UltraView 产品行为。

**结果**：`feat/ultraview-p0` 已 rebase 到 `origin/main@8cdc095c`，实现提交等价重写为
`8d6d80f1`，分支为 `0 behind / 2 ahead`。

### 0.1 合并前记录

```bash
git status --short --branch
git rev-parse HEAD main origin/main
git rev-list --left-right --count main...HEAD
git diff --name-only eab5600d..8d6d80f1 | sort
git diff --name-only eab5600d..main | sort
```

- [x] rebase 前工作区干净；
- [x] `main == origin/main == 8cdc095c...`；
- [x] 保存 9 个重叠文件清单，不把“无文本冲突”当语义复核完成。

### 0.2 合入与语义复核

- [x] 按用户明确要求执行 `git rebase origin/main`，没有修改或 force push `main`；
- [x] `git range-diff` 显示两个补丁与 rebase 前等价；
- [x] 对 9 个重叠文件逐个检查两边意图：
  - `_analysis_mixin.py`：UltraView result-generation hook 与主线 cache/restore 语义并存；
  - `_project_io_mixin.py`：F7 remap、恢复 guard 与 UltraView save/open/reset 合同并存；
  - `_view_mixin.py`：UltraView capture/Alt+N 与主线 View apply 守卫并存；
  - `window.py`：最新 Toast/analysis mode/close lifecycle 与第六模式路由并存；
  - `line_canvas.py`：markup revision 与最新 render/overlay 行为并存；
  - `style.qss`：不整段覆盖主线 QSS；
  - 三个 tests：保留主线新增断言并补 UltraView，不删除任一保护。
- [x] rebase 无 conflict marker，未使用 ours/theirs 整文件覆盖；
- [x] 新产生的文档改动通过 `git diff --check`；branch-wide diff check 仍显示上游
  UltraView 报告的 Markdown hard-break 尾空格和 `style.qss` EOF 空行，均为 rebase
  前既有补丁，本 Task 不改写其语义。

### 0.3 基线测试

先跑当前已有 UltraView 聚焦集，真实记录 failures/crash：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_ultraview_state.py \
  tests/ui/test_ultraview_layouts.py \
  tests/ui/test_ultraview_preview_store.py \
  tests/ui/test_ultraview_capture.py \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_mode_integration.py \
  tests/ui/test_ultraview_job_isolation.py
```

再跑重叠 owner tests：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_chart_stack.py \
  tests/ui/test_pg_line_canvas.py \
  tests/ui/test_pg_timedomain_canvas.py \
  tests/ui/test_main_window_state_ownership.py
```

**实测结果**：

- UltraView 聚焦集：`80 passed, 12 warnings`；
- feature 重叠 owner 组合：`704 passed, 3 failed, 1 deselected`；
- 原样 `origin/main` 同组合：`702 passed, 3 failed, 1 deselected`；
- 三个失败节点在 feature 与 main 上单独运行均为 `3 passed`；
- 三个组合失败固定为 idle-AA/quality 状态，属于既有顺序/Qt 全局状态基线，不是
  rebase 差异；后续 Task 7 仍必须完整运行并如实报告，不能据此放宽 gate。

**Exit gate：PASS with recorded baseline**。主线已集成，重叠文件无语义丢失，起点
顺序相关失败已单列，后续不得冒充 UltraView 新回归或顺手修复。

## Task 1：修复 PreviewStore/MainWindow 析构崩溃

**Owner**：Qt lifecycle。

**Files**：

- 修改 `mf4_analyzer/ui/chart_stack/ultraview/preview_store.py`
- 修改 `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- 修改 `mf4_analyzer/ui/main_window/window.py`
- 修改 `tests/ui/test_ultraview_preview_store.py`
- 新增 `tests/ui/test_ultraview_lifecycle_subprocess.py`

**验收**：UV-R01、R02 的 shutdown 部分、R13。

### 1.1 RED

- [ ] subprocess 内创建 QApplication → MainWindow → show/processEvents → close →
  sendPostedEvents/processEvents → 删除引用 → gc.collect，断言 exit code 0；
- [ ] 同一子进程循环构造/关闭 10 次，能捕获偶发析构顺序问题；
- [ ] 单独 PreviewStore parent/child 销毁路径含有效 QImage records，exit code 0；
- [ ] `shutdown()` 连续调用两次不抛、不重复断信号；
- [ ] 测试必须在旧实现上以非零返回码或现有崩溃方式失败。

### 1.2 GREEN

- [ ] 删除 `PreviewStore.destroyed -> Python closure`；
- [ ] Store `clear()` 保持 GUI-thread、幂等和 record image 置 None；
- [ ] coordinator 建立 `_shutdown` guard；所有 queue/reconsider/publish 入口在 shutdown 后
  no-op；
- [ ] `shutdown()` 顺序：标记关闭 → stop/delete timers → disconnect canvas hooks →
  disconnect page hooks → Store.clear；
- [ ] MainWindow closeEvent 调 `shutdown()`，不再用兼具 reset 语义的 `clear()`；
- [ ] deleteLater 仅用于 Qt 对象回收，不依赖其触发 Python 清图。

### 1.3 验证

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_ultraview_lifecycle_subprocess.py \
  tests/ui/test_ultraview_preview_store.py \
  tests/ui/test_ultraview_mode_integration.py -k teardown
```

**Exit gate**：子进程反复运行 3 轮均正常退出；普通 unit green 不能替代 exit code。

**建议提交**：`fix(ui): make UltraView teardown deterministic`

## Task 2：拆分项目 reset 与最终 shutdown，修正 close-all

**Owner**：MainWindow project lifecycle。

**Files**：

- 修改 `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- 修改 `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- 修改 `mf4_analyzer/ui/main_window/window.py`（仅必要接线）
- 修改 `tests/ui/test_ultraview_mode_integration.py`
- 修改 `tests/ui/test_project_session.py`

**验收**：UV-R02、R03、R09 的 Esc/presentation 部分。

### 2.1 RED

- [ ] `reset_project_state()` 清 Board/Store/runtime，但 `_page_hooks` 数量不变；
- [ ] reset 后 add/layout/ratio/focus/open/copy/export 每个动作各触发一次，不能 0 次或 2 次；
- [ ] close-all 有文件且用户取消：Board payload、Store stats、hooks、files 全不变；
- [ ] close-all 确认：files/Board/Store 清空，随后在同一窗口新建 Board 仍可交互；
- [ ] 无文件 close-all 不清已恢复 Board；
- [ ] presentation 中 reset/离开能恢复 Inspector 状态，不遗留 snapshot；
- [ ] Esc：focus → replacement → presentation → popup，每次消费一层。

### 2.2 GREEN

- [ ] `clear()` 删除或改为兼容 shim，但产品路径只调用具名
  `reset_project_state()/shutdown()`；
- [ ] reset 清 timer、bindings、unstable、result identity/generation、runtime ledger、Store，
  重建 default Board，并 refresh page；
- [ ] reset 不断 Page/Inspector/Stack hooks；
- [ ] close-all 把 reset 移到确认之后；取消无副作用；
- [ ] open_project 的 reset 时点留给 Task 3 接入，Task 2 先提供 API；
- [ ] teardown test 增加 receiver 行为断言，而不是仅“emit 后没报错”。

### 2.3 验证

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_ultraview_mode_integration.py \
  tests/ui/test_project_session.py -k "close_all or cancel or project"
```

**Exit gate**：reset 后功能继续可用；shutdown 后信号不再进入 coordinator；取消关闭零副作用。

**建议提交**：`fix(ui): separate UltraView project reset from shutdown`

## Task 3：完成 `.tlproj` 持久化、current_mode 与退化恢复

**Owner**：project_io。

**Files**：

- 修改 `mf4_analyzer/ui/project_io.py`
- 修改 `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- 修改 `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- 修改 `tests/test_project_io.py`
- 修改 `tests/ui/test_project_session.py`
- 新增 `tests/ui/test_ultraview_project_session.py`（若现有文件已过大）

**验收**：UV-R04、R07 的持久化、R09 的 Board name round-trip、R12。

### 3.1 RED：pure codec

- [ ] `SCHEMA_VERSION == 2`；ProjectDocument 旧位置参数构造不变；
- [ ] `ultraview=None` 的旧项目 load/save 不受影响；
- [ ] Board name/layout/ratio/placements/unplaced/show flags round-trip；
- [ ] QImage/digest/selected/filter/presentation/side snapshots 不出现在 JSON；
- [ ] 未知 current_mode 回 time；未知 nested schema、layout、ratio、非法/重复 ref 返回 warnings；
- [ ] 合法缺失 ref 不被 codec 删除。

### 3.2 RED：MainWindow session

- [ ] 在 UltraView、last source=`fft` 保存，JSON current_mode=`fft`；重开落 FFT；
- [ ] 重开后 Board 已恢复，存在 ref 为 missing，缺失 ref 为 orphaned；不自动进入总览；
- [ ] 打开项目选择取消、JSON 解析失败时原 Board 不变；
- [ ] 真正替换项目时 reset 一次，page hooks 仍有效；
- [ ] 项目 warning 有 toast/log/health 可见证据；
- [ ] 保存/恢复前后 `_analysis_restore_pending` 遵守既有源工作区语义，UltraView 不消费。

### 3.3 GREEN

- [ ] dataclass 末尾加 `ultraview`；codec 使用 `.get`；
- [ ] `current_mode` loader whitelist；stack/Inspector 的未知 mode 防御继续保留；
- [ ] coordinator 提供 `project_source_mode/to_project_payload/restore_project_state`；
- [ ] save 构造 ProjectDocument 时调用以上 API；
- [ ] managers/View IDs 恢复完成后再 restore Board；
- [ ] project warning 合并到既有恢复反馈，不能覆盖 missing file health；
- [ ] 保存不调用源 render、job 或 cache store。

### 3.4 验证

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_project_io.py

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_project_session.py \
  tests/ui/test_ultraview_project_session.py \
  tests/ui/test_ultraview_job_isolation.py
```

若没有新增独立文件，第二条命令删除不存在路径，不能因命令写错把 gate 跳过。

**Exit gate**：旧项目、新项目、坏 payload、旧 reader 模拟和 UltraView 保存模式全部有证据。

**建议提交**：`feat(project): persist UltraView board state safely`

## Task 4：修正 per-ref digest 与 runtime ledger

**Owner**：UltraView identity/capture。

**Files**：

- 修改 `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- 可新增 `mf4_analyzer/ui/main_window/ultraview_runtime.py`
- 修改 `tests/ui/test_ultraview_capture.py`
- 修改 `tests/ui/test_ultraview_job_isolation.py`

**验收**：UV-R06、R11、R12、R13。

### 4.1 RED

使用同 section 两个 analysis Views A/B：

- [ ] capture A，切 active 到 B；修改 B pane_count/markup，A digest 不变；
- [ ] B 的 ref 自身 digest 改变；
- [ ] 切回 A 并修改 A markup，A 变 stale；
- [ ] time ref A 找不到 binding 时不得 fallback 读取 active canvas B；
- [ ] A/B 相同 cache key 但不同 view_id 的 generation 隔离；
- [ ] inactive worker completion 只更新目标 ref generation，不抓 active canvas；
- [ ] reset/open/shutdown 后 ledger 清空；
- [ ] digest unavailable 保持 old image=stale、no image=missing。

### 4.2 GREEN

- [ ] 提供 keyed runtime facts，key 只用 `UltraViewRef`；
- [ ] `presentation_payload_for(ref)` 首先从 ref 自身 state/pins/results 建 payload；
- [ ] widget 运行态只有 binding 精确匹配 ref 时加入；
- [ ] 成功 capture 原子提交 runtime facts 与 preview；晚到 ref/digest/binding 复检继续保留；
- [ ] analysis pane structure 不再无条件读取 active page；
- [ ] 时域 markup 不再 fallback active canvas；
- [ ] 记录结构是 coordinator 单 owner，不新增 MainWindow 多文件写入。

### 4.3 验证

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_ultraview_capture.py \
  tests/ui/test_ultraview_job_isolation.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_pg_canvas_backref_invariants.py
```

**Exit gate**：inactive ref 不再受 active canvas 污染，同时自身 markup/result 变化仍可 stale。

**建议提交**：`fix(ui): isolate UltraView digests by stable view identity`

## Task 5：实现 compositor、复制/导出闭环、显示选项和 LRU

**Owner**：ChartStack UltraView presentation/export。

**Files**：

- 新增 `mf4_analyzer/ui/chart_stack/ultraview/compositor.py`
- 修改 `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- 修改 `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- 修改 `mf4_analyzer/ui/chart_stack/ultraview/preview_store.py`
- 修改 `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- 新增 `tests/ui/test_ultraview_export.py`
- 修改 `tests/ui/test_ultraview_page.py`
- 修改 `tests/ui/test_ultraview_job_isolation.py`

**验收**：UV-R05、R07、R08、R09、R11、R12。

### 5.1 RED：信号闭环

- [ ] page 的 copy board/copy card/export 三个信号各有 coordinator receiver；
- [ ] 用户点击一次只执行一次；reset 后仍一次；shutdown 后零次；
- [ ] locate/rebind 冗余信号删除或具备真实 receiver，测试锁定决定；
- [ ] Board name 有键盘可用编辑入口并修改 BoardState。

### 5.2 RED：compositor

- [ ] 1×=1600×900、2×=3200×1800、DPR=1；
- [ ] layout rect 与 `layouts.py` 同源；
- [ ] 所有 placed slots 与状态都有确定像素，未放置/库/Inspector 不进入；
- [ ] missing 占位，stale/orphaned 用旧图并标状态；
- [ ] `show_titles/show_sources` 四组合同时影响 page model 与输出像素；
- [ ] 2× 卡图任何方向不超过 raw 100%；
- [ ] clipboard board 与同 scale compositor 像素 hash 一致；
- [ ] save failure、不可写路径、allocation failure 有结构化错误，目标无空文件；
- [ ] monkeypatch 四个 `do_*`、job submit、cache store、canvas grab，合成全程 0 调用。

### 5.3 RED：LRU 与完整零计算链

- [ ] 状态/库刷新不 touch；
- [ ] 实际卡片显示、focus、copy card、copy/export board touch 对应 ref；
- [ ] unpinned budget eviction 按真实最后使用次序；
- [ ] 完整序列：进入 → add → tray → layout/ratio → swap → compare → focus →
  presentation → copy card → copy board → PNG 1×/2× → save project → exit；
- [ ] compute/job/new cache writes 全 0，restore pending 与 source snapshot 不变。

### 5.4 GREEN

- [ ] compositor 只接 Qt-free projection + QImage record，不 import MainWindow；
- [ ] coordinator 负责 clipboard/file dialog/toast/log，compositor 负责纯绘制；
- [ ] PNG 采用同目录 temp + `os.replace`；
- [ ] Page 卡片模型遵守 show flags，不通过空字符串留下无意义占位高度；
- [ ] focus/copy/compositor 调用 store.touch；
- [ ] BoardToolbar 的 name edit 保持现有精简视觉，不新增大型 modal。

### 5.5 验证

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_ultraview_export.py \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_preview_store.py \
  tests/ui/test_ultraview_job_isolation.py
```

**Exit gate**：三个导出/复制动作真实工作；完整 P0 链零计算；失败可见且不留空文件。

**建议提交**：`feat(ui): complete UltraView export and presentation controls`

## Task 6：帮助、截图工具、打包与自动视觉证据

**Owner**：product docs/verification。

**Files**：

- 修改 `mf4_analyzer/ui/hints.py`
- 修改 `mf4_analyzer/ui/quickref.py`
- 修改 `mf4_analyzer/help/__init__.py`
- 新增 `mf4_analyzer/help/ultraview-guide.html`
- 修改 `tools/gen_help_screenshots.py`
- 新增 `tools/verify_ultraview_visuals.py`
- 修改/新增对应 hints、quickref、help、screenshot、packaging、visual tests

**验收**：UV-R07、R09、R10、R16。

### 6.1 产品文案

- [ ] QuickRef 表述为“五个分析工作区 + 一个只读总览”，不叫第六算法；
- [ ] guide 覆盖 View 库、2/4/6、托盘、四态、打开原 View、导出、项目重开 missing、
  零后台计算；
- [ ] hints 覆盖“加入总览”、卡片菜单、Esc、演示和导出；
- [ ] 不出现 PDF/SVG、board zoom、sidecar、后台补图或 live card。

### 6.2 机械与视觉门禁

- [ ] `_GUIDE_FILES`、截图 `PANEL_MODES`、packaging data 含 UltraView；
- [ ] 1100px toolbar geometry 无重叠/裁切；若 full labels 失败，实现统一六按钮紧凑态；
- [ ] visual harness 生成 1280×800/1600×900 的 hero、6-grid、托盘、四态、show flags、
  focus、presentation、1100 toolbar；
- [ ] 输出 manifest、geometry assertions 和 contact sheet 到 `.state/ultraview-p0/`；
- [ ] generated screenshots 默认不提交 Git。

### 6.3 验证

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_hints.py \
  tests/ui/test_quickref.py \
  tests/test_help_content.py \
  tests/test_gen_help_screenshots.py \
  tests/test_packaging_imports.py \
  tests/test_verify_ultraview_visuals.py
```

若真实测试名不同，先用 `rg` 找 `_GUIDE_FILES/PANEL_MODES` 消费者并更新本计划，不能
静默删掉不存在路径后声称通过。

**Exit gate**：产品文案与实际功能一致；自动 contact sheet 可用于前景验收；资源随包。

**建议提交**：`docs(ui): complete UltraView help and visual verification`

## Task 7：架构门禁、两进程回归、Cocoa 与最终报告

**Owner**：集成/验收。禁止在本 Task 顺手加功能。

**Files**：

- 新增 `docs/analyzer/verify/2026-08-XX-ultraview-p0-verification.md`
- 只修本轮引入的测试/视觉回归

**验收**：UV-R01～R18，原 UV-A01～A34。

### 7.1 静态与边界

```bash
git status --short --branch
git diff --check main...HEAD
rg -n "except Exception:\s*(pass)?" mf4_analyzer/ui/chart_stack/ultraview \
  mf4_analyzer/ui/main_window/ultraview_coordinator.py
```

运行：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_import_boundaries.py \
  tests/test_signal_no_gui_import.py \
  tests/test_batch_render_import_boundary.py \
  tests/test_native_import_boundaries.py \
  tests/test_packaging_imports.py \
  tests/ui/test_pg_canvas_backref_invariants.py
```

### 7.2 UltraView 聚焦套件

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q tests/ui/test_ultraview_*.py
```

- [ ] 再以 UI/non-UI 交错文件顺序跑一次，确认 fixture closure 没丢；
- [ ] 生命周期 subprocess 测试单独连续跑 3 轮；
- [ ] 完整零计算测试输出四类计数和 source snapshot diff；
- [ ] export golden/geometry 对比可复现，不只断言“文件存在”。

### 7.3 两进程全套回归

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q --ignore=tests/acquisition_ui

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q tests/acquisition_ui
```

两条都必须是 fresh process 且正常结束。历史 pass count 只作对照，不是成功条件。

### 7.4 macOS Cocoa 前景

- [ ] 从真实主窗口进入/退出总览，左 Navigator 与右 Inspector 状态精确恢复；
- [ ] 2/4/6、ratio、拖放、托盘、右键、keyboard、focus、Esc；
- [ ] fresh/stale/missing/orphaned、show flags 和 Board name；
- [ ] Retina 清晰度、圆角、间距、标题不遮图；
- [ ] clipboard board/card 与 PNG 1×/2×打开检查；
- [ ] 使用 visual harness contact sheet 自动汇总，不要求逐张手工找差异；
- [ ] Windows Full/Lite frozen 未跑时明确 `UNVERIFIED`。

### 7.5 最终报告格式

`docs/analyzer/verify/...` 必须有：

| 字段 | 内容 |
|---|---|
| Contract | UV-R01～R18 与 UV-A01～A34 |
| Evidence class | unit / subprocess / offscreen / rendered / Cocoa / source-only / Windows frozen |
| Command/action | 精确命令或手工动作 |
| Result | PASS / FAIL / UNVERIFIED |
| Evidence | test 名、log、manifest、contact sheet 或截图路径 |
| Notes | baseline、偏差、平台限制 |

**Exit gate**：UV-R01～R17 无遗漏；Windows 状态诚实；无异常退出；Cocoa 有前景证据。

**建议提交**：`test(ui): verify UltraView P0 completion gates`

## 最终提交与发布边界

推荐提交序列：

1. `fix(ui): make UltraView teardown deterministic`
2. `fix(ui): separate UltraView project reset from shutdown`
3. `feat(project): persist UltraView board state safely`
4. `fix(ui): isolate UltraView digests by stable view identity`
5. `feat(ui): complete UltraView export and presentation controls`
6. `docs(ui): complete UltraView help and visual verification`
7. `test(ui): verify UltraView P0 completion gates`

最终准备合入前：

- [ ] `git diff --name-status main...HEAD` 只含 UltraView 及必要兼容；
- [ ] 评审每个提交，没有其他 Grok/Cursor 工作被重新带入；
- [ ] 最终验证报告已提交且 SHA 与测试基线一致；
- [ ] 不 force push `main`；
- [ ] 未经用户明确要求，不自动 merge/push UltraView 到 main。
