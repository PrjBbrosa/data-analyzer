# TraceLab 常规桌面交互与快捷键统一 Spec

- 日期：2026-09-02
- 状态：READY FOR IMPLEMENTATION
- 冻结分析基线：f07b6a7c
- 配套计划：[实施计划](../plans/2026-09-02-standard-desktop-interaction-contract-plan.md)
- 适用范围：主窗口、标准对话框、View/图表、Markup、UltraView、文件导航、搜索和配置管理界面

## 0. 决策结论

本轮不是机械地给每个控件绑定一批快捷键，而是建立一套可预测的桌面交互合同：

1. Enter/Return 只确认当前明确的、非危险操作；Esc 每次只退出最内层临时状态；
   Ctrl/Cmd+Z 永远表示编辑撤销，不再承担图表视角后退。
2. 快捷键由“当前焦点及其所属编辑域”决定。文本编辑、弹窗、Markup、UltraView、
   图表和主窗口按固定优先级路由，禁止用一个全局 event filter 抢走全部按键。
3. 打开、保存、另存为、退出、撤销、重做、查找等全局命令使用 Qt 标准键序列；
   图表视角历史迁移到 Alt+Left/Right，Home 继续表示视角复位。
4. 每个 dialog 都必须显式指定默认按钮。搜索、导入、选色、删除等按钮不能因 Qt
   隐式 autoDefault 抢走 Enter。
5. 增加项目级未保存状态与“保存 / 不保存 / 取消”保护，覆盖退出应用和打开另一个项目；
   程序化 View 恢复、投影和重绘不算用户修改。
6. 所有仅能拖拽或点击的小部件增加键盘等价操作和可见焦点；帮助、tooltip、菜单和
   实际绑定共同读取一套命令定义，避免平台显示和运行行为漂移。

## 1. 目标与非目标

### 1.1 目标

- 用户可依靠常见桌面软件经验完成确认、取消、撤销、保存、查找和导航。
- 同一个键在不同区域有明确 owner，不发生双执行或 QAction ambiguous activation。
- 鼠标交互保持可用，同时为关键流程提供完整键盘路径。
- 危险操作默认安全；取消路径零 mutation、零历史、零 dirty。
- Windows 显示 Ctrl、macOS 显示原生 Command 符号，帮助文字不硬编码错误的平台键名。
- 新交互可以由自动化测试和真实前台运行共同验证。

### 1.2 明确非目标

- 不在本轮为所有历史功能补建一个跨全应用、跨项目的万能 Undo 栈。
- 不把图表缩放/平移历史、View 切换、选中状态或焦点变化伪装成编辑撤销。
- 不开放用户自定义快捷键，不修改项目持久化 schema 来保存按键映射。
- 不给未定义 owner 的 Delete、Ctrl/Cmd+A、Ctrl/Cmd+W 增加全局行为。
- 不改变现有数据计算、绘图数学、WWT 首帧、Batch 执行或 UltraView Board 模型语义。
- 不用本 Spec 顺带重构 MainWindow、Markup 或 UltraView 架构。

## 2. 已验证的当前基线

| 现状 | 当前 owner | 本 Spec 决策 |
| --- | --- | --- |
| 图表 Ctrl+Z 后退，Ctrl+Shift+Z 前进 | ui/hints.py、ui/chart_stack/_helpers.py | 移除冲突；改为 Alt+Left/Right |
| UltraView 使用 QKeySequence.Undo/Redo | ui/chart_stack/ultraview/page.py | 保留 owner；补齐平台全部 redo bindings |
| Markup 有独立 QUndoStack 和分层 Esc | ui/markup/editor.py | 保留；统一标准 Undo/Redo 路由和文本焦点保护 |
| Channel Editor 的隐式默认按钮是“创建通道” | ui/dialogs/channel_editor.py | “确定”显式 default；其他按钮禁用 autoDefault |
| Chart Options 的隐式默认按钮是颜色“选择” | ui/dialogs/chart_options.py | “确定”显式 default；选色按钮不接管 Enter |
| Channel Config Manager 的隐式默认按钮是“导入” | ui/widgets/channel_config_manager.py | “保存更改”是唯一 default；搜索 Enter 留在搜索域 |
| DB reference 主动关闭所有 autoDefault | ui/dialogs/db_reference_dialog.py | 保留例外：表格内 Enter 提交单元格，不接受 dialog |
| UltraViewSheet 主动吞掉 Return | ui/drawers/ultraview/sheet.py | 保留例外：独立工具窗口不能被 Return 关闭 |
| 主工具栏已有打开/保存 signal，但没有统一 QAction/菜单 | ui/toolbar.py | 建立 File/Edit/View/Help 命令面，并复用现有 slots |
| 主窗口关闭未检查项目级 dirty | ui/main_window/window.py | 先决策 dirty，再停止任务和销毁窗口 |
| 打开新项目只按“是否已加载文件”判断替换 | ui/main_window/_project_io_mixin.py | 未保存项目先走同一保护事务 |
| QuickRef 搜索内按 Esc 直接关闭面板 | ui/quickref_panel.py | 有文本时先清空；再次 Esc 才关闭并恢复焦点 |
| 文件行主要依赖鼠标，配置表/复选框不可聚焦 | ui/file_navigator.py、ui/widgets/channel_config_manager.py | 增加键盘激活、导航、排序和可见焦点 |

当前 macOS Qt5 探针还确认：字符串 Ctrl+Z 的 NativeText 会显示为 Command+Z；
QKeySequence.Redo 的单一主序列是 Ctrl+Y/Command+Y，而
QKeySequence.keyBindings(Redo) 还包含 Ctrl+Shift+Z 等平台可接受别名。因此运行时
必须注册 keyBindings 返回的全部有效序列，不能只创建一个 QShortcut(Redo) 后在帮助中
宣称另一个键也可用。SaveAs 在当前 Qt5 环境可能返回空 binding，须显式回退
Ctrl+Shift+S，并仍以 NativeText 展示。

## 3. 输入路由模型

### 3.1 固定优先级

按键只允许被以下链路中的第一个有效 owner 消费：

~~~
原生文本编辑 / IME
  → modal dialog、inline editor、popup、临时工具模式
    → 当前编辑工作区（Markup / UltraView / 配置草稿）
      → 当前图表或 View 导航域
        → MainWindow 全局命令
~~~

硬规则：

- owner 消费后必须 accept/返回 handled；其他层不得重复执行。
- 文本控件拥有标准复制、粘贴、全选、Undo/Redo；工作区快捷键不得穿透文本焦点。
- Qt.ApplicationShortcut 只用于真正全局且无上下文歧义的命令。局部编辑命令使用
  WidgetWithChildrenShortcut 或显式 focus-owner router。
- 不安装一个吞掉所有 KeyPress 的应用级 filter。UltraView 既有 viewport router
  只处理已定义 CanvasHost 手势，并让未处理事件正常传播。
- IME composing、快捷键冲突、disabled action 和已销毁 Qt wrapper 必须 fail closed。

### 3.2 命令与物理按键分离

统一命令注册表至少定义 OPEN_PROJECT、SAVE_PROJECT、SAVE_PROJECT_AS、QUIT、UNDO、
REDO、FIND、QUICK_REFERENCE、NEXT_VIEW、PREVIOUS_VIEW、VIEW_BACK、VIEW_FORWARD、
RESET_VIEW 和 RENAME。

注册表保存 command id、中文标签、Qt standard key/fallback、scope 和 help 文案；不保存
QWidget、MainWindow 或运行时 QUndoStack。菜单、toolbar tooltip、hints 和 quickref 从
该定义投影，不能各自硬编码第二份快捷键文本。

## 4. Enter / Return 合同

### 4.1 普通 dialog

- 主确认按钮显式 setDefault(True)；其余 QPushButton 显式 setAutoDefault(False)，
  除非确有第二个上下文默认动作。
- 单行输入框中 Enter 触发当前 dialog 的主确认；验证失败时 dialog 保持打开、焦点落到
  首个错误字段并显示原因。
- Esc 等价于取消/关闭，dirty draft 必须先走其既有丢弃确认。
- 删除、覆盖、清空、断开等危险 dialog 的默认按钮必须是“取消”或安全选项；Enter 不得
  默认执行危险动作。

### 4.2 局部编辑和搜索

- inline rename：Enter 提交，Esc 恢复原值；现有 View rename 行为保持。
- 数值范围/Inspector 单行字段：Enter 只提交当前字段或字段组，不隐式关闭父 dialog。
- 多行文本：Enter 插入换行；若存在提交动作，使用 Ctrl/Cmd+Enter 并明确提示。
- 搜索框：Enter 打开/应用当前高亮结果，或执行“下一个匹配”；绝不触发 Import、Delete、
  Save 等邻近按钮。
- 表格 cell editor：Enter 提交当前 cell 并按控件既有规则移动；不接受整个 dialog。
- focused button、checkbox、radio：Space 是主要激活键；Enter 可由平台标准行为激活
  明确默认按钮，但不能依赖控件创建顺序决定。

### 4.3 工具窗口例外

BatchSheet、UltraViewSheet 等独立非模态工具窗口不是表单 dialog。Return 不得调用
QDialog.accept 或关闭窗口；其内部具体编辑器按自己的 owner 合同处理 Return。

## 5. Esc 合同：一次退出一层

每次 Esc 只解除最内层、最临时的状态：

1. 取消 IME/原生文本临时编辑；
2. 取消 inline rename、drag preview、crop、draw、placement 等当前工具事务；
3. 关闭当前 popup/menu/tooltip，并把焦点还给打开它的控件；
4. 清除当前工作区临时 selection/context island；
5. 搜索框有内容时清空内容并保留焦点；无内容时关闭搜索 surface 并恢复入口焦点；
6. modal dialog 执行 reject/取消；
7. 无可取消层时 no-op。

Esc 明确禁止：退出应用、关闭项目、删除对象、回退已提交历史、清空持久化设置，或一次
跨越两层状态。UltraView 与 Markup 已有的分层 Esc 是应保留并补测的正向基线。

## 6. Undo / Redo 与图表视角历史

### 6.1 编辑历史

- Undo 使用 QKeySequence.keyBindings(QKeySequence.Undo)；Redo 使用
  QKeySequence.keyBindings(QKeySequence.Redo)，去重后全部注册。
- 当前 owner 为文本编辑器时，调用原生文本 Undo/Redo。
- 当前 owner 为 Markup 时，只操作 Markup 的 QUndoStack。
- 当前 owner 为 UltraView 时，只操作当前 Board 历史；文本编辑、工具草稿或非法 mixed
  mutation 必须阻断 Board history。
- 配置管理器已有草稿撤销入口的操作应进入同一局部 history；一次批量操作是一条原子
  entry，不拆成 N 次撤销。
- 当前上下文无可撤销内容时 Edit 菜单动作 disabled；快捷键 no-op，不转而执行别的命令。
- selection、focus、hover、打开 popup、图表视角移动和程序化 projection 不写编辑历史。

本轮不要求把所有主窗口参数变化纳入一个全局 QUndoStack。没有可靠 command/owner 的
旧操作保持“不可撤销但可保存”，不得用快照猜测或半实现的全局 Undo 制造数据风险。

### 6.2 图表视角历史

- Alt+Left：当前 focused chart 的视角后退。
- Alt+Right：当前 focused chart 的视角前进。
- Home：当前 focused chart 恢复初始/fit 视角，沿用当前 owner 语义。
- toolbar Back/Forward 按钮继续存在，历史数据结构和分支截断语义不变。
- Ctrl/Cmd+Z、Ctrl/Cmd+Shift+Z 不再触发图表 back/forward。

## 7. 标准快捷键矩阵

| 命令 | Windows/Linux | macOS | Scope / 结果 |
| --- | --- | --- | --- |
| 打开项目 | Ctrl+O | Command+O | MainWindow；先走 dirty guard |
| 保存项目 | Ctrl+S | Command+S | MainWindow；无路径时转 Save As |
| 另存为 | Ctrl+Shift+S | Shift+Command+S | MainWindow；Qt 无 standard binding 时 fallback |
| 退出 | 平台标准 Quit | Command+Q | dirty guard 完成后才关闭 |
| 撤销 | Qt Undo bindings | 平台 NativeText | 当前 edit owner |
| 重做 | Ctrl+Y、Ctrl+Shift+Z 等 Qt bindings | 平台 NativeText | 当前 edit owner |
| 查找 | Ctrl+F | Command+F | 当前可搜索 surface；否则聚焦 QuickRef 搜索 |
| 快速参考 | ? | ? | 保留现有入口；Help 菜单同时可达 |
| 下/上一个 View | Ctrl+Tab / Ctrl+Shift+Tab | Control+Tab / Control+Shift+Tab | 当前 section 的 ViewManager |
| 视角后退/前进 | Alt+Left/Right | Option+Left/Right | 当前 focused chart |
| 视角复位 | Home | 平台映射 | 当前 focused chart |
| 重命名 | F2 | F2 | focused、可重命名的 View/配置/行 |

补充键盘合同：

- Tab/Shift+Tab 按视觉顺序移动焦点，不进入装饰控件。
- Up/Down 在列表/菜单中移动当前项；Left/Right 仅用于有明确层级或横向语义的控件。
- Space 切换 focused checkbox/radio 或激活 focused button。
- Delete/Backspace 只删除当前 focused selection，沿用既有确认；无 owner 时 no-op。
- Alt+Up/Down 为可拖拽排序的 View、配置、文件行提供键盘等价操作。
- Ctrl/Cmd+A 只由 focused 文本或明确 selection surface 处理，不做全局全选。
- Ctrl/Cmd+W 暂不注册，直到“关当前 View、关工具窗还是关项目”有唯一产品定义。

## 8. 搜索、列表和键盘可达性

- 每个关键列表行可获得焦点并有 visible focus ring；accessible name 使用完整名称。
- 文件导航行支持 Up/Down、Enter/Space 打开或聚焦内容、Delete 走既有移除确认、
  Alt+Up/Down 排序；行内 close button 仍独立可聚焦。
- Channel Config Manager 的配置列表、channel table 和复选框进入合理 tab order；
  不再用 NoFocus/NoSelection 让键盘用户无法完成选择和移除。
- drag-only 操作必须有按钮、菜单或 Alt+Up/Down 等等价路径；不能仅在 QuickRef 中描述
  一个运行时不存在的键。
- 搜索有内容时 Esc 清空；空搜索再次 Esc 关闭 surface。清空不改变选中对象或项目 dirty。
- 搜索结果为空时 Enter no-op 并提供“无匹配”反馈，不意外激活 dialog default。

## 9. 项目 dirty 与安全关闭事务

### 9.1 单 owner

项目 dirty 由一个显式 ProjectDirtyState/等价 holder 所有，至少包含当前 revision、
saved revision/semantic digest、restore guard 和当前项目路径。不得在多个 MainWindow
mixin 各写一份 dirty 布尔值，也不得扩大 state-ownership whitelist 掩盖新散点状态。

dirty 只表示“当前可持久化项目语义与最后一次成功保存不同”：

- 用户修改 View、曲线绑定、轴/分析参数、注释、项目级配置、UltraView workspace 等已
  序列化字段后 dirty；
- selection、focus、hover、popup、render cache、job progress、toast、临时 preview 不 dirty；
- 打开/恢复项目时的 widget projection、View apply、replot 和 schema migration projection
  不当作用户意图；
- 保存成功后设置新 save point；保存失败或取消保持 dirty；Undo 回到 save point 后 clean，
  Redo 离开 save point 后重新 dirty。

实现前必须清点当前 project serializer 的真实字段。若 revision 事件可能漏报，关闭/替换
决策点应以同一 canonical semantic payload 做低频 digest 复核；digest 必须排除 runtime
对象、缓存和不稳定排序，不能另写一套“近似 serializer”。

### 9.2 退出/替换项目

退出应用、Quit 快捷键、窗口关闭和打开另一个项目共用一条 guard：

1. clean：直接继续；
2. dirty：显示“保存 / 不保存 / 取消”；默认按钮为“保存”，危险选项不为 default；
3. 保存：成功才继续；用户取消路径选择或保存失败则留在当前项目；
4. 不保存：明确放弃后继续；
5. 取消：零 teardown、零项目替换、零任务停止、窗口保持原样。

guard 通过后才停止 worker/timer、关闭工具窗口和销毁 Qt 对象。重复 close event、应用菜单
Quit 和系统窗口关闭必须收敛到一次 decision，不弹多个 dialog。

## 10. 菜单、提示与发现性

- 增加平台标准 File / Edit / View / Help 菜单；按钮和菜单复用同一个 QAction 或同一
  named slot，不能各自执行一次。
- Edit 菜单的 Undo/Redo 标签随 active owner 更新；没有历史时 disabled。
- tooltip 使用 Qt NativeText 显示当前平台按键，不直接拼 Ctrl/Cmd 充当运行时事实。
- ui/hints.py 与 ui/quickref.py 仍是必须同步的用户可见面，但快捷键 token 来自统一
  command registry；测试禁止同一 command 出现冲突硬编码。
- QuickRef 只保留入口、关键限制和异常提示；完整矩阵可进入帮助页。
- 快捷键迁移至少一个版本内，在旧图表提示位置说明“视角后退已改为 Alt+Left”；
  旧冲突键本身不再执行图表导航。

## 11. Ownership 与实现边界

