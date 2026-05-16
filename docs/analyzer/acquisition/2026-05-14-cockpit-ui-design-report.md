# Acquisition Cockpit UI — 设计讨论记录

| | |
|---|---|
| **Date** | 2026-05-14 |
| **Branch** | `fix/acquisition-p0-truth-up` |
| **Session** | 头脑风暴 4 方案 → 落到 Approach A (Cockpit) → v1 → v2 → v3 多轮深化 |
| **Status** | 设计已基本拍板，待写实现 plan |
| **Owner** | TBD |

---

## 1 · 背景与触发

`mf4_analyzer/acquisition/` 当前是纯库 + CLI（`preflight.py` / `manifest.py` / `regression.py` / `signals.py`），`can_logger/p0/` 有 `mf4_probe` / `a2l_probe` / `vector_probe`（Win-only stub）/ `xcp_short_upload_probe`。Roadmap `2026-05-14-data-acquisition-validation-roadmap.md` 定义了 L1–L5 验证阶梯。

讨论问题：给 acquisition 配一个 Qt5 GUI，要和现有 MF4 Data Analyzer "Precision Light" 风格一致；目标不只是验证程序，而是覆盖**实际采集（live capture）**——这是讨论中期发生的关键认知翻转。

---

## 2 · 关键决定（按落定顺序）

### 2.1 方向：Approach A · 独立"伙伴窗" Cockpit

四个方案对比后选 A：

| 方案 | 选 / 弃 | 原因 |
|---|---|---|
| **A · Cockpit 独立同风格窗** | **选** | 实时采集 + 资产库 + 验证三件事都装得下，跟 Analyzer 双窗联动天然 |
| B · Analyzer 顶栏加"采集" mode | 弃 | mode 抽象本是"同文件不同视图"，硬塞 acquisition 概念冲突；FileNavigator/Inspector 要写双语义；`MainWindow` 已 1849 行 |
| C · QWizard 流程向导 | 弃 | 浏览/编辑场景是反模式；live capture 不可能塞进 wizard |
| D · 深色 Bench Console | 弃（延后）| 只为 L4 台架，当下用不上；Vector 就绪后作为 Cockpit Capture 的全屏模式 |

完整比稿见 `docs/analyzer/ui-prototypes/2026-05-14-acquisition-ui-options.html`。

### 2.2 重大翻转：Cockpit 的中心是"实时采集"，不是"事后验证"

v1 错位：顶栏 5 个 mode（资产 / Preflight / Manifest / Replay / Capture），开屏是资产库表格，Capture 被 disable。用户指出："实际采集需要窗口显示当前数据流"、"从 A2L 选好参数和变量名不就可以采集了吗"。

v2 修正：
- 主屏改成 A2L 树 + 已选信号 + 录制参数（Scene 1） / Live streaming（Scene 2）
- Preflight + Manifest 折进"录完后弹的复盘 modal"，不再是独立 mode
- 资产库降级为次要 tab "历史"

### 2.3 单窗 4 态机（v3 最终）

用户进一步指出："勾选完应该默认是 Scene 2 那个 live 状态，点采集就开始记录"——意识到 Scene 1（选信号占位）和 Scene 2（live）应该是**同一屏的不同状态**。

```
[未连接] ──连接 ECU──► [已连接·待机] ──● 采集──► [录制中] ──■ Stop──► [复盘 modal]
                              │                                          │
                              ▲────────────────────────────────────────保存/丢弃
                              │
                       (主区永远 live charts，"采集"只是开始落盘)
```

| 状态 | 中区 | 右栏 | 主按钮 |
|---|---|---|---|
| 未连接 | 灰色斜纹占位 + "未连接 ECU" | 连接前检查清单 | **[连接 ECU]** |
| 已连接·待机 | live charts streaming + REC OFF 灰指示器 | 录制预检（4 项） | **[● 采集]** |
| 录制中 | live charts + 红色脉动 REC + elapsed | 实时质量监控 | **[■ Stop & 复盘]** |
| 复盘 modal | charts 暂停在 stop 那一刻 | — | 模态弹出 |

### 2.4 砍掉 / 延后

| 项 | 决定 | 备注 |
|---|---|---|
| 顶栏 5 mode | 砍到 3：采集 / 回放 / 历史 | "采集"是默认 |
| 资产库做开屏 | 砍 | 搬到次要 tab "历史" |
| 独立 Preflight mode | 砍 | 复盘 modal 里自动跑 |
| 独立 Manifest mode | 砍 | 同上 |
| Arm 触发模式 | **砍**（用户明确不需要）| 主按钮只剩 [● 采集] |
| Replay mode | **延后** | 顶栏槽位保留，等需求长清楚 |
| Live Capture（Vector）| **延后** | Windows + Vector 硬件 + `vector_probe.py` 就绪后启用；UI 不需要再改 |
| Bench Console (方案 D) | **延后** | Vector 就绪后作为 Cockpit 的全屏台架模式 |

---

## 3 · 主屏布局规范（v3）

参考 `docs/analyzer/ui-prototypes/2026-05-14-acquisition-ui-option-a-v3.html`。

### 3.1 顶 toolbar（48 px 高）

`[A2L 选择] [DBC 选择] [输出目录]  |  [采集 ▾ 回放 历史]  ……  [REC 指示器] [● 采集]`

- 主按钮按状态变身：[连接 ECU] / [● 采集] / [■ Stop & 复盘]
- REC 指示器：未录时灰色 "REC OFF"，录制时红色脉动 + elapsed

### 3.2 健康 strip（新增 · 32 px 高）

`[● HW] [● CAN] [● XCP] [● DAQ] [● REC] …… [全部正常 · 已连接 00:01:14] [断开]`

5 个 LED chip，绿 / 黄 / 红三色 + hover tooltip 写明 backing 信息（"VN1610 drv v15.2"、"slave 0x551"、"buf 12%"……）。

**强约束：任一 LED 非绿 → 主按钮 disabled**。

### 3.3 左栏 · A2L Measurement (280 px)

```
┌──────────────────────────────┐
│ ⌕ [搜索输入框]                │ ← 固定
│ [只看已选] [有 DAQ] [最近]    │ ← 过滤 chip
│ [收藏] [组 ▾] [类型 ▾]        │
├──────────────────────────────┤
│ ★ 3 已选 · 同 event_10ms     │ ← 批量条（多选才出）
│              [批量设 raster ▾]│
├──────────────────────────────┤
│ POWERTRAIN · 4 选中           │ ← 树
│ ☑ EngSpdAvg  rpm  @ 10ms ▾   │
│ ☑ EngTrqAct  Nm   @ 10ms ▾   │
│ ...                           │
├──────────────────────────────┤
│ 12 已选 · 14.4 kB/s 预估      │ ← 底部 footer
│ 1ms × 1 · 10ms × 7 · 100ms ×4 │
└──────────────────────────────┘
```

### 3.4 中栏 · 永远 live charts

- 连上 ECU 即开始 stream（无关是否录制）
- 每张卡 56 px svg + 16 px 大字号瞬时值 + raster pill + 简短统计（μ / σ / max）
- 录制中右上 indicator 变红 + stats 切到 "since rec start"

### 3.5 右栏 · 状态相关切换（300 px）

| 状态 | 内容 |
|---|---|
| 未连接 | A2L 解析 / 硬件 / 当前选择是否可拉起 |
| 待机 | **录制预检**：CAN 负载条 / DAQ slot per event / 磁盘 / 采样事件 + 底部 verdict banner |
| 录制中 | **实时质量监控**：ring buffer / 写盘速率 / 丢帧 / CAN 各通道负载 / Recorder thread / 磁盘空间 |

### 3.6 状态栏（28 px）

state-aware：未连接显示"未连接 + A2L 信息"；待机显示"streaming evt/s + ring buf"；录制中显示"RECORDING + samples + file size + dropped + buf"。

---

## 4 · 默认值与阈值

### 4.1 搜索算法

| 输入特征 | 自动切换的模式 |
|---|---|
| `0x...` 或 hex 字符 | 地址搜索 |
| 全部是单位字符（`rpm`, `km/h`, `Nm`） | 单位搜索 |
| 其它 | 名字搜索（默认） |

**名字搜索 = token-aware + 模糊回退**：

| 排序得分 | 命中级 | 例（输入 `eng trq`）|
|---|---|---|
| 1000 | Exact | `eng_trq` |
| 800 | Name prefix | `EngTrq*` |
| 700 | 所有 token 同序 | `EngTrqAct` |
| 600 | 所有 token 任意序 | `DesEngTrq` |
| 500 | 所有 token 是 substring | `EnergyTorque` |
| 200 | Levenshtein ≤ 2 模糊 | `ang trq` |

显示前 50；命中字符高亮蓝色；模糊默认开（设置可关）。

### 4.2 过滤 chip 初始状态

| Chip | 默认 |
|---|---|
| 只看已选 | OFF |
| **有 DAQ** | **ON**（隐藏 CAL-only） |
| 最近 | OFF |
| 收藏 | OFF |
| 组 / 类型 | All |

chip 间 AND；持久化到 `acquisition_config.yaml`（per-A2L）。

### 4.3 最近 / 收藏

- **最近**：last 14 天、最多 50 个，存 `~/.acquisition-cockpit/recent.json`，自动维护
- **收藏**：右键 ⭐，per-project 存 `acquisition_config.yaml`

### 4.4 批量选择

| 操作 | 行为 |
|---|---|
| Ctrl/⌘+click | 多选切换 |
| Shift+click | 范围选 |
| Ctrl/⌘+A | 全选当前过滤结果（非全 A2L） |
| 右键 row | ⭐收藏 / 复制名字 / 复制地址 / 跳到 A2L 源行 |
| 右键多选 | 批量设 raster / 取消选 / 复制为列表 |
| 批量 raster 下拉 | 显示选中信号 events 交集；交集空则禁用 |

### 4.5 预检阈值

| 指标 | 绿 | 黄 | 红 |
|---|---|---|---|
| CAN bus load | < 60% | 60–80% | **≥ 80%** |
| DAQ slot / event | < 75% | 75–95% | **= 100%** |
| 磁盘剩余 | > 5 GB | 1–5 GB | **< 1 GB** |
| 当前配置可录时长 | > 4 h | 30 min – 4 h | **< 30 min** |
| 总采样事件 / 秒 | < 30 k | 30–80 k | **> 80 k** |

行为：全绿主按钮 normal；任一黄出 warning banner；任一红主按钮 disabled + 写明阻断原因。所有阈值在 设置 → 预检阈值 dialog 可改。

CAN 80% 是 CiA 推荐工业默认；DAQ 75% 是给 ECU 端 DAQ list 留余量。

### 4.6 录制中质量监控告警

**Ring buffer**（32 MB lock-free ring）：

| 水位 | UI | 内部动作 |
|---|---|---|
| 0–50% | 绿 | — |
| 50–70% | 黄 + 状态栏 warning | — |
| 70–85% | 红 | UI 绘图 30→10 fps（释 CPU 给 Writer） |
| 85–95% | 红 + 持续 alert | 丢最旧样本（计入 dropped_frames） |
| ≥ 95% × 5 s | — | **自动停录 + 保存已有 + 弹错误 modal** |

**丢帧**：

| 累计 | UI |
|---|---|
| 0 | 绿 |
| 1–10 | 黄 + 写入 `problems[]` |
| > 10 / 10 s | 红 + 状态栏 "建议检查 CAN 负载" |
| > 100 累计 | 弹 modal "丢帧过多 · 是否停止？"（不强停） |

**录制中 CAN load**：阈值同预检；持续 > 90% 超 5 s 弹提示。

**磁盘**：每 10 s 检查；< 1 GB 红；**< 100 MB 自动停**。

---

## 5 · 跨窗交付 Analyzer

### 5.1 架构：**同进程双 QMainWindow**（决定）

```
QApplication (一个进程)
├── Cockpit Window  (mf4_analyzer.acquisition_ui.MainWindow)
│   ├── Recorder QThread     (XCP receive → ring buf)
│   └── Writer QThread       (ring buf → MF4)
└── Analyzer Window (mf4_analyzer.ui.MainWindow)
    └── FFTTimeWorker 等 (已有)
```

**为什么不选独立进程 + IPC**：

| 方案 | 稳定性 | 效率 | 复杂度 |
|---|---|---|---|
| **A · 同进程双窗** ✓ | 高 | 最高 | 低 |
| B · 独立进程 + QLocalSocket | 高（崩溃隔离）| 中 | 高（握手 / 超时 / 协议） |
| C · 文件系统 watcher 自动开 | 中 | 中 | 中（行为不可预测） |

理由：共用 `QApplication` / 字体 / 配色 / 图标缓存——零重复加载；零 IPC；Qt worker QThread 已经把重活和 UI 隔开，单进程崩溃面已经很小；`ui_kit` 抽取本来就是为这个铺路。

### 5.2 强约束：**先保存再打开**

复盘 modal 按钮启用规则：

```
[丢弃（不归档）]                    ← 永远启用
[仅保存文件]  [保存并归档 (推荐)]   ← 主路径
[▷ 在 Analyzer 打开]                ← 保存完成前禁用 ★
```

- modal 弹出时 [在 Analyzer 打开] 灰显，tooltip "先保存"
- 点 [仅保存] 或 [保存并归档] → worker thread 落盘 + SHA + （若归档）写 manifest → 完成后点亮 [在 Analyzer 打开]
- 点击 [在 Analyzer 打开]：
  1. `QApplication.topLevelWidgets()` 找现有 Analyzer
  2. 找到 → `analyzer.load_file(saved_path)` + `raise_()` + `activateWindow()`
  3. 没找到 → 新建 Analyzer 窗口并加载

**保证 Analyzer 永远只收到 finalized 文件**（SHA 已算、manifest 已写、文件 handle 已关）——零并发风险。

---

## 6 · 性能（多通道为什么会卡 · 我们怎么不卡）

### 6.1 CANape 卡的根因

| 根因 | 现象 | 物理 |
|---|---|---|
| CAN 总线饱和 | 假装在采，实际丢帧 | 10 信号 × 1ms × 4 字节 ≈ 40 KB/s；CAN 500 k 跑到 75–90% 就丢 |
| ECU DAQ 列表溢出 | 第 N 个信号订阅失败 / 静默丢 | event_1ms 的 ODT 数典型 4–8 |
| 同线程 UI | UI 转圈点不动 | receive + decode + plot + write 在同线程 |
| 同步写盘 | 周期性顿一下 | 每样本 fwrite，磁盘 ack 慢就阻塞 receiver |

### 6.2 Cockpit 的反制

1. **预检阻断**（最关键）— 4 项任一红即 disable [采集]，并指出"event_1ms 满 / CAN 负载 92%"
2. **三线程拓扑**：
   ```
   Vector driver → [Recv QThread] → ring buf 32 MB → [Writer QThread] MF4 64 KB 批写
                                                  → [UI QThread] 30 fps downsampled
   ```
   Receiver 永远不被下游阻塞
3. **Backpressure 而非崩溃**：水位透明可视化，70% 降帧，85% 丢最旧，95% × 5 s 自动停
4. **磁盘预分配** `posix_fallocate()` — 避免文件系统扩张延迟尖峰
5. **不在录制热路径压缩** — Stop 之后后台 worker 跑
6. **UI downsampling** — 1 ms 采样不需要 1000 fps 渲染，blit 增量绘 30 fps 封顶

---

## 7 · 后续要做的事（清单，不是 plan）

### 7.1 工程预备工作

- [ ] **`ui_kit` 抽取**：`mf4_analyzer/ui/` 下的 `icons.py`、`_palette.py`、`_fonts.py`、`drawers/`、`widgets/searchable_combo.py` 提到独立 `ui_kit/`，Analyzer 和 Cockpit 都 import 它（不互相依赖）
- [ ] **A2L IF_DATA XCP DAQ_EVENT 解析**：现有 `can_logger/p0/a2l_probe.py` 只提取了 `MeasurementSummary`，DAQ event 字段还没读；需要扩展到能返回 `{measurement_name → [available_events]}` 和 `{event_name → max_odt_count}`
- [ ] **Recorder / Writer worker QThread 骨架**：可以参考 `mf4_analyzer/ui/main_window.py:FFTTimeWorker` 的模式
- [ ] **Lock-free ring buffer 实现**：32 MB 默认，水位回调
- [ ] **MF4 incremental writer**：评估 `asammdf` 是否支持流式 append；不支持则自己写裸 MF4 + 后处理转标准格式
- [ ] **配置存储**：`~/.acquisition-cockpit/recent.json` + per-project `acquisition_config.yaml`
- [ ] **Cockpit 入口**：`python -m mf4_analyzer.acquisition_ui`；PyInstaller spec 加一条目

### 7.2 待决定（设计上有歧义、需要 plan 阶段定）

- [ ] **暂停 / 分段 按钮**在录制中保留还是删？v3 mockup 有，但讨论中没说要不要。建议：暂停删（XCP DAQ 没有 graceful pause）；分段保留（操作员现场分场景常用）
- [ ] **收藏存哪里**：per-user (`~/.acquisition-cockpit/favorites.json`) 还是 per-project (`acquisition_config.yaml`)？建议后者，让"项目就该关注这些信号"跟着仓库走
- [ ] **预检阈值配置 dialog** UI 形态：模态 / 抽屉 / 设置窗的某 tab？建议设置窗 tab，跟未来其它设置共存
- [ ] **A2L 多文件 / 多 ECU**：当前设计假设单 A2L；如果一辆车多个 ECU（VCU + BMS + MCU），UI 怎么表达？暂时延后
- [ ] **断线重连**：录制中 XCP 会话掉了怎么办？自动重连 + 标记 gap，还是停录？建议自动重连 3 次失败再停
- [ ] **DBC 在 acquisition 里干什么用**：当前 A2L 路径走 XCP，DBC 是用于额外的 CAN 报文捕获？需要明确

### 7.3 可能踩的坑（值得提前评估）

- [ ] **`python-can[vector]` 线程安全**：Vector 的 driver wrapper 是否允许多线程读？文档语焉不详
- [ ] **`asammdf` 并发**：边录边能否被另一个进程 `read_only` 打开（Analyzer 在线监看）？大概率不能
- [ ] **Qt HiDPI 双窗一致性**：Analyzer 已经做了 HiDPI 处理（`app.py:_configure_high_dpi`），Cockpit 复用前要验证
- [ ] **大 A2L 解析时间**：2 000+ measurement + DAQ event 表，pyA2L 解析时长？> 3 s 就需要进度条 + 缓存
- [ ] **Linux 上没有 Vector driver**：CI 跑得过吗？要 mock 一层 `RecorderBackend` 抽象，让"合成 / replay / Vector"在接口上等价
- [ ] **复盘 modal 期间允许新一轮录制吗**：不允许 → 用户连录两次得多走一步；允许 → 状态机更复杂。建议不允许，但保存按钮按下后立即可以开下一轮

### 7.4 在写 plan 时要参考的

- `docs/analyzer/acquisition/2026-05-14-data-acquisition-validation-roadmap.md` — L1–L5 验证阶梯，定义了 Cockpit 长期要服务的场景
- `docs/analyzer/acquisition/P0_Runbook.md` — P0 hardware probe 状态
- `mf4_analyzer/acquisition/preflight.py` — 录完 modal 里直接用
- `mf4_analyzer/acquisition/manifest.py` — 归档逻辑直接用
- `can_logger/p0/*.py` — Vector / XCP / A2L 这一层
- `mf4_analyzer/ui/main_window.py:FFTTimeWorker` — worker QThread 范式参考

---

## 8 · 关联 prototype HTML（按演进顺序）

| 文件 | 是什么 | 状态 |
|---|---|---|
| `2026-05-14-acquisition-ui-options.html` | 4 方案比稿（A/B/C/D） | 历史参考 |
| `2026-05-14-acquisition-ui-option-a-v2.html` | Cockpit 第一版（以"事后验证"为中心，**错位**）| 历史参考，说明翻转过程 |
| `2026-05-14-acquisition-ui-option-a-v3.html` | **最终版**：单窗 4 态 + 健康 strip + 搜索过滤 + 预检 + 实时监控 | **主参考** |

---

## 9 · 一句话总结

Cockpit 是一个和 Analyzer 同进程、同视觉、同 ui_kit 的伙伴窗；单窗 4 态机；左栏 A2L 选信号、中栏永远 live、右栏跟着状态切（连接前检查 / 录制预检 / 实时监控）；预检阻断不可行配置、三线程 + ring buffer 水位透明——避开 CANape 多通道卡死的根因。
