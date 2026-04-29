from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from skyfield.api import EarthSatellite, load, wgs84
from spacetrack import SpaceTrackClient

from .types import TrackPoint
from .io import get_tle_cache_path, write_json


def load_spacetrack_client(username: str | None = None, password: str | None = None) -> SpaceTrackClient:
    """
    Build a Space-Track client.

    If username/password are not passed directly, we look for:
        SPACETRACK_USER
        SPACETRACK_PASS

    Why this exists:
    ----------------
    For the library/demo, we want one clean place that handles auth instead
    of having notebook cells manually setting this every time.
    """
    username = username or os.environ.get("SPACETRACK_USER")
    password = password or os.environ.get("SPACETRACK_PASS")

    if not username or not password:
        raise ValueError(
            "Space-Track credentials not found. "
            "Pass username/password directly or set SPACETRACK_USER and SPACETRACK_PASS. "
            "If you do not have an account, register at https://www.space-track.org."
        )

    return SpaceTrackClient(identity=username, password=password)


def _cache_key(norad_id: int, analysis_start_utc: datetime, lookback_days: int) -> str:
    """
    Build a deterministic cache filename for the TLE request.

    Why:
    ----
    We want the cache naming to reflect:
        - object ID
        - the start of the analysis window
        - how far back we looked for candidate TLEs
    """
    t = analysis_start_utc.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"norad{norad_id}_t0{t}_lb{lookback_days}d.tle"


def _parse_first_tle_pair(tle_text: str):
    """
    Find the first valid TLE pair in a response.

    Handles cases where the response contains:
        - name lines
        - multiple TLE blocks
        - blank lines

    Returns:
        (line1, line2) or (None, None)

    Why:
    ----
    Space-Track responses are not always just two clean lines, so this makes
    the extraction step more robust.
    """
    lines = [ln.strip() for ln in tle_text.splitlines() if ln.strip()]

    for i in range(len(lines) - 1):
        if lines[i].startswith("1 ") and lines[i + 1].startswith("2 "):
            return lines[i], lines[i + 1]

    return None, None


def fetch_tle_best_before_cached(
    st: SpaceTrackClient,
    norad_id: int,
    analysis_start_utc: datetime,
    base_cache_dir: str | Path,
    lookback_days: int = 30,
):
    """
    Return the most recent TLE whose epoch is <= analysis_start_utc.

    Workflow:
        1. Check cache first
        2. If not cached, query Space-Track gp_history
        3. Take the first valid TLE pair
        4. Save it to cache
        5. Return the pair

    Why this exists:
    ----------------
    This is one of the most important pieces of the whole front end:
        - we want the best TLE right before our analysis window
        - we want to avoid repeated API requests
        - we want this logic to be reusable in the library
    """
    if analysis_start_utc.tzinfo is None:
        analysis_start_utc = analysis_start_utc.replace(tzinfo=timezone.utc)
    else:
        analysis_start_utc = analysis_start_utc.astimezone(timezone.utc)

    cache_path = get_tle_cache_path(
        base_cache_dir,
        _cache_key(norad_id, analysis_start_utc, lookback_days),
    )

    # 1) Cache hit
    if cache_path.exists():
        cached = cache_path.read_text(encoding="utf-8")
        l1, l2 = _parse_first_tle_pair(cached)

        if l1 and l2:
            return l1, l2, cache_path

        # If the cache file exists but is bad/corrupted, fall through and re-fetch.

    # 2) Query historical TLEs
    start_dt = analysis_start_utc - timedelta(days=lookback_days)
    start = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    end = analysis_start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    tle_text = st.gp_history(
        norad_cat_id=norad_id,
        epoch=f"{start}--{end}",
        orderby="epoch desc",
        limit=10,
        format="tle",
    )

    l1, l2 = _parse_first_tle_pair(tle_text)
    if not (l1 and l2):
        raise RuntimeError(f"No TLE returned for NORAD {norad_id} in {start} -- {end}")

    # 3) Cache it
    cache_path.write_text(l1 + "\n" + l2 + "\n", encoding="utf-8")

    return l1, l2, cache_path


def build_satellite_from_tle(
    line1: str,
    line2: str,
    norad_id: int | None = None,
    name: str | None = None,
):
    """
    Build a Skyfield EarthSatellite object from a TLE pair.

    Why:
    ----
    This keeps the TLE -> Skyfield conversion separate from the rest of the
    library logic, which makes testing easier.
    """
    ts = load.timescale()

    if name is None:
        if norad_id is not None:
            name = f"OBJECT ({norad_id})"
        else:
            name = "SATELLITE"

    sat = EarthSatellite(line1, line2, name, ts)
    return sat, ts


