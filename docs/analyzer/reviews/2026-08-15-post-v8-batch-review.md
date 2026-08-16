# v8 后续批次全盘 review(3b2d8cde..350969f2)

- 日期:2026-08-15
- 范围:上一轮全盘 review 基线 `main@3b2d8cde`(见
  `docs/analyzer/specs/2026-08-14-v8-review-hardening-and-ultraview-polish-spec.md`)
  之后合入 main 的全部提交,HEAD `350969f2`,共 8 个实质提交、77 文件、
  +8184/−1059:
  - Codex v8 加固批:`40c3e038`(画布空闲质量)· `fc465104`(DBC 精确/抽样证据 +
    ChannelFrame)· `9534b611`(UltraView 三级 LOD)· `3d60479c`(尺寸保持原子
    碰撞规划)· `7267d1a1`(ASC 回退进度)· `3971d5a3`(compact rail 居中)
  - `58fee980`(UltraView 演示/库钉、通道配置白底、谱图峰值保持)
  - Cursor QSS 瘦身批:`5ce5cc15`(按 `2026-08-15-qss-consolidation-plan.md` 执行)
- 方法:四路并行深度 review(逐提交读 diff → HEAD 代码核实 → 复现脚本/聚焦测试
  验证,关键项与父提交做 A/B 对照)+ 一路全量套件基线。所有「已验证」发现都在
  HEAD 上实测过,不是 diff 阅读印象。
- 配套修复 plan:`docs/analyzer/plans/2026-08-15-post-v8-batch-fixes-plan.md`

## 1. 总评

**方向与主干质量都不错,但有一条必须立即修的 P0 功能回归和五条 P1。**
碰撞规划重写(3d60479c)是这批质量最高的部分:纯函数、2000 例随机 fuzz 零违规、
「普通移动不改尺寸」硬契约真正立住;QSS 瘦身批经逐名复核**零误删**、三道棘轮
实现质量高;ASC 进度状态机四分支实测单调无假 100%。问题集中在三类:
① fc465104 的发现样本因一处恒零表达式整体失效,把「精确/抽样分离」做成了
「抽样覆盖变差」,大日志上真能解码的 DBC 被整链路拒绝(P0);② 多处「做了一半」
——回退原因进日志不进 UI、LOD 迟滞双边界污染漏掉整个 band、空闲质量修了 FFT
画布留下时域画布;③ 外围状态清理与护栏流失——手势 dim 泄漏、rail 防重叠从
构造保证退化为巧合、状态栏 showMessage 被钉成永久不可视。

## 2. P0(合入即修)

### P0-1 BLF/DBC 发现样本是死代码,合法 DBC 在大日志上被判「不匹配」

`mf4_analyzer/io/blf_format.py:681,724-725`(fc465104 引入)。
`leftover = max(0, _PROBE_DECODE_CAP - len(statistical))` 恒为 0
(`_statistical_probe_indices` 在 n>cap 时恰好返回 cap 个下标),
`sampling_complete and leftover` 永不为真,`_discovery_probe_indices()` 的结果
永远进不了解码。低频 ID 的信号名全部丢失 → `is_match=False`。

A/B 对照(30000 帧,`0x123` 仅出现在 index 1,DBC 只定义 0x123):
HEAD `is_match=False, signal_names=()`;父提交 `is_match=True,
signal_names=('EngineSpeed','Throttle')`;直接调 `_decode_blf_with_dbc`
确认 DBC 确实能解码。

下游全部实链核实:`_validated_blf_dbc_paths` 返回 None(工程恢复的 DBC 绑定
静默丢弃)· 候选列表把该 DBC 过滤掉(用户根本看不到)· 批处理
`source_adapters._probe_blf` 直接 raise「CAN 日志与所选 DBC 不匹配」·
`seed_source_channels()` 通道表缺项。

修法:发现样本独立预算(统计解码后无条件跑 discovery,自带 cap),结果只喂
`signal_names` + 新增 `discovery_decoded_count`,**不进** `decoded_sample_count`
分母;`is_match` = 统计或发现任一成功;discovery 扫描搬进真正使用它的分支
(现在每候选无条件多跑一次被丢弃的全表 O(n) 扫描,strong 早停去掉后 ×3)。

## 3. P1

### P1-1 ASC:`TxRq` 行被静默丢帧且不触发回退

`io/asc_can_format.py:119-122`。`_ASC_MESSAGE_HINT_RE` 尾部比 python-can 原版
多了一个 `\b`:`TxRq` 既不被 `_parse_asc_data_line` 接受、也不被 hint 识别为
「像 CAN 帧但解析不了」→ 快速路径 `continue` 丢帧,预检 `supported=True` 永不
回退。实测同文件 fast=0 帧 vs python-can=1 帧,静默不一致。既有缺陷,但
7267d1a1 把「不支持语法必回退」写成预检契约后它成了承重假设。修法:去掉 `\b`
(或放宽方向判据),并补 fast/python-can 逐帧一致的差分守卫用例。

### P1-2 ASC:回退原因只进日志,到不了用户可见状态

生产调用方 `_project_io_mixin.py:671-677` 传两参 lambda,
`_AscProgressCoordinator._emit`(asc_can_format.py:329-342)降级后
`ASC_PHASE_FALLBACK`(「兼容解析重试」)永远到不了状态栏;
`AscParseOutcome.warning`/`diagnostic_context` 在生产代码零消费方。
号称覆盖此点的 `test_ui_fallback_reason_is_visible_when_opening_canoe_asc`
只断 caplog,名不符实。spec §2.1「用户能看见回退原因」未达成。
(注意与 P1-5 联动:状态栏本身已不可视,呈现面要选 toast。)

### P1-3 UltraView:LOD 迟滞双边界污染,36%–39.9% 跳过「仅标题」档

`ui/chart_stack/ultraview/viewport.py:226-244`。`current == LOD_FULL` 分支把
`hide_footer` 与 `title_only` **两条**阈值同时下调 0.04,从 100% 直接缩到 37%
时落 NO_FOOTER 而非 TITLE_ONLY;`_lod` 粘性,不再变缩放就永远停错档。实测
`lod_level(0.37, FULL)=='no_footer'`,页面级复现 37% 下预览仍在渲染。
修法:迟滞只放宽与当前档**相邻**的那条边界。现有边界测试恰好没测这一段(假绿,
见 P2 测试项)。

### P1-4 UltraView:规划器搜索预算全 plan 共享,密集板「合法却被拒」且文案撒谎

`free_grid.py:35 PLANNER_SEARCH_CAP=512` 跨所有 blocker 共享,ring 搜索按
`2·d²` 增长。实测 60 张 2×2 卡的板上 resize → `SEARCH_CAP` 拒绝(512/512),
同一输入 cap=100000 时 587 次即接受(合法布局存在);48 张时 495/512 已贴边。
UI 把 `SEARCH_CAP` 与 `NO_LEGAL_LAYOUT` 映射成同一句「当前位置放不下,已保持
原布局」——实际是规划器放弃了,不是无解;日志仅 `logger.debug`。
修法:per-blocker 预算或按卡数缩放;`SEARCH_CAP` 单独文案;log 提 warning
(「吞掉的基础设施失败必须留痕」)。

### P1-5 状态栏 `showMessage()` 被钉成永久不可视,50+ 调用点失去用户反馈

`ui/main_window/window.py:113-126`(58fee980)。`SurfaceStatusBar.showMessage()`
恒调 `super().showMessage("", 0)`,真文本只存 `_logical_message`;新增测试甚至
断言调用后无深色像素(官方确认「不绘制」)。全仓 50+ 处
`statusBar.showMessage(...)`(FFT 峰值读数、保存/关闭、游标重置、**错误提示**)
从此没有任何用户可见反馈。根因早于本批(98446767 hint bar 抢占消息区槽位后
文字本已挤压成残影),本提交是把「残影」清理成「彻底不画」的那次——清理残影
本身正确,但影响面没有被声明,错误类提示静默尤其不可接受。
修法(本批范围):审计全部调用点分类;**错误/失败类改走 toast**;信息类维持
现状但在 lessons/CLAUDE.md 显式标注「showMessage 已是纯逻辑 API」防后人再往
死胡同里加提示。全面的消息呈现重设计留给产品决策。

### P1-6 时域画布仍留着 40c3e038 自己点名的空闲质量反模式

`ui/pg_canvas/quality.py:707-723`。40c3e038 把 FFT 画布(line_canvas.py)的
空闲质量闸门从全局 `QApplication.mouseButtons()` 改成画布本地
`_IdleQualityActivity`,lessons 文档 frontmatter 自书风险范围「or a sibling
canvas」,但时域画布的 `QualityManager._idle_quality_allowed` 一行未动:仍以
全局 mouseButtons 无条件早退,且命中闸门时不重新武装计时器(quality.py:674-687
直接 return)——外部窗口按住鼠标时本画布 AA 恢复被静默放弃,要等用户再碰画布。
旁证:test_pg_timedomain_canvas.py 有 20 处 monkeypatch mouseButtons,与
line_canvas 修复前的症状同构。修法:把 `_IdleQualityActivity` 模式移植到
`QualityManager`,全局检查降级为可注入防御 provider;lessons `checks` 扩到
quality.py。

## 4. P2(按子系统)

### 4.1 CAN/BLF/DBC(fc465104)

- **完整扫描被标「抽样解码」**:`_project_io_mixin.py:1068-1073` 不读
  `sampling_strategy`/`sampling_complete`,全扫也打抽样标签,置信度被说低;
  且「完整匹配」实为 ID 命中数,与解码成功数两个「匹配」易混。
- **取消/截断探测被当「不匹配」**:`blf_dbc_candidates.py:138-149` 让
  `strength=="none"` 落 `"mismatch"`(docstring 自己说 absent≠mismatch),
  排序低于 unverified 且被 selectable 过滤;同时全仓无生产调用方给
  `probe_blf_dbc_frames` 传 `cancel_check`,取消分支只有测试能到——大日志
  多候选探测中用户按取消实际打断不了。修法:加 `"incomplete"` 档 + 接取消信号。
- **LazyZohFrame 重名列塌陷**:`channel_frame.py:28-29` ABC 承诺支持重名,
  实现用名字 dict 且预置 `_cache["Time"]`——DBC 里名为 `Time` 的信号被时间轴
  静默顶替(实测两列 Time 同值)。配套用例 fixture 用同一份 series 撑两列,假绿。
- **BLF 探测进度提前 100%**:`blf_format.py:721-722` ID 扫完即发 100%,统计解码
  阶段重复发 100%——ASC 侧刚立的「交出结果才 100%」原则没搬到兄弟路径
  (`probe_blf_dbc` 公共 API 语义错,主窗口因外层再映射不至于全局假 100%)。
- 杂项:零帧探测 `reason=None`(与 D1 不符,当前不可达)· `is_lazy()` 物化后仍
  True · `get_column` 返回活缓存可写数组(与 `__getitem__` 只读语义不一致)·
  `_project_io_mixin.py:1018/1196` 宽泛 except 无留痕。

### 4.2 ASC(7267d1a1)

- **`_emit_progress` 裸 `except Exception: pass`** 吞掉 `as_callback` 里的
  `AscParseCancelled`(死安全网 + 无留痕宽泛 except;功能未坏,逐行 cancel_check
  兜着)。
- **`_emit` 把回调内部 TypeError 误判为参数不匹配**,一次 emit 双调回调,
  副作用执行两遍。修法:首次探测后缓存调用形态。
- **预检窗口只看 64 行/8KiB「任意行」**:头部长注释可吃满窗口给假 supported →
  晚回退实测 99.5% 字节才回退。修法:至少看 N 条**数据行**再下结论,或在
  spec/docstring 写死「早回退只覆盖前缀可判定」边界。

### 4.3 UltraView 交互(9534b611 / 3d60479c / 3971d5a3)

- **手势 dim 泄漏**:`widgets.py:3120-3176` dim 集合按首帧算、restore 按最终
  plan 算,推挤集合中途一变就对不上——不提交路径下邻卡永久停 40% 透明度
  (实测复现;提交路径的 apply_model 自愈掩盖了大半)。修法:board 维护
  `_dimmed_refs` 集合增量 dim/undim,finish 无条件 restore。
- **rail 防重叠护栏消失**:`floating_layout.py:251-260` 纯居中 + clamp,无分离
  约束,stage 高 <~301px 时实测 rail 与上下浮岛相交;现有断言只测高 stage。
- **rail 锚定浮层与触发钮脱节**:`floating_layout.py:389` 浮层 y 仍贴
  board_island 底(1280×800 实测差 237px),按钮在画布竖直中点、面板贴左上角弹。
- **类型 chip 造成拖拽死区**:`widgets.py:1550-1559` chip 是 QToolButton,吞
  press(实测 chip 上按下不 arm 手势),位于 header 最左 22-97px 抓取热区;
  还带 TabFocus 但无 clicked 接收方。修法:改 QLabel 或
  WA_TransparentForMouseEvents,去 TabFocus。
- **群组越界 ghost 与结果不符**:`gesture.py:283-291` 越界置 plan=None →
  ghost 回退逐张 clamp,画出压扁自叠的假形状,而真实结果是拒绝保持原布局
  (违反「ghost 是将要提交结果的预览」)。
- **blocker 落点方向优先,非 spec D9.3「最近合法位置」**:实测被推卡落到比全部
  内容低两行的视口外,而更近空位空着。修法:改 spec 措辞为「拖拽轴优先」
  (docstring 已如此)或先做有界最近邻;displaced 出视口应有滚动跟随或提示。
- **死代码簇**:`plan_boundary_yield`(生产零调用且丢守卫)·
  `LAYOUT_ARRANGE`+`plan_neighbor_shrink`(无人传 "arrange",spec D9.7「显式
  整理允许缩邻卡」实为空实现——UI 整理走 organize_free_grid 不经 plan_layout)·
  `FEEDBACK_AVOID_BOUNDARY` 无消费者 · `_legal_grid_rect`≡clamp_rect ·
  `widgets.py:2661-2664` 两字段重复初始化两遍。
- **假绿测试两处**:`test_plan_layout_24_card_search_is_capped` 只断
  `visits<=CAP`(恒真)不断 `accepted`,抓不到 P1-4 的误拒;
  `test_lod_state_boundaries…` 恰好没测 FULL→0.36-0.399 段,P1-3 因此全绿。
- **overflow 菜单泄漏**:`chrome.py:1062-1076` 每次 new QMenu 无 deleteLater。
- **focusChanged(now=None) 取消手势偏脆**(疑似):瞬态 hide/destroy 也触发,
  WindowDeactivate 路径已覆盖真失焦。
- **TITLE_ONLY 档仍为隐藏预览做 pixmap 缩放**:`widgets.py:1688` apply_model
  无条件 `_set_image`(低 LOD 正是卡最多时);resizeEvent 侧已正确守卫。

### 4.4 58fee980 / 画布 / QSS 批

- **pandas 懒加载夹带**:`channel_frame.py:87-94` 改 `sys.modules.get`,功能
  验证等价安全,但与提交主题无关、commit message/lessons 均未提。
- **术语撞车「峰值保持/peak-hold」**:FFT 计算层 `compute_peak_hold_fft`
  (改数据)与新增渲染层 `build_peak_trace`(纯降采样)同名无消歧。
- **pin 命名撞车**:新增 ViewLibraryPanel `_pin`(钉面板)与既有
  `set_pinned_refs`(View 引用集合)同域重名,无功能冲突。
- **`_IdleQualityActivity.last_activity_monotonic` 死字段**,类 docstring 谎称
  计时器靠它 delay(实际靠调用点显式重排)。
- **QSS plan 记录错位**:`2026-08-15-qss-consolidation-plan.md` Task 2/3 复选框
  全 `[ ]` 但实际已完成(diff/spec 旁注/liveness 三方互证);
  `test_qss_duplicate_selectors.py:12` docstring「44」过期(HEAD 实测 45,断言
  动态比对不受影响)。
- **工作区卫生**:`docs/analyzer/reviews/2026-08-14-ultraview-floating-ui-review.md`
  未跟踪未入库。

## 5. 已排除的风险面(与发现同等重要)

- QSS 批:29 个被删 objectName 逐名词边界复核**零误删**;frfSegmentChoice 成对
  删除且考古属实;既有 token 值零改动;三棘轮起点数字独立复算一致。
- 碰撞规划:2000 例随机 fuzz 零 span 违规/零重叠/零越界;规划失败全有全无,
  无部分落地;undo 单条原子;`confirm_auto_avoid` 彻底删除(非模态是实断言)。
- 谱图峰值保持:`build_peak_trace` 纯 numpy;批处理/GUI 共用 PgLineCanvas,
  13 条 parity 用例全绿,无两侧分叉。
- 机械护栏:状态所有权棘轮/backref 白名单/import 边界/signal 无 GUI/lambda
  棘轮(净缩小 4→2)/QSS border 简写(白名单仍空集)/paint 计时器哨兵,全部
  实跑绿,无白名单扩张。
- 产品约束:无臆造采样率;CANoe 取证链路原样;ChannelFrame 消费方全量排查无
  未实现语义落点;无版本硬编码。

## 6. 全量测试基线(HEAD 350969f2,2026-08-15 实测)

- 主体(`--ignore=tests/acquisition_ui`):**6891 passed / 13 failed /
  38 skipped / 3 deselected**(31:43,本次与四路 review agent 并行跑,耗时
  高于常态的 ~7 分钟)。`tests/acquisition_ui` 单独:**359 passed**。
  `tests/test_gen_help_screenshots.py` 本机样本齐全,6 passed(未落入环境性红)。
- 13 条失败分两类:
  - **4 条独立可复现**:`tests/test_batch_render_qt_display_envelope.py::
    test_time_display_envelope_uses_real_view_width_across_layouts` 的
    overlay-False-time / overlay-True-time / overlay-False-channel /
    subplot-False-time(envelope spy 调用 4 次≠2 次;subplot 条卡
    `pixel_width 1818 == 350`)。**已 A/B 钉死为既有红**:在范围起点
    `3b2d8cde` 的干净 worktree 上同样 4 failed——不是本批引入,是更早的
    实现/测试漂移(F1–F8 基线 6230/0 之后、3b2d8cde 之前),修复列入 plan
    Task F7。
  - **9 条顺序污染型**:单独/子集重跑全部转绿(`test_batch_output_panel` ×3、
    `test_chart_stack` ×1、`test_pill_switch` ×2、`test_ultraview_chrome` ×2、
    `test_ultraview_entry` ×1)。其中 `test_ultraview_chrome` 两条是 58fee980
    新增用例(离 HEAD 仅 4 提交),污染源是否随本批引入待收尾复跑判定。
- 结论:**本批(3b2d8cde..HEAD)零新增可复现失败**;真实遗留债 = 4 条既有红 +
  9 条顺序污染(待收尾全量复跑对账)。
- **UltraView Task 0「3 条独立红」更正**(2026-08-16):见
  `docs/analyzer/specs/2026-08-16-daily-review-followup-spec.md` B7 —
  1 独立(harness)+ 1 污染(layout picker)+ 1 已修(palette)。证据:
  `docs/analyzer/verify/2026-08-15-ultraview-seam-hardening/baseline.txt`。

## 7. 处置

按严重度收敛为 7 个修复 Task,由
`docs/analyzer/plans/2026-08-15-post-v8-batch-fixes-plan.md` 安排 agent 执行:
P0-1 与 P1 六条全修;P2 除两项裁决类(blocker 落点语义改 spec 措辞、showMessage
呈现面重设计留产品决策)外全修;测试假绿与弱断言随对应 Task 一并收紧。

**执行旁注(2026-08-15,`claude/post-v8-review-fixes`)**:七 Task 全部完成
并合入,修后全量:主体 **6978 passed / 9 failed / 13 skipped**、acquisition_ui
359 passed——F7 四条既有红转绿,9 红与 §6 顺序污染集逐条同名,零新增失败。
补充定性:
- P1-5 审计结论比预估乐观:51 处 showMessage 中 26 处**早已**配对 toast、
  25 处纯信息,零未配对错误类;F5 补了 3 条守卫用例钉住该不变量。
- F7 bisect 钉出 `36efcbd0` 把 `DENSE_DISCRETE_POLICY_ENABLED` 翻 False,
  批导出路径(无 ink 实测兜底)350 桶封顶随之失效;裁决为未评审的批导出契约
  副作用,回敬开关为 True(引用 07-23 CRC spec §8.4 / 08-08 ink spec §4.3)。
  **交互侧行为也随之回到 350 桶封顶**——若当初关闸是有意的交互决策,需另立
  spec 再关,并给批导出侧独立开关。
- 遗留跟进:① 9 条顺序污染(完整顺序稳定复现、单跑绿)待专项治理;
  ② BLF 探测取消只留了 `request_blf_dbc_probe_cancel()` 缝,进度 UI 无取消
  按钮;③ 批量导入路径的 ASC warning 未接 toast(仅单文件路径接了);
  ④ Cocoa 真机待验:UltraView 浮层锚点观感、矮 stage rail 分离、LOD 37% 档
  实际渲染、QSS 色板归并(consolidation plan Task 4 门禁)、新增 toast 呈现。
