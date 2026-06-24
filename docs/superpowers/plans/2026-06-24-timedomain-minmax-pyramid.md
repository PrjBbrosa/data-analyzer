# 执行计划：时域 min/max 金字塔（B1）+ 滤波 FFT 快赢

- **日期：** 2026-06-24
- **设计：** `docs/superpowers/specs/2026-06-24-timedomain-minmax-pyramid-design.md`
- **状态：** 待批准。**本计划仅描述执行步骤，尚未执行。**
- **依据：** 2026-06-24 真机 profile（8 通道 × 3.16M @48kHz）。

---

## 优先级建议（按「体感收益 / 成本」）

| # | 项 | 解决的痛点 | 成本 | ROI | 范围 |
|---|---|---|---|---|---|
| **P0** | 滤波 FFT pad → fast length | **「滤波 ON 一开卡 ~8.6s」**（最大单点） | **小**（改 1 处 pad 长度 + 裁回） | **极高** | signal 算法 |
| **P1** | min/max 金字塔（B1） | **pan/zoom 卡（缩小看全程 78ms→~20ms）** | 中高 | 高 | signal 核心 + UI 接入 |
| P2 | 交互降分辨率 LOD（可选） | 拖动更跟手 | 小（接金字塔） | 中 | UI |
| P3 | 异步加载 + 后台建塔（可选） | 「打开卡 UI」体感 | 中 | 中 | UI/IO |

> **强烈建议先做 P0**：它最便宜、最直接命中用户最初「滤波太卡」的抱怨，且与金字塔
> 正交（金字塔治不了它）。P0 可独立先行落地、立竿见影。

---

## P0（快赢，独立）：滤波 FFT pad 对齐 fast length

**真因**：`mf4_analyzer/signal/filters.apply` 对 n0=3.16M 点 odd-reflection pad 到
`N = n0 + 2·(n0//10) ≈ 3.79M`（非 2 幂）→ `np.fft.rfft(xp)` 走混合基/Bluestein 慢
路径 → 单通道 1080ms、8 通道 ~8.6s。

**任务（signal-processing-expert，TDD-first）：**
1. 写失败测试：对一段「pad 后长度恰为坏长度」的信号，断言滤波结果与现有实现
   **数值一致**（这是重构，不能改滤波语义/相位）。
2. 把 pad 目标长度从 `n0 + 2·(n0//10)` 改为「**≥ 该值的下一个 fast length**」
   （`scipy.fft.next_fast_len`，若不引 scipy 则用 2 的幂 / 5-smooth 数表），FFT 在
   fast length 上做，逆变换后**裁回原长度**（多 pad 的尾部丢弃，不影响零相位/边界
   处理语义——pad 本就是为消除边界，pad 更多只会更安全）。
3. 验证：① 数值等价（与 git-stash 旧实现逐点对比，容差 ~1e-9）；② 单通道耗时从
   ~1080ms 降到百 ms 量级（perf 断言，可 `@pytest.mark.slow`）。
4. 注意：`requirements.txt` 现由另一 session（BLF）在改——若需 scipy，先确认是否已
   有 scipy 依赖（spec 里打包是 `--exclude-module scipy`，说明运行时**不**用 scipy）。
   故**优先用纯 numpy 的 fast-length 表 / 2 的幂**，避免重新引入 scipy 依赖与打包回归。

**验收**：滤波 ON 打开 8 通道，从 ~8.6s 降到 ~1s 量级；滤波数值不变（回归测试绿）。

---

## P1（主菜）：min/max 金字塔（B1）

依设计 spec §3–§6。分两个串行子阶段（数值核心 → UI 接入），中间有契约。

### P1-a 数值核心（signal-processing-expert，TDD-first）
新文件 `mf4_analyzer/signal/_minmax_pyramid.py`（纯 numpy，无 Qt）：
1. **build**：`build_pyramid(sig, factor=8, min_bucket=4096) -> Pyramid`
   - 逐层每 F 桶取 (min,max)，float32 存；记录每层步长。
   - 仅规整（单调/均匀）通道；非单调/NaN-gap 不建（调用方判定，见 P1-b 回退）。
   - 测试：层数、各层长度、min/max 单调合并正确（含 NaN 处理：层内全 NaN → NaN，
     部分 NaN → 忽略 NaN 取有限极值，匹配现有 envelope 的 NaN 语义）。
2. **query**：`pyramid_envelope(pyr, sig, t, xlim, pixel_width, is_monotonic) -> (env_t, env_s)`
   - 时间→可见源下标（均匀:除法 / 单调:二分）。
   - 选层：最粗且「可见层桶数 ≥ pixel_width」的层。
   - 层桶 → 像素桶 二次 min/max 归并，输出与 `positions_envelope` **同形**
     （交错 min/max，env_t 对齐像素桶中心/边界，与现有约定一致）。
3. **像素级等价测试（核心验收）**：合成信号（正弦 + 注入单点尖峰 + 平段 + NaN 段），
   对多组 (xlim, pixel_width)，断言 `pyramid_envelope` 与 `positions_envelope` 的
   **逐像素桶 min/max 相等**（或金字塔包络严格 ⊇ 真实窗口极值，不丢尖峰）。
4. **perf 测试**（`@pytest.mark.slow`）：3.16M 点全量窗查询 << 全扫
   `positions_envelope`（目标个位数 ms vs ~9ms/通道，且**不随 N 增长**）。

**契约（交给 P1-b）**：`pyramid_envelope(...)` 签名与 `positions_envelope` 同参同
返回形；`build_pyramid` 的 Pyramid 对象可序列化挂在 canvas 上。

### P1-b canvas/renderer 接入（pyqt-ui-engineer）
1. **存储**：canvas 上 `self._channel_pyramid = _ChannelKeyDict()`（复合键
   (data_id,name)），随 `clear()`/`plot_channels` 重建失效；与 `channel_data` 同生命周期。
2. **构建时机**：先做**惰性/首帧后**构建（首帧仍用现有全扫，避免把成本搬到打开）；
   P3 再升级为后台线程。规整性判定用现有 `_channel_is_monotonic`。
3. **查询接入**：`renderer._refresh_visible_data` 调 `positions_envelope` 处改为：
   「该通道有金字塔且规整 → `pyramid_envelope`；否则回退 `positions_envelope`」。
   - **保留** `_legacy_positions_envelope` monkeypatch seam。
   - **保留** `_effective_pixel_width`（overlay/subplot 封顶）与窄Y墙守卫
     `_is_y_overflow_wall`/`_WALL_BUCKET_BUDGET`：把它们算出的 `effective_width`
     作为金字塔查询的目标桶数（含 wall-capped 值）。**桶守卫语义不变**。
4. **测试**：
   - 接入后 `test_pg_timedomain_canvas` / `test_time_filter_overlay` /
     `test_pg_multifile_samename_curves` 全绿（无回归）。
   - 新增：有金字塔时 pan 不改变最终显示桶数（守卫不变量）；非单调通道走回退路径。
   - perf 回归：缩小看全程 pan 单帧 envelope 显著下降（用 profile 量级断言）。
5. **真机复核项**（headless 抓不到光栅，列给用户）：加载真实 8 通道文件，缩小看全程
   拖动应明显变顺；放大、缩放、切通道、滤波叠加显隐均不回归。

---

## P2（可选）交互降分辨率 LOD
拖动态查询更粗一层（`disable_interactive_quality` 已标交互态），空闲
（`schedule_idle_quality`）补全到精确层。金字塔使「取更粗层」近免费。UI 专家，接现有
idle-AA 门控。

## P3（可选）异步加载 + 后台建塔
加载（parse_head_hdf）+ 建金字塔放 QThread；UI 先给加载态，塔就绪前用全扫兜底。
改善「打开卡 UI」361ms+450ms 的体感。UI/IO，需与正在改 BLF 的 session 协调
（io/loader.py 是热点文件）。

---

## 依赖与协调
- **P0、P1-a 是 signal 专家**（数值，TDD）；**P1-b、P2、P3 是 pyqt-ui 专家**。
- P1-b 依赖 P1-a 契约；P0 独立可先行。
- ⚠️ **并发协调**：另一 Claude session 在改 BLF（io/loader.py、requirements.txt、
  _project_io_mixin.py）。P0 碰 `signal/filters.py`（不冲突）；P1 碰 `signal/` 新文件
  + `pg_canvas/`（不冲突）；**P3 碰 io/loader.py（会冲突，须等 BLF 收尾或隔离 worktree）**。
- 执行时建议：P0 / P1 在隔离 worktree 跑，避免与 BLF session 撞共享 git index。

## 验收总览
- P0：滤波 8 通道打开 8.6s → ~1s；滤波数值回归绿。
- P1：缩小看全程 pan 单帧 ~78ms → ~20ms 量级；envelope 63ms → 个位数；像素级等价
  测试绿；桶守卫不变量保持；全量 UI 套无回归。
- 真机复核（用户）：拖动/缩放跟手、各显隐与多文件同名场景不回归。
