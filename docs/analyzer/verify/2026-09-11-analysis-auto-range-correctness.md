# 自动范围与频谱显示优化验收

日期：2026-09-11。实现已完成，focused 与适用边界检查通过；Cocoa 合成数据实机画布及 Batch PNG 验收已执行。未执行 Windows frozen 验收，也未用客户原文件核实截图中的 24/48 kHz 元数据差异。

## 快照与责任

- 起始 HEAD：`a8d4b231c96f1a2f25f85c2aeee2e9a7cbf47f46`。
- 集成 HEAD：`569fdc0c07d00adf1f2ee1ef0d06de90b91686a2`。其他会话在执行期间提交了已有“四项交互优化”，并把当前分支切回 `main`；实施验收阶段未提交、暂存或推送；提交由用户后续单独授权。
- 原工作区状态及差异：`.state/analysis-auto-range/baseline-status.txt`、`baseline.patch`；最终状态及源文件指纹见同目录 `final-status.txt`、`final-source-sha256.json`。
- 用户本轮明确授权 agent 执行，覆盖原计划中“不派生 agent”的历史执行备注。三个 agent 分别负责中立范围/Batch、FFT 画布、Pane 状态；协调者负责热图/Order 接入、交叉审查和最终门。
- 新增范围数学只在 `signal/display_ranges.py`；未修改 DSP、采样率、计权、NFFT 计算或产品版本。帮助、项目 schema10 与一条已验证 lesson 同步更新。

## 实现与缺陷关闭

| 项目 | 结果与证据 |
|---|---|
| R1 Linear 切片误用 dB 阈值 | 用原始有效 mask 与中立 padded helper；Linear 0..1000 为 -50..1050，缩放后 900..1000 为 895..1005 |
| R2 Batch 窗口外峰影响 Y | 先确定 X，再适配可见原始幅值；0..200 Hz 可见 -110..-90 dB 得到 -111..-89 |
| R3 时频自动意图被改手动 | 生产自动路径不再传手动 freq_range；主图与切片跟随同一当前 viewport |
| R4 能量裁频隐藏弱峰 | FFT/时频使用实际有限结果 bins，FFT 多源取并集，保留旧能量 helper 兼容入口 |
| R5 完整频段抽点导致窄窗稀疏 | 可见窗口及实际绘图区宽度重建 peak trace；保留原邻点、NaN 断点，原数据不变 |
| R6 自动 Y 裁深谷 | GUI/Batch 不再使用线图 P99-30 或 peak-200 截底；热图自动颜色对比度规则保持 |
| R7 FFT Home 沿用旧裁频 | Home 使用完整 raw extent 和有效原幅值；预览仍显示所有已选来源 |
| R8 自动捕获被当用户范围 | Pane 逐轴 auto/user/home/legacy，程序捕获不改变来源；参数、重算与恢复事务区分 |

交叉审查还关闭了：NaN X 过滤后造桥、有断点的 peak trace 漏边界邻点、手动 Z 参考平移后切片未同步、空热图残留、极值 padding 溢出、ViewBox mouseEnabled 被误认为实际变更轴，以及只恢复 X 时自动 Y 被旧全窗口 Y 覆盖。相关 red/green 日志保存在 `.state/analysis-auto-range/`。

## 验收矩阵

| ID | 证据 | 结论 |
|---|---|---|
| A1 | FFT 24/48 kHz 合成结果实际 bins gate；MainWindow 时频生产入口到 12000 Hz | PASS（合成结果；客户元数据未调查） |
| A2 | Cocoa NFFT=1188000：窄窗绘图点 19→1237，resize 后 1415；已知峰 -15 dB 保留，raw 数组不变 | PASS |
| A3 | raw deep-valley tests；Cocoa Y=-314.25..-0.75 覆盖 -300..-15 | PASS（peak trace 保峰，不承诺每桶保留最小值） |
| A4 | Linear 单位缩放、真实 Order 入口的转置 mask、GUI/Batch slice tests；Cocoa -50..1050 | PASS |
| A5 | GUI/Batch 实际画布/scene gates；Batch PNG 可见曲线 -110..-90 | PASS |
| A6 | MainWindow 时频入口 + Cocoa：主图/切片 1000..2000，Home 两者回 0..12000 | PASS |
| A7 | View 切换、X-only auto-Y、逐轴 Apply、状态提示/恢复按钮、新计算重置 | PASS |
| A8 | schema10/legacy JSON round-trip、独立轴失效、联动 split、三种分析冷缓存、fresh MainWindow 项目打开真实 worker 重算、来源移除 | PASS |
| A9 | 中立 empty/constant/dtype/shape/mask/boundary tests；空热图清理、NaN断点、深谷、极值范围 | PASS |
| A10 | manual-Z/reference/颜色拖动既有 gates；新增参考平移切片与矩阵不变测试 | PASS |
| A11 | FFT Home/restore/resize/可见Y适配/ChartOptions/历史既有路径；实际轴事件回归 | PASS |
| A12 | 时域 ChartOptions raw-union、FRF Hz/log/coherence 两项指定对照 | PASS |

## 测试结果

测试运行时均为项目 `.venv/bin/python`，环境 `TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=.`。以下为不同 gate 的结果，不相加冒充去重总数。

| Gate | 实际结果/日志 |
|---|---|
| 范围、FFT/热图画布、Batch、兼容 helper owner 汇总 | `final-render-owners.txt`：577 passed / 2 failed；两项为旧无位移事件预期及测试矩阵坐标形状不匹配，修正后 `final-owner-recheck.txt` 2 passed，热图完整复验见下行 |
| 热图完整复验 | `final-heatmap-owner.txt`：182 passed |
| 状态/真实多View/项目IO/dialog/axis/source owner 汇总 | `final-state-owners.txt`：230 passed |
| 三种分析真实生产范围/Order 转置 mask | `production-order-gate.txt`：3 passed |
| 时频/Order 冷缓存及 fresh MainWindow 项目打开 | `cold-restore-tests.txt`：3 passed |
| 适用边界、帮助、时域/FRF 指定对照 | `boundary.txt`：118 passed / 1 skipped / 4 failed；两项为lambda ratchet可缩减、一项新增hint超长、一项原有quickref超长。修正后 `boundary-recheck.txt` 87 passed |
| 最后源改动后的 backref/state/lambda 与真实来源移除 | `final-boundary-recheck.txt`：12 passed |

唯一边界 skip 为 `tests/test_packaging_imports.py::test_pyinstaller_spec_lists_new_modules_and_style_data`：本机没有 `build/spec/TraceLab8.2.3.spec`（生成的 Windows 构建产物）；不能等价于 Windows 打包通过。Qt offscreen 插件能力提示及上游 pyqtgraph/NumPy shape deprecation warnings 未作为业务测试失败隐藏。未运行全量套件，符合本计划 focused/boundary 范围。

## Cocoa 与产物

实机命令（使用本机 Cocoa GUI 线程创建、show、处理事件及截图）：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=cocoa PYTHONPATH=. .venv/bin/python .state/analysis-auto-range/cocoa_probe.py
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=cocoa PYTHONPATH=. .venv/bin/python .state/analysis-auto-range/cocoa_status_probe.py
```

- `cocoa-results.json`：baseline/current 同机对照。baseline 加载 HEAD 中原 FFT 画布类；共用当前其他依赖，属于显示路径对照，不是独立旧版本整包 benchmark。
- 每项耗时包含固定 50 ms 事件处理：baseline 首显 57.98 ms、窄窗 50.11 ms；current 首显 73.66 ms、窄窗 54.59 ms、resize 55.93 ms。单次样本不能推导 P95 或宣称整体性能更快。修复了实现期间 `union1d` 带来的首显约 387 ms 退化。
- 已实际读取截图：`current-fft-narrow.png`、`current-linear-slice.png`、`batch-fft-visible.png`、`cocoa-mainwindow-zoom.png`、`cocoa-mainwindow-home.png`。范围、峰值、切片及按轴暂停/恢复入口可见。
- `cocoa-status.json` 记录实际主窗口 label 几何、缩放后主图/切片及 Home 范围。最终状态探针使用独立 INI QSettings 路径。一次补齐 Inspector 展示的探针在 closeEvent 等待保存确认，已停止并改为销毁测试窗口；最终命令 exit 0。
- 以上为真实 Cocoa 窗口、合成数据与自动探针，不替代客户完整前台工作流或 Windows Full/Lite frozen 可执行文件验收。

## 收尾

`git diff --check` 通过；lesson 已晋升为 `docs/lessons-learned/analysis-line-ranges-use-raw-valid-window.md`。历史文档、外部任务与无关 `ssh-keygen` 文件未清理。验证脚本、截图、日志放在 `.state/`，不加入产品包。
