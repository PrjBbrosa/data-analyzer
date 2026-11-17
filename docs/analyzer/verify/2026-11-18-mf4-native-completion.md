# MF4 原生采样收尾执行记录

日期：2026-11-18。结论：**数值与产品接线 partial，不能切换普通打开默认，不能发版。**

合同：[收尾 Spec](../specs/2026-11-18-mf4-native-completion-spec.md)、[收尾 Plan](../plans/2026-11-18-mf4-native-completion-plan.md)。基线是文档提交 `a43c85c8`。版本仍是 `APP_VERSION` v8.4.8。本记录不改历史 Spec/Plan。

运行环境：Linux offscreen Qt。没有 Cocoa，没有 Windows Full/Lite，没有事故样本 `72d81a087e…`，没有图2文件。这些项保持 UNKNOWN。没有跑全套 pytest。

## 账本

| 项 | 本轮证据 | 状态 |
| --- | --- | --- |
| L01 | 未重写已接收的 `_source_has_channel` | 接收 |
| L02 | 原生 RPM 按真实时钟对齐。信号 `[.2,1,1.8]` 不再把 RPM `[100,200,300]` 变成 `[120,200,280]`。覆盖不足仍拒绝，不延长端点 | PASS（定向） |
| L03 | GUI 中点失效 999 不再算出转速。等长且不重叠的 Custom-X 真实 Runner 单次失败。未知 Fs 的时域原始导出仍走现有「fs 必须为正」合同，本轮没有放宽 | partial |
| L04 | Batch 与 GUI 频响使用 prepared 目标 Fs。2000/1000 Hz 作业的 DTO 为 1000 Hz | PASS（定向） |
| L05 | `byte_limit=1` 在滤波前拒绝，spy 看不到 `_apply_antialias`。对齐段内部 NaN 拒绝，段外坏点不阻断 | PASS（定向） |
| L06 / F08 | 冻结零相位 Chebyshev II。4000→500 的 300/510 Hz、通带 0.30 Ft、2/4/8 倍率和非零初相位进入独立 oracle。用户 Butterworth 未改。单次纹波用 0.049 dB，避免 `sosfiltfilt` 把恰好 0.05 dB 推过 0.1 dB | PASS（offscreen oracle） |
| F09 | 2/4/8、高低率两种方向、非零共同起点、增益 2、已知延迟、多正弦、H1/H2。安全通带内 coherence、增益、相位按合同。非整数比、不同起点、短到吃掉边缘的段为 unsupported | PASS（offscreen oracle） |
| L07 | GUI Excel 复用 `export_native_samples` 长表。`2**53+3` 回读为文本。读取失败的通道不再被静默丢掉后继续导出 | PASS（定向） |
| L08 / L09 | 未重写 reader、store 或精度 helper | 接收 |
| L10 | `materialize=False` 不调用抗混叠，也不做整段 hash。应用级 reservation、准备 LRU、20 轮 RSS 未做；`ImportBudget.used_bytes` 不能当作峰值证据 | partial |
| L11 | 「对齐后计算」接到频响计算区和批处理配方，默认关闭。帮助、hints、quickref 写明回放页与直接接口的差别，以及整数比限制。普通打开/拖入/最近仍是公共轴 | partial |
| C7 / R01 / 性能 / Cocoa / Windows | 本机没有对应平台和事故样本 | UNKNOWN |

定向命令使用 `TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest`。通过的 owner 包括准备层、Batch 来源集成中的新用例、阶次转速、频响核心、批处理 reporter、帮助版本、Excel 长表，以及 signal/UI/批渲染 import、状态所有权和 lambda 连接护栏。

本机既有红，未算进本轮：hints 里若干旧文案的全角宽度超过 18；`test_wwt_export_storage` 仍要求旧的 WWT 文案；Linux offscreen 解析不到 CJK 字体时，批处理预设列宽用例在取字体处失败。这些断言对应的文案和字体解析本轮没有改。
