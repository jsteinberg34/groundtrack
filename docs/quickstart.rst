Quickstart
==========

This page walks through the most common ways to use groundtrack. For a deeper explanation of what each step does, see :doc:`concepts`.

Minimal Run
-----------

The simplest call downloads waveform data for a re-entry event without any processing:

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

This runs the full pipeline — fetching the TLE, propagating the ground track, tiling it into download boxes, querying FDSN providers for nearby stations, and downloading the raw waveforms. Everything gets written to ``data/outputs/shenzhou15_reentry/``.

The ``results`` dictionary contains:

- ``results["track"]`` — the propagated ground track and TLE metadata
- ``results["boxes"]`` — the list of ``BoxWindow`` objects that were used
- ``results["manifest"]`` — a record of what was downloaded and where

With Processing
---------------

Pass ``apply_processing=True`` to also remove instrument response and apply a bandpass filter after downloading:

.. code-block:: python

   results = run_pipeline(
       norad_id=56873,
       start="2024-04-02T08:40:00Z",
       end="2024-04-02T09:00:00Z",
       cache_dir="data/cache",
       output_dir="data/outputs",
       event_name="shenzhou15_reentry",
       apply_processing=True,
       freqmin=1.0,
       freqmax=20.0,
   )

The default processing chain is: demean → detrend → 5% cosine taper → instrument response removal (output in velocity, m/s) → 1–20 Hz bandpass. All parameters are configurable — see :doc:`api/pipeline` for the full list.

Two-Step Workflow
-----------------

If you want to download once and experiment with different processing parameters without re-downloading, use the two-step workflow:

.. code-block:: python

   from groundtrack import run_pipeline, process_boxes

   # Step 1 — download only
   results = run_pipeline(
       norad_id=56873,
       start="2024-04-02T08:40:00Z",
       end="2024-04-02T09:00:00Z",
       cache_dir="data/cache",
       output_dir="data/outputs",
       event_name="shenzhou15_reentry",
   )

   # Step 2 — process with custom parameters
   process_boxes(
       boxes_root=results["manifest"]["boxes_root"],
       freqmin=1.0,
       freqmax=10.0,
   )

``run_pipeline()`` is idempotent for the download step — if waveforms already exist for a box, it skips them. This means you can safely re-run it after a partial download or network interruption.

Visualizing Results
-------------------

groundtrack includes plotting utilities for inspecting what was downloaded and validating the processing. These require the ``[plotting]`` extras.

**Plot the ground track and download boxes:**

.. code-block:: python

   from groundtrack import plot_track_and_boxes

   plot_track_and_boxes(
       track_points=results["track"]["track_points"],
       box_windows=results["boxes"],
   )

**Compare raw vs. processed waveforms for a single station:**

.. code-block:: python

   from groundtrack import plot_waveform_comparison
   from pathlib import Path

   plot_waveform_comparison(
       boxes_root=Path(results["manifest"]["boxes_root"]),
       network="CI",
       station="SMI",
       t_start_utc="2024-04-02T08:44:00Z",
       t_end_utc="2024-04-02T08:54:00Z",
   )

**Plot all processed waveforms across every downloaded station:**

.. code-block:: python

   from groundtrack import plot_all_waveforms
   from pathlib import Path

   plot_all_waveforms(
       boxes_root=Path(results["manifest"]["boxes_root"]),
       t_start_utc="2024-04-02T08:44:00Z",
       t_end_utc="2024-04-02T08:54:00Z",
   )

See :doc:`api/plotting` for the full plotting API.
