"""Directional cache and stale-result ownership for interactive FRF jobs."""
from __future__ import annotations

from typing import Mapping

from PyQt5.QtCore import QObject, pyqtSignal


_COMPUTE_FIELDS = (
    "fs",
    "estimator",
    "window",
    "periodic_window",
    "t_win_s",
    "overlap",
    "nfft_mode",
    "nfft",
    "detrend",
)


def frf_compute_cache_params(params: Mapping) -> dict:
    """Extract the fields that can change the raw complex FRF result.

    Frequency/phase presentation and coherence styling intentionally stay out
    of this mapping so they can redraw an existing complex result without a
    worker dispatch.
    """

    return {field: params.get(field) for field in _COMPUTE_FIELDS}


class FrfCoordinator(QObject):
    """Coordinate per-pane FRF requests over the shared section FIFO.

    ``AnalysisJobService`` remains the only thread and queue owner.  A newer
    request always invalidates the originating pane's generation, so a stale
    completion can never render or reach the cache.

    The service's ``replace``/``cancel`` operations are section-wide, so they
    are used only in the one case where "section-wide" and "this pane" mean
    the same thing: nothing else the coordinator still tracks is outstanding
    (see ``_may_replace_section``).  Whenever another pane holds queued or
    in-flight work, the request is a plain append and the older job is
    suppressed on completion instead of being cancelled.
    """

    render_requested = pyqtSignal(object, object, bool)
    failed = pyqtSignal(object, object)
    job_queued = pyqtSignal(object)

    _SECTION = "frf"

    def __init__(self, cache, job_service, parent=None):
        super().__init__(parent)
        self._cache = cache
        self._job_service = job_service
        self._next_job_id = 0
        self._pane_generations: dict[object, int] = {}
        self._pending: dict[int, dict] = {}

        job_service.finished.connect(self._on_job_finished)
        job_service.failed.connect(self._on_job_failed)

    def request(self, candidate: Mapping) -> bool:
        """Render from cache or append one job to section ``frf``.

        Returns ``True`` only when a worker job was submitted.  A preflight
        issue or cache hit completes synchronously through the corresponding
        signal and returns ``False``.
        """

        if not isinstance(candidate, Mapping):
            raise TypeError("FRF candidate must be a mapping")
        if "pane_idx" not in candidate:
            raise ValueError("FRF candidate missing pane_idx")
        pane_idx = int(candidate["pane_idx"])
        pane_token, generation = self._begin_pane_request(
            candidate, pane_idx
        )
        issue = candidate.get("preflight_error")
        if issue is not None:
            context = self._issue_context(candidate)
            context["pane_idx"] = pane_idx
            context["_coordinator_pane_token"] = pane_token
            context["_coordinator_pane_generation"] = generation
            self.failed.emit(context, issue)
            return False

        ctx = self._build_context(candidate)
        ctx["_coordinator_pane_token"] = pane_token
        ctx["_coordinator_pane_generation"] = generation

        cached = self._cache.get(ctx["analysis_key"])
        if cached is not None and not candidate.get("force", False):
            self.render_requested.emit(ctx, cached, True)
            return False

        job = candidate.get("job")
        if not callable(job):
            raise TypeError("FRF candidate job must be callable")

        # Decide before this request joins the ledger: ``_pending`` must show
        # only what *other* work the section still owes.
        replace = self._may_replace_section()

        self._next_job_id += 1
        job_id = self._next_job_id
        ctx["_coordinator_job_id"] = job_id
        self._pending[job_id] = ctx
        # UI progress must exist before AnalysisJobService can start a very
        # short worker and emit progress/terminal signals.
        self.job_queued.emit(ctx)
        self._job_service.submit(
            self._SECTION,
            job,
            ctx=ctx,
            replace=replace,
        )
        return True

    def _may_replace_section(self) -> bool:
        """Whether a section-level replace can only hit superseded work.

        ``_begin_pane_request`` has already dropped the calling pane's own
        contexts, so a non-empty ``_pending`` means another pane still owns a
        queued or in-flight job -- ``cancel('frf')`` would discard it and its
        user-visible result, which spec 8.4 forbids.

        An empty ``_pending`` with a live section is the opposite case: every
        remaining worker is one whose result this coordinator has already
        committed to discarding (superseded by this very request, or dropped
        by ``invalidate_pane``/``invalidate_fid``/``invalidate_all``).
        Cancelling stops a full wasted compute and lets the replacement start
        immediately instead of queueing behind it.  ``is_running`` gates the
        idle case so a cold section is a plain append with nothing to cancel.
        """

        if self._pending:
            return False
        return bool(self._job_service.is_running(self._SECTION))

    def invalidate_fid(self, fid: str) -> None:
        """Invalidate cache and suppress late jobs touching either endpoint."""

        fid = str(fid)
        self._cache.invalidate_fid(fid)
        affected_panes = {
            ctx["_coordinator_pane_token"]
            for ctx in self._pending.values()
            if self._context_contains_fid(ctx, fid)
        }
        self._pending = {
            job_id: ctx
            for job_id, ctx in self._pending.items()
            if not self._context_contains_fid(ctx, fid)
        }
        for pane_token in affected_panes:
            self._pane_generations[pane_token] = (
                self._pane_generations.get(pane_token, 0) + 1
            )

    def invalidate_pane(self, view_id: str, pane_idx: int) -> None:
        """Suppress pending work for one persisted pane only.

        The shared service owns a section-wide FIFO, so pane-local edits must
        never call ``cancel('frf')`` or replace another pane's queued work.
        Bumping the pane generation makes an already-running completion stale;
        dropping its pending context also prevents it from populating cache.
        """

        token = self._pane_token(
            {"view_id": view_id, "pane_idx": int(pane_idx)}, int(pane_idx)
        )
        self._pane_generations[token] = self._pane_generations.get(token, 0) + 1
        self._drop_pending_for_pane(token)

    def invalidate_all(self) -> None:
        """Clear cached results and make every pending completion stale."""

        self._cache.clear()
        for pane_token in {
            ctx["_coordinator_pane_token"] for ctx in self._pending.values()
        }:
            self._pane_generations[pane_token] = (
                self._pane_generations.get(pane_token, 0) + 1
            )
        self._pending.clear()

    def _build_context(self, candidate: Mapping) -> dict:
        required = (
            "pane_idx",
            "input_source",
            "output_source",
            "params",
            "time_range",
            "render_params",
        )
        missing = [field for field in required if field not in candidate]
        if missing:
            raise ValueError("FRF candidate missing " + ", ".join(missing))

        input_source = self._coerce_source(candidate["input_source"], "input")
        output_source = self._coerce_source(candidate["output_source"], "output")
        params = dict(candidate["params"])
        time_range = candidate["time_range"]
        pane_idx = int(candidate["pane_idx"])

        context = dict(candidate)
        context.pop("job", None)
        context.pop("preflight_error", None)
        context["pane_idx"] = pane_idx
        context["input_source"] = input_source
        context["output_source"] = output_source
        context["params"] = params
        context["render_params"] = dict(candidate["render_params"])
        context["analysis_key"] = self._cache.make_key(
            input_source,
            output_source,
            frf_compute_cache_params(params),
            time_range,
        )
        return context

    @staticmethod
    def _issue_context(candidate: Mapping) -> dict:
        context = dict(candidate)
        context.pop("job", None)
        context.pop("preflight_error", None)
        return context

    @staticmethod
    def _coerce_source(value, role: str) -> tuple[str, str]:
        try:
            fid, channel = value
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"FRF {role}_source must be a (fid, channel) pair"
            ) from exc
        return str(fid), str(channel)

    @staticmethod
    def _pane_token(candidate: Mapping, pane_idx: int):
        if "pane_key" in candidate:
            pane_key = candidate["pane_key"]
            try:
                hash(pane_key)
            except TypeError as exc:
                raise ValueError("FRF pane_key must be hashable") from exc
            return pane_key
        view_id = candidate.get("view_id")
        if view_id is None or not str(view_id):
            raise ValueError("FRF candidate needs stable view_id or pane_key")
        return str(view_id), pane_idx

    def _drop_pending_for_pane(self, pane_token) -> None:
        self._pending = {
            job_id: ctx
            for job_id, ctx in self._pending.items()
            if ctx["_coordinator_pane_token"] != pane_token
        }

    def _begin_pane_request(
        self, candidate: Mapping, pane_idx: int
    ) -> tuple[object, int]:
        pane_token = self._pane_token(candidate, pane_idx)
        generation = self._pane_generations.get(pane_token, 0) + 1
        self._pane_generations[pane_token] = generation
        self._drop_pending_for_pane(pane_token)
        return pane_token, generation

    @staticmethod
    def _context_contains_fid(ctx: Mapping, fid: str) -> bool:
        return (
            str(ctx["input_source"][0]) == fid
            or str(ctx["output_source"][0]) == fid
        )

    def _on_job_finished(self, section: str, ctx, result) -> None:
        if section != self._SECTION:
            return
        pending = self._take_current_pending(ctx)
        if pending is None:
            return
        self._cache.put(pending["analysis_key"], result)
        self.render_requested.emit(pending, result, False)

    def _on_job_failed(self, section: str, ctx, issue) -> None:
        if section != self._SECTION:
            return
        pending = self._take_current_pending(ctx)
        if pending is not None:
            self.failed.emit(pending, issue)

    def _take_current_pending(self, ctx):
        if not isinstance(ctx, Mapping):
            return None
        job_id = ctx.get("_coordinator_job_id")
        if not isinstance(job_id, int):
            return None
        pending = self._pending.pop(job_id, None)
        if pending is None:
            return None
        pane_token = pending["_coordinator_pane_token"]
        generation = pending["_coordinator_pane_generation"]
        if (
            ctx.get("_coordinator_pane_token") != pane_token
            or ctx.get("_coordinator_pane_generation") != generation
            or self._pane_generations.get(pane_token) != generation
        ):
            return None
        return pending
