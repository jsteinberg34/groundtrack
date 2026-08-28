"""
Unit tests for groundtrack.download.

The pure helpers are tested directly. download_boxes is driven with faked FDSN
Client and MassDownloader (monkeypatched at their module-level names) so the
real filtering, storage-callback, file-counting, and manifest logic run with no
network. All on tmp_path.
"""

import json
from datetime import datetime, timezone

import pytest

from groundtrack.download import (
    _normalize_providers,
    _count_files,
    _make_mseed_storage,
    _query_provider,
    download_boxes,
)

from conftest import FakeFDSNClient, FakeMassDownloader


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #

def test_normalize_providers():
    assert _normalize_providers(None) == []
    assert _normalize_providers(("A", "B")) == ["A", "B"]
    assert _normalize_providers(["A", "B"]) == ["A", "B"]
    assert all(isinstance(p, str) for p in _normalize_providers([1, 2]))


def test_count_files_recursive(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "x.mseed").write_text("")
    (tmp_path / "a" / "b" / "y.mseed").write_text("")
    (tmp_path / "a" / "z.xml").write_text("")
    assert _count_files(tmp_path, "*.mseed") == 2
    assert _count_files(tmp_path, "*.xml") == 1


def test_make_mseed_storage_gates_on_approved(tmp_path):
    storage = _make_mseed_storage({("XX", "AAA")}, tmp_path)
    approved_path = storage("XX", "AAA", "", "HHZ", None, None)
    assert approved_path == str(tmp_path / "XX.AAA..HHZ.mseed")
    assert storage("XX", "BBB", "", "HHZ", None, None) is None


def _request(box_id="box_000"):
    return {
        "box_id": box_id,
        "lat_min": -1.0,
        "lat_max": 6.0,
        "lon_min": 0.0,
        "lon_max": 10.0,
        "t_start_utc": datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        "t_end_utc": datetime(2020, 1, 1, 0, 10, 0, tzinfo=timezone.utc),
    }


# --------------------------------------------------------------------------- #
# _query_provider
# --------------------------------------------------------------------------- #

def test_query_provider_writes_stationxml_and_returns_path(tmp_path):
    client = FakeFDSNClient([("XX", "STA", 0.0, 0.0)])
    xml_path = _query_provider("MYPROVIDER", client, _request(), ["HHZ", "BHZ"], tmp_path)
    assert xml_path == tmp_path / "MYPROVIDER_stations.xml"
    assert xml_path.exists()


def test_query_provider_raises_on_no_data(tmp_path):
    from obspy.clients.fdsn.header import FDSNNoDataException

    class NoDataClient:
        def get_stations(self, **kwargs):
            raise FDSNNoDataException("no data")

    with pytest.raises(FDSNNoDataException):
        _query_provider("MYPROVIDER", NoDataClient(), _request(), ["HHZ"], tmp_path)


def test_query_provider_raises_on_generic_error(tmp_path):
    class FailingClient:
        def get_stations(self, **kwargs):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        _query_provider("MYPROVIDER", FailingClient(), _request(), ["HHZ"], tmp_path)


# --------------------------------------------------------------------------- #
# download_boxes with faked clients
# --------------------------------------------------------------------------- #

def _patch_clients(monkeypatch, stations, mdl=FakeMassDownloader):
    monkeypatch.setattr(
        "groundtrack.download.Client", lambda name: FakeFDSNClient(stations)
    )
    monkeypatch.setattr("groundtrack.download.MassDownloader", mdl)


# Two candidate stations: NEAR (~55 km off the equator track) and FAR (~555 km).
STATIONS = [("XX", "NEAR", 0.5, 5.0), ("XX", "FAR", 5.0, 5.0)]


def test_download_boxes_happy_path(tmp_path, monkeypatch, make_track):
    _patch_clients(monkeypatch, STATIONS)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    manifest = download_boxes(
        [_request()], track, output_base=tmp_path, event_name="ev",
        providers=("TEST",), corridor_km=100.0, verbose=False,
    )

    assert manifest["ok"] == 1
    assert manifest["skipped_existing"] == 0
    assert manifest["failed"] == 0
    assert manifest["processing"]["applied"] is False

    box = manifest["results"][0]
    assert box["status"] == "ok"
    assert box["candidate_station_count"] == 2
    assert box["filtered_station_count"] == 1   # only NEAR
    assert box["mseed_files"] == 1
    assert box["stationxml_files"] >= 1

    assert (tmp_path / "ev" / "download_manifest.json").exists()


