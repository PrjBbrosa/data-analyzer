# WWT Export Dual-Compatibility Spec (2026-08-11)

## Goal

Channel-editor **导出** can write a `.wwt` that:

1. **TraceLab** re-imports via `load_wwt_groups` with matching time base,
   channel names/units, and sample values; and
2. **WinWert** opens the file as a normal measurement (channels visible,
   time axis usable). Display polish (layout, tolerance curves, Pars) is
   out of scope for v1.

This is a higher bar than “TraceLab-only roundtrip”. Synthetic fixtures used
for help screenshots are **not** proof of WinWert acceptance.

## Non-goals (v1)

- Round-tripping original WWT extras: `Pars`, tolerance/limit short blocks,
  `IntB` / `InBT` / `FloT` / `I10T`, multi-`Zeit` topology, original trailer UI.
- Evaluating or emitting WinWert arithmetic formulas.
- Exporting irregular (non-equidistant) time axes without an explicit
  resample/reject policy.
- Mixing channels from unequal sample rates / lengths into one file.

## Write profile (v1)

| Piece | Choice |
| --- | --- |
| Magic | `WinWert091293` (dominant in `testdoc`; layout compatible with reader) |
| Records | One `Zeit` + N data channels as `Real` (`float64`, scale `a=1`, offset `c=0`) |
| Time | Equidistant: `t0`, `dt`, `n` from the export source (or cropped range) |
| Names / units | Truncate to 40 / 17 bytes (latin-1); preserve when possible |
| Display range | Fill record `min`/`max` from finite data extents |
| `count` @ `0x20F` | Exact record count written (`1 + N`) |
| `xkanalnr` @ rec `+0x9` | 有显示尾块 → `0`；极简尾块 → 非 0（**WinWert 拒开条件**，见下） |
| Trailer | 真实 `DatenFenste2` 显示块，曲线表按目标通道重建 — TraceLab 忽略 |

Prefer physical `Real` over quantized `int1`/`Long` so MF4/CSV/MAT exports
do not invent scales.（这正是 WinWert 自己的写法，见「WinWert 自己写的参照
文件」。）

Exported length must be ≥ TraceLab’s `_MIN_TIMESERIES_SAMPLES` (100); shorter
`Zeit` blocks are treated as curve definitions on re-import. The channel-editor
export path refuses below that threshold.

## Hard constraints

- Time must be equidistant within a tight tolerance; otherwise refuse with a
  clear Chinese error (or, if product later opts in, resample — not silent).
- All exported Y channels share the same `n` as `Zeit`.
- “仅导出选定时间范围” rewrites `n` / `t0` consistently (absolute time kept).
- “包含时间列” for WWT means “emit `Zeit`” (always on for a valid file).

## WinWert gate (blocking for “开得了”)

Real `testdoc` files always end with a large `DatenFenste2` display block
(~32–114 KiB). TraceLab stops at that marker and never parses it.

### Trial log (2026-08-11)

| Candidate | Result |
| --- | --- |
| Original `YP_SS_000089.wwt` | opens |
| Comment-only byte-copy | opens |
| Body-only / 256 B stub（`xkanalnr=0`） | rejected —— 原因是 `xkanalnr`，见「WinWert 自己写的参照文件」 |
| 256 B stub + `xkanalnr=1`（`testdoc/20260527.wwt`） | **opens**（横坐标由 WinWert 的 `.lay` 决定 → 角度） |
| Clean-room body + grafted full trailer（曲线表未重建） | rejected |
| Graft + rewritten slot labels | rejected |
| `candidate_from_csv_convert.wwt`（Servo 模板 in-place） | **opens**，但横坐标是角度（见 §显示轴机制） |
| `testdoc/20260527.wwt`（stub 布局 + DC2E 真实数据重写） | opens（横坐标仍是角度——空尾块时 WinWert 用自家默认版式） |

**Implication:** in-place 模板路线成立（开得了）。stub 的两次结果矛盾，
差异未定位——正文可疑，尾块本身未必是拒开原因；clean-room 路线留探针
复测（`probe_time_D`），产品不押注。

## 显示轴机制（2026-08-11 解出并实证）

「打开后横坐标是什么」由文件自己声明。模板 in-place 导出如果不改，会
**原样继承模板的角度轴**——这就是导出文件打开后横坐标是角度的直接原因。

**决定性字段：尾块曲线记录的 X 引用。**
曲线记录基址 = `尾块起点 + 171 + 曲线号 × 283`；**曲线号 = 记录序号**
（0 基，含 Pars/未知记录；曲线 0 是对话框底部的「X Axis」行）。记录内：

| 偏移 | 类型 | 含义 |
| --- | --- | --- |
| +0 / +8 | double | 轴下限 / 上限 |
| **+18** | **u16** | **X 轴引用曲线号 —— 0 = 记录 0（Zeit）= 按时间显示** |
| +20 / +22 | u16 | Selector 勾选 / 是否绘制 |
| **+26 / +34** | double | 主刻度 / 网格间隔 —— **写 0 = 交给 WinWert 自动**（见下） |
| **+44** | **double** | **轴原点 = −(上限 × 比例) − C**（C 是版式常量，见下） |
| **+52** | **double** | **绘图比例 = K / 轴跨度**（见下） |
| +60 | char[64] | 轴标签 `Name [unit]` |
| **+263 / +271** | u32 / 3×u8 | 颜色下拉序号 / RGB（配套写） |

**轴原点 +44 必须跟着量程重算**（2026-08-11 实测）：`+44 = −(hi × 比例) − C`，
C 在文件内恒定（8 个样本、几十条曲线逐条验证；实测 C 因版式而异：100 / 50 /
250，X 轴行另有一套：−5100 / −5070 / −4950）。原型曲线的下限恰好是 0 时
`hi × 比例` 正好等于 K，照抄原型的 +44 就等于宣称「上限在满幅处」——下限为负
的曲线于是被顶上去半格，**首帧只画出正半边**（Ch4 轴只显示 0..4 而不是
−4..4），刷新后才归位。`wwt_display.layout_constants` 在改任何轴范围之前从
模板推出 `(K, C)` 两套常量，`write_curve` 写范围时一并同步 +52 与 +44。

**刻度写 0**：WinWert 自己的导出（含 X 轴行）全部写 0（= 自动），照抄即可。
早先 `_nice_step` 那套「跟着量程重算刻度」已删除。

**颜色**：序号 → RGB 实测 `0=黑 000000 · 1=红 ff0000 · 2=绿 00ff00 ·
3=深蓝 000080 · 4=品红 ff00ff · 5=蓝 0000ff · 6=橄榄 808000 · 8=青 00ffff ·
9=棕 7f0000`（序号 7 语料未出现，调色板跳过）。WinWert 自己的 `.mat` 导出
**按曲线序号取色**（curve1..6 = 序号 1..6），X 轴行取 0（黑）。导出侧照此
循环配色——所有曲线都是从同一个原型记录复制出来的，不单独配色会全是红色。

**+52 绘图比例**：`轴跨度 × +52 = K`，K 在文件内按方向恒定——12 个样本实测
X 侧 4200、Y 侧 2400，U-Can 版式 X 侧 2000；4200/2400 正好是曲线设置对话框
`Window size (mm): X 210 Y 120` 的 20 倍，即「绘图区 mm × 20」。
**WinWert 首帧按 +52 作图**，只改轴范围不同步它，打开时数据会挤成左边一条
细带、刻度标签叠在一起，手动刷新后才按轴范围重绘（2026-08-11 实测截图）。
导出侧因此在改任何轴范围**之前**先从模板推出 K（`wwt_display.layout_constants`，
Y 侧取中位数），写范围时按 `K / 新跨度` 同步 +52。X 轴行（曲线 0）的 +52
就是尾块头 +223 —— 二者是同一个字段，早期把它当独立「窗口缩放」是误读。

尾块头 **+69 的 u16 是全局 X 曲线号**（该曲线从曲线列表隐藏），逐曲线 +18
可以各自覆盖它。另有 +13 double 0.2 · +23 u32 1 · +27 u32 记录总数 ·
+89 字体名。曲线表之后的 `Beschriftung` / `MetaDateienI` / `Zeichnungsel` /
`WinWertMessparamete` 段是版式/元数据/评价公式。

验证方式：用户在 WinWert「曲线设置」对话框里截图 DC2E 文件的 X 列
（`5,5,5,5,5,0,8,8,8`）与每行 From/To/Ticks/Grid，按上表解码逐行一致；
10 个 testdoc 样本语义交叉自洽（Servo 曲线 7 MotorOutput → X=5
RotorPosition，正是探针 A 画出的迟滞环；EO3 公差曲线成对互指 `(x)` 通道；
SFNS 指 Rack Travel）。

**记录头 +0x9 的 `xkanalnr`（官方 `.m` 的 `XKanalNr`）显示不读**——探针 E1
把它改成 6，对话框仍显示 8。它是采集侧字段，导出时一并写 0 只为语义自洽。

## 量化槽位必须重新标定（2026-08-11 回归）

模板的 `int1`/`Long` 槽位带着**原被测量的** scale/offset（Servo 的 int16 槽位
只到 ±32）。沿用它写别的通道会**静默截断**——实测 ±450° 的转向角被削成
±32。`_fit_scale` 因此按本次数据 min/max 重算 `a`/`c` 并写回记录头
（+0x84 scale、+0x94 offset），量化误差降到量程的 1/65534；实测 ±450°
通道最大误差 0.007°。测试 `test_convert_rescales_quantized_slots` 看守。

**产品写法（已实现）**：`convert_to_wwt(..., time_axis=True)`（默认开）在
in-place 改写后调用 `wwt_display.force_time_axis`：**每条曲线记录的 +18 写 0**、
全局 +69 写 0、曲线 0（X 轴行）标签写 `Time [s]` 且量程写实际时间跨度、
**刻度/网格写 0**、**+52 绘图比例与 +44 轴原点按版式常量同步**。写入的曲线
各自拿到标签 / 量程 / 比例 / 原点 / 颜色并置为可见；**未写入的模板曲线取消勾选**（+22 = 0），
否则模板残留数据会跟导出通道画在同一张图上。其余尾块字节原样保留。

## WinWert 自己写的参照文件（2026-08-11 晚，决定性）

用户用 WinWert 直接把 `.mat` 导成了 `.wwt`
（`testdoc/exporttowwt/175rpm_-45deg-270tighten.wwt`，13.7 MB）。这是**厂商
写入器的输出**，比任何逆向都权威。三条硬结论：

1. **正文就是 clean-room 写法**：`Zeit`（n=284988, dt=0.001）+ 6×`Real`
   （float64, a=1 / b=1 / c=0），`src` 字段填源 `.mat` 名。与
   `wwt_writer.write_wwt` 的记录头**逐字节一致**（只差样本数、极值、dt 末位
   舍入这些本就该不同的字段）。⇒ 我们的正文格式没有问题。
   附带：WinWert 给 `Zeit` 记录的 min/max 写的是 `[0, 1]`，可见该字段不重要。
2. **尾块曲线表用的正是本文解出的布局与常数**：X 轴行 `Time [s]` 范围
   `[0, 284.987]`（末点时刻，未做圆整）K=4200；每条曲线 `+18`=0（时域）、
   `vis`=1、范围 = 数据真实 min/max、K=2400；**`ticks`/`grid` 全写 0**、
   **颜色按曲线序号 1..6 循环**。⇒ 逆向结论全部证实，后两条还直接给出了
   「首帧轴布局错位」与「曲线全红」两个问题的正解。
   它还把当时会话的 `Beschriftung` / `.lay` 路径 / CAN 名表原样带了出来，
   说明尾块是**应用显示状态的转储**，与数据无关。
3. **`xkanalnr` 的真正作用是尾块缺失时的兜底**：`testdoc/20260527.wwt`
   （能打开）与我们 writer 的输出**逐字节相同**，只差三条数据记录的
   `xkanalnr`——它写 1，我们写 0，而写 0 的探针 D 打不开。这是一次完成的
   受控对照：**极简尾块 ⇒ 必须非 0**（显示则由 WinWert 自己的 `.lay` 决定，
   所以那个文件是角度横坐标）；**带完整显示尾块 ⇒ 写 0 即可**（WinWert 自己
   就是 0 + 完整尾块）。`write_wwt` 因此按尾块能力自动选默认值。
   ⚠️ 本次会话一度把 writer 的 `xkanalnr` 从 1 改成 0（当时误以为 0=时域），
   那正是探针 D 打不开的原因，已修复并由测试看守。

### clean-room 路线复活（已作为产品默认）

既然正文格式无误、尾块只是显示状态转储，就可以：**我们的正文（任意点数 /
任意通道数 / float64 无量化）+ `wwt_display.rebuild_display_trailer` 把真实
尾块的曲线表按目标通道重建**（表体 = 记录数 × 283，表项 i 对应记录 i，
表项 0 是 Zeit 即 X 轴行；其余段整体搬运，`+27` 记录数同步）。一次去掉现路径
的三条限制：6 通道上限、9936 点重采样、int16/int32 量化。

顺带解决的还有一条**正确性**问题：模板尾块 `Log2` 段的 4 条页脚注释会把
模板来源的台架编号、试验规范、操作员姓名印在导出图下方（用户截图里的
"function test bench: 591-082 RT" 就是这么来的）。这些是 NUL 填充的定长文本槽
（4×201 B 注释 + 2×101 B 标题/注释 + 51 B 署名，相对 `Log2` 标记定位），
`wwt_display.set_display_text` 负责改写：导出时写入本次的标题/注释、清空继承
的页脚、署名写 `TraceLab`。捆绑资源在生成时就已清洗（`test_wwt_display.py::
test_bundled_trailer_asset_carries_no_session_text` 看守）。

候选：`probe_cleanroom_I_native.wwt`（DC2E 三通道原生 43062 点 float64）·
`probe_cleanroom_K_8ch.wwt`（8 通道 5000 点，验证曲线表增长）。
I 的一轮回执：**打得开、时域显示、±450° 完整**；残留的「首帧范围不对」与
「曲线全红」已按厂商写法修正（刻度写 0 + 按序号配色），见探针台账。

### 探针回执台账（2026-08-11，WinWert 实测截图）

| 探针 | 改了什么 | 结果 |
| --- | --- | --- |
| A | 产品路径 v1（xkanalnr=0 + 窗口头→Zeit/`Time [s]`） | 能开；X 轴**标签**变成 `Time [s]`，画的仍是模板残留 MotorOutput vs RotorPosition 迟滞环 ⇒ 标签生效、数据绑定未切 |
| B | 仅 `xkanalnr`→0 | 显示与原件完全相同 ⇒ 记录头字段显示不读 |
| C | 仅窗口头 +69→Zeit | Steering angle 从「被当 X 隐藏」变成可见曲线（角度 vs 角度对角线），其余仍 vs 角度 ⇒ +69 只是全局 X |
| D | clean-room 全长 + stub 尾块 | **打不开** —— 后经逐字节对比定位为 `xkanalnr=0`（见上节第 3 条），**不是** clean-room 路线本身的问题 |
| E1 | `xkanalnr`→6（Zeit）+ 窗口头→6 | 曲线设置对话框显示：底部 X Axis=6（+69 生效），但**逐曲线 X 列仍是 8** ⇒ 逐曲线 X 在第三处 → 由该截图解出上表 |
| F | 产品路径 v2（曲线 +18 全 0 + 隐藏未写入曲线 + 量化重标定） | **时域显示成立**：0–40 s 横轴、三条曲线各自 Y 轴、±450° 角度完整。唯一残留：**首帧**数据挤在左侧、刻度标签重叠，手动刷新后正常 ⇒ 绘图比例 +52 未同步 |
| G | DC2E 原件仅曲线 +18 全 0 | 同上（机制确认：仅改 +18 即可切时域） |
| H | DC2E 原件 + 完整显示改写（数据不动） | 同 F，首帧同样需刷新 |
| F/G/H v3 | 追加 +52 绘图比例同步（K 守恒） | 未单独回执（被 clean-room 取代） |
| I（clean-room v1） | 自写正文 + 重建尾块，原生 43062 点 float64 | **打得开、时域显示、±450° 完整**。两处残留：①**首帧**总范围不对、只显示一半，刷新后正常；②所有曲线同色（红） |
| I/K（clean-room v2） | ①刻度/网格写 0 ②按曲线序号循环配色 | 颜色正确；**首帧仍只显示上半边**（Ch4 轴 0..4 而非 −4..4），刷新后完整 |
| I/K（clean-room v3） | 追加轴原点 +44 按量程重算 | **待验证**（原型下限为 0，照抄其 +44 正好差半个轴高，与实测吻合） |

## Product surfaces

- Channel editor 导出：格式下拉 Excel / WinWert (.wwt)；WWT 时锁定「写入 Zeit
  时基（必需）」，范围裁剪可选。
- 导出代码全部在 `mf4_analyzer/io/`，UI 只调 `wwt_export.export_wwt` 并把
  `WwtExportResult.summary` 拼进状态栏 / toast。
- 测试分工：`test_wwt_display.py`（显示块字段契约）·`test_wwt_export.py`
  （门面两条路的产品契约）·`test_wwt_inplace.py`（模板路径特有问题）·
  `test_wwt_writer.py`（正文与 `xkanalnr` 兜底规则）·
  `tests/ui/test_channel_editor_export.py`（UI 串通）。
- 打包：`assets/wwt` 目录整体 `--add-data`，四个 wwt 模块显式列进 hidden
  imports（导出是函数体内惰性 import），`test_windows_build_script.py` 看守。
- Record durable findings in this spec or
  `docs/analyzer/specs/2026-08-11-wwt-zfd-official-import-notes.md`.

## Dependencies / unknowns

- Need access to **WinWert** (or a colleague who can open candidate files) for
  the gate above. Repo tooling alone cannot close dual-compat.
- Official MATLAB `wwt_import.m` is read-only; no vendor writer in-tree.
- If WinWert rejects minimal trailers, schedule a follow-up to map
  `DatenFenste2` (or obtain ZFLS write documentation).

## Status（2026-08-11 收尾）

- **Goal**: any loaded format (MF4/CSV/…) → ``.wwt`` that **WinWert and TraceLab**
  both open, and that WinWert displays **time-domain**（X = 时间）。
- **Shipped default = clean-room**：``io/wwt_export.export_wwt``（``mode=
  "cleanroom"``）自写正文（``Zeit`` + N×``Real`` float64）+ 用捆绑的真实显示
  尾块 ``assets/wwt/winwert_display_trailer.bin`` 按目标通道重建曲线表。
  **点数原生保留、通道数不限、零量化误差**，并强制时域显示、清掉模板继承的
  页脚文本。依据见「WinWert 自己写的参照文件」一节。
- **Fallback = template**（``mode="template"``，即 ``wwt_inplace.convert_to_wwt``）：
  重采样进 ``assets/wwt/winwert_export_template.wwt`` 的 6 个测量槽位
  （n=9936），量化槽位按数据量程重新标定，未写入的曲线取消勾选。
  这条路的显示已由 WinWert 实测通过（探针 F/H）。
- Channel-editor **导出 → WinWert** 走 ``export_wwt``（可先按范围裁剪）。
- **等间隔 Zeit**：源时间轴非等间隔时，clean-room 自动线性重采样到
  ``linspace(t0, t1, n)``（保留点数与起止时刻），结果摘要标 ``已重采样``。
- **拒绝而不是编造**：源短于 ``_MIN_TIMESERIES_SAMPLES``（100）时报错而不是
  上采样——补点等于凭空造数据，且 TraceLab 自己也会把短块当曲线定义跳过。
- 模块分工：``wwt_writer``（正文）· ``wwt_display``（``DatenFenste2`` 显示块）·
  ``wwt_inplace``（模板原地改写）· ``wwt_export``（产品门面）。
  资源生成器 ``tools/make_wwt_display_trailer.py``（抽取并清洗会话文本）。
- 已验证：clean-room 文件 WinWert 打得开、按时域显示、数据完整。
  v2（刻度写 0 + 逐曲线配色）待复验：``probe_cleanroom_I_native.wwt`` /
  ``probe_cleanroom_K_8ch.wwt``
  （`emit_wwt_cleanroom_probes.py` 产出）。若 WinWert 拒开，把 UI 的
  ``export_wwt`` 调用加上 ``mode="template"`` 即可退回已验证的路径。


## Related

- Import research: `docs/analyzer/specs/2026-08-11-wwt-zfd-official-import-notes.md`
- Reader: `mf4_analyzer/io/wwt_format.py`
- Standalone ports: `tools/matlab_ports/`
