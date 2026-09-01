# WWT WinWert 原生排版导入 Spec

- 日期：2026-08-28
- 状态：原规格已实施（`1cb54ca..676e96a3`）；2026-08-28 正确性加固补充合同见 §17
- 基线：`main@8445d909`（原设计基线，不随 follow-up 改写）
- 配套计划：
  [`2026-08-28-wwt-winwert-layout-import-implementation.md`](../plans/2026-08-28-wwt-winwert-layout-import-implementation.md)
- 正确性加固计划：
  [`2026-08-28-wwt-import-correctness-followup-plan.md`](../plans/2026-08-28-wwt-import-correctness-followup-plan.md)
- 第二轮加固（2026-08-29 保真回归与投影边界，已实施，见配套规格）：
  [`2026-08-29-wwt-import-fidelity-and-projection-hardening-spec.md`](2026-08-29-wwt-import-fidelity-and-projection-hardening-spec.md)
- 后续产品合同（多窗口独立 Board、毫米非等距换算、时域 24 View；不回溯改写本文）：
  [`2026-08-29-wwt-multi-board-layout-fit-and-24-views-spec.md`](2026-08-29-wwt-multi-board-layout-fit-and-24-views-spec.md)
- 现行 WWT 最小首帧显示合同（取代本文的 native tick/viewport/物理排版显示要求；本文历史结论不回溯改写）：
  [`2026-09-01-wwt-minimal-initial-view-contract-simplification-plan.md`](../plans/2026-09-01-wwt-minimal-initial-view-contract-simplification-plan.md)
- 产品范围：TraceLab WWT 导入、时域 View、UltraView、项目保存与恢复
- 既有相关规格：
  [`2026-08-11-wwt-export-dual-compat-spec.md`](2026-08-11-wwt-export-dual-compat-spec.md)

> §2 的三份客户样例仍是原设计的外部字面证据，不是仓库夹具。`.gitignore` 忽略
> `testdoc/`。原实施波次之后的正确性合同（加载层 record store、claimed binding、
> 诊断分级、tick 预检）写在 §17，不回溯改写 §2–§16 的历史证据，也不假装原实现
> 已经满足这些加固项。

## 1. 一句话结论

> 打开带 `DatenFenste2` 的 WinWert `.wwt` 后，TraceLab 在数据加载成功后询问是否按
> WinWert 排版生成时域 View；确认后把每个可解码显示块翻译为一个可编辑、可持久化的
> 原生时域 View，并把全部新 View 加入 UltraView。曲线、逐曲线 X/Y 关系、计算通道、
> 轴范围、标签、刻度、网格、颜色、线型和线宽保持 WinWert 图形语义；窗口皮肤、字体
> 抗锯齿和像素间距继续采用 TraceLab / UltraView 自身视觉系统。

这不是截图导入，也不是一套 WWT 专用画布。WWT 显示状态被翻译为 TraceLab 现有 View、
pyqtgraph 曲线和 UltraView 引用，用户仍能缩放、游标、改色、保存项目和继续编辑。

## 2. 已确认的真实文件证据

### 2.1 用户指定样例

| 文件 | 已确认显示语义 |
| --- | --- |
| `testdoc/WWT/SFNS_10_P779_0007.wwt` | 1 个显示块；X=`Rack Travel [mm]`，范围 `-100..100`、主刻度 `10`；Y=`Rack Force [N]`，范围 `-1500..1500`、主刻度 `500`、网格 `100`、深蓝色 |
| `testdoc/WWT/YP_SS_P779_0007.wwt` | 1 个显示块；X=`Steering Angle [°]`，范围 `-720..720`、主刻度 `120`、网格 `60`；Y=`Druckstückspiel [mm]`，范围 `0..0.2`、主刻度 `0.05`、网格 `0.01`；红色 `Tol_oben` 评价线与深蓝测量曲线同时可见 |
| `testdoc/WWT/UCAN-b6_P779_0007.wwt` | 21 条记录、4 条 `Pars` 计算通道、7 个连续 `DatenFenste2` 显示块、6 个独立窗口位置；第 7 块与第 6 块位置完全重叠 |

现有 `mf4_analyzer/io/wwt_display.py` 已验证曲线表的范围、X 引用、可见性、主刻度、网格、
标签和颜色字段，但 `find_trailer()` / `read_curve_table()` 默认只处理第一个显示块；现有
`mf4_analyzer/io/wwt_format.py` 在正文解析结束时停止于首个 `DatenFenste`，并把 `Pars`、
短评价曲线和样本数不等于当前 `Zeit` 的独立 XY 记录放入 `skipped_channels`。本功能要补齐
这些读取能力，不推翻现有 WWT 正文缩放与分组规则。

### 2.2 UCAN 的 21 条记录与新建通道

UCAN 样例的文件内记录序号是显示块曲线表和 `Pars` 公式共同使用的稳定身份。关键记录为：

| 记录 | 类型 | 名称 | 点数/角色 |
| ---: | --- | --- | --- |
| 0 | `Zeit` | `Time` | 1988，评价曲线组 |
| 1–3 | `Real` | `Diff.Limit A`、`Diff.Limit B`、`X_Wheel input torque` | 1988，评价/限值 XY 数据 |
| 4–5 | `Pars` | `Diff.Moment A`、`Diff.Moment B` | 声明点数 50000，但真实输出轴由引用记录决定 |
| 6 | `Zeit` | `Time` | 15274，主测量组 |
| 7–10 | 数值记录 | `Wheel input torque`、`Rack Force`、`Battary Current`、`Wheel input angle` | 主测量通道 |
| 11–12 | `Pars` | `Spurstangenkraft`、`Motor torque A+B` | 主测量计算通道 |
| 13–16 | `Floa` | `Sensor torque A`、`Motor torque A`、`Sensor torque B`、`Motor torque B` | 主测量通道 |
| 17–20 | `Real` | symmetry / hysteresis 的 X/Y 记录 | 72 或 151 点的独立 XY 曲线，不得伪造时间轴 |

四条公式必须按以下原文读取和验证：

```text
record 4  Diff.Moment A      = -(k7-(-k13))
record 5  Diff.Moment B      = -(k7-(-k15))
record 11 Spurstangenkraft   = abs(k8)
record 12 Motor torque A+B   = k14+k16
```

`kN` 中的 `N` 是 0 基 WWT 记录序号，不是通道显示名称，也不是 DataFrame 列序号。
`Pars` 头部的声明点数不是输出长度真值：record 4/5 声明 50000，而其引用记录均为
15274 点。只有引用图证明所有叶子记录属于同一采集轴且长度完全一致时，公式才可物化。

### 2.3 UCAN 的多窗口几何

显示块头部 `+13` 的 little-endian `double` 是线宽；本样例 7 块均为 `0.2 mm`。
`+31` 起的四个 little-endian `int16` 是窗口矩形边，按以下唯一换算得到截图中的毫米值：

```text
x_mm      = left / 20
y_mm      = -bottom / 20
width_mm  = (right - left) / 20
height_mm = (top - bottom) / 20
```

| 显示块 | X mm | Y mm | W mm | H mm | UltraView 决策 |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 25 | 65 | 100 | 60 | 放置 |
| 2 | 41 | 138.2 | 90 | 60 | 放置 |
| 3 | 147.5 | 62.5 | 50 | 60 | 放置 |
| 4 | 215.5 | 62.5 | 50 | 60 | 放置 |
| 5 | 147.5 | 138 | 50 | 60 | 放置 |
| 6 | 214.5 | 138 | 50 | 60 | 放置 |
| 7 | 214.5 | 138 | 50 | 60 | 与 6 完全重叠；普通 View 保留，UltraView 放入未放置区 |

这组字面值是 parser、布局归一化和 UltraView 集成测试的固定外部证据；不得用“读到 7 块”
或“布局看起来接近”代替逐项断言。

## 3. 范围

### 3.1 要做

1. 一次解析完整 WWT 正文、全部 `Pars` 记录和全部结构合法的 `DatenFenste2` 显示块。
2. 安全计算样例已证明的 `Pars` 语法，并把成功结果作为普通可选通道加入正确逻辑源。
3. 保留不属于时域组的评价线和独立 XY 记录，不给它们发明采样率或时间轴。
4. 支持同一 View 中每条曲线独立选择 X 数据；YP 的评价线与测量线必须同时正确显示。
5. 把每个显示块翻译为一个普通时域 `ViewState`，恢复曲线顺序、颜色、轴范围、标签、
   主刻度、网格间隔、线型和线宽。
6. 加载成功后弹一次确认框；确认即创建 View 并绘制第一个，拒绝只加载数据。
7. 一文件多显示块时创建多个普通 View；受 `ui/view_state.py:MAX_VIEWS == 12` 限制。
8. 把所有实际创建的 View 加入当前 UltraView Board；6 个独立 UCAN 位置按相对几何放置，
   第 7 个完全重叠窗口进入未放置区。
9. `.tlproj` 保存/恢复、文件关闭、通道删除和 degraded restore 正确处理新引用。
10. 同步用户可见帮助入口 `ui/hints.py` 与 `ui/quickref.py`。

### 3.2 明确不做

- 不逐像素复刻 WinWert 窗口边框、白色背景、字体、抗锯齿、页脚和旧式控件皮肤。
- 不嵌入、启动或自动化 WinWert，也不依赖本机安装 WinWert。
- 不导入截图或不可交互的 raster 作为曲线替代品。
- 不用 Python `eval`、`exec`、NumExpr 字符串执行或任意函数调用解释 `Pars`。
- 不为独立 XY 记录生成假 `Time`、假采样率或索引秒数。
- 不用 `min(len(x), len(y))`、插值、重采样或静默截短修补不兼容 X/Y。
- 不承诺解释尚无样本证据的 `Pars` 函数、WinWert LOG 轴、非 1 Factor、Move 或非 Line
  表示方式；遇到这些值按 §11 可观察降级。
- 不增加 WWT 专用 Canvas、UltraView 卡片类型或第二套项目状态。
- 不改 WWT 导出格式和既有 WinWert 双路导出规格。

## 4. 产品与架构决策

### D1 — “相同”是图形语义相同，不是像素相同

验收对象是 View 数量、可见曲线、逐曲线 X/Y、曲线顺序、轴范围/标签/刻度、网格、颜色、
Line 表示和物理线宽。TraceLab 继续使用自身背景、字体、布局 chrome、抗锯齿和交互反馈。

### D2 — 读取结果是一个 WWT 文档，不是互不相干的 groups

新增 Qt 无关的 `WwtDocument` 保存记录目录、时域 groups、公式依赖、显示窗口和诊断。
`DataLoader.load_wwt()` 的兼容返回仍是 groups；主窗口使用新增的文档入口取得同一次解析的
groups + display state，禁止为了生成 View 再读一遍整个文件。

### D3 — 公式计算属于 IO/数据层，窗口翻译属于 UI-neutral View 层

- `mf4_analyzer/io/` 负责字节解析、公式安全求值、记录到采集轴的归属和成功计算通道物化；
- `mf4_analyzer/ui/wwt_view_import.py` 只把已注册 fid/通道和 WWT 显示 DTO 翻译为 View 提案；
- `WwtImportCoordinator` 负责确认框和 View/UltraView 提交事务；
- `window.py` 只初始化协调器，并在既有 `_build_time_plot_data` seam 薄委托通用 binding helper；
  不在其中新增 WWT 算法或另一簇跨 mixin mutable state。

### D4 — 逐曲线 X 是通用时域绑定，不是 WWT renderer 特判

`ViewState` 增加可序列化的 `curve_bindings`。每条绑定携带 Y 数据引用、X 数据引用、轴槽和
展示配置。普通 DataFrame 通道使用复合 `(fid, raw_channel_name)`；独立 WWT 记录使用
`(owner_fid, record_index)`，运行时从该 WWT source metadata 中的只读 record store 解析。

Canvas 仍接收每条曲线自己的 `x_values` / `y_values` 行。Canvas 不导入
`mf4_analyzer.io.wwt_*`，也不判断文件扩展名。

### D5 — 成功计算通道是普通通道，独立 XY 记录不是假时域源

公式输出只有在依赖轴和长度明确时才加入相应 DataFrame/group，进入 Navigator、Batch 和
通道选择。独立评价/XY 记录留在 WWT record store，由曲线绑定引用；它们不生成额外
`FileData`，因而不会触发 `FileData` 的默认 1000 Hz 假时间轴。

### D6 — `visible` 决定画线，`selected` 决定显式 Y 轴

- `visible != 0` 的显示表行进入曲线绑定；
- `selected != 0` 且 visible 的行成为显式 Y 轴 owner；
- visible 但未 selected 的评价线优先加入单位、范围、主刻度、网格均相同的已选轴槽；
- 无完全匹配轴槽时创建隐藏标签的独立轴槽并记录 warning，不把它强塞进错误量程。

这条规则必须固定 YP：未 selected 的红色 `Tol_oben` 与 selected 的
`Druckstückspiel` 共用 `0..0.2 mm` 轴。

### D7 — 所有结构合法的显示块都成为普通 View

UCAN 的 7 块全部创建，不因第 7 块被原软件窗口遮住而丢弃。普通 View 是数据语义清单，
不继承桌面遮挡。UltraView 才投影窗口位置：完全重叠的后出现窗口进入未放置区，避免
生成一张不可发现的被覆盖卡片。

### D8 — 数据先成功加载，排版选择不回滚数据

确认框只控制 View/UltraView 生成：

- “按 WinWert 排版并绘图”是默认按钮；
- “仅加载数据”保留已加载原始通道和成功计算通道；
- 关闭对话框等同“仅加载数据”；
- 项目恢复期间不弹框、不自动再生成 View，因为 `.tlproj` 已保存 View 真值。

### D9 — View cap 和 UltraView cap 都必须显式

初始、语义上未修改的空白时域 View可复用；否则只追加。可创建数为：

```text
available = MAX_VIEWS - existing_views + reusable_blank_count
```

若显示块数大于 available，对话框写明“检测到 N 个，可创建 M 个”；确认后只创建前 M 个，
并给出 warning toast。不得静默截断。UltraView membership cap 是 200、placed cap 是 24；
本样例不会触顶，但批量 API仍返回明确 warning。

### D10 — 一次事务、一次可见绘制、一次 UltraView 投影刷新

生成过程先构造全部 `ViewState`，再通过 ViewManager 批量提交，一次 emit；激活第一个新 View
并只绘制它。其余 View 不通过 UI 轮流激活。UltraView 批量加入后一次 mark-dirty/history/
refresh；预览沿用现有异步捕获，未访问的卡片可显示“待同步”，不得为生成预览来回切 View。

## 5. 数据契约

### 5.1 中立 DTO

建议的 public shapes：

```python
@dataclass(frozen=True)
class WwtRecord:
    index: int
    tag: str
    declared_n: int
    name: str
    unit: str
    scale_a: float
    offset_c: float
    axis_record: int | None
    values: np.ndarray | None
    formula: str | None

@dataclass(frozen=True)
class WwtWindowRectMm:
    x: float
    y: float
    width: float
    height: float

@dataclass(frozen=True)
class WwtCurveDisplay:
    record_index: int
    x_record_index: int
    selected: bool
    visible: bool
    label: str
    lo: float
    hi: float
    tick_interval: float
    grid_interval: float
    color_rgb: tuple[int, int, int]

@dataclass(frozen=True)
class WwtDisplayWindow:
    index: int
    rect_mm: WwtWindowRectMm
    line_width_mm: float
    curves: tuple[WwtCurveDisplay, ...]

@dataclass(frozen=True)
class WwtDocument:
    path: Path
    version: str
    records: tuple[WwtRecord, ...]
    groups: tuple[dict, ...]
    windows: tuple[WwtDisplayWindow, ...]
    diagnostics: tuple[str, ...]
```

实际实现可把 numpy array 设为 read-only view，但不得在 View/project JSON 中复制数组。
`WwtDocument` 在当前加载事务内共享；`FileData.source_metadata` 只保存同一只读 record store
引用及必要索引，不为每个 logical source 深复制数据。

### 5.2 公式语法与安全

第一阶段只接受 Python 表达式 AST 的以下节点：

```text
Expression, BinOp(Add/Sub/Mult/Div), UnaryOp(UAdd/USub),
Call(Name("abs"), exactly one positional argument), Name("k" + digits),
Constant(int|float), Load
```

其他节点，包括 Attribute、Subscript、Lambda、comprehension、keyword argument、其他函数、
字符串和布尔值，一律产生 `unsupported_formula`。解析和求值禁止调用 `eval` / `exec`。

依赖求值规则：

1. 先解析引用图，拒绝未知记录和环；
2. 递归物化被引用 `Pars`；
3. 所有叶子数组必须一维、长度完全相同，并属于同一 `Zeit` acquisition cohort；
4. 结果必须一维且长度保持；不允许 broadcast 产生二维数组；
5. 除零等 numpy 非有限值保留并产生 warning；结果没有任何有限值则失败；
6. 成功通道 metadata 保存 `record_index`、`formula`、`derived=True` 和引用记录序号。

### 5.3 曲线数据引用

```python
@dataclass(frozen=True)
class TimeDataRef:
    kind: Literal["channel", "wwt_record"]
    fid: str
    channel: str | None = None
    record_index: int | None = None

@dataclass(frozen=True)
class TimeCurveBinding:
    binding_id: str
    y_ref: TimeDataRef
    x_ref: TimeDataRef
    display_name: str
    unit: str
    color: str
    axis_id: str
    y_range: tuple[float, float]
    y_tick_interval: float | None
    y_grid_interval: float | None
    line_width_mm: float
    line_style: str
```

约束：

- `kind="channel"` 必须同时有 fid/channel，record_index 为 None；
- `kind="wwt_record"` 必须同时有 fid/record_index，channel 为 None；
- `binding_id` 由 view window index + display row record index 构成，不用显示名做身份；
- resolver 失败返回结构化 `TimePlotIssue`，不返回猜测数组；
- project restore 用 fid_map 重写两端 fid；任一 owner 缺失则丢弃绑定并进入 degraded warning。

## 6. 显示块解析契约

1. `find_trailers(data)` 返回所有结构合法 marker 的 offset，保持文件顺序。
2. 每块最小合法长度为 `CURVE_BASE + declared_record_count * CURVE_STRIDE`；曲线表越过下一个
   marker 或 EOF 时该块损坏，但不使正文 groups 加载失败。
3. 记录数上限继续为 4096；非法范围产生诊断。
4. `global_x` 只作 fallback；每条曲线 `x_curve` 非零时优先使用行内引用。
5. X 轴展示范围、标签、主刻度、网格和颜色来自 curve row 0；不得用数据 min/max 覆盖。
6. 行 `record_index >= len(records)` 为无效引用；跳过该曲线并诊断。
7. `lo/hi` 必须有限且 `hi > lo`；否则该轴退回 TraceLab auto-range 并诊断。
8. RGB 按已验证的 WinWert sRGB 字节转换为 `#rrggbb`。
9. 本阶段 Line 是唯一有证据的 representation；样例均生成 `line_style="line"`。未知代码不
   猜映射，降级为 TraceLab Line 并显示一次汇总 warning。
10. LOG 勾选、Factor != 1、Move != 0 若出现则保留 raw facts、显示 unsupported warning；不得
    把它们当作默认值静默忽略。

## 7. WWT 到 View 的翻译

### 7.1 注册映射

每个 materialized group 的 `channel_metadata[channel]["record_index"]` 是唯一映射入口。
注册 FileData 后构建：

```text
record_index -> (fid, raw_channel_name)
```

同名通道消歧继续使用已有 `[record_index]` 后缀；翻译器从 metadata 找到实际列名，不按 label
反查。未物化的独立记录由该物理 WWT 的第一个成功注册 fid 作为 `owner_fid`。

### 7.2 ViewState

每个显示块生成：

- `name = "WinWert {1-based index} · {X axis label without unit}"`；重名仍靠序号区分；
- `attached_file_ids` = 当前物理 WWT 的全部 logical fids，保持注册顺序；
- `checked` = 可见且已物化为普通通道的 Y 复合键；
- `colors` = 对应普通 checked 曲线颜色；
- `plot_mode = "overlay"`，因为 WinWert 数据窗口把多曲线/多 Y 轴画在同一 frame；
- `xlim` = X 轴 row 0 的合法范围；
- `ylims` = 每个轴 owner 的明确范围，使用现有复合 JSON key；
- `axis_opts["x_axis"]` 保留主 X 标签/单位供 Inspector 展示，但逐曲线实际 X 来自 binding；
- `axis_opts["native_ticks"]` 保存 X/Y 主刻度与网格间隔；
- `curve_bindings` = 所有 visible rows 的有序绑定，包括未 materialized 的评价线/XY 记录。

### 7.3 数据范围与筛选

WinWert 原生 XY View 的显示 X 不一定是 acquisition time。右侧“时间范围”仍代表采集时间，
只对能证明 acquisition cohort 的普通/计算通道应用。无时间语义的独立 XY 记录不参与时间
范围 mask；它们按完整 X/Y 显示，并在诊断详情标记 `native_xy_full_range`。禁止用 record index
假装时间来裁剪它们。

## 8. 轴、刻度、网格与线宽

### 8.1 初始范围

View 第一次绘制必须使用显示块给出的 X/Y 范围，而不是数据 auto-range。后续用户缩放、Home、
项目保存/恢复沿用现有 View range contract。恢复路径继续遵守：

```text
restore_visible_xlim(flush=False)
→ restore_visible_ylims(...)
→ settle_view_restore()
```

### 8.2 固定主刻度与无标签网格

WinWert `ticks > 0` 表示有标签主刻度间隔，`grid > 0` 表示网格间隔。native tick mode 生成：

- 主 level：`ceil(lo/tick)*tick ... hi`，带格式化标签；
- 网格 level：`ceil(lo/grid)*grid ... hi`，排除主 level，标签为空字符串；
- `ticks == 0` 或 grid == 0 的一侧交给现有 adaptive policy；
- 单轴最多生成 2000 条网格事实；超过即降级 adaptive 并 warning，防止绘制风暴。

不得用 `AxisItem.setTickSpacing(major, minor)`，因为现有回归已经证明它会给 minor level 也画
标签。使用显式 `setTicks([major, unlabeled_grid])` 或同等只标主 level 的 owner helper。

用户在 Inspector/ChartCard 主动修改刻度密度后，该 View 清除 `native_ticks`，回到 TraceLab
自适应刻度；该显式用户意图随项目保存。

### 8.3 线宽

项目中保存原始 `line_width_mm`。屏幕 pen 宽使用当前 widget logical DPI 换算：

```text
width_px = max(1.0, line_width_mm * logical_dpi / 25.4)
```

UCAN 的 `0.2 mm` 在 96 logical DPI 下为 `0.7559 px`，按最小可见值渲染为 `1.0 px`。
不得把 `0.2` 直接当 0.2 px，也不得全局改变非 WWT 曲线的 1.5 px 默认值。

## 9. 打开与确认事务

### 9.1 触发条件

以下入口统一经 `_open_paths()` / `_load_one()`，因此行为必须一致：文件对话框、拖放、
Acquisition Cockpit 的 `load_file(path)`。只有同时满足以下条件才弹框：

- 当前扩展名是 `.wwt`；
- 数据 groups 已成功注册；
- 至少有 1 个结构合法、含可解析 visible curve 的显示块；
- 当前不是 `_restoring_project`。

### 9.2 文案

单个 UCAN 样例的正文固定为：

```text
检测到 7 个 WinWert 数据窗口和 4 个可用计算通道。
可按原排版生成 7 个时域 View，并同步加入 UltraView。
第 7 个窗口与第 6 个位置重叠，将放入 UltraView 未放置区。
```

按钮：

- 默认 AcceptRole：`按 WinWert 排版并绘图`
- RejectRole：`仅加载数据`

有 unsupported/损坏项或 View cap 截断时，在 informative text 中追加准确计数，不增加第二个
确认框。

### 9.3 提交顺序

1. 捕获当前焦点 View，防止未提交 UI 状态丢失；
2. 纯函数构造全部 proposal；
3. 确认并计算 cap；
4. 复用至多一个 untouched blank View，批量追加其余 ViewState；
5. 一次发出 `views_changed`，设置第一个新 View 为 active；
6. 投影 Inspector/Navigator，绘制第一个 View 一次；
7. 把所有实际创建的 stable `view_id` 批量加入 UltraView；
8. 一次 refresh；显示创建/截断/降级汇总 toast。

任一步在 View commit 前失败，不产生半套 View；数据仍保留。View 已提交而 UltraView 放置部分
失败时，View 不回滚，失败引用进未放置区或产生 warning。

## 10. UltraView 排版

### 10.1 几何归一化

对不完全重叠的有效 rect：

1. 用 `left=min(x)`、`top=min(y-height)` 平移到原点；
2. 使用同一个 scale 把总宽映射到 `GRID_COLUMNS`，不分别拉伸 X/Y；
3. 对每条边取最近 micro-grid 坐标，再由量化后的两边相减得到 span，避免独立 round 宽高
   累积缝隙；
4. 应用现有 `GRID_MIN_*` / `GRID_MAX_*` 与 safety bounds；
5. 保留输入显示块顺序作为 z/order 和 Library 顺序。

UCAN 的 1–6 号必须得到 6 个非碰撞 `FreeGridPlacement`，并保持：1 号约为 3–6 号宽度的
2 倍、上排 1/3/4、下排 2/5/6。使用 `GRID_COLUMNS == 24` 的当前 schema-5 micro-grid，
字面结果必须为：

```text
1 → GridRect(0,  0, 10, 6)
2 → GridRect(2,  8,  9, 6)
3 → GridRect(12, 0,  5, 6)
4 → GridRect(19, 0,  5, 6)
5 → GridRect(12, 8,  5, 6)
6 → GridRect(19, 8,  5, 6)
7 → unplaced
```

测试断言这些 `GridRect` 字面值，而不是只断言无碰撞。

### 10.2 重叠处理

若两个原始毫米 rect 的四边在 `1e-6 mm` 内完全相同：

- 先出现的 ref 正常放置；
- 后出现的 ref 加入 `board.unplaced`；
- 不自动错位、缩小或覆盖已有卡片；
- toast 汇总 `1 个重叠窗口已放入未放置区`。

部分相交但不完全相同的 rect 先按原始几何量化；若量化后发生非法碰撞，使用现有 placement
legalizer，把后出现项放入未放置区并 warning，不重排前面已成功卡片。

### 10.3 批量 mutation seam

UltraView 增加一次性 `add_time_views_from_native_layout(...)`；内部在副本/plan 上验证全部 refs 和
rect，再通过 WorkspaceController 的单一 mutation funnel 提交。禁止 import coordinator 连续调用
私有 `_apply_add_ref()` N 次造成 N 次 history/refresh。

## 11. 错误与降级

| 条件 | 数据 | View | 用户可见结果 |
| --- | --- | --- | --- |
| 无显示块 | 正常加载 | 不生成 | 沿用现有 WWT 成功提示，不弹排版框 |
| 某显示块截断/越界 | 正常加载 | 其余合法块生成 | warning 汇总块号和原因 |
| 曲线引用未知 record | 正常加载 | 跳过该曲线；空窗口不生成 | warning，不能画零线 |
| 公式语法不支持 | 原始通道加载；公式不物化 | 依赖曲线 placeholder/跳过 | `unsupported_formula`，显示公式名 |
| 公式环/缺失引用/轴不一致 | 原始通道加载 | 依赖曲线不画 | 对应结构化错误码 |
| X/Y 长度不等 | 正常加载 | 该曲线不画 | `unaligned`，显示两端长度 |
| 非默认 LOG/Factor/Move | 正常加载 | 其余支持语义生成 | unsupported warning；不假装完全匹配 |
| View cap 不足 | 正常加载 | 前 M 块生成 | 对话框预告 + toast 实际 N/M |
| UltraView collision/cap | 正常加载 | 普通 View 全保留 | 后出现 refs 进未放置区或 warning |

所有 recoverable fallback 必须存在于 returned diagnostics、toast 或 View plot issue 中。未知
`ImportError`、Qt programming error 和非预期异常不得被 `except Exception: pass` 降级。

## 12. 生命周期与项目持久化

1. `ViewState.to_dict/from_dict` round-trip `curve_bindings` 和 native axis facts；旧项目缺字段时为空。
2. 当前 project schema 按实现时基线决定是否 bump；若 `ViewState` 是向后兼容可选字段且现有
   schema 允许透传，可不 bump，但必须用旧 fixture 证明。若 loader 丢未知字段，则 bump 一次并
   保留旧 schema 读取。
3. `project_io.remap_view_fids()` 同时 remap binding 的 X/Y owner fid。
4. `collect_dropped_time_refs()` 和 `analysis_source_scope.collect_source_uses()` 索引 binding 两端，
   因而关闭 owner 前确认框不会漏掉隐藏评价曲线引用。
5. `_filter_time_view_state_for_removed_fids/channels()` 对称移除 binding；没有可绘曲线的 View
   保留为空 View，不自动删除用户的 tab。
6. UltraView 继续只保存 stable `UltraViewRef("time", view_id)`；不复制 WWT record arrays。
7. 项目恢复先重新加载 WWT/计算通道/record store，再 remap View；不弹 WinWert 排版确认框。
8. View 名、颜色、原生范围、未放置第 7 卡和 UltraView free-grid rect 保存/恢复一致。

## 13. 性能与线程

- 单个 WWT 字节只读一次；显示块解析复用同一 bytes。
- `Pars` 表达式只解析一次；按 record index memoize，环检测使用 visiting set。
- numpy 运算保持向量化；不逐样本 Python loop。
- UI 仍在现有同步加载事务内登记数据；确认框只在解析完成后出现。
- 不为生成 7 个 View 轮流 plot；只有 active View 首次绘制。
- pyqtgraph / QPen / QWidget 只在 GUI thread 创建和修改。
- 不把 numpy arrays、Qt objects、diagnostics 或 preview cache 写入项目 JSON。

## 14. 验收矩阵

### 14.1 IO 与公式

- SFNS、YP、UCAN 三文件均保持现有物理值/单位断言。
- UCAN：`len(records)==21`、`len(windows)==7`、公式原文和四个 record index 逐项一致。
- UCAN 四个公式输出长度均为 15274，数值分别与直接 numpy 表达式逐点相等。
- record 4/5 的 50000 声明值只保留为 metadata，不导致 padding/truncation。
- unsupported AST、未知 `kN`、cycle、跨 cohort、长度不等都有独立错误码测试。
- 无 `eval` / `exec` 字面调用的静态 guard。

### 14.2 显示与 View 提案

- SFNS proposal 的 X/Y/范围/刻度/网格/颜色与 §2.1 字面值一致。
- YP proposal 同时包含红色 `Tol_oben` 和深蓝 `Druckstückspiel`，且两条各用自己的 X ref。
- UCAN 的 7 个 proposal 顺序稳定，窗口几何与 §2.3 七行完全一致。
- visible/selected 轴槽规则固定 YP 和 UCAN window 1。
- 关闭 owner fid、删除计算通道和项目缺失文件时 binding 对称清理/降级。

### 14.3 UI 与 UltraView

- 文件对话框、drop 和 `load_file()` 走同一提示路径；synthetic Qt drag event 保持
  `QMimeData` 强引用直至 event 销毁。
- Accept 创建并绘制；Reject 只加载；project restore 不弹框。
- untouched blank View 复用，non-empty View 不覆盖，12 View cap 文案/实际数一致。
- UCAN 创建 7 个普通 View；UltraView 6 placed + 第 7 unplaced；一次 history/refresh。
- 项目 save/reopen 后 7 个 View、逐曲线 X、范围、颜色和 UltraView 位置一致。
- Qt UI 测试使用 `tests/ui/conftest.py` 的 QSettings 隔离；任何独立 probe 也必须使用临时 INI
  或精确恢复真实 key。

### 14.4 渲染证据

确定性 offscreen artifact 比较以下事实，不做 WinWert 像素 diff：

- 曲线数、每条曲线首尾/极值或 hash；
- X/Y visible range；
- major tick 和 unlabeled grid 的数值位置；
- RGB、line style、logical line width；
- UCAN UltraView card rect 和 unplaced membership。

另做一次真实前台运行检查 SFNS、YP、UCAN，确认运行 widget path 和可见几何。offscreen 结果不能
替代 Windows frozen 或真实前台检查；未运行的 gate 在交付中标记 `UNVERIFIED`。

## 15. 文档与发现性

- `ui/hints.py` 增加一次性发现提示：WWT 可按 WinWert 排版生成 View/UltraView；
- `ui/quickref.py` 的 WWT 导入说明从“支持打开”扩展为“可恢复原生窗口排版与计算通道”；
- 帮助文案不宣称像素级复刻，也不宣称支持所有 WinWert 公式/LOG/Factor/Move；
- 现有工作树已对 `hints.py`、`quickref.py`、`window.py` 有用户未提交修改，实施者必须在这些
  修改上做最小增量合并，不得 checkout/revert/覆盖。

## 16. 完成定义

同时满足以下条件才可宣称完成：

1. 三份用户指定真实 WWT 通过字面契约测试；
2. UCAN 4 个公式真实物化，21 records / 7 windows / 6 placed + 1 unplaced 全部成立；
3. Accept/Reject/project restore/View cap/错误降级都有测试；
4. 普通时域、项目恢复、UltraView、import boundary、state ownership focused gates 全绿；
5. `git diff --check` 通过，spec/plan/hints/quickref 与运行行为一致；
6. full suite 只在稳定集成快照运行一次；若测试期间相关文件变化，结果标记 `UNVERIFIED`；
7. 未运行的真实前台、macOS Cocoa 或 Windows frozen 验收逐项报告，不能用 offscreen 代替。

## 17. 2026-08-28 正确性加固补充合同

本节是原规格落地（`1cb54ca..676e96a3`）之后的加固，不是原实现的既有行为。
对应计划：
[`2026-08-28-wwt-import-correctness-followup-plan.md`](../plans/2026-08-28-wwt-import-correctness-followup-plan.md)。
产品代码合入 `wwt-followup-integration`：`9efb35d8` … `5e46059a`。

### 17.1 Record store 由加载层拥有

`load_wwt_document()` / `parse_wwt_document()` 通过 `attach_wwt_record_store()`
把**同一份**不可变 `tuple[WwtRecord, ...]` 写入该物理文件展开的每个
`LoadedSource` / group `source_metadata["wwt_record_store"]`。多 group 共享这一
tuple，不按 group 复制 ndarray。

这条路径覆盖 Accept、Reject（只保留数据）、无可用 display/window、以及项目恢复。
`WwtImportCoordinator` 只消费 proposal 与 placement，不再回写 record store。
项目恢复期间不弹排版确认框；store 随 WWT 重新加载附着，不依赖协调器。

`.tlproj` / session JSON 只保存 source 路径和 View 身份（`TimeDataRef` /
`TimeCurveBinding` 的 `kind` / `fid` / `channel` / `record_index` 与显示事实）。
禁止把 record store 或 ndarray 样本展开进 JSON。运行时 store 在再次打开 WWT
时由加载层重新附着。

### 17.2 Claimed binding 不得 Time-Y fallback

`bound_time_plot_rows()` 返回 UI-neutral `BoundTimePlotResult`：

```text
rows, issues, claimed_channel_keys, successful_channel_keys
```

三值解包是 `(rows, issues, claimed_channel_keys)`，因此 MainWindow 普通 Time-Y
循环跳过的是 **claimed** 键，而不是只跳过成功解析的键。

- 一条 active binding 一旦声明 channel-backed Y，复合键 `(fid, raw_channel_name)`
  立即进入 `claimed_channel_keys`，发生在 X/Y 解析之前。
- 解析、长度与时间对齐成功后，该键才进入 `successful_channel_keys` 并产生 row。
- 失败 binding 留下结构化 `TimePlotIssue` / placeholder；不得把同一个 Y 再画成
  普通 Time-Y 曲线。
- 身份键是复合 source/channel identity，不是显示名。不得用 `dict(...)` 或
  `{**mapping}` 把 `_ChannelKeyDict` 压成显示名键。

### 17.3 Channel-backed Y 服从当前 View 勾选

`bound_time_plot_rows(..., checked_channel_keys=...)` 把当前 View 的 checked
复合键当作 channel-backed Y 的可见性条件：

- Y 为 channel-kind 且不在 checked 集合中：仍 claimed（挡住 Time-Y fallback），
  但不产生 row。
- 重新勾选后按持久化 X/Y 绑定恢复，不丢 binding。
- record-only Y 没有 Navigator channel 身份，不走这套勾选门；可见性仍由导入时
  的 binding 决定。
- `checked_channel_keys=None` 只用于跳过 Navigator 门控的纯解析测试。
- 当前 View 新勾选、但没有被任何 binding 声明的通道，仍追加为普通 Time-Y。

### 17.4 诊断按事实分层

`WwtIssue` 使用稳定 code（展示文案由 code + 上下文生成，不以中文字符串去重）：
`truncated_window`、`unknown_record`、`unsupported_display`、
`unsupported_formula`、`unsupported_representation`、`view_cap`、
`exact_overlap`。

三类结果不得混用出口：

| 类 | 事实 | 用户可见 |
| --- | --- | --- |
| retained auxiliary | 已进入 record store，仅未成为 Navigator source channel；metadata `wwt_auxiliary_records` | 无黄色“通道未导入” |
| degraded import | 不支持的 display/formula/representation、未知 record、不对齐、窗口截断、view cap 等 | 一次聚合 warning/issue，code 稳定 |
| placement outcome | exact overlap、append/new view 等用户已在确认框接受的布局结果 | 确认框即为说明；接受后不再发第二个黄色 toast |

`WwtImportCoordinator` 聚合成一次 import summary。`_project_io_mixin._consume_wwt_import_outcome()`
是黄色摘要的唯一消费点；项目恢复不弹 toast，但 View issue 必须持久。plot-time
`missing_record` / `unaligned` 继续挂在对应 View。

### 17.5 Native tick 先计数再枚举

`native_axes._bounded_index_range()` 在分配 tick 列表之前，用有限的 lo/hi/step
商证明候选数。major 与 unlabeled grid **共用**产品上限 `max_grid=2000`
（`_GRID_CAP`）。候选超限、非有限、零/负 step 或无效 range 时整轴退回现有
adaptive 路径，warning 为 `tick_cap`（或 `invalid_range`），不得出现“一侧
native、一侧静默失败”的半应用轴。禁止先构造完整列表再检查长度。

View restore 顺序不变：`restore_visible_xlim(flush=False)` →
`restore_visible_ylims` → `settle_view_restore()`。本加固不改 ink、AA、raster
或 150 ms idle timer。

### 17.6 可移植夹具与未完成门禁

核心 owner 测试使用仓库内合成字节 `tests/_helpers/wwt_factory.py`，profile：

- `channel_xy_with_auxiliaries`：单窗口 channel X/Y + 不可见 limit/line 辅助 record
- `measurement_plus_record_only_tolerance`：channel 测量 + 独立长度的 record-only 评价线
- `multi_window_overlap_and_formula`：多窗口、独立 X/Y、公式、exact overlap

通道 Zeit `n=128`；辅助/评价数组 4–32 点。名称与数值完全合成，不复制客户数据。
`testdoc/WWT` 仅作可选 skip-guarded smoke / 前台证据；缺失时 `pytest.skip`，
不得 `pytest.fail`。

Task 5 聚焦与边界门禁已通过。下列门禁仍为 `UNVERIFIED`，证据见
`.state/wwt-followup-task5-report.md`：两段全套（主套 segfault）、真实前台六项、
Windows frozen。offscreen 不能代替前台。
