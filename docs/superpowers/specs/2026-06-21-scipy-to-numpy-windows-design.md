# scipy → numpy 窗函数替换 设计 (Design Spec)

**日期:** 2026-06-21
**状态:** 待用户评审
**目标读者:** 实现该改动的工程师 / signal-processing-expert

## 1. 目标

把 `scipy` 从项目依赖中彻底移除，方法是用 numpy 原生窗函数 + 一段手写
flattop 重写唯一的 scipy 调用点。**零功能、零数值、零 UI 变化**——对当前
UI 暴露的全部窗函数，输出与 scipy 逐元素一致（浮点容差内）。

回收：site-packages ~98M；打包(onedir)体积同步下降（注意 numpy 仍在，
共享的 OpenBLAS/LAPACK 不会被删，故净降略小于 98M）。

## 2. 现状（落在代码上的事实）

- **全工程 scipy 的唯一运行时用途**：`mf4_analyzer/signal/fft.py:29`
  ```python
  from scipy.signal import get_window as _scipy_get_window
  ```
  仅在 `get_analysis_window(name, n)`（fft.py:41-76）里被调用一次：
  ```python
  return _scipy_get_window(spec, n, fftbins=False).astype(float, copy=False)
  ```
- **滤波不依赖 scipy**：全量 grep 确认无 `butter/filtfilt/sosfilt/lfilter`
  等任何 `scipy.signal` 滤波调用。scipy 当前就是个"加窗器"。
- **UI/预设暴露的窗集合**（`get_analysis_window` docstring 为权威）：
  `hanning`/`hann`、`hamming`、`blackman`、`bartlett`、`kaiser`(β=14)、
  `flattop`，全部 `fftbins=False`（对称）。
- 别名表 `_WINDOW_ALIASES = {'hann': 'hanning'}`（fft.py:36-38）。

## 3. 窗函数映射

| app 窗名 | 替换实现 | 等价性 |
|---|---|---|
| hanning / hann | `np.hanning(n)` | numpy 窗本就是对称(=fftbins=False)，公式一致 |
| hamming | `np.hamming(n)` | 一致 |
| blackman | `np.blackman(n)` | 系数 [0.42,0.5,0.08]，与 scipy 默认一致 |
| bartlett | `np.bartlett(n)` | 一致 |
| kaiser | `np.kaiser(n, 14)` | β=14，I0 贝塞尔实现一致 |
| **flattop** | 手写 5 项余弦和 | numpy 无此窗，用 scipy 同款系数 + general_cosine 公式 |

flattop 实现（与 `scipy.signal.windows.flattop`，即 `general_cosine` + 标准
系数、对称分支等价）：
```python
def _flattop(n):
    if n < 1:
        return np.array([], dtype=float)
    if n == 1:
        return np.ones(1, dtype=float)
    a = [0.21557895, 0.41663158, 0.277263158, 0.083578947, 0.006947368]
    fac = np.linspace(-np.pi, np.pi, n)
    w = np.zeros(n, dtype=float)
    for k in range(len(a)):
        w += a[k] * np.cos(k * fac)
    return w
```

## 4. 数值安全策略（核心）

**不靠人脑确认等价，靠 TDD 锁死等价**，两阶段：

1. **等价证明（scipy 尚在）**：新增一个特征化测试，对 6 个窗 × 多个 n
   断言 `get_analysis_window(name, n)` 的新 numpy 实现 ==
   `scipy.signal.get_window(spec, n, fftbins=False)`，容差 `atol=1e-12`。
   先让它绿——这就**机械证明了数值零变化**。
2. **冻结黄金值 + 卸 scipy**：把上一步的 scipy 期望值落盘为一份提交进仓库
   的黄金参考（`tests/data/window_golden.npz`），把测试改成对比黄金值（不
   再 import scipy）。然后删 fft.py 的 scipy import、删 requirements 的
   scipy、删 PyInstaller 多余收集。

这样即使 scipy 被卸，等价性仍被黄金值守卫，且 CI 不再需要 scipy。

边界：`n=0` → 空数组；`n=1` → `[1.0]`（numpy 各窗与 scipy 在此一致，测试覆盖）。
未知窗名：现状是"甩给 scipy 报错"，替换后显式 `raise ValueError(f"unknown window: {name!r}")`，
信息更清晰、行为等价（都是抛错）。

## 5. 架构与边界

- 改动**仅限** `mf4_analyzer/signal/fft.py` 的 `get_analysis_window` 函数体
  + 新增模块级私有 `_flattop`/`_numpy_window` 辅助。函数签名、返回类型
  （float64 ndarray, 长度 n）、别名行为、kaiser β=14 默认**全部不变**。
- `one_sided_amplitude` 等所有下游调用者**零改动**——它们只依赖
  `get_analysis_window` 的契约，契约不变。
- `signal/` 仍然 GUI-free（只 import numpy），`test_signal_no_gui_import`
  继续绿（实际更干净）。

## 6. 受影响文件

- 改：`mf4_analyzer/signal/fft.py`（窗实现 + 去 scipy import）
- 改：`requirements.txt`（删 `scipy>=1.10`）
- 改：`build/spec/MF4DataAnalyzer.spec`（`excludes` 加 `'scipy'`，锁死打包不收）
- 新：`tests/test_window_equivalence.py`（等价测试 → 黄金值测试）
- 新：`tests/data/window_golden.npz`（黄金参考，提交进仓库）
- 无关：`tests/test_task7_characterization.py:215` 的禁词表含 'scipy' —
  那是 UI tooltip 禁词检查，与本改动无关，**保持不动**（仍然绿）。

## 7. 非目标 (YAGNI)

- 不新增任何窗函数、不改窗的数学定义、不动 UI 窗选择器。
- 不触碰滤波代码（本来就没 scipy）。
- 不为"将来可能上 scipy 滤波"预留任何东西——真要做时再加回 scipy。

## 8. 验收标准

- [ ] 全测试套件 `pytest` 全绿（含新等价/黄金测试）。
- [ ] `.venv` 卸载 scipy 后，`pytest` 仍全绿（证明运行/测试不再依赖 scipy）。
- [ ] `grep -rn scipy mf4_analyzer/` 仅剩 docstring/注释（无 import）。
- [ ] 6 窗 × 多 n 与 scipy 黄金值 `atol=1e-12` 一致。

## 9. 已知风险

- **滤波后路**：移除 scipy 后，将来上 IIR/FIR 滤波需重新加回 scipy.signal。
  已与用户确认：当前滤波不用 scipy，接受此后路成本。
- numpy 各窗与 scipy 的系数约定差异：由第 4 节等价测试机械兜底，非靠人确认。
