"""
Unit tests for groundtrack.pipeline._parse_utc.

Only the pure datetime-normalization helper is in scope; run_pipeline itself is
network/orchestration and is covered in a later phase.
"""

from datetime import datetime, timedelta, timezone

from groundtrack.pipeline import _parse_utc


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
