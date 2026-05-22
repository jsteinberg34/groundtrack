groundtrack
===========

**groundtrack** is a Python library for discovering and analyzing seismic signals produced when space debris or spacecraft re-enter the atmosphere. When an object re-enters at hypersonic speeds, it generates sonic booms that couple into the ground and are recorded by seismic stations. groundtrack automates everything from fetching the orbital data to downloading and processing the waveforms.

The library was developed at Johns Hopkins University in collaboration with Dr. Benjamin Fernando (Department of Earth and Planetary Sciences) and was validated against the `Shenzhou-15 re-entry event <https://doi.org/10.1126/science.adz4676>`_, reproducing published results from a peer-reviewed *Science* paper.

.. code-block:: bash

   pip install groundtrack

.. code-block:: python

   from groundtrack import run_pipeline

   results = run_pipeline(
       norad_id=56873,
       start="2024-04-02T08:40:00Z",
       end="2024-04-02T09:00:00Z",
       cache_dir="data/cache",
       output_dir="data/outputs",
       event_name="shenzhou15_reentry",
   )

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   installation
   quickstart
   concepts

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   api/pipeline
   api/track
   api/tiling
   api/download
   api/processing
   api/stations
   api/plotting
   api/geodesy
   api/io
   api/types

.. toctree::
   :maxdepth: 1
   :caption: About

   changelog

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
