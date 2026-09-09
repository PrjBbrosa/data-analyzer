# 控件适用条件与禁用反馈执行 Plan

日期：2026-09-09
状态：仅文档完成，尚未实施。
唯一产品合同：[Spec](../specs/2026-09-09-control-applicability-and-disabled-feedback-spec.md)

## 1. 执行原则

默认单一执行者顺序完成，不要求子代理。保持无关未提交改动，尤其已有 Batch 首显宽度修复、预设基准、分析 View 和帮助文案修改；仅编辑本任务必要片段。

当前文档 gate：完整阅读两份文件、路径与符号核对、验收覆盖、`git diff --check`。本轮无可执行变更，不运行运行时测试。

实现阶段先 owner-focused，再相关边界；不跑全量 baseline，不因共享 QSS 改动启动整个 tests/ui。每个稳定步骤已有通过结果可复用。新增失败或源文件变更才补跑对应范围。

## 2. 步骤 0：核对当前合同和测试接缝

Owner：执行者，只读核对。

- 对照 Spec §2 确认共享 QSS 优先级、动画底板、业务禁用 owner 未漂移。
- 阅读 `docs/lessons-learned/qt-composite-disabled-cues-follow-effective-state.md` 与 `batch-first-show-scrollbar-settlement.md`。
- 检查 `DynamicParamForm.get_params / apply_params / set_method`：隐藏普通 overlap 后必须保留旧参数兼容，写清测试输入与期望输出，不能让 visible_field_names 静默改变旧方案。
- 定位现有 PersistentTop 绑定 X 轴测试；优先扩展已有测试。不存在对应 owner 测试时在 `tests/ui/` 新增最小测试文件。
- 记录当前 HEAD、相关 dirty scope；检查已有 pytest 进程，避免重叠运行同一组 gate。

Gate：A1–A9 均有可执行测试或真实窗口验证入口；不扩大 DSP/持久化范围。既有 6 项 Batch smoke 失败属于前次观察，必须按当前快照确认，不能直接当作永久豁免。

## 3. 步骤 1：统一分段按钮禁用外观

Owner 文件：`mf4_analyzer/ui_kit/widgets/segmented_choice.py`、`mf4_analyzer/ui_kit/style.qss`。

先扩展 `tests/ui_kit/test_segmented_choice.py`，覆盖 A1–A3 的共享部分：自身 / 祖先禁用、选中保留、事件交互阻止、零业务信号、动画开关及中途禁用、恢复原值。使用真实按钮与渲染像素断言，不能只 grep :disabled 字符串。

实现：补齐与专用 checked 同级的 disabled / checked-disabled 覆盖；动画底板按有效禁用状态绘制并立即停止位移；沿用现有颜色 token、motion owner、圆角和透明壳。不要清除 checked 或复制业务规则。

Focused：`tests/ui_kit/test_segmented_choice.py`。
Boundary：`tests/ui_kit/test_qss_border_shorthand.py`；仅当修改共享 motion 实现时才追加 `tests/ui_kit/test_motion.py`，否则在控件测试内覆盖 motion 接口。

Gate：A2、A3；正常可用态像素不退化；两条绘制路径的禁用选中区一致。

## 4. 步骤 2：图内布局、运行锁定与 X 轴消费者

Owner 文件：`mf4_analyzer/ui/drawers/batch/method_buttons.py`；`sheet.py`、`persistent_top.py` 仅在测试证明需要时调整局部投影。

先增加分组 none ↔ source/channel、运行锁定 / 结束解锁和曲线绑定 X 轴的测试。加入字段标签的原因 tooltip，保持隐藏 combo 与可见选择一致。运行锁定测试必须使用实际生命周期入口，不仅手动禁用面板。

Focused：`tests/ui/test_batch_method_buttons.py`、`tests/ui/test_batch_smoke.py` 中相关分组/锁定/首显用例；实际定位的 PersistentTop owner 测试。
Boundary：若修改 signal wiring，运行 `tests/ui/test_no_lambda_signal_connections.py`。

Gate：A1、A4、A8；解锁不覆盖业务禁用，导入预设不清空原布局值；现有首显宽度回归仍通过。

## 5. 步骤 3：FFT 字段适用性

Owner 文件：`mf4_analyzer/ui/drawers/batch/method_buttons.py`。

先写四组合参数化测试，覆盖 Spec §4.2：NFFT / 窗长 / 平均重叠，以及方法切换、apply_params、保留值。另加旧 FFT overlap payload 的往返检查；基于现有计算入口验证隐藏字段不改变数值，不修改 numeric owner。

实现时复用当前 avg / nfft sync，让两个上游变化都刷新窗长适用性；FFT 隐藏普通 overlap，时频和 FRF 保持现状。控件值不能因为 disabled 而被清空。

Focused：`tests/ui/test_batch_method_buttons.py`；若已有 recipe 往返测试可覆盖兼容，定位并运行该具体文件/用例，不新增平行参数存储。

Gate：A5、A8；与 Spec 不符的旧字段行为先修正文档边界，不悄悄改算法。单帧窗长/重叠变化不影响数值的探针应转成有意义的回归证据，而不是测试 UI 实现细节。

## 6. 步骤 4：参考值和输出用途

Owner 文件：`mf4_analyzer/ui/drawers/batch/output_panel.py`；必要时使用 `sheet.py` 已有参数同步入口。

先扩展 `tests/ui/test_batch_output_panel.py`：Linear/dB 往返、参考模式和值保留、整组入口禁用、方法切换、signal-blocked apply、祖先锁定。扩展 XLSX/PNG 四种组合检查与可见说明的高度/换行检查。

实现 Spec §4.3–4.4。参考整组外层拥有业务禁用，内部 Auto/手动状态仍由原 owner 管理。仅数据说明放在输出区，不禁用预览仍需的设置，不声称计算范围/滤波/切片不影响数据。

Focused：`tests/ui/test_batch_output_panel.py`、`tests/ui/test_batch_settings.py`；Sheet 联动仅追加相关 smoke 用例。

Gate：A6–A8；不修改导出格式合同、输出数值、目录偏好和运行/预览 gate。

## 7. 步骤 5：帮助和真实界面验收

Owner 文件：`mf4_analyzer/ui/hints.py`、`mf4_analyzer/ui/quickref.py`，必要的最终验证记录放 `.state/`。保留这两个文件的其他在途修改。

同步禁用原因、单帧 FFT 字段和仅预览用途。不要引入另一个产品版本常量或修改旧的 dated 文档。

真实 Cocoa + Fusion 矩阵：

1. 时域每项单独，分别保留叠加、分屏；合并后恢复；hover 和键盘不能误改禁用项。
2. Batch 运行锁定与完成/失败/中断恢复；不通过真实昂贵运算获取锁定，使用既有可控 worker fixture。
3. PersistentTop 曲线绑定 / 解除绑定 X 轴。
4. FFT 四组合；FFT→时频→FFT；Linear→dB；预设导入。
5. XLSX-only / PNG-only / 两者 / 无输出；1080×760 与小窗口，说明不遮挡底部动作，长内容可滚动。
6. 动画开 / 关，以及动画中禁用。测量选中区底色、边线、文字和实际禁用交互；记录首显与稳定后宽度。

Gate：A9；截图只能说明外观，互动探针证明禁用，参数/产物测试证明语义。Windows Full/Lite 冻结验收作为独立状态列出，未跑标记 UNVERIFIED，不以 Cocoa 替代。

## 8. 集成检查与完成报告

统一 focused 命令模板：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <本步骤 owner 文件或 nodeid> -q
```

Cocoa 检查使用 `QT_QPA_PLATFORM=cocoa`，其余沿用项目环境。pytest 参数按目录成组，不依赖特定排序掩盖 fixture 问题。

- 对本次改动做 scope review 和 `git diff --check`。
- 汇总 A1–A9，不以测试总数替代验收矩阵。
- 测试失败先在当前快照用改动前逻辑对照；既有失败和新增失败分开列出。
- 不重复已通过且未受后续改动影响的 gate；无新增导入边界则不扩全套架构测试。
- 检查 lessons 状态；有新的可复用失误模式时按项目流程记录，避免重复已有禁用反馈教训。
- 最终说明改动、参数保留、focused / Cocoa 结果、未跑 Windows gate。提交或推送不属于本计划默认动作。

本轮仅交付两份文档；以上实现步骤尚未执行。
