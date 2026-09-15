#!/usr/bin/env python3
"""
drc_acceptance.py -- acceptance tests for a DRC correction filter.

Run this on the WAV that BruteFIR will actually load, before deploying it.
It screens the filter for sharp features, delay excursions and residual output
after note-off. It does not measure speaker/room decay or establish audibility.

    ./drc_acceptance.py FLX-trimmed-48k.wav
    ./drc_acceptance.py FLX-trimmed-48k.wav FRX-trimmed-48k.wav
    ./drc_acceptance.py --plot out.png FLX-trimmed-48k.wav

Three tests, all run on the unsmoothed filter itself:

  1. sharpest feature below 200 Hz, as Q = centre frequency / bandwidth.  A
     feature far too narrow for its frequency cannot have come from smoothed
     data, and is a resonator.  Q rather than FFT bins: bin spacing is fs/n,
     so a bin-based threshold passes or fails the same filter depending on how
     long the exported file happens to be.
  2. group delay excursion over 20-200 Hz.  A correction filter should show
     a few ms; tens of ms means a resonator.  This is the test that maps
     onto a single REW graph.
  3. gated-tone tail: play a sine, stop it, measure how long the output
     takes to fall 40 dB.  This is the direct numerical form of the
     symptom.  A unit impulse is pushed through the identical chain as a
     CONTROL, because the measurement has its own floor at low frequency --
     see the NOTES.md section 18 retraction for what happens without one.

     The tail is the MEDIAN over nine explicitly spaced gate phases. It is
     the last -40 dB exceedance, followed by at least two periods (and at
     least 50 ms) below threshold. All later output in the observation is
     checked, including delayed echoes. Censored trials remain in the median
     and IQR; their count is reported. Noisy trials still affect the verdict.

     Each tail is judged as control + MAX_EXCESS_MS, because the estimator
     has a floor of its own that is large at low frequency: a pure delay,
     which rings not at all, measures 132 ms at 28.7 Hz and 5 ms at 180 Hz.
     What the test asks is how far above that floor the filter puts you.

Revision 2 (2026-09-13) rewrote the tail estimator.  Revision 1 reported the
FIRST -40 dB crossing, so a rebound afterwards did not count; it circularly
rolled the impulse before a LINEAR convolution, which could move late ringing
in front of the main peak and out of the measurement; its observation window
shrank by the filter's own latency; and it dropped never-settled trials from
the median instead of carrying them.  Numbers from revision 1 are NOT
comparable with these -- it under-reported.  The estimator is anchored: it
reproduces this project's Sept 2025 filter at 1349 ms against the 1348 ms on
record, and measures X801, the known-good control, at the floor exactly.

The thresholds remain build-quality heuristics, not audibility limits: no
listening test has been run against this scale.
The default frequency checks end at 200 Hz; use --fmax to cover a wider band.

Exit status is 0 if every filter passes, 1 otherwise.
"""

import argparse
import struct
import sys

import numpy as np
from scipy.signal import find_peaks, peak_widths, hilbert, fftconvolve

# ---- thresholds (NOTES.md section 21.9) ------------------------------------
# Sharpness limit for the narrowest feature below FMAX, as f0/bandwidth.
#
# This used to be expressed in FFT bins, which is a bug: bin spacing is fs/n,
# so the SAME filter passed or failed depending on how long the exported file
# was.  Measured 2026-08-14, one filter trimmed from 262144 to 131072 taps:
# the band-edge feature is 9.07 Hz wide in one and 9.37 Hz in the other -- the
# same feature -- but 49.6 bins against 25.6, because each bin doubled in
# width.  It "failed" purely by getting shorter.
#
# f0/bandwidth is dimensionless. This is a half-prominence sharpness ratio,
# not resonator Q, and FDW cycles do not impose a strict ceiling on its value.
# The threshold is a project heuristic calibrated against historical examples:
#
#   Sept 2025 deployed filter, 0.30 Hz at 28.9 Hz   -> 96   FAIL (1348 ms ring)
#   no-LF-tail notch,          0.23 Hz at 20.0 Hz   -> 87   FAIL
#   74 Hz SBIR shoulder,       5.78 Hz at 73.2 Hz   -> 13   marginal
#   20 Hz band-edge transition,9.37 Hz at 25.6 Hz   ->  3   pass
MAX_Q = 12.0
MIN_BINS = 30.0      # legacy, reported for reference only -- not a pass/fail
MAX_GD_MS = 10.0     # max group-delay excursion 20-200 Hz, ms
FMAX = 200.0         # band over which the filter is judged

# Gated-tone ringing allowed ABOVE the analysis floor, in ms -- not an absolute
# tail.  The estimator has a floor of its own: a pure delay, which rings not at
# all, still measures 5 ms at 180 Hz and 132 ms at 28.7 Hz, because a 40 dB fall
# of the Hilbert envelope cannot be resolved faster than that.  Every tail is
# therefore judged against the control, never on its own.
#
# This used to be `max(MAX_TAIL_MS, 3*control, ...)`, which is a bug: the
# control is the NOISIEST quantity in the test, so multiplying it put the
# verdict at the mercy of the floor rather than the filter.  Measured
# 2026-09-13 on FDW6 L at 79 Hz, the nine gate phases gave
#
#   filter    113.8 125.4 124.5 111.3 104.6 114.5 125.2 123.4 109.8   IQR 13
#   control    20.9  47.4  52.8  30.9   8.1  35.6  53.5  45.1   1.9   IQR 27
#
# -- a floor twice as dispersed as the signal it gates.  Three times its median
# made the filter FAIL at 107 ms and PASS at drop_db 35 or 45, or ramp 1 ms or
# 20 ms: the tail never moved, the limit did.  Additive headroom over the floor
# is stable under all four.  Calibrated 2026-09-13 against the whole archive:
#
#   X801, the known-good control     floor + 0 ms at every tone   pass
#   FDW6 L / R                       worst floor + 79 ms          pass
#   FDW8 R                           worst floor + 88 ms          pass
#   FDW8 L                           floor + 106 ms at 79 Hz      FAIL
#   Sept 2025 deployed (120.blue L)  floor + 1282 ms at 51.2 Hz   FAIL
#
# The gap between the worst passing filter and the known-bad one is 14x, so the
# exact value is not delicate.  It is still a build-quality heuristic and NOT an
# audibility threshold: no listening test has been run against this scale.
MAX_EXCESS_MS = 100.0

TONES = [28.7, 40.0, 51.2, 63.0, 79.0, 100.0, 116.5, 128.2, 145.5, 180.0]
TAIL_PHASES = tuple(2 * np.pi * np.arange(9) / 9)
TAIL_DURATION = 1.20
TAIL_OBSERVATION = 2.0


