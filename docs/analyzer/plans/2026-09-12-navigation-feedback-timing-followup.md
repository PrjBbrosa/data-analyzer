# Section / View 导航反馈时序 Follow-up

日期：2026-09-12。状态：**文档完成，尚未实施本 follow-up**。
范围：修正导航指示动画启动晚于业务切换的问题；保留现有绘图、状态恢复和任务调度。

关联：[Section 性能主计划](2026-09-12-section-switch-performance-plan.md)、[已有局部实施记录](../verify/2026-09-12-section-switch-performance.md)。主计划的实现已在当前工作区推进，本 follow-up 必须建立在实施时的实际代码上，不能恢复旧版本。

**本文件取代主计划 T1 中“保持 toolbar 业务 signal 时序；不重排 `_apply_mode`”的限制。** 只允许调整呈现启动与 signal 的相对顺序，不允许调整业务 capture → commit → apply 的依赖关系。当前用户仅授权写文档，不授权产品实施、agent、提交或推送。

## 1. 当前证据与目标

- `mf4_analyzer/ui/toolbar.py:_apply_mode` 当前顺序：更新选中状态 → `mode_changed.emit(mode)` → `_follow_indicator(animate=animate)`。同线程 signal 会同步进入内容切换，动画启动必须等它返回。这是已确认的调用顺序问题。
- `mf4_analyzer/ui/view_tabbar.py:_sync_active` 在 manager 确认后执行 `_relocate_marker`。其订阅在当前初始化路径中早于 MainWindow 渲染订阅，不能直接认定 View 下划线也存在同样的“后启动”代码错误；恢复/绘制阻塞可能让已启动的动画无法及时上屏。
- `tests/ui/test_view_tabbar.py:test_unconfirmed_switch_request_does_not_move_marker` 明确要求：未确认请求不移动下划线，随后程序确认采用 snap。延迟切换不能为了追求动画而绕过这个合同。

目标时序：

```text
Section：确认有效目标 → 更新选中状态并启动指示动画 → 同步发出原业务 signal
View：请求 → manager 确认 → 启动/定位指示线 → 原有内容恢复
两者：业务不等待动画结束；绘制就绪与动画推进不应表现为两次分离的响应
```

“动画已启动”与“实际画出位移”分开验证。单纯调换两行只解决启动晚，不能声称消除了主线程掉帧。

## 2. 必须保留的边界

1. 每次实际切换仍只发一次业务 signal；重复点击 no-op；程序切换 snap；MotionPolicy off/reduced 不等待动画。
2. 不改变动画时长、easing、颜色或 geometry 规则，不纳入当前 `motion.py` 的其他任务改动。
3. View 以 manager 确认的 view_id 为准；拒绝/尚未确认的请求不提前把下划线滑向目标。overflow、resize、重排导致布局变化时继续 snap。
4. 连点 A→B→C 从当前显示位置转向最新已确认目标；不在旧动画结束后补放 B。不改变 TimeRenderGate 的延迟/重入保护及 UltraView 的逐源同步队列。
5. 不新增 `processEvents()`、强制 repaint 整个窗口、固定 sleep、动画结束后才切内容，或把整个 `_on_mode_changed` 放进 `singleShot(0)`。这些做法会影响输入、捕获和状态一致性。
6. 不删除任何 capture/apply/render；不改数值计算、缓存键、范围恢复、历史、游标、dirty、项目恢复和 UltraView capture 生命周期。

## 3. 三个小任务

### F0 — 给启动顺序加回归

Files：`tests/ui/test_toolbar.py`、`tests/ui/test_view_tabbar.py`；需要产品路径覆盖时扩展现有 `tests/ui/test_section_entry_presentation.py`。

- [ ] 新增 `test_toolbar_starts_feedback_before_mode_changed_delivery`：使用已显示且启用 light policy 的 Toolbar；在 `mode_changed` 的同步接收槽中检查目标按钮已选中、indicator 的目标已经更新且 driver 已启动；接收槽调用一次，原实现应因 driver 尚未启动而失败。不用 sleep 模拟慢工作。
- [ ] 覆盖槽内程序改选目标与销毁 toolbar：外层返回后不得补放旧目标动画或访问已销毁对象。保留重复点击、程序 snap、off/reduced 测试。
- [ ] MainWindow 集成记录 manager confirm、marker `go/snap`、重恢复入口的事件顺序，分别覆盖时域和 FFT View。不能只靠手写一个理想的 signal 接线替身证明实际初始化正确。
- [ ] 复用未确认请求、overflow、快速 A/B/C 的既有 marker 测试；加 busy gate 延迟确认场景，验证确认前不移动、确认后沿既有 snap 合同落位且最终身份一致。

### F1 — 顶部 Section 局部修正

File：`mf4_analyzer/ui/toolbar.py:_apply_mode`。

- [ ] 在选中状态和 active dots 更新后，将 `_follow_indicator(animate=animate)` 移到 `mode_changed.emit(mode)` 前。保留原 signal、参数、同步发出方式及 no-op 判断。
- [ ] 不在 signal 返回后再次启动/定位旧目标。槽内若发生更新的程序导航，让较新的目标自然取代当前动画；销毁后无需外层尾部访问控件。
- [ ] 运行 F0 新增 node 及 Toolbar owner 测试。若仅有当前其他任务已修改时长导致旧断言失败，单独记录并协调该 owner，不能把它混进本补丁。

### F2 — View 下划线与真实画面验收

Files：先仅测试与 `.state/navigation-feedback-timing/` 探针；只有 F0 证明 marker 启动实际晚于渲染，才修改 `mf4_analyzer/ui/view_tabbar.py` 或 MainWindow 的明确接线点。

- [ ] 若当前 manager 确认 → marker 启动 → render 顺序成立，保持 View 产品代码，仅保留回归。不能为“形式统一”在 `switch_requested.emit` 前猜测确认或添加 optimistic marker。
- [ ] 若发现某个真实入口顺序倒置，将确认后的呈现同步放到该入口的重恢复之前；不移动 manager 提交和离开 View capture。记录具体入口，不能全局重连全部信号。
- [ ] 真实 Cocoa、生产 QSS/字体、隔离 QSettings，测空页、小数据、已缓存大数据的 Section 和 View 点击；记录点击、driver 启动、首个非零指示位移 paint、首个正确目标内容 paint、动画结束与最终稳定。曲线数据/范围/身份与未改前一致。
- [ ] 视觉目标：不出现新内容已稳定显示、指示条却仍停在旧位置后才开始独立滑动；不引入空白闪烁。内容可以在动画途中到达，无需等滑块抵达终点。
- [ ] 若启动顺序已修正，实际位移仍因重绘阻塞滞后，则交付标记“启动顺序已修正，视觉同步仍 partial”，附 paint 时间线回到主性能计划处理；本小任务不扩成绘图架构改造。

## 4. 验证与交付

后续实施先执行新增失败 node，再执行 owner / 相关边界：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_toolbar.py tests/ui/test_view_tabbar.py tests/ui/test_section_entry_presentation.py -q
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_time_section_entry.py tests/ui/test_view_switch_reentrancy.py tests/ui/test_no_lambda_signal_connections.py -q
git diff --check
```

若实际改动 MainWindow 状态或接线，追加 `tests/ui/test_main_window_state_ownership.py`；只改 Toolbar 顺序不跑全套 UI。offscreen 证明逻辑顺序，Cocoa 证明实际 paint；不要用 driver.is_active() 代替屏幕同步验收。

本次 docs-only：仅创建此 follow-up，核对当前源码、相关测试、文档链接与格式；不跑 runtime suite，不改已有局部实现或主计划的执行记录。后续实施验收分别报告启动顺序、实际画面和残余阻塞，不宣称整个 Section 性能问题已经完成。
