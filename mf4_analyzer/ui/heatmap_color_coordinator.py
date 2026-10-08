"""Pane-owned color requests and final, focused heatmap presentation.

Runtime records contain natural (unlocked) windows. A group union is only a
projection and never feeds the next pane's request or reference anchor.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, replace
from weakref import WeakKeyDictionary

import numpy as np
from PyQt5 import sip
from PyQt5.QtCore import QObject

from ..heatmap_color_policy import resolve_heatmap_color_policy

_Z_KEYS = ("z_auto", "z_floor", "z_ceiling")


@dataclass(frozen=True)
class _Record:
    target: object
    policy: object
    source: object
    resolution: object
    amplitude_mode: str
    natural: tuple[float, float] | None = None


class HeatmapColorCoordinator:
    def __init__(self, *, context):
        self._context = context
        self._prepared = WeakKeyDictionary()
        self._records = WeakKeyDictionary()
        self._pending_basis = WeakKeyDictionary()
        self._depth = {}
        self._comparison_compatible = None
        self._after_settle = {}
        self._edit_sessions = WeakKeyDictionary()

    def set_comparison_compatibility_checker(self, callback):
        self._comparison_compatible = callback

    def target(self, section, canvas):
        from .main_window.analysis_comparison import AnalysisViewTarget

        if section not in ("fft_time", "order") or canvas is None:
            return None
        if isinstance(canvas, QObject) and sip.isdeleted(canvas):
            return None
        comp = self._context.comparison
        if comp.is_open(section):
            target = comp.target_for_canvas(canvas)
            if target is not None and target.section == section:
                return target if self._pane(target) is not None else None
        manager = self._context._analysis_managers.get(section)
        if manager is None or not manager.views:
            return None
        state = manager.get(manager.active)
        page = self._context.page(section)
        for index in range(min(page.pane_count(), len(state.panes))):
            if page.pane_canvas(index) is canvas:
                return AnalysisViewTarget(section, str(state.view_id), index)
        return None

    def _state(self, target):
        return self._context._analysis_state_for_id(target.section, target.view_id)

    def _pane(self, target):
        state = self._state(target)
        if state is not None and 0 <= target.pane_index < len(state.panes):
            return state.panes[target.pane_index]
        return None

    def is_focused(self, section, canvas):
        if self._context._chart_stack.current_mode() != section:
            return False
        target = self.target(section, canvas)
        if target is None:
            return False
        comp = self._context.comparison
        if comp.is_open(section):
            return comp.focused(section) == (target.view_id, target.pane_index)
        return target.pane_index == self._context.page(section).focused_index()

    def has_current_picture(self, section, canvas, source=None):
        """Whether a rejected projection may safely keep this target's picture."""
        target = self.target(section, canvas)
        row = self._records.get(canvas)
        if target is None or row is None or row.target != target or not self._has_data(canvas):
            return False
        if row.source is not None and tuple(row.source) not in self._pane(target).sources:
            return False
        if source is not None and (row.source is None or tuple(row.source) != tuple(source)):
            return False
        return row.natural is not None and all(np.isfinite(row.natural)) and row.natural[0] < row.natural[1]

    def prepare(self, section, canvas, params, resolution, source, amplitude_mode):
        target = self.target(section, canvas)
        if target is None:
            return None
        pane, state = self._pane(target), self._state(target)
        request = {"z_auto": False, "z_floor": -80.0 if section == "fft_time" else -30.0,
                   "z_ceiling": 0.0, **params, **state.params}
        policy = resolve_heatmap_color_policy(
            params=request, appearance=pane.chart_appearances.get("heatmap"),
            basis=pane.heatmap_color_basis, source=source, amplitude_mode=amplitude_mode,
            reference=resolution.value, unit=resolution.unit or "", quantity=resolution.quantity or "",
            reference_source=resolution.source or "",
        )
        self._prepared[canvas] = _Record(target, policy, source, resolution, amplitude_mode)
        return policy

    @staticmethod
    def _has_data(canvas):
        probe = getattr(canvas, "has_result", None)
        if callable(probe) and not probe():
            return False
        mask = getattr(canvas, "_matrix_amp_valid", None)
        if mask is not None:
            return bool(np.any(mask))
        matrix = getattr(canvas, "_matrix_disp", None)
        return matrix is not None and bool(np.any(np.isfinite(matrix)))

    def complete(self, section, canvas, policy):
        record = self._prepared.get(canvas)
        if record is None or record.policy is not policy:
            return False
        self._prepared.pop(canvas, None)
        if self.target(section, canvas) != record.target or not self._has_data(canvas):
            self._records.pop(canvas, None)
            self._pending_basis.pop(canvas, None)
            return False
        levels = (policy.z_floor, policy.z_ceiling)
        if policy.z_auto:
            levels = getattr(canvas, "_last_auto_levels", None)
            if levels is None:
                automatic = getattr(canvas, "_automatic_color_window", None)
                levels = automatic() if callable(automatic) else None
        if levels is None or not all(np.isfinite(levels)) or levels[0] >= levels[1]:
            return False
        record = replace(record, natural=(float(levels[0]), float(levels[1])))
        self._records[canvas] = record
        self._pending_basis[canvas] = record
        if not self._depth.get(section, 0):
            self.settle(section)
        return True

    @contextmanager
    def transaction(self, section):
        outer = not self._depth.get(section, 0)
        prior = {canvas: row for canvas, row in self._records.items() if row.target.section == section}
        self._depth[section] = self._depth.get(section, 0) + 1
        page = self._context.page(section)
        batch = getattr(page, "color_projection_batch", None)
        try:
            with batch() if outer and callable(batch) else nullcontext():
                yield
        except BaseException:
            if outer:
                self.forget(section)
                self._records.update(prior)
            raise
        else:
            if outer:
                self.settle(section)
        finally:
            self._depth[section] = max(0, self._depth.get(section, 1) - 1)
        if outer:
            callbacks = self._after_settle.pop(section, [])
            for callback in callbacks:
                callback()

    def _visible_records(self, section):
        return [(canvas, row) for canvas, row in list(self._records.items())
                if row.target.section == section and self.target(section, canvas) == row.target
                and self._has_data(canvas)
                and (row.source is None or tuple(row.source) in self._pane(row.target).sources)]

    def _cross_locked(self, section):
        comp = self._context.comparison
        return (comp.is_open(section) and comp.levels_locked(section)
                and self._comparison_compatible is not None
                and self._comparison_compatible(section))

    def _group_key(self, section, target):
        if self._cross_locked(section):
            return (section, "cross_view")
        if self._context.comparison.is_open(section):
            state = self._state(target)
            locked = state is not None and state.compare.get("levels_locked", False)
        else:
            locked = self._context.page(section).is_levels_locked()
        return (section, target.view_id) if locked else target

    def _group_members(self, section, target, records):
        key = self._group_key(section, target)
        return [(canvas, row) for canvas, row in records
                if self._group_key(section, row.target) == key]

    def settle(self, section):
        records = self._visible_records(section)
        rendered = set()
        for canvas, row in records:
            pending = self._pending_basis.pop(canvas, None)
            if pending is not None and pending.target == row.target:
                self._pane(row.target).heatmap_color_basis = copy.deepcopy(row.policy.basis)
                rendered.add(canvas)
        groups = {}
        for canvas, row in records:
            groups.setdefault(self._group_key(section, row.target), []).append((canvas, row))
        for members in groups.values():
            reset_baseline = any(canvas in rendered for canvas, _ in members)
            levels = (min(row.natural[0] for _, row in members),
                      max(row.natural[1] for _, row in members))
            for canvas, row in members:
                project = getattr(canvas, "project_color_levels", None)
                if callable(project):
                    project(row.policy.z_auto, *levels, reset_baseline=reset_baseline)
                if self.is_focused(section, canvas):
                    self._context.section_ctx(section).project_color_levels(
                        row.policy.z_auto, *levels, requested=dict(self._state(row.target).params),
                    )

    def _clear_override(self, pane):
        spec = dict(pane.chart_appearances.get("heatmap") or {})
        for key in ("z_auto", "z_min", "z_max"):
            spec.pop(key, None)
        if spec:
            pane.chart_appearances["heatmap"] = spec
        else:
            pane.chart_appearances.pop("heatmap", None)

    def _anchor_request(self, target):
        """Reanchor edited requests with each pane's own last successful facts."""
        pane = self._pane(target)
        if pane is None:
            return
        pane.heatmap_color_basis = None
        for canvas, row in list(self._records.items()):
            if (row.target != target or self.target(target.section, canvas) != target
                    or not self._has_data(canvas)):
                continue
            resolver = getattr(self._context, "resolve_db_reference_for_source", None)
            resolution = (resolver(target.section, row.source, params=self._state(target).params)
                          if callable(resolver) else row.resolution)
            row = replace(row, resolution=resolution)
            policy = self.prepare(target.section, canvas, {}, resolution, row.source, row.amplitude_mode)
            if policy is not None:
                pane.heatmap_color_basis = copy.deepcopy(policy.basis)
                if not policy.z_auto:
                    self._records[canvas] = replace(row, policy=policy, natural=(policy.z_floor, policy.z_ceiling))
                else:
                    automatic = getattr(canvas, "_automatic_color_window", None)
                    natural = automatic() if callable(automatic) else row.natural
                    if natural is not None:
                        self._records[canvas] = replace(row, policy=policy, natural=natural)
            self._prepared.pop(canvas, None)

    @contextmanager
    def edit_session(self, section, canvas):
        """Keep a dialog bound to its opening owner across a nested Qt event loop."""
        sessions = self._edit_sessions.setdefault(canvas, [])
        sessions.append((section, self.snapshot(section, canvas)))
        try:
            yield
        finally:
            sessions.pop()
            if not sessions:
                self._edit_sessions.pop(canvas, None)

    def _edit_session_matches(self, section, canvas):
        sessions = self._edit_sessions.get(canvas, ())
        for saved_section, snapshot in sessions:
            if saved_section != section:
                continue
            if snapshot is None or self.target(section, canvas) != snapshot["target"]:
                return False
            for view_id, saved in snapshot["views"].items():
                state = self._context._analysis_state_for_id(section, view_id)
                if (state is None or len(state.panes) != len(saved["panes"])
                        or any(pane.sources != old["sources"] for pane, old in zip(state.panes, saved["panes"]))):
                    return False
        return True

    def commit(self, section, canvas, edit, origin="inspector"):
        if origin not in ("inspector", "colorbar", "chart_options", "preset"):
            raise ValueError("unknown heatmap color edit origin")
        if not self._edit_session_matches(section, canvas):
            # Canvas dialogs preview before publishing intent. Reproject the
            # current target without allowing that preview to become its request.
            self.settle(section)
            return False
        target = self.target(section, canvas)
        if target is None or not isinstance(edit, dict) or not any(key in edit for key in _Z_KEYS):
            return False
        row = self._records.get(canvas)
        state, pane = self._state(target), self._pane(target)
        current = dict(state.params)
        if row is not None and row.target == target:
            visible = self._group_members(section, target, self._visible_records(section))
            natural = ((min(item.natural[0] for _, item in visible),
                        max(item.natural[1] for _, item in visible)) if visible else row.natural)
            current.update(z_auto=row.policy.z_auto, z_floor=natural[0], z_ceiling=natural[1])
        current.update({key: edit[key] for key in _Z_KEYS if key in edit})
        # Validate before changing any member. Linear avoids reference anchoring here.
        checked = resolve_heatmap_color_policy(params=current, source=None, reference=None, amplitude_mode="amplitude")
        values = dict(z_auto=checked.z_auto, z_floor=checked.z_floor, z_ceiling=checked.z_ceiling)
        targets = [target]
        if origin != "preset":
            members = self._group_members(section, target, self._visible_records(section))
            targets = list(dict.fromkeys([target] + [record.target for _, record in members]))
        affected = set()
        for member in targets:
            member_state, member_pane = self._state(member), self._pane(member)
            override = member_pane.chart_appearances.get("heatmap") or {}
            pane_edit = ((origin == "chart_options" and member == target)
                         or (origin == "colorbar" and "z_auto" in override)
                         or (member != target and "z_auto" in override))
            if pane_edit:
                member_pane.chart_appearances["heatmap"] = {
                    **override, "z_auto": values["z_auto"], "z_min": values["z_floor"], "z_max": values["z_ceiling"],
                }
                affected.add(member)
                continue
            member_state.params.update(values)
            if origin == "preset":
                for item in member_state.panes:
                    self._clear_override(item)
            else:
                self._clear_override(member_pane)
            for index, item in enumerate(member_state.panes):
                if "z_auto" not in (item.chart_appearances.get("heatmap") or {}):
                    affected.add(type(member)(section, member.view_id, index))
        for member in affected:
            self._anchor_request(member)
        if not self._depth.get(section, 0):
            self.settle(section)
        if (self.is_focused(section, canvas)
                and not any(record.target == target for _, record in self._visible_records(section))):
            self._context.section_ctx(section).project_color_levels(
                values["z_auto"], values["z_floor"], values["z_ceiling"],
                requested=dict(state.params),
            )
        return True

    def snapshot(self, section, canvas):
        """Opening Z intent of the addressed owner and its locked participants."""
        target = self.target(section, canvas)
        if target is None:
            return None
        members = [target]
        members += [row.target for _, row in self._group_members(
            section, target, self._visible_records(section),
        )]
        views = {}
        for member in members:
            state = self._state(member)
            if state is None or member.view_id in views:
                continue
            views[member.view_id] = {
                "params": {key: copy.deepcopy(state.params[key]) for key in _Z_KEYS if key in state.params},
                "panes": [{
                    "sources": copy.deepcopy(pane.sources),
                    "z": {key: copy.deepcopy(pane.chart_appearances.get("heatmap", {})[key])
                          for key in ("z_auto", "z_min", "z_max")
                          if key in pane.chart_appearances.get("heatmap", {})},
                    "basis": copy.deepcopy(pane.heatmap_color_basis),
                } for pane in state.panes],
            }
        return {"target": target, "views": views}

    def restore(self, section, canvas, snapshot):
        """Restore opening request/basis, retaining unrelated appearance edits."""
        target = self.target(section, canvas)
        if not isinstance(snapshot, dict) or target != snapshot.get("target") or target is None:
            return False
        restored = []
        for view_id, saved in snapshot["views"].items():
            state = self._context._analysis_state_for_id(section, view_id)
            if (state is None or len(state.panes) != len(saved["panes"])
                    or any(pane.sources != old["sources"] for pane, old in zip(state.panes, saved["panes"]))):
                return False
            restored.append((state, saved))
        for state, saved in restored:
            for key in _Z_KEYS:
                state.params.pop(key, None)
            state.params.update(copy.deepcopy(saved["params"]))
            for pane, old in zip(state.panes, saved["panes"]):
                self._clear_override(pane)
                if old["z"]:
                    pane.chart_appearances.setdefault("heatmap", {}).update(copy.deepcopy(old["z"]))
                pane.heatmap_color_basis = copy.deepcopy(old["basis"])
        for item, row in self._visible_records(section):
            if row.target.view_id not in snapshot["views"]:
                continue
            policy = self.prepare(section, item, {}, row.resolution, row.source, row.amplitude_mode)
            self._prepared.pop(item, None)
            if policy is not None:
                natural = (policy.z_floor, policy.z_ceiling)
                if policy.z_auto:
                    automatic = getattr(item, "_automatic_color_window", None)
                    natural = automatic() if callable(automatic) else row.natural
                if natural is not None:
                    self._records[item] = replace(row, policy=policy, natural=natural)
        self.settle(section)
        return True

    def defer_after_settle(self, section, callback):
        if self._depth.get(section, 0):
            self._after_settle.setdefault(section, []).append(callback)
        else:
            # complete() has already settled a standalone successful paint.
            callback()

    def forget_canvas(self, canvas):
        for mapping in (self._records, self._prepared, self._pending_basis):
            mapping.pop(canvas, None)

    def forget(self, section, view_id=None):
        self._after_settle.pop(section, None)
        for mapping in (self._records, self._prepared, self._pending_basis):
            for canvas, row in list(mapping.items()):
                if row.target.section == section and (view_id is None or row.target.view_id == str(view_id)):
                    mapping.pop(canvas, None)

    def reset(self):
        self._records.clear()
        self._prepared.clear()
        self._pending_basis.clear()
        self._depth.clear()
        self._after_settle.clear()
        for sessions in self._edit_sessions.values():
            sessions[:] = [(section, None) for section, _ in sessions]
