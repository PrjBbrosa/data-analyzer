# TraceLab v8 稳健性硬化与 UltraView 精致化规格

- 状态：Draft / implementation-ready
- 日期：2026-08-14
- 基线：`main@3b2d8cde`
- 适用版本：v8.x 后续修订
- 对应实施计划：`docs/analyzer/plans/2026-08-14-v8-review-hardening-and-ultraview-polish-implementation.md`
- 相关既有规格：
  - `docs/analyzer/specs/2026-08-14-ultraview-p3-canvas-interaction-spec.md`
  - `docs/analyzer/specs/2026-08-14-ultraview-miro-narrow-rail-spec.md`
  - `docs/analyzer/specs/2026-07-23-blf-dbc-crc-interaction-performance-spec.md`

## 1. 背景与结论

近期提交完成了 UltraView 多 Board、自由网格、预览缓存、项目恢复、CAN 日志解析与 v8.0.0 版本同步等大块能力。当前实现总体架构方向可继续沿用，但 review 发现三类需要在继续扩展前收口的问题：

1. **数据可信度问题**：BLF/DBC 的有限抽样结果被外推后以“精确帧数”展示；ASC 快速解析回退时进度可能倒退；BLF 公共 API 声称返回 pandas `DataFrame`，实际返回不完整的惰性类 DataFrame 对象。
2. **交互契约不完整**：UltraView 低缩放 LOD 没有真正进入“仅标题”状态；普通拖放可能弹确认框、改变邻卡尺寸或让卡片在边界处自动长大，破坏直接操控的可预期性。
3. **视觉状态表达含混**：分析类型在低缩放时丢失；布局模式与面板打开共用同一种 active 外观；画布无需滚动时仍显示 minimap；底部与选中态控制密度偏高。

本规格不推翻现有架构。它保留惰性 ZOH、PreviewStore、稳定 `UltraViewRef`、自由网格离散占位与原子项目保存等已验证方向，并对数据契约、进度语义、拖放规划和视觉状态做窄范围硬化。

## 2. 目标

### 2.1 必须达成

- 所有“精确值、抽样值、估算值”在模型、排序、日志和 UI 中分开表达。
- BLF 的惰性存储继续避免整表 ZOH 展开，同时公共返回类型与实际行为一致。
- ASC 快速解析回退全程进度单调，用户能看见回退原因，不出现假 100%。
- UltraView 在 55% 和 35% 等低缩放下仍能识别卡片分析类型，并真正执行三级 LOD。
- 普通移动不改变任何卡片尺寸；普通缩放只改变被缩放卡片尺寸。
- 拖放过程不弹模态确认框，提交前能预览最终落点和受影响卡片；失败时明确拒绝。
- 模式、面板、选中、同步过期、处理中等状态各自有明确视觉语义。
- 不改变分析数值、源文件/通道复合身份、预览摘要和项目持久化语义。

### 2.2 期望改善

- 空间充足时减少不必要的 minimap、重复状态条和图标岛。
- 让 800、1280、1440 宽度下的控制密度保持稳定，常用动作更靠近选中对象。
- 将偶发依赖全局鼠标状态的定时器逻辑改为可测试、由组件自身交互生命周期驱动。

## 3. 非目标

- 不重写 BLF/ASC 解析器，不在本轮实现完整 pandas 协议。
- 不把 BLF 惰性帧立即替换成稀疏矩阵、Arrow 或其他存储后端。
- 不改变 DBC 信号计算、bit decoding、单位转换或分析算法。
- 不重新设计 PreviewStore，不把 UltraView 变成第二套分析计算入口。
- 不改变 `UltraViewRef` 的稳定身份，不用显示名替代源/通道复合键。
- 不在本规格中增加协作、云同步、无限画布或任意角度旋转。
- 不以单次 offscreen 截图代替真实 Cocoa 前台验收，也不以源码检查代替 Windows frozen 验收。

## 4. 术语与不变量

### 4.1 CAN 探测术语

- **精确总量**：完整顺序扫描可直接计数的帧数、帧 ID 数。
- **发现样本**：用于尽快覆盖不同帧 ID、提取候选信号名称的小集合；不用于估计总体解码率。
- **统计样本**：在完整文件位置域上均匀或分层抽取的、可说明抽样方法的集合。
- **样本命中**：统计样本中能被 DBC 找到消息定义的帧。
- **样本解码成功**：样本命中后实际完成解码的帧。
- **估算值**：根据统计样本外推的比例或区间，必须带“估算/抽样”标签。

### 4.2 UltraView 交互不变量

- `move`：所有卡片的 `col_span`、`row_span` 在提交前后完全不变。
- `resize`：只有 mover 的 span 可变化；被推动卡片只能平移。
- `cancel/reject`：卡片集合、位置、尺寸、z-order 和 undo 栈均不改变。
- 一次手势最多产生一个 undo command；自动位移和 mover 变更一起原子提交。
- ghost 是将要提交结果的预览，不是仅表示鼠标位置的装饰。
- 低 LOD 只改变呈现，不改变卡片逻辑矩形、选择、拖拽、键盘焦点或持久化数据。

### 4.3 数据与渲染不变量

- 无用户明确触发时，UltraView 不重新运行 FFT、阶次、时域统计或其他分析计算。
- 同一物理文件展开出的不同逻辑源继续以复合身份区分。
- 任何优化不得用 `min(len(x), len(y))` 静默掩盖 X/Y 不一致。
- 预览摘要、digest、源 freshness 与项目恢复结果在 UI 重排后保持一致。

## 5. 产品与技术决策

### D1. DBC 探测结果采用“精确事实 + 抽样事实 + 估算比例”模型

`BlfDbcProbe` 不再用一个 `decoded_frame_count` 同时表示真实计数和线性外推结果。新模型至少表达：

| 类别 | 建议字段 | 语义 |
| --- | --- | --- |
| 精确 | `total_frame_count` | 完整扫描得到的 CAN 数据帧总数 |
| 精确 | `total_frame_id_count` | 完整扫描得到的唯一帧 ID 数 |
| 精确 | `matched_frame_count` | 若完整扫描阶段能无额外解码成本判断，记录 DBC 中存在定义的帧数；否则为空而非伪造 |
| 样本 | `decode_sample_count` | 实际进入统计解码样本的帧数 |
| 样本 | `sampled_matched_frame_count` | 样本中存在消息定义的帧数 |
| 样本 | `decoded_sample_count` | 样本中真正解码成功的帧数 |
| 派生 | `sample_match_ratio` | 样本命中率，分母为 `decode_sample_count` |
| 派生 | `sample_decode_success_ratio` | 样本解码成功率，分母和异常处理必须明确 |
| 派生 | `estimated_decoded_frame_ratio` | 可选估算比例；只在统计样本满足约束时提供 |
| 诊断 | `sampling_strategy` / `sampling_complete` | 抽样策略与是否完成，便于 UI、日志和测试判断 |

约束：

- 发现样本与统计样本分别构建，前者不能混入总体比例的分母。
- 统计样本应覆盖文件前、中、后段，不能只取前 8192 帧后线性放大。
- 如取消、截断、文件损坏或样本不足，估算字段为空并给出原因。
- 可以保留旧属性作为一版兼容只读别名，但它必须明确标记 deprecated，且不得继续供 UI 展示或新排序逻辑使用。
- UI 使用“抽样解码 `A/B`（`x%`）”或“完整匹配 `A/B`”，不得把估算值显示成“帧 `A/B`”的精确计数。

### D2. 有界候选集内不因第一个 sampled-strong 提前停止

- 结构预筛仍负责限制成本，最多对排序靠前的 3 个候选做内容探测。
- 除用户取消外，进入该有界集合的候选全部完成同等策略的探测，再统一排序。
- `strong` 只是最终证据等级，不再作为循环 `break` 条件。
- 排序优先使用可比较的精确覆盖和样本比例；并列时再使用结构分、路径邻近度和稳定文件名顺序。
- 未匹配和多个接近候选继续向用户呈现选择，不静默把抽样第一名当作确定答案。

### D3. BLF 返回显式 `ChannelFrame` 契约，保留惰性 ZOH

新增 UI-neutral 的 `mf4_analyzer/io/channel_frame.py`，定义项目真正需要的列帧协议。建议名称为 `ChannelFrame`，最小能力包括：

- 列名枚举与列存在性判断；
- 按列获取一维数据；
- `drop_columns(names)`，只支持明确的列操作；
- 行数、时间列/索引语义和 dtype 说明；
- `to_pandas()` 或 `to_dataframe()` 显式物化；
- 是否惰性、物化成本和 ZOH 语义可被诊断。

迁移规则：

- `DataLoader.load_blf()` 的文档、类型和错误信息改为返回 `ChannelFrame`，不再承诺 pandas `DataFrame`。
- 提供命名明确的兼容入口，如 `load_blf_dataframe()`，让确实需要 pandas 的调用方主动承担物化成本。
- 当前 `LazyZohFrame` 可成为实现类或兼容别名，但不得继续模拟未实现完整的 pandas 行为。
- `drop(axis=0)`、任意 pandas kwargs 等未实现语义应明确拒绝，不能返回 `self` 造成静默错误。
- `SourceAdapter`、`FileData` 和加载器消费者通过契约/帮助函数判断能力，不用类名或含糊的“必须为 pandas DataFrame”错误兜底。
- 保持按需列物化：只访问时间列或少量信号时，不展开无关信号的完整 ZOH 数组。

### D4. ASC 回退采用预检与单调进度状态机

优先在快速解析前读取有界前缀做格式预检。已知不支持的格式直接进入 python-can 兼容路径，避免先扫大量字节再从头重读。

统一结果建议使用 `AscParseOutcome`：

- `backend`: `fast` / `python-can`；
- `fallback_reason`: 枚举化原因；
- `bytes_consumed_before_fallback`；
- `warning` / `diagnostic_context`；
- 最终帧数与取消状态。

进度要求：

- 外部进度从 0 到 100 单调不减。
- 预检、fast parse、fallback retry 使用同一阶段映射；晚回退时切换成“兼容解析重试”不确定态或保留高水位，不能跳回低百分比。
- 只有最终结果已交付时才能报告 100%。
- 回退原因必须进入节流诊断和用户可见状态，不能只在内部吞掉。

### D5. UltraView 实施真实三级 LOD

LOD 由统一阈值函数驱动，Card、Page 与测试不能各自硬编码第二套阈值。

| 有效缩放 | 呈现 | 必须保留 |
| --- | --- | --- |
| `>= 60%` | 完整卡片 | 标题、类型、信任状态、预览、footer、必要动作 |
| `40%–59%` | 紧凑卡片 | 标题、类型、信任状态、预览；隐藏 footer 与低优先动作 |
| `< 40%` | 标题卡 | 标题、分析类型/图标、信任状态；隐藏预览 body、footer、正文动作和孤立占位区域 |

逻辑命中矩形、选择框、拖拽柄和键盘可达性不随 LOD 改变。过渡时不改变持久化状态，也不触发分析计算。

### D6. 分析类型在卡片头部持续可见

- 在 header 增加短类型 chip 或等价图标/标签，显示“时域、FFT、阶次、统计”等稳定类型。
- 用户标题继续独立保存；不得为解决通用 `View 1` 标题而自动重命名用户数据。
- 类型 chip 在完整、紧凑和标题卡三种 LOD 中都存在，可在极窄卡片中退化为带 tooltip 的图标。
- stale、missing、loading 等信任状态与类型视觉分离，不能用同一个颜色承担两个含义。

### D7. Minimap 只在确有导航价值时出现

Minimap 显示条件同时满足：

1. 当前为 free-grid；
2. board 内容范围超出 viewport，存在实际水平或垂直滚动范围；
3. 不处于会遮挡关键 modal/popover 的状态。

内容完全落入 viewport 时隐藏 minimap。窗口 resize、zoom、模板切换、卡片移动/缩放和 Board 切换后都重新计算，但用现有调度合并，避免每帧抖动。

### D8. 区分 `modeActive` 与 `panelOpen`

- 布局按钮持续表达当前布局模式，属性建议为 `modeActive`。
- 控制面板展开只表达当前浮层/侧栏状态，属性建议为 `panelOpen`。
- 两种状态在颜色、填充或轮廓上至少有一项明确差异，不能同时呈现为两个同等强度的“选中主按钮”。
- 关闭面板不改变布局模式；切换模式必须更新持久化/undo 契约并关闭或刷新不再适用的面板内容。

### D9. 普通拖放改为非模态、可预演、尺寸保持的碰撞规划

新的默认碰撞规则：

1. 手势过程中计算候选布局，并用 ghost 同时显示 mover 最终位置与所有将被平移的卡片。
2. 普通 move 不改变任何 span；普通 resize 只改变 mover span。
3. blocker 可以按稳定顺序平移到最近合法位置，但不能被缩小，也不能让 mover 因碰到边界自动长大。
4. 若在当前 Board 限制内无合法布局，ghost 变为拒绝态；释放后保持原布局并给出短状态提示。
5. 不为常规碰撞调用 `QMessageBox`。取消、Esc、失焦均不提交。
6. 成功提交后显示非模态反馈，如“已重排 3 张 · Ctrl+Z 撤销”。
7. 邻卡缩小、填满空隙、边缘自动扩展等能力只允许由显式“智能整理/整理布局”命令触发，并在提交前显示整体预览。

此决策在实现落地时取代当前项目 lessons 中“边缘扩展可缩邻卡”和“重叠时弹框选择自动避让”的旧规则；文档阶段不提前修改历史 lesson。

### D10. 选中对象动作分层，降低常驻 chrome 密度

选中卡片的常用动作保持靠近对象，但只常驻：

- 打开/定位源；
- 过期时显示“同步”；
- 聚焦；
- 更多。

复制、移入未放置、删除、调试信息等低频或危险动作进入“更多”或右键菜单。图标必须有 tooltip、accessible name、键盘焦点和禁用原因。该调整不得删除原有能力。

底部状态区按宽度响应：保留 Board、缩放/导航和必要信任状态；重复说明、长文本或低频动作可折叠。800 px 下不能互相覆盖，1440 px 下也不应为了填满空间制造空洞大条。

### D11. 渲染质量空闲判定由画布交互生命周期拥有

- 画布在 press/move/release、wheel、gesture、kinetic scroll 等入口维护自身 activity 状态和最后活动时间。
- `QApplication.mouseButtons()` 不再作为阻止 repin/idle-quality 恢复的唯一条件；若保留，只能通过可注入 provider 做防御性校验。
- 画布外部无关鼠标按下不能让该画布永久停留在 pending 状态。
- 测试应控制画布 activity/provider，不依赖测试进程的全局鼠标瞬时状态。

### D12. 错误与反馈保持现有分类

- 用户数据不兼容：明确 item/status 提示，可继续处理其他项。
- 解析器回退：记录上下文并给用户可见的降级状态。
- 可识别的 optional renderer 缺失：按现有契约降级。
- 编程错误、未知 `ImportError`、非法 frame 操作：传播或转为明确失败，不静默吞掉。
- 热路径诊断沿用节流机制，不因缩放、鼠标移动或 minimap 刷新形成日志风暴。

## 6. 可访问性与视觉细节

- 所有 icon-only 控件最小逻辑点击区沿用产品现有触控/鼠标基线，不以缩小图标同时缩小 hit target。
- hover、pressed、focus-visible、disabled、mode active、panel open 六种状态需要分别验收。
- header chip、ghost 拒绝态和 stale 状态不能只靠颜色区分；至少增加图标、轮廓或文本。
- 动画遵循系统 reduced-motion；ghost 与 minimap 淡入淡出不阻塞输入。
- 中英文长度、长 View 名和同名通道不应破坏布局或身份映射；完整名称通过 tooltip 可见。
- 圆角面板必须在真实渲染中检查四角像素和底层 backing rectangle，不能只看 QSS radius。

## 7. 持久化、兼容与迁移

- 本轮不新增第二套产品版本常量。
- UltraView 项目 schema 尽量不变；`modeActive`/`panelOpen` 属于呈现状态时不写入可复现项目数据，布局模式继续使用现有字段。
- 碰撞规划只改变现有卡片 geometry 的提交方式，不改变 `UltraViewRef`、PreviewStore key 或 digest。
- 新 `ChannelFrame` 是模块级契约；若保留 `LazyZohFrame` 导入路径，至少跨一个兼容周期并有测试。
- 旧 DBC probe 字段如需兼容，只允许只读派生并发 deprecation 诊断；内部新逻辑必须全部迁移到新字段。
- 任何用户可见交互名称或快捷键变化都同步 `mf4_analyzer/ui/hints.py` 与 `mf4_analyzer/ui/quickref.py`，并更新 UltraView 帮助页。

## 8. 验收标准

### 8.1 数据与解析

- **V8H-A01**：构造前段全命中、后段全失败的 BLF；UI 与模型只报告样本比例，不显示线性外推的精确解码帧数。
- **V8H-A02**：构造 bursty、multiplexed、invalid-tail 数据；均匀/分层样本能反映中后段，发现样本不进入统计分母。
- **V8H-A03**：三个候选中第一个达到 sampled-strong、第二个实际更优；系统完成三个候选探测并选择证据更强者。
- **V8H-A04**：取消或截断探测时估算字段为空，状态明确，不生成伪精确值。
- **V8H-A05**：`load_blf()` 返回显式 `ChannelFrame`；只访问一列不物化其他列；`load_blf_dataframe()` 输出与既有期望 DataFrame 等价。
- **V8H-A06**：对 ChannelFrame 执行不支持的行 `drop` 明确失败，不返回未改变的自身。
- **V8H-A07**：ASC 在早回退和晚回退两种路径中进度单调，只有成功交付时达到 100%，且回退原因可观察。

### 8.2 UltraView 交互与视觉

- **V8H-A08**：100%、55%、35% 下分别呈现完整、紧凑、标题卡；35% 不残留预览 body/footer 空白，但仍可选中和拖动。
- **V8H-A09**：55% 与 35% 下通用标题卡仍能识别分析类型和 freshness/trust 状态。
- **V8H-A10**：Board 完全 fit 时 minimap 隐藏；产生真实滚动范围时出现；缩放回 fit 后再次隐藏。
- **V8H-A11**：布局模式 active 与面板 open 在截图和属性测试中可区分；关闭面板不改变模式。
- **V8H-A12**：普通 move 推动邻卡后，所有 span 不变；普通 resize 后只有 mover span 变化。
- **V8H-A13**：无合法碰撞方案时显示拒绝 ghost，release、Esc 和失焦均不改变布局或 undo 栈。
- **V8H-A14**：一次成功重排只有一个 undo command，Undo/Redo 精确恢复所有受影响卡片。
- **V8H-A15**：常规拖放全过程无 modal；受影响卡片在 release 前均有最终位置 ghost。
- **V8H-A16**：选中卡片的所有原动作仍可通过常驻按钮、更多或右键菜单访问，icon-only 控件具备 tooltip 和 accessible name。
- **V8H-A17**：画布外部的全局鼠标按下不会阻止空闲质量恢复；测试重复运行不依赖机器即时输入状态。

### 8.3 回归与平台

- **V8H-A18**：UltraView 操作不改变分析 payload、digest、复合身份和 PreviewStore 命中语义。
- **V8H-A19**：800、1280、1440 宽度以及 100%、55%、35% 缩放的截图矩阵无覆盖、截断、错误 backing rectangle 或状态混淆。
- **V8H-A20**：真实 Cocoa 前台以 5 张常用场景和 24 张压力场景验收拖放、LOD、minimap、焦点和圆角；offscreen 结果单独记录。
- **V8H-A21**：相关 owner tests、架构边界、主 suite 与 acquisition suite 两进程门禁全部完成；异常退出或中断记为 `UNVERIFIED`。
- **V8H-A22**：若作为 Windows 发布内容，必须完成当前 Full/Lite frozen executable 的启动、打开文件、UltraView 操作和帮助页验收；源码级打包测试不能替代。
- **V8H-A23**：`git diff --check` 通过，修复当前 `chrome.py` EOF 空白；不夹带无关工作区文件。

## 9. 验收矩阵

| 维度 | 最小集合 |
| --- | --- |
| CAN | 小 BLF、大 BLF、bursty、multiplexed、invalid tail、取消、ASC 早/晚回退 |
| Frame | 惰性单列、全量 pandas、非法行操作、重复信号名、空/短/非有限数据 |
| UltraView | template/free-grid、空 Board、5 卡、24 卡、fit/scroll、move/resize/reject/undo |
| 缩放 | 100%、60%、59%、40%、39%、35% |
| 宽度 | 800、1280、1440 px |
| 平台 | offscreen Qt、真实 macOS Cocoa、Windows Full/Lite frozen（发布时） |
| 证据 | 单测、属性/几何、像素截图、前台观察、日志/结果对象，分别记录 |

## 10. 完成定义

只有同时满足以下条件才可将本规格标为 Done：

1. D1–D12 的实现或明确删减决策已经合入，删减项有理由且不破坏验收目标；
2. V8H-A01–A23 有对应自动化证据或明确的平台验收记录；
3. 帮助、hints、quickref、兼容注释和相关 lessons 已同步；
4. 主 suite 与 acquisition suite 按两个新进程完成，没有用历史通过数替代当前结果；
5. 真实 Cocoa 证据与 offscreen 证据分开陈述；
6. 发布时的 Windows frozen 验收未完成则明确标为 release blocker，而不是“源码已检查”；
7. Git 范围只包含本规格实施相关文件，`git diff --check` 为零问题。
