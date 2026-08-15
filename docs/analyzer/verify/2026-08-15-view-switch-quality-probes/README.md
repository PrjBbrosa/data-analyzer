# View 切换渲染质量探针（2026-08-15）

服务于 [`specs/2026-08-15-view-switch-quality-settlement-spec.md`](../../specs/2026-08-15-view-switch-quality-settlement-spec.md)
与 [`plans/2026-08-15-view-switch-quality-settlement-plan.md`](../../plans/2026-08-15-view-switch-quality-settlement-plan.md)。
`results/` 里 `after-*` 之外、且不是 `analysis-ink-calibration.*` 的，都是 **改前**
读数：`main@380e5ac2`，macOS Cocoa，dpr 2.0，画布 1600×950（MainWindow 探针为整窗
1600×950），仓库 `.venv`。
`analysis-ink-calibration.*` 是 plan Task 4 的**标定**读数（不是改前基线），
量在 `feat/view-switch-quality-settlement@49302046`、画布 1400×900，详见下表末行。
`after-*` 是 plan Task 7 的**改后**验收读数（`agent/vsqs-task78`，同机同 dpr），
逐项对照见本页末节「改后读数（plan Task 7）」。

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
# plan Task 4 的标定扫描（约 9 分钟，会连开三个窗口）：
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/probe_view_switch_quality.py analysis-calibrate --json-out out.json
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
| （无历史脚本）`analysis-calibrate` | **spec §5 三行 ink 带的真机标定**（plan Task 4，不是改前基线）：谱行 7 档峰底比 / 预览行 2·3·4 条 × Y 默认与拉窄填满 / FRF 3 档 bins × 干净·噪声相位·噪声相干，每档 ≥2 遍取中位、AA 显式开关，输出 ink→ms 散点 + 最小二乘拟合 + 推荐常量 | `analysis-ink-calibration.txt` / `.json` | 同左（本身即定稿读数） |

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

## 分析画布 ink 带标定摘要（plan Task 4，`analysis-ink-calibration.*`）

真机 macOS 27.0 / arm64 / Cocoa / dpr 2.0 / 画布 1400×900，每档 ≥2 遍 × 每遍 3 帧
取中位（同机另有两个 offscreen pytest 进程，loadavg ≈2.0；除预览行 2 条 Y 默认档
22% 外全部 ≤4%）。三遍独立跑出的推荐常量完全一致。

| 组 | 点数 | 定带拟合斜率 | 截距 | R² | 250 ms @ ink | 推荐 ON / OFF |
|---|---|---|---|---|---|---|
| 谱行（3 曲线，只改峰底比） | 7（定带取 ≤600 ms 的 4 点） | 1.68 ms/k·dev-px | 9.0 ms | 0.976 | 143 k | **95 k / 145 k** |
| 时域预览行（2/3/4 条 × Y 默认·拉窄填满） | 6 | 0.93 ms/k·dev-px | −5.9 ms | 0.995 | 275 k | **复用 `_INK_AA_ON/OFF` 200 k / 300 k** |
| FRF 三行（bins × 干净·噪声相位·噪声相干） | 9 | 3.21 ms/k·dev-px | −125 ms | 0.916 | 117 k | **75 k / 115 k** |

三条给实施的告诫（都在原始输出里有对应行）：

- **谱行不是一条直线**：≤600 ms 段 1.68 ms/k，>600 ms 段 3.83 ms/k。带只能在近目标
  段标定，全局拟合会把截距压到 −138 ms，外推无意义。
- **FRF 也不是一条直线**：噪声相位 1.44 ms/k vs 噪声相干 3.55 ms/k（2.47×）。原因在
  per-row ink 拆分里：相干行 y 跨度被 `setYRange(0,1)` 恒钉成 1.0，随机相干每个 bin
  都是满行高笔画，同样 ink 下比幅值行的短笔画贵得多（2049 bins：噪声相干 342 k ink
  里 340 k 来自相干行，1095 ms；噪声相位 143 k ink 主要在幅值行，154 ms）。因此按最
  保守的全局拟合定带。
- **ink 腿必须与点数腿 AND**：FRF「干净」构形 ink 恒为 2.5 k（平滑曲线几乎不产生墨迹）
  而 AA 帧随 bins 从 8.2 涨到 20.7 ms——单独一条 ink 腿看不见点数成本。

## 改后读数（plan Task 7，`after-*`）

同机 macOS 27.0 / arm64 / Cocoa / dpr 2.0，仓库 `.venv`，分支 `agent/vsqs-task78`
（基点 `feat/view-switch-quality-settlement@4191987c`）。逐项判定见
spec §6 下方的「实施注记」表。

### 先读这一条：改后这台机器 loadavg ≈2.2–4.2，改前基线是空闲机

**wall-clock 的绝对值不能跨文件直接比**——`plot_channels`（本批一行没动）在改后
run 里是 22–27 ms，改前基线里是 13–16 ms，同一个函数 1.7×，那是环境不是改动。
所以本批给两条**同机同刻**的对照 lane，用它们做 A/B，不用跨文件减法：

| 对照文件 | 怎么做的 | 结论 |
|---|---|---|
| `after-control-time-mainwindow-legacy-view-mixin.txt` | 只把 `_view_mixin.py` 单文件 `git checkout 380e5ac2 --`（画布仍是新代码，但没人调 `settle_view_restore`，`restore_visible_xlim` 走默认 `flush=True`）→ 跑同一条探针 → 还原 | overlay 回切 ink **904 560 → 4 824**、点 **red → green**；切换调用 44 → 50 ms，即**真实代价 +4~7 ms** |
| `after-control-time-canvas-legacy-order.txt` | `time-canvas --legacy-order`（新增开关，改前调用顺序） | 复现改前基线到 ±1.5 ms（to_first_frame 16.0 vs 基线 17.3），证明画布级探针**不受本机负载影响**；事务 lane 的 +5.3 ms 是真实差值 |

### 时域（产品路径 `time-mainwindow`，同机 A/B）

| 项 | 改前（同机对照 lane） | 改后 | |
|---|---|---|---|
| overlay View 2 回切 ink | 904 560 / 1 010 681 | **4 824 / 5 454**（首访 4 719 / 5 335，+2.2%） | ✅ |
| overlay View 2 回切质量点 | red「波形填满绘图区」 | **green「抗锯齿已完成」** | ✅ |
| overlay View 2 回切 `aa_on` | False（空转到底也不开） | **True** | ✅ |
| overlay 回切绘点 | 1968 | 1968（首访 1864） | ⚠️ 见下 |
| 切换调用（overlay warm） | 43.6–45.8 ms | 49.5–50.2 ms | +4~7 ms |
| `settle_view_restore()` 自身 | — | **0.7–0.9 ms** | |
| 分区来回切（时域↔FFT ×2） | — | 不抛异常 | ✅ |

⚠️ **绘点 1968 vs 首访 1864 是改前就有的，不是本批引入**（对照 lane 也是 1968）。
成因：`_current_pixel_width()` 读 `vb.sceneBoundingRect().width()`，而 pyqtgraph 的
左轴宽度要**画过一帧**才定得下来（刻度标签宽度只有 `AxisItem` 绘制时才知道），所以
全量重建后的第一次结算拿到的是布局前的 979 px，真值是 877/931 px。979/931 = 1.052，
1968/1864 = 1.056——对得上。实验记录：`ci.layout.activate()` 强制同步布局**无效**
（仍是 979），因为这不是「布局没跑」而是「轴宽度还没被渲染决定」。
后果只有多约 5% 的分桶（更细，不丢特征、不改判定），故不修。

### 「首帧即 AA」按路径分（`time-mainwindow` 的 `paints_first_turn` 列）

paint 级证据：探针在 `_glw` 上再叠一层 `paintEvent` 记录每次 paint 当时的 `aa_on`。

| 路径 | 改前 | 改后 | |
|---|---|---|---|
| `subplot-object-reuse`（全显 / 含隐藏通道） | 首帧非 AA → 150 ms → AA | **第 2 次起 `aa@切换返回=True`、首帧就是 AA**（`[True, True]`） | ✅ |
| `plot-mode-changed` 的 subplot 侧 | 同上 | **首帧即 AA**（`[True, True]`） | ✅ |
| `new-channel` / `plot-mode-changed` 的 overlay 侧（全量重建） | AA 根本不开（`[False, False]`，红点） | AA 在**同一轮事件循环**的第 3 个 paint 落地（`[False, False, True]`，≈6 ms） | ⚠️ 非首帧 |

⚠️ 的机制与上面同一条：memo 键含 `_view_signature()`，而签名含像素宽；
`settle_view_restore()` 跑在第一帧之前，此时宽度还是 979，AA 帧却是在宽度已定
（877/931）之后被计时的——**写入键与查询键必然不同，memo 在全量重建路径上永远不命中**。
这不是可以靠调用顺序修的：轴宽度要渲染才知道。spec §7 第一条已把这种情况列为
「两种都正确」，且改后仍比改前好一个数量级（6 ms vs 150 ms 且改前压根不开 AA）。
真要拿到全量重建的首帧 AA，得让 memo 键不含像素宽或改成两段式结算，属另开一批。

### `stale-ink`（同一次运行里并排两 lane）

| lane | 回切后绘点 | 回切后 ink | AA 判定 | 点 |
|---|---|---|---|---|
| 旧顺序（`--lane legacy`） | 1404 / 1376 | 2 662 227 / 2 715 569 | False | red |
| 事务顺序（`--lane transaction`） | **3124 / 3124**（= 首访） | **36 659 / 44 400**（= 首访，0.0%） | True | **green** |

首访是 3124 / 36 659。事务 lane 三个后果同时消失，且空转 500 ms 后仍是 green。

### `time-canvas`（两个后端，事务 lane vs `--legacy-order` 同机对照）

| | 改前顺序（同机） | 事务顺序 | |
|---|---|---|---|
| 向量AA to_first_frame | 16.0 ms | 21.3 ms | +5.3 ms |
| 向量AA to_settled | 36.5 ms | 62.0 ms | 见下 |
| 向量AA 稳定段路径 | `[dense-raster]` **6/6 轮全部误收编** | **`[green]`**，`raster_entries=0` | ✅ |
| 向量AA 首帧即 AA | 0/4 | 2/4（第 2 轮起） | ✅ |
| 光栅 to_first_frame | 47.6 ms | 48.8 ms | 持平 |
| 光栅 to_settled | 91.5 ms | 100.6 ms | 持平 |
| 光栅 `restore_xlim` | 31.6 ms | 0.3 ms（flush 挪进 settle 的 27.0 ms） | 同一笔钱换了位置 |

to_settled 变大是**度量口径变了不是变慢**：探针每轮强制 3–4 次 repaint，改前那几帧
是廉价的光栅 blit（8.2–8.7 ms），改后是真正的向量 AA 帧（smoothA 26 ms）。产品一次
切换只画一帧。`to_first_frame` 才是用户感知的那个数，+5.3 ms 正是 spec §1.2 预测的
「真正把 AA 画出来的钱」。

### 分析画布（`analysis-frames` / `spectrum-switch`）

「产品判定」= `plot_spectra` / `set_result` 后处理 ≥200 ms 事件再读 `quality_status()`，
即用户看到的红/绿点；「显式 AA 帧」= 先 `disable_interactive_quality()` 解除 backstop
武装、停两个计时器，再手动 `_set_curve_aa(True)` 量的「若开 AA 这一帧多少钱」
（**不解除武装的话，>1000 ms 的帧会跳闸并异步关 AA，把大 ink 档读成 AA-off 的帧**）。

| 谱行（3 曲线，绘点恒 4095） | ink | 改前 AA 帧 | 改后显式 AA 帧 | 产品判定 |
|---|---|---|---|---|
| 纯噪声底 | 617.4k | 1652 ms | 1556.9 | **red / high-ink** ✅ |
| 峰/底=10 | 212.3k | 336 | 322.3 | **red / high-ink** ✅（>OFF 145k） |
| 峰/底=40 | 66.8k | 136 | 133.8 | **green** ✅（<ON 95k） |
| 峰/底=200 | 19.8k | 71 | **68.6** | **green** ✅（≤100 ms 目标） |
| 纯噪声底 · 1 条 | 239.5k | 728 | 664.0 | red / high-ink ✅ |
| 纯噪声底 · 6 条 | 1126.9k | 26（点数拒） | 2676.2 | red / **high-ink** ✅（ink 腿在点数腿之前判） |

| FRF | 改前 | 改后 `set_result` | 改后显式 AA 帧 | 产品判定 |
|---|---|---|---|---|
| 2k bins 干净 | 14 ms AA 帧 | **4.6 ms** | 17.6 | **green** ✅ |
| 2k bins 噪声相位/相干 | **527 ms 同步在调用里** | **1.7 ms** | 509.1 | **red / high-ink** ✅（连那一帧都不付） |
| 8k bins 噪声 | 2540 | 3.3 ms | 2458.6 | red / high-ink ✅ |
| 32k bins 噪声 | 11403 / 非AA 4111 | 8.5 ms | 10909.2 / 非AA 3888.8 | red / high-ink ✅ |

`plot_spectra` 切换调用（`spectrum-switch`）：**中位 21.3 ms**（改前同步开 AA 245 ms），
且 `_apply_idle_curve_aa` 在调用里被调用 **0 次**；`_aa_on=True` 与 `_aa_on=False`
两档收敛（21.3 / 28.5 ms），因为 `plot_spectra` 现在一律以 AA-off 建曲线。
其中 View A（3 曲线 × 65536 bins 噪声）产品判定为 **red / aa-backstop**——实测 EMA
264.9 ms > 250 ms 跳闸拉黑，之后的回切首帧只要 8.5 ms：这就是 spec §6「backstop
一帧内拉黑」那条的实物。

### 标定复跑（`after-analysis-calibrate.*`）

三组全扫（谱行 7 档 / 预览行 6 档 / FRF 9 档，每档 2 遍取中位，spread 多数 0–2%）
推荐常量与 spec §5 定稿**逐字一致**，代码里的常量无需改动：

| 组 | 定带拟合斜率 | 250 ms @ ink | 推荐 ON / OFF | 代码现值 |
|---|---|---|---|---|
| 谱行 | 2.631 ms/k（全部点，R²=0.976） | 147.4k | **95k / 145k** | `_SPECTRUM_INK_AA_ON/OFF` = 95k/145k ✅ |
| 预览行 | 0.923 ms/k（R²=0.995），对时域隐含斜率 1.11× | 274.8k | **复用 `_INK_AA_ON/OFF`** | 复用 ✅ |
| FRF 三行 | 3.256 ms/k（全部点，R²=0.916） | 115.8k | **75k / 115k** | `_FRF_INK_AA_ON/OFF` = 75k/115k ✅ |

单档帧读数与 `analysis-ink-calibration.txt` 相差 1–2%（如谱行 617k：1555.8 vs 1539 ms）。
两条「不是一条直线」的告诫照旧成立（谱行 >600 ms 段 3.375 ms/k；FRF 噪声相干 3.614
vs 噪声相位 1.460，2.48×）。

### 既有门禁（`after-gates.txt` / `after-aa-ink-budget-smooth.txt`）

`benchmark_timedomain_interaction.py --assert-standards` **通过**（门禁未改）：

| 指标 | 实测 | 上限 |
|---|---|---|
| initial_plot | 135.1 ms | 1300 |
| pan_frame_p95 | 18.9 | 120 |
| pan_settle | 22.2 | 150 |
| resize_frame_p95 | 28.5 | 300 |
| resize_settle | 21.4 | 250 |
| warm_checkbox_callback_p95 | 2.3 | 30 |
| warm_checkbox_paint_p95 | 18.6 | 220 |

`probe_aa_ink_budget.py aa-frame --cases smooth`：`aa_gate=allow aa_on=True`，
首帧 239.1 ms / 稳态 236.8 ms，与 2026-08-08 spec 的「平滑对照稳态 240」同量级
——**零回归**。

### 探针本身的改动（Task 7 顺带）

- `stale-ink` 现在**一次跑两 lane**（`--lane both|legacy|transaction`）：改前顺序
  与 `restore_visible_xlim(flush=False)` → `restore_visible_ylims` →
  `settle_view_restore()` 并排，缺陷与修复在同一份输出里。
- `time-canvas` 默认改走**产品当前的事务顺序**（并把每个 fixture 首轮的 ylim 存下来，
  后续轮当「回到访问过的 View」恢复），`--legacy-order` 保留改前顺序做同机对照；
  新增 `settle_ms` / `aa_before_first_frame` 两列。
- `time-mainwindow` 新增：每 View 的**首访基线**快照、每条可见线的**绘点**、
  `settle_view_restore` 计时、paint 级 `aa_on` 记录（`_install_paint_recorder`）、
  时域↔FFT 分区来回切的路径检查。
- `analysis-frames` / `analysis-calibrate` 的「显式 AA 帧」一律先
  `disable_interactive_quality()` 再手动开 AA（理由见上），并新增**产品判定**列；
  `analysis-frames` 的取帧改走 `_timed_repaint`（带重试），修掉 32k 档非 AA 帧被
  漏画成 0.0 ms 的问题。
- 所有子命令的 `environment` 里都记 `loadavg`。
