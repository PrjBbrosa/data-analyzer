# WWT 导入与分析 View 状态问题报告

- **日期：** 2026-08-29
- **性质：** 当前行为核查 + 问题分级；**不包含产品代码修改**
- **范围：** 本轮对 WWT/WinWert 原始曲线、U-Can 样本、通道树，以及 FFT/Order 的「查看全部」后 View/Section 切换行为的核查。
- **样本：** `testdoc/wwt/U-Can_D6-CSER double_00479.wwt`、`testdoc/wwt/U-Can_EO3_000089.wwt`；用户提供的 NLTNP 截图。

---

## 0. 结论

当前没有发现 U-Can D6 的第 7 个原始图窗或已支持的 WWT 公式通道被实际丢弃；两者都被保留了，但界面呈现缺少可发现性。

有两个应进入修复计划的问题：

1. **P1：WWT 的 record-only 边界线会绘制，却没有 TraceLab 内的单条可见性开关。** 用户无法在不回到 WinWert 修改源文件的情况下控制上下限等辅助线。
2. **P1：FFT / Order 的移动、缩放与「查看全部」均是临时画布动作，不属于 Analysis View 状态。** 切 View 或离开 Section 后，缓存重绘会按该 View 保存的显示参数重新设轴，从而撤销当前画幅。

另有两项确认的可发现性问题：重叠窗口进入 UltraView 未放置托盘时看起来像少了一张图；同采样率的 WWT 逻辑源同名时，计算通道虽然存在于树内却难以被定位。

---

## 1. 证据与复现结论

### 1.1 U-Can D6 的 View 数量与重叠

直接通过当前加载器和 `MainWindow`（offscreen）导入 `U-Can_D6-CSER double_00479.wwt`：

```text
views 7
1 WinWert 1 · Wheel input torque
2 WinWert 2 · Wheel input torque
3 WinWert 3 · Motor torque A
4 WinWert 4 · Motor torque B
5 WinWert 5 · Motor torque A+B
6 WinWert 6 · Wheel input torque Symmetry
7 WinWert 7 · Wheel input torque Hysteresis
ultraview placed=6 unplaced=1
```

**结论：** 源文件的 7 个图窗均创建为时域 View；第 7 张并未丢失。原始矩形完全重叠时，导入逻辑保留全部 View，但 UltraView 只将一张放在原位置，另一张进入「未放置」托盘。确认弹窗也明确提示重叠窗口会进入未放置区（`mf4_analyzer/ui/main_window/wwt_import_coordinator.py:138-143`）。

### 1.2 WWT 公式通道是否进入通道树

D6 中的 `Pars` 记录已成功求值并注入第二个逻辑源的数据列：

| 已计算通道 | 公式记录 |
| --- | --- |
| `Diff.Moment A` | 4 |
| `Diff.Moment B` | 5 |
| `Spurstangenkraft` | 11 |
| `Motor torque A+B` | 12 |

随后 `MainWindow` 的左侧树可见这四个叶子。因此「U-Can 计算通道完全不显示」不成立。问题在于一个物理 WWT 文件可以拆成多个逻辑源，D6 的两个分组均只显示为 `1.0 kHz`；用户无法从树标签判断哪一组承载了计算通道。

支持的 `Pars` 记录的求值、注入及元数据写入路径见 `mf4_analyzer/io/wwt_document.py:533-613`。无法求值、无法找到所属 `Zeit` 轴或样本长度不匹配的 `Pars` 才会保留为 auxiliary，而不会成为树中通道。

### 1.3 边界记录与「是否 plot」

WWT 的记录存在、其曲线在某个窗口可见、以及该曲线是否是坐标轴 owner 是三件不同的事。

| 样本 | 原始边界记录 | 原始文件标记为可见并应绘制的边界 |
| --- | --- | --- |
| D6 | `Diff.Limit A/B` | 仅 View 2 的 `Diff.Limit A` |
| EO3 | 多个 `Grenze`、`SKL Grenze`、`Tol.` | View 5 两条 `Unterst. Kl.`；View 9 `Md Sensor Tol. unten/oben` |

当前导入只选择每个窗口 `visible=True` 的 Y 曲线（`mf4_analyzer/ui/wwt_view_import.py:224-233`），因此「某项边界数据存在但未 plot」在上述样本中是原始 WWT 的显示意图，不是导入漏画。

---

## 2. 问题清单

### P1 — WWT 原始辅助线无单条开关

**现象**

WWT 中上下限等 record-only 辅助线按原始 `visible` 标志导入并显示，但左侧通道树没有它们，用户无法单独隐藏或重新显示。

**根因**

导入时每条可见 WWT 曲线都被固化为 `TimeCurveBinding`（`mf4_analyzer/ui/wwt_view_import.py:321-345`）。渲染时仅 channel-backed binding 依据 Navigator 勾选状态跳过；`wwt_record` binding 没有独立的显示状态，因而始终追加到 plot rows（`mf4_analyzer/ui/time_curve_bindings.py:390-440`）。

**影响**

- 上下限、目标线等可能遮挡主曲线；
- 用户在 TraceLab 内无法做展示取舍；
- 左侧树与实际画面不一致，容易误判为「多出来的红线」或数据错误。

**建议验收**

在 WinWert View 中暴露原始辅助曲线列表：名称、原始颜色、来源标记、眼睛开关。关闭后只影响该 View 的绘制，不删除记录、不改变普通 Navigator 通道，也不修改原 WWT 文件；保存/重开项目后保持。

### P1 — FFT / Order 的「查看全部」范围切换后不保持

**现象**

FFT 或 Order 图中右键「查看全部」后，当前画面会回到全结果范围；切换分析 View，或切到别的 Section 再回来，X/Y 画幅又回到计算完成时/Inspector 显示参数所规定的范围。

**根因**

Analysis View 离开时保存参数、源、时间范围、overlay 等状态；仅 FRF 额外捕获画布范围，FFT/Order 没有对应 capture（`mf4_analyzer/ui/main_window/_analysis_mixin.py:317-334`）。

进入分析 View 后，系统从缓存重绘（`mf4_analyzer/ui/main_window/_analysis_mixin.py:1120-1219`）。FFT 重绘会按 `x_auto/x_min/x_max/y_auto/y_min/y_max` 重设坐标轴（`mf4_analyzer/ui/main_window/window.py:1698-1733`）；Order/FFT-vs-Time 的热图亦按同一组持久化显示参数设范围（`mf4_analyzer/ui/pg_canvas/heatmap_canvas.py:834-860`）。

「查看全部」仅调用画布的 full-extent reset，不会写回 Analysis View 参数或新的 viewport 状态（Order 示例：`mf4_analyzer/ui/pg_canvas/heatmap_canvas.py:1146-1187`）。

**影响**

- 用户完成一次明确的全图复位后，切换工作区会失去上下文；
- View 的“独立工作台”心智模型被打断；
- 「Y 轴仍是计算完成状态」容易被误解为又计算了一次。正常切换的主要路径是 cache render，不是新的计算提交。

**已确认的产品要求与验收**

FFT、Order、FFT-vs-Time 的每个 Analysis View、每个 pane 均应独立保持用户主动形成的 X/Y viewport，包括拖动平移、框选缩放、滚轮缩放和右键「查看全部」。

- 切换到其他 Analysis View、离开并返回对应 Section、或从缓存恢复同一结果后，应还原该 View + pane 的最后 X/Y viewport；其他 View/pane 不得被污染。
- 「查看全部」应将该结果的完整 X/Y 范围写入同一份 viewport 状态，而非仅改变当前画布。
- Inspector 中用户明确“应用”的轴范围设定应成为新的该 View + pane viewport；一般缓存重绘不得再无条件覆盖已保存的 viewport。
- 热图色标（Z）继续遵循其现有独立语义；本项只规定 X/Y viewport，不把 Z 范围混入同一状态。
- 重绘恢复必须在结果绘制完成、最终几何已确定后进行，避免后续设轴步骤覆盖已恢复的范围。

### P2 — U-Can 重叠图窗保留但未放置状态不够显著

**现象**

用户看到 UltraView 只有 6 张卡，推断第 7 张丢失。

**事实与根因**

当前实现正确地保留 7 个时域 View，并将重叠的一张移入未放置托盘；这是为了避免两张卡在同一原始位置互相遮蔽，而非导入数量被截断。

**体验缺口**

导入结束时缺少直观、可操作的数量闭环，例如“已生成 7 个 View：6 张已按原图放置，1 张因重叠在未放置”。用户必须自己打开 UltraView 左侧窄轨才知道该卡仍在。

**建议验收**

导入完成提示和 UltraView 入口显示未放置数量；点击可直达托盘并将指定卡插入自由网格。验收应同时断言 `placed + unplaced == generated Views`。

### P2 — 同采样率逻辑源标签导致计算通道难以发现

**现象**

同一个 WWT 分裂出的多个逻辑源，在通道树内都标为相同的 `1.0 kHz`。已计算通道存在，但其所属分组没有语义名称或来源提示。

**影响**

用户容易得出“计算通道没有显示”的结论，也难以判断普通记录、辅助记录和公式结果的归属。

**建议验收**

保留现有分组语义的前提下，为同名逻辑源提供稳定的可区分标签或 tooltip（例如数据块/时间记录、通道数量、包含公式结果）；搜索可命中公式通道名称；不要用显示名称代替复合 source/channel identity。

---

## 3. 非问题与边界

1. **边界记录存在却不画，不自动构成导入缺陷。** 是否绘制尊重 WWT 窗口曲线的 `visible` 标志；不能按记录名称猜测应显示。
2. **D6 的第 7 个 View 并未丢失。** 这是 UltraView 重叠处理的可发现性问题，不是时域 View 创建错误。
3. **D6 的四个已支持公式通道已经进入树。** 公式未出现时，应先检查求值诊断、所属时间轴和样本对齐，不能一律归因于导航树。
4. **FFT / Order 的画面返回时变化，当前不等价于重复计算。** 当前实现会从缓存结果重绘，并重新应用已持久化的 Inspector 显示参数。

---

## 4. 已确认的产品决策与剩余边界

**已确认：** FFT 和 Order 的全部手动移动、缩放、框选缩放及「查看全部」都按 **Analysis View + pane** 保持，不能只保存「查看全部」。

**仍需在实现前确认：** 点击“重新计算”后结果数据或频率/阶次范围可能变化。默认建议将该 View + pane 的旧 viewport 重置为新的 Inspector 设定/结果有效范围，避免恢复到失效或全空的坐标范围；若希望在数轴仍有交集时尽量保留旧 viewport，需要额外定义裁剪规则和验收样例。

---

## 5. 验证状态与限制

| 证据 | 状态 | 说明 |
| --- | --- | --- |
| WWT 文件结构解析 | 已验证 | 读取两个 U-Can 文件的 records/windows/`visible` 标志。 |
| D6 导入数量与 UltraView 托盘 | 已验证 | 当前 checkout 的 offscreen `MainWindow`：7 View，6 placed + 1 unplaced。 |
| D6 `Pars` 通道进入数据列/通道树 | 已验证 | 当前 loader + offscreen `MainWindow`：4 条计算通道。 |
| FFT / Order View-All 范围回退根因 | 已验证 | 已追踪 capture、cache render、canvas reset 与重新设轴路径。 |
| macOS 前台交互表现 | 未验证 | 本报告未做 Cocoa 前台手势复现。 |
| 不同客户 WWT 的 record-only 开关需求 | 未验证 | 已从代码与两份 U-Can 样本确认机制，尚未统计客户文件覆盖率。 |

## 6. 后续顺序

1. 确认第 4 节中“重新计算”后的 viewport 重置规则。
2. 以 P1 的辅助线开关和 Analysis viewport 状态分别建立红测，不把两个状态模型混在一次改动中。
3. 再补 P2 的重叠 View 数量闭环与逻辑源标签；保持 WWT 原始记录、复合身份及 UltraView 未放置语义不变。
