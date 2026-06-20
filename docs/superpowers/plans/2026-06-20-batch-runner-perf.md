# 批处理性能优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本计划由 main Claude 派发给 `signal-processing-expert`（sonnet）整体执行；每个 Task 内部 TDD-first。

**Goal:** 在不改 UI、不改 CSV 输出、不引入并行的前提下，去掉批处理两处浪费——谱图导出的 `matrix→long→pivot` 往返，以及 `run()` 前对磁盘文件的全量预加载。

**Architecture:** 纯 `mf4_analyzer/batch.py` 改动。引入矩阵优先的 `_Spectro2D` 载体让图像直接吃矩阵、长表按需构造（Task 1）；把 `target_signals` 任务枚举改成延迟元组 `(file_key, ch)`、`run()` 逐任务解析+加载+逐文件驱逐（Task 2）。旧方法名留薄包装保既有测试。

**Tech Stack:** Python 3.12 · numpy · pandas · matplotlib(Figure, 离屏) · pytest（`.venv/bin/python`）

## Global Constraints

- `BatchRunner` 必须保持 **GUI-free**（无 Qt import）。lesson `codex-order-batch-boundaries`。
- 复用 `mf4_analyzer/signal/` 既有助手，**不**另造 FFT/window 缩放路径。
- **不改**：`_compute_fft_dataframe`、`_write_dataframe` 的输出内容、`current_single` 路径、`pattern`（`signal_pattern`）枚举路径、`fft.py` 的 tuple 公开契约、任何 `ui/` 文件。
- `_Spectro2D.matrix` 为 x-major `(len(x), len(y))`，与 `_matrix_to_long_dataframe(x, y, matrix)` 约定一致 → CSV 输出逐字节不变。
- 热图渲染矩阵必须等于旧 `pivot.to_numpy()`，即 `spectro.matrix.T`。lesson `2026-06-11-slice-must-read-same-display-matrix-as-heatmap`。
- 每次数值改动 TDD-first（先写会失败的期望测试）。运行器统一：`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest ...`。
- 频繁提交；提交信息结尾附本仓 trailer（见各 Task 的 commit 步）。

---

## 文件结构

- Modify: `mf4_analyzer/batch.py`
  - 新增模块级 `@dataclass(frozen=True) _Spectro2D`（紧邻 `_matrix_to_long_dataframe`）。
  - 新增/改 `BatchRunner._compute_order_time_spectro`、`_compute_fft_time_spectro`，旧 `*_dataframe` 改薄包装。
  - 改 `BatchRunner._run_one`（image_payload + 长表按需）、`_write_image`（热图吃矩阵）。
  - 新增 `BatchRunner._resolve_task_file`、`_any_target_could_match`；改 `_expand_tasks`（target_signals 分支）、`run()`（循环吃 2 元组 + 驱逐）。
- Test: `tests/test_batch_runner.py`（主）、必要时 `tests/ui/test_order_smoke.py`。

---

### Task 1: 去除谱图 pivot 往返（`_Spectro2D`）

**Files:**
- Modify: `mf4_analyzer/batch.py`（`_matrix_to_long_dataframe` 上方加类；`_compute_order_time_dataframe:518`、`_compute_fft_time_dataframe:557`、`_run_one:392`、`_write_image:621`）
- Test: `tests/test_batch_runner.py`

**Interfaces:**
- Produces:
  - `_Spectro2D(x, y, matrix, x_name, y_name)`，`.to_long_dataframe() -> pd.DataFrame`
  - `BatchRunner._compute_order_time_spectro(sig, rpm, time, fs, params) -> _Spectro2D`
  - `BatchRunner._compute_fft_time_spectro(sig, time, fs, params, *, channel_name='') -> _Spectro2D`
  - `image_payload`：FFT=`('fft', df)`；热图=`(kind, _Spectro2D)`
- Consumes（不变）：`_matrix_to_long_dataframe`、`COTOrderAnalyzer`、`SpectrogramAnalyzer`、`_uniform_time_axis_for_spectrogram`

- [ ] **Step 1: 写失败测试——spectro 矩阵与长表互证**

在 `tests/test_batch_runner.py` 增：

```python
def test_order_time_spectro_matrix_matches_long_dataframe():
    import numpy as np
    from mf4_analyzer.batch import BatchRunner, _Spectro2D
    rng = np.random.default_rng(0)
    n = 4096
    fs = 1000.0
    t = np.arange(n) / fs
    sig = np.sin(2 * np.pi * 5 * t)
    rpm = np.linspace(600, 1800, n)
    params = {'samples_per_rev': 64, 'nfft': 256, 'max_order': 10,
              'order_res': 0.5, 'time_res': 0.1}
    spectro = BatchRunner._compute_order_time_spectro(sig, rpm, t, fs, params)
    assert isinstance(spectro, _Spectro2D)
    assert spectro.matrix.shape == (len(spectro.x), len(spectro.y))
    df_new = spectro.to_long_dataframe()
    df_old = BatchRunner._compute_order_time_dataframe(sig, rpm, t, fs, params)
    import pandas as pd
    pd.testing.assert_frame_equal(df_new, df_old)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_batch_runner.py::test_order_time_spectro_matrix_matches_long_dataframe -v`
Expected: FAIL（`cannot import name '_Spectro2D'` 或 `_compute_order_time_spectro` 不存在）

- [ ] **Step 3: 实现 `_Spectro2D` + 两个 `_spectro` 方法 + 旧名薄包装**

在 `batch.py` 中 `_matrix_to_long_dataframe` 上方加：

```python
@dataclass(frozen=True)
class _Spectro2D:
    """2-D analysis result kept matrix-first to avoid a long→wide pivot
    round-trip on export. ``matrix`` is x-major: shape (len(x), len(y))."""
    x: np.ndarray
    y: np.ndarray
    matrix: np.ndarray
    x_name: str
    y_name: str

    def to_long_dataframe(self) -> pd.DataFrame:
        return _matrix_to_long_dataframe(
            self.x, self.y, self.matrix, self.x_name, self.y_name)
```

把 `_compute_order_time_dataframe` 改成（保留签名/docstring，body 改为委托 + 包装）：

```python
@classmethod
def _compute_order_time_spectro(cls, sig, rpm, time, fs, params) -> "_Spectro2D":
    import numpy as np
    from .signal.order_cot import COTOrderAnalyzer, COTParams
    time_arr = np.asarray(time, dtype=float)
    if len(time_arr) < 2 or np.any(np.diff(time_arr) <= 0):
        time_arr = np.arange(len(time_arr), dtype=float) / float(fs)
    cot_params = COTParams(
        samples_per_rev=int(params.get('samples_per_rev', 256)),
        nfft=int(params.get('nfft', 1024)),
        window=str(params.get('window', 'hanning')),
        max_order=float(params.get('max_order', params.get('max_ord', 20))),
        order_res=float(params.get('order_res', 0.1)),
        time_res=float(params.get('time_res', 0.05)),
        fs=float(fs),
    )
    result = COTOrderAnalyzer.compute(sig, rpm, time_arr, cot_params)
    return _Spectro2D(
        x=np.asarray(result.times, dtype=float),
        y=np.asarray(result.orders, dtype=float),
        matrix=np.asarray(result.amplitude, dtype=float),
        x_name='time_s', y_name='order',
    )

@classmethod
def _compute_order_time_dataframe(cls, sig, rpm, time, fs, params):
    return cls._compute_order_time_spectro(sig, rpm, time, fs, params).to_long_dataframe()
```

同样把 `_compute_fft_time_dataframe` 改为：

```python
@classmethod
def _compute_fft_time_spectro(cls, sig, time, fs, params, *, channel_name='') -> "_Spectro2D":
    from .signal.spectrogram import SpectrogramAnalyzer, SpectrogramParams
    time, fs = cls._uniform_time_axis_for_spectrogram(time, fs, len(sig))
    sp = SpectrogramParams(
        fs=float(fs),
        nfft=int(params.get('nfft', 1024)),
        window=str(params.get('window', 'hanning')),
        overlap=float(params.get('overlap', 0.5)),
        remove_mean=bool(params.get('remove_mean', True)),
        db_reference=float(params.get('db_reference', 1.0)),
    )
    result = SpectrogramAnalyzer.compute(
        signal=sig, time=time, params=sp,
        channel_name=channel_name or 'signal',
    )
    return _Spectro2D(
        x=np.asarray(result.times, dtype=float),
        y=np.asarray(result.frequencies, dtype=float),
        matrix=np.asarray(result.amplitude.T, dtype=float),
        x_name='time_s', y_name='frequency_hz',
    )

@classmethod
def _compute_fft_time_dataframe(cls, sig, time, fs, params, *, channel_name=''):
    return cls._compute_fft_time_spectro(
        sig, time, fs, params, channel_name=channel_name).to_long_dataframe()
```

确认文件顶部已 `from dataclasses import dataclass, field`（已有）。

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_batch_runner.py::test_order_time_spectro_matrix_matches_long_dataframe -v`
Expected: PASS

- [ ] **Step 5: 写失败测试——`_write_image` 热图矩阵 == 旧 pivot；只导图不建长表**

```python
def test_write_image_heatmap_uses_transposed_matrix(tmp_path):
    import numpy as np
    from mf4_analyzer.batch import BatchRunner, _Spectro2D
    x = np.array([0.0, 1.0, 2.0])           # time
    y = np.array([1.0, 2.0])                 # order
    matrix = np.array([[1., 2.], [3., 4.], [5., 6.]])  # (len(x), len(y))
    spectro = _Spectro2D(x, y, matrix, 'time_s', 'order')
    out = BatchRunner._write_image(('order_time', spectro), tmp_path / 'h.png',
                                   params={'z_auto': True})
    assert out.exists()
    # 渲染矩阵应为 matrix.T（rows=y, cols=x），与旧 pivot 等价
    df = spectro.to_long_dataframe()
    pivot = df.pivot(index='order', columns='time_s', values='amplitude')
    np.testing.assert_allclose(pivot.to_numpy(), matrix.T)
```

- [ ] **Step 6: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_batch_runner.py::test_write_image_heatmap_uses_transposed_matrix -v`
Expected: FAIL（`_write_image` 解包 `_Spectro2D` 会因当前期望 df 而 `df.pivot` AttributeError）

- [ ] **Step 7: 改 `_run_one` + `_write_image`**

`_run_one` 的方法分派改为（保留 `fft` 不变）：

```python
spectro = None
if method == 'fft':
    sig, time, _ = self._apply_time_range(sig, time, preset.params)
    fft_df = self._compute_fft_dataframe(sig, fs, preset.params)
    image_payload = ('fft', fft_df)
elif method == 'fft_time':
    sig, time, _ = self._apply_time_range(sig, time, preset.params)
    spectro = self._compute_fft_time_spectro(
        sig, time, fs, preset.params, channel_name=signal_name)
    image_payload = ('fft_time', spectro)
else:
    rpm = self._rpm_values(fd, preset)
    sig, time, rpm = self._apply_time_range(sig, time, preset.params, rpm=rpm)
    if method == 'order_time':
        spectro = self._compute_order_time_spectro(sig, rpm, time, fs, preset.params)
        image_payload = ('order_time', spectro)
    else:  # pragma: no cover - guarded by _expand_tasks
        raise ValueError(f"unsupported method: {method}")

data_path = None
image_path = None
if preset.outputs.export_data:
    export_df = fft_df if method == 'fft' else spectro.to_long_dataframe()
    data_path = self._write_dataframe(
        export_df, output_dir / f"{stem}.{preset.outputs.data_format}")
if preset.outputs.export_image:
    image_path = self._write_image(
        image_payload, output_dir / f"{stem}.png", params=preset.params)
```

`_write_image` 把热图分支从「pivot 长表」改为「直接吃 `_Spectro2D`」。保留 `kind=='fft'` 的一维分支不变；db/vmin/vmax/colorbar/grid/tight_layout/savefig 逻辑不变，仅替换矩阵与 extent 来源：

```python
@staticmethod
def _write_image(payload, path, params=None):
    kind, data = payload
    from matplotlib.figure import Figure
    params = params or {}
    x_auto = bool(params.get('x_auto', True)); x_min = float(params.get('x_min', 0.0)); x_max = float(params.get('x_max', 0.0))
    y_auto = bool(params.get('y_auto', True)); y_min = float(params.get('y_min', 0.0)); y_max = float(params.get('y_max', 0.0))
    z_auto = bool(params.get('z_auto', True)); z_floor = float(params.get('z_floor', -80.0)); z_ceiling = float(params.get('z_ceiling', 0.0))
    default_amp_mode = 'amplitude_db' if kind == 'fft_time' else 'amplitude'
    amp_mode = str(params.get('amplitude_mode', default_amp_mode)).lower()
    render_db = 'db' in amp_mode
    db_reference = float(params.get('db_reference', 1.0) or 1.0)
    if db_reference <= 0:
        db_reference = 1.0

    fig = Figure(figsize=(8, 4.5), dpi=140)
    try:
        ax = fig.subplots()
        if kind == 'fft':
            df = data
            ax.plot(df['frequency_hz'], df['amplitude'], lw=1.0)
            ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('Amplitude')
            if not x_auto and x_max > x_min: ax.set_xlim(x_min, x_max)
            if not y_auto and y_max > y_min: ax.set_ylim(y_min, y_max)
        else:
            spectro = data
            matrix = np.asarray(spectro.matrix, dtype=float).T  # (rows=y, cols=x)
            if render_db:
                eps = np.finfo(float).tiny
                matrix = 20.0 * np.log10(np.maximum(matrix, eps) / db_reference)
                cbar_label = 'Amplitude (dB)'
            else:
                cbar_label = 'Amplitude'
            vmin = vmax = None
            if not z_auto:
                vmin = z_floor; vmax = z_ceiling
            im = ax.imshow(
                matrix, aspect='auto', origin='lower',
                extent=[float(spectro.x.min()), float(spectro.x.max()),
                        float(spectro.y.min()), float(spectro.y.max())],
                interpolation='bilinear', cmap='turbo', vmin=vmin, vmax=vmax,
            )
            ax.set_xlabel(spectro.x_name); ax.set_ylabel(spectro.y_name)
            if not x_auto and x_max > x_min: ax.set_xlim(x_min, x_max)
            if not y_auto and y_max > y_min: ax.set_ylim(y_min, y_max)
            fig.colorbar(im, ax=ax, label=cbar_label)
        ax.grid(True, alpha=0.25, ls='--')
        fig.tight_layout(**CHART_TIGHT_LAYOUT_KW)
        fig.savefig(path)
    finally:
        fig.clear()
    return path
```

- [ ] **Step 8: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_batch_runner.py::test_write_image_heatmap_uses_transposed_matrix -v`
Expected: PASS

- [ ] **Step 9: 写「只导图不建长表」测试（spy）**

```python
def test_image_only_export_skips_long_dataframe(tmp_path, monkeypatch):
    import numpy as np
    import mf4_analyzer.batch as batch_mod
    from mf4_analyzer.batch import BatchRunner, _Spectro2D
    calls = {'n': 0}
    orig = _Spectro2D.to_long_dataframe
    def spy(self):
        calls['n'] += 1
        return orig(self)
    monkeypatch.setattr(_Spectro2D, 'to_long_dataframe', spy)
    x = np.array([0., 1.]); y = np.array([1., 2.])
    sp = _Spectro2D(x, y, np.array([[1., 2.], [3., 4.]]), 'time_s', 'order')
    BatchRunner._write_image(('order_time', sp), tmp_path / 'i.png', params={'z_auto': True})
    assert calls['n'] == 0  # 画图不应触发长表构造
```

- [ ] **Step 10: 跑测试 + Task 1 全量批测试**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -k batch -q`
Expected: 全绿（含原 116 + 新增 3）

- [ ] **Step 11: Commit**

```bash
git add mf4_analyzer/batch.py tests/test_batch_runner.py
git commit -m "perf(batch): drop spectrogram long→pivot round-trip via _Spectro2D" -- mf4_analyzer/batch.py tests/test_batch_runner.py
```

---

### Task 2: 惰性加载 + 逐文件驱逐（`target_signals` 路径）

**Files:**
- Modify: `mf4_analyzer/batch.py`（`run():163`、`_expand_tasks():320`；新增 `_resolve_task_file`、`_any_target_could_match`）
- Test: `tests/test_batch_runner.py`、必要时 `tests/ui/test_order_smoke.py`

**Interfaces:**
- Produces:
  - `_expand_tasks` 对 `target_signals` 产出 2 元组 `(file_key, signal_name)`（`current_single`/`pattern` 也统一产出 2 元组 `(fid, ch)`）
  - `BatchRunner._resolve_task_file(file_key) -> (fid, fd_or_failure)`
  - `BatchRunner._any_target_could_match(file_keys, target_signals) -> bool`
- Consumes：`self.files`、`self._loader`、`self._disk_cache`、`_LoadFailure`

- [ ] **Step 1: 写失败测试——loader 惰性 + `_disk_cache` 驻留 ≤1**

```python
def test_file_paths_loaded_lazily_and_evicted(tmp_path):
    import numpy as np, pandas as pd
    from mf4_analyzer.batch import BatchRunner, AnalysisPreset, BatchOutput
    from mf4_analyzer.io import FileData
    load_order = []
    peak = {'max': 0}
    def make_fd(path):
        load_order.append(path)
        df = pd.DataFrame({'sig': np.zeros(8), 'rpm': np.linspace(1, 2, 8)})
        return FileData(path, df, ['sig', 'rpm'], {'sig': '', 'rpm': ''}, idx=-1)
    def spy_loader(path):
        fd = make_fd(path)
        return fd
    runner = BatchRunner(files={}, loader=spy_loader)
    # 包住 _disk_cache 以观测峰值驻留
    real_cache = runner._disk_cache
    class Watch(dict):
        def __setitem__(self, k, v):
            super().__setitem__(k, v)
            peak['max'] = max(peak['max'], len(self))
    runner._disk_cache = Watch()
    preset = AnalysisPreset.free_config(
        name='t', method='fft', target_signals=('sig',),
        outputs=BatchOutput(export_data=True, export_image=False, data_format='csv'),
    )
    import dataclasses
    preset = dataclasses.replace(preset, file_paths=('a.mf4', 'b.mf4', 'c.mf4'))
    result = runner.run(preset, tmp_path)
    assert result.status == 'done'
    assert load_order == ['a.mf4', 'b.mf4', 'c.mf4']  # 逐个、按序
    assert peak['max'] == 1  # 同时只驻留 1 个磁盘文件
```

> 注：若 `FileData` 构造签名与此处不符，执行者按真实签名调整 `make_fd`（参考 `_default_loader`）。

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_batch_runner.py::test_file_paths_loaded_lazily_and_evicted -v`
Expected: FAIL（当前 run 前 `list(_resolve_files)` 一次性全载 → `load_order` 顺序或 `peak` 不符）

- [ ] **Step 3: 加 `_resolve_task_file` + `_any_target_could_match`，改 `_expand_tasks`**

新增两个方法：

```python
def _resolve_task_file(self, file_key):
    """Resolve a deferred task file_key to (fid, fd_or_failure).
    Registered fid → live FileData. Disk path → loaded via self._loader,
    cached in self._disk_cache (FileData or _LoadFailure)."""
    fd = self.files.get(file_key)
    if fd is not None:
        return file_key, fd
    if file_key in self._disk_cache:
        return file_key, self._disk_cache[file_key]
    try:
        fd = self._loader(file_key)
    except Exception as exc:  # noqa: BLE001
        fd = _LoadFailure(file_key, str(exc))
    self._disk_cache[file_key] = fd
    return file_key, fd

def _any_target_could_match(self, file_keys, target_signals):
    """True if some task could plausibly run without loading disk files.
    Loaded files are checked against real columns; disk paths / unknown
    keys are assumed possibly-matching (verified per-task in run())."""
    for key in file_keys:
        fd = self.files.get(key)
        if fd is None:
            return True
        if any(ch in fd.data.columns for ch in target_signals):
            return True
    return False
```

把 `_expand_tasks` 改为产出 2 元组（`current_single` 与 `pattern` 也统一 2 元组）：

```python
def _expand_tasks(self, preset):
    if preset.method not in self.SUPPORTED_METHODS:
        return
    if preset.source == 'current_single':
        if preset.signal is None:
            return
        fid, ch = preset.signal
        fd = self.files.get(fid)
        if fd is not None and ch in fd.data.columns:
            yield (fid, ch)
        return
    if preset.target_signals:
        # Lazy: defer disk loads to run(); enumerate the full cartesian
        # product (missing signals surface as task_failed in run(), same as
        # the old unconditional phase-2 yield).
        file_keys = list(preset.file_ids) + list(preset.file_paths)
        if not file_keys:
            file_keys = list(self.files.keys())  # legacy: all loaded files
        if not self._any_target_could_match(file_keys, preset.target_signals):
            return  # all-loaded & none match → run() blocked (preserved)
        for key in file_keys:
            for ch in preset.target_signals:
                yield (key, ch)
        return
    # Pattern fallback (legacy/tests): unchanged — eager load to enumerate.
    pattern = preset.signal_pattern.strip()
    for fid, fd in self._resolve_files(preset):
        if isinstance(fd, _LoadFailure):
            continue
        for ch in fd.get_signal_channels():
            if preset.method.startswith('order') and ch == preset.rpm_channel:
                continue
            if self._matches(ch, pattern):
                yield (fid, ch)
```

- [ ] **Step 4: 改 `run()` 循环吃 2 元组 + 逐文件驱逐**

把 `run()` 里从 `for index, task in enumerate(...)` 到循环结束这一段改为（仅展示循环体关键改动，其余 status 汇总/run_finished 不变）：

```python
items = []
blocked = []
cancelled = False
total = len(tasks)
prev_disk_key = None  # last disk path resident in _disk_cache (for eviction)

for index, (file_key, signal_name) in enumerate(tasks, start=1):
    # file-major ordering → evict the previous disk file when we move on.
    if prev_disk_key is not None and file_key != prev_disk_key:
        self._disk_cache.pop(prev_disk_key, None)
        prev_disk_key = None

    if cancel_token is not None and cancel_token.is_set():
        cancelled = True
        for j in range(index, total + 1):
            key_j, sig_j = tasks[j - 1]
            if key_j in self.files:
                fname_j = getattr(self.files[key_j], 'filename', str(key_j))
            else:
                fname_j = str(key_j)
            if on_event:
                on_event(BatchProgressEvent(
                    kind='task_cancelled', task_index=j, total=total,
                    file_name=fname_j, signal=sig_j, method=preset.method))
        break

    fid, fd_or_fail = self._resolve_task_file(file_key)
    if isinstance(fd_or_fail, _LoadFailure):
        fname = fd_or_fail.path
    else:
        fname = getattr(fd_or_fail, 'filename', str(fid))
        if file_key not in self.files:
            prev_disk_key = file_key  # disk-loaded → eligible for eviction

    if on_event:
        on_event(BatchProgressEvent(
            kind='task_started', task_index=index, total=total,
            file_name=fname, signal=signal_name, method=preset.method))
    try:
        if isinstance(fd_or_fail, _LoadFailure):
            raise IOError(fd_or_fail.error)
        if signal_name not in fd_or_fail.data.columns:
            raise ValueError(f"missing signal: {signal_name}")
        item = self._run_one(preset, fid, fd_or_fail, signal_name, output_dir)
        items.append(item)
        if on_event:
            on_event(BatchProgressEvent(
                kind='task_done', task_index=index, total=total,
                file_name=fname, signal=signal_name, method=preset.method))
        if progress_callback:
            progress_callback(index, total)
    except Exception as exc:
        items.append(BatchItemResult(
            method=preset.method, file_id=fid, file_name=fname,
            signal=signal_name, status='blocked', message=str(exc)))
        blocked.append(f"{fname}:{signal_name}: {exc}")
        if on_event:
            on_event(BatchProgressEvent(
                kind='task_failed', task_index=index, total=total,
                file_name=fname, signal=signal_name,
                method=preset.method, error=str(exc)))

# evict any trailing disk file
if prev_disk_key is not None:
    self._disk_cache.pop(prev_disk_key, None)
```

> `_resolve_files` 保留（`pattern` 分支仍用）。注意 `_resolve_task_file` 的 `file_key not in self.files` 判定区分「已注册 fid（不驱逐）」与「磁盘路径（驱逐）」。

- [ ] **Step 5: 跑惰性测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_batch_runner.py::test_file_paths_loaded_lazily_and_evicted -v`
Expected: PASS

- [ ] **Step 6: 写「全已加载且 target 无一匹配 → blocked」回归测试**

```python
def test_target_signals_none_match_loaded_files_blocks():
    import numpy as np, pandas as pd
    from mf4_analyzer.batch import BatchRunner, AnalysisPreset, BatchOutput
    from mf4_analyzer.io import FileData
    df = pd.DataFrame({'foo': np.zeros(8)})
    fd = FileData('f.mf4', df, ['foo'], {'foo': ''}, idx=0)
    runner = BatchRunner(files={'f0': fd})
    import dataclasses
    preset = AnalysisPreset.free_config(name='t', method='fft', target_signals=('nope',))
    preset = dataclasses.replace(preset, file_ids=('f0',))
    result = runner.run(preset, _tmp_outdir())
    assert result.status == 'blocked'
```

> `_tmp_outdir()`：执行者用 `tmp_path` fixture 或 `tempfile.mkdtemp()` 替换（既有测试里已有同类用法可复用）。

- [ ] **Step 7: 跑测试 + 处理 `_expand_tasks` 元组形状变更的既有测试**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -k batch -q`
Expected: 多数绿；**若**有直接解包 `_expand_tasks(...)` 旧 3 元组 `(fid, fd, ch)` 的测试失败 → 按新 2 元组 `(file_key, ch)` 更新它们（TDD：改期望、不改产物）。同样检查 `tests/ui/test_order_smoke.py`。逐个修复至全绿。

- [ ] **Step 8: 全量冒烟回归**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: 与基线一致（无新增失败；记录基线既有失败如有）。

- [ ] **Step 9: Commit**

```bash
git add mf4_analyzer/batch.py tests/test_batch_runner.py tests/ui/test_order_smoke.py
git commit -m "perf(batch): lazy per-task file load + single-file disk eviction" -- mf4_analyzer/batch.py tests/test_batch_runner.py tests/ui/test_order_smoke.py
```

---

## Self-Review（计划自检）

- **Spec coverage**：P0-A→Task 1（`_Spectro2D`+compute+`_write_image`+`_run_one`+只导图跳长表）；P0-B→Task 2（惰性枚举+`_resolve_task_file`+驱逐+保 blocked 语义）。契约表逐项有对应步骤。✓
- **Placeholder scan**：无 TODO/「适当处理」类占位；测试与实现均给了完整代码。`_tmp_outdir()`/`make_fd` 两处显式标注按真实签名微调（FileData 构造在不同分支可能有差异，执行者用 `_default_loader:145-152` 作为权威参照）。
- **Type consistency**：`_Spectro2D(x,y,matrix,x_name,y_name)` 全程一致；`_compute_*_spectro` 命名与调用一致；`image_payload` 二元组 `(kind, data)` 在 `_run_one`/`_write_image` 两端一致；`_expand_tasks` 2 元组在 `run()` 解包一致。
- **关键不变量**：CSV 输出（`to_long_dataframe` 委托 `_matrix_to_long_dataframe`，参数不变）、热图渲染矩阵（`spectro.matrix.T == 旧 pivot`）、任务集与事件流计数/顺序（target_signals 仍是全笛卡尔积）均证明保持。
