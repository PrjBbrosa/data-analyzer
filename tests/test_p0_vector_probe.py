import sys

import pytest


def test_vector_probe_imports_on_any_platform():
    """Import must succeed on macOS -- no top-level python-can dependency."""
    from can_logger.p0 import vector_probe  # noqa: F401


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows behavior only")
def test_vector_probe_raises_clear_error_off_windows():
    from can_logger.p0.vector_probe import list_vector_channels

    with pytest.raises(RuntimeError, match="(?i)vector|windows"):
        list_vector_channels()
