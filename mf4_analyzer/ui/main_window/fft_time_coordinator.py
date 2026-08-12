"""Cache-aware dispatch for FFT-vs-Time analysis requests."""
from __future__ import annotations

from typing import Callable, Mapping

from PyQt5.QtCore import QObject, pyqtSignal


def fft_time_compute_cache_params(params: Mapping, time_range) -> dict:
    """Return the compute-only FFT-vs-Time cache parameter mapping.

    Display choices deliberately stay out of this mapping.  ``time_range`` is
    an explicit input because a split view can compute the same source over
    independent pane-local ranges.
    """
    nfft = params.get("nfft_effective", params.get("nfft"))
    return {
        "fs": params.get("fs"),
        "nfft": int(nfft),
        "window": params.get("window"),
        "overlap": params.get("overlap"),
        "remove_mean": params.get("remove_mean"),
        "weighting": str(params.get("weighting", "None")),
        "time_range": time_range,
    }


def make_fft_time_analysis_key(
    cache_make_key: Callable, fid: str, channel: str, params: Mapping,
    time_range,
):
    """Build one FFT-vs-Time cache key from a cache's pure key function."""
    return cache_make_key(
        fid, channel, fft_time_compute_cache_params(params, time_range)
    )


class FftTimeCoordinator(QObject):
    """Associate FFT-vs-Time jobs with cache keys and render contexts.

    The coordinator deliberately receives its collaborators by injection.  It
    neither constructs presentation objects nor understands how a completed
    result is drawn.  Its public events carry opaque contexts for the caller
    that owns those responsibilities.

    Writes go exclusively through ``store_result`` so View pinning can record
    the dispatch-time ``view_id`` (never the callback-time active View).
    """

    render_requested = pyqtSignal(object, object, bool)
    failed = pyqtSignal(object, object)
    batch_started = pyqtSignal(int, object)

    _SECTION = "fft_time"
    _MISSING = object()

    def __init__(
        self,
        cache,
        job_service,
        key_builder: Callable,
        store_result: Callable,
        parent=None,
    ):
        super().__init__(parent)
        self._cache = cache
        self._job_service = job_service
        self._key_builder = key_builder
        self._store_result = store_result
        self._generation = 0
        self._next_job_id = 0
        self._pending: dict[int, dict] = {}

        job_service.finished.connect(self._on_job_finished)
        job_service.failed.connect(self._on_job_failed)

    def request_batch(self, candidates, *, replace: bool = False) -> int:
        """Resolve ``candidates`` from cache or queue them as one batch.

        Each candidate is a mapping containing ``fid``, ``channel``,
        ``params``, ``pane_idx``, ``time_range``, ``job``, ``render_params``,
        and ``source``.  A ``job`` of ``None`` remains a service-level skip so
        that callers retain correct progress totals for a multi-pane request.
        Alternatively, a zero-argument ``job_factory`` is called only after a
        cache miss.  It may return a job directly, or ``(job, ctx_updates)``
        where updates refine final compute parameters after preflight.

        Returns the number of items sent to the service.  This distinguishes a
        cache-only batch from a batch that needs progress-token ownership.
        """
        candidates = list(candidates)
        if replace:
            self._generation += 1
            self._pending.clear()

        queued = []
        for candidate in candidates:
            job = candidate.get("job", self._MISSING)
            if job is None:
                ctx = self._build_context(candidate, include_key=False)
                queued.append((None, ctx))
                continue

            ctx = self._build_context(candidate)
            if not candidate.get("force", False):
                cached = self._cache.get(ctx["analysis_key"])
                if cached is not None:
                    self.render_requested.emit(ctx, cached, True)
                    continue

            factory = candidate.get("job_factory")
            if factory is not None:
                if not callable(factory):
                    raise TypeError("FFT-vs-Time job_factory must be callable")
                job, updates = self._unpack_factory_result(factory())
                if updates:
                    self._apply_factory_updates(ctx, updates)
            elif job is self._MISSING:
                raise ValueError("FFT-vs-Time candidate needs job or job_factory")

            if job is None:
                queued.append((None, ctx))
                continue
            if not callable(job):
                raise TypeError("FFT-vs-Time job must be callable or None")
            self._next_job_id += 1
            job_id = self._next_job_id
            ctx["_coordinator_generation"] = self._generation
            ctx["_coordinator_job_id"] = job_id
            self._pending[job_id] = ctx
            queued.append((job, ctx))

        if queued:
            self.batch_started.emit(len(queued), queued[0][1])
            self._job_service.submit_batch(
                self._SECTION, queued, replace=replace
            )
        elif replace:
            cancel = getattr(self._job_service, "cancel", None)
            if callable(cancel):
                cancel(self._SECTION)
        return len(queued)

    def invalidate_fid(self, fid: str) -> None:
        """Forget one file's results and suppress any of its late callbacks."""
        fid = str(fid)
        self._cache.invalidate_fid(fid)
        self._pending = {
            job_id: ctx
            for job_id, ctx in self._pending.items()
            if str(ctx["fid"]) != fid
        }

    def invalidate_all(self) -> None:
        """Forget every cached result AND drop every in-flight pending context.

        The close-all counterpart to :meth:`invalidate_fid`: without clearing
        ``_pending`` a fft_time job still running when all files close would,
        on completion, resurrect a now-dead fid's result back into the just-
        cleared cache and render an over-stale heatmap onto a reset pane."""
        self._cache.clear()
        self._pending.clear()

    def _build_context(self, candidate: Mapping, *, include_key: bool = True) -> dict:
        required = (
            "fid",
            "channel",
            "params",
            "pane_idx",
            "time_range",
            "render_params",
        )
        missing = [field for field in required if field not in candidate]
        if missing:
            raise ValueError(
                "FFT-vs-Time candidate missing " + ", ".join(missing)
            )

        fid = str(candidate["fid"])
        channel = str(candidate["channel"])
        params = dict(candidate["params"])
        time_range = candidate["time_range"]
        context = dict(candidate)
        context.pop("job", None)
        context.pop("job_factory", None)
        context["fid"] = fid
        context["channel"] = channel
        context["params"] = params
        context["render_params"] = dict(candidate["render_params"])
        context["source"] = candidate.get("source", (fid, channel))
        if include_key:
            context["analysis_key"] = self._key_builder(
                fid, channel, params, time_range
            )
        return context

    @staticmethod
    def _unpack_factory_result(built) -> tuple[object, dict]:
        if built is None:
            return None, {}
        if isinstance(built, tuple) and len(built) == 2:
            job, updates = built
            if updates is None:
                return job, {}
            if not isinstance(updates, Mapping):
                raise TypeError("FFT-vs-Time job_factory updates must be a mapping")
            return job, dict(updates)
        return built, {}

    def _apply_factory_updates(self, ctx: dict, updates: Mapping) -> None:
        """Merge factory preflight outputs while retaining key ownership here."""
        for field in (
            "fid", "channel", "params", "pane_idx", "time_range",
            "render_params", "source",
        ):
            if field in updates:
                ctx[field] = updates[field]
        ctx["fid"] = str(ctx["fid"])
        ctx["channel"] = str(ctx["channel"])
        ctx["params"] = dict(ctx["params"])
        ctx["render_params"] = dict(ctx["render_params"])
        ctx["analysis_key"] = self._key_builder(
            ctx["fid"], ctx["channel"], ctx["params"], ctx["time_range"]
        )

    def _on_job_finished(self, section: str, ctx, result) -> None:
        if section != self._SECTION:
            return
        pending = self._take_current_pending(ctx)
        if pending is None:
            return
        self._store_result(
            pending.get("view_id"),
            int(pending.get("pane_idx", 0)),
            pending["analysis_key"],
            result,
        )
        self.render_requested.emit(pending, result, False)

    def _on_job_failed(self, section: str, ctx, error) -> None:
        if section != self._SECTION:
            return
        pending = self._take_current_pending(ctx)
        if pending is None:
            return
        self.failed.emit(pending, error)

    def _take_current_pending(self, ctx):
        if not isinstance(ctx, Mapping):
            return False
        job_id = ctx.get("_coordinator_job_id")
        if not isinstance(job_id, int):
            return None
        pending = self._pending.pop(job_id, None)
        if (
            pending is None
            or pending.get("_coordinator_generation") != self._generation
            or ctx.get("_coordinator_generation") != self._generation
        ):
            return None
        return pending