def test_download_boxes_skips_existing(tmp_path, monkeypatch, make_track):
    _patch_clients(monkeypatch, STATIONS)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    # Pre-seed the box under the exact layout download_boxes inspects.
    box_dir = tmp_path / "ev" / "boxes" / "box_000"
    (box_dir / "waveforms").mkdir(parents=True)
    (box_dir / "stations").mkdir(parents=True)
    (box_dir / "waveforms" / "old.mseed").write_text("x")
    (box_dir / "stations" / "old.xml").write_text("x")

    manifest = download_boxes(
        [_request()], track, output_base=tmp_path, event_name="ev",
        providers=("TEST",), overwrite_existing=False, verbose=False,
    )

    assert manifest["skipped_existing"] == 1
    assert manifest["results"][0]["status"] == "skipped_existing"


def test_download_boxes_apply_processing(tmp_path, monkeypatch, make_track):
    _patch_clients(monkeypatch, STATIONS)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    manifest = download_boxes(
        [_request()], track, output_base=tmp_path, event_name="ev",
        providers=("TEST",), apply_processing=True, verbose=False,
    )

    box = manifest["results"][0]
    assert "processing" in box
    assert set(box["processing"]) == {"traces_in", "traces_out", "skipped_existing", "n_errors"}
    assert manifest["processing"]["applied"] is True


def test_download_boxes_all_stations_rejected(tmp_path, monkeypatch, make_track):
    # Only the FAR station exists -> nothing passes the corridor filter.
    _patch_clients(monkeypatch, [("XX", "FAR", 5.0, 5.0)])
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    manifest = download_boxes(
        [_request()], track, output_base=tmp_path, event_name="ev",
        providers=("TEST",), corridor_km=100.0, verbose=False,
    )

    box = manifest["results"][0]
    assert box["status"] == "ok"
    assert box["filtered_station_count"] == 0
    assert box["mseed_files"] == 0


def test_download_boxes_tolerates_client_init_failure(tmp_path, monkeypatch, make_track):
    def _raising_client(name):
        raise RuntimeError("provider down")

    monkeypatch.setattr("groundtrack.download.Client", _raising_client)
    monkeypatch.setattr("groundtrack.download.MassDownloader", FakeMassDownloader)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    manifest = download_boxes(
        [_request()], track, output_base=tmp_path, event_name="ev",
        providers=("TEST",), verbose=False,
    )
    # No provider clients -> no candidates, but the run completes cleanly.
    assert manifest["ok"] == 1
    assert manifest["failed"] == 0
    assert manifest["results"][0]["candidate_station_count"] == 0


@pytest.mark.parametrize("exc", ["nodata", "generic"])
def test_download_boxes_tolerates_get_stations_errors(tmp_path, monkeypatch, make_track, exc):
    from obspy.clients.fdsn.header import FDSNNoDataException

    error = FDSNNoDataException("no data") if exc == "nodata" else RuntimeError("boom")

    class RaisingClient:
        def get_stations(self, **kwargs):
            raise error

    monkeypatch.setattr("groundtrack.download.Client", lambda name: RaisingClient())
    monkeypatch.setattr("groundtrack.download.MassDownloader", FakeMassDownloader)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    manifest = download_boxes(
        [_request()], track, output_base=tmp_path, event_name="ev",
        providers=("TEST",), verbose=False,
    )
    box = manifest["results"][0]
    assert box["status"] == "ok"
    assert box["candidate_station_count"] == 0  # query failed -> no candidates
    assert manifest["failed"] == 0


def test_download_boxes_tolerates_massdownloader_error(tmp_path, monkeypatch, make_track):
    class RaisingMDL(FakeMassDownloader):
        def download(self, *args, **kwargs):
            raise RuntimeError("download blew up")

    _patch_clients(monkeypatch, STATIONS, mdl=RaisingMDL)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    manifest = download_boxes(
        [_request()], track, output_base=tmp_path, event_name="ev",
        providers=("TEST",), corridor_km=100.0, verbose=False,
    )
    box = manifest["results"][0]
    assert box["status"] == "ok"
    assert box["mseed_files"] == 0  # downloader raised, nothing written
    assert manifest["failed"] == 0


# --------------------------------------------------------------------------- #
# cross-box ownership: each physical station downloaded at most once
# --------------------------------------------------------------------------- #

def _overlapping_requests(n_boxes=3):
    """
    Requests whose boxes all span the same ground, so every candidate station
    is near every box. This is the pathological version of the real overlap:
    without a claim, each box downloads all of them.
    """
    return [_request(box_id=f"box_{i:03d}") for i in range(n_boxes)]


# Three stations, all within the corridor of the equator track.
SHARED_STATIONS = [
    ("XX", "AAA", 0.2, 2.0),
    ("XX", "BBB", 0.3, 5.0),
    ("XX", "CCC", 0.4, 8.0),
]


def _downloaded_station_set(boxes_root):
    """Every (box_id, station) actually written to disk under boxes_root."""
    return {
        (p.parts[-3], p.name.split(".")[1])
        for p in boxes_root.rglob("waveforms/*.mseed")
    }


def test_station_in_multiple_boxes_is_downloaded_exactly_once(
    tmp_path, monkeypatch, make_track
):
    _patch_clients(monkeypatch, SHARED_STATIONS)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    manifest = download_boxes(
        _overlapping_requests(3), track, output_base=tmp_path, event_name="ev",
        providers=("TEST",), corridor_km=100.0, verbose=False, max_workers=1,
    )

    boxes_root = tmp_path / "ev" / "boxes"
    downloaded = _downloaded_station_set(boxes_root)

    # Three stations, three fully overlapping boxes -> still three files.
    assert len(downloaded) == 3
    assert {sta for _, sta in downloaded} == {"AAA", "BBB", "CCC"}
    assert manifest["unique_stations_claimed"] == 3

    # Every box still reports all three as *near* it, even though one box owns them.
    for box in manifest["results"]:
        assert box["filtered_station_count"] == 3


def test_first_box_claims_and_later_boxes_skip(tmp_path, monkeypatch, make_track):
    _patch_clients(monkeypatch, SHARED_STATIONS)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    manifest = download_boxes(
        _overlapping_requests(3), track, output_base=tmp_path, event_name="ev",
        providers=("TEST",), corridor_km=100.0, verbose=False, max_workers=1,
    )

    first, second, third = manifest["results"]

    # Sequential ownership is deterministic: the first box takes everything.
    assert first["claimed_station_count"] == 3
    assert first["skipped_claimed_elsewhere_count"] == 0
    assert first["mseed_files"] == 3

    for later in (second, third):
        assert later["claimed_station_count"] == 0
        assert later["skipped_claimed_elsewhere_count"] == 3
        assert later["mseed_files"] == 0
        # Downloading nothing because a neighbour owns it is a normal outcome.
        assert later["status"] == "ok"


def test_membership_recorded_for_boxes_that_downloaded_nothing(
    tmp_path, monkeypatch, make_track
):
    """filtered_stations.json is geometry, not bookkeeping: a box that owns no
    station still lists the stations near it, because plotting depends on it."""
    _patch_clients(monkeypatch, SHARED_STATIONS)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    download_boxes(
        _overlapping_requests(2), track, output_base=tmp_path, event_name="ev",
        providers=("TEST",), corridor_km=100.0, verbose=False, max_workers=1,
    )

    second = tmp_path / "ev" / "boxes" / "box_001"
    assert not list((second / "waveforms").glob("*.mseed"))

    listed = json.loads((second / "logs" / "filtered_stations.json").read_text())
    assert {s["station"] for s in listed} == {"AAA", "BBB", "CCC"}


def test_claim_released_when_download_fails_and_reclaimed_by_later_box(
    tmp_path, monkeypatch, make_track
):
    """A claim is a promise to download. If the download fails outright, the
    promise must be handed back, or the station silently vanishes from the run."""
    calls = {"n": 0}

    class FailFirstBoxMDL(FakeMassDownloader):
        def download(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("first box download blew up")
            return super().download(*args, **kwargs)

    _patch_clients(monkeypatch, SHARED_STATIONS, mdl=FailFirstBoxMDL)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    manifest = download_boxes(
        _overlapping_requests(2), track, output_base=tmp_path, event_name="ev",
        providers=("TEST",), corridor_km=100.0, verbose=False, max_workers=1,
    )

    first, second = manifest["results"]

    # First box claimed all three, wrote none, and recorded the shortfall.
    assert first["claimed_station_count"] == 3
    assert first["mseed_files"] == 0
    assert sorted(first["claimed_not_downloaded"]) == ["XX.AAA", "XX.BBB", "XX.CCC"]
    assert "download_error" in first

    # Released, so the second box picks them up rather than skipping them.
    assert second["claimed_station_count"] == 3
    assert second["mseed_files"] == 3


def test_partial_write_keeps_claims_for_stations_already_on_disk(
    tmp_path, monkeypatch, make_track
):
    """Releasing everything on failure would let a neighbour re-fetch the files
    that did land -- the exact duplicate the claim exists to prevent."""
    class PartialThenRaiseMDL(FakeMassDownloader):
        raised = False

        def download(self, domain, restrictions, mseed_storage=None,
                     stationxml_storage=None, threads_per_client=3):
            if not PartialThenRaiseMDL.raised:
                PartialThenRaiseMDL.raised = True
                # Write exactly one station, then fail.
                path = mseed_storage("XX", "AAA", "", "HHZ",
                                     restrictions.starttime, restrictions.endtime)
                if path:
                    from conftest import _write_min_mseed
                    _write_min_mseed(path, "XX", "AAA", "HHZ")
                raise RuntimeError("died after one write")
            return super().download(domain, restrictions, mseed_storage,
                                    stationxml_storage, threads_per_client)

    _patch_clients(monkeypatch, SHARED_STATIONS, mdl=PartialThenRaiseMDL)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    manifest = download_boxes(
        _overlapping_requests(2), track, output_base=tmp_path, event_name="ev",
        providers=("TEST",), corridor_km=100.0, verbose=False, max_workers=1,
    )

    first, second = manifest["results"]

    # AAA landed, so its claim is kept; only BBB and CCC go back.
    assert first["claimed_not_downloaded"] == ["XX.BBB", "XX.CCC"]
    assert second["claimed_station_count"] == 2

    # AAA is on disk exactly once across the whole run.
    downloaded = _downloaded_station_set(tmp_path / "ev" / "boxes")
    assert sum(1 for _, sta in downloaded if sta == "AAA") == 1


def test_one_box_failing_does_not_abort_the_run(tmp_path, monkeypatch, make_track):
    class RaiseOnSecondBox(FakeMassDownloader):
        def download(self, domain, restrictions, *args, **kwargs):
            if "BBB" in (restrictions.station or ""):
                raise RuntimeError("box blew up")
            return super().download(domain, restrictions, *args, **kwargs)

    _patch_clients(monkeypatch, SHARED_STATIONS, mdl=RaiseOnSecondBox)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    manifest = download_boxes(
        _overlapping_requests(3), track, output_base=tmp_path, event_name="ev",
        providers=("TEST",), corridor_km=100.0, verbose=False, max_workers=1,
    )

    assert len(manifest["results"]) == 3
    assert all("box_id" in r for r in manifest["results"])


@pytest.mark.parametrize("max_workers", [1, 2, 4])
def test_downloaded_station_set_is_identical_at_any_concurrency(
    tmp_path, monkeypatch, make_track, max_workers
):
    """The guarantee is the run-wide station set, not which box holds what."""
    _patch_clients(monkeypatch, SHARED_STATIONS)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    download_boxes(
        _overlapping_requests(4), track, output_base=tmp_path, event_name="ev",
        providers=("TEST",), corridor_km=100.0, verbose=False,
        max_workers=max_workers,
    )

    downloaded = _downloaded_station_set(tmp_path / "ev" / "boxes")
    assert {sta for _, sta in downloaded} == {"AAA", "BBB", "CCC"}
    # At most once, whichever box won the race.
    assert len(downloaded) == 3


def test_results_reported_in_request_order_regardless_of_completion(
    tmp_path, monkeypatch, make_track
):
    _patch_clients(monkeypatch, SHARED_STATIONS)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    requests = _overlapping_requests(5)
    manifest = download_boxes(
        requests, track, output_base=tmp_path, event_name="ev",
        providers=("TEST",), corridor_km=100.0, verbose=False, max_workers=4,
    )

    assert [r["box_id"] for r in manifest["results"]] == [
        r["box_id"] for r in requests
    ]


def test_manifest_records_concurrency_settings(tmp_path, monkeypatch, make_track):
    _patch_clients(monkeypatch, SHARED_STATIONS)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    manifest = download_boxes(
        [_request()], track, output_base=tmp_path, event_name="ev",
        providers=("TEST",), corridor_km=100.0, verbose=False,
        max_workers=2, threads_per_client=5,
    )

    assert manifest["max_workers"] == 2
    assert manifest["threads_per_client"] == 5


# --------------------------------------------------------------------------- #
# claim primitives under contention
# --------------------------------------------------------------------------- #

def test_concurrent_claims_never_hand_the_same_station_to_two_callers():
    """Many threads racing on one claim set: every station goes to exactly one."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from groundtrack.download import _claim_stations

    candidates = [
        {"network": "XX", "station": f"S{i:03d}"} for i in range(200)
    ]
    claimed: set = set()
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()  # maximise the overlap between claim attempts
        return _claim_stations(candidates, claimed, lock)

    with ThreadPoolExecutor(max_workers=8) as ex:
        batches = [f.result() for f in [ex.submit(worker) for _ in range(8)]]

    handed_out = [s["station"] for batch in batches for s in batch]

    # Every station claimed exactly once across all threads, none lost.
    assert len(handed_out) == len(set(handed_out)) == 200
    assert len(claimed) == 200


def test_release_only_returns_stations_without_files(tmp_path):
    import threading

    from groundtrack.download import _claim_stations, _release_unwritten_claims

    stations = [
        {"network": "XX", "station": "WROTE"},
        {"network": "XX", "station": "MISSING"},
    ]
    claimed: set = set()
    lock = threading.Lock()

    mine = _claim_stations(stations, claimed, lock)
    assert len(claimed) == 2

    (tmp_path / "XX.WROTE..HHZ.mseed").write_text("")

    released = _release_unwritten_claims(mine, tmp_path, claimed, lock)

    assert [s["station"] for s in released] == ["MISSING"]
    assert claimed == {("XX", "WROTE")}


@pytest.mark.parametrize("max_workers", [1, 3])
def test_unexpected_box_error_is_isolated_at_any_concurrency(
    tmp_path, monkeypatch, make_track, max_workers
):
    """An error escaping the per-box worker must be contained identically
    whether boxes run sequentially or concurrently."""
    import groundtrack.download as dl

    real = dl._process_one_box

    def boom_on_second(req, **kwargs):
        if req["box_id"] == "box_001":
            raise RuntimeError("unexpected worker failure")
        return real(req, **kwargs)

    _patch_clients(monkeypatch, SHARED_STATIONS)
    monkeypatch.setattr(dl, "_process_one_box", boom_on_second)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    manifest = download_boxes(
        _overlapping_requests(3), track, output_base=tmp_path, event_name="ev",
        providers=("TEST",), corridor_km=100.0, verbose=False,
        max_workers=max_workers,
    )

    by_id = {r["box_id"]: r for r in manifest["results"]}
    assert by_id["box_001"]["status"] == "failed"
    assert "unexpected worker failure" in by_id["box_001"]["error"]
    assert manifest["failed"] == 1

    # The other boxes still ran and still produced data.
    assert by_id["box_000"]["status"] == "ok"
    assert by_id["box_002"]["status"] == "ok"
    assert manifest["ok"] == 2


# --------------------------------------------------------------------------- #
# resumed runs: skipped boxes still own what is already on their disk
# --------------------------------------------------------------------------- #

def test_resume_does_not_redownload_stations_owned_by_a_skipped_box(
    tmp_path, monkeypatch, make_track
):
    """A skipped box never runs discovery, so it must register the stations it
    already holds -- otherwise a neighbour sees them as unclaimed and fetches
    them again, reintroducing duplicates on every resumed run."""
    _patch_clients(monkeypatch, SHARED_STATIONS)
    track = make_track(lat=0.0, lon_step=0.5, n=40)
    requests = _overlapping_requests(2)

    common = dict(
        output_base=tmp_path, event_name="ev", providers=("TEST",),
        corridor_km=100.0, verbose=False, max_workers=1,
    )

    download_boxes(requests, track, **common)
    # Second pass over the same output: box_000 now has data and is skipped.
    manifest = download_boxes(requests, track, **common)

    assert manifest["results"][0]["status"] == "skipped_existing"

    downloaded = _downloaded_station_set(tmp_path / "ev" / "boxes")
    counts = {}
    for _, sta in downloaded:
        counts[sta] = counts.get(sta, 0) + 1

    assert counts == {"AAA": 1, "BBB": 1, "CCC": 1}


def test_skipped_box_reports_the_claims_it_retained(tmp_path, monkeypatch, make_track):
    _patch_clients(monkeypatch, SHARED_STATIONS)
    track = make_track(lat=0.0, lon_step=0.5, n=40)
    requests = _overlapping_requests(2)
    common = dict(
        output_base=tmp_path, event_name="ev", providers=("TEST",),
        corridor_km=100.0, verbose=False, max_workers=1,
    )

    download_boxes(requests, track, **common)
    manifest = download_boxes(requests, track, **common)

    skipped = manifest["results"][0]
    assert skipped["status"] == "skipped_existing"
    assert skipped["claimed_station_count"] == 3
    # The neighbour finds nothing left to take.
    assert manifest["results"][1]["claimed_station_count"] == 0
    assert manifest["unique_stations_claimed"] == 3


def test_existing_station_keys_reads_identities_from_filenames(tmp_path):
    from groundtrack.download import _existing_station_keys

    (tmp_path / "XX.AAA..HHZ.mseed").write_text("")
    (tmp_path / "YY.BBB.00.BHZ.mseed").write_text("")
    (tmp_path / "notes.txt").write_text("")          # ignored, not mseed
    (tmp_path / "malformed.mseed").write_text("")    # ignored, unparseable

    assert _existing_station_keys(tmp_path) == {("XX", "AAA"), ("YY", "BBB")}


def test_max_workers_is_capped_with_a_warning(tmp_path, monkeypatch, make_track):
    """An accidental huge max_workers must not be honoured -- each worker opens
    threads_per_client connections of its own against shared infrastructure."""
    from groundtrack.download import MAX_WORKERS_CAP

    _patch_clients(monkeypatch, SHARED_STATIONS)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    with pytest.warns(UserWarning, match="exceeds the safety cap"):
        manifest = download_boxes(
            _overlapping_requests(2), track, output_base=tmp_path, event_name="ev",
            providers=("TEST",), corridor_km=100.0, verbose=False,
            max_workers=500,
        )

    assert manifest["max_workers"] == MAX_WORKERS_CAP
    # Still correct, just bounded.
    downloaded = _downloaded_station_set(tmp_path / "ev" / "boxes")
    assert len(downloaded) == 3


def test_max_workers_at_the_cap_does_not_warn(tmp_path, monkeypatch, make_track):
    import warnings as _w
    from groundtrack.download import MAX_WORKERS_CAP

    _patch_clients(monkeypatch, SHARED_STATIONS)
    track = make_track(lat=0.0, lon_step=0.5, n=40)

    with _w.catch_warnings():
        _w.simplefilter("error")  # any warning becomes a failure
        manifest = download_boxes(
            _overlapping_requests(2), track, output_base=tmp_path, event_name="ev",
            providers=("TEST",), corridor_km=100.0, verbose=False,
            max_workers=MAX_WORKERS_CAP,
        )
    assert manifest["max_workers"] == MAX_WORKERS_CAP
