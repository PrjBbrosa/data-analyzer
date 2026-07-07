"""SettingsMixin: transport/settings/config/a2l/file-dialogs/status-bar for CockpitMainWindow."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.config_store import ConfigSchemaError
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog
from mf4_analyzer.acquisition_ui.state import CockpitState
from ._defs import (
    DROPPED_FRAMES_PROMPT_TEXT,
    DROPPED_FRAMES_PROMPT_TITLE,
)

logger = logging.getLogger(__name__)


class SettingsMixin:
    """Domain mixin: transport settings, config persistence, A2L, file dialogs,
    segment marker, status bar, and dropped-frame prompt.

    All methods become CockpitMainWindow instance methods.
    They may only reference ``self.*`` attributes set in
    ``CockpitMainWindow.__init__``.

    QMessageBox monkeypatch anchor:
    Tests patch ``mf4_analyzer.acquisition_ui.main_window.QMessageBox.open``.
    All QMessageBox construction in this mixin resolves the class via
    ``sys.modules`` at call time so patches applied to the package
    namespace are visible here.
    """

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------

    def set_transport(
        self,
        transport: TransportConfig | None,
        *,
        device_model: str | None = None,
    ) -> None:
        self._invalidate_owned_vector_backend()
        self._transport_config = transport
        if transport is None:
            self._transport_chip.setText("传输未配置")
            self._transport_chip.setToolTip("打开传输设置")
            self._set_visual_property(
                self._transport_chip,
                "transportState",
                "unconfigured",
            )
            return

        fd_label = "CAN-FD" if transport.can_fd else "CAN"
        rate = transport.bitrate // 1000
        prefix = f"{device_model} · " if device_model else "传输 · "
        text = (
            f"{prefix}App={transport.app_name} · Ch={transport.channel} · "
            f"{fd_label} {rate}k"
        )
        self._transport_chip.setText(text)
        self._transport_chip.setToolTip(text)
        self._set_visual_property(self._transport_chip, "transportState", "configured")
        self._recompute_toolbar_overflow()
        # Force a fresh health poll on the next event-loop tick so the
        # HW chip / probe results reflect the new transport without
        # waiting up to HEALTH_POLL_INTERVAL_S (otherwise the user sees
        # the previous transport's stale verdict for ~200 ms).
        if getattr(self, "_health_timer", None) is not None:
            QTimer.singleShot(0, self._poll_health)

    def _open_settings_dialog(self, *, initial_tab: str | None = None) -> None:
        if self._settings_dialog is not None:
            if initial_tab is not None:
                self._settings_dialog.open_tab(initial_tab)
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dialog = SettingsDialog(
            self,
            transport=self._transport_config or TransportConfig(),
            ifdata=self._ifdata_xcp,
        )
        if initial_tab is not None:
            dialog.open_tab(initial_tab)
        dialog.settings_saved.connect(self._on_settings_changed)
        dialog.settings_reset.connect(self._on_settings_reset)
        dialog.finished.connect(lambda _result: setattr(self, "_settings_dialog", None))
        self._settings_dialog = dialog
        dialog.open()

    def _on_settings_changed(self, _values: dict[str, float | int]) -> None:
        if self._settings_dialog is not None:
            transport = self._settings_dialog.current_transport()
            self.set_transport(transport)
            self._persist_transport(transport)
        self._apply_threshold_runtime_refresh()
        self._status.showMessage("设置已保存")

    def _hydrate_from_config_path(self) -> None:
        """T1-6: pull Transport from ``acquisition_config.yaml``.

        ``self._config_path`` is the yaml file (typically
        ``<project_root>/acquisition_config.yaml``). When the file does
        not exist yet we still wire :meth:`LeftPane.set_config_path` so
        the pane keeps the same settings context, but we leave
        ``self._transport_config`` at ``None`` so the toolbar chip keeps
        showing "传输未配置".
        """

        if self._config_path is None:
            return

        try:
            from mf4_analyzer.acquisition_capture.config_store import (
                load_or_default,
            )

            store = load_or_default(
                project_root=self._config_path.parent,
                cli_config_path=self._config_path,
            )
        except ConfigSchemaError as exc:
            self._status.showMessage(f"配置文件加载失败: {exc}")
            return
        except Exception as exc:  # noqa: BLE001 - keep UI responsive
            self._status.showMessage(f"配置文件读取失败: {exc}")
            return

        # Keep the left pane bound to the same config path even when
        # feature-specific controls such as favorites are hidden.
        if hasattr(self, "_left_pane"):
            self._left_pane.set_config_path(self._config_path)

        # Only hydrate transport when an on-disk config actually existed.
        # ``pinned=False`` means we got the in-memory default — pushing
        # that would falsely flip the chip to "configured".
        if store.pinned:
            self.set_transport(store.transport)
            self._status.showMessage(
                f"已加载配置：{self._config_path.name}"
            )
            stored_a2l = getattr(store, "a2l_path", None)
            if stored_a2l:
                a2l = Path(stored_a2l)
                if a2l.exists():
                    # Defer until after __init__ so the window can paint
                    # before the native-parser subprocess work starts.
                    QTimer.singleShot(0, lambda: self.apply_a2l_path(a2l))
                else:
                    self._status.showMessage(f"上次的 A2L 已不存在: {a2l}")

    def _persist_transport(self, transport: TransportConfig) -> None:
        """Write the new transport block back to ``self._config_path``.

        No-op when ``self._config_path`` is ``None`` (tests, ephemeral
        instances). Errors hit the status bar so the operator notices —
        a silent failure here would let them think Vector flags were
        saved when they weren't.
        """

        if self._config_path is None:
            return

        try:
            from mf4_analyzer.acquisition_capture.config_store import (
                save_transport,
            )

            save_transport(transport, config_path=self._config_path)
        except Exception as exc:  # noqa: BLE001 - keep UI responsive
            self._status.showMessage(f"配置保存失败: {exc}")

    def _persist_a2l_path(self, a2l_path: Path) -> None:
        """Write the last successfully loaded A2L path to config."""

        if self._config_path is None:
            return

        try:
            from mf4_analyzer.acquisition_capture.config_store import (
                save_a2l_path,
            )

            save_a2l_path(a2l_path, config_path=self._config_path)
        except Exception as exc:  # noqa: BLE001 - persistence must not break load
            self._status.showMessage(f"A2L 路径持久化失败: {exc}")

    def _on_settings_reset(self) -> None:
        self._apply_threshold_runtime_refresh()
        self._status.showMessage("设置已还原默认")

    def _apply_threshold_runtime_refresh(self) -> None:
        self._health_timer.setInterval(
            int(thresholds.HEALTH_POLL_INTERVAL_S * 1000)
        )
        self._update_record_button_enabled()
        if self._state_machine.state == CockpitState.CONNECTED_IDLE:
            self._refresh_idle_right_panel()
        elif self._state_machine.state == CockpitState.RECORDING:
            self._refresh_recording_right_panel()

    # ------------------------------------------------------------------
    # Segment marker + status bar
    # ------------------------------------------------------------------

    def _on_mark_segment(self) -> None:
        if self._state_machine.state != CockpitState.RECORDING:
            return
        if self._capture_controller is None:
            return
        label, ok = QInputDialog.getText(self, "标记一段", "标签（可选）:")
        self._capture_controller.mark_segment(label if ok else None)

    def _update_status_bar(self) -> None:
        if not hasattr(self, "_status"):
            return
        state = self._state_machine.state
        if state == CockpitState.DISCONNECTED:
            a2l_name = self._a2l_name or "未加载"
            self._status.showMessage(f"未连接 · A2L: {a2l_name}")
            return
        if state == CockpitState.CONNECTED_IDLE:
            self._status.showMessage(
                f"streaming · {self._event_rate_per_s()} evt/s"
            )
            return
        if state == CockpitState.RECORDING:
            elapsed = self._recording_elapsed_text()
            size_mb = self._recording_file_size_mb()
            size_part = f"{size_mb:.1f} MB" if size_mb > 0 else "缓冲中"
            self._status.showMessage(
                f"RECORDING · {elapsed} · {self._sample_count()} samples · "
                f"{size_part} · "
                f"drop {self._cumulative_dropped} · buf {self._ring.level_pct:.1f}%"
            )

    def _event_rate_per_s(self) -> int:
        if self._stream_start_ts is None:
            return 0
        elapsed = max(0.0, time.monotonic() - self._stream_start_ts)
        if elapsed <= 0:
            return 0
        return int(round(self._cumulative_rx_count / elapsed))

    def _recording_elapsed_text(self) -> str:
        if self._rec_start_ts is None:
            total = 0
        else:
            total = int(max(0.0, time.monotonic() - self._rec_start_ts))
        minutes, seconds = divmod(total, 60)
        return f"{minutes:02d}:{seconds:02d}"

    def _sample_count(self) -> int:
        if self._capture_controller is not None:
            try:
                return int(self._capture_controller.writer.write_count)
            except Exception:  # noqa: BLE001 - status bar must stay best-effort
                return int(self._cumulative_rx_count)
        return int(self._cumulative_rx_count)

    def _recording_file_size_mb(self) -> float:
        path: Path | None = None
        if self._capture_controller is not None:
            try:
                path = self._capture_controller.config.output_mf4
            except Exception:  # noqa: BLE001 - injected test controllers are partial
                path = None
        elif self._last_session_summary and self._last_session_summary.output_mf4:
            path = Path(self._last_session_summary.output_mf4)
        if path is None or not path.exists():
            return 0.0
        try:
            return path.stat().st_size / (1024.0 * 1024.0)
        except OSError:
            return 0.0

    # ------------------------------------------------------------------
    # File dialogs
    # ------------------------------------------------------------------

    def _on_pick_a2l(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 A2L 文件", "", "A2L (*.a2l);;All (*)"
        )
        if path:
            self.apply_a2l_path(Path(path))

    def apply_a2l_path(self, a2l_path: Path) -> None:
        """Load A2L summary + IF_DATA, refresh the left pane.

        Extracted from :meth:`_on_pick_a2l` so tests can drive A2L
        selection without faking ``QFileDialog`` and so non-dialog
        callers (e.g. a future "recall last A2L" path) reuse the same
        plumbing.

        T1-1 / T1-2: this is the spot that was missing the
        ``set_pool`` call. Without it, picking an A2L only updated the
        title chip and IF_DATA cache — the measurement list stayed
        empty.

        T2-2 / T2-3: on parse failure we now (a) show a
        managed window-modal warning so the operator can't miss it at the
        vehicle, and (b) treat the A2L load as an atomic transaction.
        IF_DATA and the measurement pool are committed only when both
        parse steps succeed. Any partial failure clears both so Settings
        Test Connection cannot mix a new transport block with stale
        measurements.
        """

        self._invalidate_owned_vector_backend()
        self._a2l_name = a2l_path.name
        self._set_selector_value(self._a2l_btn, "A2L", self._a2l_name)

        previous_ifdata = self._ifdata_xcp

        ifdata_error: str | None = None
        next_ifdata = None
        try:
            from can_logger.p0.ifdata_xcp import parse_ifdata_xcp_file

            blocks = parse_ifdata_xcp_file(a2l_path)
        except Exception as exc:  # noqa: BLE001 - file picker must stay responsive
            ifdata_error = str(exc)
            blocks = ()

        if blocks:
            next_ifdata = blocks[0]
        elif ifdata_error is None:
            ifdata_error = (
                "A2L 不含可用 IF_DATA XCP block（XCPplus-only ECU 或 "
                "transport 段缺失）"
            )

        summary, measurement_error = self._load_measurement_summary(a2l_path)

        # T2-2: surface failures via a modal so vehicle-side operators
        # don't miss them. Combine ifdata + measurement issues into one
        # dialog when both went bad (common: wrong filetype picked).
        problems: list[str] = []
        if ifdata_error is not None:
            problems.append(f"IF_DATA XCP：{ifdata_error}")
        if measurement_error is not None:
            problems.append(measurement_error)
        if problems and previous_ifdata is not None:
            problems.append(
                "上一次 A2L 的 IF_DATA 和 measurement pool 已被清空——"
                "重新选择 A2L 后再 Test Connection。"
            )
        if problems:
            self._ifdata_xcp = None
            self._left_pane.set_pool((), a2l_has_daq_events=False)
            self._status.showMessage(
                f"A2L 加载失败：{'; '.join(problems)}"
            )
            self._warn_a2l_load_problems(a2l_path, problems)
            return

        self._ifdata_xcp = next_ifdata
        self._left_pane.set_pool(
            summary.measurements,
            a2l_has_daq_events=summary.a2l_has_daq_events,
        )
        shown = len(summary.measurements)
        if shown == summary.total_measurements:
            self._status.showMessage(f"A2L 已加载：{shown} measurement")
        else:
            self._status.showMessage(
                f"A2L 已加载：{shown}/{summary.total_measurements} measurement"
            )
        self._persist_a2l_path(a2l_path)

    def _warn_a2l_load_problems(self, a2l_path: Path, problems: list[str]) -> None:
        """T2-2 toast: an operator-visible warning is the only thing
        that survives a noisy garage.

        We use a window-modal :class:`QMessageBox.open()` (non-blocking
        from the caller's perspective, but the operator can't dismiss
        the cockpit until they acknowledge). Static QMessageBox helpers
        are blocking and hang offscreen test runs, so we drive a managed
        instance instead.
        Tests stub this method via attribute assignment.
        """
        # Runtime sys.modules lookup so test patches on
        # mf4_analyzer.acquisition_ui.main_window.QMessageBox are visible.
        import sys as _sys
        _pkg = _sys.modules.get("mf4_analyzer.acquisition_ui.main_window")
        _QMessageBox = getattr(_pkg, "QMessageBox", None) if _pkg is not None else None
        if _QMessageBox is None:
            _QMessageBox = QMessageBox
        box = _QMessageBox(self)
        box.setIcon(_QMessageBox.Warning)
        box.setWindowTitle("A2L 加载警告")
        box.setText(
            f"{a2l_path.name}\n\n" + "\n".join(f"• {p}" for p in problems)
        )
        box.setWindowModality(Qt.WindowModal)
        # Keep a reference so the dialog isn't GC'd before the user
        # dismisses it. Replaces any prior dialog (operator only acts
        # on the most recent A2L pick anyway).
        self._a2l_warning_box = box
        if self.isVisible():
            box.open()

    def _load_measurement_summary(self, path: Path):
        """Load the measurement pool for the left pane.

        Returns ``(summary, error)``. The caller owns committing or
        clearing UI state so IF_DATA and the measurement pool cannot
        diverge.
        """

        try:
            from can_logger.p0.a2l_probe import load_measurement_summary

            return load_measurement_summary(str(path), limit=None), None
        except Exception as exc:  # noqa: BLE001 - same rationale as above
            return None, f"A2L measurement 解析失败：{exc}"

    def _on_pick_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", "")
        if path:
            self._output_dir_label = path
            self._set_selector_value(self._output_btn, "输出", self._output_dir_label)
            self._status.showMessage(f"输出目录: {path}")

    # ------------------------------------------------------------------
    # Dropped-frames prompt
    # ------------------------------------------------------------------

    def _dropped_prompt_can_fire(self) -> bool:
        if self._dropped_prompt_last_ts is None:
            return True
        elapsed = time.monotonic() - self._dropped_prompt_last_ts
        delta = self._cumulative_dropped - self._dropped_prompt_last_count
        return (
            elapsed >= self._DROPPED_PROMPT_REARM_S
            and delta >= self._DROPPED_PROMPT_REARM_DELTA
        )

    def _show_dropped_frames_prompt(self) -> None:
        self._dropped_prompt_last_ts = time.monotonic()
        self._dropped_prompt_last_count = self._cumulative_dropped
        # Runtime sys.modules lookup so test patches on
        # mf4_analyzer.acquisition_ui.main_window.QMessageBox are visible.
        import sys as _sys
        _pkg = _sys.modules.get("mf4_analyzer.acquisition_ui.main_window")
        _QMessageBox = getattr(_pkg, "QMessageBox", None) if _pkg is not None else None
        if _QMessageBox is None:
            _QMessageBox = QMessageBox
        box = _QMessageBox(self)
        box.setObjectName("droppedFramesPrompt")
        box.setIcon(_QMessageBox.Warning)
        box.setWindowTitle(DROPPED_FRAMES_PROMPT_TITLE)
        box.setText(DROPPED_FRAMES_PROMPT_TEXT)
        cont_btn = box.addButton("继续录制", _QMessageBox.AcceptRole)
        stop_btn = box.addButton("停止并复盘", _QMessageBox.DestructiveRole)
        # Use ``open`` to keep the prompt non-modal w.r.t. the
        # recording loop per spec ("stays inside the Recording state;
        # never auto-dismisses"). Under Windows offscreen Qt, opening a
        # QMessageBox for a hidden test window can access-violate; keep
        # the object inspectable but only paint it for a visible cockpit.
        if self.isVisible():
            box.open()
        # Wire the stop branch. ``继续录制`` is dismiss-only; we
        # just close the box (Qt's default ``buttonClicked`` slot).
        # ``停止并复盘`` runs the same stop/flush/finalize flow as the
        # toolbar Stop.
        def _on_dropped_prompt_button(btn) -> None:
            if btn is stop_btn:
                self.request_stop_and_review()
            # ``继续录制`` simply dismisses; the recording continues.

        box.buttonClicked.connect(_on_dropped_prompt_button)
        # Hold a reference so it isn't garbage-collected before the user
        # clicks. Also exposed for tests to assert presence.
        self._dropped_prompt = box
        self._dropped_prompt_continue_btn = cont_btn
        self._dropped_prompt_stop_btn = stop_btn

    # ------------------------------------------------------------------
    # Disk-free estimator
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_disk_free_bytes() -> int:
        """Return free-byte estimate for the output path's filesystem.

        The right panel needs a conservative number that clears the
        green threshold in demo/offscreen runs.
        """
        try:
            import shutil

            return int(shutil.disk_usage("/").free)
        except Exception:
            # Defensive: anything > green threshold so the demo isn't
            # red on environments without /.
            return thresholds.DISK_FREE_GREEN_MIN_BYTES * 2
