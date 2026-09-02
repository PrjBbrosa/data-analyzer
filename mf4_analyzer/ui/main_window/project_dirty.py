"""Single owner for project-session dirty state (Spec §9).

``ProjectDirtyState`` is the only place that decides whether persistable
project semantics differ from the last successful save. Mixins and widgets
must not scatter ``dirty=True``. Mutation funnels (Task 5B) call
:meth:`mark_user_mutation`; close/Quit/open-replace (Task 5C) read
:attr:`is_dirty` and the :class:`DirtyGuardResult` enum.

Dirty means the canonical ``.tlproj`` payload would change. Selection, focus,
hover, popup, render cache, job progress, toast, and temporary preview do not
belong here. Programmatic View restore/projection is not user intent: wrap it
in :meth:`begin_restore` / :meth:`end_restore` so intent handlers fail closed.
See ``docs/lessons-learned/programmatic-view-projection-is-not-user-intent.md``.

The QMessageBox lives on ``ProjectIOMixin.confirm_leave_unsaved_project``;
this holder only tracks revision, save point, restore depth, and guard
reentrancy. The save-path serializer lives in ``mf4_analyzer.ui.project_io``;
digest helpers there reuse the same payload object ``save_project_to_json``
writes. Guard-time digest review is optional and must not run on paint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DirtyGuardResult(Enum):
    """Outcome of the shared save/discard/cancel guard (Task 5C)."""

    PROCEED_SAVED = "proceed_saved"
    PROCEED_DISCARDED = "proceed_discarded"
    CANCELLED = "cancelled"


@dataclass
class ProjectDirtyState:
    """Revision/save-point holder for one MainWindow project session.

    ``revision`` counts accepted user mutations. ``save_point`` is the
    revision at the last successful save (or the post-restore clean point).
    ``is_dirty`` is true iff they differ. ``path`` is the current ``.tlproj``.
    """

    revision: int = 0
    save_point: int = 0
    path: str | None = None
    restore_depth: int = 0
    saved_digest: str | None = None
    guard_open: bool = False
    close_teardown_started: bool = False
    _last_mutation_token: object | None = field(
        default=None, repr=False, compare=False,
    )

    @property
    def is_dirty(self) -> bool:
        return self.revision != self.save_point

    def session_needs_guard(self, current_digest=None) -> bool:
        """True when revision is dirty, or guard-time digest disagrees.

        ``current_digest`` is the canonical payload hash from the save-path
        serializer. It is compared only when both sides exist; paint/replot
        must not call this.
        """
        if self.is_dirty:
            return True
        if current_digest is not None and self.saved_digest is not None:
            return current_digest != self.saved_digest
        return False

    def mark_user_mutation(self, token: object | None = None) -> bool:
        """Increment ``revision`` for one user-intent mutation.

        Fail-closed while ``restore_depth > 0`` (programmatic projection).
        A non-``None`` ``token`` is coalesced: the same token in a row is a
        no-op so one action that fans out to several funnels marks once.
        Bare calls (no token) always bump when not restoring.
        """
        if self.restore_depth > 0:
            return False
        if token is not None and token == self._last_mutation_token:
            return False
        self._last_mutation_token = token
        self.revision += 1
        return True

    def mark_saved(self, path=None, digest=None) -> None:
        """Record a successful save. Failed or cancelled saves must not call this."""
        self.save_point = self.revision
        if path is not None:
            self.path = str(path)
        if digest is not None:
            self.saved_digest = str(digest)
        self._last_mutation_token = None

    def begin_restore(self) -> None:
        self.restore_depth += 1

    def end_restore(self) -> None:
        self.restore_depth = max(0, self.restore_depth - 1)

    def clear(self) -> None:
        """Reset to the same empty session as ``ProjectDirtyState()``."""
        self.revision = 0
        self.save_point = 0
        self.path = None
        self.restore_depth = 0
        self.saved_digest = None
        self.guard_open = False
        self.close_teardown_started = False
        self._last_mutation_token = None
