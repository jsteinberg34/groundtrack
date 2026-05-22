processing
==========

The ``processing`` module handles instrument response removal and waveform filtering. Processing is optional — you can download raw waveforms and process them later, or not at all.

The default processing chain was validated against the Shenzhou-15 re-entry event and reproduces the published waveform results from Fernando & Charalambous (2026). The steps are:

1. **Demean** — remove the mean value of the trace
2. **Detrend** — remove any linear trend
3. **Taper** — apply a 5% cosine taper to both ends of the trace
4. **Response removal** — convert raw instrument counts to ground velocity (m/s) using the station's StationXML response. Uses a water level of 60 and a pre-filter whose upper corners are set dynamically per trace (see below).
5. **Bandpass** — 1–20 Hz, 4th-order Butterworth, causal filter (``zerophase=False``). The upper corner is capped at 90% of the trace's Nyquist frequency.

Nyquist-Aware Filtering
-----------------------

Different stations record at different sample rates. Broadband HHZ stations typically sample at 100 Hz (Nyquist: 50 Hz), while BHZ stations sample at 40 Hz (Nyquist: 20 Hz). Setting a 20 Hz bandpass corner on a BHZ trace without adjustment means the filter corner sits exactly at Nyquist, which produces ringing artifacts in the output.

To handle this, groundtrack computes the pre-filter upper corners and the bandpass upper corner dynamically per trace as a fraction of the actual Nyquist frequency. This ensures the filter stays safely below Nyquist regardless of the station's sample rate.

Default Parameters
------------------

All defaults live at module scope so they're easy to find and audit. Changing them will change scientific results.

.. code-block:: python

   DEFAULT_WATER_LEVEL = 60
   DEFAULT_OUTPUT = "VEL"        # velocity in m/s; validated against Shenzhou-15 re-entry
   DEFAULT_TAPER_PCT = 0.05
   DEFAULT_FREQMIN = 1.0
   DEFAULT_FREQMAX = 20.0
   DEFAULT_CORNERS = 4
   DEFAULT_ZEROPHASE = False
   DEFAULT_PRE_FILT_LOW = (0.5, 0.8)   # lower corners only; upper corners computed per trace

.. automodule:: groundtrack.processing
   :members:
   :undoc-members:
   :show-inheritance:
