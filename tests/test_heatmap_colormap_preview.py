"""Authoring preview must carry the exact shipping LUT, not another palette."""
import json
import re

import pytest

from mf4_analyzer.colormaps import DEFAULT_HEATMAP_CMAP, list_colormap_specs, load_rgb_lut
from tools.preview_heatmap_colormaps import build_preview, main


@pytest.mark.parametrize("ident", [s.id for s in list_colormap_specs() if s.provider == "rgb_lut"])
def test_preview_embeds_shipping_rgb_and_evidence(ident):
    page = build_preview(ident)
    payload = json.loads(re.search(
        r'<script id="palette-data" type="application/json">(.*?)</script>', page,
    ).group(1))
    assert payload["id"] == ident
    assert payload["rgb"] == [list(row) for row in load_rgb_lut(ident)]
    assert len(payload["baseline"]) == 256
    assert payload["evidence_level"]
    assert payload["source_note"]


def test_preview_unknown_id_fails_without_writing_a_fallback(tmp_path, capsys):
    output = tmp_path / "preview.html"
    assert main(["--id", "missing-palette", "--output", str(output)]) == 1
    assert not output.exists()
    assert "missing-palette" in capsys.readouterr().err


def test_preview_cli_uses_head_default_and_creates_parent(tmp_path):
    output = tmp_path / "nested" / "preview.html"
    assert main(["--output", str(output)]) == 0
    assert DEFAULT_HEATMAP_CMAP in output.read_text(encoding="utf-8")
