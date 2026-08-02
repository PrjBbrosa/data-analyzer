# 圆角 surface 绘制归属审计

**日期：** 2026-08-02
**范围：** Batch 首层文件管理区的已确认缺陷，以及主界面圆角 surface 的定向抽样审计。
**证据等级：** Qt 离屏像素探针、源码/QSS 路径；不等同于 macOS 前台逐页面验收。

## 结论

截图中的 Batch 文件管理框不是“少了圆角线”，而是一个确定的覆写顺序问题：
外层 `QFrame#BatchInlineFileManager` 画白底、1px 边框和 9px 圆角；零 margin 的
`QWidget#BatchInlineFileManagerBody` 随后以矩形白底从 `(1, 1)` 绘制，覆盖了父框
圆弧的抗锯齿内侧像素。浅色 1px 边框使被覆写后的缺失看上去像泛白或断线。

这不是一个可以用全局 `border-radius`、全局 `mask` 或全局
`WA_TranslucentBackground` 修复的问题。正确动作是给每一个圆角 surface 指定唯一的
paint owner，再核对贴边 child/viewport 是否透明或有真实 inset。

## 已确认 Batch 证据

离屏渲染 `336×140` 的真实文件管理框时，body 几何为 `(1, 1, 334, 138)`：

| 条件 | 左上 9px 圆弧中间像素 | 结论 |
|---|---|---|
| 隐藏 body | 连续蓝灰边框像素可见 | 父框自身 radius/border 可正常绘制 |
| 显示 body | 中间弧线像素变为纯白，只留下顶/左直边 | body 的矩形背板覆盖父框圆弧 |

父框和 body 均已设置 `WA_StyledBackground`，因此它不是本次缺失的原因。主 QSS 中的
`QWidget { background-color: #ffffff; }` 会让任何没有被局部覆写为透明的贴边子层更容易
重现同一现象，但目前不移除这条基础规则。

## 代表性绘制路径审计

| 族 | 抽样路径 | 结论 | 动作 |
|---|---|---|---|
| 嵌入式圆角 shell | Batch `BatchInlineFileManager` → `BatchInlineFileManagerBody` | **缺陷已证实**；child 覆写父弧 | 父框单独拥有 fill/border/radius；body/空态/列表承接区透明或在可见 inset 内；加真实 arc 像素回归 |
| 侧栏的滚动 shell | `FileNavigator` → `fileArea`/`fileScroll` | 代码已把 `fileScroll` 与其 holder 设为 transparent；没有发现与 Batch 相同的贴边白底 selector | 保持现有路径；不因 Batch 缺陷批量改动，后续前台巡检 |
| Inspector 滚动 surface | `Inspector` → `inspectorScroll` → `inspectorScrollBody` | scroll 与 holder 已透明，body 是内层中性底色；这是有意的分层而非父弧贴边覆盖证据 | 保持；已有 surface-layering 合同继续覆盖 |
| Batch 三栏滚动 pane | `Batch*Scroll` → Qt viewport/holder | pane 无圆角，且显式统一 scroll/viewport/holder 背景；与本次圆角缺失不属于同一 defect | 仅确认其不能重新给文件 shell 加白底；无需 radius 改动 |
| 自绘/全幅画布卡片 | `ChartStack` / `chartCard` 与 pyqtgraph canvas | 画布可能全幅绘制，QSS 半径本身不能证明角部；当前未从该路径得到缺陷像素证据 | 在出现实际截图症状时，用同一 QImage arc profile 针对性测试，不改全局 QSS |
| 顶层 popup/menu | `apply_popup_shell`、`RebuildTimePopover`、`SignalPickerPopup` | 顶层窗口有独立的原生 backing 风险；现有策略是透明无框 outer shell + rounded inner surface | 保持专属 shell 方案；不把 `WA_TranslucentBackground` 迁移到普通嵌入卡片 |
| 叶子控件/子控件 | 输入框、按钮、徽标、scrollbar handle | 含 radius 的 QSS 规则很多，但未有本次根因的绘制证据 | 只按后续具体截图/像素 probe 修复，不批量替换 131 个规则 |

## 已实施的最小策略

本轮只把 Batch 文件管理框的绘制责任收敛到外层，并把固定视口、内部滚动与圆角像素合同
放在同一个测试范围。这样不会改变文件 source model、probe 生命周期、信号交集或 BatchRunner。

本轮明确不做：

- 不删除全局 `QWidget` 基础白底；
- 不给所有 `QWidget` 添加透明属性或圆角 mask；
- 不把 popup 的透明原生窗口方案用于普通 `QFrame`；
- 不把 QSS 中 radius 规则数量当成缺陷数量。

## 验证与剩余边界

离屏验证必须同时证明：四个角的 arc profile 连续、中心保持白色、直边未丢失；单看 QSS
里有 `border-radius` 不算通过。文件 0/1/4/8 行还必须维持同一外框高度，长列表只在内部
滚动。

离屏像素和自动化几何验证并不能替代 macOS 前台检查；在 1080×760 与 1440×900 两种窗口
尺寸下，仍需确认白底、圆角、滚动条和相邻 pane 分界没有新的视觉重叠。
