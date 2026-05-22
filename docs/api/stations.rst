stations
========

The ``stations`` module handles loading, parsing, deduplicating, and filtering seismic station metadata from the StationXML files downloaded by the pipeline.

After the download stage, each box directory contains a ``stations/`` subfolder with per-station StationXML files. These files carry both the station metadata (location, network code) and the instrument response needed for processing. The stations module provides tools to walk that directory tree, extract station metadata, and filter by proximity to the ground track.

Station Deduplication
---------------------

Because adjacent boxes overlap, the same physical station may appear in multiple box directories. Before filtering by distance or plotting, groundtrack deduplicates the station list by ``(network, station)`` to ensure each station is represented only once.

The convenience function ``load_and_filter_stations()`` handles the full workflow in one call and is what most users will want.

.. automodule:: groundtrack.stations
   :members:
   :undoc-members:
   :show-inheritance:
