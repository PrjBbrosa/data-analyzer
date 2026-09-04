# “最近打开”搜索弹层优化 Spec

- 日期：2026-09-04
- 状态：DRAFT FOR APPROVAL；HTML 视觉方向已确认，生产实现尚未开始
- 2026-09-05 前台 follow-up：800px 仍偏宽，空态副文案折行叠字。实现改为最大宽
  640px、列比 46/54、行内 padding 收紧并继续各列 ElideMiddle；空态关闭 word-wrap，
  标题与副文案分两行居中。下文 800px / 42/58 为当时冻结值，以代码常量为准。
- 冻结分析基线：`a9a2f562`
- 现有功能基线：`a3a9736e`（`feat(ui): add recent files split button next to Open`）
- 配套计划：
  [`2026-09-04-recent-open-search-popup-plan.md`](../plans/2026-09-04-recent-open-search-popup-plan.md)
- 视觉与交互参考：
  [`2026-09-04-recent-open-search-panel.html`](../ui-prototypes/2026-09-04-recent-open-search-panel.html)
- 渲染参考：
  [`recent-open-default.jpg`](../ui-prototypes/screenshots/2026-09-04-recent-open-search-panel/recent-open-default.jpg) ·
  [`recent-open-search-p166.jpg`](../ui-prototypes/screenshots/2026-09-04-recent-open-search-panel/recent-open-search-p166.jpg)
- 适用范围：顶部工具栏“打开”分裂按钮的最近项目 / 最近数据文件入口

## 0. 决策结论

现有 `QMenu` 升级为一个由“打开”右侧箭头锚定的、可搜索的 transient popup。它仍是
“最近打开”入口，不变成文件管理器或全盘索引器。

1. 弹层正常宽度冻结为 **800 logical px 上限**，不再随长路径扩张；可用屏幕不足时向内
   夹取。视觉结构、颜色和密度以配套 HTML 的收窄版为参考。
2. 弹层目标高度为 **700 logical px 上限**，搜索栏、列头和 footer 固定，结果区独立
   滚动；正常桌面高度下至少完整显示 13 行，较矮屏幕按可用区域收缩。
3. 文件名与路径改成两列：**文件名 42% / 所在位置 58%**，两列各自省略，中间有真实
   分隔线；不再拼成 `文件名 · 父目录` 的单行 action 文案。
4. 最近记录上限从“项目 4 + 文件 8”提高为 **项目 10 + 文件 40**。现有
   `files/recent_v1` 格式不变；升级不会恢复此前已被 4/8 上限淘汰的旧记录，只会从升级后
   继续积累。
5. 空查询按全局最近时间混排项目和文件；有查询时在内存中对文件名、显示路径和完整路径
   做即时模糊匹配，按匹配质量排序，同分保持最近优先。
6. popup 打开即聚焦搜索；支持 Up/Down、Enter、分层 Esc，并把 HTML 中的
   `⌘K / Ctrl+K` 作为“打开或聚焦最近搜索”的正式窗口级命令。
7. 打开文件、打开项目、缺失项处理和 QSettings owner 继续走现有路径；只替换最近记录的
   呈现与选择 UI，不增加第二套加载逻辑。

HTML 是布局、文案、状态和交互节奏的参考。网页 toast、网页 viewport 缩放和浏览器字体
栅格不是 Qt 产品合同；生产实现以本 Spec 的 logical-pixel、owner 和验收条款为准。

## 1. 用户反馈与现状证据

### 1.1 需求逐项闭环

| 用户反馈 | 当前事实 | 冻结目标 |
| --- | --- | --- |
| 显示条目太少 | `RecentFilesStore(..., max_files=8, max_projects=4)`；截图仅见 8 行 | 保存 40 个文件 + 10 个项目；正常高度完整显示至少 13 行 |
| 下拉栏太短 | 高度由 `QMenu` actions 自然撑开，无法形成固定搜索头 / 独立滚动体 | 700px 目标高度；较矮屏幕夹取，header/footer 不滚走 |
| 文件名和路径没有分隔 | `format_recent_label()` 用 `"  ·  "` 拼成一段 action text | 双列、42/58、1px 分隔线、独立省略与 tooltip |
| 没有搜索 | `QMenu` 只有 actions | 顶部 `SearchField`，打开即聚焦、即时模糊匹配 |
| HTML 太宽 | 初版视觉覆盖面积过大 | 收窄版最大 800px；实渲染约 790px，无水平溢出 |

### 1.2 已验证的代码基线

| 当前 owner / seam | 当前行为 | 本轮处置 |
| --- | --- | --- |
| `ui/recent_files.py:RecentFilesStore` | QSettings JSON、绝对路径去重、分类型淘汰、缺失检测 | 保留 owner 与 key；扩大默认上限并增加全局 MRU 投影 / 纯搜索 helper |
| `ui/recent_files.py:format_recent_label` | 文件名与父目录拼接并按字符数省略 | 生产 popup 不再使用；为兼容已有 import 暂时保留，不顺手删除 |
| `ui/toolbar.py:_make_open_split` | 创建 split button 与 `_recent_menu: QMenu` | split button 不变；单实例 `RecentOpenPopup` 替换 `QMenu` |
| `ui/toolbar.py:set_recent_entries` | 把项目与文件转成 actions | 改为向 popup 投影 immutable entries，不做加载或 QSettings mutation |
| `ui/main_window/window.py:_populate_recent_menu` | aboutToShow 时读 store 并投影 | 保留同步刷新时机；改读全局 MRU，仍不新增 MainWindow mutable state |
| `ui/main_window/window.py:_open_recent_path` | 复用 `_open_paths([path])`；失败或消失后 remove | 原样保留，popup 只发 path intent |
| `ui_kit/widgets/search_field.py:SearchField` | 自绘搜索 / 清除 icon；Esc 分层；Return 可被 host 监听 | 必须复用，不另造 QLineEdit 搜索壳 |
| `ui_kit/popup_shell.py:apply_popup_shell` | translucent + frameless + no native shadow | 必须用于新 popup，并由可见内层 surface 自绘圆角底板 |
| `ui/command_registry.py` + `CommandCoordinator` | 窗口命令单一 registry / QAction owner | 新增 OPEN_RECENT，禁止 toolbar 再手写第二个快捷键 |

现有打开分裂按钮的主按钮、箭头宽度、蓝色 primary chrome、`open_requested` 行为和
`CommandId.OPEN_PROJECT` 不变。

## 2. 范围与非目标

### 2.1 本次范围

- 最近记录容量、全局 MRU 顺序和可测试的模糊匹配。
- 单实例最近搜索 popup、双列结果、缺失状态、结果计数、空态和清除入口。
- 箭头 / `⌘K` 或 `Ctrl+K` 打开，鼠标选择和完整键盘链路。
- popup 圆角、屏幕夹取、滚动条、首帧焦点和关闭后的状态清理。
- hints、QuickRef 和主帮助页的用户可见说明同步。
- 聚焦测试、边界护栏、offscreen 几何 / 像素证据与真实 Cocoa 前台验收。

### 2.2 明确非目标

- 不扫描磁盘、不接 Spotlight / Everything service、不维护文件系统索引。
- 不搜索“从未打开过”的文件；搜索域仅限 `files/recent_v1` 内保留的最近记录。
- 不改变 `_open_paths`、`.tlproj` 读取、文件格式识别、拖放或文件对话框。
- 不增加收藏、置顶、右键菜单、删除单条记录、批量选择或排序列点击。
- 不改变 recent JSON schema/version，不迁移到 SQLite，不恢复已被旧上限淘汰的历史。
- 不把搜索结果按“项目 / 文件”分组；分组标题会减少可见行并破坏统一相关度排序。
- 不重构 `ViewOverflowPopup` 或抽取新的通用 popup framework；只复用已存在的
  `apply_popup_shell`、`SearchField` 与已验证绘制约束。
- 不以 HTML 截图代替真实 Qt Cocoa 验收。

## 3. 视觉与布局合同

### 3.1 视觉系统

沿用 TraceLab Precision Light，不引入新的装饰主题：

| token | 值 | 用途 |
| --- | --- | --- |
| tray | `#f2f4f7` | 后方工作区 |
| surface | `#ffffff` | popup / 搜索 / 行底板 |
| ink | `#111827` | 文件名与主文案 |
| muted | `#64748b` | 路径、计数与键盘提示 |
| line | `#d3dbe6` | 外框、header/footer 边界 |
| accent | `#1769e0` | 焦点、当前行、匹配反馈 |

字体继续使用产品现有栈：`Microsoft YaHei` / `Segoe UI` / `PingFang SC` /
`SF Pro Text`。文件名靠字重区分主信息，路径靠字号 / 颜色降级；不引入 monospace 路径，
避免把工程路径误读为代码块。

### 3.2 冻结线框

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ 🔍 搜索文件名或所在位置，例如 250 lowfri、P166 tlproj       ⌘K   50 条记录 │
├───────────────────────────────┬──────────────────────────────────────────────┤
│ 文件名                 最近优先 │ 所在位置                                     │
├───────────────────────────────┼──────────────────────────────────────────────┤
│ ▣ P166_连续转向…tlproj  项目   │ ~/Documents/TraceLab/Projects/P166/…          │
│ ▤ whole ±250deg_LowFri.MF4    │ ~/Downloads/data analyzer/testdoc/…           │
│ ▤ whole ±90deg_LowFri.MF4     │ ~/Downloads/data analyzer/testdoc/…           │
│ …                             │ …                                             │
│                         独立纵向滚动；无水平滚动                              │
├──────────────────────────────────────────────────────────────────────────────┤
│ ↑ ↓ 选择   Enter 打开   Esc 清空 / 关闭                    清除最近记录      │
└──────────────────────────────────────────────────────────────────────────────┘
```

除记录数和 footer 清除动作右对齐外，所有文本左对齐。搜索框是唯一强化焦点；列表不增加
卡片、渐变或重复胶囊背景。

### 3.3 外壳与几何

- popup 锚定到 `toolbarOpenSplit` 左下方，间距 4px；优先向下打开。
- `RECENT_POPUP_MAX_WIDTH = 800` logical px。当前屏幕可用宽度 ≥ 816px 时宽度为
  800px；不足时使用 `available.width() - 16px`，并在左右各保留 8px 安全边距。
- 不根据最长文件名 / 路径扩宽，不因查询或记录重建改变已打开 popup 的宽度。
- `RECENT_POPUP_TARGET_HEIGHT = 700` logical px。可用高度不足时夹取在当前屏幕内，顶部、
  底部至少各留 8px；header/footer 保持可见，只有结果区压缩。
- 搜索区目标 70px、列头 32px、footer 48px、结果行 40px；700px 高时必须完整显示至少
  13 行。字体 / QStyle 微差不得让第 13 行只露一部分。
- 圆角 12px，外边框 1px。外层 top-level 透明；可见内层 surface 自绘完整白底和四边框。
- 纵向滚动槽始终预留，避免结果从 12 条变 13 条时两列宽度抖动；水平滚动永远关闭。
- popup 必须按 anchor 所在 `QScreen.availableGeometry()` 计算，不得用主屏幕或硬编码
  1920×1080。多屏、负坐标和 toolbar 靠右时都不得越界。

### 3.4 双列与行内容

- 内容宽度按 **42% 文件名 / 58% 所在位置** 分配；正常 800px 外宽下，文件名内容列
  不小于 320px、路径列不小于 400px（不含 scrollbar / 边框的少量平台差异）。
- 列头精确文案：`文件名`、`所在位置`。空查询时文件名列右侧显示 `最近优先`；有查询时
  显示 `按匹配度排序`。
- 两列之间有 1px `#e5ebf2` 分隔线。分隔线由实际拥有该 viewport 像素的 widget /
  delegate 绘制，不能画在会被白色 child 覆盖的父 surface 上。
