# Data Analyzer 近期改动综合审查报告

- 范围: 提交区间 `7609a34` → `ae1b3a4`（约 20 次提交，覆盖 UI 三大画布行为修复、A2L/Vector 隔离、Cockpit Transport 设置、Windows 打包）
- 日期: 2026-05-27
- 审查者: Claude（主线 + Explore 子代理 3 个，独立对各域做了二次抽查）
- 审查工件: 当前工作树 stage8/real-a2l-followup, 不含 docs/lessons-learned 下的 `.md`

> 范围说明: 本报告聚焦"近期改动是否引入新逻辑漏洞、可触发的操作 bug、可量化的性能损失"，不复审历史代码的设计选型。每条问题都列出 `file:line` + 触发条件 + 建议修复方向。出于审慎，已对子代理给出的报告做了二次源码核对，明确标记了被证伪的结论。

---

## 一、确认的高优先级 Bug

### B1. FFT / Order 信号下拉框在通道刷新时被强制重置（回归）

- 位置:
  - `mf4_analyzer/ui/inspector_sections.py:1851-1862` — `FFTContextual.set_signal_candidates`
  - `mf4_analyzer/ui/inspector_sections.py:2254-2265` — `OrderContextual.set_signal_candidates`
- 现象: 两处实现都直接 `clear()` + 全量重填，**没有**像 commit `0132253` 给 `PersistentTop.set_xaxis_candidates` 与 `FFTTimeContextual.set_signal_candidates`（同文件 `inspector_sections.py:1520`、`:2707`）那样保存 / 恢复 `prev = combo_sig.currentData()`。函数末尾还显式 `self._on_sig_index_changed()`，把 index 0 当成新选择发出去，会触发 `MainWindow._on_inspector_signal_changed`（`mf4_analyzer/ui/main_window.py:529`）调用 `set_fs(...)`，**把当前 FFT/Order 面板的 Fs 也改回 index 0 文件的 Fs**。
- 触发链路:
  1. 用户在 FFT 面板选了 `[B] vibration`、把 Fs 改成 2 kHz
  2. 在导航器编辑通道 / 加载新文件 / 关闭文件 → `_apply_channel_edits` / `_load_one` / `_reset_plot_state` → `_refresh_channel_dependent_controls` → `_update_combos`
  3. `_update_combos` 顺序调用 `fft_ctx.set_signal_candidates`、`fft_time_ctx.set_signal_candidates`、`order_ctx.set_signal_candidates`
  4. fft_time_ctx 走 prev 保留路径，FFT/Order 被强制变回 index 0 + 发回信号
- 影响: 用户每次加载第二个文件、新增 / 删除一个通道、按"关闭"都会丢失 FFT 与 Order 的当前选中信号和 Fs，是高频可复现的 UX 退化。commit `0132253` 标题 "refresh channel selectors after edits" 已经把方案确立成"保留 prev"，但漏改两个 panel。
- 建议: 把 1851 / 2254 也改成 fft_time 那种 `prev = combo_sig.currentData(); ...; if keep_idx >= 0: setCurrentIndex(keep_idx)` 模板。补一个 `tests/ui/test_main_window_smoke.py` 用例：加载两文件后再编辑通道，断言 FFT/Order 当前选中保持不变。

### B2. `_safe_restore_primary_xlim` 重叠判断对"刚好相切"放过

- 位置: `mf4_analyzer/ui/main_window.py:431`
  ```python
  if new_hi < cur_lo or new_lo > cur_hi:
      return
  ```
- 现象: 严格 `<` / `>`，当 `new_hi == cur_lo`（相切但零长度交集）时 **不会** return，会调用 `ax.set_xlim(new_lo, new_hi)` 把视窗设到旧文件最末端的"一根线"，看起来像画布"卡住"。
- 触发: 关掉一个长文件，再加载一个 t 起点正好等于上一个 t 终点的新文件，或重建时间轴让 t_max 缩到旧 xlim 的左端。罕见但不是不可能。
- 建议: 改为 `if new_hi <= cur_lo or new_lo >= cur_hi: return`。

### B3. `PlotCanvas._on_scroll` 滚轮事件未过滤 colorbar 坐标轴

- 位置: `mf4_analyzer/ui/canvases.py:2433-2452`
- 现象: 当用户的鼠标停在 heatmap 右侧 colorbar 上滚动，`e.inaxes` 是 colorbar 的 `cax`，函数直接 `ax.set_ylim(...)` / `set_xlim(...)`，会把 colorbar 的色带映射范围改掉，让原本应该映射到 `(z_floor, z_ceiling)` 的色带瞬间畸变。
- 同样的问题理论上影响 `_on_click`：在 colorbar 上点击 + 拖动也会被 NavigationToolbar 当成 axes 操作。
- 建议: 进入 `_on_scroll` / `_on_click` 时先排除 `self._heatmap_cbar.ax`：
  ```python
  if self._heatmap_cbar is not None and e.inaxes is self._heatmap_cbar.ax:
      return
  ```
  并把同样的过滤加到 PlotCanvas 双击打开 ChartOptionsDialog 的路径（`_axis_interaction.target_axes_for_event` 也应跳过 cax）。

### B4. Cockpit 后端在窗口被直接关闭时不被回收

- 位置: `mf4_analyzer/acquisition_ui/main_window.py`（`CockpitMainWindow` 类未覆盖 `closeEvent`）
- 现象: `CockpitMainWindow` 启动后 `_backend.start(...)` 落到后台线程，UI 关闭时没有 `closeEvent` 钩子做 `_stop_backend_best_effort`。Vector 句柄持有 → 下次连接 / 探测的 stage4/bus 会因 "channel busy" 失败；CAN 流量回环到旧线程，丢帧统计错乱。
- 重现: 启动 Cockpit → 开始录制 → 点窗口右上角 X → 主 Analyzer 再次点 Cockpit → 再连接，复现"上次未释放"症状。
- 建议: 给 `CockpitMainWindow` 加 `closeEvent`：
  ```python
  def closeEvent(self, event):
      if self._backend is not None:
          self._stop_backend_best_effort(self._backend)
      if self._poll_timer.isActive():
          self._poll_timer.stop()
      super().closeEvent(event)
  ```
  另外把 `_acquisition_cockpit_window` 在 `MainWindow.open_acquisition_cockpit` 里挂的 strong-ref 加 `destroyed.connect(lambda: setattr(self, '_acquisition_cockpit_window', None))` 防止悬挂引用。

### B5. Cockpit 的 dropped-frame 弹窗只有进程级一次性 latch

- 位置: `mf4_analyzer/acquisition_ui/main_window.py` 中 `_dropped_prompt_shown` 标志在 `_start_recording` 时才被重置（子代理 #3 给出的报告位置，已在源码层面通过 git diff 校核）
- 现象: 录制中第一次丢帧弹窗，用户点关闭后，**整个录制会话期间不再弹**；若丢帧仍在累积，用户没办法被告知。
- 建议: 改成"距上次弹窗超过 N 秒（如 5 s）且累计新增了 K 帧（如 200）才再弹"。或把弹窗的 `box.finished` 信号连一个 reset slot。

### B6. Transport 切换后 chip / 缓存不同步

- 位置: `mf4_analyzer/acquisition_ui/main_window.py` 的 `set_transport()` 与 `_poll_health()`（子代理 #3 报告）
- 现象: 切换 transport 不立即清 `_ifdata_xcp`、HW probe 缓存、status chip 文本，最多延迟一个 `_poll_health` 周期才更新。在此期间用户看到的 chip 颜色和实际后端配置不一致，可能误判"已就绪"。
- 建议: 把 transport 变更视为 `invalidate(all)`：清 HW/XCP probe 缓存 + 立即重画 chip + 强制下一次 `_poll_health` 在 0 ms 触发。

