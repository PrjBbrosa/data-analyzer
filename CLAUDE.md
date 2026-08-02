# Repository Instructions

**Project:** MF4 Data Analyzer — PyQt5 桌面 GUI，分析 MF4 / HEAD-HDF 等测量数据
（FFT、阶次分析、滤波、加窗），含 CAN 采集。

## TraceLab 7.7 product baseline

- Import supports MF4/MDF, CSV/Excel/HDF, BLF+DBC, audio/video, generic ASCII
  (`.asc`/`.fdc`), waveform-based NI TDMS (`.tdms`), native WinWert (`.wwt`),
  ZFGE2/TestRunPRO (`.zfd`), and MATLAB (`.mat`, including v7.3 via HDF5).
- ASCII needs either a recognizable time column or verified fixed-width sampling
  metadata. TDMS needs valid waveform timing; never invent a fallback rate.
- `.tdms_index` is a TDMS sidecar, never an importable data file.
- WWT uses the file's `Zeit` axis and preserves units/scale/offset. ZFD may use
  an explicitly marked 1 kHz estimated fallback when its timing is invalid.
  MAT uses recognizable time variables only and never guesses engineering units.
- The main time-domain workspace supports up to 12 Views. At narrow widths tabs
  compact to ordinal labels, then overflow into `»`; preserve active View
  visibility, tooltip names, reordering, and context actions.

## Dev commands
```bash
pip install -r requirements.txt        # 依赖
python "MF4 Data Analyzer V1.py"       # 启动 GUI（薄启动器 → mf4_analyzer.app.main）
pytest                                  # 测试（pytest.ini 默认 -m "not slow"）
pytest -m slow                          # 仅性能/长跑用例
```

## Architecture
- `mf4_analyzer/` 主包：`app.py`(入口) · `io/` · `signal/`(数值算法) ·
  `ui/`+`ui_kit/`(PyQt 界面) · `acquisition*/`(采集) · `batch.py`。
- `tests/`（pytest / pytest-qt 自动化测试）· `scripts/`（冒烟/回归脚本）。
- `AGENTS.md` 是 **Codex 专用**，与本文件并行，勿混用。

## Gotchas
- **验真机渲染**：UI/视觉问题（尤其 macOS 原生）必须验真实渲染（截图 / objc 读原生
  属性），别凭「属性设上了 + 单测过」就判定修好。
- 嵌入浮层/菜单的自定义 `QWidget` 必须透明背景；`WA_TranslucentBackground` 会让本体
  QSS 失效 → 需 `paintEvent` 或内部子 widget 兜底。
- 若项目位于 `~/Downloads`：子进程（codex 等）跑过后触发 macOS TCC，对项目目录
  EPERM。解法：给终端 Full Disk Access，或把项目移出 Downloads。

## 历史经验
`docs/lessons-learned/` 存有历年踩坑记录（DSP / PyQt / 重构 / 批处理），
按角色分目录，索引在 `LESSONS.md`。遇到相关模块可先检索，非强制流程。
