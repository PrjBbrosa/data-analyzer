"""Main-window adapter for directional SISO frequency-response analysis."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ...signal.frf import FrfParams, compute_frf
from ...signal.spectrogram import DEFAULT_TIME_JITTER_TOLERANCE
from ..time_xaxis import CHANNEL_MODE, CustomXAxisSpec
from .frf_coordinator import frf_compute_cache_params


@dataclass
class FrfPreflightError(ValueError):
    """A user/data issue that must be shown without starting a worker."""

    message: str

    def __str__(self) -> str:
        return self.message


class FrfMixin:
    """Collect pair intent, validate real timebases, dispatch, and render FRF."""

    _FRF_Y_PANELS = ("magnitude", "phase", "coherence")

    def _active_frf_state(self):
        manager = self.analysis_managers["frf"]
        state = manager.get(manager.active)
        page = self._analysis_page("frf")
        pane_idx = min(page.focused_index(), len(state.panes) - 1)
        return manager, state, page, pane_idx, state.panes[pane_idx]

    def _capture_frf_sources(self, state, pane_idx=None):
        page = self._analysis_page("frf")
        if pane_idx is None:
            pane_idx = page.focused_index()
        idx = min(int(pane_idx), len(state.panes) - 1)
        pane = state.panes[idx]
        input_source, output_source = self.inspector.frf_ctx.pair()
        pane.sources = []
        pane.input_source = tuple(input_source) if input_source else None
        pane.output_source = tuple(output_source) if output_source else None

    def _apply_frf_sources(self, state):
        page = self._analysis_page("frf")
        idx = min(page.focused_index(), len(state.panes) - 1)
        pane = state.panes[idx]
        ctx = self.inspector.frf_ctx
        old_input = ctx.combo_input.blockSignals(True)
        old_output = ctx.combo_output.blockSignals(True)
        try:
            ctx.set_input_source(pane.input_source)
            ctx.set_output_source(pane.output_source)
        finally:
            ctx.combo_output.blockSignals(old_output)
            ctx.combo_input.blockSignals(old_input)
        ctx._refresh_validation()

    def _capture_frf_canvas_ranges(self, state):
        page = self._analysis_page("frf")
        for pane_idx in range(min(page.pane_count(), len(state.panes))):
            pane = state.panes[pane_idx]
            canvas = page.pane_canvas(pane_idx)
            if not canvas.has_result():
                continue
            xlim = canvas.get_xlim()
            if xlim is not None:
                pane.xlim = tuple(float(value) for value in xlim)
            pane.ylims = {
                name: tuple(float(value) for value in limits)
                for name, limits in canvas.get_ylims().items()
                if name in self._FRF_Y_PANELS
            }
            pane.ylim = pane.ylims.get("magnitude")

    def _restore_frf_canvas_ranges(self, canvas, pane):
        if pane.xlim is not None:
            canvas.set_xlim(*pane.xlim)
        ylims = dict(pane.ylims or {})
        if not ylims and pane.ylim is not None:
            ylims["magnitude"] = pane.ylim
        for panel in self._FRF_Y_PANELS:
            limits = ylims.get(panel)
            if limits is not None:
                canvas.set_ylim(panel, *limits)

    def _capture_frf_time_range(self, state, pane_idx=None):
        page = self._analysis_page("frf")
        if pane_idx is None:
            pane_idx = page.focused_index()
        idx = min(int(pane_idx), len(state.panes) - 1)
        pane = state.panes[idx]
        mode = self.inspector.frf_ctx.range_mode()
        state.params["range_mode"] = mode
        if mode == "manual":
            pane.source_time_view_id = None
            pane.time_range = self._normalize_analysis_time_range(
                self.inspector.top.range_values()
            )
        elif mode == "full":
            pane.source_time_view_id = None
            pane.time_range = None

    def _apply_frf_time_range(self, state):
        page = self._analysis_page("frf")
        idx = min(page.focused_index(), len(state.panes) - 1)
        pane = state.panes[idx]
        mode = str(state.params.get("range_mode", "full"))
        self.inspector.frf_ctx.set_range_mode(mode)
        if mode == "manual" and pane.time_range is not None:
            self.inspector.top.set_range_from_span(*pane.time_range)

    def _mark_frf_pane_stale(self, state, pane_idx):
        manager = self.analysis_managers["frf"]
        if manager.get(manager.active) is not state:
            return
        page = self._analysis_page("frf")
        if 0 <= int(pane_idx) < page.pane_count():
            page.pane_canvas(int(pane_idx)).mark_stale()

    def _dirty_frf_pane(self, state, pane_idx, *, clear_effective=False):
        """Invalidate one pane's in-flight generation and stale its canvas."""

        idx = int(pane_idx)
        if not (0 <= idx < len(state.panes)):
            return
        if clear_effective:
            state.panes[idx].effective_time_range = None
        self._frf_coordinator.invalidate_pane(state.view_id, idx)
        self._mark_frf_pane_stale(state, idx)

    def _on_frf_pair_changed(self, input_source, output_source):
        if self._applying_analysis_view:
            return
        _manager, state, _page, pane_idx, pane = self._active_frf_state()
        pane.sources = []
        pane.input_source = tuple(input_source) if input_source else None
        pane.output_source = tuple(output_source) if output_source else None
        self.inspector.frf_ctx.set_validation_message("")
        self._dirty_frf_pane(state, pane_idx, clear_effective=True)

    def _on_frf_compute_params_changed(self, params):
        if self._applying_analysis_view:
            return
        _manager, state, _page, _pane_idx, _pane = self._active_frf_state()
        state.params.update(dict(params or {}))
        # Compute controls belong to the whole Analysis View, so both split
        # panes must reject any completion produced with the previous values.
        for pane_idx in range(len(state.panes)):
            self._dirty_frf_pane(state, pane_idx)

    def _on_frf_display_params_changed(self, params):
        if self._applying_analysis_view:
            return
        _manager, state, page, _pane_idx, _pane = self._active_frf_state()
        state.params.update(dict(params or {}))
        for idx in range(min(page.pane_count(), len(state.panes))):
            page.pane_canvas(idx).set_display_params(params)

    def _on_frf_range_mode_changed(self, mode):
        if self._applying_analysis_view:
            return
        _manager, state, _page, pane_idx, pane = self._active_frf_state()
        state.params["range_mode"] = str(mode)
        self.inspector.frf_ctx.set_validation_message("")
        if mode == "current_time":
            try:
                source_state, time_range = self._current_physical_time_view_range()
            except FrfPreflightError as issue:
                pane.source_time_view_id = None
                self.inspector.frf_ctx.set_validation_message(str(issue))
                self.toast(str(issue), "warning")
            else:
                pane.source_time_view_id = source_state.view_id
                pane.time_range = time_range
                if pane.input_source is not None and pane.output_source is not None:
                    try:
                        self._frf_pair_effective_range(
                            state, pane, lightweight=True
                        )
                    except FrfPreflightError as issue:
                        self.inspector.frf_ctx.set_validation_message(str(issue))
                        self.toast(str(issue), "warning")
        elif mode == "manual":
            pane.source_time_view_id = None
            pane.time_range = self._normalize_analysis_time_range(
                self.inspector.top.range_values()
            )
        else:
            pane.source_time_view_id = None
            pane.time_range = None
        self._dirty_frf_pane(state, pane_idx, clear_effective=True)

    def _on_frf_manual_time_range_edited(self, *_args):
        if (
            self._applying_analysis_view
            or self.chart_stack.current_mode() != "frf"
            or self.inspector.frf_ctx.range_mode() != "manual"
        ):
            return False
        _manager, state, _page, pane_idx, pane = self._active_frf_state()
        time_range = self._normalize_analysis_time_range(
            self.inspector.top.range_values()
        )
        old = self._normalize_analysis_time_range(pane.time_range)
        if (
            old is not None
            and time_range is not None
            and np.allclose(old, time_range, rtol=0.0, atol=1e-12)
        ):
            return False
        pane.time_range = time_range
        self._dirty_frf_pane(state, pane_idx, clear_effective=True)
        return True

    def _time_view_state_by_id(self, view_id):
        target = str(view_id or "")
        for state in self.view_manager.views:
            if state.view_id == target:
                return state
        return None

    def _current_physical_time_view_range(self):
        resolved = self._focused_time_view_state()
        if resolved is None:
            raise FrfPreflightError("没有可关联的时域 View")
        _idx, state = resolved
        spec = CustomXAxisSpec.from_axis_opts(
            (state.axis_opts or {}).get("x_axis")
        )
        if spec.mode == CHANNEL_MODE:
            raise FrfPreflightError(
                "当前时域横轴不是物理时间，无法作为 FRF 时间范围；"
                "请切回时间轴或手动输入秒范围。"
            )
        time_range = self._normalize_analysis_time_range(state.xlim)
        if time_range is None:
            canvas = self._canvas_for_view_index(resolved[0])
            if canvas is not None:
                time_range = self._normalize_analysis_time_range(
                    canvas.get_visible_xlim()
                )
        if time_range is None:
            raise FrfPreflightError("当前时域 View 没有有限、递增的可见时间范围")
        return state, time_range

    @staticmethod
    def _frf_validate_array_shapes(time, signal, role):
        if time.ndim != 1 or signal.ndim != 1:
            raise FrfPreflightError(f"{role}通道与时间轴必须是一维数组")
        if len(time) != len(signal):
            raise FrfPreflightError(f"{role}通道与真实时间轴长度不一致")

    @classmethod
    def _frf_validate_time_axis(cls, time, signal, fs, role):
        cls._frf_validate_array_shapes(time, signal, role)
        if len(time) < 2:
            raise FrfPreflightError(f"{role}通道样本不足")
        if not np.isfinite(time).all() or not np.isfinite(signal).all():
            raise FrfPreflightError(f"{role}通道或时间轴包含非有限值")
        differences = np.diff(time)
        if np.any(differences <= 0):
            raise FrfPreflightError(f"{role}真实时间轴必须严格递增")
        nominal_dt = 1.0 / fs
        jitter = float(np.max(np.abs(differences - nominal_dt)) / nominal_dt)
        if jitter > DEFAULT_TIME_JITTER_TOLERANCE:
            raise FrfPreflightError(
                f"{role}真实时间轴不均匀（相对抖动 {jitter:.6g}）"
            )

    def _frf_source_arrays(self, source, role):
        if source is None:
            raise FrfPreflightError(f"请选择{role}通道")
        fid, channel = (str(source[0]), str(source[1]))
        fd = self.files.get(fid)
        if fd is None or channel not in fd.data.columns:
            raise FrfPreflightError(f"{role}来源或通道已不可用")
        try:
            fs = float(fd.fs)
        except (TypeError, ValueError) as exc:
            raise FrfPreflightError(f"{role}采样率无效") from exc
        if not np.isfinite(fs) or fs <= 0:
            raise FrfPreflightError(f"{role}采样率必须大于 0")
        time_source = str(getattr(fd, "_time_source", "") or "").lower()
        time_values = getattr(fd, "time_array", None)
        if time_values is None or time_source == "generated":
            raise FrfPreflightError(
                "FRF 需要真实时间轴，不能使用缺失或自动生成的时间轴；"
                "请加载带物理时间列的来源。"
            )
        try:
            time = np.asarray(time_values, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise FrfPreflightError(f"{role}真实时间轴必须是一维数值数组") from exc
        raw_signal = fd.data[channel].to_numpy(copy=False)
        if np.iscomplexobj(raw_signal) or np.issubdtype(raw_signal.dtype, np.bool_):
            raise FrfPreflightError(f"{role}通道必须是实数数值")
        try:
            signal = np.asarray(raw_signal, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise FrfPreflightError(f"{role}通道必须是实数数值") from exc
        self._frf_validate_array_shapes(time, signal, role)
        unit = str((getattr(fd, "channel_units", None) or {}).get(channel, "") or "")
        return (fid, channel), fd, time, signal, fs, unit

    def _frf_requested_range(self, state, pane):
        mode = str(state.params.get("range_mode", "full"))
        if mode == "current_time":
            if pane.source_time_view_id is None:
                raise FrfPreflightError(
                    "关联的时域 View 已失效；请重新关联：选择『当前时域范围』。"
                )
            source_state = self._time_view_state_by_id(pane.source_time_view_id)
            if source_state is None:
                pane.source_time_view_id = None
                raise FrfPreflightError(
                    "关联的时域 View 已删除；请重新关联：选择『当前时域范围』。"
                )
            spec = CustomXAxisSpec.from_axis_opts(
                (source_state.axis_opts or {}).get("x_axis")
            )
            if spec.mode == CHANNEL_MODE:
                pane.source_time_view_id = None
                raise FrfPreflightError(
                    "关联的时域 View 已切换为自定义横轴；请切回物理时间后重新关联。"
                )
            if pane.time_range is None:
                pane.source_time_view_id = None
                raise FrfPreflightError(
                    "关联的时域范围快照缺失；请重新关联：选择『当前时域范围』。"
                )
            time_range = pane.time_range
        elif mode == "manual":
            time_range = pane.time_range
            if time_range is None:
                raise FrfPreflightError("请输入有限、递增的手动时间范围")
        elif mode == "full":
            pane.source_time_view_id = None
            time_range = None
        else:
            raise FrfPreflightError(f"未知 FRF 分析范围模式：{mode}")
        return self._normalize_analysis_time_range(time_range)

    def _frf_prepare_pair_samples(self, state, pane, *, validate_selected=True):
        """Read and validate the directional pair on one common time crop."""

        input_key, input_fd, input_time, input_values, input_fs, input_unit = (
            self._frf_source_arrays(pane.input_source, "输入")
        )
        output_key, output_fd, output_time, output_values, output_fs, output_unit = (
            self._frf_source_arrays(pane.output_source, "输出")
        )
        if input_key == output_key:
            raise FrfPreflightError("输入和输出不能是同一通道")
        if input_key[0] != output_key[0]:
            raise FrfPreflightError("输入和输出必须来自同一个逻辑来源")
        if not np.isclose(input_fs, output_fs, rtol=1e-9, atol=0.0):
            raise FrfPreflightError("输入和输出采样率不一致")
        if len(input_time) == 0 or len(output_time) == 0:
            raise FrfPreflightError("输入和输出没有共同的物理时间样本")

        requested_range = self._frf_requested_range(state, pane)
        common_lo = max(float(input_time[0]), float(output_time[0]))
        common_hi = min(float(input_time[-1]), float(output_time[-1]))
        if requested_range is not None:
            common_lo = max(common_lo, float(requested_range[0]))
            common_hi = min(common_hi, float(requested_range[1]))
        if common_hi < common_lo:
            raise FrfPreflightError("输入和输出在当前范围内没有共同的物理时间样本")

        input_mask = (input_time >= common_lo) & (input_time <= common_hi)
        output_mask = (output_time >= common_lo) & (output_time <= common_hi)
        input_time = input_time[input_mask]
        input_values = input_values[input_mask]
        output_time = output_time[output_mask]
        output_values = output_values[output_mask]
        if len(input_time) == 0 or len(output_time) == 0:
            raise FrfPreflightError("输入和输出在当前范围内没有共同的物理时间样本")

        if validate_selected:
            # Selected-data validation intentionally follows the common
            # physical mask so jitter outside an explicitly requested range
            # stays irrelevant.
            self._frf_validate_time_axis(
                input_time, input_values, input_fs, "输入"
            )
            self._frf_validate_time_axis(
                output_time, output_values, output_fs, "输出"
            )
            if len(input_time) != len(output_time):
                raise FrfPreflightError(
                    "应用同一物理范围后输入和输出样本数不一致"
                )
            alignment_tolerance = DEFAULT_TIME_JITTER_TOLERANCE / input_fs
            max_difference = float(np.max(np.abs(input_time - output_time)))
            if max_difference > alignment_tolerance:
                raise FrfPreflightError("输入和输出真实时间轴未逐点对齐")

        effective_range = (float(input_time[0]), float(input_time[-1]))
        return {
            "input_key": input_key,
            "output_key": output_key,
            "input_fd": input_fd,
            "output_fd": output_fd,
            "input_time": input_time,
            "output_time": output_time,
            "input_values": input_values,
            "output_values": output_values,
            "input_fs": input_fs,
            "input_unit": input_unit,
            "output_unit": output_unit,
            "requested_range": requested_range,
            "effective_range": effective_range,
        }

    def _frf_display_params_for_state(self, state):
        values = dict(self.inspector.frf_ctx.display_params())
        values.update({
            key: state.params[key]
            for key in values
            if key in state.params
        })
        return values

    def _build_frf_candidate(self, state, pane_idx, *, force=False):
        idx = min(int(pane_idx), len(state.panes) - 1)
        pane = state.panes[idx]
        prepared = self._frf_prepare_pair_samples(state, pane)
        input_key = prepared["input_key"]
        output_key = prepared["output_key"]
        input_fd = prepared["input_fd"]
        output_fd = prepared["output_fd"]
        input_time = prepared["input_time"]
        output_time = prepared["output_time"]
        input_values = prepared["input_values"]
        output_values = prepared["output_values"]
        input_fs = prepared["input_fs"]
        input_unit = prepared["input_unit"]
        output_unit = prepared["output_unit"]

        compute_values = self.inspector.frf_ctx.compute_params()
        compute_values.update({
            key: state.params[key]
            for key in compute_values
            if key in state.params
        })
        try:
            params = FrfParams(**compute_values)
        except ValueError as exc:
            raise FrfPreflightError(str(exc)) from exc
        nperseg = int(round(input_fs * params.t_win_s))
        if nperseg < 2:
            raise FrfPreflightError("FRF 段长必须至少包含 2 个样本")
        noverlap = int(np.floor(params.overlap * nperseg))
        hop = nperseg - noverlap
        segment_count = 1 + (len(input_values) - nperseg) // hop
        if segment_count < 2:
            raise FrfPreflightError(
                "FRF 平均至少需要 2 个完整段；请缩短段长或扩大时间范围"
            )
        if params.nfft_mode == "manual" and int(params.nfft) < nperseg:
            raise FrfPreflightError("NFFT 不能小于段长样本数")

        effective_range = prepared["effective_range"]
        render_params = self._frf_display_params_for_state(state)
        input_copy = np.array(input_values, dtype=np.float64, copy=True)
        output_copy = np.array(output_values, dtype=np.float64, copy=True)
        input_time_copy = np.array(input_time, dtype=np.float64, copy=True)
        output_time_copy = np.array(output_time, dtype=np.float64, copy=True)

        def job(worker):
            return compute_frf(
                input_copy,
                output_copy,
                fs=input_fs,
                params=params,
                input_time=input_time_copy,
                output_time=output_time_copy,
                cancel_check=worker.cancelled,
                progress=worker.progress.emit,
            )

        return {
            "view_id": state.view_id,
            "pane_idx": idx,
            "input_source": input_key,
            "output_source": output_key,
            "params": {"fs": input_fs, **params.__dict__},
            "time_range": effective_range,
            "render_params": render_params,
            "source_time_view_id": pane.source_time_view_id,
            "input_unit": input_unit,
            "output_unit": output_unit,
            "input_label": f"{input_fd.short_name} · {input_key[1]}",
            "output_label": f"{output_fd.short_name} · {output_key[1]}",
            "force": bool(force),
            "job": job,
        }

    def do_frf(self, force=False):
        self._capture_active_analysis_view("frf")
        _manager, state, page, pane_idx, _pane = self._active_frf_state()
        try:
            candidate = self._build_frf_candidate(state, pane_idx, force=force)
        except FrfPreflightError as issue:
            context = {"view_id": state.view_id, "pane_idx": pane_idx}
            self._frf_coordinator.request({
                **context,
                "preflight_error": issue,
            })
            return False
        self.inspector.frf_ctx.set_validation_message("")
        page.pane_canvas(pane_idx).show_progress()
        return self._frf_coordinator.request(candidate)

    def _recompute_restored_frf_view(self, view_id):
        """Dispatch every complete persisted pane without reading live combos."""

        state = self._frf_state_by_id(view_id)
        if state is None:
            return 0
        manager = self.analysis_managers["frf"]
        page = self._analysis_page("frf")
        is_active = manager.get(manager.active) is state
        submitted = 0
        for pane_idx, pane in enumerate(state.panes):
            if pane.input_source is None or pane.output_source is None:
                continue
            try:
                candidate = self._build_frf_candidate(state, pane_idx)
            except FrfPreflightError as issue:
                self._frf_coordinator.request({
                    "view_id": state.view_id,
                    "pane_idx": pane_idx,
                    "preflight_error": issue,
                })
                continue
            if is_active and pane_idx < page.pane_count():
                page.pane_canvas(pane_idx).show_progress()
            submitted += bool(self._frf_coordinator.request(candidate))
        return submitted

    def _on_frf_job_queued(self, context):
        if self._analysis_jobs.progress_token("frf") is None:
            token = self._begin_compute_progress(
                "频响计算中", total=1000, process_events=False
            )
            self._analysis_jobs.set_progress_token("frf", token)
        state = self._frf_state_by_id(context.get("view_id"))
        if state is self.analysis_managers["frf"].get(
            self.analysis_managers["frf"].active
        ):
            pane_idx = int(context.get("pane_idx", 0))
            page = self._analysis_page("frf")
            if 0 <= pane_idx < page.pane_count():
                page.pane_canvas(pane_idx).show_progress()

    def _on_frf_job_progress(self, done, total):
        token = self._analysis_jobs.progress_token("frf")
        if token is None:
            return
        self._update_compute_progress(done, total, label="频响计算中", token=token)
        if done == total and not self._analysis_jobs.is_running("frf"):
            self._finish_compute_progress(token=token)
            self._analysis_jobs.clear_progress_token("frf")

    def _frf_state_by_id(self, view_id):
        target = str(view_id or "")
        for state in self.analysis_managers["frf"].views:
            if state.view_id == target:
                return state
        return None

    def _frf_render_context_for_pane(self, pane):
        input_source = pane.input_source
        output_source = pane.output_source
        if input_source is None or output_source is None:
            return {}
        input_fd = self.files.get(input_source[0])
        output_fd = self.files.get(output_source[0])
        return {
            "input_source": input_source,
            "output_source": output_source,
            "input_unit": "" if input_fd is None else str(
                input_fd.channel_units.get(input_source[1], "") or ""
            ),
            "output_unit": "" if output_fd is None else str(
                output_fd.channel_units.get(output_source[1], "") or ""
            ),
            "input_label": input_source[1],
            "output_label": output_source[1],
        }

    def _on_frf_render_requested(self, context, result, cache_hit):
        state = self._frf_state_by_id(context.get("view_id"))
        if state is None:
            return
        pane_idx = int(context.get("pane_idx", 0))
        if not (0 <= pane_idx < len(state.panes)):
            return
        pane = state.panes[pane_idx]
        pane.effective_time_range = (
            float(result.effective.time_start),
            float(result.effective.time_end),
        )
        pane.source_time_view_id = context.get("source_time_view_id")
        manager = self.analysis_managers["frf"]
        if manager.get(manager.active) is not state:
            return
        page = self._analysis_page("frf")
        if pane_idx >= page.pane_count():
            return
        render_context = self._frf_render_context_for_pane(pane)
        render_context.update({
            key: context[key]
            for key in (
                "input_unit", "output_unit", "input_label", "output_label"
            )
            if key in context
        })
        canvas = page.pane_canvas(pane_idx)
        canvas.set_result(
            result,
            # Presentation controls do not invalidate compute. A job may
            # complete after the user changed them, so render with the current
            # persisted View values rather than the submission snapshot.
            display_params=self._frf_display_params_for_state(state),
            context=render_context,
        )
        self._restore_frf_canvas_ranges(canvas, pane)
        if pane_idx == page.focused_index():
            self.inspector.frf_ctx.set_validation_message("")
        suffix = "（缓存）" if cache_hit else ""
        self.statusBar.showMessage(
            f"频响完成{suffix} · {result.effective.segments} 段 · "
            f"df {result.effective.df:g} Hz"
        )

    def _on_frf_failed(self, context, issue):
        message = str(issue)
        state = self._frf_state_by_id(context.get("view_id"))
        if state is not None:
            manager = self.analysis_managers["frf"]
            pane_idx = int(context.get("pane_idx", 0))
            if manager.get(manager.active) is state:
                page = self._analysis_page("frf")
                if 0 <= pane_idx < page.pane_count():
                    page.pane_canvas(pane_idx).show_error(message)
                if pane_idx == page.focused_index():
                    self.inspector.frf_ctx.set_validation_message(message)
        self.statusBar.showMessage(f"频响错误: {message}")
        self.toast(message, "error")

    def _frf_cache_key_for_pane(self, state, pane):
        if (
            pane.input_source is None
            or pane.output_source is None
            or pane.effective_time_range is None
        ):
            return None
        input_fd = self.files.get(pane.input_source[0])
        if input_fd is None:
            return None
        params = dict(state.params)
        params["fs"] = float(input_fd.fs)
        return self.analysis_caches["frf"].make_key(
            pane.input_source,
            pane.output_source,
            frf_compute_cache_params(params),
            pane.effective_time_range,
        )

    def _render_frf_view_from_cache(self, state):
        page = self._analysis_page("frf")
        missing = False
        for pane_idx in range(min(page.pane_count(), len(state.panes))):
            pane = state.panes[pane_idx]
            canvas = page.pane_canvas(pane_idx)
            key = self._frf_cache_key_for_pane(state, pane)
            if key is None:
                canvas.full_reset()
                continue
            result = self.analysis_caches["frf"].get(key)
            if result is None:
                missing = True
                canvas.full_reset()
                canvas.show_empty_hint("点击『计算频响』生成")
                continue
            canvas.set_result(
                result,
                display_params=self._frf_display_params_for_state(state),
                context=self._frf_render_context_for_pane(pane),
            )
            self._restore_frf_canvas_ranges(canvas, pane)
        if missing:
            self.statusBar.showMessage("参数/输入输出已就绪，点击计算频响")

    def _on_frf_source_time_xrange_changed(self, canvas, lo, hi):
        # Time canvases emit settled ranges while a View is being rebuilt and
        # its saved X limits are restored. Those are projection transients,
        # not user interaction, and must never rewrite FRF snapshots.
        if getattr(self, "_applying_view", False):
            return False
        view_idx = self._view_index_for_canvas(canvas)
        if view_idx is None or not (0 <= view_idx < len(self.view_manager.views)):
            return False
        time_state = self.view_manager.get(view_idx)
        spec = CustomXAxisSpec.from_axis_opts(
            (time_state.axis_opts or {}).get("x_axis")
        )
        manager = self.analysis_managers["frf"]
        if spec.mode == CHANNEL_MODE:
            message = (
                "当前时域横轴不是物理时间，无法作为 FRF 时间范围；"
                "关联已解除，请切回时间轴后重新选择『当前时域范围』。"
            )
            return self._invalidate_frf_time_view_link(
                time_state.view_id, message
            )
        time_range = self._normalize_analysis_time_range((lo, hi))
        if time_range is None:
            return False
        changed = False
        for state in manager.views:
            for pane_idx, pane in enumerate(state.panes):
                if pane.source_time_view_id != time_state.view_id:
                    continue
                old = self._normalize_analysis_time_range(pane.time_range)
                if old is not None and np.allclose(
                    old, time_range, rtol=0.0, atol=1e-12
                ):
                    continue
                pane.time_range = time_range
                changed = True
                self._dirty_frf_pane(state, pane_idx, clear_effective=True)
        return changed

    def _invalidate_frf_time_view_link(self, view_id, message):
        """Clear every FRF link to one Time View and suppress late results."""

        manager = self.analysis_managers["frf"]
        active_state = manager.get(manager.active)
        page = self._analysis_page("frf")
        changed = False
        for state in manager.views:
            for pane_idx, pane in enumerate(state.panes):
                if pane.source_time_view_id != str(view_id):
                    continue
                pane.source_time_view_id = None
                changed = True
                self._dirty_frf_pane(state, pane_idx, clear_effective=True)
                if (
                    state is active_state
                    and pane_idx < page.pane_count()
                    and pane_idx == page.focused_index()
                ):
                    self.inspector.frf_ctx.set_validation_message(message)
        return changed

    def _on_frf_source_time_view_deleted(self, view_id):
        return self._invalidate_frf_time_view_link(
            view_id,
            "关联的时域 View 已删除；请重新关联：选择『当前时域范围』。",
        )

    def _frf_pair_effective_range(self, state, pane, *, lightweight=False):
        return self._frf_prepare_pair_samples(
            state, pane, validate_selected=not lightweight
        )["effective_range"]

    @staticmethod
    def _same_range(left, right):
        return (
            left is not None
            and right is not None
            and np.allclose(left, right, rtol=0.0, atol=1e-12)
        )

    @staticmethod
    def _frf_time_view_signature(input_source, output_source, effective_range):
        return {
            "input": [str(input_source[0]), str(input_source[1])],
            "output": [str(output_source[0]), str(output_source[1])],
            "effective_time_range": [
                float(effective_range[0]), float(effective_range[1])
            ],
        }

    def _time_view_has_frf_signature(
        self, view, input_source, output_source, effective_range
    ):
        raw = (view.axis_opts or {}).get("frf_source_signature")
        if not isinstance(raw, dict):
            return False
        try:
            stored_input = tuple(str(value) for value in raw["input"])
            stored_output = tuple(str(value) for value in raw["output"])
            stored_range = tuple(float(value) for value in raw["effective_time_range"])
        except (KeyError, TypeError, ValueError):
            return False
        return (
            stored_input == tuple(str(value) for value in input_source)
            and stored_output == tuple(str(value) for value in output_source)
            and self._same_range(stored_range, effective_range)
        )

    def _view_frf_pair_in_time_domain(self):
        _manager, state, _page, _pane_idx, pane = self._active_frf_state()
        if pane.input_source is None or pane.output_source is None:
            self.toast("请先选择 FRF 输入和输出", "warning")
            return -1
        try:
            effective_range = self._frf_pair_effective_range(state, pane)
        except FrfPreflightError as issue:
            self.toast(str(issue), "warning")
            return -1
        input_source = tuple(pane.input_source)
        output_source = tuple(pane.output_source)
        title = f"频响 · {output_source[1]}/{input_source[1]}"
        target = None
        for idx, view in enumerate(self.view_manager.views):
            spec = CustomXAxisSpec.from_axis_opts(
                (view.axis_opts or {}).get("x_axis")
            )
            if (
                self._time_view_has_frf_signature(
                    view, input_source, output_source, effective_range
                )
                and spec.mode != CHANNEL_MODE
            ):
                target = idx
                break
        if target is None:
            target = self.view_manager.new_view()
            if target < 0:
                self.toast("时域 View 已达 12 个；请先关闭一个 View 再重试", "warning")
                return -1
            view = self.view_manager.get(target)
            view.name = title
            view.attached_file_ids = list(dict.fromkeys(
                [str(input_source[0]), str(output_source[0])]
            ))
            view.checked = [input_source, output_source]
            view.hidden_channels = []
            colors = self._analysis_channel_color_map()
            view.colors = {
                key: colors[key] for key in view.checked if key in colors
            }
            view.plot_mode = "overlay"
            view.xlim = tuple(effective_range)
            axis_opts = dict(view.axis_opts or {})
            axis_opts.update({
                "x_axis": CustomXAxisSpec(mode="time").to_axis_opts(),
                "range_filter": {
                    "enabled": True,
                    "start": float(effective_range[0]),
                    "end": float(effective_range[1]),
                },
                "frf_source_signature": self._frf_time_view_signature(
                    input_source, output_source, effective_range
                ),
            })
            view.axis_opts = axis_opts
            self.view_manager.views_changed.emit()
        else:
            view = self.view_manager.get(target)
            # Re-assert the dedicated contract if the user panned or temporarily
            # edited the view after it was created; the canonical signature,
            # not the presentation name, determines reuse.
            view.attached_file_ids = list(dict.fromkeys(
                [str(input_source[0]), str(output_source[0])]
            ))
            view.checked = [input_source, output_source]
            view.hidden_channels = []
            view.xlim = tuple(effective_range)
            axis_opts = dict(view.axis_opts or {})
            axis_opts["x_axis"] = CustomXAxisSpec(mode="time").to_axis_opts()
            axis_opts["range_filter"] = {
                "enabled": True,
                "start": float(effective_range[0]),
                "end": float(effective_range[1]),
            }
            view.axis_opts = axis_opts
            self.view_manager.views_changed.emit()
        if self.view_manager.active != target:
            self.view_manager.set_active(target)
        self.toolbar._set_mode("time")
        self._apply_active_view(target)
        return target


__all__ = ["FrfMixin", "FrfPreflightError"]
