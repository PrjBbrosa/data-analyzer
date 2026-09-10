# 四项交互的本体模拟

日期：2026-09-10。交付范围仅 HTML 与对照截图，不修改产品实现。

入口：[本体模拟](2026-09-10-native-interaction-context.html)。顶部切换当前代码逻辑 / 拟接入效果；仅保留通道搜索、Batch 失败详情、小开关、View 标记四项。

## 当前路径与拟接入边界

| 场景 | 当前实际路径 | 拟接入内容 |
|---|---|---|
| 通道搜索 | 主窗口左侧文件区下方。关键词匹配通道名，已选按钮与关键词取交集；全选只作用于可见项；眼睛控制时域显示。过滤会展开匹配分组。 | 搜索零结果提示；清除筛选恢复此前分组展开和滚动位置，不改变勾选和显隐。 |
| Batch 失败详情 | 批处理三栏底部紧凑汇总。旧 TaskListWidget 保留事件/产物模型，但已隐藏且不加入可见布局；不能将其 tooltip / 双击当作现有入口。结束时有结果提示。 | 汇总旁新增查看详情，在底栏上方临时展开逐项结果。诊断必须来自真实运行结果；只有可确认归属的错误提供定位，未知错误仅提供诊断。 |
| 小开关 | Batch 左侧预处理；中部时域图内统计；时频/阶次谱图切片。开关直接更新配置/参数区，计算只由预览或运行触发。关闭保留子参数；运行锁住三栏及方法选择。 | 接入已有 160 ms 呈现能力。禁用、导入方案、程序恢复直接定位。时域 Inspector 滤波的关闭是禁用子字段，Batch 是隐藏子字段，不能混为一谈。 |
| View 标记 | 主图底部 View 栏。先紧凑编号，再收起尾部，当前 View 不被收起；管理入口总是存在。单个 View 不可单独删除；关闭全部重置为一个默认 View。 | 仅 2 px 底部标记 140 ms；增删、布局改变、重排、恢复直接定位。新建默认空 View，是否自动加入文件由用户实际设置决定，本示例采用未自动加入。 |

## 源码核对点

- `mf4_analyzer/ui/widgets/channel_tree.py`：`_apply_filters`、`_all`、`_none`、`_sync_empty_state`、`set_channel_visible`。
- `mf4_analyzer/ui/drawers/batch/sheet.py`：TaskListWidget 创建后的 `hide()`；`_on_runner_progress`、`_on_thread_finished`、`lock_editing`、`unlock_editing`。
- `mf4_analyzer/ui/drawers/batch/task_list.py`：模型保存逐项状态、tooltip、产物，当前不提供可见入口。
- `mf4_analyzer/ui/drawers/batch/filter_panel.py`、`slice_panel.py`、`chart_statistics_panel.py`：开关、摘要、参数展开与恢复。
- `mf4_analyzer/ui/widgets/pill_switch.py`：44×24 几何、默认 POLICY_OFF、禁用/隐藏/阻断信号时直接定位。
- `mf4_analyzer/ui/view_tabbar.py`：`_retire_tail_tabs`、`_set_overflow`、`_overflow_rows`、`_relocate_marker`。
- `mf4_analyzer/ui/view_state.py`：`delete_view`、`reset_to_single_default`；时域上限由 manager 指定（24），分析 View 仍为 12。

## 演示数据及证据边界

截图在本次会话使用当前工作树启动独立 Qt / Cocoa 窗口生成，隔离 QSettings；不是直接操作用户已经打开的项目。主窗口读取合成 CSV，Batch 对照截图为空配置，仅用于校准真实三栏、控件、底栏位置。

HTML 的 Sweep 文件、曲线、成功/失败/跳过结果均为示例，不声称来自用户文件；失败分支使用示例 PermissionError；跳过分支对照 BatchRunner 的 SkippedFrfTask：按来源可用时缺少配对输入。GUI 当前输出固定为 XLSX/PNG、冲突自动编号，故不提供虚构的冲突跳过设置入口。HTML 不读取文件、不导出产物、不模拟 DSP 正确性。非四项范围的界面内容只作为视觉上下文。

Qt 截图生成完成；日志出现已有 Microsoft YaHei 字体回退及 MethodButtonGroup stylesheet 解析警告，未修复产品源码，也不据此声明软件整体验收通过。

HTML 浏览器验证覆盖：搜索上下文/勾选与显隐分离、当前/拟新增行为区分、方法相关小开关、运行锁定/中断/恢复、任务详情定位、View 最后一个保护/新建空状态/管理入口。页面保留桌面布局，小宽度采用横向滚动，不另行设计移动版。
