# 代码评审报告 — 时域 View 标签切换 P1

- **评审对象**:codex 在分支 `docs/timedomain-view-tabs-plan` 上完成的实现(工作区未提交)
- **对应计划**:`docs/superpowers/plans/2026-06-04-timedomain-view-tabs.md`
- **评审范围**:里程碑 **P1(Task 1–7)** —— 标签栏 + 单画布切换
- **评审日期**:2026-06-04
- **评审方式**:逐文件读实现 + 核对所引用仓库 API 真实性 + 跑测试 + 红线项专项核查(**未修改任何代码**)

---

## 结论:**P1 通过(APPROVED)**

P1 的 7 个 Task 全部落地,逻辑正确、测试扎实,且在多个点上**比计划更稳健**。未发现 P1 级别的阻断性缺陷。

但有两件**收尾事项**需要在"整个特性完成"前处理(详见 §5):
1. 计划要求的**人工/视觉验真**(活画布、macOS 真机渲染、改名/右键/拖动/改色交互)尚无证据,目前只有 headless 测试。
2. **P2 已部分落地且与 P1 交织**(Task 8 + Task 9 前 4 步在树里),但 **Task 9 Step 5 聚焦路由未做** —— 需明确是补完还是标 WIP。

---

## 1. 交付完整性(Task 1–7)

| Task | 内容 | 状态 | 证据 |
|---|---|---|---|
| 1 | `ViewState` 数据类 + JSON 往返 | ✅ | `view_state.py:22-93`;`test_view_state.py` |
| 2 | `ViewManager` 列表逻辑(6 上限) | ✅ | `view_state.py:96-210`;`test_view_manager.py` |
| 3 | 通道 widget setter + 画布屏幕范围读写 | ✅ | `widgets/__init__.py:319-379`、`file_navigator.py:234-242`、`pg_canvases.py` 新增 4 方法;`test_channel_widget_setters.py`、`test_pg_timedomain_canvas.py` 新增 3 例 |
| 4 | `ViewCaptureBridge` 抓取/写回 | ✅ | `view_bridge.py`;`test_view_bridge.py` |
| 5 | `ViewTabBar` Excel 标签栏 | ✅ | `view_tabbar.py`;`test_view_tabbar.py` |
| 6 | 标签栏插进 `TimeChartCard` + `ChartStack` 接口 | ✅ | `chart_stack.py:1248-1252`、`1432-1483`;`test_view_tabbar_mount.py` |
| 7 | `MainWindow` 编排切换 | ✅ | `main_window.py:208-210`、`338-345`、`410-596`;`test_view_switch_integration.py` |

**测试实测**:`QT_QPA_PLATFORM=offscreen pytest`(9 个 view 相关文件)→ **66 passed in 3.23s**。

端到端测试 `test_switch_view_restores_screen_snapshot_state` 用**真实 MainWindow + 真实加载 CSV**,逐项断言 checked / plot_mode / cursor_mode / overlay_primary / 时间范围开关与值 / X 轴模式(time↔channel)/ 自定义 X fid·ch·label / 刻度密度 / xlim / ylims 全部往返恢复 —— 屏幕状态快照的验收范围被真实覆盖。

---

## 2. 关键正确性核查(逐项过关)

- **引用的仓库 API 真实存在**:`_restore_view_axis_opts` 用到的 `inspector.top` 控件与方法(`set_range_values`/`set_xaxis_mode`/`range_values`/`range_enabled`/`tick_density`/`xaxis_label`/`_update_range_rows_visible`/`_update_xaxis_channel_row_visible`/`spin_start`/`spin_end`/`chk_range`/`combo_xaxis`/`_combo_xaxis_ch`/`edit_xlabel`/`spin_xt`/`spin_yt`)全部存在于 `inspector_sections.py`;`_refresh_xaxis_candidates`/`_on_cursor_mode_changed`/`set_tick_density`/`invalidate_envelope_cache`/`_capture_primary_xlim`/`_restore_primary_xlim` 均存在。**单测用假对象,但真机入口已核对真实存在,不会运行时 AttributeError。**
- **同名方法重复定义红线(memory `project-ui-files-structural-corruption`)未被触碰**:`main_window.py`/`chart_stack.py`/`widgets/__init__.py`/`pg_canvases.py` 经检查无"同类内重复定义"。`plot_mode`/`set_plot_mode`/`cursor_mode`/`set_cursor_mode` 各出现两次,但分别落在 `TimeChartCard`(`chart_stack.py:1276-1292`)与 `ChartStack`(`chart_stack.py:1491-1500`)两个不同类(ChartStack 委托 card),非重复。
- **cursor 同步路径安全**:`apply_view` 在 signals blocked 状态下设 cursor mode,故另调 `_sync_canvas_cursor_mode` → `MainWindow._on_cursor_mode_changed`(`main_window.py:608-610`),后者只调 `canvas_time.set_cursor_visible`/`set_dual_cursor_mode`,**不触发 plot_time、不回调 chart_stack,无重入**。
- **切换前必抓取**:所有会改变屏幕状态的转移(`_switch_view`/`_on_view_new`/`_on_view_delete`/`_on_view_duplicate`/`_on_view_split`)入口都先 `_capture_current_view()`;rename/color/reorder 不改屏幕状态故不抓取 —— 设计自洽。
- **重入护栏**:`_applying_view` 标志在 apply/restore 期间置位,`_sync_time_range_inputs_from_visible_xlim`(`main_window.py:725-727`)据此提前返回,避免重绘回写污染刚恢复的时间范围控件。

---

## 3. 相对计划的偏差(均为**改进**,非回退)

