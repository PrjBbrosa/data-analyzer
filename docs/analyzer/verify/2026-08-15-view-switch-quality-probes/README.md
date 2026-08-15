# View 切换渲染质量探针（2026-08-15）

服务于 [`specs/2026-08-15-view-switch-quality-settlement-spec.md`](../../specs/2026-08-15-view-switch-quality-settlement-spec.md)
与 [`plans/2026-08-15-view-switch-quality-settlement-plan.md`](../../plans/2026-08-15-view-switch-quality-settlement-plan.md)。
所有 `results/` 均为 **改前** 读数：`main@380e5ac2`，macOS Cocoa，dpr 2.0，
画布 1600×950（MainWindow 探针为整窗 1600×950），仓库 `.venv`。

> **正式入口已迁到 `scripts/probe_view_switch_quality.py`**（plan Task 0）。
> 本目录 `probes/` 下六个脚本是 2026-08-15 当时的调查快照，**不再维护**——
> 六个子命令（`time-mainwindow` / `time-canvas` / `ylim-order` / `stale-ink` /
> `analysis-frames` / `spectrum-switch`）1:1 对应下表六行，合成信号/画布尺寸/
> 输出列照抄未变，统一加了 `--json-out`。改探针请改 `scripts/` 版本，
> 别再碰 `probes/`。2026-08-15 用新脚本逐个子命令真机复核过一遍，读数与本页
> 「改前读数摘要」同量级（多数项目 <5% 偏差），复核输出存在
> `results/rerun-from-scripts-<子命令>.txt`。

**全部真机跑**（不要设 `QT_QPA_PLATFORM=offscreen`）：探针量的是 paint
成本与真实事件循环时序，offscreen 数字无效（CLAUDE.md Gotchas「验真机渲染」）。
唯一例外 `stale-ink` 子命令（原 `probe_stale_ink_effects.py`）是逻辑缺陷复现，
offscreen 也能复现，但本目录基线同样取自真机。

```bash
cd "<repo>"
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/probe_view_switch_quality.py time-mainwindow --json-out out.json
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/probe_view_switch_quality.py time-canvas --json-out out.json
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/probe_view_switch_quality.py ylim-order --n-channels 8 --json-out out.json
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/probe_view_switch_quality.py stale-ink --json-out out.json
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/probe_view_switch_quality.py analysis-frames --json-out out.json
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/probe_view_switch_quality.py spectrum-switch --json-out out.json
```

历史命令（`probes/` 下六个脚本，仍能跑，但不再随代码改动更新）：

```bash
cd "<repo>" && V=docs/analyzer/verify/2026-08-15-view-switch-quality-probes
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python $V/probes/probe_mainwindow_view_switch.py out.json
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python $V/probes/probe_view_switch_aa.py out.json
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python $V/probes/probe_view_switch_ylim_order.py 8
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python $V/probes/probe_stale_ink_effects.py
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python $V/probes/probe_analysis_aa_frames.py
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python $V/probes/probe_fft_view_switch.py
```

| 探针（历史脚本 → 现子命令） | 量什么 | 改前结果文件 | 复核结果文件 |
|---|---|---|---|
| `probe_mainwindow_view_switch.py` → `time-mainwindow` | **产品路径**：`_register_file_data` 装 8ch×1M 点，建两个 View 来回 `_switch_view`；四种布局（subplot 全显 / subplot 含隐藏 / overlay / 两 View 布局不同）。每次切换打点 `_build_time_plot_data` / `try_apply_selection_delta` / `plot_channels` / `restore_visible_xlim|ylims` / `apply_controls_from_state`，并读画布走的路径（对象复用 vs 全量重建）、每条线记录到的 ink、稳定后 AA 判定、质量点 | `mainwindow-view-switch.txt` / `.json` | `rerun-from-scripts-time-mainwindow.txt` |
| `probe_view_switch_aa.py` → `time-canvas` | 画布级：按产品顺序 `plot_channels(defer)` → `restore_visible_xlim` → 首帧 → 光栅 flush → `try_enable_idle_quality` → AA 首帧/稳态，两类信号（低 ink 平滑 / 满幅振荡）各切 3 轮 | `canvas-view-switch-two-backends.txt` / `.json` | `rerun-from-scripts-time-canvas.txt` |
| `probe_view_switch_ylim_order.py` → `ylim-order` | A/B：产品顺序（先 X 后 Y）vs 先 Y 后 flush，8ch×1M；看记录到的 ink、AA 是否开、光栅收编数、合计耗时 | `ylim-order-ab-8ch.txt` | `rerun-from-scripts-ylim-order.txt` |
| `probe_stale_ink_effects.py` → `stale-ink` | 回切后 stale ink 的三个后果：envelope 分桶被砍、AA 拒、光栅误收编，且空转 500 ms 不自愈 | `stale-ink-effects.txt` | `rerun-from-scripts-stale-ink.txt` |
| `probe_analysis_aa_frames.py` → `analysis-frames` | 分析画布：`PgLineCanvas` 谱行同 4095 绘点只改竖直墨迹的 AA 帧 vs `envelope_ink_dev_px`；`PgFrfCanvas` 各 bins 数 AA/非 AA 帧 | `analysis-aa-frames.txt` | `rerun-from-scripts-analysis-frames.txt` |
| `probe_fft_view_switch.py` → `spectrum-switch` | `PgLineCanvas.plot_spectra` 切换调用耗时（AA 同步开 vs 不开） | （见 spec §1.4 表，未单独存文件） | `rerun-from-scripts-spectrum-switch.txt` |

## 改前读数摘要（详见各结果文件）

### 时域（产品路径，warm 中位）
| 场景 | 路径 | 切换调用 | 备注 |
|---|---|---|---|
| subplot ↔ subplot（全显） | `subplot-object-reuse` | 13–14 ms | 首次 72 ms（追加行 31 ms） |
| subplot ↔ subplot（含隐藏通道） | `subplot-object-reuse` | 13 ms | |
| overlay ↔ overlay | `new-channel` 全量重建 | 26–29 ms | plot_channels 13–16 ms |
| subplot ↔ overlay | `plot-mode-changed` 全量重建 | 27–33 ms | |
| 切走前在 View 里拨过（UltraView 离场抓图） | — | +8–11 ms | `grab_pixmap` 5–7 ms |

AA 判定调用本身 0.1 ms，ink 现场测量 0.0 ms（表内已有记录）——**AA 决策不是成本**。

### 缺陷 A：全量重建的回切在 Y 恢复前测 ink
| 场景 | 记录到的 ink | 真值 | 放大 | 后果 |
|---|---|---|---|---|
| overlay 2ch，窗口 10%（产品路径） | 904 560 / 1 010 681 | ≈4 k | ~215× | AA 拒、红点「波形填满绘图区」 |
| subplot 8ch，全量重建（A/B 探针） | 75 412… | 1 131… | ~67× | AA 拒 |
| overlay 2ch，窗口 30%（stale-ink 探针） | 2 662 227 | 35 994 | ~74× | **绘点 3124→1404**（分桶被砍）、AA 拒 |
| 3ch 平滑 1M 点（画布级探针） | 461 481… | ≈3 k | ~136× | 误收进光栅路径（`[dense-raster]`），每次切换白建光栅 |

空转 500 ms 不自愈；用户拨一下画布才恢复。

### 分析画布
| 画布 / 构形 | 绘点 | 现闸门 | ink | AA 帧 |
|---|---|---|---|---|
| 谱行 3 曲线 纯噪声底 | 4095 | 放行 | 617 k | **1 652 ms** |
| 谱行 3 曲线 峰/底=10 | 4095 | 放行 | 212 k | 336 ms |
| 谱行 3 曲线 峰/底=40 | 4095 | 放行 | 67 k | 136 ms |
| 谱行 3 曲线 峰/底=200 | 4095 | 放行 | 20 k | 71 ms |
| 谱行 1 曲线 纯噪声底 | 1365 | 放行 | 240 k | 728 ms |
| 谱行 6 曲线 纯噪声底 | 8364 | 点数拒 | 1 127 k | 26 ms（AA 关） |
| 同图 AA 关（对照） | 4095 | — | — | 15 ms |
| FRF 2k bins 干净 | — | 无闸门 | — | 14 ms |
| FRF 2k bins 噪声相位/相干 | — | 无闸门 | — | 527 ms |
| FRF 8k bins 噪声 | — | 无闸门 | — | 2 540 ms（非 AA 442） |
| FRF 32k bins 噪声 | — | 无闸门 | — | 11 403 ms（非 AA 4 111） |

`plot_spectra` 切换调用：AA 同步开 → 合计 245 ms（其中首帧 227）；不开 → 25 ms。

改动落地后再跑一遍，预期变化写在 plan §「真机验收」。
