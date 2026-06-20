# 音视频音轨导入 + A 计权频域分析 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 MF4 Data Analyzer 能导入 mp4/mp3/mov 等音视频文件的音轨为普通信号通道，并为 FFT / FFT vs Time / Order 三个分析增加 A 计权（IEC 61672）选项；识别到音视频文件时三个默认预设智能带上 A 计权。

**Architecture:** 用 PyAV 解码音轨进现有 `FileData`（fs 为任意 float、立体声=多列）。新建纯数值模块 `weighting.py` 提供 A 计权增益；在三个分析的 signal 层、线性幅值阶段、dB 转换之前各自挂载（FFT/Spectrogram 在频率轴上一次性乘；Order 因阶次随转速变需逐帧用 `mean_rpm` 把阶次换算成 Hz 再加权）。weighting 作为正交参数贯穿 params dict → dataclass → 缓存 → 持久化；选中音频信号时三个 contextual 的加权组合框自动置 'A'。

**Tech Stack:** Python, PyQt5, pyqtgraph, numpy, pandas, scipy, **PyAV(`av`)**, pytest / pytest-qt。

## Global Constraints

- 新增依赖：`av`（PyAV，自带预编译 ffmpeg，无需系统 ffmpeg）。`requirements.txt` 加一行 `av`。
- A 计权按 **IEC 61672-1** 解析式，归一化使 **A(1000Hz)=0 dB**。
- 仅 **相对加权频谱 / 相对 dBFS(A)**，**不**产出绝对 dB SPL、不做标定、不出总声级数字。
- `weighting` 字段值域 `'None' | 'A'`，**默认 `'None'`**；旧预设/旧项目缺该键时按 `'None'` 处理（向后兼容）。
- 音频 dtype 用 **float32** 存储（控内存）；短片段全量加载，**不**降采样、不分块。
- A 计权在 signal 层 **线性幅值** 上乘 `a_weighting_gain_linear(freqs)`，**在 dB 转换之前**。
- **不**修改底层 `one_sided_amplitude()`（FFT 与 Spectrogram 共享它，改它会导致 Spectrogram 被重复加权）。
- 现有 164 个 pytest 用例不得回归（机械域默认 `weighting='None'` → 数值逐字节不变）。
- 测试放置约定：用 `qtbot` 的 UI 测试放 `tests/ui/`（与既有 `tests/ui/test_inspector.py` 一致）；纯数值/IO 测试放 `tests/`（与 `tests/test_signal_adaptive.py` 一致）。本计划中 Tasks 9/10/11/13/14 的测试归 `tests/ui/`，其余归 `tests/`。
- UI 改动须**验真机渲染**（截图 / objc 读原生属性），不得只凭"属性设上了 + 单测过"判定完成（CLAUDE.md 规则）。
- 项目在 `~/Downloads`：若子进程触发 TCC EPERM，用 harness Read 工具或给终端 Full Disk Access。

---

### Task 1: A 计权数值模块 `weighting.py`

纯数值、零依赖、所有后续分析的基础，先行。TDD。

**Files:**
- Create: `mf4_analyzer/signal/weighting.py`
- Test: `tests/test_weighting.py`

**Interfaces:**
- Consumes: 无（仅 numpy）。
- Produces:
  - `a_weighting_gain_linear(freqs: np.ndarray | float) -> np.ndarray` — 线性乘子 `R_A(f)/R_A(1000)`；`f<=0` 返回 0；输出与输入同形。
  - `a_weighting_gain_db(freqs: np.ndarray | float) -> np.ndarray` — `20*log10(linear)`；`f<=0` 返回 `-inf`。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_weighting.py
import numpy as np
import pytest
from mf4_analyzer.signal.weighting import (
    a_weighting_gain_db, a_weighting_gain_linear,
)

# IEC 61672-1 Table 3 nominal A-weighting values (dB). The formula IS the
# standard; these rounded values match it within ±0.2 dB.
A_TABLE = [
    (10, -70.4), (20, -50.5), (50, -30.2), (100, -19.1),
    (200, -10.9), (500, -3.2), (1000, 0.0), (2000, 1.2),
    (2500, 1.3), (5000, 0.5), (10000, -2.5), (20000, -9.3),
]


@pytest.mark.parametrize("f,expected", A_TABLE)
def test_a_weighting_db_matches_iec(f, expected):
    assert float(a_weighting_gain_db(f)) == pytest.approx(expected, abs=0.2)


def test_a_weighting_linear_unity_at_1khz():
    assert float(a_weighting_gain_linear(1000.0)) == pytest.approx(1.0, abs=1e-6)


def test_a_weighting_dc_is_zero_linear():
    assert float(a_weighting_gain_linear(0.0)) == 0.0
    assert a_weighting_gain_db(0.0) == -np.inf


def test_a_weighting_vectorized_shape_and_monotonic_up_to_peak():
    f = np.array([20.0, 100.0, 500.0, 1000.0, 2500.0])
    g = a_weighting_gain_db(f)
    assert g.shape == f.shape
    assert np.all(np.diff(g) > 0)  # strictly rising from 20 Hz to ~2.5 kHz peak
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_weighting.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mf4_analyzer.signal.weighting'`

- [ ] **Step 3: Write minimal implementation**

```python
# mf4_analyzer/signal/weighting.py
"""IEC 61672-1 frequency weighting (A-weighting).

Relative weighting only — applied as a per-frequency LINEAR gain onto the
amplitude spectrum BEFORE any dB conversion. Normalised so A(1000 Hz)=0 dB.
"""
import numpy as np

# IEC 61672-1 pole frequencies (Hz).
_F1 = 20.598997
_F2 = 107.65265
_F3 = 737.86223
_F4 = 12194.217


def _ra(f):
    """Unnormalised A-weighting magnitude response R_A(f)."""
    f2 = f * f
    num = (_F4 ** 2) * (f2 * f2)
    den = (
        (f2 + _F1 ** 2)
        * np.sqrt((f2 + _F2 ** 2) * (f2 + _F3 ** 2))
        * (f2 + _F4 ** 2)
    )
    return num / den


_RA_1000 = _ra(1000.0)


def a_weighting_gain_linear(freqs):
    """Linear A-weighting multiplier R_A(f)/R_A(1000). f<=0 -> 0. Same shape as input."""
    f = np.asarray(freqs, dtype=float)
    safe = np.where(f > 0, f, 1.0)  # avoid 0/garbage at f<=0; masked out below
    lin = _ra(safe) / _RA_1000
    return np.where(f > 0, lin, 0.0)


def a_weighting_gain_db(freqs):
    """A-weighting gain in dB = 20*log10(linear). f<=0 -> -inf."""
    lin = a_weighting_gain_linear(freqs)
    return np.where(lin > 0, 20.0 * np.log10(np.where(lin > 0, lin, 1.0)), -np.inf)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_weighting.py -v`
Expected: PASS (all parametrized + 3 cases)

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/signal/weighting.py tests/test_weighting.py
git commit -m "feat(signal): IEC 61672 A-weighting gain module"
```

---

### Task 2: 音视频音轨 loader

**Files:**
- Modify: `requirements.txt`
- Modify: `mf4_analyzer/io/loader.py` (add module-level `AUDIO_VIDEO_EXTS` before `class DataLoader:` at line 115; add `load_audio_video` static method inside `DataLoader`)
- Test: `tests/test_audio_loader.py`

**Interfaces:**
- Consumes: 无（PyAV 运行时导入）。
- Produces:
  - module constant `AUDIO_VIDEO_EXTS: set[str]` = `{'.mp4','.mov','.mkv','.m4v','.mp3','.m4a','.aac','.wav','.flac'}`
  - `DataLoader.load_audio_video(fp) -> tuple[pd.DataFrame, list[str], dict[str,str], float, dict]`
    返回 `(data, channels, units, fs, source_metadata)`；`source_metadata['source_kind'] == 'audio'`；无音轨抛 `ValueError("文件不含音轨")`。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audio_loader.py
import wave
import numpy as np
import pytest
from mf4_analyzer.io.loader import DataLoader, AUDIO_VIDEO_EXTS


def _write_wav(path, fs, sig_float):
    pcm = np.clip(sig_float, -1.0, 1.0)
    pcm = (pcm * 32767).astype('<i2')
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(pcm.tobytes())


def test_audio_video_exts_cover_common_formats():
    for e in ('.mp4', '.mov', '.mp3', '.wav', '.flac', '.m4a'):
        assert e in AUDIO_VIDEO_EXTS


def test_load_audio_video_mono_wav(tmp_path):
    pytest.importorskip('av')
    fs = 48000
    n = fs  # 1 s
    t = np.arange(n) / fs
    _write_wav(tmp_path / "tone.wav", fs, 0.5 * np.sin(2 * np.pi * 1000 * t))
    data, chans, units, got_fs, meta = DataLoader.load_audio_video(
        str(tmp_path / "tone.wav"))
    assert got_fs == 48000.0
    assert chans == ['audio']
    assert units == {'audio': ''}
    assert meta['source_kind'] == 'audio'
    assert meta['channels'] == 1
    # decoder framing can pad/trim a few ms
    assert len(data) == pytest.approx(n, abs=int(fs * 0.05))


def test_load_audio_video_no_audio_stream_raises(tmp_path):
    pytest.importorskip('av')
    p = tmp_path / "empty.bin"
    p.write_bytes(b"not media")
    with pytest.raises(Exception):
        DataLoader.load_audio_video(str(p))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_audio_loader.py -v`
Expected: FAIL — `ImportError: cannot import name 'AUDIO_VIDEO_EXTS'` / `load_audio_video` missing

- [ ] **Step 3a: Add the `av` dependency**

In `requirements.txt`, after the `asammdf` line add:

```
av
```

- [ ] **Step 3b: Add `AUDIO_VIDEO_EXTS` constant**

In `mf4_analyzer/io/loader.py`, immediately before `class DataLoader:` (currently line 115), insert:

```python
# Audio/video container extensions whose first audio track we import as
# ordinary signal channels (see DataLoader.load_audio_video).
AUDIO_VIDEO_EXTS = {
    '.mp4', '.mov', '.mkv', '.m4v',          # video containers (audio track)
    '.mp3', '.m4a', '.aac', '.wav', '.flac',  # audio files
}
```

- [ ] **Step 3c: Add `load_audio_video` method**

In `mf4_analyzer/io/loader.py`, inside `class DataLoader`, after `load_mf4` (i.e. after current line 167), add:

```python
    @staticmethod
    def load_audio_video(fp):
        """Decode the FIRST audio track of an audio/video file into channels.

        Returns ``(data, channels, units, fs, source_metadata)``.
        ``source_metadata['source_kind'] == 'audio'`` marks the file as an
        audio source (drives FileData.is_audio_source + the smart A-weighting
        default). Raises ``ValueError`` when the file has no audio stream.

        Short clips only: the whole track is decoded into memory (float32).
        """
        import av  # PyAV; requires `pip install av`

        container = av.open(str(fp))
        try:
            streams = container.streams.audio
            if not streams:
                raise ValueError("文件不含音轨")
            stream = streams[0]
            fs = int(stream.rate)
            n_ch = int(stream.channels)
            container_name = container.format.name
            codec_name = stream.codec_context.name
            resampler = av.AudioResampler(format='fltp', layout=stream.layout)
            per_ch = [[] for _ in range(n_ch)]

            def _drain(frames):
                for fr in frames:
                    arr = fr.to_ndarray()  # (n_ch, n_samples), float32 planar
                    for ci in range(arr.shape[0]):
                        per_ch[ci].append(arr[ci])

            for frame in container.decode(stream):
                _drain(resampler.resample(frame))
            _drain(resampler.resample(None))  # flush
        finally:
            container.close()

        cols = [
            np.concatenate(c) if c else np.zeros(0, dtype=np.float32)
            for c in per_ch
        ]
        n = min((len(c) for c in cols), default=0)
        cols = [c[:n].astype(np.float32, copy=False) for c in cols]

        if n_ch == 1:
            names = ['audio']
        elif n_ch == 2:
            names = ['L', 'R']
        else:
            names = [f'ch{i}' for i in range(n_ch)]

        data = pd.DataFrame({nm: col for nm, col in zip(names, cols)})
        units = {nm: '' for nm in names}
        source_metadata = {
            'source_kind': 'audio',
            'container': container_name,
            'codec': codec_name,
            'fs': fs,
            'channels': n_ch,
        }
        return data, names, units, float(fs), source_metadata
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_audio_loader.py -v`
Expected: PASS (wav cases skip if `av` not installed; install with `pip install av`)

- [ ] **Step 5: Commit**

```bash
git add requirements.txt mf4_analyzer/io/loader.py tests/test_audio_loader.py
git commit -m "feat(io): import audio track from audio/video files via PyAV"
```

---

### Task 3: `FileData` 显式 fs + 音频标记

**Files:**
- Modify: `mf4_analyzer/io/file_data.py:18-50` (`__init__`) — add `fs` keyword + audio short-circuit; add `is_audio_source` method
- Test: `tests/test_file_data_audio.py`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `FileData(fp, df, chs, units, idx=0, *, fs=None, source_metadata=None, channel_metadata=None, label_suffix="")` — 当 `fs` 显式给出：`self.fs=fs`、`_time_source='audio'`、`time_array=arange(n)/fs`，跳过时间列推断。
  - `FileData.is_audio_source() -> bool` — `source_metadata.get('source_kind') == 'audio'`。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_file_data_audio.py
import numpy as np
import pandas as pd
from mf4_analyzer.io.file_data import FileData


def test_explicit_fs_skips_time_column_inference():
    df = pd.DataFrame({'audio': np.zeros(48000, dtype=np.float32)})
    fd = FileData('x.wav', df, ['audio'], {'audio': ''}, fs=48000.0,
                  source_metadata={'source_kind': 'audio'})
    assert fd.fs == 48000.0
    assert fd._time_source == 'audio'
    assert len(fd.time_array) == 48000
    assert fd.time_array[1] == 1.0 / 48000.0


def test_is_audio_source_true_false():
    df = pd.DataFrame({'audio': np.zeros(10, dtype=np.float32)})
    audio = FileData('x.wav', df, ['audio'], {'audio': ''}, fs=48000.0,
                     source_metadata={'source_kind': 'audio'})
    plain = FileData('y.csv', df, ['audio'], {'audio': ''})
    assert audio.is_audio_source() is True
    assert plain.is_audio_source() is False


def test_no_fs_keeps_legacy_behavior():
    # No time column, no fs -> legacy default 1000 Hz, generated time axis.
    df = pd.DataFrame({'sig': np.zeros(100)})
    fd = FileData('z.csv', df, ['sig'], {'sig': ''})
    assert fd.fs == 1000.0
    assert fd._time_source == 'generated'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_file_data_audio.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'fs'`

- [ ] **Step 3a: Add `fs` keyword + short-circuit**

In `mf4_analyzer/io/file_data.py`, change the `__init__` signature (line 18-19) from:

```python
    def __init__(self, fp, df, chs, units, idx=0, *,
                 source_metadata=None, channel_metadata=None, label_suffix=""):
```

to:

```python
    def __init__(self, fp, df, chs, units, idx=0, *, fs=None,
                 source_metadata=None, channel_metadata=None, label_suffix=""):
```

Then replace the time-axis block (current lines 36-50):

```python
        # 尝试从列名识别时间列
        for ch in chs:
            if ch.lower() in _TIME_NAMES:
                self.time_array = df[ch].to_numpy(copy=False).astype(float, copy=False)
                if len(self.time_array) > 1:
                    dt = np.median(np.diff(self.time_array))
                    if dt > 0:
                        self.fs = 1.0 / dt
                        self._time_source = 'column'
                break

        # 如果没有时间列，根据采样率生成
        if self.time_array is None:
            self.time_array = np.arange(len(df), dtype=float) / self.fs
            self._time_source = 'generated'
```

with:

```python
        # Audio/video sources carry an authoritative sample rate in the file
        # header — trust it and skip time-column inference entirely.
        if fs is not None:
            self.fs = float(fs)
            self.time_array = np.arange(len(df), dtype=float) / self.fs
            self._time_source = 'audio'
        else:
            # 尝试从列名识别时间列
            for ch in chs:
                if ch.lower() in _TIME_NAMES:
                    self.time_array = df[ch].to_numpy(copy=False).astype(float, copy=False)
                    if len(self.time_array) > 1:
                        dt = np.median(np.diff(self.time_array))
                        if dt > 0:
                            self.fs = 1.0 / dt
                            self._time_source = 'column'
                    break

            # 如果没有时间列，根据采样率生成
            if self.time_array is None:
                self.time_array = np.arange(len(df), dtype=float) / self.fs
                self._time_source = 'generated'
