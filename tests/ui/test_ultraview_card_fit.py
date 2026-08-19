"""Card Fit solver contracts: oracle parity, local-only commit, Fit split."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mf4_analyzer.ui.chart_stack.ultraview.card_fit import (
    CARD_FIT_SNAP_WINDOW,
    REASON_NO_IMPROVEMENT,
    REASON_NO_PREVIEW,
    REASON_NO_SPACE,
    CardFitFacts,
    aspect_contain_box,
    card_fit_plot_size,
    iter_card_fit_search_rects,
    solve_card_fit,
    unconstrained_card_fit_facts,
)
from mf4_analyzer.ui.chart_stack.ultraview.free_grid import (
    GRID_ROW_HEIGHT,
    fit_rect_for_aspect,
    plan_auto_arrange,
    rect_to_pixels,
    rects_overlap,
    screen_grid_metrics,
)
from mf4_analyzer.ui.chart_stack.ultraview.layouts import (
    CARD_FIT_CHROME_HEIGHT,
    CARD_FOOTER_HEIGHT,
    CARD_HEADER_HEIGHT,
    CARD_IMAGE_PADDING,
    preview_reading_box,
)
from mf4_analyzer.ui.ultraview_state import (
    GRID_MAX_COLUMN_SPAN,
    GRID_MAX_ROW_SPAN,
    GRID_MIN_COLUMN_SPAN,
    GRID_MIN_ROW_SPAN,
    GRID_RESOLUTION,
    FreeGridPlacement,
    GridRect,
    make_ref,
    set_free_grid_rects,
    template_to_free_grid,
    default_board,
    add_ref,
    set_layout,
)

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "chart_stack"
    / "ultraview"
    / "card_fit.py"
)
COORDINATOR_PATH = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "main_window"
    / "ultraview_coordinator.py"
)

# Retired shrink-then-one-axis-grow cap. Kept only to prove the old helper
# disagrees with the F3 oracle on two-axis growth.
_LEGACY_GROW_MAX = 2 * GRID_RESOLUTION
_LEGACY_LETTERBOX_COST = 0.35


def _facts(
    origin: GridRect,
    image: tuple[int, int] | None,
    metrics,
    *,
    footer_height: int = CARD_FOOTER_HEIGHT,
    occupied: tuple[GridRect, ...] = (),
    header_height: int = CARD_HEADER_HEIGHT,
    image_margin_x: int = CARD_IMAGE_PADDING,
    image_margin_y: int = CARD_IMAGE_PADDING,
    orphan_height: int = 0,
) -> CardFitFacts:
    return CardFitFacts(
        image_logical_size=image,
        current_rect=origin,
        metrics=metrics,
        header_height=header_height,
        footer_height=footer_height,
        image_margin_x=image_margin_x,
        image_margin_y=image_margin_y,
        occupied=occupied,
        orphan_height=orphan_height,
    )


def _oracle_key(rect: GridRect, facts: CardFitFacts):
    image = facts.image_logical_size
    if image is None or int(image[0]) <= 0 or int(image[1]) <= 0:
        return None
    if rect.column != facts.current_rect.column or rect.row != facts.current_rect.row:
        return None
    if not (
        int(facts.min_column_span) <= rect.column_span <= int(facts.max_column_span)
        and int(facts.min_row_span) <= rect.row_span <= int(facts.max_row_span)
    ):
        return None
    if rect.column < facts.safety_column_min or rect.row < facts.safety_row_min:
        return None
    if rect.column + rect.column_span > facts.safety_column_max:
        return None
    if rect.row + rect.row_span > facts.safety_row_max:
        return None
    if any(rects_overlap(rect, occupied) for occupied in facts.occupied):
        return None
    plot = card_fit_plot_size(rect, facts)
    if plot is None:
        return None
    plot_w, plot_h = plot
    image_w, image_h = int(image[0]), int(image[1])
    reading = aspect_contain_box(plot_w, plot_h, (image_w, image_h))
    if reading is None:
        return None
    reading_w, reading_h = reading
    plot_area = float(plot_w * plot_h)
    unused_area = max(0.0, plot_area - float(reading_w * reading_h))
    unused_h = max(0.0, float(plot_h - reading_h))
    current = facts.current_rect
    current_area = current.column_span * current.row_span
    area = rect.column_span * rect.row_span
    return (
        0,
        1 if area > current_area else 0,
        unused_area / plot_area,
        abs(area - current_area),
        abs(rect.column_span - current.column_span)
        + abs(rect.row_span - current.row_span),
        unused_h / float(plot_h),
        rect.row_span,
        rect.column_span,
    )


def brute_force_oracle(facts: CardFitFacts) -> GridRect | None:
    """Independent hug-window search; does not call solve_card_fit."""
    best = None
    for candidate in iter_card_fit_search_rects(facts):
        key = _oracle_key(candidate, facts)
        if key is None:
            continue
        if best is None or key < best[0]:
            best = (key, candidate)
    return None if best is None else best[1]


def _legacy_plot_size(rect: GridRect, metrics, chrome: int) -> tuple[int, int]:
    _x, _y, width, height = rect_to_pixels(rect, metrics)
    return max(1, int(width)), max(1, int(height) - chrome)


def _legacy_key(rect: GridRect, image, metrics, chrome: int):
    width, plot_h = _legacy_plot_size(rect, metrics, chrome)
    reading_w, reading_h = preview_reading_box(width, plot_h, image)
    unused_area = max(0.0, float(width * plot_h - reading_w * reading_h))
    bottom = max(0.0, float(plot_h - reading_h))
    plot_area = max(1.0, float(width * plot_h))
    cost = (unused_area + _LEGACY_LETTERBOX_COST * width * bottom) / plot_area
    return (cost, bottom / max(1.0, float(plot_h)), -(rect.column_span * rect.row_span))


def legacy_fit_rect_for_aspect(origin: GridRect, image, metrics) -> GridRect:
    """Pre-R2 shrink-inside-current then one-axis FIT_SHORT_SIDE_GROW_MAX."""
    chrome = CARD_FIT_CHROME_HEIGHT
    image_w = max(1, int(image[0]))
    image_h = max(1, int(image[1]))
    image_size = (image_w, image_h)
    max_col = min(int(origin.column_span), GRID_MAX_COLUMN_SPAN)
    max_row = min(int(origin.row_span), GRID_MAX_ROW_SPAN)
    best = None
    best_key = None
    for col_span in range(GRID_MIN_COLUMN_SPAN, max_col + 1):
        if int(origin.column) + col_span > origin.column + origin.column_span:
            continue
        for row_span in range(GRID_MIN_ROW_SPAN, max_row + 1):
            if int(origin.row) + row_span > origin.row + origin.row_span:
                continue
            candidate = GridRect(origin.column, origin.row, col_span, row_span)
            key = _legacy_key(candidate, image_size, metrics, chrome)
            if best is None or key < best_key:
                best = candidate
                best_key = key
    if best is None:
        return origin
    width, plot_h = _legacy_plot_size(best, metrics, chrome)
    reading_w, reading_h = preview_reading_box(width, plot_h, image_size)
    leftover_w = max(0.0, float(width - reading_w))
    leftover_h = max(0.0, float(plot_h - reading_h))
    if max(leftover_w, leftover_h) <= GRID_ROW_HEIGHT:
        return best
    grow_rows = leftover_w >= leftover_h
    chosen = best
    chosen_key = best_key
    for extra in range(1, _LEGACY_GROW_MAX + 1):
        col_span = best.column_span + (0 if grow_rows else extra)
        row_span = best.row_span + (extra if grow_rows else 0)
        if col_span > GRID_MAX_COLUMN_SPAN or row_span > GRID_MAX_ROW_SPAN:
            continue
        candidate = GridRect(origin.column, origin.row, col_span, row_span)
        key = _legacy_key(candidate, image_size, metrics, chrome)
        if key < chosen_key:
            chosen = candidate
            chosen_key = key
    return chosen


def _imported_roots(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module.split(".")[0])
    return imported


def _call_names(tree: ast.AST, class_name: str, func_name: str) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef) or item.name != func_name:
                continue
            for child in ast.walk(item):
                if not isinstance(child, ast.Call):
                    continue
                func = child.func
                if isinstance(func, ast.Name):
                    names.add(func.id)
                elif isinstance(func, ast.Attribute):
                    names.add(func.attr)
    return names


def test_card_fit_module_has_no_qt_imports():
    imported = _imported_roots(MODULE_PATH)
    assert "PyQt5" not in imported
    assert "sip" not in imported


@pytest.mark.parametrize(
    "image",
    [
        (1600, 400),
        (400, 1600),
        (800, 800),
        (160, 90),
        (1600, 900),
        (800, 1400),
        (1600, 1200),
        (640, 480),
    ],
)
@pytest.mark.parametrize("footer_height", [CARD_FOOTER_HEIGHT, 0])
def test_card_fit_matches_bruteforce_oracle(image, footer_height):
    metrics = screen_grid_metrics([])
    origin = GridRect(0, 0, 8, 6)
    facts = _facts(origin, image, metrics, footer_height=footer_height)
    product = solve_card_fit(facts)
    oracle = brute_force_oracle(facts)
    assert oracle is not None
    assert product.candidate == oracle
    assert product.reason != REASON_NO_PREVIEW


def test_card_fit_matches_bruteforce_oracle_for_live_chrome_dto(qapp, qtbot):
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QImage
    from PyQt5.QtWidgets import QWidget

    from mf4_analyzer.ui.chart_stack.ultraview.viewport import LOD_FULL, LOD_NO_FOOTER
    from mf4_analyzer.ui.chart_stack.ultraview.widgets import CardViewModel, UltraViewCard

    image = QImage(1600, 900, QImage.Format_ARGB32)
    image.fill(Qt.blue)
    card = UltraViewCard(
        CardViewModel(
            slot_id="tl",
            section="time",
            view_id="v1",
            image=image,
            show_title=True,
            show_source=True,
        )
    )
    qtbot.addWidget(card)
    card.resize(420, 320)
    card.show()
    qtbot.wait(10)

    metrics = screen_grid_metrics([])
    origin = GridRect(2, 4, 8, 6)

    def facts_from_live_card() -> CardFitFacts:
        image_widget = card.findChild(QWidget, "ultraViewCardImage")
        header = card.findChild(QWidget, "ultraViewCardHeader")
        footer = card.findChild(QWidget, "ultraViewCardFooter")
        assert image_widget is not None and header is not None and footer is not None
        contents = image_widget.contentsRect()
        return _facts(
            origin,
            (1600, 900),
            metrics,
            header_height=0 if header.isHidden() else header.height(),
            footer_height=0 if footer.isHidden() else footer.height(),
            image_margin_x=max(0, int(contents.x())),
            image_margin_y=max(0, int(contents.y())),
        )

    card.apply_lod(LOD_FULL, show_title=True, show_source=True)
    qtbot.wait(10)
    full_facts = facts_from_live_card()
    assert full_facts.footer_height > 0
    full_result = solve_card_fit(full_facts)
    assert full_result.candidate == brute_force_oracle(full_facts)

    card.apply_lod(LOD_NO_FOOTER, show_title=True, show_source=True)
    qtbot.wait(10)
    no_footer_facts = facts_from_live_card()
    assert no_footer_facts.footer_height == 0
    no_footer_result = solve_card_fit(no_footer_facts)
    assert no_footer_result.candidate == brute_force_oracle(no_footer_facts)
    assert (
        no_footer_facts.footer_height != full_facts.footer_height
        or no_footer_result.candidate != full_result.candidate
        or no_footer_result.score != full_result.score
    )


def test_card_fit_search_stays_in_the_hug_window():
    metrics = screen_grid_metrics([])
    facts = _facts(GridRect(0, 0, 8, 6), (1550, 800), metrics)
    searched = iter_card_fit_search_rects(facts)
    assert len(searched) <= 1 + (2 * CARD_FIT_SNAP_WINDOW + 1)
    full_board = (GRID_MAX_COLUMN_SPAN - GRID_MIN_COLUMN_SPAN + 1) * (
        GRID_MAX_ROW_SPAN - GRID_MIN_ROW_SPAN + 1
    )
    assert len(searched) < full_board
    result = solve_card_fit(facts)
    assert result.candidate in searched


def test_card_fit_does_not_jump_to_global_min_waste_size():
    metrics = screen_grid_metrics([])
    origin = GridRect(0, 0, 8, 6)
    wide = solve_card_fit(_facts(origin, (1550, 800), metrics)).candidate
    ultra_wide = solve_card_fit(_facts(origin, (1600, 400), metrics)).candidate
    square = solve_card_fit(_facts(origin, (800, 800), metrics)).candidate
    tall = solve_card_fit(_facts(origin, (400, 1600), metrics)).candidate
    assert (wide.column_span, wide.row_span) != (20, 15)
    assert (ultra_wide.column_span, ultra_wide.row_span) != (23, 9)
    assert (square.column_span, square.row_span) != (9, 13)
    assert (tall.column_span, tall.row_span) != (6, 15)
    origin_area = origin.column_span * origin.row_span
    for candidate in (wide, ultra_wide, square, tall):
        assert candidate.column_span * candidate.row_span <= origin_area
        assert candidate.column == origin.column and candidate.row == origin.row


def test_card_fit_keeps_scale_for_the_same_image_at_different_origins():
    metrics = screen_grid_metrics([])
    image = (1600, 900)
    small = solve_card_fit(_facts(GridRect(0, 0, 4, 4), image, metrics)).candidate
    standard = solve_card_fit(_facts(GridRect(0, 0, 8, 6), image, metrics)).candidate
    large = solve_card_fit(_facts(GridRect(0, 0, 12, 8), image, metrics)).candidate
    assert (small.column_span, small.row_span) != (standard.column_span, standard.row_span)
    assert (standard.column_span, standard.row_span) != (large.column_span, large.row_span)
    assert small.column_span * small.row_span < standard.column_span * standard.row_span
    assert standard.column_span * standard.row_span <= large.column_span * large.row_span


def test_card_fit_does_not_collapse_a_large_card_around_a_small_preview():
    metrics = screen_grid_metrics([])
    origin = GridRect(0, 0, 12, 8)
    result = solve_card_fit(_facts(origin, (160, 90), metrics))
    assert result.candidate.column_span > GRID_MIN_COLUMN_SPAN
    assert result.candidate.row_span > GRID_MIN_ROW_SPAN
    assert result.candidate.column_span * result.candidate.row_span > 4 * 4
    origin_area = origin.column_span * origin.row_span
    assert result.candidate.column_span * result.candidate.row_span >= origin_area // 2


def test_card_fit_far_neighbor_does_not_reopen_a_global_search():
    metrics = screen_grid_metrics([])
    origin = GridRect(0, 0, 8, 6)
    image = (1550, 800)
    far_neighbor = GridRect(40, 0, 8, 6)
    facts = _facts(origin, image, metrics, occupied=(far_neighbor,))
    result = solve_card_fit(facts)
    unconstrained = brute_force_oracle(_facts(origin, image, metrics))
    assert result.candidate == unconstrained
    assert not rects_overlap(result.candidate, far_neighbor)
    assert result.candidate.column_span * result.candidate.row_span <= (
        origin.column_span * origin.row_span * 2
    )


def test_card_fit_never_moves_neighbor_cards():
    metrics = screen_grid_metrics([])
    origin = GridRect(0, 0, 8, 6)
    neighbor = GridRect(8, 0, 8, 6)
    image = (1600, 400)
    facts = _facts(origin, image, metrics, occupied=(neighbor,))
    result = solve_card_fit(facts)
    assert result.candidate.column == origin.column
    assert result.candidate.row == origin.row
    assert not rects_overlap(result.candidate, neighbor)
    unconstrained = brute_force_oracle(_facts(origin, image, metrics))
    assert unconstrained is not None
    if unconstrained.column_span > 8:
        assert result.candidate.column_span <= 8

    board = default_board()
    set_layout(board, "grid_2x2")
    self_ref = make_ref("time", "fit-self")
    other_ref = make_ref("fft", "fit-neighbor")
    add_ref(board, self_ref)
    add_ref(board, other_ref)
    template_to_free_grid(board)
    assert set_free_grid_rects(
        board,
        (
            (self_ref, origin),
            (other_ref, neighbor),
        ),
    ) == []
    before_neighbor = neighbor
    assert set_free_grid_rects(board, ((self_ref, result.candidate),)) == []
    placed = {item.ref: item.rect for item in board.free_grid}
    assert placed[other_ref] == before_neighbor
    assert placed[self_ref] == result.candidate
    assert placed[self_ref].column == origin.column
    assert placed[self_ref].row == origin.row


def test_card_fit_reports_structured_no_preview_and_no_space():
    metrics = screen_grid_metrics([])
    origin = GridRect(0, 0, 4, 4)
    empty = solve_card_fit(_facts(origin, None, metrics))
    assert empty.reason == REASON_NO_PREVIEW
    assert empty.improved is False
    assert empty.candidate == origin

    already = solve_card_fit(_facts(origin, (1600, 900), metrics))
    assert already.reason == REASON_NO_IMPROVEMENT
    assert already.improved is False
    assert already.candidate == origin

    undersized = GridRect(0, 0, 2, 2)
    wall_right = GridRect(2, 0, 12, 16)
    wall_below = GridRect(0, 2, 2, 12)
    boxed = solve_card_fit(
        _facts(
            undersized,
            (1600, 900),
            metrics,
            occupied=(wall_right, wall_below),
        )
    )
    unconstrained = brute_force_oracle(_facts(undersized, (1600, 900), metrics))
    assert unconstrained is not None
    assert unconstrained != undersized
    assert boxed.reason == REASON_NO_SPACE
    assert boxed.improved is False
    assert boxed.candidate == undersized

    fitted = solve_card_fit(_facts(GridRect(0, 0, 8, 6), (1600, 900), metrics))
    already_best = solve_card_fit(_facts(fitted.candidate, (1600, 900), metrics))
    assert already_best.reason == REASON_NO_IMPROVEMENT
    assert already_best.improved is False
    assert already_best.candidate == fitted.candidate


def test_fit_rect_for_aspect_wrapper_matches_unconstrained_solver():
    metrics = screen_grid_metrics([])
    origin = GridRect(2, 2, 8, 6)
    image = (1000, 800)
    wrapped = fit_rect_for_aspect(origin, image, metrics)
    facts = unconstrained_card_fit_facts(origin, image, metrics)
    solved = solve_card_fit(facts)
    assert wrapped == solved.candidate == brute_force_oracle(facts)


def test_existing_auto_arrange_is_not_a_loop_of_card_fit():
    tree = ast.parse(COORDINATOR_PATH.read_text(encoding="utf-8"))
    autofit_calls = _call_names(tree, "UltraViewCoordinator", "_on_free_grid_autofit")
    arrange_calls = _call_names(tree, "UltraViewCoordinator", "_on_auto_arrange_free_grid")
    organize_calls = _call_names(tree, "UltraViewCoordinator", "_on_organize_free_grid")
    assert "solve_card_fit" in autofit_calls
    assert "plan_layout" not in autofit_calls
    assert "plan_auto_arrange" in arrange_calls
    assert "solve_card_fit" not in arrange_calls
    assert "solve_card_fit" not in organize_calls

    first = FreeGridPlacement(make_ref("time", "a"), GridRect(0, 8, 8, 6))
    second = FreeGridPlacement(make_ref("fft", "b"), GridRect(8, 8, 8, 6))
    metrics = screen_grid_metrics((first, second))
    plan = plan_auto_arrange((first, second))
    assert plan.accepted
    moved = {ref: rect for ref, rect in plan.committed_updates()}
    assert moved
    assert any(
        rect.column != item.rect.column or rect.row != item.rect.row
        for item in (first, second)
        for rect in [moved.get(item.ref, item.rect)]
    )
    for item in (first, second):
        fitted = solve_card_fit(
            _facts(item.rect, (800, 600), metrics, occupied=(second.rect if item is first else first.rect,))
        )
        assert fitted.candidate.column == item.rect.column
        assert fitted.candidate.row == item.rect.row
