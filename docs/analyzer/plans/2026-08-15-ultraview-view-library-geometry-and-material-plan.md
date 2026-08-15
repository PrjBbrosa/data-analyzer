# UltraView View 库 —— 几何止跳与月白石蓝质感对齐 plan

- 日期：2026-08-15
- 状态：ACCEPTED（三处产品决策已由用户拍板，见 §3）
- 基线：`main@380e5ac2`（"加宽 View 库并换成展开/概览，布局改月白石蓝"）
- 原型基线：[2026-08-15-ultraview-view-library-rework-options.html](../ui-prototypes/2026-08-15-ultraview-view-library-rework-options.html)
- 前序 plan：`2026-08-15-ultraview-view-library-chrome-plan.md`（信息架构：展开/概览两态、去色条、无新建）——**那一包的产品语义保留，本包只修它落地时留下的几何与材质问题**。

## §0 执行护栏

- 本 plan 的所有数字都是**实测值**，不是估算。复现命令见 §7.1，探针脚本清单见 §7.4。
  执行者动手前先按 §7.1 重跑一遍现状探针，确认与本文 §1 的表格一致；**不一致就先停下来对账**，
  说明工作区已被其它会话改过（lesson：Codex 会话可能并行改工作区）。
- 与在途批的重叠：`2026-08-15-ultraview-board-popover-and-trigger-state-plan.md` 与
  `2026-08-15-ultraview-layout-and-material-polish-plan.md` 也动 `style.qss` / `page.py`。
  本包动的 QSS 段是 `style.qss:3869-4070` 的 `ultraViewLibrary*` 块，`page.py` 只动
  `_overlay_size` 的一个字面量；冲突面小但**执行前 `git status` 对账**。
- 每项修复配一条「能抓住原缺陷」的测试，先红后绿。§6 逐条给出。
- QSS 状态规则不许 `border:` 简写（会把 `border-radius` 打成 0），只动 `border-color`
  （`tests/ui_kit/test_qss_border_shorthand.py` 看守）。
- 新信号连接用 bound method / `functools.partial`（`.connect(lambda` 棘轮）。
- 视觉项 offscreen 只当排版草稿；材质/配色的最终验收必须 Cocoa 真机（Gotchas）。
  验收要自动化——截图 + 几何断言 + 哈希，不把人工清单丢给用户。
- UI 交互有增删改，收尾走 `/update-hints` 同步 `ui/hints.py` 与 `ui/quickref.py`。

---

## §1 现状实测

### 1.1 面板会跳（1280×800，探针 `probe3`）

| 操作 | 面板 rect (x, y, w, h) | 相对打开态 |
|---|---|---|
| 打开（展开态） | (68, **64**, 470, **656**) | — |
| 切「概览」 | (68, **147**, 470, **356**) | 顶边下移 83，高度掉 300 |
| 折叠「时域」 | (68, **81**, 470, **488**) | 顶边下移 17，高度掉 168 |
| 搜索 `View 1` | (68, 64, 470, **530**) | 高度掉 126 |
| 清空搜索 | (68, 64, 470, 656) | 回到打开态 |

**注意这张表有两个坏味道叠在一起**：上表是**每步显式调用 `_apply_floating_layout()` 之后**测的。
产品里这几个面板内操作**都不会触发重排** —— `_apply_floating_layout` 的调用点只有
初始化（`page.py:475`）、开/关面板（`820` / `845`）、`set_board`（`1696`）、
演示切换（`1537`）、窗口 resize（`1843`）、CanvasHost resize（`1850`）。所以真实体感是：

- 操作当下：面板外框不动，**内容与外框对不上**——展开态内容溢出被裁、概览态卡片被撑大；
- 下一次窗口 resize / 重新打开 / **往 Board 加一个 View（走 `set_board`）** 时：
  面板**突然**跳到上表里那个完全不同的高度。

用户说的"面板高度还会乱跳"就是这两段叠加出来的：跳动与触发它的操作**在时间上是错开的**，
所以看起来毫无规律。这也是为什么只调"高度上限"治不好——得让高度从一开始就与内容无关（§3.2）。

### 1.2 展开态：分组卡被裁（探针 `probe_lib` / `probe4`）

| 分组 | 实际渲染高度 | 自身 `minimumSizeHint` | 结论 |
|---|---|---|---|
| 时域（4 行） | **164** | **215** | 被压 51px → 最后一行的通道行被卡片下边框切掉 |
| 频谱 / 时频 / 频响 / 阶次（各 1 行） | 83 | 83 | 正常 |

即用户截图 1 里"时域卡片下边框横穿 View 4 的通道名"的直接来源。

### 1.3 概览态：卡片被撑大（探针 `probe_lib`）

| 项 | 实测 |
|---|---|
| `_LibraryCatalogCard.sizeHint()` | 43 |
| 实际渲染高度 | **81 / 80 / 81 / 80 / 81** |

五张摘要卡把整个视口高度均分了 —— 用户截图 2 的形态。

### 1.4 内部度量与 HTML 的偏差（探针 `probe2`）

| 元素 | HTML 原型 | 产品实测 | 偏差 |
|---|---|---|---|
| 面板宽 | 470 | 470 | ✅ 一致 |
| 弹层头 | `min-height:52`，底部 1px 分隔线 | 无独立头区，无分隔线（root margins 10 一路到底） | 头与列表共用同一内缩，读不出"头" |
| 搜索框高 | 35 | 32 | 偏矮 |
| 展开/概览 tab | `flex:1`，各占半宽（≈222） | 各 **53** 宽，浮在半格中央 | ⚠️ 最明显的"不整齐" |
| 分组头高 | 32 | 32 | ✅ |
| 分组头/列表分隔 | `.view-group-content` 有 `border-top` | 无 | 分组头是"飘"的 |
| View 行高 | 38（单行） | 42（两行） | 见 §3.1 决策 |
| 行内圆点左内缩 | 15 | **7** | 圆点几乎贴着卡片边框 |
| ＋/− 按钮 | 23×23，薄荷描边 | **20×20**，Tailwind 亮绿/亮红实心 | 尺寸与调子都不对 |
| 概览卡高 | 40 | hint 43 / 实渲 80 | 见 §1.3 |
| 滚动条 | 在 12px body padding 之外 | 8px 竖条**压在分组卡右边框上** | 卡片被啃掉一条 |

---

## §2 根因（四条独立机制，必须四条都修）

### R1 —— 面板高度 = 内容高度，而内容高度天天变

`ViewLibraryPanel.sizeHint()`（`widgets.py:1577`）返回
`max(LIBRARY_OVERLAY_MIN_HEIGHT, _content_height())`，而 `_content_height()`
（`widgets.py:1590`）= `20+36+40+32 + _measured_body_height()`。
`page._overlay_size()`（`page.py:650`）直接吃这个 `sizeHint`，
`floating_layout._place_overlay()`（`floating_layout.py:391`）再拿它算 rect。

于是「折叠一个分组 / 切一次概览 / 敲一个字」都会改面板外框尺寸。

### R2 —— 锚点是"触发按钮垂直居中"，所以高度一变顶边跟着挪

`floating_layout.py:416`：

```python
anchor_y = trigger_rect.top + (trigger_rect.height - height) // 2
```

`height` 出现在分子里。R1 让 `height` 抖，R2 就把抖动放大成**顶边位移**
（656→356 时顶边挪 83px）。两条合起来才是"乱跳"，单修一条不够。

### R3 —— 手写的高度公式与真实控件度量长期脱节

`_measured_body_height()`（`widgets.py:1594`）用常量重算了一遍 Qt 已经算过的东西：

```
LIBRARY_SECTION_MIN_HEIGHT = 32   实际分组头 = 34（QSS min-height 是 content-box，1px 边框 ×2）
LIBRARY_ROW_MIN_HEIGHT     = 40   实际行     = 42（同上）
                                  分组卡自身 contentsMargins(1,1,1,4) = 5px，公式里根本没算
```

实测：公式给 **528**，`_body_layout.totalMinimumSize()` 给 **579**，差 51px。
`_sync_body_min_height()` 把 528 钉成 `_body` 的最小高度，QVBoxLayout 只好压缩最大的那个分组
（时域 215→164）→ **裁切**。

> 这是本包最值得记住的一条：**QSS 的 `min-height` 是 content-box，1px 边框会额外加 2px。**
> 18 渲染成 20、40 渲染成 42、32 渲染成 34 全是这一条。所以本包所有常量一律按**外框高度**定义，
> QSS 里写 `常量 − 2`，并由测试钉死渲染后的外框值（§6）。

