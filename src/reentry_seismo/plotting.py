from __future__ import annotations

import numpy as np
from pathlib import Path

from .geodesy import wrap_lon_deg
from .stations import station_lats_lons

# Check if user has optional plotting dependencies
try:
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    HAS_PLOTTING = True
except ImportError:
    HAS_PLOTTING = False


# Function to check if plotting dependencies are available
def _check_plotting_deps():
    if not HAS_PLOTTING:
        raise ImportError(
            "Plotting requires matplotlib and cartopy. "
            "Install them with: pip install reentry-seismo[plotting]"
        )

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
    _check_plotting_deps()
    
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
                ax.plot(rect_lons, rect_lats, alpha=0.6)
            else:
                # dateline split
                rect_lats = [box.lat_min, box.lat_min, box.lat_max, box.lat_max, box.lat_min]

                rect_lons_1 = [-180.0, box.lon_max, box.lon_max, -180.0, -180.0]
                rect_lons_2 = [box.lon_min, 180.0, 180.0, box.lon_min, box.lon_min]
    
                ax.plot(rect_lons_1, rect_lats, alpha=0.6)
                ax.plot(rect_lons_2, rect_lats, alpha=0.6)

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
    _check_plotting_deps()

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
                ax.plot(rect_lons, rect_lats, alpha=0.6)
            else:
                rect_lats = [box.lat_min, box.lat_min, box.lat_max, box.lat_max, box.lat_min]

                rect_lons_1 = [-180.0, box.lon_max, box.lon_max, -180.0, -180.0]
                rect_lons_2 = [box.lon_min, 180.0, 180.0, box.lon_min, box.lon_min]

                ax.plot(rect_lons_1, rect_lats, alpha=0.6)
                ax.plot(rect_lons_2, rect_lats, alpha=0.6)

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
    _check_plotting_deps()

    all_lats, all_lons = station_lats_lons(all_stations)
    filt_lats, filt_lons = station_lats_lons(filtered_stations)

    fig = plt.figure(figsize=(12, 7))
    ax = plt.axes(projection=ccrs.PlateCarree())

    ax.scatter(all_lons, all_lats, s=18, alpha=0.6, label="Candidate Stations")
    ax.scatter(filt_lons, filt_lats, s=22, alpha=0.9, label="Filtered Stations")

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


def plot_waveform_comparison(
    raw_path,
    proc_path,
    proc_freqmin: float = 1.0,
    proc_freqmax: float = 20.0,
    t_start_utc: str | None = None,
    t_end_utc: str | None = None,
):
    """
    Plot raw vs processed waveform side by side for a single station.

    Why this exists:
    ----------------
    The primary validation plot for the processing pipeline. Shows the
    raw instrument counts alongside the response-removed, bandpass-filtered
    velocity trace so you can verify the processing looks physically reasonable
    and identify impulsive arrivals.

    Args:
        raw_path:       Path to raw MiniSEED file in waveforms/
        proc_path:      Path to processed MiniSEED file in processed/
        proc_freqmin:   Lower bandpass corner used during processing (for title label)
        proc_freqmax:   Upper bandpass corner used during processing (for title label)
        t_start_utc:    Optional zoom start as ISO string e.g. "2025-02-19T03:40:00Z"
        t_end_utc:      Optional zoom end as ISO string e.g. "2025-02-19T03:50:00Z"
    """
    _check_plotting_deps()

    from obspy import read, UTCDateTime
    import matplotlib.dates as mdates

    raw_path = Path(raw_path)
    proc_path = Path(proc_path)

    def read_trace(path):
        st = read(str(path))
        if len(st) == 0:
            return None
        if len(st) > 1:
            st.merge(method=1, fill_value="interpolate")
        return st[0]

    tr_raw = read_trace(raw_path)
    tr_proc = read_trace(proc_path) if proc_path.exists() else None

    if tr_raw is None and tr_proc is None:
        print(f"No data found for {raw_path.stem}")
        return

    # Apply time zoom if requested
    if t_start_utc and t_end_utc:
        t0 = UTCDateTime(t_start_utc)
        t1 = UTCDateTime(t_end_utc)
        if tr_raw is not None:
            tr_raw = tr_raw.copy().trim(t0, t1)
        if tr_proc is not None:
            tr_proc = tr_proc.copy().trim(t0, t1)

    station_id = raw_path.stem.replace("..", ".")
    zoom_label = f"  |  {t_start_utc} — {t_end_utc}" if t_start_utc else ""

    fig, axes = plt.subplots(1, 2, figsize=(14, 3))

    ax_raw = axes[0]
    if tr_raw is not None:
        t_raw = tr_raw.times("matplotlib")
        ax_raw.plot_date(t_raw, tr_raw.data, "-", linewidth=0.6)
        ax_raw.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        ax_raw.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax_raw.xaxis.get_majorticklabels(), rotation=30, ha="right")
        ax_raw.set_ylabel("Counts")
    else:
        ax_raw.text(0.5, 0.5, "No raw data", ha="center", va="center",
                    transform=ax_raw.transAxes, color="gray")
    ax_raw.set_title(f"{station_id}  -  raw")
    ax_raw.set_xlabel("UTC Time")
    ax_raw.grid(alpha=0.3)

    ax_proc = axes[1]
    if tr_proc is not None:
        t_proc = tr_proc.times("matplotlib")
        ax_proc.plot_date(t_proc, tr_proc.data * 1e6, "-", linewidth=0.6, color="tab:orange")
        ax_proc.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        ax_proc.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax_proc.xaxis.get_majorticklabels(), rotation=30, ha="right")
        ax_proc.set_ylabel("Velocity (μm/s)")
    else:
        ax_proc.text(0.5, 0.5, "No processed file found", ha="center", va="center",
                     transform=ax_proc.transAxes, color="gray")
    ax_proc.set_title(f"{station_id}  -  processed ({proc_freqmin}-{proc_freqmax} Hz)")
    ax_proc.set_xlabel("UTC Time")
    ax_proc.grid(alpha=0.3)

    plt.suptitle(f"{station_id}{zoom_label}", fontsize=10)
    plt.tight_layout()
    plt.show()


def plot_all_waveforms(
    boxes_root,
    box_ids: list[str] | str | None = None,
    proc_freqmin: float = 1.0,
    proc_freqmax: float = 20.0,
    t_start_utc: str | None = None,
    t_end_utc: str | None = None,
    max_stations: int = 50,
):
    """
    Plot raw vs processed for every downloaded waveform across all boxes,
    deduplicated by station.

    Why this exists:
    ----------------
    Quick way to visually scan all downloaded data after a pipeline run
    without manually finding and plotting individual files. Deduplicates
    stations that appear in multiple overlapping boxes so each station
    is only plotted once.

    Args:
        boxes_root:     Path to the boxes/ root directory
        box_ids:        Optional single box ID string or list of box ID strings
                        to restrict plotting to specific boxes. If None, plots
                        all boxes up to max_stations.
        proc_freqmin:   Lower bandpass corner (for title label)
        proc_freqmax:   Upper bandpass corner (for title label)
        t_start_utc:    Optional zoom start as ISO string e.g. "2025-02-19T03:40:00Z"
        t_end_utc:      Optional zoom end as ISO string e.g. "2025-02-19T03:50:00Z"
        max_stations:   Maximum number of stations to plot when box_ids is None.
                        Ignored when box_ids is specified.
    """
    _check_plotting_deps()

    from obspy import read, UTCDateTime
    import matplotlib.dates as mdates

    boxes_root = Path(boxes_root)

    # Normalize box_ids to a set for filtering
    if isinstance(box_ids, str):
        box_ids = {box_ids}
    elif box_ids is not None:
        box_ids = set(box_ids)

    # Build deduplicated raw/processed pairs
    seen = set()
    pairs = []

    for raw_path in sorted(boxes_root.glob("box_*/waveforms/*.mseed")):
        box_id = raw_path.parent.parent.name
        if box_ids is not None and box_id not in box_ids:
            continue
        if raw_path.stem in seen:
            continue
        proc_path = raw_path.parent.parent / "processed" / raw_path.name
        seen.add(raw_path.stem)
        pairs.append((raw_path, proc_path))

    if not pairs:
        if box_ids is not None:
            print(f"No waveform files found in specified box(es): {box_ids}")
        else:
            print(f"No waveform files found in {boxes_root}")
        return

    # Only apply max_stations cap when no specific boxes were requested
    if box_ids is None and len(pairs) > max_stations:
        print(f"Found {len(pairs)} stations — plotting first {max_stations}. "
              f"Pass box_ids to plot a specific box, or increase max_stations.")
        pairs = pairs[:max_stations]

    print(f"Plotting {len(pairs)} stations...")

    def read_trace(path):
        st = read(str(path))
        if len(st) == 0:
            return None
        if len(st) > 1:
            st.merge(method=1, fill_value="interpolate")
        return st[0]

    fig, axes = plt.subplots(len(pairs), 2, figsize=(14, 2.5 * len(pairs)), squeeze=False)

    for row, (raw_path, proc_path) in enumerate(pairs):
        tr_raw = read_trace(raw_path)
        tr_proc = read_trace(proc_path) if proc_path.exists() else None

        if t_start_utc and t_end_utc:
            t0 = UTCDateTime(t_start_utc)
            t1 = UTCDateTime(t_end_utc)
            if tr_raw is not None:
                tr_raw = tr_raw.copy().trim(t0, t1)
            if tr_proc is not None:
                tr_proc = tr_proc.copy().trim(t0, t1)

        station_id = raw_path.stem.replace("..", ".")

        ax_raw = axes[row, 0]
        if tr_raw is not None:
            t_raw = tr_raw.times("matplotlib")
            ax_raw.plot_date(t_raw, tr_raw.data, "-", linewidth=0.6)
            ax_raw.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
            ax_raw.xaxis.set_major_locator(mdates.AutoDateLocator())
            plt.setp(ax_raw.xaxis.get_majorticklabels(), rotation=30, ha="right")
            ax_raw.set_ylabel("Counts")
        else:
            ax_raw.text(0.5, 0.5, "No raw data", ha="center", va="center",
                        transform=ax_raw.transAxes, color="gray")
        ax_raw.set_title(f"{station_id}  -  raw")
        ax_raw.grid(alpha=0.3)

        ax_proc = axes[row, 1]
        if tr_proc is not None:
            t_proc = tr_proc.times("matplotlib")
            ax_proc.plot_date(t_proc, tr_proc.data * 1e6, "-", linewidth=0.6, color="tab:orange")
            ax_proc.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
            ax_proc.xaxis.set_major_locator(mdates.AutoDateLocator())
            plt.setp(ax_proc.xaxis.get_majorticklabels(), rotation=30, ha="right")
            ax_proc.set_ylabel("Velocity (μm/s)")
        else:
            ax_proc.text(0.5, 0.5, "No processed file", ha="center", va="center",
                         transform=ax_proc.transAxes, color="gray")
        ax_proc.set_title(f"{station_id}  -  processed ({proc_freqmin}-{proc_freqmax} Hz)")
        ax_proc.grid(alpha=0.3)

        if row == len(pairs) - 1:
            ax_raw.set_xlabel("UTC Time")
            ax_proc.set_xlabel("UTC Time")

    plt.tight_layout()
    plt.show()