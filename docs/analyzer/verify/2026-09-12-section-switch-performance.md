# Section 切换性能优化：Grok 会话接续与验收

日期：2026-09-12。基线 HEAD：`eb5d149bd85acb6f9a4a5fdda4dd89159d743b3a`。

**结论：PARTIAL。** T1/T2/T3 的局部实现已完成，FFT 回切获得明显诊断性改善；时域回切未达到计划的 20% 改善目标。不得将本报告视为完整 §5 性能或客户验收通过。

## 会话恢复

- Grok 会话：`01a0937d-5cd4-71b1-8d3d-4d3cf20a16a6`；原始用户请求为按计划安排 agent 执行。
- 子任务：`01a09382-e64f-70e1-847f-f429c614e9df`，因 HTTP 402 usage balance exhausted 中断。恢复其未提交 T0 测试、探针和日志；未修改 Grok 原始会话。
- 接续时曾误改探针根目录，产生全为 None 的产品哈希，首轮 recovery/candidate 可比较性声明已撤回；已恢复正确根目录，并以缺失即失败的检查重跑基线与候选，独立核对全部必需哈希非空。原始 Grok parents[2] 根目录正确。旧 history 测试跳过 forward 断言，已修正。
- 原有 motion/channel_config_bar 及对应测试修改、`ssh-keygen` 均保留，不属于本次范围。

## 实现与边界

1. FFT 保留画布在显现前降低 AA，经真实 GraphicsView paint 完成、几何一致和 generation 校验后，用既有独立离散计时器结算。保留曲线/raw数据/范围/replot绑定；接入 capture pending，显式 grab 同步绘制并结算。未改 ink、point、AA 阈值或 150ms quiet window。
2. 时域回切仅本次入口禁止 begin 的全局事件泵，保留准备、delta/rebuild、范围、诊断、进度 finish。默认调用仍保留原行为。待执行目标按 View 对象身份校验、合并重复请求、关闭取消；busy 时由现有 render scope 退出后重放。
3. FFT 事实整理复用本次调用刚准备的 `(sig, fs)`，两个来源从四次 fetch 降为两次；不做跨切换缓存、不改数值算法。新增旧路径逐字段 facts/cache-key 对照。
4. fft_time/order/frf 仍走各自按 Pane 缓存重绘；没有复用 FFT reveal。FRF 的共享 paint timer 无 token provider 时不触发新 hook，热图不安装该 timer。

## Cocoa 诊断性前后比较

同机 Cocoa、DPR 2、1600×950、QTest.mouseClick；每组每方向 5 次 warmup、30 次测量。基线与候选分开新进程运行，下面仅采用 corrected 轮：产品、探针与相关测试哈希均非空、各自运行前后完全一致，正常关闭；warm compute submit 均为 0。候选在独立快照中排除用户原有动效和通道栏修改。

|场景|方向|内容就绪 P95 基线→候选 ms|后续稳定观测 P95 基线→候选 ms|单次 paint P95 基线→候选 ms|
|---|---|---:|---:|---:|
|empty|to_fft|35.06 → 37.69|58.41 → 37.69|2.57 → 2.62|
|empty|to_time|35.38 → 34.24|59.36 → 54.41|2.69 → 1.77|
|small|to_fft|488.75 → 66.81|488.75 → 235.62|146.93 → 140.66|
|small|to_time|116.78 → 112.97|180.80 → 180.65|14.49 → 14.37|
|cached|to_fft|217.97 → 90.98|217.97 → 147.03|50.77 → 47.39|
|cached|to_time|231.55 → 188.43|231.77 → 235.73|46.83 → 47.41|

大数据为 2×1,188,000 点、24kHz；实际 NFFT=1,188,000，每来源频谱 594,000 点。小数据为 2×10,000 点、1kHz。大数据 FFT 内容就绪 P95 约下降 58%；time 约下降 19%，未达 20% 改善目标。小数据仍有约 141ms 的单次绘制，不能宣称完全无卡顿。

源码哈希：基线 `bf371d00ed1e4462bf90731b94b88c0accd8aee6964d6520e9e9b7ce596babf2`；候选 `72c273704f9242bc42261ac564b0127a73de84e759621acd283bb1a41512a51b`。

测量限制：性能探针沿用隔离 MainWindow，未加载生产全局样式；真实文件功能 smoke 则另行加载 Fusion、生产 QSS 与图表字体并检查截图。以下性能不等同最终生产样式验收。这是顺序分组的诊断对比，未完成交错 A/B、各步独立性能归因、冷路径分位数、窄宽窗全矩阵。稳定字段为 capture predicate 收敛后的自然目标 paint 观测，未直接证明该帧从开始即处于最终几何/质量；heartbeat 包含初始化和 warmup，不作纯 warm 性能验收。缺少 compositor 时间戳，不报告 FPS。旧 T0 中未实断言的快照字段不算覆盖。

## 验证

- 集成 focused + 状态所有权/导入/backref/signal 接线边界：105 passed，2 deselected（23.65s）。
- 两条 deselected 的 progress 测试在未修改基线同样失败：FFT fake fetch 缺 params；Order fake effective=None 不符合 dataclass replace 合同。未改产品兼容这些过时替身。
- T3 owner/数值合同与两条原 FFT 往返：58 passed。
- T1 测量前执行 reveal/质量 focused 及 line canvas/shared timer owner；最终六条 reveal 测试通过。详细阶段结果存 .state，不把重叠测试计数相加。
- capture/dirty 选定35项全部通过；routing/source/follow/toolbar 96 passed、2 failed。split cursor-pill 失败在未改product基线复现；toolbar 的400ms断言因用户原有motion改为320ms而失败，未改本次无关文件。

## 剩余验收

- time 性能目标未达到；按计划 §6，完整时域恢复缓存和跨分区复用需另立失效合同，不自动实施。
- 严格稳定质量帧、客户全矩阵、UltraView 主动同步/项目保存重开组合、其他三分区真实性能、Windows frozen 均未完整验收。
- 本地真实 MF4 `CenterwithVehSpd_LowFri.MF4`：3775点，加载Fs≈99.9975Hz，实际惯量补偿扭矩通道/U_Nm；时域range及FFT全数组hash、双轴range一致，额外compute/job=0，Cocoa正常退出。单文件smoke不能代替客户全矩阵或用户前台验收。

可复核本地证据位于 `.state/section-switch-performance/`：`recovered/recovery-review.md`、`corrected-baseline/`、`corrected-candidate/`、测试日志及 customer smoke；运行时证据不加入 Git。

未运行全套或 Windows frozen；未提交、推送。原 Grok 基线目录保留，本次创建的临时候选 worktree 已清理。