### R4 —— 两个 host 后面没有 stretch

`_rebuild()`（`widgets.py:1540-1541`）把 `_groups_host` 和 `_compact_host` 加进
`_body_layout` 后就结束了，没有尾部 stretch。`QScrollArea.setWidgetResizable(True)`
把 `_body` 撑到视口高度，多出来的空间被 QVBoxLayout 均分给可见 host 里的卡片
→ 概览卡 43 变 80。

---

## §3 已拍板的三处产品决策

### 3.1 View 行：两行 46px，节奏钉死

HTML 的行是单行 38px（名称 + 右侧一小段 mono 量程）。产品这里第二行是**通道名列表**
（`ultraview_coordinator._checked_summary`，取前 3 个 checked 通道，多余记 `+N`），
而 View 名常常就是默认的 `View 1..N` —— 通道列表是列表里**唯一**能区分它们的信息。

**决策：保留两行，但把行高按实测钉成常量 46，第二行改 mono 弱色。**
这是对 HTML 的一处**有意偏离**，理由写进代码注释与 spec 批注：整齐度靠精确高度拿，不靠删信息。

### 3.2 面板高度：定高常量 + 保留触发锚点

**决策：`ViewLibraryPanel.sizeHint()` 返回常量高度，与内容完全无关；内容只在里面滚。**
保留 HTML「以触发按钮垂直中心为锚点」的合同（`floating_layout` 不改）。

已用探针 `probe5` 验证（把 `sizeHint` 换成常量 560 后，跨窗口尺寸实测）：

| 页面尺寸 | 打开 | 切概览后 | 切回展开后 |
|---|---|---|---|
| 1280×800 | (68, 64, 470, 560) | (68, 64, 470, 560) | (68, 64, 470, 560) |
| 1280×720 | (68, 64, 470, 560) | 同左 | 同左 |
| 1600×1000 | (68, 145, 470, 560) | 同左 | 同左 |
| 1000×620 | (68, 64, 470, **496**) | 同左 | 同左 |

**rect 在任何面板内操作下恒定**；只有窗口尺寸变化才会动（620 高的窗口被安全带夹到 496，符合预期）。

### 3.3 ＋/− 按钮：降饱和，保留语义色

现状 `#d1fae5/#34d399/#047857`（绿）与 `#fecaca/#f87171/#b91c1c`（红）是 Tailwind 告警色，
在月白石蓝里是整个面板最抢视线的东西；HTML 那边只有一个克制的薄荷描边 `+`，根本没有红。

**决策：`+` 用 HTML 的薄荷描边；`−` 换成同明度带的低饱和陶土色。加/移仍一眼可分，但不再抢视线。**

---

## §4 目标常量表

全部按**外框**定义（含 1px 边框）。QSS 里写 `值 − 2`。

```python
# widgets.py 常量区（现 widgets.py:334-352）
LIBRARY_DEFAULT_WIDTH       = 470   # 不变，= HTML .popover width
LIBRARY_MAX_WIDTH           = 520   # 不变
LIBRARY_OVERLAY_HEIGHT      = 560   # 新增：定高常量（§3.2）
LIBRARY_OVERLAY_MIN_HEIGHT  = 360   # 320 → 360，短窗口下仍能露出 4 个分组
LIBRARY_HEAD_HEIGHT         = 52    # = HTML .popover-head min-height
LIBRARY_SEARCH_HEIGHT       = 34    # HTML 35，取偶数让 1px 边框居中
LIBRARY_MODE_TAB_HEIGHT     = 28    # = HTML .architecture-tabs button
LIBRARY_SECTION_GAP         = 8     # HTML .view-groups gap 7 → 8，Qt 偶数节奏
LIBRARY_SECTION_HEAD_HEIGHT = 32    # = HTML .view-group-head
LIBRARY_ROW_HEIGHT          = 46    # 两行（§3.1）；替换 LIBRARY_ROW_MIN_HEIGHT
LIBRARY_SECTION_ROW_GAP     = 4     # 2 → 4
LIBRARY_CATALOG_HEIGHT      = 40    # = HTML .catalog-card；替换 LIBRARY_CATALOG_MIN_HEIGHT
LIBRARY_CATALOG_GAP         = 8     # = HTML .catalog-stack gap
LIBRARY_ROW_ACTION_SIZE     = 23    # = HTML .row-action
LIBRARY_ROW_DOT_INSET       = 14    # 圆点左内缩（HTML 15，扣掉分组卡 1px 边框）
```

