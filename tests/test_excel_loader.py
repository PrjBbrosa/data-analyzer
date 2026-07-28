from __future__ import annotations

import pandas as pd
import pytest

from mf4_analyzer.io import loader
from mf4_analyzer.io.loader import DataLoader


@pytest.mark.parametrize(
    ("filename", "engine", "available_flag"),
    [
        ("book.xlsx", "openpyxl", "HAS_OPENPYXL"),
        ("book.xls", "xlrd", "HAS_XLRD"),
    ],
)
def test_excel_loader_selects_engine_from_extension(
    monkeypatch, filename, engine, available_flag,
):
    monkeypatch.setattr(loader, available_flag, True)
    calls = []

    def fake_read_excel(path, **kwargs):
        calls.append((path, kwargs))
        return pd.DataFrame({"Time": [0.0, 0.1], "sig": [1.0, 2.0]})

    monkeypatch.setattr(pd, "read_excel", fake_read_excel)

    DataLoader.load_excel(filename)

    assert calls == [(filename, {"engine": engine})]


def test_excel_loader_rejects_unknown_excel_extension():
    with pytest.raises(ValueError, match="unsupported Excel extension"):
        DataLoader.load_excel("book.ods")


def test_xls_missing_xlrd_has_specific_dependency_error(monkeypatch):
    monkeypatch.setattr(loader, "HAS_XLRD", False)

    with pytest.raises(ImportError, match="xlrd"):
        DataLoader.load_excel("legacy.xls")