def read_wav(path):
    """Minimal RIFF reader: mono PCM 16/24/32 and IEEE float 32/64."""
    b = open(path, "rb").read()
    if b[:4] != b"RIFF" or b[8:12] != b"WAVE":
        raise ValueError("%s: not a RIFF/WAVE file" % path)
    i, fmt, data = 12, None, None
    while i + 8 <= len(b):
        cid = b[i:i + 4]
        sz = struct.unpack("<I", b[i + 4:i + 8])[0]
        if cid == b"fmt ":
            fmt = b[i + 8:i + 8 + sz]
        elif cid == b"data":
            data = b[i + 8:i + 8 + sz]
        i += 8 + sz + (sz & 1)
    if fmt is None or data is None:
        raise ValueError("%s: missing fmt or data chunk" % path)
    tag, ch, fs, _, _, bits = struct.unpack("<HHIIHH", fmt[:16])
    if tag == 0xFFFE:                      # WAVE_FORMAT_EXTENSIBLE
        tag = struct.unpack("<H", fmt[24:26])[0]
    if tag == 3:
        if bits not in (32, 64):
            raise ValueError('%s: unsupported float bit depth %s' % (path, bits))
        x = np.frombuffer(data, dtype="<f4" if bits == 32 else "<f8")
        x = x.astype(np.float64)
    elif tag == 1 and bits == 32:
        x = np.frombuffer(data, dtype="<i4").astype(np.float64) / 2 ** 31
    elif tag == 1 and bits == 16:
        x = np.frombuffer(data, dtype="<i2").astype(np.float64) / 2 ** 15
    elif tag == 1 and bits == 24:
        v = np.frombuffer(data, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        w = v[:, 0] | (v[:, 1] << 8) | (v[:, 2] << 16)
        x = np.where(w >= 1 << 23, w - (1 << 24), w).astype(np.float64) / 2 ** 23
    else:
        raise ValueError("%s: unsupported format tag=%d bits=%d" % (path, tag, bits))
    if ch != 1:
        raise ValueError('%s: expected mono filter, got %s channels' % (path, ch))
    if fs <= 0 or len(x) < 2 or not np.isfinite(x).all() or not np.any(x):
        raise ValueError('%s: invalid, empty, non-finite or silent filter' % path)
    return x, fs


def analysis_spectrum(h, fs):
    """Dense spectrum, with bulk peak delay removed before phase unwrapping.

    Remove only exact zero padding; never reorder samples. At least 0.1 Hz
    grid spacing and 4x support oversampling reduce FFT-grid dependence.
    """
    support = np.flatnonzero(h)
    if not len(support):
        raise ValueError('Silent filter')
    core = h[support[0]:support[-1] + 1]
    nfft = max(int(np.ceil(fs / 0.1)), 4 * len(core))
    f = np.fft.rfftfreq(nfft, 1 / fs)
    spectrum = np.fft.rfft(core, nfft)
    spectrum *= np.exp(2j * np.pi * f * np.argmax(np.abs(core)) / fs)
    return f, spectrum


def narrowest_feature(h, fs, fmax=FMAX, prominence=1.5):
    """Sharpest peak/notch below fmax -> (centre Hz, width Hz, width bins, Q).

    A "feature" is any local bump or dip in the FILTER's own response standing
    at least `prominence` dB clear of its surroundings.  Width is taken at half
    that prominence (scipy's rel_height=0.5), so it is not the -3 dB bandwidth
    of a resonance and Q here is a sharpness ratio rather than a biquad Q --
    consistent, dimensionless, and independent of the exported file length,
    which is what the criterion needs.

    "Sharpest" means largest f0/bandwidth, not smallest bandwidth: a 5 Hz-wide
    feature at 25 Hz is broad, the same width at 190 Hz is not.
    """
    f, spectrum = analysis_spectrum(h, fs)
    # Find prominence/width using the complete spectrum, then select centres
    # in-band. Cropping first can hide or truncate features at band edges.
    sb = 20 * np.log10(np.abs(spectrum) + 1e-30)
    df = fs / len(h)
    best_f, best_bw, best_q = None, np.inf, 0.0
    for sign in (-1, 1):
        pk, _ = find_peaks(sign * sb, prominence=prominence)
        if not len(pk):
            continue
        w, _, _, _ = peak_widths(sign * sb, pk, rel_height=0.5)
        for i, k in enumerate(pk):
            if not 15 <= f[k] <= fmax:
                continue
            bw = w[i] * (f[1] - f[0])
            if bw <= 0:
                continue
            q = f[k] / bw
            if q > best_q:
                best_q, best_bw, best_f = q, bw, f[k]
    if best_f is None:
        return None, np.inf, np.inf, 0.0
    return best_f, best_bw, best_bw / df, best_q


def group_delay_excursion(h, fs, fmax=FMAX):
    """Peak |group delay| over 20..fmax Hz, referenced to the 200-400 Hz level."""
    f, spectrum = analysis_spectrum(h, fs)
    gd = -np.gradient(np.unwrap(np.angle(spectrum)), 2 * np.pi * (f[1] - f[0])) * 1e3
    ref_band = (f >= 200) & (f <= 400)
    ref = np.median(gd[ref_band]) if ref_band.any() else 0.0
    m = (f >= 20) & (f <= fmax)
    g = gd[m] - ref
    k = int(np.argmax(np.abs(g)))
    return f[m][k], g[k]


def _settling_ms(envelope, threshold, fs, hold_samples):
    """Last exceedance plus one sample; NaN if the quiet suffix is too short."""
    if not np.isfinite(envelope).all() or not np.isfinite(threshold) or threshold <= 0:
        return np.nan
    above = np.flatnonzero(envelope >= threshold)
    settled = int(above[-1]) + 1 if len(above) else 0
    if len(envelope) - settled < hold_samples:
        return np.nan
    return settled / fs * 1e3


def _gated_tail_once(h, fs, f0, dur=TAIL_DURATION, ramp=0.005, drop_db=40.0,
                     phase=0.0, observation=TAIL_OBSERVATION):
    """Settling time after note-off; phase is explicitly set at the gate end.

    Full linear convolution preserves all pre/post-peak samples. Exact leading
    zeros are an irrelevant pure delay and trailing zeros are removed to make
    the Hilbert record invariant to WAV padding. Zero guards isolate its edges.
    Observe at least two seconds and the entire FIR post-peak support, with a
    quiet hold interval afterward, so even later echoes cannot be skipped.
    """
    support = np.flatnonzero(h)
    if not len(support):
        return np.nan
    h = np.asarray(h[support[0]:support[-1] + 1])
    n = int(dur * fs)
    t = np.arange(n) / fs
    x = np.sin(2 * np.pi * f0 * (t - n / fs) + phase)
    r = max(1, int(ramp * fs))
    w = np.ones(n)
    w[:r] = 0.5 * (1 - np.cos(np.pi * np.arange(r) / r))
    w[-r:] = w[:r][::-1]
    delay = int(np.argmax(np.abs(h)))
    hold = int(np.ceil(max(0.05, 2 / f0) * fs))
    count = max(int(np.ceil(observation * fs)), len(h) - 1 - delay) + hold
    y = fftconvolve(x * w, h)
    off = n + delay
    guard = int(np.ceil(max(0.5, 10 / f0) * fs))
    # Pad after the full convolution, never truncate its physical output.
    padded = np.pad(y, (guard, max(0, off + count - len(y)) + guard))
    env = np.abs(hilbert(padded))[guard:guard + off + count]
    lo = max(0, off - int(0.30 * fs))
    ss = np.median(env[lo:max(lo + 1, off - int(0.02 * fs))])
    if not ss > 0:
        return np.nan
    return _settling_ms(env[off:], ss * 10 ** (-drop_db / 20), fs, hold)


def _tail_statistics(v):
    """Preserve right-censored observations in order statistics."""
    v = np.asarray(v)
    v = np.where(np.isfinite(v), v, np.inf)
    ordered = np.sort(v)
    # Nearest-rank quartiles avoid undefined inf-inf interpolation.
    q1 = ordered[int(np.ceil(0.25 * len(v))) - 1]
    q3 = ordered[int(np.ceil(0.75 * len(v))) - 1]
    iqr = float(q3 - q1) if np.isfinite(q3) else np.inf
    return float(np.median(ordered)), iqr, int(np.isinf(v).sum())


def gated_tail(h, fs, f0, spread=False, details=False, **kw):
    """Median over nine gate phases; details also returns censored-trial count."""
    v = [_gated_tail_once(h, fs, f0, phase=p, **kw) for p in TAIL_PHASES]
    med, iqr, censored = _tail_statistics(v)
    if details:
        return med, iqr, censored
    if not spread:
        return med
    return med, iqr


def tail_limit(f0, control):
    """Longest tail allowed at f0 given the analysis floor measured there.

    A tail counts as real only once it clears the control, so the control is
    ADDED, never multiplied -- it is the noisiest quantity in the test and
    scaling it puts the verdict at the mercy of the floor rather than the
    filter.  See MAX_EXCESS_MS.

    The floor of four periods survives from revision 1: a 40 dB decay of a
    sinusoid cannot be resolved faster than a few cycles, so demanding less
    would measure the envelope estimator rather than the filter.  It binds
    only at the lowest tones, where the control is itself small.
    """
    return max(MAX_EXCESS_MS + control, 4000.0 / f0)


def check(path, verbose=True, fmax=FMAX, extra_tones=()):
    h, fs = read_wav(path)
    n = len(h)
    peak = int(np.argmax(np.abs(h)))
    hr = h
    pk = peak
    tot = float((hr ** 2).sum())
    pre = float((hr[:pk] ** 2).sum()) / tot * 100 if tot else np.nan

    # Control: a pure delay. The estimator factors out exact leading silence
    # for both signals and adds Hilbert guards; the control estimates the
    # analysis floor, but does not cancel arbitrary filter-dependent artefacts.
    delta = np.zeros(n)
    delta[pk] = 1.0

    if not 20 < fmax < fs / 2:
        raise ValueError('fmax must be above 20 Hz and below Nyquist')
    tones = sorted(set([t for t in TONES if t <= fmax] + list(extra_tones)))
    if any(not np.isfinite(t) or not 0 < t < fs / 2 for t in tones):
        raise ValueError('Tone frequencies must be positive and below Nyquist')
    f0, bw_hz, bw_bins, q = narrowest_feature(hr, fs, fmax=fmax)
    gd_f, gd_ms = group_delay_excursion(hr, fs, fmax=fmax)
    tails, censored = [], {}
    for t in tones:
        med, iqr, count = gated_tail(hr, fs, t, details=True)
        control = gated_tail(delta, fs, t)
        tails.append((t, med, iqr, control))
        censored[t] = count

    def limit(t, c):
        return tail_limit(t, c)

    def failed(v, c, t):
        return (not np.isfinite(v)) or (not np.isfinite(c)) or v > limit(t, c)

    # "Worst" is the tone that misses its own limit by the most, not the one
    # with the longest tail: the limits differ per tone, so the longest tail is
    # often merely the lowest tone, where the analysis floor is widest.
    real = [(t, v, s, c) for t, v, s, c in tails if failed(v, c, t)]
    worst = max(real, key=lambda r: np.inf if not np.isfinite(r[1])
                else r[1] - limit(r[0], r[3])) if real else None

    p1 = q <= MAX_Q
    p2 = abs(gd_ms) <= MAX_GD_MS
    p3 = worst is None
    ok = p1 and p2 and p3

    if verbose:
        print("=" * 72)
        print("%s" % path)
        print('  Tail estimator v2: sustained settling over 9 gate phases, judged as')
        print('  control + %.0f ms.  Build-quality heuristic, not an audibility limit.'
              % MAX_EXCESS_MS)
        print("  %d taps @ %d Hz = %.0f ms   peak at %d (%.1f ms latency)"
              % (n, fs, n / fs * 1e3, peak, peak / fs * 1e3))
        print("  FFT bin = %.4f Hz    pre-peak energy %.2f %%" % (fs / n, pre))
        if f0 is None:
            print("  PASS sharpest feature < %g Hz  : none (no peak/notch > 1.5 dB)"
                  % fmax)
        else:
            print("  %-4s sharpest feature < %g Hz  : Q %.1f  (%.2f Hz wide at "
                  "%.2f Hz, %.1f bins)"
                  % ("PASS" if p1 else "FAIL", fmax, q, bw_hz, f0, bw_bins))
        print("       threshold Q <= %.0f   (bins are length-dependent, "
              "reported for reference only)" % MAX_Q)
        print("  %-4s group delay 20-%g Hz     : %+.1f ms at %.2f Hz"
              % ("PASS" if p2 else "FAIL", fmax, gd_ms, gd_f))
        print("       threshold <= %.0f ms" % MAX_GD_MS)
        if p3:
            worst_txt = "all within limits"
        elif not np.isfinite(worst[1]):
            worst_txt = "did not settle within observation (at least 2 s) at %g Hz" % worst[0]
        else:
            worst_txt = "%.0f ms at %g Hz, %+.0f ms past its limit" \
                % (worst[1], worst[0], worst[1] - limit(worst[0], worst[3]))
        print("  %-4s gated-tone tails         : %s"
              % ("PASS" if p3 else "FAIL", worst_txt))
        print("       %-9s %9s %7s %9s %9s %9s"
              % ("tone", "tail", "spread", "control", "excess", "allowed"))
        for t, v, s, c in tails:
            flag = "  <-- FAIL" if failed(v, c, t) else ""
            if np.isfinite(v) and np.isfinite(s) and s > max(0.5 * v, 25.0):
                flag += "  (noisy)" if flag else "  <-- noisy"
            if censored[t]:
                flag += '  [%d/9 trials did not settle]' % censored[t]
            shown = "%9s" % ("unsettled" if not np.isfinite(v) else "%.0f" % v)
            spread = "%7s" % ("n/a" if not np.isfinite(s) else "%.0f" % s)
            excess = "%9s" % ("unsettled" if not np.isfinite(v) else "%+.0f" % (v - c))
            print("       %6.1f Hz %s %s %8.0f %s %8.0f%s"
                  % (t, shown, spread, c, excess, limit(t, c) - c, flag))
        print("       All ms.  tail = median over %d gate phases; spread = nearest-rank"
              % len(TAIL_PHASES))
        print("       IQR.  excess = tail - control, the quantity judged; a filter that")
        print("       adds no ringing of its own scores 0.  allowed = %.0f ms, widened at"
              % MAX_EXCESS_MS)
        print("       the lowest tones to the four-period resolution floor.")
        print('       Censored trials remain in statistics; noisy flags do not override the verdict.')
        print("  RESULT: %s" % ("PASS" if ok else "FAIL"))
    return ok, dict(path=path, h=hr, fs=fs, tails=tails, censored=censored, fmax=fmax,
                   estimator_version=2)


def make_plot(results, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(2, 1, figsize=(11, 8))
    for r in results:
        h, fs = r["h"], r["fs"]
        f, spectrum = analysis_spectrum(h, fs)
        spl = 20 * np.log10(np.abs(spectrum) + 1e-30)
        gd = -np.gradient(np.unwrap(np.angle(spectrum)),
                          2 * np.pi * (f[1] - f[0])) * 1e3
        ref = np.median(gd[(f >= 200) & (f <= 400)])
        m = (f >= 20) & (f <= r['fmax'])
        lab = r["path"].split("/")[-1]
        ax[0].semilogx(f[m], spl[m], lw=1.0, label=lab)
        ax[1].semilogx(f[m], gd[m] - ref, lw=1.0, label=lab)
    ax[0].set_ylabel("gain (dB)")
    fmax = max(r['fmax'] for r in results)
    ax[0].set_title("filter magnitude, 20-%g Hz" % fmax)
    ax[1].set_ylabel("group delay re 200-400 Hz (ms)")
    ax[1].set_xlabel("Hz")
    ax[1].set_title("group delay -- the fast failure test")
    for a in ax:
        a.grid(alpha=0.3, which="both")
        a.legend(fontsize=8)
    ax[1].axhline(MAX_GD_MS, color="r", ls=":", lw=1)
    ax[1].axhline(-MAX_GD_MS, color="r", ls=":", lw=1)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    print("\nwrote %s" % out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav", nargs="+", help="filter WAV(s) to test")
    ap.add_argument("--plot", metavar="PNG", help="also write a magnitude/group-delay plot")
    ap.add_argument('--fmax', type=float, default=FMAX,
                    help='upper bound of sharpness/group-delay checks (default: 200 Hz)')
    ap.add_argument('--tone', type=float, action='append', default=[],
                    help='additional gated-tone frequency in Hz; repeat for multiple tones')
    a = ap.parse_args()

    allok, results = True, []
    for p in a.wav:
        try:
            ok, r = check(p, fmax=a.fmax, extra_tones=a.tone)
        except Exception as e:                      # noqa: BLE001
            print("%s: ERROR %s" % (p, e), file=sys.stderr)
            allok = False
            continue
        allok &= ok
        results.append(r)
    if a.plot and results:
        make_plot(results, a.plot)
    print("\n%s" % ("ALL PASS" if allok else "FAILURES PRESENT"))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
