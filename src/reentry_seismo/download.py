from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Sequence

from obspy import UTCDateTime, read_inventory
from obspy.clients.fdsn import Client
from obspy.clients.fdsn.header import FDSNNoDataException

from .geodesy import min_distance_km_to_track


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


def _safe_loc(location_code):
    """
    Normalize location code for filenames.

    ObsPy/metadata sometimes uses an empty string for location. That is valid,
    but we still want filenames that are consistent.
    """
    return location_code if location_code else ""


def _parse_stationxml_files(xml_files):
    """
    Read StationXML files and extract simple station metadata rows.

    Returns rows like:
        {
            "network": "...",
            "station": "...",
            "lat": ...,
            "lon": ...,
            "source_xml": "..."
        }

    Why:
    After we query candidate inventory for a box, we want a very simple
    station list we can filter against the propagated track.
    """
    station_rows = []

    for xml in xml_files:
        try:
            inv = read_inventory(str(xml))

            for net in inv:
                for sta in net:
                    station_rows.append(
                        {
                            "network": net.code,
                            "station": sta.code,
                            "lat": float(sta.latitude),
                            "lon": float(sta.longitude),
                            "source_xml": str(xml),
                        }
                    )
        except Exception as e:
            # One bad XML should not kill the entire run.
            print(f"Could not read StationXML: {xml} -> {repr(e)}")

    return station_rows


def _deduplicate_stations(station_rows):
    """
    Deduplicate stations by (network, station).

    Why:
    The same physical station can appear from multiple providers or multiple
    inventory files. For filtering, we only want one logical copy.
    """
    seen = set()
    unique_rows = []

    for row in station_rows:
        key = (row["network"], row["station"])
        if key not in seen:
            seen.add(key)
            unique_rows.append(row)

    return unique_rows


def _filter_stations_by_track_distance(station_rows, track_points, corridor_km):
    """
    Keep only stations whose minimum great-circle distance to the propagated
    track is within corridor_km.

    Why:
    This is the key physical filter. The box is a coarse region used to find
    candidate stations, but the actual scientific rule is distance to the track.
    """
    kept = []

    for row in station_rows:
        d_km = min_distance_km_to_track(row["lat"], row["lon"], track_points)

        if d_km <= corridor_km:
            row_copy = dict(row)
            row_copy["min_dist_km"] = d_km
            kept.append(row_copy)

    return kept


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


def _download_station_waveforms(
    client: Client,
    station_row: dict,
    req: dict,
    wav_dir: Path,
    channel_priorities: Sequence[str],
    location_priorities: Sequence[str],
):
    """
    Attempt to download waveform data for one already-approved station.

    Returns a small result dict describing success/failure.

    Why:
    By this point the station has already passed the 100 km filter, so now
    we actually try to grab the waveform data.
    """
    net = station_row["network"]
    sta = station_row["station"]

    starttime = UTCDateTime(req["t_start_utc"])
    endtime = UTCDateTime(req["t_end_utc"])

    last_error = None

    # Try preferred channels and location codes in order.
    # This mirrors the logic from the notebook, but only after the station
    # has already been judged physically relevant.
    for channel in channel_priorities:
        for location in location_priorities:
            try:
                st = client.get_waveforms(
                    network=net,
                    station=sta,
                    location=location,
                    channel=channel,
                    starttime=starttime,
                    endtime=endtime,
                    attach_response=False,
                )

                if len(st) == 0:
                    continue

                loc = _safe_loc(location)
                out_path = wav_dir / f"{net}.{sta}.{loc}.{channel}.mseed"
                st.write(str(out_path), format="MSEED")

                return {
                    "status": "ok",
                    "network": net,
                    "station": sta,
                    "channel": channel,
                    "location": loc,
                    "waveform_file": str(out_path),
                }

            except Exception as e:
                last_error = repr(e)

    return {
        "status": "failed",
        "network": net,
        "station": sta,
        "error": last_error,
    }


def download_boxes(
    download_requests: Iterable[dict],
    track_points,
    output_base: str | Path,
    event_name: str,
    corridor_km: float = 100.0,
    providers: Sequence[str] | None = ("IRIS", "SCEDC", "NCEDC"),
    channel_priorities: Sequence[str] = ("HHZ", "BHZ"),
    location_priorities: Sequence[str] = ("", "00", "10", "20"),
    overwrite_existing: bool = False,
    verbose: bool = True,
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
        station_rows = _parse_stationxml_files(provider_stationxml_files)
        unique_stations = _deduplicate_stations(station_rows)

        # ------------------------------------------------------------
        # Stage 2: keep only stations within the physical corridor
        # ------------------------------------------------------------
        kept_stations = _filter_stations_by_track_distance(
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
        # Stage 3: only now download waveforms for the kept stations
        # ------------------------------------------------------------
        waveform_results = []

        for station_row in kept_stations:
            station_downloaded = False
            station_errors = []

            # Try providers in the order given until one succeeds.
            for provider_name, client in clients.items():
                wf_result = _download_station_waveforms(
                    client=client,
                    station_row=station_row,
                    req=req,
                    wav_dir=wav_dir,
                    channel_priorities=channel_priorities,
                    location_priorities=location_priorities,
                )

                if wf_result["status"] == "ok":
                    wf_result["provider"] = provider_name
                    waveform_results.append(wf_result)
                    station_downloaded = True
                    break
                else:
                    station_errors.append(
                        {
                            "provider": provider_name,
                            "error": wf_result.get("error"),
                        }
                    )

            if not station_downloaded:
                waveform_results.append(
                    {
                        "status": "failed",
                        "network": station_row["network"],
                        "station": station_row["station"],
                        "errors": station_errors,
                    }
                )

        new_mseed = _count_files(wav_dir, "*.mseed")
        new_xml = _count_files(inv_dir, "*.xml")

        box_result = {
            "box_id": box_id,
            "status": "ok",
            "candidate_station_count": len(unique_stations),
            "filtered_station_count": len(kept_stations),
            "mseed_files": new_mseed,
            "stationxml_files": new_xml,
            "waveform_results": waveform_results,
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