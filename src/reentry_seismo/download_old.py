from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Sequence

from obspy import UTCDateTime
from obspy.clients.fdsn.mass_downloader import (
    MassDownloader,
    RectangularDomain,
    Restrictions,
)


def _normalize_providers(providers):
    """
    Ensures providers are in a consistent list format.

    Why:
    ObsPy expects a list of provider strings. This just makes sure
    we don't accidentally pass something weird.
    """
    if providers is None:
        return None
    return [str(p) for p in providers]


def _build_domain(req):
    """
    Converts one of our box requests into an ObsPy spatial domain.

    Each request already contains:
        lat_min, lat_max, lon_min, lon_max

    This tells ObsPy:
        "Only look for stations inside this geographic region"
    """
    return RectangularDomain(
        minlatitude=req["lat_min"],
        maxlatitude=req["lat_max"],
        minlongitude=req["lon_min"],
        maxlongitude=req["lon_max"],
    )


def _build_restrictions(
    req,
    channel_priorities,
    location_priorities,
    reject_channels_with_gaps,
    minimum_length,
):
    """
    Converts our time window + filtering rules into ObsPy Restrictions.

    This is where we define:
        - time window (when the event passes the box)
        - which channels we care about (HHZ, BHZ)
        - which location codes we prefer
        - quality filters (no gaps, minimum length)

    Important:
    This is the part that determines WHAT data we actually download.
    """
    return Restrictions(
        starttime=UTCDateTime(req["t_start_utc"]),
        endtime=UTCDateTime(req["t_end_utc"]),
        channel_priorities=list(channel_priorities),
        location_priorities=list(location_priorities),
        reject_channels_with_gaps=reject_channels_with_gaps,
        minimum_length=minimum_length,
    )


def _count_files(path: Path, pattern: str) -> int:
    """
    Counts files recursively.

    Why:
    We use this to:
        - check if a box already has data
        - count how many files were downloaded
    """
    return sum(1 for p in path.rglob(pattern) if p.is_file())


def download_boxes(
    download_requests: Iterable[dict],
    output_base: str | Path,
    event_name: str,
    providers: Sequence[str] | None = ("IRIS", "SCEDC", "NCEDC"),
    channel_priorities: Sequence[str] = ("HHZ", "BHZ"),
    location_priorities: Sequence[str] = ("", "00", "10", "20"),
    reject_channels_with_gaps: bool = True,
    minimum_length: float = 0.9,
    overwrite_existing: bool = False,
    verbose: bool = True,
) -> dict:
    """
    Main download function.

    High-level idea:
    ----------------
    We already split the orbital track into boxes + time windows.

    Now for each box:
        1. Build a folder
        2. Ask ObsPy for stations in that region/time
        3. Download waveforms + station metadata
        4. Record what happened (manifest)

    Returns:
        A manifest dictionary describing the entire run.
    """

    requests = list(download_requests)

    # Root folder for this event
    run_folder = Path(output_base) / event_name
    boxes_root = run_folder / "boxes"
    boxes_root.mkdir(parents=True, exist_ok=True)

    # Initialize ObsPy downloader (can query multiple providers)
    mdl = MassDownloader(providers=_normalize_providers(providers))

    results = []
    n_ok = 0
    n_skip = 0
    n_fail = 0

    # Loop through each box request
    for k, req in enumerate(requests, start=1):
        box_id = req["box_id"]

        # Each box gets its own folder
        box_dir = boxes_root / box_id
        inv_dir = box_dir / "stations"
        wav_dir = box_dir / "waveforms"
        log_dir = box_dir / "logs"

        inv_dir.mkdir(parents=True, exist_ok=True)
        wav_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Check if we already downloaded data for this box
        existing_mseed = _count_files(wav_dir, "*.mseed")
        existing_xml = _count_files(inv_dir, "*.xml")

        if not overwrite_existing and existing_mseed > 0 and existing_xml > 0:
            # Skip to avoid re-downloading
            n_skip += 1
            results.append({
                "box_id": box_id,
                "status": "skipped_existing",
                "existing_mseed_files": existing_mseed,
                "existing_stationxml_files": existing_xml,
            })

            if verbose:
                print(f"[{k}/{len(requests)}] skipping {box_id} (already has data)")

            continue

        # Build spatial + temporal query
        domain = _build_domain(req)
        restrictions = _build_restrictions(
            req,
            channel_priorities,
            location_priorities,
            reject_channels_with_gaps,
            minimum_length,
        )

        # Custom naming for waveform files
        def get_mseed_path(network, station, location, channel, starttime, endtime):
            loc = location if location else ""
            return str(wav_dir / f"{network}.{station}.{loc}.{channel}.mseed")

        try:
            if verbose:
                print(f"[{k}/{len(requests)}] downloading {box_id} ...")

            # Core ObsPy call
            mdl.download(
                domain,
                restrictions,
                mseed_storage=get_mseed_path,
                stationxml_storage=str(inv_dir / "{network}.{station}.xml"),
            )

            # Count what we got
            new_mseed = _count_files(wav_dir, "*.mseed")
            new_xml = _count_files(inv_dir, "*.xml")

            n_ok += 1
            results.append({
                "box_id": box_id,
                "status": "ok",
                "mseed_files": new_mseed,
                "stationxml_files": new_xml,
            })

        except Exception as e:
            n_fail += 1
            results.append({
                "box_id": box_id,
                "status": "failed",
                "error": repr(e),
            })

            if verbose:
                print(f"FAILED: {box_id} -> {repr(e)}")

    # Build manifest (summary of everything that happened)
    manifest = {
        "event_name": event_name,
        "run_folder": str(run_folder),
        "total_requests": len(requests),
        "providers": list(providers) if providers else None,
        "ok": n_ok,
        "skipped_existing": n_skip,
        "failed": n_fail,
        "results": results,
    }

    # Save manifest to disk
    manifest_path = run_folder / "download_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)

    if verbose:
        print("\n=== Download Summary ===")
        print("OK:", n_ok, "| Skipped:", n_skip, "| Failed:", n_fail)
        print("Manifest saved to:", manifest_path)

    return manifest