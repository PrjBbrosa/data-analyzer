# 通道树 delegate paint 交错 segfault — Triage 记录

- 日期：2026-08-11（深夜，pinning 实施 review 期间发现）
- 状态：**已修复**（2026-08-12，见 §6；引入提交 `f85b5d4e`，修在
  `tests/ui/conftest.py`）。§1–§5 保留当晚的归因过程原貌，其中 §2 结尾对引入窗口的
  推测已被 §6.1 的逐提交验证纠正。
- 关联：`2026-08-11-analysis-cache-view-pinning-spec.md` 的收尾验证被此崩溃阻断；
  CLAUDE.md「全量要分两条命令跑」记录的 acquisition_ui 交错崩溃是**另一处**同类问题

## 1. 现象

主体套件（`pytest --ignore=tests/acquisition_ui -q`）在约 **49%**（第 ~3000 个
用例，落在 `tests/ui/test_channel_widget.py` 开头段）确定性 SIGSEGV 中断，无汇总。
两次连续复现（22:42 与 23:0x 各一次），崩溃点一致。

faulthandler Python 栈（两次运行踩点略有不同，但都在同一个
`_ChannelLeafDelegate.paint` 调用内）：

```
mf4_analyzer/ui/widgets/channel_tree.py:358 paint → :130 _row_shows_checkbox   # 工作区树
mf4_analyzer/ui/widgets/channel_tree.py:312 paint → :282 _paint_pts → :297 _paint_text  # HEAD worktree
pytestqt/plugin.py:220 _process_events   （pytest_runtest_call 期间）
```

原生栈（macOS `.ips`）：`sipQTreeWidget::drawRow → sipQStyledItemDelegate::paint
→ Python → QPainter.drawText / QModelIndex.flags → KERN_INVALID_ADDRESS`。
即 **paint 事件在 `_process_events` 中被投递给了 model/item 已释放的通道树**
——QModelIndex 悬垂，典型的 wrapper/所有权生命周期问题，不是 paint 逻辑错误。

## 2. 归因：与 2026-08-11 的 pinning 实施无关

- **干净 HEAD A/B**：在 `git worktree`（HEAD = `5477add1`，不含 pinning 工作区
  改动）用同一命令复跑 → **同样 segfault、同一位置、同一家族栈**。
- **历史崩溃日志**：`~/Library/Logs/DiagnosticReports/` 里 2026-08-11 全天有
  ~20 个同家族 Python 崩溃（02:57 起、15:36–15:49 密集六连、21:15–21:21 三个、
  22:42/23:0x 为本次 review 的运行），最早的批次远早于 pinning 实施。21 点档
  三连很可能就是实施方尝试跑全量时崩的——这解释了 pinning plan 实测记录里
  只有聚焦数字、没有全量数字。
- 交错依赖：单跑 `test_channel_widget.py`、或「新增 pinning 测试 + 通道树测试」
  组合均不复现；需要前置数千用例的状态。与 CLAUDE.md 已记录的 acquisition_ui
  交错崩溃同一类（单跑不崩、全量交错崩），但栈不同、属另一处病灶。

注意：CLAUDE.md 的全量绿基线标注「树内容即 merge `2c8e9b5a`」。当前 HEAD 已
前进（WWT 系列 + `f85b5d4e` channel-tree chrome + `5477add1` 12-View）。最早
崩溃在 02:57，早于 `5477add1` 的提交时刻（21:54），结合 `f85b5d4e` 名字就叫
"stabilize channel-tree"，**引入窗口大概率在 `2c8e9b5a`..HEAD 之间的
channel-tree/12-View 相关提交**，未做逐提交 bisect（见 §4）。

## 3. 对验证口径的临时影响

在专项修复落地前，「主体一条命令」的全量口径对当前 HEAD 不可用。临时口径
（本 triage 当晚实测）：

```bash
pytest --ignore=tests/acquisition_ui --ignore=tests/ui   # 段1：非 ui 主体
pytest tests/ui                                           # 段2：ui
pytest tests/acquisition_ui                               # 段3：采集 UI（原有口径）
```

结果见 §5。分段传参均为整目录、不重复进出目录，不触发根 conftest 防护的
「目录重复收集」陷阱。

## 4. 建议的后续（专项，不并入 pinning 收尾）

1. `2c8e9b5a..5477add1` 间对 channel-tree 相关提交做交错 bisect（每步跑主体
   一条命令即可判崩/不崩，约 4 分钟/步）。
2. 病灶方向：`_ChannelLeafDelegate.paint` 经 `option.widget or self.parent()`
   触达宿主树；排查测试 teardown 中树/模型先亡、delegate 仍被某个存活视图引用
   的路径（对照 `docs/analyzer/reviews/2026-08-11-two-day-delivery-and-frf-view-review.md`
   §4.3 的僵尸 wrapper teardown 簇经验）。
3. 修复后把 CLAUDE.md 的全量基线数字与「两条命令」说明更新到位；若本临时
   三段口径已无必要，删除本节引用。

## 5. 实测记录（2026-08-11 深夜，pinning 工作区树）

- 段1 非 ui 主体（`--ignore=tests/ui`）：**2263 passed / 11 skipped**，全绿。
- 段2 `tests/ui` 整目录：在 ~#844（`test_channel_widget.py` 开头段）segfault
  ——即本文的病灶，位置与全量运行时一致（都卡在
  `test_channel_editor_expression.py → test_channel_widget.py` 边界后首批
  泵 paint 的用例上）。
- 段2 拆两半（按上述边界切文件列表）：前半 **851 passed + 1 failed**，后半
  **2904 passed + 1 failed**，均无 segfault。两个 failed 都与 pinning 无关：
  - `test_batch_blf_dbc_context.py::test_batch_blf_cancel_skips_blf_but_keeps_other_files`
    ——单跑通过；且该测试文件当时正被**并行会话**（在途的 CANoe ASC/CAN 导入
    工作，同时段还在改 `io/loader.py` / `source_adapters.py` / CLAUDE.md）
    编辑，属在途污染 + 文件序口径的顺序敏感，非回归。
  - `test_surface_layering.py::test_surface_top_bottom_and_panels_render_rounded_corners`
    ——在干净 HEAD worktree 单跑**同样失败**，是 `5477add1`（改过
    `style.qss`/toast/tabbar）自己遗留的既有红，与 pinning 及在途 ASC 工作
    均无关，需另行修复。
- 段3 tests/acquisition_ui：**355 passed**（与基线一致）。
- pinning 相关聚焦集（两个新守卫文件 + 四个缓存契约文件 + coordinator +
  状态所有权 + quickref/hints/multiview 相关面）：**269 passed / 0 failed**。

结论：除本文的交错 segfault（既有）与上述 `test_surface_layering` 既有红外，
全部用例在分段口径下通过；pinning 改动未引入任何失败。

## 6. 已修复（2026-08-12）

### 6.1 引入提交

`f85b5d4e`（`fix(ui): stabilize channel-tree and follow-link chrome`）。

逐提交验证走 `git worktree`（主树当时脏且有并行会话），判据＝
`pytest tests/ui -q` 是否 exit 139。崩溃点在 21%，故「跑过 36% 无崩」即判 good：

| 提交 | 结果 |
| --- | --- |
| `2c8e9b5a`（基线 merge） | 36% 无崩 |
| `fc47cc25`（follow link Stage 1.1） | 36% 无崩 |
| `d488f348`（release v7.9.8） | 36% 无崩 |
| `f85b5d4e`（channel-tree chrome） | **exit 139**，栈与 §1 同族 |

§2 里「最早崩溃 02:57 早于 `f85b5d4e`」的推测不成立：02:57 那次崩的是当时**在途**
的工作区，不是任何一个已提交树。

### 6.2 机制

一句话：**测试体返回后，被 show 过的顶层 widget 变成「只被自身引用环持有」的垃圾，
而 pytest-qt 还在往它身上泵 paint；paint 里的 Python 分配触发 gen-0 回收，把 widget
连环收掉，sip 在画到一半时析构了 C++ `QTreeWidget`/viewport，下一次穿过悬垂对象的
调用就踩空。**

拆开：

1. `QtBot.addWidget` 只存**弱引用**（`pytestqt/qtbot.py` 存 `weakref.ref`，
   `_close_widgets` 里 `w = w()` 解引用）。测试体一返回，无父的 `QWidget` 就只剩
   自身引用环撑着——PyQt 里这种环必然存在（`_ChannelTree._owner` 反指持有它的
   `MultiFileChannelWidget`，每个绑定方法的信号连接又添一条）。引用计数收不掉它，
   它还是 shown、还排着一次 update。
2. pytest-qt 随后又调 3 次 `app.processEvents()`（`pytest_runtest_call` 后 1 次、
   `pytest_runtest_teardown` 里 2 次），把那次排队的 paint 投递下去。
