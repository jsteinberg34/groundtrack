download
========

The ``download`` module handles waveform acquisition from FDSN seismic data providers. It runs in two phases for each box:

**Phase 1** — inventory query. The library queries each configured provider for the list of stations that exist within the box's geographic bounds. This is a fast, metadata-only request.

**Phase 2** — distance filtering and waveform download. Each candidate station is checked against the corridor distance threshold. Only stations within ``corridor_km`` of the actual ground track are kept, and ``MassDownloader`` is used to fetch the waveform data for those stations.

Each box writes its output to its own subdirectory (``box_000/``, ``box_001/``, etc.) inside the event's output folder. This per-box directory structure preserves ObsPy's MassDownloader skip-existing behavior, so runs are resumable — if a box was already downloaded, it's skipped on the next run.

.. note::
   The same physical station may appear in multiple overlapping boxes. This is expected and handled at the processing and visualization stages, which deduplicate by ``(network, station)`` before working with the data.

.. automodule:: groundtrack.download
   :members:
   :undoc-members:
   :show-inheritance:
