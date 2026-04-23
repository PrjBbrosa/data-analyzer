# Mac 浅色风格 · 三栏 + Drawer UI 重构

**日期：** 2026-04-23
**范围：** `mf4_analyzer/ui/` 整层，以 `main_window.py` 为核心
**约束：** 现有所有 feature 不得删除；纯 UI 重构，不改变分析算法

---

## 1. 目标

把当前的 2-pane 布局（窄左栏参数面板 + 右侧 TabWidget 容器）重构为 Mac 浅色风格的 **3-pane + Drawer** 布局：

- **左栏**：数据源导航 — 文件 + 通道
- **中栏**：可视化主区 — 单一图表画布，由顶部 segmented 切换时域 / FFT / 阶次三种模式
- **右栏**：Inspector — 上半常驻（跨模式共享的横坐标、范围、刻度），下半按中栏模式上下文切换
- **Drawer / Sheet / Popover**：较重或低频功能从主布局剥离

视觉语言参考 Finder / 邮件 / 备忘录：浅色 + 半透明侧栏 + SF Pro + 大圆角 + 细分隔线。

## 2. 不变量

- 现有所有 feature 保留，包括多文件加载、跨文件通道选择、Subplot/Overlay、单/双游标、区间选择、轴锁、刻度密度、自定义横坐标、重建时间轴、统计、Excel 导出、通道编辑（含数学通道）、窗函数/NFFT/重叠/自适应/标注、三种阶次分析（时间-阶次谱 / 转速-阶次谱 / 阶次跟踪）及其全部参数。
- 分析算法层（`signal/*`）不动。
- I/O 层（`io/*`）不动。

## 3. 整体框架

```
┌────────────────────────────────────────────────────────────────┐
│  TitleBar: MF4 Data Analyzer │ <active file metadata>          │
├────────────────────────────────────────────────────────────────┤
│  Toolbar:  ＋添加  🔧编辑通道  📥导出  │  [时域|FFT|阶次]  │  ⌖ 🔒 📷  │
├────────────┬─────────────────────────────────────┬─────────────┤
│            │                                     │             │
│  LEFT      │           CENTER                    │   RIGHT     │
│  文件列表   │           Chart canvas              │   Inspector │
│  通道列表   │           (单画布, 模式切换)         │   (持久+上下文)│
│            │                                     │             │
│            ├─────────────────────────────────────┤             │
│            │     Stats strip (常驻)              │             │
├────────────┴─────────────────────────────────────┴─────────────┤
│  StatusBar: Ready · 2 channels · Fs 1000 Hz · 12.0 s           │
└────────────────────────────────────────────────────────────────┘
```

三栏之间用 `QSplitter(Qt.Horizontal)` 拼接，splitter handle 可拖动调整各栏宽度。栏比例默认依据实际内容设置（见 §9 尺寸），拖动后持久化到本会话内存（v1 不落盘）。

## 4. 左栏 — 数据源

### 4.1 文件列表（替代当前 QTabWidget）

- 竖排 row，每行展示：`📄 filename` + 关闭 `✕` + 下一行 metadata（行数 / Fs / 时长）
- 活动文件：`#007aff` 背景，白字；其他：无背景，点击切换
- 关闭 `✕` 点击：仅关闭该文件（等效当前 `_tab_close`）
- 替换当前的 `self.file_tabs` QTabWidget；`file_id ↔ row` 绑定关系用 `QListWidget` 或自绘 `QWidget` 实现

### 4.2 通道列表（保留跨文件能力）

- 分组显示：每个已加载文件一个分组 header `[filename]`（小字 `#86868b`）
- 每行：checkbox + 色块 + 通道名 + 单位（右对齐、`#86868b`）
- Active 文件的通道行微底色 `rgba(0,122,255,0.08)` 以增强"当前文件"感
- 通道复选等价于当前 `MultiFileChannelWidget.channels_changed` 信号

### 4.3 左栏头部

- `文件` 小标题 + 右侧加载数量
- `通道` 小标题 + 右侧 `全选` 链接（动作：勾选/取消活动文件的所有通道）

## 5. 中栏 — 图表主区

### 5.1 单一画布

- 用一个 `QStackedWidget` 容纳三个 canvas（`TimeDomainCanvas` / 两个 `PlotCanvas`），由顶部 segmented control 切换。**不再使用 `QTabWidget` 容器**。
- 每个 canvas 仍保留自己的 `NavigationToolbar`；但 toolbar 不再放在 canvas 上方独占一行，而是以半透明悬浮卡片形式叠在画布右上角（`rgba(255,255,255,0.85)` + 1px 边框）。实现方式：`NavigationToolbar` 作为 canvas 的**同级子 widget**，手动定位到 canvas 的 `(x=width-toolbar_width-8, y=8)`；canvas resize 时同步重定位。**不会遮挡 axes 区域**（matplotlib 默认 axes padding 足够）；若局部遮挡极端情况出现，用户可通过 NavigationToolbar 的 pan 移开。

### 5.2 游标读数（重新设计）

- **当前**：深色背景（`#1e1e1e`）+ 绿色 monospace（`#0f0`）独立 QLabel 条，占画布上方一行高度。
- **新**：简单大方风格 — 浅色背景 pill 标签，贴在画布左下角内部。
  - 背景 `rgba(255,255,255,0.92)` + 1px `#e5e5e7` 边框 + 圆角 6px
  - 文字：系统字体（非 monospace），`#1d1d1f`，12px
  - 单游标示例：`t = 5.320 s   Speed = 1820.5 rpm   Torque = 84.2 Nm`
  - 双游标示例：`Δt = 2.150 s   ΔSpeed = +320.4   ΔTorque = +12.1`
- 叠在画布之内而非之上，不占用画布布局高度。
- 无通道选中 / 未 hover 时自动隐藏。

### 5.3 统计条（常驻）

- 画布下方一行 `QWidget`，浅灰底 `#f7f7f9`，边框 `#e5e5e7`，圆角 7px。
- 内容格式：`● Speed: min=0 max=2100 rms=1204 p2p=2100  ● Torque: …  │ 区间 3.2s–8.5s`
- 无选中通道时显示"—"占位（不塌陷）。

### 5.4 模式特定行为

| 模式 | 画布行为 |
|---|---|
| 时域 | `TimeDomainCanvas`；支持 span selector、单/双游标、区间 highlight |
| FFT | `PlotCanvas`（上幅值下 PSD）；支持 remark 标注 |
| 阶次 | `PlotCanvas`；pcolormesh 谱图 或 阶次跟踪双子图 |

切换模式时：
- 各 canvas 的 matplotlib 状态独立保留（不会因切换丢掉 FFT 结果）
- 右栏 Inspector 下半对应切换
- 游标 / 区间选择仅时域可见

## 6. 右栏 — Inspector

**结构：两个垂直堆叠的卡片，卡片内按节折叠。**

### 6.1 常驻顶部卡片

三种模式下都显示：

| 节 | 内容 | 对应现有控件 |
|---|---|---|
| 横坐标 | 时间/通道 segmented · 通道下拉 · 标签 LineEdit | `combo_xaxis` / `combo_xaxis_ch` / `edit_xlabel` / `btn_apply_xaxis` |
| 范围 | 启用 checkbox · 开始/结束 双 DoubleSpinBox · "从图中拖选" 链接 | `chk_range` / `spin_start` / `spin_end` |
| 刻度密度 | X/Y SpinBox（默认折叠） | `spin_xt` / `spin_yt` |

### 6.2 上下文下部卡片

**时域：**
- 绘图模式 — Subplot/Overlay segmented（替代 `combo_mode`）
- 游标 — 双游标 checkbox（单游标默认开）；游标说明 subtitle

**FFT：**
- 分析信号 — 信号下拉（单选） + Fs SpinBox + `⏱ 重建` 小按钮（popover）
  - 信号下拉 = 所有已加载文件的所有通道（复用当前 `combo_sig`）
  - 切到 FFT 时若 Fs 空，默认取活动文件的 Fs
- 谱参数 — 窗函数下拉 + NFFT 下拉 + 重叠 SpinBox
- 选项 — 自适应频率范围 checkbox + 点击标注 checkbox
- `▶ 计算 FFT` 按钮（宽度满 card）

**阶次：**
- 信号源 — 信号下拉 + 转速下拉 + Fs + RPM 系数
- 谱参数（时间-阶次 / 转速-阶次 共用） — 最大阶次 · 阶次分辨率 · 时间分辨率 · RPM 分辨率 · FFT 点数
- 两按钮行：`▶ 时间-阶次` · `▶ 转速-阶次`（宽度均分）
- 阶次跟踪（独立节） — 目标阶次 SpinBox + `▶ 阶次跟踪` 按钮
- 进度 Label 显示在按钮行下方（替代 `lbl_order_progress`）

分组逻辑说明：`目标阶次` 只被"阶次跟踪"使用，与"时间-阶次 / 转速-阶次"无关；分到独立节避免视觉误导。

### 6.3 切换逻辑

- 模式切换时：仅下部卡片 swap；顶部卡片（含用户已输入的范围值等）原样保留
- 文件切换时：顶部卡片保留；下部卡片的"信号/转速/Fs"下拉刷新选项；Fs 更新为新文件默认
- 所有"计算类"按钮（FFT / 时间-阶次 / 转速-阶次 / 阶次跟踪）**都在 Inspector 内**，不在顶部 toolbar。改完参数就地触发。

## 7. 顶部工具栏

三段式：

| 左 | 中 | 右 |
|---|---|---|
| ＋ 添加文件 · 🔧 编辑通道 · 📥 导出 | [时域 \| FFT \| 阶次] segmented | ⌖ 重置游标 · 🔒 轴锁 · 📷 截图 |

- 所有按钮均为浅色 pill 样式：白底 + `#d2d2d7` 边 + 6px 圆角 + 5×11 padding
- segmented control：`#e8e8ed` 底 + 选中 segment 白底 + 轻阴影
- 关闭活动文件按钮去掉（改到左栏每行 `✕`）
- "全部关闭" 移到文件列表头部右侧 kebab 菜单或右键菜单（v1 放 kebab）

## 8. Drawer / Sheet / Popover

| 功能 | 形态 | 触发 | 行为 |
|---|---|---|---|
| 通道编辑 | Slide-in Drawer（右侧） | Toolbar 🔧 按钮 | 主界面仍可见；宽度 ~420px；关闭按钮在 drawer 顶部；保存/取消在底部 |
| 导出 Excel | Sheet（从窗口顶部下拉） | Toolbar 📥 按钮 | 遮罩背景（`rgba(0,0,0,0.2)`）；点击遮罩不关闭；必须明确取消或确定 |
| 重建时间轴 | Popover | Inspector FFT/阶次 下拉旁的 `⏱ 重建` | 小浮窗：Fs 输入 + 确定；点 popover 外关闭 |
| 轴锁 | Popover | Toolbar 🔒 按钮 | 轴锁详情面板（现 `AxisLockBar` 内容） |

### Qt 实现要点

- Drawer：自写 `QWidget` 子类 + `QPropertyAnimation` on `QRect`；父级为 `MainWindow` 的 center widget
- Sheet：`QDialog` with `Qt.Sheet` window flag + 手动从顶部动画下拉
- Popover：`QDialog` with `Qt.Popup` flag + anchor 到按钮下方

## 9. 尺寸与窗口

- **默认尺寸**：1400 × 860（基于：左 220 + 中 ≥ 600 + 右 260 + 间距 + title/toolbar/status ≈ 880 px 高）
- **最小尺寸**：1100 × 640
- **栏初始比例**：左 `220px`，右 `260px`，中自适应（使用 `QSplitter.setSizes([220, width-220-260, 260])`）
- **栏最小宽度**：左 180px / 中 400px / 右 220px（低于此 splitter handle 不能拖过去）
- Splitter handle：1px 细线、悬停时显示拖动游标

## 10. 视觉 tokens（QSS 层）

```
颜色
  背景主      #ffffff
  背景侧栏    rgba(248,248,250,0.85)
  背景次卡    #f7f7f9
  边框        #e5e5e7
  边框深      #d2d2d7
  文字主      #1d1d1f
  文字次      #6e6e73
  文字弱      #86868b
  强调        #007aff
  警示        #ff9500
  危险        #ff3b30

字体
  系统        -apple-system, "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif
  尺寸        12/11/10/9 px (body/label/subtitle/hint)

圆角
  卡片        10 px
  按钮        6 px
  pill        5 px

阴影
  浅          0 1px 2px rgba(0,0,0,0.04)
  卡片悬浮    0 4px 12px rgba(0,0,0,0.06)
```

状态栏、title 栏和现有 QSS 中的深色残留样式（如游标 label 的 `background:#1e1e1e;color:#0f0`）全部改为浅色 token。

## 11. 快捷键

v1 不加。保留 matplotlib NavigationToolbar 自带的键盘交互（P/S/H 等）。

## 12. 代码组织影响

新的 UI 组件文件建议：

```
mf4_analyzer/ui/
  main_window.py        # 瘦身：仅承载 QSplitter + toolbar + status
  toolbar.py            # 新增：顶部三段工具栏 + segmented 控件
  file_navigator.py     # 新增：左栏文件 + 通道组合
  chart_stack.py        # 新增：中栏 QStackedWidget + 模式切换 + stats strip
  inspector.py          # 新增：右栏 Inspector 框架
  inspector_sections.py # 新增：各节子 widget（横坐标/范围/刻度/绘图模式/FFT参数/阶次参数）
  drawers/
    channel_editor_drawer.py  # 原 ChannelEditorDialog 改造为 drawer
    export_sheet.py           # 原 ExportDialog 改造为 sheet
    axis_lock_popover.py
    rebuild_time_popover.py
  canvases.py           # 保留；调整 cursor readout 传递方式
  axis_lock_toolbar.py  # 内容迁入 axis_lock_popover.py 后删除或保留为过渡
  icons.py              # 保留，可能新增 segmented icon
  widgets.py            # StatisticsPanel 重新设计为统计条；MultiFileChannelWidget 迁入 file_navigator.py
  style.qss             # 全面重写：浅色 token + 圆角 + 半透明
```

`main_window.py` 的职责从"装配所有控件 + 信号分发 + 算法调用"缩减为"装配三栏容器 + toolbar + 路由信号"。算法调用方法（`plot_time` / `do_fft` / `do_order_*`）保留在 MainWindow，但表单读值改为从 Inspector 子组件读。

## 13. 交互一致性规则

1. **切换模式不丢参数** — 顶部常驻节用户输入原样保留；下部节 swap，上一模式的值记在内存，回切时恢复
2. **切换文件不重置计算** — 三个 canvas 各自保留上一次的绘制结果；切换活动文件只刷新 Fs 及信号/转速下拉选项，不自动触发重绘。用户需显式按"绘图" / "计算 FFT" / "▶ 时间-阶次" 等按钮才会重算。（与当前行为一致）
3. **关闭文件即清图** — 对应现有 `_reset_plot_state('file')` 行为，扩展到三种 canvas
4. **Overlay > 5 通道二次确认** — 保留现有提示
5. **无通道选中时**画布 clear + 统计条占位 —，与现有 `plot_time` 中的 guard 行为一致

## 14. 非目标（v1 不做）

- 布局方案多主题（深色模式）
- 拖动文件到窗口打开（保留当前"添加"按钮路径）
- 快捷键
- 多 inspector 面板分离成独立窗口
- 保存用户栏宽到磁盘

## 15. 验证标准

- [ ] 所有原有按钮/控件/对话框功能等价可用
- [ ] 无回归：打开任意 MF4/CSV/XLSX 文件后，时域/FFT/阶次三种分析结果与重构前一致
- [ ] 三栏 splitter 可拖动；拖到极限不崩溃
- [ ] 模式切换时常驻区保留、上下文区切换
- [ ] Drawer/Sheet/Popover 打开关闭无残留
- [ ] 窗口缩到最小尺寸（1100×640）所有控件可见
- [ ] QSS 全浅色，无深色残留
- [ ] 中文字体显示正常
