# 大规模提交质量补强执行记录

日期：2026-11-18。结论：**R01–R07 的局部反例已接上，整体仍是 partial。不能切换普通打开默认，不能发版，也不能把旧 C6/C7 写成通过。**

合同：[Spec](../specs/2026-11-18-large-commit-quality-spec.md)、[Plan](../plans/2026-11-18-large-commit-quality-plan.md)。证据来源：[审查](../reviews/2026-11-18-large-commit-quality-review.md)。版本仍是 `APP_VERSION` v8.4.8。本记录不改写审查时的失败描述。

源码快照：分支 `main`，HEAD `b802b382e38cedc896af4f34f51637aecd819238`。交接点测试前后这个 HEAD 没变，下列文件哈希也没变：

| 文件 | SHA-256 |
| --- | --- |
| `mf4_analyzer/analysis_signal_prepare.py` | `9d9b5c506626347b3f8bb50c47779935bd3083c92c510acc90909be2589319d9` |
| `mf4_analyzer/ui/main_window/window.py` | `f4c82791576f7fb86228a9ce5a1f5c5100fde62741a27b3a1fa7a361610743c2` |
| `mf4_analyzer/ui/hints.py` | `8395f04cb04944bbcb5f0be4b8d1f6de9ed99caabcfd4c9d5acb8f81f7a9d023` |
| `mf4_analyzer/acquisition_ui/replay_tab.py` | `5c4476c9535c7f8e90d61223019e9f481e30c6f9a39675e712bca454720a3a65` |

工作区另有未跟踪的 `CSER TTR/`，以及另一组尚未执行的 `2026-11-18-test-quality-efficiency-*` 文档。它们不在本轮改动里。本轮产品改动未提交。截图、数组和探针留在 `.state/quality-20261118/`，不入库。

没有跑全套 pytest。没有新的 lesson：沿用已有的原生质量、真实消费者和准入规则。

## 交接点

同一份脏工作区上，主进程先跑显示、滤波、预算、FRF、帮助和边界护栏，以及 backend / native Replay 导出。采集界面单独新进程。

主进程：**1 failed, 496 passed**。失败是 HEAD 上已有的 `tests/ui/test_frf_main_window.py::test_frf_completion_publishes_resident_effective_facts_and_warnings`：`FrfParams(**ctx.compute_params())` 收到 `align_then_compute`。产品路径 `frf_params()` 会去掉这个准备开关。`contextual_frf.py` 本轮没改，这条不算 R04 回归，也没有顺手改测试。

采集界面新进程：`tests/acquisition_ui/test_replay_tab.py` **11 passed**。

## R 编号

| 编号 | 状态 | 本轮证据 |
| --- | --- | --- |
| R01 | partial | 1000 点 PlotDataItem 首次绘制和刷新都是 10–19.99。Cocoa 真窗口、切 View、保存重开保持该坐标。选择增量更新没有单独再驱动，仍是 partial。 |
| R02 | partial | 失效千值脉冲在滤波前拒绝，不再出现 115.03 / 112.02。远离坏点的 181 点零段输出为 0。关闭、失败重绘、换 View 会清 companion。换文件没有单独验收。 |
| R03 | partial | 请求级三条反例拒绝，低预算拒绝前完整 hash 为 0。GUI/Batch 生产调用传入中立额度。应用级共存账本、LRU、20 轮 RSS 未做。 |
| R04 | PASS（定向） | `[.1001, 3.5]` 不再被选区首样本误拒。2/4/8、两种方向、非零原点和已知增益/延迟有独立 oracle。真正分数偏移仍拒绝。 |
| R05 | partial | 未选段不能播放；前段 0/1/2，后段 3/4/5。同一时钟共享选择。独立时钟仍不能合并，局部段号不是全局身份。 |
| R06 | partial | 同轴和跨率的生产轻量调用与缓存查找，完整 hash、全量副本、抗混叠和 `load_native_channel` 为 0。百万点耗时和 RSS 未测。 |
| R07 | PASS（定向） | 三条原红测转绿。WWT 与原生长表分开。频响帮助写成同轴直接计算、整数比须用户打开「对齐后计算」。短提示仍受 18 字宽约束。 |

Cocoa 只覆盖本轮反例，不填平台矩阵：`t1-cocoa-custom-x.png`、`t3-cocoa-rejected.png`、`t3-cocoa-valid-segment.png`、`T5-cocoa-waiting.png`、`T5-cocoa-segment0.png`、`T5-cocoa-segment1.png`、`t6-cocoa-hints-replay.png`。

## 仍未关闭

旧 C6：存活源、绑定结果、缓存和并发任务的共存计费；按字节 LRU `min(128MiB, admission_memory/8)`；20 轮生命周期和 RSS；双游标、Replay、导出热路径。请求级 hold 不能代替这些。

旧 C7：完整编辑、保存、重开、再派生；Pin/比较矩阵；事故样本和图 2；原 Spec 性能；新鲜 Windows Full/Lite。有限 Cocoa 截图和这次 offscreen 交接点不能代替它们。

未改 native 默认政策，未改版本号，未改 ink/AA 门槛。
