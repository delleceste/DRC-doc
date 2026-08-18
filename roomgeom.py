#!/usr/bin/env python3
"""Single source of truth for the DRC-185 / 120.blue listening-room geometry.

Imported by figroom.py (the measurement sheets) and figreflect.py (the
reflection study) so the two can never drift apart -- which they would, since
this geometry was revised three times in one afternoon.

MEASURED 2026-08-10, all to the TWEETER (the cabinet's vertical centre axis,
which is what the image-source construction mirrors):

    tweeter to front wall        1.20 m
    tweeter to tweeter           2.74 m
    left tweeter to left wall    0.68 m
    right tweeter to right wall  0.70 m
    listener to front wall       4.30 m
    tweeter height               1.20 m
    ear height                   1.08 m
    half-wall length             1.75 m   (confirmed)

Those sum to 4.120 m across the speaker line, against the 4.186 m decoded from
the pencil plan in room.png -- a 66 mm residual, so the tape closes.  W below
follows the tape.

STILL FROM THE SKETCH, not measured: room length 7.40 m, the 1.80 m the room
opens by past the half-wall, the 1.4 m corridor opening at the back-right, the
back-left chamfer, and the ceiling slant.  Treat those as indicative.
"""
import numpy as np

C = 343.0               # m/s

# --- architecture -------------------------------------------------------
L        = 7.400        # front wall to back wall
W        = 4.120        # width at the speaker line (0.68 + 2.74 + 0.70)
W2       = 5.920        # width past the half-wall (W + 1.80)
HALF     = 1.750        # how far the half-wall runs in from the front wall
CORR_X0, CORR_X1 = 4.520, 5.920   # 1.4 m corridor opening, back-right corner
CHAM_Y, CHAM_X   = 6.20, 1.20     # chamfered back-left corner
SCR_W    = 2.500        # projector screen width, on the front wall
CEIL     = 2.600        # ASSUMED flat; the real ceiling slants 2.4 -> 3.0 m
                        # and is heavily beamed, so it scatters above ~800 Hz

# --- system -------------------------------------------------------------
SPK_Y    = 1.200        # tweeter to front wall
TW_L, TW_R = 0.680, 3.420        # tweeters, 2.74 m apart
Z_TW, Z_EAR = 1.200, 1.080       # heights; the ear is 2.0 deg below the axis
CAB_W, CAB_D = 0.41, 0.55        # cabinet footprint, for drawing only
LP_X, LP_Y = (TW_L + TW_R) / 2, 4.300

MIC = np.array([LP_X, LP_Y, Z_EAR])
SRC = {'L': np.array([TW_L, SPK_Y, Z_TW]),
       'R': np.array([TW_R, SPK_Y, Z_TW])}

# axis index for each reflecting plane, and the plane's coordinate
SURFACES = [('left side wall',  0, 0.0),
            ('right side wall', 0, W),
            ('front wall',      1, 0.0),
            ('back wall',       1, L),
            ('floor',           2, 0.0),
            ('ceiling',         2, CEIL)]


def image(S, axis, plane):
    """Mirror image of source S in the given plane."""
    I = np.array(S, float)
    I[axis] = 2 * plane - I[axis]
    return I


def reflection(S, axis, plane, M=MIC):
    """Everything about one first-order specular reflection.

    The whole method in three lines: mirror the source, the reflected path is
    then the straight line from the image to the receiver, and the reflection
    point is where that line crosses the plane.
    """
    S = np.array(S, float)
    I = image(S, axis, plane)
    direct = float(np.linalg.norm(S - M))
    path = float(np.linalg.norm(I - M))
    f = (I[axis] - plane) / (I[axis] - M[axis])
    return dict(image=I, direct=direct, path=path,
                excess=path - direct,
                delay=(path - direct) / C * 1000.0,
                level=-20 * np.log10(path / direct),
                point=I + f * (M - I))


def direct_distance(ch):
    return float(np.linalg.norm(SRC[ch] - MIC))


def wall_hit_is_real(axis, plane, P):
    """Does the reflection point land on a surface that actually exists?"""
    if axis == 0 and plane == W:            # the right wall stops at HALF
        return P[1] <= HALF
    return True
