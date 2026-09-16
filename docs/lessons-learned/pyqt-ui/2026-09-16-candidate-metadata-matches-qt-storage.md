---
id: pyqt-ui/2026-09-16-candidate-metadata-matches-qt-storage
status: active
owners: [codex]
keywords: [pyqt, qcombobox, candidate, metadata, qvariant, itemdata]
paths:
  - mf4_analyzer/ui_kit/widgets/searchable_combo.py
checks:
  - candidate metadata matches QComboBox model.itemData roles
tests:
  - tests/ui/test_searchable_combo.py
role: pyqt-ui
tags: [qcombobox, candidate, metadata, qvariant, itemdata, identity]
created: 2026-09-16
updated: 2026-09-16
cause: insight
supersedes: []
---

# Candidate Metadata Matches Qt Storage

Trigger: Changing a QComboBox candidate no-op comparison or rows containing a
None placeholder, empty display text, or a QVariant value.

Past failure: Candidate metadata always expected UserRole=None and an empty
tooltip, but QComboBox's model omits invalid QVariant and empty tooltip roles.
Identical FRF/Order candidate rows therefore cleared and reinserted on every
refresh.

Rule: Compare candidates against the roles Qt actually stores: retain display
text, order, composite source identity, and every valid extra role; omit only
roles produced from invalid QVariant or an empty tooltip. Do not suppress all
extra-role checks to obtain a no-op.

Verification: Assert a repeated complete None-placeholder candidate list emits
no rowsRemoved/rowsInserted, and assert source identity, row order, and a
stored extra role each rebuild exactly once. Run the SearchableComboBox and
analysis-source projection tests.

## Context

FRF input/output and Order RPM selectors share SearchableComboBox and include a
None placeholder. The candidate helper compared an idealized role dict with
model.itemData(), although Qt had discarded its invalid role values.

## Lesson

Qt role comparisons must reflect the model's persistent role surface rather
than the values submitted to addItem(). None and an invalid QVariant both map
to an absent UserRole; the normal empty-label addItem path also leaves no
ToolTipRole, while valid composite tuples and later-added roles remain visible.

## How to apply

When adding a candidate no-op optimization, first probe model.itemData() for
all placeholder and empty cases. Keep the full stored role dict as the equality
contract, then cover both no-op signals and View-specific selection projection.
