# 时域滤波叠加 (Time-Domain Filter Overlay) 设计

## 背景与目标

当前时域面板可绘制勾选通道的原始波形，但**没有任何 DSP 滤波**（界面里的 "filter"
仅是通道名搜索）。主代码栈是纯 numpy，**scipy 不是依赖**（Windows 打包特意排除）。

目标：在时域面板新增低通/高通/带通/带阻滤波，对**当前已勾选的通道**滤波后，把滤波
结果**叠加**到对应时域图上，并可勾选切换"显示原始 / 显示滤波后"做前后对比。

**v1 范围 = 仅显示叠加**（方案 A）：滤波曲线只画在时域图，不进通道树、不参与
FFT/阶次/导出、不存项目。算法层与参数对象按"将来可横展为通道前处理"的方式设计，使
A→B 升级是"改连线 + 加缓存键字段"，而非重写（见 §6）。

## 非目标 (v1)

- 不做派生通道 / FFT 前处理（留作后续 B，但架构为其留好接口）。
- 不改 `channel_data` 原始样本、不动 project 序列化。
- 不引入 scipy 或任何新后端。
- 不做陷波(notch)、不做自定义任意响应（YAGNI）。

## 架构

三个解耦单元：

### 1. `mf4_analyzer/signal/filters.py`（纯 numpy，无状态、无 UI）

**方法 = FFT 频域滤波**（毫秒级、数值稳健、天然零相位；非 IIR 递归）。理由见
`docs/lessons-learned`：纯 numpy 的 IIR sosfilt 在百万级样本×多通道上是秒级，FFT 频域
是 O(N log N) 的 C 实现、毫秒级，且无极点/稳定性问题。

- `FilterSpec` dataclass：`kind`(`'low'|'high'|'band'|'bandstop'`)、`cutoff`(低/高通单值)
  或 `cutoff_lo/cutoff_hi`(带通/带阻)、`order`(int)。可序列化、可 hash（供缓存键/将来横展）。
- `butter_magnitude(freqs, spec) -> np.ndarray`：按 Butterworth 幅度响应生成频域掩码——
  低通 `1/sqrt(1+(f/fc)^(2n))`、高通 `1/sqrt(1+(fc/f)^(2n))`、带通=低通×高通、带阻=1−带通。
  实数、非负、对称，保证零相位。
- `apply(sig, spec, fs) -> np.ndarray`：反射填充(odd-reflect)压端点 wrap → `np.fft.rfft`
  → 乘 `butter_magnitude(rfftfreq, spec)` → `irfft` → 去填充。纯 numpy，零相位。
- `nyquist_guard(spec, fs)`：截止频率 ≥ fs/2 时钳制并返回 `(clamped_spec, msg)`，供 UI 提示。

**单一职责**：给定 (spec, fs, sig) 返回滤波后数组。任何消费方（时域、将来 FFT/阶次）
都调 `apply`，互不耦合。无 scipy、无递归、无稳定性问题。

### 2. 面板 UI（时域 inspector）

面板**重组为两个独立卡片**（消除"三个确认按钮"的冗余，详见 §4）：

- **卡片①「横坐标」**（从现 `图表设置` 卡拆出）：来源 / 标签 + **「应用」**按钮（保留其
  校验+缓存失效+重绑 t 轴语义，行为不变）。
- **卡片②「时间范围 · 滤波」**（合并）：
  - 时间范围：`使用选定时间范围` 复选 + `最大` + 开始/结束（行为不变，绘图时实时读取）。
  - 滤波：`类型`(下拉 低通/高通/带通/带阻) · `截止`(低/高通单框；带通/带阻动态变
    `下限/上限`双框) · `阶数`(下拉 2/4/6/8) · `显示原始`/`显示滤波后`(勾选,默认都开)。
    **无「零相位」勾选**——FFT 频域法天然零相位（将来若加因果滤波再引入此开关）。
  - 底部 **「绘图」** 按钮 = **本卡唯一提交**：点击时一并读取时间范围 + 滤波参数并渲染。
    **滤波无独立「应用滤波」按钮**（与时间范围一致，绘图时实时读取）。

**硬约束（视觉）**：滤波相关控件/容器一律**透明背景**，不得留默认灰底
（QSS `background: transparent` + 必要处 `WA_TranslucentBackground` + `paintEvent`
兜底）；字段输入框不带灰填充。真机渲染验收专门核此条。

### 3. 绘图接入（`window.py:_plot_time_on_canvas`）

现有该函数对每个勾选通道组装 `data.append((name, visible, x, sig, color, unit, fid))`
再交 `plot_channels`。改动：

- 读取面板 `FilterSpec` 与两个显示勾选。
- 对每个勾选通道：
  - 原始曲线：`(name, show_original, x, sig, color, unit, fid)`。
  - 若滤波启用：按该通道**自身 fs** 算 `filtered = filters.apply(sig, spec, fs)`，
    追加 `(name+" (LP 100Hz)"等, show_filtered, x, filtered, 同源色, unit, fid)`，
    **虚线**样式区分。
- 滤波结果按 (fid, ch, spec) 缓存；spec/通道不变则复用，不重算。

## 数据流

```
面板(FilterSpec + 显示勾选) ──┐
勾选通道 (navigator)          ├─► _plot_time_on_canvas
时间范围 (top)                ┘     │  对每通道: 原始 sig
                                    │           filtered = filters.apply(sig, spec, fs_ch)
                                    ▼
                            data=[(name,vis,x,sig,...), (name+后缀,vis,x,filtered,...,虚线)]
                                    ▼
                            plot_channels(overlay/subplot)
```

- **取消滤波看** = 取消勾选「显示滤波后」→ 该曲线 `visible=False`（`setVisible`，不重算、
  不重绘整图）；重新勾选秒回（缓存命中）。原始曲线始终在 → 即"回到无滤波态"。
- 多速率：截止频率按每条通道自身 fs 校验（`nyquist_guard`），超奈奎斯特钳制 + toast。

## 错误处理

- 截止 ≥ fs/2：钳制到略低于 fs/2 + toast 提示（不阻断其它通道）。
- 带通/带阻 lo≥hi：toast，跳过滤波（只画原始）。
- 滤波数值异常（NaN/全零/过短）：跳过该通道滤波曲线 + warning，原始照画。
- 两个显示勾选都关：允许（图空），不报错。

## 测试

- `signal/filters.py`（TDD，纯数值，可脱 UI）：
  - 幅频响应：合成多频正弦，低通后高频成分被压、低频保留；高/带通/带阻对称验证。
  - -3dB 截止点：在 cutoff 处掩码增益 ≈ 0.707（`butter_magnitude` 直接验）。
  - 零相位：`apply` 后峰位不偏移（与原始互相关峰在 0 延迟）；反射填充后端点无明显 wrap 伪影。
  - 多速率：同一 spec 对 129.5kHz / 5.4kHz 通道各按自身 fs（`rfftfreq`）映射、不串。
  - 边界：cutoff≥Nyquist 钳制；带通 lo≥hi 报错；DC bin/极短信号不崩。
- UI 结构性：两卡片拆分；滤波无独立按钮；显示勾选映射到曲线 visible；带通时双截止框。
- 真机渲染（offscreen `grab()`）：①滤波卡无灰底（透明）②原始实线+滤波虚线叠加可见
  ③取消「显示滤波后」后滤波曲线消失、原始仍在。

## §6 未来横展 (B：通道前处理 / FFT 之前) 的代价

**只需"改连线 + 加缓存键字段"，非重写**，前提是 v1 守住：`filters.py` 无状态纯函数、
`FilterSpec` 独立可序列化、在"取信号"层应用（非画布层）。届时：
- FFT/阶次的取信号入口（如 `_order_sig_for` 及 FFT 对应 helper）同样调 `filters.apply`
  —— 即"改连线"。
- 把 `FilterSpec` 纳入各分析 compute 参数/**缓存键**（否则改滤波 FFT 不重算）。项目已有
  `test_cache_key_dataclass_binding` 守卫缓存键↔dataclass 字段集，加字段机械且有测试兜底。
- 一个产品决策待定：滤波是"全局前处理"还是"按分析独立"。

## 待实施期核实的点

- `persistent_top` 跨模式共享：`self.inspector.top.range_values()/range_enabled()/xaxis_*`
  被 FFT/阶次的取信号路径读取（视图在 `_time_domain_card` 内，但取值方法是全模式共享的
  数据源）。拆卡片只能重组**呈现**（把现有的两个 group 分成两张卡 + 把滤波放进时间范围那张），
  绝不能动这些 getter 的语义/可读性，否则 FFT/阶次取时间范围会坏。
- FFT 频域反射填充长度与去填充对齐需测（端点不引入偏移/截断）。
