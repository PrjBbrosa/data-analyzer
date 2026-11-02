# 剩余回归失败与 Qt teardown 修复计划

日期：2026-11-03。用户授权提交、合入主线、确认本地/远端状态，并安排 agent 继续修复剩余失败，优先定位 5 项会话相关失败。

## 已有证据与边界

- 上一轮完整主套件：14,123 passed、69 failed、71 skipped、3 deselected、2 errors，退出码 1；采集 UI 独立进程 369 passed、2 skipped。详见[验收记录](../verify/2026-11-03-import-recovery-verification.md)。
- 其中 3 个测试合同已经定向修正；本轮从剩余 61 项已复现失败、5 项会话相关 UNKNOWN 和两个 teardown 错误出发，不再重复旧全套作为 baseline。
- 原有版本、dB reference、帮助及 Windows 脚本未提交修改保持独立。上一轮导入修复已按任务差异提交到 `main`：`0a9393bf`，并推送成功；纯暂存快照专项 220 passed、12 skipped。
- 整体工作区不是干净分支，任何“本地与远端一致”只指已提交历史，不能代替未提交修改的说明。新修复测试不能依赖未纳入提交的旧工作区功能。

## 分工与修复原则

1. **会话/生命周期 agent**：优先定位 PillSwitch 两项与 pinned cursor 三项失败。初期自然前序、输入前序、重复运行与 QSS 前序未复现；完整会话采样后，已用 `test_dialogs.py` 的真实前序稳定复现全部 5 项，确认未注册的可见 canvas/dialog 将后续鼠标移动导向旧 canvas。修复实际创建者的 `qtbot` 所有权，覆盖同文件全部 6 个已证实的遗留创建者。另以确定性红测修复 controller 先销毁而 canvas 后发信号造成的 deleted-wrapper 回调错误；两者保持独立归因。
2. **分析/View agent**：先修 detach 的旧结果绑定和 FFT-time 失败的 generation token，再把缓存/异步/懒初始化 fixture 接到真实请求及接受结果合同；修复两个回调签名 teardown 错误。marker/history、chart-options 恢复须区分真实产品缺陷和旧断言，保留结果身份、曲线、事实卡、缓存 pin、无隐式计算的断言。
3. **非 View agent**：修复 parity 工具的默认/回退色图区分、带 token QSS 的测试读取、Batch 用户基准快照 fixture；表达式交互态颜色改为既有 token 家族，完整展开 QSS 必须逐字节不变，颜色预算不抬高。
4. **主协调者**：Git 提交范围、共享合同、最终集成、真实 Cocoa 验证、唯一完整门禁与远端核对。workers 不提交、不推送、不跑完整门禁。共享 conftest 如需修改，先由主协调者统一所有权。

不删除有效断言，不扩大 whitelist，不用 xfail、固定运行顺序、任意 sleep 或吞异常掩盖问题。数学公式不在本轮重设计范围。每个产品缺陷应有修复前失败证据；纯旧 fixture 同步必须引用当前源合同并验证真实行为。

## 分阶段门禁

| 阶段 | 可验证结果 | 检查 |
| --- | --- | --- |
| 5 项会话失败定位 | 有最小复现或真实完整会话的诊断状态；无证据时保持 UNKNOWN | 对应两个 owner、自然顺序诊断；比较 fixture closure，保留 Qt 状态记录 |
| View/异步修复 | 解绑撤销 accepted binding；旧 completion 不可发布；失败可见；显式计算语义不退化 | 对应失败节点及新增回归；explicit-result、View comparison、generation/token owner tests |
| Qt 销毁顺序 | 两种销毁顺序与解绑都不触发已删除 receiver 的回调 | pinned cursor 生命周期 owner；真实 Cocoa 子进程退出 |
| 样式与工具 | parity 通过；展开 QSS 字节一致；合法用户 reference snapshot 传到 runner | parity owner；compact/surface/thread；control_style、palette ratchet、border shorthand |
| 集成 | 旧正式失败名单全部复跑；新增 owner tests 与触及的边界通过 | ownership、连接 ratchet、import/packaging 边界按实际改动选择；不无条件跑全部 UI |
| 唯一完整验收 | 稳定源快照、完整结果与退出码，5 目标有定点采样 | 主协调者先查 pytest 进程并记录 HEAD/文件指纹；主套件 `--ignore=tests/acquisition_ui` 完成后另起进程跑 acquisition_ui；不并发 |
| 发布核对 | 修复范围独立提交并进入 main；远端读回与本地 HEAD 相同；原有 dirty 保留 | 暂存范围审核、干净暂存树的必要定向检查、diff check、push 与远端 ref 核对 |

有新失败才扩大定向范围；稳定集成点最多一轮完整主套件。若完整会话 5 项仍失败，依据已采集状态收敛修复后再定义新的必要门禁，不能将前面的通过项当作全套通过。

## 验收与文档

真实行为变更通过 Cocoa 验证；样式 token 化用字节等价证明无视觉改动，不能把其他 UI 变更混入该结论。Windows frozen 验收单独注明。保留 `.state/regression-followup/` 与 `.state/import-recovery/` 的命令、traceback、指纹及状态证据；最终记录未完成项。

相关 lessons：fixture/conftest 路径隔离、工具 QSS 会话污染、item pin 引用释放、accepted result binding、parentless popup/SIP 生命周期。发现新可复用模式时执行 lesson 门禁。

本计划自身只做范围、引用、一致性和 diff 检查，不因文档新增运行 runtime suite。

## 执行结果

已完成产品修复、真实 Cocoa 检查和定向/边界门禁。旧 69 失败节点统一复跑全部通过；纯暂存快照 198 passed、1 skipped。唯一完整主套件正常退出：14,201 passed、7 failed、71 skipped、0 errors，前后源码与 HEAD 一致。7 项已分别通过真实前序和实际 token 合同复现；最后两份测试补丁写回后，四个完整 owner 文件 134 passed。独立采集 UI 369 passed、2 skipped。详见[验收记录](../verify/2026-11-03-regression-recovery-verification.md)。

最后修改仅是测试 fixture 的 token 和 Qt 所有权，按根因复测完整 owner/消费者，没有重复主全套，也不把修正前的 7-failure 全量记录表述为绿色。提交保持任务范围，原有版本、dB reference、帮助和 Windows 构建改动留在工作区。
