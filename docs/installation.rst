Installation
============

Requirements
------------

- Python 3.10 or later
- A free `Space-Track <https://www.space-track.org>`_ account for TLE and TIP message access

Install from PyPI
-----------------

.. code-block:: bash

   pip install groundtrack

This installs the core library. If you want to use the built-in plotting utilities (``plot_track_and_boxes``, ``plot_stations``, ``plot_waveform_comparison``, etc.), install with the optional plotting dependencies:

.. code-block:: bash

   pip install groundtrack[plotting]

The plotting extras pull in ``matplotlib`` and ``cartopy``. Cartopy in particular can be finicky to install on some systems — if you run into issues, the `Cartopy installation guide <https://scitools.org.uk/cartopy/docs/latest/installing.html>`_ covers platform-specific steps.

Space-Track Credentials
------------------------

groundtrack needs Space-Track credentials to fetch orbital data. The easiest way to set these up is with a ``.env`` file in your project root:

.. code-block:: text

   SPACETRACK_USER=your_email@example.com
   SPACETRACK_PASS=your_password

Make sure ``.env`` is in your ``.gitignore``:

.. code-block:: bash

   echo ".env" >> .gitignore

Alternatively, you can pass credentials directly to ``run_pipeline()``:

.. code-block:: python

   results = run_pipeline(
       ...,
       username="your_email@example.com",
       password="your_password",
   )

The direct approach is useful for notebooks or environments where you manage secrets differently. Either way, credentials are never stored or logged by the library.
