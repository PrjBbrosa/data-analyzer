# 两日优化后的正确性与鲁棒性 Spec

日期：2026-09-12。状态：**设计完成；本轮 R06 入口移除已实施**。其余需求状态见各自实施记录。

依据：[两日 Review](../reviews/2026-09-12-two-day-optimization-review.md)。执行：[Plan](../plans/2026-09-12-optimization-robustness-plan.md)。

2026-09-12 用户决策更新：取消范围状态条及“恢复参数范围”入口，使用 Home 查看全图、重新点击计算按参数显示。该指令授权本轮 R06 的移除，不扩展其他任务范围；以下 R06/A11 取代先前的按钮 dirty 修复要求。

## 1. 目标与边界

使已经落地的频谱范围/缓存、选择动效、通道筛选恢复、Batch 结果详情及 Custom-X 标签，在边界输入、同步回调、程序恢复和大通道规模下保持一致、可解释、可验证。

本 Spec 定义修复合同，不表示全部实现通过。初始交付是 review 和文档；用户后续已明确授权本轮 R06 的入口移除，其余任务的授权与完成状态以各自实际会话和验证记录为准。实施保留现有 Qt 面板、按钮、三栏及图卡语言；不新增业务等待动画、不重写 MainWindow、不调低已校准 AA/ink 阈值、不改 FFT 数学或原始时域数据。

基线须在实施时重新冻结：Review 的已提交基线是 `9cda71ad`，另有 `d1299597` 与 Section/motion/channel-config 在途候选；不能直接恢复任一历史文件覆盖最新工作。

## 2. 状态与责任合同

| 事实 | 唯一 owner | 消费者 | 不允许的替代 |
|---|---|---|---|
| 有效 raw 可见极值 | 中立 `signal/display_ranges.py` | GUI、Batch、canvas 拟合 | 由抽点曲线或固定工程量 epsilon 决定真实性 |
| 频谱刷新、最终 Y、缓存生命周期 | `PgLineCanvas` 与既有 `spectrum_display.py` | ViewBox、quality、export | 新的并行 auto-Y manager |
| 筛选前树上下文 | channel tree 快照与 generation | 同代 live tree | 显示文字 key / 永久缓存 Qt 节点 |
| 最终选中状态及呈现目标 | 控件自身；View 由 manager 确认 | signal 接收者、indicator | 外层旧请求在回调后覆盖新提交 |
| 本次 Batch 结果是否对应当前配置 | `BatchSheet` 结果 generation / stale | 标题、详情、复制 | 从结果对象内容临时猜测、修改 frozen rows |
| run/group/item 诊断来源 | 中立结果 DTO | 只读详情投影 | 有 item 就省略 run 诊断、归因到错误条目 |
| 分析 View 的持久意图 | `AnalysisViewState` 及协调层 | Canvas / project dirty | 控件私有字段成为第二份业务状态 |
| X 标签内容与生成来源 | `CustomXAxisSpec` 所在中立意图模块 | apply、View/project、Inspector | `label == channel` 作为新状态的来源事实 |

## 3. 必须满足的需求

### R01 · 自动范围对单位缩放保持正确（F01）

1. 自动 Y 每次 final flush 后必须包含当前 X 窗口内按既有有限性、有效性和边界线段规则得到的极值。padding 沿用当前中立算法。
2. `setYRange` 的 no-op 判断不得使用固定绝对工程量阈值掩盖真实变化。可采用规范化后的精确重复目标去重，或有明确相对/ULP 误差与极值包含约束的比较；选型由失败回归和实际 pyqtgraph 范围往返证据决定。
3. 数据乘以正的单位换算系数后，正确性应等比保持；测试至少覆盖 `1e-12、1e-6、1、1e6` 量级。不可为了去重容忍可见极值落到范围外。
4. 保持 empty、单点、常量、短数组、非有限 X/Y、NaN 间隙、重复/非单调 X、数值 dtype 的现有合同；新增 guard 不裁剪数组、不改变 shape、不跨无效区间连线。不兼容长度按既有显式错误处理，不用 `min(len(x),len(y))` 掩盖。
5. manual Y 不查询或拟合自动 Y；Home、历史、resize、View restore、复制/导出在最终范围与最终曲线一致后才完成。raw 数组、FFT 输出和导出数值不变。

