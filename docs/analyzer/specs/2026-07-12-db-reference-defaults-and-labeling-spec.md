# dB Reference 默认值、自动解析与结果标识 — Product / Design Spec

Date: 2026-07-12  
Status: Approved direction; implementation not started  
HTML reference: `docs/analyzer/reviews/reports/2026-07-12-db-reference-defaults-draft.html`  
Implementation plan: `docs/analyzer/plans/2026-07-12-db-reference-defaults-and-labeling-implementation.md`

## 1. Outcome

TraceLab 的 FFT、FFT-vs-Time 和 Order 三类分析共享一套可追溯的 dB reference
系统：

1. 每个现有 `dB 参考:` 输入框右侧增加一个紧凑的默认值管理按钮。
2. 用户可以编辑内置默认、添加自定义单位映射、删除条目、恢复系统默认。
3. Auto 模式按当前 source 的通道 metadata、物理量和单位选择 reference；Manual
   模式保留当前 View 的手动值。
4. FFT 纵轴、热力图色标、切片轴、readout、批处理图片都显示当前 reference。
5. `weighting=A` 且结果为对数幅值时，标签使用 `dBA`，不再只写通用 `dB`。
6. `db_reference` 仍是 display-only：改变 reference 只从已有线性结果重新渲染，
   不重新计算 FFT、Spectrogram 或 COT；`weighting` 仍是 compute-relevant。

完成后的界面必须同时满足两项视觉要求：

- 信息层级、交互关系、A/M 徽标、来源说明和管理弹窗向已批准 HTML 看齐；
- 字体、颜色、圆角、字段高度、卡片和弹窗外壳使用 TraceLab 当前 Qt/QSS 体系，
  不能把 HTML 的网页像素或独立视觉主题原样搬进软件。

## 2. Evidence And Current State

| 当前事实 | 代码锚点 | 差距 |
| --- | --- | --- |
| 三个 Inspector 共用 `make_db_reference_spinbox()` | `mf4_analyzer/ui/inspector_sections/_helpers.py:124`；三个 `contextual_*` | 默认 `1.0`，只有数值框，没有模式、来源或管理按钮 |
| 当前控件使用 6 位小数 | `_helpers.py:131-135` | `1e-9`、`1e-12` 无法可靠显示/保存，可能成为 `0.0` |
| HEAD HDF 已保留通道 `quantity`、`unit`、`db_reference` | `mf4_analyzer/io/loader.py:727-734` | source 选择路径只读取 unit，没有应用 channel reference |
| selected-source 只做 unit preset 推荐和 audio weighting | `mf4_analyzer/ui/main_window/window.py:1452-1533` | 没有统一 ChannelFacts / reference resolver |
| FFT compute cache 已排除 reference，render signature 包含数值 | `window.py:851-878`；`_analysis_mixin.py:365-418` | Auto 多 source 需要 per-source render signature，而不是单个 Inspector 数值 |
| FFT direct/cache render 使用统一线性结果 | `_fft_mixin.py`；`window.py:922-982` | 纵轴仍只写 `Amplitude (dB)`；overlay 共用一个 reference |
| FFT-vs-Time render-time 接收 `db_reference` | `_fft_time_mixin.py:641-682` | 色标/切片/readout 没有统一 dBA/re 标签 |
| Order 在 renderer 外预转换 dB | `_order_mixin.py:545-626` | 色标有 `dB re`，切片/readout 仍只写 `dB` |
| `AnalysisViewState.params` 随项目保存 | `analysis_view_state.py:57-89`；`_project_io_mixin.py:557-612` | 没有 `db_reference_mode` 和旧 schema 迁移 |
| Batch image 尊重 reference 数值 | `mf4_analyzer/batch.py:875-1016` | 图片标签只写通用 `Amplitude (dB)`；Auto 未按目标 source 解析 |

## 3. Goals

### G1 — Reference 可追溯

用户在任何 dB 图上都能回答：当前 0 dB 对应什么值、什么单位、来自哪里。

### G2 — Auto 可靠且可覆盖

Auto 优先尊重文件携带的合法 channel metadata；没有 metadata 时使用用户目录和
系统目录。用户可以覆盖目录，也可以对当前 View 输入 Manual reference。

### G3 — 多 source 不制造假比较

分屏和 FFT overlay 按各自 source 解析。不同 reference 或单位不能被一个来自第一条
曲线的全局标签掩盖。

### G4 — 兼容旧状态

旧 preset/project 不得因为缺少新字段而重置 `weighting`，也不得把旧的明确
`db_reference` 静默解释成新的 Auto 默认。

### G5 — 视觉可验收

最终 Qt 界面不是“有按钮就算完成”。必须在实际 TraceLab 窗口中证明 compound
字段、A/M 徽标、来源说明、弹窗、窄 Inspector、图轴标签与 HTML 的层级一致。

## 4. Non-goals

- 不改变 FFT、PSD、Spectrogram、COT 的计算公式或数据缓存内容。
- 不把 `db_reference`、catalog revision 或 Auto/Manual mode 加进 compute cache key。
- 不自动修改用户选择的 `weighting`；现有 audio-source 默认 A 计权逻辑保持独立。
- 不在每个项目中复制用户默认目录；目录属于本机用户设置。
- 不为 Batch 新增第二套 reference 编辑器；Batch 继续继承 current/preset params。
- 不改变 CSV/DataFrame 的线性数据值；reference 只影响 dB 图片和 dB 显示。
- 不处理声功率、声强等 `10·log10` quantity；本轮只处理线性幅值的
  `20·log10(A/A0)`。
- 不声称下表是“已验证的 Artemis 官方工厂表”。目前可安全描述为
  `ISO 1683 / HEAD compatible defaults`；真实 HEAD channel metadata 始终优先。
- 不引入网络同步、云端配置或按项目共享 catalog。

## 5. Terms And Data Model

### 5.1 Mode

`db_reference_mode` 只有两个合法值：

| 值 | 含义 |
| --- | --- |
| `auto` | 每个 pane/source 依据 metadata + catalog 动态解析 |
| `manual` | 当前 Analysis View 使用保存的 `db_reference`，不随 source/catalog 改变 |

新建 Analysis View 默认 `auto`。手动提交一个合法数值立即将当前 View 切换为
`manual`；在管理弹窗中启用“随通道自动选择”切回 `auto`。

### 5.2 Pure Domain Types

新增不依赖 Qt 的 `mf4_analyzer/db_reference.py`，至少提供：

```python
@dataclass(frozen=True)
class DbReferenceEntry:
    id: str
    quantity: str
    label: str
    unit: str
    aliases: tuple[str, ...]
    reference: float
    builtin_id: str | None = None

@dataclass(frozen=True)
class ChannelReferenceFacts:
    quantity: str
    unit: str
    metadata_reference: object = None
    is_audio_source: bool = False

@dataclass(frozen=True)
class DbReferenceResolution:
    value: float
    unit: str
    quantity: str
    source: str          # manual | metadata | user | system | generic | fallback
    warning: str = ""
```

`origin` 不从 JSON 直接信任；运行时根据 immutable built-in、override/custom 和
resolution 路径派生。

### 5.3 Persisted Analysis Params

三个 Contextual 的 `get_params()` / `current_params()` 必须包含：

```json
{
  "db_reference_mode": "auto",
  "db_reference": 0.000001
}
```

- Manual 时，`db_reference` 是手动权威值。
- Auto 时，`db_reference` 是 focused pane 最近一次解析到的兼容快照；重新打开、
  切换 source 或 catalog 后必须重新解析，不能把快照当权威。
- `db_reference_source`、catalog 内容、catalog revision 不进 View params。

## 6. Built-in Catalog

### 6.1 Immutable Factory Table

| Stable ID | Quantity | Unit / aliases | 0 dB reference | Product wording |
| --- | --- | --- | ---: | --- |
| `sound_pressure.pa` | `sound pressure` | `Pa` | `2e-5 Pa` | ISO/HEAD compatible |
| `acceleration.si` | `acceleration` | `m/s²`, `m/s^2`, `m/s2` | `1e-6 m/s²` | ISO/HEAD compatible |
| `velocity.si` | `velocity` | `m/s` | `1e-9 m/s` | ISO/HEAD compatible |
| `displacement.si` | `displacement` | `m` | `1e-12 m` | ISO/HEAD compatible |
| `force.si` | `force` | `N` | `1e-6 N` | ISO/HEAD compatible |
| `acceleration.g` | `acceleration` | `g` | `1e-6 / 9.80665 g` | SI-equivalent compatibility value |

`acceleration.g` 的存储值使用双精度表达式结果，不把显示舍入值重新写回。

### 6.2 Evidence Boundary

- HEAD HDF 内的合法 `db_reference` 是文件级事实，比内置表更可信。
- 当前没有足够证据把内置表命名为“Artemis official defaults”。代码注释、UI 文案、
  帮助和测试 fixture 都必须使用 `system` / `ISO/HEAD compatible`。
- 如果后续拿到 Artemis 设置页或官方手册，允许在不改 resolver 优先级的前提下更新
  built-in table 和引用说明；该证据更新必须同时改测试。

## 7. Unit And Quantity Normalization

### R1 — Exact Matching

沿用并提升当前 `_normalize_unit()` 的精确匹配思想：

- trim + casefold；
- `² → 2`、`³ → 3`，删除 `^` 和内部空白；
- 不做 substring match；`g` 不能命中 `kg` / `deg`，`Pa` 不能命中 `kPa`；
- alias 在保存时预归一化，运行时仍保留用户可读原文。

### R2 — Match Key

优先使用 `(normalized quantity, normalized unit alias)`。

- quantity 存在时，不允许仅凭相似字符串跨 quantity 命中。
- quantity 为空时，只有当 normalized unit 在当前有效 catalog 中只对应一个 quantity
  时才允许 unit-only match。
- `Pa` 且 quantity 缺失时，只在 `is_audio_source=True` 时推断为
  `sound pressure`；否则回退并警告，避免把一般压力静默当作 20 µPa 声压。
- duplicate `(quantity, alias)` 是保存错误，不允许 last-one-wins。

### R3 — Reference Validation

所有来源都必须通过同一个 validator：

```text
float-convertible AND finite AND value > 0
```

NaN、±Inf、空字符串、零、负值、无法解析的 metadata 都视为无效。无效 metadata
不阻断后续 catalog 解析；无效用户行不能保存，并在对应单元格显示错误。

## 8. Resolver Contract

### 8.1 Priority

同一 source 的最终顺序固定为：

1. `manual` View 的手动值；
2. 合法 channel metadata（仅当全局 `prefer_channel_metadata=True`）；
3. 用户对 built-in 的 override 或用户 custom entry；
4. 未被隐藏的 immutable built-in；
5. 单位不在 catalog：`1.0` 通用默认（source=`generic`，中性展示，无警告）；
6. 解析真正失败（unit-only 命中多个 quantity、alias 歧义等）：`1.0` +
   visible warning（source=`fallback`）。

第 5 步是常态而非异常：本项目主力数据是 EPS 信号（`Nm`、`rpm`、`A`、`deg`、
`V` 等），这些单位不在声学/振动 catalog 中，对它们 `dB re 1 <unit>` 本来就是
合理的相对 dB 约定。`generic` 不得使用 warning 配色或 `⚠` 标记——否则用户最
常见的使用场景变成常驻警告态，警告失去信息量。warning 只保留给第 6 步的真正
解析失败。

`prefer_channel_metadata=False` 只跳过第 2 步，不删除文件 metadata，也不改变
Manual View。

### 8.2 Source Tokens

| 内部 token | UI 文案 | 颜色语义 |
| --- | --- | --- |
| `manual` | `手动覆盖` | amber |
| `metadata` | `通道 metadata` | cyan/blue |
| `user` | `用户默认` | amber |
| `system` | `系统默认` | blue |
| `generic` | `通用默认` | neutral muted（与 system/user 同级，无警告） |
| `fallback` | `解析失败回退` | warning amber/red |

颜色不能是唯一信息；来源文字必须始终存在。

### 8.3 Catalog Change

保存 catalog 后：

- 当前所有 Auto View 在下一次显示/渲染时重新解析；
- 当前可见 Auto View 立即从 cache 重新渲染；
- Manual View 的数值、mode 和图不变；
- 不 dispatch compute worker，不清 compute cache；
- service revision 只用于 render-staleness 判断。

### 8.3.1 Reference Change × Manual Color Levels

effective reference 变化（Auto 解析变化或 Manual 手输）会把 heatmap 的整个
dB 矩阵平移 `delta = 20·log10(ref_old / ref_new)`（加速度 `1.0 → 1e-6` 即
+120 dB）。为避免用户已调好的手动色阶窗口瞬间错位、图面发黑/全白：

- 手动色阶窗口必须随同一 delta 平移：
  `[floor, ceiling] → [floor + delta, ceiling + delta]`；
- 自动色阶不需处理（下一次渲染重新推导即可）；
- 平移只改显示电平，绝不 clip 数据矩阵（2026-06-21 四轮色阶事故的红线）。

### 8.4 Pane And Overlay Semantics

- Manual 是 View-level：同一 View 的全部 panes/sources 使用同一个手动值。
- Auto 是 source-level：每个 `PaneState.sources` 独立解析。
- FFT overlay 中，reference identity 同时比较 value 与 unit；数值相同但单位不同仍是
  mixed reference。
- focused pane 的 Inspector 展示 focused pane 的解析结果。切换 pane 只更新展示，
  不把 focused pane 的派生值写进其他 pane。
- inactive section/project save 必须以 `AnalysisViewState.panes[*].sources` 为事实，
  不能使用当前 navigator selection 重算并覆盖它们。

## 9. Scientific Reference Input

### I1 — Representation

新增 `ScientificReferenceSpinBox`，保持 `QDoubleSpinBox` 的键盘、focus、signal 和
无 stepper 行为，但覆盖解析/显示：

- 接受 `1e-12`、`1E-9`、`0.000001`、`5e-8`；
- 显示使用 compact general/scientific notation，不固定补六位小数；
- 至少完整往返 `1e-12`、`1e-9`、`1e-6`、`2e-5`、`1.019716...e-7`；
- 内部保留 float，不把 pretty label 的 `20 µPa` 写回编辑器；
- `value()` / `setValue()` / `valueChanged` 与现有 call sites 兼容。

### I2 — Commit

- 用户按 Enter、移出焦点或完成编辑时才提交 mode 变化；输入到一半时不触发 Manual。
- 合法提交：保存最后有效值、切换 `manual`、更新 badge/source/label、仅 rerender。
- 非法提交：恢复最后有效文本，保持原 mode/value，并用字段错误状态 + tooltip
  说明“reference 必须是有限正数”；不弹阻塞 modal。

### I3 — Conversion

显示转换必须用已验证的正 reference，不得再通过 `max(reference, 1e-12)` 把用户值
静默改成另一个 reference。幅值 numerator 的 zero protection 与 denominator
reference validation 分开处理。

## 10. Inspector Compound Control

### 10.1 Structure

三个 Contextual 共用 `DbReferenceControl`：

```text
dB 参考:  [ 1e-6                         ][ tune ]
           ● 自动 · 系统默认 · acceleration / m/s²
```

Required object names:

- root: `dbReferenceControl`
- editor: `dbReferenceEditor`
- manage button: `dbReferenceManageButton`
- badge: `dbReferenceModeBadge`
- source line: `dbReferenceSourceLabel`

保留 `ctx.spin_db_ref`，使它继续指向 editor；新增
`ctx.db_reference_control` 指向 compound root，避免一次性破坏现有测试和信号 wiring。

### 10.2 Button And Badge

- 使用项目已有 icon family 的 `mdi.tune-vertical`，不引入新的 SVG 视觉语言。
- button 是正方形，rendered outer height 与相邻 editor 完全相等；宽度等于高度。
- editor 与 button 间距 6px；button 不抢占 editor 的最小可读宽度。
- Auto badge 是蓝底白字 `A`；Manual badge 是 amber 底白字 `M`。
- badge 约 16 logical px，位于 button 右下角并完全落在 compound bounding rect 内，
  不能被 parent/QSS clipping 切角。
- badge 是状态，不单独充当按钮；keyboard/tab 只进入 manage button。

### 10.3 Source Line

- 11px muted text，一行显示 `自动 · 系统默认 · acceleration / m/s²` 等事实。
- 窄 pane 可 elide，但 hover tooltip 必须给出完整内容。
- generic（单位不在 catalog）使用普通 muted dot +
  `自动 · 通用默认 · dB re 1 <unit>`，中性展示。
- fallback（解析失败）才使用 warning dot +
  `自动 · 解析失败回退 · <quantity/unit>`。

## 11. Defaults Manager Dialog

### 11.1 Entry And Scope

单击三个 manage button 中任意一个，打开同一个
`DbReferenceDefaultsDialog`。MainWindow/Inspector 共享一个 service/store；弹窗不是每个
Contextual 各自维护 catalog。

### 11.2 Required Layout

从上到下：

1. title `dB reference 默认值` + 简短说明 + close；
2. `当前 View` 行：`随通道自动选择` toggle、当前 effective reference/source；
3. `优先使用通道 metadata` 全局 toggle；
4. 可滚动 catalog 表：`物理量 | 单位/别名 | 0 dB reference | 来源 | 删除`；
5. footer：左侧 `添加默认值`、`恢复系统默认`；右侧 `取消`、primary `保存更改`。

HTML 里的 demo-only “模拟通道/计权/HDF” 控件不进入产品弹窗；`当前 View` toggle
承接 demo 中 Auto/Manual 的真实操作入口。

### 11.3 Edit Semantics

- 打开弹窗使用 working copy；`取消` / Esc / close 不写 QSettings、不改 View mode。
- 修改 built-in 后，保存为 user override，来源显示 `用户`。
- 未改动的 built-in 保持 `系统`。
- 删除 built-in 记录其 stable ID 到 `hidden_builtin_ids`；删除 custom 直接移除。
- `恢复系统默认` 只在 working copy 中清空 overrides/custom/hidden，恢复 factory table；
  不自动改变 metadata preference，直到用户点 `保存更改` 才落盘。
- 当前 View mode 和 catalog 一次原子提交；任一表格行非法时不关闭弹窗。
- 保存成功后所有打开的 compound controls 更新 mode/source/effective value。

### 11.4 Accessibility

- Tab 顺序：mode → metadata → table editors/actions → footer。
- Enter 在 editor 内提交单元格，不应误触整个弹窗保存；primary button 仅在显式 focus
  或平台标准 shortcut 下触发。
- Esc 取消；delete button 有包含物理量/单位的 accessible name。
- A/M、来源、错误都提供文字，不依赖颜色。

## 12. User Settings Schema

使用项目既有 `QSettings("MF4Analyzer", "DataAnalyzer")`，但 store 必须支持注入
临时 `QSettings` 供测试使用。

Keys:

```text
analysis/db_reference/catalog_v1
analysis/db_reference/prefer_channel_metadata
```

`catalog_v1` JSON：

```json
{
  "schema": 1,
  "overrides": [
    {
      "builtin_id": "acceleration.si",
      "label": "振动加速度",
      "unit": "m/s²",
      "aliases": ["m/s²", "m/s^2", "m/s2"],
      "reference": 0.000002
    }
  ],
  "custom": [
    {
      "id": "user.example",
      "quantity": "custom",
      "label": "自定义量",
      "unit": "unit",
      "aliases": ["unit"],
      "reference": 1.0
    }
  ],
  "hidden_builtin_ids": []
}
```

Rules:

- JSON 写入前完整校验，`QSettings.sync()`；保存失败不替换运行中 catalog。
- 未知 schema：回退 factory catalog，显示一次 non-blocking warning，不覆盖原值。
- malformed JSON/entry：同样安全回退并警告，不阻止应用启动。
- unknown fields 可忽略；unknown built-in IDs 不激活。
- `restore` 删除 `catalog_v1` key 或写入等价空 delta；factory constant 永不被修改。

## 13. State, Preset And Project Compatibility

### S1 — Partial Apply

`apply_params(d)` 继续是 partial-dict API：

- 只有 key 存在才改变对应 state；
- `db_reference` 单独出现时只设置 value，不隐式切换 mode；
- `db_reference_mode` 单独出现时切换 mode；切入 Auto 后立即解析 focused source；
- 缺少 `weighting`、`db_reference`、`db_reference_mode` 时全部保留当前状态。

### S2 — Preset Full Blob

- 新 preset 同时保存 mode + value。
- 旧 preset 若包含 `db_reference` 但没有 mode，迁移为 `manual`，因为旧版本的该值本身
  就是权威显示 reference。
- 旧 preset 连 `db_reference` 都没有时，不改变当前 mode/value。
- 缺少 `weighting` 仍不重置当前 A/None。

### S3 — AnalysisViewState Migration

`AnalysisViewState.to_dict()` nested `schema` 从 1 升到 2：

- schema 2 原样保存 `db_reference_mode`。
- schema 1 params 中存在 `db_reference` 但没有 mode：`from_dict()` 注入
  `db_reference_mode="manual"`。
- schema 1 不含 reference：保持 params 缺键，由 live control 当前状态处理。
- project 顶层 schema 不因 nested migration 被无理由升级；沿用现有 project reader。

### S4 — Batch Preset Migration

Batch preset params 应用同一 legacy request 规则：有 value 无 mode → Manual；新 Auto
preset 逐目标 source 解析。无需把用户 catalog 写入 preset JSON。

