"""
Region-aware FDSN provider selection.

Why this exists:
----------------
Provider lists used to be hardcoded and US-centric, so a re-entry over Italy
queried three US archives and found almost nothing. Querying every provider
ObsPy knows is not an option either: ObsPy runs availability queries
*sequentially* per client, so a box's wall time is the sum of its providers'
response times, and several endpoints are slow or hang.

This module answers "which providers are worth asking for this box?" offline,
from a built-in map of where each provider actually holds stations. No network
call, no geometry dependency, and the answer is deterministic for a given
release so a past run's selection can be reconstructed.

The map itself lives in the generated module ``_provider_regions``; see
``tools/build_provider_regions.py`` for how it is produced.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

from ._provider_regions import (
    CELL_DEG,
    PROVIDER_SERVICES,
    REGIONS,
    REGIONS_GENERATED_UTC,
)

__all__ = [
    "CELL_DEG",
    "REGIONS",
    "REGIONS_GENERATED_UTC",
    "PROVIDER_SERVICES",
    "INVENTORY",
    "ALWAYS_QUERIED",
    "EXPLICIT_ONLY",
    "EXCLUDED_FROM_AUTO",
    "EXCLUDED_NETWORKS",
    "AUTO",
    "cell_id",
    "box_cells",
    "serves_waveforms",
    "resolve_providers",
    "skipped_by_region",
]


# ---------------------------------------------------------------------------
# Curated inventory
# ---------------------------------------------------------------------------

# Sentinel for automatic, region-based selection.
AUTO = "auto"

# The providers automatic selection may choose from. Every one of these carries
# region data in REGIONS; a test asserts that, because a provider listed here
# but absent from the map would match no box and could never be auto-selected.
INVENTORY = frozenset({
    "AUSPASS",      # Australia
    "BGR",          # Germany
    "BGS",          # United Kingdom
    "EPOSFR",       # France, mainland
    "ETH",          # Switzerland
    "GEOFON",       # Germany, global deployments
    "GEONET",       # New Zealand
    "ICGC",         # Catalonia
    "IESDMC",       # Taiwan
    "IGN",          # Spain
    "INGV",         # Italy
    "IPGP",         # France, overseas and volcano networks
    "KAGSR",        # Kamchatka, Russia
    "KNMI",         # Netherlands
    "KOERI",        # Turkey
    "LMU",          # Germany
    "NCEDC",        # Northern California
    "NIEP",         # Romania
    "NOA",          # Greece
    "NRCAN",        # Canada
    "ORFEUS",       # European aggregator (ODC)
    "SCEDC",        # Southern California
    "TEXNET",       # Texas
    "UIB-NORSAR",   # Norway
    "USP",          # Brazil
})

# Queried for every box regardless of geography. EARTHSCOPE archives networks
# worldwide, so region-filtering it would be meaningless, and it guarantees a
# box always resolves to at least one provider.
ALWAYS_QUERIED = ("EARTHSCOPE",)

# Reachable only when the caller names them. RASPISHAKE is a citizen-science
# network: high volume, variable quality, and its channels (EHZ/SHZ) do not even
# match the default channel_priorities. Opt in via ``extra_providers``.
EXPLICIT_ONLY = frozenset({"RASPISHAKE"})

# Never chosen automatically, for reasons that are not about geography:
#   IRISPH5            nodal experiment data, can match enormous datasets
#   USGS, EMSC, ISC    event catalogues, no station metadata at all
#   EIDA               a router, holds no data of its own and routes to members
#                      already in INVENTORY
EXCLUDED_FROM_AUTO = frozenset({"IRISPH5", "USGS", "EMSC", "ISC", "EIDA"})

# Alternative names for an archive already in the registry. Kept so that every
# name ObsPy knows is accounted for (a test asserts that, to catch ObsPy adding
# a provider we have not classified) and so two names for one archive do not
# cost two serial availability queries.
#
# GFZ/GEOFON, ODC/ORFEUS and IRIS/IRISDMC/EARTHSCOPE share a URL outright.
# RESIF and EPOSFR do not, but are the same archive mid-rename, and the
# fedcatalog still reports it under the old name.
#
# IRISPH5 is deliberately *not* here: it shares EARTHSCOPE's URL but is a
# distinct nodal dataset that can match enormous requests, so it stays excluded
# in its own right rather than collapsing into EARTHSCOPE.
ALIASES = {
    "IRIS": "EARTHSCOPE",
    "IRISDMC": "EARTHSCOPE",
    "GFZ": "GEOFON",
    "ODC": "ORFEUS",
    "RESIF": "EPOSFR",
}

# Reserved network codes that must never be downloaded, whatever the provider.
# SY is the FDSN-reserved code for synthetic seismograms and EARTHSCOPE serves
# thousands of them with real-looking coordinates; XX is a test/placeholder
# code. Note this is deliberately narrow: X*, Y*, Z* and 1-9 are *temporary*
# deployment codes carrying real data and must not be swept up here.
EXCLUDED_NETWORKS = frozenset({"SY", "XX"})


# ---------------------------------------------------------------------------
# Grid arithmetic
# ---------------------------------------------------------------------------

_N_LON = int(round(360.0 / CELL_DEG))     # columns of the global grid
_LAT_OFFSET = int(round(90.0 / CELL_DEG))  # shift so row indices start at 0
_LON_OFFSET = int(round(180.0 / CELL_DEG))


def cell_id(lat: float, lon: float) -> int:
    """
    Map a latitude/longitude to the id of the grid cell containing it.

    The globe is divided into fixed CELL_DEG-sized tiles and each is given a
    single integer id, so provider footprints can be stored as flat lists of
    ints and looked up with a dict rather than any geometric test.
    """
    return _cell_id_from_indices(
        int(math.floor(lat / CELL_DEG)),
        int(math.floor(lon / CELL_DEG)),
    )


def _cell_id_from_indices(row: int, col: int) -> int:
    return (row + _LAT_OFFSET) * _N_LON + (col + _LON_OFFSET)


def _bounds(box: Any) -> tuple[float, float, float, float]:
    """
    Pull (lat_min, lat_max, lon_min, lon_max) from a GeoBox, a download request
    dict, or anything else exposing those four names.
    """
    if isinstance(box, Mapping):
        return (
            float(box["lat_min"]), float(box["lat_max"]),
            float(box["lon_min"]), float(box["lon_max"]),
        )
    return (
        float(box.lat_min), float(box.lat_max),
        float(box.lon_min), float(box.lon_max),
    )


def box_cells(box: Any) -> set[int]:
    """
    Every grid cell a box overlaps.

    Antimeridian:
    -------------
    ``lon_bounds_dateline_safe`` returns lon_min > lon_max for a box that
    crosses +/-180. A naive ``range(floor(lon_min), floor(lon_max))`` is empty
    in that case, so the box would silently resolve to no providers at all
    rather than raising. Longitude is therefore walked as two spans whenever
    the box wraps, mirroring what ``filter_ocean_boxes`` already does.
    """
    lat_min, lat_max, lon_min, lon_max = _bounds(box)

    row_lo = int(math.floor(lat_min / CELL_DEG))
    row_hi = int(math.floor(lat_max / CELL_DEG))

    col_lo = int(math.floor(lon_min / CELL_DEG))
    col_hi = int(math.floor(lon_max / CELL_DEG))

    if lon_min <= lon_max:
        col_spans = [(col_lo, col_hi)]
    else:
        col_spans = [
            (col_lo, _N_LON - _LON_OFFSET - 1),   # up to just below +180
            (-_LON_OFFSET, col_hi),               # from -180 onward
        ]

    cells: set[int] = set()
    for row in range(row_lo, row_hi + 1):
        for span_lo, span_hi in col_spans:
            for col in range(span_lo, span_hi + 1):
                cells.add(_cell_id_from_indices(row, col))
    return cells


# ---------------------------------------------------------------------------
# Inverted index, built once at import
# ---------------------------------------------------------------------------
#
# REGIONS is stored provider-first because that form is readable and diffs
# cleanly when regenerated. Resolution wants the opposite direction, so it is
# inverted here exactly once. This is what keeps a lookup proportional to the
# number of cells a box covers (2.6 on average) rather than to the number of
# providers: resolving never iterates the provider list at all.

def _build_index(regions: Mapping[str, Sequence[tuple[int, int]]]) -> dict[int, dict[str, int]]:
    index: dict[int, dict[str, int]] = {}
    for provider, cells in regions.items():
        for cid, count in cells:
            index.setdefault(cid, {})[provider] = count
    return index


_INDEX = _build_index(REGIONS)


def serves_waveforms(provider: str) -> bool:
    """
    True if this provider offers a dataselect service.

    Station metadata and waveform service are advertised independently, and two
    inventory providers (KAGSR, USP) offer the former but not the latter. They
    are still worth querying, because "instruments exist near this corridor" is
    a real result, but nothing may depend on them to supply data.

    Providers we hold no capability record for are assumed capable, so an
    explicitly named provider outside the inventory behaves as it always has.
    """
    services = PROVIDER_SERVICES.get(provider)
    if services is None:
        return True
    return "dataselect" in services


def _require_name(provider: Any) -> str:
    """
    Providers must be named, not passed as client objects.

    ObsPy's MassDownloader accepts an initialized ``Client``, so reaching for
    one here is reasonable, but this library builds and reuses its own clients
    keyed by provider name. An object would be stringified to its repr, and the
    resulting ``Client("<... object at 0x...>")`` would raise and be swallowed by
    the initialization loop, dropping that provider from the run with nothing to
    show for it. Better to say so.
    """
    if isinstance(provider, str):
        return provider
    if hasattr(provider, "get_stations"):
        raise TypeError(
            "providers must be provider names, not client objects. "
            f"Received {type(provider).__name__}. Pass the short name (for "
            f"example 'SCEDC') and the client will be built and reused for you."
        )
    return str(provider)


def _auto_for_box(box: Any) -> list[str]:
    """
    Region-selected providers for one box, best first.

    Ordering matters: MassDownloader treats the provider list as a priority
    list and takes the first one holding a given station. Sorting by how many
    stations a provider has *inside this box* puts the genuinely local archive
    first, which alphabetical order does not: for a Southern California box it
    would rank LMU (3 stations there) above SCEDC (3228).
    """
    scored: dict[str, int] = {}
    for cid in box_cells(box):
        for provider, count in _INDEX.get(cid, {}).items():
            scored[provider] = scored.get(provider, 0) + count

    return [
        provider
        for _, provider in sorted(
            ((-n, p) for p, n in scored.items())
        )
    ]


def resolve_providers(
    box: Any,
    providers: Sequence[str] | str | None = AUTO,
    extra_providers: Iterable[str] = (),
) -> list[str]:
    """
    Decide which providers to query for one box, in priority order.

    ``providers``:
        - ``"auto"`` (or ``None``) selects by region from INVENTORY, then
          appends the always-queried archive.
        - an explicit sequence replaces automatic selection entirely and is
          used in the caller's own order, with no region filtering.

    ``extra_providers``:
        always queried, never region-filtered, and ranked last. The canonical
        use is layering Raspberry Shake onto automatic selection, where lowest
        priority is right: if a station is available from both a professional
        archive and an amateur one, the professional copy should win. Anyone
        needing different precedence should pass an explicit ``providers``
        list, which is honoured verbatim.

    ``providers=None`` means auto rather than "no providers". Previously it
    produced an empty list, so a run silently downloaded nothing.
    """
    if providers is None or providers == AUTO:
        resolved = _auto_for_box(box)
        resolved.extend(ALWAYS_QUERIED)
    else:
        resolved = [_require_name(p) for p in providers]

    # Extras are appended rather than merged so they land last.
    resolved.extend(str(p) for p in extra_providers)

    # Dedup keeps the earliest (highest priority) occurrence, and compares by
    # archive rather than by name: querying GEOFON and GFZ, or IRIS and
    # EARTHSCOPE, would spend two serial availability queries on one archive.
    # The caller's chosen spelling is preserved in the output.
    seen: set[str] = set()
    ordered: list[str] = []
    for provider in resolved:
        archive = ALIASES.get(provider, provider)
        if archive not in seen:
            seen.add(archive)
            ordered.append(provider)
    return ordered


def skipped_by_region(
    box: Any,
    queried: Iterable[str],
    auto: bool = True,
) -> list[str]:
    """
    Inventory providers that automatic selection excluded for this box.

    Recorded in the manifest so that a box returning no stations can be told
    apart from a box where a relevant provider was never asked. A quiet result
    should never be indistinguishable from an unasked question.

    Empty when selection was not automatic: an explicit provider list is the
    caller's own choice, not a geographic exclusion, and reporting the rest of
    the inventory under this name would describe it wrongly. What was asked is
    still recorded per box, alongside the selection mode.
    """
    if not auto:
        return []
    return sorted(INVENTORY - set(queried))
