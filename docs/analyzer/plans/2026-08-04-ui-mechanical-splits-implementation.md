# UI 机械拆分热身包 · 实施计划(包 A)

> **For agentic workers:** 按任务逐条执行,checkbox(`- [ ]`)跟踪。四个任务(A1–A4)
> **互相独立**,可单独执行、单独 revert;每任务一个 commit。任何验证失败先对照基线
> 失败集,确认是自己引入的才修;不是自己引入的记录后继续。

**设计文档:** [2026-08-04-ui-mechanical-splits-design.md](../specs/2026-08-04-ui-mechanical-splits-design.md)
**基线:** `main` @ `e385ce5a`。分支:`refactor/ui-mechanical-splits`。
**测试命令前缀(下称 `PYTEST`):** `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest`

## 全局约束

- **纯移动**:除 import 语句与拆分点本身外,函数/类体一行不改;不重排语句、不改名、
  不"顺手优化"。
- 外部 import 路径零改动(spec「已核实的兼容面」一节是硬约束清单)。
- `main` 上 `tests/ui/` 既有红测试(`test_split_*` 等)——Task 0 先记录,不算新账。

---

## Task 0: 锚点核验 + 基线采集

- [x] **Step 1:** 核验 spec 锚点,任何一条失配 → **停止并回报**,不要凭猜测继续:
  - `grep -n "^class \|^def \|^INTERNAL" mf4_analyzer/ui/widgets/__init__.py`
    应与 spec D-A1 表格一致(:42/:45/:52/:76/:80/:111/:284/:463/:1624/:1670)。
  - `grep -n "^class " mf4_analyzer/ui/dialogs.py` 应为 :54/:614/:642 三类。
  - `grep -n "def read_blf_frames\|def load_blf\|def probe_blf_dbc" mf4_analyzer/io/loader.py`
    确认公开门面方法;BLF 私有帮助函数区间约 L149-515。
  - `mf4_analyzer/ui/chart_stack/cards.py` 中 `_ChartCard.__init__` 为 L106-404。
  - 重跑 spec 兼容面的三条 grep(ui.widgets / ui.dialogs / BLF 符号外部引用),
    确认消费者清单未变。
- [x] **Step 2:** 跑基线并存档失败集:
  `PYTEST tests/ui/ -q > docs/analyzer/verify/ui-splits-baseline-ui.txt 2>&1 || true`
  `PYTEST tests/test_blf_loader.py tests/test_blf_dbc_candidates.py tests/test_batch_loader_dispatch.py -q`

**核验结果(2026-08-06,`main` @ `b886a30e`):**

- 行号锚点全部命中:A1 的 :42/:45/:52/:76/:80/:111/:284/:463/:1624/:1670、A2 的
  :54/:614/:642、A4 的 `_ChartCard.__init__` L106-404、A3 的 BLF 区间 L148-514
  (`@dataclass` 装饰器在 148;spec 写「8 个函数」,实为 10 个——多出
  `_emit_progress`:186 与 `_numeric_decoded_values`:329,均在区间内且仓库内无外部引用)。
- A3 额外公开门面方法:`probe_blf_dbc_frames`(:533)、`load_blf_frames`(:544)。
- **基线失败集(2 条,与 CLAUDE.md 里「`test_split_*` 全红」的旧描述不符——那批已转绿):**
  - `tests/ui/test_batch_runner_thread.py::test_sheet_preview_and_result_share_channel_metadata_reference`
  - `tests/ui/test_hint_nudges.py::test_view_compact_tabs_ranks_between_coaxis_and_custom_action`
  - 计数:`2 failed, 2914 passed, 1 deselected`。
- **A1 兼容面核验失配 → A1 已停止,见下方 Task A1 的「停止说明」。**

---

## Task A1: 拆 `ui/widgets/__init__.py`

**Files(计划):** Create `mf4_analyzer/ui/widgets/{_swatches,channel_tree,stats,toast}.py`;
Modify `mf4_analyzer/ui/widgets/__init__.py`;Create `tests/ui/test_widgets_misc.py`。

**Files(实际落地,按下方裁决走方向 c):** Create
`mf4_analyzer/ui/widgets/{stats,toast}.py` + `tests/ui/test_widgets_misc.py`;
Modify `mf4_analyzer/ui/widgets/__init__.py`。**`_swatches.py` 与 `channel_tree.py`
未创建**——理由见「停止说明」与「裁决」两节。

