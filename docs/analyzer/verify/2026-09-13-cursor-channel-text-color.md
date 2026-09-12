# Cursor 通道文字颜色补充修复

- 基线：`9132efe0`；用户要求读数文字跟随通道颜色。
- 根因：共享表格的名称/值固定为 `#111827`，单位/方向/诊断也覆盖了通道颜色，只有色点使用 `block.color`。
- 修复：名称、读数、单位、方向和所属诊断统一使用各通道颜色；公共表头、指标标签、摘要保留中性色。缺少通道颜色时保留原深色 fallback。
- 同步修订现行 spec 与修复计划中的颜色规则；HTML历史示图不代表这次用户补充要求。

## 验证

新增回归先失败：实际paint document中的 `Steering` 文字为 `#111827`，预期 `#008577`。

- 全八模式 × 三宽度（320/500/1200），同一identity连续改色，检查实际paint document的名称/单位/值/方向/诊断foreground及glyph containment：24 passed。
- `test_cursor_table_modes.py + test_cursor_table_geometry.py`：615 passed，4个既有NumPy弃用warnings，36.80s。
- Cocoa生产QSS、实际ChartStack，三类fixture与full/mini渲染后目视核对；证据在 `.state/cursor-color/`，测试日志 `.state/cursor-color-tests.log`。
- `git diff --check`通过；既有lesson补充实际文字颜色与同identity改色检查，lesson_required=False。

未改数值计算或布局尺寸。用户当前工程未重启验收、Windows未验收；Cocoa为独立fixture实例。此补充修改尚未提交。

## 同日补充：双游标 mini 隐藏名称

用户要求双游标收起态与单游标一致，隐藏名称，仅用色点识别通道。结构化表格及其兼容HTML均隐藏通道名/来源，宽度计算也不再预留名称；保留读数、单位、颜色、Custom-X方向与诊断，展开恢复名称。指标优先级和复合identity不变。

- 先复现mini仍包含Long_channel的失败，再验证Time/Custom的full→mini→full内容/宽度恢复，两项通过。
- 模式矩阵、geometry、settings、single pipeline、quickref、hints合并执行835 passed / 2 failed；两项失败均为提示文案的宽度与mini措辞约束，缩短文案后hints全46 passed。代码与布局其余门禁已通过，不将重叠批次相加。
- Cocoa生产QSS的真实ChartStack单/双与full/mini渲染位于 `.state/cursor-mini/`；已检查双游标mini无名称且尺寸收窄。用户原工程前台及Windows仍未验收。
- spec/plan、hints/quickref已同步；`git diff --check`通过。与前述颜色修复一起保持未提交。
