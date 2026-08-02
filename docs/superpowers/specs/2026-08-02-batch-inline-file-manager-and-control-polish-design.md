# 批处理第一层文件管理与控件细节修正 —— 设计补充

**日期：** 2026-08-02

**状态：** 已实施；Qt 离屏矩阵 PASS，macOS 前台验收待执行

**Governing Spec：** `docs/superpowers/specs/2026-08-01-batch-compact-ui-redesign-design.md`
**视觉原型：** `docs/analyzer/ui-prototypes/2026-08-02-batch-inline-file-manager.html`

## 1. 覆盖关系

本补充只覆盖原 Governing Spec 的以下合同：

- 覆盖 D1 / §3.1“主界面摘要 + 模态文件管理器”，改为**文件管理直接位于 Input 第一层**；
- 补充 §4.1：四个分析方法按钮等宽；
- 补充 §4.3：四个分析预设卡内文字居中；
- 补充 §5：`刻度与字体` 三条滑杆必须可以用鼠标连续拖动。

其余已实施合同继续有效，尤其是数据源/信号术语、共享单次分析预设、方法参数归属、
固定 XLSX/PNG 输出、状态栏和 BatchRunner GUI-free 边界。

## 2. 用户反馈的确定解释

### 2.1 分析方法

`时域 / FFT / FFT vs Time / 阶次` 四个按钮占用相同宽度。长文案不得通过额外 stretch
获得双倍宽度；支持宽度下仍须完整显示 `FFT vs Time`。

### 2.2 分析预设

“文字居中”指四张预设卡内的名称与摘要居中，不改变“分析预设”区标题的左对齐，也不
改变“与单次分析同步”徽标的位置。applied、dirty、disabled、自定义空槽语义保持不变。

### 2.3 文件管理第一层

删除 `管理文件` 按钮和二级模态窗口。Input 栏直接显示：

1. 标题行：`数据文件`、数据源/共同信号事实、总体状态；
2. 操作行：`+ 已加载`、`+ 从磁盘…`；
3. 结构化文件行：名称、路径/逻辑组、解析状态、逐行移除；
4. 空状态：解释下一步，但不另造第三个添加入口。

文件较多时，列表保留一个紧凑的内部滚动视口；列表始终属于第一层，不再通过 modal
或折叠面板进入。内部滚动到边界后应允许外层 Input pane 继续滚动，避免滚轮被困住。

### 2.4 Feature parity

第一层重排必须继续复用当前 `FileListWidget` / source registry 的同一权威状态：

- 从主窗口已加载文件添加；
- 从磁盘多选添加；
- 支持物理文件展开为多个逻辑 source；
- 后台 probe 的 pending / probing / ready / failed / unavailable 状态；
- 重复路径去重；
- 路径、group、probe cost、错误 tooltip；
- 逐行移除；
- 文件数、共同信号、信号选择宇宙、pipeline、预检和运行可用性即时刷新。

不得把 HTML 的模拟文件、数量或延时写入产品代码。不得为了第一层显示而复制第二份文件
模型、重新 probe 已完成来源，或把失败行静默隐藏。

## 3. 第一层文件区布局

```text
数据文件                       3 个数据源 · 126 个共同信号  [解析中]
┌───────────────────────────────────────────────────────────┐
│ [+ 已加载] [+ 从磁盘…]                                    │
├───────────────────────────────────────────────────────────┤
│ ● drive_front.mf4      /data/...              已就绪   ×  │
│ ◌ bench_run_02.hdf     /data/...              解析中   ×  │
│ ! damaged_source.mf4   /data/...              解析失败 ×  │
└───────────────────────────────────────────────────────────┘
```

- 标题事实不能与两个添加按钮争抢同一行；窄栏下事实可换行，但操作不消失。
- 行高目标 48–52 px；列表默认展示约 3 行，最多约 4 行后内部滚动。
- ready / pending / failed / unavailable 必须同时用文字和颜色表达，不能只靠颜色。
- 移除按钮的可点击区不小于 28×28 px，并保留键盘焦点。
- 空态总高约 96 px；不使用截图中那种占满窗口的大空白列表。

## 4. 刻度与字体拖动合同

当前 `RenderStylePopover._on_editor_changed()` 同时读取三个 spinbox。slider 改值时，对应
spinbox 尚未同步，随后 `set_style()` 又用旧 spinbox 值覆盖 slider，因此滑块立即弹回。
修复必须建立明确的双向绑定：

```text
slider(value) -> 同步配对 spin -> 组装 RenderStyle -> emit style_changed
spin(value)   -> 同步配对 slider -> 组装 RenderStyle -> emit style_changed
preset/reset  -> 一次性更新全部编辑器 -> emit 一次
```

要求：

- X、Y、字号三条 slider 都能从轨道和滑块手柄拖动；
- slider 与 spin 始终显示相同规范值；字号按 5% 步进；
- 每次用户动作最多发出一次最终 `style_changed`；
- 自定义拖动后，若不再匹配“疏/标准/密”，预设选中态清除；
- OutputPanel 摘要和最终 recipe 立即更新，不需关闭 popover。

## 5. 验收合同

- 四个方法按钮可见宽度最大差值 ≤1 px，`FFT vs Time` 文案不裁切；
- 四张预设卡名称和摘要的视觉中心线与卡片中心线偏差 ≤2 px；
- Input 主界面无 `管理文件` 入口、无 `BatchFileManagerDialog`，文件动作和行直接可见；
- 空、ready、probing、failed/unavailable、多逻辑 source、移除后的状态均可达；
- 文件变化继续刷新 target picker、pipeline、预检和任务摘要；
- X/Y/字号 slider 经真实 mouse press/move/release 后值发生变化，配对 spin、摘要和 recipe 一致；
- 1080×760 与 1440×900 的真实 Qt 截图均无裁切、重叠或不可达控件；
- HTML 只作为视觉/操作基准，最终 Qt 完成仍需离屏截图目视，macOS 前台证据单独报告。

## 6. 非目标

- 不改变文件解析器、source adapter、信号交集算法或 BatchRunner。
- 不新增清空全部、重试失败、拖放排序、文件分组编辑等新产品能力。
- 不改变预设名称、参数内容、推荐/applied/dirty 状态机。
- 不修改导出图片尺寸、格式、冲突策略或刻度/字号数值范围。
