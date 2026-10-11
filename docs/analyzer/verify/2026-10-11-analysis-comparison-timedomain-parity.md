# 分析对比视图：共享操作与独立状态实施验证

- 日期：2026-10-11。
- 状态：核心修复已实施；验收 **PARTIAL**。用户原始报错项目、完整人工长链路及 Windows fresh Full/Lite frozen 未验收。
- 基线 HEAD：`4667dd06c98d624b6d5e5663eeb69e4b8911e60e`。工作区已有版本、dB reference、FRF、色图及帮助改动；没有回退、提交或推送。
- 合同：[spec](../specs/2026-10-11-analysis-comparison-timedomain-parity-followup-spec.md)、[plan](../plans/2026-10-11-analysis-comparison-timedomain-parity-followup-plan.md)。
- 并行分工：共享 card/toolbar，tabbar 颜色与菜单，参数/右键/持久化三路；主执行者整合 stack、Inspector、帮助和验收。

## 修复与根因

| 项目 | 实施结果 |
| --- | --- |
| F1 重复工具栏/提示带 | peer 和同 View 第二 pane 统一接入共享 toolbar；保留控制器，隐藏各 card 的额外 chrome |
| F2 动作错侧 | page 统一 focused_card；Home、标注、清除、选项与游标解析实际 View/pane；stack 的标注 setter/relay 同步修正 |
| F3 模式/历史遗漏 | pan/zoom 双向广播覆盖可见 host/peer；每侧保留独立历史；右侧单独手势立即刷新共享 Back，拆除 peer 刷新可用性 |
| F4/F5 颜色错误 | tabbar 只读 provider 解析分析对比关系，复用半色绘制；peer 保持实色，焦点条采用所属 View 色 |
| F6 card 遍历遗漏 | 新增非懒创建 all_cards，stack 游标 card 归属、刻度控件和实际 canvas 刻度更新均纳入 peer；peek_cards 保持 host-only |
| U1 参数入口误导 | 独立 View 对比为主入口；旧窗格更名“同参数窗格”，菜单明确 host 名；Inspector 现有标题显示当前 View/窗格 |
| 新增：保存旧输入值 | 保存/切换绑定前通过编辑器自己的 focus-out 验证提交；非法输入保留上个有效值及错误提示 |
| 新增：显示改动排队计算 | dB 参考编辑使用 cache-only 刷新；延迟动作保留编辑时的 View 身份，避免换焦点后重路由，兼容 Auto→Manual 提交顺序 |
| 新增：标注回显反向关闭 | FFT 隐藏 remark 参数投影阻断用户信号，按目标 card 实际标注状态回显；A/B/A 与同侧右键保留模式 |
| 新增：peer Pin 重开不显示 | 真实 P 键记录归 peer，关闭后状态保留；只在新 peer 画布挂载时恢复 overlay/pinned collection，避免常规缓存重画覆盖尚未捕获的实时标注/游标 |
| 新增：窄窗口当前标签消失 | 收起比较动作到“对比选项”，为 active tab 的色块、文字及命中区域预留实际宽度；宽窗恢复原按钮 |
| U2 右键 | 四模块 host/peer 主图、FFT预览、热图切片、FRF三行实际弹菜单并执行 Zoom；标注模式右键删除手势仍保留 |

标注右键的分析 owner 是 `pg_canvas/remarks.py::RemarkInteraction.handle_mouse_press`。初版 spec 引用时域 `viewbox.py::_delete_remark_from_context_event` 不准确，已更正。用户当次是否开启标注模式仍 UNKNOWN；不能据普通菜单通过断言原路径已完全重现。

## 失败先行与现有回归

证据目录：`.state/analysis-comparison-followup-20261011/` 和 `.state/analysis-comparison-implementation-20261011/`。下列计数是各次运行原始结果，存在交集，不相加充当唯一总数。

| Gate | 结果 / 范围 |
| --- | --- |
| 最终稳定集成 | **252 passed,469 warnings in57.20s**；四个新增交互/state/stack/tabs合同、既有comparison两文件、ownership/lambda、hints/help。`stable-integration.log` |
| 最终 Pin Cocoa | **4 passed,23 warnings in2.97s**；真实P键、source身份、close/reopen新canvas恢复、现canvas重画不覆盖记录。`cursor-cocoa.log` |
| 初始 chrome 正确行为断言 | 16 failed，覆盖四模块重复 chrome、错误目标、模式及焦点色；修复后通过 |
| stack card/刻度控件 | 4 failed → 4 passed |
| stack 标注 relay/实际刻度 | 8 failed + 4 passed → 父级综合门禁 111 passed（含12个stack测试、ownership、hints、help） |
| 历史布局两个 node | 当前树均通过；未修改 FRF 三行和 FFT-time 对齐算法或放宽阈值 |
| chrome owner 阶段 | 120 passed，1个旧标签文案断言失败；更新受影响期望后通过。后续历史/确认竞态补测分别通过 |
| 共享边界与时域焦点 | 32 passed；import、lambda ratchet、split focus 等（chrome-boundary.log） |
| 标签 owner 阶段 | 144 passed，8个旧标签文案断言失败；更新对应期望后11个受影响节点通过；新增9项Cocoa像素/关系测试通过 |
| Pin 生命周期补修 | cursor + test_frf_pinning + test_pinned_cursor_panels：39 passed,95 warnings in10.72s；首次新canvas挂载恢复，不在日常重画重放旧state |
| 参数/事件新增合同 | offscreen 41 passed；最终 Cocoa 41 项加 analysis_view_bridge 17 项，共58 passed,65 warnings in22.48s |
| Inspector 现有布局/宽度/控件 | 305 passed，包含首次显示、回入、宽度限制；新目标标题原生截图另检 |

**现有独立失败**：`tests/ui/test_analysis_multiview_integration.py::test_fft_time_chart_options_restore_reverts_range_and_color` 预期 `gnuplot2`，当前恢复为 `tracelab.head-style.v1`。在独立进程中把本轮修改的六个 AnalysisMixin 方法换回 HEAD 实现后同样失败，证明不依赖本轮 mixin 修改。本轮不改当前色图迁移合同、不 skip/xfail，不将其算作通过。

## Cocoa 原生与输出证据

父级使用生产字体、Fusion/QSS、真实 MainWindow 和双来源合成 CSV（5000点，1000 Hz，speed/torque）在 `QT_QPA_PLATFORM=cocoa` 运行四模块验收：初轮 **4 passed, 15 warnings in 9.65s**；稳定源码补窄窗几何断言后的最终运行 **4 passed, 15 warnings in 9.46s**。通过生产 do_fft/do_fft_time/do_order_time/do_frf 分别算 A/B；图像包含实际结果。

验证真实 viewport 点击、焦点参数提示、普通右键菜单→Zoom、共享 Home、单一 toolbar、peer 焦点色，以及组合图真实 PNG 保存与复制信号。保存/复制图尺寸均为 `3740×3572`；当前证据证明尺寸与范围路径一致，不冒充逐像素完全一致或全部读数正确性。

截图存于 `.state/analysis-comparison-implementation-20261011/native/`：四模块 `*-wide.png`、`*-narrow.png`，`*-export.png` 和 JSON。已人工检查 FFT、FFT-time、Order、FRF 渲染：原始重复 toolbar 消失；半色标签和 peer 绿色焦点条正确；FRF 三行、热图切片起点对齐；Inspector 目标标题未与 SISO 徽章重叠。初轮 Order 窄窗截图发现当前标签被按钮挤掉；修复后检查实际 tabRect 可见宽度与色块，截图可见当前标签及“对比选项”。最终窗口四模块的 active tab 实际可见宽度均通过至少40px断言；正式几何回归还检查色块完整命中、菜单动作及宽窗恢复。

## AC 状态与剩余边界

| 合同 | 已有证据 | 未覆盖 / 限制 |
| --- | --- | --- |
| AC1 | 四模块共享 toolbar；1+1/1+2/2+1/2+2 动态 chrome/mode 回归 | 全部组合的双平台原生像素矩阵未穷举 |
| AC2 | 真实 peer 点击、真实 Home 相机、标注、清除确认竞态与 stack relay | 完整人工快捷键/菜单长链路未穷举 |
| AC3 | 窗函数、数值、预设、来源/时间、dB pending save/reopen、非法值与显示不提交DSP | 每一控件组合的穷举矩阵未做 |
| AC4 | 主图/预览/切片/FRF子图普通菜单；标注删除模式独立覆盖 | 用户原项目及当次操作顺序 UNKNOWN |
| AC5 | provider身份/改色/改名/重排/删除/溢出与DPR1/2像素 | Windows像素 UNKNOWN |
| AC6 | 模式、各自历史、联动原回归、真实保存复制与现有布局 | 输出未做全部已知读数像素差分 |
| AC7 | 动态 panes、关闭/替换/删除、保存重开、迟到结果既有对比回归；FFT/FRF真实P键及close/reopen归属 | 长时间压力及所有源卸载组合未穷举 |
| AC8 | offscreen、Cocoa、原场景、Windows 分开记录 | 用户原场景/Windows frozen UNKNOWN；无发布结论 |

集成中另遇到一个旧测试要求比较按钮始终可见；更新为紧凑菜单中仍可用、checked/enabled 保持原语义，单节点通过。首次集成期间 page 最后收口，源指纹变化，因此其结果不充当最终稳定快照证据。

没有运行全仓或全量 tests/ui：本次是已有 owner 的局部接线与输入事务修复，使用 focused、适用边界及原生窗口验收。项目 schema、DSP 算法、版本号没有本轮改动。帮助四指南、用户指南、hints/quickref 已同步新交互；新增验证型编辑器提交 lesson，未重复既有 pane-local/视觉 lesson。

## 变更范围与收口

产品修改位于 `analysis_section_page.py`、`chart_stack/{stack,toolbar}.py`、`view_tabbar.py`、`inspector.py`、`main_window/{_analysis_mixin,window}.py`，加对应 hints/quickref 与帮助段落。新增五个 `test_analysis_comparison_*_contract.py` / `test_analysis_comparison_tabs.py` 测试文件；既有测试只调整同参数窗格名称及窄窗菜单可达语义。现有非本轮改动保留于 `.state/analysis-comparison-implementation-20261011/preexisting.patch`。

源快照见 `source-stable-before.json` / `source-stable-after.json`；HEAD和产品源哈希一致。期间唯一变化为未纳入252项命令的 cursor测试文件新增保留live pin断言，该文件随后单独Cocoa 4项通过；日志与截图是本地证据，未加入 Git。文档相互链接检查通过。`git diff --check` 干净，lesson_required=False；未commit/push。
