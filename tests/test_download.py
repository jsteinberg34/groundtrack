"""
Unit tests for groundtrack.download.

The pure helpers are tested directly. download_boxes is driven with faked FDSN
Client and MassDownloader (monkeypatched at their module-level names) so the
real filtering, storage-callback, file-counting, and manifest logic run with no
network. All on tmp_path.
"""

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
