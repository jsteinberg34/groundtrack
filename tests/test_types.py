"""
Unit tests for groundtrack.types.

Covers dataclass construction, default fields, GeoBox.box_id zero-padding, and
dataclass equality.
"""

import pytest

from groundtrack.types import TrackPoint, GeoBox, BoxWindow, TrackSegment

from conftest import EPOCH


# --------------------------------------------------------------------------- #
# TrackPoint
# --------------------------------------------------------------------------- #

def test_track_point_altitude_defaults_to_none():
    p = TrackPoint(time=EPOCH, lat=12.0, lon=-34.0)
    assert p.time == EPOCH
    assert p.lat == 12.0
    assert p.lon == -34.0
    assert p.altitude_km is None


def test_track_point_stores_altitude_when_given():
    p = TrackPoint(time=EPOCH, lat=0.0, lon=0.0, altitude_km=120.5)
    assert p.altitude_km == 120.5


# --------------------------------------------------------------------------- #
# GeoBox.box_id
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "index, expected",
    [
        (0, "box_000"),
        (5, "box_005"),
        (42, "box_042"),
        (123, "box_123"),
        (1234, "box_1234"),  # overflows past three digits gracefully
    ],
)
def test_box_id_zero_padding(index, expected):
    box = GeoBox(lat_min=0.0, lat_max=1.0, lon_min=0.0, lon_max=1.0, box_index=index)
    assert box.box_id == expected


def test_geobox_stores_fields():
    box = GeoBox(lat_min=-1.0, lat_max=2.0, lon_min=-3.0, lon_max=4.0, box_index=7)
    assert box.lat_min == -1.0
    assert box.lat_max == 2.0
    assert box.lon_min == -3.0
    assert box.lon_max == 4.0
    assert box.box_index == 7


# --------------------------------------------------------------------------- #
# BoxWindow / TrackSegment construction and equality
# --------------------------------------------------------------------------- #

def test_box_window_constructs_with_declared_fields():
    box = GeoBox(lat_min=0.0, lat_max=1.0, lon_min=0.0, lon_max=1.0, box_index=0)
    bw = BoxWindow(
        box=box,
        t_enter=EPOCH,
        t_exit=EPOCH,
        t_download_start=EPOCH,
        t_download_end=EPOCH,
        first_track_index=0,
        last_track_index=6,
        n_points=7,
    )
    assert bw.box is box
    assert bw.first_track_index == 0
    assert bw.last_track_index == 6
    assert bw.n_points == 7


def test_track_segment_constructs_with_declared_fields():
    seg = TrackSegment(
        lat_a_rad=0.1,
        lon_a_rad=0.2,
        lat_b_rad=0.3,
        lon_b_rad=0.4,
        bearing_ab_rad=0.5,
        length_rad=0.6,
    )
    assert seg.lat_a_rad == 0.1
    assert seg.length_rad == 0.6


def test_dataclass_equality_holds_for_equal_values():
    a = GeoBox(lat_min=0.0, lat_max=1.0, lon_min=0.0, lon_max=1.0, box_index=3)
    b = GeoBox(lat_min=0.0, lat_max=1.0, lon_min=0.0, lon_max=1.0, box_index=3)
    c = GeoBox(lat_min=0.0, lat_max=1.0, lon_min=0.0, lon_max=1.0, box_index=4)
    assert a == b
    assert a != c

    p1 = TrackPoint(time=EPOCH, lat=1.0, lon=2.0)
    p2 = TrackPoint(time=EPOCH, lat=1.0, lon=2.0)
    assert p1 == p2
