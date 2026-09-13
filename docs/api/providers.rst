providers
=========

The ``providers`` module decides which FDSN data providers are worth querying for each download box.

Why this is not simply "query everything": ObsPy's ``MassDownloader`` runs availability queries **sequentially** per client, so a box's wall time is the *sum* of its providers' response times rather than the maximum. Measured per-provider response for a single box ranges from 0.11 s to nearly 5 s, and several endpoints in ``URL_MAPPINGS`` hang or serve no station metadata at all. Across a 30-box event, querying every provider for every box is not affordable for a re-entry-triggered run.

Selection is offline. The module ships a map of the grid cells where each provider actually holds stations, inverted once at import into a cell-to-provider index, so resolving a box is a couple of dictionary lookups and never iterates the provider list. Cost is proportional to the number of cells a box covers, not to how many providers exist, and no network request is involved. Provider choice is therefore deterministic for a given release and reproducible offline.

Supported providers
-------------------

With ``providers="auto"`` these 26 archives are supported:

================  =====================================
Provider          Region
================  =====================================
``EARTHSCOPE``    Global, **queried for every box**
----------------  -------------------------------------
``AUSPASS``       Australia
``BGR``           Germany
``BGS``           United Kingdom
``EPOSFR``        France, mainland
``ETH``           Switzerland
``GEOFON``        Germany, global deployments
``GEONET``        New Zealand
``ICGC``          Catalonia
``IESDMC``        Taiwan
``IGN``           Spain
``INGV``          Italy
``IPGP``          France, overseas and volcano networks
``KAGSR``         Kamchatka, Russia (station metadata only)
``KNMI``          Netherlands
``KOERI``         Turkey
``LMU``           Germany
``NCEDC``         Northern California
``NIEP``          Romania
``NOA``           Greece
``NRCAN``         Canada
``ORFEUS``        European aggregator (ODC)
``SCEDC``         Southern California
``TEXNET``        Texas
``UIB-NORSAR``    Norway
``USP``           Brazil (station metadata only)
================  =====================================

The region label is where the archive is based, not a boundary. Actual coverage is the measured cell footprint and is often much wider, which is why the map is measured rather than hand-drawn.

``KAGSR`` and ``USP`` publish station metadata but return 404 for waveforms. They are still queried, since knowing instruments exist near a corridor is a meaningful result, but nothing depends on them for data.

Not selected automatically
~~~~~~~~~~~~~~~~~~~~~~~~~~

- ``RASPISHAKE`` — citizen-science network, available via ``extra_providers``. Its ``EHZ``/``SHZ`` channels also need ``channel_priorities`` widened to be reachable at all.
- ``IRISPH5`` — nodal experiment data, which can match enormous requests.
- ``USGS``, ``EMSC``, ``ISC`` — event catalogues, no station metadata.
- ``EIDA`` — a router holding no data of its own, routing to members already listed.
- ``IRIS``, ``IRISDMC``, ``GFZ``, ``ODC``, ``RESIF`` — alternative names for archives already listed. Passing one is fine; it will not be queried twice.

Any of these can still be requested by name through ``providers`` or ``extra_providers``.

Selection modes
---------------

``providers="auto"`` (the default, and what ``None`` now means) selects by region from the built-in inventory and always appends EarthScope. An explicit sequence replaces automatic selection entirely and is used in the caller's own order. ``extra_providers`` is unioned on top of whichever of those applies, is never region-filtered, and ranks last.

Ordering
--------

The resolved list is ordered by how many stations each provider holds *inside that box*, then EarthScope, then any extras. Order is priority for ``MassDownloader``: the first provider holding a station wins. Sorting by in-box station count is what puts the genuinely local archive first — for a Southern California box, alphabetical order would rank LMU (3 stations there) above SCEDC (over 3000).

.. note::
   Not every provider serves waveforms. ``KAGSR`` and ``USP`` offer station metadata but return 404 on dataselect. They are still queried, because "instruments exist near this corridor" is a real result, but a station only they report is **not claimed**: ``MassDownloader`` requires both a station and a dataselect service and would drop the provider, so the claim could never be honoured while still preventing any other box from trying. Those stations are reported per box as ``discovered_not_obtainable``, distinct from ``claimed_not_downloaded``.

.. note::
   Stations in the reserved ``SY`` (synthetic) and ``XX`` (test) networks are never downloaded, in any selection mode, including when the caller names their host provider explicitly. EarthScope serves thousands of ``SY`` stations at real-looking coordinates and nothing else in the pipeline would stop one being treated as a candidate detection.

Regenerating the map
--------------------

The map is a source constant, generated by ``tools/build_provider_regions.py`` and committed. That script is kept in the repository so the map is auditable and reproducible rather than asserted, but it is excluded from the installed package: nothing at runtime should reach the network.

.. code-block:: console

   python tools/build_provider_regions.py

It takes its data from a single EarthScope fedcatalog request, which routes by *actual holdings*. A provider's own station service is not equivalent — SCEDC republishes metadata for networks it does not serve, which produced phantom coverage across Alaska in an earlier draft. Inventory providers absent from the fedcatalog response fall back to their own station service, and that set is computed each run rather than hardcoded. The generator fails rather than emitting a map in which any inventory provider has no cells, since such a provider would look supported while never matching a box.

Run it when ObsPy adds a provider (a test fails when that happens), when a provider's coverage is known to have changed materially, or periodically. Review the diff before committing: it is a versioned artifact, and ``provider_regions_generated_utc`` in each run manifest records which build produced that run's selection.

.. automodule:: groundtrack.providers
   :members:
   :undoc-members:
   :show-inheritance:
