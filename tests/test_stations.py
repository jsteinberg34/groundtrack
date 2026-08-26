"""
Unit tests for groundtrack.stations.

All functions here are network-free: StationXML is read from local files, and
the rest is pure data processing. Uses synthetic StationXML and tmp_path.
"""

import pytest

from groundtrack.stations import (
    find_stationxml_files,
    parse_stationxml_files,
    deduplicate_stations,
    filter_stations_by_track_distance,
    load_and_filter_stations,
    station_lats_lons,
)
from groundtrack.geodesy import min_distance_km_to_track, _AMBIGUOUS_BAND_KM
from groundtrack.types import TrackPoint

from conftest import EPOCH, KM_PER_DEGREE


def _write_station(synthetic_inventory, path, network, station, lat, lon):
    inv = synthetic_inventory(
        network=network, station=station, latitude=lat, longitude=lon
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    inv.write(str(path), format="STATIONXML")


# --------------------------------------------------------------------------- #
# find_stationxml_files
# --------------------------------------------------------------------------- #

def test_find_stationxml_files(tmp_path, synthetic_inventory):
    boxes = tmp_path / "boxes"
    _write_station(synthetic_inventory, boxes / "box_000" / "stations" / "XX.AAA.xml", "XX", "AAA", 0.0, 0.0)
    _write_station(synthetic_inventory, boxes / "box_001" / "stations" / "XX.BBB.xml", "XX", "BBB", 1.0, 1.0)
    # An XML not under a stations/ folder must be ignored.
    (boxes / "box_000" / "other.xml").write_text("<not-a-station/>")

    found = find_stationxml_files(boxes)

    names = [p.name for p in found]
    assert names == ["XX.AAA.xml", "XX.BBB.xml"]  # sorted
    assert all("stations" in p.parts for p in found)


# --------------------------------------------------------------------------- #
# parse_stationxml_files
# --------------------------------------------------------------------------- #

def test_parse_stationxml_files_parses_valid_and_skips_corrupt(tmp_path, synthetic_inventory):
    good = tmp_path / "XX.AAA.xml"
    _write_station(synthetic_inventory, good, "XX", "AAA", 34.1, -118.2)
    bad = tmp_path / "broken.xml"
    bad.write_text("not valid stationxml")

    rows = parse_stationxml_files([good, bad])

    assert len(rows) == 1
    row = rows[0]
    assert row["network"] == "XX"
    assert row["station"] == "AAA"
    assert row["lat"] == 34.1
    assert row["lon"] == -118.2
    assert row["source_xml"] == str(good)


# --------------------------------------------------------------------------- #
# deduplicate_stations
# --------------------------------------------------------------------------- #

def test_deduplicate_stations_keeps_first_of_each_pair():
    rows = [
        {"network": "XX", "station": "AAA", "lat": 0.0, "lon": 0.0},
        {"network": "XX", "station": "AAA", "lat": 0.0, "lon": 0.0},  # dup
        {"network": "XX", "station": "BBB", "lat": 1.0, "lon": 1.0},
        {"network": "YY", "station": "AAA", "lat": 2.0, "lon": 2.0},  # different net
    ]
    unique = deduplicate_stations(rows)
    keys = [(r["network"], r["station"]) for r in unique]
    assert keys == [("XX", "AAA"), ("XX", "BBB"), ("YY", "AAA")]


# --------------------------------------------------------------------------- #
# filter_stations_by_track_distance
# --------------------------------------------------------------------------- #

def test_filter_stations_by_track_distance(make_track):
    track = make_track(lat=0.0, lon_step=0.5, n=40)  # equatorial track
    stations = [
        {"network": "XX", "station": "NEAR", "lat": 0.5, "lon": 5.0},   # ~55 km off
        {"network": "XX", "station": "FAR", "lat": 5.0, "lon": 5.0},    # ~555 km off
    ]
    kept = filter_stations_by_track_distance(stations, track, corridor_km=100.0)

    assert [s["station"] for s in kept] == ["NEAR"]
    assert "min_dist_km" in kept[0]
    assert kept[0]["min_dist_km"] < 100.0


def test_filter_stations_by_track_distance_refines_ambiguous_band_station():
    # Two widely spaced track points; a station near the midpoint has a
    # point-sampled distance (~567 km, to the nearest endpoint) far larger
    # than its true perpendicular cross-track distance (~111 km, one degree
    # off the great-circle arc). filter_stations_by_track_distance must
    # thread corridor_km into min_distance_km_to_track so this refinement
    # actually runs -- otherwise the station is wrongly rejected using only
    # the point-sampled distance.
    track = [
        TrackPoint(time=EPOCH, lat=0.0, lon=0.0),
        TrackPoint(time=EPOCH, lat=0.0, lon=10.0),
    ]
    station_lat, station_lon = 1.0, 5.0

    point_sampled = min_distance_km_to_track(station_lat, station_lon, track)
    assert point_sampled == pytest.approx(567.0, rel=1e-2)

    # Corridor placing the point-sampled distance inside the ambiguous band,
    # but far above the true refined distance -- so refinement flips the
    # inclusion decision from reject to keep.
    corridor_km = point_sampled - 5.0
    assert abs(point_sampled - corridor_km) < _AMBIGUOUS_BAND_KM

    stations = [
        {"network": "XX", "station": "MID", "lat": station_lat, "lon": station_lon}
    ]
    kept = filter_stations_by_track_distance(stations, track, corridor_km=corridor_km)

    assert [s["station"] for s in kept] == ["MID"]
    assert kept[0]["min_dist_km"] == pytest.approx(KM_PER_DEGREE, rel=1e-3)


# --------------------------------------------------------------------------- #
# station_lats_lons
# --------------------------------------------------------------------------- #

def test_station_lats_lons_wraps_longitude():
    rows = [
        {"lat": 10.0, "lon": 200.0},  # wraps to -160
        {"lat": 20.0, "lon": -100.0},  # unchanged
    ]
    lats, lons = station_lats_lons(rows)
    assert lats == [10.0, 20.0]
    assert lons[0] == -160.0
    assert lons[1] == -100.0


def test_station_lats_lons_empty():
    assert station_lats_lons([]) == ([], [])


# --------------------------------------------------------------------------- #
# load_and_filter_stations (end-to-end, local)
# --------------------------------------------------------------------------- #

def test_load_and_filter_stations_end_to_end(tmp_path, synthetic_inventory, make_track):
    boxes = tmp_path / "boxes"
    _write_station(synthetic_inventory, boxes / "box_000" / "stations" / "XX.NEAR.xml", "XX", "NEAR", 0.5, 5.0)
    _write_station(synthetic_inventory, boxes / "box_001" / "stations" / "XX.FAR.xml", "XX", "FAR", 5.0, 5.0)

    track = make_track(lat=0.0, lon_step=0.5, n=40)
    result = load_and_filter_stations(boxes, track, corridor_km=100.0)

    assert set(result) == {"xml_files", "all_station_rows", "unique_stations", "filtered_stations"}
    assert len(result["xml_files"]) == 2
    assert len(result["unique_stations"]) == 2
    assert [s["station"] for s in result["filtered_stations"]] == ["NEAR"]
