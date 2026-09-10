# UI 与操作逻辑收口 Spec

日期：2026-09-10。状态：**设计完成，待实施验证**。基线：`29ab049c5932a5fb17b4478cb8fa8b0fb3cd6043`。

依据：[两日提交 Review](../reviews/2026-09-10-ui-interaction-two-day-review.md)。执行：[Hardening Plan](../plans/2026-09-10-ui-interaction-hardening-plan.md)。本文件规定后续实现，不表示相关缺陷已修复。

## 1. 目标、范围与明确决策

目标是让现有 UI 的用户输入、持久化意图、计算请求与可见反馈一致，修复 review 已复现的断点。保持现有 Qt 面板、方法页签、预设按钮和三栏结构；不另做一套视觉设计。

纳入：四个分析区的时间范围；单分析预设基准、差异、View/项目保存；Batch 有效目标数量、方法默认契约、禁用反馈；ZFD fixture 供应；对应的帮助、生命周期及平台验收。

不纳入：DSP 算法改写、渲染 ink 阈值重标定、MainWindow 大拆分、BatchRunner 重构、项目总 schema 重建、扩大 ZFD 格式支持、未获原文件支持的客户结果承诺、全局依赖升级。

本设计确定以下选择，实施不再反复询问一般实现细节：

1. 保留当前 Batch 新窗口默认 `time`；完整方案/current-view handoff 仍按各自已有优先级提供方法。需要 FFT 的回归显式选择 FFT。
2. “保留手动轴”后，基准表示目标预设的解析结果；实际保留的差异继续显示。不是把保留动作后的整个当前面板重新定义为目标。
3. 非法时间输入阻止局部范围提交；只能由明确的“全部”操作放弃它。勾选启用不是同意放弃输入。
4. 未编辑的控件投影不回写业务状态。显示四舍五入不改变计算值。
5. 参数等价但基准不同，是需要保存的用户变化；不需要重算。
6. 运行禁用和业务不适用共存，二者分别保留原因，恢复后重新计算 effective enabled。

## 2. 需求与发现映射

| ID | 必须满足的契约 | 关联 Finding | 实施任务 |
| --- | --- | --- | --- |
| R01 | 原始文本、数值区间、来源覆盖分层验证；非法输入不可静默回退 | F01 | T1/T2 |
| R02 | 计算范围选择对全部目标先验证后一次提交；取消无副作用 | F01 | T2 |
| R03 | 无用户编辑时精确范围在切 View/保存/恢复中不变 | F02 | T1 |
| R04 | 时间状态完整投影；来源修订身份可靠、清理对称 | F06/F07 | T1/T2 |
| R05 | 目标基准与保留轴后的应用结果分离 | F04 | T3 |
| R06 | View 恢复保留加载来源证据，支持旧 baseline 迁移 | F05 | T3 |
| R07 | 预设事务即时同步完整 View 状态并参与 dirty guard | F03 | T4 |
| R08 | Batch 数量直接来自有效规划，支持稀疏逻辑来源与 FRF | F09 | T5 |
| R09 | 标准/自绘/祖先禁用行为和像素一致，值与业务锁不丢 | F10 | T6 |
| R10 | ZFD 普通测试可重现，真实 corpus 的供应与结果明确 | F08 | T7 |
| R11 | Batch 默认及用户/程序事件契约统一，保留原运行判断 | F11及待证横展 | T5 |
| R12 | 平台、异常、帮助和验收证据分层，不用绿测替代真实接线 | 多项 | T6/T8 |

## 3. 状态所有权与依赖方向

