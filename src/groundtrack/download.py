from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Sequence

from obspy import UTCDateTime
from obspy.clients.fdsn import Client
from obspy.clients.fdsn.header import FDSNNoDataException
from obspy.clients.fdsn.mass_downloader import (
    MassDownloader,
    RectangularDomain,
    Restrictions,
)

from .stations import (
    parse_stationxml_files,
    deduplicate_stations,
    filter_stations_by_track_distance,
)

from .processing import (
    process_box,
    DEFAULT_PRE_FILT_LOW,
    DEFAULT_WATER_LEVEL,
    DEFAULT_OUTPUT,
    DEFAULT_TAPER_PCT,
    DEFAULT_FREQMIN,
    DEFAULT_FREQMAX,
    DEFAULT_CORNERS,
    DEFAULT_ZEROPHASE,
)


def _normalize_providers(providers):
    """
    Make sure providers are always in a clean list format.

    Why:
    ObsPy expects provider names as strings. This avoids weird behavior if
    something else gets passed in accidentally.
    """
    if providers is None:
        return []
    return [str(p) for p in providers]


def _count_files(path: Path, pattern: str) -> int:
    """
    Count files recursively underneath a folder.

    Why:
    We use this for quick bookkeeping, like:
        - checking whether a box already has downloaded content
        - recording how many files ended up on disk
    """
    return sum(1 for p in path.rglob(pattern) if p.is_file())


def _provider_station_query(
    client: Client,
    req: dict,
    channel_priorities: Sequence[str],
    level: str = "station",
):
    """
    Query one provider for station inventory inside one box.

    Why:
    This is the coarse discovery step. We are asking:
        "What stations exist in this box and this time window?"
    """
    return client.get_stations(
        starttime=UTCDateTime(req["t_start_utc"]),
        endtime=UTCDateTime(req["t_end_utc"]),
        minlatitude=req["lat_min"],
        maxlatitude=req["lat_max"],
        minlongitude=req["lon_min"],
        maxlongitude=req["lon_max"],
        channel=",".join(channel_priorities),
        level=level,
    )


def _make_mseed_storage(approved_stations: set[tuple[str, str]], wav_dir: Path):
    """
    Build a callable for MassDownloader's mseed_storage parameter.

    MassDownloader calls this once per channel/time-interval it considers
    downloading. Returning a file path means "download here"; returning
    None means "skip this station entirely."

    We use this to enforce the corridor distance filter: only stations
    that passed Phase 1 filtering are in approved_stations.
    """
    def storage(network, station, location, channel, starttime, endtime):
        if (network, station) not in approved_stations:
            return None
        loc = location if location else ""
        return str(wav_dir / f"{network}.{station}.{loc}.{channel}.mseed")

    return storage


def download_boxes(
    download_requests: Iterable[dict],
    track_points,
    output_base: str | Path,
    event_name: str,
    corridor_km: float = 100.0,
    providers: Sequence[str] | None = ("EARTHSCOPE",),
    channel_priorities: Sequence[str] = ("HHZ", "BHZ"),
    location_priorities: Sequence[str] = ("", "00", "10", "20"),
    overwrite_existing: bool = False,
    verbose: bool = True,

   # ------------------------------------------------------------------
    # Optional post-download processing
    # ------------------------------------------------------------------
    # When apply_processing is False (default), raw data is downloaded and
    # nothing else happens -- this preserves the original behavior. When it
    # is True, each box is processed immediately after its waveforms land
    # on disk, using the parameters below. All defaults match process_boxes()
    # so the one-shot and two-step workflows produce identical output.
    apply_processing: bool = False,
    # Pre-processing (before response removal)
    demean: bool = True,
    detrend_linear: bool = True,
    taper_pct: float = DEFAULT_TAPER_PCT,
    # Response removal
    output: str = DEFAULT_OUTPUT,
    pre_filt_low: tuple[float, float] | None = DEFAULT_PRE_FILT_LOW,
    water_level: float = DEFAULT_WATER_LEVEL,
    # Bandpass (after response removal)
    apply_bandpass: bool = True,
    freqmin: float = DEFAULT_FREQMIN,
    freqmax: float = DEFAULT_FREQMAX,
    corners: int = DEFAULT_CORNERS,
    zerophase: bool = DEFAULT_ZEROPHASE
) -> dict:
    """
    Main box-based download pipeline.

    High-level logic:
    -----------------
    For each box:
        1. Query candidate station inventory inside the box
        2. Parse and deduplicate stations
        3. Filter stations by distance to the propagated track
        4. Download waveforms only for stations that survive the filter
        5. Save a manifest describing what happened

    This is the box -> candidate inventory -> distance filter -> waveform
    download architecture we discussed.
    """
    requests = list(download_requests)

    run_folder = Path(output_base) / event_name
    boxes_root = run_folder / "boxes"
    boxes_root.mkdir(parents=True, exist_ok=True)

    provider_names = _normalize_providers(providers)

    # Initialize provider clients once up front.
    clients = {}
    for provider_name in provider_names:
        try:
            clients[provider_name] = Client(provider_name)
        except Exception as e:
            if verbose:
                print(f"Could not initialize provider {provider_name}: {repr(e)}")

    mdl = MassDownloader(providers=provider_names)  # One instance used for every box

    results = []
    n_ok = 0
    n_skip = 0
    n_fail = 0

    for k, req in enumerate(requests, start=1):
        box_id = req["box_id"]

        box_dir = boxes_root / box_id
        inv_dir = box_dir / "stations"
        wav_dir = box_dir / "waveforms"
        log_dir = box_dir / "logs"

        inv_dir.mkdir(parents=True, exist_ok=True)
        wav_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        existing_mseed = _count_files(wav_dir, "*.mseed")
        existing_xml = _count_files(inv_dir, "*.xml")

        if not overwrite_existing and existing_mseed > 0 and existing_xml > 0:
            n_skip += 1
            results.append(
                {
                    "box_id": box_id,
                    "status": "skipped_existing",
                    "existing_mseed_files": existing_mseed,
                    "existing_stationxml_files": existing_xml,
                }
            )

            if verbose:
                print(f"[{k}/{len(requests)}] skipping {box_id} (already has data)")

            continue

        if verbose:
            print(f"[{k}/{len(requests)}] processing {box_id} ...")

        # ------------------------------------------------------------
        # Stage 1: gather candidate inventory files from providers
        # ------------------------------------------------------------
        provider_stationxml_files = []

        for provider_name, client in clients.items():
            try:
                inv = _provider_station_query(
                    client=client,
                    req=req,
                    channel_priorities=channel_priorities,
                    level="station",
                )

                xml_path = inv_dir / f"{provider_name}_stations.xml"
                inv.write(str(xml_path), format="STATIONXML")
                provider_stationxml_files.append(xml_path)

                if verbose:
                    print(f"    inventory from {provider_name}: saved {xml_path.name}")

            except FDSNNoDataException:
                if verbose:
                    print(f"    inventory from {provider_name}: no data")
            except Exception as e:
                if verbose:
                    print(f"    inventory from {provider_name}: FAILED -> {repr(e)}")

        # Parse raw candidate stations from the StationXML files we just saved.
        station_rows = parse_stationxml_files(provider_stationxml_files)
        unique_stations = deduplicate_stations(station_rows)

        # ------------------------------------------------------------
        # Stage 2: keep only stations within the physical corridor
        # ------------------------------------------------------------
        kept_stations = filter_stations_by_track_distance(
            unique_stations,
            track_points=track_points,
            corridor_km=corridor_km,
        )

        if verbose:
            print(
                f"    candidate stations: {len(unique_stations)} | "
                f"kept within {corridor_km} km: {len(kept_stations)}"
            )

        # Save a simple filtered station summary for debugging / inspection.
        filtered_summary_path = log_dir / "filtered_stations.json"
        with open(filtered_summary_path, "w", encoding="utf-8") as f:
            json.dump(kept_stations, f, indent=2, default=str)


        # ------------------------------------------------------------
        # Stage 3: bulk waveform download via MassDownloader
        # ------------------------------------------------------------
        approved = {(s["network"], s["station"]) for s in kept_stations}

        if approved:
            domain = RectangularDomain(
                minlatitude=req["lat_min"],
                maxlatitude=req["lat_max"],
                minlongitude=req["lon_min"],
                maxlongitude=req["lon_max"],
            )

            restrictions = Restrictions(
                starttime=UTCDateTime(req["t_start_utc"]),
                endtime=UTCDateTime(req["t_end_utc"]),
                network=",".join(sorted({s["network"] for s in kept_stations})),
                station=",".join(sorted({s["station"] for s in kept_stations})),
                channel_priorities=list(channel_priorities),
                location_priorities=list(location_priorities),
                reject_channels_with_gaps=True,
                minimum_length=0.9,
            )

            try:
                mdl.download(
                    domain,
                    restrictions,
                    mseed_storage=_make_mseed_storage(approved, wav_dir),
                    stationxml_storage=str(inv_dir / "{network}.{station}.xml"),
                )
            except Exception as e:
                if verbose:
                    print(f"    MassDownloader error: {repr(e)}")

        new_mseed = _count_files(wav_dir, "*.mseed")
        new_xml = _count_files(inv_dir, "*.xml")

        box_result = {
            "box_id": box_id,
            "status": "ok",
            "candidate_station_count": len(unique_stations),
            "filtered_station_count": len(kept_stations),
            "mseed_files": new_mseed,
            "stationxml_files": new_xml,
        }

        # ------------------------------------------------------------
        # Optional: process this box's waveforms right after download
        # ------------------------------------------------------------
        if apply_processing and new_mseed > 0:
            if verbose:
                print(f"    processing {box_id} ...")
            proc_result = process_box(
                box_dir,
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
                overwrite_existing=overwrite_existing,
                verbose=verbose,
            )
            box_result["processing"] = {
                "traces_in": proc_result["traces_in"],
                "traces_out": proc_result["traces_out"],
                "skipped_existing": proc_result["skipped_existing"],
                "n_errors": len(proc_result["errors"]),
            }        

        n_ok += 1
        results.append(box_result)

    manifest = {
        "event_name": event_name,
        "run_folder": str(run_folder),
        "boxes_root": str(boxes_root),
        "total_requests": len(requests),
        "providers": provider_names,
        "channel_priorities": list(channel_priorities),
        "location_priorities": list(location_priorities),
        "corridor_km": corridor_km,
        "ok": n_ok,
        "skipped_existing": n_skip,
        "failed": n_fail,
        "processing": {
            "applied": apply_processing,
            "params": {
                "demean": demean,
                "detrend_linear": detrend_linear,
                "taper_pct": taper_pct,
                "output": output,
                "pre_filt_low": list(pre_filt_low) if pre_filt_low is not None else None,
                "water_level": water_level,
                "apply_bandpass": apply_bandpass,
                "freqmin": freqmin,
                "freqmax": freqmax,
                "corners": corners,
                "zerophase": zerophase,
            } if apply_processing else None,
        },
        "results": results,
    }

    manifest_path = run_folder / "download_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)

    if verbose:
        print("\n=== Download Summary ===")
        print("OK:", n_ok, "| Skipped:", n_skip, "| Failed:", n_fail)
        print("Manifest saved to:", manifest_path)

    return manifest