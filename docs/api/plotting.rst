plotting
========

The ``plotting`` module provides visualization utilities for inspecting the pipeline output. All plotting functions require the optional ``[plotting]`` extras:

.. code-block:: bash

   pip install groundtrack[plotting]

This installs ``matplotlib`` and ``cartopy``. If these are not installed and you call a plotting function, you'll get a clear error message.

Functions
---------

**plot_track_and_boxes** — maps the propagated ground track alongside the generated download boxes. Handles antimeridian crossing by splitting boxes that span the dateline. Useful for verifying the tiling looks right before running a long download.

**plot_stations** — maps seismic stations overlaid with the track and boxes. You can pass either all candidate stations or only the filtered set depending on what you want to see.

**plot_station_comparison** — side-by-side view of candidate stations vs. stations that passed the corridor filter. This is the clearest way to verify that the distance filtering is working correctly.

**plot_waveform_comparison** — plots raw instrument counts vs. processed velocity waveform side by side for a single station. Supports optional time window zoom. This is the primary plot for validating the processing chain against a known result.

**plot_all_waveforms** — runs ``plot_waveform_comparison`` across every station in the output directory, deduplicated across overlapping boxes so each station only appears once. Can be restricted to specific boxes and capped at a maximum station count to avoid generating hundreds of figures.

.. automodule:: groundtrack.plotting
   :members:
   :undoc-members:
   :show-inheritance:
