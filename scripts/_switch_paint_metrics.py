"""Read paint-time facts without importing Qt or starting the probe app."""


def canvas_aa_state(canvas):
    """Prefer the rendered slice child over an owner's possibly stale flag."""
    if canvas is None:
        return None
    if hasattr(canvas, "_slice_aa_on"):
        item = getattr(canvas, "_slice_curve", None)
        if item is None:
            return False
        curve = getattr(item, "curve", item)
        return bool(curve.opts.get("antialias", False))
    quality = getattr(canvas, "_quality", None)
    return (
        getattr(quality, "aa_on", None) if quality is not None
        else getattr(canvas, "_aa_on", None)
    )


def transition_paint_facts(canvas):
    """Snapshot BEFORE paint: acknowledgement can start a fade inside paint."""
    facts = {
        "section": None, "phase": "idle", "generation": None,
        "target": False, "held": False,
    }
    if canvas is None:
        return facts
    stack = getattr(canvas.window(), "chart_stack", None)
    if stack is None:
        return facts
    card = stack._card_for_canvas(canvas)
    facts["section"] = getattr(card, "_chart_mode", None)
    controller = stack.page_transition()
    token = stack._discrete_quality_hold_token
    facts["held"] = any(canvas is held for held in stack._discrete_quality_hold_canvases)
    facts["target"] = facts["held"]
    facts["generation"] = getattr(token, "request_generation", None)
    if controller.is_active():
        facts["phase"] = "fade"
    elif token is not None or controller.is_pending():
        facts["phase"] = "awaiting-paint"
    return facts
