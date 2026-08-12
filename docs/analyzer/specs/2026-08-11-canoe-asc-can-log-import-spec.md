# CANoe ASC（CAN 总线文本日志）按 BLF 链路导入 · 设计规格

- **状态**：已实现（2026-08-11，review 通过：局部门禁 192 绿 + 真机样本全链路冒烟）
- **日期**：2026-08-11
- **组件**：`io/`（新 CANoe 识别 + ASC 读帧）· `DataLoader` 门面 · `ProjectIOMixin` 打开链路 ·
  `io/source_adapters.py`（批处理分发）· `ui/drawers/batch/sheet.py`（批处理 DBC 上下文门控）
- **执行计划**：`docs/analyzer/plans/2026-08-11-canoe-asc-can-log-import-implementation.md`
- **实测样本**：`testdoc/ASC/datalog485.asc`（442 MB，本机存在、未入库）

---

## 1. 背景

`.asc` 在本项目当前语义 = **通用表格 ASCII**（`ascii_format.sniff_fixed_width_ascii`
→ CSV 回退，必须有时间列）。而 CANoe 导出的 `.asc` 是 **Vector CAN 总线文本日志**：
同一扩展名、完全不同的格式。样本头部：

```
date Mon Jul 27 17:32:25 PM 2026
base hex timestamps absolute
no internal events logged
// version 10.0.0
Begin Triggerblock Mon Jul 27 17:32:25 PM 2026
    0.100000 19   0339   Rx   d 8   28 32 3c 46 0a 00 00 00
    ...
    0.711200    SV: 99 0 1 ::SOA::LIghtsSt_Event_Tx = [20 02 ...]
```

主体一行一条 CAN 帧，中间夹杂 `SV:` 系统变量（SOA 服务）行。实测样本共
2,794,781 行 = **2,576,029 条 CAN 帧** + 218,746 条 SV 行 + 7 行头部；前 2000 帧内
57 个 CAN ID，无错误帧/远程帧。当前 `load_ascii` 对它必然失败
（"Cannot detect a supported ASCII table layout"），产品层面表现为「打不开、不识别」。

BLF 链路已把「帧序列 → DBC 探测/确认/解码」做成**与容器无关**：一旦读成
`(timestamp, arbitration_id, data)` 元组，后续的 probe（`_probe_blf_dbc_frames`）、
解码（`_decode_blf_with_dbc`）、候选 DBC 弹窗链（`_resolve_blf_dbc_paths` 一族）、
DBC 历史记忆、项目保存/恢复，全都只吃帧元组或 `dbc_paths`，不再关心文件格式。
**唯一 BLF 特定的环节是 `_read_blf_frames` 用 `BLFReader` 读文件。**

### 1.1 可行性实证（2026-08-11 本机 venv，python-can 4.6.1）

- `can.io.ASCReader` 直接读真实样本成功：CAN 帧全解析，`SV:` 行**静默跳过**，
  `Begin/End Triggerblock` 与注释行不干扰。
- 全文件解析 **7.2 s（358k msg/s）**，与同量级 BLF 读取相当，无需性能设计。
- 首帧字段核对：`t=0.100000`（保持测量相对时间，非 epoch）、`id=0x339`、
  `len=8`、payload 与文本一致；`msg.channel=18`（文件写 19，python-can 减 1，
  本链路本来就不使用 channel，与 BLF 同）。

### 1.2 为什么现在做

用户手上已有 CANoe `.asc` 采集数据、对应 DBC 后补。复用面全部就绪，增量只集中在
「识别 + 读帧 + 路由」三点；用户预期的操作逻辑「与打开 BLF 完全一样，弹 DBC 提示」
恰好就是现有链路的行为。

### 1.3 非目标

- **不**解析 `SV:` 系统变量/SOA 行——它们不是 CAN 帧，DBC 也解不了；将来若要
  SOA 信号另立 spec。
- **不**给 ASC 提供「无 DBC 原始字节查看」UI。与 `.blf` 打开语义严格一致：
  取消选 DBC = 不打开该文件（`_load_one_impl` 对 BLF 也从不走 raw-bytes 路径）。
- **不**把 DBC 写入批处理 recipe/preset JSON——沿用
  `2026-08-10-batch-blf-dbc-context-reuse-spec.md` 的决定（会话上下文，重开再提示）。
- **不**升版本号、**不**改 `help/`（跟随下次常规版本说明）；`quickref.py` 一行
  文案除外（§2.8）。
- **不**改 `blf_dbc_candidates.py` 纯函数与 DBC 历史记忆机制——CANoe ASC 天然
  共用同一份 `blf/recent_dbc_path_sets` 历史与同目录 `*.dbc` 候选扫描（这是特性，
  不是妥协：同一台架的 BLF 和 ASC 用同一批 DBC）。

---

## 2. 设计

### 2.1 识别（evidence-based，与 `ascii_format` 同哲学）

新模块 `mf4_analyzer/io/asc_can_format.py`：

```python
def sniff_canoe_asc(path) -> bool
```

- 只读文件**前 8 KB**、按行扫描前 ~64 行；命中一行
  `^base\s+(hex|dec)\s+timestamps\s+(absolute|relative)\b`（大小写不敏感、
  允许前导空白）即判定为 CANoe CAN 日志。该行是 CANoe ASC 的必需头
  （实测样本第 2 行）；通用表格 ASCII 不可能出现这一行。
- 解码失败 / IO 失败 / 空文件一律返回 `False`——回落到通用 ASCII 路径，
  **不新增任何失败模式**。
- 不放进 `ascii_format.py`：那个模块的职责是表格布局取证，两种 `.asc` 是
  互斥的两个格式，各留各的取证模块。

### 2.2 读帧

同模块内：

```python
def _read_asc_frames(fp, progress_callback=None) -> list[tuple[float, int, bytes]]
```

- `can.io.ASCReader`（**默认参数**；4.6.1 实测时间戳保持测量相对值）。
- 产出与 `_read_blf_frames` **完全同构**的 `(float(timestamp), int(arbitration_id),
  bytes(data))`；`is_error_frame` / `is_remote_frame` 丢弃（与 BLF 同）。
- 进度：`Path(fp).stat().st_size` 为总量、`reader.file.tell()` 每 512 帧采样一次，
  照抄 `_read_blf_frames` 的 best-effort 模式（进度回调只做信息展示，
  **绝不允许让有效导入失败**）。
- `finally` 里 `reader.stop()`。
- python-can 缺失时 `ImportError` 文案与 BLF 版同格式：
  「python-can 未安装，无法读取 CANoe ASC 文件。请先 pip install python-can」。
- CAN FD 行 `ASCReader` 原生支持（payload ≤ 64B 对下游无影响）；扩展帧 ID
  正常进整数元组。`msg.channel` 不参与（BLF 同）。

### 2.3 门面分发（不改公开名）

`DataLoader.read_blf_frames` 内部按后缀分发：`Path(fp).suffix.lower() == ".asc"`
→ `_read_asc_frames`，其余 → `_read_blf_frames`。

- `read_blf_frames` / `probe_blf_dbc` / `probe_blf_dbc_frames` / `load_blf_frames`
  / `load_blf` 门面名**全部保持不变**——它们是
  `docs/analyzer/specs/2026-08-10-batch-blf-dbc-context-reuse-spec.md` 钉住的
  公开缝（UI、BatchSheet、tests 多处引用），改名是纯 churn。docstring 更新为
  「Vector CAN 日志（BLF / CANoe ASC）」。
- **空帧哨兵文案是被字符串匹配的**：`"BLF 文件没有可读的 CAN 数据帧"` 在
  `_project_io_mixin._probe_blf_dbc_candidates`（当前 723 行附近）用
  `in str(exc)` 判断是否重抛。改法：在 `io/loader.py` 定义
  `NO_CAN_FRAMES_MESSAGE = "CAN 日志没有可读的数据帧"`，`read_blf_frames` /
  `probe_blf_dbc_frames` / `load_blf_frames` 三处 raise 与 mixin 的匹配点
  **同步改为引用该常量**。禁止只改一侧。

