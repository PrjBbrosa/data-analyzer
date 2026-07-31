"""Regression tests for the real-desktop popup pixel acceptance guard."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_probe_module():
    probe_path = Path("scripts/probe_signal_picker_popup_shell.py")
    spec = importlib.util.spec_from_file_location("popup_shell_probe", probe_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _host_sample():
    return {"rgb": [196, 24, 67]}


def _surface_corners():
    return {
        "top_left": _host_sample(),
        "top_right": _host_sample(),
        "bottom_left": _host_sample(),
        "bottom_right": _host_sample(),
    }


def test_surface_acceptance_rejects_hidden_all_host_false_positive():
    """A hidden popup can mimic transparent corners across every sample."""
    probe = _load_probe_module()

    result = probe._evaluate_surface(
        visible=False,
        corners=_surface_corners(),
        interior=_host_sample(),
    )

    assert result["corners_match_host"] is True
    assert result["interior_differs_from_host"] is False
    assert result["passed"] is False


def test_surface_acceptance_requires_visible_non_host_interior_pixel():
    """Visible geometry alone is insufficient if the host covers the surface."""
    probe = _load_probe_module()

    result = probe._evaluate_surface(
        visible=True,
        corners=_surface_corners(),
        interior=_host_sample(),
    )

    assert result["visible"] is True
    assert result["passed"] is False


def test_surface_acceptance_allows_visible_surface_with_transparent_corners():
    probe = _load_probe_module()

    result = probe._evaluate_surface(
        visible=True,
        corners=_surface_corners(),
        interior={"rgb": [252, 252, 251]},
    )

    assert result["interior_differs_from_host"] is True
    assert result["passed"] is True
