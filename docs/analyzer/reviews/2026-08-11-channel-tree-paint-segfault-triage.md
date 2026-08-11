# 通道树 delegate paint 交错 segfault — Triage 记录

- 日期：2026-08-11（深夜，pinning 实施 review 期间发现）
- 状态：**已归因为既有问题（与 pinning 改动无关），待专项修复**
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
