from __future__ import annotations

from pathlib import Path
from typing import Iterable

from obspy import read_inventory

from .geodesy import min_distance_km_to_track, wrap_lon_deg


def find_stationxml_files(boxes_root: str | Path) -> list[Path]:
    """
    Recursively find all StationXML files underneath a boxes/ directory.

    Why this exists:
    ----------------
    Each download box gets its own folder, and each box may contain a
    stations/ subfolder with StationXML files. We want one function that
    can walk that whole tree and gather every XML file we downloaded.

    Example folder structure:
        boxes/
            box_000/
                stations/
                    CI.PASC.xml
            box_001/
                stations/
                    CI.BAK.xml
    """
    boxes_root = Path(boxes_root)
    return sorted([p for p in boxes_root.rglob("stations/*.xml") if p.is_file()])


def parse_stationxml_files(xml_files: Iterable[str | Path]) -> list[dict]:
    """
    Read StationXML files and extract basic station metadata.

    Returns a list of dictionaries like:
        {
            "network": "CI",
            "station": "PASC",
            "lat": 34.15,
            "lon": -118.17,
            "source_xml": "..."
        }

    Why this exists:
    ----------------
    ObsPy inventories contain much more than we need right now. For the
    current pipeline, the main things we care about are:
        - network code
        - station code
        - latitude
        - longitude

    This is the information we need for:
        - deduplicating stations
        - filtering by distance to the orbital track
        - plotting stations on a map
    """
    station_rows: list[dict] = []

    for xml in xml_files:
        xml = Path(xml)

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
            # We do not want one bad XML file to kill the whole run.
            # Better to skip it and keep processing the rest.
            print(f"Could not read StationXML: {xml} -> {repr(e)}")

    return station_rows


def deduplicate_stations(station_rows: Iterable[dict]) -> list[dict]:
    """
    Deduplicate stations by (network, station).

    Why this exists:
    ----------------
    The same physical station can show up in multiple download boxes, since
    neighboring boxes overlap in space/time. That means the same station may
    have been written to disk multiple times in different box folders.

    For plotting and track-distance filtering, we only want one copy of each
    unique station.
    """
    seen = set()
    unique_stations: list[dict] = []

    for row in station_rows:
        key = (row["network"], row["station"])

        if key not in seen:
            seen.add(key)
            unique_stations.append(row)

    return unique_stations


def filter_stations_by_track_distance(
    stations: Iterable[dict],
    track_points,
    corridor_km: float,
) -> list[dict]:
    """
    Keep only stations within corridor_km of the propagated ground track.

    Adds:
        "min_dist_km"

    to each kept station dict.

    Why this exists:
    ----------------
    Our downloader currently works in two stages:

        1. Download candidate stations inside rectangular box windows
        2. Apply a more physically meaningful great-circle distance filter

    The rectangular boxes are mainly a practical way to query ObsPy's
    MassDownloader. But the true scientific question is:

        "Which stations are actually close enough to the trajectory to be
         plausible sonic boom detections?"

    That is what this function answers.
    """
    kept: list[dict] = []

    for row in stations:
        d_km = min_distance_km_to_track(
            row["lat"],
            row["lon"],
            track_points
        )

        if d_km <= corridor_km:
            row_copy = dict(row)
            row_copy["min_dist_km"] = d_km
            kept.append(row_copy)

    return kept


def load_and_filter_stations(
    boxes_root: str | Path,
    track_points,
    corridor_km: float = 100.0,
    verbose: bool = True,
) -> dict:
    """
    Full convenience function for the current station-processing pipeline.

    Steps:
        1. Find all StationXML files
        2. Parse them into simple station dictionaries
        3. Deduplicate by network/station
        4. Keep only stations within corridor_km of the track

    Returns a dictionary with:
        {
            "xml_files": [...],
            "all_station_rows": [...],
            "unique_stations": [...],
            "filtered_stations": [...]
        }

    Why this exists:
    ----------------
    This gives us one clean library-level function that mirrors what we were
    doing manually in the notebook. It keeps the logic reusable while still
    being easy to inspect.
    """
    xml_files = find_stationxml_files(boxes_root)
    all_station_rows = parse_stationxml_files(xml_files)
    unique_stations = deduplicate_stations(all_station_rows)
    filtered_stations = filter_stations_by_track_distance(
        unique_stations,
        track_points,
        corridor_km,
    )

    if verbose:
        print("StationXML files found:", len(xml_files))
        print("Unique stations (downloaded candidates):", len(unique_stations))
        print(
            f"Stations within {corridor_km} km of track:",
            f"{len(filtered_stations)} / {len(unique_stations)}"
        )

    return {
        "xml_files": xml_files,
        "all_station_rows": all_station_rows,
        "unique_stations": unique_stations,
        "filtered_stations": filtered_stations,
    }


def station_lats_lons(stations: Iterable[dict]) -> tuple[list[float], list[float]]:
    """
    Convert station dictionaries into latitude / longitude lists for plotting.

    Why this exists:
    ----------------
    Plotting functions usually just want arrays/lists of latitudes and
    longitudes. This helper keeps that conversion in one place.
    """
    lats = [float(row["lat"]) for row in stations]
    lons = [wrap_lon_deg(float(row["lon"])) for row in stations]
    return lats, lons