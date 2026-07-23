# Groundtrack

<a name="readme-top"></a>

<!-- PROJECT SHIELDS -->
[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]
[![LinkedIn][linkedin-shield]][linkedin-url]
[![Documentation](https://readthedocs.org/projects/groundtrack/badge/?version=latest&style=for-the-badge)](https://groundtrack.readthedocs.io/en/latest/)
[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.20100697-blue?style=for-the-badge)](https://doi.org/10.5281/zenodo.20100696)
[![CI](https://img.shields.io/github/actions/workflow/status/jsteinberg34/groundtrack/ci.yml?branch=main&style=for-the-badge&label=tests)](https://github.com/jsteinberg34/groundtrack/actions/workflows/ci.yml)
[![codecov](https://img.shields.io/codecov/c/github/jsteinberg34/groundtrack?style=for-the-badge)](https://codecov.io/gh/jsteinberg34/groundtrack)


<!-- PROJECT LOGO -->
<br />
<div align="center">
  <a href="https://github.com/jsteinberg34/groundtrack">
    <img src="Images/GroundtrackLogo.png" alt="Logo" width="80" height="80">
  </a>


  <h3 align="center">Groundtrack</h3>

  <p align="center">
    Seismic waveform pipeline for atmospheric re-entry events using orbital ground tracks and seismic station data.
    <br />
    <br />
    <a href="#usage"><strong>Quick Start »</strong></a>
    ·
    <a href="https://github.com/jsteinberg34/groundtrack/issues">Report Bug</a>
    ·
    <a href="https://github.com/jsteinberg34/groundtrack/issues">Request Feature</a>
  </p>
</div>

<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li><a href="#about-the-project">About The Project</a></li>
    <li><a href="#built-with">Built With</a></li>
    <li><a href="#getting-started">Getting Started</a></li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>

<!-- ABOUT THE PROJECT -->
## About The Project

Groundtrack is a Python library developed for discovering and analyzing seismic signals that are produced when an object re-enters the atmosphere. When space debris or a spacecraft re-enters the atmosphere at hypersonic speeds, it generates sonic booms that then couple into the ground and are recorded by seismic stations. Groundtrack automates the full pipeline from orbital data to the processed waveforms, while allowing each piece of the pipeline to be easily configured/called if the user wishes: 

1. Fetches TLE elements from Space-Track using a user-provided NORAD ID
2. Propagates the ground track over a user-defined analysis window
3. Tiles the track into spatial boxes, automatically skips boxes that are entirely over open ocean, and queries FDSN providers for nearby seismic stations in the remaining boxes
4. Downloads waveform data for stations within a configurable distance from the ground track
5. Applies instrument response removal and bandpass filtering
6. Provides optional visualization tools for validating output

The library was developed at Johns Hopkins University as independent research in collaboration with Dr. Benjamin Fernando (Department of Earth and Planetary Sciences), building on the methodology established in his [work on seismic detection of the 2024 Shenzhou-15 re-entry](https://www.science.org/doi/10.1126/science.adz4676). The pipeline was first validated in multiple proof-of-concept Jupyter notebooks replicating published detection results before being migrated into this library format.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



### Built With

* [![Python][Python]][Python-url]
* [![NumPy][NumPy]][NumPy-url]
* [![ObsPy][ObsPy]][ObsPy-url]
* [![pandas][pandas]][pandas-url]
* [![Space-Track][SpaceTrack]][SpaceTrack-url]
* [![Skyfield][Skyfield]][Skyfield-url]
* [![global-land-mask][GlobalLandMask]][GlobalLandMask-url]



### Optional Features

Groundtrack includes built-in plotting utilities for analyzing re-entry events:

- Ground track + download boxes visualization
- Station distribution maps
- Raw vs. processed waveform comparisons

Install with plotting support:

```bash
pip install groundtrack[plotting]
```

* [![matplotlib][matplotlib]][matplotlib-url]
* [![cartopy][cartopy]][cartopy-url]

<p align="right">(<a href="#readme-top">back to top</a>)</p>


<!-- GETTING STARTED -->
## Getting Started

### Prerequisites

- Python 3.10+
- A free [Space-Track](https://www.space-track.org/auth/createAccount) account for TLE and TIP message access

### Installation

Install from PyPI:

```bash
pip install groundtrack
```

With optional plotting support:

```bash
pip install groundtrack[plotting]
```

### Credentials

Groundtrack requires Space-Track credentials to fetch orbital data. Create a `.env` file in your project root:

```
SPACETRACK_USER=your_email@example.com
SPACETRACK_PASS=your_password
```

Add `.env` to your `.gitignore` to avoid accidentally committing credentials:

```bash
echo ".env" >> .gitignore
```

Or pass them directly to `run_pipeline()`:

```python
results = run_pipeline(
    ...,
    username="your_email@example.com",
    password="your_password",
)
```

<p align="right">(<a href="#readme-top">back to top</a>)</p>


<!-- USAGE EXAMPLES -->
## Usage

### Minimal Example

```python
from groundtrack import run_pipeline

results = run_pipeline(
    norad_id=56873,
    start="2024-04-02T08:40:00Z",
    end="2024-04-02T09:00:00Z",
    cache_dir="data/cache",
    output_dir="data/outputs",
    event_name="shenzhou15_reentry",
)
```

### With Processing and Custom Parameters

```python
results = run_pipeline(
    norad_id=56873,
    start="2024-04-02T08:40:00Z",
    end="2024-04-02T09:00:00Z",
    cache_dir="data/cache",
    output_dir="data/outputs",
    event_name="shenzhou15_reentry",
    corridor_km=100.0,          # station inclusion threshold
    chunk_km=300.0,             # along-track box size
    apply_processing=True,      # remove instrument response + bandpass
    freqmin=1.0,                # bandpass lower corner (Hz)
    freqmax=20.0,               # bandpass upper corner (Hz)
)
```

### Two-Step Workflow

Download first, process later with different parameters:

```python
from groundtrack import run_pipeline, process_boxes

# Step 1 - download only
results = run_pipeline(
    norad_id=56873,
    start="2024-04-02T08:40:00Z",
    end="2024-04-02T09:00:00Z",
    cache_dir="data/cache",       # TLEs are cached here to avoid redundant Space-Track requests
    output_dir="data/outputs",
    event_name="shenzhou15_reentry",
)

# Step 2 - process separately with custom settings
process_boxes(
    boxes_root=results["manifest"]["boxes_root"],
    freqmin=1.0,
    freqmax=10.0,
)
```

### Visualization

```python
from groundtrack import (
    plot_track_and_boxes,
    plot_stations,
    plot_all_waveforms,
)
from pathlib import Path

# Plot ground track and download boxes
plot_track_and_boxes(
    track_points=results["track"]["track_points"],
    box_windows=results["boxes"],
)

# Plot all processed waveforms for a specific box
plot_all_waveforms(
    boxes_root=Path(results["manifest"]["boxes_root"]),
    box_ids="box_006",
    t_start_utc="2024-04-02T08:44:00Z",
    t_end_utc="2024-04-02T08:54:00Z",
)
```

<p align="right">(<a href="#readme-top">back to top</a>)</p>


<!-- ROADMAP -->
## Roadmap

- [x] Validated against Shenzhou-15 re-entry event
- [x] Space-Track TLE fetching with local caching
- [x] Orbital propagation and ground track tiling
- [x] FDSN station discovery with 100 km corridor filter (configurable)
- [x] MassDownloader-based waveform acquisition
- [x] Instrument response removal and bandpass filtering
- [x] Visualization utilities
- [x] Automated test suite
- [x] Full documentation site
- [x] Ocean-tile filtering to skip all-ocean boxes before FDSN queries (~45% speedup on station query phase)
- [ ] Parallelized station queries for full-orbit passes
- [ ] Automated sonic boom detection and classification
- [ ] Trajectory reconstruction from detection results
- [ ] Live re-entry support with real-time orbital data updates

See the [open issues](https://github.com/jsteinberg34/groundtrack/issues) for a full list of proposed features and known issues.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTRIBUTING -->
## Contributing

Contributions are welcome. If you have a suggestion or find a bug, please open an issue or submit a pull request.

1. Fork the project
2. Create your feature branch (`git checkout -b feature/YourFeature`)
3. Commit your changes (`git commit -m 'Add YourFeature'`)
4. Push to the branch (`git push origin feature/YourFeature`)
5. Open a pull request

### Running the tests

The test suite covers the pure geometry and data modules (`geodesy`, `tiling`,
`types`) and requires no network access or external data. Install the test
extras and run pytest:

```sh
pip install -e ".[test]"
pytest
```

To see a coverage report for the package:

```sh
pytest --cov=groundtrack --cov-report=term-missing
```

Every push and pull request runs the suite on Python 3.10 and 3.13 via GitHub
Actions, and coverage is reported to Codecov.

<p align="right">(<a href="#readme-top">back to top</a>)</p>


<!-- LICENSE -->
## License

Distributed under the MIT License. See `LICENSE` for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTACT -->
## Contact

Joseph Steinberg - [LinkedIn](https://www.linkedin.com/in/joey-steinberg/) - josephsteinberg933@gmail.com

Project Link: [https://github.com/jsteinberg34/groundtrack](https://github.com/jsteinberg34/groundtrack)

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- ACKNOWLEDGMENTS -->
## Acknowledgments

- [Dr. Benjamin Fernando](https://eps.jhu.edu/directory/benjamin-fernando/) - Johns Hopkins University, Department of Earth and Planetary Sciences. Scientific methodology and validation.
- [ObsPy](https://docs.obspy.org/) - Core seismic data library
- [Skyfield](https://rhodesmill.org/skyfield/) - Orbital propagation
- [Space-Track](https://www.space-track.org) - TLE and TIP message data
- [Cartopy](https://scitools.org.uk/cartopy/docs/latest/) - Map visualization
- [Ed Williams' Aviation Formulary](http://www.edwilliams.org/avform147.htm) - Spherical cross-track distance formula

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- MARKDOWN LINKS & IMAGES -->
[contributors-shield]: https://img.shields.io/github/contributors/jsteinberg34/groundtrack.svg?style=for-the-badge
[contributors-url]: https://github.com/jsteinberg34/groundtrack/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/jsteinberg34/groundtrack.svg?style=for-the-badge
[forks-url]: https://github.com/jsteinberg34/groundtrack/forks
[stars-shield]: https://img.shields.io/github/stars/jsteinberg34/groundtrack.svg?style=for-the-badge
[stars-url]: https://github.com/jsteinberg34/groundtrack/stargazers
[issues-shield]: https://img.shields.io/github/issues/jsteinberg34/groundtrack.svg?style=for-the-badge
[issues-url]: https://github.com/jsteinberg34/groundtrack/issues
[license-shield]: https://img.shields.io/badge/license-MIT-green?style=for-the-badge
[license-url]: https://github.com/jsteinberg34/groundtrack/blob/main/LICENSE
[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=for-the-badge&logo=linkedin&colorB=555
[linkedin-url]: https://www.linkedin.com/in/joey-steinberg/
[Python]: https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge&logo=python
[Python-url]: https://www.python.org/
[NumPy]: https://img.shields.io/badge/numpy-%23013243.svg?style=for-the-badge&logo=numpy
[NumPy-url]: https://numpy.org/

[ObsPy]: https://img.shields.io/badge/ObsPy-seismology-orange?style=for-the-badge
[ObsPy-url]: https://docs.obspy.org/

[pandas]: https://img.shields.io/badge/pandas-150458?style=for-the-badge&logo=pandas
[pandas-url]: https://pandas.pydata.org/

[SpaceTrack]: https://img.shields.io/badge/Space--Track-API-blue?style=for-the-badge
[SpaceTrack-url]: https://www.space-track.org/

[matplotlib]: https://img.shields.io/badge/matplotlib-plotting-blue?style=for-the-badge
[matplotlib-url]: https://matplotlib.org/

[cartopy]: https://img.shields.io/badge/cartopy-mapping-green?style=for-the-badge
[cartopy-url]: https://scitools.org.uk/cartopy/docs/latest/

[Skyfield]: https://img.shields.io/badge/Skyfield-orbital%20propagation-blue?style=for-the-badge
[Skyfield-url]: https://rhodesmill.org/skyfield/

[GlobalLandMask]: https://img.shields.io/badge/global--land--mask-land%20detection-green?style=for-the-badge
[GlobalLandMask-url]: https://pypi.org/project/global-land-mask/
