from __future__ import annotations

import json
from pathlib import Path


def ensure_dir(path: str | Path) -> Path:
    """
    Make sure a directory exists and return it as a Path object.

    Why this exists:
    ----------------
    A lot of this pipeline depends on folders being present before we write
    cache files, manifests, or downloaded data. This keeps that logic in one
    place instead of repeating mkdir everywhere.
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_tle_cache_dir(base_cache_dir: str | Path) -> Path:
    """
    Return the TLE cache directory and create it if needed.

    Example:
        cache/
            tle/

    Why:
    ----
    TLE caching is a must so we do not keep hitting the Space-Track API and
    risk running into request limits.
    """
    base_cache_dir = ensure_dir(base_cache_dir)
    return ensure_dir(base_cache_dir / "tle")


def get_tle_cache_path(base_cache_dir: str | Path, cache_key: str) -> Path:
    """
    Return the full file path for one cached TLE file.
    """
    tle_cache_dir = get_tle_cache_dir(base_cache_dir)
    return tle_cache_dir / cache_key


def get_run_folder(output_base: str | Path, event_name: str) -> Path:
    """
    Return the main output folder for one event/run.

    Example:
        output_base/
            shenzhou15_20240402T084000Z_to_20240402T090000Z/

    Why:
    ----
    This keeps event outputs grouped cleanly and makes the demo notebook
    easier to read.
    """
    output_base = ensure_dir(output_base)
    return ensure_dir(output_base / event_name)


def write_json(path: str | Path, obj) -> Path:
    """
    Write a JSON artifact to disk.

    Why:
    ----
    We use JSON for simple reproducibility artifacts like:
        - selected TLE metadata
        - propagation metadata
        - request plans
        - manifests
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)

    return path