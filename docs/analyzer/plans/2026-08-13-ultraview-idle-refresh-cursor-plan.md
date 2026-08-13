# UltraView idle 刷新与游标/标注入图

- 日期：2026-08-13
- 状态：**IMPLEMENTED**（2026-08-13）
- 前置：`5e36b27a`（总览已能抓已绘时域图）
- 不混入：View 栏 Dock 入口、工具栏保存拆分

## 0. 目标

总览开着时，**源图面停手之后**，板上对应卡片跟上当前可见内容，并且和「复制为图片」同一套标准：

1. 曲线 / 视口 / 网格；
2. **标注**（备注点、引线，已是持久层）；
3. **游标结果**：已武装的单/双游标竖线、双游标极值标记、浮动读数 pill（含 Δ）。

不是直播，不是后台计算。没在屏幕上的 View、没算过的频谱/阶次仍然 missing/stale。

## 1. 为什么现在不会动

| 图面变化 | 现在 | 原因 |
| --- | --- | --- |
| 勾选通道 / 切 View 重绘 | 会抓 | `_render_view_to_canvas` → `time-render` |
| 分析 `set_result` | 会抓（页可见时） | `notify_ultraview_plot` |
| 平移缩放 | 不抓 | `visible_range_changed` 只写 ViewState xlim，不 `request_capture` |
| 加点/挪标注 | 不抓 | `markup_revision` 已在 digest 里，没有触发 |
| 开关/移动游标 | 不抓，抓了也没有 | digest 不含游标；`hide_transient_overlays` 会藏竖线；pill 不在画布上 |

卡片在源已变时甚至仍显示「新鲜」，因为没人按新 digest 重算状态。

## 2. 产品决定

### 2.1 只在 idle 后拍一张

与时域 `_INTERACTION_SETTLE_MS`（100ms）对齐：pan/zoom/框选期间不抓；停手后再抓。

游标读数会随鼠标连发 `cursor_info`。这条也必须进**同一个合并定时器**，禁止每像素抓一次。

总览窗口不可见时不额外调度（重绘路径上已有的 capture 可保留）。

### 2.2 游标结果怎么进图（对齐复制为图片）

`ChartStack._copy_card_image` 已经是标准：

- 画布 `grab` **不**藏武装游标线，所以竖线在图里；
- 再把浮动 **cursor pill** 按几何合成上去。

总览应复用这条，而不是在 coordinator 里再发明一套。

`hide_transient_overlays` 收窄为真正的临时层：

- **仍藏**：hover 跟随十字（未武装）、`rbScaleBox` 框选、选择高亮；
- **不再藏**：单/双游标 `InfiniteLine`、双游标极值标记。

读数 pill 是 ChartStack 上的 sibling，不在 canvas 里，必须合成，单靠 canvas.grab 永远没有数字。

### 2.3 digest 必须看见游标，否则会跳过抓图

现测试钉死：改 `cursor_mode` digest 不变。要改掉。

digest 增加（只读、不触发计算）：

- `cursor_mode`（off/single/dual）；
- 已武装游标的 x（双游标两个 x）；
- pill 纯文本/HTML 的短指纹（读数变化也要刷新）。

标注继续用已有 `markup_revision`。

xlim/ylim 已在 ViewState 里；idle 抓之前 `visible_range_changed` 已经写过，digest 会变。

### 2.4 明确不做

- 跟手刷新（每一帧 pan 或每一个 `cursor_info`）；
- 为了刷新去 `do_fft` / restore / 重绘不可见 View；
- 把总览卡片做成共享 scene 的真直播；
- 把 hover 十字和框选橡皮筋打进快照。

## 3. 卡顿与主窗口闪烁

| 风险 | 控制 |
| --- | --- |
| 与包络刷新抢 GUI 线程 | `_is_stable` 已挡 `_refresh_pending` / interaction / AA yellow；idle 后才 `_queue_grab` |
| 密波形 AA 导出帧 | UltraView 继续 `grab_pixmap(scale=1.0)`，dense-raster 走当前屏幕像素拷贝 |
| 主窗口游标闪一下 | 来自现在「抓之前 hide 游标」。收窄 hide 之后武装游标不再闪；pill 本就不在 hide 集合里 |
| 内存 | 仍是 PreviewStore 最长边 1600 + 像素预算，原地替换 |

预期：一次停手 = 至多一张卡的一次 grab，和打开总览时那一下同类。交互路径不应变卡。

## 4. 实现形状

### Task 1 — 抽出「演示抓图」缝（不进剪贴板）

Owner：`chart_stack/stack.py`（现 `_copy_card_image`）。

- 抽出 `grab_presentation_pixmap(card_or_canvas, *, scale=1.0) -> QPixmap`：
  canvas 像素 + 与复制相同的 pill 合成（分析区分 pane 仍走 `grab_combined_pixmap`）；
- `_copy_card_image` 改为调用它再 `image_captured.emit`；
- UltraView coordinator 的 `_grab_image` 优先走这条，没有 pill 的假画布保持现在的 `grab_pixmap`。

验收：现有复制测不回退；新测「pill 可见时合成进 pixmap」。

### Task 2 — 收窄 transient hide + digest 含游标

Owner：`ultraview_coordinator.py`、`tests/ui/test_ultraview_capture.py`。

- hide 集合去掉武装游标线 / 极值标记；
- `_time_payload` / 分析 payload 写入 cursor_mode、cursor x、pill fingerprint；
- 改现测 `test_transient_overlays_hidden_but_markup_revision_is_captured`：武装游标在 grab 时可见，hover/框选仍隐藏；改 cursor_mode 必须改变 digest。

### Task 3 — 合并 idle 调度

Owner：`UltraViewCoordinator`，一个 `QTimer`（单次，间隔与 settle 同量级，100–150ms）。

触发（bound method / `partial`，禁止新 `.connect(lambda`）：

- 已有：`time-render`、`notify_ultraview_plot`、打开总览；
- 新增：`visible_range_changed`（画布已接）、`cursor_info` / `dual_cursor_info`、标注 `markup_revision` 变化（若无信号则在 annotations 现有 revision bump 处 notify）。

槽只做 `_schedule_idle_capture(ref)`：重置定时器。超时后：

1. 总览 sheet 不可见 → return；
2. widget 不可见 / 无结果 → 维持现有 missing 语义；
3. 不稳 → 再等（现成 `_unstable`）；
4. digest 已有有效图 → skip；
5. 否则 `_queue_grab`。

同一 ref 多次事件必须合并成一次 grab。禁止对每个 `cursor_info` 直接 `request_capture`。

### Task 4 — 板上状态

idle 抓成功 → `_push_preview` 变 fresh。  
digest 变了但还没抓到（仍在 settle）→ 卡片可显示 stale「源已变化」，不要继续假装 fresh。  
不要在无图时改成 missing（会误报「尚无可用结果」）。

### Task 5 — 发现性

`hints.py` / `quickref.py`：总览在停手后跟上当前图面，快照含游标读数与标注。不写「实时/直播」。

### Task 6 — 验证

定向：

- `tests/ui/test_ultraview_capture.py`（coalesce、digest、hide 集合、pill 合成缝）；
- `tests/ui/test_ultraview_mode_integration.py`：画时域 → 开总览 → pan 后 wait settle → 卡片 digest/图变化；加标注同样；
- `tests/ui/test_ultraview_job_isolation.py`：idle 刷新路径 compute 仍为 0；
- `tests/ui/test_no_lambda_signal_connections.py` 棘轮不升。

然后 `tests/ui/test_ultraview_*.py`。macOS 前台：总览与主图并排，停手后卡片有竖线、pill 数字、备注；拖动期间主图不卡、游标不闪。

## 5. 文件与风险

| 文件 | 角色 |
| --- | --- |
| `ui/chart_stack/stack.py` | 抽出演示 grab；复制路径变薄 |
| `ui/main_window/ultraview_coordinator.py` | hide、digest、idle timer、触发 |
| `ui/pg_canvas/canvas.py` 或 annotations | 仅当标注 bump 没有可连信号时加一针 notify |
| `tests/ui/test_ultraview_capture.py` 等 | 合同 |
| `ui/hints.py` `ui/quickref.py` | 文案 |

风险：

- 分析区 pill 几何与时域不同，合成必须按 `_pill_for_canvas`；
- 切 View 时旧游标 digest 不得写到新 ref（现成 `bound_ref_for`）；
- Dock 入口未完成，本计划不改 `open_ultraview` 的按钮位置。

## 6. 建议提交切分（落地时）

1. `refactor(ui): extract presentation grab used by copy and UltraView`
2. `fix(ui): UltraView idle recapture includes cursor readout and markup`
3. `docs/test` 与 hints/quickref

不与 View 栏 Dock、保存拆分混提交。
