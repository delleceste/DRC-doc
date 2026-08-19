#!/usr/bin/env python3
"""Signal-flow diagram of the REW inversion chain, for REW-INVERSION.md.

The diagram follows the multi-position V5.40 beta procedure. Four things it
is meant to make obvious:

  * the FDW is applied once, to every original capture (the shaded band),
  * three divisors leave step 3, and the mono sum is built L+R per position
    before the positions are RMS-averaged,
  * minimum phase is taken at two stages (the filled boxes), and
  * X801 is multiplied in twice and is never itself windowed or inverted.

Mathtext is avoided in the box labels: pdflatex renders the PNG as-is, and
mathtext put visible gaps around the periods in './drc_acceptance.py'.
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

INK   = '#1a1a1a'
MUTED = '#6b6b6b'
MP    = '#b3502e'   # the two minimum-phase steps
WIN   = '#2f6f8f'   # the one windowing step
XO    = '#4a7a3a'   # the crossover filter
CHK   = '#7a5aa0'   # the verification step

XL, XR, XC = 1.15, 5.85, 3.5     # left column, right column, centre

fig, ax = plt.subplots(figsize=(9.4, 13.7))
ax.set_xlim(-0.98, 8.05); ax.set_ylim(-1.15, 13.65); ax.axis('off')


def box(x, y, w, h, text, ec=INK, fc='white', fs=9.5, lw=1.1, tc=None,
        bold=False, ls='solid'):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                                boxstyle='round,pad=0.055,rounding_size=0.09',
                                ec=ec, fc=fc, lw=lw, zorder=3, linestyle=ls))
    ax.text(x, y, text, ha='center', va='center', fontsize=fs, zorder=4,
            color=tc or ec, fontweight='bold' if bold else 'normal',
            linespacing=1.4)


def arrow(x0, y0, x1, y1, c=MUTED, lw=1.1, rad=0.0):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle='-|>',
                                 mutation_scale=11, lw=lw, color=c,
                                 shrinkA=1, shrinkB=1, zorder=2,
                                 connectionstyle='arc3,rad=%g' % rad))


def step(y, n, label, c=INK):
    ax.text(-0.90, y, n, ha='left', va='center', fontsize=11.5,
            fontweight='bold', color=c)
    ax.text(-0.90, y - 0.31, label, ha='left', va='center', fontsize=7.4,
            color=MUTED)


Y = dict(meas=12.80, fdw=11.72, sp=10.58, lx=9.46, mp=8.36, avg=7.30, tgt=6.46,
         chk=5.41, div=4.08, mpf=2.72, bake=1.55, out=0.35)

# ---- 1  measure -------------------------------------------------------
step(Y['meas'], '1', 'measure')
box(XL, Y['meas'], 2.6, 0.74, 'L at 5 positions\nC, F20, B20, L20, R20')
box(XR, Y['meas'], 2.6, 0.74, 'R at 5 positions\nC, F20, B20, L20, R20')

# ---- 2  the one and only window ---------------------------------------
step(Y['fdw'], '2', 'window', WIN)
ax.add_patch(Rectangle((XL - 1.75, Y['fdw'] - 0.44), (XR + 1.75) - (XL - 1.75),
                       0.88, ec=WIN, fc='#eaf2f6', lw=1.2, zorder=1))
ax.text(XC, Y['fdw'] + 0.15, 'Add FDW — 12 cycles', ha='center', va='center',
        fontsize=11, color=WIN, fontweight='bold', zorder=4)
ax.text(XC, Y['fdw'] - 0.21, 'Apply to all, keep ref time   ·   before any average',
        ha='center', va='center', fontsize=8.2,
        color=WIN, zorder=4)
for x in (XL, XR):
    arrow(x, Y['meas'] - 0.41, x, Y['fdw'] + 0.46)
    arrow(x, Y['fdw'] - 0.46, x, Y['sp'] + 0.42)

# ---- 3a-3d  reduce the captures to three divisors ---------------------
step(Y['sp'], '3', 'reduce')
box(XL, Y['sp'], 2.05, 0.72, 'L-SP\nRMS of the 5 positions', fs=8.2)
box(XR, Y['sp'], 2.05, 0.72, 'R-SP\nRMS of the 5 positions', fs=8.2)
box(XC, Y['sp'], 2.02, 0.84,
    'SUM-SP\nvector L+R at each position,\nthen RMS of the 5 positions',
    fs=6.9)
# the captures feed the sum lane too
arrow(XL + 0.75, Y['fdw'] - 0.46, XC - 0.80, Y['sp'] + 0.44)
arrow(XR - 0.75, Y['fdw'] - 0.46, XC + 0.80, Y['sp'] + 0.44)

# ---- 3e  bake the crossover into the channel averages -----------------
step(Y['lx'], '', 'crossover', XO)
box(XL, Y['lx'], 2.05, 0.60, 'LX = L-SP × X801', fs=8.6)
box(XR, Y['lx'], 2.05, 0.60, 'RX = R-SP × X801', fs=8.6)
box(XC + 0.30, Y['lx'], 1.10, 0.80, 'X801\nall-pass\n0.000 dB',
    ec=XO, fc='#eef4ec', fs=7.4)
arrow(XC - 0.28, Y['lx'], XL + 1.06, Y['lx'], c=XO)
arrow(XC + 0.88, Y['lx'], XR - 1.06, Y['lx'], c=XO)
for x in (XL, XR):
    arrow(x, Y['sp'] - 0.38, x, Y['lx'] + 0.32)
ax.text(XC + 0.15, Y['lx'] - 0.63, 'X801 cancels out of the sum',
        ha='center', va='center', fontsize=6.6, color=XO, style='italic',
        zorder=4)

# ---- 4  minimum phase, first time -------------------------------------
step(Y['mp'], '4', 'min phase 1', MP)
box(XL, Y['mp'], 2.05, 0.62, 'LX-MP', ec=MP, fc='#fbeee9', bold=True)
box(XR, Y['mp'], 2.05, 0.62, 'RX-MP', ec=MP, fc='#fbeee9', bold=True)
box(XC, Y['mp'], 2.02, 0.72, 'SUM-MP\nthe divisor for 7b', ec=MP,
    fc='#fbeee9', fs=8.4, bold=True)
for x in (XL, XR):
    arrow(x, Y['lx'] - 0.34, x, Y['mp'] + 0.36, c=MP)
# the sum lane passes down the corridor between the LX box and X801
arrow(XC - 0.95, Y['sp'] - 0.44, XC - 0.95, Y['mp'] + 0.40, c=MP)

# ---- 5  target --------------------------------------------------------
step(Y['avg'], '5', 'target')
box(XC, Y['avg'], 3.7, 0.56, 'RMS average of LX, RX')
box(XC, Y['tgt'], 3.7, 0.56, 'Target   (EQ window target shape)', lw=1.4)
arrow(XL + 0.95, Y['lx'] - 0.20, XC - 1.35, Y['avg'] + 0.32)
arrow(XR - 0.95, Y['lx'] - 0.20, XC + 1.35, Y['avg'] + 0.32)
arrow(XC, Y['avg'] - 0.32, XC, Y['tgt'] + 0.32)

# ---- 6  verify before you divide --------------------------------------
step(Y['chk'], '6', 'verify', CHK)
box(XC, Y['chk'], 6.6, 0.72, 'STOP — export LX-MP, RX-MP and SUM-MP with Smoothing: None.\n'
    'No feature below 200 Hz may be narrower than 30 bins (11 Hz).',
    ec=CHK, fc='#f4f0f8', fs=8.8, ls=(0, (4, 2.5)))
arrow(XL, Y['mp'] - 0.36, XL, Y['chk'] + 0.40, c=CHK)
arrow(XR, Y['mp'] - 0.36, XR, Y['chk'] + 0.40, c=CHK)

# ---- 7  the divide ----------------------------------------------------
step(Y['div'], '7', 'invert')
for x, n, d in ((XL, 'Fl', 'LX-MP'), (XR, 'Fr', 'RX-MP')):
    box(x, Y['div'], 3.0, 1.06,
        '%s = (Target ÷ SUM-MP) 20–80\n× (Target ÷ %s) 80–225\n'
        'Max gain selected: 0.0 dB' % (n, d), lw=1.3,
        bold=True, fs=7.9)
    arrow(x, Y['chk'] - 0.40, x, Y['div'] + 0.57)
arrow(XC - 1.30, Y['tgt'] - 0.32, XL + 1.20, Y['div'] + 0.55)
arrow(XC + 1.30, Y['tgt'] - 0.32, XR - 1.20, Y['div'] + 0.55)
ax.text(XC, Y['div'] - 0.72, 'unity outside the limits, blended over one octave',
        ha='center', va='center', fontsize=7.9, color=MUTED, style='italic')

# ---- 8  minimum phase, second time ------------------------------------
step(Y['mpf'], '8', 'min phase 2', MP)
box(XL, Y['mpf'], 2.6, 0.62, 'LFilter', ec=MP, fc='#fbeee9', bold=True)
box(XR, Y['mpf'], 2.6, 0.62, 'RFilter', ec=MP, fc='#fbeee9', bold=True)
for x in (XL, XR):
    arrow(x, Y['div'] - 0.57, x, Y['mpf'] + 0.36, c=MP)
ax.text(XC, Y['mpf'], 'force the filter\ncausal', ha='center', va='center',
        fontsize=7.9, color=MP, style='italic')

# ---- 9  bake the crossover in, last -----------------------------------
step(Y['bake'], '9', 'bake')
box(XL, Y['bake'], 2.6, 0.62, 'FLX  =  X801 × LFilter')
box(XR, Y['bake'], 2.6, 0.62, 'FRX  =  X801 × RFilter')
box(XC, Y['bake'], 1.20, 0.50, 'X801', ec=XO, fc='#eef4ec', fs=8.6)
arrow(XC - 0.66, Y['bake'], XL + 1.36, Y['bake'], c=XO)
arrow(XC + 0.66, Y['bake'], XR - 1.36, Y['bake'], c=XO)
for x in (XL, XR):
    arrow(x, Y['mpf'] - 0.36, x, Y['bake'] + 0.36)

# ---- 10  out ----------------------------------------------------------
step(Y['out'], '10', 'export')
box(XC, Y['out'], 6.6, 0.80, '', lw=1.4)
ax.text(XC, Y['out'] + 0.15, 'Trim IR to windows  →  export WAV  '
        '(48 kHz, 32-bit float, 128k)', ha='center', va='center', fontsize=9,
        color=INK, zorder=4)
ax.text(XC, Y['out'] - 0.17, './drc_acceptance.py  FLX-trimmed-48k.wav  '
        'FRX-trimmed-48k.wav', ha='center', va='center', fontsize=8.6,
        color=INK, zorder=4, family='monospace', fontweight='bold')
arrow(XL, Y['bake'] - 0.36, XC - 1.7, Y['out'] + 0.44)
arrow(XR, Y['bake'] - 0.36, XC + 1.7, Y['out'] + 0.44)

ax.text(XC, -0.95, 'Combine L with R only within a position (vector average); '
        'combine different positions only with RMS average.',
        ha='center', va='center', fontsize=7.7, color=MUTED, style='italic')

fig.savefig('fig-chain.png', dpi=150, facecolor='white',
            bbox_inches='tight', pad_inches=0.20)
print('wrote fig-chain.png')
