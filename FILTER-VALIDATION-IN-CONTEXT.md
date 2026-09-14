# Validating a room-correction filter in context

## Purpose

A correction filter should not be judged only from its own impulse response.
The relevant endpoint is the loudspeaker, room and filter together. Phase
rotation or stored energy in a filter may be correcting behavior already
present in the loudspeaker-room system.

Filter-only tests remain useful: they catch sharp resonators, excessive group
delay, long tails and export errors before deployment. They are screening
tests, not a complete acoustic or perceptual verdict.

## Required calculation

Use unsmoothed complex left and right measurements at every design position,
the exact deployed filters, and a common acoustic timing reference. For each
position `p`:

```text
L_after(p,f) = L_before(p,f) * F_left(f)
R_after(p,f) = R_before(p,f) * F_right(f)

Stereo_before(p,f) = (L_before(p,f) + R_before(p,f)) / 2
Stereo_after(p,f)  = (L_after(p,f)  + R_after(p,f))  / 2
```

Apply filters before spatial averaging, while phase remains meaningful. A
spatial RMS average has no coherent spatial phase and cannot reconstruct the
stereo result at any seat.

Remove only common implementation latency. Retain the filter's relative phase,
which is part of the correction under test. If exports omit DC or Nyquist,
restrict analysis to measured frequencies and use identical tapered windows
before and after. A rectangular frequency window creates a symmetric impulse
that can be mistaken for pre-ringing.

## What to report

Report tonal correction, group delay, precursor energy, late energy and
gated-tone settling for left, right and coherent left-plus-right responses.
Show medians and the full range across positions; do not hide a poor position
inside one average.

Pre- and post-arrival energy have different perceptual meaning. Existing room
decay after a transient does not automatically excuse new energy before it.
Measure several precursor windows, such as earlier than 1, 5, 10 and 20 ms.
A component confined close to the main impulse differs from a long pre-echo.

Band-limited bass impulses are intrinsically long. Their symmetric lobes must
not be called filter pre-echo without comparison against the identical analysis
window. Normalized late-energy fractions also change when EQ changes spectral
weighting, so interpret them alongside level and main-arrival-referenced decay.

## Role of `drc_acceptance.py`

`drc_acceptance.py` screens the filter for sharp features, bass group-delay
excursions and gated-tone tails. Revision 2 uses full linear convolution, nine
gate phases, a sustained quiet interval, late-echo observation, a pure-delay
control and preserved censored trials. Regression tests cover rebounds, late
echoes, phase coverage, censoring and zero-padding invariance.

Its thresholds are project build-quality heuristics. A pass does not establish
audibility, acoustic improvement, spatial robustness or safe gain. Pre-peak
energy is reported but does not enter pass/fail. The tail verdict uses the
median of nine phases, and default tests stop at 200 Hz.

| Evidence | Question answered |
|---|---|
| Filter-only acceptance | Is the coefficient set obviously pathological? |
| Multi-position contextual prediction | Does it improve the measured system, and at what timing cost? |
| Fresh corrected measurements | Did the real chain produce the prediction? |
| Level-matched listening | Is the resulting tradeoff preferable? |

## Manual correction and Dirac Live

Minimum-phase magnitude correction, crossover all-pass correction and inversion
of position-dependent room excess phase are different operations. Crossover
timing is a loudspeaker property that can remain consistent nearby. A
reflection or cancellation that moves with the microphone is a poor candidate
for exact phase inversion.

Professional mixed-phase systems face the same physics. Dirac says it limits
pre-ringing by correcting excess phase only when it is common across measurement
positions. Ordinary Dirac Live does not expose a user-controlled factorization
equivalent to this project's common-bass filter plus separate left/right
filters. Dirac Live Bass Control is related: its documentation describes a
common low-frequency target, speaker-group-specific higher-frequency targets
and cross-channel optimization. Its internal optimization is proprietary and
is not the same inspectable construction.

The manual method has an advantage when kept auditable: the common and
per-channel terms, their ranges, phase contribution and gain cost can be tested
separately. Automation has another advantage: it can constrain a multi-position
optimization consistently. The useful distinction is not homemade versus
professional; it is whether stable behavior is separated from
position-specific behavior and the combined response is verified.

References:

- [Dirac Live technical overview](https://www.dirac.com/wp-content/uploads/2025/07/Dirac-Live-a-technical-overview-white-paper.pdf)
- [Dirac Live Bass Control filter design](https://helpdesk.dirac.com/en/dirac-bass-control/Filter-Design-c592)
- [REW Group Delay graph](https://www.roomeqwizard.com/help/help/html/graph_groupdelay.html)
- [DRC documentation](https://drc-fir.sourceforge.net/doc/drc.html)

## Program-material headroom

Maximum frequency gain does not bound arbitrary music peaks after mixed-phase
filtering. Phase rotation changes instantaneous summation, while resampling can
reveal intersample peaks. Validate headroom with analytical checks, oversampled
source peaks, offline convolution through the deployed path, demanding real
recordings and a margin above the largest result.

A safety limit above 0 dBFS is an emergency abort threshold, not usable digital
headroom. High-precision digital attenuation does not alter phase or create
harmonic ringing; its practical cost is lower signal level relative to the
downstream noise floor.

For each build retain measurement and coefficient hashes, acceptance output,
per-position contextual results, coherent stereo results, stated precursor
windows, real-program peak tests, attenuation, fresh corrected measurements
when available, and the level-matched listening conclusion.
