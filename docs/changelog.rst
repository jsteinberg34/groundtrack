Changelog
=========

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
