# 批处理对话框块状重构设计

**日期：** 2026-04-26
**作者：** brainstorm 输出（main Claude + 用户）
**状态：** spec — 待用户 review

## 1. 背景

当前 `mf4_analyzer/ui/drawers/batch_sheet.py` 是一个 `QTabWidget`：
- Tab "当前单次"：展示主窗口当前一次分析作为 preset 摘要（只读 label）
- Tab "自由配置"：手动表单（任务 + 8 个参数 + RPM 通道 + 信号匹配 pattern）
- Output 区：在 Tab 之外，全局共享（目录 / 数据 / 图片 / 格式）

后端 `mf4_analyzer/batch.py`：
- `AnalysisPreset` 数据类，两种来源：`current_single` / `free_config`
- `BatchRunner._expand_tasks` 通过 `signal_pattern`（substring 优先 + regex 兜底）匹配信号
- `BatchRunner.run` 接 `progress_callback(index, total)`，仅汇总状态

### 现状问题

1. **概念错位**。"当前单次" / "自由配置" 是 *来源* 维度，而批处理的核心其实是 input → analysis → output 流水线。Tab 把 OUTPUT 抽离到全局，把 INPUT 和 ANALYSIS 揉在一起。
2. **多文件 × 同一信号是真实场景，但 UI 是按 "信号 pattern" 在抽象**。用户很少需要 fuzzy/regex 匹配；更常见的是"我有 N 个 .mf4，每个里都有 vibration_x 和 engine_rpm，跑一遍 FFT"。
3. **参数无差别全显示**。FFT 不需要"目标阶次/RPM 系数"，但表单里照样在；视觉噪声大。
4. **没有 preset 文件持久化**。用户配置完一次自由配置，下次还得重填。
5. **没有运行预览**。运行前看不到将生成多少个任务、哪些文件 / 信号；跑错的代价是删一堆错文件。
6. **进度反馈薄弱**。仅 `index/total`，没有 per-task 状态。

## 2. 目标

1. 把对话框重构为 **input → analysis → output** 三阶段块状结构（顶部摘要链路 + 下方三列详情对齐）。
2. **输入语义对齐真实场景**：明确选 N 个文件 + 1 至 M 个目标信号（多选），删除 fuzzy `signal_pattern`。
3. 支持两类入口：
   - 从主窗口当前单次分析"填入"（一次性快照，沿用现有 `from_current_single`）
   - **导入 / 导出 preset 文件**（JSON，跨机器可移植 — 不含 `output_dir` 和文件路径）
4. **底部任务列表**双重职能：运行前 dry-run 预览 + 运行中实时进度（⏸/⟳/✓/✗）。
5. ANALYSIS 块**按方法动态显示**参数，方法用按钮组而非下拉。
6. **不破坏** `BatchRunner` 的批处理后端语义，只扩展事件接口。

### 非目标

- 不引入新的分析方法（FFT / order_time / order_rpm / order_track 维持原状）。
- 不改变 `AnalysisPreset.from_current_single` 的语义（继续支持单文件单信号快照）。
- 不做 preset 的迁移机制（仅 v1；遇到未来 v2 直接拒绝加载，提示用户）。
- 不做 preset 库（presets 目录列表 / 收藏 / 标签等）。

## 3. UI 设计

### 3.1 整体布局

对话框尺寸 **1080 × 760**（resizable，最小 960 × 680）。结构：

```
┌──────────────────────────────────────────────────────────────────┐
│                                            [从当前单次填入]      │
│                                            [导入 preset…]        │
│                                            [导出 preset…]        │
├──────────────────────────────────────────────────────────────────┤
│ ┌────────────┐    ┌────────────┐    ┌────────────┐              │
│ │ ① INPUT  ✓ │    │ ② ANALYSIS │    │ ③ OUTPUT ✓ │   摘要链路   │
│ │ 3文件·2信号 │    │ FFT·hanning│    │ CSV+PNG    │              │
│ └────────────┘    └────────────┘    └────────────┘              │
├──────────────────────────────────────────────────────────────────┤
│ ┌────────────┐    ┌────────────┐    ┌────────────┐              │
│ │ 文件列表   │    │ 方法按钮组  │    │ 输出目录   │   详情三列   │
│ │ 信号 chips │    │ 动态参数表  │    │ 导出选项   │   （列宽与   │
│ │ RPM 通道   │    │            │    │ 数据格式   │   摘要对齐） │
│ │ 时间范围   │    │            │    │            │              │
│ └────────────┘    └────────────┘    └────────────┘              │
├──────────────────────────────────────────────────────────────────┤
│ ▾ 6 任务待执行 · 12 输出                          ← 折叠任务列表 │
├──────────────────────────────────────────────────────────────────┤
│                                          [Cancel]    [运行]      │
└──────────────────────────────────────────────────────────────────┘
```

视觉细节：
- 每块顶部 4px 色条作 stage 标识（蓝/绿/橙）
- 摘要卡片右上角 `✓` / `⚠`：三块都 ✓ 时启用 "运行" 按钮
- 卡片内边距 14-16px，圆角 10px，微阴影 `0 1px 2px rgba(0,0,0,0.04)`
- 字号：标题 14px / 正文 13px / 分组小标题 11px 全大写 letter-spacing 0.5px
- 按钮 padding 8px·12px，font 13px

### 3.2 INPUT 列

```
文件 (3)              [+ 已加载] [+ 磁盘…]
┌─────────────────────────────────┐
│ run_2024_03_a.mf4              ×│
│ run_2024_03_b.mf4              ×│
│ run_2024_03_c.mf4              ×│
└─────────────────────────────────┘

目标信号
┌─────────────────────────────────┐
│ [vibration_x ×] [vibration_y ×]▾│  ← 点击展开 popup
└─────────────────────────────────┘

RPM 通道       [engine_rpm           ▾]
时间范围       [_____________________  ]  (留空=全段；"a,b" 表示 [a,b]s)
```

**信号选择器**（自定义 widget `SignalPickerPopup`）：
- 显示态：一行 chips（已选信号），尾部展开箭头 `▾`
- 展开 popup：顶部 `QLineEdit` 搜索框 + 下方多选列表
- 列表项：所有"在所有已选文件中都存在的信号"为可选；"仅在部分文件中存在的"灰显并标注 `(2/3)`，不可选
- 列表项前 `QCheckBox`，主区 chip 跟随选中态实时更新
- popup 失焦自动收起；ESC 键也收起

**文件管理**：
- "+ 已加载"：弹小菜单从 `main_window.files` 中挑（多选）
- "+ 磁盘…"：`QFileDialog.getOpenFileNames` 选 `.mf4`，**不**做完整加载（懒加载到运行时）；仅做 metadata-only probe 读出 channel 名列表（asammdf `MDF(path).channels_db.keys()` 不解码采样数据）— 否则大文件加进来 batch 对话框就卡顿
- 列表里 `×` 按钮移除单条；列表项右侧显示文件状态徽标（见下表）
- 文件列表变化 → 重算"信号交集" → 信号 popup 列表刷新

**文件状态机**（每条文件列表项独立持有）：

| 状态 | 触发 | 视觉 | 是否参与信号交集 | 是否参与任务展开 |
|---|---|---|:-:|:-:|
| `loaded` | "+ 已加载" 加入；或 `path_pending` 完成探针 | 默认行 | ✓ | ✓ |
| `path_pending` | "+ 磁盘…" 加入瞬间 | 行末 spinner | ✗（先排除）→ probe 完成后转 `loaded` | — |
| `probing` | 后台读 channel 列表中（一般 < 1s） | 行末 spinner | ✗ | — |
| `probe_failed` | metadata 探针失败（坏 mf4） | 行末红 ⚠ + tooltip 错误 | ✗ | ✗ |
| `loading`（仅运行时） | 运行到该文件、首次读采样 | — | — | — |
| `load_failed`（仅运行时） | 运行时全量加载失败 | 任务列表对应行 ✗ + tooltip | — | 该文件所有 task 标 ✗ |

**Probe 策略**：磁盘文件加入 → 立刻派一个轻量后台任务（`QThreadPool` 或简短 worker）读 `MDF(path).channels_db`，得到 channel 名集合，缓存在 BatchSheet 内存（`{path: frozenset[str]}`）；探针完成后状态转 `loaded`，触发信号交集重算。**dry-run 任务清单计入 `loaded` 状态文件**；`path_pending` / `probing` 状态期间，底部任务列表标"……正在解析 N 个文件"，运行按钮 disabled。

**运行时读失败处理（`load_failed`）**：`BatchRunner._resolve_files` 全量加载某 disk path 抛异常 → 该文件的**所有任务**直接发 `task_failed` 事件（error="cannot load mf4: ..."），不影响其他文件继续。运行不 fast-fail。

### 3.3 ANALYSIS 列

