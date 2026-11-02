# 剩余回归失败与 Qt teardown 修复验收

日期：2026-11-03。对应[执行计划](../plans/2026-11-03-regression-recovery-plan.md)。本轮接续导入修复提交 `0a9393bf`；该提交已进入 `main` 并推送，服务器 ref 已读回确认。

## 修复与证据

| 分类 | 已确认原因与处理 | 验证 |
| --- | --- | --- |
| 解绑后旧结果重现 | draft 来源清理没有撤销 accepted binding；现在同时检查已接受请求、清除受影响绑定并推进 revision，拒绝晚到结果 | 4 类来源角色红测后通过；其他 View 和共享 cache 保持 |
| FFT-time 错误反馈丢失 | 失败路径将 generation token 与 `id(pane)` 比较；改为与 dispatch/success 相同的 generation | 有效失败显示反馈并保留旧图；过期 token/revision 不串状态，3 项通过 |
| View 标记、FFT 历史、配色恢复 | focus/deferred fit 提前 snap；计算绘图未记录 retained signature；policy 重绘覆盖 cmap | 只在布局改变时重定位标记；只有当前焦点 canvas 可登记 signature；policy 重绘之后应用 cmap |
| 非焦点 FFT 绘图 | 集成审查补出的 split/comparison 红测证明，非焦点绘图不能登记全局焦点签名 | 收窄后 retained/peer/ownership 13 项通过 |
| 两个正式 teardown error | 旧 restore spy 只接收两个参数，实际回调有第三个 `rendered_ids` | 按真实签名透传，旧正式失败名单复跑零 error |
| deleted-controller 回调 | `partial(bound_method, key)` 没有 QObject receiver 生命周期；canvas 后销毁仍回调已清理的 controller | 改为 controller 子 receiver 与弱 owner；新增 7 项通过；Cocoa/debug allocator 四种销毁组合正常退出 |
| 旧测试合同 | cache-only fixture 没有 accepted request；async stub 缺请求字段；lazy 页面未进入；配色默认/回退和 token QSS 读取未区分 | 使用真实 request/result/source；保留数据身份、无隐式计算和缓存驻留断言 |
| 样式与 Batch 工具 | parity 无效 cmap 使用默认值而非回退值；Batch 用户 reference fixture 未覆盖实际有效目录 | 使用既有 `force.si / N` 用户覆盖；表达式颜色 token 化，完整展开 QSS 字节不变、208 色预算不变 |

原 5 项完整会话专有 hover/pin 失败已定位：`test_dialogs.py` 中未交给 `qtbot` 管理的可见 canvas/dialog 跨测试存活。完整门禁现场显示 PillSwitch 的 hit-test、焦点、样式、按钮状态都正常，但 `underMouse()` 始终为 false；新 pinned cursor 没有收到鼠标移动，按钮读数为 None。独立快照用真实 1200×800 canvas 前序加 5 个目标，稳定复现 **1 passed、5 failed**；接收者追踪确认鼠标移动进入旧 canvas。注册该 canvas/dialog 后同组 **6 passed**。

完整 creating-owner 验证进一步发现同文件另外 5 个创建者也遗留窗口，因此最终只在这 6 个测试注册 canvas/dialog（包括样式循环中的每个 dialog）。三个完整文件随后 **111 passed**，有/无诊断插件均通过，正常 teardown 后没有新增可见窗口遗留。没有强制 hover、修改目标断言或做全局 widget 清理。这是测试会话的窗口所有权问题；独立的 deleted-controller 产品缺陷另有确定性销毁回归验证。

完整门禁另外发现两项 FFT-time 测试仍用 `id(pane)` 伪造回调 token。它们分别未能标记 stale、未能推进 hidden View revision，与真实 dispatch 的 generation token 不符。只更新两处 fixture：FFT-time 使用生产 token helper，Order 保留自己的 id 合同；整个 owner **23 passed**，原有 hidden/edited/deleted 断言不变。

## 门禁结果

- **原正式 69 个失败节点统一复跑：69 passed，59 warnings，46.08 s，exit 0**。原 compute-revert 节点改名，明确要求显式 Calculate；旧结果身份/缓存对象保持且没有隐式 worker 提交。前后源码指纹一致。
- analysis/View worker：62 项修复集、63 项边界集通过；后续新增 peer 风险单独 13 项、真实来源 failure-token 3 项通过。
- 非 View worker：105 passed；有效目录 fixture 修正后当前工作区和独立 HEAD 目录模块各 1 passed。QSS 完整展开 SHA-256：`5d4ed6141114833a243900a3196456f11cb8b8c1ac59bcac82a369de2ce0195f`，与修复前相同。
- 生命周期 worker：76 passed、4 skipped；Cocoa + `PYTHONMALLOC=debug` 子进程 exit 0，四种创建顺序/parent 组合没有回调异常。
- 实际 Cocoa widget：marker/history/chart-options 4 项通过；生产样式 marker、peer signature、history 4 项通过。已检查实际 AnalysisSectionPage 截图中的 View 标记和 tab 几何；空 canvas 为测试场景，不代表真实数据图渲染验收。
- **纯暂存快照专项：198 passed、1 skipped，68.04 s，exit 0**。包含原失败集、新回归、Qt 生命周期及实际触及的 import/packaging/ownership/QSettings/border 边界。
- **完整主套件（最后两份测试 fixture 补丁写回之前）：14,201 passed、7 failed、71 skipped、3 deselected，0 errors，3:55:38，exit 1**。7 项与上述两个 token fixture 和 5 个鼠标递送失败完全一致；无 deleted-wrapper RuntimeError/teardown traceback。HEAD 与全部文件指纹前后一致。不能将此结果称为全套通过。
- **独立采集 UI：369 passed、2 skipped，16.30 s，exit 0**。在主套件正常退出后另起进程运行，前后快照一致。
- **最后两份补丁写回主工作区后：四个完整 owner 文件 134 passed，14.59 s，exit 0**，无诊断插件；前后源码指纹一致。原有行为断言全部保留。

最后收敛仅修改两个测试文件的真实 token/窗口所有权。按已复现根因复测完整创建者及受影响消费者，全部已知失败已闭环；未重复运行约四小时的主套件，最终全量绿色结果不作宣称。

本轮未改数学算法、全局 conftest 或测试顺序，没有提高 ratchet、增加 xfail 或吞掉异常。原有版本、dB reference、帮助与 Windows 脚本改动未混入提交。使用 `0a9393bf + 本轮任务差异` 导出的纯暂存快照额外检验未发布功能依赖。

## 证据范围

`.state/regression-followup/` 保存原失败名单复跑、纯暂存快照及最终完整门禁的命令、日志、JUnit、前后源码指纹。`.state/import-recovery/` 保存 worker 红/绿测及 Cocoa 证据；`pointer-triage/` 保存 5 项会话探针和 controller 生命周期复现。

offscreen、独立 Cocoa widget 和用户当前运行实例是不同证据。此次未替换或重启用户当前 TraceLab 实例，未执行 Windows Full/Lite frozen 验收。五项会话失败的结论来自完整现场、真实前序最小复现及所有权修复后的红绿对照；CPU 采样只证明当时消耗在 Qt 全局样式应用，不能据此宣称修复了全部测试性能问题。
