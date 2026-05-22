pipeline
========

The ``pipeline`` module contains the top-level ``run_pipeline()`` function, which is the primary entry point for the library. It chains together all five pipeline stages — track propagation, spatial tiling, station discovery, waveform download, and optional processing — into a single call.

Most users will only need this module. The underlying stage functions are all importable directly if you need finer control over any individual step.

.. automodule:: groundtrack.pipeline
   :members:
   :undoc-members:
   :show-inheritance:

Parameters Reference
--------------------

``run_pipeline()`` accepts a large number of keyword arguments, all of which have sensible defaults. Here's a summary grouped by stage:

**Required**

- ``norad_id`` — NORAD catalog ID of the object (five-digit integer)
- ``start`` — analysis window start, as an ISO string (``"2024-04-02T08:40:00Z"``) or a ``datetime`` object
- ``end`` — analysis window end, same format as ``start``
- ``cache_dir`` — directory where TLE files will be cached
- ``output_dir`` — base directory for all output
- ``event_name`` — name for this run, used as the output subfolder name

**Propagation**

- ``lookback_days`` (default: 7) — how far back to search for a valid TLE before the analysis start time
- ``step_seconds`` (default: 1) — time step between propagated track points in seconds

**Tiling**

- ``chunk_km`` (default: 300.0) — along-track length of each download box in km
- ``overlap_km`` (default: 50.0) — overlap between adjacent boxes in km
- ``corridor_km`` (default: 100.0) — cross-track distance threshold for station filtering in km
- ``pre_pad_minutes`` (default: 2.0) — time padding before the first track point in each box
- ``post_pad_minutes`` (default: 13.0) — time padding after the last track point in each box

**Download**

- ``providers`` (default: ``("EARTHSCOPE", "SCEDC", "NCEDC")``) — FDSN data providers to query
- ``channel_priorities`` (default: ``("HHZ", "BHZ")``) — channel preference order
- ``location_priorities`` (default: ``("", "00", "10", "20")``) — location code preference order
- ``overwrite_existing`` (default: ``False``) — if ``False``, existing waveforms are skipped

**Processing**

- ``apply_processing`` (default: ``False``) — set to ``True`` to run the full processing chain after download
- ``freqmin`` (default: 1.0) — bandpass lower corner in Hz
- ``freqmax`` (default: 20.0) — bandpass upper corner in Hz
- ``corners`` (default: 4) — bandpass filter order
- ``zerophase`` (default: ``False``) — causal filter; set to ``True`` for zero-phase
- ``water_level`` (default: 60) — water level for response removal
- ``taper_pct`` (default: 0.05) — taper fraction applied before response removal

**Misc**

- ``username`` / ``password`` — Space-Track credentials; if not provided, loaded from environment variables
- ``verbose`` (default: ``True``) — print progress to stdout