```
分析方法
[ FFT (selected) ] [ order_time ]
[ order_rpm      ] [ order_track ]

参数（按方法动态显示）
窗函数:    [hanning ▾]
NFFT:      [1024]
（FFT 不显示阶次相关 / RPM 系数）
```

**方法切换** → 参数表单按 method 重渲：

| 字段 | fft | order_time | order_rpm | order_track |
|---|:-:|:-:|:-:|:-:|
| 窗函数 | ✓ | ✓ | ✓ | ✓ |
| NFFT | ✓ | ✓ | ✓ | ✓ |
| 最大阶次 |   | ✓ | ✓ | ✓ |
| 阶次分辨率 |   | ✓ | ✓ |   |
| 时间分辨率 |   | ✓ |   |   |
| RPM 分辨率 |   |   | ✓ |   |
| 目标阶次 |   |   |   | ✓ |
| RPM 系数 |   | ✓ | ✓ | ✓ |

切换方法时保留共享字段（窗函数 / NFFT），其余按方法刷新默认值。

### 3.4 OUTPUT 列

```
输出目录
[~/Desktop/mf4_batch_output  ] [选择…]

导出内容
[✓] 数据文件
[✓] 图片

数据格式
[csv ▾]   (csv / xlsx)
```

与现状字段一致，仅版式调整。

### 3.5 任务列表 / 进度条（底部折叠区）

折叠态（默认）：

```
▾ 6 任务待执行 · 12 输出
```

展开态（运行前）：

```
▾ 6 任务待执行 · 12 输出
┌─────────────────────────────────────────────────┐
│ ⏸ run_2024_03_a · vibration_x · fft             │
│ ⏸ run_2024_03_a · vibration_y · fft             │
│ ⏸ run_2024_03_b · vibration_x · fft             │
│ ⏸ run_2024_03_b · vibration_y · fft             │
│ ⏸ run_2024_03_c · vibration_x · fft             │
│ ⏸ run_2024_03_c · vibration_y · fft             │
└─────────────────────────────────────────────────┘
```

运行中：

```
进度 3 / 6  [████████░░░░░░░░] ~12s 剩余
┌─────────────────────────────────────────────────┐
│ ✓ run_2024_03_a · vibration_x · fft             │
│ ✓ run_2024_03_a · vibration_y · fft             │
│ ✓ run_2024_03_b · vibration_x · fft             │
│ ⟳ run_2024_03_b · vibration_y · fft             │  ← 黄色高亮
│ ⏸ run_2024_03_c · vibration_x · fft             │
│ ⏸ run_2024_03_c · vibration_y · fft             │
└─────────────────────────────────────────────────┘
```

状态：
- `⏸` 灰：待执行
- `⟳` 黄：进行中
- `✓` 绿：完成
- `✗` 红：失败 — 鼠标悬停显示错误信息

运行中：
- 三块详情区禁用（编辑控件 setEnabled(false)），保持视觉
- "Cancel/运行" 区切换为单按钮 "中断"
- 运行结束后状态保留，方便回看哪些成功 / 失败

## 4. 数据模型

### 4.1 AnalysisPreset 扩展（保持单一 dataclass + 序列化白名单 + 工厂校验）

新增字段：

```python
@dataclass
class AnalysisPreset:
    # ... 现有字段
    target_signals: tuple[str, ...] = ()       # 多选目标信号；free_config 用
    # 以下两个是"运行选择" — 仅 free_config 来源 + 仅运行时存在；
    # 不参与序列化（见 §4.2 白名单）
    file_ids: tuple[object, ...] = ()
    file_paths: tuple[str, ...] = ()
```

**字段所属 / 不变量**（防 footgun）：

| 字段 | 性质 | 适用 source | 是否序列化到 preset JSON |
|---|---|---|:-:|
| `name` / `method` / `params` / `outputs` | 配方 | both | ✓ |
| `target_signals` / `rpm_channel` | 配方 | `free_config` | ✓ |
| `signal_pattern` | 后端兜底（UI 不写入） | `free_config` | ✗ |
| `signal` / `rpm_signal` | 运行选择 | `current_single` | ✗ |
| `file_ids` / `file_paths` | 运行选择 | `free_config` | ✗ |

> `signal_pattern` 不写入 JSON：UI 已经没有入口，preset 文件保存的是"用户在 UI 里设定的配方"，pattern 只是后端兜底（来自老 API / 编程化构造）。新建 preset 不会有 pattern 值。

工厂方法增强：
- `AnalysisPreset.free_config(...)` **不接受** `file_ids` / `file_paths`（这两个是 UI 层运行时状态，由 `BatchSheet.get_preset()` 在返回前注入）
- 反之 `from_current_single(...)` 不接受 `target_signals` / `file_ids` / `file_paths`
- 工厂内部 assert 不变量；非法组合直接抛 `ValueError`

兼容性：
- 老的 `from_current_single` 路径不动
- `free_config` 路径下，`signal_pattern` 字段保留作后端兜底；运行时若 `target_signals` 非空则直接用、否则回落到 pattern。UI 不再有 pattern 入口。

> 设计权衡：codex spec review F-4 提议拆成 `AnalysisPreset` + `BatchRunRequest`，但侵入面太大（runner 签名 / current_single 路径都得动）。当前选"单 dataclass + 工厂校验 + 序列化白名单"，依赖工厂强制不变量来防 footgun。如果将来 file_ids/file_paths 出现更多变体，再切到 split。

### 4.2 PresetFile（新增 JSON 序列化模块）

文件：`mf4_analyzer/batch_preset_io.py`

```python
def save_preset_to_json(preset: AnalysisPreset, path: Path) -> None: ...
def load_preset_from_json(path: Path) -> AnalysisPreset: ...
```

JSON schema v1（**自起始就带 `schema_version`**）：

```json
{
  "schema_version": 1,
  "name": "vibration FFT",
  "method": "fft",
  "target_signals": ["vibration_x", "vibration_y"],
  "rpm_channel": "",
  "params": {
    "window": "hanning",
    "nfft": 1024
  },
  "outputs": {
    "export_data": true,
    "export_image": true,
    "data_format": "csv"
  }
}
```

**白名单序列化**（实现要点）：`save_preset_to_json` 不直接 `dataclasses.asdict(preset)`，而是显式抽取上表 §4.1 中"是否序列化"列为 ✓ 的字段。`file_ids` / `file_paths` / `signal` / `rpm_signal` 即使被错误注入也不会泄漏到磁盘。

**版本处理**：
- 写入：始终 `schema_version: 1`
- 读取：
  - 文件含 `schema_version: 1` → 正常解析
  - 文件**缺** `schema_version` → 视为 v1（兼容前期手写示例 / 测试 fixture）
  - 文件含未知版本（如 v2，将来出现破坏性变更时） → 抛 `UnsupportedPresetVersion`，UI 端 toast "preset 文件版本不支持（v2），请用更新版本的应用打开"

**不包含**：`file_ids`、`file_paths`、`outputs.directory` — preset 是"分析配方"，文件和输出目录每次手动选。

加载 preset 时：
- 若 `target_signals` 中**部分**信号在当前选中文件交集里不存在 → 这些信号在 chip 里红色显示 + warning 文字 "信号 X 在当前文件里不可用"，不强制阻止运行（缺的那部分按 §7 在任务展开时处理）
- 若 `target_signals` **全部**不可用（交集空 + 用户没换文件）→ INPUT 块标 ⚠，运行 disabled，提示 "导入的 preset 与当前文件无交集，请调整文件或信号"
- 若 `method` 是 order_*  但 RPM 通道未填 → 走自动识别（沿用 `_guess_rpm_channel`）

### 4.3 任务展开逻辑

`BatchRunner.__init__` 增加可选 `loader` 注入：

```python
class BatchRunner:
    def __init__(self, files: dict, loader: Callable[[str], FileData] | None = None):
        self.files = files
        # 默认走 mf4_analyzer.io.loader.load_file；测试可注入 mock
        self._loader = loader or _default_loader
        self._disk_cache: dict[str, FileData] = {}
```

`_expand_tasks` 改造（**两阶段：先全缺检测短路 → 再 yield 全部**）：

```python
def _expand_tasks(self, preset):
    if preset.method not in self.SUPPORTED_METHODS:
        return
    if preset.source == 'current_single':
        # ... 不变
        return
    files_iter = list(self._resolve_files(preset))
    if preset.target_signals:
        # —— 阶段 1：全缺检测。如果 target_signals 中所有信号在所有文件里
        # 都不存在 → 0 yield → run() 内 `if not tasks:` 走 blocked 分支。
        has_any_runnable = any(
            ch in fd.data.columns
            for fid, fd in files_iter
            for ch in preset.target_signals
        )
        if not has_any_runnable:
            return  # → BatchRunResult(status='blocked', blocked=['no matching batch tasks'])

        # —— 阶段 2：至少一个可执行 → yield 全部 (file × signal) 笛卡尔积。
        # 缺的 (file, signal) 对仍然 yield；_run_one 内 `ch not in fd.data.columns`
        # 时抛 "missing signal: X"，由 run() 转成 task_failed 事件 + ✗ 行。
        # 这样 UI 端能"预先看到 file_b 不会有 vibration_x"。
        for fid, fd in files_iter:
            for ch in preset.target_signals:
                yield fid, fd, ch
    else:
        # 兜底：维持老的 pattern 路径（同现状 _matches）
        ...
```

> **两层防护**：UI 端 §7 在导入 preset 后若 target_signals 全部不可用就禁用 Run（第一层）；若调用方绕过 UI 直接构造 preset（如测试），runner 端阶段 1 检测兜底（第二层），返回 blocked 而不是抛异常。这与 §6.2.1 描述的 blocked 路径、§8 测试用例 "target_signals 全部不在文件中 → status == 'blocked'" 完全一致。

`_resolve_files`：
- `preset.file_ids` 直接查 `self.files`
- `preset.file_paths` 走 `self._loader(path)` 懒加载，结果缓存在 `self._disk_cache`（key=path），同一 BatchRunner 实例多次展开复用；不污染 `self.files`（那是 main_window 的真相源）

`_default_loader`：
```python
def _default_loader(path: str):
    from mf4_analyzer.io.loader import load_file
    return load_file(path)
```

测试中可以 `BatchRunner(files={}, loader=lambda p: fake_fd)` 注入 fake，覆盖加载成功 / `loader` 抛异常两条路径。

### 4.4 进度事件接口 + 取消契约

```python
@dataclass
class BatchProgressEvent:
    kind: Literal[
        'task_started',
        'task_done',
        'task_failed',
        'task_cancelled',
        'run_finished',     # 终态事件
    ]
    # 以下 5 字段：task_* 事件必填；run_finished 时全部 None / 0
    task_index: int | None = None
    total: int | None = None
    file_name: str | None = None
    signal: str | None = None
    method: str | None = None
    # 仅 task_failed
    error: str | None = None
    # 仅 run_finished：'done' / 'partial' / 'cancelled' / 'blocked'
    final_status: str | None = None
```

**Payload 规则**：

| kind | task_index | total | file_name/signal/method | error | final_status |
|---|:-:|:-:|:-:|:-:|:-:|
| task_started | ✓ | ✓ | ✓ | — | — |
| task_done | ✓ | ✓ | ✓ | — | — |
| task_failed | ✓ | ✓ | ✓ | ✓ | — |
| task_cancelled | ✓ | ✓ | ✓ | — | — |
| run_finished | — | — | — | — | ✓ |

`run_finished` 是语义事件，提示监听者"runner 已结束、final_status 是这个"。**它不替代 `BatchRunResult`**（仍然是 `run()` 的返回值）；UI 端实际编辑解锁仍由 `BatchRunnerThread.finished` 信号触发（QThread 内置），见 §6.2。

**`BatchRunResult.status` 取值扩展**：现有 `'done' / 'partial' / 'blocked'` + 新增 `'cancelled'`（用户中断；可能已完成 0~N-1 个 task，剩余标 cancelled）。

**规范签名**（保持向后兼容 + 取消支持）：

```python
def run(
    self,
    preset: AnalysisPreset,
    output_dir: str | Path,
    progress_callback: Callable[[int, int], None] | None = None,
    *,
    on_event: Callable[[BatchProgressEvent], None] | None = None,
    cancel_token: threading.Event | None = None,
) -> BatchRunResult:
    ...
```

- **位置参数 `progress_callback`** 保留位置 3，与现有签名一致（现有 caller `main_window.open_batch` 和 `tests/test_batch_runner.py` 全都不传 callback，所以新增 `*,` keyword-only 不破坏）
- **`on_event`** keyword-only，传入即接收上面所有 kind 的事件
- **`cancel_token`** keyword-only：runner 在每个 task 边界 `if cancel_token and cancel_token.is_set(): break`；break 后剩余 task 各发一次 `task_cancelled` 事件；最终 `BatchRunResult.status = 'cancelled'`
- **同时传两个 callback**：每个 `task_done` 事件触发后**先**调 `on_event(event)`、**再**调 `progress_callback(index, total)`（保持 progress_callback 语义不变）

**线程模型**：UI 端用 `BatchRunnerThread(QThread)` 包装 `BatchRunner.run`，`on_event` 通过 `pyqtSignal(object)` 跨线程转发。当前 `main_window.open_batch` 用 `QApplication.processEvents()` 顶着的方式废弃。

### 4.5 取消路径（端到端）

```
[用户点 "中断" 按钮 或 关闭对话框时弹确认]
        ↓
BatchSheet.request_cancel():
  - cancel_token.set()
  - "中断" 按钮 disabled，显示 "正在停止…"
        ↓
BatchRunner 当前正在跑的 task 不打断（保证文件写入完整，避免半截 csv），完成后检查 token
        ↓
runner 跳出循环 → 给剩余每个未启动 task 发 task_cancelled 事件
        ↓
runner 发 run_finished(final_status='cancelled')
        ↓
BatchRunnerThread.finished signal → BatchSheet.unlock_editing():
  - 三块详情区 setEnabled(True)
  - 按钮恢复 [Cancel] [运行]
  - 任务列表保留 ✓/✗/⏸（cancelled 显示为 "—" 灰色 + tooltip "已取消"）
```

**说明**：取消"在 task 边界"而不"在 task 内部"。理由：(1) 阶次/FFT 计算用 numpy/scipy，没现成 cancel hook；(2) 写文件中途中断会留半截文件比让 task 完成更糟。代价是单 task 可能要等 1-3 秒才停下，spec 接受。

## 5. UI 组件分解

新增 / 改造（实现期由 squad 分工）：

```
mf4_analyzer/ui/drawers/batch/
├── __init__.py               # 导出 BatchSheet
├── sheet.py                  # BatchSheet 主容器（替换 batch_sheet.py）
├── pipeline_strip.py         # 顶部三块摘要链路 widget
├── input_panel.py            # INPUT 详情列：文件列表 + 信号 chips + RPM + 时间范围
├── analysis_panel.py         # ANALYSIS 详情列：方法按钮组 + 动态参数表
├── output_panel.py           # OUTPUT 详情列
├── signal_picker.py          # 自定义 SignalPickerPopup 组件
├── method_buttons.py         # 4 按钮 method selector + dynamic param form
├── task_list.py              # 底部折叠任务列表 + 进度条
└── runner_thread.py          # QThread 包装 BatchRunner，发 BatchProgressEvent
```

把 `batch_sheet.py` 改成上面的 package（`drawers/batch/`），单文件已经撑不下。

非 UI：

```
mf4_analyzer/
├── batch.py                  # 改：AnalysisPreset 扩展 + BatchProgressEvent + run() 新签名
└── batch_preset_io.py        # 新：JSON 序列化
```

## 6. 数据流

### 6.1 运行前（用户配置）

```
[文件列表/信号/方法/参数/输出 任一变化]
        ↓
PipelineStrip 重算每块 ✓/⚠ 状态
        ↓
TaskList 重算 dry-run 任务清单
        ↓
底部摘要更新 "N 任务 · M 输出"，运行按钮启用条件刷新
```

### 6.2 运行中

```
[运行] 点击
    ↓
BatchSheet.lock_editing()  → 三块详情禁用；按钮区切到 [中断]
    ↓
BatchRunnerThread.start()  → BatchRunner.run(on_event=signal.emit, cancel_token=token)
    ↓ (per task, runner 线程内)
event task_started   → TaskList 行图标 ⏸ → ⟳
event task_done      → TaskList 行图标 ⟳ → ✓
event task_failed    → TaskList 行图标 ⟳ → ✗ (悬浮 tooltip = error)
event task_cancelled → TaskList 行图标 ⏸ → "—" 灰色 (tooltip "已取消")
    ↓ (终态)
event run_finished(final_status='done'|'partial'|'cancelled'|'blocked')
   - 仅作语义信号；UI 可据此选择不同 toast 文案
    ↓ (BatchRunnerThread 退出 run loop → QThread.finished 信号)
BatchSheet._on_thread_finished(result: BatchRunResult):
   - unlock_editing()：三块详情 setEnabled(True)
   - 按钮区切回 [Cancel] [运行]
   - TaskList 保留所有图标状态供回看
   - 根据 result.status 决定 toast：done / partial(N 失败) / cancelled / blocked(原因)
```

**unlock 触发器**：始终为 `QThread.finished` 信号，**不**依赖 `run_finished` 事件（事件可能因 runner 内异常未送达；QThread.finished 由 Qt 自身保证）。`run_finished` 仅作"runner 自报终态"，提供给观察者。

### 6.2.1 blocked 路径（无任务可跑）

```
runner.run() 内 _expand_tasks 产生 0 个 task
    ↓
return BatchRunResult(status='blocked', blocked=['no matching batch tasks'])
    ↓
UI 端 _on_thread_finished 看到 status='blocked' → toast "无可执行任务"
```

> 走到这一步通常意味着 UI 端检查漏了（§7 规则应已经禁用运行按钮）；但若发生，runner 端 fail-soft，不抛异常。

### 6.3 Preset 导入 / 导出

```
[导出 preset…]
  → QFileDialog.getSaveFileName(filter='*.json')
  → batch_preset_io.save_preset_to_json(self.current_preset(), path)

[导入 preset…]
  → QFileDialog.getOpenFileName(filter='*.json')
  → batch_preset_io.load_preset_from_json(path)
  → BatchSheet.apply_preset(preset)  (填表单；文件列表保持当前；目标信号若不可用 → 红 chip + 警告)
```

### 6.4 从当前单次填入

```
[从当前单次填入]
  → main_window._build_current_batch_preset() (复用现有逻辑)
  → BatchSheet.apply_preset(preset)
     - 文件列表填入 [当前单次的 fid]
     - 目标信号填入 [当前单次的 channel]
     - 方法 / 参数 / RPM 通道 / 时间范围按 preset 填
```

## 7. 错误 / 边界

| 场景 | 行为 |
|---|---|
| 三块未全部 ✓ 就点运行 | 运行按钮 disabled |
| 选了 0 个文件 | INPUT 块标 ⚠，运行 disabled |
| 选了 0 个目标信号 | INPUT 块标 ⚠，运行 disabled |
| 信号交集为空 | 信号 popup 列表全灰，提示 "所选文件无共同信号" |
| 有 `path_pending` / `probing` 状态文件 | 底部任务列表显示 "正在解析 N 个文件…"；运行 disabled 直至探针完成 |
| 磁盘文件 metadata 探针失败（坏 mf4） | 列表项标 `probe_failed` + 红 ⚠ + tooltip 错误；不参与信号交集和任务展开 |
| 导入 preset 后**部分** target_signals 在交集中缺失 | 缺的信号 chip 红色显示；可运行；运行时这些信号在任务列表里预先显示 ✗ + "missing in this file" |
| 导入 preset 后**全部** target_signals 不可用 | INPUT 标 ⚠，运行 disabled，提示 "preset 与当前文件无交集" |
| 运行时全量加载磁盘文件失败 | 该文件**全部** task 标 ✗（task_failed，error="cannot load mf4: ..."）；其他文件继续；不 fast-fail |
| 运行中点 "中断" 按钮 | 见 §4.5 取消路径 |
| 运行中关闭对话框 | 弹确认 "中断当前运行？"；确认 → 走 §4.5 取消路径；取消按钮区间禁用 X 角，避免重复点击 |
| preset JSON 损坏 / 未知 schema_version | toast "preset 文件格式不支持（v2）" + 不修改当前表单 |
| 输出目录创建失败（权限/磁盘满） | 在第一个 task 启动前 raise → `BatchRunResult(status='blocked', blocked=['cannot create output dir: ...'])`；运行结束事件 final_status='blocked'；UI 显示错误 toast |
| 输出目录可创建但运行中某 task 写文件失败 | 该 task 标 task_failed；其他 task 继续 |

## 8. 测试策略

**单元测试**（`tests/`）：

`test_batch_preset_io.py`：
- 写入 + 读回往返：所有 portable 字段一致
- 写入文件**不含** `file_ids` / `file_paths` / `signal` / `rpm_signal` / `signal_pattern` / `outputs.directory`（即使 dataclass 上被注入）— 白名单序列化验证
- `schema_version: 1` 写入正确
- 读取缺 `schema_version` 字段 → 视为 v1 解析成功
- 读取 `schema_version: 2` → 抛 `UnsupportedPresetVersion`
- 读取损坏 JSON → 抛 `ValueError`，错误消息明确

`test_batch_runner.py` 扩展：
- `target_signals` 多信号正常展开
- `target_signals` 全部不在文件中 → `BatchRunResult.status == 'blocked'`，blocked 信息明确
- `target_signals` 部分缺：缺的那部分 task_failed（"missing signal: X"），其余正常
- `file_paths` 懒加载成功路径
- `file_paths` 加载失败 → 该文件全部 task 标 task_failed，其他文件继续，不 fast-fail
- 输出目录创建失败 → 第一个 task 启动前 blocked
- `BatchProgressEvent` 全部 5 种 kind 都能触发（task_started / done / failed / cancelled / run_finished）
- `cancel_token` 在两个 task 间被 set → 后续 task_cancelled，最终 status='cancelled'，部分文件可能已生成（验证写入完整，不留半截）
- 老 `progress_callback`（位置参数 3）兼容路径：调用次数 = 完成 task 数
- `progress_callback` + `on_event` 同时传：每个 task_done 事件后**先** on_event **后** progress_callback

**UI 测试**（`tests/ui/`）：

`test_batch_drawers.py` 重写：
- PipelineStrip ✓/⚠ 状态切换：每块的 0/1 输入对状态的影响
- SignalPickerPopup：搜索框过滤、多选、交集过滤（仅显示 N/N 文件含的信号）、点击外部收起
- 文件状态机：
  - "+ 磁盘…" 加入 → `path_pending` → 探针完成 → `loaded`
  - 坏 mf4 → `probe_failed`，红 ⚠ + tooltip
  - 仍有 `probing` 状态时运行按钮 disabled
- MethodButtons 切换时参数表重渲：fft 切到 order_time → 出现"目标阶次/时间分辨率/RPM 系数" + 共享字段（窗函数/NFFT）保留
- TaskList 折叠展开、状态图标随 BatchProgressEvent 更新（mock event 流）
- 取消路径 UI：点 "中断" → cancel_token.set；finished 信号到达后编辑解锁、按钮回到 [Cancel][运行]、任务行 cancelled 显示
- apply_preset 后表单字段一致；apply 部分缺信号的 preset → 缺信号 chip 红色

**手动测试**（squad 实施时）：
- 导出 preset → 关闭重开 → 导入 preset → 任务清单一致
- 跨机器：把 preset 文件拷到另一台机器，加载后能正常运行（验证不含 output_dir / 文件路径的设计）
- 加一个 5GB 的 mf4 文件作为 disk file，验证对话框响应正常（probe < 2s）

## 9. 范围 / 切片建议

squad 实施期建议切片（每片可独立 PR）：

1. **后端基础**：`AnalysisPreset` 字段扩展 + 工厂校验 + 序列化白名单 contract（不含 IO 实现）。tests 覆盖工厂不变量和字段所属。
2. **后端 runner 扩展**：`_expand_tasks` 走 `target_signals` + `_resolve_files` 懒加载磁盘文件（含 `loader` 注入）+ `BatchProgressEvent`（5 种 kind）+ `cancel_token` + 新签名 `run(preset, output_dir, progress_callback=None, *, on_event=None, cancel_token=None)`。tests 覆盖 §8 中所有 runner 用例。
3. **Preset JSON IO**：`batch_preset_io.py` + schema_version 处理 + 错误类。tests 覆盖往返 + 白名单 + 版本处理。
4. **UI 骨架**：`drawers/batch/` package 创建 + 顶部摘要链路 + 三列详情壳（先内嵌静态 widget，逻辑空）。
5. **UI 详情填充**：`SignalPickerPopup`、`MethodButtons` + 动态参数表、文件列表管理（含状态机 + metadata probe worker）。
6. **任务列表 + 进度 + 取消**：`TaskList` widget + `BatchRunnerThread` + 事件 → UI 接线 + 中断按钮 + 关闭对话框确认。
7. **Preset 导入导出 + 从当前单次填入**：toolbar 三个按钮接线。
8. **回归 + 删除 `signal_pattern` UI 入口**：保留后端兜底，删除 UI（YAGNI）。

> 切片调整说明（vs codex F-2 / F-3 反馈）：原 PR 1 把数据模型 / 任务展开 / 事件 API / JSON IO 全揉一起风险高；现在拆成 1+2+3 三个独立 PR，IO 与 runner 解耦；PR 6 显式包含取消路径（不再隐藏在"任务列表 + 进度"里）。

每片 squad 走一次 plan → execute → review，依次合入。

## 10. 迁移影响

- `mf4_analyzer/ui/drawers/batch_sheet.py` 删除 → 由 `drawers/batch/` 包替代；`main_window.open_batch` 引用同名类，导入路径改成 `from .drawers.batch import BatchSheet`。
- `BatchRunner.run` 签名扩展（保留 `progress_callback` 兼容） — 调用方 `main_window.open_batch` 改用 `on_event` 路径同时启用 worker 线程。
- 现有 `signal_pattern` 字段保留在 `AnalysisPreset` 中作为兜底，UI 端入口移除；测试里直接构造 preset 仍可走 pattern 路径。
