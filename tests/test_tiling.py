"""
Unit tests for groundtrack.tiling.

Covers time-window padding, along-track box chunking with overlap, antimeridian
box bounds, short-track / invalid-parameter edge cases, the download-request
conversion, and the ocean-box filter. Uses obspy's CPU-only geodesy -- no network.
"""

import warnings
from datetime import datetime, timedelta, timezone

import pytest

from groundtrack.tiling import (
    pad_window,
    track_to_box_windows,
    box_windows_to_download_requests,
    filter_ocean_boxes,
    derive_post_pad_minutes,
    max_corridor_km,
)
from groundtrack.types import GeoBox, BoxWindow, TrackPoint

from conftest import EPOCH


# --------------------------------------------------------------------------- #
# Helper
# --------------------------------------------------------------------------- #

_T = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _make_box_window(lat_min, lat_max, lon_min, lon_max):
    """Minimal BoxWindow for filter_ocean_boxes tests (only box bounds matter)."""
    box = GeoBox(lat_min=lat_min, lat_max=lat_max, lon_min=lon_min, lon_max=lon_max, box_index=0)
    return BoxWindow(
        box=box, t_enter=_T, t_exit=_T,
        t_download_start=_T, t_download_end=_T,
        first_track_index=0, last_track_index=1, n_points=2,
    )


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
        equator_track, chunk_km=300.0, overlap_km=50.0, corridor_km=100.0,
        skip_ocean=False,
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
        track, chunk_km=300.0, overlap_km=50.0, corridor_km=100.0,
        skip_ocean=False,
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
    # Pre-pad is the fixed default; post-pad is derived from corridor_km.
    assert w.t_download_start == w.t_enter - timedelta(minutes=2)
    assert w.t_download_end == w.t_exit + timedelta(
        minutes=derive_post_pad_minutes(corridor_km=100.0)
    )
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
        track, chunk_km=300.0, overlap_km=50.0, corridor_km=100.0,
        skip_ocean=False,
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


# --------------------------------------------------------------------------- #
# filter_ocean_boxes
# --------------------------------------------------------------------------- #

def test_filter_ocean_boxes_drops_all_ocean_box():
    # Mid-Pacific: no land between 5-10°N, 160-155°W.
    w = _make_box_window(5, 10, -160, -155)
    assert filter_ocean_boxes([w]) == []


def test_filter_ocean_boxes_keeps_land_box():
    # US interior (Kansas/Nebraska): entirely over land.
    w = _make_box_window(38, 42, -100, -95)
    assert filter_ocean_boxes([w]) == [w]


def test_filter_ocean_boxes_keeps_coastal_mixed_box():
    # US West Coast: straddles the California coastline, part ocean part land.
    w = _make_box_window(35, 40, -125, -120)
    assert filter_ocean_boxes([w]) == [w]


def test_filter_ocean_boxes_handles_antimeridian_crossing():
    # Open Pacific straddling the dateline (lon_min > lon_max).
    # Naive linspace(179, -179, 5) = [179, 90, 0, -90, -179] — sweeps the globe
    # and could falsely hit land at 90°E (Indian Ocean / India at higher lats).
    # The correct split samples only the actual box near ±180°.
    w = _make_box_window(-5, 5, 179, -179)
    assert filter_ocean_boxes([w]) == []


def test_filter_ocean_boxes_empty_input():
    assert filter_ocean_boxes([]) == []


# --------------------------------------------------------------------------- #
# track_to_box_windows -- skip_ocean parameter
# --------------------------------------------------------------------------- #

def test_skip_ocean_true_filters_ocean_boxes(equator_track):
    # The equator track runs 0°–19.5°E. The first box (~0–2.7°E) is entirely
    # over the Gulf of Guinea (open ocean) and must be dropped when skip_ocean=True.
    all_boxes = track_to_box_windows(equator_track, skip_ocean=False)
    kept_boxes = track_to_box_windows(equator_track, skip_ocean=True)
    assert len(kept_boxes) < len(all_boxes)


def test_skip_ocean_false_returns_all_boxes(equator_track):
    # skip_ocean=False must reproduce the pre-filter box count exactly.
    all_boxes = track_to_box_windows(equator_track, skip_ocean=False)
    default_no_skip = track_to_box_windows(
        equator_track, chunk_km=300.0, overlap_km=50.0, corridor_km=100.0,
        pre_pad_minutes=2, post_pad_minutes=13, skip_ocean=False,
    )
    assert len(all_boxes) == len(default_no_skip)


def test_skip_ocean_default_is_true(equator_track):
    # Calling without skip_ocean should behave identically to skip_ocean=True.
    implicit = track_to_box_windows(equator_track)
    explicit = track_to_box_windows(equator_track, skip_ocean=True)
    assert len(implicit) == len(explicit)


# --------------------------------------------------------------------------- #
# Derived post-pad
#
# The post-pad is an acoustic travel time: the slant range from the object to
# the farthest station in the corridor, divided by the celerity. Constants come
# from Neidhart et al. (2021). See the change's evidence.md for the numbers
# these tests pin.
# --------------------------------------------------------------------------- #

def test_derived_post_pad_grows_with_corridor_below_the_cap():
    # Below the envelope cap the slant range, and so the pad, tracks corridor width.
    assert derive_post_pad_minutes(corridor_km=50.0) < derive_post_pad_minutes(
        corridor_km=100.0
    )
    assert derive_post_pad_minutes(corridor_km=100.0) < derive_post_pad_minutes(
        corridor_km=150.0
    )


def test_derived_post_pad_is_capped_by_the_envelope():
    # Past the envelope no signal has ever been observed, so the pad stops growing.
    assert derive_post_pad_minutes(corridor_km=250.0) == pytest.approx(
        derive_post_pad_minutes(corridor_km=400.0)
    )


def test_derived_post_pad_grows_as_celerity_falls():
    # Slower propagation means a later arrival.
    assert derive_post_pad_minutes(200.0, celerity_km_s=0.36) < derive_post_pad_minutes(
        200.0, celerity_km_s=0.30
    )
    assert derive_post_pad_minutes(200.0, celerity_km_s=0.30) < derive_post_pad_minutes(
        200.0, celerity_km_s=0.24
    )


def test_derived_post_pad_matches_hand_computed_values():
    # corridor 100: sqrt(100^2 + 100^2) = 141.42 km, /0.30 + 60 s
    assert derive_post_pad_minutes(corridor_km=100.0) == pytest.approx(8.857, abs=1e-3)
    # corridor 200: sqrt(200^2 + 100^2) = 223.6 km, capped at 215, /0.30 + 60 s
    assert derive_post_pad_minutes(corridor_km=200.0) == pytest.approx(12.944, abs=1e-3)


def test_max_corridor_uses_the_lowest_boom_altitude():
    # sqrt(215^2 - 46^2). Using the 100 km continuum ceiling would give 190.3 km
    # and warn spuriously on the 200 km default.
    assert max_corridor_km() == pytest.approx(210.0, abs=0.1)
    assert max_corridor_km() > 200.0


def test_max_slant_is_not_a_public_parameter():
    # Structural guard: the envelope is empirical survey data, not a caller
    # preference, and the only motive to lower it is downloading less data.
    import inspect
    from groundtrack.pipeline import run_pipeline

    for fn in (track_to_box_windows, run_pipeline):
        names = set(inspect.signature(fn).parameters)
        assert not {"max_slant_km", "MAX_SLANT_KM"} & names


def test_derived_post_pad_ignores_propagated_altitude(equator_track):
    # SGP4 reports orbital altitude (~140 km on a decaying object), not the
    # acoustic source altitude (~65 km). It must not reach the derivation.
    low = [TrackPoint(time=p.time, lat=p.lat, lon=p.lon, altitude_km=80.0)
           for p in equator_track]
    high = [TrackPoint(time=p.time, lat=p.lat, lon=p.lon, altitude_km=400.0)
            for p in equator_track]
    w_low = track_to_box_windows(low, corridor_km=100.0, skip_ocean=False)[0]
    w_high = track_to_box_windows(high, corridor_km=100.0, skip_ocean=False)[0]
    assert (w_low.t_download_end - w_low.t_exit) == (
        w_high.t_download_end - w_high.t_exit
    )


def test_explicit_post_pad_bypasses_the_derivation(equator_track):
    # An explicit value wins exactly, even where the derivation disagrees.
    w = track_to_box_windows(
        equator_track, corridor_km=100.0, post_pad_minutes=20.0, skip_ocean=False
    )[0]
    assert w.t_download_end == w.t_exit + timedelta(minutes=20.0)


# --------------------------------------------------------------------------- #
# Silent-failure warnings
# --------------------------------------------------------------------------- #

def test_too_short_post_pad_warns_and_is_still_honoured(equator_track):
    # A clipped arrival is indistinguishable from no detection, so this must be loud.
    with pytest.warns(UserWarning, match="shorter than"):
        w = track_to_box_windows(
            equator_track, corridor_km=200.0, post_pad_minutes=5.0, skip_ocean=False
        )[0]
    assert w.t_download_end == w.t_exit + timedelta(minutes=5.0)


def test_sufficient_post_pad_does_not_warn(equator_track):
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        track_to_box_windows(
            equator_track, corridor_km=200.0, post_pad_minutes=20.0, skip_ocean=False
        )


def test_corridor_beyond_envelope_warns_and_is_still_honoured(equator_track):
    with pytest.warns(UserWarning, match="detectability envelope"):
        windows = track_to_box_windows(
            equator_track, corridor_km=250.0, skip_ocean=False
        )
    assert windows  # corridor still applied, not clamped


def test_default_corridor_does_not_warn(equator_track):
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        track_to_box_windows(equator_track, skip_ocean=False)


def test_derive_post_pad_rejects_nonsense_inputs():
    # A negative celerity silently yields a NEGATIVE pad, which would put
    # t_download_end before t_exit. An inverted window is indistinguishable
    # from a normal short download, so it must fail loudly.
    with pytest.raises(ValueError, match="celerity_km_s"):
        derive_post_pad_minutes(200.0, celerity_km_s=0.0)
    with pytest.raises(ValueError, match="celerity_km_s"):
        derive_post_pad_minutes(200.0, celerity_km_s=-0.3)
    with pytest.raises(ValueError, match="corridor_km"):
        derive_post_pad_minutes(corridor_km=-50.0)
    with pytest.raises(ValueError, match="margin_seconds"):
        derive_post_pad_minutes(200.0, margin_seconds=-60.0)


def test_derived_post_pad_is_always_positive():
    # Guard against a future edit reintroducing an inverted window.
    for corridor in (0.0, 1.0, 100.0, 1000.0):
        for celerity in (0.18, 0.30, 0.45):
            assert derive_post_pad_minutes(corridor, celerity_km_s=celerity) > 0
