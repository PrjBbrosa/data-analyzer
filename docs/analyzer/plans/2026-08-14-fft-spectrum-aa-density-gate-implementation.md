# FFT 频谱抗锯齿密度门槛实施计划

**状态：** 已授权执行
**范围：** `PgLineCanvas` 的上方 FFT 幅值频谱行；不改 FFT 数值计算、缓存内容或下方时域预览的既有共享阈值。

## 1. 问题与证据

用户在 `260417-ripple-PK2C-电机加热-1.hdf` 中同时计算 `MOTOR Y` 与
`MOTOR X` 后，报告频谱 section 切换和拖动卡顿。两条原始通道各
1,188,000 点，FFT 各约 594,000 bin。

当前不是“把 59.4 万 bin 原样画出”：
`PgLineCanvas._spectrum_plot_arrays()` 已按图面像素宽度做 min/max 包络，
该量级在 1,200px 画布中各约 2,274–2,296 点。但上方频谱曲线在创建时
强制 `antialias=True`，并且空闲期无条件把上方曲线重新设为 AA-on；只有
下方时域预览有按绘制点数的 5k/7k 滞回门槛。

同量级离屏诊断的单帧 `grab_pixmap`：上下 AA-on 为 4,166ms；仅上方 AA-off
为 948ms；仅下方 AA-off 为 3,225ms；上下 AA-off 为 28ms。它说明主因是
上方频谱的 native AA 光栅，而不是 FFT 再计算或包络本身；不是 macOS 前台
验收数据。

## 2. 实施目标

在不丢失频率包络峰值、不中断缓存复用的前提下，让高密度多曲线频谱在静止
后也保持 native AA-off。拖动/缩放继续沿用当前立即关 AA、150ms 空闲后再判定
的策略。

## 3. 最小改动设计

### 3.1 单独的频谱密度门槛

在 `mf4_analyzer/ui/pg_canvas/line_canvas.py` 为 `_amp_curves` 增加独立、
基于**所有已绘制频谱曲线点数总和**的滞回状态：

| 状态 | 条件 |
|---|---|
| 初建判断 | `sum <= 3,000` 才允许 AA |
| 已拒绝后的恢复 | `sum <= 2,000` 才恢复 AA |
| 已允许后的拒绝 | `sum > 3,000` 时关闭 AA |

两条约 2,300 点的截图级曲线合计约 4,600，稳定地留在 AA-off；两条各约
1,000 点的轻量覆盖仍保持 AA-on。阈值仅对应频谱行，不替换时域预览从
`canvas.py` 导入的 5,000/7,000 共享门槛。

### 3.2 建图与交互

`plot_spectra()` 新建曲线时先以 AA-off 创建，曲线集合完整后再通过同一个
idle 质量函数作最终判定，避免生成密集覆盖时先付一次昂贵 AA 画帧。每次新
频谱曲线集合重置频谱滞回种子；选择变化但保留旧频谱时不重置，以保持稳定。

`disable_interactive_quality()` 仍关闭上/下两行的 AA；`_enable_idle_quality()`
仍在鼠标松开后的 150ms 才恢复，但恢复时须分别调用频谱门槛和既有预览门槛。

### 3.3 质量提示

当画布空闲、频谱 AA 被密度门槛拒绝时，质量点维持 red，但 tooltip 必须说明
“频谱叠加密度 X > 3000”，不要把受控性能策略误报为未知错误。轻量曲线和
普通交互中的 red/yellow/green 时序保持原有语义。

## 4. 回归测试

在 `tests/ui/test_pg_line_canvas.py`：

1. 更新“频谱永远 AA-on”的陈旧断言：轻量双曲线仍 green/AA-on。
2. 新增高密度双频谱覆盖：通过真实 `plot_spectra()` 验证两条已包络大曲线
   的上排稳定 AA-off、下方预览既有策略不被此改动重写、质量 tooltip 给出
   频谱密度原因。
3. 覆盖滞回：高密度拒绝后，中间区保持拒绝，只有降至 ON 门槛才恢复。
4. 保留拖动和 Ctrl+滚轮测试，确保交互中全部曲线立即 AA-off。

继续运行已有的大频谱包络测试，确认 raw `_entries` 不被改写且曲线仍显著
小于原始 bin 数；继续运行 section away/back 测试，确认缓存 FFT 不重算、
也不重建已保留曲线。

## 5. 明确非目标

- 不改 `signal/fft.py`、NFFT、平均方式、幅值归一化、缓存键或原始数组。
- 不改下方时域预览 5k/7k 共享门槛；它需独立的 real-Cocoa 标定。
- 不引入 QPixmap 平滑缓存、OpenGL 后端或全局 pyqtgraph 自动 downsample。
- 不合并现有 UltraView 未提交文件。

## 6. 验收与提交

必须通过：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \\
  .venv/bin/python -m pytest -q \\
  tests/ui/test_pg_line_canvas.py \\
  tests/ui/test_fft_audio_compute_safety.py \\
  tests/ui/test_analysis_multiview_integration.py \\
  -k 'fft_section_switch_away_and_back_preserves_spectrum or not test_fft_section_switch_away_and_back_preserves_spectrum'
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \\
  .venv/bin/python -m pytest -q tests/ui/test_import_boundaries.py
git diff --check
```

实际执行时可拆开前两个 pytest 命令以避免 `-k` 意外过滤其他文件。最终只暂存：
本计划、`line_canvas.py` 和该变更确实需要的 focused tests。前台 macOS 手势
流畅性仍需另行确认，不能由 offscreen 成功替代。
