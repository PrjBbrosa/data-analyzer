# 导入恢复 Followup 独立分支执行记录

日期：2026-11-18。§1–§7 记录 `2c08c890` 独立分支验收；后续 main 合并接收见 §8，旧的未实施状态不直接代表合并后的源码。结论：**partial，不能作为 native 默认启用或发布验收。**

合同：[Followup Spec](../specs/2026-11-17-import-recovery-review-followup-spec.md)、[Followup Plan](../plans/2026-11-17-import-recovery-review-followup-plan.md)。原始问题与严重度保留在 Spec §3；本记录不改写历史审查结果。

## 1. 隔离与版本证据

用户明确要求“开一个分支执行 followup plan，别和现有 Grok agent session 混到一起”。执行位置：

- 分支：`codex/import-recovery-followup`。
- Worktree：`/Users/donghang/.codex/worktrees/import-recovery-followup/data analyzer`。
- 基线：`68013e346e0dba3b60922117b68bf555e5d47802`，已包含 `63619b1c` 的 native 修复；没有将旧审查的 `c848fdb1` 当作当前代码。
- 原 checkout `/Users/donghang/Downloads/data analyzer` 只读核对；未编辑、清理、暂存其文件。原目录中的同名 followup 文档保留为起草版本，本分支副本为执行版本。
- 本轮只修改 14 个产品文件、6 个测试文件和 3 个文档。未改 `_project_io_mixin.py`、原生计划、CLAUDE 文件、默认入口或版本。未合并、推送、发布，未启动第二个全套测试。
- 运行时：macOS 27.3 arm64；Python 3.12.16；numpy 2.5.3；asammdf `8.8.32+tracelab.1`；pytest 9.1.1；Qt 5.15.14 / PyQt 5.15.11；pyqtgraph 0.14.0。使用现有项目 venv，未安装或更改依赖。

产品/测试最终文件内容清单的 SHA256：`c8c7f3e096eb2d848289e219810e05b7dc3168821f37f7a04e0f47c18e6967e4`。算法：按路径排序，对 20 个文件分别 SHA256，再对 `{路径:完整hash}` 的 `json.dumps(sort_keys=True,separators=(',',':'))` UTF-8 内容 SHA256；文件清单见 §7。文档不参与此指纹，避免自引用。

测试分波次运行。下列结果不能累加成最终快照的“总通过数”；每个未改动 owner 复用其已有证据，后续改动的 owner 单独重验。全套和跨平台验收未执行。

## 2. 修复与验收账本

| 项 | 修复前证据 | 本分支实现和当前证据 | 状态/边界 |
| --- | --- | --- | --- |
| H01 | 4 个终态 weakref 红测；完成的 call 保留宿主/数组 | coordinator 在 worker drain/continuation 后清空最后调用、workflow/factory/完成/进度回调。成功、错误、取消、session 失效的 bound transform/参数释放，队列下一项继续；真实 Cocoa 重试后旧/新 worker 均消失 | 定向 PASS；完整 Cocoa 父销毁/最后窗口退出仍归 H06 |
| H02 | 2 个编辑/重放红测；abs→derivative 得 1 而非 4 | 暂存和应用后的派生统一保留 time/axis/validity/segment/revision；真实编辑器导数为 4，非等间距三级积分满足 `4*t`；空/单点、无效掩码和跨 gap 拒绝有回归 | 定向 PASS |
| H03 | 应用后目录有派生名但无法读取/继续派生 | FileData 拥有逻辑目录，统一读取支持 span/halo；删除后不能通过旧 physical key 复活，同名新派生独立。真实导入→编辑器→应用→勾选/绘图→分析准备→schema 6 保存通过；选定暂存派生 CSV 回读正确且不夹带未选通道 | **partial**：未完成真实项目重开 |
| H04 | MDF2/3 最小文件红测，MDF4 控制通过 | 类型、转换、失效位按版本分支；MDF2/3 读前验证 record coverage、offset/width、channel/byte budget。真实 broker 验证 2.14/3.30/4.10 × 空/单点/多点，每文件含整数/浮点、大小端、identity/`2*raw+3`；低预算拒绝后正常读取、readonly/shared/source hash 均验证 | 支持的标量矩阵 PASS；不等同旧格式所有布局、R01 或 Windows 验收 |
| H05 | 12 个精度红测、1 个控制通过；两点 int64 合并 | 中立 bounded-chunk significant-bit 检查，在 float64 转换前拒绝；允许精确的大偶数/极值，原始 store 不改。准备政策版本升至 `m4-same-axis-2`。真实 FFT dispatch 不进入计算，Order 不构建 job，原因含 float64；真实 Batch 单条失败，time/FFT 合法范围可继续 | 定向 PASS；完整多入口/平台矩阵交 B5/B6 |
| H06 | 原报告未测矩阵 | Cocoa 生产短框/Batch/UltraView，以及真实资源拒绝→等待处理→fresh limits→独立新 worker 成功通过；见 §4 | **partial**：完整 P02、Windows 未关闭 |

补充发现：`read_logical_channel` 在 time 长 8、values 长 9 时会由切片静默截短。新增红测实际失败后，在读取边界验证一维/equal shape/失效 mask shape。长值、二维值、短 mask 三类都明确抛错；不是通过 `min(len(...))` 隐藏输入损坏。

派生副本预检复用 `preflight_prepare` 和既有字节上限，并计入已持有的暂存/应用派生数组；取消/切文件/关闭源清理所属状态。这只是该 owner 的准入与释放，不代表 B5 的全应用 reservation、LRU 或 RSS 峰值已达标。

共享 Batch 入口审查时另发现两处 `fd.data.columns` 会拒绝 native；改为已有 `_source_has_channel`。测试也暴露了 FFT 旧 monkeypatch seam 不接受新增 keyword 的回归；已限定只有 native 分支传入 rejection 收集参数，复验 compute-progress 集成通过。没有扩大 Batch reporter 的终态写入路径。

## 3. 定向验证

本地原始日志位于 `.state/import-recovery-followup/`，不入 Git。以下列出实际结果和可复验范围；不是依赖本地日志才能重建的唯一说明。

共同 offscreen 前缀：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. /Users/donghang/Downloads/data\ analyzer/.venv/bin/python -m pytest
```

| 验证范围/日志 | 结果 | 证据解释 |
| --- | --- | --- |
| `tests/ui/test_native_derived_followup.py`，`dispatch-final.log` | **16 passed** | 最后新增的真实 FFT dispatch/Order job 拒绝、实际导入/编辑/应用/保存、形状边界全部包含 |
| `tests/ui/test_native_derived_followup.py tests/test_signal_access.py tests/test_channel_edit_log.py`，`logical-shape-final.log` | **37 passed** | shape 修复后读取/配方 owner 回归；后续只增加上一行的 dispatch 测试 |
| `tests/ui/test_native_derived_followup.py tests/ui/test_compute_progress_integration.py`，`product-chain-final.log` | **37 passed** | native/legacy 参数兼容修正后；当时尚未加入 shape/dispatch 新用例 |
| 准备层、保真、原始导出、真实 Batch 精度路由，`precision-final.log` | **85 passed, 2 xfailed** | `test_analysis_signal_prepare.py`、`test_mf4_native_fidelity.py`、`test_mf4_native_export.py`、`test_native_precision_routes.py`；F08/F09 的原有 strict xfail 保持原状，不计通过 |
| MDF reader/safety/loader/adapters/transport，`io-green.log` | **185 passed** | `test_mdf_native_reader.py`、`test_mdf_reader_safety.py`、`test_mf4_loader.py`、`test_source_adapters.py`、`test_import_transport.py`；此后 reader 未变 |
| coordinator/editor UI owner，`ui-green.log` | **73 passed** | H01 引用/队列与编辑 UI 回归；后来 shape/dispatch 变化用上述对应 owner 重验 |
| 原生消费者/迁移/导出相关 owner，`consumer-green.log` | **81 passed** | 波次结果；不能据此关闭真实项目重开 |
| 依赖/packaging/state ownership/lambda/Batch reporter，`boundaries.log` | **57 passed, 2 skipped** | 中立层、native、GUI import boundaries，packaging source checks、MainWindow 状态、signal-connection 与 reporter 门禁；skip 不作为平台通过 |
| Cocoa 独立验收，`cocoa-acceptance.log` | **2 passed in 5.97s** | 真实 Cocoa 平台证据，详见下节 |

另外两个失败命令已定位并处理：`recovery-final.log` 的 **176 passed, 1 failed** 是上述 legacy fake fetch 不接受 keyword，修正后的 compute-progress 集成已通过；初次真实产品链用错 `plot_selected` 方法名的测试错误已改为实际 `plot_time`，之后真实链通过。失败记录没有冒充绿色结果。

定向复验只需选择相关 owner，不应把表中所有行再叠加跑一遍。文档检查使用路径/引用检查与 `git diff --check`；没有因文档更新启动运行时全套。

## 4. Cocoa 验收与未验证结果

实际命令范围：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=cocoa PYTHONPATH=. \
IMPORT_RECOVERY_EVIDENCE=.state/import-recovery-followup/cocoa \
/Users/donghang/Downloads/data\ analyzer/.venv/bin/python -m pytest \
  tests/ui/test_import_recovery_followup.py -q
```

使用生产 MainWindow、AppMessageDialog、BatchSheet、UltraViewSheet、正式 broker/reader/transport。真实资源重试测试仅隔离 toast 与 fresh-limit 取值观察点；没有用 fake worker/result 代替导入。加载真实应用 QSS，等待布局稳定，实际渲染截图已检查。

| 窗口 | 宽×高（逻辑像素） | DPR |
| --- | --- | --- |
| 短消息 | 380×115 | 2 |
| Batch | 1080×760 | 2 |
| UltraView | 1280×800 | 2 |
| 资源重新检查 | 498×166 | 2 |
| 等待处理的进度窗 | 420×152 | 2 |

重试事实：初始 memory limit `251658240` bytes（240 MiB），合成较大 MDF 被明确拒绝；进入提示框时 `_thread is None` 且进度为 `waiting_user`。重新检查调用 fresh default 一次，本次取得 `1357189120` bytes；再次请求新 worker，PID 分别为 80404/80503，结束后均不存在。唯一终态 `success`，注册一个 native FileData，最后调用和进度窗引用均清空。预算大小随运行环境变化，不把本次值写死为产品门槛。

必须保留的限制：

- 未加载完整 QSS/未等待布局的早期截图不作为几何证据；按真实启动条件重验后正常，未为测试修改产品尺寸。
- 将本文件与额外 coordinator 生命周期用例混跑的一次 Cocoa 命令停滞，采样显示 Qt/AppKit event loop 等待，已停止该进程；**该整次命令为 UNVERIFIED，不能把已输出的点算通过**。目前未证明是产品还是测试交互问题。独立 2 项通过只覆盖本节范围，不覆盖完整 P02。
- offscreen 生命周期用例与真实 Cocoa 重试是不同证据。没有宣称 Cocoa 父销毁/重复取消/迟到回调/最后窗口退出完整矩阵通过。
- Windows Full/Lite windowed EXE、100%/125%/150% DPR：**UNKNOWN，未运行**。源码 packaging 检查不能替代。

## 5. 剩余接收项与上游关系

| 剩余项 | 当前证据/责任 | 下一步与退出条件 |
| --- | --- | --- |
| H03 完整保存重开 | `_project_io_mixin.py::_restore_project_file_refs` 仍未按 native policy 分派；候选事实读 file-level fs，`_apply_verified_file_ref` 对 native ref/legacy source 保持 unapplied。此文件本轮未改 | 原生 B5/N08 owner 接续真实 `save→open_project→read/plot/analyze/继续派生`；使用各通道时间、配方重放，源变化明确悬挂。当前“保存成功”和内存 replay 不能替代 |
| H06/P02 Cocoa 混合生命周期 | 本轮独立资源重试通过，混合命令停滞未定因 | 恢复 T4 owner 以新进程拆分定位父销毁/取消/迟到/队列/状态栏，确认停止后不留 worker、终态一次、下一任务继续；不得加 sleep/xfail 掩盖 |
| W01/原生平台 | 未获得 Windows 新鲜包证据 | B6 唯一平台 owner 验证 Full/Lite、DPR、资源拒绝/取消/重试、工作窗；记录包 hash 与真实运行结果 |
| F08/F09、N07、R01、Replay/全入口 | 保留原生计划范围及两个 strict xfail；本轮未重新实现 | B5 关闭设计/实现合同，B6 执行事故样本、固定预算、性能及完整平台验收；H05 的精确转换准入不构成抗混叠正确性证明 |
| S7 联合门禁 | 本分支 focused 证据可接收，尚未与 Grok 后续更改集成 | 集成 owner 对比两边重叠文件，合并后仅重跑受影响 owner/boundary；稳定里程碑由唯一 owner 顺序运行主套与 acquisition_ui。未获合并/发布授权前不操作 main |

**无需再起一份重复 followup plan。** 本 Plan S3/S6/S7 和上游 B5/B6/T4 已有明确归属；把本表作为接收待办即可。只有独立定位出新的、现合同未覆盖的产品缺陷，才扩展问题矩阵。不能因为 Grok 的 N01–N09 工作已提交，就自动关闭以上项目重开、平台或资源合同。

Batch 的现有 `fft_time/order_time` 参数正规化会忽略源数据 `time_range`，因此其整段含不可精确整数时仍拒绝；测试明确保留此政策。time/FFT 的有效选区则按读取范围先裁切再准入，段外坏值不阻断合法请求。此差异不作为“全方法范围语义已统一”的证据。

## 6. 收尾检查

本轮使用既有 weak-host、native numeric admission、partial-import identity/gap、dialog-purpose lessons；新增回归关闭这些已记录模式，没有新建重复 lesson。`scripts/lessons/check.py --status`：`lesson_required: False`。本轮创建的 venv 链接只用于隔离目录运行，交付前移除；没有删除主工作区环境。截图、日志、采样和临时编辑脚本均留在忽略的 `.state/`，不提交。

## 7. 指纹文件清单

| 文件 | SHA256 前 16 位 |
| --- | --- |
| `mf4_analyzer/analysis_signal_prepare.py` | `8abd361e83712cfd` |
| `mf4_analyzer/batch.py` | `e14f5ee4d39854e8` |
| `mf4_analyzer/batch_output.py` | `ff0ce89ac8eeedf5` |
| `mf4_analyzer/io/channel_edit_log.py` | `f5604f015f6ed795` |
| `mf4_analyzer/io/file_data.py` | `206a9138ec570bc0` |
| `mf4_analyzer/io/mdf_reader.py` | `65d80ba89eb1106f` |
| `mf4_analyzer/io/signal_access.py` | `6ff44f83bdd1f8bd` |
| `mf4_analyzer/signal/numeric_precision.py` | `9d3bf5312968d962` |
| `mf4_analyzer/ui/dialogs/channel_editor.py` | `a94edd928896c1e2` |
| `mf4_analyzer/ui/hints.py` | `b5222dcf5cdb7ef2` |
| `mf4_analyzer/ui/main_window/_fft_mixin.py` | `fad33393b74d8bc2` |
| `mf4_analyzer/ui/main_window/_order_mixin.py` | `d0754de87f3cb5ac` |
| `mf4_analyzer/ui/main_window/import_coordinator.py` | `d8c7edfabf586fe4` |
| `mf4_analyzer/ui/quickref.py` | `185cae41dff6aca6` |
| `tests/test_analysis_signal_prepare.py` | `29f3cb917b48fc66` |
| `tests/test_mdf_native_reader.py` | `341e6cb13aa8d1ad` |
| `tests/test_native_precision_routes.py` | `a6fe7b12b7bf9562` |
| `tests/ui/test_import_coordinator.py` | `484f20cac7dae86f` |
| `tests/ui/test_import_recovery_followup.py` | `a156864f36785562` |
| `tests/ui/test_native_derived_followup.py` | `ac85ad33a73b09ed` |

## 8. 用户授权 commit and merge 后的接收记录

目标为本地 main；接收其提交 `67c64205ee603587098b4e4dc8faea9831010833`，包含 PR #44 的 native 项目重开/整数比对齐与 PR #41 的 UltraView 修复。先在隔离 worktree 合并并验证，再更新主工作区；不推送远端。

唯一文本冲突位于 `analysis_signal_prepare.py` 的 imports：同时保留本分支精度 helper 与 main 的滤波依赖，保留精度政策版本 `m4-same-axis-2`。额外接缝测试发现 main 的 `_align_uniform_pair` 直接滤波/转换会绕过本分支的整数精度准入；左右输入两个红测均返回 ready 而非 rejected。已在该入口调用相同的中立精度 helper，拒绝时不运行 filter、不生成输出；没有复制精度算法或改变对齐设计。

实际验证（相同 offscreen 前缀与项目运行时，未执行全套）：

- 合并后的准备/保真/Batch 精度、配方/读取、依赖边界、真实产品导入/项目重开、native 消费者、coordinator 和 MainWindow ownership：**183 passed, 12 warnings**（`merge-focused.log`）。范围为 `tests/test_analysis_signal_prepare.py tests/test_mf4_native_fidelity.py tests/test_native_precision_routes.py tests/test_channel_edit_log.py tests/test_signal_access.py tests/test_native_import_boundaries.py tests/test_signal_no_gui_import.py tests/ui/test_native_derived_followup.py tests/ui/test_mf4_native_product_path.py tests/ui/test_native_signal_consumers.py tests/ui/test_import_coordinator.py tests/ui/test_main_window_state_ownership.py`。
- 新增两条跨采样率精度接缝测试先 **2 failed**；补保护后重新跑受影响的 `test_analysis_signal_prepare.py`、`test_mf4_native_fidelity.py`、`test_native_precision_routes.py`、`test_signal_no_gui_import.py`、`test_native_import_boundaries.py`：**73 passed**（`merge-precision-green.log`）。两次通过数不相加为全树验收。
- `git diff --check`、未解决冲突与文件范围检查通过。数值保护沿用既有 numeric-admission lesson，没有新独立规则。

main 的 native 项目重开用例和 F08/F09 定向实现测试现已通过，因此 §5 对旧源码“尚未分派/两个 strict xfail”的描述仅为 `2c08c890` 历史状态；本次没有重做完整派生项目重开、全入口、资源或平台矩阵，不因此关闭整体 B5/B6。Cocoa 完整生命周期及 Windows UNKNOWN 仍保留。

主工作区两份与已跟踪文件同名的未跟踪 followup 草稿，原字节移至其 `.state/import-recovery-followup/pre-merge-drafts-*/` 备份，避免覆盖；其他未跟踪目录和 native completion spec 不移动、不暂存。最终合并提交与工作区状态由本次交付消息给出。
