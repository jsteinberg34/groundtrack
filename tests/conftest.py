"""
Shared fixtures for the groundtrack unit test suite.

These helpers build small synthetic ground tracks out of TrackPoint objects so
that the pure geometry modules (geodesy, tiling, types) can be exercised
without any network access or external data. They also synthesize ObsPy
Trace/Stream/Inventory objects and on-disk box directories for the processing
tests -- again with no network and no real waveform data.
"""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from obspy import Stream, Trace, UTCDateTime
from obspy.core.inventory import Channel, Inventory, Network, Site, Station
from obspy.core.inventory.response import Response
from skyfield.api import load

from groundtrack.types import TrackPoint


# A fixed epoch so time-window assertions are deterministic.
EPOCH = datetime(2020, 1, 1, 0, 0, 0)

# obspy.geodetics.degrees2kilometers(1.0) -- one degree of great-circle arc.
# Expected distances are expressed as multiples of this constant rather than
# hard-coded magic numbers.
KM_PER_DEGREE = 111.19492664455873


@pytest.fixture
def make_track():
    """
    Factory for a ground track lying along a parallel of latitude.

    Returns a ``build`` function producing a list of evenly spaced TrackPoint
    objects marching eastward in longitude, one every ``dt_seconds``.
    """
    def build(lat=0.0, lon_start=0.0, lon_step=0.5, n=40, dt_seconds=10):
        return [
            TrackPoint(
                time=EPOCH + timedelta(seconds=dt_seconds * i),
                lat=lat,
                lon=lon_start + lon_step * i,
            )
            for i in range(n)
        ]

    return build


@pytest.fixture
def equator_track(make_track):
    """A 40-point track along the equator from lon 0 to lon ~19.5 degrees."""
    return make_track()


# --------------------------------------------------------------------------- #
# Synthetic ObsPy fixtures for the processing tests
# --------------------------------------------------------------------------- #

# A start time for synthetic traces, distinct from EPOCH's datetime type.
TRACE_START = UTCDateTime(2020, 1, 1, 0, 0, 0)


@pytest.fixture
def make_trace():
    """
    Factory for a synthetic ObsPy Trace.

    Returns a ``build`` function. ``data`` may be an explicit array, or omitted
    to get a default in-band (5 Hz) sine of ``npts`` samples.
    """
    def build(
        data=None,
        sampling_rate=100.0,
        network="XX",
        station="ABC",
        location="",
        channel="BHZ",
        npts=6000,
        freq=5.0,
        starttime=TRACE_START,
    ):
        if data is None:
            t = np.arange(npts) / sampling_rate
            data = np.sin(2 * np.pi * freq * t)
        tr = Trace(data=np.asarray(data, dtype=float))
        tr.stats.network = network
        tr.stats.station = station
        tr.stats.location = location
        tr.stats.channel = channel
        tr.stats.sampling_rate = sampling_rate
        tr.stats.starttime = starttime
        return tr

    return build


@pytest.fixture
def make_stream(make_trace):
    """Factory assembling a Stream from a list of trace-kwarg dicts."""
    def build(trace_kwargs):
        return Stream([make_trace(**kw) for kw in trace_kwargs])

    return build


@pytest.fixture
def synthetic_inventory():
    """
    Factory for a minimal poles/zeros Inventory whose response can be removed.

    The network/station/channel codes default to the same values as
    ``make_trace`` so the trace and inventory match out of the box. Validated
    to make ``Trace.remove_response(output="VEL")`` succeed.
    """
    def build(network="XX", station="ABC", channel="BHZ", sampling_rate=100.0):
        resp = Response.from_paz(
            zeros=[0j, 0j],
            poles=[-0.037 - 0.037j, -0.037 + 0.037j, -250 + 0j],
            stage_gain=1.0,
            stage_gain_frequency=1.0,
            input_units="M/S",
            output_units="COUNTS",
            normalization_frequency=1.0,
            normalization_factor=1.0,
        )
        resp.instrument_sensitivity.value = 1.0
        resp.instrument_sensitivity.frequency = 1.0
        resp.instrument_sensitivity.input_units = "M/S"
        resp.instrument_sensitivity.output_units = "COUNTS"

        cha = Channel(
            code=channel,
            location_code="",
            latitude=0.0,
            longitude=0.0,
            elevation=0.0,
            depth=0.0,
            sample_rate=sampling_rate,
            response=resp,
        )
        sta = Station(
            code=station,
            latitude=0.0,
            longitude=0.0,
            elevation=0.0,
            channels=[cha],
            site=Site(name="synthetic"),
        )
        net = Network(code=network, stations=[sta])
        return Inventory(networks=[net], source="groundtrack-tests")

    return build


@pytest.fixture
def make_box_dir(make_trace, synthetic_inventory):
    """
    Factory building an on-disk box directory under a tmp path.

    Creates ``<root>/<box_name>/{stations,waveforms,processed}/``. When
    ``with_raw`` is set, writes one MiniSEED file per provided trace spec into
    ``waveforms/``. When ``with_inventory`` is set, writes a per-station
    StationXML (``{NET}.{STA}.xml``) into ``stations/`` for each station seen.

    Returns the created box directory Path.
    """
    def build(
        root,
        box_name="box_000",
        trace_kwargs=None,
        with_raw=True,
        with_inventory=True,
    ):
        if trace_kwargs is None:
            trace_kwargs = [{}]  # one default matching trace

        box_dir = root / box_name
        stations = box_dir / "stations"
        waveforms = box_dir / "waveforms"
        (box_dir / "processed").mkdir(parents=True, exist_ok=True)
        stations.mkdir(parents=True, exist_ok=True)
        waveforms.mkdir(parents=True, exist_ok=True)

        traces = [make_trace(**kw) for kw in trace_kwargs]

        if with_raw:
            for i, tr in enumerate(traces):
                out = waveforms / f"{tr.id}.{i}.mseed"
                Stream([tr]).write(str(out), format="MSEED")

        if with_inventory:
            seen = set()
            for kw in trace_kwargs:
                net = kw.get("network", "XX")
                sta = kw.get("station", "ABC")
                cha = kw.get("channel", "BHZ")
                sr = kw.get("sampling_rate", 100.0)
                key = (net, sta)
                if key in seen:
                    continue
                seen.add(key)
                inv = synthetic_inventory(
                    network=net, station=sta, channel=cha, sampling_rate=sr
                )
                inv.write(str(stations / f"{net}.{sta}.xml"), format="STATIONXML")

        return box_dir

    return build


# --------------------------------------------------------------------------- #
# Fixtures for the Shenzhou-15 regression and track/io tests
# --------------------------------------------------------------------------- #

# Decoded epoch of the committed Shenzhou-15 TLE (independent of the analysis
# window, which starts ~3 hours later).
SHENZHOU15_TLE_EPOCH_UTC = "2024-04-02T05:50:34Z"


def fixtures_dir() -> Path:
    """Absolute path to tests/fixtures, resolved relative to this file."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _offline_timescale():
    """
    Pre-warm Skyfield's builtin timescale so any implicit ``load.timescale()``
    call (e.g. inside ``build_satellite_from_tle``) uses bundled data and never
    attempts a network/file download. Keeps the suite hermetic.
    """
    load.timescale(builtin=True)


@pytest.fixture
def shenzhou15_tle():
    """The validated Shenzhou-15 TLE as a ``(line1, line2)`` tuple."""
    text = (fixtures_dir() / "shenzhou15.tle").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[0], lines[1]
