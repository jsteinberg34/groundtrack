"""
Regression tests for plot_waveform_comparison() and plot_all_waveforms().

Skipped entirely when the optional [plotting] extras (matplotlib, cartopy)
aren't installed. Both are required to skip on, even though the functions
tested here only use matplotlib -- plotting.py's HAS_PLOTTING flag bundles
the two imports together, so cartopy's absence disables these functions too.
CI does not install [plotting] today, so these tests skip there by design;
they run and verify for real whenever [plotting] is installed locally.
"""

import pytest

pytest.importorskip("matplotlib")
pytest.importorskip("cartopy")

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from obspy import Stream

from groundtrack.plotting import plot_waveform_comparison, plot_all_waveforms


def _write_mseed(make_trace, path, **trace_kwargs):
    tr = make_trace(**trace_kwargs)
    path.parent.mkdir(parents=True, exist_ok=True)
    Stream([tr]).write(str(path), format="MSEED")
    return path


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


# --------------------------------------------------------------------------- #
# plot_waveform_comparison
# --------------------------------------------------------------------------- #

def test_plot_waveform_comparison_renders_raw_and_processed(tmp_path, make_trace):
    # Regression test for ax.plot_date() removal in matplotlib >= 3.11: this
    # used to raise AttributeError on both the raw and processed axes.
    raw_path = _write_mseed(make_trace, tmp_path / "waveforms" / "XX.ABC..BHZ.mseed")
    proc_path = _write_mseed(make_trace, tmp_path / "processed" / "XX.ABC..BHZ.mseed")

    plot_waveform_comparison(raw_path, proc_path)

    ax_raw, ax_proc = plt.gcf().axes
    assert isinstance(ax_raw.xaxis.get_major_formatter(), mdates.DateFormatter)
    assert isinstance(ax_proc.xaxis.get_major_formatter(), mdates.DateFormatter)


def test_plot_waveform_comparison_handles_missing_processed_file(tmp_path, make_trace):
    raw_path = _write_mseed(make_trace, tmp_path / "waveforms" / "XX.ABC..BHZ.mseed")
    proc_path = tmp_path / "processed" / "XX.ABC..BHZ.mseed"  # never written

    plot_waveform_comparison(raw_path, proc_path)  # must not raise

    assert len(plt.gcf().axes) == 2


# --------------------------------------------------------------------------- #
# plot_all_waveforms
# --------------------------------------------------------------------------- #

def test_plot_all_waveforms_renders_across_boxes(tmp_path, make_trace):
    boxes_root = tmp_path / "boxes"
    _write_mseed(
        make_trace, boxes_root / "box_000" / "waveforms" / "XX.ABC..BHZ.mseed",
        station="ABC",
    )
    _write_mseed(
        make_trace, boxes_root / "box_000" / "processed" / "XX.ABC..BHZ.mseed",
        station="ABC",
    )
    _write_mseed(
        make_trace, boxes_root / "box_001" / "waveforms" / "XX.DEF..BHZ.mseed",
        station="DEF",
    )  # no processed file for DEF -- exercises the "no processed" placeholder path

    plot_all_waveforms(boxes_root)

    axes = plt.gcf().axes
    assert len(axes) == 4  # 2 stations x (raw, processed) columns

    # ABC has both raw and processed data -- both axes must hit the fixed
    # ax.xaxis_date() + ax.plot() path, not the removed ax.plot_date().
    ax_abc_raw, ax_abc_proc = axes[0], axes[1]
    assert isinstance(ax_abc_raw.xaxis.get_major_formatter(), mdates.DateFormatter)
    assert isinstance(ax_abc_proc.xaxis.get_major_formatter(), mdates.DateFormatter)