```

- [ ] **Step 3b: Add `is_audio_source` method**

In `mf4_analyzer/io/file_data.py`, after `rebuild_time_axis` (current line 57), add:

```python
    def is_audio_source(self):
        """True iff this file was imported from an audio/video track."""
        return self.source_metadata.get('source_kind') == 'audio'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_file_data_audio.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/io/file_data.py tests/test_file_data_audio.py
git commit -m "feat(io): FileData explicit fs + is_audio_source marker"
```

---

### Task 4: 文件对话框过滤器 + `_load_one` 分派

UI 加载分派。`load_audio_video` 返回 5 元组（含 fs），与其它 loader 的 3 元组不同，单独解构并把 `fs`/`source_metadata` 透传到注册。

**Files:**
- Modify: `mf4_analyzer/ui/main_window/_project_io_mixin.py` — 文件过滤器（lines 33-34 与 81 区域）、`_load_one` 分派（line 147-148 前加分支）、确认 `_register_file_data` 透传 `fs`（line 100-121 区域，签名见 `_register_file_data`）
- Test: `tests/test_audio_load_dispatch.py`

**Interfaces:**
- Consumes: `DataLoader.load_audio_video` (Task 2), `AUDIO_VIDEO_EXTS` (Task 2), `FileData(fs=...)` (Task 3)
- Produces: 选 mp4/mp3/… 文件 → 注册出 `is_audio_source()==True` 的 FileData。

- [ ] **Step 1: Inspect `_register_file_data` and confirm fs passthrough**

Run: `grep -n "def _register_file_data" mf4_analyzer/ui/main_window/_project_io_mixin.py`

Read that method. It constructs `FileData(...)`. Confirm whether it accepts/forwards a `fs` keyword. If it does NOT, add `fs=None` to its signature and pass `fs=fs` into the `FileData(...)` construction.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_audio_load_dispatch.py
import wave
import numpy as np
import pytest
from mf4_analyzer.io.loader import DataLoader


def _write_wav(path, fs=48000, secs=1):
    n = fs * secs
    t = np.arange(n) / fs
    pcm = (0.5 * np.sin(2 * np.pi * 1000 * t) * 32767).astype('<i2')
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fs)
        w.writeframes(pcm.tobytes())


def test_load_audio_video_returns_fs_for_registration(tmp_path):
    pytest.importorskip('av')
    p = tmp_path / "tone.wav"
    _write_wav(p)
    data, chs, units, fs, meta = DataLoader.load_audio_video(str(p))
    # The dispatch in _load_one must use THIS fs + meta when registering.
    from mf4_analyzer.io.file_data import FileData
    fd = FileData(str(p), data, chs, units, fs=fs, source_metadata=meta)
    assert fd.fs == 48000.0
    assert fd.is_audio_source() is True
```

> 注：`_load_one`/对话框依赖 QApplication，难做纯单测；此处验证分派所依赖的 5 元组 + FileData 契约。GUI 端到端在 Task 14 真机验证。

- [ ] **Step 3: Run test to verify it fails (or passes trivially), then wire dispatch**

Run: `pytest tests/test_audio_load_dispatch.py -v` (Tasks 2+3 done → 此测试应已 PASS；它锁定契约。)

Then wire the GUI dispatch:

**(a) 文件过滤器** — in `_project_io_mixin.py` 的两处过滤器字符串（`open_files_or_project` 内，约 line 33-34 与 81），把音视频扩展名加进"所有支持的文件"并新增一项。例如把
`"所有支持的文件 (*.mf4 *.mdf *.csv *.xlsx *.xls *.hdf *.tlproj);;..."`
改为包含 `*.mp4 *.mov *.mkv *.m4v *.mp3 *.m4a *.aac *.wav *.flac`，并追加
`"音视频文件 (*.mp4 *.mov *.mkv *.m4v *.mp3 *.m4a *.aac *.wav *.flac);;"`。

**(b) `_load_one` 分派** — in `_project_io_mixin.py`, add an import near the top:

```python
from ...io.loader import AUDIO_VIDEO_EXTS
```

then in `_load_one`, before the final `else:` (current line 147), insert a branch:

```python
            elif ext in AUDIO_VIDEO_EXTS:
                data, chs, units, fs, smeta = DataLoader.load_audio_video(fp)
                self._register_file_data(
                    fp, data, chs, units, fs=fs, source_metadata=smeta)
                self._update_info()
                self.statusBar.showMessage(
                    f"✅ 已加载音轨: {p.name} ({len(data)} 采样 @ {fs:.0f} Hz)")
                self.toast(f"已加载音轨 {p.name}", "success")
                return
```

(`_register_file_data` 已在 Step 1 确认接受 `fs`/`source_metadata`。)

- [ ] **Step 4: Run test + smoke import**

Run: `pytest tests/test_audio_load_dispatch.py -v`
Expected: PASS
Run: `python -c "import mf4_analyzer.ui.main_window._project_io_mixin"`
Expected: no ImportError

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/main_window/_project_io_mixin.py tests/test_audio_load_dispatch.py
git commit -m "feat(ui): wire audio/video file dialog filter + load dispatch"
```

---

### Task 5: `batch.py` loader 分派修复

`_default_loader` 当前硬编码只 `load_mf4`（既有缺陷，批处理落后 GUI）。改为按扩展名分派，使音视频在批处理自动覆盖。

**Files:**
- Modify: `mf4_analyzer/batch.py:145-152` (`_default_loader`)
- Test: `tests/test_batch_loader_dispatch.py`

**Interfaces:**
- Consumes: `DataLoader.load_audio_video` / `load_mf4` / `load_csv` / `load_excel` (Task 2 + 既有), `AUDIO_VIDEO_EXTS` (Task 2), `FileData(fs=...)` (Task 3)
- Produces: `_default_loader(path) -> FileData`，按扩展名选 loader；音视频路径走 5 元组 + fs。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_batch_loader_dispatch.py
import wave
import numpy as np
import pytest
from mf4_analyzer.batch import _default_loader


def test_default_loader_audio(tmp_path):
    pytest.importorskip('av')
    fs = 48000
    n = fs
    t = np.arange(n) / fs
    pcm = (0.5 * np.sin(2 * np.pi * 1000 * t) * 32767).astype('<i2')
    p = tmp_path / "tone.wav"
    with wave.open(str(p), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fs)
        w.writeframes(pcm.tobytes())
    fd = _default_loader(str(p))
    assert fd.is_audio_source() is True
    assert fd.fs == 48000.0


def test_default_loader_csv(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("Time,sig\n0,1\n0.1,2\n0.2,3\n")
    fd = _default_loader(str(p))
    assert fd.is_audio_source() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_batch_loader_dispatch.py -v`
Expected: FAIL — `_default_loader` calls `load_mf4` on a `.wav`/`.csv` and errors.

- [ ] **Step 3: Rewrite `_default_loader`**

In `mf4_analyzer/batch.py`, replace `_default_loader` (lines 145-152) with:

```python
def _default_loader(path):
    """Default disk loader for ``BatchRunner.file_paths`` resolution.

    Extension-based dispatch so batch keeps parity with the GUI loader
    (mf4/mdf/csv/xlsx/xls/audio-video). Returns FileData; idx -1 marks
    "not registered with main_window".
    """
    from pathlib import Path
    from mf4_analyzer.io import DataLoader, FileData
    from mf4_analyzer.io.loader import AUDIO_VIDEO_EXTS

    ext = Path(path).suffix.lower()
    if ext in AUDIO_VIDEO_EXTS:
        data, chs, units, fs, smeta = DataLoader.load_audio_video(path)
        return FileData(path, data, chs, units, idx=-1, fs=fs,
                        source_metadata=smeta)
    if ext in ('.xlsx', '.xls'):
        data, chs, units = DataLoader.load_excel(path)
    elif ext == '.csv':
        data, chs, units = DataLoader.load_csv(path)
    else:
        data, chs, units = DataLoader.load_mf4(path)
    return FileData(path, data, chs, units, idx=-1)
```

> 注：`.hdf` 走多组返回，批处理既有未支持；保持现状（不在本任务范围）。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_batch_loader_dispatch.py -v`
Expected: PASS (audio case skips without `av`)

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/batch.py tests/test_batch_loader_dispatch.py
git commit -m "fix(batch): extension-based loader dispatch incl. audio/video"
```

---

### Task 6: FFT signal 层 A 计权

给 `FFTAnalyzer` 的四个方法加 `weighting='None'`，在最终线性幅值上乘 `a_weighting_gain_linear(freq)`。**不**改 `one_sided_amplitude`。

**Files:**
- Modify: `mf4_analyzer/signal/fft.py` — import + `compute_fft`(156-173) / `compute_psd`(175-178) / `compute_averaged_fft`(180-244) / `compute_peak_hold_fft`(246-280)
- Test: `tests/test_fft_weighting.py`

**Interfaces:**
- Consumes: `a_weighting_gain_linear` (Task 1)
- Produces:
  - `compute_fft(sig, fs, win='hanning', nfft=None, weighting='None')`
  - `compute_psd(sig, fs, win='hanning', nfft=None, weighting='None')`
  - `compute_averaged_fft(sig, fs, win='hanning', nfft=1024, overlap=0.5, weighting='None')`
  - `compute_peak_hold_fft(sig, fs, win='hanning', nfft=1024, overlap=0.5, weighting='None')`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fft_weighting.py
import numpy as np
import pytest
from mf4_analyzer.signal.fft import FFTAnalyzer


def _two_tone(fs=48000, n=48000):
    t = np.arange(n) / fs
    return np.sin(2 * np.pi * 1000 * t) + np.sin(2 * np.pi * 100 * t)


def test_compute_fft_a_weighting_keeps_1khz_attenuates_100hz():
    fs, n = 48000, 48000
    sig = _two_tone(fs, n)
    f, a0 = FFTAnalyzer.compute_fft(sig, fs, 'hanning', nfft=n, weighting='None')
    _, a1 = FFTAnalyzer.compute_fft(sig, fs, 'hanning', nfft=n, weighting='A')
    i100 = int(np.argmin(np.abs(f - 100)))
    i1000 = int(np.argmin(np.abs(f - 1000)))
    assert a1[i1000] == pytest.approx(a0[i1000], rel=0.02)
    ratio_db = 20 * np.log10(a1[i100] / a0[i100])
    assert ratio_db == pytest.approx(-19.1, abs=0.5)


def test_compute_fft_default_is_unweighted():
    fs, n = 48000, 48000
    sig = _two_tone(fs, n)
    f, a_def = FFTAnalyzer.compute_fft(sig, fs, 'hanning', nfft=n)
    _, a_none = FFTAnalyzer.compute_fft(sig, fs, 'hanning', nfft=n, weighting='None')
    np.testing.assert_array_equal(a_def, a_none)


def test_averaged_and_peakhold_accept_weighting():
    fs, n = 48000, 48000
    sig = _two_tone(fs, n)
    f, a, psd = FFTAnalyzer.compute_averaged_fft(sig, fs, 'hanning', 4096, 0.5, weighting='A')
    assert np.all(np.isfinite(a)) and np.allclose(psd, a ** 2, rtol=1e-6)
    f2, pk = FFTAnalyzer.compute_peak_hold_fft(sig, fs, win='hanning', nfft=4096, overlap=0.5, weighting='A')
    i1000 = int(np.argmin(np.abs(f2 - 1000)))
    i100 = int(np.argmin(np.abs(f2 - 100)))
    assert pk[i1000] > pk[i100]  # A-weighting suppresses 100 Hz below 1 kHz
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fft_weighting.py -v`
Expected: FAIL — `compute_fft() got an unexpected keyword argument 'weighting'`

- [ ] **Step 3a: Import the gain helper**

In `mf4_analyzer/signal/fft.py`, add near the top imports:

```python
from .weighting import a_weighting_gain_linear
```

- [ ] **Step 3b: `compute_fft`** — change signature (line 156) and apply gain. Replace the body tail (lines 166-173):

```python
        sig = np.asarray(sig, dtype=float)
        n = len(sig)
        if nfft is None or nfft <= 0:
            nfft = n
        nfft = int(nfft)
        freq, amp = one_sided_amplitude(sig, fs, win=win, nfft=nfft, remove_mean=True)
        if weighting == 'A':
            amp = amp * a_weighting_gain_linear(freq)
        nh = nfft // 2
        return freq[:nh], amp[:nh]
```

and the signature line:

```python
    def compute_fft(sig, fs, win='hanning', nfft=None, weighting='None'):
```

- [ ] **Step 3c: `compute_psd`** — replace (lines 175-178):

```python
    @staticmethod
    def compute_psd(sig, fs, win='hanning', nfft=None, weighting='None'):
        f, a = FFTAnalyzer.compute_fft(sig, fs, win, nfft, weighting=weighting)
        return f, a ** 2
```

- [ ] **Step 3d: `compute_averaged_fft`** — change signature (line 180-181) to add `weighting='None'`, then replace the return tail (lines 242-244):

```python
        psd = psd_sum / n_segments / (w_sum ** 2) * 2
        amp = np.sqrt(psd)
        if weighting == 'A':
            gain = a_weighting_gain_linear(freq)
            amp = amp * gain
            psd = psd * (gain ** 2)
        return freq, amp, psd
```

signature:

```python
    def compute_averaged_fft(sig, fs, win='hanning', nfft=1024, overlap=0.5, weighting='None'):
```

- [ ] **Step 3e: `compute_peak_hold_fft`** — change signature (line 246-247) to add `weighting='None'`, then replace the return tail (lines 278-280):

```python
        if peak is None:
            freq, peak = one_sided_amplitude(sig, fs, win=win, nfft=nfft)
        if weighting == 'A':
            peak = peak * a_weighting_gain_linear(freq)
        return freq, peak
```

signature:

```python
    def compute_peak_hold_fft(sig, fs, win='hanning', nfft=1024, overlap=0.5, weighting='None'):
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_fft_weighting.py -v`
Expected: PASS
Run: `pytest tests/ -k fft -q`
Expected: existing FFT tests still PASS (default `weighting='None'` → unchanged)

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/signal/fft.py tests/test_fft_weighting.py
git commit -m "feat(signal): A-weighting option in FFTAnalyzer (none by default)"
```

---

### Task 7: Spectrogram (FFT vs Time) signal 层 A 计权

`SpectrogramParams` 加 `weighting` 字段；`compute()` 帧循环后按频率行广播加权。

**Files:**
- Modify: `mf4_analyzer/signal/spectrogram.py` — import + `SpectrogramParams`(55-69) 加字段 + `compute()` 帧循环后（line 302 后）加权
- Test: `tests/test_spectrogram_weighting.py`

**Interfaces:**
- Consumes: `a_weighting_gain_linear` (Task 1)
- Produces: `SpectrogramParams(..., weighting: str = 'None')`；compute 结果幅值矩阵每频率行乘 `a_weighting_gain_linear(freq)`。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_spectrogram_weighting.py
import numpy as np
import pytest
from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer, SpectrogramParams
from mf4_analyzer.signal.weighting import a_weighting_gain_linear


def test_spectrogram_weighting_scales_each_freq_row():
    fs, n = 48000, 48000
    t = np.arange(n) / fs
    sig = np.sin(2 * np.pi * 1000 * t) + np.sin(2 * np.pi * 100 * t)
    base = SpectrogramParams(fs=fs, nfft=4096, window='hanning', overlap=0.5)
    wtd = SpectrogramParams(fs=fs, nfft=4096, window='hanning', overlap=0.5, weighting='A')
    r0 = SpectrogramAnalyzer.compute(sig, t, base)
    r1 = SpectrogramAnalyzer.compute(sig, t, wtd)
    gain = a_weighting_gain_linear(r0.frequencies).astype(np.float32)
    np.testing.assert_allclose(r1.amplitude, r0.amplitude * gain[:, None], rtol=1e-3, atol=1e-7)


