# 近一周优化小修的疏漏模式复盘与全局横扫（2026-08-06 ~ 08-12）

- 分析日期：2026-08-12
- 分析范围：`main` 上 2026-08-06 以来 57 条 fix/perf/polish 提交（不含 feat/docs/chore），
  逐条读 diff + 提交说明穿透；交叉引用既有评审文档
  （`2026-08-11-two-day-delivery-and-frf-view-review.md`、
  `2026-08-11-channel-tree-paint-segfault-triage.md`、
  `2026-08-12-analysis-view-param-isolation-report.md`）
- 方法：四路并行穿透（IO/数据正确性 · UI 布局细节 · 状态/生命周期语义 ·
  渲染/性能质量）→ 归纳疏漏模式成 guideline → 五路并行按 guideline 横扫当前
  HEAD 找未爆的同类隐患
- 性质：纯分析。未修改任何产品代码；§4 隐患清单待逐项确认后再决定是否修

## 1. 结论先行

57 条小修不是 57 个孤立失误。穿透后收敛成 **8 类疏漏模式**（§3），每类都在
本周期内至少出现 3 次、跨 2 个以上模块。最高频的三类：

1. **同一真值在两条路径各写一遍**（≥10 例）——GUI/批处理、决策/解释、
   交互/导出、算法/文案这四对面是本仓的结构性高危面；
2. **代理量当权威量**（≥7 例）——截断名、重建 fs、幅值比、源点数……修复形态
   高度一致：回退一步找权威量，而不是在代理量上打补丁；
3. **单源/单 View 场景下恒等、多源/多 View 下分叉的作用域错误**（≥6 例）——
   写的时候必然看不出来，只能靠"多源问题意识"或真实多源文件暴露。

另一个值得记录的元规律：**这批 bug 几乎全部由用户回执的真实文件或真机操作触发，
而不是测试套件发现**（DC2E_0011、260417-ripple、SFNS_40_X04、真机 65.9 s 帧）。
原因见 §3.8——验证用例往往与被验证代码共享同一个退化假设。

## 2. 逐提交穿透摘要

### 2.1 IO / 数据正确性（10 条）

| 提交 | 症状 | 疏漏本质 |
| --- | --- | --- |
| `d25c5707` WWT Zeit NUL 脏填充 | 主测量整段静默丢失 | 把定长字段"有效前缀"语义当"整段干净"校验；假阴性被下游"n 不匹配整批丢弃"放大 |
| `72f5d611` WWT 导出轴原点 | 首帧只显示半幅 | 派生字段漏同步 + 原型（t 通道，下限恰为 0）退化到让 bug 自洽 |
| `c286836d` WWT 刻度与配色 | 首帧范围错、全部红色 | 逆向格式靠"看起来合理"猜（厂商正解是写 0=自动）；未识别字段默认照抄原型 |
| `3bc27219` HDF ext name str | 通道名截到 16 字符、4 个塌成同名 | 用近似字段（截断 name str）而非权威字段；把症状（重名）当问题治，绕开病因 |
| `7611a8fa` batch 按探针通道规划 | 拆分来源预览拒绝 + 幽灵失败 | "unknown 就保留"对单源安全、对拆分来源就错；调用方已知的信息没传到需要的层 |
| `6abfc3d9` COT 等距支撑网格 | 切片吸附错位 ±6 s、x 轴撒谎 | 帧中心是 hop 的副产品而非被指定的量；coverage 生产/消费语义错配 |
| `b5836294` 热力图色图统一 | 批处理与单文件配色不一致 | 分层禁止 import 逼出"就地写字面量"；parity 工具钉死同一常量自我掩盖 |
| `e614f851` 预览显示渲染 warnings | 警告链路通但末端不渲染 | 生产者尽责、传输尽责、消费端忘了消费；新状态 UI 漏清理入口 |
| `95e364df` parity 按各自 spec 断言 | parity 工具 14/14 全红失守 | 验证工具第三次声明产品常量；用代理量（padded range、bbox）断言真实约束 |
| `63bbd4ed` 采样率标注统一 | 同一 1 kHz 显示两种写法 | 浮点重建值当精确标称值做阈值分支；分支判据与格式化舍入各算各的 |

### 2.2 UI 布局 / 视觉细节（13 条）

| 提交 | 症状 | 疏漏本质 |
| --- | --- | --- |
| `d98a7262` 进度百分比遮挡 | 文字压进进度条 | 裁剪责任推给不保证触发的 resizeEvent；文本变化≠尺寸变化 |
| `650fecdf` 进度采样+裁切 | 进度冻 0%、文案截断 | except 把失败翻译成"无进展"（且是 100% 命中的常态路径）；进度契约只覆盖测过的格式分支 |
| `b5ec2969` Inspector 首开压扁 | 首次切分区表单挤成一团 | QSS polish 不触发 updateGeometry，首帧 sizeHint 缓存永不自愈；WordWrap 高度不进 plain sizeHint |
| `bb784060` Toast 上移+按钮扩宽 | Toast 挡 View 条、中文按钮裁切 | 让位常量按过时估值写死（22px 状态栏实际 40）；共享修复工具存在但新调用点漏接 |
| `4ab994b6` 底栏跟随圆角 | ChartStack 四角被削平 | 子控件不透明填充盖父 border-radius（Qt 不裁剪子背景）；同缺陷在另一处存在两个月 |
| `3ab58b48` qproperty 引号 | **整张样式表**静默失效 | Qt 惰性解析 + 单测走局部 setStyleSheet，纯语法错误可以静默活着 |
| `f4a6b923` drop-down 圆角 | combo 右角被削平 | 同 4ab994b6；另 border 简写会把省略的 radius 重置为 0（非 CSS 级联语义） |
| `9f8a44b5` 通道树 tooltip+中间省略 | 长名无处看全名、_DV/_PV/_VT 渲染相同 | 省略策略与数据形状（共享前缀、尾部区分）不匹配；无 tooltip 逃生口 |
| `1617b2d0` QMenu 密度 | 所有菜单为少数 checkable 菜单虚胖 | 全局默认按最坏情况取值，把特例的 chrome 税摊给全部实例 |
| `9683ac2e` 滤波对齐+中文分隔符 | 编辑器锯齿、中文逗号被拒 | 同一契约 5 处各写 split(",")，此前踩过一次只修了踩到那处；提示文案自己用中文标点 |
| `da851602` 滤波对齐+预设 chrome | 同 bug 时域侧孪生、预设卡自成一派 | max_width 帽只加了同表单一半控件破坏列基准；字面色值不走 token 自动脱队 |
| `9c30a23c` 工具栏对齐 | 「打开」比邻居高一截 | role 捆绑视觉+尺寸两件事，调用方只想要其一；QSS 特异性让全局属性规则胜过上下文规则 |
| `bac04b68` 阶次 picker 布局 | 大片空白、空态文案裁切 | QStackedWidget 默认 sizeHint 取所有页最大值；一个魔法下限被两种内容物共用 |

### 2.3 状态 / 生命周期 / 交互语义（13 条）

| 提交 | 症状 | 疏漏本质 |
| --- | --- | --- |
| `cf530b92` 「全部」按已绘制通道 | X 轴撑到全局最长、曲线挤左侧 | 用全局仓库（self.files）回答视图级问题（图面画了什么） |
| `4eb00502` 「全部」只复位视口 | 点「最大」顺手武装计算窗口 | 复用 set_range_from_span 只为拿填值，整份吞下武装副作用；默认值 4 处各写 |
| `67f4c20d` FFT 手动勾选+计算确认 | 预览缩放被当成计算承诺 | 浏览手势接到武装 API；早退 return 让后续 elif 成死路 |
| `c74c08d8` View 参数隔离 | 改显示单位清掉 sibling 结果 | 序列化面（get_params）与真实状态面（current_params）各写一半；cache key 白名单由消费方手写 |
| `777135c8` 隔离试点收尾 R1/R2 | 切 View 触发真实计算任务；owner 文案错 | 程序化回灌冒充用户编辑（守卫漏判一个标志）；一个 else 合并两种状态 |
| `ca5cf843` 评审 F1-F5 | stale 画布、参数覆盖、依赖漏报、假可点、逐 fid 弹确认 | 状态变了投影/渲染没跟；引用索引器没随引用种类增长；一次动作实现成 N 次操作 |
| `6ec3a310` 信号框跟随 View | 能选到界面上不存在的通道；旧视窗套新数据 | 可选集比可见集宽；判据（相交）比意图（子集）宽；return 误当"回退默认"实为"保持现状" |
| `81bc8c9e` 组关闭反馈聚合 | 关一张卡片蹦 N 个 toast | F5 修复的后遗症：确认聚合了、反馈没聚合 |
| `b1504cf5` chrome 重放早退 | projection p95 ×2.75 | F4 修复的后遗症：全量重放没配幂等短路；缓存化后另一写入口不维护签名 |
| `02e38972` BatchSheet 僵尸 wrapper | teardown RuntimeError 连锁 8 errors | lambda/属性存 bound method 让子强引用父，跨 C++/Python 生命周期成环 |
| `56c42f4d` 钉住顶层 widget | 21% 处随机段错误 | 纯外观改动的分配把 gen-0 GC 推进 paint 内部；隐式不变量无词法关联 |
| `1169c2d5` conftest 重入 | 测试照跑但静默丢隔离 | 上游破坏"一目录一节点"，fixture 按节点身份查找静默降级；污染伪装成业务 bug |
| `38d1c81a` sheet 自持 toast | 点预览"没反应"（消息画在 sheet 底下） | 通知宿主没跟随用户注视的表面；36px 让位常量为唯一宿主写死 |

