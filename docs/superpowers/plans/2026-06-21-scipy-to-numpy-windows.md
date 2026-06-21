# scipy → numpy 窗函数替换 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 numpy 原生窗 + 手写 flattop 重写 `get_analysis_window`，移除 scipy 依赖，数值逐元素不变。

**Architecture:** 仅改 `signal/fft.py` 一个函数体；两阶段 TDD——先对 scipy 证等价、再冻结黄金值卸 scipy。下游契约不变。

**Tech Stack:** numpy；pytest。归 signal-processing-expert（数值改动 TDD-first）。

## Global Constraints

- 窗集合固定为：`hanning`/`hann`、`hamming`、`blackman`、`bartlett`、`kaiser`(β=14)、`flattop`，全部 `fftbins=False`（对称）。
- `get_analysis_window(name, n)` 签名/返回（float64 ndarray，长度 n）/别名/kaiser β=14 默认**不得改变**。
- 数值等价容差 `atol=1e-12`，逐元素。
- 等价性必须由测试机械守卫，不得靠人工判断。
- `signal/` 子包禁止 import PyQt5 / matplotlib.pyplot（`test_signal_no_gui_import` 守卫）。

---

### Task 1: 等价测试（scipy 仍在）+ numpy 重写

**Files:**
- Modify: `mf4_analyzer/signal/fft.py`（`get_analysis_window` 函数体，约 41-76 行；别名表 36-38 不动）
- Test: `tests/test_window_equivalence.py`（新建）

**Interfaces:**
- Consumes: 现有 `get_analysis_window(name, n) -> np.ndarray`、`_WINDOW_ALIASES`。
- Produces: 同名同签名函数，内部不再调用 scipy；新增模块级私有 `_flattop(n)`。

- [ ] **Step 1: 写失败测试**（对 scipy 证等价 + 边界）

```python
# tests/test_window_equivalence.py
import numpy as np
import pytest
from scipy.signal import get_window as _scipy_get_window  # 本阶段仍需 scipy

from mf4_analyzer.signal.fft import get_analysis_window

_CASES = ['hanning', 'hann', 'hamming', 'blackman', 'bartlett', 'kaiser', 'flattop']
_NS = [2, 3, 4, 8, 16, 31, 64, 256, 1024]


def _scipy_ref(name, n):
    key = 'hanning' if name == 'hann' else name
    if key == 'kaiser':
        spec = ('kaiser', 14)
    elif key == 'hanning':
        spec = 'hann'
    else:
        spec = key
    return _scipy_get_window(spec, n, fftbins=False).astype(float)


@pytest.mark.parametrize("name", _CASES)
@pytest.mark.parametrize("n", _NS)
def test_window_matches_scipy(name, n):
    got = get_analysis_window(name, n)
    ref = _scipy_ref(name, n)
    assert got.shape == ref.shape
    np.testing.assert_allclose(got, ref, atol=1e-12, rtol=0)


def test_window_n1_is_unit():
    for name in _CASES:
        np.testing.assert_array_equal(get_analysis_window(name, 1), np.ones(1))


def test_unknown_window_raises():
    with pytest.raises(ValueError):
        get_analysis_window('no_such_window', 16)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_window_equivalence.py -q`
Expected: FAIL —— flattop 仍走 scipy 时可能通过，但 `test_unknown_window_raises` 会失败（现状把未知名甩给 scipy，scipy 抛的是 ValueError 子类，可能通过；若通过，本步以 numpy 重写后仍须保持）。重点是建立基线。

- [ ] **Step 3: numpy 重写 `get_analysis_window`**

替换 fft.py 中 `from scipy.signal import get_window as _scipy_get_window`（第 29 行）为：删除该 import。
替换 `get_analysis_window` 函数体（保留 docstring，改实现）：

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


_NUMPY_WINDOWS = {
    'hanning': np.hanning,
    'hamming': np.hamming,
    'blackman': np.blackman,
    'bartlett': np.bartlett,
}


def get_analysis_window(name, n):
    # ... 保留原 docstring ...
    key = (name or 'hanning').lower()
    key = _WINDOW_ALIASES.get(key, key)
    if key == 'kaiser':
        return np.kaiser(n, 14).astype(float, copy=False)
    if key == 'flattop':
        return _flattop(n).astype(float, copy=False)
    fn = _NUMPY_WINDOWS.get(key)
    if fn is None:
        raise ValueError(f"unknown window: {name!r}")
    return fn(n).astype(float, copy=False)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_window_equivalence.py -q`
Expected: PASS（全部 case 与 scipy `atol=1e-12` 一致；未知名抛 ValueError）。

- [ ] **Step 5: 跑全套 signal 测试确认无回归**

Run: `pytest tests/test_fft_amplitude_normalization.py tests/test_spectrogram.py tests/test_signal_adaptive.py tests/test_signal_no_gui_import.py -q`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/signal/fft.py tests/test_window_equivalence.py
git commit -m "refactor(signal): reimplement analysis windows with numpy (drop scipy.get_window)"
```

---

### Task 2: 冻结黄金值，测试脱离 scipy

**Files:**
- Create: `tests/data/window_golden.npz`（由脚本生成，提交进仓库）
- Modify: `tests/test_window_equivalence.py`（改为对比黄金值，删 scipy import）

**Interfaces:**
- Consumes: Task 1 的 `get_analysis_window`。
- Produces: 不依赖 scipy 的等价守卫测试。

- [ ] **Step 1: 生成黄金参考（scipy 仍在时一次性运行）**

```bash
.venv/bin/python - <<'PY'
import numpy as np
from scipy.signal import get_window
cases = ['hanning','hann','hamming','blackman','bartlett','kaiser','flattop']
ns = [2,3,4,8,16,31,64,256,1024]
out = {}
for name in cases:
    key = 'hanning' if name=='hann' else name
    spec = ('kaiser',14) if key=='kaiser' else ('hann' if key=='hanning' else key)
    for n in ns:
        out[f"{name}_{n}"] = get_window(spec, n, fftbins=False).astype(float)
np.savez_compressed("tests/data/window_golden.npz", **out)
print("wrote", len(out), "golden arrays")
PY
```

- [ ] **Step 2: 改测试对比黄金值（删 scipy）**

把 `test_window_equivalence.py` 顶部的 `from scipy.signal import ...` 删掉，
`_scipy_ref` 换成读黄金值：

```python
import os
import numpy as np
import pytest
from mf4_analyzer.signal.fft import get_analysis_window

_GOLDEN = np.load(os.path.join(os.path.dirname(__file__), "data", "window_golden.npz"))
_CASES = ['hanning','hann','hamming','blackman','bartlett','kaiser','flattop']
_NS = [2,3,4,8,16,31,64,256,1024]


@pytest.mark.parametrize("name", _CASES)
@pytest.mark.parametrize("n", _NS)
def test_window_matches_golden(name, n):
    got = get_analysis_window(name, n)
    ref = _GOLDEN[f"{name}_{n}"]
    assert got.shape == ref.shape
    np.testing.assert_allclose(got, ref, atol=1e-12, rtol=0)
```
（保留 `test_window_n1_is_unit` / `test_unknown_window_raises`，它们不依赖 scipy。）

- [ ] **Step 3: 跑测试确认通过（此时仍装着 scipy，但测试不再 import 它）**

Run: `pytest tests/test_window_equivalence.py -q`
Expected: PASS。

- [ ] **Step 4: 提交**

```bash
git add tests/data/window_golden.npz tests/test_window_equivalence.py
git commit -m "test(signal): freeze window golden reference, drop scipy from tests"
```

---

### Task 3: 移除 scipy 依赖 + 打包排除

**Files:**
- Modify: `requirements.txt`（删 `scipy>=1.10`）
- Modify: `build/spec/MF4DataAnalyzer.spec`（`excludes=[]` → `excludes=['scipy']`）

**Interfaces:**
- Consumes: Task 1/2 完成（代码与测试均不再 import scipy）。
- Produces: 无 scipy 的依赖与打包配置。

- [ ] **Step 1: 删 requirements 的 scipy**

`requirements.txt` 删除 `scipy>=1.10` 这一行。

- [ ] **Step 2: PyInstaller 排除 scipy**

`build/spec/MF4DataAnalyzer.spec` 第 57 行 `excludes=[],` 改为：
```python
    excludes=['scipy'],
```

- [ ] **Step 3: 实测卸掉 scipy 后全套绿（关键验收）**

```bash
.venv/bin/pip uninstall -y scipy
pytest -q
```
Expected: 全套 PASS（证明运行/测试彻底脱离 scipy）。
> 若某无关测试因环境其它包失败，先确认与本改动无关再继续。

- [ ] **Step 4: 确认源码无 scipy import 残留**

Run: `grep -rn "import scipy\|from scipy" mf4_analyzer/ tests/`
Expected: 无输出（仅 docstring/注释里出现 scipy 字样可接受）。

- [ ] **Step 5: 提交**

```bash
git add requirements.txt build/spec/MF4DataAnalyzer.spec
git commit -m "build: drop scipy dependency, exclude from PyInstaller bundle"
```

---

## Self-Review

- **Spec coverage:** §3 窗映射→Task1 Step3；§4 两阶段等价→Task1(等价)+Task2(黄金)；§6 文件→Task1/2/3 全覆盖；§8 验收→Task3 Step3/4。
- **Placeholder scan:** 无 TBD/TODO；所有步骤含完整代码与命令。
- **Type consistency:** `get_analysis_window(name, n) -> np.ndarray(float64, len n)` 全程一致；`_flattop(n)`、`_NUMPY_WINDOWS` 命名一致。
- **唯一外部依赖顺序约束:** Task2 Step1 必须在 scipy 卸载（Task3 Step3）之前运行。计划顺序已保证。