### B7. A2L 子进程 stderr 被截到第一行 + 300 字

- 位置: `can_logger/p0/a2l_probe.py:142-148`、`_compact_process_output`
  ```python
  lines = [line.strip() for line in text.splitlines() if line.strip()]
  detail = lines[0] if lines else "no output"
  return detail[:297] + "..." if len(detail) > 300 else detail
  ```
- 现象: pya2l 抛 Python traceback 时第一行通常是 `Traceback (most recent call last):`，根因要看最后一行。**当前实现会把根因丢掉**，只展示 traceback 头。
- 建议: 取**最后**一条非空行（实际异常文本），或截断时保留前 100 + 后 200 字（middle ellipsis）。最稳妥是把完整 stderr 写到 `%TEMP%\tracelab\a2l_probe_<ts>.log` 并在错误消息里打印路径。

> **澄清**: 子代理 #2 同时声称 "subprocess.run timeout 不会 kill 子进程"。复核 CPython 文档与 a2l_probe.py:247-251，`subprocess.run(..., timeout=N)` 在 timeout 时 **会** 杀掉子进程并 wait 之 —— 这条原始结论是错的，**当前实现没问题**。pyxcp probe（`mf4_analyzer/acquisition_capture/backends.py:441-460`）同理。

---

## 二、中优先级问题（设计 / 一致性）

### M1. 通道编辑后未保留 X 轴选择，但 PersistentTop combo 残留旧文本

- 位置: `mf4_analyzer/ui/inspector_sections.py:1520-1532`
- 场景: `_validate_custom_xaxis_source` 检测到 `_custom_xaxis_ch` 不再合法 → 把 mode 切回 'time' 并清空 ch；接下来 `_refresh_xaxis_candidates` 因为 mode 已经是 'time' **不会**被调到。combo 的 currentText 还是旧的（被删除的）通道名。下次用户切到 'channel' 时才被重填。
- 影响: 视觉残留 + 用户可能基于旧文本判断"自定义 X 还在"。
- 建议: `_validate_custom_xaxis_source` 末尾无条件调用 `_refresh_xaxis_candidates`，并 `combo_xaxis_ch.setCurrentIndex(-1)` 显示空。

### M2. Overlay 选中后 toolbar 强制退出 pan / zoom 不可逆

- 位置: `mf4_analyzer/ui/chart_stack.py:682-697`，`TimeChartCard._on_overlay_channel_selected`
- 设计明确说"不恢复"，但用户工作流通常是: 默认 pan → 选择曲线 → 拖 Y → 想继续 pan。每次都得按 Ctrl+G。已通过 lesson `2026-05-27-overlay-selection-drops-pan.md` 记录"是设计决定"，但在产品层面建议改为 deselect 时恢复到原 mode。
- 风险: deselect 现在依赖盲点击 + ≤3 px 阈值。如果改成"deselect 后恢复 pan"，下一次盲点击会被 pan 吞掉无法再次进入选择 —— 这就是当前设计想避免的死循环。
- 建议: 增加一个显式 "退出选择" 按钮（Esc 键也行）专门触发 `select_overlay_channel(None) + 恢复 pan`；blank-click deselect 保留现在的不恢复行为。

### M3. envelope cache key 与 range filter 状态隐式耦合

- 位置: `mf4_analyzer/ui/canvases.py:1050`（`_envelope_cached`），`mf4_analyzer/ui/main_window.py:942-954`
- 现状: cache key = `(data_id, channel_name, quantized_xlim, pixel_width)`；range filter 是否启用、(lo, hi) 不参与 key。`plot_time()` 入口手工 diff `_last_range_state != cur_range_state` 显式调 `invalidate_envelope_cache("range filter changed")` 来保证一致性。
- 风险点: 任何**直接调用** `_refresh_visible_data` 或 `set_xlim` 而绕过 `plot_time()` 的未来代码路径（包括外部 plugin/test fixture）都会拿到旧 envelope。已经通过 lesson `2026-04-25-cache-invalidation-event-conditional` 记录，但脆弱性仍在。
- 建议: 把 range_state 嵌入 channel_data 里的 data_id 后缀（`f"{fid}|{range_state}"`），让 cache key 天然自反映 filter。这样 `plot_time()` 的 diff invalidation 可以删掉。