### S5 — Migration Consequence And Discovery Nudge

现有三个 Contextual 的 `get_params()` **无条件**输出 `db_reference`
（`contextual_fft.py:492/619`，另两个同构），因此**全部存量
View/preset/项目都会命中 value-without-mode 规则并迁移为 Manual**（多数是旧
默认 `1.0`）。这是有意的保守行为（G4）：Auto 实际只对新建 Analysis View 生
效，旧图的 dB 数值不因升级发生任何平移。实现者不得把这个后果当作迁移 bug
“修掉”。

为避免存量用户永远发现不了 Auto，接入现有情境 nudge 层
（`mf4_analyzer/ui/hints.py` 中 `surface="nudge"` 注册表 + predicates）：

- 新增 `nudge.db_ref_manual_default`：当前 View 为 `manual`、值等于旧默认
  `1.0`、且当前 source 能解析出非 `1.0` 的 catalog/metadata reference 时，
  提示可在管理弹窗切换「随通道自动选择」；
- 遵守 nudge 层现有门控/优先级/发现语义与 `≤18 全宽` 文案约束，不新增第二套
  机制；
- 迁移判定 key off「params 有 `db_reference` 且无 `db_reference_mode`」，
  不依赖 nested `schema` 数字（`from_dict()` 目前完全不读 schema 字段）。

## 14. Label Formatter Contract

所有 consumer 调用 `mf4_analyzer.db_reference` 的同一 formatter；禁止在 renderer、
canvas、batch 内继续拼接各自的 `Amplitude (dB)`。

### 14.1 Canonical Examples

| Case | Required label |
| --- | --- |
| acceleration, None, dB, `1e-6 m/s²` | `Amplitude (dB re 1×10⁻⁶ m/s²)` |
| acceleration, A, dB, `1e-6 m/s²` | `Amplitude (dBA re 1×10⁻⁶ m/s²)` |
| sound pressure, A, dB, `2e-5 Pa` | `Sound pressure (dBA re 20 µPa)` |
| mixed FFT, None | `Amplitude (dB · per-curve reference)` |
| mixed FFT, A | `Amplitude (dBA · per-curve reference)` |
| acceleration, A, Linear | `A-weighted amplitude (m/s²)` |
| generic（单位不在 catalog，如 `Nm`） | `Amplitude (dB re 1 Nm)`（无警告标记） |
| generic（通道单位为空） | `Amplitude (dB re 1)` |
| resolution failure fallback | `Amplitude (dB re 1 <unit>) ⚠` |

### 14.2 Token Rules

- `dBA` 仅当 `weighting == "A"` 且 output scale 是 logarithmic amplitude。
- Linear A-weighted 结果必须说明 `A-weighted`，不能写 `dBA`。
- `2e-5 Pa` pretty 为 `20 µPa`；其他小 reference pretty 为 `c×10ⁿ unit`。
- editor 使用 `1e-6`，axis 使用 `1×10⁻⁶`；两者是同一 float 的不同 formatter。
- generic 标签中的 `1 <unit>` 使用通道实际单位原文；单位为空时省略 unit
  token，写 `dB re 1`。`⚠` 只出现在 `fallback`（解析失败），绝不出现在
  `generic`。
- fallback warning 进入 axis/source note；不在数值本身后附不可解析字符。

## 15. Render Consumer Contracts

### C1 — FFT Direct / Cached / Re-entry

- 每个 entry 从自己的 `(fid, channel)` + View mode 解析 reference。
- dB 转换发生在 raw linear cached result 上；`amp_for_xlim` 仍保持 linear。
- all entries reference identity 相同：axis 使用 exact canonical label。
- mixed：axis 使用 `per-curve reference`；每条 legend/curve label 或 companion metadata
  显示自己的 `dB[A] re ...`。
- time preview 的线性 trace 不附 dB reference。
- `_fft_render_signature()` 包含 mode、per-source resolution identity 和 service revision；
  compute key 不变。

### C2 — FFT-vs-Time

- 每个 pane 根据自己的 single source 解析；传入 canvas 的是 validated effective value。
- colorbar、slice amplitude axis、readout/remark Z unit 使用同一 label context。
- dB/Linear、A/None 切换与当前 compute/cache边界一致。

### C3 — Order

- 保留 renderer 外预转换和 explicit levels 的现有契约。
- validated reference 直接传入 amplitude-to-dB，不做 silent clamp。
- colorbar、slice、readout/remark 使用统一 formatter。

