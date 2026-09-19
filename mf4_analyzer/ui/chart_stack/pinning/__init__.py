"""Pin collaborators package.

Keep this init light: do not import sampling, commands, key_router,
presentation, canvas, stack, or the controller façade. Callers import
submodules directly.
"""

__all__ = (
    "PinCommands",
    "PinSampleEvaluator",
    "PinKeyRouter",
    "PinPanelProjector",
)