| 层 | 职责 | 禁止 |
| --- | --- | --- |
| ui/command_registry.py（建议新增） | command metadata、Qt bindings、NativeText | import MainWindow、保存 QWidget/QUndoStack |
| MainWindow command coordinator / holder | 全局 QAction、active owner、dirty guard、菜单 enablement | 在多个 mixin 复制快捷键与 dirty 状态 |
| dialog owner | default/autoDefault、字段验证、accept/reject | 依赖创建顺序决定 Enter |
| chart card/toolbar | camera back/forward/reset | 抢占 Undo/Redo |
| Markup editor | 自己的 QUndoStack、工具 Esc、文本保护 | 写 UltraView/MainWindow history |
| UltraView Page/controller | Board history、selection/tool Esc | 从文本焦点或其他窗口截获 Undo |
| list/search widget | 局部导航、清空、激活和焦点回归 | 直接关闭项目或执行邻近危险按钮 |

新增 signal connection 使用 named slot/既有合规 helper，不扩大 connect(lambda) ratchet。
Qt wrapper 在 owner destroyed 后清理；快捷键随 surface show/activate 生效，hide/deactivate
后不能残留 application-wide activation。

## 12. 验收合同

### 12.1 自动化 acceptance IDs

- SDI-A01：三个已知 dialog 的 Enter 均到达正确确认，不触发创建/选色/导入。
- SDI-A02：危险 dialog 默认安全，取消或验证失败时零 mutation。
- SDI-A03：DB reference cell Enter 和独立 tool-window Return 例外不回归。
- SDI-A04：Esc 按最内层逐次退出；无层可退时 no-op。
- SDI-A05：搜索 Esc 首次清空、再次关闭并恢复入口焦点。
- SDI-A06：文本焦点 Undo/Redo 不穿透 Markup、UltraView 或 chart。
- SDI-A07：Markup/UltraView 接受 Qt 提供的全部 Undo/Redo bindings，且一次输入只执行一次。
- SDI-A08：图表 Alt+Left/Right 维护既有 camera history；任何 Undo/Redo binding 不导航。
- SDI-A09：Open/Save/SaveAs/Quit 只有一个 QAction owner，toolbar/menu/shortcut 不双执行。
- SDI-A10：SaveAs 在 Qt 返回空 standard binding 时仍有 Ctrl+Shift+S fallback。
- SDI-A11：菜单、tooltip、hints、quickref 对同一 command 的 NativeText 一致。
- SDI-A12：View 切换、F2 rename、列表导航、Space、Alt+Up/Down 有完整 keyboard path。
- SDI-A13：文件行和配置表有 visible focus，键盘行为与鼠标行为使用同一 mutation owner。
- SDI-A14：真实用户项目 mutation 置 dirty；保存成功清除；保存取消/失败不清除。
- SDI-A15：程序化 restore/projection、selection、render 和 preview 不置 dirty。
- SDI-A16：退出和打开替换的 Save/Discard/Cancel 共用 guard；Cancel 发生在 teardown 前。
- SDI-A17：Undo 回到 save point 后 clean，Redo 后 dirty；原子操作只产生一条 history。
- SDI-A18：隐藏/失焦/销毁局部 surface 后无 stale shortcut、ambiguous activation 或 crash。

### 12.2 前台验收

macOS Cocoa 和 Windows Full/Lite frozen 分开记录：

- 菜单显示平台原生符号；按键与 tooltip/QuickRef 一致；
- 中文 IME、单行/多行文本中 Enter、Esc、Undo/Redo 不被工作区抢走；
- dialog default focus ring 与真实 Enter 结果一致；
- 连续打开/关闭 popup、Markup、UltraView 和主窗口，无快捷键泄漏或重复触发；
- 键盘完成打开项目、搜索、切 View、改配置、保存、取消退出全流程；
- focus ring 在浅色/深色及键盘导航时可辨。

Offscreen Qt 结果不能代替 Cocoa 或 frozen Windows 输入分发证据。

## 13. 完成定义

只有同时满足以下条件才可宣称完成：

1. Enter/Esc/Undo/Redo/文件命令遵守本 Spec 的 owner 和安全合同；
2. Ctrl/Cmd+Z 不再承担图表后退，图表 camera history 完整迁移且不丢能力；
3. dirty guard 覆盖退出和项目替换，程序化 projection 不产生假 dirty；
4. 鼠标关键流程均有键盘等价操作和 visible focus；
5. runtime、菜单、tooltip、hints、quickref 对快捷键没有漂移；
6. owner tests、边界门禁、Cocoa 与 Windows frozen 验收有稳定 snapshot 证据；
7. 未修改本 Spec 非目标中的数据、计算、WWT、Batch 和持久化 schema 行为。
