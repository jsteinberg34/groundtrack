"""
Spatial tiling utilities for converting a propagated orbital track
into download windows for seismic data.
"""

from typing import List
from .types import TrackPoint, BoxWindow


def track_to_box_windows(
    track: List[TrackPoint],
    chunk_km: float = 300.0,
    overlap_km: float = 50.0,
    corridor_km: float = 100.0,
    pre_pad_minutes: int = 2,
    post_pad_minutes: int = 13,
) -> List[BoxWindow]:
    """
    Convert a propagated ground track into spatial-temporal
    download windows.

    Parameters
    ----------
    track : list[TrackPoint]
        Ordered ground track points.
    chunk_km : float
        Along-track chunk length.
    overlap_km : float
        Overlap between neighboring chunks.
    corridor_km : float
        Cross-track padding around the track.
    pre_pad_minutes : int
        Time padding before the chunk.
    post_pad_minutes : int
        Time padding after the chunk.

    Returns
    -------
    list[BoxWindow]
    """

    # Temporary placeholder so imports work
    return []