"""The -m entry must dispatch through the canonical module name."""

from pathlib import Path

import can_logger.p0.a2l_probe as probe


def test_dunder_main_dispatches_to_canonical_module():
    src = Path(probe.__file__).read_text(encoding="utf-8")
    assert "from can_logger.p0.a2l_probe import main as _canonical_main" in src
