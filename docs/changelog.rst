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

0.1.2 (2026-05-30)
------------------

- Added full Sphinx documentation hosted on Read the Docs
- Added CITATION.cff for software citation
- Added contributing and license pages to documentation
- Connected GitHub Actions workflow for automated PyPI publishing
