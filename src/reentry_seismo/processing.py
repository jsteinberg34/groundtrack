from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from obspy import Stream, read, read_inventory
from obspy.core.inventory import Inventory


# ---------------------------------------------------------------------------
# Validated defaults
# ---------------------------------------------------------------------------
#
# These defaults come from the single-waveform test notebook that reproduced
# Dr. Fernando's figure for SMI/SEV during the Shenzhou-15 re-entry. Changing
# them silently will change scientific results, so they live at module scope
# where they are easy to find and audit.
#
# pre_filt notes:
#   Upper corners are computed dynamically per trace as 90/95% of the
#   trace's Nyquist frequency (sampling_rate / 2), preserving as much
#   high-frequency information as the station allows. Lower corners are
#   fixed via DEFAULT_PRE_FILT_LOW. Pass pre_filt_low=None to skip the
#   pre-filter entirely.
#
DEFAULT_WATER_LEVEL = 60
DEFAULT_OUTPUT = "VEL"          # velocity in m/s, matches Dr. Fernando's paper
DEFAULT_TAPER_PCT = 0.05
DEFAULT_FREQMIN = 1.0
DEFAULT_FREQMAX = 20.0
DEFAULT_CORNERS = 4
DEFAULT_ZEROPHASE = False

# Lower two corners are fixed defaults. Upper two corners (f3, f4) are
# computed dynamically per trace as 90/95% of each trace's Nyquist frequency,
# preserving as much high-frequency information as the station allows.
# Dr. Fernando: "preserve as much information as possible - don't throw away
# high frequencies for stations that have them."
DEFAULT_PRE_FILT_LOW = (0.5, 0.8)  # lower corners only - upper computed per trace


# ---------------------------------------------------------------------------
# Inventory handling
# ---------------------------------------------------------------------------

def _load_box_inventory(inv_dir: Path) -> Inventory | None:
    """
    Read every per-station StationXML file in a box's stations/ directory
    and merge them into one Inventory object.

    Why this exists:
    ----------------
    MassDownloader writes one StationXML per station with full response
    information (e.g. CI.ADO.xml, NN.LYSIM.xml). The same directory also
    contains provider-level inventory files from the Phase 1 discovery
    step (e.g. EARTHSCOPE_stations.xml) which only have station-level
    metadata with no response data. We skip those: they add nothing
    useful to remove_response() and just bloat the merged inventory.

    The discriminator is the filename. Per-station files look like
    "{NETWORK}.{STATION}.xml" (exactly one dot in the stem); provider
    files do not match that pattern.
    """
    xml_files = sorted(inv_dir.glob("*.xml"))
    if not xml_files:
        return None

    merged: Inventory | None = None
    for xml in xml_files:
        # Only merge per-station response files, not provider-level summaries.
        # Stem "CI.ADO" -> keep; stem "EARTHSCOPE_stations" -> skip.
        if xml.stem.count(".") != 1:
            continue

        try:
            inv = read_inventory(str(xml))
        except Exception as e:
            print(f"    could not read inventory {xml.name}: {repr(e)}")
            continue

        if merged is None:
            merged = inv
        else:
            merged += inv

    return merged


# ---------------------------------------------------------------------------
# Core per-stream processing
# ---------------------------------------------------------------------------

def process_stream(
    stream: Stream,
    inventory: Inventory,
    # Pre-processing (before response removal)
    demean: bool = True,
    detrend_linear: bool = True,
    taper_pct: float = DEFAULT_TAPER_PCT,
    # Response removal
    output: str = DEFAULT_OUTPUT,
    pre_filt_low: tuple[float, float] | None = DEFAULT_PRE_FILT_LOW,
    water_level: float = DEFAULT_WATER_LEVEL,
    # Bandpass (after response removal)
    apply_bandpass: bool = True,
    freqmin: float = DEFAULT_FREQMIN,
    freqmax: float = DEFAULT_FREQMAX,
    corners: int = DEFAULT_CORNERS,
    zerophase: bool = DEFAULT_ZEROPHASE,
    verbose: bool = True,
) -> tuple[Stream, list[dict]]:
    """
    Apply the validated processing chain to a Stream in-place-copy style.

    Pipeline (matches the test notebook that reproduced Dr. Fernando's figure):
        1. detrend("demean") → detrend("linear") → taper
        2. remove_response(output=VEL, pre_filt=..., water_level=...)
        3. filter("bandpass", 1–20 Hz, corners=4, zerophase=False)

    Why this exists:
    ----------------
    Every step of this chain is validated against a published figure. We keep
    it in one function so that both single-stream analysis and bulk
    per-box processing go through the same code path.

    Important design choices:
    -------------------------
    - Runs trace-by-trace, not on the whole stream at once, so a single
      bad trace (missing response, dead channel, NaNs after deconvolution)
      only skips itself and does not kill the rest of the station.
    - No trimming. The caller is expected to pass the full downloaded
      window so the bandpass doesn't see filter edge effects in the
      region of interest.
    - Returns a new Stream rather than mutating the input, so the raw
      stream stays inspectable in notebooks.

    Returns:
    --------
    (processed_stream, errors) where errors is a list of
    {"trace_id": ..., "stage": ..., "error": ...} dicts. An empty list
    means every trace made it through.
    """
    processed = Stream()
    errors: list[dict] = []

    for tr in stream:
        tr_id = tr.id
        tr_work = tr.copy()

        # ---- Stage 1: pre-processing ----
        try:
            if demean:
                tr_work.detrend("demean")
            if detrend_linear:
                tr_work.detrend("linear")
            if taper_pct and taper_pct > 0:
                tr_work.taper(max_percentage=taper_pct)
        except Exception as e:
            msg = f"pre-processing failed: {repr(e)}"
            errors.append({"trace_id": tr_id, "stage": "preprocess", "error": msg})
            if verbose:
                print(f"    [skip] {tr_id}: {msg}")
            continue
        
        # ---- Stage 2: response removal ----
        try:
            # Compute upper pre_filt corners dynamically from this trace's
            # sampling rate. This preserves as much high-frequency information
            # as the station allows rather than hardcoding a fixed cutoff.
            # Lower corners stay fixed; upper corners are 90/95% of Nyquist.
            if pre_filt_low is not None:
                nyquist = tr_work.stats.sampling_rate / 2.0
                pre_filt = (
                    pre_filt_low[0],
                    pre_filt_low[1],
                    0.90 * nyquist,
                    0.95 * nyquist,
                )
            else:
                pre_filt = None

            tr_work.remove_response(
                inventory=inventory,
                output=output,
                pre_filt=pre_filt,
                water_level=water_level,
            )
        except Exception as e:
            msg = f"remove_response failed: {repr(e)}"
            errors.append({"trace_id": tr_id, "stage": "remove_response", "error": msg})
            if verbose:
                print(f"    [skip] {tr_id}: {msg}")
            continue

        # ---- Stage 3: bandpass ----
        if apply_bandpass:
            try:
                tr_work.filter(
                    "bandpass",
                    freqmin=freqmin,
                    freqmax=freqmax,
                    corners=corners,
                    zerophase=zerophase,
                )
            except Exception as e:
                msg = f"bandpass failed: {repr(e)}"
                errors.append({"trace_id": tr_id, "stage": "bandpass", "error": msg})
                if verbose:
                    print(f"    [skip] {tr_id}: {msg}")
                continue

        processed += tr_work

    return processed, errors


# ---------------------------------------------------------------------------
# Per-box processing (disk-based)
# ---------------------------------------------------------------------------

def process_box(
    box_dir: str | Path,
    # Pre-processing
    demean: bool = True,
    detrend_linear: bool = True,
    taper_pct: float = DEFAULT_TAPER_PCT,
    # Response removal
    output: str = DEFAULT_OUTPUT,
    pre_filt_low: tuple[float, float] | None = DEFAULT_PRE_FILT_LOW,
    water_level: float = DEFAULT_WATER_LEVEL,
    # Bandpass
    apply_bandpass: bool = True,
    freqmin: float = DEFAULT_FREQMIN,
    freqmax: float = DEFAULT_FREQMAX,
    corners: int = DEFAULT_CORNERS,
    zerophase: bool = DEFAULT_ZEROPHASE,
    # I/O
    overwrite_existing: bool = False,
    verbose: bool = True,
) -> dict:
    """
    Process every raw waveform file in one box directory.

    Expected layout (same as download_boxes writes):
        box_dir/
            stations/   StationXML files (already on disk)
            waveforms/  raw MiniSEED files
            processed/  <-- outputs written here

    Why this exists:
    ----------------
    This is the unit of work for the bulk processor and also the natural
    thing for a user to call on a single box when they are iterating on
    parameters during exploration.

    Returns a small result dict describing what happened in this box.
    """
    box_dir = Path(box_dir)
    inv_dir = box_dir / "stations"
    wav_dir = box_dir / "waveforms"
    out_dir = box_dir / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    box_id = box_dir.name

    raw_files = sorted(wav_dir.glob("*.mseed"))
    if not raw_files:
        if verbose:
            print(f"    {box_id}: no raw waveforms to process")
        return {
            "box_id": box_id,
            "status": "no_raw_data",
            "traces_in": 0,
            "traces_out": 0,
            "skipped_existing": 0,
            "errors": [],
        }

    inventory = _load_box_inventory(inv_dir)
    if inventory is None:
        if verbose:
            print(f"    {box_id}: no inventory files found -- cannot remove response")
        return {
            "box_id": box_id,
            "status": "no_inventory",
            "traces_in": len(raw_files),
            "traces_out": 0,
            "skipped_existing": 0,
            "errors": [],
        }

    traces_in = 0
    traces_out = 0
    skipped = 0
    errors: list[dict] = []

    for raw_path in raw_files:
        out_path = out_dir / raw_path.name

        if out_path.exists() and not overwrite_existing:
            skipped += 1
            continue

        try:
            st = read(str(raw_path))
        except Exception as e:
            msg = f"read failed: {repr(e)}"
            errors.append({"trace_id": raw_path.name, "stage": "read", "error": msg})
            if verbose:
                print(f"    [skip] {raw_path.name}: {msg}")
            continue

        traces_in += len(st)

        proc_st, proc_errors = process_stream(
            st,
            inventory=inventory,
            demean=demean,
            detrend_linear=detrend_linear,
            taper_pct=taper_pct,
            output=output,
            pre_filt_low=pre_filt_low,
            water_level=water_level,
            apply_bandpass=apply_bandpass,
            freqmin=freqmin,
            freqmax=freqmax,
            corners=corners,
            zerophase=zerophase,
            verbose=verbose,
        )

        errors.extend(proc_errors)

        if len(proc_st) == 0:
            # All traces in this file failed -- nothing to write.
            continue

        try:
            proc_st.write(str(out_path), format="MSEED")
            traces_out += len(proc_st)
        except Exception as e:
            msg = f"write failed: {repr(e)}"
            errors.append({"trace_id": raw_path.name, "stage": "write", "error": msg})
            if verbose:
                print(f"    [skip] {raw_path.name}: {msg}")

    if verbose:
        print(
            f"    {box_id}: {traces_out}/{traces_in} traces processed "
            f"| {skipped} skipped (existing) | {len(errors)} errors"
        )

    return {
        "box_id": box_id,
        "status": "ok",
        "traces_in": traces_in,
        "traces_out": traces_out,
        "skipped_existing": skipped,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Bulk processing across an entire boxes/ tree
# ---------------------------------------------------------------------------

def process_boxes(
    boxes_root: str | Path,
    # Pre-processing
    demean: bool = True,
    detrend_linear: bool = True,
    taper_pct: float = DEFAULT_TAPER_PCT,
    # Response removal
    output: str = DEFAULT_OUTPUT,
    pre_filt_low: tuple[float, float] | None = DEFAULT_PRE_FILT_LOW,
    water_level: float = DEFAULT_WATER_LEVEL,
    # Bandpass
    apply_bandpass: bool = True,
    freqmin: float = DEFAULT_FREQMIN,
    freqmax: float = DEFAULT_FREQMAX,
    corners: int = DEFAULT_CORNERS,
    zerophase: bool = DEFAULT_ZEROPHASE,
    # I/O
    overwrite_existing: bool = False,
    verbose: bool = True,
    write_manifest: bool = True,
) -> dict:
    """
    Process every box under a boxes/ root directory.

    This is the standalone entry point for the two-step workflow:

        download_boxes(...)                  # raw only
        process_boxes(boxes_root, ...)       # parameters can be tuned later

    Why this exists:
    ----------------
    Users will often want to download once and then experiment with
    processing parameters (water_level, pre_filt, bandpass corners, etc.)
    across multiple runs. Keeping this separate from download_boxes means
    they never have to re-hit the data center to change a filter setting.

    Parameter defaults must stay in sync with download_boxes(apply_processing=True)
    so switching between the one-shot and two-step workflows is a no-op
    scientifically.

    Returns a manifest dict. If write_manifest is True and boxes_root
    lives under an event folder, the manifest is also written to
    <event>/processing_manifest.json.
    """
    boxes_root = Path(boxes_root)
    if not boxes_root.exists():
        raise FileNotFoundError(f"boxes_root does not exist: {boxes_root}")

    box_dirs = sorted([p for p in boxes_root.iterdir() if p.is_dir() and p.name.startswith("box_")])

    if verbose:
        print(f"Processing {len(box_dirs)} boxes under {boxes_root}")

    results = []
    total_in = 0
    total_out = 0
    total_skipped = 0
    total_errors = 0

    for k, box_dir in enumerate(box_dirs, start=1):
        if verbose:
            print(f"[{k}/{len(box_dirs)}] {box_dir.name} ...")

        box_result = process_box(
            box_dir,
            demean=demean,
            detrend_linear=detrend_linear,
            taper_pct=taper_pct,
            output=output,
            pre_filt_low=pre_filt_low,
            water_level=water_level,
            apply_bandpass=apply_bandpass,
            freqmin=freqmin,
            freqmax=freqmax,
            corners=corners,
            zerophase=zerophase,
            overwrite_existing=overwrite_existing,
            verbose=verbose,
        )
        results.append(box_result)

        total_in += box_result["traces_in"]
        total_out += box_result["traces_out"]
        total_skipped += box_result["skipped_existing"]
        total_errors += len(box_result["errors"])

    manifest = {
        "boxes_root": str(boxes_root),
        "n_boxes": len(box_dirs),
        "params": {
            "demean": demean,
            "detrend_linear": detrend_linear,
            "taper_pct": taper_pct,
            "output": output,
            "pre_filt_low": list(pre_filt_low) if pre_filt_low is not None else None,
            "water_level": water_level,
            "apply_bandpass": apply_bandpass,
            "freqmin": freqmin,
            "freqmax": freqmax,
            "corners": corners,
            "zerophase": zerophase,
        },
        "totals": {
            "traces_in": total_in,
            "traces_out": total_out,
            "skipped_existing": total_skipped,
            "errors": total_errors,
        },
        "results": results,
    }

    if write_manifest:
        # boxes_root is typically <event_name>/boxes/, so write the manifest
        # one level up alongside download_manifest.json.
        event_folder = boxes_root.parent
        manifest_path = event_folder / "processing_manifest.json"
        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, default=str)
            manifest["manifest_path"] = str(manifest_path)
            if verbose:
                print(f"Manifest saved to: {manifest_path}")
        except Exception as e:
            if verbose:
                print(f"Could not write processing manifest: {repr(e)}")

    if verbose:
        print("\n=== Processing Summary ===")
        print(f"Boxes: {len(box_dirs)}")
        print(f"Traces in: {total_in} | out: {total_out} | "
              f"skipped: {total_skipped} | errors: {total_errors}")

    return manifest