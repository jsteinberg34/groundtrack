geodesy
=======

The ``geodesy`` module handles the spherical geometry calculations needed for corridor distance filtering. Most users won't interact with this module directly — it's used internally by the download and stations modules.

Cross-Track Distance
--------------------

The key function is ``min_distance_km_to_track()``, which computes the minimum great-circle distance from a point (a seismic station) to a sequence of track segments. This is what determines whether a station falls inside the corridor.

The calculation uses a two-pass approach for efficiency:

**Fast pass** — for each track segment, a quick point-to-point distance check determines whether the station is clearly inside or outside the corridor with enough margin that the exact cross-track distance doesn't matter.

**Ambiguous band** — if the station's nearest sampled track point falls within 10 km of the corridor threshold in either direction, there's a chance the station's true closest approach (which lies between two sampled points) could be on the other side of the threshold. For these borderline cases, groundtrack computes the true spherical cross-track arc distance using the formula from `Ed Williams' Aviation Formulary <http://www.edwilliams.org/avform.htm>`_.

The 10 km ambiguous band is hardcoded as ``_AMBIGUOUS_BAND_KM = 10.0``. A future improvement would compute this dynamically from the actual track point spacing, but in practice a 1-second sampling rate at typical LEO velocities (~7.5 km/s) means point spacing is around 7.5 km, so 10 km is a reasonable static value.

.. automodule:: groundtrack.geodesy
   :members:
   :undoc-members:
   :show-inheritance:
