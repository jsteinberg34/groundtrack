"""
Unit tests for groundtrack.processing.

Covers the in-memory processing chain (process_stream), the box-inventory
loader, and the disk orchestration (process_box / process_boxes). All tests are
hermetic: synthetic ObsPy objects, pytest tmp_path for disk, verbose=False, and
no assertions on stdout or network access.
"""

import numpy as np
import pytest
from numpy.fft import rfft, rfftfreq

from obspy import Stream

from groundtrack.processing import (
    process_stream,
    process_box,
    process_boxes,
    _load_box_inventory,
)


# --------------------------------------------------------------------------- #
# process_stream -- pre-processing
# --------------------------------------------------------------------------- #

def test_demean_detrend_remove_offset_and_trend(make_trace, synthetic_inventory):
    sr, npts = 100.0, 6000
    t = np.arange(npts) / sr
    # Large DC offset + linear trend on top of an in-band signal.
    data = 100.0 + 0.01 * np.arange(npts) + np.sin(2 * np.pi * 5 * t)

    tr_kwargs = dict(sampling_rate=sr)
    inv = synthetic_inventory(sampling_rate=sr)

    # Isolate pre-processing: disable bandpass and the pre-filter highpass so
    # only demean/detrend can remove the offset.
    common = dict(apply_bandpass=False, pre_filt_low=None, verbose=False)

    on, err_on = process_stream(
        Stream([make_trace(data=data, **tr_kwargs)]), inv, **common
    )
    off, _ = process_stream(
        Stream([make_trace(data=data, **tr_kwargs)]),
        inv,
        demean=False,
        detrend_linear=False,
        **common,
    )

    assert err_on == []
    mean_on = abs(float(np.mean(on[0].data)))
    mean_off = abs(float(np.mean(off[0].data)))
    assert mean_on == pytest.approx(0.0, abs=1.0)
    # Pre-processing, not a later stage, is what removed the offset.
    assert mean_on < mean_off / 10.0


def test_preprocessing_can_be_disabled(make_trace, synthetic_inventory):
    inv = synthetic_inventory()
    processed, errors = process_stream(
        Stream([make_trace()]),
        inv,
        demean=False,
        detrend_linear=False,
        taper_pct=0,
        verbose=False,
    )
    # No pre-processing error, and the trace still made it through.
    assert all(e["stage"] != "preprocess" for e in errors)
    assert len(processed) == 1


# --------------------------------------------------------------------------- #
# process_stream -- response removal
# --------------------------------------------------------------------------- #

def test_response_removal_succeeds_with_matching_inventory(
    make_trace, synthetic_inventory
):
    inv = synthetic_inventory()
    processed, errors = process_stream(Stream([make_trace()]), inv, verbose=False)
    assert len(processed) == 1
    assert errors == []


def test_unmatched_trace_is_recorded_and_skipped(make_stream, synthetic_inventory):
    # Inventory only knows about XX.ABC; the stream also has XX.ZZZ.
    inv = synthetic_inventory(station="ABC")
    stream = make_stream([{"station": "ABC"}, {"station": "ZZZ"}])

    processed, errors = process_stream(stream, inv, verbose=False)

    out_ids = [tr.id for tr in processed]
    assert any(tr_id.startswith("XX.ABC") for tr_id in out_ids)
    assert all(not tr_id.startswith("XX.ZZZ") for tr_id in out_ids)

    bad = [e for e in errors if e["trace_id"].startswith("XX.ZZZ")]
    assert len(bad) == 1
    assert bad[0]["stage"] == "remove_response"


# --------------------------------------------------------------------------- #
# process_stream -- bandpass
# --------------------------------------------------------------------------- #

def test_bandpass_attenuates_out_of_band_energy(make_trace, synthetic_inventory):
    sr, npts = 100.0, 6000
    t = np.arange(npts) / sr
    # 5 Hz in the 1-20 Hz passband, 40 Hz well outside it.
    data = np.sin(2 * np.pi * 5 * t) + np.sin(2 * np.pi * 40 * t)
    inv = synthetic_inventory(sampling_rate=sr)

    processed, errors = process_stream(
        Stream([make_trace(data=data, sampling_rate=sr)]),
        inv,
        apply_bandpass=True,
        verbose=False,
    )
    assert errors == []

    spectrum = np.abs(rfft(processed[0].data))
    freqs = rfftfreq(len(processed[0].data), 1.0 / sr)
    in_band = spectrum[np.argmin(np.abs(freqs - 5.0))]
    out_band = spectrum[np.argmin(np.abs(freqs - 40.0))]
    assert in_band > 10.0 * out_band


def test_bandpass_skipped_when_effective_freqmax_not_above_freqmin(
    make_trace, synthetic_inventory
):
    # Low sampling rate: 0.9 * nyquist = 0.9 Hz <= freqmin (1.0 Hz).
    sr, npts = 2.0, 400
    t = np.arange(npts) / sr
    data = np.sin(2 * np.pi * 0.3 * t)
    inv = synthetic_inventory(sampling_rate=sr)

    processed, errors = process_stream(
        Stream([make_trace(data=data, sampling_rate=sr)]),
        inv,
        apply_bandpass=True,
        verbose=False,
    )
    # Bandpass was skipped, but the trace still returns and records no error.
    assert len(processed) == 1
    assert all(e["stage"] != "bandpass" for e in errors)


# --------------------------------------------------------------------------- #
# _load_box_inventory
# --------------------------------------------------------------------------- #

def test_load_box_inventory_merges_per_station_and_skips_summaries(
    tmp_path, synthetic_inventory
):
    inv_dir = tmp_path / "stations"
    inv_dir.mkdir()

    # Per-station response file -> merged.
    synthetic_inventory(station="ABC").write(
        str(inv_dir / "XX.ABC.xml"), format="STATIONXML"
    )
    # Provider summary file (stem has no dot) -> skipped, never read.
    (inv_dir / "EARTHSCOPE_stations.xml").write_text("<not-real-stationxml/>")

    merged = _load_box_inventory(inv_dir)

    assert merged is not None
    station_codes = {sta.code for net in merged for sta in net}
    assert "ABC" in station_codes


def test_load_box_inventory_merges_multiple_stations(tmp_path, synthetic_inventory):
    inv_dir = tmp_path / "stations"
    inv_dir.mkdir()

    # Two per-station files exercise the merge-into-existing branch.
    synthetic_inventory(station="ABC").write(
        str(inv_dir / "XX.ABC.xml"), format="STATIONXML"
    )
    synthetic_inventory(station="DEF").write(
        str(inv_dir / "XX.DEF.xml"), format="STATIONXML"
    )

    merged = _load_box_inventory(inv_dir)

    assert merged is not None
    station_codes = {sta.code for net in merged for sta in net}
    assert {"ABC", "DEF"} <= station_codes


def test_load_box_inventory_empty_dir_returns_none(tmp_path):
    inv_dir = tmp_path / "stations"
    inv_dir.mkdir()
    assert _load_box_inventory(inv_dir) is None


# --------------------------------------------------------------------------- #
# process_box (disk, tmp_path)
# --------------------------------------------------------------------------- #

def test_process_box_happy_path(tmp_path, make_box_dir):
    box_dir = make_box_dir(tmp_path)
    result = process_box(box_dir, verbose=False)

    assert result["status"] == "ok"
    assert result["traces_out"] > 0
    written = list((box_dir / "processed").glob("*.mseed"))
    assert len(written) > 0


def test_process_box_no_raw_data(tmp_path, make_box_dir):
    box_dir = make_box_dir(tmp_path, with_raw=False)
    result = process_box(box_dir, verbose=False)
    assert result["status"] == "no_raw_data"
    assert result["traces_out"] == 0


def test_process_box_no_inventory(tmp_path, make_box_dir):
    box_dir = make_box_dir(tmp_path, with_inventory=False)
    result = process_box(box_dir, verbose=False)
    assert result["status"] == "no_inventory"
    assert result["traces_out"] == 0


def test_process_box_records_unreadable_waveform(tmp_path, make_box_dir):
    # Valid inventory but no real waveforms, then drop in a corrupt MiniSEED.
    box_dir = make_box_dir(tmp_path, with_raw=False)
    (box_dir / "waveforms" / "corrupt.mseed").write_text("not a real mseed file")

    result = process_box(box_dir, verbose=False)

    assert result["status"] == "ok"
    assert result["traces_out"] == 0
    read_errors = [e for e in result["errors"] if e["stage"] == "read"]
    assert len(read_errors) == 1


def test_process_box_skips_existing_outputs(tmp_path, make_box_dir):
    box_dir = make_box_dir(tmp_path)

    first = process_box(box_dir, verbose=False)
    assert first["traces_out"] > 0

    second = process_box(box_dir, overwrite_existing=False, verbose=False)
    assert second["skipped_existing"] > 0
    assert second["traces_out"] == 0


# --------------------------------------------------------------------------- #
# process_boxes (disk, tmp_path)
# --------------------------------------------------------------------------- #

def test_process_boxes_missing_root_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        process_boxes(tmp_path / "does_not_exist", verbose=False)


def test_process_boxes_discovers_boxes_and_aggregates(tmp_path, make_box_dir):
    boxes_root = tmp_path / "boxes"
    boxes_root.mkdir()
    make_box_dir(boxes_root, box_name="box_000")
    make_box_dir(boxes_root, box_name="box_001")

    manifest = process_boxes(boxes_root, write_manifest=False, verbose=False)

    assert manifest["n_boxes"] == 2
    assert len(manifest["results"]) == 2
    assert manifest["totals"]["traces_out"] > 0


def test_process_boxes_writes_manifest(tmp_path, make_box_dir):
    boxes_root = tmp_path / "boxes"
    boxes_root.mkdir()
    make_box_dir(boxes_root, box_name="box_000")

    process_boxes(boxes_root, write_manifest=True, verbose=False)

    # Manifest is written one level up from boxes_root (alongside downloads).
    assert (tmp_path / "processing_manifest.json").exists()
