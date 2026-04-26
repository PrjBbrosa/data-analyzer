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
- 不做 preset 的版本演化 / 迁移机制（v1 schema 直接 break 即可，将来需要时再上 schema_version）。
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
- "+ 磁盘…"：`QFileDialog.getOpenFileNames` 选 `.mf4`，但只走"路径加入候选"，**不**真去加载（懒加载到运行时）— 否则大文件加进来 batch 对话框就卡顿
- 列表里 `×` 按钮移除单条
- 文件列表变化 → 重算"信号交集" → 信号 popup 列表刷新

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

### 4.1 AnalysisPreset 扩展

新增字段（`free_config` 来源时使用）：

```python
@dataclass
class AnalysisPreset:
    # ... 现有字段
    file_ids: tuple[object, ...] = ()         # 主窗口已加载的文件 id 集合
    file_paths: tuple[str, ...] = ()          # 通过"+ 磁盘…"加进来的绝对路径
    target_signals: tuple[str, ...] = ()      # 多选目标信号；空 → 走 signal_pattern 兜底
```

兼容性：
- 老的 `from_current_single` 路径不动（仍通过 `signal=(fid, channel)` 单点传入）
- `free_config` 路径下，`signal_pattern` 字段保留但不再由 UI 写入；运行时若 `target_signals` 非空则直接用、否则回落到 pattern（保持后端稳定，但 UI 删除入口）

### 4.2 PresetFile（新增 JSON 序列化模块）

文件：`mf4_analyzer/batch_preset_io.py`

```python
def save_preset_to_json(preset: AnalysisPreset, path: Path) -> None: ...
def load_preset_from_json(path: Path) -> AnalysisPreset: ...
```

JSON schema（v1，无 schema_version 字段；将来需要时再加）：

```json
{
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

**不包含**：`file_ids`、`file_paths`、`outputs.directory` — preset 是"分析配方"，文件和输出目录每次手动选。

加载 preset 时：
- 若 `target_signals` 中某些信号在当前选中文件里不存在 → 这些信号在 chip 里红色显示 + warning 文字 "信号 X 在当前文件里不可用"，不强制阻止运行（运行时按 Q9 跳过）
- 若 `method` 是 order_*  但 RPM 通道未填 → 走自动识别（沿用 `_guess_rpm_channel`）

### 4.3 任务展开逻辑

`BatchRunner._expand_tasks` 改造：

```python
def _expand_tasks(self, preset):
    if preset.method not in self.SUPPORTED_METHODS:
        return
    if preset.source == 'current_single':
        # ... 不变
        return
    # free_config: 优先 target_signals
    files_iter = self._resolve_files(preset)  # file_ids + file_paths 合并
    if preset.target_signals:
        for fid, fd in files_iter:
            for ch in preset.target_signals:
                if ch in fd.data.columns:
                    yield fid, fd, ch
                else:
                    # 缺信号：仍 yield，但带 missing 标记
                    yield fid, fd, ch  # 走 _run_one 时会抛 missing
    else:
        # 兜底：维持老的 pattern 路径
        ...
```

`_resolve_files`：
- `preset.file_ids` 直接查 `self.files`
- `preset.file_paths` 走 `loader.load(path)` 懒加载（缓存到 `self.files` 不变；只是 batch 临时持有）

### 4.4 进度事件接口

替换 `progress_callback(index, total)` 为更细粒度的回调：

```python
@dataclass
class BatchProgressEvent:
    kind: Literal['task_started', 'task_done', 'task_failed']
    task_index: int
    total: int
    file_name: str
    signal: str
    method: str
    error: str | None = None

def run(self, preset, output_dir, on_event: Callable[[BatchProgressEvent], None] | None = None):
    ...
```

UI 层接 `on_event`，以此驱动任务列表的图标更新。**保持向后兼容**：`run(preset, output_dir, progress_callback=None, on_event=None)` 两个 kwarg 都接受；当只传老 `progress_callback(index, total)` 时，runner 内部在每个 `task_done` 事件触发后回调一次它，等价于老 API。两者可同时传，互不影响。

UI 端建议：`BatchRunner.run` 在 worker 线程跑（`QThread` 或 `QtConcurrent`），`on_event` 通过 `pyqtSignal` 跨线程发送，避免阻塞 UI（当前 `open_batch` 用 `QApplication.processEvents()` 顶着，不正经）。

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
BatchSheet.lock_editing()  → 三块详情禁用
    ↓
RunnerThread.start()  → BatchRunner.run(on_event=signal.emit)
    ↓ (per task)
event task_started → TaskList 行图标 ⏸ → ⟳
event task_done    → TaskList 行图标 ⟳ → ✓
event task_failed  → TaskList 行图标 ⟳ → ✗ (悬浮 tooltip = error)
    ↓ (all done)
BatchSheet.unlock_editing(); 按钮恢复 Cancel/运行；保留状态
```

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
| 三块未全部 ✓ 就点运行 | 运行按钮 disabled，无需处理 |
| 选了 0 个文件 | INPUT 块标 ⚠，运行 disabled |
| 选了 0 个目标信号 | INPUT 块标 ⚠，运行 disabled |
| 信号交集为空 | 信号 popup 列表全灰，提示 "所选文件无共同信号" |
| 加载磁盘文件失败（坏 mf4） | 文件列表里红色显示 + tooltip 错误，不参与任务展开 |
| 缺信号文件（导入 preset 后） | 任务展开时该任务直接标 ✗ + "missing signal: X" |
| 运行中关闭对话框 | 弹确认 "中断当前运行？"；用户确认后取消 worker thread |
| preset JSON 损坏 / schema 不符 | toast "preset 文件格式不支持" + 不修改当前表单 |
| 输出目录写入失败 | 第一个 task_failed 事件传出 + 后续 task 全部失败（fast-fail） |

## 8. 测试策略

**单元测试**（`tests/`）：
- `test_batch_preset_io.py`：preset 序列化/反序列化往返、缺字段降级、坏 JSON 处理
- `test_batch_runner.py` 扩展：
  - `target_signals` 路径展开正确
  - `file_paths` 懒加载路径
  - `BatchProgressEvent` 全部三种 kind 触发
  - 缺信号文件行为：task_failed + 错误消息
  - 老 `progress_callback` 兼容路径

**UI 测试**（`tests/ui/`）：
- `test_batch_drawers.py` 重写：
  - PipelineStrip ✓/⚠ 状态切换
  - SignalPickerPopup 搜索 + 多选 + 交集过滤
  - MethodButtons 切换时参数表重渲（field 集合按 method 表）
  - TaskList 折叠展开、状态图标随事件更新
  - apply_preset 后表单字段一致

**手动测试**（squad 实施时）：
- 导出 preset → 关闭重开 → 导入 preset → 任务清单一致
- 跨机器：把 preset 文件拷到同代码的另一台机器，加载后能跑（验证不含 output_dir / 文件路径的设计）

## 9. 范围 / 切片建议

squad 实施期建议切片（每片可独立 PR）：

1. **后端先行**：`AnalysisPreset` 字段扩展 + `_expand_tasks` 走 `target_signals` + `BatchProgressEvent` + tests。`batch_preset_io` 同步落地。
2. **UI 骨架**：`drawers/batch/` package 创建 + 顶部摘要链路 + 三列详情壳（先内嵌静态 widget，逻辑空）。
3. **UI 详情填充**：`SignalPickerPopup`、`MethodButtons` + 动态参数表、文件列表管理。
4. **任务列表 + 进度**：`TaskList` widget + `RunnerThread` + 事件接线。
5. **Preset 导入导出 + 从当前单次填入**：toolbar 三个按钮接线。
6. **回归 + 删除 `signal_pattern` UI 入口**：保留后端兜底，删除 UI（YAGNI）。

每片 squad 走一次 plan → execute → review，依次合入。

## 10. 迁移影响

- `mf4_analyzer/ui/drawers/batch_sheet.py` 删除 → 由 `drawers/batch/` 包替代；`main_window.open_batch` 引用同名类，导入路径改成 `from .drawers.batch import BatchSheet`。
- `BatchRunner.run` 签名扩展（保留 `progress_callback` 兼容） — 调用方 `main_window.open_batch` 改用 `on_event` 路径同时启用 worker 线程。
- 现有 `signal_pattern` 字段保留在 `AnalysisPreset` 中作为兜底，UI 端入口移除；测试里直接构造 preset 仍可走 pattern 路径。
