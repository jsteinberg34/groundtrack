from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt

import cartopy.crs as ccrs
import cartopy.feature as cfeature

from .geodesy import wrap_lon_deg
from .stations import station_lats_lons


def _compute_extent(track_points=None, station_lats=None, station_lons=None, pad_deg=5.0):
    """
    Compute map bounds.

    Why this exists:
    ----------------
    We want the map to automatically zoom to:
        - the track
        - the stations

    instead of hardcoding coordinates.
    """
    lats = []
    lons = []

    if track_points:
        lats.extend([p.lat for p in track_points])
        lons.extend([wrap_lon_deg(p.lon) for p in track_points])

    if station_lats is not None:
        lats.extend(station_lats)
        lons.extend(station_lons)

    if not lats or not lons:
        # fallback global
        return [-180, 180, -90, 90]

    min_lat = min(lats) - pad_deg
    max_lat = max(lats) + pad_deg
    min_lon = min(lons) - pad_deg
    max_lon = max(lons) + pad_deg

    return [min_lon, max_lon, min_lat, max_lat]


def plot_track_and_boxes(track_points, box_windows=None, title="Track + Boxes"):
    """
    Plot the orbital ground track and the generated boxes.

    Why this exists:
    ----------------
    This is your main debugging + validation plot:
        - Are boxes aligned with the track?
        - Are we covering the trajectory properly?
    """
    fig = plt.figure(figsize=(12, 7))
    ax = plt.axes(projection=ccrs.PlateCarree())

    # Track
    if track_points:
        lats = [p.lat for p in track_points]
        lons = [wrap_lon_deg(p.lon) for p in track_points]

        ax.plot(lons, lats, linewidth=2.0, label="Ground Track")

    # Boxes
    if box_windows:
        for bw in box_windows:
            box = bw.box

            if box.lon_min <= box.lon_max:
                rect_lons = [box.lon_min, box.lon_max, box.lon_max, box.lon_min, box.lon_min]
                rect_lats = [box.lat_min, box.lat_min, box.lat_max, box.lat_max, box.lat_min]
                ax.plot(rect_lons, rect_lats, alpha=0.25)
            else:
                # dateline split
                rect_lats = [box.lat_min, box.lat_min, box.lat_max, box.lat_max, box.lat_min]

                rect_lons_1 = [-180.0, box.lon_max, box.lon_max, -180.0, -180.0]
                rect_lons_2 = [box.lon_min, 180.0, 180.0, box.lon_min, box.lon_min]

                ax.plot(rect_lons_1, rect_lats, alpha=0.25)
                ax.plot(rect_lons_2, rect_lats, alpha=0.25)

    extent = _compute_extent(track_points=track_points)
    ax.set_extent(extent, crs=ccrs.PlateCarree())

    ax.add_feature(cfeature.LAND, facecolor="lightgray")
    ax.add_feature(cfeature.OCEAN, facecolor="white")
    ax.add_feature(cfeature.COASTLINE)
    ax.add_feature(cfeature.BORDERS)

    ax.gridlines(draw_labels=True, linestyle="--", alpha=0.5)

    ax.set_title(title)
    ax.legend()

    plt.show()


def plot_stations(
    stations,
    track_points=None,
    box_windows=None,
    title="Stations",
):
    """
    Plot stations (optionally with track + boxes).

    stations = list of station dicts (from stations.py)

    Why this exists:
    ----------------
    This lets you visualize:
        - all downloaded stations OR
        - filtered stations (within corridor)

    depending on what you pass in.
    """
    st_lats, st_lons = station_lats_lons(stations)

    fig = plt.figure(figsize=(12, 7))
    ax = plt.axes(projection=ccrs.PlateCarree())

    # Stations
    ax.scatter(st_lons, st_lats, s=12, alpha=0.9, label="Stations")

    # Track
    if track_points:
        track_lats = [p.lat for p in track_points]
        track_lons = [wrap_lon_deg(p.lon) for p in track_points]

        ax.plot(track_lons, track_lats, linewidth=2.0, label="Ground Track")

    # Boxes (optional overlay)
    if box_windows:
        for bw in box_windows:
            box = bw.box

            if box.lon_min <= box.lon_max:
                rect_lons = [box.lon_min, box.lon_max, box.lon_max, box.lon_min, box.lon_min]
                rect_lats = [box.lat_min, box.lat_min, box.lat_max, box.lat_max, box.lat_min]
                ax.plot(rect_lons, rect_lats, alpha=0.15)
            else:
                rect_lats = [box.lat_min, box.lat_min, box.lat_max, box.lat_max, box.lat_min]

                rect_lons_1 = [-180.0, box.lon_max, box.lon_max, -180.0, -180.0]
                rect_lons_2 = [box.lon_min, 180.0, 180.0, box.lon_min, box.lon_min]

                ax.plot(rect_lons_1, rect_lats, alpha=0.15)
                ax.plot(rect_lons_2, rect_lats, alpha=0.15)

    extent = _compute_extent(
        track_points=track_points,
        station_lats=st_lats,
        station_lons=st_lons,
    )

    ax.set_extent(extent, crs=ccrs.PlateCarree())

    ax.add_feature(cfeature.LAND, facecolor="lightgray")
    ax.add_feature(cfeature.OCEAN, facecolor="white")
    ax.add_feature(cfeature.COASTLINE)
    ax.add_feature(cfeature.BORDERS)

    ax.gridlines(draw_labels=True, linestyle="--", alpha=0.5)

    ax.set_title(title)
    ax.legend()

    plt.show()


def plot_station_comparison(
    all_stations,
    filtered_stations,
    track_points=None,
    title="Station Comparison",
):
    """
    Plot BOTH:
        - all downloaded stations
        - filtered stations (within corridor)

    Why this exists:
    ----------------
    This is your strongest visualization for:
        - showing your filtering works
        - explaining your method to your professor

    Blue = candidates
    Red = kept stations
    """
    all_lats, all_lons = station_lats_lons(all_stations)
    filt_lats, filt_lons = station_lats_lons(filtered_stations)

    fig = plt.figure(figsize=(12, 7))
    ax = plt.axes(projection=ccrs.PlateCarree())

    ax.scatter(all_lons, all_lats, s=10, alpha=0.5, label="All Downloaded Stations")
    ax.scatter(filt_lons, filt_lats, s=14, alpha=0.9, label="Filtered Stations")

    if track_points:
        track_lats = [p.lat for p in track_points]
        track_lons = [wrap_lon_deg(p.lon) for p in track_points]
        ax.plot(track_lons, track_lats, linewidth=2.0, label="Ground Track")

    extent = _compute_extent(
        track_points=track_points,
        station_lats=all_lats,
        station_lons=all_lons,
    )

    ax.set_extent(extent, crs=ccrs.PlateCarree())

    ax.add_feature(cfeature.LAND, facecolor="lightgray")
    ax.add_feature(cfeature.OCEAN, facecolor="white")
    ax.add_feature(cfeature.COASTLINE)
    ax.add_feature(cfeature.BORDERS)

    ax.gridlines(draw_labels=True, linestyle="--", alpha=0.5)

    ax.set_title(title)
    ax.legend()

    plt.show()