- 文件名和路径分别执行字体度量式省略；文件名优先 `Qt.ElideMiddle` 以保留扩展名，路径
  同样保留首尾目录。禁止重新拼成 `name · parent` 后统一截断。
- tooltip / accessible description 包含完整绝对路径与 `最近打开 YYYY-MM-DD HH:MM`。
- 项目使用项目图标并显示 `项目` badge；数据文件使用文件图标，不重复显示“文件”badge。
- 缺失项整行降级并在路径列显示 `未找到`；不可由鼠标、Enter 或双击触发打开，键盘导航
  跳过。弹出时只做一次存在性快照，输入搜索时不得重复 `Path.exists()`。
- hover 与 keyboard current 使用同一整行选中底色；当前行左侧有 3px accent 标记，但不
  改变行高或两列宽度。

### 3.5 结果与空态

- 无查询：右上角 `<N> 条记录`。
- 有查询：右上角 `<M> / <N> 条匹配`。
- 记录为空：`暂无最近记录`；辅助文案 `打开文件或项目后，会显示在这里。`；清除按钮
  disabled。
- 查询无命中：`没有匹配项`；辅助文案 `试试缩短关键词，或搜索目录名。`。
- 清除最近记录沿用现有无确认行为；成功后 popup 保持打开并即时切到“暂无最近记录”。

## 4. 模糊搜索合同

### 4.1 搜索域

每条记录建立三个只读字段：

1. `filename`：`Path(entry.path).name`；
2. `display_parent`：父目录并把 home 折叠为 `~`；
3. `raw_path`：规范化完整绝对路径。

用户可以用文件名、目录片段或两者组合搜索。匹配 `raw_path` 但命中内容不在可见
`display_parent` 时，结果仍保留，tooltip 提供完整路径；不得把完整绝对路径塞回列表抢宽。

### 4.2 规范化与 token 语义

- 查询和候选按 Unicode NFKC + `casefold()` 规范化；`\` 与 `/` 视为同一路径分隔符。
- 查询按连续空白拆成 tokens；空 token 丢弃。
- 多 token 使用 **AND**：每个 token 都必须在 filename、display_parent 或 raw_path 的
  任一字段命中；不同 token 可以分别命中文件名和路径。
- 单 token 优先连续子串；连续子串不存在时允许按字符顺序的 subsequence 模糊匹配。
- 第一版不解释 `*`、`?`、正则、引号短语、排除符号或布尔语法；这些字符按普通字符处理。

示例：

| 查询 | 预期 |
| --- | --- |
| `lowfri 0526` | 文件名命中 `LowFri` 且路径命中 `0526` 的记录 |
| `w250lf` | subsequence 命中 `whole ±250deg_LowFri.MF4` |
| `p166 tlproj` | 同时命中 P166 路径 / 名称与项目扩展名 |
| `LOWFRI` | 大小写不敏感，结果与 `lowfri` 相同 |
| `zz-no-match` | 0 条并显示无结果空态 |

### 4.3 排序

空查询严格保持 store 的全局 MRU 顺序，项目和文件混排。有查询时每个 token 的最佳命中
按下列优先级构成稳定排序 key：

1. filename 完全匹配；
2. filename 前缀；
3. filename 连续子串；
4. filename subsequence；
5. display_parent / raw_path 的目录段前缀；
6. 路径连续子串；
7. 路径 subsequence。

同一层级内，起点越靠前、subsequence 间隙越小越优；多 token 汇总后仍同分时按原始
MRU 次序。排序必须确定性，不依赖 Python hash 顺序。

可见 filename / display_parent 中的命中字符使用 accent wash 高亮。高亮 spans 必须来自
matcher 的 source-index 映射，不允许用第二套正则近似导致排序命中与高亮不一致。

### 4.4 性能与错误边界

- 搜索只遍历最多 50 条内存记录，不启线程、不加 debounce；`textChanged` 后同一事件循环
  turn 内更新结果、计数和 current row。
- 搜索热路径禁止文件 I/O、QSettings 读取、`Path.exists()`、图标重新栅格化或 MainWindow
  回调。
- 空、长查询和非 ASCII 查询不得抛错。matcher 是纯函数，输入 tuple，输出 immutable
  match projections。
- 不写基于墙钟毫秒数的脆弱单测；用调用计数证明热路径无 I/O，并在真实 popup 中人工确认
  连续输入无明显卡顿。

## 5. 输入、焦点与关闭合同

| 输入 / 状态 | 唯一结果 | 明确禁止 |
| --- | --- | --- |
| 点击打开箭头，popup 关闭 | 同步刷新 entries，显示 popup，清空旧 query，聚焦 SearchField，选择第一条可打开记录 | 不触发主“打开”文件对话框 |
| 点击打开箭头，popup 已开 | 关闭 popup | 不创建第二个实例 |
| `⌘K / Ctrl+K`，popup 关闭 | 走同一 `show_recent_popup()` 路径 | 不复制 populate / geometry 逻辑 |
| `⌘K / Ctrl+K`，popup 已开 | 聚焦搜索并全选 query | 不关闭 / 重建 popup |
| 普通字符 | 继续在搜索框输入并即时过滤 | 不把焦点移到列表 |
| Up / Down | current row 在可打开结果间循环并滚入可见区；搜索框保持焦点 | 不进入缺失项，不修改 query |
| Enter | 打开 current row，精确发一次 path intent，关闭 popup | 不同时触发默认按钮或主“打开” |
| 单击 / 双击可用行 | 第一次激活只发一次 path intent并关闭 | 双击不得双开 |
| Esc，query 非空 | 只清空 query，搜索保持焦点，popup 保持打开 | 不关闭 |
| Esc，query 为空 | 关闭 popup并把焦点还给箭头 | 不触发窗口级退出 |
| 点击 popup 外 | Qt.Popup 正常关闭；不抢回用户刚点击的新焦点 | 不残留 expanded 状态 |
| 清除最近记录 | 发一次 clear intent；owner 清 store 后投影空态，popup 保持打开 | 不直接从 presentation 写 QSettings |

Tab 顺序至少覆盖 SearchField 与“清除最近记录”；图标型清除按钮继续服从共享
`SearchField` 的 NoFocus 合同。列表本身使用 row selection，但 Everything 式键盘输入期间焦点
留在 SearchField。

## 6. 最近记录数据合同

- `RecentEntry(path, kind, opened_at)`、`KEY_RECENT_V1 = "files/recent_v1"` 和 JSON 字段
  原样保留。
- `RecentFilesStore` 默认 `max_files=40`、`max_projects=10`；显式注入的测试上限继续生效。
- 新增只读 `all_entries() -> tuple[RecentEntry, ...]`，返回 `_load()` 的全局 MRU 顺序；既有
  `entries(kind)` 保留给现有调用 / 测试。
- 记录仍以规范化绝对路径 identity 去重；重新打开会跨 kind 去重并置顶。
- 淘汰仍分别按 kind 执行，保证项目不会被高频数据文件完全挤出；序列中其余项的全局顺序
  不得重排。
- 旧 v1 payload 必须直接可读；不写迁移标记。升级后的第一次 record 才按新上限保存。
- JSON 损坏、字段缺失和 QSettings 失败继续遵守现有 warning-once / empty 行为。
- `exists` 是 popup projection 的状态，不进入持久化 JSON。

## 7. 组件与 ownership

| 层 | 职责 | 禁止 |
| --- | --- | --- |
| `ui/recent_files.py` | store、全局 MRU、纯规范化 / 匹配 / 排序 DTO | import MainWindow、toolbar、ui_kit；持有 QWidget |
| `ui/widgets/recent_open_popup.py`（新） | popup chrome、SearchField、双列表格、selection、geometry、typed intents | 读写 QSettings、调用 `_open_paths`、import MainWindow |
| `ui/toolbar.py` | 保持 split button；持有一个 popup；转发 refresh/open/clear intent | 重做 search algorithm 或打开文件 |
| `ui/command_registry.py` | `OPEN_RECENT` metadata、平台原生 shortcut text | live popup state |
| `ui/main_window/command_coordinator.py` | 唯一窗口 QAction；快捷键调用 toolbar 同一 show 方法 | 新建第二个 popup / QShortcut |
| `ui/main_window/window.py` | 从 store 投影、clear store、沿用 `_open_recent_path` | 新增跨 mixin state、按名称识别记录 |

`RecentOpenPopup` 至少发出：

- `open_requested(str path)`
- `clear_requested()`
- `closed()`

Toolbar 对外现有 `recent_open_requested(str)`、`recent_clear_requested()` 和
`recent_menu_about_to_show()` 暂时保留；最后一个名字虽然含 `menu`，但已是当前生产 seam，
本轮不为命名洁癖增加兼容 alias。内部 `_recent_menu` / QAction 结构不是兼容合同，应删除。

popup mutable state（query、matches、current index、exists snapshot、打开后的固定尺寸）全部由
popup 单一实例持有，并在新 show session、hide、parent destroy 路径对称复位。不得扩大
`tests/ui/test_main_window_state_ownership.py` 白名单。

## 8. Qt popup、绘制与生命周期合同

- `RecentOpenPopup(QFrame, Qt.Popup)` 由 Toolbar parent；Toolbar 生命周期内最多一个实例。
- 构造时调用 `apply_popup_shell()`，设置 `WA_NoSystemBackground` / `NoFrame`；不得依赖全局
  QMenu QSS，因为实现已不再是 QMenu。
- 透明 top-level 不画白底；可见 inner surface 自己 paint 圆角 fill / border。table viewport、
  header、footer 留 1px frame guard，四边与 outer shell 共线，不出现内缩台阶。
- table selection、column divider、footer hover 的像素必须由实际覆盖该区域的 child /
  delegate paint；不能只断言 stylesheet token 或 parent grab。
- `hideEvent` / `closeEvent` 发一次 closed，箭头 expanded 状态对称复位。重复 open/close 不
  新建 top-level window，不积累 signal connection、timer 或 deleted Qt wrapper。
- `populate()` 在 popup 可见时保留当前 query，重新过滤并按 path identity 尽量保留 current；
  新的一次 show session 则清 query并从第一条可用记录开始。
- 所有 row DTO 和图标 wrapper 在 owner 消失前清理；若缓存 Qt wrapper，复用前必须验证
  `sip.isdeleted()`，否则不缓存。

## 9. 文案、快捷键与可访问性

- Search placeholder：`搜索文件名或所在位置，例如 250 lowfri、P166 tlproj`
- 箭头 tooltip / accessible name：`搜索最近打开的项目和文件 (<NativeText>)`
- `CommandId.OPEN_RECENT`：label `打开最近…`，fallback `Ctrl+K`，scope `WINDOW`；macOS
  NativeText 必须由 registry 渲染为 `⌘K`，Windows/Linux 为 `Ctrl+K`，禁止手写平台分支文案。
- QuickRef 的“打开数据 / 项目”行必须说明：最近 10 个项目 / 40 个文件、文件名与路径搜索、
  缺失项灰显、清除记录和 native shortcut。
- hint 保留 id `toolbar.recent_menu` 与 `retire_on="recent_open"`，更新为“打开旁箭头可搜索
  最近项目和文件”，并继续通过宽度预算。
- 主帮助页 load slide 同步搜索、容量和双列说明；不改 dated changelog 的历史版本文案。
- 每行 accessible name 含 kind、完整文件名和完整路径；缺失行明确附加 `未找到，不可打开`。
- 高亮不是唯一反馈：结果计数、排序提示与 current row 背景必须同时可见。

## 10. 验收矩阵

### 10.1 数据与搜索

- 默认上限精确为文件 40 / 项目 10；显式小上限、去重、置顶和分类型淘汰不回归。
- `all_entries()` 保持 project/file 全局 MRU 混排；旧 v1 payload 无迁移即可读取。
- `lowfri 0526`、`w250lf`、`p166 tlproj`、大小写、中文、反斜杠路径和零命中均有纯函数测试。
- 多 token AND、field 跨越、排序层级、gap tie-break 与 MRU final tie-break 均为确定结果。
- 连续输入期间 QSettings read、exists probe 和图标构建计数均为 0。

### 10.2 popup 与接线

- Toolbar 内只存在一个 `RecentOpenPopup`；不再存在 `_recent_menu` 或为 recent rows 创建的
  QAction。
- 箭头、OPEN_RECENT QAction 和再次聚焦均落到同一 `show_recent_popup()`。
- click / double-click / Enter 每次只发一个完整 path；缺失项发 0 次。
- Esc 两阶段、外点关闭、焦点恢复、clear 后空态和 reopen 重置 query 均有 Qt 测试。
- popup 重复打开 / 关闭 20 次后实例数、signal 次数和 child 数不增长。
- `_open_recent_path` 仍是唯一加载 seam；竞态删除 / 打开失败仍会从 store 移除。

### 10.3 几何与视觉

- 正常屏幕：popup outer width ≤800 且为 800±1 logical px；两列约 42/58，误差 ≤2px。
- 700px outer height时至少 13 个完整 40px rows；footer / search / header 均完全可见。
- 可用屏幕窄 / 矮、负坐标副屏、toolbar 靠右时外框不越出 availableGeometry。
- 无水平滚动；纵向 scrollbar 预留不引起列宽跳动。
- Cocoa 首帧搜索已聚焦、圆角四角无矩形 backing、header/body/footer 四边共线。
- 长文件名 / 长路径各自在自己的列内省略，扩展名 / 尾目录可见，tooltip 可读全路径。
- hover、keyboard selection、匹配高亮、missing 和 focus-visible 在真实前台可区分。

### 10.4 不回归

- 主“打开”仍只打开文件 / 项目对话框；箭头与 shortcut 不触发主 action。
- Save split、Batch、toolbar compact 布局和高度不变。
- QSettings 测试不读写开发者真实 `MF4Analyzer/DataAnalyzer` store。
- `test_no_lambda_signal_connections` 与 MainWindow ownership 棘轮不得放宽。
- 新 popup QSS 不改变全局 QMenu、SearchField、View overflow 或其他 table/list 的样式。

## 11. 完成定义

- [ ] 用户确认本 Spec 中 800px 宽度、700px 高度、40+10 容量与 `⌘K / Ctrl+K`；
- [ ] 配套 HTML 保持最大 800px，并有默认 / 搜索两张渲染图；
- [ ] 纯 matcher 与 50 条 MRU store 合同由红测先冻结；
- [ ] 自定义 popup、双列、搜索、keyboard、missing、empty、clear 全部通过 owner tests；
- [ ] command registry、hints、QuickRef、主帮助页同步且无手写平台快捷键副本；
- [ ] rounded shell / frame / SearchField icon / QSettings / MainWindow ownership 边界通过；
- [ ] macOS Cocoa 前台完成真实 popup 几何、像素、输入和外点关闭验收；
- [ ] 未运行的 Windows 前台 / frozen acceptance 明确标为 `UNVERIFIED`，不得由 offscreen 代替；
- [ ] `git diff --check` 通过，提交范围不含任何预先存在的删除或根目录 untracked 文件。
