# Plan: FFT 时域预览同步 TimeDomain overlay 中高优先级契约

日期：2026-08-12  
范围：`line_canvas.py` · hints/quickref · 必要 main_window 接线 · `tests/ui/test_pg_line_canvas.py`  
对照：`overlay_axes.py` / `canvas.py` overlay 路径

## 0. 是否改善？

是。预览已是多源独立 Y + 共享格栅，却仍用「单图自由拖 Y / 平滚轮空转」模型，和 TD overlay 文案与手感冲突。对齐后只会更一致，不削弱 FFT「可见 X = 分析窗」。

## 1. 高优先级（交互模型）

| ID | 项 | 做法 | 状态 |
|----|----|------|------|
| H1 | 主 VB 图区 X-only | 主图 `y=True`（左轴 gutter 仍可拖）；`_modifierWheelViewBox` 图区 2D 拖强制 X-only | ✅ |
| H2 | 平滚轮 = Y 平移 | `_handle_wheel_dispatch`：无修饰键 → 按格平移；Shift → nice 步进缩放；Ctrl → X | ✅ |
| H3 | gutter 单轴 / 图区全轴 | `axis==1` 只动该 ViewBox；`axis is None` 所有 time VBs | ✅ |
| H4 | 框选后 Y | `_apply_time_preview_box_zoom_y`：主 VB Y 分数映射到各通道 nice 框定 | ✅ |
| H5 | 松手 snap | `_end_view_interaction` → idle `_snap_time_axes_to_grid`（保 span） | ✅ |

## 2. 中优先级（体验）

| ID | 项 | 做法 | 状态 |
|----|----|------|------|
| M1 | 双击编辑 | viewport 双击 → 左轴 chart options / 右轴色板 | ✅ |
| M2 | 选中强调 | lw↑ / 其余 alpha↓ | ✅ |
| M3 | 右轴标签 | `_middle_ellipsis` 通道名 | ✅ |
| M4 | 通道树设为左轴 | FFT：`promote_time_entry_to_left_by_channel` | ✅ |
| M5 | hints/quickref | `fft.preview_*` + 图表手势行 | ✅ |

## 3. 非目标

不嵌整棵 `OverlayAxisManager`；不做分屏/共轴/companion；不改 FFT 分析窗 X 契约。

## 4. 验证

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py tests/ui/test_hints.py tests/ui/test_quickref.py -q
```

实测（2026-08-12）：**194 passed**。

## 5. 完成定义

- [x] H1–H5 + M1–M5 代码落地
- [x] 聚焦测试绿
- [x] hints/quickref 与行为一致
