"""
Unit tests for the pure logic in groundtrack.plotting.

Only _compute_extent is tested here -- it is pure (numpy + wrap_lon_deg) and
imports without matplotlib/cartopy. plot_waveform_comparison() and
plot_all_waveforms() are covered separately in test_plotting_render.py,
gated behind the optional [plotting] extras. plot_track_and_boxes(),
plot_stations(), and plot_station_comparison() remain untested;
plotting.py stays excluded from coverage accordingly.
"""

from datetime import datetime

from groundtrack.plotting import _compute_extent
from groundtrack.types import TrackPoint


EPOCH = datetime(2020, 1, 1)


def _pts(coords):
    return [TrackPoint(time=EPOCH, lat=lat, lon=lon) for lat, lon in coords]


def test_compute_extent_global_fallback_when_empty():
    # No track and no stations -> whole globe.
    assert _compute_extent() == [-180, 180, -90, 90]


def test_compute_extent_from_track_points_applies_padding():
    track = _pts([(0.0, 0.0), (1.0, 10.0)])
    # [min_lon-pad, max_lon+pad, min_lat-pad, max_lat+pad] with pad_deg=5
    assert _compute_extent(track_points=track) == [-5.0, 15.0, -5.0, 6.0]


def test_compute_extent_custom_pad():
    track = _pts([(0.0, 0.0), (2.0, 2.0)])
    assert _compute_extent(track_points=track, pad_deg=1.0) == [-1.0, 3.0, -1.0, 3.0]


def test_compute_extent_from_stations_only():
    extent = _compute_extent(station_lats=[10.0, 20.0], station_lons=[30.0, 40.0])
    assert extent == [25.0, 45.0, 5.0, 25.0]


def test_compute_extent_combines_track_and_stations():
    track = _pts([(0.0, 0.0)])
    extent = _compute_extent(
        track_points=track, station_lats=[50.0], station_lons=[60.0]
    )
    # lats {0, 50}, lons {0, 60} -> [-5, 65, -5, 55]
    assert extent == [-5.0, 65.0, -5.0, 55.0]


def test_compute_extent_wraps_track_longitude():
    # A track longitude of 200 wraps to -160, which becomes the min lon.
    track = _pts([(0.0, 200.0), (0.0, 0.0)])
    extent = _compute_extent(track_points=track)
    assert extent[0] == -165.0   # -160 - 5
    assert extent[1] == 5.0      # 0 + 5
