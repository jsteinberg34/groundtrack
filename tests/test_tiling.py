"""
Unit tests for groundtrack.tiling.

Covers time-window padding, along-track box chunking with overlap, antimeridian
box bounds, short-track / invalid-parameter edge cases, and the download-request
conversion. Uses obspy's CPU-only geodesy -- no network.
"""

from datetime import datetime, timedelta

import pytest

from groundtrack.tiling import (
    pad_window,
    track_to_box_windows,
    box_windows_to_download_requests,
)
from groundtrack.types import TrackPoint

from conftest import EPOCH


# --------------------------------------------------------------------------- #
# pad_window
# --------------------------------------------------------------------------- #

def test_pad_window_shifts_start_earlier_and_end_later():
    t_enter = EPOCH
    t_exit = EPOCH + timedelta(minutes=5)
    start, end = pad_window(t_enter, t_exit, pre_pad_minutes=2, post_pad_minutes=13)
    assert start == t_enter - timedelta(minutes=2)
    assert end == t_exit + timedelta(minutes=13)


# --------------------------------------------------------------------------- #
# track_to_box_windows -- happy path
# --------------------------------------------------------------------------- #

def test_chunking_produces_sequential_overlapping_boxes(equator_track):
    windows = track_to_box_windows(
        equator_track, chunk_km=300.0, overlap_km=50.0, corridor_km=100.0
    )

    assert len(windows) >= 2

    # box_index / box_id increase monotonically from zero.
    assert [w.box.box_index for w in windows] == list(range(len(windows)))
    assert windows[0].box.box_id == "box_000"
    assert windows[1].box.box_id == "box_001"

    # Consecutive boxes overlap in their track-index ranges.
    for prev, nxt in zip(windows, windows[1:]):
        assert nxt.first_track_index <= prev.last_track_index

    # The final box reaches the last track point.
    assert windows[-1].last_track_index == len(equator_track) - 1


def test_latitude_bounds_padded_by_corridor_and_clamped(make_track):
    # Track near the north pole so corridor padding clamps at +90.
    track = make_track(lat=89.5, lon_step=0.5, n=20)
    windows = track_to_box_windows(
        track, chunk_km=300.0, overlap_km=50.0, corridor_km=100.0
    )
    box = windows[0].box
    # corridor of 100 km is ~0.9 deg; lat_max must clamp at 90, not exceed it.
    assert box.lat_max == pytest.approx(90.0)
    assert box.lat_min < 89.5  # padded below the track latitude


def test_box_window_times_and_counts(equator_track):
    windows = track_to_box_windows(
        equator_track, chunk_km=300.0, overlap_km=50.0, corridor_km=100.0
    )
    w = windows[0]
    chunk = equator_track[w.first_track_index : w.last_track_index + 1]

    assert w.t_enter == chunk[0].time
    assert w.t_exit == chunk[-1].time
    # Download window equals the pass window padded by the defaults (2 / 13).
    assert w.t_download_start == w.t_enter - timedelta(minutes=2)
    assert w.t_download_end == w.t_exit + timedelta(minutes=13)
    assert w.n_points == w.last_track_index - w.first_track_index + 1
    assert w.n_points == len(chunk)


# --------------------------------------------------------------------------- #
# track_to_box_windows -- antimeridian
# --------------------------------------------------------------------------- #

def test_dateline_crossing_chunk_has_wrapped_longitude_bounds():
    lons = [178.0, 178.5, 179.0, 179.5, -180.0, -179.5, -179.0, -178.5]
    track = [
        TrackPoint(time=EPOCH + timedelta(seconds=10 * i), lat=0.0, lon=lon)
        for i, lon in enumerate(lons)
    ]
    windows = track_to_box_windows(
        track, chunk_km=300.0, overlap_km=50.0, corridor_km=100.0
    )
    box = windows[0].box
    # lon_min > lon_max signals the box spans the antimeridian.
    assert box.lon_min > box.lon_max


# --------------------------------------------------------------------------- #
# track_to_box_windows -- edge cases
# --------------------------------------------------------------------------- #

def test_empty_track_returns_no_windows():
    assert track_to_box_windows([]) == []


def test_single_point_track_returns_no_windows(make_track):
    assert track_to_box_windows(make_track(n=1)) == []


def test_overlap_not_smaller_than_chunk_raises(equator_track):
    with pytest.raises(ValueError):
        track_to_box_windows(equator_track, chunk_km=100.0, overlap_km=100.0)
    with pytest.raises(ValueError):
        track_to_box_windows(equator_track, chunk_km=100.0, overlap_km=150.0)


# --------------------------------------------------------------------------- #
# box_windows_to_download_requests
# --------------------------------------------------------------------------- #

def test_download_requests_map_keys_and_values(equator_track):
    windows = track_to_box_windows(
        equator_track, chunk_km=300.0, overlap_km=50.0, corridor_km=100.0
    )
    requests = box_windows_to_download_requests(windows)

    assert len(requests) == len(windows)

    expected_keys = {
        "box_id",
        "lat_min",
        "lat_max",
        "lon_min",
        "lon_max",
        "t_start_utc",
        "t_end_utc",
    }
    for req, w in zip(requests, windows):
        assert set(req.keys()) == expected_keys
        assert req["box_id"] == w.box.box_id
        assert req["lat_min"] == w.box.lat_min
        assert req["lat_max"] == w.box.lat_max
        assert req["lon_min"] == w.box.lon_min
        assert req["lon_max"] == w.box.lon_max
        assert req["t_start_utc"] == w.t_download_start
        assert req["t_end_utc"] == w.t_download_end
