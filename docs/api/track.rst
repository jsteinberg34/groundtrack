track
=====

The ``track`` module handles fetching TLE data from Space-Track and propagating the orbital trajectory into a series of ground track points. This is the first stage of the pipeline.

Under the hood it uses the `Skyfield <https://rhodesmill.org/skyfield/>`_ library for SGP4 propagation, which gives accurate sub-kilometer positions for low Earth orbit objects over the typical re-entry analysis windows.

TLEs are cached to disk to avoid hitting Space-Track's strict rate limits. If a cached TLE already exists for the requested object and is recent enough to cover the analysis window, it gets used without making a new API request.

.. automodule:: groundtrack.track
   :members:
   :undoc-members:
   :show-inheritance:
