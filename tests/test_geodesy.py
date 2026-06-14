"""
Unit tests for groundtrack.geodesy.

Covers longitude wrapping, dateline-safe longitude bounds, point-sampled vs.
ambiguous-band cross-track distance, and the bearing/segment helpers. All
deterministic and network-free.
"""

import numpy as np
import pytest

from groundtrack.geodesy import (
    wrap_lon_deg,
    lon_bounds_dateline_safe,
    min_distance_km_to_track,
    _bearing_rad,
    _compute_segment,
    _AMBIGUOUS_BAND_KM,
)
from groundtrack.types import TrackPoint

from conftest import EPOCH, KM_PER_DEGREE


# --------------------------------------------------------------------------- #
# wrap_lon_deg
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "value, expected",
    [
        (0.0, 0.0),
        (179.9999, 179.9999),
        (190.0, -170.0),
        (-190.0, 170.0),
        (360.0, 0.0),
        (-360.0, 0.0),
        (540.0, -180.0),
    ],
)
def test_wrap_lon_deg_known_values(value, expected):
    assert wrap_lon_deg(value) == pytest.approx(expected)


def test_wrap_lon_deg_both_antimeridian_representations_normalize_to_minus_180():
    assert wrap_lon_deg(180.0) == -180.0
    assert wrap_lon_deg(-180.0) == -180.0


@pytest.mark.parametrize("value", [-720.0, -181.0, -1.0, 0.0, 1.0, 181.0, 720.0])
def test_wrap_lon_deg_always_in_half_open_interval(value):
    result = wrap_lon_deg(value)
    assert -180.0 <= result < 180.0


# --------------------------------------------------------------------------- #
# lon_bounds_dateline_safe
# --------------------------------------------------------------------------- #

def test_lon_bounds_non_crossing_returns_ordered_bounds():
    lon_min, lon_max = lon_bounds_dateline_safe([10.0, 20.0, 30.0])
    assert lon_min == pytest.approx(10.0)
    assert lon_max == pytest.approx(30.0)
    assert lon_min <= lon_max


def test_lon_bounds_dateline_crossing_returns_wrapped_bounds():
    lon_min, lon_max = lon_bounds_dateline_safe([170.0, 175.0, -175.0, -170.0])
    assert lon_min == pytest.approx(170.0)
    assert lon_max == pytest.approx(-170.0)
    # lon_min > lon_max is the documented signal of an antimeridian crossing.
    assert lon_min > lon_max


def test_lon_bounds_single_point_has_equal_bounds():
    lon_min, lon_max = lon_bounds_dateline_safe([5.0])
    assert lon_min == pytest.approx(5.0)
    assert lon_max == pytest.approx(5.0)


# --------------------------------------------------------------------------- #
# min_distance_km_to_track
# --------------------------------------------------------------------------- #

def test_station_on_track_has_zero_distance(equator_track):
    on_track = equator_track[5]
    d = min_distance_km_to_track(on_track.lat, on_track.lon, equator_track)
    assert d == pytest.approx(0.0, abs=1e-6)


def test_one_degree_off_dense_track_is_about_111_km(equator_track):
    # Station 1 degree north of a densely sampled equatorial track.
    d = min_distance_km_to_track(1.0, 5.0, equator_track, corridor_km=None)
    assert d == pytest.approx(KM_PER_DEGREE, rel=1e-3)


def _two_point_equator_track():
    """Two sampled points ~1113 km apart on the equator (lon 0 and lon 10)."""
    return [
        TrackPoint(time=EPOCH, lat=0.0, lon=0.0),
        TrackPoint(time=EPOCH, lat=0.0, lon=10.0),
    ]


def test_ambiguous_band_refines_to_true_cross_track_distance():
    track = _two_point_equator_track()
    station_lat, station_lon = 1.0, 5.0  # 1 degree off the midpoint

    point_sampled = min_distance_km_to_track(station_lat, station_lon, track)
    # Nearest sampled point is an endpoint ~567 km away.
    assert point_sampled == pytest.approx(567.0, rel=1e-2)

    # A corridor placing the point-sampled distance inside the ambiguous band
    # triggers refinement to the true perpendicular distance (~111 km).
    refined = min_distance_km_to_track(
        station_lat, station_lon, track, corridor_km=point_sampled
    )
    assert refined == pytest.approx(KM_PER_DEGREE, rel=1e-3)
    assert refined < point_sampled


def test_ambiguous_band_considers_both_neighbouring_segments():
    # Three points so the nearest sampled point is interior (index 1); both the
    # preceding and following arc segments become refinement candidates.
    track = [
        TrackPoint(time=EPOCH, lat=0.0, lon=0.0),
        TrackPoint(time=EPOCH, lat=0.0, lon=5.0),
        TrackPoint(time=EPOCH, lat=0.0, lon=10.0),
    ]
    station_lat, station_lon = 1.0, 5.0  # 1 degree off the interior point
    point_sampled = min_distance_km_to_track(station_lat, station_lon, track)
    refined = min_distance_km_to_track(
        station_lat, station_lon, track, corridor_km=point_sampled
    )
    assert refined == pytest.approx(KM_PER_DEGREE, rel=1e-3)
    assert refined <= point_sampled


def test_clearly_inside_band_skips_refinement():
    track = _two_point_equator_track()
    station_lat, station_lon = 1.0, 5.0

    point_sampled = min_distance_km_to_track(station_lat, station_lon, track)
    # min_km <= corridor_km - _AMBIGUOUS_BAND_KM  => clearly inside, no refine.
    corridor = point_sampled + _AMBIGUOUS_BAND_KM + 100.0
    result = min_distance_km_to_track(
        station_lat, station_lon, track, corridor_km=corridor
    )
    assert result == pytest.approx(point_sampled)


def test_clearly_outside_band_skips_refinement():
    track = _two_point_equator_track()
    station_lat, station_lon = 1.0, 5.0

    point_sampled = min_distance_km_to_track(station_lat, station_lon, track)
    # min_km > corridor_km + _AMBIGUOUS_BAND_KM  => clearly outside, no refine.
    corridor = point_sampled - _AMBIGUOUS_BAND_KM - 100.0
    result = min_distance_km_to_track(
        station_lat, station_lon, track, corridor_km=corridor
    )
    assert result == pytest.approx(point_sampled)


# --------------------------------------------------------------------------- #
# _bearing_rad / _compute_segment
# --------------------------------------------------------------------------- #

def test_bearing_due_east_is_half_pi():
    # From (0, 0) to (0, 1 deg) is due east.
    bearing = _bearing_rad(0.0, 0.0, 0.0, np.deg2rad(1.0))
    assert bearing == pytest.approx(np.pi / 2, abs=1e-6)


def test_bearing_due_north_is_zero():
    # From (0, 0) to (1 deg, 0) is due north.
    bearing = _bearing_rad(0.0, 0.0, np.deg2rad(1.0), 0.0)
    assert bearing == pytest.approx(0.0, abs=1e-6)


def test_compute_segment_length_matches_one_degree_separation():
    lats = np.array([0.0, 0.0])
    lons = np.array([0.0, 1.0])
    seg = _compute_segment(lats, lons, 0)
    assert seg.length_rad == pytest.approx(np.deg2rad(1.0), rel=1e-4)
    assert seg.lat_a_rad == pytest.approx(0.0)
    assert seg.lon_b_rad == pytest.approx(np.deg2rad(1.0))
