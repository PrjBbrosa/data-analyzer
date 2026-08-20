# UltraView Miro 二/三级菜单、Shapes、Rail 与 Draw 纠偏 Plan

日期：2026-08-21  
状态：**IMPLEMENTED / OFFSCREEN GREEN / COCOA LIVE MATRIX PENDING**  
基线：`codex/ultraview-authoring-tools` @ `c00d9f73175de630f2395e288424c1176658e718`  
性质：用户前台截图触发的修正计划。W1–W5 已落地；focused/boundary offscreen 242 passed。真实 Cocoa 连点矩阵本轮未重跑。

## 0. 结论先行

上一轮已经把四个入口从横向控件堆积改成了接近 Miro 的结构，但用户新提供的 7 张前台截图推翻了“可以进入最终视觉验收”的判断。当前不是继续微调几个 padding，而是要修复五个明确缺陷：

1. Selection toolbar 与二级 surface 在重复点击后不是幂等布局；
2. 字号等三级 picker 复用旧 geometry，第二次打开会塌成残缺白条；
3. Shapes 目录的图标、名称、快捷键没有形成紧凑三列；Triangle/Rhombus 的共享绘制路径未闭合；
4. ToolRail 内部出现不需要的实心白底；
5. Draw 混用了 Font Awesome 和临时手绘图标，Eraser/Lasso 不可识别，preset 也没有真正对齐 Miro 的圆形 chip。

因此，本轮验收状态从上一份 HTML 的 `CONDITIONAL GO` 下调为 **NEEDS REWORK**。第一优先级是稳定交互状态和修复真实几何错误，然后才是视觉精修。

## 1. 用户 7 张图对应的问题与代码证据

| 图 | 可见问题 | 当前代码证据 | 判定 |
|---|---|---|---|
| 1、2 | 同一 Text selection 的 toolbar 在重复操作后，字体/字号 cell、divider 和整体宽度发生变化；图 1 的 `Sans` 被切断，图 2 又恢复 | `SelectionToolbar.apply_capabilities()` 每次刷新都会 `_clear_body()` 并销毁/重建全部按钮；`button()` 又通过 `findChildren()` 搜索仍处于 `deleteLater()` 生命周期的对象；页面随后重新 `adjustSize()` 和定位 | 高风险根因，W0 先冻结确切点击序列 |
| 3、4 | 第一次字号 picker 是完整长列表，第二次只剩一个 48px 左右的白色圆角条，并覆盖文字 | 全部格式类型复用一个 `FormatChoiceFlyout`；`_clear_body()` 只调用 `deleteLater()`；`present_labels()` 仅修改 minimum width，没有重置旧显式 geometry/scroll 状态；`_popup_format_picker()` 对同 key 没有 toggle 合同 | 根因链完整，必须改为稳定 picker session |
| 5 | 图标与中文名称距离过大、名称像居中列；目录显得空；三角形和菱形缺一条闭合边，实际画布也缺 | `_CatalogRow` 用 QToolButton 原生文字布局，同时在 `paintEvent()` 手动画图标和快捷键，三者不是同一列系统；`shape_path()` 用 `QPainterPath.addPolygon()` 后没有 `closeSubpath()` | 缺边为已确认代码缺陷；目录为布局设计缺陷 |
| 6 | Rail 外壳内出现从上到下的实心白色矩形，破坏透明/磨砂画布感 | `#ultraViewToolRail` 与内部 group wrapper 没有一个明确的“外壳半透明、子层全透明”绘制合同；当前 QSS/子 QWidget 仍可能绘出实体 surface | 需要 rendered-pixel 与 Cocoa 双门，不能只改 token |
| 7 | Pen/Highlighter 勉强可猜，Eraser/Lasso 看起来像带缺口的圆或残缺角；三个 preset 是线段药丸，不是 Miro 图示 | Pen/Highlighter 来自 `qtawesome`，Eraser/Lasso 在 `_DrawSessionButton.paintEvent()` 临时画；工具按钮还有单独白底边框；preset 用横线表达宽度 | 未实现“同一家族、无需 tooltip 也可识别”的 UI 对标 |

