# 批处理配置记忆（QSettings 持久化）执行计划

- **状态**：待执行
- **日期**：2026-08-02
- **问题**：批处理面板的选项每次打开都回到硬编码默认值，刻度密度、字号、图片格式/尺寸/DPI、输出目录等需要反复重设。
- **主改文件**：`mf4_analyzer/ui/drawers/batch/sheet.py` + 新增 `mf4_analyzer/ui/batch_settings.py`

> 与 `2026-08-02-batch-signal-picker-option-a-plan.md` 无文件冲突
> （那份只碰 `signal_picker.py` / `icons.py`），两者可并行，但**建议先合入
> 选择器改造**再做本项，避免同一目录下的测试基线互相干扰。

---

## 1. 现状

`BatchSheet` 是 `QDialog`，每次 `_open_batch` 都新建 → `exec_()` → 关闭即销毁
（`ui/main_window/window.py:3269`）。面板状态没有任何跨会话持久化：

- `ui/drawers/batch/output_panel.py:456` 直接 `self._render_style = RenderStyle()`，
  即硬编码默认值（刻度 X=14 / Y=10、字号 100%）。
- `BatchOutput` 的 13 个字段全部走 dataclass 默认值（`batch.py:87-102`）。
- 传入的 `current_preset` **不是**「上次批处理配置」，而是主窗口**当前单次分析**
  的状态快照（`window.py:_build_current_batch_preset`），且仅在非 `None` 时 apply
  （`sheet.py:985-987`）。

唯一的持久化是**手动**的 preset JSON 存/读（`sheet.py:990` / `:1017`，
`QFileDialog`）。刻度密度与字号确实能随 preset 往返（`batch_render_style.py`
模块文档明载，`batch_recipe.py:62-63` 白名单里也有），但要手动点存、下次手动点读。

### 已有的有利条件

1. **读写接口已完全对称**，持久化层可以做得很薄，几乎不用碰 `output_panel` 内部：

   | 读 | 写 |
   | --- | --- |
   | `get_outputs() -> BatchOutput` | `apply_outputs(out)` |
   | `directory() -> str` | `apply_directory(path)` |
   | `render_style_params() -> dict` | `apply_render_style_params(params)` |

2. **序列化形状已存在**：`sheet.py:737 _output_controls_snapshot()` 已经把
   `axes` / `reference` / `render_style` / `outputs` 打包成 dict。本计划直接复用它的
   子集，不另造形状。

3. **QSettings store 范式已成熟**：`ui/db_reference_settings.py` 是一份带 schema
   版本、validate-before-write、可注入测试 settings 的实现，照抄其结构即可。

---

## 2. 设计决定

### 2.1 分两层：只记「展示偏好」，不记「数据绑定项」

这是本计划的核心约束。

| 记忆 | 项目 | 理由 |
| --- | --- | --- |
| ✅ 记 | `render_style`：刻度密度 X/Y、字号缩放 | 纯展示偏好，与数据无关，正是反复调整的痛点 |
| ✅ 记 | `outputs`：导出数据/图片开关、数据格式、图片格式/尺寸/宽高/DPI/背景/线宽、冲突策略、写入清单 | 同上 |
| ✅ 记 | `directory`：输出目录 | 大多数导出工具的通行行为 |
| ❌ 不记 | 文件列表、目标信号、RPM 通道及系数 | **与具体数据集绑定**。带着上次的信号名打开新来源，只会制造「目标信号在所选来源中不可用」（`sheet.py:1114`） |
| ❌ 不记 | `axes`（含 `x_min`/`x_max`、时间区间） | 同上，轴范围是数据尺度的函数 |
| ❌ 不记 | 分析方法与其参数 | 属于「这次要做什么」，不是「我习惯怎么看」 |
| ❌ 不记 | `reference`（dB 参考） | **已有独立真相源** `ui/db_reference_settings.py`；再存一份会造成两个来源打架 |

`BatchOutput` 中的 `requested_image_format` 与 `migration_warnings` 是运行时诊断
字段，**不序列化**。`resume_policy` 属于单次运行意图，也不记。

### 2.2 优先级

打开面板时按此顺序应用，后者覆盖前者：

```
硬编码默认值  →  QSettings 记住的偏好  →  current_preset（若非 None）
```

`current_preset` 是用户主动带进来的「从当前单次填入」，必须赢过记忆值。
实现上即：在现有 `apply_preset(self._current_preset)`（`sheet.py:987`）**之前**
应用记忆值。

### 2.3 写入时机

- `closeEvent` 的**正常关闭分支**（`sheet.py:1470` 中 `super().closeEvent(event)` 那条路径）写一次。
- `_on_run_clicked`（`sheet.py:1236`）成功启动后再写一次，避免长时间运行中崩溃丢失偏好。

**不要**挂在 `_on_output_controls_changed` 上逐次写——那是每个控件变更都触发的高频信号。

### 2.4 容错

照抄 `db_reference_settings.py` 的口径：schema 版本不识别、JSON 解析失败、
字段类型不对 → **静默回落到默认值**，不弹错、不阻塞打开面板。
`RenderStyle` 自身已有 clamp 逻辑（`batch_render_style.py` 的 `_clamp_int` /
`_clamp_float`），越界值会被夹到合法区间，这条防线免费继承。

输出目录若已不存在：保留字符串填入输入框但**不**自动创建目录，让既有的
`validate_outputs`（`sheet.py:1151`）照常报错——不要在恢复阶段做静默的文件系统操作。

---

## 3. 执行步骤

### 第 0 步 · 取基线

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_batch_smoke.py tests/ui/test_batch_input_panel.py tests/ui/test_batch_output_panel.py -q
```

记下失败用例；`main` 上 `tests/ui/test_split_*` 已知红，与本项无关。

### 第 1 步 · 新增持久化 store

**新文件**：`mf4_analyzer/ui/batch_settings.py`

照 `ui/db_reference_settings.py` 的结构写：

```python
SETTINGS_ORG = "MF4Analyzer"
SETTINGS_APP = "DataAnalyzer"
KEY_PANEL_PREFS_V1 = "batch/panel_prefs_v1"
PREFS_SCHEMA_VERSION = 1

@dataclass(frozen=True)
class BatchPanelPrefs:
    directory: str = ""
    render_style: dict = ...      # tick_density_x/y, font_scale
    outputs: dict = ...           # BatchOutput 的可序列化子集

class BatchPanelPrefsStore:
    def __init__(self, settings=None): ...   # None → QSettings(ORG, APP)
    def load(self) -> BatchPanelPrefs: ...   # 任何异常 → 默认值
    def save(self, prefs: BatchPanelPrefs) -> None: ...  # validate before write
```

硬性要求（项目铁律，`db_reference_settings.py` 模块文档明载）：
**store 绝不在测试中隐式构造 `QSettings("MF4Analyzer", "DataAnalyzer")`**；
生产代码可省略 `settings` 参数拿默认值，但每条测试必须注入
`QSettings(tmp_path/..., QSettings.IniFormat)`。

字段白名单在本模块内显式列出，**不要** `dataclasses.asdict(BatchOutput)` 全量落盘
——那会把 `migration_warnings` 等运行时字段一起写进用户配置。

### 第 2 步 · 面板打开时恢复

**文件**：`sheet.py`

在 `__init__` 中、现有 `apply_preset(self._current_preset)` 之前插入恢复逻辑：

```
prefs = BatchPanelPrefsStore().load()
self._output_panel.apply_directory(prefs.directory)          # 空串则跳过
self._output_panel.apply_render_style_params(prefs.render_style)
self._output_panel.apply_outputs(BatchOutput(**prefs.outputs))
```

注意 `apply_outputs` 会触发 `_on_output_controls_changed`（进而可能清掉
`_analysis_preset_output_snapshot`）。恢复期间需要用现成的
`self._applying_analysis_preset` 抑制标志把这段包起来——`sheet.py:730-733`
已有同样的用法可循。

### 第 3 步 · 关闭/运行时写入

**文件**：`sheet.py`

新增 `_persist_panel_prefs()`，从 `_output_controls_snapshot()` 取
`render_style` / `outputs` 两个键 + `self._output_panel.directory()`，交给 store。

挂到两处（见 2.3）：`closeEvent` 正常分支、`_on_run_clicked` 启动成功后。

### 第 4 步 · 「恢复默认」出口

在渲染样式弹层（`render_style_popover.py`）或输出设置区加一个「恢复默认」
按钮：清掉 QSettings 键并把面板重置为硬编码默认值。

理由：一旦引入记忆，用户就需要一个逃生口——尤其当记住的是一个他自己都忘了
为什么设成那样的图片尺寸时。**这一步不可省略**。

### 第 5 步 · 测试

**新文件**：`tests/ui/test_batch_settings.py`

| 测试 | 断言 |
| --- | --- |
| `test_prefs_round_trip` | save → load 后 render_style / outputs / directory 一致 |
| `test_load_returns_defaults_when_key_absent` | 空 QSettings → 全默认值 |
| `test_load_survives_unknown_schema_version` | 写入 `schema_version: 999` → 回落默认，不抛异常 |
| `test_load_survives_corrupt_json` | 写入非法 JSON → 回落默认 |
| `test_save_omits_runtime_fields` | 落盘 JSON 中不含 `migration_warnings` / `requested_image_format` |
| `test_out_of_range_values_are_clamped` | `tick_density_x=999` → 载入后夹到 `MAX_TICK_DENSITY_X` |

**新增到** `tests/ui/test_batch_smoke.py`（或 `test_batch_output_panel.py`）：

| 测试 | 断言 |
| --- | --- |
| `test_sheet_restores_remembered_render_style` | 注入含非默认刻度密度的 QSettings，新建 BatchSheet → 面板显示该值 |
| `test_current_preset_wins_over_remembered_prefs` | 记忆值与 `current_preset` 冲突时，preset 赢（2.2） |
| `test_sheet_does_not_restore_signals_or_files` | 记忆里即便混入信号名，也不得出现在目标信号选择中（2.1 的负向守卫） |

每条测试都要注入隔离的 `QSettings(IniFormat)`，**不得触碰用户真实配置**。

### 第 6 步 · 收尾

1. 全量套件与基线比对，失败集合 ⊆ 基线。
2. 真机跑一次：改刻度密度与图片 DPI → 关闭 → 重开，确认带回来了；再确认
   目标信号与文件列表**是空的**（2.1 的行为验收）。
3. 交互有增改（新增「恢复默认」入口、面板打开行为变化）→ 按 CLAUDE.md 跑
   `/update-hints` 同步 `ui/hints.py` 与 `ui/quickref.py`。

---

## 4. 风险

| 风险 | 应对 |
| --- | --- |
| 恢复时触发 `_on_output_controls_changed`，误清 `_analysis_preset_output_snapshot` | 用现成的 `_applying_analysis_preset` 抑制标志包住恢复段（第 2 步） |
| 记住的图片尺寸/DPI 组合在新场景下产生超大导出 | 尺寸字段本就有 `validate_outputs` 把关；「恢复默认」出口（第 4 步）是兜底 |
| 测试污染用户真实 QSettings | store 强制可注入；测试一律用 `IniFormat` + `tmp_path` |
| 用户期望「连信号一起记住」 | 2.1 已明确划界。若后续确实需要，正确做法是做**具名预设**（复用现有 preset JSON），而不是把数据绑定项塞进隐式记忆 |

**回滚**：新增文件 + `sheet.py` 三处小改（恢复、两个写入点），`git revert`
单个提交即可；删除 QSettings 键后行为完全回到现状。

---

## 5. 不做的事

- 不改 preset JSON 的格式与版本（那是可移植的显式存档，与隐式记忆是两回事）。
- 不记忆窗口几何/分栏位置（另一类问题，不在本次范围）。
- 不做多套具名「批处理配置档」——若将来需要，应扩展现有 preset 机制。

## 基线记录（第 0 步产出，执行时填写）

```
日期：
失败用例：
```

## 验收记录（第 6 步产出，执行时填写）

```
真机往返验证：
信号/文件未被恢复：
```
