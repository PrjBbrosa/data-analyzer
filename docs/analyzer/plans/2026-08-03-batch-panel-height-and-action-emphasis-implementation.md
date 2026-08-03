# 批处理面板 —— 高度收敛与动作按钮强调（实施计划）

日期：2026-08-03 · 版本基线：TraceLab v7.9.1 · 目标文件：`mf4_analyzer/ui/drawers/batch/`

## 1. 问题（用户反馈，逐条）

1. **批处理面板默认高度超出笔记本屏幕**，底部 footer 的「运行 / 预览 / 关闭」被裁掉，
   完全不可点。
2. **顶部两行 chrome（工具条 50px + 管线条 62px = 112px）信息价值低、占高过多**。
3. **「运行」「预览」以及预览弹窗内的按钮全部是同一张扁平白底面孔**，没有主次，
   不醒目，也和全局 `role="primary"` 体系脱节。

## 2. 现状测量（offscreen 实测，非推断）

```
dialog minSizeHint   : QSize(452, 166)        # 面板本身能缩到很小
_toolbar_host  h=50   strip h=62   _footer_host h=54     # 固定 chrome = 166
_input_panel   minHint h=465
_analysis_panel minHint h=526   ← 三栏里最高
_output_panel  minHint h=433
```

结论：`minimumSizeHint` 只有 166px，**面板并没有被内容撑高**——第 1 条纯粹是
`sheet.py:136` 的 `self.resize(1080, 760)` 写死、且从不与屏幕可用区域取交集造成的。
1366×768 笔记本上可用高度 ≈ 768 − 48（任务栏）= 720，客户区再减去 ~31px 标题栏
≈ 689 < 760，于是底部被切。预览弹窗 `preview_dialog.py:23` 的 `resize(1040, 720)`
有**完全相同的缺陷**，一并修。

收敛后的目标：chrome 从 166px → 94px；在 689px 客户区下内容区 = 595px，
**最高的分析栏（526px）第一次能不出竖向滚动条完整显示**。

## 3. 改动清单

### 改动 A — 初始尺寸与屏幕可用区取交集（对应问题 1）

复用仓库已有的成熟范式 `mf4_analyzer/ui/db_reference_dialog.py:361`
`_fit_to_available_screen(parent, target_w, target_h)`，**不要另造轮子**。

`mf4_analyzer/ui/drawers/batch/sheet.py`

- 删除 `self.resize(1080, 760)`（第 136 行），改为在 `__init__` **末尾**（所有子面板
  构造完成后）调用新增的私有方法 `self._fit_to_available_screen(parent, 1080, 760)`。
- 新方法实现要点（照抄 `db_reference_dialog` 的取屏逻辑）：
  - 取屏优先级：`QApplication.screenAt(parent.geometry().center())` →
    `QApplication.instance().primaryScreen()` → `None`；`screenAt` 用 `try/except`
    包住（父窗口尚未映射时会抛）。
  - `max_w = min(1080, avail.width()  - 48)`
  - `max_h = min(760,  avail.height() - 72)` — 72 要同时吃掉 Windows 标题栏
    （~31px）+ 边框 + 阴影，`resize()` 设的是**客户区**尺寸。
  - 若有父窗口且 `parent.width() > 0`：`max_w = min(max_w, parent.width() - 24)`
    （「模态不宽于宿主窗口」，与 db_reference 一致）。
  - 下限：`max_w = max(640, max_w)`，`max_h = max(480, max_h)`。
  - **只调用 `self.resize(...)`，绝对不要 `setMaximumHeight/setMaximumSize`** ——
    现有测试（`tests/ui/test_batch_smoke.py:908` 等）会显式 `resize(1080, 760)`，
    加最大尺寸会把它们打红，也会剥夺用户手动放大的自由。
- 追加 `showEvent` 兜底（照抄 `ui/drawers/channel_editor_drawer.py:46-60` 的 clamp）：
  `super().showEvent(event)` 之后，把 `frameGeometry()` 夹回 `availableGeometry()`，
  防止 Qt 把窗口摆到父窗口位置后仍然下沿出屏。

`mf4_analyzer/ui/drawers/batch/preview_dialog.py`

- 同样把 `self.resize(1040, 720)` 换成同一套夹取（目标 1040×720，下限 640×420）。
  为避免两份实现，把夹取逻辑提到一个模块级函数，例如在
  `mf4_analyzer/ui/drawers/batch/_geometry.py` 新建
  `fit_dialog_to_available_screen(dialog, parent, target_w, target_h, *, min_w, min_h)`，
  两个类都调它；`sheet.py` 里的 `_fit_to_available_screen` 只是一层薄转发。

### 改动 B — 顶部保持两行，各自收紧（对应问题 2）

> **2026-08-03 修订**：初稿把两行合并成一行 44px（删掉与窗口标题栏重复的
> `QLabel("批处理分析")`，把 `PipelineStrip` 塞进工具条）。已按真机截图评审推翻——
> 用户要的是「**还是两行，只是不要浪费太多高度**」。合并还有一个实打实的副作用：
> 管线条 29/39/32 的分栏权重原本与下方三栏严格对齐，右侧被三个方案按钮占掉 ~275px
> 后这份对齐就没了。**两行结构保留**，只压高度。

两行承载的是两类东西——工具条是方案 I/O（导入/导出/从单次同步），管线条是流水线状态
——不该混排。收紧手段是各自去掉多余留白：

| 行 | 现在 | 改为 |
| --- | --- | --- |
| `_toolbar_host` | 50 | **36** |
| `strip` | 62 | **40** |
| `_footer_host` | 54 | **50** |
| 合计 chrome | 166 | **126**（省 40px） |

36px 的工具条只有配合 QSS 缩短按钮才站得住（见改动 C-2 的第二条）：全局
`QPushButton` 的最小高度是 26 + padding 8 + border 2 = **36**，直接放进 36px 的行会
撑爆布局。方案按钮属于次级 chrome，用 `QWidget#BatchCompactToolbar QPushButton`
把它压到 `min-height:24; padding:2px 10px` → 最小高度 30，配 3px 上下边距正好 36。

`mf4_analyzer/ui/drawers/batch/pipeline_strip.py`

| 项 | 现在 | 改为 |
| --- | --- | --- |
| `PipelineCard.setFixedHeight` | 62 | **40** |
| `PipelineCard` 卡片背景 | `#ffffff` | **不变**（初稿改成 `transparent` 是为了融进工具条；两行结构下管线条仍是独立一行，保持白底） |
| 卡片 layout margins | `(18, 9, 18, 9)` | **`(12, 0, 12, 0)`** |
| 卡片 layout spacing | 8 | **7** |
| `number_label` 尺寸 | `(24, 24)` | **`(20, 18)`** |
| `number_label` 圆角 / 字号 | `7px` / `10px` | **`5px` / `9px`** |
| `title_label` 字号 | 12px/800 | **11px/800**（颜色不变） |
| `summary_label` 字号 | 11px | **11px 不变**（这是唯一的事实文本，别再缩） |
| `PipelineStrip.setFixedHeight` | 62 | **40** |

**公有 API 一个字都不许动**：`strip.cards`、`set_stage(index, status, text)`、
`card.number_label / title_label / summary_label / badge_label / stage_status`
被 `sheet._recompute_pipeline_status` 和 4 个测试文件依赖。

`mf4_analyzer/ui/drawers/batch/sheet.py`（第 198-226 行区块）

- `_toolbar_host.setFixedHeight(50)` → **`36`**。
- `bar.setContentsMargins(14, 8, 14, 8)` → **`(14, 3, 14, 3)`**；`bar.setSpacing(7)` 保持。
- `self._toolbar_title`（「批处理分析」）、`bar.addStretch(1)`、三个方案按钮的顺序与
  文案**全部保持原样**；`QLabel#BatchToolbarTitle` 的 QSS 只把 13px 调成 **12px**。
- `self.strip = PipelineStrip(self)` + `root.addWidget(self.strip)` 保持独立一行，
  与下方三栏的列对齐因此完整保留。

`_footer_host`（第 298-303 行）

- `setFixedHeight(54)` → **`50`**。
- margins `(18, 8, 14, 8)` → **`(16, 5, 14, 5)`**；`_apply_compact_mode` 里的
  `(12, 8, 14, 8)` → **`(12, 5, 14, 5)`**。

  > **实施期修正（2026-08-03，实测）**：本节初稿写的是上下 7px，算错了 Qt 的 CSS 盒
  > 模型——改动 C-2 给动作按钮设的 `min-height: 30px` 之上还要加 `padding 4+4` 与
  > `border 1+1`，按钮真实 `minimumSizeHint().height()` 是 **40**，`7+40+7 = 54 > 50`，
  > footer 布局最小高度溢出宿主，Qt 把按钮顶到上沿，视觉上留下 7px/3px 的偏心。
  > 改成 5px 后 `5+40+5 = 50` 正好贴合（实测 `_footer_lay.minimumSize().height() == 50`，
  > 紧凑/非紧凑两种模式都是）。

合计 chrome：`36 + 40 + 50 = 126`（原 166），省出 40px。689px 客户区下内容区
= 563px ≥ 分析栏最小高度 524px，最高的一栏依旧能不出竖向滚动条完整显示。

### 改动 C — 动作按钮的全局一致强调（对应问题 3）

全局体系里已有 `QPushButton[role="primary"]`（#1769e0 实心蓝，17 处在用）和
`role="destructive"`（红字红框）。批处理是**唯一没接进这套体系**的地方——所以这条
既是「更醒目」，也是「全局一致」。缺的只有一档「次强调」，补上即可。

**C-1 `mf4_analyzer/ui_kit/style.qss`：紧跟 `role="primary"` 区块（第 618 行后）新增
`role="accent"`**（描边蓝，配色直接取文件头部已声明的 accent #1769e0 / accent-wash
#e8efff，不引入新色）：

```qss
QPushButton[role="accent"],
QToolButton[role="accent"] {
    background-color: #ffffff;
    border-color: #1769e0;
    color: #1769e0;
}
QPushButton[role="accent"]:hover,
QToolButton[role="accent"]:hover {
    background-color: #e8efff;
    border-color: #135abd;
    color: #0f3f8f;
}
QPushButton[role="accent"]:pressed,
QToolButton[role="accent"]:pressed { background-color: #d8e6fb; }
QPushButton[role="accent"]:disabled,
QToolButton[role="accent"]:disabled {
    color: #94a3b8;
    background-color: #f5f7fb;
    border-color: #eef2f7;
}
```

> **不要改** 既有的 `role="primary"` / `role="destructive"` 任何一条声明（含 `:disabled`）
> ——它们有 17 + 5 个调用点，这次改动无权波及。

**C-2 同文件，`QWidget#BatchCompactFooter` 区块（第 475 行）附近新增尺寸强调**，
让两处动作区的按钮比普通按钮更有分量：

```qss
QWidget#BatchCompactFooter QPushButton,
QDialog#BatchPreviewDialog QPushButton {
    min-height: 30px;
    min-width: 76px;
    padding: 4px 14px;
    font-weight: 700;
}
```

同一区块再加一条**反向**规则，服务改动 B 的 36px 工具条——方案按钮是次级 chrome，
比 footer 的动作按钮矮一档，正好把主次拉开：

```qss
QWidget#BatchCompactToolbar QPushButton {
    min-height: 24px;
    padding: 2px 10px;
}
```

**C-3 角色落位**（`role` 在构造时 `setProperty` 一次即可，之后 enable/visible 切换走
Qt 伪状态，**不需要** unpolish/polish）：

`sheet.py` footer：

| 按钮 | role | 观感 |
| --- | --- | --- |
| `_btn_run`「运行」 | **`primary`** | 实心蓝，全场唯一主动作 |
| `_btn_preview`「预览」 | **`accent`** | 蓝描边，次强调 |
| `_btn_cancel`「关闭」 | 不设（中性） | 保持白底 |
| `_btn_abort`「中断」 | **`destructive`** | 红描边，运行中出现 |

`preview_dialog.py`（先 `self.setObjectName("BatchPreviewDialog")`，C-2 的选择器依赖它）：

| 按钮 | role |
| --- | --- |
| `_btn_run_all`「运行全部」 | **`primary`** |
| `_btn_regenerate`「重新生成」 | **`accent`** |
| `_btn_back`「返回修改」 | 不设（中性） |
| `_btn_cancel`「取消生成」 | **`destructive`** |

按钮顺序两处都保持现状（中性 … 次强调、主动作在最右），本来就是一致的，别动。

## 4. 需要同步修改的既有测试（不改会红）

| 文件:行 | 现断言 | 改为 |
| --- | --- | --- |
| `tests/ui/test_batch_compact_contract.py:187` | `_toolbar_host.height() == 50` | `== 36` |
| `tests/ui/test_batch_compact_contract.py:188` | `strip.height() == 62` | `== 40` |
| `tests/ui/test_batch_compact_contract.py:189` | `_footer_host.height() == 54` | `== 50` |
| `tests/ui/test_batch_compact_contract.py:209-210` | `strip.min/maximumHeight() == 62` | `== 40` |
| `tests/ui/test_batch_smoke.py:917` | `_footer_host.height() == 54` | `== 50` |

`test_batch_shell_matches_html_fixed_rows_and_contiguous_columns`（同文件第 174 行）
里三栏 29/39/32 宽度比断言**针对的是下方 detail 栏，不受本次影响**，保持原样。

## 5. 新增测试（写进 `tests/ui/test_batch_compact_contract.py`）

1. `test_batch_sheet_initial_size_fits_available_screen`
   —— 不显式 resize，构造后断言
   `sheet.height() <= avail.height() - 40` 且 `sheet.width() <= avail.width() - 24`
   （offscreen 默认屏 800×600，正好是天然的「小屏」试验台）。
2. `test_batch_preview_dialog_fits_available_screen` —— 同上，针对 `BatchPreviewDialog`。
3. `test_batch_footer_actions_stay_inside_a_short_dialog`
   —— 加载 production QSS，`sheet.resize(1080, 620)`、`show()`，断言
   `_btn_run` 映射到 sheet 坐标后 `y + height() <= sheet.height()`，且
   `_btn_run.isVisible()`。这是问题 1 的行为级验收。
4. `test_batch_action_buttons_use_global_button_roles`
   —— 断言 8 个按钮的 `property("role")` 与 C-3 表一致（中性两个断言为 `None`）。
5. `test_accent_role_is_declared_in_global_qss`
   —— 读 `mf4_analyzer/ui_kit/style.qss`，断言存在 `[role="accent"]` 且带 `#1769e0`。
6. `test_batch_header_keeps_two_rows_but_tightened`
   —— 断言 `sheet.strip.parent() is sheet`（**不是** `_toolbar_host`，两行不合并）、
   `_toolbar_title.text() == "批处理分析"`、三行 chrome 合计 `== 126`。
7. `test_batch_toolbar_row_fits_its_preset_buttons`
   —— 加载 production QSS，断言工具条布局最小高度 `<=` 宿主 36px，且三个方案按钮
   上下各留 3px（36px 行只有配合 C-2 的按钮压缩规则才站得住，这条守住那个耦合）。

## 6. 验证

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/ui/test_batch_compact_contract.py tests/ui/test_batch_smoke.py tests/ui/test_batch_toolbar.py tests/ui/test_batch_method_buttons.py tests/ui/test_batch_input_panel.py -q
```

- **先取基线**：`main` 上 `tests/ui/` 已有一批 `test_split_*` 是红的
  （`canvas_time.get_visible_xlim()` 返回 `None`），动手前先记下失败数，别把既有失败
  算到本次改动头上。
- offscreen 只是排版草稿。**视觉验收必须跑真机**：按 CLAUDE.md 的 Gotchas，
  用原生 `windows` 平台（不设 `QT_QPA_PLATFORM`）构造 `BatchSheet` /
  `BatchPreviewDialog`、`show()` 后 `grab()` 截图，确认
  (a) 底部「运行」完整可见，(b) 顶部两行都收紧且按钮不被压扁，(c) 运行=实心蓝 /
  预览=蓝描边 / 中断=红描边，(d) 预览弹窗四个按钮同样分级。

### 6.1 真机验收结果（2026-08-03，本机 1366×768）

原生平台实测，非 offscreen 推断：

```
real available geometry : QRect(0, 0, 1366, 720)     # 768 − 48 任务栏
sheet initial size      : QSize(1080, 648)           # 客户区，已夹取
sheet frame geometry    : QRect(142, 5, 1082, 680)   # 下沿 685 < 720 ✓
preview initial size    : QSize(1040, 648)           # 同样已夹取 ✓
chrome toolbar/strip/footer : 36 / 40 / 50 = 126     # 原 166 ✓
toolbar 布局最小高度      : 36（按钮 y=3 h=30，上下各 3px）✓
footer  布局最小高度      : 50（按钮 y=5 h=40，上下各 5px）✓
```

截图确认：顶部仍是两行——工具条（批处理分析 + 三个方案按钮）36px，管线条
（01/02/03）40px 独立一行、与下方三栏列对齐完好；footer 四态按钮层级正确——
关闭=中性白、预览=蓝描边、运行=实心蓝、中断=红描边；预览弹窗返回修改=中性、
重新生成=蓝描边、运行全部=实心蓝、取消生成=红描边，与主面板一致。

## 7. 明确不做（防止范围蔓延）

- 不记忆/持久化窗口尺寸（`BatchPanelPrefs` 的边界是「导出长什么样」，不是窗口几何）。
- 不改三栏 29/39/32 权重、不改 `_apply_compact_mode` 的 1180px 阈值。
- 不改 `role="primary"` / `role="destructive"` 既有声明，不动其它对话框。
- 不改任何按钮文案、顺序、信号连接与运行逻辑。
