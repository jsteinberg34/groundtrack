"""
reentry_seismo

Tools for discovering seismic signals from atmospheric re-entry events
using orbital ground tracks and seismic station data.
"""

__version__ = "0.1.0"

# Allow user to import download_boxes directly from the package
from .download import download_boxes
from .stations import load_and_filter_stations