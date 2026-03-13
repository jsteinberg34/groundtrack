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


@dataclass
class BoxWindow:
    """
    Spatial + temporal window used for a MassDownloader query.
    """
    box: GeoBox
    starttime: datetime
    endtime: datetime