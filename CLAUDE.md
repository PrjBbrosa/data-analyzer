# Repository Instructions

**Project:** TraceLab / MF4 Data Analyzer — PyQt5 桌面 GUI，做工程测量数据的导入、
时域/频域/阶次分析、批处理，以及 CAN/XCP 采集回放。版本单一事实源是
`mf4_analyzer/app_meta.py` 的 `APP_VERSION`（当前 v7.9.2），别在别处硬编码版本号。

## Dev commands
```bash
pip install -r requirements.txt   # 依赖；Windows 采集另见 requirements-windows-acquisition.txt
python "MF4 Data Analyzer V1.py"  # 启动 GUI（薄启动器 → mf4_analyzer.app.main）
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest
pytest -m slow                    # 仅性能/长跑用例（pytest.ini 默认 -m "not slow"）
```
- 本机验证走仓库 venv（`.venv/bin/python`）；裸 `python` / `pytest` 未必存在。
- Qt 用例需要 offscreen 平台；`TMPDIR=/tmp` 用来绕开下面 Gotchas 里的 TCC 问题。
- 默认套件约 4600 条、**跑满近 20 分钟**，别当成快速检查；改动局部时先跑对应子目录，
  收尾再跑全量。
- **先取基线**：`main` 上目前就有一批 `tests/ui/` 用例是红的（主要是分屏相关的
  `test_split_*`，`canvas_time.get_visible_xlim()` 返回 `None`，offscreen 和原生平台
  都复现）。动手前先记下当前失败数，别把既有失败算到自己的改动头上。

## Architecture
`mf4_analyzer/` 主包：
- `app.py` 入口 · `app_meta.py` 版本与资源路径
- `io/` 导入层：`loader.py` 总入口 + 各格式模块（`ascii_format` / `csv_format` /
  `head_hdf` / `wwt_format` / `zfd_format` / `mat_format`）
- `signal/` 纯数值算法（`fft` / `order` / `order_cot` / `filters` / `envelope` /
  `spectrogram` / `weighting` / `adaptive` / `channel_math`）——**禁止 import PyQt5 或
  matplotlib.pyplot**，`tests/test_signal_no_gui_import.py` 用子进程投毒法强制这条边界
- `ui/` 主界面：`main_window/`（mixin 组装）· `pg_canvas/`（pyqtgraph 画布）·
  `chart_stack/` · `drawers/` · `inspector_sections/` · `markup/` · `widgets/` ·
  `view_state.py`（View 管理）· `hints.py` + `quickref.py`（两个发现性面）
- `ui_kit/` 通用控件与样式：`style.qss` · `fonts.py`（中文字体）· `popup_shell.py` · `icons.py`
- `batch*.py` + `batch_render_qt/` 批处理：GUI-free runner + Qt 渲染导出
- `acquisition/`（清单/预检）· `acquisition_capture/`（XCP/Vector 运行时）·
  `acquisition_ui/`（Cockpit 界面）
- `help/` 应用内 HTML 帮助页

仓库其余部分：`tests/`（pytest / pytest-qt，按 `signal` `ui` `ui_kit` `integration`
`perf` `acquisition_ui` 分目录）· `scripts/`（冒烟/回归/性能探针）· `tools/`（帮助页截图、
Windows 打包脚本、渲染对比）· `configs/` · `assets/`。

**渲染栈**：图表全量走 pyqtgraph（时域、FFT、阶次、时频、批处理导出）。matplotlib 已从
运行时移除，代码里残留的 `matplotlib` 字样只是历史注释和配色兼容函数，不是活依赖。

## 产品约束（碰导入 / View 相关代码前必读）
- 支持格式：MF4/MDF、CSV/Excel/HDF、BLF+DBC、音视频、通用 ASCII（`.asc`/`.fdc`）、
  NI TDMS（`.tdms`）、WinWert（`.wwt`）、ZFGE2/TestRunPRO（`.zfd`）、
  MATLAB（`.mat`，v7.3 经 HDF5）。
- ASCII 需要可识别的时间列，或已验证的固定宽度采样元数据；TDMS 需要有效波形时基
  ——**绝不臆造采样率**。
- `.tdms_index` 是 TDMS 配套索引，永远不是可导入的数据文件。
- WWT 用文件自带的 `Zeit` 时基并保留单位/缩放/偏移；ZFD 在时基无效时可用**显式标注为
  估算**的 1 kHz 回退；MAT 只认可识别的时间变量，不猜工程单位。
- 批处理与 GUI 共用同一套 ASCII/TDMS 导入规则。
- View 上限按 manager 区分：时域工作区 12（`ui/main_window/window.py` 传 `max_views=12`），
  分析分区 6（`ui/view_state.MAX_VIEWS`）。窄宽度下 tab 先压成序号、再溢出到 `»`；
  改动要保住活动 View 可见性、tooltip 全名、拖拽重排与右键菜单。

## Gotchas
- **验真机渲染**：UI/视觉问题（尤其 macOS 原生）必须验真实渲染（截图 / objc 读原生属性），
  别凭「属性设上了 + 单测过」判定修好。`offscreen` 只能当排版草稿，不能写成视觉验收通过。
- 嵌入浮层/菜单的自定义 `QWidget` 必须透明背景；`WA_TranslucentBackground` 会让本体 QSS
  失效 → 需 `paintEvent` 或内部子 widget 兜底。
- 项目位于 `~/Downloads`：子进程跑过后触发 macOS TCC，对项目目录 EPERM。解法：给终端
  Full Disk Access、把 `TMPDIR` 指向 `/tmp`，或把项目移出 Downloads。
- 用户的分析领域是 **EPS（电动助力转向）**：阶次分析 base 用电机转速，示例信号用
  方向盘扭矩 / 电机转速 / 电机扭矩，别写成发动机（engine）。

## 文档与并行工具链
- 新的分析器文档（计划、评审、用户指南、UI 原型）放 `docs/analyzer/`，子目录分工见
  `docs/analyzer/README.md` 的 Routing 表；`docs/superpowers/` 是历史工作流归档，
  别往里加新内容。
- `AGENTS.md` + `docs/lessons-learned/` + `scripts/lessons/` 是 **Codex 专用**的
  lessons 系统，Claude 不需要走它的 check/promote 流程。其中 `pyqt-ui/`
  `signal-processing/` `refactor/` 下的踩坑记录可以当参考检索；`orchestrator/` 是已废弃的
  多 agent 调度产物。
- `/update-hints` 是项目内命令：UI 交互有增删改时，用它同步 `ui/hints.py`（滚动提示）与
  `ui/quickref.py`（操作速查面板）。