> **停止说明(2026-08-06,第一执行者):A1 未执行,零代码改动。**
> *(已被下方「裁决」一节部分取代:`stats`/`toast` 已落地,
> `_swatches`/`channel_tree` 仍保持未执行。)*
>
> Task 0 Step 1 的兼容面复查发现 spec 的「已核实的兼容面」清单不完整:除了纯 import
> 消费者,还有 **4 处把 `mf4_analyzer.ui.widgets` 当作 monkeypatch 命名空间**的用法。
> 其中一处与 D-A1 的搬迁方案**语义冲突**,不是靠扩充再导出清单能解决的:
>
> - `tests/ui/test_color_swatch_hidpi.py:44-47`
>   `test_swatch_default_path_picks_up_device_ratio`:
>   ```python
>   import mf4_analyzer.ui.widgets as widgets_mod
>   monkeypatch.setattr(widgets_mod, "icon_device_pixel_ratio", lambda: 2.0)
>   pix = widgets_mod._swatch_pixmap("#abcdef")
>   assert pix.devicePixelRatioF() == 2.0
>   ```
>   该用例patch 的是 **`ui.widgets` 模块命名空间里的 `icon_device_pixel_ratio`**,
>   依赖 `_swatch_pixmap.__globals__` 就是 `ui.widgets`。D-A1 把 `_swatch_pixmap`
>   移进 `_swatches.py` 后,它的 globals 变成 `ui.widgets._swatches`,patch 不再可见
>   → 断言必失败。再导出 `icon_device_pixel_ratio` 也救不了(patch 的是 `__init__`
>   的名字,函数读的是 `_swatches` 的名字)。基线该文件 **7 passed**,属于会被改红的既有测试。
> - `scripts/channel_dot_size_preview.py:43-44` 同样模式(重绑 `widgets_mod._swatch_icon`
>   期望 `MultiFileChannelWidget` 看得见),搬迁后会静默失效——不是测试,但同样是回归。
> - 另 3 处仅需 `__init__` 保留属性即可(patch 的是类/模块对象自身属性,全局生效):
>   `tests/ui/test_hints.py:365`(`ui.widgets.hints.mark_discovered`)、
>   `tests/ui/test_hints.py:370` 与 `tests/ui/test_channel_widget.py:98`
>   (`ui.widgets.QMenu.exec_`)、`tests/ui/test_file_navigator.py:279`
>   (`ui.widgets.QMessageBox.question`)⇒ 再导出清单还须含 `hints`、`QMenu`、`QMessageBox`。
>
> 按全局约束「外部 import 路径零改动 / 纯移动 / 不改既有测试」,A1 无法在不动
> `test_color_swatch_hidpi.py` 的前提下达成。**需 spec 作者裁决**,可选方向:
> (a) `_swatches.py` 只放 `_fmt_rate`/`_swatch_icon`,`_swatch_pixmap` 留在 `__init__`;
> (b) 允许改这一个用例改用 `_swatches` 模块作为 patch 目标(超出「纯移动」);
> (c) A1 整体降级为「只拆 `channel_tree` / `stats` / `toast`,`_swatches` 不拆」。
>
> **复核(2026-08-06,第二执行者,分支 @ `285132b1`):停止结论成立,且已实测坐实。**
>
> - 锚点重验全部命中(:42/:45/:52/:76/:80/:111/:284/:463/:1624/:1670),
>   `ui/widgets/__init__.py` 与 `main` 逐字一致,未被本分支动过。
> - **实测**:按 D-A1 建 `_swatches.py`(`_fmt_rate`/`_swatch_pixmap`/`_swatch_icon`)、
>   `__init__` 改为 `from ._swatches import ...` 再导出后跑
>   `tests/ui/test_color_swatch_hidpi.py` → **`1 failed, 6 passed`**(基线 7 passed),
>   失败即 `test_swatch_default_path_picks_up_device_ratio`,报错
>   `assert 1.0 == 2.0`。实验已回滚,工作树干净。
>   根因与上文一致:`_swatch_pixmap` 在函数体里读 `icon_device_pixel_ratio()`,
>   走的是**自身模块 globals**;用例 patch 的是 `ui.widgets.__init__` 的同名属性。
>   搬走后两者不再是同一个命名空间,再导出无法弥合(再导出复制的是绑定,不是作用域)。
> - 兼容面清单再补一条 spec 与前次都漏掉的消费者:
>   **`scripts/color_swatch_hidpi_smoke.py:31`** `from mf4_analyzer.ui.widgets import _swatch_pixmap`
>   ——纯 import,再导出即可,不构成新阻塞,但应计入 A1 的兼容面。
> - 另确认 `channel_tree` 的搬迁也有同类(较轻)代价:`scripts/channel_dot_size_preview.py:43-44`
>   先重绑 `widgets_mod._swatch_icon` 再构造 `MultiFileChannelWidget`,依赖
>   widget 代码从 `ui.widgets` globals 里解析 `_swatch_icon`。搬进
>   `channel_tree.py` 后该重绑静默失效(无测试覆盖 ⇒ 不会变红,但确是回归)。
> - **可安全搬迁的子集(已核实无晚绑定消费者)**:`stats.py`
>   (`StatisticsPanel` + `StatsStrip`)与 `toast.py`(`Toast`)——三者函数体只引用
>   Qt 符号与 `StatisticsPanel` 自身,仓库内无人 patch `ui.widgets` 上的这些名字。
>   即选项(c)的「stats / toast」部分零风险;有争议的只有 `_swatches` 与 `channel_tree`。
> - 裁决仍属 spec 作者:选(b)要改既有用例、选(a)/(c)要改 D-A1 表格,两者都超出
>   本包「纯移动 + 不改既有测试」的全局约束,执行者不自行决定。Step 2-4 保持未勾。

- [x] **Step 1(先补测试,红→绿在基线上完成):** 写 `tests/ui/test_widgets_misc.py`
  (spec「新增测试」第 1 条:Toast 显示/自隐/重复调用、StatsStrip 文本与空值、
  StatisticsPanel 冒烟)。写前先读 `Toast`(:1670-1760)与 `StatsStrip`(:1624-1668)
  的真实接口,按实际方法名写断言。在**基线代码**上跑绿后单独 commit。
  **已完成**(`285132b1`,224 行 / 19 用例,拆分前代码上全绿)。Step 1 不依赖
  搬迁方案,三个可选方向(a)/(b)/(c)选哪个都不影响这些断言,故先落地。
  额外锁住一条真实回归:`test_toast_reshow_cancels_pending_fade_out` 覆盖
  `show_message` 里 `_anim.finished.disconnect()` 的存在理由(fade-out 在飞时
  再来一条消息,不得被旧的 finished→hide 连接顺手隐藏)。
### 裁决(2026-08-06):执行方向(c),只拆零风险子集

两次独立执行都证实:按 D-A1 表格把 `_swatches` 纯移动出去会打红既有用例。
实测数字一致——`tests/ui/test_color_swatch_hidpi.py` 从 **7 passed** 变成
**1 failed / 6 passed**,失败的是 `test_swatch_default_path_picks_up_device_ratio`,
报错 `assert 1.0 == 2.0`。原因是 `_swatch_pixmap` 从**自身模块 globals** 读
`icon_device_pixel_ratio`,而用例 patch 的是 `ui.widgets` 包命名空间的同名属性;
再导出复制的是绑定不是作用域,补名单救不了。

`channel_tree`(`MultiFileChannelWidget`)另有一处**无测试覆盖的静默风险**:
`scripts/channel_dot_size_preview.py:43-44` 先重绑 `widgets_mod._swatch_icon`
再构造 widget,搬走后该重绑不再可见——不会变红,但确是回归。

⇒ 完整拆分需要「改 1 处测试的 patch 目标 + 动 2 处 dev 脚本」,超出本包
「纯移动 + 零测试改动」的硬约束。方向(a) 要改既有测试、(b) 会在包 `__init__`
与子模块间引入循环依赖;为凑 `__init__` ≤ 60 行的验收指标去动兼容面得不偿失。
**本次只落地已核实无晚绑定消费者的零风险子集;`_swatches` 与 `channel_tree`
的完整拆分留作独立小任务,待用户批准后执行。**

- [x] **Step 2(按方向 c 执行):** `StatisticsPanel` + `StatsStrip` → `stats.py`,
  `Toast` → `toast.py`,逐字纯移动(已用 AST 逐类比对 `main`,三个类体
  byte-identical;留在 `__init__.py` 的 6 个顶层符号同样 byte-identical)。
  `_swatches`(`_fmt_rate`/`_swatch_pixmap`/`_swatch_icon`)与 channel tree
  (`INTERNAL_FILE_FIDS_MIME`/`_ChannelLeafDelegate`/`_CheckTolerantTree`/
  `MultiFileChannelWidget`)**原位不动**。
