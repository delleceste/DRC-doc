#!/usr/bin/env python3
"""
drc_export_preflight.py -- sanity-check a REW .txts export directory before
handing it to open-media-drc's new_filter_design.py or the web installer.

Run this on the directory REW exported the session into, right after step 12
of REW-INVERSION.md, before committing anything:

    ./drc_export_preflight.py ../DRC-120.green/120.green.multipt.txts

It checks the same things new_filter_design.py itself checks before it will
deploy -- every text export unsmoothed and within 24 kHz, the file-naming
resolution that decides which file plays which role (including refusing a
directory that has both `LR.txt` and `L+R.txt`, since they say two
conflicting things about the same curve), and the listening-position
geometry comments (`* Note: ...`) the web UI's room diagram reads out of
`L`/`R`/the aggregate. All four checks -- role tables, candidate-name
matching, error/warning wording, and the geometry regexes -- are read
directly from open-media-drc's own source
(`scripts/new_filter_design.py`'s `discover()`, `measurement_distances()`,
`measurement_marker_color()`; `scripts/deploy_filter.py`'s
`parse_rew_txt()`/`export_defects()`) rather than reconstructed from memory,
so this script's messages match what the real tool would say.

What this script does NOT do, so you know when you still need the real tool:
it does not decode the impulse WAVs, does not check FLX-trimmed.txt against
FLX-trimmed-48k.wav in complex frequency space (needs SoX + NumPy), does not
touch Git, and does not write anything. It is a fast, dependency-free first
pass -- `new_filter_design.py --dry-run` in the open-media-drc checkout is
still the authoritative check before you deploy.

Exit status is 0 if the directory is ready, 1 otherwise. Geometry comments
missing (as opposed to conflicting) do not fail the run, matching the real
tool: it warns and still deploys.
"""

import argparse
import os
import re
import sys
from pathlib import Path

# ---- role tables, kept in step with open-media-drc/scripts/new_filter_design.py ----
# Single-file roles: (role, one or more acceptable base names, human title).
TXT_ROLES = (
    ("original_left",   ("L",),            "measured L"),
    ("original_right",  ("R",),            "measured R"),
    ("filter_left",     ("FLX-trimmed",),  "filter FLX response"),
    ("filter_right",    ("FRX-trimmed",),  "filter FRX response"),
    ("corrected_left",  ("L.filtered",),   "corrected L"),
    ("corrected_right", ("R.filtered",),   "corrected R"),
)

# The aggregate pair: the *original* aggregate's name decides the design's
# style, and each style accepts only its own corrected companion. A vector
# average has no re-measured form -- you cannot play one speaker and hear
# both -- so L+R.remeasured belongs to the sum style alone.
AGGREGATE_NAMES = {
    "LR":  {"original": ("LR",), "corrected": ("LR.filtered",)},
    "L+R": {"original": ("L+R",),
            "corrected": ("L+R.filtered", "L+R.remeasured", "L+R.measured")},
}
REMEASURED_NAMES = ("l+r.remeasured", "l+r.measured")

# WAV roles: filename encodes the sample rate, <rate>k.wav.
WAV_ROLES = {
    "filter_left_wav":  (re.compile(r"^FLX-trimmed-(\d+)k\.wav$", re.IGNORECASE),
                         "FLX-trimmed-<rate>k.wav, for example FLX-trimmed-48k.wav"),
    "filter_right_wav": (re.compile(r"^FRX-trimmed-(\d+)k\.wav$", re.IGNORECASE),
                         "FRX-trimmed-<rate>k.wav, for example FRX-trimmed-48k.wav"),
}

# The eight text exports that must be unsmoothed and within Nyquist.
TRACE_ROLES = (
    "original_left", "original_right", "original_sum",
    "filter_left", "filter_right",
    "corrected_left", "corrected_right", "corrected_sum",
)

# The three exports the web UI's room diagram reads listening-position
# comments out of. Same scope as new_filter_design.py's measurement_distances()
# and measurement_marker_color() -- not the filter or corrected traces.
GEOMETRY_ROLES = ("original_left", "original_right", "original_sum")

MAX_MEASUREMENT_RATE_HZ = 48000
MAX_EXPORT_FREQUENCY_HZ = MAX_MEASUREMENT_RATE_HZ / 2.0
EXPECTED_WAV_RATE_KHZ = 48  # this project's own convention (REW-INVERSION.md step 10)

# ---- geometry comment regexes, verbatim from new_filter_design.py ----
_DISTANCE_VALUE = r"(\d+(?:[.,]\d+)?)\s*m"
_FRONT_WALL_DISTANCE = re.compile(
    _DISTANCE_VALUE + r"\s+from\s+(?:the\s+)?front\s+wall\b", re.IGNORECASE)
_SPEAKER_DISTANCE = re.compile(
    _DISTANCE_VALUE +
    r"\s+(?:from\s+(?:(?:R\s+and\s+L\s+)?(?:the\s+)?speakers?)|"
    r"mic\s+to\s+(?:the\s+)?speakers?)\b",
    re.IGNORECASE)
_SPEAKER_WALL_DISTANCE = re.compile(
    _DISTANCE_VALUE + r"\s+speakers?\s+to\s+(?:the\s+)?(?:front\s+)?wall\b",
    re.IGNORECASE)
_MARKER_COLOR = re.compile(r"\bmarker\s*:\s*([a-z]+)\b", re.IGNORECASE)

# key, pattern, title, example comment. Order is display order.
GEOMETRY_FIELDS = (
    ("front_wall_m",   _FRONT_WALL_DISTANCE,   "front wall to MLP",
     "* Note: 4.18m from front wall"),
    ("speakers_m",     _SPEAKER_DISTANCE,      "MLP to speakers",
     "* Note: 3.32m from speakers"),
    ("speaker_wall_m", _SPEAKER_WALL_DISTANCE, "speakers to front wall",
     "* Note: 0.80m speakers to front wall"),
    ("marker_color",   _MARKER_COLOR,          "floor-marker colour",
     "* Note: marker: green"),
)
# The only combination new_filter_design.py itself warns about: neither
# distance found anywhere in L/R/aggregate. speaker_wall_m and marker_color
# are extracted and stored when present but are not individually required by
# the deploy tool -- this script warns about them anyway, labelled as such,
# because the room diagram is friendlier with them.
REQUIRED_BY_DEPLOY_TOOL = ("front_wall_m", "speakers_m")


class PreflightError(Exception):
    """A defect that stops discovery outright (missing/ambiguous/conflicting files)."""


class Colour:
    """Small TTY-aware ANSI helper matching
    open-media-drc/scripts/console_ui.py's Console class -- same codes, same
    OK/WARN/FAIL vocabulary -- so this script's output reads like the tools
    it feeds into. Respects NO_COLOR and TERM=dumb."""

    RESET, BOLD = "\033[0m", "\033[1m"
    RED, GREEN, YELLOW, CYAN = "\033[31m", "\033[32m", "\033[33m", "\033[36m"

    def __init__(self, stream=None):
        stream = stream or sys.stdout
        self.enabled = (
            hasattr(stream, "isatty") and stream.isatty()
            and "NO_COLOR" not in os.environ
            and os.environ.get("TERM") != "dumb"
        )

    def _wrap(self, text, *styles):
        if not self.enabled or not styles:
            return str(text)
        return "".join(styles) + str(text) + self.RESET

    def ok(self, message):
        return f"  {self._wrap('PASS', self.BOLD, self.GREEN)}  {message}"

    def warn(self, message):
        return f"  {self._wrap('WARN', self.BOLD, self.YELLOW)}  {message}"

    def fail(self, message):
        return f"  {self._wrap('FAIL', self.BOLD, self.RED)}  {message}"

    def note(self, message):
        return f"  {self._wrap('->', self.CYAN)}    {message}"


def candidate_names(base):
    """Exactly what new_filter_design.py accepts: base or base.txt, case-insensitive."""
    return (base.lower(), f"{base.lower()}.txt")


def index_directory(directory):
    entries = {}
    for path in sorted(directory.iterdir()):
        if path.is_file() and not path.is_symlink():
            entries.setdefault(path.name.lower(), []).append(path)
    return entries


def resolve_one(entries, role, bases, title):
    found = []
    for base in bases:
        for name in candidate_names(base):
            found.extend(entries.get(name, []))
    if not found:
        wanted = " or ".join(f"{base}.txt" for base in bases)
        raise PreflightError(f"no file for the {title}: expected {wanted}")
    if len(found) > 1:
        names = ", ".join(p.name for p in sorted(found))
        raise PreflightError(
            f"more than one file could be the {title} ({names}) -- "
            "these say different things about the same curve; keep exactly one")
    return found[0]


def resolve_wav(entries, role):
    pattern, example = WAV_ROLES[role]
    found = [p for paths in entries.values() for p in paths if pattern.match(p.name)]
    if not found:
        raise PreflightError(f"no file for the {role.replace('_', ' ')}: expected {example}")
    if len(found) > 1:
        names = ", ".join(p.name for p in sorted(found))
        raise PreflightError(
            f"more than one file could be the {role.replace('_', ' ')} ({names}) -- "
            "keep exactly one sample rate in this directory")
    path = found[0]
    rate_khz = int(pattern.match(path.name).group(1))
    return path, rate_khz


def discover(directory):
    """Map every required role onto exactly one file. Raises PreflightError on
    the first structural problem, with the same shape of message
    new_filter_design.py gives, since this exists to be read before that
    tool ever runs."""
    entries = index_directory(directory)

    styles = [style for style, names in AGGREGATE_NAMES.items()
              if any(name in entries
                     for base in names["original"] for name in candidate_names(base))]
    if not styles:
        raise PreflightError(
            "no measured aggregate: nothing says what the pair did before "
            "correction -- expected LR.txt (REW vector average) or L+R.txt (sum)")
    if len(styles) > 1:
        raise PreflightError(
            "both LR.txt and L+R.txt are present -- a design shows either the "
            "vector average or the sum, not both. Keep the one this correction "
            "was designed around and remove the other (see REW-INVERSION.md "
            "step 12 and DEPLOYMENT.md section 4.1: this procedure's own "
            "convention is vector_average, i.e. LR)")
    style = styles[0]

    paths = {role: resolve_one(entries, role, bases, title)
             for role, bases, title in TXT_ROLES}
    paths["original_sum"] = resolve_one(
        entries, "original_sum", AGGREGATE_NAMES[style]["original"], "measured aggregate")

    corrected_bases = AGGREGATE_NAMES[style]["corrected"]
    other_style = "L+R" if style == "LR" else "LR"
    for base in AGGREGATE_NAMES[other_style]["corrected"]:
        for name in candidate_names(base):
            if name in entries:
                raise PreflightError(
                    f"{entries[name][0].name} does not belong with {style}.txt "
                    f"-- {style}.txt is "
                    + ("REW's vector average" if style == "LR" else "the L+R sum")
                    + f", {base}.txt is "
                    + ("REW's vector average" if other_style == "LR" else "a sum")
                    + " -- one is not the corrected form of the other. With "
                    f"{style}.txt the corrected aggregate must be "
                    f"{' or '.join(corrected_bases[:2])}.txt")
    paths["corrected_sum"] = resolve_one(
        entries, "corrected_sum", corrected_bases, "corrected aggregate")

    rates = {}
    for role in WAV_ROLES:
        paths[role], rates[role] = resolve_wav(entries, role)
    if rates["filter_left_wav"] != rates["filter_right_wav"]:
        raise PreflightError(
            "the two impulse WAVs name different sample rates: "
            f"{rates['filter_left_wav']}k vs {rates['filter_right_wav']}k")

    corrected_name = paths["corrected_sum"].name.lower()
    remeasured = any(corrected_name.startswith(base) for base in REMEASURED_NAMES)
    notes = []
    if corrected_name.startswith("l+r.measured"):
        notes.append(
            f"{paths['corrected_sum'].name} reads as the room measured again after "
            "correction; prefer L+R.remeasured.txt, since '.measured' alone reads "
            "like an uncorrected sweep")
    for role, rate_khz in rates.items():
        if rate_khz != EXPECTED_WAV_RATE_KHZ:
            notes.append(
                f"{paths[role].name} names {rate_khz} kHz, not this project's usual "
                f"{EXPECTED_WAV_RATE_KHZ} kHz (REW-INVERSION.md step 10) -- confirm "
                "that's deliberate")

    aggregate = {"style": style, "corrected": "remeasured" if remeasured else "filtered"}
    return paths, aggregate, notes


def parse_rew_txt_header(path):
    """Header key/value pairs and the last (highest) frequency in the data,
    the two facts export_defects() needs. Mirrors
    open-media-drc/scripts/deploy_filter.py's parse_rew_txt()."""
    headers = {}
    last_freq = None
    with path.open(encoding="utf-8", errors="strict") as stream:
        for line in stream:
            text = line.strip()
            if not text:
                continue
            if text.startswith("*"):
                item = text[1:].strip()
                if ":" in item:
                    key, value = item.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
                continue
            parts = text.split()
            if len(parts) < 3:
                continue
            try:
                last_freq = float(parts[0])
            except ValueError:
                continue
    return headers, last_freq


def export_defects(role, title, path):
    """(reason) list for one text export -- unsmoothed and within Nyquist,
    exactly what new_filter_design.py refuses to deploy without."""
    defects = []
    try:
        headers, top = parse_rew_txt_header(path)
    except OSError as error:
        return [f"cannot read {path}: {error}"]
    smoothing = headers.get("smoothing", "").strip()
    if not smoothing:
        defects.append(
            f"{title} ({path.name}) states no smoothing at all, so it cannot be "
            "shown to be unsmoothed -- re-export it from REW with Smoothing: None")
    elif smoothing.lower() != "none":
        defects.append(
            f"{title} ({path.name}) carries REW smoothing '{smoothing}' -- "
            "re-export it with Smoothing: None")
    if top is not None and top > MAX_EXPORT_FREQUENCY_HZ:
        defects.append(
            f"{title} ({path.name}) reaches {top:,.1f} Hz, so it was measured at "
            f"{2.0 * top:,.0f} Hz or more; {MAX_MEASUREMENT_RATE_HZ:,} Hz is the "
            "highest this pipeline deploys")
    return defects


def read_comments(path):
    """Every '* ...' line in a REW export, joined into one search string.
    Matches new_filter_design.py's own comment scan exactly (utf-8-sig, so a
    BOM on the first '*' line doesn't hide it)."""
    with path.open(encoding="utf-8-sig", errors="replace") as stream:
        return " ".join(
            line.lstrip()[1:].strip() for line in stream
            if line.lstrip().startswith("*"))


def geometry_fields(paths):
    """Extract front_wall_m/speakers_m/speaker_wall_m/marker_color from the
    L/R/aggregate REW comments, exactly as new_filter_design.py's
    measurement_distances() and measurement_marker_color() do.

    Returns (values, conflicts): values maps key -> (value, [source
    filenames]); conflicts lists (key, value_a, file_a, value_b, file_b) for
    every field that disagrees between files -- the one thing the real tool
    hard-fails on rather than warns about."""
    values = {}
    conflicts = []
    for role in GEOMETRY_ROLES:
        comments = read_comments(paths[role])
        for key, pattern, _, _ in GEOMETRY_FIELDS:
            match = pattern.search(comments)
            if not match:
                continue
            raw = match.group(1)
            value = raw.lower() if key == "marker_color" else raw.replace(",", ".")
            if key in values:
                previous, sources = values[key]
                if previous != value:
                    conflicts.append((key, previous, sources[0], value, paths[role].name))
                else:
                    sources.append(paths[role].name)
            else:
                values[key] = (value, [paths[role].name])
    return values, conflicts


def geometry_report(colour, paths):
    """Coloured PASS/WARN/FAIL lines for the geometry comments, plus whether
    they cause an overall failure (only a conflict does)."""
    values, conflicts = geometry_fields(paths)
    lines = []
    for key, _, title, example in GEOMETRY_FIELDS:
        if key in values:
            value, sources = values[key]
            unit = "" if key == "marker_color" else " m"
            lines.append(colour.ok(
                f"{title:<24}: {value}{unit}  (from {', '.join(sources)})"))
        else:
            required = " (checked by the deploy tool)" if key in REQUIRED_BY_DEPLOY_TOOL \
                else " (not required by the deploy tool, but the room diagram wants it)"
            lines.append(colour.warn(
                f"{title:<24}: not found{required} -- add a comment such as "
                f"`{example}`"))

    ok = True
    for key, prev_value, prev_file, value, file_ in conflicts:
        title = next(t for k, _, t, _ in GEOMETRY_FIELDS if k == key)
        lines.append(colour.fail(
            f"{title}: conflicting values in L/R/aggregate comments -- "
            f"{prev_value} (from {prev_file}) vs {value} (from {file_})"))
        ok = False

    if not any(key in values for key in REQUIRED_BY_DEPLOY_TOOL):
        # Verbatim from new_filter_design.py's own warning.
        lines.append(colour.warn(
            "no listening-position distances found in L/R/aggregate comments; "
            "add comments such as: * Note: 4.18m from front wall; "
            "* Note: 3.32m from speakers; * Note: 0.80m speakers to front wall; "
            "* Note: marker: green"))

    return lines, ok


def check(directory, verbose=True):
    directory = Path(directory)
    colour = Colour()
    if not directory.is_dir():
        if verbose:
            print(colour.fail(f"not a directory: {directory}"))
        return False

    if verbose:
        print("=" * 72)
        print(directory)

    try:
        paths, aggregate, notes = discover(directory)
    except PreflightError as error:
        if verbose:
            print(colour.fail(str(error)))
            print(f"RESULT: {colour._wrap('FAIL', colour.BOLD, colour.RED)}")
        return False

    if verbose:
        print(f"  aggregate: {aggregate['style']} ({aggregate['corrected']} after "
              "correction)")
        for role, bases, title in TXT_ROLES:
            print(colour.ok(f"{title:<24}: {paths[role].name}"))
        print(colour.ok(f"{'measured aggregate':<24}: {paths['original_sum'].name}"))
        print(colour.ok(f"{'corrected aggregate':<24}: {paths['corrected_sum'].name}"))
        for role in WAV_ROLES:
            print(colour.ok(f"{role.replace('_', ' '):<24}: {paths[role].name}"))

    all_defects = []
    role_titles = {role: title for role, _, title in TXT_ROLES}
    role_titles["original_sum"] = "measured aggregate"
    role_titles["corrected_sum"] = "corrected aggregate"
    for role in TRACE_ROLES:
        all_defects.extend(export_defects(role, role_titles[role], paths[role]))

    geometry_lines, geometry_ok = geometry_report(colour, paths)

    ok = not all_defects and geometry_ok
    if verbose:
        if all_defects:
            print("  unsmoothed / bandwidth:")
            for defect in all_defects:
                print(colour.fail(defect))
        else:
            print(colour.ok(f"all eight text exports unsmoothed and within "
                             f"{MAX_EXPORT_FREQUENCY_HZ:,.0f} Hz"))
        for note in notes:
            print(colour.note(note))
        print("  listening-position comments (L/R/aggregate):")
        for line in geometry_lines:
            print(line)
        result_style = (colour.BOLD, colour.GREEN) if ok else (colour.BOLD, colour.RED)
        print(f"  RESULT: {colour._wrap('PASS' if ok else 'FAIL', *result_style)}")
        if ok:
            print("  Naming and export properties look ready. Still run "
                  "new_filter_design.py --dry-run in open-media-drc for the "
                  "TXT<->WAV residual check before deploying.")
    return ok


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", help="the REW .txts export directory to check")
    args = parser.parse_args(argv)
    ok = check(args.directory)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
