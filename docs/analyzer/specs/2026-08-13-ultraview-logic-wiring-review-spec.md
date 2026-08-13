# UltraView 逻辑与接线审查（Codex/Cursor 提交链 + 面板按钮语义）

- 日期：2026-08-13
- 状态：REVIEW FINDINGS — 待修复（配套计划见
  `docs/analyzer/plans/2026-08-13-ultraview-logic-wiring-fixes-plan.md`）
- 审查者：Claude（Fable 5），独立于实现方（Codex `PrjBbrosa` / Cursor 协作提交）
- 审查对象：
  - Codex 链：`506e0bd0`（P0 lifecycle/persist/export/help 收口）→ `e5f5a11e`（merge）
    → `576e5da4`（总览改独立面板）→ `50c003e6`（领养后必须显示）
  - Cursor 链：`5e36b27a`（抓已绘时域图 + 独立窗生命周期）→ `c63b633e`
    （停手跟图 + 快照含游标读数）
  - 工作区在途（未提交）：View 栏右侧 UltraView 入口（
    `docs/analyzer/specs/2026-08-13-ultraview-view-rail-dock-spec.md` 的实现，
    含未跟踪 `mf4_analyzer/ui/widgets/ultraview_entry.py`、`tests/ui/test_ultraview_entry.py`）
- 基线：审查时 HEAD `c63b633e`；聚焦套件
  `test_ultraview_page/state/capture/mode_integration/entry + view_tabbar_mount +
  analysis_section_page + toolbar` 共 **227 passed**（offscreen）。下列问题**全部
  没有被现有测试拦住**，其中一条错误行为反而被测试钉成了契约（见 B1）。

## 0. 结论总览

架构骨架是健康的：page 只投影、coordinator 单点变更 Board、独立窗领养/归还对称、
transient-parent 四条路径处理正确、入口迁移实现符合 view-rail-dock 规格。问题集中在
四个层面：

| 组 | 主题 | 数量 | 最高严重度 |
|---|---|---:|---|
| A | 面板按钮/拖放的落点与反馈语义 | 7 | HIGH（独立窗反馈不可见） |
| B | capture/digest/绑定的语义与热路径成本 | 8 | HIGH（hover 线烙进快照；分屏发错像素） |
| C | 第六模式→独立窗迁移的残留双模型 | ~10 处 | MEDIUM（死代码可达） |
| D | 在途入口工作区 | 1 | 低（仅验收状态） |
| E | 生命周期与状态清理 | 4 | MEDIUM（页面影子缓存跨项目滞留） |
| F | 批处理面板化附带 | 1 | HIGH（运行中关主窗无护栏） |

与 Codex 预写的 P1 规格 §1.2「P0 必须先关闭的问题」交集很小：那 6 条大多已在
`5e36b27a`/`c63b633e` 关闭（领养后 setVisible、隐藏窗二次 close 抢页、旧窗
destroyed 抹新句柄、transient-parent 压窗等四个洞已确认修复）；本清单是**新增**
发现，修复应先于 P1 动工。

## A. 面板按钮与拖放语义

### A1 — 空槽点击的落点被丢弃（MEDIUM）

`EmptySlotWidget.add_clicked(slot_id)` 带着被点击的槽位，但
`page.py::_on_empty_slot(_slot_id)` 丢弃参数，走 `_emit_add` →
`add_ref_requested` → `ultraview_state.add_ref` 落到 **first_empty_slot**。

- 触发：`grid_2x2` 下 A、C 两槽为空，用户点击空槽 C 添加 → 卡片出现在 A。
- 契约：点击空槽 X 添加时目标就是 X。空槽的 `replace_slot(slot_id, ref)` 等价于
  「放置到该槽」，page 应改发 `replace_slot_requested(slot_id, section, view_id)`
  （armed 替换流程优先级不变）。
- 位置：`mf4_analyzer/ui/chart_stack/ultraview/page.py:375-380`。

### A2 — 拖放落在网格留白回退到第一槽（MEDIUM）

`BoardGrid.dropEvent` 中 `slot_id_at(pos)` 为 None（BOARD_PADDING 留白、槽间缝）时
回退 `slots[0]`。从库拖一行松手在留白上 → 主槽占用者被顶进托盘。

- 契约：落点不在任何槽内 → 整次 drop 为 no-op（或仅当 Board 无任何卡片时才容错到
  第一空槽）。
- 位置：`mf4_analyzer/ui/chart_stack/ultraview/widgets.py:1290-1302`。

### A3 — armed 替换状态在无关拖放后残留（MEDIUM）

`page.py::_on_ref_dropped` 的 armed 分支只显式处理 library 来源；`kind == "card"`
（卡片互换）与 `kind == "tray"`（托盘放置）会**落穿** armed 分支继续正常流程，
且不清除 `_replacement_ref/_replacement_slot`。之后用户在库里点任意「+」都会被
`_emit_add` 解释为「完成替换」，替换掉一张早已不在意图里的卡。

- 契约：armed 状态下发生任何非 library 完成路径的 Board 变更（swap/place/tray drop）
  时，先 `clear_replacement_arm()` 再执行该变更；armed 只能被「从库选择完成」或
  Esc/再次点击取消。
- 位置：`page.py:422-465`（分支矩阵）、`page.py:467-477`（`_emit_add`）。

### A4 — 无空槽/无选中时的静默无反馈（LOW）

- 托盘「放置」在 `first_empty_slot` 为 None 时静默 return（`page.py:409-413`）；
- 工具栏「添加 View」与空槽点击在库无选中时只把焦点丢给搜索框，无任何提示文案。
- 契约：给出可见反馈（toast 或 hint bar 文案）：「Board 已满：换布局或先移除」/
  「先在左侧 View 库选择一个 View」。

### A5 — 复制/导出反馈渲染在被遮住的主窗口（HIGH，UX）

`coordinator._toast` → `MainWindow.toast` 画在 **Analyzer 主窗底部**
（`window.py:790`）。Board 是独立工具窗（且已清 transient-parent），常态下正好
盖住主窗——用户在 Board 里点「复制整板图 / 复制本卡图像 / 导出 PNG」，成功与失败
提示全部不可见。`choose_and_export_png` 的 `QFileDialog` 父窗口同样是
`self._window`，弹出时会把主窗拉到 Board 之上。

- 契约：sheet 可见时 toast 宿主与文件对话框父窗口都必须是 Board 工具窗
  （page.window()），不可见时才回落主窗。
- 位置：`ultraview_coordinator.py:1010-1024`（对话框父窗）、`:1072-1076`（toast 路由）。

### A6 — 「打开原 View」不把 Analyzer 带到前台（HIGH，UX）

`coordinator.open_source` 只调 `toolbar._set_mode(section)` + 延迟
`_switch_view/_on_analysis_switch`，全程不 `raise_()/activateWindow()` 主窗。
Board 独立窗在前时，点卡片右键/焦点层的「打开原 View」只在**背后**换页，用户
看不到任何发生的事。transient-parent 已被有意清除，系统也不会代为置前。

- 契约：切换完成后显式激活 Analyzer 主窗（`raise_` + `activateWindow`），Board 不关闭。
- 位置：`ultraview_coordinator.py:726-757`。

### A7 — 临时放大被双重触发（LOW）

卡片 `focus_requested` → `page._on_focus` 已本地 `show_focus`，同一信号又转发给
coordinator `_on_focus`，后者再调一次 `page.show_focus`。两次 `show_ref`、两次
setPixmap。无功能损害，但语义上「谁拥有 focus 展示」不清晰——应收敛为单一 owner
（建议 coordinator 只负责 `_store.touch`，展示归 page）。

- 位置：`page.py:393-395` 与 `ultraview_coordinator.py:957-965`。

## B. capture / digest 语义与热路径

### B1 — 单游标 hover 跟随线被烙进快照，且位置进 digest（HIGH）

`hide_transient_overlays` 的门控 `_host_is_dual_cursor` 只在 **dual** 模式隐藏
hover 线；`_cursor_geometry_from_host` 的 single 分支把 hover 线位置读进 digest。
而产品中单游标线**永远是未武装的 hover 跟随线**（`ui/pg_canvas/cursor.py:374-406`：
单模式 33ms 节流跟鼠标，按下武装只在 dual 生效）。`c63b633e` 自带的 plan
（`2026-08-13-ultraview-idle-refresh-cursor-plan.md:51`）明确写「仍藏：hover 跟随
十字（未武装）」——实现与自己的 plan 相悖。

- 触发：Board 开着 + 源画布单游标开启，鼠标扫过画布：每次停顿 hover x 变 →
  digest 变 → 重抓 → 快照带一条停在任意位置的 hover 线；卡片图像与 fresh/stale
  随鼠标位置反复翻动。
- 已被钉错的契约：`tests/ui/test_ultraview_capture.py:570-574` 断言非 dual 时
  cursor line 在 grab 时可见——该测试要随修复一起改。
- 契约：single hover 线属 transient（隐藏、不进 digest）；只有 dual 武装游标的
  几何与读数进快照和 digest。
- 位置：`ultraview_coordinator.py:126-134`、`:196-227`。

### B2 — 每个源信号同步做全量 digest + 全 Board 重投影（HIGH，性能）

`schedule_idle_capture` 在 120ms 防抖**之前**无条件调 `_push_preview(ref)`：
重算 `current_digest_for`（全 payload 构建 + 逐通道 CRC probe + pill 指纹），再经
`page.set_preview/set_ref_status` **各自**触发一次无变更检测的
`_refresh_projection()`——重建全部卡片 view model、`set_grid`、且
`UnplacedTray.set_refs` 会**销毁重建全部 TrayItem**。挂接的源信号包括
`cursor_info`（hover ~30Hz）、`visible_range_changed`、`manual_zoom_changed`。

- 后果：Board 开着悬停源画布 ≈ 30–60 次/秒全 Board 重投影 + 哈希，落在交互热
  路径上，违背仓库「交互成本」纪律；托盘 TrayItem 若在拖拽 `drag.exec_` 嵌套
  事件循环期间被重建，还会撞上本仓库已记录的 zombie-wrapper teardown 崩溃类。
- 契约：`_push_preview` 挪到 idle timeout 之后；`set_preview/set_ref_status` 值
  未变时 no-op 短路；一次事件循环内的多次投影合并为一次。
- 位置：`ultraview_coordinator.py:1985-1996`、`page.py:268-286`、
  `widgets.py:1459-1498`。

### B3 — `digest-changed` 抓图静默丢弃，idle 管线无重试（MEDIUM）

`_publish_grab` 发现 digest 已变时只 warn + return，不重新排队。digest 含 pill
可见性/文本，而 pill 存在不发 hooked 信号的隐藏路径（`stack.py:1339-1350`
`_reposition_pill` 在 currentChanged/resize 时 `setVisible(False)`）。

- 触发：request 与 timer fire 之间 pill 被藏掉 → 本次抓图丢弃且无人再调度 →
  卡片停在 stale，直到用户再碰那个画布。
- 契约：`digest-changed` 丢弃后用**新 digest** 重新入队一次（带上限防振荡）。
- 位置：`ultraview_coordinator.py:1504-1507`。

### B4 — 全局共享单发 idle 计时器饿死其他 ref（MEDIUM）

任何源信号都 restart 同一个 `_idle_timer`；`_idle_pending` 里其他 ref 只能等全局
120ms 静默。持续拖动画布 A 期间，画布 B 已排队的抓图无限推迟。

- 契约：per-ref 去抖（或 timeout 时只清算「已静默满 120ms」的 ref，其余保留）。
- 位置：`ultraview_coordinator.py:1992-1996`。

### B5 — 屏幕可见性/绑定状态混进身份 digest → 误报 stale 且挂死（MEDIUM，两个触发面）

`_cursor_payload` 的几何与 pill 指纹只能从 `_bound_widget_for(ref)` 的**活体
widget** 读，且 `_pill_fingerprint` 显式检查 `pill.isVisible()`。于是 fresh/stale
成了「当前哪页在前台、画布绑给谁」的函数：

- **触发面 1（绑定转移）**：画布按 `id(canvas)` 单绑定，切换 View 后同一画布重绑
  到新 ref，旧 ref 的 `cursor_geometry` 变 `[]`、`pill` 变 None → digest 与捕获时
  不同 → 误标「源已变化」。dual 武装游标的 View 一切走必 stale。
- **触发面 2（模式切换）**：抓图时 pill 可见的卡片，其 captured_digest 含
  `[text, detail]`；用户仅切换模式（时域→FFT）后源页隐藏、pill 指纹变 None →
  卡片翻 stale。且隐藏画布无法重抓（`request_capture` 见 `isVisible()==False`
  直接返回），**stale 徽章挂死**到用户切回该模式为止。
- 契约：与 `markup_revision/visible_pane_count` 一致——捕获成功时把游标几何/pill
  指纹写进 `PresentationRuntimeLedger`；构建 payload 时 widget 不可用（未绑定、
  隐藏）就从 ledger 回读，而不是当作空。fresh/stale 只允许对「源状态真实变化」
  作出反应。
- 位置：`ultraview_coordinator.py:1381-1423`、`ultraview_runtime.py`。

### B6 — `id(result)` 判结果身份，id 复用可致 FRESH 假阳性（LOW-MEDIUM）

`notify_result_stored` 用 `id(result)` 与上次比较来决定是否 bump generation，
且不持有对象引用。旧结果被 GC 后新结果分配到同一地址（CPython 常见）→
generation 不 bump → digest 不变 → `_has_current_preview` 判「无需重抓」，
卡片挂 FRESH 徽标但像素是旧数据。

- 契约：无条件 bump，或以 `weakref + 计数` 判身份（对不可 weakref 的对象回退
  无条件 bump）。
- 位置：`ultraview_coordinator.py:471-484`。

### B7 — CRC 采样探针的 FRESH 假阳性面未被文档承认（LOW，登记即可）

`_stable_source_revision` 丢掉 ndarray id 后，同长同 dtype、linspace 锚定 probe
点恰好相同的数据替换会被判「未变」：卡片 FRESH 但像素为旧数据，且跳过重抓。
lesson `ultraview-time-capture-ink-and-stable-digest.md` 记录了取舍但未提这一面。
不必改实现，把误差面写进 lesson 与本 spec 即可。

### B8 — 时域分屏下「加入总览」可能发布错误 View 的像素（HIGH）

`add_from_source_tab` 用 `_active_ref("time")`（= `view_manager.active`）取 ref，
却用 `_visible_widget_for("time")`（= `focused_canvas()`，跟随最后点击的 pane）取
画布。pane 聚焦只改 `_view_focus.focused`、不改 `manager.active`
（`window.py:3098`），两者可分叉。

- 触发：时域分屏 → 点副栏聚焦 → 右键**主栏（active）**View 标签「加入总览」：
  副栏画布被 `bind_canvas` 绑到主栏 ref，**伙伴 View 的像素**发布成 active View
  的卡片；且覆盖了原本正确的 secondary→partner 绑定，后续 idle 重抓持续发错图。
- 契约：ref 与画布必须由同一映射解析——沿用 `_capture_visible_time_refs` 的
  primary↔active / secondary↔partner 对应关系；或先按 ref 反查其所属 pane 的
  画布，取不到就不绑。
- 位置：`ultraview_coordinator.py:697-703`、`:1756-1764`。

## C. 第六模式 → 独立窗迁移的残留双模型

`576e5da4` 把总览改成独立面板后，「mode=ultraview」时代的接线仍大量在场，形成
两套并存的心智模型。全部为死代码或几乎不可达路径，但正是本次审查感受到「逻辑和
接线混乱」的主要来源：

| 残留 | 位置 | 现状 |
|---|---|---|
| `_on_mode_changed` 的 `mode == "ultraview"` / `old_mode == "ultraview"` 分支 | `window.py:1638-1664` | 不可达（toolbar 已无该 mode 可见入口） |
| `enter_ultraview()/leave_ultraview()` | `ultraview_coordinator.py:640-656` | enter 只剩 refresh_page；leave 的 `_left_snapshot` 恢复分支**永远不会执行**（全库无赋值点） |
| `_left_snapshot` | coordinator 多处置 None | 只写 None 的死状态 |
| `chart_stack.set_mode('ultraview')` 仍可达 | `stack.py:885` 起 | 若页面已被 sheet 领养，栈会显示空页 |
| `hint_bar_for_mode('ultraview')` | `stack.py:870` | 依赖页面在栈内的旧假设 |
| `_copy_card_image` 的 `current_mode() == 'ultraview'` 早退 | `stack.py:1184` | 不可达 |
| `Inspector.UltraViewContextual` + coordinator `_connect_inspector` | `inspector.py:215-220,279`、coordinator `:604-621` | 12 个信号仍全量接线、`_sync_inspector` 每次 board 变更都跑；但页面居于工具窗时**有意早退**——当前唯一形态下这块 UI 永不更新，纯死面白耗 |
| `saved_mode` 的 ultraview 分支 | `_project_io_mixin.py:1629-1630` | 项目文件不会再产出该值（project_io 已消毒 `current_mode`） |
| 隐藏 `btn_mode_ultraview` | `toolbar.py` | view-rail-dock spec §7.4 已声明「有证据后单独清理」 |
| page 对外发射但无人连接的 `locate_ref_requested` / 页级 `rebind_arm_requested` | `page.py` 信号表 | 页面内部已自处理，仅无害残留，登记即可 |

- 契约：收敛为单一「独立工具窗」模型。删 `_on_mode_changed` ultraview 分支、
  `enter/leave_ultraview`、`_left_snapshot`；`chart_stack.set_mode` 拒绝
  `'ultraview'`（或断言）；Inspector 的 UltraViewContextual 要么整体移除、要么
  显式改造为工具窗内面板——不允许保留「连着信号但永不刷新」的中间态。
  `btn_mode_ultraview` 随本次一并清理（本 spec 即为其「证据」）。
- 附带治理项：`open_source` 跨对象调私有 `toolbar._set_mode` /
  `window._switch_view` / `window._on_analysis_switch`（`coordinator:726-757`），
  收敛为 MainWindow 暴露的一个具名公共入口（如
  `window.navigate_to_view(section, view_id)`），与 A6 的置前修复同点落地。
- coordinator `attach()` 以 `_page_hooks` 非空作幂等门（`:552-575`）：若首次
  attach 时 page 尚不存在而 stack 存在，stack 钩子入表后 page 信号**永远不会补
  连**。当前构造顺序不触发，但该幂等门应按「page 钩子」与「stack 钩子」分别判断。

## D. 在途入口工作区（view-rail-dock）

未提交实现整体符合其 spec：单一 `open_ultraview_requested` 信号、五入口共用
bound-method 接线（无新增 lambda）、fitter 用 live hints 无固定断点、时域 rail 随
`_time_bottom_dock` 按模式隐藏（无双入口）、Toolbar 移除干净。唯一事项：

- **D1**：spec/plan 自标 `UVR-A15 真实 macOS 前台 UNVERIFIED`。合入前必须完成
  真机前台验收（宽/窄、合并、双 pane、上限溢出、重复打开置前），并把证据登记进
  plan；这与仓库「验真机渲染」Gotcha 一致，offscreen 227 绿不能替代。

## E. 生命周期与状态清理

### E1 — 页面级预览影子缓存永不清理（MEDIUM）

coordinator 的 reset/restore/shutdown 只清自己的 `PreviewStore`；`UltraViewPage`
自己的 `_previews`/`_statuses`/`_ref_exists`（持有 QImage）**跨项目累积**
（`page.py:88, 268-286`），且 `_status_for/_chrome_value/_axis_for`
（`page.py:499-552`）以它为渲染数据源——与「store 已清空」分叉成两份事实。

- 触发：换项目 / close_all 后内存滞留；重开同一项目（view_id 相同）时旧项目的
  像素可从页面侧复活，绕过「重开默认 missing」的 P0 契约。
- 契约：page 提供 `clear_runtime_caches()`，coordinator 在
  `reset_project_state/restore_project_state/shutdown` 中调用。

### E2 — `restore_project_state` 不复位 sheet 会话（LOW）

`reset_project_state` 会调 `page.reset_sheet_session()`，`restore_project_state`
（打开项目）不调（`ultraview_coordinator.py:520-539` vs `:1186-1198`）。总览窗
开着且焦点层放大某卡片时打开另一个 `.tlproj`，焦点层继续显示旧项目快照。

- 契约：restore 与 reset 的会话复位行为一致。

### E3 — restore 警告双重记录（LOW）

`_project_io_mixin.py:1872-1874` 与 `ultraview_coordinator.py:537-538` 对同一批
warnings 各 `logger.warning` 一次。收敛为单点（建议留 coordinator 侧）。

### E4 — `id(canvas)` 键控的绑定/钩子表不剔除死条目（LOW-MEDIUM）

`_bindings`/`_hooked_ids` 以 `id(canvas)` 为键（`ultraview_coordinator.py:383-389`、
`_ensure_stability_hooks`），死画布条目不主动剔除。分屏副画布会创建/销毁，CPython
id 复用时新画布命中 `_hooked_ids` **静默失去** stability/idle 钩子，长会话后该
pane 的预览停更。

- 契约：hook 时挂 `destroyed` 剔除对应条目，或改用 `weakref` 键控；同一修法
  覆盖 `_unstable` 表。

## F. 批处理面板化附带（`576e5da4` 非模态化引入）

### F1 — 批处理运行中关闭主窗无护栏（HIGH）

`576e5da4` 把 BatchSheet 改为非模态工具窗后，`MainWindow.closeEvent`
（`window.py:4680-4691`）对 `_batch_sheet` 调 `dlg.close()` 后**不检查结果**就
继续 teardown。BatchSheet 运行中的 closeEvent 会弹模态确认且两个分支都
`event.ignore()`（等 runner 停止再关，`ui/drawers/batch/sheet.py:2231-2253`），
但主窗照样销毁——sheet 是其子对象随之被销毁，runner 线程还活着 → 回调打进已删
widget，退出时可能崩溃/留孤儿任务。模态 `exec_` 时代此路径不存在。

- 契约：主窗 close 前若批处理在运行，走同一确认流：用户取消 → 主窗不关；确认
  停止 → runner 完整停止后才继续 teardown。任何路径不得留下活线程回调已删 widget。

## G. 验收标准（UVL-A01…A21）

- **UVL-A01**：点击空槽 X 添加，卡片必落 X；参数化覆盖全部布局。
- **UVL-A02**：拖放落在网格留白/槽间缝为 no-op，Board 状态不变。
- **UVL-A03**：armed 替换期间执行卡片互换或托盘放置后，arm 被清除；随后的
  库「+」是纯添加。Esc 取消顺序（焦点层→arm→演示）保持不变。
- **UVL-A04**：Board 满时托盘「放置」、库添加给出可见反馈；无选中时给出指引文案。
- **UVL-A05**：sheet 可见时，复制/导出的 toast 与文件对话框出现在 Board 窗口；
  sheet 关闭后回落主窗。
- **UVL-A06**：Board 前台时「打开原 View」使 Analyzer 主窗置前并完成切换，Board
  不关闭、不销毁。
- **UVL-A07**：单游标 hover 线不出现在任何快照像素中，其位置不影响 digest；
  dual 武装游标线与读数 pill 仍进快照（现有 dual 契约测试保持绿）。
- **UVL-A08**：Board 可见时悬停源画布，每个 `cursor_info` 事件不触发全 Board
  重投影；`_refresh_projection` 每 idle 周期至多一次（用计数探针断言量级）。
- **UVL-A09**：pill 在 request 与 grab 之间被隐藏时，该 ref 以新 digest 重新入队
  并最终发布，卡片不永久停留 stale。
- **UVL-A10**：画布 A 持续交互期间，画布 B 的 pending 抓图在其自身静默 120ms 后
  完成。
- **UVL-A11**：dual 武装游标的 View 切走后（绑定转移），卡片状态保持 FRESH；
  游标事实从 runtime ledger 回读。
- **UVL-A12**：同一 cache key 重存不同结果对象（含 id 复用模拟）必 bump
  generation。
- **UVL-A16**：时域分屏、副栏聚焦、右键主栏标签「加入总览」→ 卡片像素为主栏
  View；secondary→partner 的既有绑定不被覆盖。对称场景（主栏聚焦加副栏标签）
  同样正确。
- **UVL-A17**：pill 可见状态下捕获的卡片，切换到其他模式再回来，全程状态保持
  FRESH（可见性不进身份 digest）。
- **UVL-A18**：`reset/restore/shutdown` 后 page 的 `_previews/_statuses/_ref_exists`
  为空；重开项目不从页面侧复活旧像素。
- **UVL-A19**：总览开着打开另一项目 → 焦点层/替换 arm/演示被复位；restore
  warnings 只记录一次。
- **UVL-A20**：画布销毁后其 binding/hook/unstable 条目被剔除；新画布（模拟 id
  复用）能重新获得稳定性钩子。
- **UVL-A21**：批处理运行中关闭主窗出现确认；取消则主窗不关；确认停止则 runner
  停止后才 teardown，无已删 widget 回调（子进程级测试）。
- **UVL-A13**：全库不再有 `mode == "ultraview"` 可达分支；`chart_stack.set_mode`
  收到 `'ultraview'` 有确定性拒绝行为；Inspector 无死连接的 UltraView 面。
- **UVL-A14**：`navigate_to_view` 公共入口替代跨对象私有调用；coordinator 不再
  import/调用任何 `_` 前缀的 window/toolbar 方法。
- **UVL-A15**：修复后聚焦套件全绿，零计算探针（job isolation）不回归；lambda
  棘轮、状态所有权棘轮、import boundary 全部保持。

## H. 非目标

- 不实施 P1 多 Board / sidecar / 3×3 模板（另有 P1/P2 规格与计划）；
- 不改 PreviewStore 淘汰策略与 digest schema 版本（B7 只登记误差面）；
- 不重做 view-rail-dock 入口（只补 D1 验收）；
- 不回写历史 dated specs/plans；
- 不借机重构 pg_canvas 游标实现——只改 UltraView 侧对游标语义的消费。
