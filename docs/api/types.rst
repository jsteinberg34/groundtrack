types
=====

The ``types`` module defines the core data structures used throughout the library. These are all plain Python dataclasses.

TrackPoint
----------

A single point along the propagated ground track. The pipeline produces a list of these from the SGP4 propagation step.

.. code-block:: python

   @dataclass
   class TrackPoint:
       time: datetime
       lat: float
       lon: float
       altitude_km: float | None = None

GeoBox
------

A geographic bounding box defined by latitude and longitude bounds. The ``box_id`` property returns a zero-padded string identifier like ``"box_006"``.

.. code-block:: python

   @dataclass
   class GeoBox:
       lat_min: float
       lat_max: float
       lon_min: float
       lon_max: float
       box_index: int

BoxWindow
---------

The full spatial and temporal descriptor for one download box. Combines a ``GeoBox`` with the time window and track index range for that segment.

.. code-block:: python

   @dataclass
   class BoxWindow:
       box: GeoBox
       t_enter: datetime        # when the object entered the box
       t_exit: datetime         # when the object exited the box
       t_download_start: datetime   # t_enter minus pre-padding
       t_download_end: datetime     # t_exit plus post-padding
       first_track_index: int
       last_track_index: int
       n_points: int

TrackSegment
------------

Precomputed great-circle arc geometry for one segment between two consecutive track points. Used internally by the geodesy module for efficient cross-track distance calculations. All angular values are in radians.

.. automodule:: groundtrack.types
   :members:
   :undoc-members:
   :show-inheritance:
