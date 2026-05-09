import numpy as np

from .types import TrackSegment

from obspy.geodetics import (
    locations2degrees,
    degrees2kilometers,
)


def wrap_lon_deg(lon: float) -> float:
    return (lon + 180.0) % 360.0 - 180.0

# A station whose nearest sampled track point is just outside the corridor
# threshold may still be within it -- its true closest approach lies between
# two sampled points. For stations within this band of the threshold, we
# compute the true cross-track arc distance to neighboring segments to check
# whether the station actually falls inside the corridor.
_AMBIGUOUS_BAND_KM = 10.0

def min_distance_km_to_track(
    sta_lat: float,
    sta_lon: float,
    track_points,
    corridor_km: float | None = None,
) -> float:
    """
    Minimum great-circle distance in km from a station to the ground track.

    For stations clearly inside or outside the corridor, returns the
    point-sampled distance (fast, vectorized). For stations in the ambiguous
    band near the corridor boundary, computes the true cross-track distance
    to the one or two arc segments neighboring the nearest track point.

    Args:
        sta_lat:      Station latitude in degrees.
        sta_lon:      Station longitude in degrees.
        track_points: List of TrackPoint objects.
        corridor_km:  The distance threshold being tested. Required to
                      determine whether a station is in the ambiguous band.
                      If None, always returns the point-sampled distance.
    """
    sta_lon = wrap_lon_deg(float(sta_lon))

    lats = np.array([p.lat for p in track_points], dtype=float)
    lons = np.array([wrap_lon_deg(p.lon) for p in track_points], dtype=float)

    # Fast vectorized point-to-point pass
    deg_to_points = locations2degrees(sta_lat, sta_lon, lats, lons)
    min_km = float(degrees2kilometers(np.min(deg_to_points)))

    # If no corridor given, or station is clearly inside/outside the
    # ambiguous band, return the point-sampled answer immediately
    if corridor_km is None:
        return min_km
    if min_km <= corridor_km - _AMBIGUOUS_BAND_KM:
        return min_km
    if min_km > corridor_km + _AMBIGUOUS_BAND_KM:
        return min_km

    # --- Ambiguous band: compute cross-track distance for the one or two
    # segments immediately neighboring the nearest track point ---
    nearest_idx = int(np.argmin(deg_to_points))
    candidate_indices = set()
    if nearest_idx > 0:
        candidate_indices.add(nearest_idx - 1)
    if nearest_idx < len(track_points) - 1:
        candidate_indices.add(nearest_idx)

    sta_lat_r = np.deg2rad(sta_lat)
    sta_lon_r = np.deg2rad(sta_lon)

    for i in candidate_indices:
        seg = _compute_segment(lats, lons, i)

        d_AS = np.deg2rad(deg_to_points[i])
        if d_AS == 0.0:
            continue

        bearing_AS = _bearing_rad(seg.lat_a_rad, seg.lon_a_rad, sta_lat_r, sta_lon_r)

        sin_dxt = np.sin(d_AS) * np.sin(bearing_AS - seg.bearing_ab_rad)
        dxt_rad = np.arcsin(np.clip(sin_dxt, -1.0, 1.0))

        cos_dxt = np.cos(dxt_rad)
        dat_rad = np.arccos(np.clip(np.cos(d_AS) / max(cos_dxt, 1e-10), -1.0, 1.0))

        # Only use cross-track distance if the perpendicular foot
        # falls within the segment, not beyond either endpoint
        if 0.0 <= dat_rad <= seg.length_rad:
            min_km = min(min_km, float(degrees2kilometers(np.rad2deg(abs(dxt_rad)))))

    return min_km


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


def _compute_segment(lats_deg, lons_deg, i: int) -> TrackSegment:
    """
    Compute a single TrackSegment on the fly from degree arrays.
    Used when no precomputed segment list is available.
    """
    lat_a = np.deg2rad(lats_deg[i])
    lon_a = np.deg2rad(lons_deg[i])
    lat_b = np.deg2rad(lats_deg[i + 1])
    lon_b = np.deg2rad(lons_deg[i + 1])

    return TrackSegment(
        lat_a_rad=lat_a,
        lon_a_rad=lon_a,
        lat_b_rad=lat_b,
        lon_b_rad=lon_b,
        bearing_ab_rad=_bearing_rad(lat_a, lon_a, lat_b, lon_b),
        length_rad=np.deg2rad(float(locations2degrees(
            lats_deg[i], lons_deg[i],
            lats_deg[i + 1], lons_deg[i + 1],
        ))),
    )


def _bearing_rad(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Initial bearing in radians from point 1 to point 2 (all inputs in radians).
    """
    dlon = lon2 - lon1
    x = np.sin(dlon) * np.cos(lat2)
    y = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(dlon)
    return float(np.arctan2(x, y))