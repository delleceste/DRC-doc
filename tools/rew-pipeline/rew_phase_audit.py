#!/usr/bin/env python3
"""
rew_phase_audit.py -- detect an accidentally-inverted REW measurement.

Checks a family of REW multi-position frequency-response exports (same
channel, different mic positions -- e.g. "L 120.green.1.txt" .. "L
120.green.4.txt") for a position whose phase sits systematically near
180 degrees from the consensus of its siblings across the correction
band.

Why this test and not a magnitude check: a genuine spatial-position
difference (mic moved 20-30 cm) produces only tens of degrees of phase
scatter across 20-200 Hz -- time-of-flight over a small distance is a
small fraction of a period down there. REW's per-measurement "Invert"
flag, left ticked by mistake (or ticked correctly but exported before/
after the wrong moment), produces an offset pinned near 180 degrees at
almost every frequency in the band. The two are easy to tell apart with
exactly this statistic; magnitude alone cannot see it; SPL(dB) is
unaffected by inversion.

Found by hand this way on DRC-120.green, 2026-09-11: the original FDW12
build's "L 120.green.4.txt" sat 82% of 20-200 Hz within 30 degrees of a
180-degree offset from its three siblings (median offset 92.5 degrees).
The R-channel position 4 in the same export, and every position in a
later FDW8/FDW10 re-export, checked out clean (median offset a few
degrees). A corrupted position corrupts every downstream vector average
it feeds (the position-wise L+R sum, the spatial RMS average, and
therefore the target and the filter) -- see REW-INVERSION.md step 3 and
section 6. This check exists to catch that before it propagates.

Usage:
    ./rew_phase_audit.py "L 120.green."*.txt
    ./rew_phase_audit.py --fmin 20 --fmax 200 "R 120.green."*.txt
    ./rew_phase_audit.py --tol 30 --frac 0.5 L1.txt L2.txt L3.txt L4.txt

Run it once per channel (L, R, ... whatever position family you have --
do not mix L and R files in one run, they are not siblings). Needs at
least 3 files to get a consensus that outvotes a single bad one; with
exactly 2 files it still runs, but a genuine inversion in either file is
indistinguishable from the other one being inverted, so treat a 2-file
flag as "one of these is inverted, check both by hand", not a verdict.

Exit status is 1 if any file is flagged SUSPECT INVERTED, 0 otherwise --
usable as a gate before trusting a measurement set enough to run
tools/drc_acceptance.py or hand it to REW's division step.
"""

import argparse
import re
import sys

import numpy as np


def read_rew_txt(path):
    """Parse a REW Freq/SPL/Phase export. Returns (freq, spl, phase, header_notes)."""
    freq, spl, phase = [], [], []
    notes = []
    with open(path, errors="replace") as fh:
        for line in fh:
            if line.startswith("*"):
                s = line[1:].strip()
                if re.match(r"(?i)^(note|dated|measurement)\s*:", s):
                    notes.append(s)
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                f, s, p = float(parts[0]), float(parts[1]), float(parts[2])
            except ValueError:
                continue
            freq.append(f)
            spl.append(s)
            phase.append(p)
    if not freq:
        raise ValueError("%s: no Freq/SPL/Phase data rows found" % path)
    return np.array(freq), np.array(spl), np.array(phase), notes


def phase_on_grid(freq, phase, grid):
    """Unwrap then resample phase (degrees) onto a common frequency grid."""
    unwrapped = np.rad2deg(np.unwrap(np.deg2rad(phase)))
    return np.interp(grid, freq, unwrapped)


def wrap180(x):
    """Wrap degrees to (-180, 180]."""
    return (x + 180) % 360 - 180


def check(paths, fmin, fmax, tol, frac_threshold, verbose=True):
    parsed = []
    for p in paths:
        freq, spl, phase, notes = read_rew_txt(p)
        parsed.append((p, freq, phase, notes))

    grid = np.linspace(fmin, fmax, 400)
    on_grid = {p: (phase_on_grid(freq, phase, grid) % 360) for p, freq, phase, _ in parsed}

    flagged = []
    for p, freq, phase, notes in parsed:
        others = [on_grid[q] for q, *_ in parsed if q != p]
        if not others:
            continue
        consensus = np.median(others, axis=0) if len(others) > 1 else others[0]
        diff = wrap180(on_grid[p] - consensus)
        near180 = np.mean(np.abs(np.abs(diff) - 180) < tol)
        med = float(np.median(diff))
        suspect = near180 >= frac_threshold

        if verbose:
            print("=" * 72)
            print(p)
            for n in notes:
                print("  %s" % n)
            print("  median phase offset from sibling consensus, %g-%g Hz: %+.1f deg"
                  % (fmin, fmax, med))
            print("  fraction of band within %g deg of a 180 deg offset: %.0f%%"
                  % (tol, near180 * 100))
            print("  %s" % ("SUSPECT INVERTED" if suspect else "ok"))

        if suspect:
            flagged.append((p, med, near180))

    if verbose:
        print("=" * 72)
        if len(parsed) < 3:
            print("WARNING: only %d file(s) in this group -- consensus is weak. "
                  "A flag here means one of the files is probably inverted, not "
                  "necessarily this one; check both by hand." % len(parsed))
        if flagged:
            print("FLAGGED (likely REW 'Invert' set on the wrong measurement):")
            for p, med, near180 in flagged:
                print("  %-40s median %+.1f deg, %.0f%% of band near 180"
                      % (p, med, near180 * 100))
        else:
            print("No inversions detected among %d file(s)." % len(parsed))

    return flagged


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("txt", nargs="+",
                     help="REW Freq/SPL/Phase exports for ONE channel's sibling "
                          "positions (do not mix L and R)")
    ap.add_argument("--fmin", type=float, default=20.0, help="band low edge, Hz")
    ap.add_argument("--fmax", type=float, default=200.0, help="band high edge, Hz")
    ap.add_argument("--tol", type=float, default=30.0,
                     help="degrees of slack around a 180 deg offset to still "
                          "count as 'near 180' (default 30)")
    ap.add_argument("--frac", type=float, default=0.5,
                     help="fraction of the band that must sit near 180 deg to "
                          "flag the file (default 0.5)")
    a = ap.parse_args()

    try:
        flagged = check(a.txt, a.fmin, a.fmax, a.tol, a.frac)
    except Exception as e:  # noqa: BLE001
        print("ERROR: %s" % e, file=sys.stderr)
        return 2
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
