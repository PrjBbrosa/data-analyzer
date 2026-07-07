"""Guard against UTF-8-as-latin-1 double-encoded copy in acquisition UI."""

from pathlib import Path

import mf4_analyzer.acquisition_ui.main_window._connection_mixin as cm


def test_no_double_encoded_text_in_connection_mixin():
    src = Path(cm.__file__).read_text(encoding="utf-8")
    bad_prefix = bytes([0xC3, 0xA4, 0xC2, 0xB8, 0xC2, 0xBA]).decode("utf-8")
    assert bad_prefix not in src
    assert "measurement selection 为空" in src
