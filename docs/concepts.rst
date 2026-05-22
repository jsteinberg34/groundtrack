Concepts
========

This page explains the key ideas behind how groundtrack is designed. If you just want to run it, :doc:`quickstart` is the place to start. This is for when you want to understand *why* the pipeline works the way it does.

The Problem
-----------

When space debris re-enters the atmosphere, it produces sonic booms that couple into the ground and get recorded by seismic stations. In principle, you could use those recordings to figure out where the object was, how it fragmented, and where pieces landed. In practice, getting from "object re-entered somewhere over North America" to "here are the processed waveforms from every nearby seismic station" requires a lot of steps that nobody had automated before.

The naive approach — just query every global seismic station for the relevant time window — doesn't work. FDSN providers rate-limit those queries, and you'd be downloading an enormous amount of data from stations that are nowhere near the re-entry track. You need a smarter strategy.

The Ground Track and Corridor
------------------------------

The starting point is the object's orbital trajectory. Given a NORAD catalog ID and a time window, groundtrack fetches the Two-Line Element set (TLE) from Space-Track and propagates the orbit using SGP4 via the Skyfield library. This gives you a series of ``TrackPoint`` objects — each one is just a timestamp paired with a latitude, longitude, and altitude.

The key physical insight is that sonic booms from re-entry travel roughly perpendicular to the ground track. A station has to be within some cross-track distance — the *corridor* — to have any realistic chance of detecting the signal. groundtrack uses 100 km by default, which is consistent with the methodology in Fernando & Charalambous (2026).

Spatial Tiling
--------------

Rather than working with the full track at once, groundtrack divides it into overlapping *boxes*. Each box covers roughly 300 km of along-track distance, is padded by the corridor distance in the latitudinal direction, and has a time window derived from when the object was in that segment.

The boxes overlap by 50 km. This ensures that a station near the boundary between two boxes gets captured by at least one of them, rather than falling through the gap.

Each box is independent — it has its own geographic bounds, its own time window, and its own output directory. This design makes the download step resumable: if a run gets interrupted, boxes that were already completed are skipped on the next run.

Two-Phase Download
------------------

The download stage runs in two phases for each box:

**Phase 1** queries FDSN providers for the station inventory within the box's geographic bounds. This is a cheap metadata-only request that tells us which stations exist in the area.

**Phase 2** filters that inventory by the actual cross-track distance from each station to the ground track. Only stations within the corridor threshold are kept for waveform download.

This two-phase approach is the key efficiency win. By filtering stations before requesting any waveform data, we avoid downloading from stations that are inside the rectangular box but are actually far from the track.

Cross-Track Distance
--------------------

The distance filtering uses a two-pass approach. For most stations, a fast vectorized point-to-point calculation is sufficient to determine whether they're clearly inside or outside the corridor. The tricky case is a station that falls near the boundary.

Consider a station whose nearest sampled track point is 105 km away — just outside a 100 km corridor. Its true closest approach to the track might actually be less than 100 km, because the closest point on the track lies *between* two sampled points rather than at one of them. For stations within 10 km of the corridor threshold in either direction, groundtrack uses the true spherical cross-track arc formula (from Ed Williams' Aviation Formulary) to compute the exact distance to the nearest track segment.

Processing Chain
----------------

The default processing chain is validated against the Shenzhou-15 re-entry event and reproduces the waveform results from Fernando & Charalambous (2026):

1. **Demean** — remove the mean of the trace
2. **Detrend** — remove any linear trend
3. **Taper** — apply a 5% cosine taper to both ends
4. **Response removal** — remove the instrument response, outputting velocity in m/s, with a water level of 60 and a pre-filter whose upper corners are set dynamically to 90% and 95% of each trace's Nyquist frequency
5. **Bandpass** — 1–20 Hz, 4th-order Butterworth, causal (``zerophase=False``), with the upper corner capped at 90% of Nyquist per trace

The dynamic Nyquist handling is important. Different stations sample at different rates — a broadband HHZ station might sample at 100 Hz (Nyquist: 50 Hz), while a BHZ station samples at 40 Hz (Nyquist: 20 Hz). If you apply a 20 Hz bandpass to a BHZ trace without capping, the filter corner sits right at the Nyquist frequency, which causes ringing artifacts. groundtrack caps the bandpass at 90% of Nyquist per trace to avoid this.

All processing parameters are configurable. The defaults are what we found to work well for the Shenzhou-15 event, but you may want to adjust them for different events or network configurations.