3. `f85b5d4e` 把 **Pts 列（column 1）的每一行**都改走 Python paint——改之前只有
   channel 行走自绘、其余行直接落 C++ `super().paint()`，零 Python 分配。现在每个
   Pts 单元都要 `QRect` 拷贝 + `QStyleOptionViewItem` 拷贝 + `initStyleOption` +
   `QFontMetrics` + elided `str`。
4. 这些分配把 gen-0 阈值顶穿，**在 paint 内部**触发一次回收，垃圾环连同 widget 一起
   被收，C++ 对象当场析构；紧接着的 `QPainter.drawText`（`_paint_text:297`）或
   `QModelIndex.flags`（`_row_shows_checkbox`）/ `index.sibling().data()`
   （`_channel_data:92`）就踩空 —— 这解释了为什么每次栈的落点都不同：踩空的是
   「回收之后恰好执行到的那一句」。

### 6.3 证据（三个实验）

- **探针**：给 `_ChannelLeafDelegate.paint` 加计数、`gc.callbacks` 里报告「回收开始时
  paint 深度 > 0」。实测输出
  `!!! GC start during delegate paint (depth=1, gen=0) hit#1`，**紧接着**就是
  `Fatal Python error: Segmentation fault`。
- **反证**：同一条命令加 `gc.disable()`（显式的 `gc.collect()` 不受影响，套件本来
  就每条用例收一次）→ **100% 跑完、0 崩**（880 passed）。
- **修复后再开探针**：GC 依旧在 paint 中触发（3 次），**不再崩**（882 passed）。
  即证明救命的是「widget 被钉住」，不是「GC 不再发生」。

### 6.4 修法

只改 `tests/ui/conftest.py`（测试基建的生命周期错误），**未动任何产品代码**，
未跳过 / 放宽 / 删除任何用例：

- `pytest_runtest_call` 的 post-yield：此刻测试体已返回、pytest-qt 还没开始泵事件，
  把 `QApplication.topLevelWidgets()` 强引用钉进模块级 `_PINNED_TOPLEVELS`。
  只钉顶层就够：子 widget 由父在 C++ 侧持有，能被 GC 析构的只有 Python 拥有的顶层。
- `pytest_runtest_teardown` 的 post-yield：释放，并**立刻 `gc.collect()`**。

第二步的 collect 不是可选的，踩过一次坑：`_collect_mpl_cycles_between_tests` 的
collect 跑在钉住期间（fixture finalizer 在 teardown 的 yield 里，早于本 hook 的
post-yield），少了这句，这批 widget 会漏进**下一条用例的体内**——实测让 16 条
`test_pg_dense_raster` / `test_pill_switch` 变红，因为上一条用例残留的
`TimeDomainCanvasPG` 仍占着 dense-raster 的内存额度，新画布被拒绝准入
（`entry_for(ck) is None`）。加上这句后生命周期与修复前等价：一条用例的 widget
在下一条开始前就已回收，只是回收点从「测试体退出」挪到了「teardown 泵完事件之后」。

释放点也不能更早：本 hook 是普通 wrapper，post-yield 排在 pytest-qt 的 `trylast`
wrapper **之后**，也排在所有 fixture finalizer 之后（包括自己会 `processEvents()`
的 `_own_chartstacks`）。任何更早的释放都会重新打开这个窗口。

### 6.5 验证（HEAD `3ab58b48`）

- `pytest tests/ui -q` **连续两次**：**3774 passed / 0 failed / 0 errors**
  （8:29 与 9:03），两次都无 segfault。这是该目录首次一条命令跑完。
- 主体一条命令 `pytest --ignore=tests/acquisition_ui -q`：
  **6048 passed / 11 skipped / 0 failed / 0 errors**（14:27），无 segfault。
- 对照：同期干净 worktree（`650fecdf`，不含本修复）跑同一段仍 **exit 139**，
  证明崩溃在新 HEAD 依然存在、且确由本修复消除。
- 顺带澄清 §5 的两条红：`test_surface_layering` 的圆角用例已由 `4ab994b6` 修复；
  期间出现过的 `test_channel_config_manager::..._with_production_qss` 是
  `style.qss` 解析失败导致，已由 `3ab58b48` 修复。两者都与本崩溃无关。

### 6.6 收尾

§3 的三段临时口径可以撤销：主体重新可以一条命令跑完。CLAUDE.md 的全量基线数字与
「两条命令」说明需要按上面的数字更新，但本次修复期间该文件正被并行会话占用，未改；
留给下一位接手者（`tests/acquisition_ui` 的 pyqtgraph `LabelItem.resizeEvent` 交错崩
是**另一处**病灶，本次未动，那条说明仍然有效）。
