"""Cross-view comparison display for one analysis section.

View and pane state stay the intent. This owner only remembers which two
views are on screen, which pane is focused, and which canvas projects each
``(section, view_id, pane_index)``. It is not a second copy of algorithm
parameters and it does not hold compute results.

Relations are keyed by the host view id. A host remembers one peer. The
peer's own relation is left alone, so focusing the peer cannot invent the
reverse pair. Axis-link flags live on that relation, not on
``AnalysisViewState.compare`` (that dict is the in-view pane compare).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisViewTarget:
    """Explicit pane a comparison canvas is projecting."""

    section: str
    view_id: str
    pane_index: int


@dataclass
class _HostRelation:
    peer_id: str
    axis_linked: bool = False
    levels_locked: bool = False


class AnalysisComparisonDisplay:
    """Per-section comparison presentation owned by ``AnalysisContext``."""

    def __init__(self):
        self._relations: dict[str, dict[str, _HostRelation]] = {}
        self._displayed: dict[str, tuple[str, str]] = {}
        self._focus: dict[str, tuple[str, int]] = {}
        self._by_canvas: dict[int, AnalysisViewTarget] = {}
        self._by_target: dict[tuple[str, str, int], object] = {}
        self._unlinks: dict[str, list] = {}
        self.hold_switch = False
        self.propagating_levels = False

    def running_timers(self):
        """Comparison display does not own a timer."""
        return []

    def is_open(self, section) -> bool:
        return section in self._displayed

    def displayed(self, section):
        """``(host_view_id, peer_view_id)`` while the pair is on screen."""
        pair = self._displayed.get(section)
        if pair is None:
            return None
        return pair

    def focused(self, section):
        """``(view_id, pane_index)`` of the pane the inspector addresses."""
        item = self._focus.get(section)
        if item is None:
            return None
        return item

    def peer_of(self, section, host_view_id):
        rel = self._relations.get(section, {}).get(str(host_view_id))
        if rel is None:
            return None
        return rel.peer_id

    def axis_linked(self, section) -> bool:
        rel = self._displayed_relation(section)
        return bool(rel.axis_linked) if rel is not None else False

    def levels_locked(self, section) -> bool:
        rel = self._displayed_relation(section)
        return bool(rel.levels_locked) if rel is not None else False

    def activation_effect(self, section, view_id) -> str:
        """``focus`` when the id is already on screen, otherwise ``switch``."""
        pair = self._displayed.get(section)
        if pair is not None and str(view_id) in {str(pair[0]), str(pair[1])}:
            return "focus"
        return "switch"

    def begin(self, section, host_view_id, peer_view_id) -> bool:
        """Remember host → peer and mark the pair displayed.

        Re-opening the same pair keeps link flags. A different peer replaces
        the host's single relation. The reverse peer → host relation is not
        created.
        """
        host_id = str(host_view_id or "")
        peer_id = str(peer_view_id or "")
        if not host_id or not peer_id or host_id == peer_id:
            return False
        rels = self._relations.setdefault(section, {})
        current = rels.get(host_id)
        if current is not None and current.peer_id == peer_id:
            rel = current
        else:
            rel = _HostRelation(peer_id)
            rels[host_id] = rel
        self._displayed[section] = (host_id, peer_id)
        focus = self._focus.get(section)
        if focus is None or str(focus[0]) not in {host_id, peer_id}:
            self._focus[section] = (host_id, 0)
        return True

    def focus(self, section, view_id, pane_index) -> bool:
        pair = self._displayed.get(section)
        vid = str(view_id or "")
        if pair is None or vid not in {str(pair[0]), str(pair[1])}:
            return False
        try:
            pane = int(pane_index)
        except (TypeError, ValueError):
            return False
        if pane < 0:
            return False
        self._focus[section] = (vid, pane)
        return True

    def close(self, section) -> None:
        """Forget the displayed host's relation and drop the display."""
        pair = self._displayed.get(section)
        if pair is not None:
            self._relations.get(section, {}).pop(str(pair[0]), None)
        self.suspend(section)

    def suspend(self, section) -> None:
        """Disconnect the display. Host → peer memory stays."""
        self._displayed.pop(section, None)
        self._focus.pop(section, None)
        self.unlink(section)
        self.unbind_section(section)

    def forget_view(self, section, view_id) -> bool:
        """Drop relations that use ``view_id`` as host or peer.

        Returns True when the on-screen pair included that view.
        """
        vid = str(view_id or "")
        rels = self._relations.get(section, {})
        rels.pop(vid, None)
        for host_id, rel in list(rels.items()):
            if str(rel.peer_id) == vid:
                rels.pop(host_id, None)
        pair = self._displayed.get(section)
        ended = pair is not None and vid in {str(pair[0]), str(pair[1])}
        if ended:
            self.suspend(section)
        return ended

    def relations_payload(self, section) -> dict:
        """Host → peer rows safe to store in a project file.

        Canvases, numeric results, and process-local tokens are not included.
        """
        out = {}
        for host_id, rel in self._relations.get(section, {}).items():
            out[str(host_id)] = {
                "peer": str(rel.peer_id),
                "axis_linked": bool(rel.axis_linked),
                "levels_locked": bool(rel.levels_locked),
            }
        return out

    def replace_relations(self, section, payload) -> None:
        """Replace remembered rows for one section. Does not mount a display."""
        rels = {}
        rows = payload if isinstance(payload, dict) else {}
        for host_id, row in rows.items():
            if not isinstance(row, dict):
                continue
            host = str(host_id or "")
            peer = row.get("peer")
            peer_id = str(peer) if isinstance(peer, str) and peer else ""
            if not host or not peer_id or host == peer_id:
                continue
            rels[host] = _HostRelation(
                peer_id,
                axis_linked=row.get("axis_linked") is True,
                levels_locked=row.get("levels_locked") is True,
            )
        if rels:
            self._relations[section] = rels
        else:
            self._relations.pop(section, None)
        pair = self._displayed.get(section)
        if pair is not None and str(pair[0]) not in rels:
            self.suspend(section)

    def drop_host(self, section, host_id) -> bool:
        """Forget one host → peer row. Suspend only when that host is displayed."""
        host = str(host_id or "")
        rels = self._relations.get(section, {})
        existed = host in rels
        if existed:
            rels.pop(host, None)
        pair = self._displayed.get(section)
        if pair is not None and str(pair[0]) == host:
            self.suspend(section)
        return existed

    def set_axis_linked(self, section, on) -> bool:
        rel = self._displayed_relation(section)
        if rel is None:
            return False
        rel.axis_linked = bool(on)
        if not on:
            self.unlink(section)
        return True

    def set_levels_locked(self, section, on) -> bool:
        rel = self._displayed_relation(section)
        if rel is None:
            return False
        rel.levels_locked = bool(on)
        return True

    def bind_canvas(self, canvas, target: AnalysisViewTarget) -> None:
        if canvas is None:
            return
        self._drop_canvas(canvas)
        key = (target.section, str(target.view_id), int(target.pane_index))
        previous = self._by_target.get(key)
        if previous is not None and previous is not canvas:
            self._by_canvas.pop(id(previous), None)
        self._by_canvas[id(canvas)] = target
        self._by_target[key] = canvas

    def target_for_canvas(self, canvas):
        if canvas is None:
            return None
        target = self._by_canvas.get(id(canvas))
        if target is None:
            return None
        if not _qt_alive(canvas):
            self._drop_canvas(canvas)
            return None
        return target

    def canvas_for(self, section, view_id, pane_index):
        try:
            pane = int(pane_index)
        except (TypeError, ValueError):
            return None
        canvas = self._by_target.get((section, str(view_id), pane))
        if canvas is None:
            return None
        if not _qt_alive(canvas):
            self._by_target.pop((section, str(view_id), pane), None)
            self._by_canvas.pop(id(canvas), None)
            return None
        return canvas

    def unbind_section(self, section) -> None:
        for key, target in list(self._by_canvas.items()):
            if target.section == section:
                self._by_canvas.pop(key, None)
        for key in list(self._by_target):
            if key[0] == section:
                self._by_target.pop(key, None)

    def add_unlink(self, section, callback) -> None:
        self._unlinks.setdefault(section, []).append(callback)

    def unlink(self, section) -> None:
        callbacks = self._unlinks.pop(section, [])
        for callback in callbacks:
            callback()

    def teardown(self) -> None:
        for section in list(self._unlinks):
            self.unlink(section)
        self._relations.clear()
        self._displayed.clear()
        self._focus.clear()
        self._by_canvas.clear()
        self._by_target.clear()
        self.hold_switch = False
        self.propagating_levels = False

    def _displayed_relation(self, section):
        pair = self._displayed.get(section)
        if pair is None:
            return None
        return self._relations.get(section, {}).get(str(pair[0]))

    def _drop_canvas(self, canvas) -> None:
        target = self._by_canvas.pop(id(canvas), None)
        if target is None:
            return
        key = (target.section, str(target.view_id), int(target.pane_index))
        if self._by_target.get(key) is canvas:
            self._by_target.pop(key, None)


def _qt_alive(canvas) -> bool:
    try:
        canvas.objectName()
    except RuntimeError:
        return False
    return True