当前 `156 passed` 只能证明已有合同全绿，不能证明上述前台问题不存在。现有测试只覆盖第一次打开、边界内定位、图标 ink bounds 和对象创建，没有覆盖“同一入口连续点击”“A picker → B picker → A picker”“共享 path 最后一条边”和 Rail 内部白底。

## 2. Miro 对标边界

视觉基准以用户已经提供的 Miro Shapes、Draw、Text 截图为准；行为语义用官方文档校验：

- [Miro Toolbars](https://help.miro.com/hc/en-us/articles/360017730553-Toolbars)：左侧 Creation toolbar；大部分创建工具是 one-shot，Pen/Eraser/Lasso 例外。
- [Miro simplified UI](https://help.miro.com/hc/en-us/articles/20967864443410-Miro-s-new-simplified-user-interface)：Shapes and Lines 合并；Freehand drawing 打开独立子菜单。
- [Miro Pen](https://help.miro.com/hc/en-us/articles/360017730573-Pen)：Pen、Highlighter、Eraser、Lasso 有清晰不同语义；Pen/Highlighter 最多三个 preset，preset 表达颜色和粗细。

本轮的“对标”含义：信息层级、图标语义、行列对齐、选中态和开关生命周期对齐；不扩展 Miro AI、Smart drawing、Precision eraser、Block arrow、Diagram 等未进入 TraceLab 产品边界的功能。

保留既定产品决定：

- release rail 不恢复 Select/鼠标按钮，内部 `V / Esc` 仍可回 Select；
- 顶左 Board 区不改；
- 不做 dark mode；
- 钛蓝琥珀是 TraceLab 品牌状态色，不把产品变成 Miro 的蓝白复制品。

## 3. 文件所有权与允许触点

| Owner | 允许修改 | 责任 |
|---|---|---|
| author chrome | `mf4_analyzer/ui/chart_stack/ultraview/author_chrome.py` | Toolbar、Format picker、Shapes catalog、Draw subrail |
| page overlay owner | `mf4_analyzer/ui/chart_stack/ultraview/page.py` | picker/flyout toggle、锚定、safe rect、toolbar settle |
| shared shape renderer | `mf4_analyzer/ui/chart_stack/ultraview/author_render.py` | Triangle/Rhombus 闭合路径；预览与实际绘制同源 |
| rail chrome | `mf4_analyzer/ui/chart_stack/ultraview/chrome.py` | Rail group wrapper 透明合同与稳定尺寸 |
| icon source | `mf4_analyzer/ui_kit/icons.py` | 四个 Draw 子工具的统一矢量图标 |
| visual tokens/QSS | `mf4_analyzer/ui_kit/style.qss`, `mf4_analyzer/ui_kit/ultraview_style.py` | Rail 透明材质、toolbar/picker 状态；禁止布局型副作用 |
| focused tests | 下列 W0/W1–W5 的 owner tests | 先红后绿，冻结重复点击和 rendered pixels |

不新增 MainWindow 状态，不改 Board persistence schema，不复制第二套 shape geometry，不把逻辑塞进 compatibility facade。

## W0 — 先冻结 7 张图的失败护栏

### Task 0.1：记录可重复事件序列

在 `tests/ui/test_ultraview_author_chrome.py` 与 `tests/ui/test_ultraview_selection_toolbar_contract.py` 增加以下序列，所有序列都记录：

- active overlay id；
- `_format_picker_key`；
- toolbar `QRect`、`sizeHint()`、visible control key 顺序；
- trigger `QRect`；
- picker `QRect`、`content_size()`、可见 choice 数；
- `QApplication.processEvents()` 前后状态。

矩阵：

1. `font_role`：open → close → open；
2. `font_size`：open → close → open；
3. `font_role` → `font_size` → `font_role`；
4. picker 打开时触发一次 selection refresh；
5. toolbar 位于对象上方、下方、左右 safe edge；
6. desktop `1182×768` 与 compact `800×560`。

失败标准：同一状态重新打开后 geometry 不同、choice 少于期望、toolbar control 消失/重排、picker 与选框/toolbar 重叠、关闭后残留白条，任一即红。

### Task 0.2：冻结 Shape 最后一条边

在 `tests/ui/test_ultraview_author_shape_slice.py` 增加：

- `shape_path("triangle")` 和 `shape_path("rhombus")` 的 subpath 必须闭合；
- 用无填充、固定 2px pen 渲染到透明 `QImage`，采样“最后一条边”的中点与两个邻域像素；
- 同一断言覆盖 catalog preview 和真实 author layer render；
- 100%、66%、150% zoom 下不得出现缺边。

### Task 0.3：冻结 Rail 与 Draw rendered evidence

- Rail：渲染整个 rail，不只渲染按钮；断言 group wrapper 不产生实体白矩形，圆角外像素透明，内部材质与 canvas/frost 合成而不是 `surface_solid`。
- Draw：分别渲染 Pen/Highlighter/Eraser/Lasso；断言无裁切、ink bounds 在共同 safe box 内、四个 alpha mask 不相同。
- preset：断言为圆形 chip、中心色点/粗细编码与 selected outer ring，而不是横线药丸。

### W0 出口

至少出现以下四类可解释红测：重复 picker、toolbar 幂等、shape closing edge、Rail/Draw rendered visual。未能稳定复现图 1/2 时不得直接猜 QSS 数值，必须先用前台录制补全点击序列。

## W1 — Selection toolbar 只在 schema 变化时重建

### Task 1.1：稳定按钮所有权

整改 `SelectionToolbar.apply_capabilities()`：

- 为 controls 建立稳定 signature：`kind + (key, group, wide, icon_role)`；
- signature 未变时原位更新 text/value/checked/enabled/mixed/icon，不销毁按钮；
- signature 真变化时才 rebuild；rebuild 前通知 page 关闭 format overlay；
- 用 `_buttons_by_key` 直接查当前按钮，删除 `findChildren()` 对 deferred-delete 子控件的依赖；
- divider 也随 group schema 稳定复用，不能在一次 refresh 后插入字体文字中间。

### Task 1.2：一次 settle、一次定位

`page.py::_refresh_author_toolbar()` 必须形成单一事务：

1. resolve capabilities；
2. update/rebuild controls；
3. activate layout；
4. 计算最终 `sizeHint()`；
5. 只调用一次 `setGeometry()`；
6. 最后 show/raise。

禁止 picker 开关反向触发 toolbar 宽度变化。相同 selection、viewport、compact 状态下，toolbar `QRect` 必须逐像素相等。

### W1 owner tests

- `tests/ui/test_ultraview_selection_toolbar_contract.py`
- `tests/ui/test_ultraview_author_chrome.py`
- `tests/ui/test_ultraview_board_hit_routing.py`

## W2 — Format picker 改成明确的 toggle/replace 状态机

### Task 2.1：定义开关语义

在现有 page owner 内完成，不创建跨模块状态簇：

- 当前无 format overlay + click A → 打开 A；
- 当前 A 已开 + click A → 关闭 A；
- 当前 A 已开 + click B → 原子替换为 B；
- selection/toolbar schema 改变 → 关闭 picker 并清空 key；
- Esc → 只关最上层 picker，selection toolbar 保留；
- canvas click → 关闭 picker，不移动 toolbar；
- 任何时刻只允许一个 author overlay active。

### Task 2.2：消除旧 geometry 污染

整改 `FormatChoiceFlyout`：

- 不在可见状态用 `deleteLater()` 内容参与下一次 `sizeHint()`；
- 采用稳定 content root/page，或先同步脱离旧 page、invalidate/activate 后再测量；
- 每次类型切换都重置 minimum/maximum/current size、scroll policy 和内容约束；
- natural size 由新内容 layout 决定，不能被 QScrollArea 上一次 viewport geometry 反向撑大；
- 测量完成后才由 page 根据 live trigger 计算 `_format_picker_rect()`。

### Task 2.3：紧凑尺寸合同

- Font picker：外宽 `152–168px`，单列，row `32–36px`；
- Text size picker：外宽 `104–120px`，单列，row `32px`；
- 9 个字号允许纵向列表，但不能继承 Font/Shape picker 的宽度；
- shape type picker 与主 Shapes catalog 共用可读三列 row，不复用旧大白板；
- picker 与 trigger gap `6px`；翻到上方时同样保持 `6px`；
- 关闭后 overlay geometry 可保留内部缓存，但任何像素都不可见、不可拦截 hit test。

### W2 owner tests

- `tests/ui/test_ultraview_author_chrome.py`
- `tests/ui/test_ultraview_selection_toolbar_contract.py`
- `tests/ui/test_ultraview_author_text_slice.py`
- `tests/ui/test_ultraview_sticky_slice.py`
- `tests/ui/test_ultraview_author_shape_slice.py`

## W3 — Shapes 目录紧凑化并修复闭合路径

### Task 3.1：把 row 做成真正三列

保留约 `224–240px` 的 Miro 式窄 panel，但重排内部信息：

```text
┌────────────────────────┐
│  icon  名称        key │  36–38px
│  icon  名称        key │
├────────────────────────┤
│  icon  名称        key │
└────────────────────────┘
```

- icon box：`20×20px`，左 inset `12px`；
- title 起点：`44–48px`，左对齐，禁止 native QToolButton 居中算法接管；
- shortcut：右 inset `12px`，弱化色；
- row：`36–38px`；hover/checked 填满整行；
- connector/shape 分组上下留白各 `6px`，divider `1px`；
- 不缩短成只剩图标，也不把名称放到中央形成空洞。

实现优先选一套绘制所有三列：要么完整 custom paint，要么 row widget/layout；禁止继续“native text + manual icon + manual shortcut”混搭。

### Task 3.2：闭合共享 path

在 `author_render.py::shape_path()` 中用明确的 `moveTo/lineTo/closeSubpath()` 构造 Triangle/Rhombus；不要依赖 `addPolygon()` 隐式闭合。该函数继续作为：

- Shapes catalog preview；
- selection toolbar shape glyph；
- author layer 实际绘制；
- export/compositor

的唯一几何来源。一次修复必须同时关闭预览和实际对象的缺边。

### W3 owner tests

- `tests/ui/test_ultraview_author_shape_slice.py`
- `tests/ui/test_ultraview_author_chrome.py`
- `tests/ui/test_ultraview_author_export.py`

## W4 — 取消 Rail 白底，保留钛蓝琥珀状态

### Task 4.1：分离外壳与内部 group

- `#ultraViewToolRail` 只绘制一层半透明 frost + outline；
- nav/create/status group、divider wrapper 全部 `autoFillBackground=False` 且显式 transparent；
- 删除能产生 `surface_solid` 内矩形的继承路径；
- Rail 背后的 canvas 点阵/渐变应能轻微透出；
- active author tool 仍是唯一钛蓝→琥珀渐变 owner；inactive/disabled 按钮无白色 backing。

QSS 必须使用分开的 `border-width/style/color`，不得用破坏圆角的 border shorthand。

### Task 4.2：像素与前台门

- offscreen 只证明透明层级与圆角像素；
- Cocoa 截图必须证明整条 rail 没有图 6 的白色长方形；
- desktop/compact、active/inactive、badge 显示/隐藏各拍一张自动对比图。

### W4 owner/boundary tests

- `tests/ui/test_ultraview_author_chrome.py`
- `tests/ui/test_ultraview_chrome.py`
- `tests/ui_kit/test_ultraview_style.py`
- `tests/ui_kit/test_qss_border_shorthand.py`

## W5 — Draw 四图标和 preset 全面按 Miro 语义重画

### Task 5.1：统一 icon source

在 `mf4_analyzer/ui_kit/icons.py` 增加同一家族的四个矢量 icon，`DrawPopover` 不再混用 Font Awesome 与临时 `paintEvent()`：

- Pen：明确笔尖/自由曲线；
- Highlighter：宽头 marker + 短笔迹；
- Eraser：倾斜橡皮主体，带分隔带；
- Lasso：虚线闭环 + 起点/选择提示。

共同合同：`20–22px` ink box、`1.8–2px` stroke、round cap/join、四边至少 `3px` safe inset，无裁切。选中态只用 Miro 式淡蓝 cell，不给未选中工具增加白色圆框。

### Task 5.2：preset 改成圆形 chip

- 三个 preset 纵向排列；
- 外圈为中性圆形 hit target；
- 中心色点同时编码颜色和宽度，直径由 width clamp 后映射；
- selected preset 使用蓝色 outer ring；
- double-click editor 行为如果本轮实现，必须有打开/保存/切 tool 前台门；若不实现，不得画出暗示可编辑但无行为的 affordance。

### Task 5.3：语义验收

在不显示 tooltip 的截图中，四个工具必须能由用户独立辨认为 Pen/Highlighter/Eraser/Lasso。自动测试只能防裁切和漂移，不能替代这项视觉判断。

### W5 owner tests

- `tests/ui/test_ultraview_author_chrome.py`
- `tests/ui/test_ultraview_author_draw_slice.py`
- `tests/ui_kit/test_ultraview_style.py`

## W6 — 集成与真实前台验收

### Task 6.1：focused gate

不重跑无关全套基线。产品变更稳定后运行：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_author_chrome.py \
  tests/ui/test_ultraview_selection_toolbar_contract.py \
  tests/ui/test_ultraview_board_hit_routing.py \
  tests/ui/test_ultraview_author_integration.py \
  tests/ui/test_ultraview_sticky_slice.py \
  tests/ui/test_ultraview_author_text_slice.py \
  tests/ui/test_ultraview_author_shape_slice.py \
  tests/ui/test_ultraview_author_draw_slice.py \
  tests/ui/test_ultraview_author_export.py \
  tests/ui_kit/test_ultraview_style.py \
  tests/ui_kit/test_qss_border_shorthand.py \
  tests/ui/test_no_lambda_signal_connections.py -q
```

全量 suite 只在合并/发布验收或出现跨目录 teardown/顺序污染时由单一协调者运行；不得与另一全量 pytest 重叠。

### Task 6.2：Cocoa 操作矩阵

使用最终稳定提交启动：

```bash
PYTHONPATH=. .venv/bin/python -m mf4_analyzer.app
```

逐项真实鼠标执行，不能用 AX toggle 代替 Qt click：

1. 选 Text → Font 连点三次；
2. Size 连点三次；
3. Font → Size → Font；
4. picker 打开时重新选同一对象；
5. Text 位于上、下、左、右边缘；
6. `1182×768` 与 `800×560`；
7. 打开 Shapes，检查 icon/title/shortcut 紧凑列；
8. 创建 Triangle/Rhombus，在 66%、100%、150% 检查四/三条边；
9. Rail active/inactive、badge 最坏组合检查无白底；
10. 打开 Draw，不看 tooltip 识别四图标，逐个切换并检查三个圆形 preset。

每一步保存 before/open/second-click/after 四帧；自动比较 toolbar/picker bounding box，避免让用户逐张肉眼寻找位移。

### Task 6.3：文档同步

若可见交互或名称变化，必须同步：

- `mf4_analyzer/ui/hints.py`
- `mf4_analyzer/ui/quickref.py`
- `docs/analyzer/reviews/2026-08-20-ultraview-miro-post-grok-comparison.html`

最终 HTML 应把本轮 7 项从 `NEEDS REWORK` 更新为真实 evidence 状态，而不是先写 `GO` 再等用户找问题。

## 4. Definition of Done

以下条件必须同时满足：

- 同一 selection 下 toolbar 连续操作前后 `QRect` 和 control 顺序稳定；
- 同一 picker 第一次与第三次打开 geometry 相同，第二次关闭无残留白条；
- A → B → A 不继承旧宽高，picker 始终锚定当前 live trigger；
- Shapes 名称紧贴图标左对齐，快捷键独立右对齐，panel 无中央空洞；
- Triangle/Rhombus 的 preview、实际 board、export 都闭合；
- Rail 无实心白色长条，canvas/frost 层级可见，钛蓝琥珀 active 保留；
- Pen/Highlighter/Eraser/Lasso 无 tooltip 也能识别，图标无裁切；
- 三个 Draw preset 为 Miro 式圆形 chip，并正确表达颜色/粗细/选中态；
- focused/boundary tests 全绿；
- desktop + compact Cocoa 矩阵全绿；
- 最终 HTML 与运行软件一致。

未完成真实 Cocoa 重复点击矩阵、闭合边像素检查和 Draw 无提示识别时，不得宣布本轮完成。

