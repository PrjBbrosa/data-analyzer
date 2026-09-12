# Cursor 全模式排版修复验证

- 日期：2026-09-12；基线 `82948f02` + 前次 agent 未提交改动。
- 范围：三张用户截图对应的实际排版缺陷、全八种结构化模式、legacy +/-、分屏/复制链路。
- [修复计划](../plans/2026-09-12-cursor-rendering-parity-repair-plan.md) · [修订规格](../specs/2026-09-12-cursor-table-readability-spec.md)。
- 前次 offscreen pass 未拦住真实缺陷，不能作为本轮视觉验收。修复前 14 个文件快照/哈希保存在 `.state/cursor-table-audit/before/` 与 `fingerprint.json`。

## 根因与修复证据

| 用户问题 | 根因 | 修复 |
|---|---|---|
| 长名称拥挤、最右值被裁 | 名称 HTML 重复转义；测量漏算字重、单位、色点；测量可换行，实际 QLabel 不换行 | 原始文本行只转义一次，最多两行；字体真实度量；同一 QTextDocument 测量并绘制 |
| 短名称也和数值分行 | layout 只返回 grouped，测试还固定断言 grouped | 按真实信号宽度优先 horizontal；数值不够放才 grouped/compact，640逻辑像素硬上限保留 |
| 特殊 Custom-X 在表格外 | projection 与 pill 双重只接 Time-X dual full | 全8模式统一表格 DTO；方向、全程、诊断和缺失值位于同一网格 |
| 修复过程中发现的边界 | 空 primary 吞高度；零可见通道留表头；legacy primary 定宽导致 +/- 不收缩；单次 apply 入口被绕过 | 分别补失败回归并修复；保留真实唯一应用边界；极小空间明确降级并恢复 |

修复前 production QSS 探针：detail 264px，但实际 nowrap glyph 右界372.34px；Δ起于280px，整列已在外框之外。旧47项测试仍通过。探针与原图在 `.state/cursor-table-audit/unit_probe.py` / `unit-probe.png`。

## 本轮命令结果

全部使用项目 `.venv`。Qt tests 使用 `TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=.`，无 full suite。

| 批次 | 实际结果 |
|---|---|
| 首次集中 layout/geometry/modes/settings/single/source/formatting/Custom-X | 810 passed / 2 failed；两个失败为旧 name HTML 接口访问和单次 apply 入口，均已修复 |
| owner + single + formatting + 完整 ChartStack 聚焦整合 | 405 passed，350 个既有 NumPy/pyqtgraph 弃用 warnings；在最后极小隐藏恢复增强之前运行 |
| settings 独立复查 | 126 passed，保留来源/后缀识别和无 hover 断言 |
| split/routing/copy 首次集成 | 53 passed / 3 failed；3个 legacy +/- 几何失败已修复，纳入上述405通过 |
| backref/import/state ownership/no-lambda/QSS border | 28 passed |
| hints + quickref + UltraView capture | 164 passed / 1 failed（速查文案超160字）；缩短后 quickref 全39 passed，其余已通过 |
| 冻结快照 layout/geometry/single owner，含极小隐藏与 ChartStack 恢复 | 97 passed，18个既有warnings |
| 父协调者最终几何/游标/分屏/复制集成（冻结快照） | 143 passed，104 deselected，194个既有warnings；49.33s |

测试日志均保存在 `.state/cursor-table-audit/*tests.log`，不把历史 pass 与本轮通过混加成一个总数。

## 真实渲染

使用生产 `load_stylesheet(app)`、实际 `ChartStack`/canvas/`CursorPill`，独立 QSettings 文件，不改用户工程；原截图数值作为 fixture，波形仅是示意背景。第一张截图未能读取的 Δ 用缺失值 `—`，未伪造读数。

- 原生 Cocoa 渲染：三类 fixture × 窗口逻辑宽500/800/1200；另有 Time/Custom × single/dual × full/mini 八模式，PNG 在 `.state/cursor-table-audit/`。
- 最终平台记录为 `cocoa`、DPR=2。窗口800/1200逻辑像素时，长名面板512×131、短名453×138、Custom-X471×108；窗口500时长名降级为252×219。宽度为真实Qt逻辑尺寸，PNG物理像素为2倍。
- `render_chartstack.py` 为可重复探针，`chartstack-metrics.json` 记录外框、detail及layout plan。短名与读数同行、长名两行及最右完整、Custom诊断/双方向在表内已目视检查。
- production QSS geometry tests 比较同一个 paint document 的全局 glyph bounds 与实际 contentsRect，并检查同行和列对齐；不再用另外的强制换行文档证明不裁切。
- `pill-long-500.png`、`pill-short-dual-full.png`、`pill-custom-dual-full.png` 是本轮实际 QWidget.grab，不是 HTML 或生成式示意图。

## 平台门槛和范围

| 门槛 | 状态 |
|---|---|
| offscreen focused 行为/实际文档边界 | 已通过批次如上；最终集成结果见上表 |
| macOS Cocoa 真实 ChartStack 渲染 | PASS：独立fixture实例，生产QSS |
| 用户当前加载工程，重启后前台交互 | UNKNOWN：未重载用户工程；Computer Use 按应用定位命中了既有旧实例，独立实例定位超时，不能替代新代码前台交互验收 |
| Windows 100%/150%/200% 字体与冻结包 | UNKNOWN：未运行 |

`git diff --check`、本轮文档链接检查通过。新增 lesson 已提升，lesson_required=False。最终源码 SHA256 见 `.state/cursor-table-audit/final-source-fingerprint.json`。

修改展示 owner 与文案，不改 DSP/Δ算法、文件数据、项目schema或用户QSettings。前次 `stack.py`/`_view_mixin.py` 的相关未提交改动保留；本轮 stack 仅补空间不足隐藏后重新布局的恢复入口。未 commit/push。
