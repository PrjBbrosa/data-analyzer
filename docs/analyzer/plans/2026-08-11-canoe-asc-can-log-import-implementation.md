# CANoe ASC（CAN 总线文本日志）按 BLF 链路导入 · 执行计划

- **状态**：已完成（T0–T7 落地，T8 局部门禁 192 passed / 1 skipped；全量两条命令待树内并行改动收敛后随提交跑）
- **日期**：2026-08-11
- **规格**：`docs/analyzer/specs/2026-08-11-canoe-asc-can-log-import-spec.md`（先读完再动手）
- **主改**：新 `io/asc_can_format.py` · `io/loader.py`（分发 + 哨兵常量 + load_ascii 兜底）·
  `ui/main_window/_project_io_mixin.py`（路由 + 谓词 + 文案）·
  `io/source_adapters.py`（`adapter_for` 嗅探消歧，批处理）·
  `ui/drawers/batch/sheet.py`（谓词改注册表判定）· `ui/quickref.py` 一行 ·
  新测试 ×2 + 既有测试小改

执行环境提醒（来自 CLAUDE.md，务必遵守）：

- 一律用仓库 venv：`.venv/bin/python`；Qt 用例前缀
  `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=.`。
- 动手前**先记录基线失败数**（见 T0），别把既有红算到自己头上。
- python-can / cantools 在 CI 位面可能缺席：所有新测试开头
  `pytest.importorskip("can")` + `pytest.importorskip("cantools")`
  （照抄 `tests/ui/test_blf_open.py` 头部）。

---

## T0 · 基线

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_blf_loader.py tests/test_ascii_loader.py tests/test_batch_loader_dispatch.py \
  tests/test_source_adapters.py tests/ui/test_blf_open.py tests/ui/test_blf_batch_import.py \
  tests/ui/test_batch_blf_dbc_context.py tests/ui/test_batch_input_panel.py \
  tests/ui/test_project_session.py tests/ui/test_import_boundaries.py \
  -q --tb=no
```

记下 passed/failed 数。截至 2026-08-11 主体基线全绿（5925 passed / 9 skipped），
上面这个子集应为全绿；不绿先停下查环境。

## T1 · `io/asc_can_format.py`（识别 + 读帧）

按 spec §2.1/§2.2 新建模块，两个入口：

- `sniff_canoe_asc(path) -> bool`：前 8 KB、前 ~64 行，正则
  `^base\s+(hex|dec)\s+timestamps\s+(absolute|relative)\b`（`re.I`，允许前导空白）。
  任何异常（不存在/权限/解码）→ `False`。编码尝试参考 `ascii_format._ENCODINGS`
  的精神，但 CANoe 头是纯 ASCII，`errors="replace"` 读 bytes 再 decode 足够。
- `_read_asc_frames(fp, progress_callback=None)`：`can.io.ASCReader`（默认参数），
  逐条产出 `(float(msg.timestamp), int(msg.arbitration_id), bytes(msg.data))`，
  丢 `is_error_frame` / `is_remote_frame`；进度照抄 `blf_format._read_blf_frames`
  的模式（`stat().st_size` 总量、`reader.file.tell()` 每 512 帧采样、
  `_emit_progress` 复用 `blf_format` 里的，回调失败绝不打断导入）；
  `finally: reader.stop()`；ImportError 文案
  「python-can 未安装，无法读取 CANoe ASC 文件。请先 pip install python-can」。

**测试**（新 `tests/test_asc_can_loader.py`）：

1. 先在 `tests/_helpers/blf_factory.py` 增加
   `write_sample_asc(path, *, n=5, dt=0.1, t_start=1.0) -> Path`：直接写文本——
   头四行（`date ...` / `base hex timestamps absolute` / `no internal events logged`
   / `Begin Triggerblock ...`），随后交替写 `0x123`（EngineData）与 `0x100`
   （VehicleSpeed）帧行，payload 与 `write_sample_blf` 相同的编码值（照它的
   struct 打包结果转 hex 字节列），**中间故意插两行 `SV:` 系统变量行**，结尾
   `End TriggerBlock`。帧行格式照真实样本：
   `f"   {t:.6f} 1  {aid:03X}             Rx   d 8  {' '.join(f'{b:02x}' ...)}"`。
   写完先用 `ASCReader` 自检读回 n×2 条再返回（工厂自身保真）。
2. `sniff_canoe_asc`：对 `write_sample_asc` 产物 → True；对
   `tests/test_ascii_loader.py` 用的表格 ASCII 样式内容 → False；对空文件/不存在
   路径 → False。
3. `_read_asc_frames`：帧数 = 2n（SV 行被跳过）、时间戳/ID/payload 与写入值
   一致、顺序保持。
4. `DataLoader.read_blf_frames(asc_path)`（走 T2 分发）→ 与 3 同结果；
   `DataLoader.load_blf_frames(frames, dbc_paths=[two_message_dbc])` → 出
   `EngineSpeed` / `Throttle` / `Speed` 三通道、共轴 `Time` 从 0 起（t0 归零）、
   数值与 `write_sample_blf` 同参数走 BLF 链路的结果**逐点一致**（这是
   「同帧序列、两容器、一结果」的关键断言）。

## T2 · `DataLoader` 分发 + 哨兵常量 + `load_ascii` 兜底

`io/loader.py`：

- `read_blf_frames` 开头按 `Path(fp).suffix.lower() == ".asc"` 分发到
  `_read_asc_frames`（函数体内 import，与 blf 的惰性风格一致），否则原路
  `_read_blf_frames`。docstring 更新为「Vector CAN 日志（BLF / CANoe ASC）」。
- 定义 `NO_CAN_FRAMES_MESSAGE = "CAN 日志没有可读的数据帧"`；
  `read_blf_frames` / `probe_blf_dbc_frames` / `load_blf_frames` 三处
  `"BLF 文件没有可读的 CAN 数据帧"` 全部改用常量。
- **同步改** `_project_io_mixin._probe_blf_dbc_candidates` 里的字符串匹配
  （当前 723 行附近 `if "BLF 文件没有可读的 CAN 数据帧" in str(exc)`）为
  `from ...io.loader import NO_CAN_FRAMES_MESSAGE`（相对 import 按该文件现状）。
  这条哨兵是被字符串匹配的，**两侧必须同一提交里改**。
- `load_ascii` 开头：`sniff_canoe_asc(fp)` 命中 → raise spec §2.6 的 ValueError。

**测试**：

- `tests/test_asc_can_loader.py` 补：空 ASC（只有头部无帧行）→
  `read_blf_frames` raise 且文案 == `NO_CAN_FRAMES_MESSAGE`。
- `tests/test_ascii_loader.py` 增一条：对 CANoe 内容调 `load_ascii` → raise，
  报错含「CANoe CAN 总线日志」；既有表格 ASCII 用例全部不动、必须保持绿。
- `.blf` 路径回归：`tests/test_blf_loader.py` 全绿（分发不得扰动 BLF）。

## T3 · UI 路由（`_project_io_mixin.py`）

按 spec §2.4：

- 新私有方法 `_is_can_log_path(path)`（`.blf` → True；`.asc` → sniff，异常 False；
  其余 False）。注意：这是方法不是新 `self.X` 属性，不碰状态所有权棘轮。
- `_load_one_impl`：`.blf` 分支条件改为 `ext == '.blf' or (ext == '.asc' and
  sniff_canoe_asc(p))`（sniff 结果存局部变量，别读两次文件）；分支体内
  `fmt = "BLF" if ext == ".blf" else "CANoe ASC"` 用于状态栏/toast；
  `source_kind` 按 ext 写 `"blf"` / `"canoe_asc"`；`.asc` 的通用表格分支保持原样
  （sniff 未命中才会到达）。
- `_open_data_paths`：组批谓词 `suffix == ".blf"` → `self._is_can_log_path(path)`
  （变量名 `blf_paths` 可顺手改 `can_log_paths`，只在本函数内）。
- `_load_blf_batch`：`path.suffix.lower() != ".blf"` → `not self._is_can_log_path(path)`。
- `_ask_blf_batch_dbc_action` 文案「N 个 BLF 文件」→「N 个 CAN 日志文件」。
  改前 grep `tests/ui/test_blf_batch_import.py` 是否断言了旧文案，有则同步。

**测试**（新 `tests/ui/test_asc_can_open.py`，照 `tests/ui/test_blf_open.py` 的
monkeypatch 范式）：

1. `_load_one`（合成 CANoe ASC + monkeypatch `_prompt_blf_dbc` 返回
   `write_two_message_dbc`）→ `len(mw.files) == 1`，通道含 `EngineSpeed`，
   `source_metadata["source_kind"] == "canoe_asc"`、`dbc_paths` 已记录。
2. `_load_one` + `_prompt_blf_dbc` 返回 `[]` → 不打开（`len(mw.files) == 0`）。
3. 通用表格 `.asc` → 仍走 `load_ascii`（monkeypatch 一个哨兵在
   `_resolve_blf_dbc_paths` 上，断言未被调用）。
4. `_open_data_paths` 混合两个 CAN 日志（1 BLF + 1 CANoe ASC，monkeypatch
   `_ask_blf_batch_dbc_action` → "batch"、`_prompt_blf_dbc` → DBC）→ 两文件都加载。
5. 既有 `tests/ui/test_blf_open.py`、`tests/ui/test_blf_batch_import.py` 全绿。

## T4 · 项目往返

`tests/ui/test_asc_can_open.py` 或 `tests/ui/test_project_session.py` 增一条：
加载合成 CANoe ASC（带 DBC）→ `save_project(tmp.tlproj)` → `close_all(force=True)`
→ `open_project` → 文件回来、通道在、**过程中不弹 DBC 选择**（monkeypatch
`_prompt_blf_dbc` 为 raise 的哨兵即可证明）。照 `test_project_session.py` 里
BLF 往返用例的现成写法（若有）或最接近的项目往返用例。

## T5 · 批处理接线（spec §2.9）

**a) `io/source_adapters.py`**

- `SourceAdapterRegistry.adapter_for`：解析出扩展名 `.asc` 且入参**不是**裸扩展名
  （`raw.startswith(".")` 为 False）时，`sniff_canoe_asc(raw)`（函数体内 import；
  任何异常按 False 处理）：True → 返回 `self._by_extension[".blf"]` 对应 adapter，
  False → 原路 ascii。注册表构造、重复扩展名守卫、`supported_extensions` 全部不动。
- `_probe_blf`：metadata `source_kind` 按 `Path(path).suffix.lower()` 写
  `"blf"` / `"canoe_asc"`；错误文案「BLF 与所选 DBC 不匹配…」→「CAN 日志与所选
  DBC 不匹配…」。
- `availability` 的 blf limited 理由与 blf adapter `display_name` 按 spec §2.9(c)
  改措辞。改文案前先 grep `tests/` 是否断言旧字符串，有则同步。

**b) `ui/drawers/batch/sheet.py`**

- `_blf_paths_among`：后缀判断改为
  `DEFAULT_SOURCE_ADAPTER_REGISTRY.adapter_for(path).key == "blf"`
  （`except Exception` → 排除该路径）。**方法名与返回形状不变**（测试 seam）。
- toast 文案两处（「无法为 BLF 选择 DBC…」「已取消 BLF 的 DBC 选择」）按 spec
  改「CAN 日志」措辞；先 grep `tests/ui/test_batch_blf_dbc_context.py` 同步断言。
- `_ensure_blf_dbc_context` / `_add_disk_paths_with_blf_context` 逻辑不动。

**c) `_project_io_mixin.resolve_blf_dbc_paths_for_batch`**

- `suffix == ".blf"` 谓词改 `self._is_can_log_path(path)`（T3 已加），docstring
  补 CANoe ASC。

**测试**：

1. `tests/test_source_adapters.py` 增：
   - 真实 CANoe 内容文件（`write_sample_asc`）→ `adapter_for(path).key == "blf"`；
   - 表格内容 `.asc` 文件 → `"ascii"`；不存在的路径 / 裸 `"run.asc"` / `".asc"`
     → `"ascii"`（既有语义钉死）；
   - CANoe asc + `dbc_paths` context：`probe_sources` 出信号级 descriptor
     （`source_kind == "canoe_asc"`、`stable_source_id` 前缀 blf）；无 context →
     `availability("limited")`；
   - `load_sources(asc, context={"dbc_paths": [dbc]})` 通道与同帧 BLF 一致。
2. `tests/test_batch_loader_dispatch.py` 增：CANoe asc 无 context 经
   `_default_loader` → `SourceUnavailableError`（与 blf 同）；表格 asc 原用例不动。
3. `tests/ui/test_batch_blf_dbc_context.py` 增：磁盘进件含 CANoe `.asc`（stub
   resolver）→ `_source_context["dbc_paths"]` 写入、行入列；混合 BLF+ASC 一次
   进件只弹一次 resolver；取消 → CAN 日志不入列、同批表格 asc 照常入列。

## T6 · 发现性 + 文档

- `ui/quickref.py`：`QuickRow("BLF 报文解码", ...)` →
  `QuickRow("BLF / CANoe ASC 报文解码", sub="需配 DBC 文件")`。跑
  `tests/ui/` 下 quickref 相关用例（grep `quickref` 定位）确认无文案契约红。
- `ui/hints.py`：grep `BLF`，若有滚动提示提及则同步一句；没有就不加。
- `CLAUDE.md` 产品约束「支持格式」行补：`CANoe ASC CAN 日志（.asc 自动识别，配 DBC，
  与 BLF 同链路）`。同段 ASCII 一句后补一句「`.asc` 先经 CANoe 取证，命中走 CAN
  日志链路，未命中才按通用 ASCII 解析」。
- **不**改 `help/`、**不**升版本、**不**动 `docs/analyzer/specs|plans` 下历史文档。

## T7 · 真实样本冒烟（本机，非测试套件）

真实文件 442 MB 未入库，不进 pytest。跑一次性脚本（scratch，不提交）：

```bash
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python - <<'EOF'
from mf4_analyzer.io.asc_can_format import sniff_canoe_asc
from mf4_analyzer.io.loader import DataLoader
p = "testdoc/ASC/datalog485.asc"
assert sniff_canoe_asc(p) is True
frames = DataLoader.read_blf_frames(p)
print(len(frames))          # 预期 2576029
assert len(frames) == 2576029
print("t0..t1:", frames[0], frames[1])
EOF
```

另外 offscreen 起 `MainWindow`，monkeypatch `_prompt_blf_dbc → []` 后
`_load_one(真实路径)`，断言干净取消（走到弹窗链、无异常、无文件注册）。
批处理侧再补一条：`DEFAULT_SOURCE_ADAPTER_REGISTRY.adapter_for(真实路径).key
== "blf"` 且无 context 时 `availability_for` 为 limited。
真实 DBC 用户后补，解码全链路以 T1/T3/T5 合成件为准。

## T8 · 门禁

```bash
# 局部（改动面全部子目录）
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_asc_can_loader.py tests/test_blf_loader.py tests/test_ascii_loader.py \
  tests/test_batch_loader_dispatch.py tests/test_source_adapters.py \
  tests/test_packaging_imports.py tests/test_batch_render_import_boundary.py \
  tests/ui/test_asc_can_open.py tests/ui/test_blf_open.py \
  tests/ui/test_blf_batch_import.py tests/ui/test_batch_blf_dbc_context.py \
  tests/ui/test_batch_input_panel.py tests/ui/test_batch_drop_import.py \
  tests/ui/test_project_session.py tests/ui/test_import_boundaries.py \
  tests/ui/test_main_window_state_ownership.py -q

# 全量（两条命令，别合并跑——见 CLAUDE.md 的 segfault 说明）
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  --ignore=tests/acquisition_ui -q
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui -q
```

与 T0 基线比对：新增失败必须为 0。`test_gen_help_screenshots.py` 依赖本机
`testdoc/`，红了按 CLAUDE.md 判定是否环境性。

---

## 已知坑（执行时对照）

- **哨兵文案两侧同改**（T2）：loader 三处 raise 与 mixin 一处 `in str(exc)`
  匹配，漏改任何一侧 = 空帧场景静默变行为。
- `_load_one_impl` 是长函数，改分支条件时保持 `except Exception` 兜底结构不变，
  别顺手重构（`AGENTS.md` 的 Change Discipline：小步、只做本 spec 范围）。
- 新测试文件记得 `pytest.importorskip("can")` / `("cantools")`，否则 win32-gated
  依赖缺席的环境会红。
- `write_sample_asc` 的帧行时间戳列格式用 `%.6f`，ID 用大写 hex 无 `0x` 前缀
  （CANoe 习惯）；写完必须 ASCReader 自检回读，防工厂自身笔误变成假绿。
- sniff 只读 8 KB：不许在 sniffer 里整读 442 MB 文件；`_load_one_impl` 里 sniff
  结果存局部变量，避免同文件读两次头。
- 进度回调 best-effort：任何 `progress_callback` 异常不得让导入失败
  （照抄 `_emit_progress` 的吞异常语义）。
- **`adapter_for` 的裸扩展名语义是测试契约**：`test_source_adapters.py` 大量用
  不存在的裸文件名（`"run.asc"`、`"UPPER.MF4"`）调 `adapter_for`——嗅探只对
  「解析出 `.asc` 的真实路径查询」生效，文件不存在/裸扩展名一律回 ascii。
  改完先单跑该文件确认既有用例零红。
- **不许给 `.asc` 双注册**：注册表构造器有 duplicate-extension `ValueError`
  守卫，blf adapter 的 `extensions` 保持 `(".blf",)`，消歧只在 `adapter_for`。
- sheet 的 `_blf_paths_among` 改注册表判定后会对每个候选路径做一次 8 KB 头部
  读取——只在进件/拖放时调用，频度可接受；不许把它挪进任何 per-paint 路径。
- 批处理侧改的三处文案（limited 理由、探针不匹配、sheet toast）都可能被测试
  断言，改前 grep 旧字符串同步。
