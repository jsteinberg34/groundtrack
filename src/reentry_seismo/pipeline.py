from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .processing import (
    DEFAULT_PRE_FILT_LOW,
    DEFAULT_WATER_LEVEL,
    DEFAULT_OUTPUT,
    DEFAULT_TAPER_PCT,
    DEFAULT_FREQMIN,
    DEFAULT_FREQMAX,
    DEFAULT_CORNERS,
    DEFAULT_ZEROPHASE,
)


def _parse_utc(t: str | datetime) -> datetime:
    """
    Accept either an ISO-format string or a datetime object and return
    a timezone-aware UTC datetime.

    Why this exists:
    ----------------
    The high-level run_pipeline() entry point accepts strings so users
    never have to import datetime themselves. Power users who already
    have datetime objects can pass those through unchanged.
    """
    if isinstance(t, str):
        return datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(timezone.utc)
    if t.tzinfo is None:
        return t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc)


def run_pipeline(
    norad_id: int,
    start: str | datetime,
    end: str | datetime,
    cache_dir: str | Path,
    output_dir: str | Path,
    event_name: str,
    # --- Propagation ---
    lookback_days: int = 7,
    step_seconds: int = 1,
    # --- Tiling ---
    chunk_km: float = 300.0,
    overlap_km: float = 50.0,
    corridor_km: float = 100.0,
    pre_pad_minutes: float = 2.0,
    post_pad_minutes: float = 13.0,
    # --- Download ---
    providers: Sequence[str] = ("EARTHSCOPE", "SCEDC", "NCEDC"),
    channel_priorities: Sequence[str] = ("HHZ", "BHZ"),
    location_priorities: Sequence[str] = ("", "00", "10", "20"),
    overwrite_existing: bool = False,
    # --- Processing ---
    apply_processing: bool = False,
    demean: bool = True,
    detrend_linear: bool = True,
    taper_pct: float = DEFAULT_TAPER_PCT,
    output: str = DEFAULT_OUTPUT,
    pre_filt_low: tuple[float, float] | None = DEFAULT_PRE_FILT_LOW,
    water_level: float = DEFAULT_WATER_LEVEL,
    apply_bandpass: bool = True,
    freqmin: float = DEFAULT_FREQMIN,
    freqmax: float = DEFAULT_FREQMAX,
    corners: int = DEFAULT_CORNERS,
    zerophase: bool = DEFAULT_ZEROPHASE,
    # --- Misc ---
    username: str | None = None,
    password: str | None = None,
    verbose: bool = True,
) -> dict:
    """
    Full end-to-end pipeline: NORAD ID -> waveforms on disk.

    This is the primary entry point for the library. It chains together
    track propagation, spatial tiling, station discovery, and waveform
    download into a single call. All parameters have sensible defaults
    so the minimal call requires only the six required arguments.

    For users who need finer control over any individual stage, the
    underlying functions (build_track_from_norad, track_to_box_windows,
    download_boxes, process_boxes) are all importable directly.

    Why this exists:
    ----------------
    Without this function, a user has to understand four separate modules
    and chain them together correctly before getting any output. This
    function makes the common case simple while keeping the full API
    accessible for power users.

    Args:
        norad_id:       NORAD catalog ID of the object.
        start:          Analysis window start — ISO string or datetime.
                        e.g. "2024-04-02T08:40:00Z"
        end:            Analysis window end — ISO string or datetime.
        cache_dir:      Directory for caching TLE files. Will be created
                        if it does not exist.
        output_dir:     Base directory for all output. A subdirectory
                        named event_name will be created here.
        event_name:     Name for this run, used as the output folder name.
                        e.g. "shenzhou15_reentry"

    Returns:
        dict with keys:
            "track"     — result dict from build_track_from_norad
            "boxes"     — list of BoxWindow objects
            "manifest"  — download manifest dict from download_boxes
    """
    # Lazy imports to keep top-level import fast
    from .track import build_track_from_norad
    from .tiling import track_to_box_windows, box_windows_to_download_requests
    from .download import download_boxes

    start_utc = _parse_utc(start)
    end_utc = _parse_utc(end)

    # --- Stage 1: propagate orbit ---
    if verbose:
        print(f"Building track for NORAD {norad_id} ...")

    track_result = build_track_from_norad(
        norad_id=norad_id,
        analysis_start_utc=start_utc,
        analysis_end_utc=end_utc,
        base_cache_dir=cache_dir,
        lookback_days=lookback_days,
        step_seconds=step_seconds,
        username=username,
        password=password,
    )

    track_points = track_result["track_points"]

    if verbose:
        print(f"Track built: {len(track_points)} points")

    # --- Stage 2: tile the track ---
    box_windows = track_to_box_windows(
        track_points,
        chunk_km=chunk_km,
        overlap_km=overlap_km,
        corridor_km=corridor_km,
        pre_pad_minutes=pre_pad_minutes,
        post_pad_minutes=post_pad_minutes,
    )

    if verbose:
        print(f"Tiling complete: {len(box_windows)} boxes")

    # --- Stage 3: convert to download requests ---
    requests = box_windows_to_download_requests(box_windows)

    # --- Stage 4: download ---
    manifest = download_boxes(
        download_requests=requests,
        track_points=track_points,
        output_base=output_dir,
        event_name=event_name,
        corridor_km=corridor_km,
        providers=providers,
        channel_priorities=channel_priorities,
        location_priorities=location_priorities,
        overwrite_existing=overwrite_existing,
        verbose=verbose,
        apply_processing=apply_processing,
        demean=demean,
        detrend_linear=detrend_linear,
        taper_pct=taper_pct,
        output=output,
        pre_filt_low=pre_filt_low,
        water_level=water_level,
        apply_bandpass=apply_bandpass,
        freqmin=freqmin,
        freqmax=freqmax,
        corners=corners,
        zerophase=zerophase,
    )

    return {
        "track": track_result,
        "boxes": box_windows,
        "manifest": manifest,
    }