### R02 · 树上下文恢复具备线性成本和身份安全（F02）

1. N 个 live 节点、K 个快照条目，恢复身份匹配成本为 O(N+K)，不得对每个快照身份从根扫描整棵树。
2. 优先使用一次遍历形成的局部复合身份索引；快照只保存必要的展开状态和视口锚点，不保存 QWidget/QTreeWidgetItem。
3. 保留完整 Qt.UserRole 身份，包括来源与通道；同名异源互不串扰。树重建、删文件、切 View 使旧 generation 失效，延迟回调不得作用到新树。
4. 清筛选恢复展示上下文，不改变通道勾选、可见曲线、附件范围或当前业务 View。
5. 叶节点不需要保存展开状态。锚点被删除时，按既有 scroll fallback；不抛错、不滚到另一个同名来源。
6. 检查 replace-file 展开恢复的同类扫描；仅在确认同样成本问题时复用局部 helper，不引入无关树模型重构。

### R03 · 选择呈现尊重最终已提交状态（F03）

1. 选择 owner 内部顺序：验证请求 → 提交有效模式及 checked 状态 → 投影 indicator 目标 → 发出原业务通知。
2. 同步通知内改选目标时，新提交权威；外层不得在通知返回后重新投影旧模式。通知内关闭/删除 owner 后不得访问被销毁 Qt 对象。
3. 实际状态改变发一次通知；重复点击 no-op；程序恢复 snap；off/reduced 不等待动画。用户输入来源在通知前消费，避免遗留至下一次程序更新。
4. 覆盖 TimeChartCard 布局/游标、FrequencyCursorCard 焦点目标、Toolbar、MethodButtonGroup、SegmentedChoice、PillSwitch 的同类边界；没有复现或倒序证据的 owner 只加适用回归，不为统一形式改写。
5. View marker 保留 request→manager confirm 合同。拒绝/延迟确认前不猜测最终 View；overflow、resize、reorder 仍按现有 snap 规则。
6. 动画启动与实际画出位移分别验收。不能通过 `processEvents()`、固定 sleep、整窗 repaint 或 animation.finished 驱动业务来补偿顺序错误。

### R04 · Batch 诊断投影完整且不混淆归属（F04）

1. `project_result_rows` 独立投影 run、group、item 的现存信息。items 非空不抑制 run warnings 或 blocked reasons。
2. row key 保留 generation、scope、身份和稳定序号；不靠显示标题合并同名来源。
3. run 诊断是独立范围；不复制到所有 item，不假造 file/method/output path。group 图片与 item 数据文件保留真实归属。
4. 同一 DTO 诊断只投影一次；文本恰好相同但来源不同不随意去重。原 DTO 不变，下一次运行替换 generation，旧行不混入新结果。
5. 详情查看与复制必须能取到完整诊断。未知原因保留明确占位，不根据状态猜测原因；路径不存在时继续沿现有不可打开反馈。

### R05 · Batch 配置变更与结果过期一次性提交（F05）

1. 有结果后，用户成功改变影响本次运行/输出的配置，立即将结果标为“上次运行结果”；结果 rows 与输出仍来自该次运行快照。
2. 覆盖输入源增删/逻辑来源、信号、输入范围、滤波启用和参数、FRF 配对、RPM、方法、分析参数、输出/布局/切片/统计及恢复默认值。
3. 在现有 Sheet 生命周期建立明确语义入口；若 InputPanel.changed 混合元数据与用户操作，应在 owner 边界区分原因或使用既有成功提交信号，不直接把所有 changed 等同用户修改。
4. 程序恢复、元数据加载、预览重算、运行进度和只读开关详情不产生虚假的配置变更。既有 `_suspend_user_configuration` 等事务必须成对结束，异常后恢复。
5. 相同配置的 no-op 不产生额外语义提交。过期标记应幂等，不触发 DSP 或自动开始新运行。
6. 在途编辑遵循当前锁定/可用性合同；若允许编辑，worker 输入仍是已冻结快照。不得把当前 UI 参数写回运行中的结果。

### R06 · 取消独立范围恢复入口（F06 后续产品决策）

1. 移除分析页面底部的范围状态条、“恢复参数范围”按钮及专用回调；不隐藏后保留无入口的恢复方法，也不保留空白占位。
2. Home 继续查看当前分析结果全图，保留参数面板的自动/手动设置。用户再次点击计算，按当前参数范围显示。
3. 保留逐轴 `viewport_origin`、View/project 的合法范围恢复、linked X、ChartOptions Apply 和计算入口的现有语义；取消 UI 不等于删除浏览意图或改动 DSP。
4. 移除专用状态提示刷新接线，同步 hints / quickref。原 F06 入口撤销后无需再维护其 dirty 修复；其他用户变更与 canonical digest guard 保持原合同。

### R07 · X 标签来源显式保存（F07）

1. 以 `auto` / `user` 的语义区分生成标题与用户标签；可选 legacy 状态仅用于旧 payload 迁移。具体字段命名统一放在 Custom-X 意图 owner，Inspector 不单独决定持久来源。
2. 用户明确 text edit 后为 user，即使内容与 channel 字符串完全相同；apply、capture、View 切换及项目 round-trip 不重新按字符串猜测来源。
3. 拖放/选通道自动生成的标签为 auto；切回 time 清除该自动通道标题。用户标签按既有产品合同保留。
4. 老项目缺 origin 时采用与已发布路径一致的兼容推断并明确记录；新 payload 写出真实 origin。不得将旧数据中不可知的手写来源宣称为可恢复事实。
5. 不改 source/channel 身份、PER_SOURCE_NAME / EXACT_SOURCE 匹配规则和默认 Time 标签逻辑。持久化有格式号时按实际 schema 规则做兼容扩展，并覆盖旧读新写。

### R08 · Section 与动效候选以一个当前合同集成（G02）

1. 先确定当前已提交 Toolbar 顺序与在途 motion/Section 状态；已完成内容不得继续标成待执行，也不得重新覆盖。
2. 动效时长采用所属任务已接受的值，集中常量、消费者测试、当前 Spec 语义一致；保留 dated 历史记录原值。不能仅删除 400 断言来掩盖未明确的合同。
3. FFT reveal 的 generation、exposed paint/geometry、hide/clear/close、capture pending 与 export flush 成对闭合；保持 150 ms quiet timer 和独立离散 settle。
4. time section deferred work 复用 TimeRenderGate，确认目标 View 对象身份，busy 时等待既有 gate 退出，切走/关闭取消；不阻断 UltraView 逐源同步。
5. prepared `(sig, fs)` 只在同一同步调用内借用，不跨事件循环或 View 缓存；缺源、空信号、blocked、manual/auto NFFT 的 facts 与原路径逐字段一致。

### R09 · 性能以可比较的自然绘制验收（G01）

1. 固定源、依赖、机器、QSS/字体、DPR、窗口、数据与探针哈希；测试期间变化则结果 UNVERIFIED。至少 5 次 warmup、30 次有效重复，基线/候选交错 A/B 并重复分组，报告冷/暖分开。
2. 同时记录 input、业务提交、driver start、首个位移 paint、首个正确目标内容 paint、最终几何/质量 paint、事件积压和 callback 耗时。没有 compositor 时间戳不宣称实际 FPS。
3. callback 微基准、强制 repaint 和自然 GUI 绘制单独报告；不能用 cache-hit 或 helper 耗时替代端到端。
4. 保留频谱原目标：相同场景 auto-Y P95 至少下降 30%，manual-Y P95 回退不超过 10%；同时报告 median/max、>16.7 ms 比例及事件积压。旧机器绝对值仅作历史对照，新验收按可比基线比例判断。
5. 保留 Section 原 20% time 改善目标；FFT 改善、time 改善、正确稳定质量帧分开报告。未达到即 partial，不能因任务时间耗尽重写阈值。
6. 必须先通过正确性；缓存命中时不重复扫描/setData，manual Y 不做 Y 查询，停止/导出时最终数据与范围正确，无新空帧/跨 NaN 造桥/峰值越界。

### R10 · 跨 UI 与交付证据完整

1. 验收覆盖时域、FFT、时频、阶次、FRF，包含分屏焦点、切片开关、Home/历史、View 切换、项目保存重开、立即复制/导出及关闭。
2. 以改变 owner 的 focused 和边界 gate 为默认。仅在稳定集成确实横跨多个边界或发布验收需要时，指定一个全套 owner；不并发 full gates。
3. offscreen、真实 Cocoa 控件、完整前台 TraceLab、客户文件、Windows 源码与 Windows Full/Lite frozen 各自标 PASS/FAIL/UNVERIFIED，不互相代替。
4. 新增/调整用户可见交互文案同步 `ui/hints.py` 与 `ui/quickref.py`。普通修复不因文案需要而升级整个产品版本。

## 4. 验收场景与追踪

| ID | 场景与通过标准 | 需求 | 任务 |
|---|---|---|---|
| A01 | tiny Linear 平移到百倍高幅区，flush 后极值全部可见；Cocoa 截图主图不空 | R01 | T1 |
| A02 | 等比单位换算、常量/单点/空/NaN/重复 X，范围合同稳定；manual Y 零查询 | R01 | T1 |
| A03 | Home/历史/resize/View 恢复/立即导出，raw 与最终显示一致 | R01 | T1/T8 |
| A04 | 500/1k/2k/10k 节点，身份读数按线性增长；同名异源正确 | R02 | T2 |
| A05 | restore 排队期间 replace/remove/切 View/销毁，不写新树或改变 checked | R02 | T2 |
| A06 | 同步重定向布局/游标/模式，最后 checked、业务模式、indicator 一致 | R03 | T3 |
| A07 | 回调删除/禁用、快速 A→B→C、程序 snap、off/reduced、频率分屏焦点 | R03 | T3 |
| A08 | View 未确认/拒绝/busy 延迟前 marker 不移动，确认后身份一致 | R03/R08 | T3/T7 |
| A09 | run+group+item 并存、空项、blocked/cancelled、同文异来源，详情/复制完整 | R04 | T4 |
| A10 | 完成结果后逐项改变配置，全都正确标上次；程序投影/no-op 不虚假 stale | R05 | T4 |
| A11 | 无范围状态条及空白占位；Home 查看全图、计算按钮返回参数范围；View/project/逐轴恢复不退化 | R06 | T5 |
| A12 | 同名手写、异名手写、自动通道标签，apply/View/project/time 往返来源保真 | R07 | T6 |
| A13 | 缺 origin 的旧 payload 可读，新写可保真，跨源身份不受影响 | R07 | T6 |
| A14 | Section 快切/busy/关闭/capture/export，无 stale callback、无多次 settle | R08 | T7 |
| A15 | facts prepared 只取一次且缓存键/结果/诊断逐字段一致；缺源/短输入同样成立 | R08 | T7 |
| A16 | 生产样式 Cocoa 交错 A/B，频谱与 Section 原 P95 目标达标，无事件积压回归 | R09 | T8 |
| A17 | 五分区+分屏+切片+项目重开+客户数据+Windows 分别取得验收记录 | R10 | T8 |
| A18 | 每项 F/R/A/T/G 状态与证据一一对应；无历史结果冒充当前集成 | R10 | T9 |

## 5. 非目标与失败处理

- 不以行数拆文件，不建立统一所有 canvas 的基类，不给每条信号加 broad exception，不新增 `getattr(..., False)` 掩盖必需状态。
- 不修改真实文件数值、采样率或时间轴，不以缓存“优化”跳过诊断/dirty/保存/历史副作用。
- 不对性能缺证据填 0；不把 crash、timeout、skip 当通过。新性能措施若破坏正确性，先局部撤销该措施，保留回归和原始数据。
- 旧 payload 的标签来源不可逆恢复属于已知迁移限制；完整客户/Windows 验收无法执行时明确保留开放项。完成设计不等于完成修复或发布。