### 2.4 渲染 / 性能 / 质量（11 条）

| 提交 | 症状 | 疏漏本质 |
| --- | --- | --- |
| `ba54e330` ink 降桶取代 wall 守卫 | 该拦不拦（106ms）、不该拦乱拦 | 几何比值代理与真实成本非单调、触发区反相关 |
| `5b7f511e` AA 闸门 ink 求和 | 多线漏拦、dense 线误拦、阈值抖动 | 逐项布尔 OR 当全帧总量；新判据没对齐既有滞回形态；导出闸门漏同口径 |
| `8f550532` 质量点分腿解释 | tooltip 说谎/失语 | decide 链与 explain 链是两份 if，改一份没改另一份；新腿沿用旧腿文案与前置 |
| `0c07517a` 未记录 ink 当场测量 | 首帧后空闲 AA 65.9 秒 | 空表当零（"未知"编码成最宽松值）；遍历缓存表而非真实对象集合 |
| `b3199b28` overlay 门禁迁移 ink | 假阳性 71 倍、假阴性 29.8 s | 输入规模代理输出绘制量；多层门禁没人复核每层真实贡献 |
| `456ae86d` 残差 span 刻度爆炸 | 18 字符标签、导出 Y 轴全空 | 1e-16 残差没有相对容差；同一判定内联四份 |
| `4b216e5a` 缩放刻度消失 | 缩放中横轴数字全灭、图框抖动 | 显式 setTicks + 有意延迟重算之间的过渡态无人负责；测试只断言稳态 |
| `b55edcf1` log 刻度兜底+游标单位 | 窄带视图零刻度 | "典型视图必跨整十进位"当不变量；规则复制两份；数值无量纲 |
| `0c35a603` FRF 抖动自动重建 | 同一文件别的分析能算 FRF 不能 | 同一数据问题各路径策略不一致；Prepared 缺 warnings 字段静默丢诊断；str(exc) 中文串分派 |
| `0b705f98` 条件抢占 | 注定丢弃的计算跑到完 | "最坏情况不安全"推成"永远不做"，没刻画安全子集 |
| `b6760791` time_res tooltip | 声称不存在的取舍吓退用户 | 文案写通用领域直觉而非本实现；算法演进没反查依赖旧行为的说明 |

## 3. 疏漏模式 → Guideline

每条 guideline 都给出：模式定义、本周期实例数、可操作的检查判据。

### G1. 权威量原则：判据必须建立在被约束的量上，不是它的代理

**实例**（7+）：截断 `name str` vs `ext name str`；帧中心=hop 副产品 vs 显式时间网格；
重建 fs 当标称值；幅值比/源点数 vs 真实墨迹（ink）；padded range/bbox vs 数据范围/字形墨迹。

**判据**：写任何门禁/分类/断言前问三个问题——
① 这个量是**测量来的、推导来的、还是猜的**？② 它与被约束的真实量是否**单调**？
（wall 守卫在触发区甚至反相关）③ 有没有一个更权威的字段/量被跳过了？
（ext name str 就躺在同一节里）。修复形态永远是回退一步找权威量，不是在代理量上打补丁。

### G2. 单一真值原则：同一事实第二次出现就是 bug 的温床

**实例**（10+）：cmap 默认、parity 工具的 9.0、5×split(",")、log 刻度规则×2、
退化 span 判定×4、tick density 默认×4、两份滤波表单、decide/explain 双链、
idle/export 双闸门。

**本仓四对结构性高危面**（分层禁令逼出"就地写字面量"）：
- GUI 画布 ↔ `batch_render_qt`（中立收口点：`qt_analysis_shared.py`、`render_profile.py`）
- 决策链 ↔ 解释链（`_idle_aa_density_ok` ↔ `quality_status`，要求分支顺序都一致）
- 交互路径 ↔ 导出路径（idle AA 闸 ↔ `_export_aa_affordable` ↔ `grab_pixmap`）
- 算法 ↔ 文案（tooltip / help HTML / placeholder）

**判据**：为同一个症状写第二个 fix 时必须抽收口（`list_text.py` 是正确示范）；
**验证工具重新声明产品常量是最危险变体**——守卫会复述被守卫方的错误
（parity 工具一松一紧两面都栽在这）。

### G3. 作用域原则：先问"这是仓库级还是桌面级问题"

**实例**（6+）：「全部」取全局时长、下拉框枚举全部文件、隐藏 View 投影共享
navigator、live Inspector 当全局真相、可选集比可见集宽。

**判据**：凡 `for x in self.files` 或读 live 控件值做决策，先问回答的是
全局问题还是当前 View/图面问题。这类 bug 在单源/单 View 恒等、多源/多 View 分叉，
**写的时候必然看不出来**——review 时要主动构造"10 个文件只挂 1 个"的心智测试。
一个物理文件还可能拆多个 logical source（产品约束既有条款），作用域要按
logical source 算。

### G4. 未知≠最宽松值：空表、缺省、异常都不是零

**实例**（6+）：ink 空表当 0（65.9 s 帧）；no-load unknown 保留任务；`tell()` except
当"无进展"；空 range → setTicks 零刻度；1e-16 残差当真实跨度；探测假阴性被
"n 不匹配整批丢弃"放大。

**判据**：`dict.get(k, 0)`、`if not cache: return 0`、`except: x = last_x` 三种形状
逐个问"未知时正确行为是什么"——答案通常是**当场测量**（`_line_ink_now`）或
**逐级降级**（log 刻度五级降级），既不是当零也不是一律拒绝（拒绝试过，34 条用例转红）。
警惕"局部保守 + 下游整批丢弃"的组合放大器；生产者与消费者对同一 metadata 的
语义（coverage=窗覆盖 vs 每列时间范围）要显式对齐。

### G5. 语义完整性：复用函数就整份吞下它的副作用

**实例**（5+）：`set_range_from_span` 填值顺带武装（两次中招）；`_close` 循环调用
带出 N 次 toast；`_enter_fft_mode` 回捕 live 参数污染目标 View；`return` 误当
"回退默认"实为"保持现状"（重绘复用已有轴根本不碰 X）。

**判据**：调用一个函数只为拿它的一半效果时，要么拆函数、要么显式声明另一半
（`notify=True` 缺省参数是正确示范）。对偶形式同样致命：早退 `return` 之后的
行为是"默认"还是"现状"？`if ...: return` 后面跟 `elif` 的必是死路。
把单项操作包成批量时，**确认、反馈、复位三件事的粒度要一起改**——反馈粒度
绑用户意图，不绑实现循环。

### G6. 程序化写入 ≠ 用户输入：apply 区间要有完整边界

**实例**（4+）：回灌 dB reference 冒充用户编辑提交真实计算；sibling live 值污染
cache lookup；守卫判了 `_applying_preset` 漏了 `_applying_analysis_view`。

**判据**：View 恢复是**投影不是输入**（lesson 原话 "Treat View restore as
projection, not user input"）。每个程序化 apply 路径核对：守卫标志是否成套
（`_applying_view` / `_applying_analysis_view` / `_applying_preset`）、
blockSignals 区间是否包住整个 apply、隐藏面是否在投影共享控件。

### G7. 静默失败欠一个哨兵：失效不报错的机制最危险

**实例**（5+）：qproperty 缺引号整张样式表静默失效；conftest 静默丢隔离去读
真实偏好；warnings 链路末端没人渲染；toast 画在模态底下"看起来没反应"；
Prepared 缺 warnings 字段丢诊断。

**判据**：凡是"失效时不报错、照常运行只是做错事"的机制，都欠一个**直接断言
机制生效**的哨兵测试（`test_qsettings_isolation.py`、`test_stylesheet_parses.py`
是范式）。诊断信息要查生产→传输→**渲染**三段，链路通 ≠ 用户看得见；
验证遮挡类问题必须 `grabWindow`（`widget.grab()` 看不到窗口层叠，会假绿）。

### G8. 验证不得与被验证共享退化假设

**实例**（5+）：WWT 原型下限恰为 0 让漏改字段自洽；parity 钉死 turbo 恰等于
批处理默认；`fs >= 1000` 在恒采样率下恒对；角度域等跳在恒转速下恒等时间等距；
测试在 `_flush_pending_refresh()` 后只断言稳态、过渡帧无人看。

**判据**：这批 bug 几乎全部由**真实用户文件**触发而非测试发现，根因就是用例
与代码共享同一隐含假设。选测试样本时主动找非退化个体：下限为负的通道、
非零起点录制、扫速工况、多 logical source 文件、窄带视图；对防抖/延迟机制
断言要落在过渡帧上。

### 附：两条工程纪律（跨模式）

- **修复本身是新的可疑变更**：本周期三条明确的修复链——关闭原子化→反馈扇出、
  chrome 重放→p95 ×2.75、纯外观 paint 改动→GC 段错误。聚合操作连反馈一起聚合；
  加全量重放连幂等短路一起加；加缓存先数清同一状态有几个写入口。
- **保守规则要刻画安全子集**："section 级取消有时误伤"不等于"永远不取消"——
  `_may_replace_section` 显式刻画了 pane 级与 section 级等价的窗口。
  "结果被丢弃"与"计算被停止"是两件事。

## 4. 按 Guideline 横扫全局的隐患清单

五路并行扫描（双路径真值 · 未知当零/退化输入 · 作用域/状态 · Qt 物理层/生命周期 ·
反馈链路/文案），全部在 HEAD `cf530b92` 上逐条到代码核实，非 grep 命中即报。
修复设计与任务拆分见配套 spec/plan（§5）。置信度：高=已确认会错或已在错 /
中=结构上危险、待特定输入触发 / 低=待观察。

### 4.1 P0 —— 会写坏用户数据或给出错误数据

| # | 位置 | 问题 | Guideline | 置信 |
| --- | --- | --- | --- | --- |
| A1 | `ui/main_window/_project_io_mixin.py:1447` · `window.py:3841` · `window.py:1711` | 在分析分区保存项目/应用通道编辑/「设为左轴」时，`_capture_focused_view()` 无 mode 守卫，用**分析投影后的 navigator** 覆写时域 View 的 attached/checked/colors/range_filter 并写进 `.tlproj`。分析侧 `_project_io_mixin.py:1449-1453` 已有守卫，时域侧漏了 | G3 | 高 |
| A2 | `window.py:1939-2003` `_plotted_time_extent` | 「全部」在时频/阶次/FRF 三分区必然退化到 `_time_data_extent()`（全局文件时长）：Heatmap/FRF canvas 没有 `get_data_x_union`，非 fft 分区 checked 被显式清空，三级回退全穿。`cf530b92` 修的 bug 的三个兄弟 | G3 | 高 |
| A3 | `ui/project_io.py:189-266` + `_channel_scope_mixin.py:573-611` | `ViewState.ylims` 的 key 内嵌 fid（`_shared.py:22`），但 `remap_view_fids`/关文件清理/依赖索引三张表全没扫 ylims → **每次重开项目丢全部逐通道 Y 缩放** + 孤儿条目回写 | G3 | 高 |
| A4 | `io/zfd_format.py:121-134` | `0.0 < cand_dt < 1.0` 绝对区间否决：采样率 ≤1 Hz 的慢采样（温度/耐久）被静默压成 fs=1000（时间轴错 1000×）。唯一证据 `fs_estimated` 全仓**零消费者**，违反产品约束「回退必须显式标注为估算」 | G4/G7 | 高 |
| A5 | `io/head_hdf.py:155-192` | `ch order`/`nbr of scans` 一行读不到 → demux 整块跳过 → 全部通道报 "no samples (unknown)" 后整文件失败，指错方向（WWT 放大器同构）；`factor_by_ch.get(i, 1)` 猜 factor 直接决定时间轴尺度、无标记 | G4 | 高 |
| A6 | `batch_compute.py:457-489` + `batch.py:5386` | Batch FFT-vs-Time 抖动超限时**静默重建时间轴并改写 fs**，无 warnings 通道；`effective_params['fs']` 在改写前定稿，manifest 记录的 fs 与实际不符。GUI 同场景会弹窗询问 | G2/G7 | 高 |
| A7 | `_order_mixin.py:691-718` · `_fft_time_mixin.py:586-604` | 异步结果按**派发时 view_id** 入缓存（正确），却按 **callback 时的 page/pane** 绘制：计算中切 View → 错图画上并停留 | G3 | 中高 |
| A8 | `window.py:2203-2220` + `contextual_{fft,fft_time,order}.py` | 音频 A 计权默认在 View 程序化 apply 期间伪装用户编辑：`set_weighting_default` 只判 `_applying_preset` 漏 `_applying_analysis_view`（R1 同型），且扇出到两个隐藏分区，UI/state 分叉后保存固化 | G6 | 中高 |

### 4.2 P1 —— 安全网失效与真值漂移

**渲染安全网（G4）**：

| # | 位置 | 问题 | 置信 |
| --- | --- | --- | --- |
| B1 | `ui/pg_canvas/canvas.py:607` + `quality.py:130-157` | `install_frame_paint_timer` 返回值被丢弃：安装失败 ⇒ AA backstop **整体静默不存在**，spec §4.5「最多付一帧」退化为无限坏帧。防 65.9 s 事故的最后一道网自身失效无告警 | 高 |
| B2 | `renderer.py:568-573` + `:688` | `get_ylim()` 失败 ⇒ `y_span=0` ⇒ ink 0.0 **持久写进** `_line_ink_state`（注释把 bug 当特性描述）；后续每帧优先读记录 ⇒ 高墨水线被放行 AA | 高 |
| B3 | `quality.py:311-330` | `_line_ink_now` 的两个 except 返回 0.0——ink 修复承诺「never treated as zero」的补测路径自己把失败翻译成零；`view_box is None → row_height 0` 同型 | 高 |
| B4 | `renderer.py:215-236` + `quality.py:481-484` | 退化哨兵桶 `0` 与合法 `y_span≈1.0`（0/1 标志位、归一化通道）撞车；backstop 黑名单按签名误伤/漏放 | 中 |
| B5 | `qt_analysis_shared.py:99-108` / `:196` | `_finite_data_bounds`/`_slice_autorange` 的 `hi <= lo` 绝对比较无相对容差：1e-16 残差矩阵得到 1e-16 宽色标窗（残差 span 修复没覆盖到颜色轴）；全非有限时凭空造 0..1 | 中高 |
| B6 | `ui/view_state.py:118-122` + `canvas.py:2058` | 恢复侧零校验（采集侧有完整 isfinite+hi<=lo 拒绝）：旧工程里修复前存下的残差 Y 窗口原样还原——**已修 bug 的活体回归通道** | 中 |
| B7 | `quality.py:905` | 解释链把 `density["error"]` 排在 raster-cost 之前，与决策链顺序不符，破坏该文件自立的「解释顺序==决策顺序」不变量 | 中 |

**双路径真值漂移（G2）**：

| # | 位置 | 问题 | 置信 |
| --- | --- | --- | --- |
| C1 | `batch_render_qt/_page.py:155` | 全渲染器唯一裸 `point_size=9.0`，不随 `font_scale` 缩放——用户改字号即漂移（**已漂移**）；parity 只校验轴字号抓不到 | 高 |
| C2 | `tools/verify_frozen_batch_render.py:23-24` + `batch_render_smoke.py:124` | 冻结验收写死 turbo 端点 RGB 字面量，且钉 `cmap="turbo"` 绕开出货默认 gnuplot2 的**本地 LUT** 路径（PyInstaller 后最需验证的那条） | 高 |
| C3 | `batch_render_qt/_builder.py:91-92` vs `qt_analysis_shared.py:125,136` | `_AUTO_SPAN_DB`/`_AUTO_CEILING_*` 双份声明（shared 注释已预告要改 40 dB——改的那天即 cmap bug 重演）；parity 工具 `:232-235` 又是第三份（99.0/30.0/`'gnuplot2'` 字面量） | 高 |
| C4 | `_builder.py:38,93` | `_SLICE_MAX_SPAN_DB` import 了却零使用，本地 `_DISPLAY_DEAD_SPAN_DB=200.0` 仍在——收口做了一半 | 高 |
| C5 | `batch_compute.py:382-392` vs `_builder.py:174-179` | `batch_output_scale` 与 `_render_in_db` 双实现且**已分叉**（后者多 `amplitude_axis` 腿）；前者自称单一来源，`batch.py:155` 注释又称后者是权威 | 中高 |
| C6 | `ui/pg_canvas/tick_density.py:42-43` | `(20,15)` 注释自认「mirror」`DEFAULT_CHART_TICK_DENSITY`，四处收口漏这一处 | 中高 |
| C7 | `tick_density.py:203` · `overlay_axes.py:524` · `analysis_axes.py:182` | 量测字号 `_pg_chart_font(9)` 与渲染默认 9.0 靠两个互不引用的字面量巧合对齐（`9` 在产品代码共 6 份）；错位即刻度叠字 | 中高 |
| C8 | `heatmap_canvas.py:708-709,1071` vs `_builder.py:2329-2331` | `interp` 默认 ×3、平滑集合 ×2；批处理侧无控件必吃默认——cmap bug 爆发前的完整状态 | 中高 |
| C9 | `_order_mixin.py:531` vs `batch_compute.py:388` | Order `amplitude_mode` 缺省两侧相反（GUI dB / 批处理线性）；判据三种方言（子串/两种精确串）并存 | 中 |
| C10 | `batch_compute.py:648` · `method_buttons.py:1229` · `_fft_mixin.py:149` | overlap 归一化三套不等价实现 + `avg_overlap`/`overlap` 两个同义 key；`method_buttons` 缺钳位 | 中 |
| C11 | 多处 | `coherence_threshold=0.8` 五处；窗函数默认 `hanning` 大面积散落且候选**顺序**已不一致（flattop 一处排第 2、四处排第 6；此族曾爆过）；`db_reference` 回退五行双胞胎×2 | 中 |
| C12 | `frf_canvas.py:571` | 漏 `.lower()` 的内联 log 判据绕过同类 `_is_log_frequency()`；`"Log"` 输入下保护失效可致 log10(≤0) NaN 视口 | 中 |
| C13 | `batch_render_qt/_palette.py:7-10` | docstring 声称与画布同色开场，实际 `#dc2626` vs `#e03131` 已漂移 | 高(轻) |

**反馈链路与文案（G7 / 算法↔文案）**：

| # | 位置 | 问题 | 置信 |
| --- | --- | --- | --- |
| D1 | `batch.py:3818-3830` ↔ `sheet.py:2086-2124` · `task_list.py:209-222` | `BatchRunResult.warnings`（降采样/checksum/迁移警告全在）在 **Run 结果面板零出口**——预览已修、Run 未修，同一个洞的另一半 | 高 |
| D2 | `batch.py:5052-5079` + `preview_dialog.py:20` | 统计诊断只传 code 丢 message/suggestion；`chart_statistics.multiple_x_reversals` 无冒号穿透 humanizer 原样渲染机器串 | 高 |
| D3 | `io/wwt_format.py:208` · `mat_format.py:161` · `loader.py:251-256` | WWT `skipped_channels`、MAT `skipped_vars` 无 UI 出口（消费者只有测试）；TDMS 跳过连载荷都不生成。HDF `dropped_channels` 的 toast 是唯一通了的（可当模板） | 高 |
| D4 | `loader.py:766-774` · `wwt_format.py:219-224` · `loader.py:284-291` | 三处重名去重静默改名 `[idx]`，不进 metadata、无提示；旧工程按通道名对照会对不上 | 中 |
| D5 | `contextual_fft.py:164` + `:366` + `:643-648` | FFT「重叠」控件对频谱**零影响**（只进 display_params），tooltip 承诺「更平滑」、摘要还把它印出来；同一句 tooltip 在 FFT-vs-Time 是真的 | 高 |
| D6 | `contextual_fft.py:158` · `contextual_fft_time.py:173` | 「自动=按窗长取 2 的幂」与实现不符：默认单帧模式走整段 FFT；平均模式还有 min_frames/0.15n/clamp 三道闸；「窗长」控件不存在 | 高 |
| D7 | `contextual_order.py:162,194` | `order_res` 实为输出插值网格（真实分辨率是 `samples_per_rev/nfft`），tooltip 未限定「仅自动 NFFT 下成立」——`time_res` 修了、同族没修；FRF 组 tooltip（`contextual_frf.py:44-62`）逐条核实全对，可当重写标准 | 中高 |
| D8 | `help/frf-guide.html:116` | 行标签「数据被阻断」是修复残留，与同行正文「自动重建」自相矛盾 | 中 |
| D9 | `drawers/batch/analysis_panel.py:239` ↔ `:478-500` | placeholder `"0.0, 120.0 s"` 带单位，解析器 `float("120.0 s")` 必拒；报错只谈分隔符指错方向——**示例本身不可解析** | 高 |
| D10 | `window.py:3924-4028`（5 toast+2 statusBar）+ `channel_editor.py:535-551` | 通道编辑器模态抽屉不 accept 就导出，所有消息发往被遮挡的主窗口（BatchSheet 已修自持 toast，这条旧路径没跟） | 高 |
| D11 | `_frf_mixin.py:413` · `batch_compute.py:310,314,483` · `_project_io_mixin.py:408` | 5 处靠异常**文本**分派：中文子串、26 词精确等值、CPython TypeError 措辞探测签名（3.10+ 措辞已变，且任何含 "fs" 的无关 TypeError 都被吞）。`NO_CAN_FRAMES_MESSAGE` 共享常量是范本 | 中高 |

### 4.3 P2 —— Qt 物理层与生命周期

| # | 位置 | 问题 | Guideline | 置信 |
| --- | --- | --- | --- | --- |
| E1 | `ui_kit/style.qss:1893-1913` | `channelTree::item:selected` 不透明背景无自身圆角，首/末可见行选中时盖父 9px 弧（底栏盖四角同构；`BatchFileList` 的透明纪律没落到这里） | G7 | 高 |
| E2 | `style.qss:1827,3045,3051,2406,2416,2267,813` 等 9 处 | `border:` 简写清零 radius 的状态规则：5 处**未爆**（仅拖拽悬停/风险 pill/预设 applied/禁用/校验失败时触发）+ `role="tool"`（`:1123`）影响面最大；守卫测试只保证「能解析」抓不到语义错 | G7 | 高 |
| E3 | 7 文件 13 按钮（`_channel_scope_mixin.py:246,518` 等） | `fit_message_box_buttons_to_text` 漏接——同一文件 4 处接了 3 处没接 | G2 | 高 |
| E4 | `ui/inspector.py:174-184` | `contextual_stack` 四页高差极大、无 sizeHint 覆写（取最高页）；首开压扁修复对此无效——同一容器两个方向的坑修了一个 | — | 中高 |
| E5 | `ui/file_navigator.py:17-51` + `widgets/db_reference.py:383-387` | 文件名/来源文本用 ElideRight：MF4 文件名正是共享前缀命名（`DC2E_0011_*`），窄栏下渲染成同名行——channel_tree 的教训没横展到文件名 | G8 | 高 |
| E6 | `widgets/toast.py:17-28` + `window.py:450` · `markup/editor.py:179` · `sheet.py:1569` | 主窗 Toast 仍吃魔法数 100（注释自拆为三个邻居的假定高度）；markup 编辑器借用同一个数；sheet 派生 margin 只算一次、footer 变高后陈旧 | G2 | 高 |
| E7 | `chart_stack/stack.py:749` ← `window.py:978` · `contextual_{order,fft,fft_time}.py` ← `window.py:988-991` · `analysis_section_page.py:291-312` · `acquisition_ui/_toolbar_mixin.py:500` | 裸存 MainWindow bound method / lambda 进长寿命子控件——BatchSheet 僵尸 wrapper 同型，且父对象是**主窗口**（最大对象图根） | G2 | 高 |
| E8 | `drawers/batch/{output_panel,method_buttons,filter_panel,input_panel,slice_panel}.py` · `inspector_sections/time_filter.py` 共 30 处 | `.connect(lambda *_: ...)` 只为丢参数存在：跨 C++/Python 引用环，正解是信号对信号直连 | G2 | 高 |
| E9 | `ui_kit/widgets/searchable_combo.py:49-70,177-231` | delegate **每行每帧**跑完整模糊匹配 + 逐字符 drawText + QFont/QColor 分配——把 GC 推进 paint 内部的完整配方（channel_tree 段错误的加强版） | — | 高 |

### 4.4 P3 —— 小项与结构性欠债

`_on_view_split` else 合并两种状态（R2 漏网分支，当前不可达）· View 重命名不刷新
empty-state 文案 · 退出分析分屏仅 FRF 清 pane-1 pin（fft_time/order 泄漏）·
`set_range_limits` 无 blockSignals（当前无订阅者，接槽即爆）·
`PaneState.source_time_view_id` 只读不写的死字段 · 多文件加载分析模式下 N 条 toast
（`_close` 聚合已修、加载侧未修）· 通道编辑器导出 `use_range` 在分析模式读共享
Inspector 范围 · `.asc` 嗅探外层 `except: pass` 吞 ImportError 指错方向 ·
MDF 元数据 except 后单位/路径变空串与「本来没有」不可分 · CSV 布局嗅探裸 `except:` ·
`context_menu.py:374` 分支与格式化舍入不一致（`_fmt_rate` 同型未推广）·
共轴组 `_axis_groups` 视图级状态住在全局 widget（跨 View 串味、保存即丢）·
阶次 rpm 对齐失败原因统一压成「缺转速」。

### 4.5 已核查无恙的面（同样有价值的负结果）

- `.split(",")` 用户输入解析：**零残留**，`list_text.split_list_text` 收口完整。
- 整数落点/空刻度：`log_frequency_tick_levels` 阶梯降级、`_apply_target_x_ticks`
  空则回自适应、COT `k_hi<k_lo` 有兜底——上一轮教训吸收干净。
- `_export_aa_affordable` 与 idle 闸门口径一致（ink/density 均对齐播种分支）。
- `fs` 浮点重建量：无 `==` 比较、无按 fs 分组，均走相对容差
  （`DEFAULT_TIME_JITTER_TOLERANCE` 双侧共用），处理得最好的一族。
- `blf/asc` 进度回调降级已是正确形态（`byte_pos=None` → 显式合成估计）。
- 内联 QSS 60+ 处无 qproperty/模板残留/border 陷阱；QMenu/QComboBox 角部内弧全部调校正确。
- FRF 面板 tooltip 全组与 `signal/frf.py` 逐条相符（重写其他组的标准）；
  表达式帮助「两个展示面共用一份数据」是防漂移正解。
- 批量 detach / close_all / 多选删通道 / 分析计算 toast 均已聚合。

## 5. 后续

修复设计（含需产品裁决项）见
`docs/analyzer/specs/2026-08-12-guideline-hardening-spec.md`；
任务拆分与执行护栏见
`docs/analyzer/plans/2026-08-12-guideline-hardening-plan.md`。