def propagate_satellite_to_dataframe(
    sat,
    ts,
    start_utc: datetime,
    end_utc: datetime,
    step_seconds: int = 1,
) -> pd.DataFrame:
    """
    Propagate a satellite and return a dataframe of:
        time_utc, lat_deg, lon_deg, alt_km

    Why this exists:
    ----------------
    This mirrors the notebook logic closely and is still useful because:
        - dataframe output is convenient for sanity checks
        - it is easy to save or inspect
        - then we can convert that output into TrackPoint objects
    """
    if start_utc.tzinfo is None:
        start_utc = start_utc.replace(tzinfo=timezone.utc)
    else:
        start_utc = start_utc.astimezone(timezone.utc)

    if end_utc.tzinfo is None:
        end_utc = end_utc.replace(tzinfo=timezone.utc)
    else:
        end_utc = end_utc.astimezone(timezone.utc)

    if end_utc <= start_utc:
        raise ValueError("end_utc must be later than start_utc")

    if step_seconds <= 0:
        raise ValueError("step_seconds must be positive")

    total_seconds = int((end_utc - start_utc).total_seconds())

    times = ts.utc([
        start_utc + timedelta(seconds=i)
        for i in range(0, total_seconds + 1, step_seconds)
    ])

    # Propagate orbit, then convert to Earth lat/lon/alt
    g = wgs84.subpoint(sat.at(times))

    df = pd.DataFrame({
        "time_utc": [t.utc_iso() for t in times],
        "lat_deg": g.latitude.degrees,
        "lon_deg": g.longitude.degrees,
        "alt_km": g.elevation.km,
    })

    return df


def dataframe_to_track_points(df: pd.DataFrame) -> list[TrackPoint]:
    """
    Convert a propagation dataframe into TrackPoint objects.

    Why this exists:
    ----------------
    The rest of the library is built around TrackPoint objects, so this is
    the bridge from propagation output into the tiling / download pipeline.
    """
    track_times = [
        datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(timezone.utc)
        for t in df["time_utc"].tolist()
    ]

    track_lats = df["lat_deg"].tolist()
    track_lons = df["lon_deg"].tolist()
    track_alts = df["alt_km"].tolist()

    track_points = [
        TrackPoint(
            time=t,
            lat=float(lat),
            lon=float(lon),
            altitude_km=float(alt),
        )
        for t, lat, lon, alt in zip(track_times, track_lats, track_lons, track_alts)
    ]

    return track_points


def build_track_from_norad(
    norad_id: int,
    analysis_start_utc: datetime,
    analysis_end_utc: datetime,
    base_cache_dir: str | Path,
    lookback_days: int = 7,
    step_seconds: int = 1,
    username: str | None = None,
    password: str | None = None,
    save_metadata_dir: str | Path | None = None,
):
    """
    Full front-end track builder:
        NORAD -> best cached/fetched TLE -> Skyfield propagation -> TrackPoint list

    Returns a dictionary with:
        {
            "line1": ...,
            "line2": ...,
            "cache_path": ...,
            "satellite_name": ...,
            "tle_epoch_utc": ...,
            "df": ...,
            "track_points": ...
        }

    Why this exists:
    ----------------
    This is the real replacement for the notebook front half. It gives the
    library a clean way to start from a NORAD ID and analysis window.
    """
    st = load_spacetrack_client(username=username, password=password)

    line1, line2, cache_path = fetch_tle_best_before_cached(
        st=st,
        norad_id=norad_id,
        analysis_start_utc=analysis_start_utc,
        base_cache_dir=base_cache_dir,
        lookback_days=lookback_days,
    )

    sat, ts = build_satellite_from_tle(
        line1=line1,
        line2=line2,
        norad_id=norad_id,
        name=f"OBJECT ({norad_id})",
    )

    df = propagate_satellite_to_dataframe(
        sat=sat,
        ts=ts,
        start_utc=analysis_start_utc,
        end_utc=analysis_end_utc,
        step_seconds=step_seconds,
    )

    track_points = dataframe_to_track_points(df)

    result = {
        "line1": line1,
        "line2": line2,
        "cache_path": str(cache_path),
        "satellite_name": sat.name,
        "tle_epoch_utc": sat.epoch.utc_iso(),
        "df": df,
        "track_points": track_points,
    }

    # Optional metadata artifact so runs are reproducible
    if save_metadata_dir is not None:
        metadata = {
            "norad_id": norad_id,
            "analysis_start_utc": analysis_start_utc.astimezone(timezone.utc).isoformat(),
            "analysis_end_utc": analysis_end_utc.astimezone(timezone.utc).isoformat(),
            "lookback_days": lookback_days,
            "step_seconds": step_seconds,
            "cache_path": str(cache_path),
            "tle_epoch_utc": sat.epoch.utc_iso(),
            "line1": line1,
            "line2": line2,
            "n_track_points": len(track_points),
        }

        write_json(Path(save_metadata_dir) / "track_metadata.json", metadata)

    return result