配色（沿用 UltraView 局部月白石蓝 token，**不动全局 `CONTROL_COLORS`**）：

> **2026-08-15 落地修订。** 本表初稿一次引入 13 个新 hex literal，触发
> `tests/ui_kit/test_qss_palette_ratchet.py` 的 shrink-only 上限（241 → 249 > 244）。
> **护栏没有放宽**，改为按语义合并到既有 literal，最终落回 244、两条断言皆绿：
> - `+` 两档底色并入既有**正向 wash 家族**：`#E9F8F2`（`BatchFileReadyPill[status="ready"]`）
>   与 `#EAF7EE`（`toast[level="success"]`）—— 同语义角色，是真合并。
> - 行内次要说明并入 `#8291A5`（`channelConfigHtmlPreviewNote`）—— 同为弱化正文。
> - `−` 两档底色**坚持自建 literal**：最近的既有邻居是 toast / rec 的**错误色**，
>   别名过去等于把 §3.3 刚去掉的告警调子塞回来。
> - hover / pressed 只变底色与描边，**墨色恒定**；pressed 用静息墨色当描边。
>   这既省掉两个 literal，也是更克制的标准做法。

| 用途 | 静息 | hover | pressed |
|---|---|---|---|
| `+` 墨 / 描边 / 底 | `#3B7C5C` / `#A5C6B4` / `#E9F8F2` | `#3B7C5C` / `#4C936F` / `#EAF7EE` | `#3B7C5C` / `#3B7C5C` / `#EAF7EE` |
| `−` 墨 / 描边 / 底 | `#9C5A4E` / `#D8B3AE` / `#FAF0EE` | `#9C5A4E` / `#B87A6C` / `#F5E4E0` | `#9C5A4E` / `#9C5A4E` / `#F5E4E0` |
| 行内次要说明 | `#8291A5`（复用既有） | — | — |

---

## §5 实施任务

> 顺序有依赖：Task 1 是止跳的地基，Task 2/3 依赖它把高度算对。Task 4/5 是纯材质，可并行。

### Task 1 —— 面板定高，杀掉内容驱动的 sizeHint（修 R1 + R2）

文件：`mf4_analyzer/ui/chart_stack/ultraview/widgets.py`、`mf4_analyzer/ui/chart_stack/ultraview/page.py`

- [ ] `ViewLibraryPanel.sizeHint()`（`widgets.py:1577`）改为
      `QSize(LIBRARY_DEFAULT_WIDTH, LIBRARY_OVERLAY_HEIGHT)`——常量，不再看内容。
- [ ] `minimumSizeHint()`（`widgets.py:1583`）改为 `QSize(280, LIBRARY_OVERLAY_MIN_HEIGHT)`。
- [ ] **删除** `_content_height()`（`widgets.py:1590`）——它唯一的消费者就是上面那个 `sizeHint`。
- [ ] `page._overlay_size()`（`page.py:652`）里 `PANEL_LIBRARY: (LIBRARY_DEFAULT_WIDTH, 320)`
      的 `320` 换成 `LIBRARY_OVERLAY_MIN_HEIGHT`（已 import `LIBRARY_DEFAULT_WIDTH`，补 import）。
- [ ] `floating_layout.py` **不动**——触发居中锚点是有意保留的合同（§3.2）。

方法上的关键点：这一步是"把高度从内容里摘出来"，不是"给高度加个上限"。
加上限只会把跳动区间收窄，仍然会跳。

### Task 2 —— 高度改由布局自算，别再手写公式（修 R3）

文件：`mf4_analyzer/ui/chart_stack/ultraview/widgets.py`

- [ ] `_measured_body_height()`（`widgets.py:1594`）整个替换为
      `return self._body_layout.totalMinimumSize().height()`。
      实测：手写公式 528，Qt 自算 579，差 51 —— 而 579 正是不裁切所需的值。
- [ ] `_sync_body_min_height()`（`widgets.py:1615`）保留，改用上面的返回值。
- [ ] `_on_section_toggled`（`widgets.py:1618`）里 `setVisible` 后仍要调
      `_sync_body_min_height()`（现有调用保留）。
- [ ] 常量重命名：`LIBRARY_ROW_MIN_HEIGHT` → `LIBRARY_ROW_HEIGHT`（46），
      `LIBRARY_SECTION_MIN_HEIGHT` → `LIBRARY_SECTION_HEAD_HEIGHT`（32），
      `LIBRARY_CATALOG_MIN_HEIGHT` → `LIBRARY_CATALOG_HEIGHT`（40）。
      重命名的意义是语义：它们从此是**外框定高**，不是"最小值"。
- [ ] `LibraryRowWidget.__init__`（`widgets.py:1077`）：`setMinimumHeight` → `setFixedHeight(LIBRARY_ROW_HEIGHT)`。
- [ ] `_LibraryCatalogCard.__init__`（`widgets.py:1240`）：同上，`setFixedHeight(LIBRARY_CATALOG_HEIGHT)`。
- [ ] `_LibrarySectionHeader.__init__`（`widgets.py:1178`）：`setFixedHeight(LIBRARY_SECTION_HEAD_HEIGHT)`。

**QSS 侧同步（content-box 陷阱）**：`style.qss` 里
`QFrame#ultraViewLibraryRow { min-height: 40px }` → `min-height: 44px`（44 + 1px×2 = 46）；
`QFrame#ultraViewLibrarySectionHead { min-height: 32px }` → `30px`。
凡是配了 `setFixedHeight` 的，QSS 值必须是 `常量 − 2`，两边不许各说各话。

### Task 3 —— 尾部 stretch，止住概览卡气球化（修 R4）

文件：`mf4_analyzer/ui/chart_stack/ultraview/widgets.py`

- [ ] `_rebuild()` 末尾（`widgets.py:1541` 之后、`_sync_mode_visibility()` 之前）加
      `self._body_layout.addStretch(1)`。
      实测：加之前概览卡 `[81, 80, 81, 80, 81]`，加之后 `[43, 43, 43, 43, 43]`（= 各自 hint）。
- [ ] **stretch 必须放在 `_rebuild()` 里，不能只在 `__init__` 里加一次。**
      `_rebuild()` 开头的清空循环（`widgets.py:1475-1479`）是 `while count(): takeAt(0)`，
      会把 spacer 一并取走 —— 已实测：连续 4 次 `_rebuild()` + 重加，
      `_body_layout.count()` 稳定在 3，**不会累积**，所以清空循环本身不用改
      （`item.widget()` 对 spacer 返回 `None`，现有的 `is not None` 守卫已经处理）。
      漏在 `__init__` 里加则是反过来：第一次 rebuild 之后 stretch 就没了，概览卡重新气球化。

### Task 4 —— 面板骨架对齐 HTML（头区 / 搜索 / 分段控件 / 滚动槽）

文件：`mf4_analyzer/ui/chart_stack/ultraview/widgets.py`、`mf4_analyzer/ui_kit/style.qss`

- [ ] **root margins 归零**（`widgets.py:1293` 的 `setContentsMargins(10,10,10,10)` → `0,0,0,0`），
      改由三段各自持有内缩，让头区能画满宽的分隔线：
  - 头区：`QHBoxLayout` margins `(14, 12, 10, 10)`，固定高 `LIBRARY_HEAD_HEIGHT`；
    标题「View 库」+ 计数「N 个」+ 钉住按钮（**钉住保留，不换成 HTML 的关闭 ×**——
    钉住是已定的产品语义，`_on_library_pin_toggled` 挂着 `set_overlay_close_on_canvas`）。
  - 头区之下插一条满宽 1px `QFrame.HLine`，objectName `ultraViewLibraryHeadRule`，
    色 `#C7D4DF`（对应 HTML `.popover-head` 的 `border-bottom`）。
  - 搜索 + 分段控件区：margins `(12, 10, 12, 0)`。
  - `QScrollArea` 满宽（不带左右内缩），`_body_layout` margins `(12, 10, 12, 12)`
    —— 这样竖滚动条落在 12px 的槽里，不再压在分组卡右边框上（§1.4 最后一行）。
- [ ] 搜索框固定高 `LIBRARY_SEARCH_HEIGHT`；QSS `QLineEdit#ultraViewLibrarySearch`
      补 `min-height: 32px`（32 + 1px×2 = 34），radius 8 → 9。
- [ ] **展开/概览改成真正的分段控件**：两个 QToolButton 加
      `setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)`，固定高 `LIBRARY_MODE_TAB_HEIGHT`。
      实测：改前各 53 宽浮在半格中央，改后各 **222** 宽（= 448 内容宽的一半），
      选中态成为半宽色块，与 HTML `.architecture-tabs button { flex:1 }` 一致。
- [ ] 分组头与行之间补 1px 分隔线（对应 HTML `.view-group-content { border-top }`）：
      在 `_rebuild()` 的 section 循环里，`header` 之后、第一行之前插一条
      `QFrame.HLine`（objectName `ultraViewLibrarySectionRule`），
      **仅当该分组展开且有行时可见**；折叠时随行一起 `setVisible(False)`
      （挂进 `_on_section_toggled` 的同一次遍历里）。

### Task 5 —— 行内几何与 ＋/− 材质

文件：`mf4_analyzer/ui/chart_stack/ultraview/widgets.py`、`mf4_analyzer/ui_kit/style.qss`

- [ ] `LibraryRowWidget` 布局 margins（`widgets.py:1081`）
      `(6, 4, 4, 4)` → `(LIBRARY_ROW_DOT_INSET, 5, 8, 5)`，spacing 8。
      圆点从距卡片内缘 7px 移到 14px（HTML 15，扣 1px 分组卡边框）。
- [ ] 第二行（`self._meta`，`widgets.py:1091`）改 mono 弱色：QSS
      `QLabel#ultraViewLibraryMeta { font-size: 11px; color: #8A95A7; }`
      并在构造时设等宽字体（照 `chrome.NavigationIsland` 的 `QFont.Monospace` + `setFixedPitch(True)` 写法）。
      对应 HTML `.view-row small { font: 8px/1 var(--mono) }` 的角色，字号按产品可读性放大。
- [ ] `_add` 按钮（`widgets.py:1100`）`setFixedSize(18,18)` → `setFixedSize(LIBRARY_ROW_ACTION_SIZE, LIBRARY_ROW_ACTION_SIZE)`；
      QSS `QToolButton#ultraViewLibraryAdd` 的 `min/max-width|height: 18px` → `21px`（21 + 1×2 = 23），
      radius 4 → 6，`font-size: 12px` → `14px`。
      **代码与 QSS 必须同时改**：现状 `setFixedSize(18,18)` 被 QSS 的 `min-width:18px` + 边框顶成 20×20，
      两边打架，这次一次校准掉。
- [ ] `[action="add"]` / `[action="remove"]` 三档配色换成 §4 的表。
      状态规则只写 `border-color` / `background-color` / `color`，**不写 `border:` 简写**。
- [ ] 分组头的折叠箭头（`_LibrarySectionHeader._sync_arrow`，`widgets.py:1217`）
      现在用 `Qt.DownArrow` / `Qt.RightArrow` 原生三角，偏重。
      换成 `Icons.chevron_down(ULTRAVIEW_MUTED)`（`chrome.BoardIsland` 已在用同一枚），
      折叠态用已有的 chevron-right 变体；对应 HTML `.group-chevron` 的 `rotate(-90deg)`。
      若 `Icons` 无 chevron-right，加一枚，走 `tests/ui/test_ultraview_icons.py` 的既有契约。

### Task 6 —— 说明面与帮助页

- [ ] `/update-hints` 同步 `ui/hints.py`（`hints.py:766/773/780` 三条 View 库提示）与
      `ui/quickref.py`（`quickref.py:470-471`）。本包没有新增/删除交互，
      预期是措辞核对而非新增条目——**如果确实没有变化，就明确记一句"已核对无需改动"**，不要空跑。
- [ ] `mf4_analyzer/help/ultraview-guide.html:46` 的 View 库 mock（`展开 / 概览`）核对：
      两态说法不变，若 mock 里画了行内 ＋/− 的颜色，同步降饱和。
      版本号扇出面**不动**（本包不升版）。

---

## §6 测试契约

