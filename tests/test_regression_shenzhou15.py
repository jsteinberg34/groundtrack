"""
Offline regression test against the validated Shenzhou-15 re-entry.

Pins the validated 2-line TLE (committed under tests/fixtures/) and asserts the
propagation -> tiling chain reproduces known-good outputs. The track assertions
are intrinsic to the event (TLE + window + step). The box assertions pin every
tiling parameter explicitly, so changing library defaults does not break them --
only a change to the tiling algorithm itself would.

All offline and deterministic; no network, no real waveform data.
"""

from datetime import datetime, timezone

import pytest

from groundtrack.track import (
    build_satellite_from_tle,
    propagate_satellite_to_dataframe,
    dataframe_to_track_points,
)
from groundtrack.tiling import track_to_box_windows


# Validated analysis window for the Shenzhou-15 reference run.
WINDOW_START = datetime(2024, 4, 2, 8, 40, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2024, 4, 2, 9, 0, 0, tzinfo=timezone.utc)
STEP_SECONDS = 1

# Golden track values captured from the validated chain: index -> (lat, lon, alt_km).
GOLDEN_POINTS = {
    0: (27.19782, -133.99620, 142.221),
    300: (36.70523, -113.58242, 143.702),
    600: (41.41615, -88.89678, 144.539),
    900: (39.83788, -62.98267, 144.076),
    1200: (32.51744, -40.25798, 142.535),
}

# Pinned validated tiling parameters and golden box outputs.
TILING_PARAMS = dict(
    chunk_km=300.0,
    overlap_km=50.0,
    corridor_km=100.0,
    pre_pad_minutes=2,
    post_pad_minutes=13,
)
GOLDEN_N_BOXES = 35
GOLDEN_BOX0_BOUNDS = dict(
    lat_min=26.298502,
    lat_max=29.637712,
    lon_min=-133.996198,
    lon_max=-131.402716,
)


def _build_reference_track(line1, line2):
    sat, ts = build_satellite_from_tle(line1, line2, norad_id=56873)
    df = propagate_satellite_to_dataframe(
        sat, ts, WINDOW_START, WINDOW_END, step_seconds=STEP_SECONDS
    )
    return dataframe_to_track_points(df)


def test_track_matches_reference(shenzhou15_tle):
    track = _build_reference_track(*shenzhou15_tle)

    assert len(track) == 1201

    for idx, (lat, lon, alt) in GOLDEN_POINTS.items():
        p = track[idx]
        assert p.lat == pytest.approx(lat, abs=1e-3)
        assert p.lon == pytest.approx(lon, abs=1e-3)
        assert p.altitude_km == pytest.approx(alt, abs=1e-2)


def test_propagation_is_deterministic(shenzhou15_tle):
    a = _build_reference_track(*shenzhou15_tle)
    b = _build_reference_track(*shenzhou15_tle)

    assert len(a) == len(b)
    assert [(p.lat, p.lon, p.altitude_km) for p in a] == [
        (p.lat, p.lon, p.altitude_km) for p in b
    ]


def test_tiling_matches_reference_with_pinned_params(shenzhou15_tle):
    track = _build_reference_track(*shenzhou15_tle)

    # Every tiling parameter pinned explicitly -- independent of library defaults.
    windows = track_to_box_windows(track, **TILING_PARAMS)

    assert len(windows) == GOLDEN_N_BOXES

    box0 = windows[0].box
    # Geographic bounds only; time-derived fields are not part of the regression.
    assert box0.lat_min == pytest.approx(GOLDEN_BOX0_BOUNDS["lat_min"], abs=1e-3)
    assert box0.lat_max == pytest.approx(GOLDEN_BOX0_BOUNDS["lat_max"], abs=1e-3)
    assert box0.lon_min == pytest.approx(GOLDEN_BOX0_BOUNDS["lon_min"], abs=1e-3)
    assert box0.lon_max == pytest.approx(GOLDEN_BOX0_BOUNDS["lon_max"], abs=1e-3)
