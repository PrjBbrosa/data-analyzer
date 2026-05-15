"""Band-helper tests for Acquisition Cockpit threshold rows.

The helpers live in ``preflight_estimates`` so the right-pane widget can
format values without owning classifier ladders.
"""

from __future__ import annotations

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.preflight_estimates import (
    band_can_load,
    band_daq_slot,
    band_dropped_frames,
    band_rec_last_rx_age_s,
    band_record_duration_s,
    band_ring_buffer,
)


def test_band_can_load_green_yellow_red_boundaries():
    assert band_can_load(thresholds.CAN_LOAD_GREEN_MAX_PCT - 0.1) == "green"
    assert band_can_load(thresholds.CAN_LOAD_GREEN_MAX_PCT) == "yellow"
    assert band_can_load(thresholds.CAN_LOAD_YELLOW_MAX_PCT - 0.1) == "yellow"
    assert band_can_load(thresholds.CAN_LOAD_YELLOW_MAX_PCT) == "red"


def test_band_daq_slot_green_yellow_red_boundaries():
    assert band_daq_slot(thresholds.DAQ_SLOT_GREEN_MAX_PCT - 0.1) == "green"
    assert band_daq_slot(thresholds.DAQ_SLOT_GREEN_MAX_PCT) == "yellow"
    assert band_daq_slot(thresholds.DAQ_SLOT_YELLOW_MAX_PCT) == "yellow"
    assert band_daq_slot(thresholds.DAQ_SLOT_YELLOW_MAX_PCT + 0.1) == "red"
    assert band_daq_slot(100.0) == "red"


def test_band_record_duration_green_yellow_red_boundaries():
    assert (
        band_record_duration_s(thresholds.RECORD_DURATION_GREEN_MIN_S + 1.0)
        == "green"
    )
    assert (
        band_record_duration_s(thresholds.RECORD_DURATION_GREEN_MIN_S) == "yellow"
    )
    assert (
        band_record_duration_s(thresholds.RECORD_DURATION_YELLOW_MIN_S) == "yellow"
    )
    assert (
        band_record_duration_s(thresholds.RECORD_DURATION_YELLOW_MIN_S - 1.0)
        == "red"
    )


def test_band_ring_buffer_green_yellow_red_boundaries():
    assert band_ring_buffer(thresholds.RING_BUFFER_GREEN_MAX_PCT - 0.1) == "green"
    assert band_ring_buffer(thresholds.RING_BUFFER_GREEN_MAX_PCT) == "yellow"
    assert (
        band_ring_buffer(thresholds.RING_BUFFER_YELLOW_LOW_MAX_PCT - 0.1)
        == "yellow"
    )
    assert band_ring_buffer(thresholds.RING_BUFFER_YELLOW_LOW_MAX_PCT) == "red"
    assert band_ring_buffer(thresholds.RING_BUFFER_RED_MAX_PCT) == "red"
    assert band_ring_buffer(thresholds.RING_BUFFER_RED_DROP_MAX_PCT) == "red"


def test_band_dropped_frames_green_yellow_red_boundaries():
    assert band_dropped_frames(0) == "green"
    assert band_dropped_frames(1) == "yellow"
    assert band_dropped_frames(thresholds.DROPPED_FRAMES_YELLOW_MAX_PER_WINDOW) == (
        "yellow"
    )
    assert (
        band_dropped_frames(thresholds.DROPPED_FRAMES_RED_PER_10S + 1) == "red"
    )
    assert band_dropped_frames(thresholds.DROPPED_FRAMES_PROMPT_TOTAL + 1) == "red"


def test_band_rec_last_rx_age_s_green_yellow_red_boundaries():
    assert (
        band_rec_last_rx_age_s(thresholds.REC_LAST_RX_YELLOW_MIN_S - 0.01)
        == "green"
    )
    assert (
        band_rec_last_rx_age_s(thresholds.REC_LAST_RX_YELLOW_MIN_S) == "yellow"
    )
    assert (
        band_rec_last_rx_age_s(thresholds.REC_LAST_RX_RED_MIN_S - 0.01) == "yellow"
    )
    assert band_rec_last_rx_age_s(thresholds.REC_LAST_RX_RED_MIN_S) == "red"
