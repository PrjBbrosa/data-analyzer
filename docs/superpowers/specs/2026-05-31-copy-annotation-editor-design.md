# 复制后标注编辑器 + 裁剪 设计（类 Snipaste 轻量版）

日期：2026-05-31
分支：`plan/pyqtgraph-timedomain-migration`
目标文件（建议新增 + 改动）：
- 新增模块 `mf4_analyzer/ui/markup/`（`editor.py` 标注编辑器、`thumbnail.py` 悬浮缩略图）
- 改动 `mf4_analyzer/ui/main_window.py`（发布管道、缩略图 owner、打开编辑器、toast 文案）
- 改动 `mf4_analyzer/ui/chart_stack.py`（`_copy_card_image` 把图交给发布管道）
- 改动 `mf4_analyzer/ui/style.qss`（缩略图 / 编辑器样式，沿用圆角/阴影语言）

## 背景

用户要在「把图复制到剪贴板」之后,提供一个轻量标注流程(类 Snipaste:**裁剪** + 箭头/框/线/笔/文字/序号),
并且有一条**硬约束**:

> 复制完一定要明确提示「图片已被复制」,让用户不会以为非点右下角缩略图不可。

这把整个交互模型钉死成 **复制=已完成态、标注/裁剪=可选加料** —— 两者必须解耦。

### 现状核实（决定方案落点）

现存全局复制**图片**入口共 6 个,但**本轮用户入口只认 4 个图卡 toolbar「复制为图片」按钮**;另外 2 个是
FFT-vs-Time 检查器专用复制按钮,明确维持现状、范围外。代码出口仍是 2 个(其余 `clipboard()` 调用都是 `setText`
复制文字,在采集 Cockpit 侧,与本功能无关)。

1. **出口 1 = 图卡 toolbar 复制(本轮目标 4 个用户入口)** `ChartStack._copy_card_image(card)`(`chart_stack.py:1378`):用画布无关的
   `_grab_pixmap_hidpi(canvas)`(`:35`,pyqtgraph 走 `grab_pixmap(scale=)`、matplotlib fallback `QWidget.grab()`)
   抓图 → 时域卡再把 CursorPill 合成上去 → `QApplication.clipboard().setPixmap(pix)`(`:1422`)
   → `image_copied.emit("已复制图为图片")`(`:1423`,文案有错别字)。
   **此出口服务全部 4 张图卡的工具栏「复制为图片」按钮**(`_copy_btn` `:836-842`,信号 `copy_image_requested`;
   4 卡统一接线 `:1293-1295`:时域 / FFT / FFT-vs-Time / 阶次)。导出规格:`_HIDPI_EXPORT_SCALE=2.0`、`_HIDPI_MAX_WIDTH=2560`。

2. **出口 2 = FFT-vs-Time 检查器复制(范围外 2 个用户入口)** `MainWindow._copy_fft_time_image(mode)`(`main_window.py:2051`):
   `grab_main_chart()`/`grab_full_view()`(`canvases.py:2053-2115`,主谱图裁剪 vs 全视图)→ `setPixmap`(`:2073`)。
   触发自检查器两个按钮(`main_window.py:298,301`)。**此出口不在本轮范围**(见「锁定决策」)。

3. **可复用的悬浮件:** `Toast`(`widgets/__init__.py:317`)有现成 `QGraphicsOpacityEffect`+`QPropertyAnimation`(180ms 淡入)
   + `QTimer` 自动隐 + 「同时只一个」模型;但它 `WA_TransparentForMouseEvents=True`(点击穿透),**不能直接当缩略图**
   (缩略图要接点击),只能借其动画/定位范式。`Toast._reposition`(`:400`)的右下/底部 margin 算法可参考。
   `image_copied` 现连到 statusBar + `self.toast(...)`(`main_window.py:242`);`MainWindow.toast(msg,level)`(`:184`)。

## 锁定决策

| 决策 | 内容 | 理由 |
|---|---|---|
| **范围 = 出口 1 的 4 个图卡复制按钮** | 标注/缩略图只接 `_copy_card_image`(时域/FFT/FFT-time/阶次 工具栏「复制为图片」);**出口 2(FFT-time 检查器 2 按钮)维持现状,不接** | 用户拍板「覆盖顶部 toolbar 的 4 个就行」;避免本轮动 FFT-time 的专用裁剪路径 |
| 复制与标注解耦 | 点复制 → **立刻**写纯图入剪贴板 + **必弹 toast**;缩略图是纯可选二级入口 | 满足硬约束:任何时刻剪贴板都有可粘贴的图,用户永不被「卡在半路」 |
| toast 主、缩略图副 | toast 文案改 **"已复制到剪贴板 · 可直接粘贴"**(顺手修错别字);缩略图带副标题「点击标注/裁剪」+ 倒计时 | 信息层级:toast=你已搞定(必读),缩略图=想加工再点(可无视) |
| 缩略图 3 秒自动淡出 | 默认 3000ms;**鼠标悬停暂停倒计时**;`✕` 立即关;点击 → 开编辑器 | 用户拍板;悬停暂停防误触 |
| 编辑器独立非模态窗口 | 独立 `QWidget`(`Qt.Window`),与主窗口零耦合,不抢主布局 | 用户拍板;可边看 app 边标注 |
| 矢量图层模型 | `QGraphicsScene`:背景 `QGraphicsPixmapItem` + 各标注为独立 `QGraphicsItem`;完成时才拍平 | 支持选中/拖动/重编辑/撤销重做;不在位图上「刷」 |
| **裁剪 = 重定背景边界(可撤销)** | 「裁剪」工具拖框 + 8 手柄调整 + 框外压暗,应用后**背景重定为 `pixmap.copy(cropRect)`**、画布缩到裁剪区、已有标注随之平移,入 `QUndoStack` | 用户要裁剪;重定边界后导出逻辑(按背景设备像素渲染)天然产出裁剪图,无需单独导出分支;可撤销恢复全图 |
| v1 工具集 | 选择 / **裁剪** / 箭头 / 直线 / 矩形 / 画笔 / 文字 / **序号①②③**;颜色(6 预设)+ 粗细(3 档)+ 撤销重做 | 覆盖「裁/圈/指/写/编号」90% 场景;不放显式删除按钮 |
| 输出动作 | 完成并复制(Enter)覆盖剪贴板 + toast「已复制(含标注)」;另存为(Ctrl+S)存 PNG;取消(Esc)不动剪贴板 | 纯图已先入剪贴板,编辑器是「升级」语义 |
| 4 卡全覆盖,零分支 | 编辑器只认 `QPixmap`,复用 `_grab_pixmap_hidpi` 产物 | 时域/FFT/FFT-time/阶次 4 卡自动覆盖 |
| 不动的东西 | 出口 2(FFT-time 检查器)路径、envelope/数值路径、`grab_pixmap`/`grab_main_chart` 抓图语义、CursorPill 合成、`save_figure` 保存风格 | 本轮只在出口 1「已拿到 QPixmap」之后接管 |

### 交互补强批次(P0/P1,不扩工具)

用户已明确:当前标注工具种类足够,本轮不做马赛克/模糊/橡皮/取色/贴图/历史等 P2 能力;目标是把现有工具做成类
Snipaste 的顺手交互。

**P0 必做:**
- 画布可缩放/平移:鼠标滚轮或 `Cmd/Ctrl +/-` 缩放,`0`/`1:1` 恢复,缩放围绕鼠标位置;导出尺寸仍等于背景 pixmap 设备像素。
- 工具栏图标化:复用现有 `qtawesome`/MDI 图标风格,工具按钮 icon-only + tooltip;当前工具高亮;「完成复制」蓝色主按钮。
- 颜色/粗细是可操作控件:颜色 swatch + 粗细按钮/快捷键;修改会影响新标注,也会作用到当前选中标注。
- 选择工具真正可移动:单击选中、拖动整体移动、方向键微调、`Delete/Backspace` 删除选中。
- 线/箭头绘制支持 `Shift`:按住 `Shift` 时吸附水平或垂直方向。
- 文字直接在图面输入:点击创建可编辑 `QGraphicsTextItem`,聚焦直接输入;`Esc` 先结束文字编辑,不直接关闭窗口。
- 裁剪先出框:拖拽只创建/调整裁剪框,框内可拖、边角可调;`Enter`/双击应用,`Esc` 取消裁剪态。

**P1 基础优化:**
- 直线/箭头端点可二次调整;矩形有边角控制点可调整大小。
- 多选/全选:支持 `Cmd/Ctrl+A` 全选标注,`Cmd/Ctrl` 点击切换多选。
- 复制粘贴标注:`Cmd/Ctrl+C/V` 复制当前选中标注,粘贴时略微偏移并选中新副本。
- 样式记忆:当前工具、颜色、粗细在同一编辑器会话内保持,切工具不丢。
- 状态反馈:选中框/控制点、hover cursor、缩放百分比、undo/redo 可用态;这些只做编辑器内反馈,不增加说明文案。

**P2 明确范围外:**马赛克/高斯模糊/橡皮、取色器、贴图 pin、截图历史、旋转/透明/点击穿透、OCR、上传分享。

## 设计

### A — 出口 1 接发布管道（满足硬约束的核心）

新增 `MainWindow._publish_copied_pixmap(pix: QPixmap)`:

```
1. if pix is None or pix.isNull(): return            # fail-safe,不弹任何东西
2. QApplication.clipboard().setPixmap(pix)           # 纯图立即入剪贴板
3. self.toast("已复制到剪贴板 · 可直接粘贴", 'success') # 必读主提示
4. self._copy_thumbnail.present(pix)                 # 右下角可选缩略图(见 B)
```

改造 `ChartStack._copy_card_image`:保留抓图 + 时域卡 CursorPill 合成,**末尾不再自行 setClipboard/emit 文案**,
改成把最终 `pix` 上交主窗口:
- `image_copied = pyqtSignal(str)` 改为 `image_captured = pyqtSignal(QPixmap)`(或并存),`main_window.py:242` 的连接
  迁到 `_publish_copied_pixmap`;删 `chart_stack.py:1422-1423` 的 setClipboard + emit 旧文案。
- 4 张卡的复制按钮经由 `_copy_card_image` 全部汇入此管道 → 4 卡都获得「toast + 缩略图」。

**出口 2(`_copy_fft_time_image`)保持不变**:仍直接 `setPixmap`、仍是现状行为,不接缩略图/标注(本轮范围外)。

> 选址理由:缩略图与 toast 都挂顶层主窗口(定位主窗口右下角、跨卡一致),而 `toast()` 本就在 MainWindow,
> 故发布管道落在 MainWindow 最自然。

### B — 悬浮缩略图 `CopyThumbnail(QWidget)`（`markup/thumbnail.py`）

- 顶层 frameless 子件(parent=MainWindow),`present(pix)`:把 `pix` 缩成小预览(长边 ~160px,`Qt.SmoothTransformation`),
  定位主窗口右下角(参考 `Toast._reposition` margin,留状态栏空间),淡入(借 `QGraphicsOpacityEffect`+`QPropertyAnimation`)。
- 视觉:圆角卡片(沿用 style.qss)+ 缩略图 + 副标题「点击编辑」+ 右上角 `✕` + **倒计时进度条/环**(3000ms),
  让用户一眼看出「会自己消失」。
- 行为:
  - `enterEvent` → 停 `_hide_timer`、暂停倒计时;`leaveEvent` → 续。
  - 点缩略图主体 → `clicked.emit(full_pix)` → MainWindow 开编辑器(传**全分辨率** `pix`,非预览缩略)。
  - `✕` 或 3s 到 → 淡出隐藏;无视 → 剪贴板里仍是纯图。
  - 「同时只一个」:`present` 复用单实例,新复制替换旧缩略图。
- 关键:持有全分辨率 `pix` 引用,预览仅显示用;开编辑器用全分辨率那张保证清晰。

### C — 标注编辑器 `MarkupEditor(QWidget)`（`markup/editor.py`）

独立非模态窗口。构造:`MarkupEditor(pixmap: QPixmap, on_done: callable)`。

**场景 / 图层模型(矢量,非位图刷涂):**
- `QGraphicsScene` + `QGraphicsView`(view 适配窗口缩放显示,但**渲染坐标 = 背景 pixmap 原始设备像素**)。
- 背景:`QGraphicsPixmapItem(pixmap)`,z=0,不可选不可移、不参与标注 hit-test。
- 每个标注 = 独立 `QGraphicsItem`(z≥1):
  - 箭头/直线:press 定起点、drag 实时预览、release 定型(`QGraphicsLineItem` + 箭头头部 `QGraphicsPolygonItem`)。
  - 矩形:`QGraphicsRectItem`,橡皮筋式。(椭圆可选,不进 v1。)
  - 画笔:drag 累积点入 `QPainterPath` → `QGraphicsPathItem`。
  - 文字:click 落可编辑 `QGraphicsTextItem`,打完点别处提交。
  - 序号①②③:click 落自增编号圆点(圆+居中数字 group item);`self._next_index` 自增。
- 「选择」工具:item `ItemIsSelectable|ItemIsMovable`,可拖/改色;非选择工具时背景不可选。误操作优先靠撤销/重做处理,主工具栏不放垃圾桶删除。

**裁剪工具 `剪裁`(核心新增):**
- 激活 → 进入裁剪态:覆盖一个 `CropOverlay`(默认=全图或上次裁剪区),**框外半透明压暗**,
  框边 8 个手柄(4 角+4 边)可拉伸、框内可拖动整体。
- 确认:`应用`按钮 / 双击框内 / Enter → 提交;`Esc` → 退出裁剪态、放弃本次裁剪框(保留当前图)。
- 提交语义(重定背景,**可撤销**):
  1. `cropRect` 取**背景设备像素坐标**(2× 高清空间),`new_bg = pixmap.copy(cropRect)` —— 保留全分辨率。
  2. 背景 item 换成 `new_bg`;`scene.setSceneRect` 缩到新尺寸;view 重新 fit。
  3. 现有标注 item 全体平移 `-cropRect.topLeft()`;落在新边界外的部分由导出按新边界裁掉(无需删 item)。
  4. 把(旧背景 + 旧 sceneRect + 旧 item 偏移)封进 `CropCommand` 入 `QUndoStack` → `Ctrl+Z` 可还原全图。
- 可重复裁剪;每次裁剪一层 undo。

**工具栏(编辑器顶部一行,紧凑):**
```
[关闭] | 红色  4px | [↖选择] [⛶裁剪] [↗箭头] [╱直线] [▭矩形] [✎画笔] [T文字] [①序号] | [撤销] [重做] | [保存 Ctrl+S] [完成复制 ↵]
```
- 颜色 6 预设(红/橙/黄/绿/蓝/黑或白),当前色高亮;粗细 3 档;`QUndoStack` 撤销/重做(Ctrl+Z/Y);
  工具状态机 `self._tool ∈ {select,crop,arrow,line,rect,pen,text,number}`。输出动作只保留「保存」和「完成复制」,不再放单独「复制」按钮。

**输出(拍平):**
- 完成并复制(Enter,主):`scene.clearSelection()` → 渲染 scene 到**与当前背景同等设备像素尺寸**的 `QImage`
  (`scene.render(painter, target=image.rect(), source=背景 itemRect)`,`Antialiasing`+`SmoothPixmapTransform` on)
  → `QPixmap.fromImage` → 回调 `on_done(annotated_pix)` → MainWindow 走「覆盖剪贴板 + toast『已复制(含标注)』」→ 关窗。
  **裁剪后背景设备尺寸 = 裁剪区尺寸**,故导出自动是裁剪图,无单独裁剪导出分支。
- 另存为(Ctrl+S):同样拍平 → `QFileDialog.getSaveFileName(... "PNG (*.png);;JPEG (*.jpg)")`(对齐 `save_figure`)→ `pix.save(path)`。
- 取消(Esc)/关窗:什么都不做,剪贴板保留最初纯图。

> 分辨率铁律:背景是 2× 抓的高清图,裁剪用 `pixmap.copy()`(无损子图)、拍平按背景设备像素渲染,
> 不得按窗口显示尺寸导出(否则掉清晰度)。

### D — 模块边界

- `markup/` 自包含,**不 import** 画布/数值模块;只依赖 PyQt + 一个 `QPixmap` 入参 + 一个完成回调。
- MainWindow 是唯一缝合点(发布管道 + 持有缩略图单例 + 打开编辑器)。
- → 全部为 `pyqt-ui` 性质工作;动手时按 squad 规则走 `pyqt-ui-engineer`,无数值/重构耦合。

### E — UI 预览

静态预览文件:`docs/analyzer/ui-prototypes/2026-05-31-copy-annotation-editor-ui.html`。

预览覆盖两块:
- **缩略图显示 UI**:主窗口右下角小卡片,包含刚复制图的预览、副标题「点击标注/裁剪」、关闭按钮、3s 倒计时进度条;底部 toast 仍是主提示「已复制到剪贴板 · 可直接粘贴」。
- **编辑器 UI**:独立非模态窗口,顶部单行工具栏(关闭、颜色、粗细、选择/裁剪/箭头/直线/矩形/画笔/文字/序号、撤销/重做、保存、完成复制),中间高清画布,裁剪态显示框外压暗、8 个手柄、应用/退出裁剪按钮。

## 测试（离屏 `QT_QPA_PLATFORM=offscreen`，沿用 tests/ui 风格，QTimer 直调槽）

- **发布管道**:`_publish_copied_pixmap(valid_pix)` → 剪贴板拿到该 pix(尺寸匹配)、toast 被调一次、缩略图 `present` 被调;
  `pix=None/isNull` → 三者都不触发。
- **4 卡汇流**:4 张卡的 `copy_image_requested` 均经 `_copy_card_image` → `_publish_copied_pixmap`(monkeypatch 断言);
  时域卡仍含 CursorPill 合成。**出口 2 `_copy_fft_time_image` 不变**(回归:仍直接 setPixmap、行为如旧,不触发缩略图)。
- **缩略图**:`present` 后可见、定位父窗口右下区;`enterEvent` 停定时器、`leaveEvent` 续;`✕`/超时 → 隐藏;
  点击用**全分辨率**(非预览)pix 触发 `clicked`;再次 `present` 替换单实例不叠加。
- **编辑器图层**:各工具 press/move/release 生成对应 item 且数量正确;序号自增;选择工具下可选中/拖动;
  `QUndoStack` 撤销恢复 item 数。
- **裁剪**:对已知尺寸 pixmap 提交一个 `cropRect` → 背景 item 尺寸 == cropRect 尺寸、`sceneRect` 同步缩小、
  已有标注 item 坐标平移 `-topLeft`;`Ctrl+Z` 还原背景尺寸与 item 坐标(`CropCommand` 可逆);裁剪用 `pixmap.copy` 无损
  (采样裁剪区内某像素颜色 == 原图对应像素)。
- **拍平分辨率**:导出 `QImage` 尺寸 == 当前背景设备像素尺寸(裁剪前=全图、裁剪后=裁剪区),不随窗口显示尺寸变;
  标注像素确实落在导出图上。
- **完成回调**:Enter → `on_done(annotated)` 非空且尺寸=当前背景;Esc → 不调 `on_done`、剪贴板不变。
- **回归**:原有 4 卡复制仍把图(时域含 pill)送达剪贴板;`save_figure`、`grab_pixmap`/`grab_main_chart` 语义不变。

## 范围外

- **出口 2:FFT-vs-Time 检查器的「复制主图 / 复制完整视图」两个按钮 —— 本轮不接缩略图/标注,维持现状静默**。
- 马赛克/高斯模糊、钉图到桌面(pin)、取色器、椭圆/多边形等复杂形状、OCR、旋转 —— v1 不做。
- 「数据标注」(matplotlib remark `ax.annotate`,`canvases.py`)是另一层(标在数据上而非图片上),不合并、不改。
- 多缩略图堆叠 / 复制历史队列 —— 维持「同时一个」。

## 验收标准（必做真机验证；本仓库铁律：只认真机渲染/截图，不认「属性设上了+单测过」）

逐卡各验一遍(时域 subplot/overlay、FFT、FFT-vs-Time、阶次,共 4 卡的复制按钮):
- 点该卡「复制为图片」→ **立即** Ctrl+V 到外部(微信/PPT/画图)能粘出图;**同时**底部 toast 明确显示「已复制到剪贴板 · 可直接粘贴」。
- 右下角缩略图出现,3s 内不动会自行淡出;鼠标移上去倒计时暂停、移开继续;`✕` 立即关。
- 点缩略图 → 独立标注窗口(不影响主窗口操作)。
- **裁剪**:选裁剪工具拖框、拉手柄、移动框,框外压暗;应用后画布缩到裁剪区;完成复制 → 外部粘到的就是裁剪后的图且清晰;`Ctrl+Z` 能还原全图。
- 箭头/直线/矩形/画笔/文字/序号逐个可画、可选中拖动、可删、可撤销重做;颜色粗细生效。
- 完成并复制 → 外部粘贴得到**含标注/裁剪**的图且清晰(2× 不糊);toast 显示「已复制(含标注)」。另存为得 PNG。取消 → 剪贴板仍是无标注纯图。
- 时域卡复制仍正确合成 CursorPill。
- **FFT-vs-Time 检查器的两个复制按钮行为与改动前一致(回归)**。
- 高 DPI / 最大化窗口下复制,缩略图与编辑器导出均不糊。

## 风险

- **改 `image_copied` 信号**(带上 QPixmap / 改名)会动 `main_window.py:242` 连接 —— 必须同步迁到 `_publish_copied_pixmap`,否则复制无提示;用现有复制回归用例兜。
- **缩略图不能点击穿透**:不可照搬 Toast 的 `WA_TransparentForMouseEvents=True`,否则点不开编辑器。
- **裁剪坐标空间**:`cropRect` 必须在背景**设备像素**坐标(2× 空间)取,view 显示坐标需经 `mapToScene` 换算,否则裁错位置/掉清晰度。标注平移与背景重定须在同一 `CropCommand` 内原子完成,保证 undo 一致。
- **拍平分辨率**:务必按当前背景设备像素渲染(裁剪后是裁剪区尺寸),误用窗口显示尺寸会掉清晰度(测试已钉尺寸断言)。
- **非模态编辑器生命周期**:窗口需保持引用(挂 MainWindow 或模块级单例),否则被 GC 即关;完成/取消后显式释放避免泄漏。
- **缩略图与 toast 叠放**:都在底部区域,需错开(toast 底部居中、缩略图右下角)避免视觉打架。
- **大图性能**:2×+4K 下 pixmap 较大,缩略图预览用一次性 `scaled` 缓存,别每帧重算;裁剪 `copy` 一次即可。
