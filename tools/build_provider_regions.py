#!/usr/bin/env python
"""
Regenerate src/groundtrack/_provider_regions.py.

Run this occasionally, review the diff, and commit it. It is deliberately kept
out of the installed package: the library resolves providers entirely offline,
and this is the only part of the system that touches the network.

    python tools/build_provider_regions.py

Where the data comes from
-------------------------
One EarthScope fedcatalog request. The fedcatalog routes by *actual holdings*,
which is the question we need answered. A provider's own station service is not
equivalent: SCEDC republishes metadata for 23 networks including nationwide NP
and TA, but serves waveforms only for its own, which is why a naive sweep gave
it phantom coverage across Alaska and the Caribbean.

Inventory providers absent from the fedcatalog response are not federated and
fall back to their own station service, which overstates but errs toward
over-querying. That set is *computed*, never hardcoded: federation membership
is whatever the response actually contains, and a datacenter that is merely
unreachable during a run drops out the same way a non-member does.

Station footprints are built with no time filter, so decommissioned stations
still occupy cells. That is deliberate. Filtering to currently-operating
stations would drop over half of GEOFON's footprint and make the map wrong for
reprocessing older events.
"""

from __future__ import annotations

import math
import sys
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from obspy.clients.fdsn import Client  # noqa: E402
from obspy.clients.fdsn.header import URL_MAPPINGS  # noqa: E402

from groundtrack.providers import (  # noqa: E402
    ALWAYS_QUERIED,
    EXPLICIT_ONLY,
    INVENTORY,
)

CELL_DEG = 5.0
OUTPUT = REPO_ROOT / "src" / "groundtrack" / "_provider_regions.py"

FEDCATALOG = (
    "https://service.earthscope.org/irisws/fedcatalog/1/query"
    "?net=*&cha=?HZ&level=station&format=text"
)

# The fedcatalog uses its own datacenter names. Anything not listed here is
# assumed to match the ObsPy short name already.
FED_TO_OBSPY = {
    "IRISDMC": "EARTHSCOPE",
    "SED": "ETH",
    "USPSC": "USP",
    "BATS": "IESDMC",
    "RESIF": "EPOSFR",
}

# Providers whose capability we record even though they carry no region data.
CAPABILITY_ONLY = set(ALWAYS_QUERIED) | set(EXPLICIT_ONLY)


class GeneratorError(RuntimeError):
    """Raised when the map cannot be built correctly, rather than emitting a
    silently incomplete one."""


def _valid(lat: float, lon: float) -> bool:
    """
    Reject coordinates that cannot be real.

    Provider metadata is dirty: one Raspberry Shake station reports a latitude
    of 7,934,917, and (0, 0) is a common placeholder for "unknown". A single
    bad row would wreck a bounding box; here it would only add a junk cell, but
    there is no reason to keep it.
    """
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and not (lat == 0.0 and lon == 0.0)


def _cell(lat: float, lon: float) -> int:
    row = int(math.floor(lat / CELL_DEG))
    col = int(math.floor(lon / CELL_DEG))
    return (row + int(90 / CELL_DEG)) * int(360 / CELL_DEG) + (col + int(180 / CELL_DEG))


def _fetch(url: str, timeout: int = 300) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def fetch_fedcatalog() -> tuple[dict[str, dict[int, int]], int]:
    """
    Station counts per (provider, cell) from the federated routing table.

    Returns the counts and the number of coordinate rows rejected.
    """
    print(f"fetching fedcatalog ... ({FEDCATALOG})")
    body = _fetch(FEDCATALOG)
    print(f"  {len(body) / 1e6:.1f} MB")

    counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    current: str | None = None
    rejected = 0

    for line in body.splitlines():
        if line.startswith("#DATACENTER="):
            raw = line.split("=", 1)[1].split(",")[0].strip()
            current = FED_TO_OBSPY.get(raw, raw)
            continue
        if line.startswith("#") or "|" not in line or current is None:
            continue
        fields = line.split("|")
        try:
            lat, lon = float(fields[2]), float(fields[3])
        except (ValueError, IndexError):
            continue
        if not _valid(lat, lon):
            rejected += 1
            continue
        counts[current][_cell(lat, lon)] += 1

    return {k: dict(v) for k, v in counts.items()}, rejected


def fetch_station_service(provider: str) -> tuple[str, dict[int, int], int]:
    """
    Fall back to one provider's own station service.

    Used only for inventory providers the fedcatalog did not report. Their
    entries overstate coverage, which costs a wasted query rather than lost
    data.

    This goes through ObsPy rather than a raw text request because providers do
    not agree on formats: KAGSR ignores ``format=text`` and returns StationXML
    regardless. Parsing that as pipe-delimited yields zero rows, which is
    exactly how KAGSR was once misread as serving nothing at all. Letting ObsPy
    negotiate removes a whole class of silent miscounts.
    """
    try:
        inventory = Client(provider, timeout=180).get_stations(level="station")
    except Exception as exc:  # noqa: BLE001 - re-raised with context below
        raise GeneratorError(
            f"{provider}: fallback station query failed ({type(exc).__name__}: {exc}). "
            f"It is in INVENTORY but absent from the fedcatalog, so without this "
            f"it would have no region data and could never be auto-selected."
        ) from exc

    counts: dict[int, int] = defaultdict(int)
    rejected = 0
    for network in inventory:
        for station in network:
            lat, lon = float(station.latitude), float(station.longitude)
            if not _valid(lat, lon):
                rejected += 1
                continue
            counts[_cell(lat, lon)] += 1
    return provider, dict(counts), rejected


def probe_services(providers: list[str]) -> dict[str, frozenset[str]]:
    """
    Record what each provider advertises, from ObsPy's own service discovery.

    Never inferred from an empty or unparseable sweep response. That mistake
    was made once already: KAGSR was read as serving nothing because its
    response did not parse into rows, and it was nearly dropped from the
    inventory. It in fact serves 347 stations.
    """
    print(f"probing services for {len(providers)} providers ...")

    def one(name: str) -> tuple[str, frozenset[str] | None]:
        try:
            return name, frozenset(Client(name, timeout=60).services)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            print(f"  {name}: FAILED to initialise ({type(exc).__name__})")
            return name, None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = dict(pool.map(one, providers))

    failed = sorted(n for n, s in results.items() if s is None)
    if failed:
        raise GeneratorError(
            f"could not determine services for {failed}. Capability must be read "
            f"from the provider, never guessed, so the map is not written."
        )

    # "available*" entries are ObsPy bookkeeping, not FDSN services.
    return {
        name: frozenset(s for s in services if not s.startswith("available"))
        for name, services in results.items()
    }


def check_alias_collisions() -> None:
    """
    Warn when two inventory names point at the same archive.

    Querying both wastes a serial availability round trip for identical data.
    """
    by_url: dict[str, list[str]] = defaultdict(list)
    for name, url in URL_MAPPINGS.items():
        by_url[url].append(name)
    for url, names in sorted(by_url.items()):
        overlap = sorted(set(names) & INVENTORY)
        if len(overlap) > 1:
            print(f"  WARNING: {overlap} share the URL {url}; they are the same archive")


def render(
    regions: dict[str, dict[int, int]],
    services: dict[str, frozenset[str]],
) -> str:
    lines = [
        '"""',
        "Generated by tools/build_provider_regions.py. Do not edit by hand.",
        "",
        "REGIONS maps each provider to the grid cells where it holds stations,",
        "as (cell_id, station_count) pairs. The counts drive priority ordering:",
        "a provider with more stations inside a box is queried before one with",
        "fewer, so the genuinely local archive wins over an incidental match.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        f"CELL_DEG = {CELL_DEG!r}",
        "",
        f"REGIONS_GENERATED_UTC = {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')!r}",
        "",
        "PROVIDER_SERVICES: dict[str, frozenset[str]] = {",
    ]
    for name in sorted(services):
        entries = ", ".join(repr(s) for s in sorted(services[name]))
        lines.append(f"    {name!r}: frozenset({{{entries}}}),")
    lines.append("}")
    lines.append("")
    lines.append("REGIONS: dict[str, tuple[tuple[int, int], ...]] = {")

    for name in sorted(regions):
        pairs = sorted(regions[name].items())
        lines.append(f"    {name!r}: (")
        row: list[str] = []
        for cid, count in pairs:
            row.append(f"({cid}, {count})")
            if len(row) == 6:
                lines.append("        " + ", ".join(row) + ",")
                row = []
        if row:
            lines.append("        " + ", ".join(row) + ",")
        lines.append("    ),")

    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    check_alias_collisions()

    fed_counts, fed_rejected = fetch_fedcatalog()
    print(f"  {len(fed_counts)} datacenters, {fed_rejected} coordinates rejected")

    # Computed, never hardcoded. A hardcoded list rots silently: it once
    # claimed EPOSFR was non-federated (it is, as RESIF) while omitting KAGSR
    # (which genuinely is not), which would have left KAGSR with no cells at all.
    fallback = sorted(INVENTORY - set(fed_counts))
    print(f"absent from fedcatalog, using their own station service: {fallback}")

    regions: dict[str, dict[int, int]] = {
        name: counts for name, counts in fed_counts.items() if name in INVENTORY
    }

    if fallback:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for name, counts, rejected in pool.map(fetch_station_service, fallback):
                print(f"  {name}: {len(counts)} cells ({rejected} coordinates rejected)")
                regions[name] = counts

    # EARTHSCOPE is always queried and RASPISHAKE only ever arrives through
    # extra_providers, so neither is ever tested against a box's cells. Emitting
    # region data for them would be dead weight that could only cause harm if
    # some later edit consulted it. They are also the two largest footprints, so
    # leaving them out roughly halves the map.
    for name in CAPABILITY_ONLY:
        regions.pop(name, None)

    empty = sorted(name for name in INVENTORY if not regions.get(name))
    if empty:
        raise GeneratorError(
            f"no cells for {empty}. These are in INVENTORY, so automatic selection "
            f"would list them as available while they could never match a box. "
            f"Refusing to write a map with a silently unreachable provider."
        )

    services = probe_services(sorted(INVENTORY | CAPABILITY_ONLY))

    OUTPUT.write_text(render(regions, services), encoding="utf-8")

    total = sum(len(v) for v in regions.values())
    print(f"\nwrote {OUTPUT.relative_to(REPO_ROOT)}")
    print(f"  {len(regions)} providers, {total} cells")
    print(f"  capability recorded for {len(services)} providers")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GeneratorError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