### 2.4 UI 路由（`ProjectIOMixin`）

**单文件** `_load_one_impl`：

- ext 分发处对 `.asc` 先 `sniff_canoe_asc`；命中 → 与 `.blf` **同一分支**
  （读帧 → `_resolve_blf_dbc_paths` 弹窗链 → 校验 → 解码 → 注册）；未命中 →
  维持现有 `load_ascii` 分支。实现上把 `.blf` 分支条件改为
  `ext == '.blf' or is_canoe_asc`，分支体内用格式标签区分文案：
  `fmt = "BLF" if ext == ".blf" else "CANoe ASC"`，状态栏/toast 写
  「已加载 {fmt}: name (N 行 · DBC×k 解码)」。
- `source_metadata`：`.blf` 保持 `{"source_kind": "blf", ...}`；CANoe ASC 写
  `{"source_kind": "canoe_asc", "dbc_paths": [...]}`。
- `blf_dbc_paths` / `blf_frames` / `blf_dbc_validated` 参数名**不改**
  （语义就是「CAN 日志 DBC 上下文」，改名波及恢复与批量导入调用点）。

**多文件**（一次拖入/多选 ≥2 个 CAN 日志）：

- 新私有谓词 `ProjectIOMixin._is_can_log_path(path) -> bool`：`.blf` → True；
  `.asc` → `sniff_canoe_asc`（异常吞掉返回 False）；其余 → False。
  纯方法、不引入新的跨文件写属性（状态所有权棘轮不受影响）。
- `_open_data_paths` 组批谓词（当前 `suffix == ".blf"`）与 `_load_blf_batch`
  内的非 BLF 旁路判断（当前 `suffix != ".blf"`）都改用它。混合 `.blf` + CANoe
  `.asc` 一批**共享同一 DBC 选择**，`read_blf_frames` 的分发自动处理两种容器。
- `_ask_blf_batch_dbc_action` 文案「本次添加了 N 个 BLF 文件」→
  「本次添加了 N 个 CAN 日志文件」。其余对话框（不匹配重试、候选确认、picker
  标题）都以 `path.name` 呈现，无需改。

### 2.5 项目保存/恢复（零代码改动，用测试钉住）

`save_project` 从 `fd.source_metadata["dbc_paths"]` 生成 `dbc_refs`——与扩展名
无关；`open_project → _restore_project_file_refs` 对每个 ref 调
`_load_one(key, blf_dbc_paths=pio.resolve_dbc_paths(...))`。所以只要 §2.4 把
`dbc_paths` 写进了 canoe_asc 的 source_metadata，项目往返**免费成立**。
本 spec 要求新增用例显式钉住这条（防未来有人按 source_kind 过滤 dbc_refs）。

### 2.6 `load_ascii` 兜底报错

`DataLoader.load_ascii` 开头调 `sniff_canoe_asc`，命中即：

```python
raise ValueError(
    "该 .asc 是 CANoe CAN 总线日志：请配 DBC 按 CAN 日志流程解码"
    "（主窗口打开或批处理导入均可）"
)
```

经 §2.9 的注册表消歧后，正常路径不会再把 CANoe ASC 送进 `load_ascii`；这条守卫
是纵深防御（直接调用方 / sniff 分歧场景），在路由缺口处给出**可行动**的报错，
而不是误导性的「Cannot detect a supported ASCII table layout」。

### 2.7 依赖与打包

- `runtime_dependencies.py` 的 can/cantools 条目**保持** `extensions=(".blf",)`：
  `.asc` 不能无条件要求 python-can（通用表格 ASCII 不需要）。缺依赖时由 §2.2
  的 ImportError 文案在打开时兜底。
- python-can 的 `can/io/__init__.py` 静态 `from .asc import ASCReader`——
  BLF 能在冻结构建里跑，ASC 子模块必然已被收录。执行计划里跑
  `test_packaging_imports.py` 验证即可，预期零改动。

### 2.8 发现性

`ui/quickref.py` 两处一行文案：格式清单 `"MF4 · MDF · BLF · ASCII · …"` 保持
（CANoe ASC 归入 BLF 同类），`QuickRow("BLF 报文解码", sub="需配 DBC 文件")` →
`QuickRow("BLF / CANoe ASC 报文解码", sub="需配 DBC 文件")`。
`hints.py` 若有对应滚动提示同步一句（执行时 grep 确认）。
CLAUDE.md「支持格式」行补「CANoe ASC CAN 日志（.asc，自动识别，配 DBC）」。

### 2.9 批处理支持（BatchSheet / BatchRunner / source_adapters）

批处理的一切格式分发都收口在 `SourceAdapterRegistry`（扩展名索引 + 重复扩展名
守卫），`.asc` 已被 ascii adapter 占用，同一扩展名不能注册两个 adapter。消歧在
**注册表查询点**做，一处改、全链路（进件行、availability、规划期探针、运行期
加载、`stable_source_id` 身份）自动一致：

**a) `SourceAdapterRegistry.adapter_for` 嗅探消歧**

- 入参解析出的扩展名为 `.asc` 且**入参是路径而非裸扩展名**时，调
  `sniff_canoe_asc(path)`：命中 → 返回 **"blf" adapter**；未命中/文件不存在/
  任何异常 → ascii adapter（现状）。
- **裸扩展名查询 `adapter_for(".asc")` 保持返回 ascii adapter**——没有文件可
  取证，且既有测试契约（`test_source_adapters.py` 用不存在的裸文件名如
  `"run.asc"`）依赖这一语义，全部不动。
- blf adapter 的 `extensions` 保持 `(".blf",)`，注册表索引与重复守卫不变；
  消歧只发生在 `adapter_for` 的查询路径上。
- 不加缓存：每文件一个会话内 `adapter_for` 仅被调 3–5 次（add/availability/
  probe/load），每次 8 KB 头部读取，成本可忽略。

**b) 顺流而下的自动获益（零改动，测试钉住）**

- `input_panel.add_disk_path`：CANoe `.asc` 经 blf adapter →
  `availability("limited"，缺 dbc_paths)` → 行呈现与 BLF 完全一致；
  `stable_source_id("blf", path, "root")` 与后续探针身份自动吻合。
- 规划期 no-load 探针 `_probe_blf` → `DataLoader.probe_blf_dbc` →
  `read_blf_frames` 后缀分发（§2.3）→ 对 `.asc` 直接可用；
  `BatchSheet._make_runner` 的 `seed_source_channels()` 喂给规划器的通道表
  照常成立（CLAUDE.md 批处理规划 no-load 约束）。
- 运行期 `load_sources` → `DataLoader.load_blf(path, dbc_paths=…)` → 同一分发。
- `batch.py._default_loader`（无 context）对 CANoe ASC 抛
  `SourceUnavailableError`，与 BLF 今日行为一致。

**c) 少量显式改动**

- `_probe_blf` 的 descriptor metadata：`source_kind` 按容器写
  `"blf"` / `"canoe_asc"`（`Path(path).suffix.lower()` 判断）；错误文案
  「BLF 与所选 DBC 不匹配…」→「CAN 日志与所选 DBC 不匹配…」。
- `SourceAdapter.availability` 里 blf 的 limited 理由
  「BLF 需要 DBC 解码上下文…」→「CAN 日志（BLF/CANoe ASC）需要 DBC 解码上下文…」。
- blf adapter `display_name`：`"Vector BLF + DBC"` → `"Vector CAN 日志 (BLF/ASC) + DBC"`。
- `BatchSheet._blf_paths_among`：后缀判断改为注册表判定
  `adapter_for(path).key == "blf"`（`UnsupportedSourceFormatError`/异常 → 排除），
  方法名保留（既有测试 seam）；`_ensure_blf_dbc_context` /
  `_add_disk_paths_with_blf_context` 逻辑零改动、自动覆盖 CANoe ASC。
  toast 文案「…为 BLF 选择 DBC」「已取消 BLF 的 DBC 选择」→ 用「CAN 日志」措辞。
