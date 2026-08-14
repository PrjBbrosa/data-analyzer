# UltraView P1 验收记录（2026-08-14）

- 日期：2026-08-14
- 对象：P1 可扩展 Board 工作区（sidecar 生命周期、惰性加载、动态 compositor、多 Board）
- 平台：macOS Darwin 27，offscreen Qt，仓库 `.venv/bin/python`
- 证据分层：offscreen 自动化 ≠ Cocoa 前景 ≠ Windows frozen

本文件只记录当时跑过的门。未跑的层写 `UNVERIFIED`，不把部分通过推断成全套通过。

## 1. Offscreen / 源码

| 项 | 证据类 | 结果 | 说明 |
|---|---|---|---|
| UltraView 聚焦套件 | unit + offscreen Qt | **360 passed**（2026-08-14，63.7 s） | sidecar 世代清理、open 不 decode、Board 20 上限、membership 200 截断、template-aware `output_size`、短板导出裁尾白、自由网格项目往返、恶意 ZIP、SearchField / hints / quickref / help |

| 恶意 ZIP | unit | 见 `test_ultraview_preview_sidecar.py` | 条目数 / 压缩比 / `QImageReader.size()` 与 manifest 不符 |
| 多 Board 零计算 | unit | `test_multi_board_switch_and_layout_stay_zero_compute` | create / select / duplicate / `grid_4x3` 不 compute |
| lambda / SearchField | unit | shrink-only 白名单已收口；库搜索换 `SearchField` | UltraView 默认隐藏，不把可见搜索面改成 9 |
| 两进程全量 | two-process | **UNVERIFIED** | 本记录未重跑 `--ignore=tests/acquisition_ui` 与 `tests/acquisition_ui` |

命令前缀与本次命令（`tests/ui` 路径连续，非 UI 文件放最后）：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_ultraview_export.py \
  tests/ui/test_ultraview_state.py \
  tests/ui/test_ultraview_free_grid.py \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_job_isolation.py \
  tests/ui/test_ultraview_preview_sidecar.py \
  tests/ui/test_ultraview_project_session.py \
  tests/ui/test_ultraview_preview_store.py \
  tests/ui/test_ultraview_layouts.py \
  tests/ui/test_ultraview_mode_integration.py \
  tests/ui/test_ultraview_entry.py \
  tests/ui/test_ultraview_capture.py \
  tests/ui/test_ultraview_probes.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_hints.py \
  tests/ui/test_quickref.py \
  tests/ui_kit/test_search_field.py \
  tests/test_help_content.py
```

## 2. 未跑层

| 项 | 结果 |
|---|---|
| A17/A19 Cocoa 20 Board / 12 图滚动 / 导出 | **UNVERIFIED** |
| A20 Windows Full/Lite frozen | **UNVERIFIED** |
| 真机 Retina 12 图 PNG 内存探针 | **UNVERIFIED** |

offscreen 不能代替 Cocoa paint 成本或前景几何。
