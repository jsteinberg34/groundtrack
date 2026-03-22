from reentry_seismo.types import TrackPoint, GeoBox, BoxWindow
from reentry_seismo.geodesy import wrap_lon_deg, min_distance_km_to_track, lon_bounds_dateline_safe
from reentry_seismo.tiling import track_to_box_windows
from reentry_seismo import download_boxes

print("Library imported successfully!")

from reentry_seismo.stations import (
    find_stationxml_files,
    parse_stationxml_files,
    deduplicate_stations,
)

print("stations.py imported successfully")

# Minimal real test
print("------------------------------------------")

from reentry_seismo.stations import load_and_filter_stations

boxes_root = "data/event_name/boxes"  # e.g. data/event_name/boxes

# You’ll reuse your existing track_points from notebook eventually
track_points = []  # placeholder for now

result = load_and_filter_stations(
    boxes_root=boxes_root,
    track_points=track_points,
    corridor_km=100.0,
)

print("Filtered stations:", len(result["filtered_stations"]))