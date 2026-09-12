# Cursor 表格可读性验证记录

> 前次执行的历史记录。以下 pass 未拦住用户三张截图中的缺陷，不代表本轮完成；当前验证见[全模式修复验证](2026-09-12-cursor-rendering-parity-repair.md)。

- 日期：2026-09-12
- 范围：Time-X 双游标共享统计表、宽度降级、分屏 pane 边界、legacy detail 兼容与用户文案。
- 基线：`82948f02` 加本任务未提交改动；无关未跟踪 `ssh-keygen` 未读取、未修改。

## 已验证

| 证据 | 结果 |
|---|---|
| 布局、真实 Qt 富文本几何、设置、single/source/formatting、分屏路由、文案、状态所有权与 lambda 连接 | `364 passed, 214 warnings`（offscreen） |
| 本轮“按真实网格收缩 + 完整形态统一为分组表格”后的 layout/geometry/settings/single/formatting owner 回归 | `211 passed, 88 warnings`（offscreen） |
| 本轮最终 layout + 实际 Qt geometry 再确认 | `38 passed, 2 warnings`（offscreen） |
| 100 次宽/短数值交替更新的列边缘稳定性 | `1 passed`（offscreen） |
| ChartStack cursor pill、圆角与 copy/compositing 相关节点 | `20 passed, 127 deselected, 28 warnings`（offscreen） |
| UI import boundary 与 signal no-GUI-import | `11 passed` |
| `git diff --check` | 通过 |

覆盖的关键合同：共享数值列右边缘；640/60%/360 宽度预算；长名中间省略、缺失值和单位位置；primary 先到后的预算；分屏各自 canvas safe rect；拖动分割条重算；仅 legacy cursor 信号的 full/mini 兜底；结构化 rows 的单次投影优先级。

## 未验证

- macOS 前台 TraceLab 的实际字体、像素圆角、宽/窄/非等宽分屏。
- Windows 100% / 150% / 200% 缩放与字体 fallback。

以上为平台接受门槛，当前状态均为 **UNKNOWN**；offscreen Qt 不替代它们。
