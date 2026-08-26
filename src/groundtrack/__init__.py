"""
groundtrack

Tools for discovering seismic signals from atmospheric re-entry events
using orbital ground tracks and seismic station data.
"""

__version__ = "0.2.2"

# Allow user to import below functions directly from the package
from .download import download_boxes 
from .stations import load_and_filter_stations
from .tiling import track_to_box_windows, box_windows_to_download_requests, filter_ocean_boxes
from .processing import process_boxes, process_box, process_stream
from .pipeline import run_pipeline

from .plotting import (
    plot_track_and_boxes,
    plot_stations,
    plot_station_comparison,
    plot_waveform_comparison,
    plot_all_waveforms,
)
