# 时域 View 标签栏扩容至 12（紧凑密度 + 溢出菜单）

- **日期**：2026-07-16
- **状态**：已批准，待实现
- **方案稿**：https://claude.ai/code/artifact/b04fe879-5ec2-4924-9909-91ba41ba6797
- **决策**：方案 B + C（紧凑密度打底 + 溢出菜单兜底）

---

## 1. 问题

用户诉求是「时域 View 从 6 个放开到 10 个以上」。但直接把 `MAX_VIEWS` 改成 10 会立刻暴露三个问题：

### 1.1 标签栏横向溢出（核心）

时域 View 是**底部标签页**，一次只渲染一个画布——所以放开数量**不会**让图表垂直堆叠。用户说的「下方堆积」是那条 28px 高标签条的横向拥挤。

标签栏行结构（`mf4_analyzer/ui/view_tabbar.py:72-110`，`QHBoxLayout`）：

```
[_tabs (固定宽)] [+ 24px] [addStretch(1)] [_split_chip] [_split_clear "✕ 取消合并"]
```

`_sync_tabbar_width()`（`view_tabbar.py:189-202`）把栏宽钉死成自然宽度：

```python
self._tabs.setFixedWidth(max(1, self._tabs.sizeHint().width()))
```

这一行是载荷性的 bug：`setUsesScrollButtons(True)` 早在 `view_tabbar.py:81` 就配好了，但 `setFixedWidth` 让 Qt 认为永远没有溢出，滚动按钮因此从不出现。标签越多，`_tabs` 越宽，`addStretch(1)` 先被吸收到 0，然后 `+` 和「取消合并」被挤出右边缘——功能仍在，但点不到。

### 1.2 上限是四个 section 共享的

`MAX_VIEWS = 6`（`mf4_analyzer/ui/view_state.py:15`）是模块常量，而 `ViewManager` 被复用：`chart_stack/stack.py:127-131` 用同一个类建了 `fft`、`fft_time`、`order` 三个 manager。**改常量 = 四个 section 一起放开**，不符合诉求。

### 1.3 调色板只有 6 色

`_PALETTE`（`view_state.py:16`）恰好 6 个颜色，`_make()`（`view_state.py:112`）做 `_PALETTE[idx % len(_PALETTE)]`。第 7 个 View 起静默复用第 1 个的颜色，标签色点与拆分半点失去区分度。

---

## 2. 决策

**紧凑密度 + 溢出菜单。** 10 个以内全部平铺可见（零点击），超出部分优雅降级进 `»` 菜单，`+` 与右侧动作在任何数量下都不参与压缩。

单独看这两个都不够：

- **紧凑密度**在 10 个时刚好平铺得下、零点击，但 14 个必崩——是断崖不是降级。
- **溢出菜单**永远不崩，但把标签变成二等公民，切换要两步。

合起来互补。这也是 VS Code / Chrome 的成熟模式，用户有肌肉记忆。

### 已排除

| 方案 | 排除理由 |
| --- | --- |
| 只改 `MAX_VIEWS = 10` | 这是基线不是方案——正是用户看到的「堆积」 |
| 纯原生滚动箭头 | 一次只看得到一半标签，藏起来的 View 失去可发现性；单独用体验平庸（但它的地基是必需的，见 T3） |
| 双行换行 | 吃掉 24px 图表垂直空间（时域波形最缺高度）；`QTabBar` 不原生支持换行，须重写 FlowLayout，要绕开 §5.1 的闪退 guard，风险不抵收益 |
| 下拉选择器替代标签条 | 彻底放弃横向总览与一键切换；时域分析的核心动作就是来回切 View，退化不可接受 |
| 合并成叠加曲线 | 是好建议，但属于另一个功能（量纲不同需双 Y 轴或归一化），不能替代「就是想要 10 个独立 View」的诉求 |

---

## 3. 实现任务

四步独立可测，可分 PR 落。

### T1 — 解耦上限

把 `MAX_VIEWS` 从模块常量改为 `ViewManager` 的构造参数。

- `view_state.py:15` — 保留 `MAX_VIEWS = 6` 作为默认值（向后兼容），新增 `ViewManager(max_views: int = MAX_VIEWS)`。
- `view_state.py:121` `new_view()` 与 `view_state.py:152` `duplicate()` 的 guard 改读实例属性，不再读模块常量。
- `mf4_analyzer/ui/main_window/window.py:229` — 时域 manager（`ViewManager(self)`）传 `max_views=12`。**这是唯一需要传参的构造点。**
- `chart_stack/stack.py:128-130` 的 `fft` / `fft_time` / `order` 三个 manager 保持默认 6 = 不传参 = **本次零改动,不要碰这个文件**。
- `ViewManager.__init__` 现签名为 `(self, parent=None, state_factory=None)`,已有调用点用位置参数传 `parent`(`ViewManager(self)`)。新参数必须放在末尾或设为 keyword-only,勿破坏现有位置参数。
- `MAX_VIEWS = 6` **保留**为模块常量作兼容默认值——`view_tabbar.py:25` 和多个测试 import 它,不可删。
- `view_tabbar.py:228` `_update_plus_state()` — 改读 manager 的实例上限。
- `ui_kit/style.qss:2189-2196` — 注释里硬写的「(6)」要改，别留下会骗人的注释。

**验收**：时域能建到 12 个 View，第 13 次 `new_view()` 返回 `-1` 且 `+` 置灰；FFT / 阶次 section 仍在第 7 次就置灰。

### T2 — 扩 `_PALETTE` 到 12 色

取模逻辑不变，只加颜色。现有 6 色是 Open Color 的 blue-6 / orange-8 / green-8 / grape-8 / red-8 / cyan-7，补的 6 个沿用同族：

```python
_PALETTE = [
    "#2d7ff9", "#e8590c", "#2f9e44", "#9c36b5", "#e03131", "#1098ad",
    "#f08c00", "#c2255c", "#5c940d", "#5f3dc4", "#0ca678", "#495057",
]
```

**前 6 个的顺序与取值必须原样不动**——否则已存档项目里 View 1-6 的 `tab_color` 会与新建的不一致。

**验收**：12 个 View 的 `tab_color` 两两不同；`duplicate()` 与拆分半点自动受益；已有项目文件 round-trip 后颜色不变。

### T3 — 拆掉 `setFixedWidth` 这颗钉子

**这是所有方案的公共地基，也是唯一必改的一处。**

`_sync_tabbar_width()`（`view_tabbar.py:189-202`）改成把可用宽度钳到 `setMaximumWidth`，让已配置的 `setUsesScrollButtons`（`:81`）真正生效。

- 宽度上限 = 该行可用宽度 −（`+` 按钮 + 右侧动作区 + 间距）的实测宽度，不是硬编码常量。
- `setMovable(True)`（`:79`）的拖拽排序必须保留。
- 见 §5.1 的闪退 guard。

**验收**：14 个 View 时 `+` 与「取消合并」仍在可视区内且可点击；窗口收窄时标签区先压缩、右侧动作最后才让位。

### T4 — 紧凑密度 + 溢出菜单

- **密度降档**：标签宽度随数量自适应。宽松态维持现值（`style.qss:2124-2135`：`min-width: 58px; padding: 0 12px`）；紧凑态收到 `min-width: 30px; padding: 0 5px`，只留色点 + 序号，**全名进 tooltip**（不能让名字彻底无从获取）。
- **溢出菜单**：密度降到底仍放不下时，尾部标签收进 `»` 菜单，菜单项带色点 + 全名 + 当前选中态。按钮上带溢出计数。**必须用 `setTabVisible` 隐藏,不准用 `removeTab`——见 §5.5,这是硬约束。**
- `+` 与右侧动作区固定，永不参与压缩。

**验收**：真机渲染下 10 个 View 全部平铺可见；20 个时 `»` 菜单出现且计数正确、右侧动作存活；从菜单选中溢出 View 后该 View 切换成功。

---

## 4. 不做什么

- 不动 `_ChartCard` 的构成与高度（`chart_stack/cards.py` 全弹性，无 `setMinimumHeight`，不是问题源）。
- 不动 X 轴联动。时域刻意不用 `setXLink`，改用 `_propagate_xlim_to_siblings` 显式传播（理由见 `pg_canvas/canvas.py:696-703` 与 `:2415-2419`：linked-view 的屏幕几何插值会产生逐子图偏移，分析类应用要求精确）。**别顺手「优化」成 `setXLink`。**
- 不动拆分/合并（`enter_split`，最多 2 窗格）。
- 不引入图表网格平铺——View 是标签页，不是堆叠图表。

---

## 5. 风险

### 5.1 `tabMoved` 拖拽中重建标签栏 = 闪退

`view_tabbar.py:162-171` 记录了一个已修复的 use-after-free：在活跃的 `tabMoved` 拖拽里重建标签栏会崩，由 `self._reordering` guard 拦住。

**T3 / T4 任何触碰宽度或重建路径的改动都必须原样保留这个 guard**，并验证拖拽排序时不复现闪退。

### 5.2 12 色是可辨性天花板

超过 10 个之后颜色只能当辅助线索。这是接受的取舍——真正的区分靠标签名，所以紧凑态保留 tooltip 是硬要求（T4）。

### 5.3 尺寸建模需以真机为准

方案稿按 QSS `min-width: 58px` 建模，但 `view_tabbar.py` 的注释记录实测约 49px/tab（差异来自默认视图名长度）。**密度档位的阈值必须按真机渲染实测定，不能抄方案稿里的像素值。**

### 5.4 UI 结论须验真机渲染

按 CLAUDE.md 的 gotcha：「属性设上了 + 单测过」不等于修好了。T3 / T4 的验收要有真实渲染证据（截图或实测几何），不能只靠单测。

### 5.5 溢出菜单不得用 `removeTab`（严重性最高，规划期补录）

`view_tabbar.py` 有 **6 处**依赖「QTabBar 第 i 个 tab ≡ `manager.views[i]`」这条索引恒等：

| 位置 | 依赖方式 |
| --- | --- |
| `_on_current_changed` | `switch_requested.emit(idx)` |
| `_on_tab_moved` | `reorder_requested.emit(from_idx, to_idx)` |
| `_refresh_tab_swatches` | `count = min(self._tabs.count(), len(self._manager.views))` |
| `_set_current_index` | `self._manager.active` 直接当 tab 索引 |
| `_begin_inline_rename` | `self._tabs.tabRect(idx)` |
| `_on_context_menu` | `tabAt(pos)` 的 idx 直接当 view 索引发出 |

用 `removeTab` 把尾部标签收进 `»` 菜单会让这 6 处**全部静默错位**——切错 View、重命名错 View、拖拽排序错位，且不会抛异常。

**约束**：用 `QTabBar.setTabVisible`（Qt 5.15+）隐藏而非移除，保持索引恒等。规划期已实测运行环境为 **Qt 5.15.2 / PyQt 5.15.11，该 API 可用**。

若实测发现 `setTabVisible` 不可行 → **FLAG 上报重新决策溢出机制**，不得改用 `removeTab` 后自行重排这 6 处索引映射。