1. **ViewState 的 JSON key**:计划用 `\t` 作 `(fid,ch)`↔字符串分隔符;codex 改用 `json.dumps([fid, ch])`(`view_state.py:69-75`)。更稳健 —— 通道名含 tab/特殊字符也不会串 key。
2. **画布 ylims 的 key(实质修了一个潜在 bug)**:计划把 `ylims` 按 `channel_label` 存,**两个文件同名通道会撞 key**。codex 新增独立映射 `_channel_view_state_lines`,key = `json.dumps([data_id, name])`(`pg_canvases.py` `_view_state_channel_key`),与 legacy `_channel_lines` 分离,互不影响 hover/选择/options 旧路径。并有专测 `test_visible_ylims_distinguish_duplicate_display_names` 验证去碰撞。
3. **ViewManager 防御**:新增 `_is_valid_index` 全面校验;`set_active` 对 `idx==active` 短路;`delete_view`/`reorder` 正确重算 `split_with` 索引;`set_split` 校验自身/越界。均比计划版本严谨。
4. **ViewTabBar**:用内嵌 `QLineEdit` 改名(替代计划示例里的 `QInputDialog`,符合 spec 行文),Escape 取消 / FocusOut·Return 提交路径清晰且防重复 emit(`view_tabbar.py:142-164`);拖动重排后用 `QTimer.singleShot` 抑制紧随的一次误 `currentChanged`(`:195-207`);标签带颜色色块图标 + tooltip。
5. **DRY**:`main_window._restore_checked_channels` 已按计划改为一行委托 `set_checked_channels`;`plot_time` 抽出 `_plot_time_on_canvas(canvas, update_primary_ui)` 复用(`main_window.py:1202+`)。

---

## 4. 代码质量评价

**优点**
- 关注点分离干净:`view_state`(纯数据,无 Qt 依赖于 ViewState 部分)/ `view_bridge`(唯一跨 widget 读写处)/ `view_tabbar`(只发意图信号,不碰 manager)三层边界清晰,与 spec §4 一致。
- 防御式编程到位:大量 `getattr(..., None)` + `callable()` 兜底、`try/except` 跳过缺失通道、signals 阻断用 contextmanager 收口(`view_bridge.py:142-153`)。
- 测试金字塔合理:纯逻辑层(state/manager)、widget 层(setter/tabbar)、画布层(range 读写)、端到端(真实窗口往返)各层都有,且端到端断言密度高。

**可改进(均非阻断)**
- `view_bridge.py` 里 `_capture_colors` 有两条分支(navigator 有/无 `get_channel_colors`),后一分支在当前接线下走不到(navigator 已实现 getter)—— 是为健壮预留的死路径,可接受但略冗余。

---

## 5. 需处理的事项(按优先级)

### 🔴 P0 — 人工/视觉验真缺失(计划 Task 7 Step 5 + memory `verify-ui-visually`)
当前全部为 headless/offscreen 测试。`test_visible_xlim_restore_updates_visible_bottom_axis_numbers` 已在画布层检查"恢复 xlim 后底轴刻度数字真的变了",这点不错;但计划明确要求的**真机验证**仍无证据:①切回是**可缩放的活画布**;②macOS 原生渲染下标签栏/色块/菜单外观;③双击改名、右键菜单、拖动排序、改色在真窗口里逐一生效并**截图留档**。**建议:跑一遍 `python "MF4 Data Analyzer V1.py"` 手动验收并留图,再认定 P1 整体完成。**

### 🟠 P1 — P2 半落地且与 P1 交织,边界需澄清
- 已在树里:Task 8 分屏容器(`chart_stack.py` `enter_split`/`exit_split`/`secondary_canvas`/`split_active`)、Task 9 前 4 步(`main_window.py` `_on_view_split`/`_render_view_into` + `test_split_routing.py`)。
- **未做:Task 9 Step 5 聚焦路由** —— 无 `focused_canvas()`/`focused_card()`,点击副栏不切聚焦、无高亮,`plot_time`/`_ch_changed` 仍写死主画布。**后果:并排时副栏是静态快照,对副栏缩放/勾选不会路由过去。**
- 另:`_render_view_into` 为复用 `_plot_time_on_canvas` 会先把对比 view 写进全局 widget、画完再用 `_apply_active_view` 整窗恢复 —— **进入并排有一次"双重整窗重绘"**,功能对但偏重,留待 P2 评审优化。
- **建议:** 若本轮目标只是"P1 complete",把 P2 这部分要么补完(尤其聚焦路由),要么在 commit/计划里显式标 WIP,避免"看起来并排能用其实交互不路由"的误解。

### 🟡 P2 — 轻微(非缺陷,可不改)
- `delete_view` 在 `idx < old_active`(删活动标签左侧)时仍 emit `active_changed` → 对**未变的**活动 view 触发一次整窗 `plot_time`(轻微闪烁/开销)。`view_state.py:145`。
- `_switch_view` 显式 `set_split(None)` 与 `set_active` 内部的清 split 逻辑重复一次,无害。
- **设计取舍**:颜色快照只存**已勾选**通道的颜色(`view_bridge.py:_capture_colors` 过滤 checked),未勾选通道的自定义色不进快照。意在避免陈旧色块,P1 可接受。

---

## 附:测试与核查命令
```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/ui/test_view_state.py tests/ui/test_view_manager.py \
  tests/ui/test_channel_widget_setters.py tests/ui/test_view_bridge.py \
  tests/ui/test_view_tabbar.py tests/ui/test_view_tabbar_mount.py \
  tests/ui/test_view_switch_integration.py \
  tests/ui/test_split_container.py tests/ui/test_split_routing.py -q
# → 66 passed in 3.23s
```
