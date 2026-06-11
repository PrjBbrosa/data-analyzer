# 分析区多视图 + pyqtgraph 迁移 设计 spec

日期：2026-06-10
状态：已与用户对齐（brainstorm 定稿）
范围：FFT / FFT-vs-Time / Order 三个分析 section

## 1. 背景与目标

时域 section 已有成熟的多视图体系（`ViewManager`/`ViewState`/`ViewTabBar`/split），
三个分析 section（FFT、FFT-vs-Time、Order）目前是单视图、单源、matplotlib 画布，
无法做多文件/多通道对比。

目标（用户原话归纳）：

1. 三个分析 section 的绘图从 matplotlib 迁移到 pyqtgraph。
2. 每个 section 增加**独立**的多 view（Time 的 view 与 FFT/Order 的 view 互不共享）。
3. view 内支持 **split 并排**（先 2 格）；线图 pane 内支持 **overlay 叠加 N 条**。
4. 最终效果：多文件 × 多通道 × 多 section 的同时查看、切换与对比。
5. v1 携带四项对比增强：联动缩放、锁定色阶、FFT 游标 Δ 读数、per-view 结果缓存。
6. **现有功能与 feature 一项不删**（实现替换，行为对等）。

### 为什么迁移划算（决策记录）

- 反事实成本：split/联动/实时色阶在 matplotlib 上每样都要手写
  （多实例 FigureCanvas 重、轴联动要手写回调、实时色阶给不了），
  新代码量不少于迁移，且永久维护两套画布框架。
- 实际下线的只有 ~800 行 UI 画布代码（`SpectrogramCanvas` ~450 行、
  `PlotCanvas.plot_or_update_heatmap` + 标注 ~200 行、`do_fft` 内联绘图 ~130 行）。
  计算层（`signal/`）与离线导出（`batch.py`）一行不动。
- colorbar / z 范围 / 标注目前在两个 matplotlib 类里重复实现，
  合并为一个 `PgHeatmapCanvas` 是还技术债。
- 对比功能踩在 pyqtgraph 强项上：`setXLink` 一行联动、`ImageItem` 共享
  levels 即锁定色阶、`ColorBarItem` 可拖动实时调色阶。
- 性能无忧：FFT 谱线 ≤ nfft/2 ≤ 8192 点；热力图矩阵是 `ImageItem` 主场；
  不开 OpenGL（时域同款 CPU 光栅），避开 OpenGL 破坏 `grab_pixmap` 导出的已知坑。

## 2. 非目标（明确推迟）

- 热力图差值模式（A−B，需网格对齐/重采样）→ 二期。
- 2×2 网格 → 二期（pane 模型留扩展位，v1 UI 只做 2 格）。
- per-pane 参数覆盖 → 二期（v1 参数为 per-view 一套，所有 pane/曲线共用）。
- 时域 section 接入新 pane 模型 → 后期（v1 完全不动时域，含其 split_pairs 语义）。
- 跨 section 同屏 → 不做；section 之间保持互斥切换（QStackedWidget 现状）。
- FFT 计算异步化 → 不做（现状同步、足够快，保持行为对等）。

## 3. 数据模型

四层：**Section → View → Pane → Source**。

```
Section（互斥切换）
└── View（标签页，per-section 独立集合，≤ MAX_VIEWS=6）
    ├── params: dict          # 该 section 的计算+显示参数，一套/view
    ├── compare: CompareOpts  # x_linked / levels_locked
    └── panes: list[PaneState]   # v1 长度 1 或 2
        └── sources: list[ChannelKey]  # (fid, ch)；热力图 pane 恒为 1 个
```

### 新类型（`ui/analysis_view_state.py`，新文件）

- `PaneState`：`sources: list[ChannelKey]`、`xlim/ylim`（可选）、
  热力图 pane 另存 `rpm_source`（仅 Order）。
- `AnalysisViewState`：`name`、`panes`、`params: dict`、
  `compare: {"x_linked": bool, "levels_locked": bool}`、`to_dict/from_dict`
  （`schema: 1` 字段，向前兼容）。
- 约束：overlay（len(sources) > 1）仅线图 section 合法；
  热力图 pane 的 sources 长度恒为 1。校验放在 state 层，UI 不重复判。

### ViewManager 泛化

`view_state.py` 的 `ViewManager` 改为接受 `state_factory` 参数
（默认 `ViewState`，保持时域零改动），FFT/FFT-vs-Time/Order 各实例化一份
`ViewManager(state_factory=AnalysisViewState)`。`_split_pairs` 配对逻辑是
时域专属，分析 section 不使用（split 在 view 内部，由 `panes` 表达）。

### 持久化（工程文件）

`project_io.py` 的 doc 新增字段：

```
"analysis_views": {
  "fft":      {"views": [AnalysisViewState.to_dict()...], "active": int},
  "fft_time": {...},
  "order":    {...}
}
```

- 旧工程文件无此字段 → 各 section 默认 1 个空 view（行为同现状）。
- `remap_view_fids()` 扩展为同时重映射 `analysis_views` 内所有
  `panes[].sources`（与现有 `checked` 重映射同款逻辑、同款 key 编码）。

## 4. UI 组成

### ChartStack 页改造

现状：`canvas_fft` / `canvas_fft_time` / `canvas_order` 是三个裸 card 页。
改为每页：

```
_<sec>_page
├── 共享 toolbar（沿用各 card 现有按钮：copy image、模式钮等）
├── PaneArea（QSplitter(Qt.Horizontal)）
│   ├── pane[0]: AnalysisChartCard(canvas=Pg*Canvas)
│   └── pane[1]: 同上（split 时创建/显示，50:50）
└── ViewTabBar（per-section 实例，绑定该 section 的 ViewManager）
```

- `ViewTabBar` 复用现有类，每 section 一个实例（共 3 个新增），
  各绑各的 manager；时域的 tabbar 不动。
- tabbar 的 split 按钮在分析 section 语义改为「当前 view 添加/移除第二格」
  （操作 `panes`，不再是配对两个 view）。
- 焦点路由沿用时域 `_focused_card` 模式：点击哪格哪格亮边框，
  源分配与色阶拖动作用于焦点格。

### 源分配（谁进哪个 pane）

- **FFT（线图）**：navigator 勾选集 `get_checked_channels()`
  （已支持跨文件，`[(fid, ch, color), ...]`）→ 写入**焦点 pane** 的
  `sources`。曲线颜色直接采用 navigator 分配色。
- **FFT-vs-Time / Order（热力图）**：沿用 inspector 的 `combo_sig`
  （Order 另有 `combo_rpm`）选择**焦点 pane** 的唯一 source。
- 切 pane 焦点时，navigator 勾选态 / combo 选项随焦点 pane 回显。

### 参数面板

三个 Contextual（`FFTContextual`/`FFTTimeContextual`/`OrderContextual`）
UI 不改；参数经 per-section bridge 在「UI ↔ AnalysisViewState.params」间
capture/apply（仿 `view_bridge.py` 模式，新文件 `ui/analysis_view_bridge.py`）。
切 view 时恢复该 view 的参数到面板。

### 计算按钮语义

「计算」= 计算**当前 view 的全部 pane、全部 source**（缓存命中即跳过）。
切 view 时：缓存命中的 pane 立即渲染；未命中的 pane 显示空态提示
「参数/源已就绪，点击计算」——**不自动计算**（避免切标签触发重活）。

## 5. 新画布（`ui/pg_canvas/` 包内新增）

两个类服务三个 section，均仿 `TimeDomainCanvasPG` 提供
`grab_pixmap(scale)`，接入 `chart_stack._grab_pixmap_hidpi` 现有降级链。
不开 OpenGL。

### 5.1 `PgLineCanvas`（FFT）

- `GraphicsLayoutWidget` 两行：幅值谱 + PSD（对齐现有双子图）。
- overlay N 条曲线/行；图例命名「文件名 · 通道名」；颜色随 navigator。
- 轴：x 频率 auto/manual，幅值与 PSD 各自 Linear/dB（沿用 Contextual 现有项）。
- 游标：竖直 `InfiniteLine` + 读数面板，列出每条曲线在游标频率处的值
  及相对第一条（主曲线）的 Δ（dB 轴下为 dB 差，线性轴下为差值）。
- 标注（remarks）对等：点击吸附到最近曲线最近采样点，
  `TextItem` + 箭头 + 圆点；右键删除。等价替代 `PlotCanvas.store_line_data`
  + `_add_remark` 行为。

### 5.2 `PgHeatmapCanvas`（FFT-vs-Time 与 Order 共用）

- `ImageItem` + `setRect()` 标定坐标（时间×频率 / 时间×阶次）。
- `ColorBarItem(interactive=True)`：可拖动改 levels；
  拖动 ↔ inspector 的 z floor/ceiling 双向同步（拖动即切到手动模式）。
- colormap：`pg.colormap.getFromMatplotlib(name)` 复用现有 cmap 选项
  （turbo/viridis/…，matplotlib 仍是依赖，色彩完全对等）。
- dB/Linear：沿用现有转换 + 缓存策略（键 `(id(result), db_reference)`）。
- z 范围 auto/manual → `setLevels`；x/y 范围 auto/manual → `setRange`。
- 点击切片（**仅 FFT-vs-Time 启用**，构造参数开关）：点热力图选时间帧，
  底部切片行（同一 `GraphicsLayoutWidget` 内的第二个 `PlotItem`）更新
  频率切片，对等 `SpectrogramCanvas._on_click/select_time_index`；
  `cursor_info` 信号对等。
- 标注对等：右键放置 `(t, f/order, 值)` 标签 + 箭头 + 红点。
- 快速更新：`setImage()` 天然等价于现有 `set_data` 快速路径，无需单独分支。

## 6. v1 对比增强（四项全做）

1. **联动缩放**：split 时 toolbar 出现「联动」toggle（默认开）。
   线图 pane 间 `setXLink`；热力图 pane 间 `setXLink + setYLink`。
2. **锁定色阶**：热力图 split 时 toolbar 出现「锁定色阶」toggle（默认开）。
   开 = 两格共享 levels（auto 模式取两矩阵合并 min/max；手动/拖动任一
   colorbar 同步应用到两格）。关 = 各自独立。状态存 `compare.levels_locked`。
3. **FFT 游标 Δ 读数**：见 5.1。
4. **per-view 结果缓存**：泛化现有谱图 LRU（`main_window._fft_time_cache`，
   12 条）为 `AnalysisResultCache`，按 section 实例化：
   fft=32（结果小）、fft_time=12（沿用）、order=12。
   键 = `(fid, ch, 计算参数 hash)`（display-only 参数不进键，沿用现约定；
   Order 键含 rpm_source 与 COT 参数）。文件关闭时按 fid 失效。

## 7. 计算调度

- `FFTTimeWorker`（`main_window.py:29`）泛化为 `AnalysisComputeWorker`：
  接受 `(fn, args)` 在 QThread 跑，`finished/failed` 信号不变。
- **Order 计算移出 GUI 线程**（修正现状 `do_order_time` 同步阻塞）。
- FFT 保持同步（行为对等，单帧/平均都是 numpy 级耗时）。
- 一个 section 同时最多跑一个 worker；多 pane 任务排队顺序执行，
  busy 态沿用 fft_time 现有指示。

## 8. 导出

- 单图复制：新画布实现 `grab_pixmap(scale)` → 走
  `_grab_pixmap_hidpi`（`chart_stack.py:30`）现有优先链，HiDPI 对等。
- `_copy_fft_time_image` 的 full/main 两模式对等：
  full = 整 widget；main = 按热力图 `PlotItem` + colorbar 的
  scene bounding rect 裁剪（替代 matplotlib tightbbox 方案）。
- split 视图复制：对等时域「左右 pixmap 合成」逻辑。
- `batch.py:622 _write_image`（离线 matplotlib savefig）**不动**。

## 9. 功能对等清单（验收口径：一项不丢）

**FFT**：双子图（幅值+PSD）；win/nfft/overlap；平均模式（单帧/线性平均/
峰值保持）；幅值与 PSD 各自 Linear/dB；x/y 手动范围；presets；
点击标注；复制图像。
**FFT-vs-Time**：nfft/win/overlap/去均值/db_ref/cmap；x/y/z auto-manual；
dB↔Linear；点击时间帧→频率切片；cursor_info 读数；标注；presets
（diagnostic/amplitude_accuracy/high_frequency）；LRU 缓存；异步 worker；
复制图像 full/main 两模式。
**Order**：signal/rpm 选择；fs/rpm 系数/最大阶次/阶次分辨率/时间分辨率/
nfft/每转样本数；x/y/z 范围；dB↔Linear；快速更新路径；标注；presets；
复制图像。
**通用**：HiDPI 导出；中文字体（Qt 原生渲染，较 matplotlib 字体配置更稳）；
工程文件保存/加载（新增 analysis_views 字段，旧文件兼容）。

## 10. 分期（每期独立可发布、可回退）

- **P1 Order 换芯**：`PgHeatmapCanvas`（无切片模式）替换 Order 画布，
  单 view 行为不变；Order 计算移入 worker。截图回归后移除
  `plot_or_update_heatmap` 热力图路径。
- **P2 FFT-vs-Time 换芯**：启用切片行、迁移点击/标注/导出 full+main、
  沿用 worker 与 LRU。回归后移除 `SpectrogramCanvas`。
- **P3 FFT 换芯**：`PgLineCanvas` 替换 `do_fft` 内联绘图，单源行为对齐。
- **P4 多 view + pane 层**：`AnalysisViewState`/`PaneState`、
  `ViewManager` 泛化 ×3、per-section `ViewTabBar` + bridge、split 2 格、
  FFT overlay N 条、四项对比增强、工程文件持久化。
- matplotlib 画布代码随所属 phase 验收后移除；`PlotCanvas` 的线图
  能力如仍被他处引用则保留类本身，只删热力图路径。

## 11. 测试与验收

- 单测：state 模型（pane 增删、to_dict/from_dict round-trip、
  overlay 约束校验）；缓存（键、淘汰、fid 失效）；Δ 读数取值；
  锁定色阶的合并 min/max；`remap_view_fids` 对 analysis_views 的重映射。
- 数值层零改动：现有 signal 测试保持全绿即为计算无回归。
- **视觉验收（每 phase 必做，硬性）**：真实渲染截图对照——
  单热力图（轴/colorbar/范围/cmap）、点击切片、标注、导出 full/main
  像素内容、split + 联动缩放、锁定色阶前后效果、FFT N 条 overlay +
  图例 + Δ 读数。仅"属性已设置"+单测通过不算修好。

## 12. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| ColorBarItem 视觉较 matplotlib 朴素 | P1 先在 Order 上让用户过目，不满意再做自绘刻度微调 |
| main 模式导出裁剪与 tightbbox 不完全一致 | 按 scene bounding rect 实现 + 像素级目检 |
| 标注/点击交互行为差异 | 对等清单逐项验收，差异点列表向用户确认 |
| pane 焦点路由与 navigator 回显复杂 | 复用时域 _focused_card 成熟模式；P4 单独出交互走查 |
| 大改 ChartStack 影响时域 | 时域代码路径零接触为 P1–P4 红线，回归含时域冒烟 |
