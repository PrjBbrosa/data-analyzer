# Cockpit Live Capture Wiring & Persistence Spec

Date: 2026-07-06
Status: Approved for implementation
Plan: `docs/analyzer/acquisition/plans/2026-07-06-cockpit-live-capture-and-persistence-implementation.md`
Parent spec: `docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md`（本 spec 只做增量，不改父 spec 契约）

## 背景（2026-07-06 实测核实的现状）

采集 cockpit 的 Stage 0–7 已全部落地，Stage 8（Vector/XCP 硬件链）骨架在位。
本轮实测核实了以下事实，修正了此前"A2L 事件没接通"的误判：

- **A2L 链路已通**：`apply_a2l_path`（`mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py:273`）
  原子提交 IF_DATA + measurement pool。真实 A2L
  （`/Users/donghang/Downloads/C0202_T04/A/ERD6_01_01_A0_C_02_02_T04_CANape_Aside.a2l`，1.5MB）
  经 UI 同款路径实测：**1.5s 解析出 323 个 measurement、5 个 DAQ 事件**
  （Rte_Appl_OS_Task_100ms / Rte_OsTask_BSW_10ms / _5ms / _1ms / BSW_2ms），XCP on CAN
  cmd=0x6C7 resp=0x6C6。
- **真后端切换已通**：`_maybe_swap_to_vector_backend`
  （`_connection_mixin.py:98-201`）在 Transport+IF_DATA+pool+selection 齐备时自动换
  Vector 后端；缺前置时硬拦截（`[FAKE backend]` 警告），不会静默录假数据。
- **头号缺口——UI 从不写 MF4**：`_start_recording`
  （`acquisition_ui/main_window/window.py:519-534`）只翻状态机 + fake 状态，
  **从不构造 `CaptureController`**。`request_stop_and_review`（window.py:448）在
  `_capture_controller is None` 时走 demo 桩。整条 backend→ring→writer 落盘链只有
  CLI（`acquisition_capture/__main__.py:363`）在用。
- **三击入口无持久化**：`open_acquisition_cockpit`
  （`mf4_analyzer/ui/main_window/window.py:1702-1718`）构造 `CockpitMainWindow()`
  不传 `config_path` → Transport/favorites/A2L 全部不跨会话。
- **pya2l 不在 requirements**：`.venv` 里装的是发行包 **`pya2ldb`**（1.0.332，import 名
  `pya2l`），`requirements.txt` 无此行 → 新环境装完左栏必空。
- **CLI probe 双重导入 bug**：`python -m can_logger.p0.a2l_probe` 失败于
  `unexpected result type: A2LSummary`（`a2l_probe.py:295-299`）——父进程模块以
  `__main__` 身份加载，pickle 回来的类对象来自 `can_logger.p0.a2l_probe` 正名模块，
  isinstance 判否。**仅 CLI 触发，UI import 路径不受影响**（已实测）。
- **乱码文案**：`_connection_mixin.py:142` `"measurement selection ä¸ºç©º"`
  （"为空"被 UTF-8→latin-1 双重编码）。
- **误导性历史注释**：约 60 处 "Stage 5 / Stage 8" 注释指向的功能已实现
  （如 `window.py:98` `_PlaceholderReviewModal` 标题"复盘 (Stage 5)"）。

## 目标

三击 logo 打开的 cockpit 在**代码侧**达到"直接能用"：

1. 点录制 → 真实 `CaptureController` 驱动 backend→ring→Mf4Writer，产出真 MF4 +
   `session_summary.json` + `preflight.json`，review modal 走真路径，可回传 Analyzer。
   demo（FakeBackend）与真后端走**同一条**管线——demo 也写真文件（CLI 已证明可行）。
2. Transport / favorites / 上次 A2L 跨会话持久化（三击入口传 config_path +
   A2L 记忆回灌）。
3. 依赖齐备（`pya2ldb` 进 requirements）。
4. 修复 CLI probe 双重导入 bug、乱码文案；清理误导性 Stage 注释。
5. 后端身份可视（demo 模式明确标识，防止把合成数据当真数据存档）。

## 非目标（明确不做）

- **可见菜单入口**：产品决策保持三击 logo 隐藏入口，不加菜单项。
- Vector/XCP 真机验证、`_read_dto_frame`（`backends.py:642-656`）收紧、pyxcp 版本钉死
  ——硬件波，由用户在 Windows + Vector 硬件上做。
- `_probe_can/_probe_xcp/_probe_daq`（`_connection_mixin.py:250-266`）真值化——数值
  只有真硬件下才有意义，随硬件波做。
- BLF/DBC candidate flow（另有 spec，未接入，维持现状）。
- Windows 打包真机冒烟。

## 契约

### C1 采集会话生命周期（UI 侧）

- 样本形状契约：全链路 `(channel_name, timestamp, value)`
  （`backends.py:88` poll 签名、`writer.py:102-108` append_batch）。
  UI 空闲路径 `_poll_live` 现存的 `(ts, channel, value)` 反序写法
  （`_polling_mixin.py:93`）必须改为正序——recording 期 ring 与 controller 共享，
  形状不一致会把坏元组喂进 writer。
- 状态 × controller 矩阵：

  | 状态 | backend | controller | `_poll_live` 行为 |
  |---|---|---|---|
  | ConnectedIdle | 运行（连接时 `backend.start(selection)`） | None | 直接 `backend.poll()` → 卡片 + ring（watermark 用，永不 drain 到 writer） |
  | Recording | 由 controller 拥有 | 每次录制新建 | `controller.poll_step()`；卡片经 `sample_tap` 喂 |
  | ReviewModal→ConnectedIdle | 停止 → 关 modal 后重启（恢复空闲流） | 关 modal 后置 None | 回空闲路径 |

- 录制开始：先 `backend.stop()`（空闲流），**丢弃** ring 残留（`ring.drain()` 不落盘
  ——录制前的空闲样本绝不能进 MF4），再 `controller.start()`（其内部
  `backend.start(config.selected)` 以录制时刻的选择重启后端；Vector 的 DAQ list
  按选择分配，必须如此）。
- 录制中 controller 自停（ring 持续红 / writer 错 / duration 到）→ UI 在下一次
  poll 检测 `not controller.running` → 走 `request_stop_and_review(auto_stop=...)`。
- `SessionConfig.selected` 为空且非 demo → 拒绝开始录制（状态栏说明），留在
  ConnectedIdle。demo（`allow_fake_backend=True`）回退 `DemoSignal`，与
  `_begin_connection_attempt` 现行为一致（`_connection_mixin.py:70`）。
- 测试注入的 controller（`set_capture_controller`）优先——已注入则不重建，
  保持现有 182 个 UI 测试的注入契约。
- 输出命名：`<输出目录>/capture_YYYYmmdd_HHMMSS.mf4`，同秒冲突加 `_N` 后缀；
  输出目录来自工具栏选择器（`_output_dir_label`，默认 `data/runs`），录制前
  `mkdir(parents=True, exist_ok=True)`。
- `CaptureController` 增加可选 `sample_tap` 回调（poll_step 内、入 ring 前调用，
  异常吞掉不杀采集热路径）——UI 实时卡片的喂数口。**加法改动**，CLI 与现有 8 个
  controller 测试零变化。

### C2 配置持久化（三击入口）

- `open_acquisition_cockpit` 传
  `config_path = ~/.acquisition-cockpit/acquisition_config.yaml`
  （与 `default_recent_path()` 同目录；schema `ALLOWED_TOP_LEVEL` 已含 `a2l_path`，
  `config_store.py:49-61`，无需升 v3）。
- `apply_a2l_path` 成功提交后持久化 `a2l_path`（新 `save_a2l_path`，模式照抄
  `save_transport`，`config_store.py:218`）。失败不写。
- `_hydrate_from_config_path` 尾部：存在 `store.a2l_path` 且文件存在 →
  `QTimer.singleShot(0, ...)` 延迟自动 `apply_a2l_path`（窗口先画完；实测 1.5s 阻塞
  可接受）；文件已不存在 → 状态栏提示，不报错。
- Transport 持久化链（`_persist_transport`）已存在，不动。

### C3 后端身份可视

- 状态栏常驻 badge（`QLabel`，objectName `cockpitBackendBadge`）：
  `后端: FAKE·演示` / `后端: Vector` / `后端: Replay`。换后端、开始连接、
  会话结束时刷新。
- `allow_fake_backend=True` 时窗口标题追加 `· 演示模式`。
- 现有 `[FAKE backend]` 状态栏硬警告与前置条件弹窗保持不变。

### C4 修复项

- `a2l_probe.py` `if __name__ == "__main__"` 改为经正名模块 re-dispatch
  （`from can_logger.p0.a2l_probe import main`），修 isinstance 双重导入判否。
- `_connection_mixin.py:142` 乱码 → `"measurement selection 为空"`；并全仓 sweep
  同类双重编码（正则 `ä¸|ç©|æ˜|å°` 级别的 UTF-8-as-latin-1 特征串）。
- Stage 注释清理：`acquisition_ui/`、`acquisition_capture/` 内描述"将来实现"
  但实际已实现的 "Stage 5 / Stage 8" 注释改为描述现状；
  `_PlaceholderReviewModal` 标题改"复盘（无会话数据）"。只改注释与文案，
  不改行为。

## 验收标准

1. offscreen e2e（pytest-qt）：demo cockpit 连接 → 录制 ≥10 个 poll → 停止 →
   `last_stop_result` 非 None，输出目录出现 `.mf4` + `.session_summary.json` +
   `.preflight.json`，MF4 可被 `DataLoader.load_mf4` 回读且通道名 == 选择名逐字。
2. review 关闭后回 ConnectedIdle，空闲流恢复（live 卡片继续收样本），可立刻
   开始第二次录制且产出第二个不同名 MF4。
3. 用临时 HOME 跑：改 Transport + 选 A2L → 关窗重开 → Transport chip 已配置、
   左栏自动载入同一 A2L（monkeypatch 掉真实解析）。
4. `python -m can_logger.p0.a2l_probe <真实A2L> --limit 8` 退出码 0（手动验证，
   机器上有真实文件）。
5. 现有全量 pytest 无回归（既有 baseline 失败除外）；需要调整的既有 UI 测试
   仅限"曾假设无管线也能录制"的用例，逐个列明原因。
6. 新环境 `pip install -r requirements.txt` 后 `import pya2l` 成功。

## 风险与对策

- **既有 UI 测试破坏面**：`_start_recording` 增加会话构造后，未注入 controller 且无
  选择的测试会被拒录。对策：`_begin_capture_session` 对已注入 controller 短路返回；
  demo 回退 DemoSignal；其余逐例修（预计 <10 个）。
- **共享 ring 的旧样本污染**：录制开始前 drain-丢弃 + 形状统一（C1）双保险。
- **Vector 后端在本波不可实测**：所有新代码 hardware-free 可测（Fake/Replay 全覆盖），
  Vector 路径复用同一 controller 管线，不新增 Vector-only 分支。
