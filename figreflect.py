#!/usr/bin/env python3
"""First-reflection study, one A4 page per channel -> reflections-L-R.pdf

Each page carries three things:

  PLAN        the real folded ray paths, source -> reflection point -> ear,
              with the mirror image drawn wherever it fits on the sheet so the
              construction is visible rather than asserted.
  SECTION     floor and ceiling, drawn in the vertical plane that actually
              contains the source and the ear (so its horizontal axis is the
              3.39 m slant distance, not the 3.10 m axial one -- the drawing is
              then exact rather than a projection).
  TABLE       the arithmetic for every surface: image position, path, excess,
              delay, level from spreading, and where it lands.

Geometry comes from roomgeom.py.  Nothing here is typed in twice.
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle, Circle, FancyArrowPatch
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import roomgeom as g

INK, GREY, LIGHT = '#111111', '#666666', '#b5b5b5'
RAY   = '#1f4e79'      # the real, folded path
GHOST = '#9aa8b5'      # the mirror image and its straight line
REFL  = '#8a5a00'      # reflection points
DEAD  = '#c1272d'      # a reflection that has no surface to happen on
SCREEN = '#2e8b3d'

PLAN_SURFACES = [('left side wall', 0, 0.0), ('right side wall', 0, g.W),
                 ('front wall', 1, 0.0), ('back wall', 1, g.L)]


def draw_room(ax):
    walls = [(0, 0), (g.W, 0), (g.W, g.HALF), (g.W2, g.HALF), (g.W2, g.L),
             (g.CHAM_X, g.L), (0, g.CHAM_Y)]
    ax.add_patch(Polygon(walls, closed=True, fc='#fcfcfc', ec='none', zorder=0))
    for i in range(len(walls)):
        x0, y0 = walls[i]; x1, y1 = walls[(i + 1) % len(walls)]
        if y0 == g.L and y1 == g.L:
            ax.plot([min(x0, x1), g.CORR_X0], [g.L, g.L], color=INK, lw=2.0, zorder=3)
            ax.plot([g.CORR_X1, max(x0, x1)], [g.L, g.L], color=INK, lw=2.0, zorder=3)
            continue
        ax.plot([x0, x1], [y0, y1], color=INK, lw=2.0, zorder=3)
    sx = g.LP_X
    ax.plot([sx - g.SCR_W / 2, sx + g.SCR_W / 2], [0.07, 0.07], color=SCREEN,
            lw=4, solid_capstyle='butt', zorder=3)
    for xt, tag in ((g.TW_L, 'L'), (g.TW_R, 'R')):
        ax.add_patch(Rectangle((xt - g.CAB_W / 2, g.SPK_Y - g.CAB_D),
                               g.CAB_W, g.CAB_D, fc='#e6e6e6', ec=INK, lw=0.9,
                               zorder=4))
        ax.text(xt, g.SPK_Y - g.CAB_D / 2, tag, ha='center', va='center',
                fontsize=9, fontweight='bold', color=INK, zorder=5)
    ax.add_patch(Rectangle((g.LP_X - 1.05, g.LP_Y - 0.47), 2.10, 0.80,
                           fc='#f0f0f0', ec=GREY, lw=0.9, zorder=2))
    ax.plot([g.LP_X], [g.LP_Y], marker='+', ms=11, mew=1.5, color=INK, zorder=6)
    ax.add_patch(Circle((g.LP_X, g.LP_Y), 0.14, fc='none', ec=INK, lw=1.2,
                        zorder=6))


def plan(ax, ch):
    S = g.SRC[ch]
    draw_room(ax)
    ax.plot([S[0], g.LP_X], [S[1], g.LP_Y], color=INK, lw=1.4, zorder=5)
    ax.text((S[0] + g.LP_X) / 2 + 0.10, (S[1] + g.LP_Y) / 2, 'direct\n%.2f m'
            % g.direct_distance(ch), fontsize=6.6, color=INK, ha='left',
            va='center', style='italic', zorder=7, linespacing=1.25)

    for name, axis, plane in PLAN_SURFACES:
        r = g.reflection(S, axis, plane)
        P, I = r['point'], r['image']
        live = g.wall_hit_is_real(axis, plane, P)
        col = RAY if live else DEAD
        ax.plot([S[0], P[0], g.LP_X], [S[1], P[1], g.LP_Y], color=col, lw=1.0,
                zorder=5)
        ax.plot([P[0]], [P[1]], marker='D', ms=5.0, zorder=8,
                mfc=REFL if live else 'white', mec='white' if live else DEAD,
                mew=0.8 if live else 1.2)
        # draw the construction where the image fits on the sheet
        if -1.15 < I[0] < g.W2 + 0.65 and -1.75 < I[1] < g.L + 0.5:
            ax.plot([I[0], g.LP_X], [I[1], g.LP_Y], color=GHOST, lw=0.8,
                    ls=(0, (3, 2)), zorder=4)
            ax.add_patch(Rectangle((I[0] - g.CAB_W / 2, I[1] - g.CAB_D),
                                   g.CAB_W, g.CAB_D, fc='none', ec=GHOST,
                                   lw=0.9, ls=(0, (2, 2)), zorder=4))
            ax.text(I[0], I[1] + 0.26, 'image', ha='center', va='center',
                    fontsize=6.2, color=GHOST, style='italic', zorder=5)
        lab = ('%.1f ms' % r['delay'] if live else
               'NO WALL HERE\n%.0f cm past the end\n(would be %.1f ms)'
               % ((P[1] - g.HALF) * 100, r['delay']))
        if axis == 0:
            dx, dy, ha = ((-0.18, 0.0, 'right') if plane == 0.0
                          else (0.22, (0.55 if not live else 0.0), 'left'))
        else:
            dx, dy, ha = 0.0, (-0.34 if plane == 0.0 else 0.34), 'center'
        ax.text(P[0] + dx, P[1] + dy, lab, fontsize=6.6, color=col, ha=ha,
                va='center', zorder=8, linespacing=1.25)

    ax.set_aspect('equal'); ax.axis('off')
    ax.set_xlim(-1.35, g.W2 + 0.70)
    ax.set_ylim(g.L + 0.60, -1.75)
    ax.text(g.W / 2, -1.45, 'F R O N T   W A L L', ha='center', va='center',
            fontsize=8.5, fontweight='bold', color=INK)


def section(ax, ch):
    """Floor and ceiling, in the vertical plane through source and ear."""
    S = g.SRC[ch]
    run = float(np.hypot(g.LP_X - S[0], g.LP_Y - S[1]))   # true slant distance
    ax.plot([-0.5, run + 0.5], [0, 0], color=INK, lw=2.0)
    ax.plot([-0.5, run + 0.5], [g.CEIL, g.CEIL], color=INK, lw=2.0)
    ax.add_patch(Rectangle((-0.20, 0), 0.40, g.Z_TW, fc='#e6e6e6', ec=INK,
                           lw=0.9))
    ax.plot([0], [g.Z_TW], marker='o', ms=4, mfc='white', mec=INK, mew=1.1)
    ax.plot([run], [g.Z_EAR], marker='+', ms=11, mew=1.5, color=INK)
    ax.plot([0, run], [g.Z_TW, g.Z_EAR], color=INK, lw=1.4)
    for name, plane, zi in (('floor', 0.0, -g.Z_TW),
                            ('ceiling', g.CEIL, 2 * g.CEIL - g.Z_TW)):
        f = (zi - plane) / (zi - g.Z_EAR)
        xr = f * run
        r = g.reflection(S, 2, plane)
        ax.plot([0, xr, run], [g.Z_TW, plane, g.Z_EAR], color=RAY, lw=1.0)
        ax.plot([0, run], [zi, g.Z_EAR], color=GHOST, lw=0.8, ls=(0, (3, 2)))
        ax.plot([0], [zi], marker='o', ms=4, mfc='none', mec=GHOST, mew=1.1)
        ax.text(0.12, zi, 'image', fontsize=6.2, color=GHOST, style='italic',
                va='center')
        ax.plot([xr], [plane], marker='D', ms=5.0, mfc=REFL, mec='white', mew=0.8)
        ax.text(xr, plane + (0.22 if plane == 0 else -0.22), '%s  %.2f ms'
                % (name, r['delay']), fontsize=6.6, color=RAY, ha='center',
                va='center')
    ax.set_aspect('equal'); ax.axis('off')
    ax.set_xlim(-0.7, run + 0.8)
    ax.set_ylim(-g.Z_TW - 0.55, 2 * g.CEIL - g.Z_TW + 0.55)
    ax.text(run / 2, -g.Z_TW - 0.42, 'SECTION through tweeter and ear\n'
            'horizontal axis is the %.2f m slant distance — exact, not a '
            'projection' % run, ha='center', va='center', fontsize=6.5,
            color=GREY, style='italic', linespacing=1.3)


def arrivals(ax, ch):
    """The same information on a time axis — directly comparable to REW's ETC."""
    S = g.SRC[ch]
    FLOOR = -13.0
    ax.axhline(0, color=LIGHT, lw=0.7, ls=(0, (4, 3)))
    ax.plot([0, 0], [FLOOR, 0], color=INK, lw=2.0, solid_capstyle='butt')
    ax.plot([0], [0], marker='o', ms=6, mfc=INK, mec='white', mew=0.9, zorder=5)
    ax.text(0.25, 0.6, 'direct', fontsize=7.2, color=INK, fontweight='bold')
    items = []
    for name, axis, plane in g.SURFACES:
        r = g.reflection(S, axis, plane)
        live = g.wall_hit_is_real(axis, plane, r['point'])
        items.append((r['delay'], r['level'], name, live))
    items.sort()
    # arrivals cluster around 2-3 ms, so stack the labels into lanes
    lane, prev_t = 0, -99.0
    for t, lv, name, live in items:
        col = RAY if live else DEAD
        lane = lane + 1 if t - prev_t < 2.2 else 0
        prev_t = t
        ax.plot([t, t], [FLOOR, lv], color=col, lw=1.4,
                ls='solid' if live else (0, (2, 2)), solid_capstyle='butt')
        ax.plot([t], [lv], marker='o', ms=5.5, zorder=5, mew=1.0,
                mfc=col if live else 'white', mec='white' if live else col)
        right = t > 14.0                      # keep late labels on the sheet
        ax.annotate('%s   %.2f ms  %+.1f dB'
                    % (name.replace(' side wall', ' wall'), t, lv),
                    xy=(t, lv),
                    xytext=(t + (-0.45 if right else 0.45),
                            lv + 0.9 + lane * 1.75),
                    fontsize=6.4, color=col, va='center',
                    ha='right' if right else 'left',
                    arrowprops=dict(arrowstyle='-', lw=0.5, color=col,
                                    shrinkA=0, shrinkB=3))
    ax.set_xlim(-0.8, 20.5); ax.set_ylim(FLOOR, 4.2)
    ax.set_yticks([0, -3, -6, -9, -12])
    ax.tick_params(labelsize=6.8, colors=GREY, length=2)
    for sp in ('top', 'right'):
        ax.spines[sp].set_visible(False)
    for sp in ('left', 'bottom'):
        ax.spines[sp].set_color(GREY); ax.spines[sp].set_linewidth(0.6)
    ax.set_xlabel('ms after the direct sound', fontsize=7.2, color=GREY)
    ax.set_ylabel('dB', fontsize=7.2, color=GREY)
    ax.text(20.3, 3.4, 'ARRIVALS — spreading loss only, no absorption',
            fontsize=6.8, color=GREY, ha='right', style='italic')


def rule(fig, y, x0=0.055, x1=0.945, c=LIGHT, lw=0.5):
    fig.lines.append(plt.Line2D([x0, x1], [y, y], color=c, lw=lw,
                                transform=fig.transFigure))


def page(ch):
    fig = plt.figure(figsize=(8.27, 11.69))
    plan(fig.add_axes([0.045, 0.480, 0.500, 0.435]), ch)
    section(fig.add_axes([0.565, 0.545, 0.405, 0.330]), ch)
    arrivals(fig.add_axes([0.075, 0.345, 0.885, 0.130]), ch)

    fig.text(0.055, 0.962, '%s speaker — first reflections'
             % ('LEFT' if ch == 'L' else 'RIGHT'), fontsize=16,
             fontweight='bold', color=INK)
    fig.text(0.055, 0.943, 'Mirror the source in the surface — the reflected '
             'path is then the straight line from image to ear.',
             fontsize=8.4, color=GREY)
    fig.text(0.945, 0.962, 'DRC-185 · 120.blue', fontsize=8.5, color=GREY,
             ha='right')
    for lab, c, x0 in (('real path', RAY, 0.055), ('mirror image + its straight line',
                       GHOST, 0.175), ('reflection point', REFL, 0.430),
                       ('no surface there', DEAD, 0.600)):
        fig.text(x0, 0.925, '——  ' + lab, fontsize=7.4, color=c)

    S = g.SRC[ch]
    y = 0.290
    cols = [('surface', 0.058), ('image at (x, y, z)', 0.200),
            ('path', 0.400), ('excess', 0.470), ('delay', 0.552),
            ('level', 0.630), ('lands at', 0.710)]
    for cname, x0 in cols:
        fig.text(x0, y + 0.014, cname, fontsize=7.4, color=GREY)
    rule(fig, y + 0.008, c=INK, lw=1.0)
    fig.text(0.058, y - 0.008, 'direct', fontsize=8.6, fontweight='bold', color=INK)
    fig.text(0.400, y - 0.008, '%.3f m' % g.direct_distance(ch), fontsize=8.6,
             color=INK)
    rule(fig, y - 0.016)

    for k, (name, axis, plane) in enumerate(g.SURFACES):
        r = g.reflection(S, axis, plane)
        P, I = r['point'], r['image']
        live = g.wall_hit_is_real(axis, plane, P)
        yy = y - 0.034 - k * 0.0205
        col = INK if live else DEAD
        fig.text(0.058, yy, name, fontsize=8.4, color=col)
        fig.text(0.200, yy, '(%+.2f, %+.2f, %+.2f)' % tuple(I), fontsize=8.0,
                 color=col)
        fig.text(0.400, yy, '%.3f m' % r['path'], fontsize=8.4, color=col)
        fig.text(0.470, yy, '%+.3f m' % r['excess'], fontsize=8.4, color=col)
        fig.text(0.552, yy, '%.2f ms' % r['delay'], fontsize=8.4, color=col,
                 fontweight='bold')
        fig.text(0.630, yy, '%+.2f dB' % r['level'], fontsize=8.4, color=col)
        if axis == 0:
            where = 'y = %.2f m' % P[1]
            if not live:
                where += '  — %.0f cm past the half-wall' % ((P[1] - g.HALF) * 100)
        elif axis == 1:
            where = 'x = %.2f m  (%.2f m off centre)' % (P[0], abs(P[0] - g.LP_X))
        else:
            where = '%.2f m from the front wall' % P[1]
        fig.text(0.710, yy, where, fontsize=7.6, color=col)
        rule(fig, yy - 0.0072)

    yn = y - 0.034 - len(g.SURFACES) * 0.0205 - 0.020
    fig.text(0.055, yn, 'Reading it', fontsize=9, fontweight='bold', color=INK)
    notes = ['level is spreading loss only — subtract whatever the surface '
             'absorbs, and the speaker\'s own off-axis roll-off on top of that',
             'the RIGHT side wall stops 1.75 m from the front wall, so both of '
             'its mirror points have no surface to happen on',
             'floor: the drivers sit at different heights, so it is not one '
             'arrival — woofers ~1.1 ms, tweeter 2.0 ms',
             'ceiling assumed flat at %.1f m; the real one slants 2.4 → 3.0 m '
             'and is beamed, so above ~800 Hz it scatters rather than mirrors'
             % g.CEIL]
    for i, t in enumerate(notes):
        fig.text(0.063, yn - 0.019 - i * 0.0165, '·  ' + t, fontsize=7.6,
                 color=GREY)

    fig.text(0.055, 0.012, 'Geometry from roomgeom.py — measured 2026-08-10, all '
             'to the tweeter. Room length, the corridor opening and the ceiling '
             'are still from the pencil plan.', fontsize=7, color=GREY,
             style='italic', va='bottom')
    return fig


figs = [page('L'), page('R')]
with PdfPages('reflections-L-R.pdf') as pdf:
    for f in figs:
        pdf.savefig(f, facecolor='white')
for f, ch in zip(figs, 'LR'):
    f.savefig('reflections-%s.png' % ch, dpi=110, facecolor='white')
print('wrote reflections-L-R.pdf (2 pages), reflections-L.png, reflections-R.png')
