download
========

The ``download`` module handles waveform acquisition from FDSN seismic data providers. It runs in three phases for each box:

**Phase 1** — inventory query. The library queries each configured provider for the list of stations that exist within the box's geographic bounds. This is a fast, metadata-only request.

**Phase 2** — distance filtering. Each candidate station is checked against the corridor distance threshold, keeping only stations within ``corridor_km`` of the actual ground track.

**Phase 3** — ownership and waveform download. Because neighbouring boxes overlap, the same physical station is often within the corridor of several of them. Each station is claimed by whichever box reaches it first and downloaded exactly once, using that box's own time window; other boxes skip it. ``MassDownloader`` then fetches the waveforms for the stations this box claimed.

Each box writes its output to its own subdirectory (``box_000/``, ``box_001/``, etc.) inside the event's output folder. This per-box directory structure preserves ObsPy's MassDownloader skip-existing behavior, so runs are resumable — if a box was already downloaded, it's skipped on the next run.

.. note::
   A box records **every** station near it in ``logs/filtered_stations.json`` and in ``filtered_station_count``, whether or not it was the box that downloaded them — that list is geometry, and plotting depends on it. What the box actually took responsibility for is reported separately as ``claimed_station_count`` and ``skipped_claimed_elsewhere_count``. A box can legitimately finish with zero waveform files because its neighbours owned all of its stations.

.. note::
   ``max_workers`` (default 3) controls how many boxes download concurrently, and multiplies against ``threads_per_client`` (default 3) for the total connections opened per data centre — keep both modest, since FDSN providers are shared infrastructure. Which box ends up owning a station near several boxes is **not** deterministic when ``max_workers > 1``; the set of stations downloaded is. Pass ``max_workers=1`` for fully sequential, reproducible ownership.

.. automodule:: groundtrack.download
   :members:
   :undoc-members:
   :show-inheritance:
