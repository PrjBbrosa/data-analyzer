# TraceLab 选中背景滑动推广验证报告

日期：2026-09-10 · Spec / Plan：`docs/analyzer/specs|plans/2026-09-10-selection-slide-rollout-*`。

交付：**partial**。G1/G2/G5 与 Cocoa 样本齐；G4 Windows 100%/150% 无可用解释器，判 UNVERIFIED。原生录屏权限失败，截图不能代替录屏。未改 400/300 ms token、DSP 或 owner 行为。

冻结包：`NOT_IN_SCOPE`。

## 环境

| 项 | 值 |
| --- | --- |
| HEAD | `a1c4ab74f92031d234d610689df68ec820a42c4d`（与 Spec / T0 一致） |
| Cocoa 运行前后 source fingerprint | 一致（未在运行中改源） |
| OS | macOS 27.0 arm64 |
| Qt / PyQt / pyqtgraph | 5.15.14 / 5.15.11 / 0.14.0 |
| Cocoa 平台插件 | `cocoa`（未设 `QT_QPA_PLATFORM=offscreen`） |
| DPR / 刷新率 | 2.0 / 60 Hz |
| QSettings | 临时 INI：`.state/selection-slide-rollout/cocoa/probe-selection-slide-*/qsettings.ini` |
| 原始 JSON / PNG | `.state/selection-slide-rollout/cocoa/`（97 张 PNG；`selection-slide.json`；`records.json`） |

Dirty scope（本 rollout + T0 已声明的在途文件，未提交）：

- 本任务：`scripts/probe_selection_slide.py`、`tests/ui/test_selection_slide_probe.py`、本报告、`.state/selection-slide-rollout/`
- T1–T5 产品与测试（toolbar / method_buttons / SegmentedChoice / cards / inspector bind / motion / selection_indicator）
- 与本计划无关、未回滚：`ui/compute_progress.py`、`ui/widgets/channel_config_bar.py`、`ui_kit/widgets/searchable_combo.py`、`tests/ui/test_compute_progress.py`、lessons INDEX、`progress-label-implicit-indent-clips-ink.md`、`ssh-keygen`、HTML 原型

## 门禁总表

| Gate | 结论 | 证据 |
| --- | --- | --- |
| G0 | **PASS** | Spec/Plan 范围与路径已自检；T6 文件 `git diff --check` 干净 |
| G1 | **PASS** | T1–T5 owner 测试已独立通过（协调者记录 228，含 import/state/lambda/qsettings/qss）。T5 仍有 2 条预存 construction 红，见下。T6 logic-only：`tests/ui/test_selection_slide_probe.py` **12 passed** / 11.61s |
| G2 | **PASS** | 真机暴露窗口上 production QSS 的 host/plate/button/disabled grab；geometry、radius 5/6、DPR 2.0。不是 offscreen 属性断言 |
| G3 | **PASS**（样本与合同）+ 间隔门槛未全部达到 | 8 个代表场景 × Off/Light，窗口 `isExposed()`，每场景预热 5 + 暖样本 40 + 首次单独记录 + 程序恢复对照；静止 500 ms 自发更新 0。原生录屏 UNVERIFIED（ffmpeg avfoundation `Input/output error`，无屏幕录制权限）。paint interval p95 见性能表，**未改 token** |
| G4 | **UNVERIFIED** | 本机 `sys.platform=darwin`，无 Windows 项目 Python。不以 Cocoa 或 offscreen 替代 |
| G5 | **PASS** | `test_import_boundaries.py` `test_main_window_state_ownership.py` `test_no_lambda_signal_connections.py` `test_qsettings_isolation.py` `test_qss_border_shorthand.py`：**26 passed** / 4.97s。未跑 `pg_canvas` / 全量 / `acquisition_ui` |
| G6 | **PASS** | 本报告按 P1 ID 与 G0–G6 逐项给出，不以单一测试总数代替验收 |

预存、非本 rollout（T0 已记，T5 复现）：

1. `tests/ui/test_chart_card_construction.py::test_toolbar_chrome_and_action_widgets` — spacing 1 vs 8
2. `tests/ui/test_chart_card_construction.py::test_card_layout_order_is_toolbar_canvas_hintbar` — 首子为 `ToolbarScrollHost`

## 逐个 P1 ID

代表原生场景（Spec §5.2）：N1 空数据/缓存 FFT、N2、B1 相位+预设、B5 每项单独禁用布局、C1 有数据布局+游标、C2 分屏焦点。B2/B3/B4/B6 仅 G1 owner 覆盖，未进 40 次样本集。

| ID | 实现 | G1 | G2 | G3 | G4 | G5 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| N1 | Toolbar 五模式，400 ms | PASS | PASS | PASS | UNVERIFIED | PASS | 空数据独立 Toolbar；缓存路径走 MainWindow 真实按钮，**不是** `_set_mode`。Light 空数据 animation_end p95 **399.9 ms** |
| N2 | MethodButtonGroup，400 ms | PASS | PASS | PASS | UNVERIFIED | PASS | 鼠标点击与 Left/Right。Light animation_end p95 **400.0 ms**。Off 无 plate 时 feedback paint 为 null+`no_paint`，未填 0 |
| B1 | FRF SegmentedChoice 300 ms | PASS | PASS | PASS | UNVERIFIED | PASS | 相位按钮点击有动画；预设槽 1（稳健）点击 snap。相位 Light animation_end p95 **303.9 ms** |
| B2 | FFT Linear/dB、None/A | PASS | UNVERIFIED | UNVERIFIED | UNVERIFIED | PASS | 不在 §5.2 代表样本；T4 owner |
| B3 | 时频/阶次/共用幅值单位 | PASS | UNVERIFIED | UNVERIFIED | UNVERIFIED | PASS | 同上 |
| B4 | 时域横轴 `choice_xaxis` | PASS | UNVERIFIED | UNVERIFIED | UNVERIFIED | PASS | 同上 |
| B5 | `_BINARY_CHOICE_FIELDS`；每项单独禁用布局 | PASS | PASS | PASS | UNVERIFIED | PASS | 点击「每项单独」后 `layout_enabled=False`、driver 不活动、animation_end null+`not_applicable` |
| B6 | 共有/切片/统计区间 | PASS | UNVERIFIED | UNVERIFIED | UNVERIFIED | PASS | 不在代表样本；T4 owner |
| C1 | 时域分屏/叠加 + 游标三选 | PASS | PASS | PASS | UNVERIFIED | PASS | 合成 2×10k 点数据。Light 布局 animation_end p95 **304.0 ms**。程序 `set_plot_mode` / `set_cursor_mode` snap |
| C2 | 频率游标分屏焦点 | PASS | PASS | PASS | UNVERIFIED | PASS | 源卡点击：`source_cursor_mode_changed=0`，目标 canvas `dual`，源 canvas 仍 `off`；两侧 driver 不活动 |

## Cocoa 轻场景门槛（设计目标，未改 token）

阈值：首次反馈 paint p95 ≤50 ms；局部 paint 工作 p95 ≤4 ms；相对 Off 的输入回调 p95 增量 ≤2 ms；60 Hz 下 paint 间隔 p95 ≤20 ms。数值来自暖样本 40，首次访问单独存放。

| 场景 | 策略 | feedback p95 (ms) | paint work p95 (ms) | 回调相对 Off Δp95 (ms) | interval p95 (ms) | animation_end p95 (ms) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| N1-empty | Light | 0.10 | 0.026 | +0.45 | **15.95** | 399.9 |
| N1-cached | Light | 0.15 | 0.025 | −3.40 | **25.20** | **956.7** |
| N2 | Light | 0.24 | 0.029 | +0.46 | **31.96** | 400.0 |
| B1-phase | Light | 0.19 | 0.023 | +0.62 | **31.98** | 303.9 |
| B1-preset | Light | 0.32 | 0.029 | +0.73 | **31.98** | 305.1 |
| B5 | Light | 1.12 | 0.015 | +0.02 | n/a（无动画） | n/a |
| C1 | Light | 0.66 | 0.037 | +0.50 | **31.98** | 304.0 |
| C2 | Light | 0.24 | 0.017 | +0.17 | n/a（焦点目标 snap） | n/a |

观察（记录，不授权改 token / DSP / AA / settle）：

- 反馈 paint 与局部 paint 工作远低于 50 / 4 ms。输入回调增量均 ≤2 ms。
- 紧凑控件 Light 的 interval **典型约 16 ms**（单帧 60 Hz），p95 落到 **~32 ms**（偶发跳一帧）。N1 空数据 p95 16 ms 达标。这不是把 400/300 改短能修的绘制预算问题；未改 `selection_navigation` / `selection_control`。
- N1-cached animation_end p95 957 ms 是 **FFT 分区切换的 GUI 阻塞**，不是底板曲线变慢：同 token 的 N1-empty 仍是 400 ms。内容就绪 first-access ~28 ms、暖样本 content p95 ~42–45 ms（Off/Light 同量级）。按 Spec：重计算场景另报阻塞，不在本计划改分析管线。
- `fft_cache_matches` 辅助仍为 False（cache key 与 `_fft_any_source_cached` 不完全同构）；场景仍是真实按钮进入 FFT，且 `do_fft()` 已在采样前调用。不把辅助 False 写成缓存命中。
- 500 ms 静止：所有场景 `spontaneous_updates=0`，结束时 driver inactive。
- Off 无底板时部分 host 不进 Python `paintEvent`：feedback/paint_work 为 **null + `no_paint`**，不是 0。

## 探针合同

- 用户动画入口：`QTest.mouseClick` / 现有 `Key_Left`/`Key_Right`。程序对照只走 `_set_mode` / `set_method` / `setCurrentIndex` / `apply_builtin_preset` / `set_plot_mode` / `set_cursor_mode`。
- logic-only 可 offscreen；性能字段一律 null + `logic_only`，不把 `clock().setCurrentTime` 标成性能。
- 导入 `scripts/probe_selection_slide.py` 不创建 `QApplication`（子进程门）。产品代码不引用该脚本。
- 超时记录 `status=UNVERIFIED`，不是 pass。

## 未跑

- Windows 100%/150% 源码运行
- 原生屏幕录屏（权限 / avfoundation 失败）
- `tests/ui/test_pg_canvas_backref_invariants.py`、`tests/ui/test_pg_timedomain_canvas.py`（T5/T6 未改 pg_canvas owner）
- 全量套件与 `tests/acquisition_ui`
- 冻结 Windows Full/Lite

## 命令

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q tests/ui/test_selection_slide_probe.py

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_import_boundaries.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_qsettings_isolation.py \
  tests/ui_kit/test_qss_border_shorthand.py

# Cocoa：不要设 QT_QPA_PLATFORM=offscreen
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/probe_selection_slide.py \
  --output-dir .state/selection-slide-rollout/cocoa --record-screen
```
