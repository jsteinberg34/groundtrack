tiling
======

The ``tiling`` module converts a propagated ground track into a series of overlapping geographic download boxes, each with an associated time window. These boxes are the unit of work for the download stage.

The core design decision here is that boxes are defined in along-track chunks rather than as a global region. This keeps each FDSN query geographically small, which is much faster and avoids querying stations that are nowhere near the track.

Boxes overlap by ``overlap_km`` (default 50 km) to ensure stations near the boundary between adjacent boxes get picked up by at least one box. Each box also gets a time window padded by ``pre_pad_minutes`` before and ``post_pad_minutes`` after the segment's actual track times, to capture waveform arrivals that occur slightly before or after the object passes overhead.

By default, ``track_to_box_windows`` automatically drops boxes whose entire footprint is over open ocean using ``filter_ocean_boxes``. Since seismic stations only exist on land, these boxes would always return zero results from FDSN. Pass ``skip_ocean=False`` to disable this behaviour.

.. automodule:: groundtrack.tiling
   :members:
   :undoc-members:
   :show-inheritance:
