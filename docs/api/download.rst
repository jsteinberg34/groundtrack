download
========

The ``download`` module handles waveform acquisition from FDSN seismic data providers. It runs in three phases for each box:

**Phase 1** — inventory query. The library queries the providers selected for that box (see :doc:`providers`) for the list of stations that exist within its geographic bounds. This is a fast, metadata-only request. Clients are constructed once per run and reused, rather than rebuilt per box.

**Phase 2** — distance filtering. Each candidate station is checked against the corridor distance threshold, keeping only stations within ``corridor_km`` of the actual ground track.

**Phase 3** — ownership and waveform download. Because neighbouring boxes overlap, the same physical station is often within the corridor of several of them. Each station is claimed by whichever box reaches it first and downloaded exactly once, using that box's own time window; other boxes skip it. ``MassDownloader`` then fetches the waveforms for the stations this box claimed.

.. note::
   Within Phase 3, ``MassDownloader`` applies its own per-station rules, and a station dropped by any of them is listed in that box's ``claimed_not_downloaded`` rather than counted as a failure. Groundtrack sets them as follows:

   - **Location code.** ``location_priorities`` defaults to ``("", "00", "10", "20", "01", "*")``. The first pattern a station matches is used, so it yields one location and the conventional codes win when present. The trailing ``"*"`` keeps stations whose channels sit only at an unlisted code. Before 0.6.1 the default stopped at ``"20"``, and stations carrying ``HHZ``/``BHZ`` only at ``"01"`` (common in regional networks such as UU, SB, GS and NC) were never requested.
   - **Station spacing.** ObsPy's default ``minimum_interstation_distance_in_m`` of 1000 m applies: where stations sit within 1 km of each other, only one of them is downloaded.
   - **Gaps and length.** ``reject_channels_with_gaps=True`` and ``minimum_length=0.9`` are kept deliberately: a trace with gaps or overlaps, or covering less than 90% of the box's window, is discarded.

Each box writes its output to its own subdirectory (``box_000/``, ``box_001/``, etc.) inside the event's output folder. This per-box directory structure preserves ObsPy's MassDownloader skip-existing behavior, so runs are resumable — if a box was already downloaded, it's skipped on the next run.

.. note::
   A box records **every** station near it in ``logs/filtered_stations.json`` and in ``filtered_station_count``, whether or not it was the box that downloaded them — that list is geometry, and plotting depends on it. What the box actually took responsibility for is reported separately as ``claimed_station_count`` and ``skipped_claimed_elsewhere_count``. A box can legitimately finish with zero waveform files because its neighbours owned all of its stations.

.. note::
   ``max_workers`` (default 3) controls how many boxes download concurrently, and ``threads_per_client`` (default 3) how many download threads each box uses per provider. Neither sets the load on a provider: a run keeps at most three requests in flight against any one provider (``PROVIDER_CONCURRENCY_LIMIT``, SCEDC's published limit), and the rest wait. Which box ends up owning a station near several boxes is **not** deterministic when ``max_workers > 1``; the set of stations downloaded is. Pass ``max_workers=1`` for fully sequential, reproducible ownership.

.. automodule:: groundtrack.download
   :members:
   :undoc-members:
   :show-inheritance:
