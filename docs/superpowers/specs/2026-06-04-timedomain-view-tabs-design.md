# 时域 View 标签切换 — 设计 Spec

**Date:** 2026-06-04
**Author:** Hang(与 Claude brainstorm)
**Scope:** 在时域(time-domain)图表底部新增 Excel 风格的 **View 标签栏**,把"当前通道组合 + 颜色 + 模式 + 坐标/曲线设置 + 放大缩小后的可见范围"保存为可来回切换的 view(上限 6 个),并支持两个 view **并排对比**。这是**可交互的屏幕状态快照**:切回 view 后重绘成活画布,不是存图片。本 spec 只覆盖时域;FFT / 阶次 / FFT-vs-Time 不在范围内。落盘(project 持久化)不在本期,但数据模型为其预留。

---

## 1. 目标与非目标

**目标**
1. 用户调好一套时域显示(勾选通道、坐标轴、缩放、模式、游标)后,把它存进一个 view。
2. 新建 view 配置另一套组合;像标签页一样来回切换,切回去是**可继续交互的活画布**,不是图片。
3. 标签栏行为对标 Excel 工作表:**重命名、拖动排序、新建、复制、删除、改标签色**。
4. 支持两个 view **左右并排**对比。
5. 上限 **6** 个 view。

**非目标**
- 跨会话持久化 / 落盘(留给未来的 "project" 概念,见 §9)。
- FFT / 阶次 / FFT-vs-Time 的 view(本期只做时域)。
- 2×2 以上的多宫格并排(架构预留,本期只做左右 2 栏)。

---

## 2. 关键决策(来自 brainstorm)

| 决策 | 结论 | 理由 |
|------|------|------|
| 存图片 还是 存配置 | **存配置,重绘出活画布** | 切回去要能继续平移/缩放/改轴;"快照"只是比喻 |
| 重绘性能 | 无忧 | 切 view = 现有 `plot_channels`(勾通道同款管线);数据约 2 万点/通道;`pg_canvases.py` 已有降采样(:1586)+ 视口裁剪 envelope(:19/:3398) |
| 状态存储架构 | **方案 A:`ViewState` 快照 + 重绘** | `ViewState` 纯数据可 JSON 序列化,白送未来 project 落盘;内存省;可单测 |
| 标签位置 | 图表正下方、`Time (s)` 与底部快捷键提示之间,**仅图表列宽** | 用户确认;标签属于图表,不横跨文件树/检查器 |
| 并排 | 独立新功能,**不**复用 `单/双`(那是游标) | 用户澄清 单/双 = 游标 |
| 上限 | 6 | 用户指定 |
| 落盘 | 本期不做 | 用户指定,后续走 project |

---

## 3. 数据模型

新文件 **`mf4_analyzer/ui/view_state.py`**,纯数据 + 纯逻辑,**不 import 任何 Qt widget**(对标 `side_panels.reduce_panel` 范式,可纯单测)。

### 3.1 `ViewState`(`@dataclass`)

| 字段 | 类型 | 含义 |
|------|------|------|
| `name` | `str` | 标签名(默认 `"View N"`) |
| `tab_color` | `str` | 标签色 hex |
| `checked` | `list[tuple[str, str]]` | 勾选通道 `(fid, channel)` 有序列表 |
| `colors` | `dict[tuple[str,str], str]` | 每通道颜色 hex |
| `plot_mode` | `str` | `'subplot'` \| `'overlay'`(对应 分屏/叠加) |
| `cursor_mode` | `str` | `'off'\|'single'\|'dual'`;只保存游标模式,**不保存游标具体位置** |
| `xlim` | `tuple[float,float] \| None` | 共享 X 范围;`None` = 自适应 |
| `ylims` | `dict[str, tuple[float,float]]` | 各轴 Y 范围(subplot 每子图 / overlay 每轴),key 用稳定的轴标识 |
| `overlay_primary` | `tuple[str,str] \| None` | 叠加模式下"设为左轴"的通道;没有指定则为 `None` |
| `axis_opts` | `dict` | 坐标/显示设置快照,至少包含时间范围过滤、自定义 X 轴、X 轴标签、刻度密度 |

- 必须提供 `to_dict()` / `from_dict()`(JSON 友好,为未来 project)。`(fid,ch)` tuple key 在序列化时转成 `"fid\tch"` 字符串。
- `axis_opts` 用开放 dict 容纳坐标/显示设置,但本期必须至少覆盖:
  - `range_filter`: `{"enabled": bool, "start": float, "end": float}`
  - `x_axis`: `{"mode": "time"|"channel", "fid": str|None, "channel": str|None, "label": str}`
  - `tick_density`: `{"x": int, "y": int}`
- 本期验收口径是**屏幕状态快照**:切回后通道/颜色/模式/X 缩放/Y 缩放/坐标设置恢复;不是图片快照,也不保存 cursor 的具体 X 位置或 toolbar back/forward 历史。

### 3.2 `ViewManager`(`QObject`)

持有:`views: list[ViewState]`(1..6)、`active: int`、`split_with: int | None`。

**信号**
```python
views_changed = pyqtSignal()        # 列表结构变了(增删/改名/排序/改色)
active_changed = pyqtSignal(int)     # 活动 view 变了
split_changed = pyqtSignal(object)   # 并排对象变了(int 或 None)
```

**方法**(均为纯状态操作,不碰 widget)
- `new_view() -> int`:满 6 个时不动并返回 -1。
- `delete_view(idx)`:剩 1 个时不允许删空。
- `duplicate(idx) -> int`:深拷贝插到其后,名字加"副本";满 6 不动。
- `rename(idx, name)`:空名归一为 `"未命名"`。
- `set_color(idx, hex)`。
- `reorder(from_idx, to_idx)`。
- `set_active(idx)`:同时清 `split_with`(切换即退出并排)。
- `set_split(idx | None)`:`idx == active` 视为无效。
- `get(idx) -> ViewState`。

> `ViewManager` 不负责"抓取/写回界面",那是 bridge 的事。它只管 view 列表这个**单一真相源**。

---

## 4. 组件边界

| 组件 | 文件 | 职责 | 依赖 | 测试 |
|------|------|------|------|------|
| `ViewState` / `ViewManager` | 新 `ui/view_state.py` | 数据 + 列表逻辑 | 无 Qt widget | 纯单测 |
| `ViewCaptureBridge` | 新 `ui/view_bridge.py` | `capture(...) -> ViewState`、`apply(state, ...)`;**唯一**懂各 widget 内部读写的地方 | navigator / TimeChartCard / canvas | offscreen 往返测 |
| `ViewTabBar` | 新 `ui/view_tabbar.py` | Excel 标签栏 UI,由 `ViewManager` 状态渲染,只**发信号**不直接改状态 | 仅 Qt | qtbot 信号测 |
| 接线 | 改 `ui/main_window.py` + `ui/chart_stack.py` | 把 tab bar ↔ manager ↔ bridge 串起来 | — | 集成测 |

每个单元都能独立回答"做什么 / 怎么用 / 依赖谁",边界清晰。

---

## 5. 切换数据流

点标签 `j`(`j != active`):
1. `state = bridge.capture(navigator, time_card, canvas)` → 写回 `manager.get(active)`(**自动存,无手动保存按钮**)。
2. `manager.set_active(j)`。
3. `bridge.apply(manager.get(j), navigator, time_card, canvas)`:
   - `blockSignals(True)` 防止写回过程触发重绘风暴;
   - `navigator.set_checked_channels(state.checked)` + 写回颜色;
   - `time_card.set_plot_mode(state.plot_mode)`、`set_cursor_mode(state.cursor_mode)`;
   - `canvas.plot_channels(ch_list, mode)` 重绘;
   - 恢复 `xlim`(走 `plot_channels_preserving_xlim` / `PgAxisHandle.set_xlim`)、`ylims`、`overlay_primary`、`axis_opts`;
   - `blockSignals(False)`。
4. `ViewTabBar` 收 `active_changed` → 刷新高亮。

新建/删除/复制/改名/拖动/改色:只调 `manager.*` → `views_changed` → tab bar 重渲染;其中"新建/复制/删除"会顺带 `set_active` 到合适项并触发一次 `capture(旧) + apply(新)`。

**缺失通道**:`apply` 时 `(fid,ch)` 已不存在则跳过该通道,其余照常,view 不报错。

---

## 6. 并排(P2)

- `manager.set_split(k)` 后,时域画布区从单画布变成 **`QSplitter` 两栏**:左 = `active`,右 = `k`。
- 右栏**懒创建**第 2 个 `TimeDomainCanvasPG` 实例;`bridge.apply(views[k], ...)` 渲染进去。数据数组共享 `file_data`,只多一组 pyqtgraph item。
- **聚焦栏**:点击某栏使其聚焦(高亮边框);顶部 `分屏/叠加/游标`、右侧图表设置、左侧通道勾选都作用于**聚焦栏对应的 view**。
- 退出并排:再切任意标签即回单画布(`set_active` 清 `split_with`),或并排按钮再点一次。
- MVP 只做左右 2 栏;`SplitContainer` 接口允许以后扩 2×2。

---

## 7. UI 落点(精确)

| 落点 | 位置 | 动作 |
|------|------|------|
| 标签栏宿主 | `TimeChartCard`(chart_stack.py:1154)布局,`canvas` 与 `self._hint_bar`(chart_stack.py:951)之间 | **新增** `ViewTabBar`;天然只在时域出现 |
| 模式/游标复用 | `plot_mode_changed`(:1159)、`cursor_mode_changed`(:1160)、`set_plot_mode` / `set_cursor_mode` | bridge 直接读写 |
| 通道勾选读 | `FileNavigator.get_checked_channels`(file_navigator.py:231) | 已有,直接用 |
| 通道勾选写 | `FileNavigator` | **需新增** `set_checked_channels(list)`(blockSignals 批量设)+ 颜色读写(颜色在 `MultiFileChannelWidget._colors`) |
| X 范围保留 | `plot_channels_preserving_xlim`(pg_canvases.py:1512)、`PgAxisHandle.get/set_xlim` | 已有,直接用 |
| 序列化范式 | `batch_preset_io.py` 的 JSON save/load | 照搬到 `ViewState.to/from_dict` |

---

## 8. 测试策略

- **单测(Qt-free)**:`ViewManager` 全操作(新建 / 删除到剩 1 不可空 / 满 6 不增 / 复制 / 改名归一 / 拖动排序 / 切换清并排 / set_split 自指无效);`ViewState.to_dict→from_dict` 往返一致。对标 `tests/ui/test_side_panel_reducer.py`。
- **UI 测(offscreen + qtbot)**:`ViewTabBar` 点击/双击改名/右键菜单/拖动各发对的信号且只发一次;`bridge.capture→apply` 往返保真(勾选集、颜色、plot_mode、cursor_mode、xlim、ylims、overlay_primary、axis_opts 一致);切到 FFT 模式标签栏隐藏。对标 `tests/ui/test_side_panel_widgets.py`。
- **视觉验真(强制)**:真机或截图确认 —— 切换后是**活画布**(可平移缩放、双击改轴);并排两栏内容正确、聚焦边框对。不靠"属性设上了 + 单测过"就算修好。

---

## 9. 未来:project 落盘(P3,非本期)

`ViewState` 既是纯数据,project 落盘只需:把 `manager.views` 整体 `to_dict()` → JSON 存进 project 文件;打开时 `from_dict()` 还原 + 逐个 `apply`。无需为此改本期任何结构。

---

## 10. 风险与坑

1. **重复方法定义**:`chart_stack.py` / `main_window.py` 历史上存在同名方法重复、**最后一个生效**的情况(见 memory `project-ui-files-structural-corruption`)。动这两个文件前,**先对要改/要调用的方法去重**,否则改了不生效。
2. **file-keyed 通道失效**:文件移除后 `(fid,ch)` 失效 → `apply` 静默跳过,见 §5。
3. **并排聚焦路由**:sub-toolbar / inspector / navigator 的作用对象必须始终指向聚焦栏,避免误改另一栏。P2 重点测。
4. **自动捕获时机**:任何切换前**必须先 `capture`**,否则丢未保存的坐标范围、曲线设置或缩放状态。
5. **重绘风暴**:`apply` 中批量设勾选必须 `blockSignals`,否则每勾一个触发一次重绘。

---

## 11. 分期

- **P1**:`view_state.py` + `view_bridge.py` + `ViewTabBar` + 接线;切换 / 新建 / 删除 / 改名 / 拖动 / 复制 / 改色(单画布)。
- **P2**:并排(`SplitContainer` + 聚焦路由)。
- **P3(以后)**:project 落盘。
