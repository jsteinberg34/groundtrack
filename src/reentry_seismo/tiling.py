from __future__ import annotations

import numpy as np
from datetime import timedelta
from obspy.geodetics import gps2dist_azimuth, kilometers2degrees

from .types import GeoBox, BoxWindow
from .geodesy import wrap_lon_deg, lon_bounds_dateline_safe


def pad_window(t_enter, t_exit, pre_pad_minutes, post_pad_minutes):
    return (
        t_enter - timedelta(minutes=pre_pad_minutes),
        t_exit + timedelta(minutes=post_pad_minutes)
    )


def track_to_box_windows(
    track,
    chunk_km=300.0,
    overlap_km=50.0,
    corridor_km=100.0,
    pre_pad_minutes=2,
    post_pad_minutes=13,
):
    """
    Build overlapping along-track chunks of approximately chunk_km, with
    overlap_km between neighboring chunks.

    Each chunk becomes one candidate download box:
      - along-track extent comes from the chunk points
      - cross-track extent comes from corridor_km padding
      - time window comes from first/last point in chunk plus time padding
    """
    if len(track) < 2:
        return []

    if overlap_km >= chunk_km:
        raise ValueError("overlap_km must be smaller than chunk_km")

    windows = []
    corridor_deg_lat = kilometers2degrees(corridor_km)

    n = len(track)
    start_idx = 0
    box_counter = 0

    while start_idx < n:
        dist_km = 0.0
        end_idx = start_idx

        while end_idx + 1 < n and dist_km < chunk_km:
            p1 = track[end_idx]
            p2 = track[end_idx + 1]
            d_m, _, _ = gps2dist_azimuth(
                p1.lat, wrap_lon_deg(p1.lon),
                p2.lat, wrap_lon_deg(p2.lon)
            )
            dist_km += d_m / 1000.0
            end_idx += 1

        chunk = track[start_idx:end_idx + 1]

        lats = np.array([p.lat for p in chunk], dtype=float)
        lons = np.array([p.lon for p in chunk], dtype=float)

        lat_min = float(lats.min() - corridor_deg_lat)
        lat_max = float(lats.max() + corridor_deg_lat)

        lon_min, lon_max = lon_bounds_dateline_safe(lons)

        lat_mid = float(np.mean(lats))
        cosphi = np.cos(np.deg2rad(lat_mid))
        corridor_deg_lon = corridor_deg_lat / max(cosphi, 1e-6)

        lon_min = wrap_lon_deg(lon_min - corridor_deg_lon)
        lon_max = wrap_lon_deg(lon_max + corridor_deg_lon)

        t_enter = chunk[0].time
        t_exit = chunk[-1].time
        t_download_start, t_download_end = pad_window(
            t_enter,
            t_exit,
            pre_pad_minutes,
            post_pad_minutes
        )

        box = GeoBox(
            lat_min=lat_min,
            lat_max=lat_max,
            lon_min=lon_min,
            lon_max=lon_max,
            box_size_deg=np.nan,
            lat_idx=box_counter,
            lon_idx=0,
        )

        windows.append(BoxWindow(
            box=box,
            t_enter=t_enter,
            t_exit=t_exit,
            t_download_start=t_download_start,
            t_download_end=t_download_end,
            first_track_index=start_idx,
            last_track_index=end_idx,
            n_points=(end_idx - start_idx + 1),
        ))

        box_counter += 1

        if end_idx == n - 1:
            break

        target_advance_km = chunk_km - overlap_km
        advanced_km = 0.0
        next_start_idx = start_idx

        while next_start_idx + 1 < n and advanced_km < target_advance_km:
            p1 = track[next_start_idx]
            p2 = track[next_start_idx + 1]
            d_m, _, _ = gps2dist_azimuth(
                p1.lat, wrap_lon_deg(p1.lon),
                p2.lat, wrap_lon_deg(p2.lon)
            )
            advanced_km += d_m / 1000.0
            next_start_idx += 1

        if next_start_idx <= start_idx:
            next_start_idx = start_idx + 1

        start_idx = next_start_idx

    return windows


def box_windows_to_download_requests(box_windows):
    """
    Convert BoxWindow objects into the simple request dictionaries that the
    downloader expects.

    Why:
    In the notebook we were doing this conversion manually. For Demo 2 and
    for the library in general, this is one of the main pieces of glue between
    the tiling stage and the download stage.
    """
    requests = []

    for bw in box_windows:
        requests.append(
            {
                "box_id": bw.box.box_id,
                "lat_min": bw.box.lat_min,
                "lat_max": bw.box.lat_max,
                "lon_min": bw.box.lon_min,
                "lon_max": bw.box.lon_max,
                "t_start_utc": bw.t_download_start,
                "t_end_utc": bw.t_download_end,
            }
        )

    return requests