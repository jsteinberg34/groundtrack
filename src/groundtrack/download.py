from __future__ import annotations

import json
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, Sequence

from obspy import UTCDateTime
from obspy.clients.fdsn import Client
from obspy.clients.fdsn.header import FDSNNoDataException
from obspy.clients.fdsn.mass_downloader import (
    MassDownloader,
    RectangularDomain,
    Restrictions,
)

from .stations import (
    parse_stationxml_files,
    deduplicate_stations,
    filter_stations_by_track_distance,
)

from .processing import (
    process_box,
    DEFAULT_PRE_FILT_LOW,
    DEFAULT_WATER_LEVEL,
    DEFAULT_OUTPUT,
    DEFAULT_TAPER_PCT,
    DEFAULT_FREQMIN,
    DEFAULT_FREQMAX,
    DEFAULT_CORNERS,
    DEFAULT_ZEROPHASE,
)


def _normalize_providers(providers):
    """
    Make sure providers are always in a clean list format.

    Why:
    ObsPy expects provider names as strings. This avoids weird behavior if
    something else gets passed in accidentally.
    """
    if providers is None:
        return []
    return [str(p) for p in providers]


def _count_files(path: Path, pattern: str) -> int:
    """
    Count files recursively underneath a folder.

    Why:
    We use this for quick bookkeeping, like:
        - checking whether a box already has downloaded content
        - recording how many files ended up on disk
    """
    return sum(1 for p in path.rglob(pattern) if p.is_file())


def _provider_station_query(
    client: Client,
    req: dict,
    channel_priorities: Sequence[str],
    level: str = "station",
):
    """
    Query one provider for station inventory inside one box.

    Why:
    This is the coarse discovery step. We are asking:
        "What stations exist in this box and this time window?"
    """
    return client.get_stations(
        starttime=UTCDateTime(req["t_start_utc"]),
        endtime=UTCDateTime(req["t_end_utc"]),
        minlatitude=req["lat_min"],
        maxlatitude=req["lat_max"],
        minlongitude=req["lon_min"],
        maxlongitude=req["lon_max"],
        channel=",".join(channel_priorities),
        level=level,
    )


def _query_provider(
    provider_name: str,
    client: Client,
    req: dict,
    channel_priorities: Sequence[str],
    inv_dir: Path,
) -> Path:
    """Worker: query one FDSN provider and write its StationXML to disk. Returns the xml_path."""
    inv = _provider_station_query(
        client=client,
        req=req,
        channel_priorities=channel_priorities,
        level="station",
    )
    xml_path = inv_dir / f"{provider_name}_stations.xml"
    inv.write(str(xml_path), format="STATIONXML")
    return xml_path


# Upper bound on concurrent boxes. Each worker opens up to threads_per_client
# connections of its own, so the real load on a data centre is the product of
# the two -- at this cap and the default threads_per_client that is already 30
# concurrent connections per provider. FDSN providers are shared research
# infrastructure with no published rate limit, so this exists to stop an
# accidental max_workers=200 from hammering them, not because 10 is a measured
# threshold. Raising it is a deliberate act; see download_boxes().
MAX_WORKERS_CAP = 10


def _station_key(station: dict) -> tuple[str, str]:
    """
    Identity of one physical station, used for cross-box ownership.

    Matches the key deduplicate_stations() already uses, so "the same station"
    means the same thing whether we are collapsing duplicates within one box or
    across the whole run.
    """
    return (station["network"], station["station"])


def _has_waveform_file(wav_dir: Path, network: str, station: str) -> bool:
    """True if this box already has a waveform file for this station."""
    return any(wav_dir.glob(f"{network}.{station}.*.mseed"))


def _existing_station_keys(wav_dir: Path) -> set[tuple[str, str]]:
    """
    Station identities already on disk in this box, read back from filenames.

    Why this exists:
    ----------------
    A resumed run skips boxes that already hold data, so those boxes never go
    through discovery and never claim anything. Without reading their existing
    files back, every station they own would look unclaimed to their
    neighbours, which would download it a second time -- the exact duplication
    the claim mechanism exists to prevent, reintroduced on every resume.

    Files are named ``{network}.{station}.{location}.{channel}.mseed`` by
    _make_mseed_storage(), so the identity is recoverable without a network
    call. Location may be empty, giving five dot-separated fields either way.
    Anything not matching that shape is ignored rather than guessed at: a stray
    file would otherwise be claimed as a station that does not exist.
    """
    keys: set[tuple[str, str]] = set()
    for path in wav_dir.glob("*.mseed"):
        parts = path.name.split(".")
        if len(parts) == 5 and parts[0] and parts[1]:
            keys.add((parts[0], parts[1]))
    return keys


def _claim_stations(kept_stations, claimed: set, claim_lock) -> list[dict]:
    """
    Atomically take ownership of every station here that no other box has taken.

    Why this exists:
    ----------------
    Neighbouring boxes overlap in space and time, so the same physical station
    is routinely a candidate in two or three of them. Without a shared claim,
    each of those boxes downloads it again -- the same station, over nearly the
    same window, fetched two or three times.

    The check and the update must happen in one critical section. A box that
    checked, then downloaded, then recorded its claim would race with any box
    running alongside it: both would see the station as unclaimed and both
    would fetch it. Claiming up front is what makes that impossible.
    """
    with claim_lock:
        mine = [s for s in kept_stations if _station_key(s) not in claimed]
        claimed.update(_station_key(s) for s in mine)
    return mine


def _release_unwritten_claims(mine, wav_dir: Path, claimed: set, claim_lock) -> list[dict]:
    """
    Hand back claims for stations that never reached disk. Returns those stations.

    Why this exists:
    ----------------
    A claim is a promise to download. If the download fails, that promise goes
    unmet -- and because the station is still claimed, no other box will try it,
    so it drops out of the run silently. Releasing gives a box that has not yet
    reached its own claim step a chance to pick it up.

    Only stations with no file are released. MassDownloader can write some files
    before raising, and releasing those would let another box fetch the same data
    a second time, which is the exact thing the claim exists to prevent.
    """
    unwritten = [
        s for s in mine
        if not _has_waveform_file(wav_dir, s["network"], s["station"])
    ]
    with claim_lock:
        claimed.difference_update(_station_key(s) for s in unwritten)
    return unwritten


def _make_mseed_storage(approved_stations: set[tuple[str, str]], wav_dir: Path):
    """
    Build a callable for MassDownloader's mseed_storage parameter.

    MassDownloader calls this once per channel/time-interval it considers
    downloading. Returning a file path means "download here"; returning
    None means "skip this station entirely."

    We use this to enforce the corridor distance filter: only stations
    that passed Phase 1 filtering are in approved_stations.
    """
    def storage(network, station, location, channel, starttime, endtime):
        if (network, station) not in approved_stations:
            return None
        loc = location if location else ""
        return str(wav_dir / f"{network}.{station}.{loc}.{channel}.mseed")

    return storage


