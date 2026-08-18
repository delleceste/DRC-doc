#!/usr/bin/env python3
"""Figure for REW-INVERSION.md §11 — why the divisor must be the sum below 80 Hz.

Three panels, all from the 2026-08-10 Rscreen pair and the 2026-08-11 build
in ../DRC-120.blue/120.blue.Rscreen.txts/:

 (a) L and R cancel each other at 45-56 Hz.  The RMS+phase average fills that
     in by construction; the vector average (= the mono sum) does not.
 (b) What each candidate divisor asks the filter to cut.  Against the RMS
     average the target demands 1.7-2.8 dB right inside the cancellation;
     against the sum it demands nothing, because the cut-only clamp engages
     on its own.
 (c) The consequence, on the predicted mono sum: the per-channel build lost
     2.5 dB at 40-62.5 Hz; correcting the sum below 80 Hz gives it back
     without touching the 100-225 Hz correction.

Panel (c) needs no complex algebra: below 80 Hz both channels receive the
same filter, so the sum transforms exactly as |sum'| = |sum| + Fcommon(dB).
"""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, NullFormatter

D = '../DRC-120.blue/120.blue.Rscreen.txts/'


def load(path):
    """REW text export; tolerates the 2-column target-shape format."""
    f, s = [], []
    for line in open(path):
        line = line.strip()
        if not line or not (line[0].isdigit() or line[0] == '-'):
            continue
        a = line.replace(',', ' ').split()
        if len(a) < 2:
            continue
        f.append(float(a[0])); s.append(float(a[1]))
    return np.array(f), np.array(s)


def smooth(f, s, frac=6, lo=16.0, hi=2000.0):
    n = int(np.log2(hi / lo) * 48)
    fg = lo * 2 ** np.linspace(0, np.log2(hi / lo), n)
    sg = np.interp(fg, f, s)
    w = max(1, int(round(48.0 / frac)))
    k = np.ones(2 * w + 1) / (2 * w + 1)
    return fg, np.convolve(sg, k, mode='same')


G = np.logspace(np.log10(20), np.log10(300), 700)
def tr(name, frac=6):
    return np.interp(G, *smooth(*load(D + name), frac=frac))

L    = tr('L.120.Rscreen.orig.txt')
R    = tr('R.120.Rscreen.orig.txt')
rms  = tr('LRrms+phavg.txt')
vec  = tr('LR.orig.txt')
tgt  = tr('Target LRrms+phavg.txt')
cur  = tr('LR.Filtered.txt')

# --- panel (c): common correction below 80 Hz -------------------------------
def rise(grid, lim):
    """REW band limit: unity outside, raised cosine over one octave on lim."""
    a, b = lim / np.sqrt(2), lim * np.sqrt(2)
    w = np.zeros_like(grid)
    m = (grid > a) & (grid < b)
    t = (np.log(grid[m]) - np.log(a)) / (np.log(b) - np.log(a))
    w[m] = 0.5 * (1 - np.cos(np.pi * t))
    w[grid >= b] = 1.0
    return w

Fcommon = np.minimum(tgt - vec, 0.0) * (1 - rise(G, 225.))
xf = rise(G, 80.)
new = (vec + Fcommon) * (1 - xf) + cur * xf

ref_o = np.mean(vec[(G >= 250) & (G <= 300)])
ref_f = np.mean(cur[(G >= 250) & (G <= 300)])

fig, ax = plt.subplots(1, 3, figsize=(11.0, 3.5), dpi=150)

# (a) ------------------------------------------------------------------
a0 = ax[0]
a0.plot(G, L, color='#2980d9', lw=1.5, label='L alone')
a0.plot(G, R, color='#c0392b', lw=1.5, label='R alone')
a0.plot(G, rms, color='#7f8c8d', lw=2.2, ls='--', label='RMS+phase avg (divisor used)')
a0.plot(G, vec, color='#1e8449', lw=2.2, label='vector avg = mono sum')
a0.axvspan(45, 56, color='#f39c12', alpha=0.18)
a0.text(50, 63.4, 'L and R\ncancel', ha='center', fontsize=8, color='#a5680a')
a0.set_xlim(28, 160); a0.set_ylim(62, 82)
a0.set_ylabel('SPL (dB)')
a0.set_title('(a) the divisor hides a cancellation', fontsize=9.5)
a0.legend(fontsize=6.6, loc='upper left')

# (b) ------------------------------------------------------------------
a1 = ax[1]
a1.plot(G, np.maximum(rms - tgt, 0), color='#7f8c8d', lw=2.2, ls='--',
        label='cut asked vs RMS avg')
a1.plot(G, np.maximum(vec - tgt, 0), color='#1e8449', lw=2.2,
        label='cut asked vs mono sum')
a1.axvspan(45, 56, color='#f39c12', alpha=0.18)
a1.set_xlim(20, 160); a1.set_ylim(-0.3, 9)
a1.set_ylabel('cut requested (dB)')
a1.set_title('(b) what each divisor demands', fontsize=9.5)
a1.legend(fontsize=7, loc='upper left')
a1.annotate('0 dB: the clamp\ndoes the work', xy=(50, 0.06), xytext=(33, 1.5),
            fontsize=7.5, color='#14572f',
            arrowprops=dict(arrowstyle='->', color='#14572f', lw=0.9))

# (c) ------------------------------------------------------------------
a2 = ax[2]
a2.plot(G, vec - ref_o, color='#95a5a6', lw=1.5, label='before correction')
a2.plot(G, cur - ref_f, color='#c0392b', lw=1.8, label='per-channel (the build on disk)')
a2.plot(G, new - ref_f, color='#1e8449', lw=2.0, label='common below 80 Hz')
a2.axvspan(40, 62.5, color='#f39c12', alpha=0.18)
a2.axvline(80, color='k', lw=0.8, ls=':', alpha=0.5)
a2.text(81, 10.4, ' 80 Hz', fontsize=7.5, alpha=0.7)
a2.set_xlim(20, 300); a2.set_ylim(-4, 12)
a2.set_ylabel('mono sum, dB re midrange')
a2.set_title('(c) +2.3 dB recovered, correction kept', fontsize=9.5)
a2.legend(fontsize=7, loc='upper right')

for a in ax:
    a.set_xscale('log')
    a.grid(alpha=0.25, which='both')
    a.set_xlabel('frequency (Hz)')
    a.xaxis.set_major_locator(FixedLocator([20, 30, 50, 80, 125, 200, 300]))
    a.xaxis.set_minor_formatter(NullFormatter())
    a.xaxis.set_major_formatter(lambda x, _: '%g' % x)

fig.tight_layout()
fig.savefig('fig-common-bass.png')
print('wrote fig-common-bass.png')

# --- the numbers quoted in the text ----------------------------------------
print('\nband means of the predicted mono sum, dB re midrange:')
for lo, hi, lbl in ((20, 40, '20-40'), (40, 62.5, '40-62.5'),
                    (62.5, 100, '62.5-100'), (100, 160, '100-160'),
                    (160, 225, '160-225')):
    m = (G >= lo) & (G <= hi)
    print('   %-10s before %+6.2f   per-channel %+6.2f   common %+6.2f   (%+.2f)'
          % (lbl, vec[m].mean() - ref_o, cur[m].mean() - ref_f,
             new[m].mean() - ref_f, (new[m] - cur[m]).mean()))
