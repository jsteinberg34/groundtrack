"""
Unit tests for groundtrack.pipeline.

Covers the pure _parse_utc helper, plus run_pipeline's orchestration with the
two network-bound stages (build_track_from_norad, download_boxes) replaced by
spies -- so the stage wiring is verified with no network.
"""

from datetime import datetime, timedelta, timezone

from groundtrack.pipeline import _parse_utc, run_pipeline
from groundtrack.types import TrackPoint


# The same instant expressed three different ways.
EXPECTED = datetime(2024, 4, 2, 8, 40, 0, tzinfo=timezone.utc)


def test_parse_utc_iso_string_with_z():
    result = _parse_utc("2024-04-02T08:40:00Z")
    assert result.tzinfo is not None
    assert result == EXPECTED


def test_parse_utc_naive_datetime_assumed_utc():
    result = _parse_utc(datetime(2024, 4, 2, 8, 40, 0))
    assert result.tzinfo is not None
    assert result == EXPECTED


def test_parse_utc_aware_datetime_converted_to_utc():
    aware = datetime(2024, 4, 2, 10, 40, 0, tzinfo=timezone(timedelta(hours=2)))
    result = _parse_utc(aware)
    assert result.utcoffset() == timedelta(0)
    assert result == EXPECTED


# --------------------------------------------------------------------------- #
# run_pipeline orchestration with spied stages
# --------------------------------------------------------------------------- #

def test_run_pipeline_wires_stages(tmp_path, monkeypatch):
    # A realistic spy track (>= 2 points) so the real tiling stage produces boxes.
    t0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
    track_points = [
        TrackPoint(time=t0 + timedelta(seconds=10 * i), lat=0.0, lon=0.5 * i, altitude_km=100.0)
        for i in range(40)
    ]

    captured = {}

    def fake_build_track(**kwargs):
        captured["track_kwargs"] = kwargs
        return {"track_points": track_points, "line1": "", "line2": ""}

    def fake_download(**kwargs):
        captured["download_kwargs"] = kwargs
        return {"manifest": "sentinel"}

    # run_pipeline imports these lazily from their source modules, so patch there.
    monkeypatch.setattr("groundtrack.track.build_track_from_norad", fake_build_track)
    monkeypatch.setattr("groundtrack.download.download_boxes", fake_download)

    result = run_pipeline(
        norad_id=56873,
        start="2024-04-02T08:40:00Z",
        end="2024-04-02T09:00:00Z",
        cache_dir=tmp_path / "cache",
        output_dir=tmp_path / "out",
        event_name="ev",
        verbose=False,
    )

    # String inputs were parsed to tz-aware UTC and passed to the track stage.
    assert captured["track_kwargs"]["analysis_start_utc"] == EXPECTED
    assert captured["track_kwargs"]["analysis_start_utc"].tzinfo is not None

    # The real tiling stage ran on the spy's track points and produced boxes,
    # which were converted into download requests for the download stage.
    assert len(result["boxes"]) > 0
    assert len(captured["download_kwargs"]["download_requests"]) == len(result["boxes"])
    assert captured["download_kwargs"]["track_points"] is track_points

    # The orchestration return shape.
    assert set(result) == {"track", "boxes", "manifest"}
    assert result["manifest"] == {"manifest": "sentinel"}
