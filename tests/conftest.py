"""
Shared fixtures for the groundtrack unit test suite.

These helpers build small synthetic ground tracks out of TrackPoint objects so
that the pure geometry modules (geodesy, tiling, types) can be exercised
without any network access or external data.
"""

from datetime import datetime, timedelta

import pytest

from groundtrack.types import TrackPoint


# A fixed epoch so time-window assertions are deterministic.
EPOCH = datetime(2020, 1, 1, 0, 0, 0)

# obspy.geodetics.degrees2kilometers(1.0) -- one degree of great-circle arc.
# Expected distances are expressed as multiples of this constant rather than
# hard-coded magic numbers.
KM_PER_DEGREE = 111.19492664455873


@pytest.fixture
def make_track():
    """
    Factory for a ground track lying along a parallel of latitude.

    Returns a ``build`` function producing a list of evenly spaced TrackPoint
    objects marching eastward in longitude, one every ``dt_seconds``.
    """
    def build(lat=0.0, lon_start=0.0, lon_step=0.5, n=40, dt_seconds=10):
        return [
            TrackPoint(
                time=EPOCH + timedelta(seconds=dt_seconds * i),
                lat=lat,
                lon=lon_start + lon_step * i,
            )
            for i in range(n)
        ]

    return build


@pytest.fixture
def equator_track(make_track):
    """A 40-point track along the equator from lon 0 to lon ~19.5 degrees."""
    return make_track()
