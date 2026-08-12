"""dB-reference Inspector widgets: scientific-notation editor + compound
control (editor + manage button + Auto/Manual badge + source line).

Spec: ``docs/analyzer/specs/2026-07-12-db-reference-defaults-and-labeling-spec.md``
sections 9-10. Implementation plan Task 3:
``docs/analyzer/plans/2026-07-12-db-reference-defaults-and-labeling-implementation.md``.
Approved visual reference (HTML → Qt translation per spec §17):
``docs/analyzer/reviews/reports/2026-07-12-db-reference-defaults-draft.html``.

Both widgets are PURE UI: they format/validate through the shared, Qt-free
``mf4_analyzer.db_reference`` module (``format_reference_editor``,
``validate_reference``) and never touch ``QSettings`` directly — catalog
persistence is the caller's job via ``DbReferenceSettingsStore``
(``mf4_analyzer/ui/db_reference_settings.py``), wired up in Task 4/5.
"""
from __future__ import annotations

import re

import qtawesome as qta
from PyQt5.QtCore import QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QValidator
from PyQt5.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ... import db_reference
from .compact_spinbox import no_buttons

# Same slate tone as the chart-stack toolbar icon family (mf4_analyzer/ui/
# chart_stack/_helpers.py ``_ICON_COLOR``) — the manage button must not read
# as a second primary-blue accent block (spec §17.2); only the badge carries
# the primary blue/amber.
_MANAGE_ICON_COLOR = "#374151"

_INVALID_TOOLTIP = "reference 必须是有限正数"

# Permissive "looks like a number, possibly mid-typing" pattern: an optional
# sign, an optional mantissa (integer/fraction), and an optional exponent
# marker with an optional sign and digits. This intentionally accepts
# in-progress text such as "1e", "1e-", "-", "." so the QLineEdit validator
# never blocks a keystroke a user is in the middle of typing "1e-12" with —
# the POSITIVE/finite semantic gate lives in ``_commit_or_revert``, not here.
_NUMBER_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)?([eE][+-]?\d*)?$")


class ScientificReferenceSpinBox(QDoubleSpinBox):
    """Compact ``QDoubleSpinBox`` accepting decimal AND scientific notation.

    Reuses the project's no-stepper compact contract (``no_buttons`` /
    ``compact=True`` dynamic property, see ``widgets/compact_spinbox.py``) so
    it inherits the same QSS chrome as every other Inspector spinbox. What it
    overrides is text<->value conversion and commit timing:

    * ``textFromValue``/``valueFromText`` reuse
      :func:`mf4_analyzer.db_reference.format_reference_editor` and
      ``float()`` — both already handle ``1e-12``/``1E-9``/``0.000001``/
      ``5e-8`` natively (Python's ``float()`` parses scientific notation out
      of the box; ``format_reference_editor`` emits the shortest compact
      form, e.g. ``1e-6`` not ``0.000001``).
    * ``setDecimals(30)`` is load-bearing, not cosmetic: ``QDoubleSpinBox``
      internally rounds every ``setValue()`` through
      ``QString::number(value, 'f', decimals)`` (FIXED decimal PLACES, not
      significant figures) regardless of the ``textFromValue`` override
      above — at the previous 6-decimal contract (``make_db_reference_spinbox``)
      this silently truncated ``1e-9``/``1e-12`` to ``0.0`` before the user
      ever saw an error. 18 places is already enough for a "round" value like
      ``1e-12``, but a non-terminating value such as the catalog's
      ``acceleration.g`` entry (``1e-6 / 9.80665 ≈ 1.0197162129779283e-07``,
      17 significant digits) needs ~24 decimal PLACES (7 leading zeros + 17
      significant digits) to survive the fixed-point round-trip bit-exact;
      30 gives comfortable headroom for any physically plausible reference.
    * Commit happens ONLY on Enter or focus-out (``setKeyboardTracking(False)``
      alone is not enough here because we fully own validation — see
      ``_commit_or_revert``), never on every keystroke, so typing "half" a
      reference never flips Auto→Manual (spec I2).
    * An invalid commit (non-finite, zero, negative, unparsable) reverts the
      displayed text to the last valid value, sets a field error state
      (``property('error', True)`` + tooltip), and does **not** silently
      coerce the value to ``1e-12`` or any other floor — spec I3 forbids the
      old ``max(reference, 1e-12)`` denominator clamp, and the same
      "never silently substitute a value" spirit applies to the editor.
    """

    #: Emitted with the parsed float ONLY for a valid user commit (Enter or
    #: focus-out with text that passes :func:`db_reference.validate_reference`).
    #: Distinct from the inherited ``valueChanged`` (which also fires for
    #: programmatic ``setValue()`` calls, e.g. Auto re-resolution) so a host
    #: compound control can flip Auto→Manual on genuine user edits only.
    value_committed = pyqtSignal(float)

    #: Emitted when a commit attempt was rejected (text reverted, no mode
    #: change should follow).
    invalid_commit = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dbReferenceEditor")
        no_buttons(self)
        self.setDecimals(30)
        # Deliberately wide enough to never itself clamp a value — positivity
        # gating is EXCLUSIVELY validate_reference() in _commit_or_revert
        # (spec I2/I3 forbid a silent range-floor substitute). A tighter
        # range such as ``[0, 1e18]`` would let Qt's own bound() silently
        # rewrite a directly-``setValue()``-assigned negative into 0.0 before
        # our validator ever sees it — harmless for typed user input (which
        # never reaches setValue() until _commit_or_revert already validated
        # it) but still the wrong place to gate positivity.
        self.setRange(-1.0e18, 1.0e18)
        self.setKeyboardTracking(False)
        self._error = False
        self._last_valid_value = 1.0
        self._last_valid_text = db_reference.format_reference_editor(1.0)
        super().setValue(1.0)

    # -- text <-> value --------------------------------------------------

    def textFromValue(self, value):  # noqa: N802 (Qt API)
        return db_reference.format_reference_editor(value)

    def valueFromText(self, text):  # noqa: N802 (Qt API)
        try:
            return float(text.strip())
        except (TypeError, ValueError):
            return self.value()

    def validate(self, text, pos):  # noqa: N802 (Qt API)
        stripped = text.strip()
        if stripped in ("", "-", "+", ".", "-.", "+."):
            return (QValidator.Intermediate, text, pos)
        if not _NUMBER_RE.match(stripped):
            return (QValidator.Invalid, text, pos)
        try:
            float(stripped)
        except ValueError:
            return (QValidator.Intermediate, text, pos)
        return (QValidator.Acceptable, text, pos)

    # -- value tracking ---------------------------------------------------

    def setValue(self, value):  # noqa: N802 (Qt API)
        """Programmatic set (Auto re-resolution, presets, tests). Always
        applies (matches the existing ``spin_db_ref`` contract); additionally
        remembers a valid value as the revert target for the NEXT invalid
        user commit, and clears any stale error state."""
        super().setValue(value)
        if db_reference.validate_reference(value):
            self._last_valid_value = float(value)
            self._last_valid_text = self.textFromValue(self._last_valid_value)
            self._set_error(False)

    def last_valid_value(self):
        return self._last_valid_value

    def is_error(self):
        return self._error

    # -- error state -------------------------------------------------------

    def _set_error(self, is_error, tooltip=""):
        if self._error == is_error:
            if not is_error:
                self.setToolTip("")
            return
        self._error = is_error
        self.setProperty("error", is_error)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.setToolTip(tooltip if is_error else "")

    # -- commit gating (Enter / focus-out ONLY, spec I2) --------------------

    def _commit_or_revert(self):
        text = self.lineEdit().text().strip()
        try:
            parsed = float(text)
        except ValueError:
            parsed = None

        if parsed is not None and db_reference.validate_reference(parsed):
            self.setValue(parsed)
            # Re-stamp the canonical compact text even when the numeric
            # value did not change (e.g. "1.00" retyped over "1").
            self.lineEdit().setText(self._last_valid_text)
            self.value_committed.emit(parsed)
        else:
            self._set_error(True, _INVALID_TOOLTIP)
            self.lineEdit().setText(self._last_valid_text)
            self.invalid_commit.emit()

    def keyPressEvent(self, event):  # noqa: N802 (Qt API)
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._commit_or_revert()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):  # noqa: N802 (Qt API)
        self._commit_or_revert()
        super().focusOutEvent(event)


class DbReferenceControl(QWidget):
    """Compound Inspector row: ``[editor][manage button+badge]`` + source line.

    Structure (spec §10.1)::

        dB 参考:  [ 1e-6                         ][ tune ]
                   ● 自动 · 系统默认 · acceleration / m/s²

    Required object names (spec §10.1): ``dbReferenceControl`` (root),
    ``dbReferenceEditor`` (editor), ``dbReferenceManageButton`` (button),
    ``dbReferenceModeBadge`` (badge), ``dbReferenceSourceLabel`` (source
    line). ``self.editor`` / ``self.spin_db_ref`` both alias the same
    :class:`ScientificReferenceSpinBox` so Task 4's
    ``ctx.spin_db_ref = control.editor`` wiring and any code written against
    the compound control directly share one object.

    This widget owns NO QSettings/store reference — it only emits signals
    (``manage_requested``, ``mode_committed``, ``value_committed``) for a
    host (Inspector contextual / MainWindow, Task 4/5) to react to.
    """

    #: User clicked the manage (tune) button.
    manage_requested = pyqtSignal()
    #: The control's own Auto/Manual mode changed as a result of a genuine
    #: user commit in the editor (never for a programmatic ``set_mode``/
    #: ``editor.setValue`` call). Value is ``'auto'`` or ``'manual'``.
    mode_committed = pyqtSignal(str)
    #: Forwards the editor's ``value_committed`` (valid user commits only).
    value_committed = pyqtSignal(float)

    _BADGE_SIZE = 16
    # 2026-07-13 alignment-datum revision (visual feedback, see
    # docs/lessons-learned/pyqt-ui/2026-07-12-collapsed-section-body-breaks-
    # mapto-geometry-probe.md sibling): the manage BUTTON's right edge is the
    # alignment datum against the sibling fields above it (频率加权 / 幅值轴,
    # same _fit_field(align_right=True) host as this compound root), not the
    # badge. The root layout below therefore reserves NO right margin — the
    # button (and hence the row) spans flush to the compound's own right
    # edge, which _fit_field's trailing-stretch host already lines up with
    # the form column's right edge. Consequently the badge can no longer
    # overhang PAST the button's right edge (there is no reserved px left of
    # the compound's right edge to spill into) — _position_badge aligns the
    # badge's right edge to the button's right edge instead (zero horizontal
    # overhang). Only the BOTTOM overhang is retained (past the button's
    # bottom edge into the row/source-line gap below), so the badge still
    # reads as a corner accent, not a fully-inset square. The bottom margin
    # below still reserves room so the badge's rect is ALWAYS a strict
    # subset of the control's own rect — Qt clips child painting to the
    # parent's geometry, so a badge parented under the button itself would
    # have its overhanging half silently cut off (the exact failure this
    # constant exists to avoid; see CLAUDE.md gotchas + lesson
    # pyqt-ui/2026-06-15-eliding-label-stable-anchor-and-text-returns-elided.md
    # for the sibling "read the full text, not the rendered text" pitfall
    # applied to the source line below).
    _BADGE_OVERHANG = 6
    _BADGE_MARGIN = _BADGE_OVERHANG + 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dbReferenceControl")
        self.setAttribute(Qt.WA_StyledBackground, True)

        outer = QVBoxLayout(self)
        # Right margin is 0 (not _BADGE_MARGIN): the manage button's right
        # edge is the alignment datum and must reach the compound's own
        # right edge flush, matching the sibling fields' right edge above it
        # (see _BADGE_SIZE docstring). Only the bottom margin reserves room
        # for the badge's residual bottom overhang.
        outer.setContentsMargins(0, 0, 0, self._BADGE_MARGIN)
        outer.setSpacing(3)

        row = QWidget(self)
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(6)

        self.editor = ScientificReferenceSpinBox(row)
        # Task 4 alias: contextual sections keep ``self.spin_db_ref`` pointing
        # at the editor; exposing the same alias here too means any code
        # written directly against the compound control needs no adaptor.
        self.spin_db_ref = self.editor
        row_lay.addWidget(self.editor, 1)

        self.manage_button = QToolButton(row)
        self.manage_button.setObjectName("dbReferenceManageButton")
        self.manage_button.setIcon(qta.icon("mdi.tune-vertical", color=_MANAGE_ICON_COLOR))
        self.manage_button.setIconSize(QSize(16, 16))
        self.manage_button.setToolTip("管理 dB reference 默认值")
        self.manage_button.setAccessibleName("管理 dB reference 默认值")
        self.manage_button.setCursor(Qt.PointingHandCursor)
        self.manage_button.setAutoRaise(False)
        self.manage_button.clicked.connect(self.manage_requested)
        row_lay.addWidget(self.manage_button, 0)

        outer.addWidget(row)

        self.source_label = QLabel("", self)
        self.source_label.setObjectName("dbReferenceSourceLabel")
        outer.addWidget(self.source_label)

        # Badge is a ROOT-level sibling (not the button's child) precisely so
        # it can overhang the button's bottom corner without being clipped
        # to the button's own rect — see _BADGE_SIZE docstring above (no
        # rightward overhang since 2026-07-13; the button's right edge is
        # the alignment datum).
        self.badge = QLabel("A", self)
        self.badge.setObjectName("dbReferenceModeBadge")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setAttribute(Qt.WA_StyledBackground, True)
        self.badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.badge.setFixedSize(self._BADGE_SIZE, self._BADGE_SIZE)
        self.badge.setFocusPolicy(Qt.NoFocus)

        self._mode = "auto"
        self._full_source_text = ""
        self.set_mode("auto")

        self.editor.value_committed.connect(self._on_editor_value_committed)

        QTimer.singleShot(0, self.refresh_geometry)

    # -- mode / badge --------------------------------------------------------

    def _on_editor_value_committed(self, value):
        if self._mode != "manual":
            self.set_mode("manual")
            # 2026-07-12 Task 10 visual-tour finding: nothing else refreshes
            # the source line on a genuine user commit -- the host's
            # ``_resolve_and_apply_db_reference`` (the ONLY other writer of
            # ``set_source_text``) explicitly no-ops whenever mode != 'auto'.
            # Without this, the caption stays on its STALE pre-commit "自动 ·
            # ..." text directly under the now-amber "M" badge -- a
            # contradictory, misleading state (spec §17.2 "same quiet
            # one-line provenance"). This widget has no channel facts of its
            # own, so it cannot reproduce the full "手动 · 手动覆盖 ·
            # <quantity>/<unit>" HTML line; it substitutes the same "手动覆盖"
            # token already used for the badge tooltip plus the spec's own
            # manual-isolation explanation (S8.1/S8.4).
            self.set_source_text("手动覆盖 · 不随通道或目录变化")
            self.mode_committed.emit("manual")
        self.value_committed.emit(value)

    def set_mode(self, mode):
        """Programmatic mode set (Auto resolution, Task 4/5 wiring, dialog
        save echo). Does NOT emit ``mode_committed`` — that signal is
        reserved for a genuine user-edit-driven transition."""
        mode = "manual" if mode == "manual" else "auto"
        self._mode = mode
        self.badge.setText("A" if mode == "auto" else "M")
        self.badge.setProperty("mode", mode)
        self.badge.setToolTip("自动" if mode == "auto" else "手动覆盖")
        style = self.badge.style()
        style.unpolish(self.badge)
        style.polish(self.badge)

    def mode(self):
        return self._mode

    # -- source line (elide + full-text tooltip) -----------------------------

    def set_source_text(self, text, tooltip=None):
        self._full_source_text = text or ""
        self._reflow_source_text()
        self.source_label.setToolTip(
            tooltip if tooltip is not None else self._full_source_text
        )

    def full_source_text(self):
        """The un-elided source text — ``QLabel.text()`` returns the ELIDED
        string once ``setText`` has been called with a fixed-width elide, so
        callers that need the real value must read this instead (same
        pitfall as lesson pyqt-ui/2026-06-15-eliding-label...)."""
        return self._full_source_text

    def _reflow_source_text(self):
        metrics = self.source_label.fontMetrics()
        width = max(self.source_label.width(), 40)
        # Keep distinguishing tails of long source lines (same G8 lesson as
        # channel_tree / file_navigator).
        elided = metrics.elidedText(self._full_source_text, Qt.ElideMiddle, width)
        self.source_label.setText(elided)

    # -- geometry: square button matches editor height; badge never clips --

    def resizeEvent(self, event):  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self.refresh_geometry()
        if self._full_source_text:
            self._reflow_source_text()

    def showEvent(self, event):  # noqa: N802 (Qt API)
        super().showEvent(event)
        self.refresh_geometry()

    def refresh_geometry(self):
        """Re-sync the manage button's size (square, matching the editor's
        CURRENT rendered height) and the badge's position. Public + callable
        from tests directly (deferred QSS/font polish on first show is a
        known offscreen pitfall — see lesson pyqt-ui/2026-07-10-reused-
        translucent-popover-cjk-sizehint-collapses-synchronously.md) rather
        than only relying on event timing."""
        self.editor.ensurePolished()
        self.manage_button.ensurePolished()
        h = self.editor.height()
        if h > 0 and (self.manage_button.height() != h or self.manage_button.width() != h):
            self.manage_button.setFixedSize(h, h)
        self._position_badge()

    def _position_badge(self):
        top_left = self.manage_button.mapTo(self, QPoint(0, 0))
        bw = self.manage_button.width()
        bh = self.manage_button.height()
        size = self._BADGE_SIZE
        # Horizontal: FLUSH with the button's right edge, zero overhang --
        # the button's right edge is the alignment datum against the
        # sibling fields above (spec revision 2026-07-13); there is no
        # reserved px to the right of the compound's own edge to spill into
        # any more (see _BADGE_SIZE docstring).
        x = top_left.x() + bw - size
        # Vertical: retains a modest overhang past the button's bottom edge
        # (into the reserved bottom margin) so the badge still reads as a
        # corner accent rather than a fully inset square.
        y = top_left.y() + bh - size + self._BADGE_OVERHANG
        x = max(0, min(x, self.width() - size))
        y = max(0, min(y, self.height() - size))
        self.badge.setGeometry(x, y, size, size)
        self.badge.raise_()
