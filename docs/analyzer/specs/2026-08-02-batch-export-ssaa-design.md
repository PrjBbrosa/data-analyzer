# 批处理 PNG 导出抗锯齿（SSAA）设计

- 日期：2026-08-02
- 状态：待实施
- 范围：`mf4_analyzer/batch_render_qt/`（导出光栅化）+ 曲线 AA 契约归一化
- 计划文档：`docs/analyzer/plans/2026-08-02-batch-export-ssaa.md`

## 1. 问题

批处理导出的 PNG 里曲线全部呈硬台阶（无抗锯齿），文字却是平滑的。
用户报告的样本：5 面板 subplot、X 轴为通道（Rack travel，非单调）、
Y 为实测轴向力（.zfd）。

### 1.1 根因链（三层）

1. **顶层 painter hint 对曲线无效。**
   `_export.py::render_scene_image` 设置了
   `QPainter.Antialiasing | TextAntialiasing`，但 pyqtgraph 的
   `PlotCurveItem.paint()`（0.14.0，`PlotCurveItem.py:978`）在绘制前无条件
   用 `self.opts['antialias']` 覆盖该 hint。文字平滑、曲线台阶正是
   `TextAntialiasing` 未被覆盖、`Antialiasing` 被覆盖的直接证据。
2. **构造期按 profile 赋值** —— `_builder.py:864`
   `antialias=profile.strategy != "dense_discrete"`。
3. **settle 期二次覆盖（实际决定者）** —— `_builder.py:450` 的
   `setData(..., antialias=_native_time_antialias(...))`：

   ```python
   # _builder.py:317
   q90 = float(profile.normalized_step_quantiles[2])
   return not (profile.transition_fraction >= 0.5     # _HIGH_RASTER_TRANSITION_FRACTION
               and q90 >= 0.001)                      # _HIGH_RASTER_NORMALIZED_Q90
   ```

### 1.2 为什么真实信号必然命中

`q90 >= 0.001` 意为"相邻样点跳变 90 分位 ≥ 满量程 0.1% 即关 AA"。实测：

| 信号（60k 点） | q90 | AA 结果 |
| --- | --- | --- |
| 干净合成正弦（现有测试 fixture） | 1.7e-4 | True |
| 正弦 + 0.1% 高斯噪声 | 1.2e-3 | False |
| 正弦 + 0.5% 噪声 | 5.7e-3 | False |
| 复现用户 zfd 力信号 | 2.2e-1 | False |

规则以无噪声 fixture 验收（`test_batch_render_qt_display_envelope.py:172`），
而任何带传感器噪声的实测通道都落入 False 分支。规则动机（约束光栅成本）
是真实的——见 §2 实测——但阈值把"例外"变成了"常态"。

## 2. 方案对比（全部实测）

基准场景：1920×1080、5 subplot、60k 点/曲线、X=通道（非单调）、
offscreen、`.venv` Python 3.12 / PyQt5 / pyqtgraph 0.14.0，三次取最优。

| 方案 | 单图耗时 | 相对基线 | 结论 |
| --- | --- | --- | --- |
| A 现状（AA off） | 143 ms | — | 质量不可接受 |
| B 强开 pyqtgraph 原生 AA | 2275 ms | **+2131 ms** | 淘汰：成本随数据形状爆炸（AA-off 走 `drawLines` 快路径；AA-on 退回 QPainterPath 全路径合成，`PlotCurveItem.py:786`） |
| F′ 仅加 SSAA、保留 AA 规则 | +21~55 ms 起 | 数据相关 | 淘汰：AA-on 曲线在 N× 光栅下成本 ×N²；FFT 谱线硬编码 `antialias=True`（`_builder.py:1204`）而 dB 谱通常呈密集毛刺，单图可能额外数百 ms；且成本模型不可预测 |
| **F 曲线原生 AA 统一关 + 导出端 SSAA（选定）** | 164 ms (2×) / 199 ms (3×) | **+21 / +55 ms** | 成本与数据无关（纯光栅面积）；单一 AA 机制 |

质量核验（同场景）：2× SSAA 放大裁切与原生 AA 目视基本一致，硬台阶消失；
3× 在浅斜率细线上灰阶更细腻（每轴 3×3=9 个覆盖子样本）。与现状的逐像素
差异集中于线条边缘（2× pen 补偿版 mean|Δ|=1.25，>60 灰阶差异像素 0.54%），
版面几何零漂移。

关键前置验证：`scene().render()` 在 1× 下与现行 `widget.render()`
**逐字节相同**（time 类，mean|d|=0、max=0），原语可替换。

## 3. 选定方案

**总原则：批处理渲染器中曲线级原生 AA 永远为 False；唯一的抗锯齿机制是
导出光栅化时的整场景超采样（SSAA）。** 场景仍按 1× 构建与 settle（版面、
envelope、tick 全部不变），仅最终光栅化到 N× 画布再平滑缩回。

### 3.1 `_export.py::render_scene_image` 新流程

```python
_SSAA_MAX_FACTOR = 3
_SSAA_MAX_SIDE_PX = 32_000        # Qt QImage 单边上限 32767，留余量
_SSAA_MAX_PIXELS = 160_000_000    # 3x FHD≈18.7MP, 3x 4K≈74.6MP, 2x 8K≈132MP

def supersample_factor(width_px: int, height_px: int) -> int:
    for factor in (3, 2):
        if (width_px * factor <= _SSAA_MAX_SIDE_PX
                and height_px * factor <= _SSAA_MAX_SIDE_PX
                and width_px * height_px * factor * factor <= _SSAA_MAX_PIXELS):
            return factor
    return 1

def render_scene_image(scene, *, metadata=None):
    scene.show_and_settle()
    w, h = scene.options.width_px, scene.options.height_px
    factor = supersample_factor(w, h)
    big = QImage(w * factor, h * factor, QImage.Format_ARGB32_Premultiplied)
    big.fill(scene.theme.background)
    painter = QPainter(big)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    with _cosmetic_pens_scaled(scene.widget, factor):
        scene.widget.scene().render(
            painter, QRectF(0, 0, w * factor, h * factor), QRectF(0, 0, w, h))
    painter.end()
    image = big if factor == 1 else big.scaled(
        w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    # 元数据与 DPI 一律设在最终图上：QImage.scaled() 不保证携带 setText 文本。
    for key, value in dict(metadata or {}).items():
        image.setText(str(key), str(value))
    image.setDotsPerMeterX(round(scene.options.dpi / 0.0254))
    image.setDotsPerMeterY(round(scene.options.dpi / 0.0254))
    return image
```

要点：

- **单一代码路径**：factor==1 时同样走 `scene().render()`（已验证 1× 逐字节
  等价），不保留 `widget.render()` 双路径。
- AxisItem 的 QPicture 在 paint 时按当时 paint-device DPI 记录；`big` 使用
  默认逻辑 DPI，与现行行为一致，dpm 仅在最终图上设置——保持现有注释所述
  契约（`_export.py:31-35`）。
- 背景 `transparent` 时 Premultiplied 格式经 `scaled()` 缩回 alpha 正确。

### 3.2 设备像素状态补偿（`_prepared_for_supersampling`）

有**两类**场景状态钉死在设备像素上，会原封不动穿过放大、再被缩回打小。
（第二类是实施期发现的，不在初版设计里——见 §8。）

#### 3.2.1 cosmetic pen

pyqtgraph `mkPen` 默认 `cosmetic=True`（`functions.py:425`），线宽以设备
像素计、不随 render 的 source→target 变换缩放。不补偿则 N× 渲染缩回后
线宽只有 1/N（首轮探针实测确认）。pyqtgraph 自带 `ImageExporter` 的
`resolutionScale` 机制全库只有 `ScatterPlotItem` 认，指望不上。

契约：

- 上下文管理器；进入时把宽度 ×factor（宽度 0 的 hairline 先视为 1.0），
  退出时**必须还原原 QPen 并触发失效**。
  `tests/test_batch_qt_render_parity.py:76-127` 存在对同一 scene 连续两次
  `render_scene_image` 后对比的用例，不还原即双重放大、直接违约。
- 覆盖对象（本仓库批处理场景实际存在的全部持笔者）：
  1. 任何带 `opts` dict 且值为 QPen 的 item（`pen`/`shadowPen`/
     `symbolPen`）——经 `scene.items()` 递归天然覆盖 PlotDataItem 的子
     PlotCurveItem，以及 LegendItem（其 `opts['pen']` 为边框笔）。
     直接改 `opts[key]` 后 `item.update()`（PlotCurveItem.paint 每帧读
     opts，无 pen 级缓存）。
  2. `AxisItem`：经 `setPen()` 读改写（同时覆盖轴线、tick 与 grid——grid
     由轴笔加 alpha 派生），setter 自带 QPicture 缓存失效。`textPen` 只
     影响文字颜色，不处理。
  3. `ViewBox.border`：经 `setBorder()`。
- 仅处理 `isCosmetic()` 为 True 的笔；DashLine 的 dash pattern 以笔宽为
  单位，随宽度等比缩放、缩回后观感不变，无需特殊处理。
- 当前场景中 TextItem（面板内标题）只有 fill 无 border，不在覆盖面内；
  若未来加 border 需纳入（见 §6 风险 1 的兜底 gate）。
- TextItem **不需要**处理：它虽然靠 `updateTransform()` 保持屏幕尺寸，但取的是
  **父项**的 sceneTransform；批处理里标题直接 `plot.scene().addItem()` 无父项，
  逆变换为单位阵，因此正常随 painter 缩放。

#### 3.2.2 `ItemIgnoresTransformations`

`LegendItem` 在 `__init__` 里设了这个 flag 以保持屏幕尺寸。Qt 对该 flag 的处理
是相对 **painter 的 world transform**——`QGraphicsScene.render()` 的 target/source
缩放会被剥掉，图例于是在 N× 画布上按 1× 设备尺寸绘制，缩回后只剩 1/N。实测
(fft-linear, factor=3) 图例区墨量 92 px，而正确值为 390 px。

对策：超采样这一遍把带该 flag 的 item 逐个 `setFlag(..., False)`，结束后还原。
清 flag 是安全的——这些 item 的几何本来就在 view 像素坐标系里，锚定的场景位置
与 flag 无关（实测 `sceneBoundingRect()` 在清/还原前后逐位不变）。

pyqtgraph 的 `ButtonItem`（原生 auto-range 按钮）同属此类，一并覆盖。

### 3.3 `_builder.py` 归一化（删规则）

- `_builder.py:864`：`antialias=profile.strategy != "dense_discrete"` →
  `antialias=False`。
- `_builder.py:450-455`：`setData(...)` 去掉 `antialias=` 参数（构造时已
  False，pyqtgraph 0.14 的 `updateItems` 强制 styleUpdate 会重推 opts）。
- `_builder.py:1204`（FFT 谱线）：`antialias=True` → `False`。
- 删除 `_native_time_antialias`（`_builder.py:317`）及
  `_HIGH_RASTER_TRANSITION_FRACTION` / `_HIGH_RASTER_NORMALIZED_Q90`
  两常量（`_builder.py:47-48`）。
- `classify_render_profile` / `RenderProfile` **保留**：envelope 分桶
  （`bucket_width_for`、`positions_envelope`）仍依赖它，本设计不动数据
  抽稀路径。

附带修复：现状同一张分组图里"干净通道 AA-on、噪声通道 AA-off"的混搭
观感随规则删除一并消失。

## 4. 非目标

- 不给 `BatchRenderOptions` / 配方 / UI 增加超采样开关（内部常量 + 钳制
  函数，导出为模块级以便测试 monkeypatch）。无 UI 交互变化，无需
  `/update-hints`。
- 不改屏上单文件画布（`ui/pg_canvas/line_canvas.py` 的交互 AA 策略是另
  一套预算，继续独立）。
- 不改 envelope/分桶/`_ds_legacy_pure`。非单调 X 的 8000 点固定抽稀在
  X-Y 图上可能自带毛刺（按样点索引分桶取 Y 极值、桶内 X 顺序被打乱），
  与走样是两个问题，另行立项验证。
- 不对 fft_time 热力图做特殊分支：`ImageItem` 默认最近邻采样，整数因子
  放大后箱式缩回近似恒等；实际效果由 §7 gate 5 目检兜底。

## 5. 受影响契约（枚举）

| 位置 | 现状 | 变更 |
| --- | --- | --- |
| `tests/test_batch_render_qt.py:383` | 断言全部曲线 `antialias is True` | 改为 `is False`（测试名中的 "curves_are_aa" 同步更名） |
| `tests/test_batch_render_qt_display_envelope.py:172` | 干净信号原生 AA=True | 改为 False；"导出质量"意图由新 SSAA 测试承接 |
| `tests/test_batch_render_qt_display_envelope.py:190` | 高光栅信号 AA=False | 断言保留（恒 False），删除对 `_native_time_antialias` 语义的引用 |
| `tests/test_batch_qt_render_parity.py:76,99,122` | 同 scene 两次渲染对比 | 行为必须保持（pen 还原契约）；corner ink 阈值（160）若被 SSAA 边缘像素影响需重标定 |
| `tools/verify_batch_qt_render_parity.py:1245` | gate `batch_export_antialias` = 全 True | 语义反转为全 False（token 名同步改） |
| `mf4_analyzer/batch_time_group_acceptance.py:172` | 直接调 `render_scene_image` | 行为核验（其 ink/文本断言基于区域统计，预期兼容） |

## 6. 风险与对策

1. **漏补某类 cosmetic pen → 该元素缩回后偏细。** 对策：§3.2 覆盖面枚举
   自本仓库场景 item 实测清单；gate 3 的 1× 逐字节对照 + gate 5 四类图
   目检兜底。任何"某元素变淡/变细"都指向此处。
2. **缩放丢元数据。** 对策：setText/dpm 一律设在最终图（§3.1），gate 4
   显式断言。
3. **大尺寸内存/Qt 边界。** 3× FHD 临时画布 ≈75 MB，可接受；因子钳制
   保证单边 ≤32000、总像素 ≤160MP，16384×16384 极端配置退化为 1×（无
   AA，与现状持平，不劣化）。
4. **GUI 线程增时。** SSAA 增量发生在 `render_on_gui_thread` 回调内，
   FHD +21~55 ms、相对现状 143 ms 同数量级；PNG 编码仍在 worker 侧。
5. **`test_show_and_settle_uses_a_bounded_paint_event_drain_budget`
   （settle 绘制预算）**：SSAA 不新增 paint drain（渲染发生在 settle 之
   后的显式 `scene().render()`），预期不受影响；纳入 gate 2 回归确认。

## 7. 验收 Gates

1. **新增 `tests/test_batch_render_qt_ssaa.py`**：
   - `supersample_factor` 钳制表（FHD→3、4K→3、8K→2、16384²→1、单边
     32000 约束）；
   - 双次渲染幂等：同 scene 连续两次 `render_scene_image` 输出逐字节相
     同（pen 还原契约）；
   - 平滑效果量化：噪声 fixture 在 factor=1（monkeypatch）与默认 factor
     下各渲一次，曲线带内"介于背景与线色之间的过渡像素"占比显著上升
     （宽松阈值，如 ≥3×）；
   - 元数据存续：最终 PNG 的 `text("Title")` 非空、dpm 与 dpi 一致；
   - 1× 原语等价：四类 kind（time/fft/fft_time/order_time）各取小 fixture，
     factor 强制 1 时 `scene().render` 输出与 `widget.render` 参照逐字节
     相同。
2. **存量套件**：`tests/test_batch_render_qt*.py`、
   `tests/test_batch_qt_render_parity.py`、`tests/test_batch_runner.py`
   全绿（按 §5 更新契约后）。
3. **性能预算**：复跑基准探针（计划文档附方法），FHD 5 面板 60k×5 场景
   相对改动前基线增量 ≤ +100 ms。
4. **工具核验**：`tools/verify_batch_qt_render_parity.py` 按新 token 语义
   跑通。
5. **真实产物目检**（CLAUDE.md「验真机渲染」）：用真实 .zfd 批任务重新
   导出 time/fft/fft_time/order_time 各一张，放大检查曲线边缘平滑、线宽
   与改动前一致、热力图无发糊。

## 8. 实施结果与偏差（2026-08-02 完成）

实现与本设计一致，以下四点在实施期修正：

1. **新增 `ItemIgnoresTransformations` 处理**（§3.2.2）。初版设计只考虑了
   cosmetic pen；图例缩成 1/3 的 bug 是在四类图目检里发现的，初版探针只测了
   无图例的 time subplot 才漏掉。契约函数因此从 `_cosmetic_pens_scaled`
   更名为 `_prepared_for_supersampling`。
2. **gate 4 重新定标。** `tools/verify_batch_qt_render_parity.py` 在 `main`
   上**本就是红的**（14/14 case 失败：`axis_font_9pt` 14 次、
   `axis_ranges_match` 4 次、`no_text_overlap` 1 次），`跑通` 不可达。实际
   验收改为「失败断言键与基线逐项一致，无新增无恶化」——已达成。
   `tests/test_batch_qt_render_parity.py::test_parity_tool_generates_current_machine_evidence`
   同属既有失败，非本次引入。
3. **幂等契约放宽。** 同一 scene 首次渲染与第二次不逐位相同——这是既有行为
   （factor=1 下 time-subplot8 同样如此，属 pyqtgraph 首帧惰性缓存预热），
   非本次引入。实测两张图墨量差 ≤5%、曲线墨量差 0.25%，视觉等价。最终契约：
   渲染 2 与 3 逐位相同 + 墨量三次互差 ≤10%（漏还原会导致 ×3 变粗，量级远超
   该容差），另加一条直接检查 pen 值与 flag 是否还原的确定性用例。
4. **`test_plot_corner_pixel_guard_detects_native_auto_range_button` 的
   mutation 改写。** pen 补偿会连带触发 pyqtgraph 自身的 `updateButtons()`，
   把测试手工 `autoBtn.show()` 强开的按钮重新隐藏（生产环境该按钮本就必须
   隐藏，无害）。改为走 pyqtgraph 自己的可见性规则
   （`showButtons()` + `mouseHovering=True` + `updateButtons()`），mutation
   才能存活到渲染。

**实测数据（offscreen，5 面板 60k×5 非单调 X-Y，1920×1080，三次取最优）：**
改动前 139.5 ms → 改动后 208.5 ms，**+69 ms**（gate 3 门槛 ≤ +100 ms）。

**Mutation 验证**（确认测试有牙齿）：跳过还原 → 9 条失败；去掉 flag 清除 →
图例用例失败；不放大 pen → 3 条失败。
