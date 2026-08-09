# 全局操作控件视觉系统实施计划

日期：2026-08-09

状态：**P0 已于 2026-08-09 本地落地；退出条件待完成**。共享角色、三档高度
轨道、选中签名、SearchField、二选一分段、PillSwitch、MessageBox 和离屏证据均已
实现并通过两进程全量回归。仍未满足的退出条件：运行期可见按钮高度审计为 11 种
（目标 ≤4），以及 macOS 前景 / Windows 冻结包验收；P1 checkbox 未获批准，未实施。

对应规格：`docs/analyzer/specs/2026-08-09-global-control-visual-system-spec.md`

审计基线：`main@e782adcf` 加 2026-08-09 当前在途工作区；执行者必须以开始实施时的
checkout 重新核对符号与 dirty diff

修订：2026-08-09 第二稿，跟随 spec 第二稿。第一稿的 Task 0–6 全部保留，
新增 Task 1.5（高度轨道）、Task 2.5（统一选中签名）、Task 3.5（SearchField）、
Task 3.6（二选一控件），并改写 §1 §2 与验证顺序。改写理由见 spec §2.2–§2.5 的实测。

## 1. 实施结论

按两个阶段执行：

- **P0（本计划可执行范围）**：建立共享控件角色/色阶/**高度档**、精修通用按钮、
  **统一选中签名**、迁移旧角色、**收敛搜索框与二选一控件**、精修既有 `PillSwitch`，
  完成 Analyzer 与 Cockpit 双入口验证；
- **P1（证据门控，不自动执行）**：只有 P0 contact sheet 和 macOS 前景检查显示 checkbox
  与新控件体系明显失配，并经用户确认后，才精修 checkbox。

不调整页面布局（margin / spacing / 面板宽度 / 列宽 / 字号）、不改顶部与 Batch 模式
选择器的结构，也不重做菜单、标签页和图表内部控件。**控件自身高度按 spec §6.1 收敛，
这是本轮与第一稿最大的差别。** 每一步先写失败测试/确定性 probe，再改唯一所有者。

### 1.1 任务顺序与依赖

```
Task 0   基线 + 冻结影响面（含四个 audit 脚本的 before 快照）
  ├─ Task 1    control_style.py：角色 + 色阶 + 高度档 token
  │    ├─ Task 1.5  高度轨道落地（含逐条判定局部覆盖）   ← 收益最大
  │    ├─ Task 2    按钮 QSS 合同与兼容层
  │    │    └─ Task 2.5  统一选中签名（七族 + 修 2px 抖动）
  │    ├─ Task 3    逐点迁移旧角色
  │    ├─ Task 3.5  SearchField（八处）
  │    ├─ Task 3.6  二选一 → SegmentedChoice
  │    └─ Task 3.7  FFT 幅值单位归位到坐标轴设置（信息架构）
  ├─ Task 4    PillSwitch 精修
  ├─ Task 5    MessageBox 色阶对齐
  └─ Task 6    页面级窄修复 + 自动化对比
```

Task 1.5 / 2.5 / 3.5 / 3.6 之间没有依赖，可以按任意顺序做，但都必须在 Task 1 之后
（要 token）、Task 6 之前（要一起进对比）。若要分批交付，**先做 Task 1 + 1.5 + 2.5**：
这两条覆盖用户实际看到的绝大部分失配，且不触碰任何持久化格式。

### 1.2 一条硬性排序约束：icon 角色不能滞后

**Task 3 的 `role="icon"` 拆分必须和 Task 1.5 / Task 2 同一批落地，不能排在后面。**

原型渲染实测到的失效模式：通用规则把按钮 padding 提到 `4px 14px` 之后，一个
仅图标的 `QToolButton` 的 sizeHint 宽度多出 8 px；在宽度受限的行里（288 px Inspector
的 `dB 参考` 行，编辑框 stretch=1、按钮 stretch=0），Qt 会把按钮压到 sizeHint 以下，
**16 px 的 `mdi.tune-vertical` 图标被裁成一条竖线**——不报错、不告警，只是图标没了。

这与 `style.qss:749-752` 已有的注释是同一个坑（"even setFixedSize is inflated by
Qt's CSS sizing math"），只是方向相反。两条附带教训：

1. 图标控件必须在同一次改动里拿到 square compact 几何（`min-width == min-height`、
   小 padding），不能等后续任务；
2. `#dbReferenceManageButton` 是 **`QToolButton`**，选择器写成
   `QPushButton#dbReferenceManageButton` 不会命中。全仓所有 objectName 选择器
   在改 padding 前都要核对宿主类型。

因此 Task 6 的验收里必须包含一项**图标完整性**检查：对每个 icon-only 控件断言
`width() >= sizeHint().width()`，而不是只看按钮盒子还在。

## 2. 成功标准

1. 通用动作只使用 `primary / secondary / quiet / icon / danger / choice` 六种标准角色；
2. 旧 `accent/create/destructive/tool` 的所有现有 call site 完成明确迁移，`tool` 不再混用
   文本与图标几何；
3. `CONTROL_COLORS` / `CONTROL_HEIGHTS` 是唯一色值与高度来源，QSS token 由它们派生，
   `PillSwitch` 直接复用；
4. **`audit_controls.py` 重跑后 `QPushButton` 高度种类从 12 降到 ≤ 4，
   `role="primary"` 全应用单一高度；`audit_border_jitter.py` 零命中；
   `audit_search.py` 八处全部 32 px + 清除键 + 放大镜 + 统一文案；
   spec §9.2 表中「→ 分段」项全部完成且 1 项下拉消除**；
5. **布局** spacing、面板宽度、列宽、字号、行数不变（行高按 §6.1 变化是预期结果）；
6. 顶部模式区结构、combo/input 选择器与圆角族、MessageBox 合同无回归；
   Batch 方法区从「不等高」修为「等高」；
7. **二选一迁移不改变任何持久化格式与信号契约**：现有 preset / project IO /
   batch recipe 测试一行不改仍然通过；
8. Analyzer 和 Cockpit 的 shared stylesheet 路径均通过自动化和 macOS 前景验收；
9. 当前在途工作区不被 reset/覆盖，最终 patch 只包含批准范围。

## 3. 实施前保护

### Task 0 — 重建基线并冻结影响面

**Read/record**

- `git status --short`、`git diff --name-only`、当前 branch/HEAD；
- `mf4_analyzer/ui_kit/style.qss` 当前 diff，尤其顶部、Batch、FRF 和 combo 的在途改动；
- `mf4_analyzer/ui/widgets/pill_switch.py`；
- 所有 `setProperty("role", ...)` call site；
- Analyzer 与 acquisition/Cockpit 的 stylesheet 加载入口。

**Actions**

1. 不 reset、不 checkout、不格式化无关文件；
2. 用 `rg` 重跑控件与角色审计，把结果写入 `.state/global-control-refinement/`；
   **并重跑四个运行期 audit 脚本存下 before 快照**——它们既是 spec §2.2–§2.5 的
   数据来源，也是 §16 退出条件的判据，必须有 before 才能证明 after：

   ```bash
   cd "$REPO" && for s in audit_controls audit_search audit_border_jitter; do
     TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
       .venv/bin/python .state/global-control-refinement/$s.py \
       > .state/global-control-refinement/before-$s.txt 2>&1
   done
   ```
3. 运行现有相关测试，记录 pre-change baseline；若已有红测，单独列为 baseline，不把它
   误判为本轮回归；
4. 用当前 QSS 生成 before contact sheet，隔离 QSettings，并记录控件 geometry、sizeHint、
   文本 bounding rect 和关键像素；
5. 在真实 macOS 前景保存 Analyzer/Cockpit baseline 截图；若无法启动，标为
   `UNVERIFIED`，不能以 offscreen 替代。

**现有基线测试**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui_kit/test_combo_corner_radius.py \
  tests/ui/test_toolbar.py \
  tests/ui/test_batch_method_buttons.py \
  tests/ui/test_inspector.py \
  tests/ui/test_batch_compact_contract.py \
  tests/ui/test_batch_output_panel.py \
  tests/ui/test_message_box_buttons.py \
  tests/acquisition_ui/test_visual_stylesheet_contract.py \
  tests/acquisition_ui/test_toolbar_overflow_priority.py
```

## 4. P0 实施任务

### Task 1 — 先锁定共享角色、token 与 import 边界

**Add**

- `mf4_analyzer/ui_kit/control_style.py`
- `tests/ui_kit/test_control_style.py`

**Modify**

- `mf4_analyzer/ui_kit/__init__.py`（仅在现有 public export 约定需要时）
- `mf4_analyzer/ui_kit/stylesheet.py`
- `tests/ui/test_import_boundaries.py`

**RED tests**

1. 六种标准角色常量稳定且无重复；未知角色被显式拒绝；
2. `set_control_role()` 设置 Qt property，并在动态变更后触发安全 repolish；
3. `CONTROL_COLORS` 完整包含 spec §6 色阶且值为合法六位 hex；
   `CONTROL_QSS_TOKENS` 由其派生并保持一一对应，不复制色值；
4. stylesheet loader 合并 control token 和当前 icon token，最终 QSS 不残留
   `{{CONTROL_*}}`；
5. `import mf4_analyzer.ui_kit.control_style` 不加载 `mf4_analyzer.ui`、MainWindow、Batch
   drawer 或 acquisition UI；
6. 现有 `render_qss_template()` 公共调用和 icon cache 行为不变。

**GREEN implementation**

- `control_style.py` 只依赖 Qt 基础类型/typing；不 import 高层 UI；
- token 采用 uppercase key，QSS 用 `{{CONTROL_ACCENT}}` 等占位符；
- `stylesheet.py` 在调用既有模板替换器前合并 token map，不改变该替换器签名；
- helper 只负责语义 property 与 repolish，不设置尺寸、文本、图标或业务状态。

**Exit**

- 新测试通过；
- import subprocess probe 通过；
- 当前 QSS 渲染仍可加载，combo/icon placeholders 仍全部解析。

补充：Task 1 的 `control_style.py` 除 `CONTROL_COLORS` 外还要提供 `CONTROL_HEIGHTS`
（spec §6.1 三档）以及由二者共同派生的 `CONTROL_QSS_TOKENS`，并让
`set_control_role(widget, role, *, size=None)` 能同时写 `role` 与 `controlSize`
两个 Qt property。RED 测试相应增加：三档常量唯一且为正整数、未知档位被拒绝、
`min-height + padding + border` 的换算 helper 与 QSS 中的字面量一致。

### Task 1.5 — 高度轨道落地（收益最大的一步）

**Modify**

- `mf4_analyzer/ui_kit/style.qss`
- spec §2.2 列出的每一条更高特异性高度覆盖所在的 selector

**Add**

- `tests/ui_kit/test_control_height_scale.py`

**RED tests**

1. 用与 `audit_controls.py` 相同的实例化集合，断言可见 `QPushButton` 的不同
   `sizeHint().height()` 数量 ≤ 4；
2. 断言全应用 `role="primary"` 只有一个高度值；
3. 断言 `QLineEdit` / `QComboBox` / `QSpinBox` / `QDoubleSpinBox` 在同一表单行内
   高度相等；
4. 例外白名单是**显式列表**且只许缩小（与状态所有权棘轮同一范式）：每一项要有
   `objectName`/selector + 理由字符串；
5. QSS 中不存在对可变文字控件使用 `max-height` 的规则（静态扫描）。

**GREEN implementation**

逐条判定 spec §6.1 末尾列出的覆盖，每条只有三种结果，**不允许「先不动」**：

| selector | 判定 | 动作 |
| --- | --- | --- |
| `Inspector QPushButton[role="primary"]` (30) | 归 `cta` | 删局部值，引 token |
| `QWidget#BatchCompactFooter QPushButton` (30) | 归 `cta` 或 `base` | 同上 |
| `QWidget#BatchCompactToolbar QPushButton` (24) | 归 `compact` | 同上 |
| `QLineEdit#channelConfigManagerSearch` (28) | 由 Task 3.5 接管 | 删 |
| `QPushButton#channelConfigManagerCreate` (28) | 归 `base` | 引 token |
| `Toolbar QPushButton` (22) | 例外或 `compact` | 判定后记录 |
| `QPushButton[role="preset-load"]` (34) | 判定 | 记录 |
| `QToolButton#inspectorCollapser` (37) | 例外（是 section header 不是按钮） | 记录理由 |
| `channel_config_manager.CONTROL_HEIGHT = 36` | 归 `base` | 改常量并复核该对话框 |
| `channel_config_bar.CONTROL_HEIGHT = 32` | 已在轨道 | 改引 token |

**Exit**

- `after-audit_controls.txt` 的按钮高度种类 ≤ 4，且 diff 里能逐行对上；
- 288 px Inspector 与 1080×760 窄窗口下无文字裁切；
- 既有 `tests/ui/test_inspector.py::…button_width`、Batch compact contract、
  Cockpit stylesheet contract 全绿。

### Task 2 — 建立按钮 QSS 合同与兼容层

**Modify**

- `mf4_analyzer/ui_kit/style.qss`
- `tests/ui_kit/test_control_style.py`
- 新增 `tests/ui_kit/test_control_button_render.py`

**RED tests/probes**

1. `QPushButton/QToolButton` 的六种标准角色都覆盖必需状态；
2. default/hover/pressed/disabled/checked 的 geometry 与 sizeHint 不变；
3. `primary > secondary > quiet/icon` 的边界/表面对比顺序可由关键像素证明；
4. danger 在 hover/pressed 后仍保持红色语义；
5. 文本型 quiet 在 Inspector 约 288 px 环境下完整显示；
6. icon 角色不强制覆盖调用方 24/28 px 固定几何；
7. 旧 `accent/destructive/create` 在迁移期呈现兼容外观；
8. 顶部/Batch/FRF/图表专用 role 的关键像素和 geometry 不被通用 selector 命中。

**GREEN implementation**

- 把现有通用 button block 改为 token 化状态规则；
- 按 spec §5 修订后的方向：`primary` **保持实心蓝填充** + 轻微纵向渐变 + 深一档边界，
  `secondary` 用白底/蓝字/浅蓝边的**描边式强调**，`quiet/icon` 静止态全透明、
  hover 才出 chrome，`danger` 白底红字红边、hover 才填淡红；
- 所有状态保持 1 px border（含静止态用 `transparent` 占位），不改 padding/radius；
  高度统一由 Task 1.5 的 token 决定；
- 加 `accent → secondary`、`destructive → danger` 兼容选择器；`create` 暂时兼容
  secondary；
- 不为 `tool` 增加新的统一 alias，避免继续固化混合语义；
- 不动 input/combo 的选择器结构与圆角族、顶部 mode zone 结构。
  Batch method group / chart choice / segment selectors 的**选中态**由 Task 2.5 接管，
  本任务不要重复改。

**追加 RED**：把 §5 修订那条做成测试——灰阶下
`primary < secondary < 默认 < quiet` 的表面亮度严格单调（数值断言，不是目测）。
这正是第一稿「三块浅蓝」方案会红的地方。

**Exit**

- 确定性 gallery 中所有状态可辨识；
- 灰阶单调断言通过；
- geometry/baseline assertions 通过；
- 已有 combo corner、toolbar、Batch method tests 仍绿。

### Task 2.5 — 统一选中签名

**Modify**

- `mf4_analyzer/ui_kit/style.qss`（七族选中态收敛到 spec §7.3）

**Add**

- `tests/ui_kit/test_selection_signature.py`

**RED tests/probes**

1. `choice` / `frf-segment` / `chart-choice` / `tick-density-preset` / `slice-seg` /
   `cockpitMode` / `batchMethod` 七族，在真实 QSS 下渲染选中态，
   **取样药丸中心与边框像素**，断言七组三元组（底色 / 边色 / 字色）两两相等；
2. 断言未选态在七族里同样一致（透明底 + `CONTROL_TEXT_MUTED`）；
3. `sizeHint(checked) == sizeHint(unchecked)`，逐族；
4. `audit_border_jitter.py` 零命中；
5. 顶部 Toolbar mode zone 的蓝色竖向标记仍在（negative test：这一族**不**收敛）。

**GREEN implementation**

- 七族共用同一段 token 化的选中规则；各族只保留自己的 `min-height` / 字号 / padding；
- `QWidget#BatchMethodGroup QPushButton[batchMethod]` 静止态由 `border: none` 改为
  `border: 1px solid transparent`，`:checked` 只换边色——**这是修 34/36 抖动的全部改动**；
- `QPushButton#BatchGroupingCard` 同法处理（静止 1 px → 保持，`:checked` 2 px → 1 px
  加深色）；
- 三个非规范强调蓝（`#2563eb` / `#0b7af3` / `#1d4ed8`）在操作控件语境归零。

**Exit**

- 七族像素三元组一致；
- 切换 Batch 分析方法时整排高度不跳（运行期断言 + 前景确认）；
- `tests/ui/test_batch_method_buttons.py`、`tests/ui/test_toolbar.py`、
  `tests/acquisition_ui/test_visual_stylesheet_contract.py` 全绿。

### Task 3 — 逐点迁移旧角色

先按内容和几何分类，再改 property；不得用一次全仓字符串替换。

#### 3.1 旧 `tool` 分类

**预期迁移为 `icon`**

- `ui/file_navigator.py`：关闭、更多菜单；`btn_auto_attach` 以实际是否仅图标复核；
- `ui/widgets/stats.py`：折叠/展开；
- `ui/inspector_sections/contextual_fft.py`：重建图标按钮；
- `ui/inspector_sections/contextual_fft_time.py`：重建图标按钮；
- `ui/inspector_sections/contextual_order.py`：重建图标按钮。

**预期迁移为 `quiet`**

- `ui/widgets/channel_tree.py`：全选、全不、已选、编辑通道；
- `ui/drawers/rebuild_time_popover.py`：取消；
- `ui/drawers/batch/frf_pair_editor.py`：添加输出；删除输出若表达删除语义则用 `danger`，
  若只是移出未保存列表则用 `quiet` 并保留明确图标/tooltip；
- `ui/widgets/channel_config_manager.py:btn_batch`：按实际文本与尺寸确认 quiet/icon。

#### 3.2 其他旧角色

**Modify**

- `ui/drawers/batch/sheet.py`：`accent → secondary`，`destructive → danger`；
- `ui/drawers/batch/preview_dialog.py`：同上；
- `ui/widgets/channel_config_manager.py`：删除类 `destructive → danger`；
- `ui/dialogs/channel_editor.py`：`create → secondary`，删除类保持 `danger`；若某个 create
  是该 action cluster 的唯一提交动作，依据实际层级改为 `primary`；
- `ui/db_reference_dialog.py`：沿用 canonical `danger`；
- `ui/inspector_sections/contextual_frf.py`：现有 `secondary` 直接获得共享合同。

**Tests**

- 新增静态审计：标准业务 call site 中不残留 `accent/destructive/create`；
- `tool` 只允许在明确列出的兼容 fixture/历史文本中出现，产品 call site 归零；
- 对每个受影响页面检查 object geometry、text bounding rect、tooltip/accessibility；
- 更新 owner-level 现有测试，不建立依赖行号或全仓构造数量的脆弱断言。

**Exit**

- `rg` 结果与迁移表一一对应；
- 兼容 aliases 可暂留一个版本窗口，但没有产品 call site 依赖它们；
- 所有中文操作文字在窄窗口完整显示。

### Task 3.5 — 共享 `SearchField`

**Add**

- `mf4_analyzer/ui_kit/widgets/search_field.py`
- `tests/ui_kit/test_search_field.py`

**Modify**（spec §2.4 的八处，逐个替换构造，不动过滤逻辑）

- `ui/widgets/channel_tree.py:445`
- `ui/file_navigator.py`（同一 `MultiFileChannelWidget` 复用点，核对是否同一构造）
- `ui/quickref_panel.py:478`
- `ui/drawers/batch/signal_picker.py:325`（`setFixedHeight(32)` 一并删除）
- `ui/widgets/channel_config_manager.py:254,389`（`CONTROL_HEIGHT` 由 Task 1.5 处理）
- `acquisition_ui/widgets/left_pane.py:166`
- `acquisition_ui/history_tab.py:494`

**RED tests**

1. `SearchField` 高度恒为 `CONTROL_H_BASE`，有 leading 放大镜 action，
   `isClearButtonEnabled()` 为真；
2. 放大镜走 `ui_kit/icons.py` 缓存，不在每次构造时重新栅格化；
3. 静态审计：产品代码里不再出现「裸 `QLineEdit` + 含『搜索/Filter』的
   `setPlaceholderText`」组合；
4. 八处占位文案匹配 `^搜索.+…$`；
5. 各调用点原有的过滤/防抖/信号行为不变（复用各自现有 owner 测试，不改断言）。

**GREEN implementation**

- `SearchField(QLineEdit)`，构造参数只有 `placeholder` 与 `parent`；
- Cockpit 两处需要提示可搜 ID 的，把 `name / 0x40A` 放进 tooltip，占位文字统一；
- 不重排任何面板布局——摆放位置维持现状（spec §9.1 明确不为统一而重排）。

**Exit**

- `after-audit_search.txt` 八行全部 `32 / 有清除键 / 有放大镜 / 文案合规`；
- 各调用点 owner 测试未修改断言仍绿。

### Task 3.6 — 二选一控件改分段

**Add**

- `mf4_analyzer/ui_kit/widgets/segmented_choice.py`
- `tests/ui_kit/test_segmented_choice.py`

**Modify**（严格按 spec §9.2 的表，逐项确认，不做批量替换）

- `ui/inspector_sections/contextual_fft.py`（幅值、计权）
- `ui/inspector_sections/contextual_fft_time.py`（计权、幅值）
- `ui/inspector_sections/contextual_order.py`（转速来源、计权、幅值）
- `ui/inspector_sections/contextual_frf.py`（幅值、NFFT 模式、估计器；
  频率轴/相位已是分段，改为复用共享组件）
- `ui/inspector_sections/persistent_top.py`（X 轴来源）
- `ui/inspector_sections/_helpers.py`（`combo_amp_unit`）
- `ui/drawers/batch/output_panel.py`（幅值；**`_combo_image_format` 单项下拉改静态文本**）
- `ui/drawers/batch/analysis_panel.py`（Auto/Fixed、计权、区间）
- `ui/drawers/batch/slice_panel.py`（切片轴）
- `ui/drawers/batch/input_panel.py`（目标策略——先量宽度再决定）

**RED tests**

0. **字段槽宽度（spec §9.2.1，最先写）**：对每个被替换的行，断言
   `SegmentedChoice` 的 `mapTo(panel, ...)` 左右边缘与替换前的 `QComboBox`
   **逐像素相同**，高度同为 `CONTROL_H_BASE`。Inspector 表单那一列共享右边缘是
   用户选定的 A1 布局，收缩成短药丸会打散它——这条红了就停，不要继续；
1. `SegmentedChoice.bind(combo)` 后：点 segment → combo `currentIndex` 跟随；
   `combo.setCurrentIndex()` → segment 选中态跟随；两侧 signal 各只发一次，不回环；
2. 隐藏 combo 保持 `isVisible() == False` 但 `currentData()` 可读可写；
3. **持久化契约不变**：现有 preset / project IO / batch recipe 测试**一行不改**仍通过
   （这是本任务能不能做的判据，红了就停）；
4. 每个 segment 继承原 combo item 的 tooltip；
5. 全应用不存在可见的 `count() == 1` 的 `QComboBox`；
6. 288 px Inspector 下所有分段标签完整显示，未缩小字号；
7. `input_panel` 目标策略：若量出放不下，测试改为断言它**仍是 combo** 并记录理由。

**GREEN implementation**

- 组件化 `contextual_frf.py:_make_choice_row`，容器用 Task 2.5 的统一签名；
- 长标签缩短显示 + tooltip 存全文（`H1（输出噪声）` → `H1`）；
- 原 combo 一律 `hide()` 保留，**不删**——删掉就会动到持久化与测试面。

**Exit**

- spec §9.2 表逐行有结论（迁移 / 保留 + 理由）；
- 持久化与信号契约测试零改动通过；
- FRF 面板内部五个二选一形态一致。

### Task 3.7 — 把 Inspector FFT 的幅值单位归位到坐标轴设置

依据 spec §9.3。这是**信息架构**修正，不是视觉改动，但和 Task 3.6 改到同一批行，
放在一起做省一次回归。

**Modify**

- `mf4_analyzer/ui/inspector_sections/_helpers.py`
- `mf4_analyzer/ui/inspector_sections/contextual_fft.py`

**Add/Modify tests**

- `tests/ui/test_inspector.py`（或就近的 owner 测试）

**RED tests**

1. **持久化零影响（先写这条，红了就停）**：`combo_amp_y` 仍是同一个对象、
   仍是 `['Linear','dB']` 顺序、默认仍是 `Linear`；`collect/apply` 与预设键
   `amp_y` 行为逐字节不变。现有 preset / project IO 测试**一行不改**仍通过；
2. `幅值轴` 行不再出现在 `谱参数` QGroupBox 内；
3. `幅值单位` 行出现在 `坐标轴设置` QGroupBox 内，且在 `include_z=False` 下也成立；
4. 面板总行数不变；总高按**实测差值**断言而不是「不变」——原型量到
   748 → 740 px（两组内边距不同，搬迁必然差 8 px）。写死期望值，
   偏离即回归；
5. Batch `OutputPanel` 的 `amplitude_unit_row_label="幅值单位:"` 现有行为不回归
   （它是这条路径的既有用户）；
6. 时频 / 阶次的色阶行内联单位不受影响。

**GREEN implementation**

1. `_make_axis_settings_group()`：把幅值单位辅助行的构造**移出 `if include_z:`**，
   使其只依赖 `amplitude_unit_row_label is not None`；
2. 增加可选参数让调用方传入**已有 widget**（例如 `amplitude_unit_widget=None`，
   缺省时才回退到 helper 自建的 `combo_amp_unit`）。
   `include_z=True` 且未传 widget 时，保持现有 `z_unit_widget = None` 的互斥逻辑不变；
3. `contextual_fft.py`：从 `fl.addRow("幅值轴:", ...)` 移除该行，改在
   `_make_axis_settings_group(...)` 调用里传
   `amplitude_unit_row_label="幅值单位:", amplitude_unit_widget=self.combo_amp_y`；
4. **不要**把 `combo_amp_y` 换成 `combo_amp_unit`——见 spec §9.3 的硬约束；
5. 若 Task 3.6 也在做（幅值改分段），两者叠加后该行是「坐标轴设置里的
   `幅值单位: [Linear│dB]` 分段」，宽度仍走 §9.2.1 的字段槽合同。

**Exit**

- 上述 RED 全绿，且 preset / project IO 测试零改动；
- 前后对比图显示 `谱参数` 少一行、`坐标轴设置` 多一行、面板总高不变；
- 在 `contextual_frf.py` 的 `combo_magnitude_scale` 处补一行注释，记录
  「FRF 无坐标轴设置组，显示与可信度即其显示口径区，判定为可接受」，
  防止后续 review 反复提这条。

### Task 4 — 精修共享 `PillSwitch`

**Modify**

- `mf4_analyzer/ui/widgets/pill_switch.py`

**Add/Modify tests**

- 新增 `tests/ui/test_pill_switch.py`
- 覆盖包含 `PillSwitch` 的现有 owner tests（按当前真实使用点选择）

**RED tests/probes**

1. off/on/hover/pressed/disabled 五种状态均能确定性渲染；
2. 控件始终 44 × 24，状态切换不改 sizeHint/geometry；
3. knob 在左右状态的中心位置符合当前合同，DPR 1/2 不偏心；
4. on 轨道使用共享 accent token，off/disabled 有可辨识边界；
5. checked、clicked、toggled、keyboard toggle 行为与 pre-change baseline 一致；
6. painter 不启动 timer，不访问 QSettings，不产生父对象/Qt teardown 泄漏。

**GREEN implementation**

- painter 从 `ui_kit.control_style.CONTROL_COLORS` 读取共享颜色；
- 使用轻微线性渐变、1 px 轨道边界和极小 knob 下沿/高光；
- 保持当前 rect、knob diameter、左右 inset 和 interaction code；
- hover/pressed 只调颜色，不改位置；disabled 同时处理轨道、边界、knob。

**Exit**

- DPR 1/2 contact sheet 和像素 assertions 通过；
- 七处现有实例化无需布局 patch；若某处需要改布局，停止并回查 painter/测试假设。

### Task 5 — MessageBox 色阶对齐但保持独立合同

**Modify only if comparison proves drift**

- `mf4_analyzer/ui_kit/message_box_buttons.py`
- `mf4_analyzer/ui_kit/style.qss`
- `tests/ui/test_message_box_buttons.py`

**Rules**

- 保留 `messageBoxRole` 命名空间和 primary/warning/danger/neutral 语义；
- 只把 primary/danger 的颜色引用对齐共享 token；warning 保留黄/橙语义；
- 不用通用 `set_control_role()` 替代现有 message-box helper；
- 保留 `fit_message_box_buttons_to_text()` 及“QSS min-width 是内容宽、padding 另计”的合同。

**RED/Exit**

- 长中文按钮在应用完整 QSS 后，文本 bounding rect 加 padding 不超过真实按钮 content rect；
- 默认/危险按钮角色正确，geometry 与 baseline 一致；
- 如果现有 MessageBox 已与新体系协调，则本任务只记录无需源码修改的证据。

### Task 6 — 页面级窄修复与自动化对比

只处理共享样式落地后由真实 geometry/pixel 证据暴露的局部问题，禁止凭感觉扩大范围。

**验证矩阵**

| 区域 | 必查内容 | 允许的修复 |
| --- | --- | --- |
| Toolbar | mode zone、两侧分隔、面板开关、新建按钮 | 仅 selector specificity/意外继承 |
| Inspector | 288 px 宽、primary 30 px、FRF secondary | 局部覆盖顺序，不改面板宽度 |
| Channel tree | 全选/全不/已选/编辑通道 | quiet padding/文字 fit，不缩字体 |
| Batch sheet | 预览/运行/终止、底部操作区 | 角色和状态，不改 footer 高度 |
| Batch preview | 重新生成/运行全部/取消 | 角色和文字 fit |
| Channel dialogs | 创建/保存/删除/批量 | 局部几何例外有证据才保留 |
| Chart toolbar | chart-choice/tick presets | 不被通用 selector 命中 |
| Cockpit | 主工具条、overflow、密集窗口 | 仅修共享 QSS 回归 |

**Automation**

1. 以相同应用字体、DPR、窗口尺寸和 fixture 生成 before/after contact sheet；
2. 用控件 objectName/geometry 对齐裁图，而不是人工逐张找位置；
3. 自动报告 geometry、baseline、文字裁切、关键像素和视觉变更区域；
4. 专用模式区使用“应保持”像素/geometry gate，通用控件使用“应发生受控变化”gate；
5. 所有证据存 `.state/global-control-refinement/evidence/`，不默认加入 Git。

**Exit**

- 没有意外布局变化；
- 受控视觉变化集中在标准按钮和 switch；
- 局部 override 数量有清单和理由，未复制整段通用样式。

## 5. P1 门控任务：Checkbox 精修

本节不随 P0 自动执行。

### Gate

用户审阅 P0 contact sheet 与 macOS 前景界面后，明确确认 checkbox 仍需精修。

### Task 7 — Checkbox 状态细节

**Modify**

- `mf4_analyzer/ui_kit/style.qss`
- `mf4_analyzer/ui_kit/icons.py`（只有现有缓存 glyph 无法满足时；优先不改）
- 新增/扩展 `tests/ui_kit/test_checkbox_render.py`

**RED/implementation**

- 锁定 16 × 16、DPR 1/2、off/hover/checked/disabled/partial 状态；
- 圆角精修到 5 px、静止边界更安静、hover 有极浅蓝 wash；
- 继续使用缓存 check glyph，不用运行时文本字符；
- 不把 checkbox 的业务调用批量替换为 `PillSwitch`。

**Exit**

- 表单密集区没有因为边界变重而产生噪声；
- geometry、label spacing、keyboard behavior 无变化；
- Analyzer/Cockpit contact sheet 与前景复核再次完成。

## 6. 验证顺序

### 6.1 Focused tests

先运行新增 contract/render tests，再运行受影响 owner tests：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui_kit/test_control_style.py \
  tests/ui_kit/test_control_height_scale.py \
  tests/ui_kit/test_control_button_render.py \
  tests/ui_kit/test_selection_signature.py \
  tests/ui_kit/test_search_field.py \
  tests/ui_kit/test_segmented_choice.py \
  tests/ui/test_pill_switch.py \
  tests/ui_kit/test_combo_corner_radius.py \
  tests/ui/test_toolbar.py \
  tests/ui/test_batch_method_buttons.py \
  tests/ui/test_inspector.py \
  tests/ui/test_batch_compact_contract.py \
  tests/ui/test_batch_output_panel.py \
  tests/ui/test_message_box_buttons.py \
  tests/acquisition_ui/test_visual_stylesheet_contract.py \
  tests/acquisition_ui/test_toolbar_overflow_priority.py
```

如果 P1 未获批准，`tests/ui_kit/test_checkbox_render.py` 不应在 P0 patch 中新增。

### 6.2 Architecture/boundary gates

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_import_boundaries.py \
  tests/test_native_import_boundaries.py \
  tests/test_packaging_imports.py
```

若实际改动触及其他 owner，追加其既有边界 gate；不得因为本计划列出最小清单就跳过
真实依赖影响。

### 6.3 全量回归 gate

全局 QSS 同时覆盖两个入口，P0 完成前按仓库约定用两个新进程运行：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest --ignore=tests/acquisition_ui

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/acquisition_ui
```

任何 crash、timeout、中断或异常退出均为 `UNVERIFIED`，不能按已完成的用例数量推断通过。

最后运行：

```bash
git diff --check
/usr/bin/python3 scripts/lessons/check.py --status
```

若测试保护了一个此前未记录、未来容易复发的 Qt/QSS 失败模式，再按 lessons 流程判断是否
新增短 lesson；视觉偏好本身不自动生成 lesson。

## 7. 真实前景验收

offscreen 通过后，在 macOS Cocoa 前景执行：

1. Analyzer 1440 × 900：顶部、文件导航、Inspector、图表工具条；
2. Analyzer 1080 × 760：窄窗口、Inspector 约 288 px、中文按钮不裁切；
3. Batch：方法选择区、sheet footer、preview dialog、FRF pair editor；
4. Channel Editor、Config Manager、dB reference dialog、至少一个长中文 QMessageBox；
5. 七个 `PillSwitch` 使用点中至少覆盖正常表单、密集表单和 disabled 情形；
6. Cockpit 常规宽度与触发 overflow 的窄宽度；
7. 逐状态操作 primary/secondary/quiet/icon/danger，确认 hover/pressed 不跳动；
8. 与 before 截图自动对齐，报告控件几何不变和视觉变更集中区。

前景验收结果分开记录为：Analyzer、Batch、Cockpit。任一入口未启动或无法观察，就标记
该入口 `UNVERIFIED`，不以其他入口替代。

## 8. 回退与风险控制

| 风险 | 预防/回退 |
| --- | --- |
| 全局 selector 误伤专用按钮 | 专用角色 negative tests；先兼容再迁移；回退单个 selector |
| 文本型 `tool` 被 icon 尺寸压缩 | 先逐点分类；文字 bounding rect 与 288 px Inspector probe |
| 顶部/Batch 模式区失去定制外观 | 保留专用 namespace，增加 should-not-change render gate |
| Cockpit 因共享 QSS 回归 | acquisition tests + foreground overflow matrix |
| token 替换破坏 icon placeholders | 合并 map，不改 renderer 签名；检查所有模板占位符 |
| switch painter 在高 DPR 模糊/偏心 | DPR 1/2 像素与中心点 probe；不改 geometry |
| 角色抽象过度、局部例外反增 | 页面只声明语义；仅有 geometry 证据时保留窄 override |
| dirty worktree 覆盖前序工作 | 开始/结束均核对 diff；只用窄 patch，不 reset/checkout |

如果共享 QSS 无法在不改变某专用控件 geometry 的情况下兼容，优先缩小通用 selector，
而不是改专用控件布局来迎合新样式。

## 9. 完成与交付清单

- [ ] P0 六种标准角色、共享色阶/高度 token 与 helper 完成；
- [ ] 高度轨道落地：`audit_controls.py` 按钮高度种类 ≤ 4，`primary` 单一高度，
      例外白名单有清单和理由；
- [ ] 统一选中签名覆盖七族，`audit_border_jitter.py` 零命中，
      Batch 方法区切换不再跳 2 px；
- [ ] 八处搜索框统一为 `SearchField`，`audit_search.py` 全绿；
- [ ] 二选一控件按 spec §9.2 表逐行有结论，单项下拉消除，
      持久化/信号契约测试零改动通过；
- [ ] 分段控件占满同一个 260px 字段槽（spec §9.2.1），Inspector 字段列
      左右边缘逐行不变；
- [ ] FFT 幅值单位归位到坐标轴设置（spec §9.3），`combo_amp_y` 对象与
      `amp_y` 预设键未变，面板总高等于实测期望值（748 → 740）；
- [ ] 每个 icon-only 控件 `width() >= sizeHint().width()`（plan §1.2 的裁图坑）；
- [ ] 旧角色逐个迁移，`tool` 文本/图标混用归零；
- [ ] `PillSwitch` 精修且 44 × 24/交互合同不变；
- [ ] P0 before/after 自动 contact sheet 与几何报告完成；
- [ ] Analyzer、Batch、Cockpit 前景结果分别记录；
- [ ] focused、boundary、两进程全量回归与 `git diff --check` 完成；
- [ ] 未获批准时没有 Checkbox P1、输入/Combo、布局或版本改动；
- [ ] 工作区无无关改动、无自动 commit/push；
- [ ] 若存在未验证平台，明确列为 `UNVERIFIED`。

本计划完成不自动意味着 P1 获批，也不自动授权 commit、push、merge 或发布。