| 状态/行为 | 唯一 owner | 其他组件的职责 |
| --- | --- | --- |
| 已启用分析范围 | `PaneState.time_range`（现有 pane 状态） | worker 读取；控件投影，不持久化显示值 |
| 未启用草稿、输入无效原因、来源复核标志 | `AnalysisTimeRangeController` / `AnalysisContext` | PersistentTop 提供用户输入，analysis mixin 编排目标 |
| 当前原始输入缓冲及是否真实编辑 | `PersistentTop` | controller 接收结构化事实，不导入 Qt widget |
| 时间轴替换/重建事实 | `io/file_data.py:FileData` | 签名只读获取运行期实例/轴修订信息 |
| 预设归一化、有效差异、目标解析 | `ui/inspector_sections/preset_state.py` 与已有 Contextual 参数 owner | PresetBar 协調一次加载事务；不复制另一套比较 |
| 每 View 的 params 与 preset_baseline | `AnalysisViewState`，通过 analysis bridge/现有 coordinator 写入 | PresetBar 仅持有当前投影；project serializer 序列化 |
| 项目是否未保存 | 现有 project dirty holder/digest | 接收成功用户事务；paint/projection 不标脏 |
| Batch 有效来源/配对/分组数 | 现有中性规划路径 | Sheet 在一次状态重算后投影，卡片不算乘法 |
| 控件 effective enabled | 业务适用性结果 + QWidget 祖先锁 | 自绘只读最终状态，不能清掉用户选值 |

保留已有 public imports、兼容 facade、信号消费者和 monkeypatch seams；任何新增状态必须显式初始化和对称清理。不得通过扩大 `test_main_window_state_ownership.py` 白名单安置新的跨 mixin 写入。

## 4. 时间范围契约

### 4.1 输入事实与提交顺序（R01）

把三个问题分开：

| 层 | 判断内容 | 失败的反馈/行为 |
| --- | --- | --- |
| 文本层 | 两个编辑框当前原始文本是否可完整解释，包括 `-`、空文本、未完成指数等 intermediate 状态 | 保留输入意图并显示待修正；不得先被 `interpretText()` 回退后当有效旧值 |
| 区间层 | 两个有限标量，形状恰为一对，`lo < hi` | 区间无效；等端点、倒序、NaN/Inf 不解释为 full |
| 来源层 | 当前目标的物理来源范围是否覆盖 requested，角色/来源是否齐全 | 给出不能使用局部范围的目标及原因；不能进入 worker 后才默默裁空 |

`PersistentTop` 在真实 `textEdited`/用户步进发生时记住输入 origin、revision 与原始文本。Qt 失焦/Return 默认校正之前的无效意图必须可被查询；只在 editingFinished 后读 `value()` 不足以满足要求。

兼容保留 `range_edited(float, float)` 的有效提交语义；增设明确的无效输入通知/状态查询，不能用 `0,0`、NaN 或旧 tuple 假装完整文本。该查询至少区分 unchanged、valid edit、invalid edit，并带当前编辑 revision。具体 Qt 缓冲记录留在 PersistentTop，不由中性 controller 引用控件类。

程序调用 set_range_values/范围来源投影/项目恢复应同步控件的已投影 revision，阻断用户事件；一次键入后同时发生失焦和 Compute flush 只提交一次。无效文本如果被 Qt 视觉回退，状态仍必须清楚指出尚未接受，不能继续把旧值作为新提交；优先恢复原始可编辑文本。

### 4.2 用户动作状态表（R01/R03/R04）

| 之前 | 动作 | 之后 | 模型/计算 |
| --- | --- | --- | --- |
| full，无草稿 | 无编辑 focus-out、切 View、保存 | full | 不写 `time_range`，不创建草稿 |
| full | 完整有效编辑 | draft | 显示“范围已调整，尚未启用”，不提交计算 |
| full/draft | 非法或未完成编辑 | invalid draft | 保留意图、错误可见，不转 full |
| draft，来源覆盖有效 | 勾选启用 | enabled | 原子写精确值；使用现有计算触发策略，不额外提交任务 |
| invalid draft | 勾选启用 | invalid draft | 阻止启用并回投 checkbox；保留输入；不能改为来源全范围 |
| full，无草稿 | 勾选启用 | enabled source range | 写来源精确边界；覆盖不足的多来源统一局部范围应先反馈，不能盲用展示 envelope |
| enabled | 有效用户编辑 | enabled 或 needs-review | 使用同一验证；不把旧范围悄悄丢掉 |
| enabled | 无编辑 capture | enabled | tuple 完全不变，包含超过显示精度的尾数 |
| 任意 | 明确“全部”或取消启用 | full | `time_range=None`，清除相应草稿/复核状态 |
| 任意 | 对确认框选择取消 | 原状态 | 无 pane 写入，无 dirty，无新任务 |

这里的 cancel 是确认事务的取消；用户此前已提交的真实编辑不凭空撤销。默认“全部”是语义 `None`，其可视区间从来源动态计算，不把采样显示值存入项目。

### 4.3 计算前事务（R02）

处理顺序固定：flush 当前真实编辑 → 冻结本次目标 pane 与来源签名 → 获取 bounds 与验证结果 → 显示必要选择 → 验证全部 choice candidate → 一次写入 → 投影 → 交给现有提交路径。

1. 普通分析保持原有目标范围；一次操作覆盖其原本应计算的 pane 集合。FRF 仍按当前请求的焦点/既有 pane 策略，不因共享 controller 擅自扩大。
2. 对所有目标先构造 candidate 列表。任一无效时不写任何 pane；禁止循环写入后遇到第二个错误才 return False。
3. 对话框中“使用局部”只在所有所需局部区间通过文本、排序、来源覆盖检查时可用。无效项应给具体 pane/来源提示。“全部”仍要满足来源本身可用，不是绕过丢失输入的后门。
4. 对话框等待期间来源签名改变，丢弃 candidate 并重新评估；不提交旧版本的区间。
5. FRF requested/effective 区间、dirty 标志与缓存失效一次同步；无重复 progress/result recording，也不绕开既有 job owner。
6. preflight 不修改原始信号、不重建时间轴、不补 Fs、不通过 min(X,Y) 截断掩盖不一致。

### 4.4 数值、来源与精度边界（R03/R04）

- 精确值来自 PaneState 或真实输入提交；`DISPLAY_ENDPOINT_TOL` 仅用于“显示起来是否等于 full”的交互判断，不用于截取、持久化舍入或签名身份。
- 空/缺失时间轴返回 unavailable。单点/重复端点不可组成有效局部区间；分析所需最小样本数由既有分析验证负责，UI 不自造第二套 DSP 门槛。
- 有限值、形状和来源覆盖失败必须可观察。非均匀时间轴仍走现有 analysis-only preparation；该功能不得修改源数据或发明采样率。
- FFT/FFT-vs-Time full overlay 保留每条来源自身全时段；展示 envelope 不证明所有来源覆盖同一局部请求。
- FRF full 由真实输入/输出可用交集派生；方向交换改变身份。Order 的展示全范围来自信号轴，RPM 对齐由现有 owner 验证，不在 UI 复制算法。

### 4.5 来源修订与反馈投影（R04）

运行期签名组成：section、排序后的 composite `(fid, channel)`、有向角色、来源实例令牌、轴实例/修订令牌以及已有必要摘要。不能只用 `(t0,t1,n)`。

当前产品的时间轴赋值集中于 `io/file_data.py`。优先在该 owner 初始化并维护 `time_axis_revision`，将来源对象/轴对象替换也计入运行期签名；不扫描整数组。后续若新增原位修改，必须在同一 owner 更新 revision。令牌不序列化、不以显示名称替代、不添加全局 cache。

同一组来源重排不使草稿失效；来源实例替换、时间轴修订、FRF 角色交换、Order RPM 模式/来源改变必须使旧草稿失效或使已启用范围进入复核。全范围重新派生；不能用新来源当前值反填旧草稿身份。

投影必须消费 `kind`、`needs_review`、`errors`、`notes`：复核状态优先于普通 enabled；invalid/unavailable 给明确原因；overlay 提示保留“各信号使用自身全时段”。每次落定的状态转换只调用一次最终投影，controller 不直接操作 QLabel。

切 pane/View 的草稿以 `(section, view_id, pane)` 隔离；删除 View、清空项目、关闭来源、恢复项目必须按现有生命周期移除过期引用。程序恢复不 mark dirty、不启动意外计算。

## 5. 预设基准与事务契约

### 5.1 目标与应用结果（R05）

继续使用 `_collect_preset()` 的规范比较面。不能把含信号、Fs、effective NFFT 的 `compute_params/current_params` 混入预设差异；完整 View 持久化仍使用其原有 complete params 表面。

加载事务有三个不同值：

```text
before = 当前规范预设参数
target = 按现有 apply 语义将槽位补丁解析到 before 后的完整目标
applied = target 按用户“保留坐标”选择合并兼容手动轴后的最终值
baseline.params = target
```

target 解析必须与各 Contextual 的真正 apply 语义一致：别名、Auto NFFT、时间窗/重叠形式、单位、轴 auto/range、未出现的 RPM/dB 字段都要遵循原 owner。不能无条件 `dict.update()` 当作语义解析，也不能通过让真实面板 apply 两次来测 target。

在 `preset_state.py` 增加有范围的纯解析能力；需要 Contextual 特有语义时，由其现有参数 owner 提供规范化事实。只抽取这次证明重复或缺失的规则，不建设通用 schema 框架。

手动轴保持单位兼容检查；不兼容时提供既有清楚选择，不把 dB 范围带进 Linear。同一目标在保留后确有差异才亮黄点；没有差异就不亮。参数差异与坐标差异仍分别使用现有两种指示。

### 5.2 加载来源证据（R06）

嵌套 baseline 采用 version 2，外层 `AnalysisViewState` schema 9 和项目总格式不因这次附加字段另起一套版本。

```json
{
  "version": 2,
  "kind": "fft",
  "slot": 1,
  "display_name": "均衡",
  "params": {"window": "hann"},
  "source_payload": {"window": "hann"}
}
```

示例只展示形状，真实 `params` 必须是该 kind 完整的规范目标比较面，不能只存示例的一个字段。`source_payload` 是成功加载时槽位有效补丁的深拷贝，用于判断后来槽位是否更新；其比较使用已有规范值语义。display_name 是加载时名称快照。

| 读取情况 | 行为 |
| --- | --- |
| v2 结构有效 | 恢复 target 和加载 source_payload，当前槽只用于比较是否变化 |
| v1 结构有效 | 保留旧 params/name/slot，不从当前槽捏造 source_payload；来源版本为 unknown |
| 旧项目无 baseline | 维持既有完整匹配才可推断规则；推断不声称观察到了历史加载来源 |
| baseline 损坏/未来不支持版本 | 记录具体 warning，按现有兼容策略降为无基准；不阻止其余项目数据打开 |

v1 的旧 params 有可能是当时“保留后结果”，无法逆推出真实目标。迁移不得猜测；下一次用户成功加载才建立 v2 明确语义。来源 unknown 时不把同槽点击当肯定 no-op；可提示“来源版本未知”。

`analysis_view_state.py` 的结构校验和 `preset_state.py` 的语义校验都要支持 v1/v2；前者保持不导入 inspector/UI 的边界。deepcopy 保证两个 View 不共享 mutable baseline。相同名称内容变化、改名、槽位清空/恢复内置均能明确表示。

### 5.3 成功提交与项目 dirty（R07）

一次预设加载：读取 before/target/source → 验证 → 用户已有轴冲突选择 → 生成 applied → 一次 apply → 成功后提交 baseline → 发出一个明确的事务完成事件 → analysis owner 同步 complete params+baseline → 标记一次用户变更 → 一次最终 UI 投影。

新增事件必须表达“事务已成功”，可命名 `preset_committed`；它覆盖参数相同但基准不同的加载、显式建立新基准的保存等动作。不得靠伪造 paramsChanged 或定时扫描 baseline 实现。

analysis bridge 提供同步完整 View 载荷的现有入口；不要给 PresetBar 传 MainWindow，也不要让 widget 写 manager。Contextual 可转发信号，绑定由现有 AnalysisContext/window 接线 owner 完成。

需要区分两条通道：

- compute/display 参数差异仍走现有失效策略；没有有效参数差异就不重算。
- baseline/name/source snapshot 的持久化差异走 View 同步与 dirty。它不依赖第一条通道是否发信号。

参数变化信号若在事务完成前发生，不得把半完成载荷先写入模型并重复标脏；使用已有 apply guard 在成功边界统一同步。程序 `set_baseline`、项目打开、View 恢复/推断不发用户提交事件。

取消选择：before、baseline、dirty revision、任务计数均不变。数据/用户失败：给出原因并回滚。程序错误：不得以 `_collect_safe()=={}` 伪装成功提交；可执行必要回滚，但必须记录上下文并通过既有异常机制保持可见。

显式保存成功后，再进行等参数跨槽加载，离开保护必须看到 dirty；取消关闭保留当前 View；保存/重开恢复新 baseline。直接点击完全一致且来源已知未变的当前槽才可 no-op。

## 6. Batch 事实与交互契约

### 6.1 数量与分组（R08）

Sheet 的 pipeline recompute 获取一次已解析逻辑来源及目标策略，复用现有中性 planning 路径建立可读的数量事实。卡片仅接收对应分组的输出数量/有效性，不接收两个裸数量后自己相乘。

| 场景 | 卡片/预览要求 |
| --- | --- |
| s1=A/B、s2=A/C，available，选 B/C | none 为 2 个有效目标；不能显示 4 |
| common 策略下选双方不存在的公共目标 | 显示 0 或明确无共同目标，与 planner 一致 |
| 同一物理文件拆成多个逻辑来源 | 按 logical source identity 与各自 channels 计数 |
| 相同显示名、不同 fid | 不合并身份，不因为 label 相同少算 |
| 按 source/channel 分组 | 显示有效规划生成的组数；不把无有效目标的来源算成图片 |
| FRF | 按当前有效 input/output pair 与原有分组支持规则，不使用普通 signal 乘法 |
| probe pending/失败、未完成配对 | 不展示看似精确的错误结果；pending 显示待确定，失败指出来源 |

若既有 planner 只在 run/preview 才暴露组数，可抽取其已有只读规划步骤；不得启动 BatchRunner、render 或完整 DSP 来画卡片。输出选项关闭时明确区分“分组示意数”和“本次实际导出数”，不能继续在一处写“输出图片”而实际不导出。

保留 `seed_source_channels()` 合约。卡片、底栏、预览和运行前计划对同一 snapshot 使用同一 facts；失效时一起刷新，禁止分别重算出不同答案。

### 6.2 默认与操作 origin（R11）

新建普通 BatchSheet 默认 time；当前分析 handoff/完整方案显式方法照既有优先级应用，不被初始 time 覆盖。恢复输出偏好不伪造用户已选择方法，也不清空选择。

方法 activation 与 methodChanged 分开：同方法用户点击可以推进轻量引导，但不重置参数、不重复业务 apply。仅程序变化、probe completion、偏好恢复、布局变化不被计为首次用户配置。成功用户导入方案可以计为用户配置；取消/失败不计。

引导是只读建议，不是新增 run eligibility。先以真实回调验证现有通用 changed 信号是否误触；有误才增加明确 origin/短事务 guard，不把所有 `changed` 全仓替换成新框架。

需要特定分析方法的测试显式设置；锁定测试以动作前状态为基线，并断言 disabled 操作后值/信号/输出快照均不变。独立默认测试防止再次漂移。

### 6.3 有效禁用与自绘（R09）

effective enabled 同时考虑：当前分析方法是否适用、输出开关、Auto/Linear 模式、来源是否齐全、运行/预览锁和祖先禁用。

- `_PresetCard`、`_GroupingCard` 标题、选中圆点、描边与公式使用 shared disabled 颜色；QStyle 背景禁用不意味着手写 QPainter 文字自动禁用。
- checked 状态在禁用时保留并可辨认，但不使用正常可点击强调色。示意图的类别颜色若需保留语义，应统一降低对比，并与操作强调区分。
- 鼠标、键盘、滚轮不能改变 effective-disabled 控件；变化信号不发出。恢复运行锁后，仍业务不适用的控件保持 disabled。
- 适用性恢复时原值回来，不替用户选择默认值；项目/preset 不持久化临时 disabled/run 状态。
- 不扩大整张表单禁用来回避细粒度规则。单分析“管理参考目录”与“当前 dB 参数编辑”分别判断，不因 Linear 一概禁用管理入口。

布局以真实字体和控件 geometry 为准。窄列标题的 offscreen 字体差异先校准测试屏幕/字体；不能通过全局缩小字号消除一个环境中的 1 px 断言。小屏幕仍应夹取窗口并保证底栏可达。

## 7. ZFD 验证供应契约（R10）

默认套件不依赖 `.state/` 或开发者 Downloads 下的本机文件。保留目前的合成 ZFGE2 builder，覆盖长计数、截断、错误元数据、float32 值、dt/t0、record 边界、重复名与多来源适配。

真实 corpus 使用环境变量 `TRACELAB_ZFD_CORPUS_ROOT` 提供根目录，独立必需 job 设置 `TRACELAB_REQUIRE_ZFD_CORPUS=1`，至少有受版本控制的小型 manifest：稳定样本 ID、相对路径、SHA-256、profile、期望来源/通道/单位/样本数/时间和值证据。真实数据能否进入仓库取决于可再分发条件；不能为了让测试绿而默认加入大文件或客户数据。

普通开发 gate 无 corpus：真实样本项明确 skip，合成及边界仍必须运行。显式 corpus gate：manifest、任何必需样本或 hash 不匹配都 fail，不能 skip 成功。二者在报告中分开计数。

既有真实 A4 元数据断言保留，并补独立数值证据。合成数据按构造公式验证全部输出值和时间轴；真实样本依受控基准核对值/摘要与容差，区分 float32→float64 的表示变化。只比较两个共享同一 parser 的入口一致，不足以证明 parser 正确。

不得顺带改变支持 profile、容忍损坏记录或发明时间轴。本次无法验证原始客户长文件，验收保持 UNKNOWN，直到该文件独立跑通并留下结果。

## 8. 视觉、帮助、异常与证据（R12）

既有 hover 和 axis metrics owner 保持；针对相关修复跑原 owner tests，再补最终真实几何/像素验收。不要用 QSS token、planner 宽度或 artifact parity 替代字形可见性。

需要新增/修正文案时同步 `ui/hints.py` 与 `ui/quickref.py`：非法范围如何恢复、保留轴与目标基准的关系、来源版本未知/已更新、Batch 待确定数量和禁用原因。技术字段名不得泄漏到用户流程。

只检查此次新增/直接触及的宽泛 catch：用户/数据问题给明确反馈；Qt 已销毁对象可按现有 teardown 合约窄捕获；意外编程错误不能静默当成 empty/full/成功。热路径日志使用现有节流，避免每帧重复。

平台分层：

| Gate | 能证明的范围 | 不能替代 |
| --- | --- | --- |
| 纯函数/Qt offscreen | 状态、信号、数值、结构及受控几何 | Cocoa/Windows 实际字体和窗口行为 |
| Cocoa 独立 widget | 原生图形路径上的控件 geometry/pixels | 用户当前完整工作流、Windows |
| 前台 TraceLab walkthrough | 真正用户入口和稳定窗口交互 | Windows 新冻结包 |
| 源码 import/build/help | 包装路径、依赖、版本表面 | 冻结可执行程序能运行 |
| Windows Full/Lite frozen | 两种新包实际安装/打开/操作 | 未提供客户文件的业务验收 |

## 9. 验收案例

| ID | 场景与必须观察的结果 | 需求 |
| --- | --- | --- |
| A01 | 输入 `-`/未完成文本，失焦与 Compute 两种顺序都阻止旧值计算；恢复原值或明确全范围才继续 | R01 |
| A02 | 8→2/2→2/非有限输入后勾选不会得到 `(0,10)`；无任务提交 | R01 |
| A03 | 来源 0–10，输入 20–30/部分越界；local 不可用，明确 full/cancel 行为 | R01/R02 |
| A04 | 两 pane 中一个有效、一个无效；操作失败/取消两个都不被部分改写 | R02 |
| A05 | 末点 10.00049，启用后无编辑切换/保存/重开，精确边界及应保留末样本不变 | R03 |
| A06 | 真实编辑立即显示 draft；enabled 复核/invalid/unavailable/overlay notes 与状态一致 | R04 |
| A07 | 同首尾/点数轴替换、来源实例替换能改变签名；普通来源重排不改变；角色交换改变 | R04 |
| A08 | 草稿在 View/pane 间隔离；删除/clear/open 后没有旧引用或幽灵提示 | R04 |
| A09 | 手动 X=1–5，加载目标并保留：目标槽高亮，轴不同才黄点；再次加载能实际执行 | R05 |
| A10 | 部分补丁不改变 RPM/dB 等未拥有字段；单位冲突安全；四种分析 target 与真实 apply 对齐 | R05 |
| A11 | 槽同名重写、改名、删除后切 View/保存/重开，历史来源证据和提示仍准确 | R06 |
| A12 | v1/v2/无 baseline/损坏 baseline 的恢复可解释，深拷贝，无错误迁移“历史来源” | R06 |
| A13 | 已保存项目等参数跨槽加载即 dirty；保存重开保留新基准；取消关闭不丢 | R07 |
| A14 | 预设取消/应用失败不改基准；成功一次提交；programmatic restore 零 dirty、零额外任务 | R07 |
| A15 | 稀疏逻辑源、common/available、同名 fid、split file 的卡片=planner=预览分组 | R08 |
| A16 | FRF 有效/半配对、pending/失败来源不显示虚假确定数量；关闭图片输出文案明确 | R08 |
| A17 | 自绘卡直接/祖先禁用：鼠标键盘滚轮零变更，Cocoa/Windows 无 active 操作色，保留 checked | R09 |
| A18 | preview/run 成功、失败、取消后仅适用控件恢复，原值保留 | R09 |
| A19 | 普通新建默认 time；handoff/preset 保留指定方法；同方法点击不重复业务 apply | R11 |
| A20 | probe/偏好/程序恢复不伪装用户选择；用户导入成功与取消分开；guidance 不改变运行判断 | R11 |
| A21 | 无 `.state` 的新 checkout 正常 gate 可执行；显式 corpus 缺失必需文件 fail；六样本独立记录 | R10 |
| A22 | 合成长记录完整数值与时间通过；真实客户长文件有无分别报告，不由旧 A4 替代 | R10 |
| A23 | 字体/屏幕已知前提下首显/重绘/改轴/hover 边缘像素可见；小屏幕底栏可达 | R12 |
| A24 | 数据错误有动作建议；故障注入的编程错误不被 empty/full fallback 吞掉；hints/quickref 一致 | R12 |

关闭条件：R01–R12 的对应行为门禁通过；A01–A22 有明确当前证据，平台项按实际执行分别列 PASS/UNKNOWN。若要求发布，Windows frozen 与必要前台验收也必须完成，不能把 UNKNOWN 写成发布通过。本次仅完成设计文档，不产生这些实现完成声明。