- [x] **Step 3:** `__init__.py` 顶部显式再导出 `StatisticsPanel, StatsStrip`(`.stats`)
  与 `Toast`(`.toast`),带 `# noqa: F401`(沿用 `ui/pg_canvases.py` 的再导出惯例)。
  其余名字与代码原位保留;monkeypatch 锚点 `hints` / `QMenu` / `QMessageBox` /
  `icon_device_pixel_ratio` 均未动。仅删掉随搬迁失效的 4 个 import
  (`QFrame`、`QGraphicsOpacityEffect`、`QPropertyAnimation`、`QTimer`)。
  实测 12 个兼容面名字全部可从 `mf4_analyzer.ui.widgets` 解析,
  且 `_swatch_pixmap.__module__` 仍为 `mf4_analyzer.ui.widgets`。
- [x] **Step 4:** 验证。A1 组 **107 passed**(含 `test_color_swatch_hidpi.py` 7/7 全绿)。

Run: `PYTEST tests/ui/test_channel_widget.py tests/ui/test_channel_widget_setters.py tests/ui/test_channel_axis_groups.py tests/ui/test_color_swatch_hidpi.py tests/ui/test_head_hdf_rail.py tests/ui/test_widgets_misc.py tests/ui/test_hints.py -q`

Expected: 全绿(或与基线失败集一致)。

## Task A2: `ui/dialogs.py` → `ui/dialogs/` 包

**Files:** Create `mf4_analyzer/ui/dialogs/{__init__,channel_editor,export,chart_options}.py`;
Delete `mf4_analyzer/ui/dialogs.py`。

- [x] **Step 1:** 记录 `dialogs.py` 头部 import 清单;三个类按 :54-613 / :614-641 /
  :642-1256 切入三个模块,相对导入 `from .xxx` → `from ..xxx`(含 :44 的
  `from .expression_help import ...`)。
- [x] **Step 2:** `__init__.py`:docstring(修正过期的 `AxisEdit` 描述)+
  再导出 `ChannelEditorDialog, ExportDialog, ChartOptionsDialog`。
- [x] **Step 3:** 全仓 grep `ui.dialogs`/`from .dialogs`/`from ..dialogs` 确认所有
  消费者(产品 3 处 + 测试)无需改动即可解析。
- [x] **Step 4:** 验证。

Run: `PYTEST tests/ui/test_dialogs.py tests/ui/test_dialog_with_handle.py tests/ui/test_channel_editor_expression.py tests/ui/test_channel_editor_export.py tests/ui/test_expression_help_popup.py tests/ui/test_axis_interaction.py -q`

## Task A3: BLF/DBC → `io/blf_format.py`

**Files:** Create `mf4_analyzer/io/blf_format.py`;Modify `mf4_analyzer/io/loader.py`。

- [x] **Step 1:** 移动 L149-515 的 BLF 子系统(`BlfDbcProbe` + 8 个函数)到
  `blf_format.py`;`can`/`cantools` 的延迟 import 策略保持在函数体内。
- [x] **Step 2:** `DataLoader.read_blf_frames` / `load_blf` / `probe_blf_dbc`(以及
  Task 0 核验发现的其他 BLF 公开方法)改为对 `blf_format` 的薄委托,
  **签名与 docstring 逐字保留**。
- [x] **Step 3:** 验证(BLF 测试在无 python-can 环境会 importorskip,属正常)。

Run: `PYTEST tests/test_blf_loader.py tests/test_blf_dbc_candidates.py tests/test_batch_loader_dispatch.py tests/ui/test_blf_open.py tests/ui/test_blf_batch_import.py -q`

## Task A4: 分解 `_ChartCard.__init__`

**Files:** Create `tests/ui/test_chart_card_construction.py`;
Modify `mf4_analyzer/ui/chart_stack/cards.py`。

- [x] **Step 1(特征测试先行):** 写 `tests/ui/test_chart_card_construction.py`
  (spec「新增测试」第 2 条):对每个 `chart_mode` 构造 `_ChartCard`
  (canvas 参数用与既有测试相同的构造方式,参考 `tests/ui/test_chart_stack.py`
  的夹具),快照子 widget 类名多重集 + 关键属性存在性。在**基线**上跑绿,单独 commit。
- [x] **Step 2:** 把 L106-404 按内部注释带切成 `_init_state` / `_build_chrome` /
  `_build_toolbar_routing` / `_wire_hint_rotation` / `_wire_discovery_hooks` /
  `_wire_nudges`(实际边界以代码注释块为准,方法名可据实调整),`__init__`
  按**原语句顺序**依次调用。逐条语句对照,禁止重排。
- [x] **Step 3:** 验证:特征测试必须原样绿;hint/nudge 行为测试全绿。

Run: `PYTEST tests/ui/test_chart_card_construction.py tests/ui/test_chart_stack.py tests/ui/test_hint_nudges.py tests/ui/test_nudge_card_surfacing.py -q`

---

## Task 5: 收尾

- [x] **Step 1:** 全量 UI 测试对比 Task 0 基线失败集,新旧差异必须为空
  (新增测试文件除外)。
  **结果(2026-08-06)——跑了两轮,A1 方向(c)搬迁前后各一次,数字完全一致:**

  - 搬迁前 @ `285132b1`:`2 failed, 2957 passed, 1 deselected` in 291.80s
  - 搬迁后(`stats.py`/`toast.py` 落地):`2 failed, 2957 passed, 1 deselected` in 304.98s

  **两轮失败集与基线逐字一致,通过数一个不差 ⇒ 搬迁零回归:**
  - `tests/ui/test_batch_runner_thread.py::test_sheet_preview_and_result_share_channel_metadata_reference`
  - `tests/ui/test_hint_nudges.py::test_view_compact_tabs_ranks_between_coaxis_and_custom_action`

  通过数 2914 → 2957(+43),与两个新测试文件的收集数**精确对账**:
  `test_widgets_misc.py` 19 + `test_chart_card_construction.py` 24(含参数化展开)
  = 43。即零回归、零新增失败。

- [ ] **Step 2:** 真机冒烟(非 offscreen)。**本轮未执行**——按调度要求跳过 GUI 启动,
  且 offscreen 不得冒充真机验收(CLAUDE.md Gotchas)。改为交人工验收,清单见下。
  A2/A3/A4 涉及的对话框、FFT 卡片、BLF 已由前序执行者覆盖,此处只列 A1 相关三样;
  但注意 **A1 的搬迁并未落地(见上文停止说明),这三样代码本轮零改动**,
  该清单实为「若将来执行 A1 搬迁后需复验」的项:
  - **通道树**:打开一个多通道文件 → 展开文件节点 → 每行左侧色点清晰无锯齿
    (Retina 下尤其看边缘),勾选/取消勾选状态与色点颜色随通道配置同步。
    判定标准:色点为 11pt 紧凑圆角块、非模糊、非 14pt 重块。
  - **Toast**:触发一次保存工程(或任意带提示的操作)→ 底部居中浮出提示条,
    文案正确、约 3.5s 后自行淡出;连续触发两次只显示最新一条,不叠加、不残留。
  - **统计条**:勾选 2 个以上通道 → 折叠态一行显示每通道 `min/max/rms/p2p`
    并以 ` │ ` 分隔;点展开箭头 → 展开出 7 列统计表;取消全部勾选 → 回到「— 无通道 —」。

- [x] **Step 3:** 汇总四项的行数变化与 commit 清单,附在 PR 描述。

**Commit 清单(`main`..HEAD,时间顺序):**

| Commit | 任务 | 说明 |
| --- | --- | --- |
| `741852cf` | Task 0 | 记录 `tests/ui/` 基线失败集 |
| `2d4d8ee0` | A2 | `dialogs.py` → `ui/dialogs/` 包 |
| `562b9477` | A3 | BLF/DBC 子系统提到 `io/blf_format.py` |
| `c39acc9f` | A4 | `_ChartCard.__init__` 装配特征测试(拆分前) |
| `9c0b479c` | A4 | `__init__` 拆成有序 build/wire 方法 |
| `285132b1` | A1 | Toast / StatsStrip / StatisticsPanel 直测(Step 1) |

**行数变化:**

| 任务 | 变化 | 验收准则 | 结果 |
| --- | --- | --- | --- |
| A1 | `ui/widgets/__init__.py` 1760 → 1591(−169);新增 `stats.py` 85 + `toast.py` 96;新增测试 +224 | `__init__` ≤ 60 行 | **部分达成**——按裁决只拆零风险子集,`_swatches`/`channel_tree` 留作独立后续项 |
| A2 | `dialogs.py` 1256 → 删除;新包 15+600+648+38 = 1301 | `dialogs/__init__.py` ≤ 20 行 | 达成(15 行) |
| A3 | `loader.py` 1147 → 787(−360);新增 `blf_format.py` 384 | `loader.py` 减少 ≥ 330 行 | 达成(−360) |
| A4 | `cards.py` 1167 → 1200(+33);`__init__` 299 → **14 行**;新增测试 +311 | `__init__` ≤ 40 行 | 达成(14 行) |

Run: `PYTEST tests/ui/ -q`