### C4 — Copy / Export

- canvas grab/copy 自然携带可见 axis/colorbar/slice labels。
- 批处理 image 与交互式 canvas 使用相同 formatter。
- CSV/DataFrame 继续导出线性数值；不得因 Auto reference 改写数据列。

## 16. Cache And Performance Boundaries

| Item | Compute cache | Render signature / stale identity |
| --- | --- | --- |
| `weighting` | YES | YES |
| `db_reference` effective value | NO | YES |
| `db_reference_mode` | NO | YES |
| catalog revision | NO | YES for Auto |
| source quantity/unit/metadata reference | NO | YES for Auto |

- 修改 reference/catalog 不清 FFT/Order/FFT-time compute caches。
- 可见 chart 的更新必须走 cache-hit renderer；worker dispatch count 保持 0。
- catalog service 不扫描样本数组；只读 `FileData` metadata 和 state sources。
- 不把 derived per-pane resolutions 持久化成第二套 source state。

## 17. Visual Design Contract

### 17.1 HTML → Qt Translation

| HTML signature | Qt implementation |
| --- | --- |
| editor + 42px utility button | editor + square button；实际高度跟随 TraceLab sibling field，不硬编码 40px |
| blue A / amber M badge | 使用 TraceLab `#1769e0` primary 和现有 amber/warning token |
| porcelain/white cards | 使用 `Inspector` 当前 `#fafbfc` body + white params card |
| 7–12px web radii | field 7px、button 8px、inner group 8px、dialog 12px，复用当前 QSS rhythm |
| 880px modal | Qt dialog 目标宽约 800–880 logical px，并受 available screen geometry 限制 |
| browser table | Qt scrollable table/editor rows，white surface + `#dfe5ee` hairlines |

### 17.2 Scope And Object Styling

- QSS 必须 scope 到 objectName；不新增泛化 `QToolButton` / `QDialog` 规则。
- `DbReferenceDefaultsDialog` 使用当前 `ChartOptionsDialog` / `SheetSurface` 的视觉语言，
  不做独立 frameless web window。
- compound root 和 source line 保持 transparent，让 `fftParamsCard`、
  `fftTimeParamsCard`、`orderParamsCard` 的白色表面连续可见。
- button/icon/badge 不形成第二个主色块；页面唯一视觉强调仍是当前 active/control blue。

### 17.3 Required Rendered States

必须保存并检查以下 PyQt 截图：

1. FFT Auto + acceleration system reference；
2. FFT Manual + amber M；
3. FFT A-weighted dBA axis；
4. FFT mixed-reference overlay；
5. FFT-vs-Time dBA colorbar + slice；
6. Order dB colorbar + slice；
7. Defaults dialog factory state；
8. Defaults dialog edited/error state；
9. 960px app width / 288–320px Inspector narrow state。

Offscreen screenshot 证明 structure/geometry；macOS on-screen screenshot 才是最终字体、
颜色、圆角、badge clipping 和视觉层级真值。

## 18. Error And Empty States

| Scenario | Behavior |
| --- | --- |
| invalid editor value | revert last valid; inline error/tooltip; mode unchanged |
| invalid catalog row | mark cells; keep dialog open; no partial save |
| malformed QSettings JSON | factory catalog + one warning; preserve raw key |
| invalid HDF metadata | skip metadata; continue catalog resolution |
| unit not in catalog (generic) | reference `1.0`; neutral `通用默认` source; axis `dB re 1 <unit>`; no warning |
| ambiguous/failed resolution (fallback) | reference `1.0`; warning source/axis; no crash |
| source removed while View inactive | existing pane-source cleanup rules apply; no stale resolution object persisted |
| QSettings sync failure | retain old service catalog; show non-blocking warning |

## 19. Architecture Ownership

