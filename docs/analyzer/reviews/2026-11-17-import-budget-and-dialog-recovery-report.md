# 8.4.8 导入预算与对话框恢复 · 执行报告

日期：2026-11-17。结论：**部分完成**。短提示、导入进度和资源错误的源码合同已经落地，Cocoa 测到了短框和进度颜色。低内存根因的原生读取已经接到显式正式路径，但产品默认仍是 `load_mf4`，R01 不能关闭。

基线 `c126fcae24b73961eb798b989df1068a94327197`，`APP_VERSION` 仍是 `v8.4.8`。没有发版，没有把事故 MF4 放进 Git。本地探针、截图和账本留在 `.state/`，不作为本报告的替代品。

配套：[Review](2026-11-17-import-budget-and-dialog-regression-review.md) · [Spec](../specs/2026-11-17-import-budget-and-dialog-recovery-spec.md) · [Plan](../plans/2026-11-17-import-budget-and-dialog-recovery-plan.md) · [原生采样 Spec](../specs/2026-11-17-mf4-native-sampling-spec.md)。

## 1. 现在用户能看到什么

普通打开、拖入、最近文件、项目恢复、Batch 和 Replay 仍然调用 `load_mf4`。固定预算 `memory=498,988,944` 下，旧公共轴路径仍拒绝 `638,740,162`。`copies=3` 和数组安全检查没有放宽，默认预算也没有提高。因此图1那类“公共轴太大”的文件，在默认打开里仍然会被拒绝。

被拒绝时，错误框按资源种类给出说明。内存预估可以“重新检查并重试”：旧 worker 回收之后，用新的 `default_limits()` 和新请求只重试失败文件，不沿用对话框里保存的旧上限，也不提高上限。超时仍只加倍时间。

未保存项目这类短提示按内容定高。工作窗继续拒绝任一维小于 200 的有标题顶层计划。导入进度改成自有组件，不再用全程不更新的 `QProgressDialog`。broker 进度到 1 只表示交接，不表示导入成功。

显式入口 `request_explicit_native_import` 才会走 `load_mf4_native`。它不是默认打开。

## 2. 验收

| ID | 状态 | 依据 |
| --- | --- | --- |
| G01 | Cocoa 通过；Windows UNKNOWN | 1366×728 未保存短框客户区 394×146，内容公式 146，多余高度 0。640×360 同样多余高度 0。问号标志关闭。 |
| G02 | 源码有工作窗保护；Cocoa 未打开 Batch/UltraView，标 UNKNOWN | 几何默认仍是 `PURPOSE_WORKSPACE`。无边框和 popup 不套 200 下限。 |
| P01 | Cocoa 复测通过；Windows UNKNOWN | 首次 Cocoa 轨道是纯白。补上 `#importProgressBar` 槽色和填充色后，busy 为 accent 10338 / 其他 13470，满条为 accent 20700 / 其他 3108，纯白像素都是 0。offscreen 右端差 0。 |
| P02 | 组件取消、重复取消和程序关闭通过；父销毁、迟到回调、队列下一项和状态栏同步未在 Cocoa 上重测 | 程序关闭先 `blockSignals(True)` 再关闭，不把关闭当成用户取消。 |
| E01 | 源码与 Cocoa 文案通过 | 内存、磁盘、通道数分开。通道数单位是 `count`，不再借用字节字段。 |
| E02 | offscreen 通过；Cocoa 只点到按钮，未真的重读 | 重试拿到第二次 `default_limits()`，不是旧 `request.limits`。 |
| R01 | 未关闭 | 默认仍是 `load_mf4`。事故样本的界面注册没有重跑。图2 与 Windows 仍是 UNKNOWN。F08/F09 仍是 strict xfail。 |
| W01 | UNKNOWN | 没有新鲜 Windows Full/Lite。Mac 与 offscreen 不能代替。 |

## 3. 原生路径做到哪一步

M0 固化账本和保真合同。M1 增加 `NativeSignalStore` 与 `read_signal`。M2 增加 `DataLoader.load_mf4_native`，失败时不回退到 `load_mf4`。匿名原生准入是 `438,759,714` 字节；事故样本进程内计费是 `88,979,550` 字节。这是准入账本，不是进程 RSS，也不是此前 23.9 MiB 的 buffer 普查。

M3 让游标和统计读 `read_signal`。等距取较早的点，单点不自动勾选。M4 的同轴分析准备走 `prepare_pair`，异轴仍不支持。没有实现 `frozen_antialias_design` 或 `frozen_frf_alignment`。M5 只在确有原生政策、物理键、对齐意图或悬挂通道时写 schema 6；schema 1–5 仍按公共轴恢复，并标记不写回。默认项目 schema 仍是 4，有通道配方时仍是 5。

M6 把显式请求接到 adapter、broker、transport 和界面注册。匿名小文件在固定预算下完成界面注册，源哈希不变，`wide` 保持整数 `2**53+3`。低于必需资源的请求不注册，随后同一个窗口仍能用 `load_mf4` 打开另一个文件。macOS offscreen RSS（不是 Windows，也不是画布 paint）：匿名父进程峰值 `237,060,096`、worker `93,454,336`；事故样本父进程 `231,800,832`、worker `158,744,576`。父进程和 worker 不相加。

事故样本 `1-5.W04_180_10s_rt_11210854.mf4` 的 sha256 仍是 `72d81a087e9816c7dca80633b20f5a899c0a484a6a80465b99a6d2f3c56cf5b3`，大小 `12,353,424`。M6 当时的正式路径在传回父进程时失败，界面注册数是 0。原因不是预算：12 个 enum 通道的物理值和原始值是同一块缓冲区，传输却记成了没有转换；另外 80 个重名通道按显示名回查，同一个通道写了两次。随后的修正是：enum 用 `physical_mode="shared"`，传输按物理通道记录编码，重名显示名标成 `名称 [组:序号]`。合成往返测试通过。同一文件再经 `run_import("load_mf4_native")` 得到 979 个互不重名的通道，12 个 enum 都仍共享原始缓冲区，源哈希不变。这次没有重新打开主窗口做界面注册，所以不能把 R01 写成已通过。

图2 文件 `2.W04_360_1s_rt_11201724.mf4` 在本机附件目录、`testdoc/` 和 `mdfind` 中都没有找到。不能用事故样本代替。

## 4. 聚焦测试

没有跑全套。下面是各段当时的聚焦结果，不是一次合并后的全量数字。

- 短提示几何：`tests/ui_kit/test_dialog_geometry.py` 79 passed；`tests/ui_kit/test_message_dialog.py` 7 passed。
- 进度组件：`tests/ui_kit/test_import_progress_dialog.py` 先 16 passed，补颜色合同后 17 passed。QSS border 简写与该测试一起 8 passed。
- 资源协议：相关选择器 188 passed。匿名公共轴仍拒绝 `638,740,162`。
- 资源重试界面：owner 131 passed；帮助 18 passed；Replay 单独进程 9 passed。
- 原生保真：M0 为 17 passed、14 strict xfail。M2 起 F01–F07 去掉 xfail。最后一次 fidelity 是 36 passed、2 xfailed，没有 xpass。
- 显式正式路径：`tests/ui/test_mf4_native_product_path.py` 7 passed。传输修正后再加上两条往返测试，共 9 passed。
- 项目会话：`tests/ui/test_project_session.py` 与 UltraView 项目会话 109 passed。警告来自既有 pyqtgraph/NumPy 赋值，不是失败。

## 5. 仍不能当作完成

- 产品默认打开还不是原生读取。原生消费者、项目迁移和 Windows 包没有全部闭环，不能切 `load_mf4`。
- 事故样本只证明子进程传输可以读回。主窗口注册、逐点 oracle 和画布 paint 没有在这次修正后重跑。
- 图2 文件和 Windows Full/Lite 是 UNKNOWN。
- F08 滤波和 F09 异轴对齐仍未实现，两个 strict xfail 必须保留。
- Cocoa 没有重测 Batch/UltraView 防退化，也没有重测进度框的父销毁、迟到回调和状态栏同步。
- 全套 pytest 没有跑。不能用上面的聚焦数字推断全仓库通过。
