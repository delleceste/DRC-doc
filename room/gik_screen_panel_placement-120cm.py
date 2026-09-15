#!/usr/bin/env python3
"""Build the figures for GIK-SCREEN-PANEL-PLACEMENT-120cm.md.

The geometry comes from roomgeom.py in the documentation repository. The
measurement figure reads the two panel-order comparison sets from the sibling
../DRC-120.blue repository. Reading REW's Java-serialised MDAT requires
javaobj-py3; install it with:

    python3 -m pip install javaobj-py3
"""

from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc, Polygon, Rectangle
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import brentq

ROOT = Path(__file__).resolve().parent
DOC = ROOT
DATA = (ROOT / "../DRC-120.blue").resolve()
sys.path.insert(0, str(DOC))
from roomgeom import C, MIC, SRC, reflection  # noqa: E402


# Legacy/current ScreenPanel width: 815 mm unfolded, two hinged halves.
HALF_LEAF = 0.815 / 2
PANEL_HEIGHT = 1.830
EDGE_MARGIN = 0.100

S = SRC["L"]
M = MIC
REFL = reflection(S, 0, 0.0)
P = REFL["point"]
INCIDENT_SLOPE = (P[1] - S[1]) / S[0]
OUTGOING_SLOPE = (M[1] - P[1]) / M[0]


def panel_geometry(opening_deg, centre_y):
    """Return hinge and endpoints for a V whose hinge touches the wall."""
    theta = np.radians((180.0 - opening_deg) / 2.0)
    depth = HALF_LEAF * np.sin(theta)
    half_span = HALF_LEAF * np.cos(theta)
    hinge = np.array([0.0, centre_y])
    front = np.array([depth, centre_y - half_span])
    rear = np.array([depth, centre_y + half_span])
    return front, hinge, rear, depth, half_span


def shift_capacity(opening_deg):
    """Max downstream hinge shift for either ray to meet a leaf endpoint."""
    *_, depth, half_span = panel_geometry(opening_deg, P[1])
    return abs(half_span - INCIDENT_SLOPE * depth)


def recommended_shift(opening_deg):
    """Shift which makes the reflected path meet the active leaf halfway."""
    return 0.5 * shift_capacity(opening_deg)


def ray_y(x, branch):
    if branch == "incident":
        return P[1] - INCIDENT_SLOPE * x
    return P[1] + OUTGOING_SLOPE * x


def fresnel_interval(freq_hz, axis="y"):
    """Exact first-Fresnel-zone intersection with the concrete wall."""
    wavelength = C / freq_hz
    direct_path = REFL["path"]

    def residual(value):
        q = P.copy()
        q[1 if axis == "y" else 2] = value
        path = np.linalg.norm(S - q) + np.linalg.norm(M - q)
        return path - direct_path - wavelength / 2.0

    centre = P[1 if axis == "y" else 2]
    lo = brentq(residual, centre - 10.0, centre - 1e-10)
    hi = brentq(residual, centre + 1e-10, centre + 10.0)
    return lo, hi


def build_geometry_figure():
    fig = plt.figure(figsize=(11.2, 7.2), constrained_layout=True)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.05, 1.25])

    ax = fig.add_subplot(gs[0, 0])
    ax.set_title("(a) Exact left-wall specular reflection", loc="left", weight="bold")
    ax.plot([0, 0], [0, 4.7], color="black", lw=3, label="concrete left wall")
    ax.plot([S[0], P[0], M[0]], [S[1], P[1], M[1]], color="#1f4e79", lw=2.4)
    ax.scatter([S[0], M[0], P[0]], [S[1], M[1], P[1]],
               c=["#333333", "#333333", "#c1272d"], s=[65, 65, 85], zorder=5)
    ax.text(S[0] + .05, S[1] - .12, "left tweeter\n(0.680, 1.200 m)", fontsize=9)
    ax.text(M[0] + .05, M[1] - .20, "ear/mic\n(2.050, 4.300 m)", fontsize=9)
    ax.text(P[0] + .05, P[1] + .07,
            f"P = (0, {P[1]:.4f}, {P[2]:.4f}) m\nexcess {REFL['delay']:.3f} ms",
            fontsize=9, color="#9b1c1c")
    for f, col in [(500, "#f3c969"), (1000, "#d9a441")]:
        lo, hi = fresnel_interval(f)
        ax.plot([-.035, -.035], [lo, hi], color=col, lw=8, alpha=.85,
                solid_capstyle="butt", label=f"{f} Hz wall-projected first Fresnel span")
    ax.set(xlim=(-.15, 2.45), ylim=(0.75, 4.55), xlabel="distance from left wall x (m)",
           ylabel="distance from front wall y (m)")
    ax.set_aspect("equal")
    ax.grid(alpha=.2)
    ax.legend(fontsize=8, loc="lower right")

    ax = fig.add_subplot(gs[0, 1])
    ax.set_title("(b) 90° open-book: safe +2 cm shift\nversus unsafe edge placement",
                 loc="left", weight="bold")
    ax.plot([0, 0], [1.05, 2.85], color="black", lw=3)
    xx = np.linspace(0, .76, 200)
    ax.plot(xx, ray_y(xx, "incident"), color="#1f4e79", lw=2.2, label="incident ray")
    ax.plot(xx, ray_y(xx, "outgoing"), color="#1f4e79", lw=2.2, ls="--", label="reflected ray")
    ax.scatter([0], [P[1]], s=80, c="#c1272d", zorder=6)

    # Recommended: ray meets the rear leaf at its midpoint.
    alpha = 90.0
    rec_y = P[1] + recommended_shift(alpha)
    front, hinge, rear, _, _ = panel_geometry(alpha, rec_y)
    ax.plot([front[0], hinge[0], rear[0]], [front[1], hinge[1], rear[1]],
            color="#c1272d", lw=10, solid_capstyle="butt", label="recommended 90° ScreenPanel")
    ax.scatter([hinge[0]], [hinge[1]], c="#c1272d", marker="s", s=45, zorder=7)
    ax.annotate(f"hinge y = {rec_y:.3f} m\n(+{(rec_y-P[1])*100:.1f} cm)",
                xy=hinge, xytext=(.40, 2.55), arrowprops=dict(arrowstyle="->", color="#9b1c1c"),
                fontsize=9, color="#9b1c1c")

    # Unsafe interpretation of "point at the front edge" for a folded V.
    _, _, _, _, hs = panel_geometry(alpha, P[1])
    unsafe_y = P[1] + hs
    uf, uh, ur, _, _ = panel_geometry(alpha, unsafe_y)
    ax.plot([uf[0], uh[0], ur[0]], [uf[1], uh[1], ur[1]],
            color="#777777", lw=5, ls=(0, (4, 3)), alpha=.85,
            label="unsafe large downstream shift")
    ax.annotate("ray passes through the V\nwithout touching either leaf",
                xy=(.18, ray_y(.18, "outgoing")), xytext=(.39, 1.35),
                arrowprops=dict(arrowstyle="->", color="#555555"), fontsize=9, color="#555555")
    ax.text(.02, P[1] - .08, "wall point", color="#9b1c1c", fontsize=9)
    ax.set(xlim=(-.08, .78), ylim=(1.05, 2.85), xlabel="distance into room x (m)",
           ylabel="distance from front wall y (m)")
    ax.set_aspect("equal")
    ax.grid(alpha=.2)
    ax.legend(fontsize=8, loc="upper right")

    fig.suptitle("Left GIK ScreenPanel placement — ray geometry, not wall projection alone",
                 fontsize=15, weight="bold")
    out = ROOT / "panel-placement-left-reflection-120cm.png"
    fig.savefig(out, dpi=180, facecolor="white")
    plt.close(fig)


def build_angle_figure():
    angles = np.linspace(75, 180, 421)
    caps = np.array([shift_capacity(a) for a in angles])
    mids = caps / 2
    safe_min = caps * EDGE_MARGIN / HALF_LEAF
    safe_max = caps * (1 - EDGE_MARGIN / HALF_LEAF)

    fig = plt.figure(figsize=(11.2, 7.4), constrained_layout=True)
    gs = fig.add_gridspec(2, 4, height_ratios=[3.3, 1.35])
    ax = fig.add_subplot(gs[0, :])
    ax.fill_between(angles, safe_min * 100, safe_max * 100, color="#bed7e8", alpha=.8,
                    label="ray hits ≥10 cm from hinge and outer edge")
    ax.plot(angles, mids * 100, color="#1f4e79", lw=2.5, label="ray hits leaf midpoint (recommended)")
    ax.plot(angles, caps * 100, color="#777777", lw=1.3, ls="--", label="geometric limit: leaf endpoint")
    for a in [90, 120, 150, 180]:
        y = recommended_shift(a) * 100
        ax.scatter([a], [y], color="#c1272d", s=40, zorder=5)
        ax.annotate(f"{a:.0f}°: +{y:.1f} cm", (a, y), xytext=(4, 7),
                    textcoords="offset points", fontsize=9)
    parallel_theta = np.degrees(np.arctan(1 / INCIDENT_SLOPE))
    parallel_opening = 180 - 2 * parallel_theta
    ax.axvline(parallel_opening, color="#d28f00", lw=1.5, ls=":")
    ax.text(parallel_opening + 1, 34, f"ray nearly parallel to a leaf\n({parallel_opening:.1f}°)",
            fontsize=9, color="#9a6800")
    ax.set(xlim=(75, 181), ylim=(0, 43), xlabel="included opening angle between the two leaves",
           ylabel="hinge shift toward listener, beyond P (cm)")
    ax.grid(alpha=.25)
    ax.legend(loc="upper left", fontsize=9)
    ax.set_title("How far may the ScreenPanel centre move behind the exact reflection point?",
                 weight="bold")

    # Scaled plan-view sketches make the included-angle convention explicit.
    # The wall is vertical at the hinge and both leaves point into the room.
    for col, opening in enumerate((90, 120, 150, 180)):
        sketch = fig.add_subplot(gs[1, col])
        shift = recommended_shift(opening)
        front, hinge, rear, _, _ = panel_geometry(opening, 0.0)
        sketch.plot([-.025, -.025], [-.48, .48], color="black", lw=3,
                    solid_capstyle="butt")
        sketch.plot([front[0], hinge[0], rear[0]],
                    [front[1], hinge[1], rear[1]],
                    color="#c1272d", lw=8, solid_capstyle="butt")
        sketch.scatter([0], [0], marker="s", s=35, color="#7f1010", zorder=4)
        sketch.add_patch(Arc((0, 0), .28, .28,
                             theta1=-opening / 2, theta2=opening / 2,
                             color="#1f4e79", lw=2))
        sketch.text(.105, 0, f"{opening}°", ha="center", va="center",
                    color="#1f4e79", fontsize=11, weight="bold")
        sketch.text(-.045, .46, "wall", ha="right", va="top", fontsize=8,
                    rotation=90)
        sketch.set_title(f"{opening}° opening", fontsize=11, weight="bold", pad=4)
        sketch.text(.21, -.48,
                    f"shift +{shift * 100:.1f} cm\nhinge y = {P[1] + shift:.3f} m",
                    ha="center", va="bottom", fontsize=8.5)
        sketch.set(xlim=(-.075, .48), ylim=(-.50, .50))
        sketch.set_aspect("equal")
        sketch.axis("off")

    fig.suptitle("Opening angle, panel shape and permissible downstream placement",
                 fontsize=15, weight="bold")
    out = ROOT / "panel-placement-opening-angle-120cm.png"
    fig.savefig(out, dpi=180, facecolor="white")
    plt.close(fig)


def fields(instance):
    result = {}
    for data in instance.field_data.values():
        result.update({field.name: value for field, value in data.items()})
    return result


def load_mdat():
    try:
        import javaobj.v2 as javaobj
    except ImportError as exc:
        raise SystemExit("javaobj-py3 is required to rebuild the measurement plot") from exc
    with (DATA / "foam.screens.opendoor.mdat").open("rb") as stream:
        objects = javaobj.load(stream)
    measurements = {}
    for obj in objects:
        if getattr(getattr(obj, "classdesc", None), "name", None) != "roomeqwizard.MeasData":
            continue
        m = fields(obj)
        if m.get("irData") is None:
            continue
        ir = fields(m["irData"])
        sampled = fields(ir["ir"])
        measurements[str(m["shortDesc"])] = (np.asarray(sampled["data"], float), float(sampled["T"]))
    return measurements


PPO = 96
FG = 20 * 2 ** (np.arange(int(np.log2(20000 / 20) * PPO) + 1) / PPO)


def smooth(freq, db, fraction=6):
    power = 10 ** (np.interp(np.log(FG), np.log(freq), db) / 10)
    sigma = (PPO / fraction) / 2.355
    return 10 * np.log10(gaussian_filter1d(power, sigma=sigma, mode="nearest"))


def ir_response(item):
    data, dt = item
    freq = np.fft.rfftfreq(len(data), dt)
    db = 20 * np.log10(np.maximum(np.abs(np.fft.rfft(data)), 1e-30))
    valid = freq >= 1
    return smooth(freq[valid], db[valid])


def text_response(name):
    values = np.loadtxt(DATA / "120.blue.Rscreen.txts.boh" / name, comments="*")
    return smooth(values[:, 0], values[:, 1])


def aligned_delta(new, old):
    delta = new - old
    align = (FG >= 500) & (FG <= 5000)
    return delta - np.median(delta[align])


def build_measurement_figure():
    m = load_mdat()
    set_a = {
        "L": aligned_delta(ir_response(m["L 120.blue.screens"]),
                           ir_response(m["L 120.blue.legacy.foam.entrance door open"])),
        "R": aligned_delta(ir_response(m["R 120.blue.screens"]),
                           ir_response(m["R 120.blue.legacy.foam.entrance door open"])),
    }
    set_b = {
        ch: aligned_delta(text_response(f"{ch} 120.Rscreen.txt"),
                          text_response(f"{ch} 120.trad.txt")) for ch in "LR"
    }

    bands = ["20–80", "80–250", "250–1k", "1–4k", "4–16k", "300–8k"]
    old_a = [2.97, 3.59, 3.38, 1.38, .75, 2.25]
    new_a = [3.87, 2.80, 2.78, 1.31, .67, 1.90]
    old_b = [3.55, 3.45, 3.43, 1.70, 1.81, 2.43]
    new_b = [3.79, 2.46, 2.97, 1.52, 1.92, 2.15]

    fig, axes = plt.subplots(2, 2, figsize=(11.2, 8.0), constrained_layout=True)
    for ax, ch in zip(axes[0], "LR"):
        ax.semilogx(FG, set_a[ch], color="#c1272d", lw=2, label="Aug-17 MDAT, same mic")
        ax.semilogx(FG, set_b[ch], color="#1f4e79", lw=1.7, label="Aug-10 text set, mic shifted 3–4 cm")
        ax.axhline(0, color="black", lw=.8)
        ax.axvspan(80, 1000, color="#dfedd6", alpha=.55)
        ax.set(xlim=(20, 16000), ylim=(-3.5, 3.5), xlabel="frequency (Hz)",
               ylabel="new − traditional (dB)")
        ax.grid(which="both", alpha=.2)
        ax.set_title(f"({chr(97 if ch == 'L' else 98)}) {ch} differential, 1/6 octave", loc="left", weight="bold")
        ax.legend(fontsize=8, loc="lower right")

    ax = axes[1, 0]
    x = np.arange(len(bands)); width = .18
    ax.bar(x - 1.5*width, old_a, width, color="#be8b8b", label="Aug-17 traditional")
    ax.bar(x - .5*width, new_a, width, color="#b62525", label="Aug-17 new")
    ax.bar(x + .5*width, old_b, width, color="#8aa4bb", label="Aug-10 traditional")
    ax.bar(x + 1.5*width, new_b, width, color="#1f5e91", label="Aug-10 new")
    ax.set_xticks(x, bands, rotation=25, ha="right")
    ax.set(ylabel="RMS of L − R response (dB)", ylim=(0, 4.4))
    ax.grid(axis="y", alpha=.2)
    ax.legend(fontsize=7.5, ncols=2)
    ax.set_title("(c) L/R symmetry — lower is better", loc="left", weight="bold")

    ax = axes[1, 1]
    labels = ["open\ntraditional", "open\nnew", "closed\ntraditional", "closed\nnew"]
    peak = [-16.30, -19.23, -15.75, -18.86]
    energy = [-13.67, -16.10, -13.55, -15.98]
    x = np.arange(4)
    ax.bar(x - .18, peak, .36, color="#c1272d", label="envelope peak")
    ax.bar(x + .18, energy, .36, color="#1f4e79", label="window energy")
    ax.set_xticks(x, labels)
    ax.set(ylabel="dB relative to direct sound", ylim=(-22, -10))
    ax.grid(axis="y", alpha=.2)
    ax.legend(fontsize=8)
    ax.set_title("(d) R-side 2.2–3.0 ms path, 500 Hz–8 kHz", loc="left", weight="bold")

    fig.suptitle("Measured result of moving S3/S4 ahead of the foam panels",
                 fontsize=15, weight="bold")
    out = ROOT / "panel-placement-measurements-120cm.png"
    fig.savefig(out, dpi=180, facecolor="white")
    plt.close(fig)


def print_table():
    print(f"P: y={P[1]:.6f} m, z={P[2]:.6f} m, delay={REFL['delay']:.6f} ms")
    for angle in (90, 120, 150, 180):
        cap = shift_capacity(angle)
        rec = recommended_shift(angle)
        low = cap * EDGE_MARGIN / HALF_LEAF
        high = cap * (1 - EDGE_MARGIN / HALF_LEAF)
        _, _, _, _, span = panel_geometry(angle, P[1] + rec)
        nearest_y = P[1] + rec - span
        print(f"{angle:3d} deg: limit={cap*100:5.2f} cm, safe={low*100:5.2f}..{high*100:5.2f} cm, "
              f"mid={rec*100:5.2f} cm, hinge={P[1]+rec:.4f} m, front-end={nearest_y:.4f} m")
    for freq in (250, 500, 1000, 2000, 4000):
        yl, yh = fresnel_interval(freq, "y")
        zl, zh = fresnel_interval(freq, "z")
        print(f"{freq:4d} Hz Fresnel: y={yl:.3f}..{yh:.3f} ({yh-yl:.3f} m), "
              f"z={zl:.3f}..{zh:.3f} ({zh-zl:.3f} m)")


if __name__ == "__main__":
    print_table()
    build_geometry_figure()
    build_angle_figure()
    build_measurement_figure()
    print("wrote panel-placement-left-reflection-120cm.png")
    print("wrote panel-placement-opening-angle-120cm.png")
    print("wrote panel-placement-measurements-120cm.png")
