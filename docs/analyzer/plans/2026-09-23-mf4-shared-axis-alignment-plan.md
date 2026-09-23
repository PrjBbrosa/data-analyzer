# MF4 共享时间轴对齐

日期：2026-09-23
状态：按本计划实现。
样本：`C:\Users\hang\Downloads\test1.mf4`（CANape，MDF 4.10）。不把该文件入库。

## 1. 根因

缺通道与数值类型无关。`int16`、`float32`、`float64` 走同一条门。

`DataLoader.load_mf4` 把最长的一条序列当成公共 `Time`，其余通道只在两种情况下留下：

- 点数正好等于最长序列：按下标拷贝，不看各自的时间戳是否同一条钟。
- 点数不同，且 `np.all(np.diff(t) > 0)`：线性插值到公共时间轴。

其它情况被空的 `except: pass` 丢掉，不进 `skipped_channels`，界面上也没有「未导入」提示。

`test1.mf4` 的第 3 组是 1 ms 同步的 5 个 ECU 信号（`float32` / `int16`，各 181299 点）。时间轴上有两处完全相同的时间戳（96.996 s、162.531 s），`diff > 0` 失败，整组被丢掉。界面只剩公共时间轴和同长度的 `Msteer`，再加上时间主通道被显示成 `t [2:0]`。CANape 仍列出这 5 个信号，以及 0 点的配置通道 `Comment`、`DifferenceOf2Signals`。

因此下面几类都会显示不全或显示错，不限 dtype：

| 情况 | 现在的结果 |
| --- | --- |
| 重复时间戳、时间回退、非有限时间 | 整条数值通道丢掉 |
| 点数相同但时间轴不同 | 按下标贴到别人的时间上 |
| 字符串、字节、多维数组、0 点通道 | 丢掉且不提示 |
| 时间主通道（`channel_type` 为 time master） | 当成一条普通曲线，名字还可能变成 `t [g:i]` |

字符串和原始字节不是时域曲线，不编造成数值。它们要出现在未导入名单里。时间主通道是横轴，不作为信号列。

## 2. 行为

对每条数值通道：

1. 丢掉非有限时间戳，保留对应的采样（采样本身可以是 NaN）。
2. 时间回退时按时间稳定排序。
3. 同一时间戳保留最后一点，使时间轴严格递增。
4. 点数与时间戳长度不一致时不截断，记为 `length-mismatch`。
5. 整理后仍不足 2 点、且公共轴更长：不把单点铺满整条记录，记为 `single-sample`。整份文件只有单点时，保留这一行。
6. 公共轴取整理后最长的数值通道。只有时间戳与公共轴完全一致才直接拷贝，否则 `np.interp`。轴外仍沿用端点保持，与原先严格递增通道的插值一致。
7. 空通道、非数值、非一维、读失败写入 `skipped_channels`（`empty` / `non-numeric` / `non-1d` / `unreadable` / `unusable-time`）。时间主通道不进信号列，也不进这份名单。

返回值仍是 `(DataFrame, channels, units)`。诊断放在 `DataFrame.attrs["source_metadata"]`，供打开文件时的未导入提示和批处理来源元数据使用。不改 TDMS / BLF 的对齐合同。

## 3. 改动与门禁

- `mf4_analyzer/io/loader.py`：对齐与跳过名单。
- `mf4_analyzer/io/source_adapters.py`：三元组结果从 `attrs` 取 `source_metadata`。
- `mf4_analyzer/ui/main_window/_project_io_mixin.py`：MF4/MDF 走现有的未导入提示。
- `tests/test_mf4_loader.py`：重复时间戳、时间回退、同点数不同时钟、非数值跳过。不依赖 `Downloads\test1.mf4`。

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_mf4_loader.py -q
```

Windows 上用 `.venv\Scripts\python.exe`。不跑全量。
