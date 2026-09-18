from __future__ import annotations

import warnings

import numpy as np
from datetime import timedelta
from obspy.geodetics import gps2dist_azimuth, kilometers2degrees
from global_land_mask import globe as _globe

from .types import GeoBox, BoxWindow
from .geodesy import wrap_lon_deg, lon_bounds_dateline_safe


# --------------------------------------------------------------------------- #
# Acoustic constants
#
# All three come from Neidhart et al. (2021), "Statistical analysis of
# fireballs: Seismic signature survey", PASA 38, e016,
# https://doi.org/10.1017/pasa.2021.11
#
# These are empirical survey results, not caller preferences, so they are
# module constants and are deliberately absent from every public signature.
# Exposing them would offer no way to raise them responsibly and one obvious
# motive to lower them (downloading less data), which reintroduces exactly the
# silent clipping this module now warns about.
# --------------------------------------------------------------------------- #

# Section 4: "Beyond 215 km we do not detect any unambiguous seismic signals
# [...] It is therefore reasonable to place a threshold at 215 km as an
# approximate limit for the seismic detection of fireballs."  This is a
# "direct air distance" (abstract), i.e. a true slant range, so it needs no
# height correction.
MAX_SLANT_KM = 215.0

# Upper bound on the altitude at which a shock can form at all: above roughly
# 100 km the mean free path is too large for continuum flow. Corroborated by
# the paper's observed mean bright-flight start height of 86 +/- 25 km.
# Used for the post-pad, which wants the WORST case (longest slant range).
MAX_SOURCE_ALTITUDE_KM = 100.0

# Mean end-of-bright-flight height, h_e = 46 +/- 18 km (Section 3). Used for
# the corridor bound, which asks whether a detection is possible AT ALL and so
# wants the LOWEST emission point (the most favourable geometry).
MIN_SOURCE_ALTITUDE_KM = 46.0


# --------------------------------------------------------------------------- #
# Tunable defaults
#
# Unlike the constants above these ARE caller-configurable; they are named here
# so the value lives in one place rather than being repeated across
# derive_post_pad_minutes(), track_to_box_windows() and run_pipeline(), where
# they would drift apart the first time one of them was edited.
# --------------------------------------------------------------------------- #

# Sits inside max_corridor_km() (210.0 km) with modest room. At this width the
# envelope cap binds, giving a 12.94 min post-pad.
DEFAULT_CORRIDOR_KM = 200.0

# Neidhart et al. (2021) give 300 +/- 60 m/s. The spread is wide -- it spans
# 10.95 to 15.93 min of pad at the default corridor -- so this is the single
# most load-bearing tunable here.
DEFAULT_CELERITY_KM_S = 0.30

# Absorbs SGP4 along-track timing error, which shifts t_exit itself.
DEFAULT_MARGIN_SECONDS = 60.0


def derive_post_pad_minutes(
    corridor_km,
    celerity_km_s=DEFAULT_CELERITY_KM_S,
    margin_seconds=DEFAULT_MARGIN_SECONDS,
):
    """
    Post-pad needed for a shock signal to reach the farthest station in the
    corridor, in minutes.

    The worst case within a corridor is a station at its outer edge receiving
    a shock generated at the highest altitude one can form at, giving a slant
    range of sqrt(corridor_km**2 + MAX_SOURCE_ALTITUDE_KM**2). That is then
    capped by MAX_SLANT_KM: no signal has ever been observed beyond it, so a
    geometry implying a longer range cannot produce a detectable arrival and
    waiting for one is waste.

    celerity_km_s is the effective propagation speed (path distance divided by
    travel time), not the local speed of sound -- refraction makes the real ray
    longer than the straight line being divided. Neidhart et al. give
    300 +/- 60 m/s; that spread is wide, spanning 10.95 to 15.93 minutes of pad
    at a 200 km corridor, so it is exposed as a parameter.

    margin_seconds is not part of the acoustic calculation. It covers error in
    *when* the object was where the propagator says it was. The pad is measured
    from t_exit, which comes from SGP4, and SGP4's dominant error on a decaying
    object is along-track: the real object can reach a given point noticeably
    earlier or later than predicted. If it ran late, every arrival runs late
    with it, and without this buffer the tail could fall past t_download_end.

    Measured along-track divergence on real re-entries is 100-200 s, larger
    than the 60 s default. That is deliberate rather than an oversight: the
    slant/celerity term above is sized to the full detectability envelope,
    which at the default corridor is already ~400 s beyond the largest arrival
    delay ever actually observed, so it carries the rest of the budget. If the
    corridor is narrowed that slack shrinks, and a larger margin becomes worth
    considering.

    Note there is no entry-velocity term. The first-arrival delay does carry a
    Mach-cone factor sqrt(1 - 1/M**2), but at orbital re-entry speeds it is
    worth well under a second. Neidhart et al. put it directly: "The Mach angle
    within the Mach cone is expected to be negligibly small, because the impact
    speed is much larger than the speed of sound in the air."
    """
    # Guard the inputs rather than returning a nonsense window. A zero celerity
    # divides by zero, and a negative one silently produces a NEGATIVE pad,
    # which would put t_download_end BEFORE t_exit and truncate the window --
    # an inverted window looks like a normal short download, so this has to
    # fail loudly rather than propagate.
    if celerity_km_s <= 0:
        raise ValueError(
            f"celerity_km_s must be positive, got {celerity_km_s!r}"
        )
    if corridor_km < 0:
        raise ValueError(f"corridor_km must not be negative, got {corridor_km!r}")
    if margin_seconds < 0:
        raise ValueError(
            f"margin_seconds must not be negative, got {margin_seconds!r}"
        )

    slant_km = min(
        float(np.hypot(corridor_km, MAX_SOURCE_ALTITUDE_KM)),
        MAX_SLANT_KM,
    )
    return (slant_km / celerity_km_s + margin_seconds) / 60.0


def max_corridor_km():
    """
    Largest cross-track corridor the detectability envelope can justify.

    The object is always at altitude, so a station's ground offset is strictly
    less than its slant range. A station is reachable if *any* emission point
    along the trajectory falls inside the envelope, and the lowest emission
    point is the most favourable, so this uses MIN_SOURCE_ALTITUDE_KM rather
    than MAX_SOURCE_ALTITUDE_KM. Using the 100 km continuum ceiling here would
    give 190.3 km and flag a 200 km corridor spuriously.
    """
    return float(np.sqrt(MAX_SLANT_KM ** 2 - MIN_SOURCE_ALTITUDE_KM ** 2))


def filter_ocean_boxes(windows, grid_n=5):
    """
    Remove BoxWindows whose entire footprint is over open ocean.

    Samples a grid_n x grid_n grid of lat/lon points across each box and
    drops any box where every point is ocean. Boxes that contain at least
    one land point are kept.

    Antimeridian-crossing boxes (lon_min > lon_max) are handled by splitting
    the longitude sample into two half-ranges either side of 180°, rather
    than using a single linspace which would sweep the globe in the wrong
    direction.
    """
    kept = []
    for w in windows:
        lats = np.linspace(w.box.lat_min, w.box.lat_max, grid_n)

        if w.box.lon_min <= w.box.lon_max:
            lons = np.linspace(w.box.lon_min, w.box.lon_max, grid_n)
        else:
            lons = np.concatenate([
                np.linspace(w.box.lon_min, 180.0, grid_n // 2 + 1),
                np.linspace(-180.0, w.box.lon_max, grid_n // 2 + 1),
            ])

        lat_grid, lon_grid = np.meshgrid(lats, lons)
        if _globe.is_land(lat_grid.ravel(), lon_grid.ravel()).any():
            kept.append(w)

    return kept


def pad_window(t_enter, t_exit, pre_pad_minutes, post_pad_minutes):
    """
    Expand a satellite pass time window by fixed amounts before and after.

    pre_pad_minutes=2 gives a small buffer before the satellite enters the box.

    post_pad_minutes gives a longer tail after exit, because a shock signal has
    to propagate down to the station at roughly 0.3 km/s long after the object
    itself has gone. Callers normally let track_to_box_windows derive it from
    the corridor via derive_post_pad_minutes() rather than passing a fixed
    value; see that function for the physics and the citation.
    """
    return (
        t_enter - timedelta(minutes=pre_pad_minutes),
        t_exit + timedelta(minutes=post_pad_minutes)
    )


def track_to_box_windows(
    track,
    chunk_km=300.0,
    overlap_km=50.0,
    corridor_km=DEFAULT_CORRIDOR_KM,
    pre_pad_minutes=2,
    post_pad_minutes=None,
    skip_ocean=True,
    celerity_km_s=DEFAULT_CELERITY_KM_S,
    margin_seconds=DEFAULT_MARGIN_SECONDS,
):
    """
    Build overlapping along-track chunks of approximately chunk_km, with
    overlap_km between neighboring chunks.

    Each chunk becomes one candidate download box:
      - along-track extent comes from the chunk points
      - cross-track extent comes from corridor_km padding
      - time window comes from first/last point in chunk plus time padding

    post_pad_minutes defaults to None, meaning derive it from corridor_km,
    celerity_km_s and margin_seconds via derive_post_pad_minutes(). Passing an
    explicit value overrides the derivation exactly; a value shorter than the
    corridor requires warns, because an arrival landing after t_download_end is
    simply absent from the data with nothing to mark it as clipped.
    """
    if len(track) < 2:
        return []

    if overlap_km >= chunk_km:
        raise ValueError("overlap_km must be smaller than chunk_km")

    derived_post_pad = derive_post_pad_minutes(
        corridor_km=corridor_km,
        celerity_km_s=celerity_km_s,
        margin_seconds=margin_seconds,
    )

    if post_pad_minutes is None:
        post_pad_minutes = derived_post_pad
    elif post_pad_minutes < derived_post_pad:
        warnings.warn(
            f"post_pad_minutes={post_pad_minutes:.2f} is shorter than the "
            f"{derived_post_pad:.2f} min that corridor_km={corridor_km:g} and "
            f"celerity_km_s={celerity_km_s:g} imply. Arrivals from the far "
            f"edge of the corridor may fall outside the download window, and a "
            f"clipped arrival is indistinguishable from no detection.",
            UserWarning,
            stacklevel=2,
        )

    corridor_bound = max_corridor_km()
    if corridor_km > corridor_bound:
        warnings.warn(
            f"corridor_km={corridor_km:g} exceeds {corridor_bound:.1f} km, the "
            f"largest ground offset consistent with the {MAX_SLANT_KM:g} km "
            f"detectability envelope. Stations beyond it are being queried at "
            f"distances where no signal has been observed.",
            UserWarning,
            stacklevel=2,
        )

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

        lat_min = float(max(-90.0, lats.min() - corridor_deg_lat))
        lat_max = float(min(90.0, lats.max() + corridor_deg_lat))

        lon_min, lon_max = lon_bounds_dateline_safe(lons)

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
            box_index=box_counter,
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

    if skip_ocean:
        windows = filter_ocean_boxes(windows)

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