def test_spectrogram_default_unweighted():
    fs, n = 48000, 24000
    t = np.arange(n) / fs
    sig = np.sin(2 * np.pi * 1000 * t)
    p = SpectrogramParams(fs=fs, nfft=2048, window='hanning', overlap=0.5)
    assert p.weighting == 'None'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_spectrogram_weighting.py -v`
Expected: FAIL — `SpectrogramParams.__init__() got an unexpected keyword argument 'weighting'`

- [ ] **Step 3a: Import + dataclass field**

In `mf4_analyzer/signal/spectrogram.py`, add near the top imports:

```python
from .weighting import a_weighting_gain_linear
```

In the `SpectrogramParams` dataclass (lines 55-69), after `db_reference: float = 1.0` add:

```python
    weighting: str = 'None'  # 'None' | 'A' (IEC 61672 A-weighting)
```

- [ ] **Step 3b: Apply weighting after the frame loop**

In `compute()`, immediately after the frame loop ends and before `return SpectrogramResult(` (i.e. after current line 302, before line 304), insert:

```python
        if params.weighting == 'A':
            amplitude *= a_weighting_gain_linear(freq)[:, np.newaxis]
```

(`amplitude` is float32 shape `(freq_bins, total)`; `freq` is the constant one-sided axis; in-place `*=` keeps float32.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_spectrogram_weighting.py -v`
Expected: PASS
Run: `pytest tests/ -k spectrogram -q`
Expected: existing spectrogram tests still PASS

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/signal/spectrogram.py tests/test_spectrogram_weighting.py
git commit -m "feat(signal): A-weighting option in SpectrogramParams/compute"
```

---

### Task 8: Order (COT) signal 层逐帧 A 计权

`COTParams` 加 `weighting`；`compute()` 帧循环内用每帧 `mean_rpm_frame` 把阶次换算成 Hz 再加权（A 计权按 Hz 定义、阶次轴随转速变）。

**Files:**
- Modify: `mf4_analyzer/signal/order_cot.py` — import + `COTParams`(23-43) 加字段 + `compute()` 帧循环内（line 164 后）逐帧加权
- Test: `tests/test_order_weighting.py`

**Interfaces:**
- Consumes: `a_weighting_gain_linear` (Task 1)
- Produces: `COTParams(..., weighting: str = 'None')`；compute 在每帧把 `out_orders * mean_rpm/60` 换算成 Hz 后乘 `a_weighting_gain_linear`。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_order_weighting.py
import numpy as np
import pytest
from mf4_analyzer.signal.order_cot import COTOrderAnalyzer, COTParams


def test_cot_a_weighting_attenuates_order_by_frame_rpm():
    fs = 20000
    n = int(fs * 5.0)
    t = np.arange(n) / fs
    rpm = np.full(n, 6000.0)            # 100 rev/s -> order k @ k*100 Hz
    rev_rate = 6000.0 / 60.0           # 100 Hz per order
    theta = 2 * np.pi * rev_rate * t
    sig = np.sin(theta * 1) + np.sin(theta * 10)   # order 1 @100Hz, order 10 @1000Hz
    base = COTParams(samples_per_rev=256, nfft=2048, max_order=20.0,
                     order_res=0.05, fs=fs)
    wtd = COTParams(samples_per_rev=256, nfft=2048, max_order=20.0,
                    order_res=0.05, fs=fs, weighting='A')
    r0 = COTOrderAnalyzer.compute(sig, rpm, t, base)
    r1 = COTOrderAnalyzer.compute(sig, rpm, t, wtd)
    o1 = int(np.argmin(np.abs(r0.orders - 1.0)))
    o10 = int(np.argmin(np.abs(r0.orders - 10.0)))
    a0_1, a1_1 = r0.amplitude[:, o1].mean(), r1.amplitude[:, o1].mean()
    a0_10, a1_10 = r0.amplitude[:, o10].mean(), r1.amplitude[:, o10].mean()
    # order 10 @ ~1000 Hz: A-gain ~0 dB
    assert 20 * np.log10(a1_10 / a0_10) == pytest.approx(0.0, abs=0.6)
    # order 1 @ ~100 Hz: A-gain ~-19 dB
    assert 20 * np.log10(a1_1 / a0_1) == pytest.approx(-19.1, abs=1.5)


def test_cot_default_unweighted():
    assert COTParams().weighting == 'None'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_order_weighting.py -v`
Expected: FAIL — `COTParams.__init__() got an unexpected keyword argument 'weighting'`

- [ ] **Step 3a: Import + dataclass field**

In `mf4_analyzer/signal/order_cot.py`, add near the top imports:

```python
from .weighting import a_weighting_gain_linear
```

In the `COTParams` dataclass (lines 23-43), after `min_rpm_floor: float = 10.0` add:

```python
    weighting: str = 'None'  # 'None' | 'A' (per-frame order->Hz A-weighting)
```

- [ ] **Step 3b: Per-frame weighting inside the loop**

In `compute()`, after `amp_matrix[idx, :] = np.interp(...)` (current lines 163-164) and before the `if progress_callback is not None:` block (line 166), insert:

```python
            if params.weighting == 'A' and mean_rpm_frame > 0:
                # A-weighting is defined per Hz; the order axis maps to Hz via
                # this frame's mean RPM (order k -> k * rpm/60 Hz).
                order_freqs_hz = out_orders * (mean_rpm_frame / 60.0)
                amp_matrix[idx, :] *= a_weighting_gain_linear(order_freqs_hz)
```

(`out_orders` and `mean_rpm_frame` are both in scope here; low-RPM frames are already `continue`-skipped above.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_order_weighting.py -v`
Expected: PASS
Run: `pytest tests/ -k order -q`
Expected: existing order tests still PASS

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/signal/order_cot.py tests/test_order_weighting.py
git commit -m "feat(signal): per-frame A-weighting in COT order analysis"
```

---

### Task 9: FFT UI + compute 接线

加 `combo_weighting` 控件；weighting 进 `get_params`（→ compute）、`_collect_preset`（持久化）、load 应用；FFT 计算缓存键纳入 weighting；新增 `set_weighting_default`。

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_fft.py` — 控件创建（line 195 后）、`get_params`(491-510)、`_collect_preset`(370-392)、`_apply_preset_values`(402-440)、`apply_params`(532+)、新增 `set_weighting_default`
- Modify: `mf4_analyzer/ui/main_window/_fft_mixin.py` — `_fft_compute_cache_params`(64-70)、`_fft_compute_arrays`(83-104)
- Test: `tests/test_fft_weighting_ui.py`

**Interfaces:**
- Consumes: FFTAnalyzer weighting 方法 (Task 6)
- Produces: `FFTContextual.set_weighting_default(mode: str)`；`get_params()['weighting']`；FFT 缓存键含 weighting。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fft_weighting_ui.py
import pytest
from mf4_analyzer.ui.inspector_sections.contextual_fft import FFTContextual


def test_fft_weighting_param_roundtrip(qtbot):
    w = FFTContextual()
    qtbot.addWidget(w)
    assert w.get_params()['weighting'] == 'None'      # default
    w.set_weighting_default('A')
    assert w.get_params()['weighting'] == 'A'
    # persistence round-trip
    preset = w._collect_preset()
    assert preset['weighting'] == 'A'
    w.set_weighting_default('None')
    w.apply_params({'weighting': 'A'})
    assert w.get_params()['weighting'] == 'A'


def test_fft_cache_key_includes_weighting():
    from mf4_analyzer.ui.main_window._fft_mixin import FFTMixin
    a = FFTMixin._fft_compute_cache_params({'weighting': 'A'})
    b = FFTMixin._fft_compute_cache_params({'weighting': 'None'})
    assert a['weighting'] == 'A' and b['weighting'] == 'None'
    assert a != b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fft_weighting_ui.py -v`
Expected: FAIL — `'weighting'` not in params / `set_weighting_default` missing

- [ ] **Step 3a: Add the combo widget**

In `contextual_fft.py`, after the `combo_amp_y` row (after line 195, before line 196 `g.setTitle("")`), insert:

```python
        self.combo_weighting = QComboBox()
        self.combo_weighting.addItems(['None', 'A'])
        self.combo_weighting.setCurrentText('None')
        self.combo_weighting.setToolTip(
            'A 计权（IEC 61672）：相对加权频谱，非绝对 dB SPL。\n'
            '识别到音视频文件时自动置 A。')
        fl.addRow(
            "频率加权:",
            _fit_field(self.combo_weighting, max_width=_SHORT_FIELD_MAX_WIDTH),
        )
```

- [ ] **Step 3b: `get_params`** — in the dict (lines 495-509), before the closing `)` add:

```python
            weighting=self.combo_weighting.currentText(),
```

- [ ] **Step 3c: `_collect_preset`** — in the dict (lines 371-391), before the closing `)` add:

```python
            weighting=self.combo_weighting.currentText(),
```

- [ ] **Step 3d: `_apply_preset_values`** — after the `amp_y` block (lines 437-440), add:

```python
        if 'weighting' in d:
            i = self.combo_weighting.findText(str(d['weighting']))
            if i >= 0:
                self.combo_weighting.setCurrentIndex(i)
```

- [ ] **Step 3e: `apply_params`** — add the same block at the end of `apply_params` (after its last `if ... in d:` block):

```python
        if 'weighting' in d:
            i = self.combo_weighting.findText(str(d['weighting']))
            if i >= 0:
                self.combo_weighting.setCurrentIndex(i)
```

- [ ] **Step 3f: `set_weighting_default`** — add a method (e.g. right after `set_recommended_for_unit`, line 368):

```python
    def set_weighting_default(self, mode):
        """Smart default: set the weighting combo to ``mode`` ('A'/'None').

        Called on signal-selection change; audio sources pass 'A'. No-op while
        a preset is being applied so it does not fight an in-flight load.
        """
        if getattr(self, '_applying_preset', False):
            return
        i = self.combo_weighting.findText(str(mode))
        if i >= 0:
            self.combo_weighting.setCurrentIndex(i)
```

- [ ] **Step 3g: FFT cache key** — in `_fft_mixin.py` `_fft_compute_cache_params` (lines 65-70), add inside the returned dict:

```python
            'weighting': fft_params.get('weighting', 'None'),
```

- [ ] **Step 3h: Pass weighting into compute** — in `_fft_mixin.py` `_fft_compute_arrays` (lines 89-104), after `avg_overlap = ...` (line 93) add:

```python
        weighting = fft_params.get('weighting', 'None')
```

then add `weighting=weighting` to the three FFTAnalyzer calls:

```python
        if avg_mode == '线性平均':
            freq, amp, psd = FFTAnalyzer.compute_averaged_fft(
                sig, fs, win, int(nfft), avg_overlap, weighting=weighting)
        elif avg_mode == '峰值保持':
            freq, amp = FFTAnalyzer.compute_peak_hold_fft(
                sig, fs, win=win, nfft=int(nfft), overlap=avg_overlap, weighting=weighting)
            psd = amp ** 2
        else:
            freq, amp = FFTAnalyzer.compute_fft(sig, fs, win, nfft, weighting=weighting)
            _, psd = FFTAnalyzer.compute_psd(sig, fs, win, nfft, weighting=weighting)
        return freq, amp, psd
```

(注：`_do_fft_single` 的 dB 块（_fft_mixin.py:268-273）在加权后的 `amp` 上做归一化，**无需改**——天然得到相对 A 加权谱。)

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_fft_weighting_ui.py -v`
Expected: PASS
Run: `python -c "import mf4_analyzer.ui.main_window._fft_mixin, mf4_analyzer.ui.inspector_sections.contextual_fft"`
Expected: no error

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/inspector_sections/contextual_fft.py mf4_analyzer/ui/main_window/_fft_mixin.py tests/test_fft_weighting_ui.py
git commit -m "feat(ui): FFT weighting combo + params + cache key"
```

---

### Task 10: FFT vs Time UI + compute 接线

加 `combo_weighting`；weighting 进 `get_params`、`_collect_preset`、load 应用；两处 `SpectrogramParams` 构造穿入 weighting；新增 `set_weighting_default`。

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_fft_time.py` — 控件创建、`get_params`(447-480)、`_collect_preset`(736-763)、`_apply_preset_values`(765 后的 applier)、`apply_params`(488+)、新增 `set_weighting_default`
- Modify: `mf4_analyzer/ui/main_window/_fft_time_mixin.py` — `SpectrogramParams` 两处构造（361-368、470-477）
- Test: `tests/test_fft_time_weighting_ui.py`

**Interfaces:**
- Consumes: `SpectrogramParams(weighting=...)` (Task 7)
- Produces: `FFTTimeContextual.set_weighting_default(mode)`；`get_params()['weighting']`；两处 SpectrogramParams 带 weighting。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fft_time_weighting_ui.py
import pytest
from mf4_analyzer.ui.inspector_sections.contextual_fft_time import FFTTimeContextual


def test_fft_time_weighting_param_roundtrip(qtbot):
    w = FFTTimeContextual()
    qtbot.addWidget(w)
    assert w.get_params()['weighting'] == 'None'
    w.set_weighting_default('A')
    assert w.get_params()['weighting'] == 'A'
    assert w._collect_preset()['weighting'] == 'A'
    w.set_weighting_default('None')
    w.apply_params({'weighting': 'A'})
    assert w.get_params()['weighting'] == 'A'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fft_time_weighting_ui.py -v`
Expected: FAIL — `'weighting'` missing / `set_weighting_default` missing

- [ ] **Step 3a: Add the combo widget**

In `contextual_fft_time.py`, find the params QFormLayout where `combo_amp_unit` is added (the Z-axis amplitude-unit row) and add a weighting row right after it:

```python
        self.combo_weighting = QComboBox()
        self.combo_weighting.addItems(['None', 'A'])
        self.combo_weighting.setCurrentText('None')
        self.combo_weighting.setToolTip(
            'A 计权（IEC 61672）：相对加权频谱图，非绝对 dB SPL。')
        fl.addRow("频率加权:", self.combo_weighting)
```

> 用与本文件其它 `fl.addRow(...)` 一致的字段包装（若本文件用 `_fit_field`，照用）。

- [ ] **Step 3b: `get_params`** — in the `params = dict(...)` (lines 447-466), add a key (before the closing `)` or right after `cmap=`):

```python
            weighting=self.combo_weighting.currentText(),
```

- [ ] **Step 3c: `_collect_preset`** — in the returned dict (lines 736-762), add:

```python
            weighting=self.combo_weighting.currentText(),
```

- [ ] **Step 3d: apply on preset-load — BOTH `_apply_preset_values` AND `apply_params`**

The PresetBar load path goes through `_apply_preset` → `_apply_preset_values`; tests use `apply_params`. Add the SAME block to the end of **both** methods (find `_apply_preset_values` — invoked from `_apply_preset` at line 765-768 — and `apply_params` at line 488):

```python
        if 'weighting' in d:
            i = self.combo_weighting.findText(str(d['weighting']))
            if i >= 0:
                self.combo_weighting.setCurrentIndex(i)
```

- [ ] **Step 3e: `set_weighting_default`** — add (e.g. after `set_recommended_for_unit`, line 891):

```python
    def set_weighting_default(self, mode):
        """Smart default: set the weighting combo to ``mode`` unless mid-preset."""
        if getattr(self, '_applying_preset', False):
            return
        i = self.combo_weighting.findText(str(mode))
        if i >= 0:
            self.combo_weighting.setCurrentIndex(i)
```

- [ ] **Step 3f: Thread weighting into BOTH SpectrogramParams constructions**

In `_fft_time_mixin.py`, the construction at lines 361-368, after `db_reference=...` add:

```python
            weighting=str(p.get('weighting', 'None')),
```

And the identical construction at lines 470-477, after `db_reference=...` add:

```python
            weighting=str(p.get('weighting', 'None')),
```

(`p` is the fft_time params dict from `get_params`, which now carries `weighting`. The fft_time analysis cache key is `dict(p, ...)`, so weighting is already part of it — no separate cache edit needed.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_fft_time_weighting_ui.py -v`
Expected: PASS
Run: `python -c "import mf4_analyzer.ui.main_window._fft_time_mixin, mf4_analyzer.ui.inspector_sections.contextual_fft_time"`
Expected: no error

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/inspector_sections/contextual_fft_time.py mf4_analyzer/ui/main_window/_fft_time_mixin.py tests/test_fft_time_weighting_ui.py
git commit -m "feat(ui): FFT-vs-Time weighting combo + params + SpectrogramParams"
```

---

### Task 11: Order UI + compute 接线

加 `combo_weighting`；weighting 进 `get_params`、`_collect_preset`、load 应用；`COTParams` 构造穿入 weighting；新增 `set_weighting_default`。

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_order.py` — 控件创建、`get_params`(535-545)、`_collect_preset`(358-383)、`_apply_preset_values`(393+)、`apply_params`(578+)、新增 `set_weighting_default`
- Modify: `mf4_analyzer/ui/main_window/_order_mixin.py` — `COTParams` 构造（331-339）
- Test: `tests/test_order_weighting_ui.py`

**Interfaces:**
- Consumes: `COTParams(weighting=...)` (Task 8)
- Produces: `OrderContextual.set_weighting_default(mode)`；`get_params()['weighting']`；COTParams 带 weighting。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_order_weighting_ui.py
import pytest
from mf4_analyzer.ui.inspector_sections.contextual_order import OrderContextual


def test_order_weighting_param_roundtrip(qtbot):
    w = OrderContextual()
    qtbot.addWidget(w)
    assert w.get_params()['weighting'] == 'None'
    w.set_weighting_default('A')
    assert w.get_params()['weighting'] == 'A'
    assert w._collect_preset()['weighting'] == 'A'
    w.set_weighting_default('None')
    w.apply_params({'weighting': 'A'})
    assert w.get_params()['weighting'] == 'A'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_order_weighting_ui.py -v`
Expected: FAIL — `'weighting'` missing / `set_weighting_default` missing

- [ ] **Step 3a: Add the combo widget**

In `contextual_order.py`, find the params QFormLayout where `combo_amp_unit` is added and add a weighting row right after it:

```python
        self.combo_weighting = QComboBox()
        self.combo_weighting.addItems(['None', 'A'])
        self.combo_weighting.setCurrentText('None')
        self.combo_weighting.setToolTip(
            'A 计权（IEC 61672）：按每帧转速将阶次换算成 Hz 加权；相对谱，非 dB SPL。')
        fl.addRow("频率加权:", self.combo_weighting)
```

> 用与本文件其它 `fl.addRow(...)` 一致的字段包装。

- [ ] **Step 3b: `get_params`** — in the `return dict(...)` (lines 535-545), add:

```python
            weighting=self.combo_weighting.currentText(),
```

- [ ] **Step 3c: `_collect_preset`** — in the returned dict (lines 358-383), add:

```python
            weighting=self.combo_weighting.currentText(),
```

- [ ] **Step 3d: `_apply_preset_values`** — add a block at the end of `_apply_preset_values`:

```python
        if 'weighting' in d:
            i = self.combo_weighting.findText(str(d['weighting']))
            if i >= 0:
                self.combo_weighting.setCurrentIndex(i)
```

- [ ] **Step 3e: `apply_params`** — add the same block at the end of `apply_params`:

```python
        if 'weighting' in d:
            i = self.combo_weighting.findText(str(d['weighting']))
            if i >= 0:
                self.combo_weighting.setCurrentIndex(i)
```

- [ ] **Step 3f: `set_weighting_default`** — add (e.g. after `set_recommended_for_unit`, line 356):

```python
    def set_weighting_default(self, mode):
        """Smart default: set the weighting combo to ``mode`` unless mid-preset."""
        if getattr(self, '_applying_preset', False):
            return
        i = self.combo_weighting.findText(str(mode))
        if i >= 0:
            self.combo_weighting.setCurrentIndex(i)
```

- [ ] **Step 3g: Thread weighting into COTParams**

In `_order_mixin.py`, the `COTParams(...)` construction (lines 331-339), after `fs=fs,` add:

```python
                weighting=str(op.get('weighting', 'None')),
```

(`op` is the order params dict carrying `weighting`; the order analysis cache key hashes `op`, so weighting is already in the key — no separate cache edit.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_order_weighting_ui.py -v`
Expected: PASS
Run: `python -c "import mf4_analyzer.ui.main_window._order_mixin, mf4_analyzer.ui.inspector_sections.contextual_order"`
Expected: no error

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/inspector_sections/contextual_order.py mf4_analyzer/ui/main_window/_order_mixin.py tests/test_order_weighting_ui.py
git commit -m "feat(ui): Order weighting combo + params + COTParams"
```

---

### Task 12: batch 三分析穿入 weighting

批处理三个分析的 dataclass/方法构造从 `preset.params` 读出 weighting。

**Files:**
- Modify: `mf4_analyzer/batch.py` — `_compute_fft_dataframe`(561-569 区域 `compute_fft` 调用)、`COTParams` 构造（595-603）、`SpectrogramParams` 构造（640-647）
- Test: `tests/test_batch_weighting.py`

**Interfaces:**
- Consumes: FFTAnalyzer weighting (Task 6)、COTParams weighting (Task 8)、SpectrogramParams weighting (Task 7)
- Produces: batch 三分析按 `params.get('weighting','None')` 加权。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_batch_weighting.py
import numpy as np
from mf4_analyzer.batch import BatchRunner


def test_batch_fft_dataframe_weighting_attenuates_low_freq():
    fs, n = 48000, 48000
    t = np.arange(n) / fs
    sig = np.sin(2 * np.pi * 1000 * t) + np.sin(2 * np.pi * 100 * t)
    base = BatchRunner._compute_fft_dataframe(sig, fs, {'window': 'hanning', 'nfft': n})
    wtd = BatchRunner._compute_fft_dataframe(sig, fs, {'window': 'hanning', 'nfft': n, 'weighting': 'A'})
    # locate 100 Hz row in both; weighted amplitude must be clearly lower
    fcol = [c for c in base.columns if 'freq' in c.lower()][0]
    acol = [c for c in base.columns if c != fcol][0]
    i100_b = int((base[fcol] - 100).abs().idxmin())
    i100_w = int((wtd[fcol] - 100).abs().idxmin())
    assert wtd[acol].iloc[i100_w] < base[acol].iloc[i100_b] * 0.3
```

> 若 `_compute_fft_dataframe` 的列名/返回形态与上不符，按其真实结构调整断言（先打印 `base.columns`）。核心断言：weighting='A' 时 100 Hz 幅值显著低于不加权。

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_batch_weighting.py -v`
Expected: FAIL — weighted == unweighted（weighting 还没穿进去）

- [ ] **Step 3a: FFT batch path** — in `batch.py` `_compute_fft_dataframe`, the `FFTAnalyzer.compute_fft(...)` call (around line 569). Read the call, then add `weighting=str(params.get('weighting', 'None'))` to it. E.g.:

```python
        freq, amp = FFTAnalyzer.compute_fft(
            sig, fs, str(params.get('window', 'hanning')),
            params.get('nfft'),
            weighting=str(params.get('weighting', 'None')),
        )
```

> 按该函数现有实参顺序对齐（保持既有 window/nfft 取法不变，只追加 `weighting=`）。

- [ ] **Step 3b: Order batch path** — in `COTParams(...)` (lines 595-603), after `fs=float(fs),` add:

```python
            weighting=str(params.get('weighting', 'None')),
```

- [ ] **Step 3c: FFT-time batch path** — in `SpectrogramParams(...)` (lines 640-647), after `db_reference=...` add:

```python
            weighting=str(params.get('weighting', 'None')),
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_batch_weighting.py -v`
Expected: PASS
Run: `pytest tests/ -k batch -q`
Expected: existing batch tests still PASS

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/batch.py tests/test_batch_weighting.py
git commit -m "feat(batch): thread A-weighting through fft/order/fft-time"
```

---

### Task 13: 智能默认接线（音视频 → 三 contextual 置 A）

选中信号时：若源文件 `is_audio_source()` → 三个 contextual 的加权组合框置 'A'。fft/order 走 `_on_inspector_signal_changed`，fft_time 走 `_on_fft_time_signal_changed`（两个独立处理器）。

**Files:**
- Modify: `mf4_analyzer/ui/main_window/window.py` — `_on_inspector_signal_changed`(1254-1267)、`_on_fft_time_signal_changed`(1283-1297)
- Test: `tests/test_smart_default_weighting.py`

**Interfaces:**
- Consumes: `FileData.is_audio_source()` (Task 3)、三 contextual 的 `set_weighting_default` (Tasks 9/10/11)
- Produces: 选中音频信号 → 三 combo 自动 'A'；非音频不动。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_smart_default_weighting.py
import numpy as np
import pandas as pd
import pytest
from mf4_analyzer.io.file_data import FileData


def _audio_fd():
    df = pd.DataFrame({'audio': np.zeros(1000, dtype=np.float32)})
    return FileData('clip.wav', df, ['audio'], {'audio': ''}, idx=1, fs=48000.0,
                    source_metadata={'source_kind': 'audio'})


def _plain_fd():
    df = pd.DataFrame({'Time': np.arange(1000) / 1000.0, 'sig': np.zeros(1000)})
    return FileData('m.csv', df, ['Time', 'sig'], {'sig': ''}, idx=2)


def test_audio_signal_sets_weighting_A(main_window, qtbot):
    mw = main_window
    fd = _audio_fd()
    mw.files[fd.file_index] = fd
    mw._on_inspector_signal_changed('fft', (fd.file_index, 'audio'))
    mw._on_fft_time_signal_changed((fd.file_index, 'audio'))
    assert mw.inspector.fft_ctx.get_params()['weighting'] == 'A'
    assert mw.inspector.order_ctx.get_params()['weighting'] == 'A'
    assert mw.inspector.fft_time_ctx.get_params()['weighting'] == 'A'


def test_plain_signal_leaves_weighting_untouched(main_window, qtbot):
    mw = main_window
    fd = _plain_fd()
    mw.files[fd.file_index] = fd
    mw.inspector.fft_ctx.set_weighting_default('None')
    mw._on_inspector_signal_changed('fft', (fd.file_index, 'sig'))
    assert mw.inspector.fft_ctx.get_params()['weighting'] == 'None'
```

> `main_window` fixture：复用 `tests/` 既有的 main-window/pytest-qt fixture（先 `grep -rn "def main_window\|MainWindow(" tests/` 找现成 fixture；没有则按既有 UI 测试构造 MainWindow 的方式建一个最小 fixture）。

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smart_default_weighting.py -v`
Expected: FAIL — 选中音频后 weighting 仍为 'None'（接线未加）

- [ ] **Step 3a: Wire fft/order handler** — in `window.py` `_on_inspector_signal_changed`, after the recommend block (lines 1265-1267), add:

```python
        fd = self.files.get(data[0]) if data else None
        if fd is not None and fd.is_audio_source():
            self.inspector.fft_ctx.set_weighting_default('A')
            self.inspector.order_ctx.set_weighting_default('A')
```

- [ ] **Step 3b: Wire fft_time handler** — in `window.py` `_on_fft_time_signal_changed`, after `self.inspector.fft_time_ctx.set_recommended_for_unit(unit)` (line 1291), add:

```python
        fd = self.files.get(data[0]) if data else None
        if fd is not None and fd.is_audio_source():
            self.inspector.fft_time_ctx.set_weighting_default('A')
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_smart_default_weighting.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/main_window/window.py tests/test_smart_default_weighting.py
git commit -m "feat(ui): audio source auto-enables A-weighting on all 3 analyses"
```

---

### Task 14: 持久化往返 + 全量回归 + 真机验证

收尾：预设持久化往返、全套回归、真机渲染验证（CLAUDE.md 强制）。

**Files:**
- Test: `tests/test_weighting_persistence.py`
- Verify only（不改产品代码，除非发现缺陷）

- [ ] **Step 1: Write persistence round-trip test**

```python
# tests/test_weighting_persistence.py
import pytest
from mf4_analyzer.ui.inspector_sections.contextual_fft import FFTContextual


def test_preset_dict_without_weighting_defaults_none(qtbot):
    w = FFTContextual()
    qtbot.addWidget(w)
    # legacy preset (no weighting key) must not crash and must leave 'None'
    legacy = {k: v for k, v in w._collect_preset().items() if k != 'weighting'}
    w._apply_preset_values(legacy)
    assert w.get_params()['weighting'] == 'None'


def test_preset_dict_with_weighting_roundtrips(qtbot):
    w = FFTContextual()
    qtbot.addWidget(w)
    w.set_weighting_default('A')
    saved = w._collect_preset()
    w.set_weighting_default('None')
    w._apply_preset_values(saved)
    assert w.get_params()['weighting'] == 'A'
```

- [ ] **Step 2: Run persistence test**

Run: `pytest tests/test_weighting_persistence.py -v`
Expected: PASS

- [ ] **Step 3: Full regression**

Run: `pytest`
Expected: all prior 164 + new tests PASS, no regressions (default `weighting='None'` keeps mechanical-domain numerics byte-identical)
Run: `pytest -m slow`
Expected: PASS

- [ ] **Step 4: Real-render UI verification (CLAUDE.md mandatory)**

启动 GUI，导入一个真实 mp3/mp4，逐项验证（截图存档）：
1. 文件对话框过滤器列出音视频类型，能选中并加载，音轨进通道列表。
2. 选中音频信号后，FFT / FFT vs Time / Order 三个面板的「频率加权」组合框**自动显示 A**。
3. 手动切回 None → 重算 → 谱明显不同（低频抬升）；切 A → 低频被压、~1kHz 不变。
4. 加权组合框、tooltip 在 macOS 原生渲染下正常（无灰底/无错位；嵌入容器透明背景规则）。
5. 存预设（带 A）→ 重开应用 → A 保留。

```bash
python "MF4 Data Analyzer V1.py"
```

记录：截图 + 一句"三面板加权下拉真机显示 A、谱随加权变化正确"。若任何项不符 → 回到对应 Task 修复。

- [ ] **Step 5: Commit**

```bash
git add tests/test_weighting_persistence.py
git commit -m "test: weighting persistence round-trip + back-compat"
```

---

## Self-Review

**1. Spec coverage（spec 各节 → 任务映射）：**
- §4 音视频导入：Task 2（loader+av）、Task 3（FileData fs/标记）、Task 4（UI 分派）、Task 5（batch 分派）✓
- §5 A 计权数学模块：Task 1 ✓
- §6.1 FFT 挂载：Task 6（signal）+ Task 9（UI/cache）✓
- §6.2 Spectrogram 挂载：Task 7（signal）+ Task 10（UI/构造）✓
- §6.3 Order 逐帧变权：Task 8（signal）+ Task 11（UI/构造）✓
- §6.4 三 UI 控件：Tasks 9/10/11 ✓
- §6.5 参数/持久化：Tasks 9/10/11 的 _collect_preset + Task 14 往返 ✓
- §7 智能默认：Task 13（两处接线）+ set_weighting_default（Tasks 9/10/11）✓
- §8 错误处理：Task 2 无音轨 ValueError、Task 4/5 分派 ✓（解码失败/未装 av 的 UI 提示由 `_load_one` 既有 `except`→QMessageBox 兜底）
- §9 测试：每任务 TDD + Task 14 回归/真机 ✓
- batch 三分析穿权：Task 12 ✓

**2. Placeholder scan:** 无 TBD/TODO；每个 code step 给出完整代码。两处"按真实结构调整断言"（Task 12 列名、Task 13 fixture）是测试适配既有代码的明确指令，非占位（已给 grep/打印的兜底办法）。

**3. Type consistency:** `weighting` 全程字符串 `'None'|'A'`，默认 `'None'`；`a_weighting_gain_linear`/`a_weighting_gain_db` 命名在 Task 1 定义、Tasks 6/7/8 一致引用；`set_weighting_default` 三 contextual 同签名；`is_audio_source` Task 3 定义、Tasks 4/5/13 一致引用；`load_audio_video` 5 元组在 Tasks 2/4/5 一致解构。

---

## Execution Handoff

> 实施期若用户消息含 `squad`/`团队`/`分工`/`重构`/`refactor`/`多专家`/`multi-agent`/`agent` 等触发词，则**全程不得自己写改 `.py`**，须走 squad runbook：数值改动（Tasks 1/6/7/8/12）派 `signal-processing-expert`（TDD-first），UI 改动（Tasks 4/9/10/11/13）派 `pyqt-ui-engineer`（并验真机渲染），导入/分派（Tasks 2/3/5）按文件归属派对应专家。未触发则按下方常规执行。
