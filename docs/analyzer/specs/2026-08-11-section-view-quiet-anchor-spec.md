# Section View 安静锚点 Spec

- 日期：2026-08-11
- 状态：设计定版，待实施
- 对应计划：
  [`2026-08-11-section-view-quiet-anchor-implementation.md`](../plans/2026-08-11-section-view-quiet-anchor-implementation.md)
- 真实基线：当前 Qt `ViewTabBar` 与用户提供的宽 / 窄界面截图
- 非基线：
  `docs/analyzer/ui-prototypes/2026-08-11-section-view-context-*.html`
  仅是探索稿，其中的栏高、锚点宽度和收纳算法不得进入实现

## 1. 一句话结论

> 在现有 28px `ViewTabBar` 的最左侧增加一个不可交互的「模式图标 + section
> 名称」安静锚点；锚点的真实 `sizeHint()` 进入现有宽度预算。除此之外，继续原样使用
> 当前的 `roomy → compact → overflow` 三段逻辑，不改变 View 名称、颜色、顺序、
> 当前项保护、溢出次序或各 section 的 View 上限。

这次不是重做 View 标签栏。锚点只解决「左右切换 section 后，每条底栏都从
`View 1` 开始，且 View 色板重复，当前位置难以一眼确认」的问题。

## 2. 当前行为是必须冻结的合同

当前实现已经正确覆盖多 View 和窄窗口，不应被新设计替换：

| 状态 | 当前真实行为 | 本次要求 |
| --- | --- | --- |
| Roomy | 所有 View 显示完整名称，例如 `View 1 … View 12` | 原样保留 |
| Compact | 所有 View（包括当前项）只显示彩色标记 + 顺序号；完整名进 tooltip | 原样保留 |
| Overflow | compact 仍放不下时，从尾部开始 `setTabVisible(False)`；跳过当前项 | 原样保留 |
| 当前项 | 即使当前项位于尾部也必须留在条上；resize 不得触发 View 切换 | 原样保留 |
| `»N` | `N` 等于实际隐藏 tab 数；菜单列出全部 View 完整名并勾选当前项 | 原样保留 |
| `+` | 读取当前 manager 的上限；时域 12，分析 section 6；满员禁用 | 原样保留 |
| 分屏动作 | `+`、`»N`、关闭合并/对比等固定动作先占预算，tab 让位 | 原样保留 |

用户给出的窄状态截图是关键验收样本：当前 `12` 仍显示为编号 `12`，`7–11`
收进 `»5`。加入锚点后，在等价的可用 tab 预算下仍必须得到同类结果。

## 3. 视觉与信息层级

### 3.1 结构

真实布局仍是一行，不增加 footer 高度：

`[section 锚点] [View tabs] [»N?] [+] …… [分屏/比较动作?]`

锚点放在共享 `ViewTabBar` 内、现有 `QTabBar` 之前，因而时域和四个分析 section
使用同一套结构与样式。

### 3.2 锚点内容

| section key | 可见文案 | 图标来源 |
| --- | --- | --- |
| `time` | 时域 | 复用顶部模式切换器的 `Icons.mode_time()` |
| `fft` | 频谱 | 复用 `Icons.mode_fft()` |
| `fft_time` | 时频 | 复用 `Icons.mode_fft_time()` |
| `frf` | 频响 | 复用 `Icons.mode_frf()` |
| `order` | 阶次 | 复用 `Icons.mode_order()` |

锚点靠「图标形状 + 明文 section 名」识别，不依赖颜色。View 彩色标记继续只代表
View 身份，不按 section 重映射，也不新增另一套 section 彩虹色。

### 3.3 安静程度

- 总高度保持 `ViewTabBar` 现有 28px；锚点不得把底栏扩成原型中的 44px。
- 图标建议 14px，文案使用与 tab 接近的 11–12px 半粗字重；两者一行垂直居中。
- 使用现有中性文字/图标色，右侧只留一条现有边框体系中的浅分隔线。
- 不使用大面积 section 色块、渐变底、3px 彩色竖条、卡片阴影或独立状态栏。
- 宽度由内容、图标、间距和 padding 的真实 `sizeHint()` 决定；禁止复制 HTML
  的 `112px / 96px` 固定宽度。
- 锚点没有 hover/pressed/selected 状态，不使用手型光标，不进入 Tab 焦点链。
- accessible name 为 `当前区域：<section 名>`；视觉图标作为装饰，名称由明文提供。

## 4. 宽度预算与隐藏逻辑

### 4.1 唯一算法变化

`ViewTabBar._tabs_budget()` 当前从整行宽度中扣除 layout margins、spacing、`+`、
可见的 `»N`、split chip / split clear。实施后只增加一项：

> 当 section 锚点可见时，再扣除锚点的
> `max(sizeHint().width(), minimumSizeHint().width()) + layout spacing`。

不得引入新的像素阈值，也不得在 `_sync_tabbar_width()` 外复制一套预算算法。锚点出现
后，roomy 或 compact 较以前更早降级是正确结果，因为 tab 的真实可用宽度确实减少了。

### 4.2 三段逻辑不变

1. **Roomy**：显示全部 tab，使用 manager 中的完整 View 名称。
2. **Compact**：显示全部 tab，所有 tab 文案都改为位置顺序号；tooltip 从 manager
   读取完整名称。
3. **Overflow**：预留最宽 `»N` 后，继续从末尾向前隐藏；遇到 current index 就跳过，
   直到可见 tab 的实测宽度不超预算。

锚点不得参与以下判断：当前 View 是谁、哪些 View 优先、View 的 manager index、
重命名文本、拖拽顺序或菜单内容。它只是一个固定 sibling。

### 4.3 明确拒绝探索稿中的错误逻辑

- compact 时**不**单独保留当前 View 完整名；当前项仍显示编号。
- overflow 时**不**改成围绕当前项保留相邻 View；仍采用现有尾部收纳规则。
- 不用 HTML 的文字宽度估算、固定 anchor 宽度、固定 control 宽度决定密度。
- 不因为锚点存在而移除 tab；必须继续使用 `setTabVisible(False)` 保持
  `QTabBar index == ViewManager index`。

## 5. API、所有权与状态

`ViewTabBar` 增加向后兼容的可选 `section` 参数：

```python
ViewTabBar(manager, parent=None, *, section=None, ...)
```

- 产品挂载点必须传合法 key：时域传 `time`，`AnalysisSectionPage` 直接传自身已有的
  `section`。
- `section=None` 时不创建/不显示锚点，保留现有独立调用和测试构造方式。
- key → 文案/图标的展示映射由 `ui/view_tabbar.py` 内部持有；调用方不拼装 QLabel、
  不传任意颜色，也不把展示字段写进 `ViewState`。
- 未知非空 key 视为编程错误，尽早 `ValueError`；不得静默显示原始 key。
- 锚点无可变会话状态，不进入 `.tlproj`、QSettings、undo、复制 View 或 preset。
- View 名称、`tab_color`、split、active、顺序和 manager 上限均保持原 owner。

## 6. 全状态行为矩阵

| 场景 | 必须结果 |
| --- | --- |
| 时域 1–12 个 View、足够宽 | 左侧显示「时域」，其后 View 全名；满 12 时 `+` 禁用 |
| 任一分析 section 1–6 个 View、足够宽 | 显示对应锚点；满 6 时 `+` 禁用 |
| roomy 刚好放不下 | 只进入现有 compact；锚点不缩、不隐藏 |
| compact 刚好放不下 | 出现 `»N`；N 与隐藏 tab 数一致 |
| 当前为末尾 View 12 | View 12 始终可见，resize 不发出 `switch_requested` |
| 从 `»N` 选择隐藏 View | manager 切换后该 View 回到条上，另一尾部 View 可被收纳 |
| 重命名 View | roomy 立即按新名重测；compact tab 仍是编号，tooltip/编辑器用新全名 |
| 拖拽重排 | 不在 live drag 中重建；释放后 compact 编号按位置恢复 |
| 显示/隐藏分屏动作 | 动作和锚点都固定，重新测量后只由 tab 让位 |
| section 左右切换 | 每个页面自己的锚点稳定显示；View 状态与 active 不被锚点影响 |
| 从窄拉回宽 | overflow → compact → roomy 可逆；完整名和空 tooltip 恢复 |

## 7. 验收标准

1. 真实产品的五个 section 底栏均显示正确的模式图标与中文名称；底栏高度仍为 28px。
2. 相同 bar 宽度下，加入锚点后的 tab budget 恰好比无锚点少
   `anchor measured width + one layout spacing`，不是硬编码近似值。
3. 既有 roomy / compact / overflow、rename、reorder、current protection、menu、
   `+` cap、split reserve 测试全部保持通过，不为锚点改写期望语义。
4. 新测试证明：锚点可让同一组 tab 较早进入 compact/overflow，但不会改变隐藏顺序、
   current index、manager active 或 `switch_requested`。
5. 在 12-View 窄状态下，当前 View 12 仍显示编号 `12`，其余按现有尾部规则进入
   `»N`；菜单仍列出全部完整名称。
6. macOS 前台截图检查宽 / 中 / 窄三档：锚点与 tab 垂直对齐，无裁切、无新增灰底、
   无滚动箭头抢占固定动作、无底栏增高。
7. 颜色关闭或难以分辨时，仍可仅凭图标和文字识别 section；键盘焦点顺序不增加一站。

## 8. 非目标

- 不修改 View 默认名 `View N`，不自动给每个 section 生成不同 View 名。
- 不改变 View 色板、颜色持久化或颜色选择器。
- 不重写 `roomy → compact → overflow`，不引入“相邻优先”算法。
- 不改变时域 12 / 分析 6 的 manager 上限。
- 不增加点击锚点切 section、锚点菜单、状态栏或 breadcrumb。
- 不把探索 HTML 修成实现规格；真实 Qt 界面和本 spec 才是验收源。
- 本变更没有新增用户手势，因此不需要改 `ui/hints.py` / `ui/quickref.py`；现有
  「窄窗口只剩编号、`»` 切换收纳 View」说明仍准确。

## 9. 回退

删除 `section` 参数的两个产品传参、锚点 widget/QSS 以及预算中的锚点 reserve，即可
完整回到现状。没有 schema、项目文件或 QSettings 迁移。
