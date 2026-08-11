# WinWert open-trial candidates

## 机制（2026-08-11 解出并实证）

WinWert 打开真实骨架的 in-place 改写文件；clean-room 从零写被拒（探针 D）。
「横坐标是什么」由**尾块曲线记录**决定：
基址 = 尾块 + 171 + 曲线号×283，**+18 的 u16 是 X 引用曲线号，0 = 时间**。
记录头的 `xkanalnr` 显示不读（探针 B/E1），尾块 +69 只是全局 X（探针 C）。
完整字段表见 `docs/analyzer/specs/2026-08-11-wwt-export-dual-compat-spec.md`。

**产品路径**：`mf4_analyzer.io.wwt_inplace.convert_to_wwt` + 捆绑模板
`assets/wwt/winwert_export_template.wwt`，默认 `time_axis=True`
（逐曲线 X→0、X 轴标签/量程写时间、未写入曲线取消勾选、量化槽位按数据
量程重新标定）。

## 探针（`emit_wwt_timeaxis_probes.py` 产出）

v2 回执：F/G/H 三个**时域显示都成立**（0–40 s 横轴、各自 Y 轴、±450° 角度
完整），唯一残留是**首帧**数据挤在左侧、刷新后正常 —— 曲线记录 +52 的绘图
比例没跟着轴范围改。v3 已补上（K = 跨度 × 比例 守恒）。

| 文件 | 改了什么 | 判读 |
| --- | --- | --- |
| `probe_time_F_product_convert.wwt` | 产品路径全量（DC2E 数据 → 模板） | **主验收**：打开即 X = 时间 0–43 s，只有 3 条导出曲线，**首帧不用刷新** |
| `probe_time_G_dc2e_curve_x0.wwt` | 原件只把曲线 +18 清 0 | 最小机制证明（不含 +52，首帧仍需刷新，属预期） |
| `probe_time_H_dc2e_full_display.wwt` | 原件 + 完整显示改写（数据不动） | 时域 + 0–43 s + 首帧即正确 |

## 历史台账

一轮 A/B/C/D 与二轮 E1 的回执见 spec 的探针台账表；E1 的曲线设置对话框
截图是解出 X 字段的关键证据。`candidate_*` 是更早的 in-place / graft 试验，
保留作回归证据。
