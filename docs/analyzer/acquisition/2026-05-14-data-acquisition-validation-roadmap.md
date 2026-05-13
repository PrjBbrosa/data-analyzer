# Data Acquisition Validation Roadmap

**Date:** 2026-05-14  
**Scope:** 整理关于 MF4 历史数据、采集连接/设置、台架验证、离线回放和整车确认降频的讨论路线。  
**Goal:** 把整车测试从日常调试手段降级为最终确认手段，减少每次小更新都上车验证的频次。

---

## 1. Core Decision

后续 data acquisition 的验证路线不应是"每次更新都去车上测"。

推荐目标是：

```text
上车调试 -> 上车确认
```

也就是说，凡是可以在办公室、离线回放、台架、模拟报文或历史 MF4 中发现的问题，都应提前发现；车上只确认真实车辆环境没有引入新问题。

---

## 2. Validation Ladder

建议将验证拆成六层，风险越高越靠后：

| Layer | Name | Main purpose | Typical trigger | Tools / Inputs |
| --- | --- | --- | --- | --- |
| L1 | 离线配置检查 | 确认配置、DBC/A2L、通道清单、采样率、触发规则可加载 | 任意采集配置改动 | 配置 schema 校验、DBC parser、单元测试 |
| L1.5 | 合成信号数值回归 | 用人工合成信号验证 FFT、滤波、阶次切片等纯算法的**绝对正确性** | 算法、信号处理、数学库改动 | numpy 合成正弦 / 扫频 / 已知阶次振动；pytest 断言峰位、幅值 |
| L2 | 历史 MF4 回放 | 用已有整车数据验证解析、绘图、指标和导出没有回归（**相对**正确性，对比上次输出） | 分析工具、通道映射、UI/导出更新 | golden / smoke 数据集 + `*.golden.json` 快照 |
| L3 | 仿真/模拟报文 | 复现边界条件：缺通道、丢帧、时间戳异常、异常值、大文件 | 解析、异常处理、触发策略更新 | `python-can` 注入修改过的 trace；`asammdf` 生成异常 MF4 |
| L4 | 台架采集验证 | 验证采集设备、线束、总线、触发、分段保存 | DBC/A2L、采样率、采集链路更新 | 同型号 DAQ + 信号发生器 + USB-CAN + CAN 回放 |
| L5 | 整车确认 | 确认真实供电、接地、噪声、总线负载、唤醒休眠和真实道路工况 | 新车型、新 ECU、新线束、高风险变更、版本验收 | 实车 |

**L1.5 与 L2 的重要区分：**

- L1.5 是**绝对正确性**——输入是合成信号，预期输出由数学定义（100 Hz 正弦输入 → FFT 峰必须在 100 Hz）。
- L2 是**相对正确性**——输入是历史 MF4，预期输出来自上一次跑出来的快照。
- 改算法时**只跑 L2 不够**，必须跑 L1.5；否则会"一致地错下去"——快照对得上但物理结果错了。

日常开发优先跑 L1–L3；采集链路变化跑到 L4；只有真实车辆环境不可替代时才跑 L5。

---

## 3. MF4 Data Asset Library

已有的大量 MF4 文件应整理成数据资产库，而不是散落文件。

每个重要 MF4 至少保留一份元信息：

```yaml
file: 20260512_x04c_low_temp_ripple.MF4
vehicle: X04C_PPV_01
platform: X04C
ecu_sw: TBD
dbc_version: TBD
test_date: 2026-05-12
scenario: low_temp_low_tire_pressure
maneuver: low_speed_steering
temperature: TBD
tire_pressure: low
issue_tags:
  - ripple
  - ttr
  - gearbox
quality: good
notes: Doffset adjusted; subjective improvement needs evidence.
sets: [golden, issue]   # 一个文件可同时归入多个集合
sha256: <hash>          # 用于跨人复现校验
```

关键是未来能按这些维度检索：

- 哪台车
- 哪个平台
- 哪个 ECU/软件版本
- 哪个 DBC/A2L 版本
- 什么工况
- 什么主观/客观问题
- 哪些通道可靠
- 是否可用于回归测试

---

## 4. MF4 Storage Strategy

不规定存储位置，半年后会出现"各人各存一份"，跨人无法复现。固定如下：

| 数据集 | 存储位置 | 理由 |
| --- | --- | --- |
| `smoke` / `golden` / 截短的 `issue` 片段 | Git LFS（仓库内 `data/golden/`） | 每个开发者能直接拉到，绑定 commit 版本 |
| `extended` / `cross_vehicle` | 团队 NAS 或对象存储；仓库内只放 SHA256 索引 + manifest 条目 | 大文件不进 git，但可按 hash 校验一致性 |
| `stress` / `bad_case` | 同上 | 同上 |
| 原始全量 archive | 外部硬盘 / 冷存储 | 不参与日常流程，备查 |

**两条硬性约定：**

- `golden` 文件优先**截取 10–30 秒代表性片段**，文件量级降一两个数量级，CI 才跑得动。
- 每条 manifest 必须填 `sha256`，加载时校验，避免文件被悄悄替换导致快照漂移。

---

## 5. Recommended MF4 Dataset Split

不要每次都跑全部 MF4。建议维护几个固定集合，**一个文件可以归入多个集合**（一个 issue 文件也可以同时是 golden）：

| Dataset | Purpose | 目标耗时 | Run frequency |
| --- | --- | --- | --- |
| `smoke` | 小样本，确认文件能打开、通道能解析、图能画出来 | < 30s（3–5 个截短文件） | 每次改动后快速跑 / pre-commit |
| `golden` | 黄金样本，固定指标不应随便变化 | < 5 min | 解析、算法、导出改动后跑 / PR CI |
| `issue` | 问题复现样本，如 Ripple、TTR、低温、Gearbox 异常 | 不限 | 修问题或改相关分析逻辑时跑 |
| `cross_vehicle` | 多车型样本，确认不同车的命名、采样率、DBC 兼容性 | < 15 min | 通道映射或车型支持变化时跑 |
| `stress` | 大文件、长时间记录，用于性能和稳定性 | 不限 | 发布前或加载性能改动后跑 |
| `bad_case` | 缺通道、时间戳跳变、采样率不一致、损坏文件 | < 2 min | 异常处理、导入逻辑改动后跑 |

时间预算是**硬约束**——`smoke` 跑得不够快没人会跑；超时的集合应优先截短文件或拆分子集。

---

## 6. Signal Mapping Across Vehicles

不同车的 MF4 不宜直接按原始通道名硬比较。更稳妥的方式是建立"标准信号 -> 各车型原始通道"的映射。

**示例（仅展示概念，落地见下面的实现位置）：**

| Standard signal | Vehicle A | Vehicle B | Vehicle C |
| --- | --- | --- | --- |
| `vehicle_speed` | `Rte_VehSpdMain_vAbsAvgVehicleSpeed_xdu16` | `VehSpdAvg` | `VCU_VehicleSpeed` |
| `torsion_bar_torque` | `Rte_TAS_mTorsionBarTorque_xds16` | `TAS_Torque` | `Steer_TbarTorque` |
| `steering_angle_speed` | `calculation_vSteeringAngleSpeed_xds16` | `SAS_AngleSpeed` | `EPS_AngVel` |

### 实现位置

```text
configs/signals/
├── standard_signals.yml          # 标准信号定义（语义、单位、合理范围）
└── vehicles/
    ├── X04C.yml                  # 平台 X04C 的标准 -> 原始映射
    ├── X05A.yml
    └── ...
```

### 消费方式

- MF4 加载层（loader）一次性把原始通道按车型映射成标准信号。
- 所有上层分析、绘图、导出 API **只接受标准信号名**，不直接绑定原始通道名。
- 加一台新车 = 加一个 `vehicles/<id>.yml`，分析代码不动。
- 新增标准信号 = 改 `standard_signals.yml` + 各车型映射文件，集中维护。

否则这张表会停留在 wiki 上，代码里到处还是原始通道名，跨车回归无从谈起。

---

## 7. Vehicle Setup Baseline

第一次给某台车建立采集链路时，仍然需要上车确认。因为以下内容离开真实车辆很难完全证明：

- 供电和接地
- 接插件位置和线束走向
- 真实总线负载
- 唤醒/休眠
- 时间同步
- 安装位置和固定方式
- 噪声和干扰
- 真实道路工况

但第一次成功后，应沉淀一份车辆采集基线。

### 基线包含

- 车辆编号 / 平台
- ECU 软件版本
- DBC/A2L 版本
- 采集设备型号和固件版本
- 线束编号、接插件位置、接线照片
- 通道清单、采样率、触发条件
- 文件命名规则、保存路径、分段策略
- 时间同步方式
- 一份成功样本 MF4
- 一份车上连接 checklist
- **关键指标参考值**——例如怠速 RMS 振动范围、典型扭杆扭矩范围、关键阶次幅值范围。下次同车采集后可**自动对比判定健康度**，而不只是"肉眼看波形"

### 治理（避免基线半年后过期）

| 项 | 规定 |
| --- | --- |
| 存储位置 | 文档 / checklist / 参考值 → `docs/vehicles/<vehicle_id>/baseline.md`；照片 → Git LFS 同目录；样本 MF4 → 按 §4 存储策略 |
| Owner | 每台车指定一名 baseline owner（采集 + 工具双方各一人） |
| 刷新 cadence | 任一硬件 / 软件 / 线束变更后立即刷新；无变更时季度复核一次 |
| 失效标志 | 关键参考值连续 2 次新采集偏离 > 阈值 → 标记基线 stale，重新评估 |

后续如果这些基线没有变化，就不需要重复完整上车确认。

---

## 8. Pre-Vehicle Checklist

上车前应先完成：

- 配置文件能加载
- DBC/A2L 版本匹配
- 关键通道都存在
- 采样率设置正确
- 触发条件能被模拟
- 采集设备能正常识别
- 存储空间足够
- 录一段模拟数据后，MF4 能被分析工具打开
- 历史 MF4 回放关键指标无异常变化

这些检查通过后，再安排车上点检。

---

## 9. Bench Validation Checklist

台架或办公室可验证大部分"设置是否正确"的问题：

- CAN/LIN/Ethernet 报文能收到
- 通道换算正确
- 时间戳连续且单调
- 触发条件生效
- 文件正常分段
- 断电/重启后可恢复
- 长时间记录不明显丢数据
- 采集结果可以写入 MF4
- MF4 可被当前分析工具加载、绘图、导出

如果台架阶段已经失败，不应把问题带到车上调试。

### 最小台架配置（分阶段建，不必一次到位）

| 阶段 | 设备 | 能验证的问题 |
| --- | --- | --- |
| 阶段 1 | USB-CAN + `python-can` 回放历史 trace | DBC、CAN 解析、触发逻辑 |
| 阶段 2 | + 同型号 DAQ + 信号发生器（注入 1 路加速度 / 转速） | 通道换算、单通道完整链路 |
| 阶段 3 | + 多通道信号发生器 + 模拟温度 / 电压源 | 多通道、采样率、分段、稳定性 |

**阶段 1 几乎零成本，先把它跑起来。** 阶段 2、3 按需扩展。

---

## 10. Vehicle Quick Check

对于低风险变更，车上只做短流程确认：

1. 按照片和 checklist 确认接线。
2. 点火后确认采集设备在线。
3. 确认关键通道有值。
4. 怠速或静态转向录制 1–3 分钟。
5. 现场用 `scripts/preflight.py`（见 §16）跑一次自检，30 秒判定数据可用。
6. 保存这次点检 MF4，作为该配置版本的证据。

只有在验证低温、颠簸、车速、转向负载、Ripple、TTR、噪声等真实道路工况时，才进入动态整车测试。

---

## 11. When Vehicle Testing Is Still Required

以下情况仍建议安排整车确认：

- 新车型
- 新 ECU
- 新线束
- 新采集设备或固件
- 供电、接地、同步、唤醒/休眠相关变化
- DBC/A2L 或采样策略大幅变化
- 触发逻辑、文件分段、长时间记录策略变化
- 真实道路工况问题复现
- Release candidate 验收

以下情况通常不需要上车：

- UI、绘图、交互、报告格式更新
- 后处理算法小改且已有 MF4 能覆盖
- 通道显示名、导出字段、图表样式调整
- 已有历史数据可复现的问题分析

---

## 12. Bug → Regression Loop

正向流程是"主动积累 golden"，反向流程同等重要：**车上发现的每个 bug 都应该转成一条会失败的测试**。

固定流程：

1. 车上发现某个分析 / 采集问题（曲线异常、数值不对、文件无法解析等）。
2. 把触发问题的 MF4 截一段（10–60 秒）→ 放入 `data/golden/issue/`，manifest 标 `issue_tags` 和 `sets: [issue]`。
3. 写一条**当前会失败**的测试（断言期望的正确行为）。
4. 修 bug，让测试转绿。
5. 这条测试永久留在 `issue` 集合里，防止回归。

这是回归库**最有价值的增长方式**——比主动挑 golden 更精准，因为每条 issue 样本都对应一个真实事故，价值密度高。

---

## 13. Remote / Persistent In-Vehicle DAQ (Optional)

如果有长期测试车，可以再降一个数量级的上车次数：

- 选一台测试车，给它装一套**常驻 DAQ + 4G / WiFi 模块**。
- 配置和触发可以远程下发，数据可以远程回传。
- 行车记录式触发：持续录、按事件留（踩刹车 / 某 CAN 信号触发 → 留前后 30 秒）。
- 一次上车装好，之后大部分常规采集可以远程触发。

适用情况：长期跟踪某车型、需要高频采集异常工况、远程 OEM 协同。

门槛不高，但需要前期一次性集成投入。是否做取决于采集频次和团队规模——可作为流程跑顺后的下一阶段优化。

---

## 14. CI / Automation Hooks

文档描述的流程**必须挂到自动化里**，否则就是"应该跑但没人跑"。

| 触发时机 | 跑的内容 | 时间预算 |
| --- | --- | --- |
| Pre-commit | L1（配置 schema） + `smoke` 集 | < 30s |
| PR CI | L1 + L1.5（合成信号） + `golden` 集 + `bad_case` 集 | < 10 min |
| Nightly | 全 L2（包含 `cross_vehicle`、`stress`） + L3 异常构造 | 不限 |
| 手动 | L4 台架、L5 整车 | — |

CI 失败时除了报错，还应输出**对比图**（当前 vs golden 的 FFT / 时域 / 阶次差异），方便快速判断是真回归还是预期变更（后者需手动更新 `*.golden.json` 并在 commit 里说明）。

---

## 15. Target Workflow

按变更类型选路径，**不是每次都跑完全程**：

```text
配置 / 工具更新
  ├─ 仅 UI / 绘图 / 报告       → L1 + L2(smoke)                          → 完成
  ├─ 算法 / 信号处理改动        → L1 + L1.5 + L2(golden)                  → 完成
  ├─ 解析 / 通道映射 / 导入     → L1 + L2 + L3 + L2(cross_vehicle)        → 完成
  ├─ 采集链路 / DBC / 触发      → L1 + L2 + L3 + L4，必要时 L5            → 完成
  └─ 新车 / 新 ECU / 新线束     → 全 L1 – L5                              → 完成
```

最终目标：

- 日常小更新主要靠 MF4 回放和自动回归。
- 算法改动必须经过合成信号绝对正确性校验（L1.5）。
- 采集链路变化主要靠台架验证。
- 整车测试只用于新链路、高风险变化和最终验收。
- 每次上车后都沉淀新的可复用 MF4 和配置基线。
- 每个车上发现的 bug 都转成一条永久回归测试。

---

## 16. Next Practical Steps

按依赖顺序排列：

1. **Manifest + 集合骨架**：建一个 MF4 manifest（`data/manifest.yml`），先登记 10–20 个最有代表性的历史文件，标好 `sets:`、`vehicle`、`scenario`、`issue_tags`、`sha256`。
2. **最小数据集**：从中选出 `smoke`（3–5 个截短文件）、`golden`（10–15 个）、`issue`（按已知问题挑）三个最小集合。
3. **元信息补全**：为每个文件补充车辆、工况、软件版本、问题标签和关键通道。
4. **标准信号映射骨架**：建 `configs/signals/standard_signals.yml` + 至少 1 个车型映射文件，把 loader 改成只对外输出标准信号。
5. **两个具体脚本**：
   - `scripts/preflight.py <mf4>` —— 单文件健康检查（通道完整、采样率、时间连续、CAN 帧统计），输出红绿灯报告。可在车上立即跑，30 秒判定数据是否可用。
   - `scripts/regression.py <dataset>` —— 跑指定集合，对比 `*.golden.json` 输出快照，diff 超阈值报错；首次运行生成快照。
6. **L1.5 合成信号测试套件**：`tests/synthetic/` 下放正弦、扫频、已知阶次振动的合成测试，挡住算法回归。
7. **CI 接线**：按 §14 把 pre-commit 和 PR CI 跑起来。
8. **车辆基线归档**：把每次成功整车采集后的连接设置、照片、MF4 样本、checklist、**关键指标参考值**归档为车辆采集基线（`docs/vehicles/<id>/baseline.md`）。
9. **Bug → test 流程上线**：下次车上发现问题就走 §12 的流程，建立第一条 issue 回归。
10. **（可选）评估远程 DAQ**：根据采集频次决定是否投入 §13。
