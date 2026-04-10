from dataclasses import dataclass
from datetime import datetime


@dataclass
class TrackPoint:
    """
    A single point along the propagated ground track.
    """
    time: datetime
    lat: float
    lon: float
    altitude_km: float | None = None


@dataclass
class GeoBox:
    """
    Geographic bounding box in lat/lon.
    """
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    box_size_deg: float
    lat_idx: int
    lon_idx: int

    @property
    def box_id(self) -> str:
        return f"box_{self.lat_idx:03d}"


@dataclass
class BoxWindow:
    """
    Full spatial + temporal window for one download box.
    """
    box: GeoBox
    t_enter: datetime
    t_exit: datetime
    t_download_start: datetime
    t_download_end: datetime
    first_track_index: int
    last_track_index: int
    n_points: int


@dataclass
class TrackSegment:
    """
    Precomputed geometry for one great-circle arc between two consecutive
    track points. Built lazily per box and reused across station distance
    checks within that box.

    All angular values are in radians.
    """
    lat_a_rad: float
    lon_a_rad: float
    lat_b_rad: float
    lon_b_rad: float
    bearing_ab_rad: float  # initial bearing from A to B
    length_rad: float      # angular arc length of the segment