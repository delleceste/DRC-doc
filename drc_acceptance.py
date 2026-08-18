#!/usr/bin/env python3
"""
drc_acceptance.py -- acceptance tests for a DRC correction filter.

Run this on the WAV that BruteFIR will actually load, before deploying it.
It answers one question: will this filter keep the woofers moving after the
music stops?  See NOTES.md section 21.

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

     The tail is the MEDIAN over nine tone lengths, and the spread column
     is their interquartile range.  A single length is not reproducible:
     the gate closes at an arbitrary phase and the envelope of a low tone
     ripples at 2*f0, so the 40 dB crossing lands on either side of a lobe.
     Measured 2026-08-12 on an unchanged filter, 28.7 Hz returned anywhere
     from 80 to 225 ms depending on a 2 % change in tone length -- enough
     to fail a filter that passes.  Read `spread` before believing any
     single tail; entries flagged `noisy` are not evidence either way.

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
# f0/bandwidth is dimensionless and length-independent.  The threshold follows
# from section 8 of REW-INVERSION.md: an N-cycle FDW caps fractional bandwidth
# at 1/N, so a divisor windowed at 8-12 cycles cannot legitimately produce a
# feature sharper than about 12.  Calibrated against this project's history:
#
#   Sept 2025 deployed filter, 0.30 Hz at 28.9 Hz   -> 96   FAIL (1348 ms ring)
#   no-LF-tail notch,          0.23 Hz at 20.0 Hz   -> 87   FAIL
#   74 Hz SBIR shoulder,       5.78 Hz at 73.2 Hz   -> 13   marginal
#   20 Hz band-edge transition,9.37 Hz at 25.6 Hz   ->  3   pass
MAX_Q = 12.0
MIN_BINS = 30.0      # legacy, reported for reference only -- not a pass/fail
MAX_GD_MS = 10.0     # max group-delay excursion 20-200 Hz, ms
MAX_TAIL_MS = 100.0  # max gated-tone tail below 200 Hz, ms
FMAX = 200.0         # band over which the filter is judged

TONES = [28.7, 40.0, 51.2, 63.0, 79.0, 100.0, 116.5, 128.2, 145.5, 180.0]


def read_wav(path):
    """Minimal RIFF reader: PCM 16/24/32 and IEEE float 32/64, first channel."""
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
    if ch > 1:
        x = x.reshape(-1, ch)[:, 0]
    return x, fs


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
    n = len(h)
    f = np.fft.rfftfreq(n, 1 / fs)
    spl = 20 * np.log10(np.abs(np.fft.rfft(h)) + 1e-30)
    m = (f >= 15) & (f <= fmax)
    fb, sb = f[m], spl[m]
    df = fs / n
    best_f, best_bw, best_q = None, np.inf, 0.0
    for sign in (-1, 1):
        pk, _ = find_peaks(sign * sb, prominence=prominence)
        if not len(pk):
            continue
        w, _, _, _ = peak_widths(sign * sb, pk, rel_height=0.5)
        for i, k in enumerate(pk):
            bw = w[i] * (fb[1] - fb[0])
            if bw <= 0:
                continue
            q = fb[k] / bw
            if q > best_q:
                best_q, best_bw, best_f = q, bw, fb[k]
    if best_f is None:
        return None, np.inf, np.inf, 0.0
    return best_f, best_bw, best_bw / df, best_q


def group_delay_excursion(h, fs, fmax=FMAX):
    """Peak |group delay| over 20..fmax Hz, referenced to the 200-400 Hz level."""
    n = len(h)
    f = np.fft.rfftfreq(n, 1 / fs)
    gd = -np.gradient(np.unwrap(np.angle(np.fft.rfft(h))), 2 * np.pi * (fs / n)) * 1e3
    ref_band = (f >= 200) & (f <= 400)
    ref = np.median(gd[ref_band]) if ref_band.any() else 0.0
    m = (f >= 20) & (f <= fmax)
    g = gd[m] - ref
    k = int(np.argmax(np.abs(g)))
    return f[m][k], g[k]


def _gated_tail_once(h, fs, f0, dur=1.0, ramp=0.005, drop_db=40.0):
    """ms for the residual to fall drop_db below steady state after note-off."""
    n = int(dur * fs)
    t = np.arange(n) / fs
    x = np.sin(2 * np.pi * f0 * t)
    r = max(1, int(ramp * fs))
    w = np.ones(n)
    w[:r] = 0.5 * (1 - np.cos(np.pi * np.arange(r) / r))
    w[-r:] = w[:r][::-1]
    x = np.concatenate([x * w, np.zeros(int(2.0 * fs))])
    y = fftconvolve(x, h)[:len(x)]
    env = np.abs(hilbert(y))
    delay = int(np.argmax(np.abs(h)))
    off = n + delay
    if off >= len(env):
        return np.nan
    lo = max(0, off - int(0.30 * fs))
    ss = np.median(env[lo:max(lo + 1, off - int(0.02 * fs))])
    if not ss > 0:
        return np.nan
    idx = np.where(env[off:] < ss * 10 ** (-drop_db / 20))[0]
    return idx[0] / fs * 1e3 if len(idx) else np.nan


# Tone lengths the tail is measured over.  The gate closes at whatever phase
# the tone happens to be in, and the Hilbert envelope of a low-frequency
# sinusoid ripples at 2*f0, so a single length can land the 40 dB crossing on
# either side of a ripple lobe.  At 28.7 Hz that was worth 145 ms of swing on
# an unchanged filter -- enough to turn a passing filter into a failing one.
# Nine lengths spanning 1.33 periods at the lowest tone decorrelates it.
TAIL_DURS = (0.90, 0.93, 0.96, 1.00, 1.04, 1.08, 1.12, 1.16, 1.20)


def gated_tail(h, fs, f0, spread=False, **kw):
    """Median tail over TAIL_DURS.  With spread=True also return the IQR.

    A single measurement is not reproducible at the lowest tones -- see
    TAIL_DURS.  NaN (never decayed) is kept as +inf so it cannot be quietly
    averaged away by finite neighbours.
    """
    v = np.array([_gated_tail_once(h, fs, f0, dur=d, **kw) for d in TAIL_DURS])
    v = np.where(np.isfinite(v), v, np.inf)
    if np.isinf(v).sum() * 2 > len(v):      # mostly "never decayed"
        return (np.nan, np.inf) if spread else np.nan
    fin = v[np.isfinite(v)]
    med = float(np.median(fin))
    if not spread:
        return med
    return med, float(np.percentile(fin, 75) - np.percentile(fin, 25))


def check(path, verbose=True):
    h, fs = read_wav(path)
    n = len(h)
    peak = int(np.argmax(np.abs(h)))
    # roll the peak away from the wrap point so pre-ring is measurable
    hr = np.roll(h, n // 4 - peak)
    pk = n // 4
    tot = float((hr ** 2).sum())
    pre = float((hr[:pk] ** 2).sum()) / tot * 100 if tot else np.nan

    # Control: a pure delay of the SAME length and latency as the filter under
    # test, so gate alignment and Hilbert edge effects cancel exactly.  A bare
    # delta does not do this and false-fails long-latency all-pass filters.
    delta = np.zeros(n)
    delta[pk] = 1.0

    f0, bw_hz, bw_bins, q = narrowest_feature(hr, fs)
    gd_f, gd_ms = group_delay_excursion(hr, fs)
    tails = [(t,) + gated_tail(hr, fs, t, spread=True) + (gated_tail(delta, fs, t),)
             for t in TONES]

    # A tail counts as real only if it clears the control by a healthy margin.
    # NaN means it never decayed inside the analysis window -- the worst case,
    # not a missing value.
    # Floor of 4 periods: a 40 dB decay of a sinusoid cannot be resolved
    # faster than a few cycles, so demanding less is measuring the envelope
    # estimator, not the filter.  At 28.7 Hz that is 139 ms.
    def limit(t, c):
        return max(MAX_TAIL_MS, 3 * c, 4000.0 / t)

    def failed(v, c, t):
        return (not np.isfinite(v)) or v > limit(t, c)

    real = [(t, v, s, c) for t, v, s, c in tails if failed(v, c, t)]
    worst = max(real, key=lambda r: np.inf if not np.isfinite(r[1]) else r[1]) \
        if real else None

    p1 = q <= MAX_Q
    p2 = abs(gd_ms) <= MAX_GD_MS
    p3 = worst is None
    ok = p1 and p2 and p3

    if verbose:
        print("=" * 72)
        print("%s" % path)
        print("  %d taps @ %d Hz = %.0f ms   peak at %d (%.1f ms latency)"
              % (n, fs, n / fs * 1e3, peak, peak / fs * 1e3))
        print("  FFT bin = %.4f Hz    pre-peak energy %.2f %%" % (fs / n, pre))
        if f0 is None:
            print("  PASS sharpest feature < %g Hz  : none (no peak/notch > 1.5 dB)"
                  % FMAX)
        else:
            print("  %-4s sharpest feature < %g Hz  : Q %.1f  (%.2f Hz wide at "
                  "%.2f Hz, %.1f bins)"
                  % ("PASS" if p1 else "FAIL", FMAX, q, bw_hz, f0, bw_bins))
        print("       threshold Q <= %.0f   (bins are length-dependent, "
              "reported for reference only)" % MAX_Q)
        print("  %-4s group delay 20-%g Hz     : %+.1f ms at %.2f Hz"
              % ("PASS" if p2 else "FAIL", FMAX, gd_ms, gd_f))
        print("       threshold <= %.0f ms" % MAX_GD_MS)
        if p3:
            worst_txt = "all within limits"
        elif not np.isfinite(worst[1]):
            worst_txt = "still ringing after 2 s at %g Hz" % worst[0]
        else:
            worst_txt = "worst %.0f ms at %g Hz" % (worst[1], worst[0])
        print("  %-4s gated-tone tails         : %s"
              % ("PASS" if p3 else "FAIL", worst_txt))
        print("       %-9s %10s %8s %10s %10s"
              % ("tone", "tail", "spread", "control", "limit"))
        for t, v, s, c in tails:
            flag = "  <-- FAIL" if failed(v, c, t) else ""
            if np.isfinite(v) and np.isfinite(s) and s > max(0.5 * v, 25.0):
                flag += "  (noisy)" if flag else "  <-- noisy"
            shown = "  >2000" if not np.isfinite(v) else "%8.0f" % v
            spread = "   n/a" if not np.isfinite(s) else "%6.0f" % s
            print("       %6.1f Hz %s ms %s %8.0f ms %8.0f ms%s"
                  % (t, shown, spread, c, limit(t, c), flag))
        print("       tail = median over %d tone lengths; spread = IQR."
              % len(TAIL_DURS))
        print("  RESULT: %s" % ("PASS" if ok else "FAIL"))
    return ok, dict(path=path, h=hr, fs=fs, tails=tails)


def make_plot(results, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(2, 1, figsize=(11, 8))
    for r in results:
        h, fs = r["h"], r["fs"]
        n = len(h)
        f = np.fft.rfftfreq(n, 1 / fs)
        spl = 20 * np.log10(np.abs(np.fft.rfft(h)) + 1e-30)
        gd = -np.gradient(np.unwrap(np.angle(np.fft.rfft(h))),
                          2 * np.pi * (fs / n)) * 1e3
        ref = np.median(gd[(f >= 200) & (f <= 400)])
        m = (f >= 20) & (f <= FMAX)
        lab = r["path"].split("/")[-1]
        ax[0].semilogx(f[m], spl[m], lw=1.0, label=lab)
        ax[1].semilogx(f[m], gd[m] - ref, lw=1.0, label=lab)
    ax[0].set_ylabel("gain (dB)")
    ax[0].set_title("filter magnitude, 20-%g Hz" % FMAX)
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
    a = ap.parse_args()

    allok, results = True, []
    for p in a.wav:
        try:
            ok, r = check(p)
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
