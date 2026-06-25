"""
Unit tests for the network-free surface of groundtrack.track.

Covers TLE parsing, cache-key construction, satellite building, deterministic
propagation and its guard clauses, dataframe->points conversion, the cache-hit
branch of fetch_tle_best_before_cached, and the missing-credentials guard of
load_spacetrack_client. The Space-Track network branch (cache-miss query and
build_track_from_norad) is covered here too via a faked client -- still no
network.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from groundtrack.track import (
    _parse_first_tle_pair,
    _cache_key,
    build_satellite_from_tle,
    propagate_satellite_to_dataframe,
    dataframe_to_track_points,
    fetch_tle_best_before_cached,
    build_track_from_norad,
    load_spacetrack_client,
)
from groundtrack.types import TrackPoint

from conftest import SHENZHOU15_TLE_EPOCH_UTC, FakeSpaceTrack


# --------------------------------------------------------------------------- #
# _parse_first_tle_pair
# --------------------------------------------------------------------------- #

def test_parse_first_tle_pair_with_name_and_blank_lines(shenzhou15_tle):
    l1, l2 = shenzhou15_tle
    text = f"\nOBJECT NAME\n{l1}\n{l2}\n"
    assert _parse_first_tle_pair(text) == (l1, l2)


def test_parse_first_tle_pair_returns_first_of_multiple_blocks(shenzhou15_tle):
    l1, l2 = shenzhou15_tle
    other1 = "1 99999U 00000A   24001.00000000  .00000000  00000-0  00000-0 0  0001"
    other2 = "2 99999  00.0000 000.0000 0000000 000.0000 000.0000 00.00000000 00001"
    text = f"{l1}\n{l2}\n{other1}\n{other2}\n"
    assert _parse_first_tle_pair(text) == (l1, l2)


def test_parse_first_tle_pair_no_valid_pair():
    assert _parse_first_tle_pair("just some text\nno tle here\n") == (None, None)


# --------------------------------------------------------------------------- #
# _cache_key
# --------------------------------------------------------------------------- #

def test_cache_key_deterministic_and_encodes_request():
    t = datetime(2024, 4, 2, 8, 40, 0, tzinfo=timezone.utc)
    k1 = _cache_key(56873, t, 7)
    k2 = _cache_key(56873, t, 7)
    assert k1 == k2
    assert "56873" in k1
    assert "lb7d" in k1
    assert "20240402T084000Z" in k1


def test_cache_key_normalizes_aware_offsets_to_utc():
    from datetime import timedelta

    # Same instant, two timezone-aware representations. _cache_key normalizes
    # aware datetimes to UTC before formatting, so the filenames must match.
    # (Note: a naive datetime is treated as *local* time by .astimezone(), so
    # only aware inputs are unambiguous here.)
    utc = datetime(2024, 4, 2, 8, 40, 0, tzinfo=timezone.utc)
    plus_two = datetime(2024, 4, 2, 10, 40, 0, tzinfo=timezone(timedelta(hours=2)))
    key = _cache_key(56873, utc, 7)
    assert key == _cache_key(56873, plus_two, 7)
    assert "20240402T084000Z" in key


# --------------------------------------------------------------------------- #
# build_satellite_from_tle
# --------------------------------------------------------------------------- #

def test_build_satellite_epoch_matches_decoded_tle(shenzhou15_tle):
    sat, ts = build_satellite_from_tle(*shenzhou15_tle, norad_id=56873)
    assert sat.epoch.utc_iso() == SHENZHOU15_TLE_EPOCH_UTC


@pytest.mark.parametrize(
    "kwargs, expected_name",
    [
        ({"name": "MY SAT"}, "MY SAT"),
        ({"norad_id": 56873}, "OBJECT (56873)"),
        ({}, "SATELLITE"),
    ],
)
def test_build_satellite_name_branches(shenzhou15_tle, kwargs, expected_name):
    sat, _ = build_satellite_from_tle(*shenzhou15_tle, **kwargs)
    assert sat.name == expected_name


# --------------------------------------------------------------------------- #
# propagate_satellite_to_dataframe
# --------------------------------------------------------------------------- #

def test_propagation_frame_columns_and_inclusive_endpoint(shenzhou15_tle):
    sat, ts = build_satellite_from_tle(*shenzhou15_tle, norad_id=56873)
    start = datetime(2024, 4, 2, 8, 40, 0, tzinfo=timezone.utc)
    end = datetime(2024, 4, 2, 8, 40, 10, tzinfo=timezone.utc)  # 10 s window

    df = propagate_satellite_to_dataframe(sat, ts, start, end, step_seconds=1)

    assert list(df.columns) == ["time_utc", "lat_deg", "lon_deg", "alt_km"]
    # Endpoint inclusive: 10 s at 1 s step -> 11 rows.
    assert len(df) == 10 // 1 + 1


def test_propagation_uneven_step_truncates_final_partial_step(shenzhou15_tle):
    sat, ts = build_satellite_from_tle(*shenzhou15_tle, norad_id=56873)
    start = datetime(2024, 4, 2, 8, 40, 0, tzinfo=timezone.utc)
    end = datetime(2024, 4, 2, 8, 40, 10, tzinfo=timezone.utc)

    df = propagate_satellite_to_dataframe(sat, ts, start, end, step_seconds=3)
    # range(0, 11, 3) -> [0, 3, 6, 9] -> 4 rows == 10 // 3 + 1
    assert len(df) == 10 // 3 + 1


def test_propagation_rejects_invalid_window_and_step(shenzhou15_tle):
    sat, ts = build_satellite_from_tle(*shenzhou15_tle, norad_id=56873)
    start = datetime(2024, 4, 2, 8, 40, 0, tzinfo=timezone.utc)
    end = datetime(2024, 4, 2, 8, 50, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError):
        propagate_satellite_to_dataframe(sat, ts, end, start)  # end <= start
    with pytest.raises(ValueError):
        propagate_satellite_to_dataframe(sat, ts, start, end, step_seconds=0)


# --------------------------------------------------------------------------- #
# dataframe_to_track_points
# --------------------------------------------------------------------------- #

def test_dataframe_to_track_points(shenzhou15_tle):
    sat, ts = build_satellite_from_tle(*shenzhou15_tle, norad_id=56873)
    start = datetime(2024, 4, 2, 8, 40, 0, tzinfo=timezone.utc)
    end = datetime(2024, 4, 2, 8, 40, 5, tzinfo=timezone.utc)

    df = propagate_satellite_to_dataframe(sat, ts, start, end, step_seconds=1)
    points = dataframe_to_track_points(df)

    assert len(points) == len(df)
    assert all(isinstance(p, TrackPoint) for p in points)
    first = points[0]
    assert first.time == start  # UTC-aware, equals the window start instant
    assert first.time.tzinfo is not None
    assert isinstance(first.lat, float)
    assert isinstance(first.lon, float)
    assert isinstance(first.altitude_km, float)


# --------------------------------------------------------------------------- #
# fetch_tle_best_before_cached -- offline branches only
# --------------------------------------------------------------------------- #

class _SentinelClient:
    """Stand-in client that fails loudly if any method is touched."""
    def __getattr__(self, name):
        raise AssertionError(f"network client was used (.{name}) on cache hit")


def test_cache_hit_returns_pair_without_using_client(tmp_path, shenzhou15_tle):
    l1, l2 = shenzhou15_tle
    t = datetime(2024, 4, 2, 8, 40, 0, tzinfo=timezone.utc)

    # Pre-seed the cache at the exact path the function will look for.
    from groundtrack.io import get_tle_cache_path
    cache_path = get_tle_cache_path(tmp_path, _cache_key(56873, t, 7))
    cache_path.write_text(f"{l1}\n{l2}\n", encoding="utf-8")

    r1, r2, returned_path = fetch_tle_best_before_cached(
        _SentinelClient(), 56873, t, tmp_path, lookback_days=7
    )

    assert (r1, r2) == (l1, l2)
    assert returned_path == cache_path  # proves the early-return branch was taken


def test_corrupt_cache_falls_through_to_client(tmp_path):
    t = datetime(2024, 4, 2, 8, 40, 0, tzinfo=timezone.utc)
    from groundtrack.io import get_tle_cache_path
    cache_path = get_tle_cache_path(tmp_path, _cache_key(56873, t, 7))
    cache_path.write_text("garbage, not a tle\n", encoding="utf-8")

    # Falls past the early return and tries to use the client -> sentinel raises.
    with pytest.raises(AssertionError):
        fetch_tle_best_before_cached(
            _SentinelClient(), 56873, t, tmp_path, lookback_days=7
        )


# --------------------------------------------------------------------------- #
# load_spacetrack_client
# --------------------------------------------------------------------------- #

def test_load_spacetrack_client_requires_credentials(monkeypatch):
    monkeypatch.delenv("SPACETRACK_USER", raising=False)
    monkeypatch.delenv("SPACETRACK_PASS", raising=False)
    with pytest.raises(ValueError):
        load_spacetrack_client()


# --------------------------------------------------------------------------- #
# Network branch via a faked Space-Track client (no network)
# --------------------------------------------------------------------------- #

def test_fetch_tle_cache_miss_queries_and_caches(tmp_path, shenzhou15_tle):
    l1, l2 = shenzhou15_tle
    fake = FakeSpaceTrack(f"{l1}\n{l2}\n")
    t = datetime(2024, 4, 2, 8, 40, 0, tzinfo=timezone.utc)

    # Fresh tmp_path -> cache miss -> queries the (faked) client and caches.
    r1, r2, cache_path = fetch_tle_best_before_cached(
        fake, 56873, t, tmp_path, lookback_days=7
    )

    assert (r1, r2) == (l1, l2)
    assert Path(cache_path).exists()
    cached_lines = Path(cache_path).read_text(encoding="utf-8").splitlines()
    assert [ln for ln in cached_lines if ln.strip()] == [l1, l2]


def test_build_track_from_norad_wires_front_end(tmp_path, monkeypatch, shenzhou15_tle):
    l1, l2 = shenzhou15_tle
    fake = FakeSpaceTrack(f"{l1}\n{l2}\n")
    monkeypatch.setattr(
        "groundtrack.track.load_spacetrack_client",
        lambda username=None, password=None: fake,
    )

    start = datetime(2024, 4, 2, 8, 40, 0, tzinfo=timezone.utc)
    end = datetime(2024, 4, 2, 9, 0, 0, tzinfo=timezone.utc)

    result = build_track_from_norad(
        56873, start, end, tmp_path, lookback_days=7, step_seconds=1
    )

    assert {
        "line1", "line2", "cache_path", "satellite_name",
        "tle_epoch_utc", "df", "track_points",
    } <= set(result)
    assert result["line1"] == l1
    # Real offline propagation over the validated window.
    assert len(result["track_points"]) == 1201
