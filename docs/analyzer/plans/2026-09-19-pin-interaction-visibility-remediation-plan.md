# Pin 牵引可见性与拖动回弹：复审及优化计划

状态：**partial（offscreen 实现已落地）**。R0–R3 的 owner 测试已在 offscreen 下通过；R4 真实 Cocoa 带数据手势与 Windows 仍为 `UNVERIFIED`。用户原始工程未在本轮复验，因此不写“已完成”。

基线：在 HEAD `82871903` 之上继续改 controller、presentation、overlay 与聚焦测试。此前的 66/13/2 passed 属于历史验证结果，不代表本计划通过。

## 1. Review findings（按优先级）

### P1 — 面板位置提交后，延迟布局仍可应用旧 anchor

证据：`pinning/presentation.py:970` `_merge_owner_snapshots` 把 collection 对象存进队列；`:1007` `_apply_pending_layout` 消费这个快照；`:1083` `_apply_pill_geometry` 对 user-placed pill 应用快照里的 anchor。`pinned_cursor_controller.py:1386` `_store_anchor_from_pill` 写新 collection，但没有同步刷新或失效旧排队快照。布局也未在该入口排除正在拖动的 pill。

本轮使用真实 ChartStack 的独立 offscreen 探针：先 `reflow_visible()` 排队旧布局，再移动面板、标记 user-placed、发出正常 `moved` 信号提交，最后消费事件队列。结果：初始 `(225,48)` → 提交 `(260,88)` → 延迟布局后 `(774,48)`；collection 中新 anchor 保持不变。这证明显示层可覆盖已经提交的用户位置，现有 release 阈值修复无法解决该路径。该探针验证状态竞争，未冒充真实鼠标/Cocoa 复现。

底部 Pn 拖动修改的是 x/ax/bx；用户反馈是否也命中这一支仍待独立复现。必须检查 capture、cancel、数据版本、最后 preview、commit、View 回投，禁止将面板 anchor 结论直接套用于底部按钮。

### P1 — 牵引路由穿过自身面板，scene 的 z 值不能跨越 QWidget

证据：`pinning/presentation.py:477` 固定取面板底边中心；`pinned_cursor_overlay.py:1713` 固定把落点放到 host 顶部附近；`:1760` 在目标高于接口时先向上走 8px。线位于图表 scene，面板是 stack 上的独立 QWidget，会盖住面板内部的所有线段。

同一探针的真实面板为 `318×66`。A 端路径映射到面板本地坐标为 `(158,65) → (158,57) → (86,57) → (86,3)`，四点全部在面板内，整条折线被面板覆盖。提高 scene z 值不能把它画到另一个 QWidget 上方。B 端也有两段在面板内。旧计划要求“朝面板外引出且不穿标题/按钮”，实现没有满足。

### P2 — 拖动过程中牵引接口不随面板更新

证据：`presentation.py:51` pill event filter 仅包含 Enter/Leave/Focus；`:499` 的 `moved` 回调对应 CursorPill release 才发出的信号。没有 Move/Resize 时的接口更新。pan/zoom 可重投影目标线，但面板拖动和即时 clamp 的 port 仍可能是旧坐标。旧测试只比较 release 后 port 不等于旧值，没有验证拖动中的几何连续性。

### P2 — “同一个 helper”仍未建立同一套实际布局尺寸

证据：`pinned_cursor_overlay.py:965,1580` 使用独立构造的 `_label_font`；`:585` widget 又用实际 caption font 测量并 `max()` 扩大自身，扩大的尺寸没有回传避让 solver；`:636` cluster member 仍是独立的 advance+8 算法。helper 横向预算依旧是原来的 +8；后来追加的垂直 +1 没有证明跨平台理由。

测试 `test_axis_label_outer_size_matches_the_painted_caption_contract` 把实际 caption 的 metrics 直接传给布局，因此绕过了生产 overlay 与真实 caption 字体不一致的接缝；仅检查横向 ink 边界，也不足以证明合图上的边框与避让矩形一致。此项为代码合同缺口，尚未量化当前机器的重叠像素。

### P2 — 完成标记和验收范围不符

原 tether 测试只查图元数量、末端 X 和 release 后 port 变化；底部拖动测试只覆盖 single、无中间 move、一个事件队列阶段。均未覆盖遮挡、排队旧布局、真实全局鼠标序列或两种拖动的后续稳定性。空数据主窗口能启动不能证明这些交互完成。

## 2. 目标与边界

沿用方案 A：小接口和细虚线，面板外的短折线连接真实位置线。保留独立 Pin、多面板、A/B 语义和现有数据求值。不上新工具条，不修改 DSP、schema 或全局状态所有权。

成功条件：快速释放后数据坐标/面板位置正确，并在排队布局、后续 reflow 与事件循环结束后保持；所有可见牵引都有面板外的连续可见路径，接口随拖动同步；真实标签外框与 solver/hit rect 一致。

## 3. 执行顺序

### R0 — 冻结失败路径和验收场景

Owner：`tests/ui/test_pinned_cursor_interaction.py`、`test_pinned_cursor_panels.py`、`test_pinned_cursor_geometry.py`，临时证据放 `.state/pin-remediation/`。

- 将上述旧快照覆盖探针转为失败回归，并补真实 QMouseEvent globalPos 序列：press → move → 排队 reflow → release → 消费剩余队列。分别断言模型 anchor 与最终 geometry；追加拖动中 reflow，不能覆盖手势中的位置。
- 底部 Pn 独立覆盖 single、A、B、A=B、A>B、簇成员、阈值内 click、无 move 快速 release、最后 move 与 release 不同位置。断言预计最终采样坐标，而非只断言“与原值不同”；脏通知一次，其他 endpoint 不变。
- 若底部问题未复现，在 `.state` 探针记录一次手势的 globalPos、capture identity、cancel 原因、版本/范围、preview/commit 以及后续 View 回投。先明确首次回退发生在哪一层，再确定修复，不添加 sleep 或放宽 stale 校验。
- 为遮挡固定一张会将 A 牵引完全盖住的真实 ChartStack 场景；渲染包含面板的最终合图，保留前后图。不能靠 item 数量替代可见性。

### R1 — 单一最新状态与手势优先级

Owner：`pinning/presentation.py`、`pinned_cursor_controller.py`；仅在事件坐标确有问题时修改 `cursor_pill.py` 或 `PinnedAxisLabel`。

- 推荐排队任务仅持有 owner 标识/布局请求，执行时经窄 ports 获取当前 collection；继续用 scope/token 拒绝已解绑和旧 View 请求，避免闭包持有旧 collection。保留布局合并，不在每个 mouse move 重排全文档。
- 当前拖动 pill 的手势位置具有优先级：reflow/自动排布不能应用旧 anchor；安全区变化按明确 clamp 规则处理。release 提交最新合法位置一次，然后使用新 revision 完成最终布局。取消只清理自己的预览。
- 对底部 Pn 根据 R0 证据修复首次回退 owner。保留末位释放坐标 flush、稳定 record/endpoint identity、Shift 精调、真实数据变更取消、offscreen toggle-only 合同。
- Gate：R0 的两条手势链路均先失败后通过；无需等待停留，无重复 dirty。先不接入视觉优化以方便归因。

### R2 — 外部路由与实时接口

Owner：`pinning/presentation.py`、`pg_canvas/pinned_cursor_overlay.py`；如修改 capture 表示，纳入 `test_pinned_cursor_capture.py`。

- Presenter 交付实际面板 rect、候选 port/出线方向、目标 endpoint、可见面板障碍矩形的纯几何 DTO；overlay 继续单独拥有 tether 图元。
- 从底/侧边向外出线，落在真实位置线上且处于面板外的可见线段；目标 Y 不固定在 host 顶部。逐段检查路径不进入本面板或其他可见面板的扩张矩形；边缘空间不足时选择另一侧/可见落点，定义确定性回退，不画假关联。
- 保持 scene 在面板下方，靠正确外部路由保证可见。端口应能在边缘外看到完整标记；只增加 z 值不是此问题的修复。
- A/B 无活动端点时共用短出线段、中性分叉；选中端点不可见时保留状态接口/tooltip，不能假装连到另一端或边缘标签。
- Move/Resize/Show/Hide 与安全区 clamp 更新 port，当前 GUI turn 内跟随，不采样、不写 collection、不触发 dirty。避免递归布局和重复全量 scene 重建。
- Gate：实际最终合图可见路径、拖动中 port、zoom/pan、full/mini、多面板遮挡、边缘、收起/close/unpin/View 切换清理，以及复制/UltraView 表示一致。

### R3 — 标签实测闭环

Owner：`PinnedAxisLabel` / overlay layout / presenter 的尺寸接缝。

- 使用经过生产样式 polish 的 caption/member 外尺寸作为 solver 的输入；按文本、font/style/DPI 缓存，相关变化失效。实际 widget 只应用已经布局的尺寸，不在布局之后静默变宽。
- 覆盖 P12·A、P12·B、P12·A/B、长文本/中文及 cluster 成员。tiny host 使用显式有限布局/展开规则，不能破坏命中一致性。
- Gate：生产路径里测量矩形 = solver rect = widget rect = hit rect；完整文字的横纵 ink 不裁切，密集矩形不交叠；检查真实 QFrame/合图，不只渲染 caption。

### R4 — 带数据的 Cocoa 验收与交付状态

- 用可重复的合成数据启动真实 ChartStack/Cocoa 场景，再用实际鼠标完成快速拖动和多面板展开。没有用户文件不构成空场景验收的理由；合成场景与用户原始工程分开记录。
- 记录正常/Retina、single/dual、full/mini 的截图和手势结果；底部轴标签、数据线、读数、面板 anchor、tether 在释放后及所有排队任务完成后均一致。
- 真实原始工程尚未验证或某链路仍回弹时，状态保持 partial，不再写“已完成”。Windows 验收在对应环境记录。

## 4. 验证预算与交付

先运行新增失败用例，再按 R1/R2/R3 owner 运行有关测试；稳定后集中运行四个 pinned owner 文件：geometry、interaction、panels、capture。追加 `test_pg_canvas_backref_invariants.py`、`test_pinned_cursor_architecture.py`；改 CursorPill 时追加相关拖动/真实几何测试，改 QSS 时追加 border-shorthand。不为本轮 UI 修复运行无关全量套件。

禁止通过增加等待、只断言图元存在、调用强制 flush 掩盖真实事件排序、调整期望值匹配错误尺寸来“修复”测试。回归使用确定事件顺序，原生验收观察持续稳定。

交付：小范围代码/回归；`.state` 的失败与修复后证据；计划逐项状态及未通过平台门。沿用 painted-document lesson；上一轮新增 lesson 中关于尺寸的说法须在实测后校正，不能把未证实的 +1 预算作为跨平台规则。

## 5. 本轮执行状态（2026-09-19）

| 项 | 状态 | 证据 |
| --- | --- | --- |
| R0 失败路径冻结 | done（offscreen） | `test_queued_layout_keeps_committed_user_anchor_and_ignores_drag_reflow`；底部 Pn 参数化（single/A/B/A=B/A>B）、阈值内 click、release 覆盖 last move；`test_tether_path_leaves_the_expanded_panel_and_follows_drag` |
| R1 最新 collection + 手势优先 | done（offscreen） | 排队只持有 owner key；apply 时 `collection_for`；拖动中跳过 `apply_anchor`；重合 dual 在 unavailable 时仍可拖开端点 |
| R2 面板外路由 + 实时接口 | done（offscreen） | `route_panel_tether` / `tether_candidate_ports`；Move/Resize 同步 port；合图路径不进入面板内缩矩形 |
| R3 标签实测闭环 | done（offscreen） | 生产 polish 的 caption metrics 进入 solver；widget 只应用 layout 尺寸；去掉未证实的 +1 |
| R4 Cocoa / 原始工程 / Windows | `UNVERIFIED` | 本轮只跑了 offscreen owner 门；未做真机鼠标与冻结包 |

Offscreen owner 门（2026-09-19）：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_pinned_cursor_geometry.py \
  tests/ui/test_pinned_cursor_interaction.py \
  tests/ui/test_pinned_cursor_panels.py \
  tests/ui/test_pinned_cursor_capture.py \
  tests/ui/test_pg_canvas_backref_invariants.py \
  tests/ui/test_pinned_cursor_architecture.py -q
```

结果：94 passed。未改 CursorPill 或 QSS，故未跑 pill 拖动合同与 border-shorthand。

