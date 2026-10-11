# FRF 计算入口与错误恢复验证

日期：2026-10-05。基线：`67d88ee1`。本轮源码修改尚未提交。

## 行为修复

- 项目恢复/计算失败的诊断允许手动重试，重试继续走既有范围确认与完整预检查，不能绕过错误数据校验。
- 输入/输出缺失、相同、来源不在当前候选范围等当前阻断条件优先显示，仍然禁用按钮。
- Inspector 的瞬时诊断绑定由 MainWindow 提供的不透明请求身份：View、pane、复合来源及时间轴事实、请求范围、计算参数。控件不读取 session，也不把诊断写入项目或预设。
- 全时段、有效范围修正、View/内部窗格/跨 View 焦点切换时，旧请求诊断失效；同一请求重新投影和只改显示参数保留诊断。
- 失败回调沿用已有可见性/焦点判断与 coordinator 过期结果拦截，后台错误不能覆盖焦点侧状态。
- 保留 `set_validation_message(message)` 原有阻断语义，MainWindow 的已完成失败显式传 `retryable=True`。没有数值算法、计算精度、缓存格式或项目格式变更。
- hints/quickref 同步解释重试及必须先纠正的输入问题。

## 回归覆盖

新增 `tests/ui/test_frf_validation_recovery.py`：14 项，覆盖恢复越界 → 全时段 → 实际按钮派发、越界后的确认/取消、修正指定范围、相同计算参数的 View 切换、跨 View 与内部 pane 焦点、后台错误隔离、当前配对错误优先级、显示编辑、同一请求投影、交换配对、反复预检查失败不提交 worker。

初始测试得到 10 个行为失败及 1 个测试代码错误（调用了不存在的 split 方法，已改用真实 `_on_analysis_split`）；随后补齐 3 项横展，最终 14 项通过。没有修改已有测试断言来放宽功能要求。

## 稳定快照验收

工作区有其他会话正在编辑热图布局与多项测试。一次组合检查期间源码指纹变化，并出现热图 `activate_item_layouts` 的 NameError；该结果为 **UNVERIFIED**，不作为本轮验收。

正式验证从 `git archive 67d88ee1` 导出独立快照，仅覆盖本轮 6 个生产/测试文件。快照与当前工作区的这 6 个文件逐字节相同。运行前后生产与测试 Python 的 SHA-256 无变化。

| Gate | 结果 |
| --- | --- |
| Owner：新恢复回归、FRF MainWindow、分析对比回归、范围确认、Inspector 的 FRF 用例 | **161 passed**，20.72 s，stable=true |
| Boundary：MainWindow 状态所有权、UI import、lambda 信号约束、FRF coordinator、hints、quickref | **129 passed**，5.31 s，stable=true |
| Cocoa 原生完整计算 | **1 passed**，1.69 s，stable=true |
| `git diff --check` | 通过 |

Cocoa 使用真实 MainWindow、Fusion、生产 QSS 与图表字体，鼠标点击“全时段”和“计算频响”，经过真实 coordinator/worker 得到画布结果；按钮尺寸、可见性和可点击状态同时检查，结果截图已目视检查。数据来自合成输入输出，不代表用户 `2222.tlproj` 或 Windows frozen 验收。最初只截获派发的原生检查也通过；正式结果以上述真实计算闭环为准。

早期额外运行完整 `test_inspector.py` 时看到 6 个非 FRF 既有失败（3 个 FFT auto-X、3 个内置 preset），与已有 `/tmp/analysis-view-validity-full-main.log` 的失败相同；未改动其代码或断言，最终只使用适用的 FRF owner 范围。未运行全仓库套件，不宣称并行修改中的整个工作区全绿。

证据保留于 `.state/frf-disabled-analysis/`：`red.log`、`recovery.log`、`isolated-owner.*`、`isolated-boundary.*`、`isolated-native-compute.*`、`native-retry.png` 与 `snapshot-manifest.json`。临时源码快照验证完毕后删除，避免积累重复 checkout。
