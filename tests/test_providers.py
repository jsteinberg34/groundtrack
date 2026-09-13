"""
Region-based provider resolution.

All offline: resolution never touches the network, so these run against a small
fake region map rather than the shipped one. The handful of tests that do assert
against the real map are the ones guarding it against silent rot.
"""

import pytest

from obspy.clients.fdsn.header import URL_MAPPINGS

from groundtrack import providers as P


# --------------------------------------------------------------------------- #
# Fake region map
# --------------------------------------------------------------------------- #
#
# Cell ids are derived rather than hardcoded, so the fixture stays correct if
# CELL_DEG ever changes. Station counts are what drive priority ordering.

def _cells(points, count):
    return tuple((P.cell_id(lat, lon), count) for lat, lon in points)


FAKE_REGIONS = {
    # Dense local archive over "region A" (around 34N, 118W).
    "LOCAL": _cells([(34.0, -118.0)], 500),
    # Same area, fewer stations: must rank below LOCAL.
    "SPARSE": _cells([(34.0, -118.0)], 5),
    # Somewhere else entirely (around 42N, 13E).
    "ELSEWHERE": _cells([(42.0, 13.0)], 300),
    # Straddles the antimeridian (around -41S, +/-179).
    "DATELINE": _cells([(-41.0, 178.0), (-41.0, -178.0)], 50),
    # In the map but has no dataselect service; see METADATA_ONLY below.
    "NOWAVE": _cells([(34.0, -118.0)], 40),
}

SOCAL = {"lat_min": 33.0, "lat_max": 35.5, "lon_min": -119.0, "lon_max": -116.5}
ITALY = {"lat_min": 41.0, "lat_max": 43.5, "lon_min": 12.0, "lon_max": 14.5}
EMPTY_OCEAN = {"lat_min": 22.0, "lat_max": 24.0, "lon_min": -40.0, "lon_max": -38.0}
# Real geometry from track_to_box_windows: lon_min > lon_max means it wraps.
ANTIMERIDIAN = {"lat_min": -43.0, "lat_max": -39.7, "lon_min": 177.7, "lon_max": -179.3}


@pytest.fixture
def fake_map(monkeypatch):
    """Swap in the fake region map, index and inventory for one test."""
    monkeypatch.setattr(P, "REGIONS", FAKE_REGIONS)
    monkeypatch.setattr(P, "_INDEX", P._build_index(FAKE_REGIONS))
    monkeypatch.setattr(P, "INVENTORY", frozenset(FAKE_REGIONS))
    monkeypatch.setattr(
        P, "PROVIDER_SERVICES",
        {
            "LOCAL": frozenset({"station", "dataselect"}),
            "SPARSE": frozenset({"station", "dataselect"}),
            "ELSEWHERE": frozenset({"station", "dataselect"}),
            "DATELINE": frozenset({"station", "dataselect"}),
            "NOWAVE": frozenset({"station"}),
            "EARTHSCOPE": frozenset({"station", "dataselect"}),
        },
    )


# --------------------------------------------------------------------------- #
# Region selection
# --------------------------------------------------------------------------- #

def test_provider_over_its_own_region_is_selected(fake_map):
    assert "LOCAL" in P.resolve_providers(SOCAL)


def test_provider_outside_its_region_is_not_selected(fake_map):
    """The whole point: a box in California must not query an Italian archive."""
    assert "ELSEWHERE" not in P.resolve_providers(SOCAL)
    assert "LOCAL" not in P.resolve_providers(ITALY)


def test_box_crossing_the_antimeridian_still_resolves(fake_map):
    """
    A box that wraps has lon_min > lon_max, so a naive floor range is empty and
    the box would silently resolve to nothing at all rather than raising. This
    is real geometry out of track_to_box_windows, not a constructed case.
    """
    assert ANTIMERIDIAN["lon_min"] > ANTIMERIDIAN["lon_max"]
    assert "DATELINE" in P.resolve_providers(ANTIMERIDIAN)


def test_antimeridian_box_matches_an_equivalent_non_wrapping_box(fake_map):
    """Wrapping must not change *which* providers are found, only how they are found."""
    west = P.resolve_providers(
        {"lat_min": -43.0, "lat_max": -39.7, "lon_min": 177.7, "lon_max": 179.9}
    )
    assert set(west) <= set(P.resolve_providers(ANTIMERIDIAN))


def test_box_with_no_regional_provider_still_gets_one(fake_map):
    """
    Mid-ocean and desert boxes match no regional archive. They must still be
    processed and still query something, never resolve to an empty list.
    """
    resolved = P.resolve_providers(EMPTY_OCEAN)
    assert resolved == list(P.ALWAYS_QUERIED)
    assert len(resolved) >= 1


# --------------------------------------------------------------------------- #
# Closed inventory
# --------------------------------------------------------------------------- #

def test_provider_outside_the_inventory_is_not_auto_selected(fake_map):
    assert "NOT_IN_MAP" not in P.resolve_providers(SOCAL)


def test_provider_outside_the_inventory_is_queried_when_named(fake_map):
    assert "NOT_IN_MAP" in P.resolve_providers(SOCAL, providers=["NOT_IN_MAP"])
    assert "NOT_IN_MAP" in P.resolve_providers(SOCAL, extra_providers=["NOT_IN_MAP"])


def test_amateur_and_non_station_providers_are_absent_from_auto():
    """Checked against the real inventory, not the fake one."""
    for name in P.EXPLICIT_ONLY | P.EXCLUDED_FROM_AUTO:
        assert name not in P.INVENTORY
        assert name not in P.REGIONS


def test_amateur_provider_is_queried_when_named_explicitly(fake_map):
    assert "RASPISHAKE" in P.resolve_providers(SOCAL, extra_providers=["RASPISHAKE"])
    assert P.resolve_providers(SOCAL, providers=["RASPISHAKE"]) == ["RASPISHAKE"]


# --------------------------------------------------------------------------- #
# Explicit and additional providers
# --------------------------------------------------------------------------- #

def test_explicit_list_replaces_auto_selection(fake_map):
    assert P.resolve_providers(SOCAL, providers=["ELSEWHERE"]) == ["ELSEWHERE"]


def test_explicit_list_is_not_region_filtered(fake_map):
    """ELSEWHERE holds nothing near SOCAL, but the caller asked for it."""
    assert P.resolve_providers(EMPTY_OCEAN, providers=["ELSEWHERE"]) == ["ELSEWHERE"]


def test_extra_providers_are_queried_even_where_they_hold_nothing(fake_map):
    resolved = P.resolve_providers(EMPTY_OCEAN, extra_providers=["ELSEWHERE"])
    assert "ELSEWHERE" in resolved


def test_explicit_and_extra_providers_are_unioned(fake_map):
    resolved = P.resolve_providers(
        SOCAL, providers=["ELSEWHERE"], extra_providers=["RASPISHAKE"]
    )
    assert set(resolved) == {"ELSEWHERE", "RASPISHAKE"}
    assert "LOCAL" not in resolved


def test_none_means_auto_not_nothing(fake_map):
    """
    None used to yield an empty provider list, so a run silently downloaded
    nothing at all. It now behaves as the default.
    """
    assert P.resolve_providers(SOCAL, providers=None) == P.resolve_providers(SOCAL)
    assert P.resolve_providers(SOCAL, providers=None)


# --------------------------------------------------------------------------- #
# Ordering
# --------------------------------------------------------------------------- #

def test_provider_with_more_local_stations_is_ordered_first(fake_map):
    """
    Alphabetical order would put SPARSE before LOCAL despite it holding 5
    stations against 500. Order is priority for MassDownloader, so the genuinely
    local archive has to win.
    """
    resolved = P.resolve_providers(SOCAL)
    assert resolved.index("LOCAL") < resolved.index("SPARSE")


def test_general_archive_is_consulted_after_regional_ones(fake_map):
    resolved = P.resolve_providers(SOCAL)
    assert resolved[-1] == "EARTHSCOPE"
    assert resolved.index("LOCAL") < resolved.index("EARTHSCOPE")


def test_extra_providers_rank_last(fake_map):
    """
    Lowest priority is right for the canonical use: if a station is held by both
    a professional archive and an amateur network, the professional copy wins.
    """
    resolved = P.resolve_providers(SOCAL, extra_providers=["RASPISHAKE"])
    assert resolved[-1] == "RASPISHAKE"
    assert resolved.index("EARTHSCOPE") < resolved.index("RASPISHAKE")


def test_explicit_order_is_preserved(fake_map):
    """The escape hatch for anyone needing exact precedence."""
    order = ["SPARSE", "EARTHSCOPE", "LOCAL"]
    assert P.resolve_providers(SOCAL, providers=order) == order


def test_aliases_do_not_produce_duplicate_queries(fake_map):
    """
    GEOFON and GFZ are one archive. Querying both would spend two serial
    availability queries on the same data.
    """
    resolved = P.resolve_providers(SOCAL, providers=["GEOFON", "GFZ", "IRIS", "EARTHSCOPE"])
    assert resolved == ["GEOFON", "IRIS"]


# --------------------------------------------------------------------------- #
# Capability
# --------------------------------------------------------------------------- #

def test_metadata_only_provider_is_not_treated_as_a_waveform_source(fake_map):
    assert P.serves_waveforms("LOCAL") is True
    assert P.serves_waveforms("NOWAVE") is False


def test_unknown_provider_is_assumed_capable(fake_map):
    """An explicitly named provider we hold no record for behaves as it always did."""
    assert P.serves_waveforms("SOMETHING_NEW") is True


def test_known_metadata_only_providers_are_recorded_as_such():
    """Measured against the real registry: both serve station but 404 dataselect."""
    assert P.serves_waveforms("KAGSR") is False
    assert P.serves_waveforms("USP") is False
    assert P.serves_waveforms("EARTHSCOPE") is True


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def test_skipped_by_region_names_what_was_left_out(fake_map):
    queried = P.resolve_providers(SOCAL)
    skipped = P.skipped_by_region(SOCAL, queried)
    assert "ELSEWHERE" in skipped
    assert "LOCAL" not in skipped


# --------------------------------------------------------------------------- #
# Guards on the shipped map itself
# --------------------------------------------------------------------------- #

def test_shipped_map_has_no_entry_for_unfiltered_providers():
    """
    EARTHSCOPE is always queried and RASPISHAKE only arrives via extra_providers,
    so neither is ever tested against a box's cells. Region data for them would
    be dead weight that could only cause harm if some later edit consulted it.
    """
    for name in set(P.ALWAYS_QUERIED) | P.EXPLICIT_ONLY:
        assert name not in P.REGIONS


def test_every_inventory_provider_has_region_data():
    """
    A provider in INVENTORY but absent from REGIONS would match no box and could
    never be auto-selected, while still looking supported. That exact bug reached
    the proposal for KAGSR, so it is guarded here as well as in the generator.
    """
    missing = sorted(name for name in P.INVENTORY if not P.REGIONS.get(name))
    assert missing == []


def test_every_obspy_provider_is_classified():
    """
    Fails when ObsPy adds a provider we have not decided about, so the map going
    stale surfaces in CI rather than silently narrowing what gets queried.
    """
    classified = (
        set(P.INVENTORY)
        | set(P.ALWAYS_QUERIED)
        | set(P.EXPLICIT_ONLY)
        | set(P.EXCLUDED_FROM_AUTO)
        | set(P.ALIASES)
    )
    unclassified = sorted(set(URL_MAPPINGS) - classified)
    assert unclassified == [], (
        f"ObsPy knows providers this library has not classified: {unclassified}. "
        f"Add each to INVENTORY, EXCLUDED_FROM_AUTO or ALIASES and regenerate "
        f"the region map."
    )


def test_aliases_point_at_known_providers():
    """
    Every alias must resolve to a provider we actually support. The alias itself
    need not exist in the installed ObsPy: the table classifies across versions,
    so it may name one added in a later release (EARTHSCOPE+USGS) or dropped in
    an earlier one. An unused entry is harmless; one pointing nowhere is not.
    """
    for alias, target in P.ALIASES.items():
        assert target in P.INVENTORY or target in set(P.ALWAYS_QUERIED), (
            f"alias {alias} points at {target}, which is not a supported provider"
        )


def test_aliases_that_exist_here_share_their_target_url():
    """
    Where the installed ObsPy knows both names, they must really be one archive.
    EPOSFR/RESIF is the exception: mid-rename, so two URLs, one archive.
    """
    for alias, target in P.ALIASES.items():
        if alias in URL_MAPPINGS and target in URL_MAPPINGS and alias != "RESIF":
            assert URL_MAPPINGS[alias] == URL_MAPPINGS[target], (
                f"{alias} and {target} are treated as one archive but have "
                f"different URLs; querying one would not cover the other"
            )


def test_every_inventory_provider_is_known_to_obspy():
    """
    The reverse of the drift test: a provider we list but ObsPy has dropped
    could never have a client built for it, so auto selection would offer
    something unreachable.
    """
    missing = sorted(name for name in P.INVENTORY if name not in URL_MAPPINGS)
    assert missing == [], (
        f"INVENTORY names providers ObsPy no longer knows: {missing}. "
        f"Remove them and regenerate the region map."
    )


def test_resolution_needs_no_network(monkeypatch):
    """
    Provider choice must be reproducible offline and deterministic for a release.
    Any socket use here would mean it is neither.
    """
    import socket

    def no_network(*args, **kwargs):
        raise AssertionError("resolve_providers must not touch the network")

    monkeypatch.setattr(socket, "socket", no_network)
    assert P.resolve_providers(SOCAL)


def test_client_objects_are_rejected_with_a_clear_error(fake_map):
    """
    ObsPy's MassDownloader accepts Client instances, so reaching for one here is
    reasonable. This library keys its reused clients by name, and an object
    would be stringified to its repr, producing Client("<... at 0x...>") which
    raises and is swallowed by the init loop -- dropping the provider silently.
    """
    class SomeClient:
        def get_stations(self, **kwargs):
            return None

    with pytest.raises(TypeError, match="provider names, not client objects"):
        P.resolve_providers(SOCAL, providers=[SomeClient()])


def test_skipped_by_region_is_empty_for_explicit_selection(fake_map):
    """An explicit list is the caller's choice, not a geographic exclusion."""
    assert P.skipped_by_region(SOCAL, ["LOCAL"], auto=False) == []
    assert P.skipped_by_region(SOCAL, ["LOCAL"], auto=True) != []


def test_resolution_accepts_a_geobox_as_well_as_a_request_dict(fake_map):
    """
    The two-step workflow holds GeoBox objects from the tiler, while
    download_boxes passes request dicts. Both must resolve identically.
    """
    from groundtrack.types import GeoBox

    box = GeoBox(lat_min=33.0, lat_max=35.5, lon_min=-119.0, lon_max=-116.5, box_index=0)
    assert P.resolve_providers(box) == P.resolve_providers(SOCAL)


def test_documented_provider_table_matches_the_registry():
    """
    The supported-provider table in docs/api/providers.rst is hand-maintained.
    A reader trusts it to say what auto selection will actually query, so it
    must not drift from INVENTORY when the map is regenerated.
    """
    import pathlib
    import re

    doc = pathlib.Path(__file__).resolve().parent.parent / "docs" / "api" / "providers.rst"
    if not doc.exists():                      # docs are not installed with the package
        pytest.skip("docs not present")

    section = doc.read_text().split("Supported providers")[1].split("Not selected")[0]
    documented = set(re.findall(r"^``([A-Z0-9-]+)``", section, re.M))
    expected = set(P.INVENTORY) | set(P.ALWAYS_QUERIED)

    assert documented == expected, (
        f"docs/api/providers.rst is out of step with the registry. "
        f"Missing from docs: {sorted(expected - documented)}. "
        f"Listed but not supported: {sorted(documented - expected)}."
    )
