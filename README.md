# Groundtrack

<a name="readme-top"></a>

<!-- PROJECT SHIELDS -->
[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]
[![LinkedIn][linkedin-shield]][linkedin-url]


<!-- PROJECT LOGO -->
<br />
<div align="center">
  <a href="https://github.com/jsteinberg34/groundtrack">
    <img src="images/logo.png" alt="Logo" width="80" height="80">
  </a>


  <h3 align="center">Groundtrack</h3>

  <p align="center">
    Seismic detection pipeline for atmospheric re-entry events using orbital ground tracks and seismic station data.
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

Groundtrack is a Python library developed to assist with detecting and analyzing seismic signals that are produced when an object re-enters the atmosphere, building off the work of Dr. Fernando: <insert paper reference>. When space debris or a spacecraft re-enters the atmosphere at hypersonic speeds, they generate sonic booms that then couple into the ground and are recorded by seismic stations. Groundtrack automates the full pipeline from orbital data to the processed waveforms, while allowing each piece of the pipeline to be easily configured/called if the user wishes: 

1. Fetches TLE elements from Space-Track using a user-provided NORAD ID
2. Propagates the ground track over a user-defined analysis window
3. Tiles the track into spatial boxes and queries FDSN providers for any nearby seismic stations that fall within a given box
4. Downloads waveform data for stations within a configurable distance from the ground track
5. Applies instrument response removal and bandpass filtering
6. Provides optional visualization tools for validating output

The library was developed at Johns Hopkins University as independent research in collaboration with Dr. Benjamin Fernando (Department of Earth and Planetary Sciences), building on the methodology established in his work on seismic detection of the 2024 Shenzhou-15 re-entry (insert link to his research). The pipeline was first validated in multiple proof-of-concept notebooks replicating published detection results before being migrated into this library format.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



### Built With

This section should list any major frameworks/libraries used to bootstrap your project. Leave any add-ons/plugins for the acknowledgements section. Here are a few examples.

* [![Python][Python]][Python-url]
* [![NumPy][NumPy]][NumPy-url]
* [![ObsPy][ObsPy]][ObsPy-url]
* [![pandas][pandas]][pandas-url]
* [![Space-Track][SpaceTrack]][SpaceTrack-url]



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

Groundtrack requires Space-Track credentials to fetch orbital data. Set them as environment variables:

```bash
export SPACETRACK_USER="your_email@example.com"
export SPACETRACK_PASS="your_password"
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
    cache_dir="data/cache",
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

- [x] Orbital propagation and ground track tiling
- [x] FDSN station discovery with 100 km corridor filter
- [x] MassDownloader-based waveform acquisition
- [x] Instrument response removal and bandpass filtering
- [x] Visualization utilities
- [ ] Automated test suite
- [ ] Full documentation site
- [ ] Parallelized inventory queries for full-orbit runs
- [ ] ML classification of seismic station data

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

- [Dr. Benjamin Fernando](https://eps.jhu.edu) — Johns Hopkins University, Department of Earth and Planetary Sciences. Scientific methodology and validation.
- [ObsPy](https://docs.obspy.org/) — Core seismic data library
- [Skyfield](https://rhodesmill.org/skyfield/) — Orbital propagation
- [Space-Track](https://www.space-track.org) — TLE and TIP message data
- [Ed Williams' Aviation Formulary](http://www.edwilliams.org/avform147.htm) — Cross-track distance formula

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
[product-screenshot]: images/screenshot.png
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
