# Lite Importer Dependency Pruning Design

## Goal

Reduce the Windows analyzer-only (`lite`) onedir artifact without reducing its documented data-import support: legacy MATLAB `.mat`, MATLAB v7.3/HDF5 `.mat`, and audio/video files with audio tracks (`.mp4`, `.mov`, `.mkv`, `.m4v`, `.mp3`, `.m4a`, `.aac`, `.wav`, `.flac`). The full acquisition build is out of scope and retains its current conservative importer collection policy.

## Evidence and scope

The current lite build obtains one shared list of `--collect-all` arguments. Its largest optional-importer contributors are:

| Runtime package | Current installed footprint | Analyzer use |
| --- | ---: | --- |
| `scipy` + `scipy.libs` | 129.9 MB | `scipy.io.loadmat` and the version probe in `mf4_analyzer/io/mat_format.py` |
| `av` + `av.libs` | 65.9 MB | `av.open` and `av.AudioResampler` in `DataLoader.load_audio_video` |
| `h5py` | 8.5 MB | v7.3/HDF5 MATLAB fallback in `_collect_h5py` |

An import trace of `from scipy.io import loadmat` reaches only `scipy.io`, `scipy.io.matlab`, `scipy.sparse`, `scipy._lib`, and `scipy._cyutility` (about 6 MB of loaded SciPy files before native-dependency closure). Whole-SciPy collection additionally carries unused `stats`, `optimize`, `special`, `linalg`, `signal`, `spatial`, and `interpolate` trees.

The application does not import SciPy from FFT, FFT-vs-Time, Order analysis, or their batch paths. `mf4_analyzer/signal/fft.py` deliberately implements its window and spectral helpers with NumPy; references to SciPy there are comments or compatibility descriptions only. Packaging changes must not touch those modules or analysis UI/canvas files.

PyAV is different. Its `_core.pyd` imports FFmpeg's `avcodec`, `avformat`, `avfilter`, `avdevice`, `avutil`, `swscale`, and `swresample` DLLs. `avcodec` has load-time dependencies on codec DLLs in `av.libs`, including x264, x265, AV1, VP9, Opus, and MP3. Deleting individual `av.libs` files would break process loading before the decoder can choose a stream. Meaningful PyAV DLL reduction requires a custom FFmpeg/PyAV build and narrowed supported formats; that is out of scope.

## Design

### Shared importer contract, flavor-specific collection

Keep `FROZEN_IMPORT_DEPENDENCIES` as the single declaration of lazy importers and requirements validation. Extend `pyinstaller_collection_args()` with a `flavor` argument:

- `full` retains `--collect-all <package>` for every declared dependency.
- `lite` retains `--collect-all` for `h5py` and the existing non-SciPy importers, but replaces `--collect-all scipy` with explicit hidden imports for `scipy.io` and `scipy.io.matlab`.

The standard PyInstaller SciPy hook remains active. It includes the SciPy DLL bundle and required utility extensions, but does not recursively collect all SciPy subpackages. This conservative change lets PyInstaller discover `loadmat` and sparse-matrix imports while removing unused toolkit trees. The 19.3 MB OpenBLAS DLL stays unless a frozen smoke test proves otherwise; this work does not add an untested custom replacement for PyInstaller's SciPy hook.

### Lite build invocation

`tools/windows_runtime_dependencies.py` accepts `--flavor full|lite` and passes the value to `pyinstaller_collection_args()`. The full builder requests `full`; the lite builder requests `lite`. Both continue running the same `--verify` contract, so new lazy importers must be declared, required, and not excluded by either builder.

### Verification

Unit tests cover both argument sets, builder flavors, and absence of `--collect-all scipy` from lite. Existing MATLAB and audio loader tests remain source-level checks. Add a non-GUI `--importer-runtime-smoke` child mode to the frozen entry script; it accepts repeated `--import-path` arguments, loads each path through `DataLoader`, and writes a JSON record with its channel count. `tools/verify_lite_importer_runtime.py` creates a numeric HDF5 `.mat` and PCM WAV, invokes that child mode for those files plus the legacy MAT sample, and fails on a nonzero child exit or zero-channel result. Focused FFT, FFT-vs-Time, and Order tests confirm analysis isolation.

The 383.1 MB uncompressed baseline is expected to fall by about 75--80 MB after removing unused SciPy package trees. The conservative design keeps OpenBLAS until proven otherwise, so the target range is about 303--308 MB. A compressed-release size is measured after the build and is not predicted from a fixed compression ratio.

## Non-goals

- Do not modify `mf4_analyzer/signal/fft.py`, `mf4_analyzer/signal/order.py`, batch processing, or analysis UI/canvas code.
- Do not remove `h5py` or v7.3 MATLAB support.
- Do not delete individual PyAV/FFmpeg DLLs.
- Do not change the full acquisition build's importer collection behavior.
