#!/usr/bin/env python3
"""Two-page A4 measurement pack for the listening room.

  sheet 1  blank dimension form: room plan, seven lettered arrows, no values
  sheet 2  panel inventory and reflection points, with an experiment log

Architecture is from NOTES.md §5, the decoded reading of the pencil plan in
room.png: length 7.40 m, width 4.186 m at the speaker line, opening to 5.986 m
past a half-wall that runs 1.75 m in from the front wall, 1.4 m opening to the
corridor at the BACK-RIGHT corner (corrected 2026-08-10 from giacomo's markup;
the first draft had it centred, which mattered -- see draw_reflections).

Speakers and listener are the 120.blue profile: tweeters 1.20 m from the front
wall, 2.53 m apart, 0.78 / 0.88 m from the side walls (room.png 0.75 / 0.85;
NOTES §10 item 5 "18% and 20% of 4.186 m"), listener 4.49 m from the front wall
(the mic position in the header of L.120.Blue).

Panel positions are traced from room-form-with-panels.png. Lengths and angles
are indicative -- sheet 2 has blanks to write the measured ones in.

Sheet 1 deliberately carries no dimension VALUES; it is a form to fill in.
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle, FancyArrowPatch, Circle
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np

# ---------------------------------------------------------------- geometry
# All geometry lives in roomgeom.py so this sheet and the reflection study
# cannot drift apart.  See that file for provenance of every number.
from roomgeom import (L, W, W2, HALF, CORR_X0, CORR_X1, CHAM_Y, CHAM_X,
                      SCR_W, SPK_Y, TW_L, TW_R, Z_TW, Z_EAR, CAB_W,
                      CAB_D, LP_X, LP_Y)

INK, GREY, LIGHT = '#111111', '#666666', '#b5b5b5'
DIM    = '#1f4e79'
SCREEN = '#2e8b3d'
ROCK   = '#c1272d'      # GIK freestanding screens (rockwool)
FOAM   = '#2b4fa2'      # pyramidal foam
REFL   = '#8a5a00'      # specular reflection points

# Proposed layout: a continuous pseudo-wall on the half-wall line from its end
# at 1.75 m to just past the seat at ~4.6 m.  Screens take the front section
# because it contains the right mirror point (2.16 m) and must be broadband;
# the foam moves behind them, where the spectral demand is lower.
#   (tag, kind, centre x, centre y, angle deg)
PANELS = [
    ('S1', 'rock', 0.07, 1.97,   0),
    ('S2', 'rock', 0.07, 3.14,   0),
    ('S3', 'rock', 4.12, 1.98,   0),   # moved in from the open right
    ('S4', 'rock', 4.12, 3.14,   0),   # moved in from the open right
    ('F1', 'foam', 4.12, 3.90,   0),   # moved back
    ('F2', 'foam', 4.12, 4.45,   0),   # moved back
    ('S5', 'rock', 3.84, 5.52, -55),
    ('S6', 'rock', 1.58, 5.81,  78),
    ('S7', 'rock', 2.80, 5.81,  78),
]
# positions that fall empty, drawn hollow so the change is legible
VACATED = [(4.31, 3.85, -18), (4.31, 4.72, -18)]


def mirror_point(spk, axis, plane):
    """Where the specular reflection off `plane` lands, in metres."""
    img = np.array(spk, float)
    img[axis] = 2 * plane - img[axis]
    lp = np.array([LP_X, LP_Y])
    f = (img[axis] - plane) / (img[axis] - lp[axis])
    return img + f * (lp - img)


def delay_ms(spk, axis, plane):
    """Excess delay of that reflection over the direct sound, in ms."""
    S = np.array([spk[0], spk[1], Z_TW]); M = np.array([LP_X, LP_Y, Z_EAR])
    I = S.copy(); I[axis] = 2 * plane - I[axis]
    return (np.linalg.norm(I - M) - np.linalg.norm(S - M)) / 343.0 * 1000


SPK_L, SPK_R = (TW_L, SPK_Y), (TW_R, SPK_Y)
REFL_PTS = [mirror_point(SPK_L, 0, 0.0),      # left wall, near speaker
            mirror_point(SPK_R, 0, 0.0),      # left wall, FAR speaker
            mirror_point(SPK_L, 1, 0.0),      # front wall, from L
            mirror_point(SPK_R, 1, 0.0),      # front wall, from R
            mirror_point(SPK_L, 1, L),        # back wall, from L
            mirror_point(SPK_R, 1, L)]        # back wall, from R
REFL_LABELS = [(-0.14, mirror_point(SPK_L, 0, 0.0)[1],
                'left wall\n%.1f ms' % delay_ms(SPK_L, 0, 0.0), 'right'),
               (LP_X, -0.32, 'front wall / screen — %.1f ms'
                % delay_ms(SPK_L, 1, 0.0), 'center'),
               (LP_X, L - 0.34, 'back wall — %.1f ms'
                % delay_ms(SPK_L, 1, L), 'center'),
               (-0.14, mirror_point(SPK_R, 0, 0.0)[1],
                'left wall, R speaker\n%.1f ms' % delay_ms(SPK_R, 0, 0.0), 'right')]
RIGHT_MIRROR  = mirror_point(SPK_R, 0, W)   # near speaker, past the wall end
RIGHT_MIRROR2 = mirror_point(SPK_L, 0, W)   # far speaker, further past still


# ---------------------------------------------------------------- drawing
def new_axes(fig, rect):
    ax = fig.add_axes(rect)
    ax.set_aspect('equal'); ax.axis('off')
    ax.set_xlim(-0.98, W2 + 0.78)
    ax.set_ylim(L + 0.85, -0.98)
    return ax


def draw_room(ax, halfwall_note=True):
    walls = [(0, 0), (W, 0), (W, HALF), (W2, HALF), (W2, L),
             (CHAM_X, L), (0, CHAM_Y)]
    ax.add_patch(Polygon(walls, closed=True, fc='#fbfbfb', ec='none', zorder=0))
    for i in range(len(walls)):
        x0, y0 = walls[i]; x1, y1 = walls[(i + 1) % len(walls)]
        if y0 == L and y1 == L:          # back wall: leave the corridor opening
            ax.plot([min(x0, x1), CORR_X0], [L, L], color=INK, lw=2.2, zorder=3)
            ax.plot([CORR_X1, max(x0, x1)], [L, L], color=INK, lw=2.2, zorder=3)
            continue
        ax.plot([x0, x1], [y0, y1], color=INK, lw=2.2, zorder=3)
    ax.add_patch(Rectangle((CORR_X0, L), CORR_X1 - CORR_X0, 0.42, fc='#f0f0f0',
                           ec=LIGHT, lw=0.8, ls='--', zorder=1))
    ax.text((CORR_X0 + CORR_X1) / 2, L + 0.30, 'corridor', ha='center',
            va='center', fontsize=7.5, color=GREY, style='italic')
    sx = (TW_L + TW_R) / 2
    ax.plot([sx - SCR_W / 2, sx + SCR_W / 2], [0.07, 0.07], color=SCREEN, lw=5,
            solid_capstyle='butt', zorder=4)
    ax.text(sx, 0.30, 'projector screen', ha='center', va='center',
            fontsize=7.5, color=SCREEN, style='italic')
    ax.text(W / 2, -0.78, 'F R O N T   W A L L', ha='center', va='center',
            fontsize=10, color=INK, fontweight='bold')
    if halfwall_note:
        ax.text(0.75, L + 0.40, 'back wall', ha='center', va='center',
                fontsize=8, color=GREY)
        ax.text(W + 0.06, HALF + 0.16, 'half-wall ends here', fontsize=7,
                color=GREY, style='italic', va='top')


def draw_speakers(ax):
    for xt, tag in ((TW_L, 'L'), (TW_R, 'R')):
        a = np.arctan2(LP_X - xt, LP_Y - SPK_Y)
        ca, sa = np.cos(a), np.sin(a)
        pts = [(-CAB_W / 2, 0), (CAB_W / 2, 0), (CAB_W / 2, -CAB_D),
               (-CAB_W / 2, -CAB_D)]
        rot = [(xt + px * ca - py * sa, SPK_Y + px * sa + py * ca)
               for px, py in pts]
        ax.add_patch(Polygon(rot, closed=True, fc='#e4e4e4', ec=INK, lw=1.1,
                             zorder=4))
        ax.plot([xt], [SPK_Y], marker='o', ms=4.5, mfc='white', mec=INK,
                mew=1.2, zorder=5)
        ax.text(xt + CAB_D / 2 * sa, SPK_Y - CAB_D / 2 * ca, tag, ha='center',
                va='center', fontsize=11, fontweight='bold', color=INK, zorder=5)


def draw_sofa(ax):
    sx0, sx1 = LP_X - 1.05, LP_X + 1.05
    sy0, sy1 = LP_Y - 0.47, LP_Y + 0.33
    ax.add_patch(Rectangle((sx0, sy0), sx1 - sx0, sy1 - sy0, fc='#efefef',
                           ec=GREY, lw=1.1, zorder=2))
    ax.add_patch(Rectangle((sx0, sy1 - 0.17), sx1 - sx0, 0.17, fc='#d8d8d8',
                           ec=GREY, lw=0.8, zorder=3))
    for xx in (sx0, sx1 - 0.16):
        ax.add_patch(Rectangle((xx, sy0), 0.16, sy1 - sy0, fc='#d8d8d8',
                               ec=GREY, lw=0.8, zorder=3))
    ax.plot([LP_X], [LP_Y], marker='+', ms=13, mew=1.6, color=INK, zorder=6)
    ax.add_patch(Circle((LP_X, LP_Y), 0.16, fc='none', ec=INK, lw=1.4, zorder=6))


def draw_panels(ax):
    for tag, kind, cx, cy, deg in PANELS:
        c = ROCK if kind == 'rock' else FOAM
        ln, th = (0.95, 0.13) if kind == 'rock' else (0.80, 0.10)
        a = np.radians(deg); ca, sa = np.cos(a), np.sin(a)
        pts = [(-th / 2, -ln / 2), (th / 2, -ln / 2), (th / 2, ln / 2),
               (-th / 2, ln / 2)]
        rot = [(cx + px * ca - py * sa, cy + px * sa + py * ca) for px, py in pts]
        ax.add_patch(Polygon(rot, closed=True, fc=c, ec=c, lw=1.0, zorder=7))
        if tag in ('S6', 'S7'):
            lx, ly = cx, cy + 0.44
        else:
            lx, ly = cx + (0.44 if cx < W / 2 else -0.44), cy
        ax.text(lx, ly, tag, ha='center', va='center', fontsize=7.6,
                fontweight='bold', color=c, zorder=8)
    for cx, cy, deg in VACATED:
        a = np.radians(deg); ca, sa = np.cos(a), np.sin(a)
        pts = [(-0.065, -0.475), (0.065, -0.475), (0.065, 0.475), (-0.065, 0.475)]
        rot = [(cx + px * ca - py * sa, cy + px * sa + py * ca) for px, py in pts]
        ax.add_patch(Polygon(rot, closed=True, fc='none', ec=ROCK, lw=0.9,
                             ls=(0, (2, 2)), alpha=0.65, zorder=6))
    ax.text(VACATED[0][0] + 0.55, (VACATED[0][1] + VACATED[1][1]) / 2,
            'roughly where\nS3 / S4 stand\ntoday (traced)', ha='left',
            va='center', fontsize=6.6, color=ROCK, alpha=0.85, style='italic',
            zorder=8, linespacing=1.3)


def draw_reflections(ax):
    for px, py in REFL_PTS:
        ax.plot([px], [py], marker='D', ms=5.2, mfc=REFL, mec='white', mew=0.8,
                zorder=9)
    for lx, ly, lab, ha in REFL_LABELS:
        ax.text(lx, ly, lab, ha=ha, va='center', fontsize=6.9, color=REFL,
                zorder=9, linespacing=1.25)
    px, py = RIGHT_MIRROR
    p2 = RIGHT_MIRROR2
    ax.plot([W, W], [HALF, p2[1] + 0.15], color=REFL, lw=0.8, ls=(0, (2, 2)),
            zorder=8)
    for q in (RIGHT_MIRROR, RIGHT_MIRROR2):
        ax.plot([q[0]], [q[1]], marker='D', ms=5.2, mfc='white', mec=REFL,
                mew=1.3, zorder=9)
    ax.annotate('right wall: BOTH mirror points miss it\n'
                '%.1f ms point falls %.0f cm past the end\n'
                '%.1f ms point falls %.2f m past the end'
                % (delay_ms(SPK_R, 0, W), (py - HALF) * 100,
                   delay_ms(SPK_L, 0, W), RIGHT_MIRROR2[1] - HALF),
                xy=(px, py), xytext=(W2 + 0.10, py - 0.75), fontsize=6.9,
                color=REFL, ha='left', va='center', zorder=9,
                linespacing=1.3,
                arrowprops=dict(arrowstyle='-', lw=0.7, color=REFL,
                                shrinkA=2, shrinkB=4))


# ---------------------------------------------------------------- helpers
def dim(ax, x0, y0, x1, y1, letter, lx=0.0, ly=0.0):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle='<|-|>',
                                 mutation_scale=9, lw=1.0, color=DIM,
                                 shrinkA=0, shrinkB=0, zorder=6))
    mx, my = (x0 + x1) / 2 + lx, (y0 + y1) / 2 + ly
    ax.add_patch(Circle((mx, my), 0.20, fc='white', ec=DIM, lw=1.0, zorder=7))
    ax.text(mx, my, letter, ha='center', va='center', fontsize=9.5,
            fontweight='bold', color=DIM, zorder=8)


def ext(ax, x0, y0, x1, y1):
    ax.plot([x0, x1], [y0, y1], color=DIM, lw=0.5, ls=(0, (3, 2)), zorder=5)


def rule(fig, y, x0=0.055, x1=0.945, c=LIGHT, lw=0.5):
    fig.lines.append(plt.Line2D([x0, x1], [y, y], color=c, lw=lw,
                                transform=fig.transFigure))


# ---------------------------------------------------------------- sheet 1
def sheet1():
    fig = plt.figure(figsize=(8.27, 11.69))
    ax = new_axes(fig, [0.055, 0.330, 0.890, 0.600])
    draw_room(ax); draw_speakers(ax); draw_sofa(ax)
    ax.text(LP_X, LP_Y + 0.80, 'listening position', ha='center', va='center',
            fontsize=8.5, color=INK, style='italic')

    CY = SPK_Y - CAB_D / 2
    ext(ax, TW_L - CAB_W / 2, SPK_Y, -0.58, SPK_Y)
    ext(ax, 0.0, 0.0, -0.58, 0.0)
    dim(ax, -0.45, SPK_Y, -0.45, 0.0, 'A')
    dim(ax, TW_L, SPK_Y, TW_R, SPK_Y, 'B', lx=-0.62)
    dim(ax, 0.0, CY, TW_L - CAB_W / 2, CY, 'C', ly=0.36)
    dim(ax, TW_R + CAB_W / 2, CY, W, CY, 'D', ly=0.36)
    dim(ax, LP_X, LP_Y, TW_L, SPK_Y, 'E', lx=-0.30)
    dim(ax, LP_X, LP_Y, TW_R, SPK_Y, 'F', lx=0.30)
    dim(ax, LP_X, LP_Y, LP_X, 0.0, 'G', lx=0.34)
    ext(ax, W, 0.0, W + 0.62, 0.0)
    ext(ax, W, HALF, W + 0.62, HALF)
    dim(ax, W + 0.45, 0.0, W + 0.45, HALF, 'H')

    fig.text(0.055, 0.962, 'Listening room — measurement sheet', fontsize=16,
             fontweight='bold', color=INK)
    fig.text(0.055, 0.943, 'B&W Nautilus 801 · 120.blue profile · plan view, '
             'not to scale in detail — measure everything below before sweeping',
             fontsize=8.5, color=GREY)
    fig.text(0.945, 0.962, 'date  ______________', fontsize=9, color=INK,
             ha='right')

    rows = [('A', 'tweeter → front wall', 'nominal 120 cm for this profile'),
            ('B', 'tweeter → tweeter (speaker separation)', ''),
            ('C', 'left tweeter → left side wall', 'to the TWEETER, not the cabinet'),
            ('D', 'right tweeter → right side wall', 'the half-wall, not the far wall'),
            ('E', 'listening position → left tweeter', ''),
            ('F', 'listening position → right tweeter', ''),
            ('G', 'listening position → front wall', ''),
            ('H', 'front wall → end of the half-wall', 'decides the right reflection')]
    y = 0.285
    rule(fig, y + 0.021, c=INK, lw=1.0)
    for k, (letter, what, note) in enumerate(rows):
        yy = y - k * 0.0235
        fig.text(0.063, yy, letter, fontsize=10, fontweight='bold', color=DIM)
        fig.text(0.098, yy, what, fontsize=9.5, color=INK)
        fig.text(0.560, yy, '_____________ cm', fontsize=9.5, color=INK)
        fig.text(0.730, yy, note, fontsize=7.8, color=GREY, style='italic')
        rule(fig, yy - 0.0072)
    yb = y - len(rows) * 0.0235 - 0.008
    for lab, x0 in (('mic height', 0.063), ('mic mounting', 0.300),
                    ('mic → sofa back', 0.560), ('ear height', 0.800)):
        fig.text(x0, yb, lab + '  _________', fontsize=8.5, color=INK)
    for lab, x0 in (('toe-in', 0.063), ('speaker angle', 0.300),
                    ('anything within 1 m of a speaker', 0.560)):
        fig.text(x0, yb - 0.020, lab + '  _________', fontsize=8.5, color=INK)
    fig.text(0.055, yb - 0.034, 'Mic mounting is a first-order variable: a mic '
             'on a cushion instead of a stand moved the floor bounce from 2.0 to '
             '~1.1 ms and added\nup to 5.6 dB below 2 ms — larger than any panel '
             'change (measured 2026-08-10).', fontsize=7, color=DIM,
             style='italic', va='top')
    fig.text(0.055, yb - 0.066, 'Notes', fontsize=9, fontweight='bold', color=INK)
    rule(fig, yb - 0.080)
    fig.text(0.055, 0.008, 'Measured 2026-08-10: tweeters 120 cm from the front '
             'wall, 2.74 m apart, 0.68 / 0.70 m to the side walls (to the '
             'TWEETER); listener 4.30 m; half-wall 1.75 m.\nThose sum to 4.120 m '
             'against the 4.186 m decoded from room.png. Length 7.40 m and the '
             '1.4 m corridor opening are still from the sketch.',
             fontsize=7, color=GREY, style='italic', va='bottom')
    return fig


# ---------------------------------------------------------------- sheet 2
PANEL_ROWS = [
    ('S1', 'rock', 'left wall, y = 1.97 m',      'L speaker off the left wall, 2.2 ms', 'already covers it (edge 1.77)'),
    ('S2', 'rock', 'left wall, y = 3.14 m',      'R speaker off the left wall, 8.4 ms', 'on the wall, ±24 cm'),
    ('S3', 'rock', 'half-wall line, y = 1.98 m', 'R speaker mirror point, 2.2 ms',      'bring it here'),
    ('S4', 'rock', 'half-wall line, y = 3.14 m', 'L speaker mirror point, 8.5 ms',      'bring it here'),
    ('F1', 'foam', 'half-wall line, y = 3.90 m', 'escape into the open side',           'behind the screens'),
    ('F2', 'foam', 'half-wall line, y = 4.45 m', 'escape into the open side',           'behind the screens'),
    ('S5', 'rock', 'right rear, y ≈ 5.5 m',      'corridor mouth',                      'leave'),
    ('S6', 'rock', 'behind seat, x ≈ 1.6 m',     'back wall from L, 17.5 ms',           'leave'),
    ('S7', 'rock', 'behind seat, x ≈ 2.8 m',     'back wall from R, 17.5 ms',           'leave'),
]


def sheet2():
    fig = plt.figure(figsize=(8.27, 11.69))
    ax = new_axes(fig, [0.055, 0.535, 0.890, 0.385])
    draw_room(ax, halfwall_note=False); draw_speakers(ax); draw_sofa(ax)
    draw_reflections(ax); draw_panels(ax)

    fig.text(0.055, 0.962, 'Panel positions & reflection points', fontsize=16,
             fontweight='bold', color=INK)
    fig.text(0.055, 0.943, 'Targets are COMPUTED mirror points — the panels are '
             'drawn there, not where they stand today.', fontsize=8.5, color=GREY)
    fig.text(0.945, 0.962, 'date  ______________', fontsize=9, color=INK,
             ha='right')
    for lab, c, x0 in (('GIK freestanding screen', ROCK, 0.055),
                       ('pyramidal foam', FOAM, 0.290),
                       ('specular reflection point', REFL, 0.470),
                       ('projector screen', SCREEN, 0.750)):
        fig.text(x0, 0.928, '■  ' + lab, fontsize=7.6, color=c)

    y = 0.508
    for cname, x0 in (('panel', 0.063), ('TARGET — computed', 0.128),
                      ('the reflection it treats', 0.330),
                      ('as found', 0.615), ('action', 0.760)):
        fig.text(x0, y + 0.013, cname, fontsize=7.5, color=GREY)
    rule(fig, y + 0.007, c=INK, lw=1.0)
    for k, (tag, kind, where, treats, note) in enumerate(PANEL_ROWS):
        yy = y - 0.010 - k * 0.0198
        c = ROCK if kind == 'rock' else FOAM
        fig.text(0.063, yy, tag, fontsize=9, fontweight='bold', color=c)
        fig.text(0.128, yy, where, fontsize=8.2, color=INK)
        fig.text(0.330, yy, treats, fontsize=8.2, color=INK)
        fig.text(0.615, yy, '_________ cm', fontsize=8.2, color=INK)
        fig.text(0.760, yy, note, fontsize=7.4, color=GREY, style='italic')
        rule(fig, yy - 0.0068)

    yc = y - 0.010 - len(PANEL_ROWS) * 0.0198 - 0.026
    fig.text(0.055, yc, 'Configuration measured', fontsize=9.5,
             fontweight='bold', color=INK)
    for i, lab in enumerate(['baseline — as it was: foam at y 2.0 / 2.9 m, '
                             'S3 / S4 out in the open   (measure this first)',
                             'as drawn — continuous pseudo-wall, 1.75 → 4.6 m',
                             'as drawn, plus screens in front of the projector '
                             'screen (1.05 m off centre each side)',
                             'other  ___________________________________']):
        fig.text(0.063, yc - 0.020 - i * 0.0175, '□   ' + lab,
                 fontsize=8.5, color=INK)

    yr = yc - 0.020 - 4 * 0.0175 - 0.020
    fig.text(0.055, yr, 'Result — early energy relative to direct, '
             '300 Hz – 8 kHz (NOTES §8)', fontsize=9.5, fontweight='bold',
             color=INK)
    xs = [0.063, 0.250, 0.370, 0.490, 0.640]
    rule(fig, yr - 0.011, c=INK, lw=1.0)
    for cname, x0 in zip(['window', 'L', 'R', 'L − R', 'was, 120 cm (L / R)'], xs):
        fig.text(x0, yr - 0.025, cname, fontsize=7.8, color=GREY)
    prev = ['−7.9 / −7.3', '−4.6 / −5.3', '−9.9 / −8.1', '−8.5 / −3.2', '', '']
    for k, wname in enumerate(['0.3 – 2 ms', '2 – 5 ms', '5 – 10 ms',
                               '10 – 20 ms', 'EDT 250 Hz', 'EDT 500 Hz']):
        yy = yr - 0.040 - k * 0.0178
        fig.text(xs[0], yy, wname, fontsize=8.2, color=INK)
        for j in (1, 2, 3):
            fig.text(xs[j], yy, '_________', fontsize=8.2, color=INK)
        fig.text(xs[4], yy, prev[k], fontsize=7.6, color=GREY, style='italic')
        rule(fig, yy - 0.0062)

    fig.text(0.055, 0.008, 'y is the point on the WALL where the ray reflects. '
             'Panels lie ON the wall (NOTES §9: flat on the wall at the mirror '
             'point is correct for a\nspecular travelling wave). The ray then '
             'crosses a 10 cm panel over a 23 cm window at the 1.97 m target, so '
             'a 60 cm panel is right if centred within ±19 cm.\nFresnel is the '
             'bigger constraint: full absorption needs 1.46 m of panel at 500 Hz. '
             'Do not judge panels on the bass; change one thing per measurement.',
             fontsize=7, color=GREY, style='italic', va='bottom')
    return fig


f1, f2 = sheet1(), sheet2()
with PdfPages('room-form.pdf') as pdf:
    pdf.savefig(f1, facecolor='white')
    pdf.savefig(f2, facecolor='white')
f1.savefig('room-form.png', dpi=110, facecolor='white')
f2.savefig('room-form-panels.png', dpi=110, facecolor='white')
print('wrote room-form.pdf (2 pages), room-form.png, room-form-panels.png')
