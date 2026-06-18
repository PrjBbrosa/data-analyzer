"""Shared module-level constants for CockpitMainWindow mixins.

These were originally at module level in the monolithic main_window.py.
Putting them here avoids circular imports when the mixin files are imported
before the package __init__.py finishes.
"""

# Spec Product Decisions — DBC selector tooltip (verbatim).
DBC_DISABLED_TOOLTIP = "Reserved for raw CAN capture; XCP path uses A2L."

# Spec Product Decisions — mode tabs.
REPLAY_TAB_TITLE = "回放"
HISTORY_TAB_TITLE = "历史"
MODE_SEGMENTS = (
    ("capture", "采集", 0),
    ("replay", REPLAY_TAB_TITLE, 1),
    ("history", HISTORY_TAB_TITLE, 2),
)

# Spec §State Machine `Disconnected` failure surface text.
DROPPED_FRAMES_PROMPT_TITLE = "丢帧过多"
DROPPED_FRAMES_PROMPT_TEXT = "丢帧过多 · 是否停止？"