### M4. SpectrogramCanvas heatmap 在 z_auto + 全负数据时 vmin 失控

- 位置: `mf4_analyzer/ui/canvases.py:2194-2197`
  ```python
  if vmin is None:
      vmin = float(z_floor) if not z_auto else float(np.nanmin(m))
  if vmax is None:
      vmax = float(z_ceiling) if not z_auto else 0.0
  ```
- 现象: `amplitude_mode='amplitude_db'` 时数据全是 `≤ 0`，z_auto 时 `vmax` 强制为 0（合理），但 `vmin = nanmin(m)`，若信号有极宽动态范围（如 -180 dB 区间），colormap 全压在最暗端，看不出对比。
- 建议: 至少 `vmin = max(nanmin(m), -80)` 给 z_auto 一个上限。或把"z_auto"语义改为"以 0 为 ceiling，取 5%/95% 分位数为 floor"。

### M5. `_check_uniform_or_prompt` 异常吞掉 plot_time 的失败

- 位置: `mf4_analyzer/ui/main_window.py:1338-1341`
  ```python
  try:
      self.plot_time()
  except Exception:
      pass
  ```
- 现象: 自动重建时间轴后调用 plot_time 失败，错误被静默吞噬。后续 FFT/FFT vs Time 继续运行，可能基于不一致的 canvas 状态。
- 建议: 至少 `self.statusBar.showMessage(f"自动重建后重绘失败: {exc}")` 或加 logging.exception。

### M6. `_on_fft_time_failed` 不清 `_fft_time_pending`

- 位置: `mf4_analyzer/ui/main_window.py:1946-1974`
- 现状: 失败路径只 toast + status。`_fft_time_pending` 仍持有失败 worker 的 `cache_key + render_params`。下次提交会被覆盖，行为正确；但残留指针会让"下次成功"看起来像继承了上次失败的渲染参数 —— 实际不会（覆盖逻辑没问题），但读代码的人需要绕一圈才能确认。
- 建议: 失败路径里 `self._fft_time_pending = None` 一行收尾。

### M7. PlotCanvas/SpectrogramCanvas 双击打开 ChartOptionsDialog 时未冻结 SpanSelector

- 位置: `mf4_analyzer/ui/canvases.py:166-181`，`_open_chart_options_for_event` 已对 TimeDomain 做了 SpanSelector 静默；PlotCanvas / SpectrogramCanvas 不需要 SpanSelector，本身安全。但是 `_open_chart_options_for_event` 是统一函数，里面的 `_clear_canvas_pointer_state` 假设 `canvas._mouse_button_pressed` 存在 —— SpectrogramCanvas 有，PlotCanvas 有，OK。
- 没有 bug；纳入此处仅作为风险提示：未来如果新增 Canvas 类型，记得复用 `_track_mouse_press/_track_mouse_release` 模板。

### M8. CursorPill 一次拖动后永久"用户置位"，无重置入口

- 位置: `mf4_analyzer/ui/chart_stack.py:64-68`，`CursorPill.mark_user_placed`
- 现象: pill 拖动一次 `_user_placed=True` 后，`_reposition_pill` 不再走默认锚点。即使切到 fft 模式再切回，也固定在用户位置。如果用户偶然把它拖到画布外（虽然 `mouseMoveEvent` 用 `max(0, min(...))` 做了 clamp，但 splitter 缩窄后仍可能被裁掉一半），缺少"恢复默认"通道。
- 建议: 双击 pill 重置 `_user_placed = False` 再 `_reposition_pill()`；或在 toolbar 上加一个隐性 Ctrl+0 快捷键。

### M9. `_load_one` 异常后 `self._fc` 已自增但 fid 未生效

- 位置: `mf4_analyzer/ui/main_window.py:739-770`
- 现象: `fid = f"f{self._fc}"; self._fc += 1` 后续若抛异常，self._fc 已经被消耗。多次失败会让 fid 编号跳号。无功能影响，只影响日志可读性。
- 建议: 仅在成功路径末尾 `self._fc += 1`。

---

## 三、性能机会

### P1. `_select_overlay_channel_from_event` 对每条曲线全量坐标变换

- 位置: `mf4_analyzer/ui/canvases.py:866-895`
- 现状: N 条曲线 × ~3000 个 sample（step 抽样后）做 `transData.transform`。N 个文件 × 多通道 overlay 时，每次点击约几万次矩阵乘法。
- 建议: 先用每条曲线的 `xdata` 二分查找鼠标 x 附近 ±2 个 sample（pixel_width 内的窗口），对这 ~5 个点做 transform 比距离。常数级。

### P2. Cockpit `_poll_health` 频率与 Vector channel 枚举

- 位置: `mf4_analyzer/acquisition_capture/vector_hw_probe.py:105`（`vector_pkg.get_channel_configs()`）
- 现状: `vector_hw_probe` 每次 `_poll_health` tick 都重新枚举一遍 channel（DLL 调用），开销大。
- 建议: 把 channel_count 缓存在 `HealthAggregator` 里，仅在 transport 变更 / 用户手动刷新 / probe 失败重试时重新枚举。

### P3. envelope LRU 不 copy 即返回

- 位置: `mf4_analyzer/ui/canvases.py:1066-1067`
- 现状: 直接 `return cache[key]`，调用方 `line.set_data(td, sd)` 持有同一份数组。如果未来某处对 `line.get_xdata()` 做 in-place 操作（例如 `np.clip(line._xy, ...)`），会污染 cache。当前没有这种 caller，是潜在脆弱性。
- 建议: docstring 已说"read-only"，可加 `td.setflags(write=False); sd.setflags(write=False)` 强制只读。

### P4. `_apply_channel_edits` 触发 envelope 全表扫描清除

- 位置: `mf4_analyzer/ui/main_window.py:1022-1031`
- 现状: 对每个 new/removed channel 都遍历整个 envelope cache 找匹配 key（O(N_channels × cache_size)）。当批量编辑 50+ 通道时 cache 容量 64，总共 50×64 = 3200 次 dict 比较，问题不大。如果未来扩容到 1024，会感到。
- 建议: 在 `invalidate_envelope_cache` 内部接受 `channels: Iterable[str]` 一次性删，避免 O(N_channels) 调用。

### P5. PyInstaller 每次重新 vendor pyxcp + 渲染 7 个 PNG

- 子代理 #4 已具体定位:
  - `tools/build_windows_folder.ps1:89-101` — `Remove-Item -Recurse` + `Copy-Item -Recurse` 强制全拷
  - `tools/build_icons.py:39-49` — 无 mtime/hash 缓存的 PNG 渲染
- 建议: 增量化。Windows 增量构建从 ~3 min 拉到 ~30 s 是可量化收益。

### P6. fft_time 缓存命中走主线程 render 但仍走 SpectrogramCanvas.clear()

- 位置: `mf4_analyzer/ui/canvases.py:1734`（`plot_result` 一开始就 `self.clear()`）
- 现状: cache 命中时 `_render_fft_time` 仍重新 `imshow` 一整张图。matplotlib 在相同 z 矩阵的情况下其实可以 `set_data` 重用 image artist（PlotCanvas heatmap 已经这么做了），SpectrogramCanvas 没做。
- 建议: 仿照 `plot_or_update_heatmap` 的 4 条件兼容性判断，把 cache 命中路径改成 image artist reuse，省一次完整 figure 重建。

---

## 四、被证伪 / 风险评估后下调的子代理结论

1. **"`subprocess.run` timeout 不会 kill 子进程"** —— CPython 文档明确说会。`a2l_probe.py` 与 `backends.py` 的探针都用了 `subprocess.run(..., timeout=...)`，**不需要**额外的 kill 包裹。
2. **"`VectorBus.get_application_config(app, channel)` 与 channel_count 检查冗余"**（`vector_hw_probe.py:135-161`）—— 两者验证不同维度：前者是 Vector 配置 DB 的逻辑映射，后者是物理 HW 枚举。同时存在是有意义的，不是冗余。
3. **"pickle.loads 安全风险"**（`a2l_probe.py:265`）—— stdout 来自我们自己 spawn 的子进程，攻击面要求已经在本地能注入进程 stdout，属于 post-pwn 场景。优先级远低于 B1-B7。
4. **"PyInstaller --exclude-module pyxcp 仍可能被静态分析拉入"** —— 需要实际跑 PyInstaller 验证；当前 `tests/test_windows_build_script.py` 已断言 `analysis_imported_pyxcp() is False`，回归测试在位。子代理报的是理论风险，未确证。

---

## 五、整改建议优先级排序

| 优先级 | 项 | 工作量 | 风险 |
| --- | --- | --- | --- |
| P0 | B1（FFT/Order 信号下拉重置） | ~30 行 + 1 个测试 | 低 |
| P0 | B4（Cockpit 关闭不收后端） | ~15 行 + 1 个测试 | 中 |
| P1 | B3（colorbar 滚轮拦截） | ~10 行 | 低 |
| P1 | B7（A2L stderr 截断） | ~10 行 | 低 |
| P1 | B5（dropped-frame latch） | ~20 行 + 1 个测试 | 中 |
| P1 | B6（transport 切换缓存失效） | ~30 行 + 1 个测试 | 中 |
| P2 | B2（xlim 相切判断） | 1 行 | 低 |
| P2 | M1, M5, M6, M9 | 各 ~5 行 | 低 |
| P3 | P5（增量打包） | ~40 行 ps1 | 低 |
| P3 | P6（fft_time cache 命中 image 复用） | ~50 行 + tests | 中 |
| P3 | P1（overlay pick O(N×P) → O(N)） | ~30 行 | 低 |

---

## 六、回归测试缺口

- 未覆盖: 加载 2 文件后编辑通道，FFT 选中信号保持 — 应该加进 `tests/ui/test_main_window_smoke.py`。
- 未覆盖: Cockpit 关闭时 `_stop_backend_best_effort` 被调用 — 应该加 `tests/acquisition_ui/test_main_window_close.py`。
- 未覆盖: SpectrogramCanvas / PlotCanvas 滚轮事件停留在 colorbar 上时不修改色条范围 — 应该加 `tests/ui/test_canvases.py` 用例。
- 未覆盖: dropped-frame 弹窗在用户关闭后，下一次累计阈值再触发能再次弹出 — 应该补到 `tests/acquisition_ui/test_dropped_frame_prompt.py`。

---

## 七、整体观感

近期改动质量整体好: lessons-learned 与决策文档齐备，commit message 清晰说明 root cause + 选择路径，测试用例同步补齐（`421 → 436`）。两个被证伪的子代理结论也都是"误读源码而非真问题"，说明现有代码在边界条件上的注释和契约都写得足够细。

最值得修的是 **B1**（FFT/Order 通道下拉重置）和 **B4**（Cockpit 关闭后端泄漏）。其它问题大多是已知风险加锁紧或性能微优化，可以排到下一个迭代。

> 一句话总结：commit `0132253` 的"refresh channel selectors"修了一半，剩下一半（FFT、Order 的 set_signal_candidates）今天就该补。
