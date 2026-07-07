# Cockpit Live Capture Wiring & Persistence — Implementation Plan

> **For agentic workers (Codex):** 按任务顺序执行，checkbox 跟踪进度。每个任务
> 自带测试闭环：先写失败测试 → 实现 → 跑绿 → commit。不要跨任务合并 commit。
> 全程不要 `run_in_background` 跑全量 pytest（TCC 教训）；用前台命令。

Date: 2026-07-06
Spec: `docs/analyzer/acquisition/specs/2026-07-06-cockpit-live-capture-and-persistence-spec.md`

**Goal:** 三击 logo 打开的采集 cockpit 点录制即产出真实 MF4（demo 与真后端同一条
controller 管线），配置与上次 A2L 跨会话持久化，依赖/乱码/CLI bug 修复。

**Architecture:** 新增 `CaptureSessionMixin` 拥有 `CaptureController` 生命周期
（录制时构造、review 关闭后拆除并恢复空闲流）；`CaptureController` 加
`sample_tap` 回调喂实时卡片；ring 与 UI 共享（watermark 链不动）但录制前
drain-丢弃。持久化复用 `config_store` 既有 schema（`a2l_path` 键已在
ALLOWED_TOP_LEVEL）。

**Tech Stack:** PyQt5 + pytest-qt（offscreen）、asammdf（writer 已有）、
pya2ldb（A2L）。

## Global Constraints

- 命令一律用 `.venv/bin/python`（如 `.venv/bin/python -m pytest ...`）。
- 样本形状全链路 `(channel_name, timestamp, value)`（`writer.py:105`）。
- 通道命名契约：MF4 通道名 == A2L measurement name 逐字（`writer.py:69-73`）。
- macOS 模块导入期不得 import python-can/pyxcp/pya2l（懒加载/子进程隔离已有，勿破坏）。
- `ui_kit` 不得 import `ui.*` / `acquisition_ui.*`。
- 保持既有测试注入契约：`set_capture_controller` 注入的 controller 优先于自建。
- 文案含中文的文件 IO 显式 `encoding="utf-8"`。
- 不改 `_read_dto_frame`（硬件波）、不加可见菜单入口（产品决策：保持三击 logo）。

---

### Task 1: pya2ldb 进 requirements

**Files:**
- Modify: `requirements.txt`（在 `python-can>=4.3.0` 行附近）

**Interfaces:** 无代码接口；后续任务依赖 `import pya2l` 可用。

- [ ] **Step 1: 加依赖行**

在 `requirements.txt` 的 `python-can>=4.3.0` 行之后加：

```
pya2ldb>=1.0  # A2L 解析（import 名是 pya2l）— cockpit measurement summary 依赖
```

注意：发行包名 `pya2ldb`，import 名 `pya2l`（本机 .venv 已装 1.0.332）。
不加平台 marker——macOS 实测可用，Windows 侧已有子进程隔离守卫
（`can_logger/p0/_a2l_subprocess.py`）。

- [ ] **Step 2: 验证**

Run: `.venv/bin/python -c "import pya2l; print(pya2l.__name__)"`
Expected: 输出 `pya2l`，退出码 0。

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore(acquisition): declare pya2ldb dependency for A2L measurement summary"
```

---

### Task 2: 修乱码文案 + 双重编码 sweep

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/main_window/_connection_mixin.py:142`
- Test: `tests/acquisition_ui/test_connection_messages.py`（新建）

**Interfaces:** 无；纯文案。

- [ ] **Step 1: 写失败测试**

```python
"""Guard against UTF-8-as-latin-1 double-encoded copy in acquisition UI."""
from pathlib import Path

import mf4_analyzer.acquisition_ui.main_window._connection_mixin as cm


def test_no_double_encoded_text_in_connection_mixin():
    src = Path(cm.__file__).read_text(encoding="utf-8")
    # "为空" double-encoded shows up as "ä¸ºç©º"
    assert "ä¸º" not in src
    assert "measurement selection 为空" in src
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_connection_messages.py -v`
Expected: FAIL（`"measurement selection 为空" in src` 断言不成立）

- [ ] **Step 3: 修复**

`_connection_mixin.py:142`：

```python
            missing.append("measurement selection 为空")
```

- [ ] **Step 4: 全仓 sweep 同类问题**

Run: `grep -rn "ä¸\|ç©\|æ˜\|å¤\|è¯" --include="*.py" mf4_analyzer can_logger tests`
Expected: 0 命中。若有其他命中，逐个改回正确中文（同为文案修复，并入本 commit）。

- [ ] **Step 5: 跑测试确认通过 + Commit**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_connection_messages.py -v`
Expected: PASS

```bash
git add mf4_analyzer/acquisition_ui/main_window/_connection_mixin.py tests/acquisition_ui/test_connection_messages.py
git commit -m "fix(acquisition): repair double-encoded precondition message"
```

---

### Task 3: a2l_probe CLI 双重导入修复

**Files:**
- Modify: `can_logger/p0/a2l_probe.py:321-323`（`__main__` 块）
- Test: `tests/test_a2l_probe_cli_dispatch.py`（新建）

**Interfaces:** 无新接口；`python -m can_logger.p0.a2l_probe` 行为修复。

背景：经 `-m` 运行时本模块以 `__main__` 身份加载，`load_measurement_summary`
里 `isinstance(summary, A2LSummary)`（`a2l_probe.py:295`）拿到的是 `__main__`
下的类对象，而 pickle 反序列化回来的是 `can_logger.p0.a2l_probe.A2LSummary`
——两份类对象不等，正确结果被误判。修法：`__main__` 块 re-dispatch 到正名模块。

- [ ] **Step 1: 写失败测试**

```python
"""The -m entry must re-dispatch through the canonical module name,
otherwise pickle'd A2LSummary fails the isinstance check (double-import)."""
from pathlib import Path

import can_logger.p0.a2l_probe as probe


def test_dunder_main_dispatches_to_canonical_module():
    src = Path(probe.__file__).read_text(encoding="utf-8")
    assert "from can_logger.p0.a2l_probe import main as _canonical_main" in src
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_a2l_probe_cli_dispatch.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

把 `a2l_probe.py` 末尾的

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

改为：

```python
if __name__ == "__main__":  # pragma: no cover - module entry
    # Re-dispatch through the canonical module name: running via
    # ``-m can_logger.p0.a2l_probe`` loads this file as ``__main__``,
    # so the ``A2LSummary`` class object here is NOT the one pickle
    # resolves (``can_logger.p0.a2l_probe.A2LSummary``) and the
    # isinstance check in ``load_measurement_summary`` rejects a
    # perfectly good subprocess result.
    from can_logger.p0.a2l_probe import main as _canonical_main

    raise SystemExit(_canonical_main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_a2l_probe_cli_dispatch.py -v`
Expected: PASS

- [ ] **Step 5: 手动端到端验证（本机有真实 A2L）**

Run: `.venv/bin/python -m can_logger.p0.a2l_probe "/Users/donghang/Downloads/C0202_T04/A/ERD6_01_01_A0_C_02_02_T04_CANape_Aside.a2l" --limit 8`
Expected: 退出码 0，打印 measurement 摘要（此前报
`unexpected result type: A2LSummary`）。

- [ ] **Step 6: Commit**

```bash
git add can_logger/p0/a2l_probe.py tests/test_a2l_probe_cli_dispatch.py
git commit -m "fix(acquisition): a2l_probe -m entry re-dispatches through canonical module"
```

---

### Task 4: CaptureController 加 sample_tap

**Files:**
- Modify: `mf4_analyzer/acquisition_capture/controller.py`（`__init__` + `poll_step`）
- Test: `tests/test_acquisition_controller.py`（追加用例）

**Interfaces:**
- Produces: `CaptureController(config, backend, *, writer=None, ring=None, clock=..., sample_tap: Callable[[list[tuple[str, float, float]]], None] | None = None)`
  ——Task 5/6 的 UI 接线消费此参数。tap 在 poll_step 内、样本入 ring 之前调用，
  收到 backend.poll() 原始批次；tap 抛异常不得中断采集。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_acquisition_controller.py`，
沿用该文件现有的 config/backend 构造 fixture；若无现成 fixture，用下面的独立构造）

```python
import time

from mf4_analyzer.acquisition_capture.backends import FakeRecorderBackend
from mf4_analyzer.acquisition_capture.controller import CaptureController
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement, SessionConfig


def _tap_config(tmp_path):
    return SessionConfig(
        output_mf4=tmp_path / "tap.mf4",
        selected=(SelectedMeasurement(name="EngSpd"),),
    )


def test_sample_tap_receives_raw_backend_batches(tmp_path):
    seen = []
    ctrl = CaptureController(
        _tap_config(tmp_path), FakeRecorderBackend(), sample_tap=seen.append
    )
    ctrl.start()
    deadline = time.monotonic() + 2.0
    while not seen and time.monotonic() < deadline:
        ctrl.poll_step()
        time.sleep(0.02)
    ctrl.stop()
    assert seen, "tap never fired"
    channel, ts, value = seen[0][0]
    assert channel == "EngSpd"
    assert isinstance(ts, float) and isinstance(value, float)


def test_sample_tap_exception_does_not_kill_capture(tmp_path):
    def _boom(_batch):
        raise RuntimeError("live view died")

    ctrl = CaptureController(
        _tap_config(tmp_path), FakeRecorderBackend(), sample_tap=_boom
    )
    ctrl.start()
    deadline = time.monotonic() + 2.0
    while ctrl.writer.write_count == 0 and time.monotonic() < deadline:
        ctrl.poll_step()
        time.sleep(0.02)
    summary = ctrl.stop()
    assert summary.write_count > 0, "capture must survive a raising tap"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_acquisition_controller.py -k sample_tap -v`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'sample_tap'`

- [ ] **Step 3: 实现**

`controller.py` `__init__` 签名追加（放 `clock` 之后）：

```python
        clock: Callable[[], float] = time.monotonic,
        sample_tap: Callable[[list[tuple[str, float, float]]], None] | None = None,
    ) -> None:
```

`__init__` 体内追加 `self._sample_tap = sample_tap`。

`poll_step` 在 `new_samples = self._backend.poll()` 之后、入 ring 循环之前插入：

```python
        if new_samples and self._sample_tap is not None:
            try:
                self._sample_tap(new_samples)
            except Exception:  # noqa: BLE001 — live-view tap must never kill capture
                logger.exception("sample_tap raised; capture continues")
```

- [ ] **Step 4: 跑测试确认通过（含既有 controller 用例零回归）**

Run: `.venv/bin/python -m pytest tests/test_acquisition_controller.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_capture/controller.py tests/test_acquisition_controller.py
git commit -m "feat(acquisition): CaptureController optional sample_tap for live view"
```

---

### Task 5: CaptureSessionMixin（会话构造/命名/拆除/恢复）

**Files:**
- Create: `mf4_analyzer/acquisition_ui/main_window/_capture_session_mixin.py`
- Modify: `mf4_analyzer/acquisition_ui/main_window/window.py:121`（类基列表加 mixin）
- Test: `tests/acquisition_ui/test_capture_session.py`（新建，本任务先测纯构造逻辑）

**Interfaces:**
- Consumes: Task 4 的 `sample_tap`；`self._left_pane.current_selection()`、
  `self._output_dir_label`、`self._owns_vector_backend`、`self._transport_config`、
  `self._ring`、`self._stop_backend_best_effort`、`self.set_capture_controller`
  （均为 CockpitMainWindow 既有属性/方法）。
- Produces: 实例方法 `_begin_capture_session() -> bool`、
  `_teardown_capture_session() -> None`、`_resume_idle_stream() -> None`、
  `_next_output_path() -> Path`、`_on_capture_samples(samples: list) -> None`
  ——Task 6 接线消费。

- [ ] **Step 1: 写失败测试**

`tests/acquisition_ui/test_capture_session.py`：

```python
"""Capture-session lifecycle: real CaptureController from the record button."""
from pathlib import Path

import pytest

from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow


@pytest.fixture
def cockpit(qtbot, tmp_path):
    window = CockpitMainWindow(allow_fake_backend=True)
    qtbot.addWidget(window)
    window._output_dir_label = str(tmp_path / "runs")
    return window


def test_next_output_path_is_timestamped_and_unique(cockpit):
    p1 = cockpit._next_output_path()
    assert p1.suffix == ".mf4"
    assert p1.name.startswith("capture_")
    assert p1.parent.is_dir()
    p1.touch()
    p2 = cockpit._next_output_path()
    assert p2 != p1
    assert p2.parent == p1.parent


def test_begin_capture_session_builds_controller_demo_fallback(cockpit):
    # demo：左栏无选择 → DemoSignal 兜底
    assert cockpit._begin_capture_session() is True
    ctrl = cockpit._capture_controller
    assert ctrl is not None
    assert ctrl.running
    assert ctrl.config.selected_names == ("DemoSignal",)
    assert ctrl.config.backend == "fake"
    cockpit._teardown_capture_session()
    assert cockpit._capture_controller is None


def test_begin_capture_session_respects_injected_controller(cockpit):
    sentinel = object()
    cockpit.set_capture_controller(sentinel)
    assert cockpit._begin_capture_session() is True
    assert cockpit._capture_controller is sentinel  # 注入契约优先


def test_begin_capture_session_refuses_empty_selection_when_not_demo(qtbot, tmp_path):
    window = CockpitMainWindow(allow_fake_backend=False)
    qtbot.addWidget(window)
    window._output_dir_label = str(tmp_path)
    assert window._begin_capture_session() is False
    assert window._capture_controller is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_capture_session.py -v`
Expected: FAIL with `AttributeError: ... has no attribute '_next_output_path'`

- [ ] **Step 3: 实现 mixin**

新建 `mf4_analyzer/acquisition_ui/main_window/_capture_session_mixin.py`：

```python
"""CaptureSessionMixin: real CaptureController lifecycle for CockpitMainWindow.

Closes the long-standing seam: the cockpit UI used to drive the backend
directly and never constructed a CaptureController, so the record button
produced no MF4 (only the CLI wrote files). This mixin owns controller
construction at record start, teardown after review close, and
idle-stream resume.

Sample shape contract everywhere: ``(channel_name, timestamp, value)``
(matches ``backends.poll()`` and ``Mf4Writer.append_batch``).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

from mf4_analyzer.acquisition_capture.backends import ReplayRecorderBackend
from mf4_analyzer.acquisition_capture.controller import CaptureController
from mf4_analyzer.acquisition_capture.session import (
    SelectedMeasurement,
    SessionConfig,
)
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig

logger = logging.getLogger(__name__)


class CaptureSessionMixin:
    """Domain mixin: capture-session lifecycle.

    All methods become CockpitMainWindow instance methods and may only
    reference ``self.*`` attributes set in ``CockpitMainWindow.__init__``.
    """

    def _next_output_path(self) -> Path:
        out_dir = Path(self._output_dir_label).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = out_dir / f"capture_{stamp}.mf4"
        seq = 1
        while candidate.exists():
            candidate = out_dir / f"capture_{stamp}_{seq}.mf4"
            seq += 1
        return candidate

    def _capture_backend_kind(self) -> str:
        if self._owns_vector_backend:
            return "vector"
        if isinstance(self._backend, ReplayRecorderBackend):
            return "replay"
        return "fake"

    def _build_session_config(self) -> SessionConfig:
        selection = (
            tuple(self._left_pane.current_selection())
            if hasattr(self, "_left_pane")
            else ()
        )
        if not selection and self._allow_fake_backend:
            # Mirrors _begin_connection_attempt's demo seed.
            selection = (SelectedMeasurement(name="DemoSignal"),)
        return SessionConfig(
            output_mf4=self._next_output_path(),
            selected=selection,
            backend=self._capture_backend_kind(),
            transport=self._transport_config or TransportConfig(),
        )

    def _begin_capture_session(self) -> bool:
        """Construct + start the real CaptureController.

        Returns False (reason on the status bar) when the session cannot
        start; caller stays in ConnectedIdle. A test-injected controller
        (``set_capture_controller``) short-circuits to True — the
        injection contract owns the pipeline in that case.
        """
        if self._capture_controller is not None:
            return True
        try:
            config = self._build_session_config()
        except ValueError as exc:
            self._status.showMessage(f"无法开始录制: {exc}")
            return False
        # The idle live stream started the backend at connect time;
        # controller.start() calls backend.start(config.selected) itself
        # (Vector DAQ lists are allocated per-start from the recording
        # selection), so stop the idle stream first.
        self._stop_backend_best_effort(self._backend)
        # Discard idle-stream leftovers: the UI ring is shared for the
        # watermark wiring, and pre-record samples must never reach the
        # writer.
        self._ring.drain()
        controller = CaptureController(
            config,
            self._backend,
            ring=self._ring,
            sample_tap=self._on_capture_samples,
        )
        try:
            controller.start()
        except Exception as exc:  # noqa: BLE001 — surface, stay idle
            logger.exception("capture session start failed")
            self._status.showMessage(f"无法开始录制: {exc}")
            self._resume_idle_stream()
            return False
        self.set_capture_controller(controller)
        self._status.showMessage(f"录制中 → {config.output_mf4}")
        return True

    def _on_capture_samples(self, samples: list) -> None:
        """sample_tap sink: feed live cards + rx bookkeeping."""
        now = time.monotonic()
        if samples:
            if self._first_frame_ts is None:
                self._first_frame_ts = now
            self._fake_last_rx_monotonic = now
            self._cumulative_rx_count += len(samples)
        for channel, ts, value in samples:
            self._center.push_sample(channel, ts, value)

    def _teardown_capture_session(self) -> None:
        self.set_capture_controller(None)
        self._fake_rec_state = "off"

    def _resume_idle_stream(self) -> None:
        """controller.stop() stopped the backend; restart it so
        ConnectedIdle keeps streaming live cards. Best-effort."""
        selection = (
            list(self._left_pane.current_selection())
            if hasattr(self, "_left_pane")
            else []
        )
        if not selection:
            selection = [SelectedMeasurement(name="DemoSignal")]
        try:
            self._backend.start(selection)
        except Exception as exc:  # noqa: BLE001 — best-effort resume
            logger.warning("idle stream resume failed: %s", exc)
            self._status.showMessage(f"实时流恢复失败: {exc}")
```

`window.py:121` 类声明改为（引入放文件顶部 import 区，与其他 mixin 并列）：

```python
from ._capture_session_mixin import CaptureSessionMixin
```

```python
class CockpitMainWindow(
    ToolbarMixin,
    ConnectionMixin,
    PollingMixin,
    SettingsMixin,
    CaptureSessionMixin,
    QMainWindow,
):
```

注意 `test_begin_capture_session_refuses_empty_selection_when_not_demo`：
非 demo + 空选择时 `_build_session_config` 抛
`SessionConfig.selected must contain at least one measurement`
（`session.py:85`），被 except 捕获 → return False。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_capture_session.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/main_window/_capture_session_mixin.py mf4_analyzer/acquisition_ui/main_window/window.py tests/acquisition_ui/test_capture_session.py
git commit -m "feat(acquisition): CaptureSessionMixin owns real controller lifecycle"
```

---

### Task 6: 接线录制/轮询/review-close + e2e

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/main_window/window.py:519-534`（`_start_recording`）
- Modify: `mf4_analyzer/acquisition_ui/main_window/window.py:584-603`（`_on_review_modal_closed`）
- Modify: `mf4_analyzer/acquisition_ui/main_window/_polling_mixin.py:80-107`（`_poll_live`）
- Test: `tests/acquisition_ui/test_capture_session.py`（追加 e2e 用例）

**Interfaces:**
- Consumes: Task 5 的 `_begin_capture_session/_teardown_capture_session/_resume_idle_stream`；
  Task 4 的 tap（已在 mixin 内）。
- Produces: 无新公共接口；行为变化=录制写真 MF4。

- [ ] **Step 1: 写失败 e2e 测试**（追加到 `tests/acquisition_ui/test_capture_session.py`）

```python
import time

from mf4_analyzer.acquisition_ui.state import CockpitState
from mf4_analyzer.io.loader import DataLoader


def _pump(window, qtbot, predicate, timeout_s=8.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        window._poll_live()
        window._poll_health()
        qtbot.wait(20)
        if predicate():
            return
    raise AssertionError("timed out waiting for cockpit condition")


def test_record_stop_review_writes_real_mf4(cockpit, qtbot):
    w = cockpit
    w._on_main_button()  # 连接 ECU
    _pump(w, qtbot, lambda: w._state_machine.state == CockpitState.CONNECTED_IDLE)

    w._on_main_button()  # ● 采集
    assert w._state_machine.state == CockpitState.RECORDING
    assert w._capture_controller is not None
    _pump(w, qtbot, lambda: w._capture_controller.writer.write_count > 0)

    w._on_main_button()  # ■ Stop & 复盘
    assert w._last_stop_result is not None
    mf4 = Path(w._last_stop_result.summary.output_mf4)
    assert mf4.exists()
    assert mf4.with_suffix(".session_summary.json").exists()
    assert mf4.with_suffix(".preflight.json").exists()

    # 通道命名契约：写出的 MF4 可回读且含选中的通道名
    _df, channels, _units = DataLoader.load_mf4(mf4)
    assert "DemoSignal" in channels

    # review 关闭 → 回 idle，controller 拆除，空闲流恢复
    assert w._state_machine.state == CockpitState.REVIEW_MODAL
    w._review_modal.reject()
    qtbot.wait(50)
    assert w._state_machine.state == CockpitState.CONNECTED_IDLE
    assert w._capture_controller is None


def test_second_session_produces_distinct_file(cockpit, qtbot):
    w = cockpit
    w._on_main_button()
    _pump(w, qtbot, lambda: w._state_machine.state == CockpitState.CONNECTED_IDLE)

    outputs = []
    for _ in range(2):
        w._on_main_button()  # record
        _pump(w, qtbot, lambda: w._capture_controller.writer.write_count > 0)
        w._on_main_button()  # stop
        outputs.append(w.last_session_summary.output_mf4)
        w._review_modal.reject()
        qtbot.wait(50)
        assert w._state_machine.state == CockpitState.CONNECTED_IDLE

    assert outputs[0] != outputs[1]
    assert all(Path(p).exists() for p in outputs)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_capture_session.py -k "real_mf4 or distinct" -v`
Expected: FAIL（`_capture_controller is None`——录制未构造 controller）

- [ ] **Step 3: 改 `_start_recording`**（window.py:519-534）

在健康红拦截之后、状态翻转之前插入会话构造：

```python
    def _start_recording(self) -> None:
        # Spec: red health disables record. The button enabled state
        # already enforces this — defensive double-check here.
        if not self._main_btn.isEnabled():
            return
        levels = self._health_strip.current_levels()
        if any(level == "red" for level in levels.values()):
            return
        if not self._begin_capture_session():
            return  # 原因已上状态栏；留在 ConnectedIdle
        self._rec_start_ts = time.monotonic()
        self._fake_rec_state = "recording"
        self._cumulative_rx_count = 0
        self._cumulative_dropped = 0
        # Re-arm the dropped-frame prompt for the new session (B5).
        self._dropped_prompt_last_ts = None
        self._dropped_prompt_last_count = 0
        self._state_machine.request_start_recording()
```

- [ ] **Step 4: 改 `_poll_live`**（_polling_mixin.py:80-107）

录制中走 controller 管线；空闲路径原样保留，只修元组次序：

```python
    def _poll_live(self) -> None:
        controller = self._capture_controller
        if (
            controller is not None
            and self._state_machine.state == CockpitState.RECORDING
            and hasattr(controller, "poll_step")
        ):
            self._poll_live_recording(controller)
            return
        try:
            samples = self._backend.poll()
        except Exception:
            samples = []
        if samples:
            if self._first_frame_ts is None:
                self._first_frame_ts = time.monotonic()
            self._fake_last_rx_monotonic = time.monotonic()
        for channel, ts, value in samples:
            # Push into ring buffer for watermark accounting. Canonical
            # sample shape is (channel, ts, value) — the ring is shared
            # with the CaptureController during recording, so the shape
            # must match Mf4Writer.append_batch.
            self._ring.put((channel, ts, value))
            self._center.push_sample(channel, ts, value)
        # Repaint sparklines.
        self._center.refresh_all(now_ts=time.monotonic())
        # Update cumulative counters.
        self._cumulative_rx_count += len(samples)
        self._cumulative_dropped = self._ring.dropped_frames
        self._update_status_bar()
        if (
            self._state_machine.state == CockpitState.RECORDING
            and self._cumulative_dropped > thresholds.DROPPED_FRAMES_PROMPT_TOTAL
            and self._dropped_prompt_can_fire()
        ):
            self._show_dropped_frames_prompt()

    def _poll_live_recording(self, controller) -> None:
        """Recording path: the controller owns backend→ring→writer;
        live cards are fed through its sample_tap."""
        try:
            controller.poll_step()
        except Exception as exc:  # noqa: BLE001 — writer errors included
            logger.exception("controller poll_step failed")
            self._status.showMessage(f"录制轮询失败: {exc}")
        self._cumulative_dropped = self._ring.dropped_frames
        self._center.refresh_all(now_ts=time.monotonic())
        self._update_status_bar()
        if not controller.running:
            # Controller auto-stopped itself (sustained red ring, writer
            # error, duration cap) — run the canonical stop sequence so
            # the review modal opens with real sidecars.
            self.request_stop_and_review(
                auto_stop=bool(getattr(controller, "auto_stopped", False))
            )
            return
        if (
            self._cumulative_dropped > thresholds.DROPPED_FRAMES_PROMPT_TOTAL
            and self._dropped_prompt_can_fire()
        ):
            self._show_dropped_frames_prompt()
```

`hasattr(controller, "poll_step")` 守卫：既有测试注入的 spy/mock 不一定有
poll_step；没有就照旧走空闲路径，保持注入契约。

- [ ] **Step 5: 改 `_on_review_modal_closed`**（window.py:584-603）

在 `request_review_close` 的 try/except 之后追加：

```python
        if self._capture_controller is not None:
            self._teardown_capture_session()
            self._resume_idle_stream()
```

- [ ] **Step 6: 跑新测试 + 全量 acquisition UI 套件**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_capture_session.py -v`
Expected: 全 PASS

Run: `.venv/bin/python -m pytest tests/acquisition_ui -q`
Expected: 可能有少量既有用例失败——**只允许**这一类：曾假设"无管线也能进
RECORDING"的用例（无注入 controller、无 allow_fake_backend、无选择）。
逐个修复：给测试窗口加 `allow_fake_backend=True`，或注入 spy controller
（`set_capture_controller`）。每个被修改的测试在 commit message 里列一行原因。
若失败超出此类，停下排查实现而不是改测试。

- [ ] **Step 7: 跑 capture 核心套件回归**

Run: `.venv/bin/python -m pytest tests/test_acquisition_controller.py tests/test_acquisition_capture_writer.py tests/test_acquisition_backends.py -q`
Expected: 全 PASS

- [ ] **Step 8: Commit**

```bash
git add mf4_analyzer/acquisition_ui/main_window/window.py mf4_analyzer/acquisition_ui/main_window/_polling_mixin.py tests/acquisition_ui/
git commit -m "feat(acquisition): record button drives real CaptureController and writes MF4"
```

---

### Task 7: 三击入口配置持久化 + A2L 记忆回灌

**Files:**
- Modify: `mf4_analyzer/acquisition_capture/config_store.py`（新增 `save_a2l_path`）
- Modify: `mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py`
  （`apply_a2l_path` 尾部 + `_hydrate_from_config_path` 尾部）
- Modify: `mf4_analyzer/ui/main_window/window.py:1702-1718`（`open_acquisition_cockpit`）
- Test: `tests/test_acquisition_config_store.py`（追加）、
  `tests/acquisition_ui/test_config_path_persistence.py`（追加）

**Interfaces:**
- Produces: `save_a2l_path(a2l_path: Path | str, *, config_path: Path) -> None`
  ——read-modify-write，把 `a2l_path` 写入 yaml 并置 `pinned=True`。
- Consumes: `load_or_default`（config_store.py:98）、`_write_config_file`
  （config_store.py:273）、schema 键 `a2l_path`（ALLOWED_TOP_LEVEL 已含，无需升版）。

- [ ] **Step 1: 写失败测试（config_store 层）**，追加到 `tests/test_acquisition_config_store.py`：

```python
from mf4_analyzer.acquisition_capture.config_store import (
    load_or_default,
    save_a2l_path,
)


def test_save_a2l_path_round_trip(tmp_path):
    cfg = tmp_path / "acquisition_config.yaml"
    save_a2l_path(tmp_path / "demo.a2l", config_path=cfg)
    store = load_or_default(project_root=tmp_path, cli_config_path=cfg)
    assert store.a2l_path == str(tmp_path / "demo.a2l")
    assert store.pinned is True


def test_save_a2l_path_preserves_existing_transport(tmp_path):
    from mf4_analyzer.acquisition_capture.config_store import save_transport
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig

    cfg = tmp_path / "acquisition_config.yaml"
    save_transport(TransportConfig(channel=1), config_path=cfg)
    save_a2l_path(tmp_path / "demo.a2l", config_path=cfg)
    store = load_or_default(project_root=tmp_path, cli_config_path=cfg)
    assert store.transport.channel == 1
    assert store.a2l_path == str(tmp_path / "demo.a2l")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_acquisition_config_store.py -k a2l_path -v`
Expected: FAIL with ImportError（`save_a2l_path` 不存在）

- [ ] **Step 3: 实现 `save_a2l_path`**（放在 `save_transport` 之后，
结构完全镜像 `save_transport`（config_store.py:218-253）的读-改-写与错误语义）：

```python
def save_a2l_path(
    a2l_path: Path | str,
    *,
    config_path: Path,
) -> None:
    """Persist the last successfully applied A2L path.

    The cockpit rehydrates it on next launch (spec
    2026-07-06-cockpit-live-capture-and-persistence §C2). Read-modify-
    write mirroring ``save_transport`` so favorites/transport survive.
    """
    config_path = Path(config_path)
    store = load_or_default(
        project_root=config_path.parent,
        cli_config_path=config_path,
    )
    updated = dataclasses.replace(
        store, a2l_path=str(a2l_path), pinned=True
    )
    _write_config_file(config_path, updated)
```

（若 `ConfigStore` 非 frozen dataclass 或 `save_transport` 用别的更新方式，
以 `save_transport` 的既有写法为准，保持两函数结构一致。文件顶部按需
`import dataclasses`。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_acquisition_config_store.py -v`
Expected: 全 PASS

- [ ] **Step 5: 写失败测试（UI 层持久化 + 回灌）**，追加到
`tests/acquisition_ui/test_config_path_persistence.py`：

```python
from pathlib import Path
from types import SimpleNamespace

from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow


def _fake_summary(a2l_path):
    m = SimpleNamespace(
        name="EngSpd", unit="rpm", address=0x1000,
        available_events=("event_10ms",),
    )
    return SimpleNamespace(
        path=str(a2l_path), total_measurements=1, measurements=[m],
        event_capacity={"event_10ms": 1}, measurement_events={},
        a2l_has_daq_events=True,
    )


def _stub_a2l_chain(window, monkeypatch, a2l_path):
    monkeypatch.setattr(
        "can_logger.p0.ifdata_xcp.parse_ifdata_xcp_file",
        lambda _p: (object(),),
    )
    window._load_measurement_summary = (
        lambda _p: (_fake_summary(a2l_path), None)
    )


def test_apply_a2l_persists_and_rehydrates(qtbot, tmp_path, monkeypatch):
    cfg = tmp_path / "acquisition_config.yaml"
    a2l = tmp_path / "demo.a2l"
    a2l.write_text("stubbed", encoding="utf-8")

    w1 = CockpitMainWindow(config_path=cfg, allow_fake_backend=True)
    qtbot.addWidget(w1)
    _stub_a2l_chain(w1, monkeypatch, a2l)
    w1.apply_a2l_path(a2l)
    assert str(a2l) in cfg.read_text(encoding="utf-8")

    # 第二个窗口：hydrate 应经 singleShot 自动 apply 同一 A2L
    seen = []
    w2 = CockpitMainWindow(config_path=cfg, allow_fake_backend=True)
    qtbot.addWidget(w2)
    w2.apply_a2l_path = lambda p: seen.append(Path(p))
    qtbot.wait(80)  # 让 singleShot(0) 执行
    assert seen == [a2l]


def test_hydrate_skips_missing_a2l(qtbot, tmp_path):
    cfg = tmp_path / "acquisition_config.yaml"
    from mf4_analyzer.acquisition_capture.config_store import save_a2l_path

    save_a2l_path(tmp_path / "gone.a2l", config_path=cfg)
    seen = []
    w = CockpitMainWindow(config_path=cfg, allow_fake_backend=True)
    qtbot.addWidget(w)
    w.apply_a2l_path = lambda p: seen.append(p)
    qtbot.wait(80)
    assert seen == []  # 文件不存在 → 不 apply，仅状态栏提示
```

- [ ] **Step 6: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_config_path_persistence.py -k "persists or missing_a2l" -v`
Expected: FAIL

- [ ] **Step 7: 实现 UI 侧**

`_settings_mixin.py` `apply_a2l_path` 成功路径末尾（`self._status.showMessage(
f"A2L 已加载：..."` 之后）追加 `self._persist_a2l_path(a2l_path)`，并新增方法：

```python
    def _persist_a2l_path(self, a2l_path: Path) -> None:
        if self._config_path is None:
            return
        try:
            from mf4_analyzer.acquisition_capture.config_store import save_a2l_path

            save_a2l_path(a2l_path, config_path=self._config_path)
        except Exception as exc:  # noqa: BLE001 — persistence must not break A2L load
            self._status.showMessage(f"A2L 路径持久化失败: {exc}")
```

`_hydrate_from_config_path`（_settings_mixin.py:108-151）末尾追加：

```python
        stored_a2l = getattr(store, "a2l_path", None)
        if stored_a2l:
            a2l = Path(stored_a2l)
            if a2l.exists():
                # Defer past __init__ so the window paints before the
                # ~1.5s A2L parse (measured on the real 1.5MB A2L).
                QTimer.singleShot(0, lambda: self.apply_a2l_path(a2l))
            else:
                self._status.showMessage(f"上次的 A2L 已不存在: {a2l}")
```

（`QTimer` 从 `PyQt5.QtCore` import，加到该文件 import 区。）

`mf4_analyzer/ui/main_window/window.py` `open_acquisition_cockpit`（:1702-1718）
的 `cockpit = CockpitMainWindow()` 改为：

```python
        from mf4_analyzer.acquisition_capture.config_store import (
            CONFIG_FILENAME,
            default_recent_path,
        )

        config_path = default_recent_path().parent / CONFIG_FILENAME
        cockpit = CockpitMainWindow(config_path=config_path)
```

（即 `~/.acquisition-cockpit/acquisition_config.yaml`，与 recent.json 同目录。）

- [ ] **Step 8: 跑测试确认通过 + 相关套件回归**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_config_path_persistence.py tests/test_acquisition_config_store.py tests/acquisition_ui/test_pick_a2l_populates_left_pane.py -v`
Expected: 全 PASS

Run: `.venv/bin/python -m pytest tests/ui/test_open_and_save_entry.py -q`（analyzer 侧
open_acquisition_cockpit 相关测试如有，在 tests/ui 下 grep `cockpit` 定位并跑）
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add mf4_analyzer/acquisition_capture/config_store.py mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py mf4_analyzer/ui/main_window/window.py tests/
git commit -m "feat(acquisition): persist transport+A2L across sessions for the logo entry"
```

---

### Task 8: 后端身份 badge + 演示模式标题

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/main_window/window.py`（`__init__` 标题；
  `_build_ui` 状态栏处加 badge——用 `grep -n "_status" window.py | head` 定位
  `self._status` 赋值行，badge 紧随其后）
- Modify: `mf4_analyzer/acquisition_ui/main_window/_connection_mixin.py`
  （`_update_backend_badge` + 调用点）
- Modify: `mf4_analyzer/acquisition_ui/main_window/_capture_session_mixin.py`
  （`_teardown_capture_session` 末尾加 `self._update_backend_badge()`）
- Test: `tests/acquisition_ui/test_capture_session.py`（追加）

**Interfaces:**
- Produces: `_update_backend_badge() -> None`；`QLabel` objectName
  `cockpitBackendBadge`。

- [ ] **Step 1: 写失败测试**

```python
def test_demo_window_shows_backend_identity(cockpit):
    assert "演示模式" in cockpit.windowTitle()
    badge = cockpit.findChild(object, "cockpitBackendBadge")
    assert badge is not None
    assert "FAKE" in badge.text()


def test_production_window_title_has_no_demo_suffix(qtbot):
    w = CockpitMainWindow(allow_fake_backend=False)
    qtbot.addWidget(w)
    assert "演示模式" not in w.windowTitle()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_capture_session.py -k identity -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`window.py` `__init__` 内 `self._allow_fake_backend = bool(allow_fake_backend)`
（:210）之后追加：

```python
        if self._allow_fake_backend:
            self.setWindowTitle(self.windowTitle() + " · 演示模式")
```

`_build_ui` 中 `self._status` 创建之后追加：

```python
        self._backend_badge = QLabel(self)
        self._backend_badge.setObjectName("cockpitBackendBadge")
        self._status.addPermanentWidget(self._backend_badge)
        self._update_backend_badge()
```

（`QLabel` 已在 window.py import 区——若无则补。）

`_connection_mixin.py` 新增方法 + 三个调用点：

```python
    def _update_backend_badge(self) -> None:
        badge = getattr(self, "_backend_badge", None)
        if badge is None:
            return
        if self._owns_vector_backend:
            text = "后端: Vector"
        elif isinstance(self._backend, FakeRecorderBackend):
            text = "后端: FAKE·演示" if self._allow_fake_backend else "后端: FAKE"
        else:
            text = "后端: " + type(self._backend).__name__.replace(
                "RecorderBackend", ""
            )
        badge.setText(text)
```

调用点：
1. `_begin_connection_attempt` 中 `_maybe_swap_to_vector_backend` 调用返回后；
2. `_invalidate_owned_vector_backend` 末尾；
3. Task 5 的 `_teardown_capture_session` 末尾（`self._update_backend_badge()`）。

- [ ] **Step 4: 跑测试确认通过 + Commit**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_capture_session.py tests/acquisition_ui/test_record_backend_swap.py -q`
Expected: 全 PASS

```bash
git add mf4_analyzer/acquisition_ui/main_window/ tests/acquisition_ui/test_capture_session.py
git commit -m "feat(acquisition): backend identity badge + demo-mode title"
```

---

### Task 9: 误导性 Stage 注释清理

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/main_window/window.py`（约 20 处注释 +
  `_PlaceholderReviewModal` 标题/文案，:107-118）
- Modify: `mf4_analyzer/acquisition_ui/state.py:173-176`、
  `mf4_analyzer/acquisition_capture/writer.py:5,127` 等 grep 命中处
- Modify: 断言 "Stage 5" 文案的既有测试（grep 定位）

**Interfaces:** 无；注释与窗口标题文案，零行为变化。

- [ ] **Step 1: 盘点**

Run: `grep -rn "Stage 5\|Stage 8\|Stage 4" mf4_analyzer/acquisition_ui mf4_analyzer/acquisition_capture --include="*.py"`

逐条判断：描述"将来会做"但实际已实现的 → 改写为描述现状（例：
`# Stage 5 will own the real CaptureController` → 本计划 Task 5/6 已实现，改为
`# CaptureSessionMixin owns the controller lifecycle`）。
**保留**真实 deferred 的引用：`backends.py:642-656` `_read_dto_frame` 的
PR-4/硬件注释、spec 文件名引用（如 `docs/.../2026-05-15-...-spec.md` 字符串）。

- [ ] **Step 2: 改 `_PlaceholderReviewModal`**（window.py:107-118）

```python
        self.setWindowTitle("复盘（无会话数据）")
        ...
        layout.addWidget(QLabel("本次录制没有可复盘的会话数据。"))
        layout.addWidget(QLabel("点击「关闭」回到「已连接 · 待机」状态。"))
```

Run: `grep -rn "复盘 (Stage 5)\|Stage 5 将在此" tests/` 定位断言旧文案的测试并同步更新。

- [ ] **Step 3: 验证零行为变化**

Run: `.venv/bin/python -m pytest tests/acquisition_ui tests/test_acquisition_controller.py -q`
Expected: 全 PASS

Run: `grep -rn "Stage 5" mf4_analyzer/acquisition_ui --include="*.py" | grep -v "spec.md" | wc -l`
Expected: 0（或仅剩指向 spec 文档文件名的字符串）

- [ ] **Step 4: Commit**

```bash
git add mf4_analyzer/ tests/
git commit -m "docs(acquisition): retire stale Stage-N comments; retitle placeholder modal"
```

---

## 收尾验证（全部任务完成后）

- [ ] `.venv/bin/python -m pytest -q` — 全量（对照执行前 baseline，只允许既有失败）。
- [ ] 手动：`.venv/bin/python -m mf4_analyzer.acquisition_ui --demo` → 连接 →
  录制 10s → 停止 → review modal 显示真实统计 → 「在 Analyzer 打开」能加载曲线；
  `data/runs/` 出现 `capture_*.mf4` 三件套。
- [ ] 手动：主 app 三击 logo → cockpit 选真实 A2L
  （`/Users/donghang/Downloads/C0202_T04/A/ERD6_01_01_A0_C_02_02_T04_CANape_Aside.a2l`）
  → 左栏 323 measurements；关窗重开 → A2L 自动回灌。