| Layer | Responsibility | Expected files |
| --- | --- | --- |
| Pure domain | catalog constants, normalize, validate, resolve, pretty/axis formatter | new `mf4_analyzer/db_reference.py` |
| User settings | QSettings delta schema, load/save/restore, revision | new `mf4_analyzer/ui/db_reference_settings.py` |
| Reusable controls | scientific editor, compound control, A/M/source presentation | new `mf4_analyzer/ui/widgets/db_reference.py` |
| Manager dialog | working copy, validation, atomic commit | new `mf4_analyzer/ui/db_reference_dialog.py` |
| Inspector contexts | shared compound row, get/apply/preset mode/value | `_helpers.py`, three `contextual_*` files |
| Source adapter | build `ChannelReferenceFacts` from `FileData` and pane sources | `window.py`, `_analysis_mixin.py` |
| Render consumers | per-source FFT; heatmap labels/readouts; render signatures | `_fft_mixin.py`, `_fft_time_mixin.py`, `_order_mixin.py`, `line_canvas.py`, `heatmap_canvas.py` |
| Persistence | nested AnalysisView migration + project/preset round-trip | `analysis_view_state.py`, `analysis_view_bridge.py`, preset paths |
| Batch | per-target Auto resolution and shared image labels | `batch.py`, `batch_preset_io.py` |
| Discoverability | footer hint、quickref、`nudge.db_ref_manual_default`、tooltip 文案（按 `/update-hints` 流程维护两个面） | `mf4_analyzer/ui/hints.py`, `mf4_analyzer/ui/quickref.py`, `_helpers.py` tooltip |
| Visual | scoped Qt style and rendered tour | `style.qss`, new `scripts/db_reference_ui_tour.py` |

## 20. Acceptance Matrix

| ID | Scenario | Required proof |
| --- | --- | --- |
| A1 | three Inspector rows | same compound control, button, badge, source line; correct row order |
| A2 | narrow pane | no row wrap/overflow; editor retains readable scientific text; badge not clipped |
| A3 | scientific input | `1e-12`, `1e-9`, `1e-6`, `2e-5` input/save/restore exactly |
| A4 | Auto unit selection | Pa, m/s², m/s, m, N, g resolve expected values and provenance |
| A5 | metadata preference | legal HDF metadata wins; preference off uses user/system; invalid metadata is skipped |
| A6 | catalog editing | add/edit/delete/cancel/save/restore and provenance all deterministic |
| A7 | Manual isolation | source/catalog changes do not change Manual View or dispatch compute |
| A8 | Auto propagation | catalog/source changes update visible Auto labels from cache |
| A9 | dBA | FFT/colorbar/slice/readout/batch image use dBA for A + log; Linear never says dBA |
| A10 | mixed FFT | axis says per-curve; every curve discloses own reference; no first-source leakage |
| A11 | split panes | each pane resolves its saved source; focused Inspector does not overwrite sibling |
| A12 | project/preset | new mode/value round-trip; schema-1 value becomes Manual; missing keys preserve state |
| A13 | cache boundary | reference/catalog changes produce zero worker calls; weighting changes compute key |
| A14 | export | interactive copy and batch image carry labels; CSV linear values unchanged |
| A15 | visual parity | HTML hierarchy + TraceLab tokens verified offscreen and macOS on-screen |
| A16 | reference change vs manual color levels | manual z-window shifts by `20·log10(ref_old/ref_new)`; no black/blank map; auto levels re-derive; matrix never clipped |
| A17 | discoverability | generic units (`Nm` 等) show neutral `通用默认`, never warning; hints/quickref cover A/M badge、手输切 Manual、管理按钮; `nudge.db_ref_manual_default` gates correctly; tooltip 不再只说“平移 dB 刻度” |

## 21. Definition Of Done

本功能只有在以下全部成立时完成：

- A1–A17 有自动测试或明确的 rendered evidence；
- pure resolver/formatter 只有一个生产实现，interactive 与 Batch 共用；
- 不再存在目标 render path 的裸 `Amplitude (dB)` hard-code；
- `db_reference`、mode、catalog revision 不进入 compute cache keys；
- 旧 preset/project migration 测试通过；
- QSettings 测试使用隔离 store，不污染开发者真实设置；
- 三个 Inspector、manager dialog、mixed FFT、dBA heatmap 的 macOS 截图通过人工检查；
- `git diff --check` 和计划中的 focused regression suite 通过；
- 文档和 UI 不把 compatibility defaults 冒充为已验证 Artemis 官方表。

## 22. Remaining Evidence Note

Artemis 官方默认设置页/客户手册表目前仍是 `UNKNOWN`。这不阻塞本 spec 的实施，
因为：

1. 文件内合法 HEAD metadata 优先；
2. built-in 被诚实命名为 compatibility defaults；
3. 用户可编辑/恢复 catalog；
4. resolver 和持久化不依赖厂商名称。

但在没有新证据前，任何 release note、tooltip 或帮助页都不得写“Artemis 官方默认”。