### 6.1 新增（先红后绿）

放在 `tests/ui/test_ultraview_page.py`：

| 测试 | 断言 | 抓的是 |
|---|---|---|
| `test_library_overlay_height_is_constant_across_content_changes` | 打开后记录 rect；依次「切概览 / 切回 / 折叠时域 / 展开 / 搜索 / 清空搜索」，每步后调 `page._apply_floating_layout()`，rect **逐字段相等** | R1 + R2（§1.1 整张表） |
| `test_library_section_frames_are_never_shorter_than_their_minimum` | 展开态下对每个 `section_widgets()` 断言 `frame.height() >= frame.minimumSizeHint().height()` | R3（时域 164 vs 215 的裁切） |
| `test_library_catalog_cards_keep_their_row_height` | 概览态下每张 `catalog_cards()` 的 `height() == LIBRARY_CATALOG_HEIGHT` | R4（80 vs 40 的气球化） |
| `test_library_catalog_height_survives_rebuild` | 概览态下连续 `set_rows()` 3 次，每次之后概览卡高仍 `== LIBRARY_CATALOG_HEIGHT` | Task 3 第二条：stretch 被 rebuild 清掉后没重加 |
| `test_library_mode_tabs_split_the_panel_width` | 两个 mode 按钮宽度相等，且各 ≥ 内容宽的 45% | Task 4 的分段控件 |
| `test_library_row_action_button_is_calm_and_square` | `_add` 渲染后 `width() == height() == LIBRARY_ROW_ACTION_SIZE`；`grab()` 取中心像素，断言饱和度低于阈值（HSV S < 0.35），加/移两态色相**可分**（色相差 > 40°） | Task 5 的配色 + 尺寸打架 |

> 最后一条特意断言"低饱和 + 色相可分"而不是硬编码色值：护栏要看住的是**调子**和**可分性**，
> 不是某个十六进制串。硬编码色值会让下一次微调变成改测试。

### 6.2 需要同步放宽/收紧的既有测试

- `tests/ui/test_ultraview_page.py:2828` `test_library_overlay_keeps_section_and_row_height`：
  当前断言 `row.height() >= 36`、header `22..40`。行高从 42 变 46 仍然通过，但**它太松了，
  正是它没抓住这次的裁切**。收紧成 `row.height() == LIBRARY_ROW_HEIGHT`、
  `header.height() == LIBRARY_SECTION_HEAD_HEIGHT`。
- `tests/ui/test_ultraview_page.py:2887` `test_library_section_headers_are_not_heavy_gray_slabs`：
  头区结构改动后取样点仍在分组头上，**预期不变**；跑一遍确认。
- `tests/ui/test_ultraview_page.py:433` `test_library_has_groups_and_overview_without_directory_or_section_bars`：
  信息架构不变，**预期不变**。
- `tests/ui_kit/test_qss_duplicate_selectors.py` / `test_qss_selector_liveness.py`：
  新增 `ultraViewLibraryHeadRule` / `ultraViewLibrarySectionRule` 两个 objectName，
  QSS 里给了规则就必须在代码里真的 `setObjectName`，否则 liveness 会红。

### 6.3 视觉验收自动化

文件：`tools/verify_ultraview_visuals.py`

- [ ] `REQUIRED_SHOTS`（`tools/verify_ultraview_visuals.py:27`）加
      `library_groups_1280`、`library_overview_1280` 两张。
- [ ] `_page_snapshot` 补一组 library 几何事实：面板 rect、每个分组 frame 的
      `(height, minimumSizeHint().height())`、行高集合、概览卡高集合、两个 mode 按钮的宽度。
- [ ] `assert_geometry`（`tools/verify_ultraview_visuals.py:609`）加对应断言：
      两张 shot 的**面板 rect 必须逐字段相等**（这就是"止跳"的机器化验收），
      分组 frame 高 ≥ minHint，概览卡高 == 40。

---

## §7 验证

### 7.1 复现现状（动手前先跑，与 §1 对账）

```bash
cd "/Users/donghang/Downloads/data analyzer"
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python docs/analyzer/verify/2026-08-15-ultraview-library-probes/probe_current.py
```

（探针脚本见 §7.4——本 plan 用过的四个探针要落进
`docs/analyzer/verify/2026-08-15-ultraview-library-probes/`，别让这些数字只活在聊天记录里。）

### 7.2 聚焦回归

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_chrome.py \
  tests/ui/test_ultraview_mode_integration.py \
  tests/ui/test_ultraview_icons.py \
  tests/ui/test_hints.py \
  tests/ui/test_quickref.py \
  tests/test_help_content.py \
  tests/ui_kit/test_qss_border_shorthand.py \
  tests/ui_kit/test_qss_duplicate_selectors.py \
  tests/ui_kit/test_qss_selector_liveness.py \
  tests/ui/test_no_lambda_signal_connections.py -q
```

### 7.3 全量（两条命令，别跑裸 `pytest -q`）

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest --ignore=tests/acquisition_ui -q
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/acquisition_ui -q
```

与 CLAUDE.md 的 2026-08-15 基线对账：主体 **6978 passed / 13 skipped / 9 failed**
（9 红全是既有顺序污染，清单在 `docs/analyzer/reviews/2026-08-15-post-v8-batch-review.md` §6），
`tests/acquisition_ui` **359 passed**。**新增红一条都不许算到"既有"头上。**

### 7.4 真机验收（Cocoa，不是 offscreen）

offscreen 只能证明结构与几何；材质、配色、字重的验收必须真机。

```bash
# 不带 QT_QPA_PLATFORM，走 Cocoa
TMPDIR=/tmp MPLCONFIGDIR=/tmp PYTHONPATH=. \
  .venv/bin/python tools/verify_ultraview_visuals.py --output /tmp/uv-after
```

- [ ] `library_groups_1280` / `library_overview_1280` 两张的**面板 rect 逐字段相等**（机器断言，§6.3）。
- [ ] 与本 plan 附带的改前基线（`/tmp/uv-before`，先在 `380e5ac2` 上跑一次）做并排对比图，
      连同两侧的几何事实 JSON 一起落进 `docs/analyzer/verify/2026-08-15-ultraview-library-probes/`。
- [ ] 尺寸档位：800×560（最窄）、1280×800、1600×1000 三档都要有 shot。

---

## §8 明确不做

- 不改 `floating_layout.py` 的锚点算法 —— 触发按钮垂直居中是有意保留的合同（§3.2）。
- 不改 View 库的信息架构：仍是「展开 / 概览」两态、五个 `SOURCE_SECTIONS`、无目录、无新建。
- 不动钉住语义（点画布不关、Esc 仍关），不把钉住换成 HTML 的关闭 ×。
- 不动 Board schema、预览计算、拖放协议、`ULTRAVIEW_REF_MIME`。
- 不把月白石蓝 token 铺到分析器其它页面，不动全局 `CONTROL_COLORS`。
- 不升版本号，不碰 CLAUDE.md 记的版本扇出面。
- 不给面板加动画过渡 —— 止跳靠"高度本来就不变"，不靠动画糊过去。

---

## §9 风险

| 风险 | 说明 | 处置 |
|---|---|---|
| root margins 归零后圆角被子控件盖掉 | CLAUDE.md 已记：Qt 不会把子控件挡在 `border-radius` 外，0-margin 会抹掉顶部圆角弧 | 头区自带 `(14,12,10,10)` 内缩，满宽分隔线只在**垂直方向**满宽、左右各留 1px 给边框；Cocoa 真机截图确认四角 |
| `totalMinimumSize()` 在控件未 polish 时偏小 | `showEvent` 里已调 `_sync_body_min_height`（`widgets.py:1586`），保留 | 新增测试在 `qtbot.waitExposed` 之后断言 |
| 定高 560 在超高窗口显得小 | 1600×1000 下面板只占安全带的 64% | 本次先定常量；若要改成随窗口按比例，是**一个常量换成一个 clamp 函数**的事，测试断言的是"内容变化下 rect 恒定"，不会挡这条演进 |
| 与在途两个 plan 撞 `style.qss` | 三包都动 QSS | §0 已列：本包只动 `style.qss:3869-4070`；执行前 `git status` 对账 |
| mono 字体在 Windows 上回退难看 | `_meta` 改等宽 | 照 `chrome.py:900-903` 的 `QFont.Monospace` + `setFixedPitch(True)` 写法（已在 Windows 打包里验过） |
