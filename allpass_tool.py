#!/usr/bin/env python3
"""All-pass phase-cancellation study tool.

Reads REW-exported frequency responses (Freq / SPL / Phase) for the Left
channel, the Right channel and the measured L+R combination, then:

  1. computes the complex sum L+R and compares it with the measured one;
  2. detects destructive interference (phase cancellation): regions where the
     two channels are near opposition at comparable levels;
  3. estimates the centre frequency f0 and Q of a 2nd-order all-pass filter
     (rePhase "normal": 360 deg total lag, -180 deg at f0) and determines
     which channel must carry it (the one whose phase leads);
  4. lets f0 and Q be varied live, redrawing the corrected responses;
  5. quantifies the price of the correction - group delay and bass smearing -
     and flags it.

Impulse responses can be imported (WAV / RAW / TXT) and the designed filter
exported as WAV, RAW or TXT for REW, rePhase and BruteFIR.

Usage:
    python3 allpass_tool.py -l L0.txt -r R0.txt -s LR.txt
If -s is omitted the calculated complex sum is used (with a warning).
"""

import argparse
import os
import sys

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg

import audio_io

# ---------------------------------------------------------------------------
# palette (fixed categorical order, dark surface)
SURFACE = '#1a1a19'
FOREGROUND = '#c3c2b7'
MUTED = '#7c7b74'
COL = {
    'L': '#3987e5',        # blue
    'R': '#d95926',        # orange
    'S_meas': '#199e70',   # aqua
    'S_calc': '#c98500',   # yellow
    'S_corr': '#d55181',   # magenta
    'T_corr': '#9085e9',   # violet
    # the corrected channels wear their own hue, lightened, so that
    # "L before" and "L after" read as the same series
    'L_corr': '#7fb4f2',   # light blue
    'R_corr': '#eb9166',   # light orange
    'target': '#008300',   # green
    'extra': '#e66767',    # red
    'neutral': FOREGROUND,
    # reference lines wear neutral ink, not a series hue; this step is
    # readable both on the dark plot and on the light control panel
    'home': '#8c8a80',
}
STATUS = {'good': '#0ca30c', 'warning': '#fab219',
          'serious': '#ec835a', 'critical': '#d03b3b'}
PROBLEM_BRUSH = pg.mkBrush(208, 59, 59, 45)

# Qt6 hands out a 12 pt UI font by default (Noto Sans at 96 dpi = a 22 px
# line box), which is a third larger than a typical desktop and costs a lot
# of room in a layout this dense. 9 pt is the conventional size; --font-size
# and Ctrl+plus / Ctrl+minus / Ctrl+0 override it.
UI_FONT_PT = 9.0
FONT_PT_RANGE = (6.0, 18.0)


def set_ui_font(app, pt):
    """Apply a UI point size to the whole application."""
    pt = float(min(max(pt, FONT_PT_RANGE[0]), FONT_PT_RANGE[1]))
    f = app.font()
    f.setPointSizeF(pt)
    app.setFont(f)
    return pt


def mono_font(pt=None):
    """A genuinely fixed-pitch font.

    QFontDatabase.systemFont(FixedFont) is not reliable - on this project's
    FreeBSD box it returns Noto Sans, a proportional face - so ask for a
    monospace family by name and let the style hint catch the rest.
    """
    f = QtGui.QFont('monospace')
    f.setStyleHint(QtGui.QFont.Monospace)
    f.setFixedPitch(True)
    if pt is not None:
        f.setPointSizeF(pt)
    return f


SLIDER_STEPS = 2000
F0_RANGE = (15.0, 300.0)
Q_RANGE = (0.25, 16.0)
SAMPLE_RATES = ['44100', '48000', '88200', '96000', '176400', '192000']
DEFAULT_RATE = '48000'


# ---------------------------------------------------------------------------
# frequency-domain helpers

def load_rew(path):
    """Parse a REW export: comments start with '*', data is f, SPL, phase.

    Returns (f, spl, phase, label, meta) where meta records whether the file
    carries a REW header and whether that header declares a timing reference
    (needed for the inter-channel phase to be meaningful).
    """
    f, m, p, note = [], [], [], ''
    meta = {'has_header': False, 'timing_ref': False}
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if line.startswith('*'):
                low = line.lower()
                if 'measured by rew' in low or low.startswith('* format:'):
                    meta['has_header'] = True
                if 'timing reference' in low or 'timing signal' in low:
                    meta['timing_ref'] = True
                if line.startswith('* Measurement:'):
                    note = line.split(':', 1)[1].strip()
                continue
            parts = line.split()
            if len(parts) >= 3:
                try:
                    fv, mv, pv = float(parts[0]), float(parts[1]), float(parts[2])
                except ValueError:
                    continue
                f.append(fv)
                m.append(mv)
                p.append(pv)
    if len(f) < 16:
        raise ValueError(f'{path}: no parsable frequency response data found')
    return np.asarray(f), np.asarray(m), np.asarray(p), note, meta


def to_complex(db, ph_deg):
    return 10.0 ** (db / 20.0) * np.exp(1j * np.radians(ph_deg))


def mag_db(H):
    return 20.0 * np.log10(np.abs(H) + 1e-15)


def phase_deg(H):
    return np.degrees(np.angle(H))


def wrap180(ph):
    return (ph + 180.0) % 360.0 - 180.0


def wrap_for_plot(ph):
    """Wrap to +-180 deg and break the polyline at the wrap discontinuities."""
    w = wrap180(np.asarray(ph, dtype=float))
    out = w.copy()
    out[1:][np.abs(np.diff(w)) > 180.0] = np.nan
    return out


def smooth_oct(f, y, frac=3.0):
    """1/frac-octave running average of y over a sorted frequency grid."""
    r = 2.0 ** (0.5 / frac)
    c = np.concatenate(([0.0], np.cumsum(y)))
    lo = np.searchsorted(f, f / r, side='left')
    hi = np.maximum(np.searchsorted(f, f * r, side='right'), lo + 1)
    return (c[hi] - c[lo]) / (hi - lo)


SMOOTH_OPTIONS = ['None', '1/48', '1/24', '1/12', '1/6', '1/3', '1/2', '1/1',
                  'Variable', 'Psychoacoustic', 'ERB']

# three cascaded moving averages approximate a Gaussian (central limit); this
# factor makes the result's equivalent rectangular bandwidth match a boxcar of
# the nominal width, so "1/3 octave" still means 1/3 octave of smoothing
_GAUSS_BOX = 0.7979

HOME_MODES = ['Flat', 'Harman in-room', 'B&K 1974', 'Hide']


def home_shape_db(f, mode):
    """Relative shape of the selected home (house) target curve, in dB.

    'Flat': 0 dB everywhere.
    'Harman in-room': the widely used approximation of the Olive/Welti
      steady-state in-room preference: +6.6 dB low-shelf around 105 Hz and
      a -3.5 dB high-shelf around 2.5 kHz (smooth ~1-octave transitions).
    'B&K 1974': flat to 400 Hz, then a gentle -1 dB/octave downward tilt
      (Bruel & Kjaer recommended listening-room response).
    """
    lf = np.log2(np.asarray(f, dtype=float))
    if mode == 'Harman in-room':
        bass = 6.6 * 0.5 * (1.0 - np.tanh(1.1 * (lf - np.log2(105.0))))
        treb = -3.5 * 0.5 * (1.0 + np.tanh(1.1 * (lf - np.log2(2500.0))))
        return bass + treb
    if mode == 'B&K 1974':
        return np.minimum(0.0, -(lf - np.log2(400.0)))
    return np.zeros(len(f))


def _box_smooth_var(f, y, w_oct):
    """Moving average of y with a (possibly per-point) width in octaves."""
    r = 2.0 ** (np.asarray(w_oct, dtype=float) / 2.0)
    c = np.concatenate(([0.0], np.cumsum(y)))
    lo = np.searchsorted(f, f / r, side='left')
    hi = np.maximum(np.searchsorted(f, f * r, side='right'), lo + 1)
    return (c[hi] - c[lo]) / (hi - lo)


def _gauss_smooth_var(f, y, w_oct, passes=3):
    """Gaussian-kernel smoothing of the nominal fractional-octave bandwidth.

    REW smooths with a Gaussian kernel, not a rectangular window, and the
    difference is visible: a boxcar's transfer function is a sinc whose
    first sidelobe is only -13 dB down, so ripple leaks straight through it.
    Cascading three moving averages gives a near-Gaussian kernel for three
    O(n) passes, with no sidelobes worth the name.
    """
    out = np.asarray(y, dtype=float)
    w = np.asarray(w_oct, dtype=float) * _GAUSS_BOX
    for _ in range(passes):
        out = _box_smooth_var(f, out, w)
    return out


def _width_profile(f, anchors):
    """Bandwidth in octaves vs frequency, log-f interpolated between anchors."""
    return np.interp(np.log10(f), np.log10([a for a, _ in anchors]),
                     [w for _, w in anchors])


def _erb_width_oct(f):
    """Glasberg & Moore ERB expressed as a bandwidth in octaves."""
    erb = 24.7 * (4.37 * np.asarray(f, dtype=float) / 1000.0 + 1.0)
    lo = np.maximum(f - erb / 2.0, np.asarray(f) * 0.02)
    return np.log2((f + erb / 2.0) / lo)


def smooth_width(f, mode):
    """Bandwidth in octaves that a named smoothing mode uses at each f."""
    if mode == 'Psychoacoustic':
        return _width_profile(f, [(100.0, 1 / 3), (1000.0, 1 / 6)])
    if mode == 'Variable':
        return _width_profile(f, [(100.0, 1 / 48), (1000.0, 1 / 6),
                                  (10000.0, 1 / 3)])
    if mode == 'ERB':
        return _erb_width_oct(f)
    num, den = mode.split('/')
    return np.full(len(np.atleast_1d(f)), float(num) / float(den))


def smoothed_db(f, H, mode):
    """Displayed magnitude in dB under a REW-style smoothing mode.

    All modes use a Gaussian kernel of the stated fractional-octave
    bandwidth, as REW does.
      '1/N'            constant bandwidth, power (energy) average.
      'Variable'       1/48 oct below 100 Hz, 1/6 at 1 kHz, 1/3 above 10 kHz.
                       REW recommends it for responses that are to be
                       equalised - deliberately barely smoothed in the bass.
      'Psychoacoustic' 1/3 oct below 100 Hz to 1/6 above 1 kHz, with a cubic
                       mean (cube root of the mean of cubes) so peaks weigh
                       more than dips, as the ear does.
      'ERB'            one equivalent rectangular bandwidth of the auditory
                       filter at each frequency (Glasberg & Moore): about one
                       octave at 40 Hz narrowing to ~1/6 octave by 1 kHz.
    """
    if mode == 'None':
        return mag_db(H)
    a = np.abs(np.asarray(H))
    w = smooth_width(f, mode)
    if mode == 'Psychoacoustic':
        m = np.maximum(_gauss_smooth_var(f, a ** 3, w), 0.0) ** (1.0 / 3.0)
        return 20.0 * np.log10(m + 1e-15)
    return 10.0 * np.log10(np.maximum(
        _gauss_smooth_var(f, a * a, w), 0.0) + 1e-30)


class Display:
    """Log-spaced min/max display decimation.

    The measurement grid has ~65k points; painting them antialiased is what
    made the sliders sluggish (the DSP itself takes ~2 ms). Each display bin
    keeps the min and the max of the full-resolution data, so narrow peaks
    and dips stay visible while the painter only handles ~1.4k points.
    """

    def __init__(self, f, pts_per_oct=64):
        lf = np.log2(f)
        n_bins = max(int((lf[-1] - lf[0]) * pts_per_oct), 16)
        targets = 2.0 ** np.linspace(lf[0], lf[-1], n_bins + 1)[:-1]
        e = np.unique(np.searchsorted(f, targets, side='left'))
        self.e = e[e < len(f)]
        nxt = np.append(self.e[1:], len(f))
        self.last = nxt - 1                       # last sample in each bin
        self.centers = np.minimum(self.e + (nxt - self.e) // 2, len(f) - 1)
        self.x1 = f[self.centers]
        # the two envelope points of a bin must sit at the bin's two EDGES,
        # not both at its centre: putting them at the same x draws a vertical
        # bar per bin joined by a near-horizontal hop, i.e. a staircase. It
        # hides in noisy data and is glaring wherever the curve is smooth and
        # steep - the top octaves under Variable/psychoacoustic smoothing.
        self.x2 = np.empty(2 * len(self.e))
        self.x2[0::2] = f[self.e]
        self.x2[1::2] = f[self.last]

    def env(self, y):
        """Interleaved per-bin min/max of y, matching self.x2.

        Within a bin the two are ordered to follow the local slope, so a
        monotonic stretch is drawn monotonically rather than as a zigzag.
        """
        mn = np.minimum.reduceat(y, self.e)
        mx = np.maximum.reduceat(y, self.e)
        rising = y[self.last] >= y[self.e]
        out = np.empty(2 * len(self.e))
        out[0::2] = np.where(rising, mn, mx)
        out[1::2] = np.where(rising, mx, mn)
        return out

    def sub(self, y):
        """Plain subsample of y at the bin centres, matching self.x1."""
        return y[self.centers]


def estimate_delay(f, H, lo=150.0, hi=8000.0, max_ms=30.0):
    """Bulk delay of a response, by coherent alignment.

    The delay tau that makes |sum H(f) exp(j 2 pi f tau)| largest is the one
    that best straightens the phase. Unlike fitting the slope of an
    unwrapped phase, this never unwraps, so noisy high-frequency bins - where
    a room measurement wraps unpredictably - cannot corrupt the result. (On
    this project's own data the unwrapping fit reported 5.2 ms where the
    impulse response peak says 0.)
    """
    sel = (f >= lo) & (f <= hi)
    if sel.sum() < 32:
        return 0.0
    fs, Hs = f[sel], H[sel]
    idx = np.unique(np.linspace(0, len(fs) - 1,
                                min(len(fs), 1200)).astype(int))
    fs = fs[idx]
    u = Hs[idx] / (np.abs(Hs[idx]) + 1e-15)

    def best(taus):
        top, val = 0.0, -1.0
        for i in range(0, len(taus), 512):        # chunked: keep it in cache
            blk = taus[i:i + 512]
            s = np.abs(np.exp(2j * np.pi * np.outer(blk, fs)) @ u)
            j = int(np.argmax(s))
            if s[j] > val:
                val, top = s[j], float(blk[j])
        return top

    step = 1.0 / (8.0 * max(fs[-1], 1.0))         # ~8 steps per HF period
    coarse = best(np.arange(-max_ms * 1e-3, max_ms * 1e-3, step))
    return best(np.linspace(coarse - step, coarse + step, 401))


def contiguous(mask, min_pts=1, max_gap=3):
    """(start, stop) index pairs of True runs, bridging gaps of <= max_gap."""
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    runs, start, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev > max_gap:
            runs.append((start, prev + 1))
            start = i
        prev = i
    runs.append((start, prev + 1))
    return [(a, b) for a, b in runs if b - a >= min_pts]


# ---------------------------------------------------------------------------
# the all-pass filter itself

def allpass_h(f, f0, q):
    """2nd-order all-pass, rePhase "normal" convention.

    H(s) = (s^2 - s/Q + 1) / (s^2 + s/Q + 1),  s = j f/f0.
    |H| = 1 at every frequency; the phase runs 0 -> -360 deg and passes
    through -180 deg exactly at f0.
    """
    s = 1j * (np.asarray(f, dtype=float) / f0)
    return (s * s - s / q + 1.0) / (s * s + s / q + 1.0)


def allpass_ir(f0, q, fs, n):
    """Impulse response as the equivalent digital (RBJ) all-pass biquad.

    Reproduces a rePhase "normal" all-pass export (ap_L_42p5_Q2p5.txt) to
    within 5e-5 per tap at fs = 48000. Causal, starting at t = 0: no
    centring and therefore no added latency.
    """
    w0 = 2.0 * np.pi * f0 / fs
    alpha = np.sin(w0) / (2.0 * q)
    cw, a0 = np.cos(w0), 1.0 + alpha
    b0, b1, b2 = (1.0 - alpha) / a0, -2.0 * cw / a0, (1.0 + alpha) / a0
    a1, a2 = -2.0 * cw / a0, (1.0 - alpha) / a0
    y = np.zeros(int(n))
    x0, x1, x2 = 1.0, 0.0, 0.0
    for i in range(int(n)):
        y[i] = (b0 * x0 + b1 * x1 + b2 * x2
                - (a1 * y[i - 1] if i >= 1 else 0.0)
                - (a2 * y[i - 2] if i >= 2 else 0.0))
        x2, x1, x0 = x1, x0, 0.0
    return y


def group_delay(f, f0, q):
    """Group delay of the analytic all-pass, in seconds."""
    ph = np.unwrap(np.angle(allpass_h(f, f0, q)))
    return -np.gradient(ph, 2.0 * np.pi * np.asarray(f, dtype=float))


def gd_at_f0(f0, q):
    """Closed form: tau(f0) = 4Q/w0, also the maximum of the group delay."""
    return 4.0 * q / (2.0 * np.pi * f0)


def ringing_t60(f0, q):
    """Decay time of the all-pass tail: pole time constant 2Q/w0 -> T60.

    Verified against Schroeder backward integration of the real biquad
    impulse response (agreement within 1% for Q from 1 to 10).
    """
    return 6.9078 * (2.0 * q / (2.0 * np.pi * f0))


def burst_response(f0, q, frac=3.0):
    """Push a 1/frac-octave Gaussian tone burst at f0 through the all-pass.

    Returns (t_ms, x, y, env_x_db, env_y_db, delay_ms, peak_drop_db, t60_ms).
    This is the rate-independent evidence of smearing: a narrow-band bass
    event in, the same event delayed and stretched out.
    """
    fs = max(2000.0, 24.0 * f0)
    bw = f0 * (2.0 ** (0.5 / frac) - 2.0 ** (-0.5 / frac))
    sig = 2.355 / (2.0 * np.pi * bw)
    span = 8.0 * sig + 8.0 * gd_at_f0(f0, q)
    n = int(2 ** np.ceil(np.log2(max(2.0 * span * fs, 256))))
    t = (np.arange(n) - n // 4) / fs
    x = np.exp(-t ** 2 / (2.0 * sig ** 2)) * np.sin(2.0 * np.pi * f0 * t)
    fr = np.fft.rfftfreq(n, 1.0 / fs)
    y = np.fft.irfft(np.fft.rfft(x) * allpass_h(np.maximum(fr, 1e-9), f0, q), n)

    mask = np.zeros(n)
    mask[0] = 1.0
    mask[1:n // 2] = 2.0
    mask[n // 2] = 1.0

    def env(v):
        return np.abs(np.fft.ifft(np.fft.fft(v) * mask))

    ex, ey = env(x), env(y)
    ix, iy = int(np.argmax(ex)), int(np.argmax(ey))
    ref = max(ex.max(), ey.max())
    edb_x = 20.0 * np.log10(ex / ref + 1e-12)
    edb_y = 20.0 * np.log10(ey / ref + 1e-12)
    dec = edb_y[iy:] - edb_y[iy]
    tt = t[iy:] - t[iy]
    sel = (dec <= -5.0) & (dec >= -35.0)
    t60 = (-60.0 / np.polyfit(tt[sel], dec[sel], 1)[0]) if sel.sum() > 10 else np.nan
    return (t * 1000.0, x, y, edb_x, edb_y,
            (t[iy] - t[ix]) * 1000.0,
            20.0 * np.log10(ey.max() / ex.max()), t60 * 1000.0)


def smear_verdict(f0, q):
    """Traffic light for the price paid in group delay, in cycles at f0."""
    cycles = gd_at_f0(f0, q) * f0
    if cycles <= 1.0:
        return 'good', cycles, 'below the ~1 cycle rule of thumb'
    if cycles <= 2.0:
        return 'warning', cycles, 'borderline (1-2 cycles)'
    if cycles <= 3.0:
        return 'serious', cycles, 'likely audible as delayed / heavy bass'
    return 'critical', cycles, 'clearly excessive'


def peaking_h(f, f0, gain_db, q):
    """RBJ / REW analogue peaking (bell) filter, minimum phase.

    H(s) = (s^2 + s A/Q + 1) / (s^2 + s/(A Q) + 1), A = 10^(gain/40),
    s = j f/f0 - so |H| at f0 is exactly the requested gain.
    """
    a = 10.0 ** (gain_db / 40.0)
    s = 1j * (np.asarray(f, dtype=float) / f0)
    return ((s * s + s * a / q + 1.0) / (s * s + s / (a * q) + 1.0))


def eq_chain_h(f, filters):
    """Complex response of a list of peaking filters (enabled ones only)."""
    h = np.ones(len(f), dtype=complex)
    for flt in filters:
        if flt.get('on', True):
            h = h * peaking_h(f, flt['f0'], flt['gain'], flt['q'])
    return h


def anchored_home(f, home_shape_rel, H, lo=200.0, hi=2000.0):
    """The home curve shape put at one response's own level."""
    mid = (f >= lo) & (f <= hi)
    ref = smoothed_db(f, H, '1/1')
    return home_shape_rel + float(np.median(ref[mid] - home_shape_rel[mid]))


def ring_ms(f0, q):
    """T60 of a 2nd-order section: how long it rings, in milliseconds.

    Sign matters more than the number. A BOOST is a resonance and adds this
    much decay; a CUT at a room mode is its inverse and takes decay away.
    """
    return 2200.0 * q / float(f0)


def fit_auto_eq(f, err_db, mask, n_max=6, max_boost=3.0, max_cut=12.0,
                q_min=0.5, q_max=8.0, min_gain=0.7, q_max_boost=3.0):
    """Greedy parametric EQ: repeatedly cancel the largest remaining error.

    `err_db` is what the EQ must ADD (target minus current). `mask` marks
    the frequencies EQ is allowed to work on - interference nulls are
    excluded by the caller, since no amount of EQ fixes a cancellation
    between two channels; boosting there only wastes headroom and drive.
    """
    filters = []
    resid = np.array(err_db, dtype=float)
    work = np.array(mask, dtype=bool)
    for _ in range(20 * n_max):
        if len(filters) >= n_max:
            break
        r = np.where(work & np.isfinite(resid), resid, 0.0)
        if not np.any(r):
            break
        # Rank by what a filter can ACHIEVE here, not by the raw error.
        # A single channel's biggest errors are its deep narrow nulls, and
        # those are capped by max_boost (often to nothing). Ranking on raw
        # error spends the whole budget on them and never reaches the bumps
        # that a cut could actually fix - which is exactly how a 6-filter
        # per-channel fit left a +3.8 dB bump standing.
        lim = np.where(r > 0, abs(max_boost), abs(max_cut))
        gettable = np.minimum(np.abs(r), lim)
        # tiny tie-break on raw size, so equally-capped regions still order
        i = int(np.argmax(gettable + 1e-4 * np.minimum(np.abs(r), 100.0)))
        peak = float(r[i])
        if gettable[i] < min_gain:
            break
        f0 = float(f[i])
        # bandwidth: walk out until the error falls to half the peak
        half, sgn = abs(peak) / 2.0, np.sign(peak)
        lo = i
        while (lo > 0 and work[lo - 1] and np.sign(resid[lo - 1]) == sgn
               and abs(resid[lo - 1]) >= half):
            lo -= 1
        hi = i
        while (hi < len(f) - 1 and work[hi + 1] and np.sign(resid[hi + 1]) == sgn
               and abs(resid[hi + 1]) >= half):
            hi += 1
        bw = max(f[hi] - f[lo], f0 * 0.02)
        q = float(np.clip(f0 / bw, q_min, q_max))
        if peak > 0:
            # A boost IS a resonance: it rings for 2.2*Q/f0, so a narrow one
            # is the worst thing you can put in a room. Q=8 at 97 Hz rings
            # 182 ms, which showed up one-for-one in a measured RT60. Cuts
            # keep the full range - a narrow cut at a mode SHORTENS decay.
            q = float(min(q, q_max_boost))
        gain = float(np.clip(peak, -abs(max_cut), abs(max_boost)))
        if abs(gain) < min_gain:
            # not allowed to act here (boosts capped at 0, say): retire the
            # region instead of stopping, so the remaining errors still get
            # their filters
            work[lo:hi + 1] = False
            continue
        filters.append(dict(f0=f0, gain=gain, q=q, on=True))
        resid = resid - mag_db(peaking_h(f, f0, gain, q))
        if abs(peak) > abs(gain) + 1e-9:
            # the gain hit the limit: this region has had all it may get,
            # otherwise the next pass would stack a second filter on it
            work[lo:hi + 1] = False
    return refine_gains(f, err_db, mask, filters, max_boost, max_cut,
                        q_max_boost=q_max_boost)


def refine_gains(f, err_db, mask, filters, max_boost, max_cut, iters=6,
                 q_max_boost=3.0):
    """Re-solve every gain at once, with the frequencies and Qs fixed.

    The greedy pass places one filter at a time against the error left by
    its predecessors, so a wide cut overshoots on its shoulders and a later
    filter gets spent putting the shoulders back. Solving all the gains
    together removes that: each filter is chosen knowing what the others do,
    so the self-repair filters stop being necessary.

    Gauss-Newton on the real chain rather than a one-shot linear solve,
    because a peaking filter's dB response is only approximately
    proportional to its gain.
    """
    if not filters:
        return filters
    sel = np.asarray(mask, dtype=bool) & np.isfinite(err_db)
    if sel.sum() < 8:
        return filters
    target = np.asarray(err_db, dtype=float)[sel]
    # unit-gain shape of each filter: the basis the solve works in
    basis = np.stack([mag_db(peaking_h(f, x['f0'], 1.0, x['q']))[sel]
                      for x in filters], axis=1)
    lo = np.full(len(filters), -abs(max_cut))
    # a filter narrower than the boost limit may only ever cut: the refit
    # must not turn a sharp cut into a sharp (ringing) boost
    hi = np.array([abs(max_boost) if x['q'] <= q_max_boost + 1e-9 else 0.0
                   for x in filters])
    g = np.clip([x['gain'] for x in filters], lo, hi)

    def rms_of(gains):
        chain = [dict(x, gain=float(v)) for x, v in zip(filters, gains)]
        return float(np.sqrt(np.mean(
            (target - mag_db(eq_chain_h(f, chain))[sel]) ** 2)))

    best, best_rms = g.copy(), rms_of(g)
    for _ in range(iters):
        chain = [dict(x, gain=float(v)) for x, v in zip(filters, g)]
        resid = target - mag_db(eq_chain_h(f, chain))[sel]
        step, *_ = np.linalg.lstsq(basis, resid, rcond=None)
        trial = np.clip(g + step, lo, hi)
        r = rms_of(trial)
        if r < best_rms - 1e-6:
            best, best_rms, g = trial.copy(), r, trial
        else:
            break
    for x, v in zip(filters, best):
        x['gain'] = float(v)
    # a gain the solve drove to nothing is a filter slot wasted downstream
    return [x for x in filters if abs(x['gain']) >= 0.1]


EQ_PLACEMENT_NOTE = (
    'These filters belong on BOTH channels equally (a master/sub bus, or the '
    'same filter set in L and R). Applied commonly they cannot disturb the '
    'all-pass: the EQ phase shift is identical in both channels and cancels '
    'exactly in the L-R phase difference, which is what the cancellation '
    'depends on. Put them on ONE channel only and you break the correction - '
    'measured 36 degrees of relative phase error on this filter set.')


def write_rew_filters(path, filters, note='', placement=''):
    """REW 'Filter Settings' text, the generic format most DSPs import."""
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('Filter Settings file\n\nGenerated by allpass_tool.py\n')
        fh.write('\nNotes:\n')
        for line in (note, placement or EQ_PLACEMENT_NOTE):
            if line:
                fh.write(line + '\n')
        fh.write('\nEqualiser: Generic\n')
        n = 0
        for flt in filters:
            if not flt.get('on', True):
                continue
            n += 1
            fh.write(f'Filter {n:2d}: ON  PK       Fc {flt["f0"]:9.2f} Hz  '
                     f'Gain {flt["gain"]:6.2f} dB  Q {flt["q"]:7.3f}\n')
        for k in range(n + 1, 21):
            fh.write(f'Filter {k:2d}: OFF None\n')


def num_tag(v):
    return f'{v:g}'.replace('.', 'p').replace('-', 'm')


def write_rew_txt(path, f, H, label):
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('* Exported by allpass_tool.py\n')
        fh.write(f'* Measurement: {label}\n')
        fh.write('* Freq(Hz) SPL(dB) Phase(degrees)\n')
        for fv, mv, pv in zip(f, mag_db(H), wrap180(phase_deg(H))):
            fh.write(f'{fv:.6f} {mv:.4f} {pv:.4f}\n')


# ---------------------------------------------------------------------------

class Analysis:
    """The three responses on a common grid plus the detection results."""

    def __init__(self, left_file, right_file, stereo_file):
        self.log_lines = []
        self.extras = []          # imported responses: (name, H, colour, desc)

        fL, mL, pL, nL, metaL = load_rew(left_file)
        fR, mR, pR, nR, metaR = load_rew(right_file)
        self.log(f'Loaded L: {os.path.basename(left_file)} ({nL or "no label"}, '
                 f'{len(fL)} pts, {fL[0]:.1f}-{fL[-1]:.0f} Hz)')
        self.log(f'Loaded R: {os.path.basename(right_file)} ({nR or "no label"}, '
                 f'{len(fR)} pts, {fR[0]:.1f}-{fR[-1]:.0f} Hz)')

        # the whole analysis rests on L and R sharing one clock: refuse
        # measurements whose REW header shows no timing reference
        for name, path, meta in (('L', left_file, metaL),
                                 ('R', right_file, metaR)):
            if meta['has_header'] and not meta['timing_ref']:
                raise ValueError(
                    f'{os.path.basename(path)} ({name}) was measured WITHOUT '
                    'a timing reference: its phase has an arbitrary time '
                    'offset, so the L-R phase difference - the whole basis '
                    'of this analysis - is meaningless. Re-measure both '
                    'channels with an acoustic (or loopback) timing '
                    'reference in REW.')
            if not meta['has_header']:
                self.log(f'WARNING: {name} carries no REW header; cannot '
                         'verify that it was measured with a timing '
                         'reference. The measured-vs-calculated L+R check '
                         'below is the only remaining safeguard.')

        self.f = fL
        mR, pR = self._regrid(fR, mR, pR, 'R')
        self.HL, self.HR = to_complex(mL, pL), to_complex(mR, pR)
        self.Hcalc = self.HL + self.HR
        self.log('Calculated L+R as the complex (vector) sum of the two '
                 'measured responses.')

        self.Hmeas = None
        if stereo_file:
            fS, mS, pS, nS, _ = load_rew(stereo_file)
            self.log(f'Loaded L+R (measured): {os.path.basename(stereo_file)} '
                     f'({nS or "no label"}, {len(fS)} pts)')
            mS, pS = self._regrid(fS, mS, pS, 'L+R')
            self.Hmeas = to_complex(mS, pS)
            sel = (self.f >= 20) & (self.f <= 300)
            d = np.abs(mag_db(self.Hmeas[sel]) - mag_db(self.Hcalc[sel]))
            med = float(np.median(d))
            if med > 3.0:
                raise ValueError(
                    'The complex sum of L and R does not reproduce the '
                    f'measured L+R (median difference {med:.1f} dB over '
                    '20-300 Hz; a coherent set stays well under 1 dB). The '
                    'three measurements are not on a common time reference '
                    '- re-measure with the timing reference enabled.')
            self.log(f'Timing check passed: measured vs calculated L+R '
                     f'(20-300 Hz) differ by {med:.2f} dB median '
                     f'({np.max(d):.2f} dB max at the dip edges) -> the '
                     'measurements share one time reference and the '
                     'predictions below can be trusted.')
        else:
            self.log('WARNING: no measured L+R supplied (-s); using the '
                     'calculated complex sum in its place.')

        self.disp = Display(self.f)
        # phase rotates fast at HF: on a coarse grid consecutive points differ
        # by more than 180 deg and the wrap-break would blank whole octaves,
        # so phase gets its own denser grid
        self.disp_p = Display(self.f, pts_per_oct=320)
        self.smooth_mode = 'None'
        self.delay_s = 0.0
        self.delay_auto = estimate_delay(self.f, self.HL)

        # the level the sum CAN reach: what L and R would give in phase.
        # This is the optimiser's reference - an all-pass cannot go above it.
        self.target = smooth_oct(
            self.f, 20.0 * np.log10(np.abs(self.HL) + np.abs(self.HR)), 3.0)
        self.log('Coherent ceiling curve = 1/3-octave average of |L|+|R|: the '
                 'level the combination would reach if the two channels added '
                 'in phase. It is the physical bound an all-pass can recover '
                 'to, hence the optimiser reference.')

        self.home_mode, self.home_trim = 'Flat', 0.0
        self.eq_filters = []
        self.set_home('Flat')

        self._detect()

    # ---- helpers ----------------------------------------------------------
    def log(self, msg):
        self.log_lines.append(msg)

    def _regrid(self, f, m, p, name):
        if len(f) == len(self.f) and np.allclose(f, self.f):
            return m, p
        self.log(f'Note: {name} is on a different frequency grid; '
                 'interpolating onto the L grid.')
        return (np.interp(self.f, f, m),
                wrap180(np.interp(self.f, f, np.unwrap(p, period=360.0))))

    # ---- detection --------------------------------------------------------
    def _detect(self):
        f = self.f
        dbL, dbR = mag_db(self.HL), mag_db(self.HR)
        self.G = np.abs(self.Hcalc) / (np.abs(self.HL) + np.abs(self.HR))
        self.dphi = np.degrees(np.angle(self.HL * np.conj(self.HR)))

        mask = (self.G < 0.35) & (np.abs(dbL - dbR) < 12.0) & (f <= 500.0)
        runs = contiguous(mask, min_pts=4)
        self.regions = [(f[a], f[b - 1]) for a, b in runs]
        self.cancellation = bool(runs)

        if not runs:
            self.log('No significant phase cancellation below 500 Hz: the '
                     'coherent sum never falls below 35% of the incoherent '
                     'sum at matched levels. An all-pass correction is not '
                     'needed - and per the "least phase manipulation" rule '
                     'none should be added. Any response problems left are '
                     'EQ material (see below).')
            self.region = None
            self.f0_est, self.q_est = 60.0, 2.0
            self.channel = 'L'
            self.band = (f >= 20) & (f <= 200)
            self.alternatives = []
            self.rms_uncorrected = self.rms_shortfall(self.Hcalc)
            self._classify_eq()
            return

        i0, i1 = min(runs, key=lambda ab: self.G[ab[0]:ab[1]].min())
        self.region = (f[i0], f[i1 - 1])
        gi = i0 + int(np.argmin(self.G[i0:i1]))
        depth = 20 * np.log10(self.G[gi] + 1e-12)
        self.log(f'CANCELLATION DETECTED at {self.region[0]:.1f}-'
                 f'{self.region[1]:.1f} Hz. At {f[gi]:.1f} Hz the combination '
                 f'sits {abs(depth):.1f} dB below the in-phase sum of L and R '
                 f'(coherence {self.G[gi]*100:.0f}%) while L and R are within '
                 f'{abs(dbL[gi]-dbR[gi]):.1f} dB of each other -> destructive '
                 'interference between the channels, not a level shortfall. '
                 'This is what an all-pass can fix; EQ cannot.')
        if len(runs) > 1:
            self.log('Other (milder) low-coherence regions: ' + ', '.join(
                f'{a:.0f}-{b:.0f} Hz' for a, b in self.regions
                if (a, b) != self.region))

        # f0 evidence: the wrapped phase difference passes through +-180 deg
        cross = None
        for i in range(max(i0 - 5, 0), min(i1 + 5, len(f) - 1)):
            d0, d1 = self.dphi[i], self.dphi[i + 1]
            if d0 * d1 < 0 and abs(d0) > 150 and abs(d1) > 150:
                a0 = abs(d0) if d0 > 0 else 360.0 - abs(d0)
                a1 = abs(d1) if d1 > 0 else 360.0 - abs(d1)
                t = (180.0 - a0) / (a1 - a0) if a1 != a0 else 0.5
                cross = f[i] + (f[i + 1] - f[i]) * t
                break
        f0 = cross if cross is not None else f[gi]
        self.f0_opposition = f0
        self.log(f'f0 evidence: the L-R phase difference reaches full '
                 f'opposition (180 deg) at {f0:.1f} Hz'
                 + ('' if cross is not None else
                    ' (taken from the coherence minimum; no exact 180 deg '
                    'crossing inside the region)') + '.')

        sel = ((f >= self.region[0] * 0.8) & (f <= f0)
               & (np.abs(self.dphi) > 90) & (np.abs(self.dphi) < 178))
        lead = float(np.median(self.dphi[sel])) if sel.any() else self.dphi[gi]
        self.channel = 'L' if lead > 0 else 'R'
        self.log(f'Below f0 the phase difference (L minus R) is about '
                 f'{lead:+.0f} deg, so the {self.channel} channel leads. The '
                 f'all-pass belongs on {self.channel}: its -180 deg at f0 '
                 'rotates the leading channel back onto the other one.')

        self._optimise(f0)

    def _optimise(self, f0_seed):
        f = self.f
        lo, hi = self.region[0] / 1.4, self.region[1] * 1.4
        self.band = (f >= lo) & (f <= hi)
        fb, HLb, HRb = f[self.band], self.HL[self.band], self.HR[self.band]
        tb = self.target[self.band]

        f0s = np.arange(max(f0_seed * 0.7, F0_RANGE[0]), f0_seed * 1.35, 0.25)
        qs = np.arange(0.4, 10.001, 0.05)
        grids = {}
        for ch in ('L', 'R'):
            g = np.empty((f0s.size, qs.size))
            for i, f0 in enumerate(f0s):
                for j, q in enumerate(qs):
                    ap = allpass_h(fb, f0, q)
                    Hc = HLb * ap + HRb if ch == 'L' else HLb + HRb * ap
                    sf = np.maximum(tb - mag_db(Hc), 0.0)
                    g[i, j] = np.sqrt(np.mean(sf ** 2))
            grids[ch] = g

        base = float(np.sqrt(np.mean(np.maximum(
            tb - mag_db(self.Hcalc[self.band]), 0.0) ** 2)))
        best = {}
        for ch, g in grids.items():
            i, j = np.unravel_index(np.argmin(g), g.shape)
            best[ch] = (g[i, j], f0s[i], qs[j])
        self.log(f'Optimiser: minimise the RMS shortfall below the target '
                 f'level over {fb[0]:.0f}-{fb[-1]:.0f} Hz (uncorrected '
                 f'{base:.2f} dB). All-pass on L -> {best["L"][0]:.2f} dB '
                 f'(f0={best["L"][1]:.1f}, Q={best["L"][2]:.2f}); on R -> '
                 f'{best["R"][0]:.2f} dB (f0={best["R"][1]:.1f}, '
                 f'Q={best["R"][2]:.2f}).')

        pick = 'L' if best['L'][0] <= best['R'][0] else 'R'
        if pick != self.channel:
            self.log(f'The optimiser prefers {pick} over the phase-lead '
                     f'choice {self.channel}; following the optimiser.')
            self.channel = pick
        score = best[pick][0]
        self.rms_uncorrected = base

        # Generic trade-off ladder: for each tolerated loss of correction,
        # the filter with the least group delay (= least phase manipulation,
        # least ringing) that stays within it. The correction-vs-timing
        # choice belongs to the listener, not to the optimiser.
        g = grids[pick]
        gdm = gd_at_f0(f0s[:, None], qs[None, :])
        self.alternatives = []
        seen = set()
        for tol in (0.0, 0.25, 0.5, 1.0, 2.0):
            cost = np.where(g <= score + tol, gdm, np.inf)
            i, j = np.unravel_index(int(np.argmin(cost)), cost.shape)
            key = (round(float(f0s[i]), 2), round(float(qs[j]), 2))
            if key in seen:
                continue
            seen.add(key)
            f0v, qv = float(f0s[i]), float(qs[j])
            level, cycles, _ = smear_verdict(f0v, qv)
            _, Hc = self.corrected(f0v, qv, pick)
            self.alternatives.append(dict(
                tol=tol, user=False, channel=pick, f0=f0v, q=qv,
                rms=float(g[i, j]), gd_ms=float(gdm[i, j] * 1000.0),
                cycles=cycles, smear=level, home_dev=self.home_dev(Hc),
                t60_ms=float(ringing_t60(f0v, qv) * 1000.0)))
        self.f0_est = self.alternatives[0]['f0']
        self.q_est = self.alternatives[0]['q']

        self.log(f'=> BEST CORRECTION: all-pass on {pick}, f0 = '
                 f'{self.f0_est:.1f} Hz, Q = {self.q_est:.2f} - RMS shortfall '
                 f'{base:.2f} -> {score:.2f} dB, group delay at f0 '
                 f'{self.alternatives[0]["gd_ms"]:.0f} ms.')
        self.log('=> TRADE-OFF LADDER (generic): each row is the '
                 'least-delay filter within the stated loss of correction. '
                 'Group delay and ringing both grow with Q, so giving up a '
                 'fraction of a dB often buys a much faster filter - better '
                 'transient attack (kick drum) for slightly less fill of '
                 'the null:')
        for alt in self.alternatives:
            self.log(f'     give up {alt["tol"]:4.2f} dB -> f0 '
                     f'{alt["f0"]:5.1f} Hz  Q {alt["q"]:4.2f}  RMS '
                     f'{alt["rms"]:.2f} dB  delay {alt["gd_ms"]:3.0f} ms '
                     f'({alt["cycles"]:.2f} cycles)  T60 '
                     f'{alt["t60_ms"]:3.0f} ms')
        self.log('Pick the highest row whose delay you can hear no '
                 'difference with; phase should be manipulated as little '
                 'as the correction allows.')
        self._classify_eq()

    def _classify_eq(self):
        """EQ first, all-pass last: find bumps/dips that are NOT interference.

        Deviations from the response's own 1-octave trend that the channels
        produce coherently are level problems - parametric EQ (minimum
        phase, which also repairs the timing of a modal bump) or room
        treatment, never an all-pass.
        """
        f = self.f
        S = mag_db(self.Hmeas if self.Hmeas is not None else self.Hcalc)
        # deviation from the home curve: what EQ would actually have to undo
        dev = smooth_oct(f, S - self.home, 6.0)
        scope = (f >= 20) & (f <= 500)
        self.eq_regions = []
        for kind, mask in (('bump', dev >= 6.0), ('dip', dev <= -6.0)):
            for a, b in contiguous(scope & mask, min_pts=8, max_gap=8):
                fa, fb = f[a], f[b - 1]
                if kind == 'dip' and any(not (fb < ra or fa > rb)
                                         for ra, rb in self.regions):
                    continue      # interference: the all-pass case
                peak = float(np.max(np.abs(dev[a:b])))
                med_g = float(np.median(self.G[a:b]))
                self.eq_regions.append((fa, fb, kind, peak))
                if kind == 'bump':
                    self.log(f'EQ CANDIDATE: bump {fa:.0f}-{fb:.0f} Hz, '
                             f'+{peak:.1f} dB above the {self.home_mode} home '
                             'curve. A parametric cut tames it - and being '
                             'minimum phase it shortens the modal ringing '
                             'too. No all-pass involved.')
                else:
                    self.log(f'EQ CANDIDATE: dip {fa:.0f}-{fb:.0f} Hz, '
                             f'-{peak:.1f} dB below the {self.home_mode} home '
                             f'curve with the channels still coherent '
                             f'({med_g*100:.0f}%) -> a genuine level dip, not '
                             'interference. Gentle EQ boost (a few dB at '
                             'most) or absorption/positioning; an all-pass '
                             'cannot and should not touch it.')
        if not self.eq_regions:
            self.log(f'No EQ-sized bumps or dips (>6 dB vs the '
                     f'{self.home_mode} home curve) outside the interference '
                     'region below 500 Hz.')

    # ---- live computation -------------------------------------------------
    def corrected(self, f0, q, channel):
        ap = allpass_h(self.f, f0, q)
        if channel == 'L':
            Ht = self.HL * ap
            return Ht, Ht + self.HR
        Ht = self.HR * ap
        return Ht, self.HL + Ht

    def rms_shortfall(self, Hc):
        return float(np.sqrt(np.mean(np.maximum(
            self.target[self.band] - mag_db(Hc[self.band]), 0.0) ** 2)))

    def band_mean(self, Hc):
        return float(np.mean(mag_db(Hc[self.band])))

    def set_home(self, mode=None, trim=None, quiet=False):
        """Select the home (house) target curve and anchor it in level.

        The shape carries no absolute level, so it is anchored to the
        measured combination over 200 Hz - 2 kHz (above the modal region,
        below where directivity takes over). The anchor is a POWER average:
        averaging decibels instead would let the narrow deep nulls of a real
        room response drag the reference down - on this measurement by
        1.7 dB - because a -40 dB null counts as -40 in a dB mean but as
        almost nothing in an energy mean, which is how it sounds.

        `trim` is the user's own level offset on top of that.
        """
        if mode is not None:
            self.home_mode = mode
        if trim is not None:
            self.home_trim = trim
        mode = self.home_mode
        shape = home_shape_db(self.f, mode)
        S = smoothed_db(self.f, self.Hmeas if self.Hmeas is not None
                        else self.Hcalc, '1/1')
        mid = (self.f >= 200) & (self.f <= 2000)
        self.home_anchor = float(np.median(S[mid] - shape[mid]))
        self.home = shape + self.home_anchor + self.home_trim
        if mode != 'Hide' and not quiet:
            self.log(f'Home target curve: {mode}, anchored at '
                     f'{self.home_anchor:.1f} dB'
                     + (f' {self.home_trim:+.1f} dB trim'
                        if self.home_trim else '')
                     + ' (1-octave power average of the measured combination, '
                     'median over 200 Hz - 2 kHz). Evaluation/EQ reference '
                     'only: the all-pass optimiser still uses the coherent '
                     'ceiling |L|+|R|, the only level an all-pass can '
                     'physically recover to.')

    def eq_for(self, ch):
        """Enabled filters that act on channel ch ('L' or 'R')."""
        return [flt for flt in self.eq_filters
                if flt.get('on', True) and flt.get('ch', 'both') in ('both', ch)]

    def eq_channels(self):
        """L and R with their EQ applied (common filters plus per-channel)."""
        return (self.HL * eq_chain_h(self.f, self.eq_for('L')),
                self.HR * eq_chain_h(self.f, self.eq_for('R')))

    def channels_corrected(self, f0, q, channel):
        """L and R each with its OWN filters: per-channel EQ plus, on the
        target channel only, the all-pass. Returns (HL, HR).

        This is what physically leaves each amplifier, so it is what the
        per-channel curves must show. `eq_applied` is just its sum.
        """
        HL, HR = self.eq_channels()
        ap = allpass_h(self.f, f0, q)
        if channel == 'L':
            return HL * ap, HR
        return HL, HR * ap

    def eq_applied(self, f0, q, channel):
        """The combination with EQ and the all-pass, or None if no EQ.

        Per-channel EQ has to be applied before the summation, so this
        rebuilds the sum rather than scaling the already-summed response.
        """
        if not any(flt.get('on', True) for flt in self.eq_filters):
            return None
        HL, HR = self.channels_corrected(f0, q, channel)
        return HL + HR

    def eq_mask(self, fmin, fmax, skip_interference=True):
        """Frequencies auto EQ may touch."""
        m = (self.f >= fmin) & (self.f <= fmax)
        if skip_interference:
            for a, b in self.regions or []:
                m &= ~((self.f >= a / 1.06) & (self.f <= b * 1.06))
        return m

    def home_dev(self, Hc):
        """RMS deviation of a combination from the home curve, 20-300 Hz."""
        sel = (self.f >= 20) & (self.f <= 300)
        d = smooth_oct(self.f, mag_db(Hc), 3.0)[sel] - self.home[sel]
        return float(np.sqrt(np.mean(d ** 2)))

    def disp_amp(self, H):
        """Display-ready magnitude: smoothed (current mode) then decimated."""
        H = np.asarray(H)
        good = np.isfinite(H)
        if self.smooth_mode != 'None' and not good.all():
            # imported curves cover only part of the grid: smooth what exists
            db = np.full(len(H), np.nan)
            db[good] = smoothed_db(self.f[good], H[good], self.smooth_mode)
            return self.disp.env(db)
        return self.disp.env(smoothed_db(self.f, H, self.smooth_mode))

    def disp_ph(self, H, remove_delay=True):
        """Display-ready phase: de-delayed, complex-smoothed, decimated, wrapped.

        Phase must never be averaged as wrapped numbers (a mean across a
        +-180 jump is garbage). Instead the complex response itself is
        vector-averaged over the same bandwidth profile as the amplitude
        smoothing and the angle of the result is shown - this is coherent
        averaging: where reflections randomise the phase, the vectors
        partially cancel and the wild HF detail fades to the trend.

        The bulk delay is removed first: it makes the trace stop spiralling
        and, because the residual rotates slowly, the vector average that
        follows cancels far less. Pass remove_delay=False for quantities in
        which a common delay already cancels, such as the L-R difference.
        """
        H = np.asarray(H)
        if remove_delay and self.delay_s:
            H = H * np.exp(2j * np.pi * self.f * self.delay_s)
        mode = self.smooth_mode
        if mode != 'None' and np.all(np.isfinite(H)):
            w = smooth_width(self.f, mode)
            H = (_gauss_smooth_var(self.f, H.real, w)
                 + 1j * _gauss_smooth_var(self.f, H.imag, w))
        return wrap_for_plot(self.disp_p.sub(phase_deg(H)))


# ---------------------------------------------------------------------------
# plot pages

class LogFreqAxis(pg.AxisItem):
    """Audio-style decade ticks: 20, 30, 50, 100, ... 1k, 2k, 5k, 10k.

    pyqtgraph's log axis labels every tick as 2*10^1, 3*10^1 ... which is
    unreadable on an audio plot. Values arrive and leave in log10 space.
    """

    def tickValues(self, minVal, maxVal, size):
        lo, hi = min(minVal, maxVal), max(minVal, maxVal)
        span = hi - lo                       # in decades
        if span <= 1.2:                      # zoomed in: room for every step
            labelled = (1, 2, 3, 4, 5, 6, 7, 8, 9)
        elif span <= 2.5:
            labelled = (1, 2, 3, 5)
        else:
            labelled = (1, 2, 5)
        major, minor = [], []
        for dec in range(int(np.floor(lo)) - 1, int(np.ceil(hi)) + 1):
            for m in range(1, 10):
                v = np.log10(m * 10.0 ** dec)
                if lo <= v <= hi:
                    (major if m in labelled else minor).append(v)
        return [(1.0, major), (0.5, minor)]

    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            f = 10.0 ** v
            if f >= 999.5:
                k = f / 1000.0
                out.append(f'{k:.0f}k' if abs(k - round(k)) < 0.05
                           else f'{k:g}k')
            elif f >= 0.995:
                out.append(f'{f:.0f}')
            else:
                out.append(f'{f:g}')
        return out


class CollapsibleSection(QtWidgets.QWidget):
    """A titled body that folds away to a single header row.

    Collapsed it costs one button's height, so a splitter can give the whole
    window back to the plot without the log being closed for good.
    """

    toggled = QtCore.Signal(bool)

    def __init__(self, title, body, expanded=True, parent=None):
        super().__init__(parent)
        self.body = body
        self.button = QtWidgets.QToolButton()
        self.button.setCheckable(True)
        self.button.setChecked(expanded)
        self.button.setAutoRaise(True)
        self.button.setText(title)
        self.button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.button.setToolTip(f'Show or hide the {title.lower()}')
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(self.button)
        bar.addStretch(1)
        lay.addLayout(bar)
        lay.addWidget(body, 1)
        self.button.toggled.connect(self._set)
        self._set(expanded)

    def _set(self, on):
        self.body.setVisible(on)
        self.button.setArrowType(QtCore.Qt.DownArrow if on
                                 else QtCore.Qt.RightArrow)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred,
            QtWidgets.QSizePolicy.Expanding if on
            else QtWidgets.QSizePolicy.Fixed)
        self.toggled.emit(on)

    def is_expanded(self):
        return self.button.isChecked()

    def set_expanded(self, on):
        self.button.setChecked(on)


class FlowLayout(QtWidgets.QLayout):
    """Left-to-right layout that wraps onto the next line when it runs out.

    Qt ships no wrapping layout, and the legend needs one: a column of
    checkboxes in the side pane costs far more width than a few rows of
    small ones under the plot.
    """

    def __init__(self, parent=None, margin=0, spacing=6):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return QtCore.Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QtCore.QRect(0, 0, w, 0), test=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, test=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QtCore.QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QtCore.QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect, test):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = eff.x(), eff.y(), 0
        sp = self.spacing()
        for it in self._items:
            w = it.sizeHint().width()
            h = it.sizeHint().height()
            if x + w > eff.right() and line_h > 0:
                x = eff.x()
                y += line_h + sp
                line_h = 0
            if not test:
                it.setGeometry(QtCore.QRect(QtCore.QPoint(x, y),
                                            it.sizeHint()))
            x += w + sp
            line_h = max(line_h, h)
        return y + line_h - rect.y() + m.bottom()


class FlowWidget(QtWidgets.QWidget):
    """Host for a FlowLayout.

    A plain QWidget reports the layout's unconstrained size hint, which for
    a wrapping layout means one item per row - the legend would claim the
    height of a column. Forwarding heightForWidth lets it claim only the
    two or three rows it really needs at the width it is given.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        sp = self.sizePolicy()
        sp.setHeightForWidth(True)
        sp.setVerticalPolicy(QtWidgets.QSizePolicy.Minimum)
        self.setSizePolicy(sp)

    def heightForWidth(self, w):
        return self.layout().heightForWidth(w)

    def sizeHint(self):
        w = self.width() or 900
        return QtCore.QSize(w, self.layout().heightForWidth(w))

    def minimumSizeHint(self):
        return QtCore.QSize(0, 0)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.updateGeometry()


class PlotCursor(QtCore.QObject):
    """Cross hairs that track the mouse, freeze on click, and drop markers.

    Reports into a shared label rather than floating tooltips, so the plot
    itself stays clean. Values are read from the visible curves at the
    cursor frequency, which is what you actually want to compare.
    """

    HIT_PX = 14           # how near a Ctrl+click must be to delete a marker

    def __init__(self, page, plot, readout, unit, parent=None):
        super().__init__(parent)
        self.page = page
        self.pi = plot
        self.readout = readout
        self.unit = unit
        self.frozen = False
        self.markers = []                # (point_item, text_item, x, y)
        pen = pg.mkPen(MUTED, width=1, style=QtCore.Qt.DashLine)
        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=pen)
        self.hline = pg.InfiniteLine(angle=0, movable=False, pen=pen)
        for ln in (self.vline, self.hline):
            ln.setZValue(50)
            ln.setVisible(False)
            plot.addItem(ln, ignoreBounds=True)
        plot.scene().sigMouseMoved.connect(self._moved)
        plot.scene().sigMouseClicked.connect(self._clicked)
        act = QtGui.QAction('Clear markers', self)
        act.triggered.connect(self.clear_markers)
        plot.vb.menu.addAction(act)

    # -- helpers
    def _at(self, pos):
        """Scene position -> (view point, inside?)."""
        vb = self.pi.vb
        if not self.pi.sceneBoundingRect().contains(pos):
            return None, False
        return vb.mapSceneToView(pos), True

    def _values(self, xlog):
        """Value of every visible curve on this plot at the cursor x."""
        out = []
        for key in self.page.order:
            if self.page.curve_plot.get(key) is not self.pi:
                continue
            item, label, colour = self.page.curves[key]
            if not item.isVisible():
                continue
            xs, ys = item.getData()
            if xs is None or len(xs) < 2 or not (xs[0] <= xlog <= xs[-1]):
                continue
            v = float(np.interp(xlog, xs, ys))
            if np.isfinite(v):
                out.append((label, colour, v))
        return out

    def _text(self, pt):
        f = 10.0 ** pt.x() if self.page.log_x else pt.x()
        head = (f'<b>{fmt_hz(f)}</b> &nbsp; cursor {pt.y():.2f} {self.unit}'
                + ('  <i>(frozen - click to release)</i>' if self.frozen
                   else ''))
        vals = self._values(pt.x())
        parts = [f'<span style="color:{c}">{lab} {v:.2f}</span>'
                 for lab, c, v in vals]
        return head + ('&nbsp;&nbsp;|&nbsp;&nbsp;' + ' &nbsp; '.join(parts)
                       if parts else '')

    # -- events
    def _moved(self, pos):
        if self.frozen:
            return
        pt, inside = self._at(pos)
        self.vline.setVisible(inside)
        self.hline.setVisible(inside)
        if not inside:
            return
        self.vline.setPos(pt.x())
        self.hline.setPos(pt.y())
        self.readout.setText(self._text(pt))

    def _clicked(self, ev):
        pt, inside = self._at(ev.scenePos())
        if not inside or ev.button() != QtCore.Qt.LeftButton:
            return
        if ev.modifiers() & QtCore.Qt.ControlModifier:
            ev.accept()
            y, _lab, _c = self._snap(pt)
            if not self._remove_near(ev.scenePos(),
                                     QtCore.QPointF(pt.x(), y)):
                self.add_marker(pt)
            return
        self.frozen = not self.frozen
        self.vline.setVisible(True)
        self.hline.setVisible(True)
        self.vline.setPos(pt.x())
        self.hline.setPos(pt.y())
        self.readout.setText(self._text(pt))

    # -- markers
    def _snap(self, pt):
        """Snap to the nearest visible curve, so a marker reads a real value."""
        vals = self._values(pt.x())
        if not vals:
            return pt.y(), None, None
        lab, colour, v = min(vals, key=lambda t: abs(t[2] - pt.y()))
        return v, lab, colour

    def add_marker(self, pt):
        y, lab, colour = self._snap(pt)
        colour = colour or FOREGROUND
        f = 10.0 ** pt.x() if self.page.log_x else pt.x()
        dot = pg.ScatterPlotItem([pt.x()], [y], size=9, pen=pg.mkPen(colour),
                                 brush=pg.mkBrush(colour), symbol='o')
        dot.setZValue(60)
        txt = pg.TextItem(f'{fmt_hz(f)}  {y:.2f} {self.unit}'
                          + (f'\n{lab}' if lab else ''),
                          color=colour, anchor=(0, 1))
        txt.setPos(pt.x(), y)
        txt.setZValue(60)
        self.pi.addItem(dot, ignoreBounds=True)
        self.pi.addItem(txt, ignoreBounds=True)
        self.markers.append((dot, txt, pt.x(), y))

    def _remove_near(self, scene_pos, snapped=None):
        """Ctrl+click on an existing marker deletes it (toggle placement).

        Markers snap onto a curve, so the click that made one is usually a
        few pixels off it. Both the raw click and where a new marker WOULD
        land are tested, otherwise a marker can only be removed by hitting
        its dot exactly.
        """
        vb = self.pi.vb
        probes = [scene_pos]
        if snapped is not None:
            probes.append(vb.mapViewToScene(snapped))
        for i, (dot, txt, x, y) in enumerate(self.markers):
            p = vb.mapViewToScene(QtCore.QPointF(x, y))
            for q in probes:
                if ((p.x() - q.x()) ** 2
                        + (p.y() - q.y()) ** 2) <= self.HIT_PX ** 2:
                    self.pi.removeItem(dot)
                    self.pi.removeItem(txt)
                    self.markers.pop(i)
                    return True
        return False

    def clear_markers(self):
        for dot, txt, _x, _y in self.markers:
            self.pi.removeItem(dot)
            self.pi.removeItem(txt)
        self.markers.clear()


def fmt_hz(f):
    """Frequency for a readout: 42.6 Hz, 1.25 kHz."""
    if f >= 1000:
        return f'{f/1000:.3g} kHz'
    return f'{f:.4g} Hz'


def styled_plot(ylabel, title=None, log_x=True):
    pw = pg.PlotWidget(axisItems={'bottom': LogFreqAxis('bottom')}
                       if log_x else None)
    pi = pw.getPlotItem()
    if log_x:
        pi.setLogMode(x=True)
        pi.setLabel('bottom', 'Frequency (Hz)')
        pi.getAxis('bottom').enableAutoSIPrefix(False)
    pi.showGrid(x=True, y=True, alpha=0.25)
    pi.setLabel('left', ylabel)
    # pyqtgraph's corner "A" button turns on auto-range. Every Y range here
    # is set deliberately (framing the bass, not the noisy top end), and
    # auto-range fights our own decimation, so the button only ever undid
    # good framing. Right-click -> View All is still there if wanted.
    pi.hideButtons()
    if title:
        pi.setTitle(title, color=MUTED, size='9pt')
    return pw, pi


class PlotPage(QtWidgets.QWidget):
    """Base page: owns named curves and optional problem-region overlays."""

    log_x = True

    def __init__(self, analysis, parent=None):
        super().__init__(parent)
        self.ana = analysis
        self.curves = {}          # key -> (item, label, colour)
        self.curve_plot = {}      # key -> the PlotItem it lives on
        self.order = []
        self.cursors = []
        self._problem_items = {'ap': [], 'eq': []}
        self._f0_lines = []
        self.dirty = True
        self.display_dirty = False
        self.on_curve_toggled = None      # set by MainWindow
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.body = lay

    # -- construction
    def add_curve(self, plot, key, label, x, y, colour, width=1, dash=False,
                  visible=True):
        # widths > 1 with antialiasing lose Qt's fast path (~8x slower to
        # paint), so 1 is the default and 2 is reserved for the live curves;
        # during slider drags MainWindow drops every pen to width 1 anyway
        pen = pg.mkPen(colour, width=width,
                       style=QtCore.Qt.DashLine if dash else QtCore.Qt.SolidLine)
        item = plot.plot(x, y, pen=pen, connect='finite')
        item.setVisible(visible)
        self.curves[key] = (item, label, colour)
        self.curve_plot[key] = plot
        self.order.append(key)
        return item

    def finish(self, plots, unit='dB'):
        """Add the readout line and the checkable legend under the plots.

        Called at the end of every page's __init__, once all curves exist.
        The legend replaces the old side-pane 'Curves' box: laid out as
        small wrapping checkboxes it costs two or three short rows instead
        of a column the height of the window, and the plot keeps the space.
        """
        self.readout = QtWidgets.QLabel()
        self.readout.setTextFormat(QtCore.Qt.RichText)
        self.readout.setStyleSheet(f'color: {MUTED};')
        f = self.readout.font()
        f.setPointSizeF(max(6.5, f.pointSizeF() - 1))
        self.readout.setFont(f)
        self.readout.setText('move the pointer over the plot to read values '
                             '&nbsp;·&nbsp; click freezes &nbsp;·&nbsp; '
                             'Ctrl+click drops a marker (Ctrl+click it again '
                             'to remove)')
        self.body.addWidget(self.readout)

        legend = FlowWidget()
        flow = FlowLayout(legend, margin=0, spacing=8)
        for key in self.order:
            item, label, colour = self.curves[key]
            cb = QtWidgets.QCheckBox(label)
            cb.setChecked(item.isVisible())
            cbf = cb.font()
            cbf.setPointSizeF(max(6.5, cbf.pointSizeF() - 1))
            cb.setFont(cbf)
            cb.setStyleSheet(
                f'QCheckBox {{ color: {colour}; spacing: 3px; }}'
                'QCheckBox::indicator { width: 10px; height: 10px; }')
            cb.toggled.connect(item.setVisible)
            cb.toggled.connect(self._curve_checked)
            flow.addWidget(cb)
        self.body.addWidget(legend)
        self.legend_widget = legend

        for pi in plots:
            self.cursors.append(PlotCursor(self, pi, self.readout, unit, self))

    def _curve_checked(self, _on):
        if self.on_curve_toggled:
            self.on_curve_toggled(self)

    def set_data(self, key, x, y):
        self.curves[key][0].setData(x, y, connect='finite')

    def add_problem_overlay(self, pi):
        # narrow regions show up as their edge lines, so pen and brush
        # must be the same colour or they read as stray markers
        for a, b in getattr(self.ana, 'regions', []) or []:
            r = pg.LinearRegionItem(values=[np.log10(a), np.log10(b)],
                                    movable=False, brush=PROBLEM_BRUSH,
                                    pen=pg.mkPen(208, 59, 59, 110, width=1))
            r.setZValue(-100)
            pi.addItem(r)
            self._problem_items['ap'].append(r)
        if getattr(self.ana, 'region', None):
            a, b = self.ana.region
            txt = pg.TextItem(f'interference {a:.0f}-{b:.0f} Hz',
                              color=STATUS['critical'], anchor=(0.5, 0))
            txt.setPos(np.log10(np.sqrt(a * b)), 0)
            self._pin_top(pi, txt)
            pi.addItem(txt)
            self._problem_items['ap'].append(txt)
        for n, (fa, fb, kind, peak) in enumerate(
                getattr(self.ana, 'eq_regions', []) or []):
            r = pg.LinearRegionItem(values=[np.log10(fa), np.log10(fb)],
                                    movable=False,
                                    brush=pg.mkBrush(250, 178, 25, 40),
                                    pen=pg.mkPen(250, 178, 25, 110, width=1))
            r.setZValue(-100)
            pi.addItem(r)
            # neighbouring regions are close on a log axis: stagger the
            # labels vertically so they do not overprint each other
            txt = pg.TextItem(f'EQ: {kind} {fa:.0f}-{fb:.0f} Hz',
                              color=STATUS['warning'],
                              anchor=(0.5, 1 + 1.15 * (n % 2)))
            txt.setPos(np.log10(np.sqrt(fa * fb)), 0)
            self._pin_bottom(pi, txt)
            pi.addItem(txt)
            self._problem_items['eq'] += [r, txt]

    @staticmethod
    def _pin_top(pi, item):
        def place():
            rng = pi.vb.viewRange()
            item.setPos(item.pos().x(), rng[1][1])
        pi.vb.sigRangeChanged.connect(lambda *_: place())
        place()

    @staticmethod
    def _pin_bottom(pi, item):
        def place():
            rng = pi.vb.viewRange()
            item.setPos(item.pos().x(), rng[1][0])
        pi.vb.sigRangeChanged.connect(lambda *_: place())
        place()

    def add_f0_line(self, pi, f0, label=None):
        ln = pg.InfiniteLine(pos=np.log10(f0), angle=90,
                             pen=pg.mkPen(COL['T_corr'], width=2))
        if label:
            ln.label = pg.InfLineLabel(ln, label, position=0.92,
                                       color=COL['T_corr'])
        pi.addItem(ln)
        self._f0_lines.append(ln)
        return ln

    # -- interface used by the shell
    def set_problems_visible(self, kind, on):
        for it in self._problem_items[kind]:
            it.setVisible(on)

    def set_f0(self, f0):
        for ln in self._f0_lines:
            ln.setValue(np.log10(f0) if self.log_x else f0)

    def update_filter(self, f0, q, channel, Ht, Hc):
        """Redraw whatever depends on the live filter."""

    def refresh_static(self):
        """Redraw the static curves (after a smoothing/home change)."""

    def _refresh_home(self):
        """Re-set the home-curve data; 'Hide' empties it entirely."""
        if 'home' not in self.curves:
            return
        a = self.ana
        if a.home_mode == 'Hide':
            self.set_data('home', np.array([]), np.array([]))
        else:
            self.set_data('home', a.disp.x1, a.disp.sub(a.home))


class SpectrumPage(PlotPage):
    """Amplitude or phase of every response, overlaid."""

    def __init__(self, analysis, kind, parent=None):
        super().__init__(analysis, parent)
        self.kind = kind
        a = analysis
        ylabel = 'SPL (dB)' if kind == 'amp' else 'Phase (deg)'
        pw, pi = styled_plot(ylabel)
        self.body.addWidget(pw)
        self.pi = pi
        Hshow = a.Hmeas if a.Hmeas is not None else a.Hcalc
        meas_label = ('L+R measured' if a.Hmeas is not None
                      else 'L+R measured (MISSING)')

        z = np.array([])
        self._src = {'L': a.HL, 'R': a.HR, 'S_meas': Hshow, 'S_calc': a.Hcalc}
        self.add_curve(pi, 'L', 'L', z, z, COL['L'])
        self.add_curve(pi, 'R', 'R', z, z, COL['R'])
        self.add_curve(pi, 'S_meas', meas_label, z, z, COL['S_meas'],
                       visible=(kind == 'amp'))
        self.add_curve(pi, 'S_calc', 'L+R calculated', z, z,
                       COL['S_calc'], dash=True, visible=(kind == 'amp'))
        if kind == 'amp':
            self.add_curve(pi, 'target', 'coherent ceiling (1/3-oct |L|+|R|)',
                           a.disp.x1, a.disp.sub(a.target), COL['target'],
                           width=2, dash=True)
            self.add_curve(pi, 'home', 'home target curve',
                           a.disp.x1, a.disp.sub(a.home), COL['home'],
                           width=2, dash=True)
        else:
            self.add_curve(pi, 'T_corr', 'target channel x all-pass (live)',
                           z, z, COL['T_corr'], width=2)
        # each channel with its own filters, so the effect of a per-channel
        # EQ can be seen on the channel it acts on and not only in the sum
        self.add_curve(pi, 'L_corr', 'L corrected (own filters)', z, z,
                       COL['L_corr'], visible=False)
        self.add_curve(pi, 'R_corr', 'R corrected (own filters)', z, z,
                       COL['R_corr'], visible=False)
        self.add_curve(pi, 'S_corr', 'L+R corrected (live)', z, z,
                       COL['S_corr'], width=2)
        self.add_curve(pi, 'S_eq', 'L+R corrected + auto EQ', z, z,
                       COL['extra'], width=2)
        self.refresh_static()

        self.add_problem_overlay(pi)
        self.add_f0_line(pi, a.f0_est, 'f0')
        pi.setXRange(np.log10(15), np.log10(1000))
        if kind == 'phase':
            pi.setYRange(-190, 190)
        else:
            # frame the bass, not the noisy top end that autoscaling picks up
            w = (a.f >= 15) & (a.f <= 1000)
            vals = np.concatenate([mag_db(a.HL[w]), mag_db(a.HR[w]),
                                   mag_db(a.Hcalc[w])])
            pi.setYRange(np.percentile(vals, 0.5) - 4, vals.max() + 4)
        self.finish([pi], 'dB' if kind == 'amp' else 'deg')

    def refresh_static(self):
        a = self.ana
        for key, H in self._src.items():
            if self.kind == 'amp':
                self.set_data(key, a.disp.x2, a.disp_amp(H))
            else:
                self.set_data(key, a.disp_p.x1, a.disp_ph(H))
        self._refresh_home()

    def add_extra(self, key, label, H, colour):
        a = self.ana
        self._src[key] = H
        if self.kind == 'amp':
            self.add_curve(self.pi, key, label, a.disp.x2, a.disp_amp(H),
                           colour, width=2)
        else:
            self.add_curve(self.pi, key, label, a.disp_p.x1, a.disp_ph(H),
                           colour, width=2)

    def update_filter(self, f0, q, channel, Ht, Hc):
        a = self.ana
        Heq = a.eq_applied(f0, q, channel)
        # only compute the per-channel curves when someone is looking at them
        want_ch = any(self.curves[k][0].isVisible()
                      for k in ('L_corr', 'R_corr'))
        HLc, HRc = (a.channels_corrected(f0, q, channel) if want_ch
                    else (None, None))
        if self.kind == 'amp':
            self.set_data('S_corr', a.disp.x2, a.disp_amp(Hc))
            if want_ch:
                self.set_data('L_corr', a.disp.x2, a.disp_amp(HLc))
                self.set_data('R_corr', a.disp.x2, a.disp_amp(HRc))
            if Heq is None:
                self.set_data('S_eq', np.array([]), np.array([]))
            else:
                self.set_data('S_eq', a.disp.x2, a.disp_amp(Heq))
        else:
            self.set_data('T_corr', a.disp_p.x1, a.disp_ph(Ht))
            self.set_data('S_corr', a.disp_p.x1, a.disp_ph(Hc))
            if want_ch:
                self.set_data('L_corr', a.disp_p.x1, a.disp_ph(HLc))
                self.set_data('R_corr', a.disp_p.x1, a.disp_ph(HRc))
            if Heq is None:
                self.set_data('S_eq', np.array([]), np.array([]))
            else:
                self.set_data('S_eq', a.disp_p.x1, a.disp_ph(Heq))


class EvidencePage(PlotPage):
    """Why this f0: phase difference through 180 deg, and the coherence dip."""

    def __init__(self, analysis, parent=None):
        super().__init__(analysis, parent)
        a = analysis
        pw1, pi1 = styled_plot('phi(L) - phi(R)  (deg)',
                               'full opposition = +-180 deg: the channels '
                               'cancel where this curve touches the dashed lines')
        pw2, pi2 = styled_plot('|L+R| / (|L|+|R|)',
                               '1 = perfectly in phase, 0 = complete cancellation')
        pi2.setXLink(pi1)
        self.body.addWidget(pw1, 3)
        self.body.addWidget(pw2, 2)

        d = a.disp
        dphi0 = a.disp_ph(a.HL * np.conj(a.HR), remove_delay=False)
        self.add_curve(pi1, 'dphi', 'L-R phase difference', a.disp_p.x1,
                       dphi0, COL['S_meas'])
        self.add_curve(pi1, 'dphi_corr', 'phase difference after all-pass',
                       a.disp_p.x1, dphi0, COL['S_corr'], width=2)
        for yv in (180.0, -180.0):
            pi1.addItem(pg.InfiniteLine(
                pos=yv, angle=0, pen=pg.mkPen(STATUS['critical'], width=1,
                                              style=QtCore.Qt.DashLine)))
        self.add_curve(pi2, 'G', 'coherence', d.x2, d.env(a.G), COL['S_meas'])
        self.add_curve(pi2, 'G_corr', 'coherence after all-pass', d.x2,
                       d.env(a.G), COL['S_corr'], width=2)

        for pi in (pi1, pi2):
            self.add_problem_overlay(pi)
            self.add_f0_line(pi, a.f0_est)
        if getattr(a, 'f0_opposition', None):
            for pi in (pi1, pi2):
                pi.addItem(pg.InfiniteLine(
                    pos=np.log10(a.f0_opposition), angle=90,
                    pen=pg.mkPen(COL['target'], width=1,
                                 style=QtCore.Qt.DotLine)))
        pi1.setXRange(np.log10(15), np.log10(1000))
        pi1.setYRange(-200, 200)
        pi2.setYRange(0, 1.05)
        self.finish([pi1, pi2], 'deg')

    def refresh_static(self):
        # smoothed phase difference = phase of the smoothed cross-spectrum.
        # A delay common to both channels cancels in the product, so no
        # delay removal here - applying it would tilt the difference.
        a = self.ana
        self.set_data('dphi', a.disp_p.x1,
                      a.disp_ph(a.HL * np.conj(a.HR), remove_delay=False))

    def update_filter(self, f0, q, channel, Ht, Hc):
        a = self.ana
        other = a.HR if channel == 'L' else a.HL
        self.set_data('dphi_corr', a.disp_p.x1,
                      a.disp_ph(Ht * np.conj(other), remove_delay=False))
        self.set_data('G_corr', a.disp.x2,
                      a.disp.env(np.abs(Hc) / (np.abs(a.HL) + np.abs(a.HR))))


class FilterPage(PlotPage):
    """The all-pass on its own: magnitude, phase, group delay."""

    def __init__(self, analysis, parent=None):
        super().__init__(analysis, parent)
        self.fg = np.logspace(np.log10(5), np.log10(2000), 1500)
        pw1, pi1 = styled_plot('|H| (dB)', 'an all-pass is flat by '
                               'construction: only the phase moves')
        pw2, pi2 = styled_plot('phase (deg)',
                               'the filter passes -180 deg exactly at f0 and '
                               'reaches -360 deg overall')
        pw3, pi3 = styled_plot('group delay (ms)',
                               'how late each frequency comes out: the peak '
                               'sits at f0 and equals 4Q/w0')
        for pi in (pi2, pi3):
            pi.setXLink(pi1)
        self.body.addWidget(pw1, 2)
        self.body.addWidget(pw2, 3)
        self.body.addWidget(pw3, 4)
        self.pi_mag = pi1

        f0, q = analysis.f0_est, analysis.q_est
        H = allpass_h(self.fg, f0, q)
        self.add_curve(pi1, 'mag', '|H| all-pass', self.fg, mag_db(H),
                       COL['T_corr'], width=2)
        self.add_curve(pi2, 'phase', 'all-pass phase', self.fg,
                       np.degrees(np.unwrap(np.angle(H))), COL['T_corr'],
                       width=2)
        self.add_curve(pi3, 'gd', 'all-pass group delay', self.fg,
                       group_delay(self.fg, f0, q) * 1000.0, COL['T_corr'],
                       width=2)
        for yv, pi in ((-180.0, pi2), (-360.0, pi2)):
            pi.addItem(pg.InfiniteLine(pos=yv, angle=0,
                                       pen=pg.mkPen(MUTED, width=1,
                                                    style=QtCore.Qt.DashLine)))
        self.marker = pg.ScatterPlotItem(size=10, brush=pg.mkBrush(STATUS['warning']),
                                         pen=pg.mkPen(SURFACE, width=2))
        pi3.addItem(self.marker)
        self.gd_text = pg.TextItem(color=STATUS['warning'], anchor=(0, 1))
        pi3.addItem(self.gd_text)
        self.ph_marker = pg.ScatterPlotItem(size=10, brush=pg.mkBrush(STATUS['warning']),
                                            pen=pg.mkPen(SURFACE, width=2))
        pi2.addItem(self.ph_marker)
        self.ph_text = pg.TextItem(color=STATUS['warning'], anchor=(0, 0))
        pi2.addItem(self.ph_text)
        for pi in (pi1, pi2, pi3):
            self.add_f0_line(pi, f0, 'f0')
        pi1.setXRange(np.log10(10), np.log10(1000))
        pi1.setYRange(-1.0, 1.0)
        pi2.setYRange(-370, 10)
        self.finish([pi1, pi2, pi3], '')

    def add_extra(self, key, label, H_on_f, colour):
        """Overlay an imported filter (given on the measurement grid)."""
        self.add_curve(self.pi_mag, key, label, self.ana.disp.x2,
                       self.ana.disp.env(mag_db(H_on_f)), colour, width=2)

    def update_filter(self, f0, q, channel, Ht, Hc):
        H = allpass_h(self.fg, f0, q)
        self.set_data('mag', self.fg, mag_db(H))
        self.set_data('phase', self.fg, np.degrees(np.unwrap(np.angle(H))))
        gd = group_delay(self.fg, f0, q) * 1000.0
        self.set_data('gd', self.fg, gd)
        gd0 = gd_at_f0(f0, q) * 1000.0
        self.marker.setData([np.log10(f0)], [gd0])
        self.gd_text.setPos(np.log10(f0 * 1.06), gd0)
        self.gd_text.setText(f'{gd0:.0f} ms at f0 = {gd0*1e-3*f0:.2f} cycles')
        self.ph_marker.setData([np.log10(f0)], [-180.0])
        self.ph_text.setPos(np.log10(f0 * 1.06), -180.0)
        self.ph_text.setText('-180 deg at f0')


class RingingPage(PlotPage):
    """Bass smearing: a narrow-band bass event before and after the filter."""

    log_x = False

    def __init__(self, analysis, parent=None):
        super().__init__(analysis, parent)
        pw1, pi1 = styled_plot('envelope (dB)',
                               'a 1/3-octave tone burst at f0: how much later '
                               'and how much longer it comes out',
                               log_x=False)
        pw2, pi2 = styled_plot('amplitude', 'the same burst as a waveform',
                               log_x=False)
        pi2.setXLink(pi1)
        for pi in (pi1, pi2):
            pi.setLabel('bottom', 'Time (ms)')
        self.body.addWidget(pw1, 3)
        self.body.addWidget(pw2, 2)

        t, x, y, ex, ey, *_ = burst_response(analysis.f0_est, analysis.q_est)
        self.add_curve(pi1, 'env_in', 'envelope in', t, ex, COL['neutral'],
                       width=2, dash=True)
        self.add_curve(pi1, 'env_out', 'envelope out (live)', t, ey,
                       COL['S_corr'], width=2)
        self.add_curve(pi2, 'wav_in', 'waveform in', t, x, COL['neutral'],
                       width=1, dash=True)
        self.add_curve(pi2, 'wav_out', 'waveform out (live)', t, y,
                       COL['S_corr'], width=2)
        self.arrow = pg.PlotDataItem(pen=pg.mkPen(STATUS['warning'], width=2))
        pi1.addItem(self.arrow)
        self.note = pg.TextItem(color=STATUS['warning'], anchor=(0.5, 1))
        pi1.addItem(self.note)
        pi1.setYRange(-60, 3)
        self.pi1 = pi1
        self.finish([pi1, pi2], '')

    def update_filter(self, f0, q, channel, Ht, Hc):
        t, x, y, ex, ey, delay, drop, t60 = burst_response(f0, q)
        self.set_data('env_in', t, ex)
        self.set_data('env_out', t, ey)
        self.set_data('wav_in', t, x)
        self.set_data('wav_out', t, y)
        self.arrow.setData([0.0, delay], [-3.0, -3.0])
        self.note.setPos(delay / 2.0, -3.0)
        t60_txt = f'{t60:.0f} ms' if np.isfinite(t60) else 'n/a'
        self.note.setText(f'peak {delay:.0f} ms late,  '
                          f'{drop:+.1f} dB peak level,  '
                          f'decay T60 {t60_txt}')
        span = t60 if np.isfinite(t60) else 6.0 * ringing_t60(f0, q) * 1000.0
        self.pi1.setXRange(-3.0 / f0 * 1000, delay + 1.5 * span)


class DualPage(PlotPage):
    """Amplitude and phase of a single response, stacked."""

    def __init__(self, analysis, title, colour, H=None, live=False, parent=None):
        super().__init__(analysis, parent)
        self.live = live
        self.title = title
        pw1, pi1 = styled_plot('SPL (dB)', title)
        pw2, pi2 = styled_plot('phase (deg)')
        pi2.setXLink(pi1)
        self.body.addWidget(pw1, 3)
        self.body.addWidget(pw2, 2)
        self.pi1 = pi1
        H = analysis.Hcalc if H is None else H
        self._H = H
        d = analysis.disp
        self.add_curve(pi1, 'amp', 'amplitude', d.x2, analysis.disp_amp(H),
                       colour)
        self.add_curve(pi2, 'phase', 'phase', analysis.disp_p.x1, analysis.disp_ph(H),
                       colour, width=1)
        if live:
            self.add_curve(pi1, 'target', 'coherent ceiling', d.x1,
                           d.sub(analysis.target), COL['target'], dash=True)
            self.add_curve(pi1, 'home', 'home target curve', d.x1,
                           d.sub(analysis.home), COL['home'], width=2,
                           dash=True)
        for pi in (pi1, pi2):
            self.add_problem_overlay(pi)
            self.add_f0_line(pi, analysis.f0_est)
        pi1.setXRange(np.log10(15), np.log10(1000))
        pi2.setYRange(-190, 190)
        w = (analysis.f >= 15) & (analysis.f <= 1000)
        v = mag_db(H[w])
        pi1.setYRange(np.percentile(v, 0.5) - 4, v.max() + 4)
        self.finish([pi1, pi2], 'dB')

    def refresh_static(self):
        a = self.ana
        if not self.live:
            self.set_data('amp', a.disp.x2, a.disp_amp(self._H))
            self.set_data('phase', a.disp_p.x1, a.disp_ph(self._H))
        self._refresh_home()

    def update_filter(self, f0, q, channel, Ht, Hc):
        if not self.live:
            return
        a = self.ana
        self.set_data('amp', a.disp.x2, a.disp_amp(Hc))
        self.set_data('phase', a.disp_p.x1, a.disp_ph(Hc))
        self.pi1.setTitle(f'{self.title}: all-pass on {channel}, '
                          f'f0={f0:.1f} Hz, Q={q:.2f}', color=MUTED, size='9pt')


# ---------------------------------------------------------------------------
# controls

class SliderSpin(QtWidgets.QWidget):
    """Logarithmic slider tied to a spin box; both stay in sync."""

    valueChanged = QtCore.Signal(float)
    editingDone = QtCore.Signal()
    dragStarted = QtCore.Signal()

    def __init__(self, label, lo, hi, value, decimals, step, unit='',
                 parent=None):
        super().__init__(parent)
        self.lo, self.hi = lo, hi
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lab = QtWidgets.QLabel(label)
        lab.setMinimumWidth(18)
        lay.addWidget(lab)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, SLIDER_STEPS)
        self.spin = QtWidgets.QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setKeyboardTracking(False)
        if unit:
            self.spin.setSuffix(' ' + unit)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)
        self._guard = False
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        self.slider.sliderPressed.connect(self.dragStarted)
        self.slider.sliderReleased.connect(self.editingDone)
        self.spin.editingFinished.connect(self.editingDone)
        self.set_value(value)

    def _pos(self, v):
        v = min(max(v, self.lo), self.hi)
        return int(round(SLIDER_STEPS * np.log(v / self.lo)
                         / np.log(self.hi / self.lo)))

    def _val(self, pos):
        return self.lo * (self.hi / self.lo) ** (pos / SLIDER_STEPS)

    def _from_slider(self, pos):
        if self._guard:
            return
        self._guard = True
        v = self._val(pos)
        self.spin.setValue(v)
        self._guard = False
        self.valueChanged.emit(v)

    def _from_spin(self, v):
        if self._guard:
            return
        self._guard = True
        self.slider.setValue(self._pos(v))
        self._guard = False
        self.valueChanged.emit(v)

    def set_value(self, v):
        self._guard = True
        self.spin.setValue(v)
        self.slider.setValue(self._pos(v))
        self._guard = False

    def value(self):
        return self.spin.value()


class ImportDialog(QtWidgets.QDialog):
    """Pick a file, say what it is and how it should be read."""

    ROLES = ['Filter to compare', 'Left channel', 'Right channel',
             'L+R measured', 'Reference curve']

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Import impulse response')
        self.path_edit = QtWidgets.QLineEdit()
        browse = QtWidgets.QPushButton('Browse…')
        browse.clicked.connect(self._browse)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)

        self.role = QtWidgets.QComboBox()
        self.role.addItems(self.ROLES)
        self.rate = QtWidgets.QComboBox()
        self.rate.addItems(SAMPLE_RATES)
        self.rate.setCurrentText(DEFAULT_RATE)
        self.fmt = QtWidgets.QComboBox()
        self.fmt.addItems(list(audio_io.RAW_FORMATS))
        self.chan = QtWidgets.QSpinBox()
        self.chan.setRange(1, 8)
        self.info = QtWidgets.QLabel('WAV files carry their own rate and '
                                     'format; those settings apply to RAW.')
        self.info.setWordWrap(True)
        self.info.setStyleSheet(f'color: {MUTED};')

        form = QtWidgets.QFormLayout(self)
        form.addRow('File:', row)
        form.addRow('Import as:', self.role)
        form.addRow('RAW sample rate:', self.rate)
        form.addRow('RAW format:', self.fmt)
        form.addRow('RAW channels:', self.chan)
        form.addRow(self.info)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok
                                        | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _browse(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Impulse response', os.getcwd(),
            'Audio / IR (*.wav *.raw *.bin *.pcm *.txt *.dat);;All files (*)')
        if p:
            self.path_edit.setText(p)
            if not p.lower().endswith('.wav'):
                self.fmt.setCurrentText(audio_io.guess_raw_format(p))
                self.info.setText(f'Detected RAW format: '
                                  f'{self.fmt.currentText()} (adjust if wrong).')


class AutoEqDialog(QtWidgets.QDialog):
    """Propose parametric EQ toward the home curve, and preview it."""

    def __init__(self, ana, f0, q, channel, parent=None):
        super().__init__(parent)
        self.ana = ana
        self.ap = (f0, q, channel)
        self.Hc = ana.corrected(f0, q, channel)[1]
        self.filters = [dict(x) for x in ana.eq_filters]
        self.setWindowTitle('Auto EQ')
        self.resize(1120, 760)

        form = QtWidgets.QGridLayout()
        self.fmin = QtWidgets.QDoubleSpinBox()
        self.fmin.setRange(5, 20000)
        self.fmin.setValue(20)
        self.fmin.setSuffix(' Hz')
        self.fmax = QtWidgets.QDoubleSpinBox()
        self.fmax.setRange(20, 24000)
        self.fmax.setValue(500)
        self.fmax.setSuffix(' Hz')
        self.nmax = QtWidgets.QSpinBox()
        self.nmax.setRange(1, 20)
        self.nmax.setValue(6)
        self.boost = QtWidgets.QDoubleSpinBox()
        self.boost.setRange(0, 12)
        self.boost.setValue(3.0)
        self.boost.setSuffix(' dB')
        self.boost.setToolTip('0 disables boosts entirely - cuts only, which '
                              'costs no headroom and cannot excite a mode.')
        self.cut = QtWidgets.QDoubleSpinBox()
        self.cut.setRange(0, 24)
        self.cut.setValue(12.0)
        self.cut.setSuffix(' dB')
        self.smooth = QtWidgets.QComboBox()
        self.smooth.addItems([m for m in SMOOTH_OPTIONS if m != 'None'])
        self.smooth.setCurrentText('1/6')
        self.smooth.setToolTip('The response the fit sees. Fitting raw data '
                               'would chase narrow nulls that move with the '
                               'microphone.')
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(['Both channels (common)', 'L and R separately'])
        # Default to per-channel: the default band (20-500 Hz) is exactly
        # where L and R genuinely differ, and a common filter cannot reach
        # that difference at all. Above ~1-2 kHz the choice should be
        # reversed - see the tooltip.
        self.mode.setCurrentIndex(1)
        self.mode.setToolTip(
            'The right answer depends on frequency, so choose it to match '
            'the band above.\n\n'
            'Separately (default, correct below ~1 kHz): each channel '
            'corrected to the home curve on its own - the usual REW '
            'technique. L and R sit at different distances from the room '
            'boundaries, so they couple to the modes differently, and that\n'
            'difference is real and stable. A common filter cannot touch it. '
            'Being minimum phase, the two channels\' phase converges as '
            'their magnitude does, so coherence is preserved or slightly\n'
            'improved; the residual difference is excess phase, which is '
            'exactly what the all-pass is for. Requires the SAME target for '
            'both channels - different targets would break the all-pass.\n\n'
            'Common (correct above ~1-2 kHz): one filter set for both '
            'channels. Up there L and R barely differ, so separate fits '
            'chase measurement noise and one microphone position, and any\n'
            'difference between the two filters becomes an inter-channel '
            'level difference - about 1 dB of it is an audible image pull. '
            'Common EQ also provably cannot disturb the L-R phase\n'
            'difference, so the all-pass is untouched.\n\n'
            'The dialog reports the effect on coherence either way.')
        self.skip = QtWidgets.QCheckBox(
            'Never EQ the interference regions')
        self.skip.setChecked(True)
        self.skip.setToolTip('A cancellation between L and R is not a level '
                             'problem: EQ cannot fill it, it only burns '
                             'headroom. Leave this on.')
        for col, (lab, w) in enumerate([
                ('Apply to', self.mode), ('From', self.fmin), ('To', self.fmax),
                ('Max filters', self.nmax), ('Max boost', self.boost),
                ('Max cut', self.cut), ('Fit on', self.smooth)]):
            form.addWidget(QtWidgets.QLabel(lab), 0, col)
            form.addWidget(w, 1, col)
        form.addWidget(self.skip, 1, 7)
        self.compute_btn = QtWidgets.QPushButton('Compute')
        form.addWidget(self.compute_btn, 1, 8)

        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ['on', 'ch', 'Fc (Hz)', 'Gain (dB)', 'Q', 'rings'])
        self.table.horizontalHeaderItem(5).setToolTip(
            'T60 of the filter, 2.2*Q/f0.\n'
            'A BOOST is a resonance and ADDS this much decay - it will show '
            'up in an RT60 measurement.\n'
            'A CUT at a room mode is the mode\'s inverse and TAKES decay '
            'away, so a long number on a cut is a good thing.')
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QTableWidget.SelectRows)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.setMaximumWidth(340)

        pw, pi = styled_plot('SPL (dB)', 'before and after, against the home curve')
        self.pi = pi
        d = ana.disp
        self.c_before = pi.plot(d.x2, np.zeros(len(d.x2)),
                                pen=pg.mkPen(COL['S_corr'], width=1),
                                connect='finite')
        self.c_after = pi.plot(d.x2, np.zeros(len(d.x2)),
                               pen=pg.mkPen(COL['extra'], width=2),
                               connect='finite')
        self.c_home = pi.plot(d.x1, d.sub(ana.home),
                              pen=pg.mkPen(COL['home'], width=2,
                                           style=QtCore.Qt.DashLine))
        self.c_eq = pi.plot(d.x1, np.zeros(len(d.x1)),
                            pen=pg.mkPen(COL['target'], width=2))
        # each channel carrying its own filters. Without these the dialog
        # shows only the sum, which hides what a per-channel fit actually
        # did to the channel it acts on.
        self.c_L = pi.plot(d.x2, np.zeros(len(d.x2)),
                           pen=pg.mkPen(COL['L_corr'], width=1),
                           connect='finite')
        self.c_R = pi.plot(d.x2, np.zeros(len(d.x2)),
                           pen=pg.mkPen(COL['R_corr'], width=1),
                           connect='finite')
        self.cb_split = QtWidgets.QCheckBox('Show L and R separately')
        self.cb_split.setToolTip(
            'Each channel with its own filters (the common ones plus the '
            'ones addressed to it) and, on the target channel, the '
            'all-pass. This is what each amplifier will receive.')
        self.cb_split.setChecked(False)
        self.c_L.setVisible(False)
        self.c_R.setVisible(False)
        for a, b in ana.regions or []:
            r = pg.LinearRegionItem(values=[np.log10(a), np.log10(b)],
                                    movable=False, brush=PROBLEM_BRUSH,
                                    pen=pg.mkPen(208, 59, 59, 110, width=1))
            r.setZValue(-100)
            pi.addItem(r)
        pi.setXRange(np.log10(15), np.log10(1000))
        legend = QtWidgets.QLabel(
            f'<span style="color:{COL["S_corr"]}">&#9644; before</span> &nbsp; '
            f'<span style="color:{COL["extra"]}">&#9644; after EQ</span> &nbsp; '
            f'<span style="color:{COL["home"]}">&#9644; home curve</span> &nbsp; '
            f'<span style="color:{COL["target"]}">&#9644; EQ response</span> &nbsp; '
            f'<span style="color:{COL["L_corr"]}">&#9644; L</span>&nbsp;'
            f'<span style="color:{COL["R_corr"]}">&#9644; R corrected</span> &nbsp; '
            f'<span style="color:{STATUS["critical"]}">&#9644; interference '
            '(never EQ\'d)</span>')

        self.placement = QtWidgets.QLabel()
        self.placement.setWordWrap(True)
        self.placement.setStyleSheet(f'color: {MUTED};')

        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)

        mid = QtWidgets.QHBoxLayout()
        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel('Filters (right-click to remove):'))
        left.addWidget(self.table, 1)
        mid.addLayout(left)
        right = QtWidgets.QVBoxLayout()
        legrow = QtWidgets.QHBoxLayout()
        legrow.setContentsMargins(0, 0, 0, 0)
        legrow.addWidget(legend)
        legrow.addStretch(1)
        legrow.addWidget(self.cb_split)
        right.addLayout(legrow)
        right.addWidget(pw, 1)
        mid.addLayout(right, 1)

        bb = QtWidgets.QDialogButtonBox()
        self.apply_btn = bb.addButton('Apply', QtWidgets.QDialogButtonBox.AcceptRole)
        self.exp_btn = bb.addButton('Export…', QtWidgets.QDialogButtonBox.ActionRole)
        bb.addButton(QtWidgets.QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)

        details = QtWidgets.QWidget()
        dl = QtWidgets.QVBoxLayout(details)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.addWidget(self.summary)
        dl.addWidget(self.placement)
        self.details = CollapsibleSection('Details', details)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(mid, 1)
        lay.addWidget(self.details)
        lay.addWidget(bb)

        self.compute_btn.clicked.connect(self.compute)
        self.cb_split.toggled.connect(lambda _on: self._refresh())
        self.exp_btn.clicked.connect(self._export)
        self.table.itemChanged.connect(self._table_edited)
        self.table.customContextMenuRequested.connect(self._menu)
        if self.filters:
            self._refresh()
        else:
            self.compute()

    # ---- fitting
    def compute(self):
        a = self.ana
        mode = self.smooth.currentText()
        mask = a.eq_mask(self.fmin.value(), self.fmax.value(),
                         self.skip.isChecked())
        kw = dict(n_max=self.nmax.value(), max_boost=self.boost.value(),
                  max_cut=self.cut.value())
        shape = a.home - a.home_anchor - a.home_trim   # level-free shape

        if self.mode.currentIndex() == 0:
            err = a.home - smoothed_db(a.f, self.Hc, mode)
            self.filters = fit_auto_eq(a.f, err, mask, **kw)
            for flt in self.filters:
                flt['ch'] = 'both'
        else:
            self.filters = []
            for ch, H in (('L', a.HL), ('R', a.HR)):
                # each channel corrected to the home curve at its own level
                tgt = anchored_home(a.f, shape, H)
                got = fit_auto_eq(a.f, tgt - smoothed_db(a.f, H, mode),
                                  mask, **kw)
                for flt in got:
                    flt['ch'] = ch
                self.filters += got
        self._refresh()

    def _refresh(self):
        a = self.ana
        t = self.table
        blocked = t.blockSignals(True)
        t.setRowCount(len(self.filters))
        for row, flt in enumerate(self.filters):
            chk = QtWidgets.QTableWidgetItem()
            chk.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
            chk.setCheckState(QtCore.Qt.Checked if flt.get('on', True)
                              else QtCore.Qt.Unchecked)
            t.setItem(row, 0, chk)
            ch = flt.get('ch', 'both')
            rings = ring_ms(flt['f0'], flt['q'])
            boost = flt['gain'] > 0
            for col, val in ((1, ch), (2, f'{flt["f0"]:.1f}'),
                             (3, f'{flt["gain"]:+.2f}'), (4, f'{flt["q"]:.3f}'),
                             (5, f'{rings:+.0f} ms' if boost
                                 else f'-{rings:.0f} ms')):
                it = QtWidgets.QTableWidgetItem(val)
                if col == 3 and boost:
                    it.setForeground(QtGui.QColor(STATUS['warning']))
                if col == 5:
                    # a boost ADDS this decay, a cut removes it
                    it.setForeground(QtGui.QColor(
                        STATUS['critical'] if boost and rings > 150
                        else STATUS['warning'] if boost
                        else STATUS['good']))
                    it.setToolTip(
                        f'this boost adds about {rings:.0f} ms of decay'
                        if boost else
                        f'this cut takes about {rings:.0f} ms of decay away')
                if col == 1:
                    it.setForeground(QtGui.QColor(
                        COL.get(ch, COL['neutral']) if ch in ('L', 'R')
                        else MUTED))
                if col == 5:                   # derived, not editable
                    it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
                t.setItem(row, col, it)
        t.resizeColumnsToContents()
        t.blockSignals(blocked)

        # rebuild the sum the way the signal chain does: per-channel EQ acts
        # before the summation, so it cannot simply scale the summed response
        f0, q, apch = self.ap
        mode = self.smooth.currentText()
        keep = a.eq_filters
        a.eq_filters = self.filters
        try:
            HL2, HR2 = a.eq_channels()
            Heq = a.eq_applied(f0, q, apch)
            HLc, HRc = a.channels_corrected(f0, q, apch)
        finally:
            a.eq_filters = keep
        Heq = self.Hc if Heq is None else Heq
        before = smoothed_db(a.f, self.Hc, mode)
        after = smoothed_db(a.f, Heq, mode)
        self.c_before.setData(a.disp.x2, a.disp.env(before))
        self.c_after.setData(a.disp.x2, a.disp.env(after))
        show_split = self.cb_split.isChecked()
        self.c_L.setVisible(show_split)
        self.c_R.setVisible(show_split)
        if show_split:
            self.c_L.setData(a.disp.x2,
                             a.disp.env(smoothed_db(a.f, HLc, mode)))
            self.c_R.setData(a.disp.x2,
                             a.disp.env(smoothed_db(a.f, HRc, mode)))
        self.c_home.setData(a.disp.x1, a.disp.sub(a.home))
        self.c_eq.setData(a.disp.x1, a.disp.sub(
            after - before + a.home_anchor + a.home_trim))

        band = a.eq_mask(self.fmin.value(), self.fmax.value(),
                         self.skip.isChecked())
        if band.any():
            d0 = np.sqrt(np.mean((before[band] - a.home[band]) ** 2))
            d1 = np.sqrt(np.mean((after[band] - a.home[band]) ** 2))
        else:
            d0 = d1 = float('nan')
        boosts = [x for x in self.filters if x.get('on', True) and x['gain'] > 0]
        head = max([x['gain'] for x in boosts], default=0.0)

        # what the EQ did to the inter-channel phase - the thing the all-pass
        # depends on. Zero for common EQ, small but real for per-channel EQ.
        d_before = np.degrees(np.angle(a.HL * np.conj(a.HR)))
        d_after = np.degrees(np.angle(HL2 * np.conj(HR2)))
        sel = band & (a.f >= 25)
        dphi = (np.abs(wrap180(d_after - d_before))[sel]
                if sel.any() else np.array([0.0]))
        g0 = np.abs(a.HL + a.HR) / (np.abs(a.HL) + np.abs(a.HR))
        g1 = np.abs(HL2 + HR2) / (np.abs(HL2) + np.abs(HR2))
        nul = ((a.f >= a.region[0]) & (a.f <= a.region[1])) if a.region else sel
        phase_txt = (
            'Common EQ: the L-R phase difference is mathematically untouched, '
            'so the all-pass is unaffected.'
            if self.mode.currentIndex() == 0 else
            f'Per-channel EQ moves the L-R phase difference by '
            f'{np.mean(dphi):.1f}° mean / {np.max(dphi):.1f}° peak, and the '
            f'coherence in the null from {g0[nul].min():.3f} to '
            f'{g1[nul].min():.3f}. Re-check the all-pass afterwards.')

        self.placement.setText(
            'One filter set for <b>both</b> channels (master / sub bus). '
            'Order against the all-pass does not matter - filters commute - '
            'and neither does this EQ touch the L-R phase difference.'
            if self.mode.currentIndex() == 0 else
            'Each channel gets <b>its own</b> filter set - the usual REW '
            'technique. Export writes one file per channel. This does shift '
            'the L-R phase difference, but only by the part that follows the '
            'magnitude: both channels are corrected to the same home curve, '
            'so being minimum phase their phase converges as their magnitude '
            'does. What is left is excess phase - the all-pass\'s job.')
        self.summary.setText(
            f'{sum(1 for x in self.filters if x.get("on", True))} filters. '
            f'Deviation from the home curve over the EQ band: '
            f'{d0:.2f} → {d1:.2f} dB RMS. '
            + (f'{len(boosts)} boost(s), largest {head:+.1f} dB - reduce the '
               'level by that much to keep the headroom you had. '
               if boosts else 'Cuts only: no headroom lost. ')
            + ('Interference regions excluded. ' if self.skip.isChecked() else
               'WARNING: interference regions are being EQ\'d - a '
               'cancellation cannot be filled by EQ. ')
            + phase_txt)

    # ---- table interaction
    def _table_edited(self, item):
        row, col = item.row(), item.column()
        if row >= len(self.filters):
            return
        flt = self.filters[row]
        # columns are: 0 on | 1 ch | 2 Fc | 3 gain | 4 Q | 5 rings (derived).
        # These indices were off by one, so editing Fc silently rewrote the
        # gain and editing the gain rewrote Q.
        try:
            if col == 0:
                flt['on'] = item.checkState() == QtCore.Qt.Checked
            elif col == 1:
                ch = item.text().strip().lower()
                flt['ch'] = {'l': 'L', 'r': 'R'}.get(ch, 'both')
            elif col == 2:
                flt['f0'] = max(1.0, float(item.text()))
            elif col == 3:
                flt['gain'] = float(item.text())
            elif col == 4:
                flt['q'] = max(0.05, float(item.text()))
        except ValueError:
            pass
        self._refresh()

    def _menu(self, pos):
        row = self.table.rowAt(pos.y())
        if not 0 <= row < len(self.filters):
            return
        menu = QtWidgets.QMenu(self)
        act = menu.addAction('Remove this filter')
        if menu.exec(self.table.viewport().mapToGlobal(pos)) is act:
            self.filters.pop(row)
            self._refresh()

    def _export(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'Export filters', os.path.join(os.getcwd(), 'auto_eq.txt'),
            'REW filter settings (*.txt);;All files (*)')
        if not path:
            return
        note = (f'Auto EQ toward the {self.ana.home_mode} home curve, '
                f'{self.fmin.value():.0f}-{self.fmax.value():.0f} Hz'
                + (', interference regions excluded'
                   if self.skip.isChecked() else ''))
        written = []
        if self.mode.currentIndex() == 0:
            write_rew_filters(path, self.filters, note)
            written.append(path)
        else:
            # one file per channel: a DSP loads them into different slots
            stem, ext = os.path.splitext(path)
            for ch in ('L', 'R'):
                sub = [x for x in self.filters
                       if x.get('ch', 'both') in ('both', ch)]
                if not sub:
                    continue
                p = f'{stem}_{ch}{ext or ".txt"}'
                write_rew_filters(
                    p, sub, f'{note} - {ch} channel only',
                    placement=(f'These filters go on the {ch} channel ONLY. '
                               'Per-channel EQ does shift the L-R phase '
                               'difference; being minimum phase it mostly '
                               'follows the magnitude the two channels now '
                               'share, but re-check the all-pass afterwards.'))
                written.append(p)
        if self.parent():
            n = sum(1 for x in self.filters if x.get('on', True))
            self.parent().logbox.appendPlainText(
                f'Exported {n} EQ filters -> ' + ', '.join(written)
                + ' (REW: EQ window > Open filter settings).')


class ExportDialog(QtWidgets.QDialog):
    """Container, sample format, rate and length for a filter export."""

    def __init__(self, f0, q, rate, taps, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Export filter')
        self.container = QtWidgets.QComboBox()
        self.container.addItems(['WAV', 'RAW', 'TXT'])
        self.fmt = QtWidgets.QComboBox()
        self.fmt.addItems(audio_io.WAV_FORMATS)
        self.rate = QtWidgets.QComboBox()
        self.rate.addItems(SAMPLE_RATES)
        self.rate.setCurrentText(str(rate))
        self.taps = QtWidgets.QComboBox()
        self.taps.setEditable(True)
        self.taps.addItems(['4096', '8192', '16384', '32768', '65536',
                            '131072', '262144'])
        self.taps.setCurrentText(str(taps))
        self.note = QtWidgets.QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f'color: {MUTED};')

        form = QtWidgets.QFormLayout(self)
        form.addRow('Container:', self.container)
        form.addRow('Sample format:', self.fmt)
        form.addRow('Sample rate:', self.rate)
        form.addRow('Taps:', self.taps)
        form.addRow(self.note)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok
                                        | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        for w in (self.container, self.rate, self.taps):
            (w.currentTextChanged if w is not self.taps
             else w.currentTextChanged).connect(self._refresh)
        self.f0, self.q = f0, q
        self._refresh()

    def _refresh(self, *_):
        self.fmt.setEnabled(self.container.currentText() != 'TXT')
        try:
            fs, n = int(self.rate.currentText()), int(self.taps.currentText())
        except ValueError:
            return
        need = ringing_t60(self.f0, self.q)
        self.note.setText(
            f'{n} taps at {fs} Hz = {n/fs*1000:.0f} ms. The filter tail needs '
            f'about {need*1000:.0f} ms to decay 60 dB'
            + ('.' if n / fs >= need else
               ' - the export would truncate it; use more taps.')
            + ' The impulse response starts at t=0 (causal, no added latency).')


# ---------------------------------------------------------------------------

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, ana):
        super().__init__()
        self.ana = ana
        self.setWindowTitle('All-pass phase cancellation study')
        self.resize(1500, 950)
        self._extra_n = 0

        # ---- pages
        self.pages = []
        self.stack = QtWidgets.QStackedWidget()
        Hshow = ana.Hmeas if ana.Hmeas is not None else ana.Hcalc
        specs = [
            ('Amplitude', SpectrumPage(ana, 'amp')),
            ('Phase', SpectrumPage(ana, 'phase')),
            ('Evidence: why this f0', EvidencePage(ana)),
            ('All-pass filter', FilterPage(ana)),
            ('Ringing / bass smearing', RingingPage(ana)),
            ('L', DualPage(ana, 'Left channel', COL['L'], ana.HL)),
            ('R', DualPage(ana, 'Right channel', COL['R'], ana.HR)),
            ('L+R measured', DualPage(ana, 'L+R measured', COL['S_meas'], Hshow)),
            ('L+R calculated', DualPage(ana, 'L+R calculated', COL['S_calc'],
                                        ana.Hcalc)),
            ('L+R corrected', DualPage(ana, 'L+R corrected', COL['S_corr'],
                                       ana.Hcalc, live=True)),
        ]
        self.page_list = QtWidgets.QListWidget()
        self.page_list.setMinimumHeight(230)
        self.page_list.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                                     QtWidgets.QSizePolicy.Fixed)
        for name, page in specs:
            page.on_curve_toggled = self._curve_toggled
            self.pages.append(page)
            self.stack.addWidget(page)
            self.page_list.addItem(name)
        self.page_list.setCurrentRow(0)
        self.page_list.setFixedHeight(
            self.page_list.sizeHintForRow(0) * self.page_list.count()
            + 2 * self.page_list.frameWidth() + 8)

        # ---- right pane
        right = QtWidgets.QWidget()
        right.setMinimumWidth(330)
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(6, 6, 6, 6)
        rl.setSpacing(8)

        rl.addWidget(self._label('Plot'))
        rl.addWidget(self.page_list)

        # curve visibility lives in the checkable legend under each plot,
        # not here: a column of checkboxes cost the full window height for
        # something a couple of wrapped rows carry.

        disp_box = QtWidgets.QGroupBox('Display')
        dbox = QtWidgets.QVBoxLayout(disp_box)
        dl = QtWidgets.QHBoxLayout()
        dbox.addLayout(dl)
        dl.addWidget(QtWidgets.QLabel('Smoothing:'))
        self.smooth_combo = QtWidgets.QComboBox()
        self.smooth_combo.addItems(SMOOTH_OPTIONS)
        self.smooth_combo.setToolTip(
            'Display only - the analysis, the optimiser and every export '
            'always use the unsmoothed data. Gaussian kernel, as REW.\n'
            'Variable (REW): 1/48 oct below 100 Hz, 1/6 at 1 kHz, 1/3 above '
            '10 kHz - almost no smoothing in the bass, by design, for EQ '
            'work.\n'
            'Psychoacoustic (REW): 1/3 oct below 100 Hz to 1/6 oct above '
            '1 kHz, cubic mean (peaks weigh more, like the ear).\n'
            'ERB: one auditory filter bandwidth - about an octave at 40 Hz, '
            'the strongest smoothing in the bass.')
        dl.addWidget(self.smooth_combo, 1)

        dl2 = QtWidgets.QHBoxLayout()
        dbox.addLayout(dl2)
        dl2.addWidget(QtWidgets.QLabel('Phase delay:'))
        self.delay_combo = QtWidgets.QComboBox()
        self.delay_combo.addItems(['Keep', 'Auto', 'Manual'])
        self.delay_combo.setToolTip(
            'Remove a constant delay from the displayed phase, the way REW '
            'offsets t=0.\nA bulk delay only makes the trace spiral; what is '
            'left after removing it is the excess phase, which is what tells '
            'you about the speaker and the room.\nThe L-R phase difference is '
            'deliberately left alone: a delay common to both channels '
            'cancels in it already.')
        dl2.addWidget(self.delay_combo, 1)
        self.delay_spin = QtWidgets.QDoubleSpinBox()
        self.delay_spin.setRange(-200.0, 200.0)
        self.delay_spin.setDecimals(3)
        self.delay_spin.setSingleStep(0.05)
        self.delay_spin.setSuffix(' ms')
        self.delay_spin.setValue(ana.delay_auto * 1000.0)
        self.delay_spin.setEnabled(False)
        self.delay_spin.setKeyboardTracking(False)
        dl2.addWidget(self.delay_spin)

        dl3 = QtWidgets.QHBoxLayout()
        dbox.addLayout(dl3)
        dl3.addWidget(QtWidgets.QLabel('Home level:'))
        self.home_lbl = QtWidgets.QLabel()
        self.home_lbl.setStyleSheet(f'color: {MUTED};')
        dl3.addWidget(self.home_lbl, 1)
        self.home_trim_spin = QtWidgets.QDoubleSpinBox()
        self.home_trim_spin.setRange(-30.0, 30.0)
        self.home_trim_spin.setDecimals(1)
        self.home_trim_spin.setSingleStep(0.5)
        self.home_trim_spin.setSuffix(' dB')
        self.home_trim_spin.setKeyboardTracking(False)
        self.home_trim_spin.setToolTip(
            'Level trim on top of the automatic anchor.\nThe anchor is the '
            '1-octave power average of the measured combination over '
            '200 Hz - 2 kHz.\nA jagged response reads higher to the eye than '
            'its average, because narrow deep nulls take up little width -\n'
            'so if the curve looks low, raise it here to taste.')
        dl3.addWidget(self.home_trim_spin)
        rl.addWidget(disp_box)

        ov = QtWidgets.QGroupBox('Overlays')
        ovl = QtWidgets.QVBoxLayout(ov)
        self.cb_problems = QtWidgets.QCheckBox('Interference regions (all-pass)')
        self.cb_problems.setChecked(True)
        self.cb_problems.setStyleSheet(f'color: {STATUS["critical"]};')
        ovl.addWidget(self.cb_problems)
        self.cb_eq = QtWidgets.QCheckBox('EQ candidates (bump / dip)')
        self.cb_eq.setChecked(True)
        self.cb_eq.setStyleSheet(f'color: {STATUS["warning"]};')
        ovl.addWidget(self.cb_eq)
        rl.addWidget(ov)

        fb = QtWidgets.QGroupBox('All-pass filter')
        fbl = QtWidgets.QVBoxLayout(fb)
        chan_row = QtWidgets.QHBoxLayout()
        chan_row.addWidget(QtWidgets.QLabel('Channel:'))
        self.chan_combo = QtWidgets.QComboBox()
        self.chan_combo.addItems(['L', 'R'])
        self.chan_combo.setCurrentText(ana.channel)
        chan_row.addWidget(self.chan_combo, 1)
        chan_row.addWidget(QtWidgets.QLabel('fs:'))
        self.rate_combo = QtWidgets.QComboBox()
        self.rate_combo.addItems(SAMPLE_RATES)
        self.rate_combo.setCurrentText(DEFAULT_RATE)
        chan_row.addWidget(self.rate_combo, 1)
        fbl.addLayout(chan_row)
        self.f0_ctl = SliderSpin('f0', *F0_RANGE, ana.f0_est, 1, 0.1, 'Hz')
        self.q_ctl = SliderSpin('Q', *Q_RANGE, ana.q_est, 2, 0.05)
        fbl.addWidget(self.f0_ctl)
        fbl.addWidget(self.q_ctl)
        fbl.addWidget(QtWidgets.QLabel(
            'Correction vs timing (pick a row):'))
        self.alt_table = QtWidgets.QTableWidget(0, 4)
        self.alt_table.setHorizontalHeaderLabels(
            ['give up', 'f0 (Hz)', 'Q', 'delay@f0'])
        self.alt_table.verticalHeader().setVisible(False)
        self.alt_table.setEditTriggers(QtWidgets.QTableWidget.NoEditTriggers)
        self.alt_table.setSelectionBehavior(QtWidgets.QTableWidget.SelectRows)
        self.alt_table.setSelectionMode(QtWidgets.QTableWidget.SingleSelection)
        self.alt_table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self._rebuild_alt_table()
        fbl.addWidget(self.alt_table)
        self.add_btn = QtWidgets.QPushButton('Add correction')
        self.add_btn.setToolTip('Add the current f0 / Q / channel to the '
                                'table, evaluated the same way as the '
                                'computed rows. Right-click a row to remove.')
        fbl.addWidget(self.add_btn)
        rl.addWidget(fb)

        self.score_lbl = QtWidgets.QLabel()
        self.score_lbl.setWordWrap(True)
        self.smear_lbl = QtWidgets.QLabel()
        self.smear_lbl.setWordWrap(True)
        self.smear_lbl.setTextFormat(QtCore.Qt.RichText)
        rl.addWidget(self.score_lbl)
        rl.addWidget(self.smear_lbl)
        rl.addStretch(1)

        # ---- log
        self.logbox = QtWidgets.QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setMaximumBlockCount(4000)
        self.logbox.setFont(mono_font(QtWidgets.QApplication.font()
                                      .pointSizeF()))
        for line in ana.log_lines:
            self.logbox.appendPlainText(line)
        self.log_section = CollapsibleSection('Log', self.logbox)
        self.log_section.toggled.connect(self._log_toggled)

        # the pane is taller than a short window: scroll it rather than let
        # the layout squeeze the sections on top of each other
        right_scroll = QtWidgets.QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(right)
        right_scroll.setFixedWidth(356)
        right_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        top = QtWidgets.QWidget()
        tl = QtWidgets.QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(self.stack, 1)
        tl.addWidget(right_scroll)
        split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        split.addWidget(top)
        split.addWidget(self.log_section)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 1)
        split.setSizes([740, 190])
        split.setCollapsible(1, False)   # the header row must stay reachable
        self.split = split
        self.setCentralWidget(split)

        self._build_menu()

        # ---- signals
        self.page_list.currentRowChanged.connect(self._page_changed)
        self.f0_ctl.valueChanged.connect(self._update)
        self.q_ctl.valueChanged.connect(self._update)
        self.chan_combo.currentTextChanged.connect(self._chan_changed)
        self.f0_ctl.dragStarted.connect(lambda: self._set_fast(True))
        self.q_ctl.dragStarted.connect(lambda: self._set_fast(True))
        self.f0_ctl.editingDone.connect(lambda: self._set_fast(False))
        self.q_ctl.editingDone.connect(lambda: self._set_fast(False))
        self.f0_ctl.editingDone.connect(self._log_state)
        self.q_ctl.editingDone.connect(self._log_state)
        self.cb_problems.toggled.connect(
            lambda on: self._problems_toggled('ap', on))
        self.cb_eq.toggled.connect(
            lambda on: self._problems_toggled('eq', on))
        self.alt_table.itemSelectionChanged.connect(self._alt_selected)
        self.alt_table.cellClicked.connect(self._apply_row)
        self.alt_table.customContextMenuRequested.connect(self._alt_menu)
        self.add_btn.clicked.connect(self._add_correction)
        self.smooth_combo.currentTextChanged.connect(self._smoothing_changed)
        self.delay_combo.currentTextChanged.connect(self._delay_mode_changed)
        self.delay_spin.valueChanged.connect(self._delay_value_changed)
        self.home_trim_spin.valueChanged.connect(self._home_trim_changed)
        self.rate_combo.currentTextChanged.connect(
            lambda r: self.logbox.appendPlainText(
                f'Working sample rate set to {r} Hz (affects generated impulse '
                'responses and export defaults; the analysis itself is '
                'rate independent).'))

        self.home_lbl.setText(f'{ana.home_anchor + ana.home_trim:.1f} dB')
        self._page_changed(0)
        self._update()
        self._log_state()

    # ---- construction helpers
    @staticmethod
    def _label(text):
        lab = QtWidgets.QLabel(text)
        lab.setStyleSheet('font-weight: bold;')
        return lab

    def _build_menu(self):
        m_file = self.menuBar().addMenu('&File')
        m_file.addAction('&Import impulse response…', self._import_ir)
        m_file.addSeparator()
        m_exp = m_file.addMenu('&Export')
        m_exp.addAction('All-pass filter (WAV / RAW / TXT)…', self._export_filter)
        m_exp.addSeparator()
        m_exp.addAction('All-pass frequency response (REW txt)…',
                        lambda: self._export_fr('ap'))
        m_exp.addAction('Corrected target channel (REW txt)…',
                        lambda: self._export_fr('target'))
        m_exp.addAction('Corrected L+R (REW txt)…', lambda: self._export_fr('sum'))
        m_exp.addAction('Calculated L+R, uncorrected (REW txt)…',
                        lambda: self._export_fr('calc'))
        m_exp.addAction('Coherent ceiling curve (REW txt)…',
                        lambda: self._export_fr('target_level'))
        m_exp.addAction('Home target curve (REW txt)…',
                        lambda: self._export_fr('home'))
        m_file.addSeparator()
        m_file.addAction('&Quit', self.close, 'Ctrl+Q')

        m_edit = self.menuBar().addMenu('&Edit')
        m_edit.addAction('&Auto EQ…', self._auto_eq, 'Ctrl+E')
        m_edit.addAction('Clear auto EQ', self._clear_eq)
        m_edit.addSeparator()
        m_home = m_edit.addMenu('&Target home curve')
        self.home_group = QtGui.QActionGroup(self)
        self.home_group.setExclusive(True)
        for mode in HOME_MODES:
            act = m_home.addAction(mode)
            act.setCheckable(True)
            act.setChecked(mode == self.ana.home_mode)
            act.triggered.connect(lambda _c=False, m=mode: self._home_changed(m))
            self.home_group.addAction(act)

        m_view = self.menuBar().addMenu('&View')
        self.act_log = m_view.addAction('Show &log', self._toggle_log_action)
        self.act_log.setCheckable(True)
        self.act_log.setChecked(True)
        self.act_log.setShortcut('Ctrl+L')
        m_view.addSeparator()
        m_view.addAction('&Larger text', lambda: self._bump_font(+1),
                         QtGui.QKeySequence.ZoomIn)
        m_view.addAction('&Smaller text', lambda: self._bump_font(-1),
                         QtGui.QKeySequence.ZoomOut)
        m_view.addAction('&Reset text size',
                         lambda: self._bump_font(0), 'Ctrl+0')

    # ---- view
    def _log_toggled(self, on):
        """Give the freed height to the plot, and take it back on expand."""
        if getattr(self, 'act_log', None) and self.act_log.isChecked() != on:
            self.act_log.setChecked(on)
        if not hasattr(self, 'split'):
            return
        total = sum(self.split.sizes())
        if on:
            keep = min(190, max(120, total // 5))
            self.split.setSizes([total - keep, keep])
        else:
            head = self.log_section.sizeHint().height()
            self.split.setSizes([total - head, head])

    def _toggle_log_action(self):
        self.log_section.set_expanded(self.act_log.isChecked())

    def _bump_font(self, step):
        app = QtWidgets.QApplication.instance()
        pt = UI_FONT_PT if step == 0 else app.font().pointSizeF() + step
        pt = set_ui_font(app, pt)
        self.logbox.setFont(mono_font(pt))
        self.logbox.appendPlainText(f'UI font size: {pt:g} pt.')

    # ---- right pane wiring
    def _page_changed(self, row):
        if row < 0:
            return
        self.stack.setCurrentIndex(row)
        page = self.pages[row]
        if page.display_dirty:
            page.refresh_static()
            page.update_filter(*self._filter_args())
            page.display_dirty = page.dirty = False
        elif page.dirty:
            page.update_filter(*self._filter_args())
            page.dirty = False

    def _curve_toggled(self, page):
        """Refill lazily-computed curves when one is switched on."""
        page.update_filter(*self._filter_args())

    def _set_fast(self, fast):
        """While a slider is held, paint every curve as a width-1 hairline
        without antialiasing (~8x cheaper); restore full quality on release."""
        if fast == getattr(self, '_fast', False):
            return
        self._fast = fast
        if fast:
            self._saved_pens = []
            for page in self.pages:
                for item, _label, _colour in page.curves.values():
                    pen = item.opts['pen']
                    self._saved_pens.append((item, pen, item.opts['antialias']))
                    fp = pg.mkPen(pen.color(), width=1, style=pen.style())
                    item.opts['antialias'] = False
                    item.setPen(fp)
        else:
            for item, pen, aa in getattr(self, '_saved_pens', []):
                item.opts['antialias'] = aa
                item.setPen(pen)
            self._saved_pens = []

    def _auto_eq(self):
        f0, q, ch = self._params()
        dlg = AutoEqDialog(self.ana, f0, q, ch, self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        self.ana.eq_filters = dlg.filters
        on = [x for x in dlg.filters if x.get('on', True)]
        per_channel = dlg.mode.currentIndex() == 1
        self.logbox.appendPlainText(
            f'Auto EQ fitted to the response after the all-pass on {ch} '
            f'(f0={f0:.1f} Hz, Q={q:.2f}): {len(on)} filters toward the '
            f'{self.ana.home_mode} home curve. Design order is all-pass '
            'first, then EQ - the all-pass changes the magnitude the EQ has '
            'to correct, but not the reverse. Order in the signal chain is '
            'free: the two filters commute.')
        for flt in on:
            self.logbox.appendPlainText(
                f'     {flt.get("ch", "both"):>4}  PK  Fc {flt["f0"]:7.1f} Hz  '
                f'Gain {flt["gain"]:+6.2f} dB  Q {flt["q"]:6.3f}')
        self.logbox.appendPlainText('     ' + (
            'Per-channel EQ: each channel corrected on its own. It does move '
            'the L-R phase difference, but being minimum phase the two '
            'channels\' phase converges as their magnitudes converge on the '
            'same target - see the dialog for the measured effect. Re-check '
            'the all-pass afterwards.' if per_channel else
            'Common to both channels: the phase shift is identical in L and '
            'R and cancels in their difference, so the all-pass is '
            'untouched.'))
        boosts = [f['gain'] for f in on if f['gain'] > 0]
        if boosts:
            self.logbox.appendPlainText(
                f'     {len(boosts)} boost(s), largest {max(boosts):+.1f} dB: '
                'drop the playback level by that much to keep your headroom.')
        else:
            self.logbox.appendPlainText(
                '     Cuts only - no headroom lost, no mode driven harder.')
        self._redraw_all()
        self._page_changed(self.page_list.currentRow())

    def _clear_eq(self):
        if not self.ana.eq_filters:
            return
        self.ana.eq_filters = []
        self.logbox.appendPlainText('Auto EQ cleared.')
        self._redraw_all()
        self._page_changed(self.page_list.currentRow())

    def _home_trim_changed(self, db):
        self.ana.set_home(trim=db, quiet=True)
        self._home_refresh()
        self.logbox.appendPlainText(
            f'Home curve level: {self.ana.home_anchor:+.1f} dB anchor '
            f'{db:+.1f} dB trim = {self.ana.home_anchor + db:.1f} dB '
            'reference level.')

    def _home_refresh(self):
        """Re-evaluate every row against the home curve and redraw."""
        self.home_lbl.setText(
            '' if self.ana.home_mode == 'Hide' else
            f'{self.ana.home_anchor + self.ana.home_trim:.1f} dB')
        for alt in self.ana.alternatives:
            _, Hc = self.ana.corrected(alt['f0'], alt['q'], alt['channel'])
            alt['home_dev'] = self.ana.home_dev(Hc)
        self._rebuild_alt_table()
        self._redraw_all()
        self._update()

    def _home_changed(self, mode):
        self.ana.set_home(mode)
        self._home_refresh()
        if mode == 'Hide':
            self.logbox.appendPlainText('Home target curve hidden.')

    def _redraw_all(self):
        """Current page now, the others when they are next shown."""
        cur = self.stack.currentIndex()
        for i, p in enumerate(self.pages):
            if i == cur:
                p.refresh_static()
                p.update_filter(*self._filter_args())
                p.display_dirty = p.dirty = False
            else:
                p.display_dirty = True

    def _delay_mode_changed(self, mode):
        self.delay_spin.setEnabled(mode == 'Manual')
        if mode == 'Keep':
            self.ana.delay_s = 0.0
        elif mode == 'Auto':
            self.ana.delay_s = self.ana.delay_auto
            self.delay_spin.blockSignals(True)
            self.delay_spin.setValue(self.ana.delay_auto * 1000.0)
            self.delay_spin.blockSignals(False)
        else:
            self.ana.delay_s = self.delay_spin.value() / 1000.0
        self._redraw_all()
        if mode == 'Keep':
            self.logbox.appendPlainText(
                'Phase delay removal off: the displayed phase includes the '
                'bulk delay again.')
        else:
            self.logbox.appendPlainText(
                f'Removing {self.ana.delay_s*1000:.3f} ms of constant delay '
                f'from the displayed phase ({mode.lower()}'
                + (f'; estimated from L over 150 Hz - 8 kHz'
                   if mode == 'Auto' else '') + '). Display only: the '
                'analysis, the L-R phase difference and every export are '
                'untouched.')

    def _delay_value_changed(self, ms):
        if self.delay_combo.currentText() != 'Manual':
            return
        self.ana.delay_s = ms / 1000.0
        self._redraw_all()

    def _smoothing_changed(self, mode):
        self.ana.smooth_mode = mode
        self._redraw_all()
        note = {'Variable': ' (REW: 1/48 oct below 100 Hz, 1/6 at 1 kHz, '
                            '1/3 above 10 kHz - deliberately almost '
                            'unsmoothed in the bass, for EQ work)',
                'Psychoacoustic': ' (REW: 1/3 oct below 100 Hz to 1/6 above '
                                  '1 kHz, cubic mean so peaks weigh more)',
                'ERB': ' (auditory filter bandwidth: ~1 octave at 40 Hz, '
                       '~1/5 octave at 1 kHz)',
                'None': ''}.get(mode, ' octave (power average)')
        self.logbox.appendPlainText(
            f'Display smoothing: {mode}{note}. Display only - analysis, '
            'optimiser and exports keep the unsmoothed data.')

    def _problems_toggled(self, kind, on):
        for p in self.pages:
            p.set_problems_visible(kind, on)

    def _rebuild_alt_table(self):
        """Repaint the table from ana.alternatives (computed + user rows)."""
        t = self.alt_table
        blocked = t.blockSignals(True)
        t.setRowCount(len(self.ana.alternatives))
        for row, alt in enumerate(self.ana.alternatives):
            if alt.get('user'):
                label = f'{alt["channel"]} manual'
            elif alt['tol'] == 0:
                label = 'best'
            else:
                label = f'-{alt["tol"]:g} dB'
            cells = [label, f'{alt["f0"]:.1f}', f'{alt["q"]:.2f}',
                     f'{alt["gd_ms"]:.0f} ms']
            tip = (f'all-pass on {alt["channel"]}: RMS shortfall '
                   f'{alt["rms"]:.2f} dB (uncorrected '
                   f'{self.ana.rms_uncorrected:.2f}), deviation from the home '
                   f'curve {alt["home_dev"]:.2f} dB, group delay '
                   f'{alt["gd_ms"]:.0f} ms = {alt["cycles"]:.2f} cycles at f0, '
                   f'T60 {alt["t60_ms"]:.0f} ms, smearing {alt["smear"]}')
            for col, text in enumerate(cells):
                it = QtWidgets.QTableWidgetItem(text)
                it.setToolTip(tip)
                if alt.get('user'):
                    it.setForeground(QtGui.QColor(COL['S_corr']))
                t.setItem(row, col, it)
        t.resizeColumnsToContents()
        t.horizontalHeader().setStretchLastSection(True)
        rows_h = sum(t.rowHeight(r) for r in range(t.rowCount()))
        t.setFixedHeight(t.horizontalHeader().height() + rows_h + 6)
        t.blockSignals(blocked)

    def _describe(self, alt):
        level = alt['smear']
        return (f'all-pass on {alt["channel"]}, f0={alt["f0"]:.1f} Hz, '
                f'Q={alt["q"]:.2f} -> RMS shortfall '
                f'{self.ana.rms_uncorrected:.2f} -> {alt["rms"]:.2f} dB, '
                f'home-curve deviation {alt["home_dev"]:.2f} dB, group delay '
                f'{alt["gd_ms"]:.0f} ms ({alt["cycles"]:.2f} cycles), T60 '
                f'{alt["t60_ms"]:.0f} ms [smearing: {level}]')

    def _add_correction(self):
        f0, q, ch = self._params()
        _, Hc = self.ana.corrected(f0, q, ch)
        rms = self.ana.rms_shortfall(Hc)
        level, cycles, _why = smear_verdict(f0, q)
        alt = dict(tol=None, user=True, channel=ch, f0=f0, q=q, rms=rms,
                   gd_ms=gd_at_f0(f0, q) * 1000.0, cycles=cycles,
                   t60_ms=ringing_t60(f0, q) * 1000.0, smear=level,
                   home_dev=self.ana.home_dev(Hc))
        best = min(a['rms'] for a in self.ana.alternatives) \
            if self.ana.alternatives else rms
        self.ana.alternatives.append(alt)
        self._rebuild_alt_table()
        self.alt_table.selectRow(len(self.ana.alternatives) - 1)
        self.logbox.appendPlainText('ADDED manual correction: '
                                    + self._describe(alt))
        self.logbox.appendPlainText(
            f'   vs the best computed row: {alt["rms"] - best:+.2f} dB of '
            'correction for '
            f'{alt["gd_ms"] - self.ana.alternatives[0]["gd_ms"]:+.0f} ms of '
            'group delay.')

    def _alt_menu(self, pos):
        row = self.alt_table.rowAt(pos.y())
        if row < 0 or row >= len(self.ana.alternatives):
            return
        alt = self.ana.alternatives[row]
        menu = QtWidgets.QMenu(self)
        act_rm = menu.addAction('Remove this correction')
        act_rm.setEnabled(bool(alt.get('user')))
        if not alt.get('user'):
            act_rm.setToolTip('Only manually added rows can be removed.')
        act_apply = menu.addAction('Apply')
        chosen = menu.exec(self.alt_table.viewport().mapToGlobal(pos))
        if chosen is act_rm and alt.get('user'):
            self.ana.alternatives.pop(row)
            self._rebuild_alt_table()
            self.logbox.appendPlainText(
                f'Removed manual correction f0={alt["f0"]:.1f} Hz '
                f'Q={alt["q"]:.2f} on {alt["channel"]}.')
        elif chosen is act_apply:
            self.alt_table.selectRow(row)

    def _alt_selected(self):
        rows = {i.row() for i in self.alt_table.selectedItems()}
        if len(rows) == 1:
            self._apply_row(rows.pop())

    def _apply_row(self, row, *_):
        """Apply a table row. Also reached by clicking an already-selected
        row, which emits no selection change but must still re-apply."""
        if not 0 <= row < len(self.ana.alternatives):
            return
        alt = self.ana.alternatives[row]
        self.chan_combo.setCurrentText(alt['channel'])
        if alt.get('user'):
            name = f'manual f0={alt["f0"]:.1f} Q={alt["q"]:.2f}'
        elif alt['tol'] == 0:
            name = 'best correction'
        else:
            name = (f'give up {alt["tol"]:g} dB for '
                    f'{alt["gd_ms"]:.0f} ms delay')
        self._preset(alt['f0'], alt['q'], name)

    # ---- live updates
    def _params(self):
        return (self.f0_ctl.value(), self.q_ctl.value(),
                self.chan_combo.currentText())

    def _filter_args(self):
        f0, q, ch = self._params()
        Ht, Hc = self.ana.corrected(f0, q, ch)
        return f0, q, ch, Ht, Hc

    def _update(self, *_):
        args = self._filter_args()
        f0, q, ch, Ht, Hc = args
        cur = self.stack.currentIndex()
        for i, p in enumerate(self.pages):
            if i == cur:
                p.update_filter(*args)
                p.dirty = False
            else:
                p.dirty = True
            p.set_f0(f0)

        rms = self.ana.rms_shortfall(Hc)
        mean = self.ana.band_mean(Hc)
        home = (f'  Deviation from the {self.ana.home_mode} home curve '
                f'(20-300 Hz): {self.ana.home_dev(Hc):.2f} dB.'
                if self.ana.home_mode != 'Hide' else '')
        self.score_lbl.setText(
            f'Correction: RMS shortfall below the coherent ceiling '
            f'{self.ana.rms_uncorrected:.2f} → {rms:.2f} dB;  band mean '
            f'{mean:.1f} dB '
            f'({mean - self.ana.band_mean(self.ana.Hcalc):+.1f} dB).{home}')

        level, cycles, why = smear_verdict(f0, q)
        gd = gd_at_f0(f0, q) * 1000.0
        t60 = ringing_t60(f0, q) * 1000.0
        self.smear_lbl.setText(
            f'<b style="color:{STATUS[level]}">Smearing: {level.upper()}</b><br>'
            f'group delay at f0 <b>{gd:.0f} ms</b> = {cycles:.2f} cycles '
            f'({why});<br>tail decays 60 dB in {t60:.0f} ms '
            f'({t60*1e-3*f0:.1f} cycles).')
        self._last = (f0, q, ch, rms, mean, gd, cycles, t60, level)

    def _chan_changed(self, ch):
        self._update()
        self.logbox.appendPlainText(f'All-pass moved to the {ch} channel.')
        self._log_state()

    def _preset(self, f0, q, name):
        # the channel is the caller's business: manual rows may target the
        # other channel than the one the optimiser picked
        self.f0_ctl.set_value(f0)
        self.q_ctl.set_value(q)
        self._update()
        self.logbox.appendPlainText(f'Preset "{name}" applied.')
        self._log_state()

    def _log_state(self):
        f0, q, ch, rms, mean, gd, cycles, t60, level = self._last
        self.logbox.appendPlainText(
            f'All-pass on {ch}: f0={f0:.1f} Hz Q={q:.2f} -> RMS shortfall '
            f'{rms:.2f} dB, band mean {mean:.1f} dB, group delay at f0 '
            f'{gd:.0f} ms ({cycles:.2f} cycles), T60 {t60:.0f} ms '
            f'[smearing: {level}]')

    # ---- import
    def _import_ir(self):
        dlg = ImportDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        path = dlg.path_edit.text().strip()
        if not path or not os.path.exists(path):
            QtWidgets.QMessageBox.warning(self, 'Import', 'No such file.')
            return
        try:
            ir, fs, desc = audio_io.read_ir(
                path, dlg.fmt.currentText(), int(dlg.rate.currentText()),
                dlg.chan.value())
        except Exception as exc:                       # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, 'Import failed', str(exc))
            return

        n = int(2 ** np.ceil(np.log2(max(len(ir), 1024))))
        spec = np.fft.rfft(ir, n)
        fr = np.fft.rfftfreq(n, 1.0 / fs)
        gain = np.interp(self.ana.f, fr, np.abs(spec), left=np.nan, right=np.nan)
        ph = np.interp(self.ana.f, fr, np.unwrap(np.angle(spec)),
                       left=np.nan, right=np.nan)
        H = gain * np.exp(1j * ph)

        role = dlg.role.currentText()
        name = os.path.basename(path)
        self.logbox.appendPlainText(
            f'Imported {name}: {desc}, treated as "{role}". Peak '
            f'{np.max(np.abs(ir)):.4f} at sample {int(np.argmax(np.abs(ir)))}, '
            f'length {len(ir)/fs*1000:.0f} ms.')

        if role == 'Filter to compare':
            key = f'imp{self._extra_n}'
            self._extra_n += 1
            self.pages[3].add_extra(key, f'{name} |H|', H, COL['extra'])
            self.logbox.appendPlainText(
                '  -> overlaid on the All-pass filter page (magnitude). '
                'Compare its flatness with the designed all-pass.')
        elif role in ('Left channel', 'Right channel', 'L+R measured'):
            QtWidgets.QMessageBox.information(
                self, 'Imported',
                'An impulse response cannot replace a calibrated SPL '
                'measurement (it carries no absolute level). It has been '
                'added as a reference curve instead.')
            role = 'Reference curve'
        if role == 'Reference curve':
            key = f'imp{self._extra_n}'
            self._extra_n += 1
            for p in (self.pages[0], self.pages[1]):
                p.add_extra(key, name, H, COL['extra'])
            self.logbox.appendPlainText(
                '  -> added as a reference curve on the Amplitude and Phase '
                'pages (relative level, not calibrated SPL).')
        self._page_changed(self.page_list.currentRow())

    # ---- export
    def _save_name(self, default, filt='All files (*)'):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'Export', os.path.join(os.getcwd(), default), filt)
        return path

    def _export_filter(self):
        f0, q, ch = self._params()
        fs = int(self.rate_combo.currentText())
        need = ringing_t60(f0, q)
        taps = int(2 ** np.ceil(np.log2(max(1.5 * need * fs, 4096))))
        dlg = ExportDialog(f0, q, fs, taps, self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        container = dlg.container.currentText()
        fmt = dlg.fmt.currentText()
        fs = int(dlg.rate.currentText())
        try:
            taps = int(dlg.taps.currentText())
        except ValueError:
            QtWidgets.QMessageBox.warning(self, 'Export', 'Taps must be a number.')
            return
        ext = {'WAV': '.wav', 'RAW': '.raw', 'TXT': '.txt'}[container]
        default = (f'ap_{ch}_{num_tag(round(f0, 1))}Hz_Q'
                   f'{num_tag(round(q, 2))}_{fs//1000}k{ext}')
        path = self._save_name(default, f'{container} (*{ext});;All files (*)')
        if not path:
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            ir = allpass_ir(f0, q, fs, taps)
            if container == 'WAV':
                scale = audio_io.write_wav(path, ir, fs, fmt)
            elif container == 'RAW':
                scale = audio_io.write_raw(path, ir, fmt)
            else:
                scale = audio_io.write_txt(path, ir)
        except Exception as exc:                       # noqa: BLE001
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.critical(self, 'Export failed', str(exc))
            return
        QtWidgets.QApplication.restoreOverrideCursor()
        kept = float(np.sum(ir ** 2))
        self.logbox.appendPlainText(
            f'Exported all-pass on {ch} (f0={f0:.1f} Hz, Q={q:.2f}) as '
            f'{container}/{fmt if container != "TXT" else "text"} at {fs} Hz, '
            f'{taps} taps ({taps/fs*1000:.0f} ms, {kept*100:.2f}% of the unit '
            f'energy captured) -> {path}'
            + ('' if scale == 1.0 else f' [scaled by {scale:.4f} to avoid '
               'clipping]') + '. Causal from t=0, no added latency; load it in '
            'REW as an impulse response or in BruteFIR as a coefficient file.')

    def _export_fr(self, kind):
        f0, q, ch = self._params()
        ana = self.ana
        Ht, Hc = ana.corrected(f0, q, ch)
        tag = f'{num_tag(round(f0, 1))}Hz_Q{num_tag(round(q, 2))}'
        if kind == 'ap':
            H, label, default = (allpass_h(ana.f, f0, q),
                                 f'All-pass normal f0={f0:.1f} Hz Q={q:.2f}',
                                 f'ap_fr_{tag}.txt')
        elif kind == 'target':
            H, label, default = (Ht, f'{ch} with all-pass f0={f0:.1f} Hz '
                                 f'Q={q:.2f}', f'{ch}_ap_{tag}.txt')
        elif kind == 'sum':
            H, label, default = (Hc, f'L+R corrected (all-pass on {ch}, '
                                 f'f0={f0:.1f} Hz Q={q:.2f})',
                                 f'LR_corrected_{tag}.txt')
        elif kind == 'target_level':
            H = 10.0 ** (ana.target / 20.0) + 0j
            label, default = ('Coherent ceiling (1/3-oct average of |L|+|R|)',
                              'coherent_ceiling.txt')
        elif kind == 'home':
            H = 10.0 ** (ana.home / 20.0) + 0j
            label = f'Home target curve ({ana.home_mode})'
            default = f'home_{ana.home_mode.split()[0].lower()}.txt'
        else:
            H, label, default = (ana.Hcalc,
                                 'L+R calculated complex sum (uncorrected)',
                                 'LR_calculated.txt')
        path = self._save_name(default, 'Text files (*.txt);;All files (*)')
        if not path:
            return
        write_rew_txt(path, ana.f, H, label)
        self.logbox.appendPlainText(
            f'Exported "{label}" as REW text -> {path} (File > Import > '
            'Frequency response in REW).')


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('-l', '--left', help='left channel REW export (txt)')
    ap.add_argument('-r', '--right', help='right channel REW export (txt)')
    ap.add_argument('-s', '--stereo', help='measured L+R REW export (txt)')
    ap.add_argument('--font-size', type=float, default=UI_FONT_PT,
                    metavar='PT',
                    help=f'UI font size in points (default {UI_FONT_PT:g}; '
                         'Qt6 defaults to 12, which is large for a dense '
                         'layout). Also adjustable at runtime with '
                         'Ctrl+plus / Ctrl+minus / Ctrl+0.')
    args = ap.parse_args()

    left, right, stereo = args.left, args.right, args.stereo
    if not (left and right):
        if os.path.exists('L0.txt') and os.path.exists('R0.txt'):
            left, right = left or 'L0.txt', right or 'R0.txt'
            if not stereo and os.path.exists('LR.txt'):
                stereo = 'LR.txt'
            print('No -l/-r given; using L0.txt / R0.txt'
                  + (' / LR.txt' if stereo else '') + ' from the current dir.')
        else:
            ap.error('both -l and -r are required (or run in a directory '
                     'containing L0.txt / R0.txt)')
    for path in filter(None, (left, right, stereo)):
        if not os.path.exists(path):
            ap.error(f'file not found: {path}')

    pg.setConfigOptions(background=SURFACE, foreground=FOREGROUND,
                        antialias=True)
    app = QtWidgets.QApplication(sys.argv)
    set_ui_font(app, args.font_size)
    try:
        ana = Analysis(left, right, stereo)
    except ValueError as exc:
        QtWidgets.QMessageBox.critical(None, 'Load error', str(exc))
        return 1
    win = MainWindow(ana)
    if ana.Hmeas is None:
        QtWidgets.QMessageBox.warning(
            win, 'No measured L+R',
            'No measured L+R file was supplied (-s).\n'
            'The calculated complex sum of L and R is used instead.')
    win.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
