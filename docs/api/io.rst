io
==

The ``io`` module handles reading and writing manifests — the JSON records that track what was downloaded and processed during a pipeline run.

There are two manifests:

**Download manifest** — written after the download stage. Records which boxes were processed, which stations were downloaded for each box, and the file paths of the output waveforms. This is what ``run_pipeline()`` returns in ``results["manifest"]``.

**Processing manifest** — written after the processing stage. Records which traces were successfully processed and any that failed.

Manifests are stored as JSON files inside the event's output directory. They're useful for resuming interrupted runs, inspecting what was downloaded, and feeding downstream analysis steps.

.. automodule:: groundtrack.io
   :members:
   :undoc-members:
   :show-inheritance:
