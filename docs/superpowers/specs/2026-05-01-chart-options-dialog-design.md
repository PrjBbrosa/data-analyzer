# 图表选项轻量弹窗设计规格

## 背景

当前图表设置入口来自 Matplotlib 的原生 figure options / 轴编辑能力，视觉和
应用右侧 Inspector 不一致，字段仍带英文或原生表单感。用户确认采用网页 demo
中的“轻量弹窗”方向：双击图面和点击顶部图表选项按钮都打开同一个中文弹窗。

现有代码边界：

- `mf4_analyzer/ui/chart_stack.py` 在 `_ChartCard` 中为每个 canvas 创建
  `NavigationToolbar`，并已在 toolbar 内插入“复制为图片”按钮。
- `mf4_analyzer/ui/canvases.py` 中 `TimeDomainCanvas`、`SpectrogramCanvas`、
  `PlotCanvas` 都分别处理 `button_press_event` 的双击事件。
- `mf4_analyzer/ui/_axis_interaction.py` 当前只负责坐标轴 gutter 命中检测和
  `AxisEditDialog` 调用。
- `mf4_analyzer/ui/dialogs.py` 当前的 `AxisEditDialog` 只覆盖单轴最小值、
  最大值、标签和自动范围。

## 目标

实现一个和 Inspector 风格一致的中文轻量 `图表选项` 弹窗，并提供两个等价入口：

1. 双击图面：打开被双击 axes 的图表选项。
2. 点击 toolbar 的 `图表选项` 图标：打开当前 canvas 的默认/最近 axes 选项。

## 非目标

- 不实现完整 Matplotlib 原生 figure options 的全部曲线编辑能力。
- 不改变 FFT、FFT-vs-Time、Order 的 DSP 计算、缓存 key 或导出数据格式。
- 不改 Windows 打包/启动优化相关脚本。

## 交互规格

### 入口 A：双击图面

- 用户在任意 canvas 的图面内部双击，弹窗目标为 `event.inaxes`。
- 用户在坐标轴 tick/label gutter 双击，仍可通过现有命中检测定位对应 axes。
- 同一个 canvas 有多个 axes 时，例如 FFT-vs-Time 的主谱图和频谱切片，双击哪个
  axes 就编辑哪个 axes。
- 如果无法解析出 axes，不弹窗，也不影响现有单击、标注、游标和平移缩放逻辑。

### 入口 B：toolbar 图表选项按钮

- 每个 `_ChartCard` toolbar 增加一个 icon-only `图表选项` 按钮。
- 点击该按钮时，打开当前 card/canvas 的图表选项。
- 如果用户刚刚双击或点击过某个 axes，优先使用该 axes；否则使用 canvas 的主 axes。
- 按钮不替代保存、复制、标注、游标或 zoom/pan 控件。

## 弹窗内容

弹窗标题：`图表选项`

字段必须为中文：

- 基础信息
  - 标题
  - 显示网格线
- X 轴
  - 最小值
  - 最大值
  - 标签
  - 刻度：`线性` / `对数`
  - 自动范围
- Y 轴
  - 最小值
  - 最大值
  - 标签
  - 刻度：`线性` / `对数`
  - 自动范围
- 图例
  - 重新生成自动图例

按钮：

- `重置`
- `取消`
- `应用`
- `确定`

## 应用规则

- `应用` 和 `确定` 都把当前字段写回目标 axes。
- `确定` 应用后关闭弹窗。
- `应用` 应用后保持弹窗打开。
- `取消` 关闭弹窗，不修改 axes。
- `重置` 恢复弹窗打开时读取到的初始值，不立即写回 axes。
- X/Y 自动范围勾选时，对应轴使用 `ax.autoscale(axis='x'|'y')`；未勾选时使用
  `set_xlim` / `set_ylim`。
- 标签为空时允许清空 Matplotlib label。
- `线性` / `对数` 分别映射到 `linear` / `log`。
- `重新生成自动图例` 勾选时，若 axes 上存在可展示曲线 label，则调用 `ax.legend()`。

## 视觉规格

- 弹窗采用浅色 Inspector 风格：白底、浅蓝边框、8px 左右圆角、蓝色主按钮。
- 不使用 Matplotlib 原生 figure options 样式。
- `图表选项` toolbar 按钮使用图标优先，tooltip 显示中文。
- 字段保持紧凑，不让长通道名撑破布局。

## 测试要求

新增或更新 pytest：

- `tests/ui/test_dialogs.py`
  - `ChartOptionsDialog` 初始字段使用中文并读取 axes 当前标题、范围、标签和刻度。
  - `应用` 写回标题、X/Y 范围、X/Y 标签、X/Y 刻度。
  - `重置` 恢复打开时字段。
- `tests/ui/test_axis_interaction.py`
  - 双击图面内部时使用 `event.inaxes` 打开图表选项。
  - FFT-vs-Time 多 axes 场景下，双击 slice axes 时目标就是 slice axes。
- `tests/ui/test_chart_stack.py`
  - 每个 chart card 都有 `图表选项` toolbar 按钮。
  - toolbar 按钮调用当前 canvas 的图表选项入口。

验证命令：

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_dialogs.py \
  tests/ui/test_axis_interaction.py \
  tests/ui/test_chart_stack.py \
  tests/ui/test_canvases.py \
  tests/ui/test_inspector.py -q
```

## Review 要求

实现后做一次证据式 review，至少检查：

- 所有用户可见新增文本均为中文。
- 双击图面和 toolbar 按钮走同一个图表选项入口。
- 多 axes canvas 不会把被双击 axes 错路由到其他 axes。
- 没有改动 DSP、FFTTime cache key、SpectrogramResult shape 或 Windows 打包排除规则。