- `ProjectIOMixin.resolve_blf_dbc_paths_for_batch`：`suffix == ".blf"` 谓词改用
  `_is_can_log_path`（§2.4），docstring 补 CANoe ASC。

**d) 与主窗打开链路的一致性**

sheet 进件先确保 DBC 上下文再 `add_disk_paths`（2026-08-10 spec 的既有编排），
CANoe ASC 走完全相同的弹窗与取消语义；同批混合 BLF+ASC 共享一份
`source_context["dbc_paths"]`（sheet 级一份上下文，沿用该 spec 的决定）。

---

## 3. 交互契约（与 BLF 完全对齐）

| 场景 | 行为 |
| --- | --- |
| 打开单个 CANoe `.asc` | 读帧 → 自动候选 DBC 提示（历史 + 同目录扫描 + 结构预筛）→ 确认/手选 → 不匹配可重试 → 解码加载 |
| 无任何候选 | 「未找到可自动匹配的 DBC…」→ 手选或取消 |
| 取消选 DBC | 该文件不打开，状态栏「已取消」 |
| 一次拖入 ≥2 个 CAN 日志（含混合 BLF+ASC） | 「统一选择 DBC / 逐个选择 / 取消」三选，与今日 BLF 批量导入一致 |
| DBC 与文件不匹配 | 与 BLF 同：警告 + 重选/跳过/停止 |
| 打开通用表格 `.asc` | 完全不受影响（sniff 未命中，走 `load_ascii` 原路径） |
| 项目保存/重开 | dbc_refs 持久化，重开免弹窗直接解码（同 BLF） |
| 成功选定 DBC | 计入同一份最近 DBC 历史，之后 BLF/ASC 互相受益 |
| 批处理磁盘/拖放进件 CANoe `.asc` | 与 BLF 同：先经主窗共享弹窗链解析 DBC 写入 sheet 级 `source_context`，再入列探针；取消则本次 CAN 日志不入列、同批其他文件照常 |
| 批处理进件通用表格 `.asc` | 不触发 DBC 门控，走 ascii adapter 原路径 |
| 批处理运行 CANoe `.asc` | 经 blf adapter 以 `dbc_paths` 上下文解码，信号级来源参与规划与执行（含 `seed_source_channels` no-load 规划） |

---

## 4. 验收

1. 真实样本 `datalog485.asc`：能识别为 CAN 日志、读出 2,576,029 帧、弹出 DBC
   提示链（无真实 DBC 前验收到此为止；合成 DBC 的全链路解码由测试覆盖）。
2. 合成 ASC + 合成 DBC（复用 `tests/_helpers/blf_factory.py` 的 DBC）：
   `_load_one` 全链路出通道、单位、ZOH 共轴，与同帧序列的 BLF 结果一致。
3. 通用表格 `.asc` 回归零变化（GUI 与批处理两侧）；`tests/ui/test_import_boundaries.py`
   等护栏全绿。
4. 项目保存/重开往返对 canoe_asc 源成立。
5. 批处理：CANoe `.asc` 磁盘进件触发既有 DBC 上下文编排、探针出信号级来源、
   带 DBC 上下文的运行产出与同帧序列 BLF 一致；`adapter_for` 裸扩展名语义不变。

---

## 5. 实测证据留档（2026-08-11 本机）

- 行构成：`awk` 统计 2,794,781 行 = 2,576,029 CAN 帧 + 218,746 SV + 7 头部。
- `ASCReader` 全解析：2,576,029 msgs / 7.2 s（358,201 msg/s）。
- 首帧：`t=0.100000 ch=18 id=0x339 fd=False len=8 data=28323c460a000000`。
- 前 2000 帧 unique IDs 57 个（0x212…0x64C），无 error/remote 帧。
