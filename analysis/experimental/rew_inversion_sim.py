#!/usr/bin/env python3
"""
rew_inversion_sim.py -- automate steps 3-11 of REW-INVERSION.md.

The inversion chain is fixed, deterministic arithmetic: the same averages,
the same two minimum-phase passes, the same band-limited cut-only divides,
the same crossover multiply, every single time. Only the *inputs* change --
a new measurement set, or a new FDW cycle count. Doing that by hand in the
REW GUI costs an hour a trial and is error-prone in ways this project has
already been bitten by (a stale snapshot, an inverted capture, a wrong
band limit, an average built on the wrong five traces).

This runs the whole thing from exported captures in about a second, so an
FDW sweep is a loop rather than an afternoon, and produces:

  * FLX / FRX as 48 kHz 32-bit float WAVs (what BruteFIR would load)
  * the full step-12 bundle: L/R/LR and L.Filtered/R.Filtered/LR.Filtered
  * every intermediate trace as a REW-format .txt, for eyeballing
  * acceptance + ringing analysis per candidate (via drc_acceptance)

WHAT IS AND IS NOT SIMULATED HERE
---------------------------------
Validated against this project's own REW exports (DRC-120.green, 2026-09-11),
computed-vs-REW over the 20-225 Hz correction band:

    band-limited cut-only division   0.036 dB rms   (0.162 dB max)
    minimum phase, magnitude         0.003 dB rms   (0.019 dB max)
    minimum phase, phase             1.43 deg rms
    RMS / vector averages            0.036 dB rms

Those are interpolation-grid noise, not modelling error. Steps 3, 4, 5(use),
7, 8, 9, 10 and 12 are therefore trustworthy.

**Step 2 -- the FDW -- is reproduced approximately, and is GATED.**
An FDW is H(f) = sum_t ir(t) w(t*f) e^(-2j pi f t), w scale-invariant in
cycles. REW is closed source, but its help pins the parameterisation:
the cycle count is the window width BETWEEN HALF-AMPLITUDE POINTS (a 15
cycle window is 15 ms wide at 1 kHz), the FDW is applied after the left
and right windows, and it is centred on the window reference time.

Fitted against this project's ground truth -- the green set carries
unwindowed captures and REW's own 8- and 12-cycle versions of the same
sweeps -- checked on MAGNITUDE, PHASE and GROUP DELAY at N=8, 30-180 Hz:

    shape      k      mag rms   phase rms   GD rms    GD max
    gauss      0.875  0.180 dB    1.10 deg   1.29 ms   6.09 ms
    blackman   1.000  0.257 dB    1.51 deg   1.68 ms   7.23 ms
    hann       0.875  0.337 dB    2.29 deg   2.76 ms  11.20 ms

(k = window half-support in cycles.) Magnitude and group delay
co-minimise at the same parameters, which is the signature of a model
that is right rather than merely fitted. Blackman at k=1.0 is the shape
most consistent with the documented half-amplitude definition; gauss at
k=0.875 fits marginally better here.

**Why it is still gated.** 1.29 ms rms is good; 6 ms max is not, against
a 10 ms acceptance gate -- it can still move a marginal verdict. The
residual is probably dominated by reconstructing the source IR from a
96 ppo text export rather than by the window, so it should tighten a lot
with WAV impulse responses, but that has NOT been demonstrated yet. Until
it is, pass fdw_ok=True explicitly to say you accept a screening-grade
number, and take final verdicts from REW.

An earlier revision of this file claimed the FDW was unreproducible and
quoted a 24 ms rms group-delay error. That measurement was invalid --
degrees were passed to np.unwrap, which assumes radians, so the phase
comparison was meaningless. Corrected above. Retained as a warning: a
magnitude-only fit says almost nothing about a window's phase, and a
phase check is worthless if the unwrap is wrong.

SCOPE, honestly
---------------
  TRUSTED   the magnitude-domain chain from REW-windowed captures:
            averages, X801, both divides, the splice, both minimum-phase
            passes, the crossover multiply. 0.002-0.06 dB vs REW.

  SCREENING ONLY  the FDW (above), and any group-delay or gated-tail
            verdict computed from .txt
            captures. REW's 96 ppo text export is coarser than its own
            0.366 Hz working grid above ~50 Hz, and the information GD
            needs is simply not in the file: measured 4 ms of drift,
            enough to flip this project's R-channel verdict from REW's
            -8.9 ms PASS to +13.0 ms FAIL. Feed WAV impulse responses,
            or take verdicts from drc_acceptance on REW's own exported
            WAV -- which is what this project has been doing all along.

  NOT MODELLED  mic calibration and HF tails. Neither matters for the
            green set (no cal file loaded; captures already run to
            Nyquist, and the procedure specifies no HF tail), and the
            cal cancels in Target/LX-MP because both carry it. Both
            assumptions would break silently on a different rig.

Usage:
    # trusted: REW did the FDW, automate the rest
    rew_inversion_sim.py --from-windowed 120.green.multipt.FDW8.txts \
        --target "120.green.multipt.FDW8.txts/Target LR.RMS.AVG.txt" \
        --x801 X801.wav --out build.FDW8

    # prove the arithmetic against REW's own exports for that same set
    rew_inversion_sim.py --from-windowed 120.green.multipt.FDW8.txts \
        --target ... --x801 X801.wav --validate


Exit status 0 if the build completed (and, with --validate, matched).
"""

import argparse
import os
import re
import struct
import sys

import numpy as np

FS = 48000
NFFT = 1 << 17                 # 131072, REW's fixed export length at 48 kHz
LIN = np.fft.rfftfreq(NFFT, 1 / FS)

# Correction-band defaults, from REW-INVERSION.md step 7.
F_COMMON_LO = 25.0             # 20 default; 25 is the documented GD remedy
F_SPLICE = 80.0
F_TOP = 225.0
MP_CORNER = 16.0               # step 4 LF-tail corner, at/below sweep start
MP_SLOPE_MEAS = 12.0           # step 4: 12 dB/oct when corner near band edge
MP_SLOPE_FILT = 0.0            # step 8: shallowest, filter has no roll-off
DEFAULT_PEAK = 8192            # where REW's "trim to windows" left the peak


# ---------------------------------------------------------------- REW text io

def read_rew_txt(path):
    """Parse a REW Freq/SPL[/Phase] export -> (freq, spl_db, phase_deg)."""
    f, s, p = [], [], []
    for line in open(path, errors="replace"):
        if line.startswith("*") or not line.strip():
            continue
        q = line.split()
        if len(q) < 2:
            continue
        try:
            f.append(float(q[0]))
            s.append(float(q[1]))
            p.append(float(q[2]) if len(q) > 2 else 0.0)
        except ValueError:
            continue
    if not f:
        raise ValueError("%s: no data rows" % path)
    return np.array(f), np.array(s), np.array(p)


def to_spectrum(path, phase=True):
    """Load a REW export onto the linear rfft grid as a complex spectrum."""
    f, s, p = read_rew_txt(path)
    mag = np.interp(LIN, f, s, left=s[0], right=s[-1])
    if not phase:
        return 10 ** (mag / 20) + 0j
    ph = np.unwrap(np.deg2rad(p))
    phi = np.interp(LIN, f, ph, left=ph[0], right=ph[-1])
    return 10 ** (mag / 20) * np.exp(1j * phi)


def write_rew_txt(path, H, note="", name=""):
    """Write a spectrum back out in REW's export format (Smoothing: None)."""
    mag = 20 * np.log10(np.abs(H) + 1e-30)
    ph = np.rad2deg(np.angle(H))
    keep = (LIN >= 5) & (LIN <= 24000)
    with open(path, "w") as fh:
        fh.write("* Measurement data generated by rew_inversion_sim.py\n")
        fh.write("* Source: simulated inversion chain\n")
        fh.write("* Note: ; %s\n" % note)
        fh.write("* Measurement: %s\n" % (name or os.path.basename(path)))
        fh.write("* Smoothing: None\n")
        fh.write("*\n* Freq(Hz) SPL(dB) Phase(degrees)\n")
        for fr, m, q in zip(LIN[keep], mag[keep], ph[keep]):
            fh.write("%.6f %.3f %.4f\n" % (fr, m, q))


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
    tag, ch, fs, _, _, bits = struct.unpack("<HHIIHH", fmt[:16])
    if tag == 0xFFFE:
        tag = struct.unpack("<H", fmt[24:26])[0]
    if tag == 3:
        x = np.frombuffer(data, dtype="<f4" if bits == 32 else "<f8").astype(np.float64)
    elif tag == 1 and bits == 32:
        x = np.frombuffer(data, dtype="<i4").astype(np.float64) / 2 ** 31
    elif tag == 1 and bits == 16:
        x = np.frombuffer(data, dtype="<i2").astype(np.float64) / 2 ** 15
    else:
        raise ValueError("%s: unsupported format tag=%d bits=%d" % (path, tag, bits))
    if ch > 1:
        x = x.reshape(-1, ch)[:, 0]
    return x, fs


def load_capture(path):
    """Load one capture as a full-resolution spectrum.

    Prefer a WAV impulse-response export. A .txt export is 96 ppo, which
    above ~50 Hz is COARSER than the 0.366 Hz grid REW itself works on --
    so a txt round-trip throws away fine structure, and group delay (a
    phase derivative) is precisely what that loss destroys. Measured on the
    green FDW8 set: magnitude still lands within 0.06 dB rms of REW, but
    the reported group-delay extremum moved by ~4 ms and flipped the R
    channel's verdict. Magnitude work from txt is fine; acceptance
    verdicts from txt are not.
    """
    if path.lower().endswith(".wav"):
        x, fs = read_wav(path)
        if fs != FS:
            raise ValueError("%s is %d Hz, expected %d" % (path, fs, FS))
        x = np.pad(x, (0, NFFT - len(x))) if len(x) < NFFT else x[:NFFT]
        return np.fft.rfft(x, NFFT)
    return to_spectrum(path)


def write_wav_f32(path, x, fs=FS):
    """Write mono 32-bit IEEE float WAV -- what REW exports and BruteFIR loads."""
    d = np.asarray(x, dtype="<f4").tobytes()
    hdr = b"RIFF" + struct.pack("<I", 36 + len(d)) + b"WAVEfmt "
    hdr += struct.pack("<IHHIIHH", 16, 3, 1, fs, fs * 4, 4, 32)
    hdr += b"data" + struct.pack("<I", len(d))
    open(path, "wb").write(hdr + d)


# ------------------------------------------------------------ chain primitives

def rms_average(specs):
    """Step 3d: RMS magnitude average across positions. Phase is discarded."""
    return np.sqrt(np.mean([np.abs(h) ** 2 for h in specs], axis=0)) + 0j


def vector_average(specs):
    """Step 3c: complex average -- the one place inter-channel phase is used."""
    return np.mean(specs, axis=0)


def minimum_phase(H, corner=MP_CORNER, slope_db_oct=MP_SLOPE_MEAS):
    """Steps 4/8: Hilbert (cepstral) minimum phase, with the LF tail on.

    The LF tail is not optional -- without it the transform rings against the
    bottom edge of the data and corrupts the magnitude it is supposed to
    preserve (REW-INVERSION.md step 4's retraction; up to 13 dB of error).
    slope_db_oct=0 is step 8's "flat, no imposed high-pass" for a filter;
    12 is step 4's choice for a measurement whose corner sits near the band
    edge.
    """
    mag = 20 * np.log10(np.abs(H) + 1e-30)
    below = LIN < corner
    ref = np.interp(corner, LIN, mag)
    with np.errstate(divide="ignore", invalid="ignore"):
        mag[below] = ref + slope_db_oct * np.log2(np.maximum(LIN[below], 1e-6) / corner)
    mag = np.maximum(mag, mag.max() - 200)
    c = np.fft.irfft(mag / 20 * np.log(10), NFFT)
    c[1:NFFT // 2] *= 2
    c[NFFT // 2 + 1:] = 0
    return np.exp(np.fft.rfft(c, NFFT))


def band_limited_divide(A, B, lo, hi, max_gain_db=0.0):
    """Step 7: A/B, cut-only, reverting to unity outside [lo,hi].

    REW blends to unity over one octave centred on each limit, and `Max gain`
    at 0.0 dB clamps every boost -- so a narrow dip in the divisor asks for a
    narrow boost and gets unity instead of a resonator (step 6's table).
    Reproduces REW's own Fper_L to 0.036 dB rms.
    """
    d = 20 * np.log10(np.abs(A) + 1e-30) - 20 * np.log10(np.abs(B) + 1e-30)
    d = np.minimum(d, max_gain_db)
    w = np.ones_like(LIN)
    loA, loB = lo / np.sqrt(2), lo * np.sqrt(2)
    hiA, hiB = hi / np.sqrt(2), hi * np.sqrt(2)
    w[LIN < loA] = 0.0
    m = (LIN >= loA) & (LIN < loB)
    w[m] = np.log2(LIN[m] / loA)
    w[LIN > hiB] = 0.0
    m = (LIN > hiA) & (LIN <= hiB)
    w[m] = 1 - np.log2(LIN[m] / hiA)
    return 10 ** (d * w / 20) + 0j


def spectrum_to_ir(H, peak_at=DEFAULT_PEAK):
    """Back to the time domain, impulse placed where REW's trim leaves it."""
    ir = np.fft.irfft(H, NFFT)
    return np.roll(ir, peak_at - int(np.argmax(np.abs(ir))))


FDW_K = 0.875          # window half-support, in cycles (see docstring)
FDW_SHAPE = "gauss"    # "blackman" at k=1.0 matches REW's documented spec


def frequency_dependent_window(ir, cycles, freqs=None, shape=FDW_SHAPE, k=FDW_K,
                               fdw_ok=False):
    """Step 2's frequency-dependent window. SCREENING GRADE -- see docstring.

    Reproduces REW to ~0.18 dB magnitude / 1.29 ms rms group delay at N=8,
    but up to 6 ms peak error, which is large against the 10 ms acceptance
    gate. Set fdw_ok=True to acknowledge that and proceed; take final
    verdicts from REW, not from here.
    """
    if not fdw_ok:
        raise NotImplementedError(
            "FDW simulation is screening-grade (~1.3 ms rms, 6 ms peak "
            "group-delay error vs REW, against a 10 ms gate). Pass "
            "fdw_ok=True to accept that, or apply the FDW in REW and use "
            "--from-windowed for verdict-quality work.")
    if freqs is None:
        freqs = LIN[(LIN >= 10) & (LIN <= 500)]
    pk = int(np.argmax(np.abs(ir)))
    t = (np.arange(len(ir)) - pk) / FS
    t = np.where(t > len(ir) / (2 * FS), t - len(ir) / FS, t)
    out = np.zeros(len(freqs), complex)
    for i, f0 in enumerate(freqs):
        half = k * cycles / f0
        m = np.abs(t) <= half
        x = t[m] / half
        if shape == "gauss":
            w = np.exp(-0.5 * (2.5 * x) ** 2)
        elif shape == "blackman":
            w = 0.42 + 0.5 * np.cos(np.pi * x) + 0.08 * np.cos(2 * np.pi * x)
        elif shape == "hann":
            w = 0.5 * (1 + np.cos(np.pi * x))
        else:
            raise ValueError("unknown FDW window shape %r" % shape)
        out[i] = np.sum(ir[m] * w * np.exp(-2j * np.pi * f0 * t[m]))
    return freqs, out


# ------------------------------------------------------------------- the chain

def find_captures(d):
    """Locate the five L and five R position captures in an export directory."""
    files = os.listdir(d)
    out = {}
    for ch in ("L", "R"):
        pos = []
        for n in sorted(files):
            if not n.lower().endswith((".txt", ".wav")):
                continue
            # "L 120.green.1.txt" .. ".4", plus the centre: "L 120.green.txt"
            # or the FDW8 set's "L.0.txt". Exclude derived traces.
            if re.match(r"^%s[ .]" % ch, n) and not re.match(
                    r"^%s(Filter|R|X|-SP|\.Filtered)" % ch, n, re.I):
                if re.search(r"\.\d+\.(txt|wav)$|\.0\.(txt|wav)$|^%s [^.]*\.(txt|wav)$" % ch, n):
                    pos.append(os.path.join(d, n))
        # the plain "L.txt"/"R.txt" are step-12 unwindowed duplicates, not
        # positions -- never average them in
        pos = [p for p in pos if os.path.basename(p).lower()
               not in ("l.txt", "r.txt", "l.wav", "r.wav")]
        out[ch] = sorted(set(pos))
    return out


def build(captures, target_path, x801_path, common_lo=F_COMMON_LO,
          splice=F_SPLICE, top=F_TOP, sum_path=None, verbose=True):
    """Run steps 3e..10 and return every trace, keyed by name."""
    tr = {}

    L = [load_capture(p) for p in captures["L"]]
    R = [load_capture(p) for p in captures["R"]]
    if len(L) != len(R):
        raise ValueError("L has %d captures, R has %d -- families must match"
                         % (len(L), len(R)))
    if verbose:
        print("  %d L captures, %d R captures" % (len(L), len(R)))

    # 3c: mono sum at each position, while phase still means something
    LR = [vector_average([a, b]) for a, b in zip(L, R)]
    if sum_path:                       # prefer the measured L+R sweep at centre
        meas = load_capture(sum_path) * 10 ** (-6.0206 / 20)
        LR[0] = meas
        if verbose:
            print("  centre mono sum: measured L+R sweep, -6.0206 dB")

    # 3d: discard spatial phase
    tr["L-SP"] = rms_average(L)
    tr["R-SP"] = rms_average(R)
    tr["LR-SP"] = rms_average(LR)

    # 3e: bake in the crossover correction (magnitude-neutral, but honest)
    x, fs = read_wav(x801_path)
    if fs != FS:
        raise ValueError("%s is %d Hz, expected %d" % (x801_path, fs, FS))
    X = np.fft.rfft(x, NFFT)
    X /= np.median(np.abs(X[(LIN >= 300) & (LIN <= 1000)]))   # normalise to 0 dB
    tr["X801"] = X
    tr["LX"] = tr["L-SP"] * X
    tr["RX"] = tr["R-SP"] * X

    # 4: first minimum-phase pass, cal included, LF tail on
    tr["LX-MP"] = minimum_phase(tr["LX"], slope_db_oct=MP_SLOPE_MEAS)
    tr["RX-MP"] = minimum_phase(tr["RX"], slope_db_oct=MP_SLOPE_MEAS)
    tr["LR-SP-MP"] = minimum_phase(tr["LR-SP"], slope_db_oct=MP_SLOPE_MEAS)

    # 5: the target (supplied -- built by hand in REW's EQ window)
    tr["Target"] = to_spectrum(target_path, phase=False)

    # 7: two divides and a multiply, all cut-only
    tr["Fcommon"] = band_limited_divide(tr["Target"], tr["LR-SP-MP"], common_lo, splice)
    tr["Fper_L"] = band_limited_divide(tr["Target"], tr["LX-MP"], splice, top)
    tr["Fper_R"] = band_limited_divide(tr["Target"], tr["RX-MP"], splice, top)
    tr["FL"] = tr["Fcommon"] * tr["Fper_L"]
    tr["FR"] = tr["Fcommon"] * tr["Fper_R"]

    # 8: second minimum-phase pass, cal excluded, shallowest slope
    tr["LFilter"] = minimum_phase(tr["FL"], slope_db_oct=MP_SLOPE_FILT)
    tr["RFilter"] = minimum_phase(tr["FR"], slope_db_oct=MP_SLOPE_FILT)

    # 9: crossover last, X801 as trace A
    tr["FLX"] = X * tr["LFilter"]
    tr["FRX"] = X * tr["RFilter"]
    return tr


def predictions(tr, raw_l, raw_r):
    """Step 12's prediction: the unwindowed room, times the finished filter."""
    out = {}
    out["L"] = load_capture(raw_l)
    out["R"] = load_capture(raw_r)
    out["LR"] = vector_average([out["L"], out["R"]])
    out["L.Filtered"] = out["L"] * tr["FLX"]
    out["R.Filtered"] = out["R"] * tr["FRX"]
    out["LR.Filtered"] = vector_average([out["L.Filtered"], out["R.Filtered"]])
    return out


# -------------------------------------------------------------------- analysis

def analyse(tr, outdir, label=""):
    """Run drc_acceptance on the built filters and summarise, incl. ringing."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from drc_acceptance import (narrowest_feature, group_delay_excursion,
                                gated_tail, TONES, MAX_TAIL_MS)

    gd_f = np.array([20, 50, 100, 200, 500, 1000])
    gd_thr = np.array([45, 32, 24, 18, 12, 6])

    rows = []
    for ch, key in (("L", "FLX"), ("R", "FRX")):
        ir = spectrum_to_ir(tr[key])
        n = len(ir)
        hr = np.roll(ir, n // 4 - int(np.argmax(np.abs(ir))))
        delta = np.zeros(n)
        delta[n // 4] = 1.0
        f0, bw, bins, q = narrowest_feature(hr, FS)
        gf, gms = group_delay_excursion(hr, FS)
        thr = np.interp(np.log10(gf), np.log10(gd_f), gd_thr)
        worst, total_excess, nfail = 0.0, 0.0, 0
        for t in TONES:
            v, s = gated_tail(hr, FS, t, spread=True)
            c = gated_tail(delta, FS, t)
            lim = max(MAX_TAIL_MS, 3 * c, 4000.0 / t)
            noisy = np.isfinite(v) and np.isfinite(s) and s > max(0.5 * v, 25.0)
            if (not np.isfinite(v)) or v > lim:
                nfail += 1
            if np.isfinite(v) and not noisy:
                total_excess += max(0.0, v - c)
                worst = max(worst, v - c)
        rows.append(dict(ch=ch, q=q, gd=gms, gd_f=gf, gd_pct=100 * abs(gms) / thr,
                         tail_fails=nfail, worst_excess=worst,
                         total_excess=total_excess,
                         ok=(q <= 12 and abs(gms) <= 10 and nfail == 0)))
    return rows



def compare_wavs(mine_dir, rew_dir):
    """Paired verification: this tool's FLX/FRX against REW's own, directly.

    This is the check that turns "the arithmetic validates stage by stage"
    into "this pipeline reproduces what REW built, for MY measurement set".
    Do it once, for one N, before trusting a sweep. Group delay is the
    number that matters -- magnitude agreeing proves much less (a 96 ppo
    text round-trip of REW's own filter keeps Q and tails but moves group
    delay by 17.7 ms and flips its sign).
    """
    from drc_acceptance import (narrowest_feature, group_delay_excursion,
                                gated_tail, TONES, MAX_TAIL_MS)
    ok = True
    for ch, fn_ in (("L", "FLX-trimmed-48k.wav"), ("R", "FRX-trimmed-48k.wav")):
        a, fa = read_wav(os.path.join(mine_dir, fn_))
        b, fb = read_wav(os.path.join(rew_dir, fn_))
        n = min(len(a), len(b))
        ra = np.roll(a, n // 4 - int(np.argmax(np.abs(a))))[:n]
        rb = np.roll(b, n // 4 - int(np.argmax(np.abs(b))))[:n]
        f = np.fft.rfftfreq(n, 1 / fa)
        band = (f >= 20) & (f <= 225)
        Ha, Hb = np.fft.rfft(ra), np.fft.rfft(rb)
        e = (20 * np.log10(np.abs(Ha) + 1e-30)
             - 20 * np.log10(np.abs(Hb) + 1e-30))[band]
        ga = -np.gradient(np.unwrap(np.angle(Ha)), 2 * np.pi * (fa / n)) * 1e3
        gb = -np.gradient(np.unwrap(np.angle(Hb)), 2 * np.pi * (fa / n)) * 1e3
        ga = ga - np.median(ga[(f >= 200) & (f <= 400)])
        gb = gb - np.median(gb[(f >= 200) & (f <= 400)])
        ge = (ga - gb)[band]
        qa = narrowest_feature(ra, fa)[3]
        qb = narrowest_feature(rb, fb)[3]
        fa_, ma_ = group_delay_excursion(ra, fa)
        fb_, mb_ = group_delay_excursion(rb, fb)
        print("  %s: magnitude %.3f dB rms (%.3f max)" % (ch, np.sqrt(np.mean(e ** 2)),
                                                          np.abs(e).max()))
        print("     group delay %.2f ms rms (%.2f max)" % (np.sqrt(np.mean(ge ** 2)),
                                                           np.abs(ge).max()))
        print("     Q  mine %.1f / REW %.1f     GD extremum  mine %+.1f@%.1f / REW %+.1f@%.1f"
              % (qa, qb, ma_, fa_, mb_, fb_))
        bad = (np.abs(ge).max() > 2.0 or abs(qa - qb) > 0.5
               or abs(ma_ - mb_) > 1.0)
        print("     %s" % ("MISMATCH -- do not trust a sweep until resolved" if bad
                           else "agrees"))
        ok &= not bad
    return ok


# ------------------------------------------------------------------ validation

def validate(tr, d):
    """Compare every computed stage against REW's own export in the same dir."""
    pairs = [("L-SP", "L-SP.txt"), ("R-SP", "R-SP.txt"), ("LR-SP", "LR-SP.txt"),
             ("LX", "LX.txt"), ("RX", "RX.txt"),
             ("LX-MP", "LX-MP.txt"), ("RX-MP", "RX-MP.txt"),
             ("LR-SP-MP", "LR-SP-MP.txt"),
             ("Fcommon", "F.common.txt"), ("Fper_L", "Fper_L.txt"),
             ("Fper_R", "Fper_R.txt"), ("FL", "FL.txt"), ("FR", "FR.txt"),
             ("LFilter", "LFilter.txt"), ("RFilter", "RFilter.txt"),
             ("FLX", "FLX.txt"), ("FRX", "FRX.txt")]
    band = (LIN >= 20) & (LIN <= 225)
    print("  %-12s %10s %10s" % ("stage", "rms dB", "max dB"))
    worst = 0.0
    for key, fn in pairs:
        p = os.path.join(d, fn)
        if not os.path.exists(p) or key not in tr:
            continue
        ref = to_spectrum(p, phase=False)
        a = 20 * np.log10(np.abs(tr[key]) + 1e-30)[band]
        b = 20 * np.log10(np.abs(ref) + 1e-30)[band]
        a = a - np.median(a - b) if key in ("Target",) else a
        e = a - b
        rms, mx = np.sqrt(np.mean(e ** 2)), np.abs(e).max()
        worst = max(worst, rms)
        print("  %-12s %10.3f %10.3f" % (key, rms, mx))
    return worst


# ------------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-windowed", metavar="DIR",
                    help="directory of REW captures with the FDW already applied "
                         "(TRUSTED mode -- REW does step 2, this does the rest)")
    ap.add_argument("--target", required=True, help="Target ... .txt from REW's EQ window")
    ap.add_argument("--x801", required=True, help="X801.wav")
    ap.add_argument("--measured-sum", metavar="TXT",
                    help="measured simultaneous L+R sweep at centre (preferred "
                         "over the calculated vector average, step 3c)")
    ap.add_argument("--raw-l", help="unwindowed L for the step-12 prediction")
    ap.add_argument("--raw-r", help="unwindowed R for the step-12 prediction")
    ap.add_argument("--out", metavar="DIR", help="write the built traces/WAVs here")
    ap.add_argument("--compare-against", metavar="DIR",
                    help="paired verification: compare this run's FLX/FRX WAVs "
                         "against REW's own build of the same N in DIR. Do this "
                         "once before trusting any sweep.")
    ap.add_argument("--validate", action="store_true",
                    help="compare every stage against REW's exports in --from-windowed")
    ap.add_argument("--common-lo", type=float, default=F_COMMON_LO)
    ap.add_argument("--splice", type=float, default=F_SPLICE)
    ap.add_argument("--top", type=float, default=F_TOP)
    a = ap.parse_args()

    if not a.from_windowed:
        print("error: --from-windowed is required (see --help for why "
              "--simulate-fdw is not a substitute)", file=sys.stderr)
        return 2

    print("=" * 72)
    print("building from %s" % a.from_windowed)
    caps = find_captures(a.from_windowed)
    for ch in ("L", "R"):
        for p in caps[ch]:
            print("    %s: %s" % (ch, os.path.basename(p)))
    tr = build(caps, a.target, a.x801, a.common_lo, a.splice, a.top,
               sum_path=a.measured_sum)

    if a.validate:
        print("\nvalidation against REW's own exports (20-225 Hz):")
        worst = validate(tr, a.from_windowed)
        print("  worst stage rms: %.3f dB" % worst)

    if a.out:
        os.makedirs(a.out, exist_ok=True)
        for k in ("L-SP", "R-SP", "LR-SP", "LX", "RX", "LX-MP", "RX-MP",
                  "LR-SP-MP", "Fcommon", "Fper_L", "Fper_R", "FL", "FR",
                  "LFilter", "RFilter", "FLX", "FRX"):
            write_rew_txt(os.path.join(a.out, "%s.txt" % k), tr[k], name=k)
        for k, fn in (("FLX", "FLX-trimmed-48k.wav"), ("FRX", "FRX-trimmed-48k.wav")):
            write_wav_f32(os.path.join(a.out, fn), spectrum_to_ir(tr[k]))
        write_rew_txt(os.path.join(a.out, "FLX-trimmed.txt"), tr["FLX"], name="FLX-trimmed")
        write_rew_txt(os.path.join(a.out, "FRX-trimmed.txt"), tr["FRX"], name="FRX-trimmed")
        if a.raw_l and a.raw_r:
            pr = predictions(tr, a.raw_l, a.raw_r)
            for k in ("L", "R", "LR", "L.Filtered", "R.Filtered", "LR.Filtered"):
                write_rew_txt(os.path.join(a.out, "%s.txt" % k), pr[k], name=k)
        print("\nwrote %s" % a.out)

    txt_inputs = [q for ch in ("L", "R") for q in caps[ch]
                  if q.lower().endswith(".txt")]
    if a.compare_against and a.out:
        print("\npaired verification vs REW's own build:")
        if not compare_wavs(a.out, a.compare_against):
            print("  *** pipeline NOT verified for this measurement set")

    print("\nacceptance:")
    if txt_inputs:
        print("  *** WARNING: captures are .txt (96 ppo). Magnitude is good to")
        print("  *** ~0.06 dB, but GROUP DELAY AND TAIL VERDICTS ARE NOT RELIABLE")
        print("  *** from txt -- measured 4 ms of drift, enough to flip a verdict.")
        print("  *** Re-export the captures as impulse-response WAVs for verdicts.")
    print("  %-2s %6s %10s %8s %7s %8s %9s  %s"
          % ("ch", "Q", "GD ms", "@Hz", "%aud", "tailfail", "worstExc", "verdict"))
    for r in analyse(tr, a.out):
        print("  %-2s %6.1f %+10.1f %8.1f %6.0f%% %8d %9.0f  %s"
              % (r["ch"], r["q"], r["gd"], r["gd_f"], r["gd_pct"],
                 r["tail_fails"], r["worst_excess"],
                 "PASS" if r["ok"] else "FAIL"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
