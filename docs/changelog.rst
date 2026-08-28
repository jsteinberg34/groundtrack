Changelog
=========

0.3.0 (2026-08-27)
------------------

- Each physical station is now downloaded at most once per run. Overlapping boxes previously fetched the same station once per box that shared it; on the Shenzhou-15 reference event that was 42 of 240 files (17.5%, 4.69 MB) of redundant traffic. Station coverage is unchanged -- the same 198 unique stations, now in 198 files instead of 240, and 24.65 MB instead of 29.34 MB.
- Boxes now download concurrently, controlled by ``max_workers`` (default 3; ``max_workers=1`` restores fully sequential behaviour). Together with the removed duplicate traffic, the Shenzhou-15 reference download went from 148s to 57s (2.6x) in live validation.
- Added ``threads_per_client`` (default 3, unchanged from ObsPy) so total concurrent connections per data centre can be tuned down. It multiplies against ``max_workers``, so both defaults are kept deliberately low.
- ``max_workers`` is clamped to ``MAX_WORKERS_CAP`` (10) with a warning. Because each worker opens up to ``threads_per_client`` connections of its own, an unbounded value would multiply into a large connection count against shared FDSN infrastructure.
- Per-box results now report ownership separately from membership: ``claimed_station_count``, ``skipped_claimed_elsewhere_count`` and ``claimed_not_downloaded`` are new. ``filtered_station_count`` and ``logs/filtered_stations.json`` keep their existing meaning (every station near that box, regardless of which box downloaded it), so plotting and reporting are unaffected. A box may now legitimately finish with zero waveform files because its neighbours owned all of its stations.
- A station claimed by a box whose download then fails is released, so another box can still fetch it instead of the station silently dropping out of the run. Claims for stations that did land on disk are kept, so releasing cannot reintroduce a duplicate.
- A failure in one box no longer aborts the run, at any concurrency level.
- Resumed runs stay deduplicated: a box skipped because it already holds data reads its station identities back from its own filenames and registers them, so neighbours sharing those stations do not fetch them a second time.

.. note::
   Which box ends up owning a station that falls near several boxes is not deterministic when ``max_workers > 1``; the set of stations downloaded is. Use ``max_workers=1`` if reproducible per-box file placement matters.

0.2.3 (2026-08-26)
------------------

- Fixed ``plot_waveform_comparison()`` and ``plot_all_waveforms()`` raising ``AttributeError`` on modern matplotlib (``Axes.plot_date`` was removed in 3.11, not just deprecated). Replaced with ``ax.xaxis_date()`` + ``ax.plot()``, a confirmed drop-in equivalent with no change to rendered output.

0.2.2 (2026-08-26)
------------------

- Fixed ``filter_stations_by_track_distance()`` not passing ``corridor_km`` through to the cross-track refinement in ``min_distance_km_to_track()``, so the boundary-precision correction (present since the initial 0.1.1 release) never actually ran. Now wired up. It only affects stations within 10 km of the corridor threshold (3 of 37 candidates in a real test case), can only rescue stations that were wrongly excluded, never drop ones already included, and adds a few microseconds per affected station -- negligible next to a single station-inventory network query (~100 ms).

0.1.1 (2026-05-09)
------------------

Initial public release.

- TLE fetching from Space-Track with local caching
- Orbital propagation and ground track tiling into spatial download boxes
- FDSN station discovery with 100 km corridor filter (configurable)
- Two-phase MassDownloader-based waveform acquisition
- Instrument response removal and bandpass filtering
- Visualization utilities (requires ``[plotting]`` extras)
- Validated against the Shenzhou-15 re-entry event (NORAD ID 56873)

0.2.1 (2026-07-23)
------------------

- FDSN provider station queries are now issued concurrently (``ThreadPoolExecutor``) rather than sequentially, reducing per-box station-query wall time from ``N × latency`` to ``~latency`` where N is the number of configured providers

0.2.0 (2026-07-22)
------------------

- Added ``filter_ocean_boxes()`` to skip tiles whose entire footprint is over open ocean before querying FDSN providers, reducing station query time by ~45% on tracks with significant ocean coverage (e.g. Shenzhou-15: 35 boxes → 19 boxes, 43 seconds saved on the station-query phase alone)
- ``track_to_box_windows()`` now accepts ``skip_ocean=True`` (default) to apply this filter automatically; pass ``skip_ocean=False`` to restore the previous behaviour
- Added ``global-land-mask`` as a core dependency (1 km-resolution GLOBE land mask, 1.8 MB wheel, no transitive dependencies)

0.1.3 (2026-06-25)
------------------

- Added full automated test suite covering all pipeline stages (geodesy, tiling, types, processing, stations, download, track, pipeline)
- Coverage reported to Codecov on every CI run

0.1.2 (2026-05-30)
------------------

- Added full Sphinx documentation hosted on Read the Docs
- Added CITATION.cff for software citation
- Added contributing and license pages to documentation
- Connected GitHub Actions workflow for automated PyPI publishing
