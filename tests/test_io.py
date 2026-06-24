"""
Unit tests for groundtrack.io filesystem helpers, using tmp_path.
"""

import json
from datetime import datetime, timezone

from groundtrack.io import (
    ensure_dir,
    get_tle_cache_dir,
    get_tle_cache_path,
    get_run_folder,
    write_json,
)


def test_ensure_dir_creates_and_is_idempotent(tmp_path):
    target = tmp_path / "a" / "b" / "c"
    result = ensure_dir(target)
    assert result == target
    assert target.is_dir()
    # Calling again does not error.
    assert ensure_dir(target) == target


def test_get_tle_cache_dir_and_path(tmp_path):
    cache_dir = get_tle_cache_dir(tmp_path)
    assert cache_dir == tmp_path / "tle"
    assert cache_dir.is_dir()

    path = get_tle_cache_path(tmp_path, "norad56873_t0....tle")
    assert path == cache_dir / "norad56873_t0....tle"
    assert path.parent == cache_dir


def test_get_run_folder_returns_event_subfolder(tmp_path):
    folder = get_run_folder(tmp_path, "shenzhou15_reentry")
    assert folder == tmp_path / "shenzhou15_reentry"
    assert folder.is_dir()
    # Idempotent.
    assert get_run_folder(tmp_path, "shenzhou15_reentry") == folder


def test_write_json_round_trips_native_dict(tmp_path):
    path = tmp_path / "manifest.json"
    obj = {"a": 1, "b": [1, 2, 3], "c": "text"}
    write_json(path, obj)
    assert json.loads(path.read_text(encoding="utf-8")) == obj


def test_write_json_creates_parents_and_stringifies_non_native(tmp_path):
    path = tmp_path / "nested" / "deeper" / "meta.json"  # parents do not exist yet
    dt = datetime(2024, 4, 2, 8, 40, tzinfo=timezone.utc)
    write_json(path, {"epoch": dt})

    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    # default=str serializes the datetime via its str() form.
    assert loaded["epoch"] == str(dt)
