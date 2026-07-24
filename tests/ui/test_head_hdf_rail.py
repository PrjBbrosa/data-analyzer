"""Tests for HEAD .hdf grouped rail: 1 card + 2-level collapsible tree."""
import numpy as np
import pandas as pd
import pytest
from pathlib import Path
from PyQt5.QtCore import Qt


def _make_fd(filepath, label_suffix, fs=1000.0, n_rows=100, channels=None):
    """Build a minimal FileData with the given label_suffix."""
    from mf4_analyzer.io import FileData
    if channels is None:
        channels = ['ch_a', 'ch_b']
    data = pd.DataFrame({ch: np.zeros(n_rows) for ch in channels})
    units = {ch: 'V' for ch in channels}
    fd = FileData(filepath, data, list(data.columns), units, 0,
                  label_suffix=label_suffix)
    fd.fs = fs
    fd.time_array = np.arange(n_rows, dtype=float) / fs
    return fd


# ── Navigator tests ──────────────────────────────────────────────────────────

def test_navigator_same_filepath_one_card(qapp, tmp_path):
    """Two fids with same filepath + non-empty label_suffix → 1 card."""
    from mf4_analyzer.ui.file_navigator import FileNavigator
    fp = tmp_path / "synth.hdf"
    fp.touch()
    nav = FileNavigator()
    fd1 = _make_fd(fp, label_suffix="2x", fs=2000.0, n_rows=200, channels=['A'])
    fd2 = _make_fd(fp, label_suffix="1x", fs=1000.0, n_rows=100, channels=['B'])
    nav.add_file("f0", fd1)
    nav.add_file("f1", fd2)
    assert nav.file_list_count() == 1, "same-filepath HDF must show as 1 card"


def test_navigator_remove_one_fid_card_stays(qapp, tmp_path):
    """remove_file for one fid keeps the card (group still has another fid)."""
    from mf4_analyzer.ui.file_navigator import FileNavigator
    fp = tmp_path / "synth.hdf"
    fp.touch()
    nav = FileNavigator()
    fd1 = _make_fd(fp, label_suffix="2x", channels=['A'])
    fd2 = _make_fd(fp, label_suffix="1x", channels=['B'])
    nav.add_file("f0", fd1)
    nav.add_file("f1", fd2)
    nav.remove_file("f0")
    assert nav.file_list_count() == 1, "card must remain after removing one of two fids"


def test_navigator_remove_all_fids_card_gone(qapp, tmp_path):
    """remove_file for both fids deletes the card."""
    from mf4_analyzer.ui.file_navigator import FileNavigator
    fp = tmp_path / "synth.hdf"
    fp.touch()
    nav = FileNavigator()
    fd1 = _make_fd(fp, label_suffix="2x", channels=['A'])
    fd2 = _make_fd(fp, label_suffix="1x", channels=['B'])
    nav.add_file("f0", fd1)
    nav.add_file("f1", fd2)
    nav.remove_file("f0")
    nav.remove_file("f1")
    assert nav.file_list_count() == 0, "card must be gone after removing all fids"


# ── Channel tree tests ────────────────────────────────────────────────────────

def test_channel_tree_nested_structure(qapp, tmp_path):
    """Two fids → 1 file node at top level, 2 raster children, channels at 3rd level."""
    from mf4_analyzer.ui.widgets import MultiFileChannelWidget
    fp = tmp_path / "synth.hdf"
    fp.touch()
    w = MultiFileChannelWidget()
    fd1 = _make_fd(fp, label_suffix="2x", fs=2000.0, channels=['A', 'B'])
    fd2 = _make_fd(fp, label_suffix="1x", fs=1000.0, channels=['C'])
    w.add_file("f0", fd1)
    w.add_file("f1", fd2)

    # Should have 1 top-level item (the file node)
    assert w.tree.topLevelItemCount() == 1, "nested: 1 file node at top level"
    file_node = w.tree.topLevelItem(0)
    d = file_node.data(0, Qt.UserRole)
    assert d and d[0] == 'source', f"file node role should be 'source', got {d}"

    # Should have 2 raster children
    assert file_node.childCount() == 2, "2 raster subgroup children"
    r0 = file_node.child(0)
    rd0 = r0.data(0, Qt.UserRole)
    assert rd0 and rd0[0] == 'raster', f"raster node role should be 'raster', got {rd0}"

    # Raster node labels use kHz for rates ≥ 1000 Hz
    r1 = file_node.child(1)
    assert "kHz" in r0.text(0), f"fast raster (2000 Hz) label should use kHz, got {r0.text(0)!r}"
    assert "2.0 kHz" in r0.text(0), f"fast raster label should be '2.0 kHz', got {r0.text(0)!r}"
    assert "kHz" in r1.text(0), f"slow raster (1000 Hz) label should use kHz, got {r1.text(0)!r}"
    assert "1.0 kHz" in r1.text(0), f"slow raster label should be '1.0 kHz', got {r1.text(0)!r}"

    # Channels at 3rd level
    assert r0.childCount() == 2, "fast raster has 2 channel leaves"
    ch0 = r0.child(0)
    cd0 = ch0.data(0, Qt.UserRole)
    assert cd0 and cd0[0] == 'channel', f"channel leaf role should be 'channel', got {cd0}"


def test_refresh_hdf_raster_keeps_other_rasters_and_view_state(qapp, tmp_path):
    """Editing one HDF raster must not detach or rebuild its sibling raster."""
    from mf4_analyzer.ui.widgets import MultiFileChannelWidget

    fp = tmp_path / "synth.hdf"
    fp.touch()
    w = MultiFileChannelWidget()
    fd0 = _make_fd(fp, label_suffix="2x", channels=["A", "B"])
    fd1 = _make_fd(fp, label_suffix="1x", channels=["C"])
    w.add_file("f0", fd0)
    w.add_file("f1", fd1)
    w.set_attached_file_ids(["f0", "f1"])
    w.set_checked_channels([("f0", "A"), ("f1", "C")])
    w.set_hidden_channels([("f0", "A")])
    w.set_channel_colors({("f0", "A"): "#abcdef"})

    w.refresh_file(
        "f0", _make_fd(fp, label_suffix="2x", channels=["A", "d_dt_A"])
    )

    assert w.get_attached_file_ids() == ["f0", "f1"]
    assert [row[:2] for row in w.get_checked_channels()] == [
        ("f0", "A"), ("f1", "C"),
    ]
    assert w.get_hidden_channels() == [("f0", "A")]
    assert w.get_channel_colors()[("f0", "A")] == "#abcdef"
    source = w.tree.topLevelItem(0)
    assert source.childCount() == 2
    assert [source.child(i).data(0, Qt.UserRole)[1] for i in range(2)] == [
        "f0", "f1",
    ]
    refreshed = w._raster_items["f0"]
    assert [refreshed.child(i).text(0) for i in range(refreshed.childCount())] == [
        "A", "d_dt_A",
    ]


def test_channel_tree_check_raster_selects_all_channels(qapp, tmp_path):
    """Checking a raster node selects all its channel leaves."""
    from mf4_analyzer.ui.widgets import MultiFileChannelWidget
    fp = tmp_path / "synth.hdf"
    fp.touch()
    w = MultiFileChannelWidget()
    fd1 = _make_fd(fp, label_suffix="2x", fs=2000.0, channels=['A', 'B'])
    w.add_file("f0", fd1)

    file_node = w.tree.topLevelItem(0)
    raster_node = file_node.child(0)

    # Check the raster node
    raster_node.setCheckState(0, Qt.Checked)
    # Process item changed
    qapp.processEvents()

    # Both channels should be checked
    for i in range(raster_node.childCount()):
        ch = raster_node.child(i)
        assert ch.checkState(0) == Qt.Checked, f"channel {i} should be checked"


def test_get_checked_channels_returns_fid_ch_color(qapp, tmp_path):
    """get_checked_channels() returns (fid, ch, color) tuples."""
    from mf4_analyzer.ui.widgets import MultiFileChannelWidget
    fp = tmp_path / "synth.hdf"
    fp.touch()
    w = MultiFileChannelWidget()
    fd1 = _make_fd(fp, label_suffix="2x", channels=['A', 'B'])
    fd2 = _make_fd(fp, label_suffix="1x", channels=['C'])
    w.add_file("f0", fd1)
    w.add_file("f1", fd2)

    # Check raster 0's channels
    file_node = w.tree.topLevelItem(0)
    raster0 = file_node.child(0)
    raster0.setCheckState(0, Qt.Checked)
    qapp.processEvents()

    checked = w.get_checked_channels()
    assert len(checked) > 0, "should have checked channels"
    for fid, ch, color in checked:
        assert isinstance(fid, str)
        assert isinstance(ch, str)
        assert color.startswith('#')
    # Only channels from raster0 should be checked
    fids = {fid for fid, ch, color in checked}
    assert "f0" in fids
    assert "f1" not in fids


def test_channel_tree_remove_one_raster_file_node_stays(qapp, tmp_path):
    """remove_file for one raster keeps the file node (group still has another)."""
    from mf4_analyzer.ui.widgets import MultiFileChannelWidget
    fp = tmp_path / "synth.hdf"
    fp.touch()
    w = MultiFileChannelWidget()
    fd1 = _make_fd(fp, label_suffix="2x", channels=['A'])
    fd2 = _make_fd(fp, label_suffix="1x", channels=['B'])
    w.add_file("f0", fd1)
    w.add_file("f1", fd2)

    w.remove_file("f0")

    # File node should still be there
    assert w.tree.topLevelItemCount() == 1, "file node should remain"
    file_node = w.tree.topLevelItem(0)
    assert file_node.childCount() == 1, "1 raster child should remain"


def test_channel_tree_remove_both_rasers_file_node_gone(qapp, tmp_path):
    """remove_file for both rasers deletes the file node."""
    from mf4_analyzer.ui.widgets import MultiFileChannelWidget
    fp = tmp_path / "synth.hdf"
    fp.touch()
    w = MultiFileChannelWidget()
    fd1 = _make_fd(fp, label_suffix="2x", channels=['A'])
    fd2 = _make_fd(fp, label_suffix="1x", channels=['B'])
    w.add_file("f0", fd1)
    w.add_file("f1", fd2)

    w.remove_file("f0")
    w.remove_file("f1")

    assert w.tree.topLevelItemCount() == 0, "file node should be gone"


# ── Flat (single mf4/csv) regression tests ───────────────────────────────────

def test_flat_single_file_two_level(qapp, tmp_path):
    """A plain FileData (label_suffix='') renders as flat 2-level tree."""
    from mf4_analyzer.ui.widgets import MultiFileChannelWidget
    fp = tmp_path / "test.csv"
    fd = _make_fd(fp, label_suffix="", channels=['rpm', 'temp'])
    w = MultiFileChannelWidget()
    w.add_file("f0", fd)

    # 1 top-level file node
    assert w.tree.topLevelItemCount() == 1
    file_node = w.tree.topLevelItem(0)
    d = file_node.data(0, Qt.UserRole)
    assert d and d[0] == 'file', f"flat mode: top node role should be 'file', got {d}"

    # Channels directly under file node
    assert file_node.childCount() == 2


def test_flat_get_checked_channels_works(qapp, tmp_path):
    """get_checked_channels() works for flat single-file case."""
    from mf4_analyzer.ui.widgets import MultiFileChannelWidget
    fp = tmp_path / "test.csv"
    fd = _make_fd(fp, label_suffix="", channels=['rpm', 'temp'])
    w = MultiFileChannelWidget()
    w.add_file("f0", fd)

    # Check one channel
    file_node = w.tree.topLevelItem(0)
    file_node.child(0).setCheckState(0, Qt.Checked)
    qapp.processEvents()

    checked = w.get_checked_channels()
    assert len(checked) == 1
    assert checked[0][0] == "f0"
    assert checked[0][1] == 'rpm'