def _process_one_box(
    req: dict,
    *,
    boxes_root: Path,
    track_points,
    clients: dict,
    provider_names: Sequence[str],
    corridor_km: float,
    channel_priorities: Sequence[str],
    location_priorities: Sequence[str],
    overwrite_existing: bool,
    verbose: bool,
    claimed: set,
    claim_lock,
    threads_per_client: int,
    apply_processing: bool,
    processing_params: dict,
) -> dict:
    """
    Run the full download pipeline for a single box and return its result dict.

    Why this exists:
    ----------------
    Boxes are independent apart from the shared claim set, so pulling one box's
    work into its own function is what lets several of them run at once. It also
    keeps the per-box logic readable instead of nested three levels deep inside
    a loop.

    ``claimed`` and ``claim_lock`` are shared across every box in one run; each
    box also builds its own MassDownloader rather than sharing one, since
    MassDownloader carries per-instance state whose thread-safety is not
    documented and instantiating it is cheap.
    """
    box_id = req["box_id"]

    box_dir = boxes_root / box_id
    inv_dir = box_dir / "stations"
    wav_dir = box_dir / "waveforms"
    log_dir = box_dir / "logs"

    inv_dir.mkdir(parents=True, exist_ok=True)
    wav_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    existing_mseed = _count_files(wav_dir, "*.mseed")
    existing_xml = _count_files(inv_dir, "*.xml")

    if not overwrite_existing and existing_mseed > 0 and existing_xml > 0:
        # A skipped box still owns whatever is already on its disk. It has to
        # register that ownership, or a neighbour sharing those stations would
        # see them as unclaimed and fetch them again -- reintroducing on every
        # resumed run exactly the duplicates this claim mechanism removes.
        # The filenames carry the identity, so no network call is needed.
        existing_keys = _existing_station_keys(wav_dir)
        with claim_lock:
            claimed.update(existing_keys)

        if verbose:
            print(
                f"    skipping {box_id} (already has data; "
                f"retained {len(existing_keys)} existing claims)"
            )
        return {
            "box_id": box_id,
            "status": "skipped_existing",
            "existing_mseed_files": existing_mseed,
            "existing_stationxml_files": existing_xml,
            "claimed_station_count": len(existing_keys),
        }

    if verbose:
        print(f"    processing {box_id} ...")

    # ------------------------------------------------------------
    # Stage 1: gather candidate inventory files from providers
    # ------------------------------------------------------------
    provider_stationxml_files = []

    with ThreadPoolExecutor(max_workers=max(1, len(clients))) as executor:
        futures = {
            executor.submit(_query_provider, name, client, req, channel_priorities, inv_dir): name
            for name, client in clients.items()
        }
        for future in as_completed(futures):
            provider_name = futures[future]
            try:
                xml_path = future.result()
                provider_stationxml_files.append(xml_path)
                if verbose:
                    print(f"    inventory from {provider_name}: saved {xml_path.name}")
            except FDSNNoDataException:
                if verbose:
                    print(f"    inventory from {provider_name}: no data")
            except Exception as e:
                if verbose:
                    print(f"    inventory from {provider_name}: FAILED -> {repr(e)}")

    # Parse raw candidate stations from the StationXML files we just saved.
    station_rows = parse_stationxml_files(provider_stationxml_files)
    unique_stations = deduplicate_stations(station_rows)

    # ------------------------------------------------------------
    # Stage 2: keep only stations within the physical corridor
    # ------------------------------------------------------------
    kept_stations = filter_stations_by_track_distance(
        unique_stations,
        track_points=track_points,
        corridor_km=corridor_km,
    )

    # This file records *membership*: every station near this box, whether or
    # not this box is the one that ends up downloading it. Plotting and
    # reporting depend on that geometric fact, so it must not be narrowed to
    # the stations this box happens to own.
    filtered_summary_path = log_dir / "filtered_stations.json"
    with open(filtered_summary_path, "w", encoding="utf-8") as f:
        json.dump(kept_stations, f, indent=2, default=str)

    # ------------------------------------------------------------
    # Stage 2b: claim the stations no other box has taken
    # ------------------------------------------------------------
    mine = _claim_stations(kept_stations, claimed, claim_lock)
    n_skipped_claimed_elsewhere = len(kept_stations) - len(mine)

    if verbose:
        print(
            f"    {box_id}: {len(unique_stations)} candidates | "
            f"{len(kept_stations)} within {corridor_km} km | "
            f"{len(mine)} claimed here | "
            f"{n_skipped_claimed_elsewhere} already owned elsewhere"
        )

    # ------------------------------------------------------------
    # Stage 3: bulk waveform download via MassDownloader
    # ------------------------------------------------------------
    approved = {_station_key(s) for s in mine}
    download_error = None

    if approved:
        domain = RectangularDomain(
            minlatitude=req["lat_min"],
            maxlatitude=req["lat_max"],
            minlongitude=req["lon_min"],
            maxlongitude=req["lon_max"],
        )

        restrictions = Restrictions(
            starttime=UTCDateTime(req["t_start_utc"]),
            endtime=UTCDateTime(req["t_end_utc"]),
            network=",".join(sorted({s["network"] for s in mine})),
            station=",".join(sorted({s["station"] for s in mine})),
            channel_priorities=list(channel_priorities),
            location_priorities=list(location_priorities),
            reject_channels_with_gaps=True,
            minimum_length=0.9,
        )

        mdl = MassDownloader(providers=list(provider_names))

        try:
            mdl.download(
                domain,
                restrictions,
                mseed_storage=_make_mseed_storage(approved, wav_dir),
                stationxml_storage=str(inv_dir / "{network}.{station}.xml"),
                threads_per_client=threads_per_client,
            )
        except Exception as e:
            download_error = repr(e)
            if verbose:
                print(f"    MassDownloader error: {download_error}")
            # Anything we claimed but never wrote goes back, so a box that has
            # not claimed yet can still reach it.
            released = _release_unwritten_claims(mine, wav_dir, claimed, claim_lock)
            if verbose and released:
                print(f"    released {len(released)} unwritten claims from {box_id}")

    # Stations we took responsibility for but have no file for. Recorded rather
    # than inferred from a missing file, so a station lost this way is visible.
    claimed_not_downloaded = sorted(
        f"{s['network']}.{s['station']}"
        for s in mine
        if not _has_waveform_file(wav_dir, s["network"], s["station"])
    )

    new_mseed = _count_files(wav_dir, "*.mseed")
    new_xml = _count_files(inv_dir, "*.xml")

    box_result = {
        "box_id": box_id,
        "status": "ok",
        "candidate_station_count": len(unique_stations),
        # Membership: stations near this box, unchanged in meaning.
        "filtered_station_count": len(kept_stations),
        # Ownership: what this box actually took responsibility for.
        "claimed_station_count": len(mine),
        "skipped_claimed_elsewhere_count": n_skipped_claimed_elsewhere,
        "claimed_not_downloaded": claimed_not_downloaded,
        "mseed_files": new_mseed,
        "stationxml_files": new_xml,
    }

    if download_error is not None:
        box_result["download_error"] = download_error

    # ------------------------------------------------------------
    # Optional: process this box's waveforms right after download
    # ------------------------------------------------------------
    if apply_processing and new_mseed > 0:
        if verbose:
            print(f"    processing {box_id} ...")
        proc_result = process_box(
            box_dir,
            overwrite_existing=overwrite_existing,
            verbose=verbose,
            **processing_params,
        )
        box_result["processing"] = {
            "traces_in": proc_result["traces_in"],
            "traces_out": proc_result["traces_out"],
            "skipped_existing": proc_result["skipped_existing"],
            "n_errors": len(proc_result["errors"]),
        }

    return box_result


def download_boxes(
    download_requests: Iterable[dict],
    track_points,
    output_base: str | Path,
    event_name: str,
    corridor_km: float = 100.0,
    providers: Sequence[str] | None = ("EARTHSCOPE",),
    channel_priorities: Sequence[str] = ("HHZ", "BHZ"),
    location_priorities: Sequence[str] = ("", "00", "10", "20"),
    overwrite_existing: bool = False,
    verbose: bool = True,

    # ------------------------------------------------------------------
    # Concurrency
    # ------------------------------------------------------------------
    # max_workers is how many boxes are downloaded at once. It multiplies
    # against threads_per_client (MassDownloader's own internal pool) to give
    # the total concurrent connections per data centre, so the default is kept
    # deliberately low -- these are shared research providers. max_workers=1
    # runs fully sequentially and gives deterministic box ownership.
    max_workers: int = 3,
    threads_per_client: int = 3,

    # ------------------------------------------------------------------
    # Optional post-download processing
    # ------------------------------------------------------------------
    # When apply_processing is False (default), raw data is downloaded and
    # nothing else happens -- this preserves the original behavior. When it
    # is True, each box is processed immediately after its waveforms land
    # on disk, using the parameters below. All defaults match process_boxes()
    # so the one-shot and two-step workflows produce identical output.
    apply_processing: bool = False,
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
    zerophase: bool = DEFAULT_ZEROPHASE
) -> dict:
    """
    Main box-based download pipeline.

    High-level logic:
    -----------------
    For each box:
        1. Query candidate station inventory inside the box
        2. Parse and deduplicate stations
        3. Filter stations by distance to the propagated track
        4. Claim the stations no other box has already taken
        5. Download waveforms only for the stations this box claimed
        6. Save a manifest describing what happened

    Ownership across boxes:
    -----------------------
    Neighbouring boxes overlap, so one physical station is often near several
    of them. Each station is downloaded once, under whichever box claims it
    first, using that box's own time window -- adjacent windows overlap almost
    entirely, so a per-station merged window would buy tens of seconds against
    a window of many minutes and is not worth the complexity.

    Every box still records *all* the stations near it in its
    ``logs/filtered_stations.json`` and in ``filtered_station_count``, whether
    or not it was the box that downloaded them. Ownership is reported
    separately as ``claimed_station_count`` and
    ``skipped_claimed_elsewhere_count``.

    Concurrency:
    ------------
    ``max_workers`` boxes are downloaded at a time (default 3). This multiplies
    against ``threads_per_client`` for total connections per data centre, so
    both are kept low by default. Note that which box ends up owning a station
    near several boxes is not deterministic when ``max_workers > 1``; the set of
    downloaded stations is. Pass ``max_workers=1`` for fully deterministic,
    sequential behaviour.
    """
    requests = list(download_requests)

    run_folder = Path(output_base) / event_name
    boxes_root = run_folder / "boxes"
    boxes_root.mkdir(parents=True, exist_ok=True)

    provider_names = _normalize_providers(providers)

    # Initialize provider clients once up front.
    clients = {}
    for provider_name in provider_names:
        try:
            clients[provider_name] = Client(provider_name)
        except Exception as e:
            if verbose:
                print(f"Could not initialize provider {provider_name}: {repr(e)}")

    # Shared across every box in this run: the set of stations already spoken
    # for, and the lock guarding it. Local to this call, never module state --
    # two concurrent download_boxes() runs for different events must not see
    # each other's claims.
    claimed: set[tuple[str, str]] = set()
    claim_lock = threading.Lock()

    # Register everything already on disk before any box runs.
    #
    # Doing this only inside the workers is not enough. A box that will be
    # skipped registers its stations when its turn comes, but a *fresh* box
    # that runs earlier -- because it was submitted first, or simply won the
    # race for a worker slot -- would see those stations as unclaimed and
    # download a second copy. That is the same duplication this whole
    # mechanism exists to prevent, just triggered by resume ordering rather
    # than by box overlap.
    #
    # Only boxes that will actually be skipped are pre-registered, matching
    # the skip condition below exactly: a partially-downloaded box still needs
    # to run and re-request whatever it is missing.
    if not overwrite_existing:
        for req in requests:
            box_dir = boxes_root / req["box_id"]
            wav_dir, inv_dir = box_dir / "waveforms", box_dir / "stations"
            if not wav_dir.is_dir() or not inv_dir.is_dir():
                continue
            if _count_files(wav_dir, "*.mseed") > 0 and _count_files(inv_dir, "*.xml") > 0:
                claimed.update(_existing_station_keys(wav_dir))

        if verbose and claimed:
            print(f"Pre-registered {len(claimed)} stations already on disk")

    processing_params = {
        "demean": demean,
        "detrend_linear": detrend_linear,
        "taper_pct": taper_pct,
        "output": output,
        "pre_filt_low": pre_filt_low,
        "water_level": water_level,
        "apply_bandpass": apply_bandpass,
        "freqmin": freqmin,
        "freqmax": freqmax,
        "corners": corners,
        "zerophase": zerophase,
    }

    def _run(req):
        return _process_one_box(
            req,
            boxes_root=boxes_root,
            track_points=track_points,
            clients=clients,
            provider_names=provider_names,
            corridor_km=corridor_km,
            channel_priorities=channel_priorities,
            location_priorities=location_priorities,
            overwrite_existing=overwrite_existing,
            verbose=verbose,
            claimed=claimed,
            claim_lock=claim_lock,
            threads_per_client=threads_per_client,
            apply_processing=apply_processing,
            processing_params=processing_params,
        )

    # Boxes are submitted in order so that, with spare worker capacity, claims
    # tend to fall in box order. Ownership is still a race under load -- the
    # guarantee is the downloaded station *set*, not which box holds a given
    # station. max_workers=1 makes ownership deterministic.
    n_workers = max(1, int(max_workers))
    if n_workers > MAX_WORKERS_CAP:
        warnings.warn(
            f"max_workers={n_workers} exceeds the safety cap of "
            f"{MAX_WORKERS_CAP}; clamping. Each worker opens up to "
            f"threads_per_client={threads_per_client} connections of its own, so "
            f"{n_workers} workers would open up to "
            f"{n_workers * threads_per_client} concurrent connections per "
            f"provider. FDSN providers are shared infrastructure. Raise "
            f"groundtrack.download.MAX_WORKERS_CAP deliberately if you have "
            f"cleared the load with the data centres you are querying.",
            stacklevel=2,
        )
        n_workers = MAX_WORKERS_CAP
    results_by_box: dict[str, dict] = {}

    def _failure_result(box_id: str, e: Exception) -> dict:
        # One box blowing up must not take the run with it. Applied identically
        # whether boxes run sequentially or concurrently, so max_workers does
        # not change how a failure is handled.
        if verbose:
            print(f"    {box_id}: FAILED -> {repr(e)}")
        return {"box_id": box_id, "status": "failed", "error": repr(e)}

    if n_workers == 1:
        for req in requests:
            try:
                results_by_box[req["box_id"]] = _run(req)
            except Exception as e:
                results_by_box[req["box_id"]] = _failure_result(req["box_id"], e)
    else:
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = {executor.submit(_run, req): req["box_id"] for req in requests}
            for future in as_completed(futures):
                box_id = futures[future]
                try:
                    results_by_box[box_id] = future.result()
                except Exception as e:
                    results_by_box[box_id] = _failure_result(box_id, e)

    # Report in request order regardless of completion order.
    results = [results_by_box[req["box_id"]] for req in requests]

    n_ok = sum(1 for r in results if r["status"] == "ok")
    n_skip = sum(1 for r in results if r["status"] == "skipped_existing")
    n_fail = sum(1 for r in results if r["status"] == "failed")

    manifest = {
        "event_name": event_name,
        "run_folder": str(run_folder),
        "boxes_root": str(boxes_root),
        "total_requests": len(requests),
        "providers": provider_names,
        "channel_priorities": list(channel_priorities),
        "location_priorities": list(location_priorities),
        "corridor_km": corridor_km,
        "max_workers": n_workers,
        "threads_per_client": threads_per_client,
        # Distinct stations this run took ownership of. Not every claim yields a
        # file -- a provider can decline an individual station without raising --
        # so per-box "claimed_not_downloaded" records the shortfall.
        "unique_stations_claimed": len(claimed),
        "ok": n_ok,
        "skipped_existing": n_skip,
        "failed": n_fail,
        "processing": {
            "applied": apply_processing,
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
            } if apply_processing else None,
        },
        "results": results,
    }

    manifest_path = run_folder / "download_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)

    if verbose:
        print("\n=== Download Summary ===")
        print("OK:", n_ok, "| Skipped:", n_skip, "| Failed:", n_fail)
        print("Manifest saved to:", manifest_path)

    return manifest