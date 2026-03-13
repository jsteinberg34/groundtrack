import numpy as np
from obspy.geodetics import (
    locations2degrees,
    degrees2kilometers,
    gps2dist_azimuth,
    kilometers2degrees,
)


def wrap_lon_deg(lon: float) -> float:
    return (lon + 180.0) % 360.0 - 180.0


def min_distance_km_to_track(sta_lat, sta_lon, track_points):
    """
    Great-circle min distance in km from a station to any sampled track point.
    """
    sta_lon = wrap_lon_deg(float(sta_lon))

    lats = np.array([p.lat for p in track_points], dtype=float)
    lons = np.array([wrap_lon_deg(p.lon) for p in track_points], dtype=float)

    deg = locations2degrees(sta_lat, sta_lon, lats, lons)
    km = degrees2kilometers(deg)

    return float(np.min(km))


def lon_bounds_dateline_safe(lons_wrapped):
    """
    Return (lon_min, lon_max), possibly with lon_min > lon_max to indicate
    dateline crossing. Chooses the shortest longitude interval containing
    all points.
    """
    lons = np.array([wrap_lon_deg(x) for x in lons_wrapped], dtype=float)
    s = np.sort(lons)

    gaps = np.diff(np.r_[s, s[0] + 360.0])
    k = int(np.argmax(gaps))

    lon_min = s[(k + 1) % len(s)]
    lon_max = s[k]

    return wrap_lon_deg(lon_min), wrap_lon_deg(lon_max)