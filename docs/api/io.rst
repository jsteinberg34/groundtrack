io
==

The ``io`` module provides file system utilities used throughout the pipeline —
creating directories, managing TLE cache paths, and writing JSON artifacts to disk.

The main JSON artifact produced by the pipeline is the download manifest
(``download_manifest.json``), written to the event's run folder after the download
stage completes. It records which boxes were processed, how many stations were
downloaded for each, and the processing parameters if ``apply_processing=True``
was used. This is what ``run_pipeline()`` returns in ``results["manifest"]``.

Manifests are useful for resuming interrupted runs, inspecting what was downloaded,
and feeding downstream analysis steps without re-running the full pipeline.

.. automodule:: groundtrack.io
   :members:
   :undoc-members:
   :show-inheritance: