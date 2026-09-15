#!/usr/bin/env python3
"""Drive REW's own REST API through the full inversion chain in
../../../REW-INVERSION.md (steps 2-10), then check the result with
../drc_acceptance.py. Full writeup: REW-INVERSION.md, "Part V --
Automating the procedure".

This does NOT reimplement REW's FDW windowing or minimum-phase transform --
it asks the running REW instance to do each step (window, average, divide,
minimum-phase, trim) the same way a person would in the GUI, and reads back
the resulting impulse responses. That is the whole point: REW's internal
numerics are not reverse-engineered, they are used directly.

Requires REW running with its API enabled (API preferences, "Start the API
when REW starts", or launch with -api). Default port 4735.

Input naming convention (override any of it -- on the command line, or in a
config file, see below -- if your session uses different titles): a centre
measurement pair `L0`/`R0`, and optionally 1-4 more position pairs
`L1`/`R1` .. `L4`/`R4`, each `n` cm away from centre. If a real simultaneous
sweep `L0+R0` is present it is used as the centre mono sum (normalised
-6.0206 dB per REW-INVERSION.md 3c); otherwise the centre sum is `L0`
vector-averaged with `R0`, same as every other position.

Every DSP parameter (FDW aside) defaults to the exact value recorded in the
reference `120.green.multipt.FDW8` session's own measurement notes -- see
`../../DRC-120.green/IMPLEMENTATION-STATUS.md` -- and every one of them is a flag, so a rebuild at
a different FDW, or a different LF-tail slope, is one command:

    ./rew_pipeline.py --fdw-cycles 12 --tag fdw12 --output output/fdw12 \\
        --center-l L.0 --center-r R.0 \\
        --pos-l-pattern 'L 120.green.{n}' --pos-r-pattern 'R 120.green.{n}'

Config file: copy rew_pipeline.example.toml to rew_pipeline.toml (picked up
automatically) or pass --config some-name.toml, to keep the knobs above (and
the LF-tail/target/division settings) in one place you can look at and edit
instead of a long command line -- a command-line flag still overrides
whatever the file says.

Each run writes one importable design under --output, in the three-level shape
open-media-drc reads an identity out of -- see "The design directory" in its
doc/FILTER_PROVENANCE_AND_RESPONSE.md: a project directory named for the room,
holding one `<name>.txts` export folder beside the `<name>.mdat` session it
came from, with `<name>` = `<geometry>.<tag>`. Every name there is
load-bearing; together they are what spares you typing the geometry and the
design ID into the importer by hand:

    output/fdw12/                        --output: this run, and only this run
      DRC-120.green/                     <- the directory to pick in the browser
        120.green.fdw12.mdat             the session (written by --save-mdat)
        120.green.fdw12.txts/            exactly the ten files it resolves by name
          FLX-trimmed-48k.wav  FRX-trimmed-48k.wav  the two filters (BruteFIR
                                                    input)
          FLX-trimmed.txt  FRX-trimmed.txt  their frequency response (phase
                                            referenced to the WAV's own peak
                                            sample, required for that tool's
                                            TXT-vs-WAV check)
          L.txt  R.txt  LR.txt              measured L/R/vector-average,
                                            before correction
          L.filtered.txt  R.filtered.txt    raw (no-FDW) centre capture x
          LR.filtered.txt                   its filter, and their average
      manifest.json                      parameters + every measurement UUID
      acceptance.txt                     drc_acceptance.py's own output

Read it the way the importer does, outside in:

  DRC-120.green/           the project directory: `DRC-` off, and what is left
                           is the geometry, the room the design installs under.
                           Without it the importer has only the export name to
                           go on and stops at "cannot infer a known geometry".
  120.green.fdw12.txts/    the geometry again, so the rest -- `fdw12` -- is the
                           design ID. A stem that does not start with the
                           geometry leaves no design ID to read, and the
                           importer stops at "cannot infer a valid design ID".
  120.green.fdw12.mdat     same stem, in the same directory: this is the pair
                           the browser matches, and it attaches the session by
                           itself once it finds it.

Nothing but those ten files goes inside the export folder: the importer uploads
it whole and flattens it, so a stray file there is a stray input. manifest.json
and acceptance.txt stay outside the project directory, where neither
new_filter_design.py nor the UI looks. And give every run its own --output:
two `.txts`/`.mdat` pairs under one project directory is exactly the "No
unique .txts/.mdat pair found" the browser refuses to guess at.
"""
import argparse
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

from rew_client import RewClient, RewError

# Mirrors ../open-media-drc/scripts/new_filter_design.py's own comment
# regexps (front-wall/speaker distances, sofa marker colour), which it
# extracts from the L/R/aggregate TXT exports' "* Note: ..." lines to
# record listening-position provenance. Kept in sync by hand -- if that
# script's patterns change, update these too.
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


def check_geometry_comments(client, center_l, center_r):
    """Pre-flight check, before any processing: does at least one of the
    centre L/R measurements' notes carry the listening-position comments
    open-media-drc's new_filter_design.py looks for? It only warns (not a
    hard failure there either) when these are absent, but surfacing it now
    is cheaper than discovering it after a full run.
    """
    notes = ' '.join(client.get(f'/measurements/{uuid}')['notes'] or ''
                      for uuid in (center_l, center_r))
    found = {
        'front wall distance': _FRONT_WALL_DISTANCE.search(notes),
        'speaker distance': _SPEAKER_DISTANCE.search(notes),
        'speaker-to-wall distance': _SPEAKER_WALL_DISTANCE.search(notes),
        'marker colour': _MARKER_COLOR.search(notes),
    }
    for label, match in found.items():
        print(f'  geometry comment check: {label}: '
              f'{match.group(0) if match else "not found"}')
    if not (found['front wall distance'] or found['speaker distance']):
        print('  WARNING: no listening-position distance in the centre L/R notes; '
              'open-media-drc will warn at deploy time too. Add comments such as '
              '"4.18m from front wall" or "3.32m from speakers" to the REW '
              'measurement notes if you want that provenance recorded.')


def build(client, title, fn):
    """Run fn() (a 0-arg callable issuing one command/process) and give the
    resulting measurement `title`, first deleting any stale measurement of
    that name -- makes every step idempotent across reruns of the same tag.
    """
    for summary in client.measurements().values():
        if summary['title'] == title:
            client.delete_measurement(summary['uuid'])
    new_uuid = fn()
    if new_uuid is None:
        raise RewError(f'{title}: command produced no new measurement')
    client.rename(new_uuid, title)
    return new_uuid


def tagged(name, tag):
    return f'{name}.{tag}'


def clean_tag(client, tag, num_positions):
    """Remove all intermediates owned by a prior run of this tag.

    Cleaning lazily in ``build`` is insufficient after an interrupted run:
    later-stage leftovers remain loaded until the pipeline reaches them and
    can make REW hit its configurable measurement-count limit first.
    """
    roles = {
        *(f'SUM.{i}' for i in range(num_positions + 1)),
        'L-SP', 'R-SP', 'SUM-SP', 'LX', 'RX', 'LX-MP', 'RX-MP', 'SUM-SP-MP',
        'L-R RMS average', 'F.common', 'Fper_L', 'Fper_R', 'FL', 'FR',
        'PEQ.82', 'PEQ.530', 'PEQ.both', 'FL.exp', 'FR.exp',
        'LFilter', 'RFilter', 'FLX', 'FRX', 'FLX-trimmed', 'FRX-trimmed',
        'LFilter.baseline', 'RFilter.baseline', 'FLX.baseline', 'FRX.baseline',
        'FLX-trimmed.baseline', 'FRX-trimmed.baseline',
        'L.nofdw', 'R.nofdw', 'L.filtered', 'R.filtered', 'LR.filtered', 'LR',
        'L.filtered.baseline', 'R.filtered.baseline', 'LR.filtered.baseline',
        'L.filtered.eq82', 'R.filtered.eq82', 'LR.filtered.eq82',
        'L.filtered.eq530', 'R.filtered.eq530', 'LR.filtered.eq530',
    }
    owned_titles = {tagged(role, tag) for role in roles}
    stale = [summary for summary in client.measurements().values()
             if summary['title'] in owned_titles]
    if stale:
        print(f'Removing {len(stale)} stale measurements from prior {tag!r} run ...')
        for summary in stale:
            client.delete_measurement(summary['uuid'])


def retain_raw_inputs(client, args):
    """Discard every loaded trace except the named raw input measurements.

    This is deliberately opt-in: it removes targets, prior arithmetic,
    filters, response copies and imported X801 so the pipeline reconstructs
    the complete design from raw captures plus the configured X801 WAV.
    """
    keep = {args.center_l, args.center_r,
            *(args.pos_l_pattern.format(n=n) for n in range(1, args.num_positions + 1)),
            *(args.pos_r_pattern.format(n=n) for n in range(1, args.num_positions + 1))}
    if args.sum_c_title:
        keep.add(args.sum_c_title)
    stale = [summary for summary in client.measurements().values()
             if summary['title'] not in keep]
    if stale:
        print(f'Removing {len(stale)} non-raw measurements from input session ...')
        locked = []
        for summary in stale:
            try:
                client.delete_measurement(summary['uuid'])
            except RewError as exc:
                if 'is locked and cannot be deleted' not in str(exc):
                    raise
                locked.append(summary['title'])
        if locked:
            print('  REW API retained locked trace(s), which are excluded from the build: '
                  + ', '.join(repr(title) for title in locked))
    missing = keep - client.titles().keys()
    if missing:
        raise RewError(f'Raw-only cleanup is missing required inputs: {sorted(missing)}')


def response_band(client, uuid, low=20.0, high=225.0, ppo=96):
    """Return frequency and SPL arrays over one verification band."""
    f0, actual_ppo, mag = client.frequency_response(uuid, unit='SPL', ppo=ppo)
    freqs = f0 * 2.0 ** (np.arange(len(mag)) / actual_ppo)
    keep = (freqs >= low) & (freqs <= high) & np.isfinite(mag)
    if not np.any(keep):
        raise RewError(f'Measurement {uuid} has no finite response in {low:g}-{high:g} Hz')
    return freqs[keep], mag[keep]


def verify_product_is_unity(client, source, product, label, low=20.0, high=225.0,
                            median_tolerance_db=0.5):
    """Verify that multiplying by X801 did not change acoustic magnitude.

    X801 is a phase/crossover reference whose magnitude is unity. This test
    catches bad REW SPL calibration metadata even when X801 looks like 0 dB
    in the Filter response graph: REW arithmetic propagates ``splOffsetdB``.
    """
    freqs, source_mag = response_band(client, source, low, high)
    product_freqs, product_mag = response_band(client, product, low, high)
    product_on_source = np.interp(np.log(freqs), np.log(product_freqs), product_mag)
    delta = product_on_source - source_mag
    median = float(np.median(delta))
    max_abs = float(np.max(np.abs(delta)))
    print(f'  X801 check {label}: median {median:+.3f} dB, max |delta| {max_abs:.3f} dB')
    if abs(median) > median_tolerance_db:
        raise RewError(
            f'{label} differs from its pre-X801 source by a median {median:+.3f} dB '
            f'over {low:g}-{high:g} Hz (max |delta| {max_abs:.3f} dB). X801 must be '
            'unity magnitude; check its WAV and SPL offset before continuing.')


def verify_no_level_explosion(client, source, corrected, label, low=20.0, high=225.0):
    """Guard the final REW display traces against calibration propagation."""
    freqs, source_mag = response_band(client, source, low, high)
    corrected_freqs, corrected_mag = response_band(client, corrected, low, high)
    corrected_on_source = np.interp(np.log(freqs), np.log(corrected_freqs), corrected_mag)
    delta = corrected_on_source - source_mag
    corrected_median = float(np.median(corrected_on_source))
    maximum_gain = float(np.max(delta))
    print(f'  corrected-level check {label}: median {corrected_median:.2f} dB SPL, '
          f'max gain versus raw {maximum_gain:+.2f} dB')
    # A small positive excursion is possible from REW's band-edge blending
    # and X801's sub-hundredth-dB ripple. Tens of dB cannot be DSP here: both
    # divisions were explicitly clamped to maxGain=0.
    if not 30.0 <= corrected_median <= 130.0 or maximum_gain > 6.0:
        raise RewError(
            f'{label} has an implausible level after correction (median '
            f'{corrected_median:.2f} dB SPL, maximum gain {maximum_gain:+.2f} dB). '
            'Stopping: check X801 and target SPL calibration metadata.')


def normalize_x801(client, uuid, desired_offset_db):
    """Put an imported X801 at REW's unit-filter SPL calibration offset.

    REW currently imports a floating-point filter IR with a 120 dB SPL
    offset. The reference/manual session has X801 at 3 dB, so the required
    operation for a fresh import is Add SPL offset = -117 dB. Although its
    Filter response graph can already look correct, leaving the 120 dB
    metadata in place makes subsequent Arithmetic products about 117 dB
    too high.
    """
    before = float(client.measurement(uuid)['splOffsetdB'])
    delta = float(desired_offset_db) - before
    if abs(delta) > 0.02:
        print(f'  X801 SPL offset {before:.6g} dB -> {desired_offset_db:.6g} dB '
              f'(REW Add SPL offset {delta:+.6g} dB)')
        client.add_spl_offset(uuid, delta)
    else:
        print(f'  X801 SPL offset already {before:.6g} dB')
    after = float(client.measurement(uuid)['splOffsetdB'])
    if abs(after - desired_offset_db) > 0.02:
        raise RewError(
            f'REW reported X801 splOffsetdB={after:.6g} after normalisation; '
            f'expected {desired_offset_db:.6g} dB')
    return {'before_db': before, 'adjustment_db': delta if abs(delta) > 0.02 else 0.0,
            'after_db': after}


def configure_x801_windows(client, uuid, window_type, left_ms, right_ms):
    """Make X801's inherited trim/window state match the reference session."""
    wanted = {
        'leftWindowType': window_type,
        'rightWindowType': window_type,
        'leftWindowWidthms': float(left_ms),
        'rightWindowWidthms': float(right_ms),
        'addFDW': False,
    }
    before = client.ir_windows(uuid)
    client.put(f'/measurements/{uuid}/ir-windows', wanted)
    after = client.ir_windows(uuid)
    mismatches = {}
    for key, value in wanted.items():
        actual = after.get(key)
        if isinstance(value, float):
            equal = actual is not None and abs(float(actual) - value) <= 1e-6
        else:
            equal = actual == value
        if not equal:
            mismatches[key] = (value, actual)
    if mismatches:
        raise RewError(f'REW did not retain requested X801 window settings: {mismatches}')
    print(f'  X801 windows: {window_type}, {left_ms:g} ms left / {right_ms:g} ms right, FDW off')
    return {'before': before, 'after': after}


def write_wav(client, uuid, path):
    """Fetch a (already trimmed) measurement's impulse response and write it
    as a 32-bit float mono WAV laid out exactly as REW's own exporter does.

    `windowed=False` is deliberate -- see RewClient.impulse_response. The
    container is written here rather than with scipy because scipy emits an
    18-byte `fmt ` chunk plus a `fact` chunk, where REW writes a bare
    16-byte `fmt ` and no `fact`; matching REW keeps the two files
    byte-comparable everywhere except the samples themselves.
    """
    fs, samples, _ = client.impulse_response(uuid, windowed=False, normalised=False, unit='percent')
    samples = samples.astype('<f4')
    fs = int(fs)
    payload = samples.tobytes()
    header = (b'RIFF' + struct.pack('<I', 36 + len(payload)) + b'WAVE'
              + b'fmt ' + struct.pack('<IHHIIHH', 16, 3, 1, fs, fs * 4, 4, 32)
              + b'data' + struct.pack('<I', len(payload)))
    Path(path).write_bytes(header + payload)
    return path, samples, fs


def write_filter_text(samples, fs, path):
    """open-media-drc's new_filter_design.py checks that each filter TXT is
    (an integer-delay, constant-gain copy of) the exported response of its
    own WAV -- so this derives the text directly from the exact array
    written to that WAV, not from a separate API call, guaranteeing they
    agree to floating-point precision.

    Its alignment search only tries delays within 16 samples of the WAV's
    own peak (`new_filter_design.py`'s `detect_filter_alignment`), so the
    phase must already be referenced to the impulse peak as t=0, not to
    the buffer start -- confirmed empirically (exactly 0 residual at
    delay = peak, vs. ~104 deg RMS one sample either side) against its own
    `deploy_filter.filter_spectrum`/`response_metrics`.
    """
    n = len(samples)
    peak = int(np.argmax(np.abs(samples)))
    freqs = np.fft.rfftfreq(n, 1 / fs)
    h = np.fft.rfft(samples) * np.exp(2j * np.pi * freqs * peak / fs)
    db = 20 * np.log10(np.maximum(np.abs(h), 1e-30))
    phase_deg = np.degrees(np.angle(h))
    _write_rew_text(path, freqs, db, phase_deg,
                     note=f'derived directly from its own WAV, phase referenced to its peak (sample {peak})')
    return path


def _write_rew_text(path, freqs, db, phase_deg, note, notes_text='', measurement=None, dated=None):
    """Write a frequency-response text export compatible with both
    ../DRC-doc/rewio.py's read_fr() and open-media-drc's new_filter_design.py.

    The latter refuses any export that is not genuinely unsmoothed, checked
    as a literal '* Smoothing: None' header line, and any grid reaching past
    24 kHz. `freqs` must therefore be linear-spaced (a plain rfft grid) and
    already capped at Nyquist -- both true by construction for every caller
    here, since none of them go through REW's own /frequency-response
    endpoint (which could not be made to return unsmoothed data when tested;
    see IMPLEMENTATION-STATUS.md).

    `notes_text`, when given, is written as one '* Note: ...' line, matching
    REW's own export convention -- new_filter_design.py's geometry-provenance
    regexes (front-wall/speaker distance, marker colour) search exactly this
    line on the original_left/original_right/original_sum exports.
    """
    n = len(freqs)
    step = float(freqs[1] - freqs[0]) if n > 1 else 0.0
    with open(path, 'w') as f:
        f.write(f'* Generated by rew_pipeline.py ({note})\n')
        if measurement is not None:
            f.write(f'* Measurement: {measurement}\n')
        if dated is not None:
            f.write(f'* Dated: {dated}\n')
        if notes_text:
            f.write(f'* Note: ; {" ".join(notes_text.split())}\n')
        f.write('* Smoothing: None\n')
        f.write(f'* Frequency Step: {step:.7g} Hz\n')
        f.write('* Start Frequency: 0 Hz\n*\n* Freq(Hz) SPL(dB) Phase(degrees)\n')
        for fr, m, p in zip(freqs, db, phase_deg):
            f.write(f'{fr:.6f} {m:.3f} {p:.4f}\n')


def write_freq_text(client, uuid, path, calibration_freq_hz=100.0):
    """Frequency-response text export of a measurement's full impulse
    response (not tied to any WAV), calibrated in absolute level against
    REW's own SPL value at one stable frequency so the numbers read in dB
    SPL rather than an arbitrary FFT scale -- purely for human/plot use, no
    downstream check depends on this being exact.
    """
    summary = client.get(f'/measurements/{uuid}')
    notes_text = summary['notes'] or ''
    fs, samples, start_time = client.impulse_response(
        uuid, windowed=False, normalised=False, unit='percent')
    n = len(samples)
    freqs = np.fft.rfftfreq(n, 1 / fs)
    # `samples[0]` sits at `start_time` on REW's own time axis, not at t=0 --
    # for a sweep measurement REW leaves roughly a second of pre-arrival
    # buffer, so start_time is about -1 s. A plain rfft of that buffer
    # therefore references the phase to the *start of the buffer*, adding a
    # ~1 s bulk delay: about one full 360 deg wrap per hertz, which turns
    # every plotted phase curve into noise and makes any smoothing of it
    # (circular mean over a fractional-octave band) average to ~0. REW's own
    # Phase graph references t=0, so shift the spectrum back onto that axis
    # -- the same correction write_filter_text() already applies with its
    # WAV's peak sample. Magnitude is unaffected.
    spectrum = np.fft.rfft(samples) * np.exp(-2j * np.pi * freqs * start_time)
    raw_db = 20 * np.log10(np.maximum(np.abs(spectrum), 1e-30))
    phase_deg = np.degrees(np.angle(spectrum))

    f0, ppo0, mag0 = client.frequency_response(uuid, unit='SPL', ppo=96)
    rew_freqs = f0 * 2.0 ** (np.arange(len(mag0)) / ppo0)
    cal_idx = int(np.argmin(np.abs(rew_freqs - calibration_freq_hz)))
    raw_idx = int(np.argmin(np.abs(freqs - rew_freqs[cal_idx])))
    offset_db = float(mag0[cal_idx] - raw_db[raw_idx])

    _write_rew_text(path, freqs, raw_db + offset_db, phase_deg,
                     note=f'source UUID {uuid}, calibrated to its own SPL at {calibration_freq_hz:g} Hz, '
                          f'phase referenced to REW t=0 (IR start {start_time:.6f} s)',
                     notes_text=notes_text, measurement=summary.get('title'), dated=summary.get('date'))
    return path


# open-media-drc names geometries and design IDs with this alphabet
# (omdrc-ctrl/src/configuration.py, _SAFE_NAME); a directory it cannot parse
# back into the two is an import that stops to ask.
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")


def default_geometry():
    """The room this project measures, as open-media-drc names it: the
    project directory itself, minus the conventional DRC- prefix
    (DRC-120.green -> 120.green). The web UI strips the prefix the same way
    when it infers a geometry from an imported path, so deriving it here
    keeps the exported names and the installed design in agreement."""
    return re.sub(r'^drc[-_.]', '', Path.cwd().name, flags=re.IGNORECASE)


def project_directory(args):
    """Where the .txts/.mdat pair lives: a directory named for the room, so the
    importer can take `DRC-` off it and have the geometry. --output is the run,
    which is a different thing (a tag, a date, an experiment) and usually named
    like one -- so the project directory is made inside it, unless --output is
    already named for this geometry and nesting would only repeat it."""
    if re.sub(r'^drc[-_.]', '', args.output.name, flags=re.IGNORECASE).casefold() \
            == args.geometry.casefold():
        return args.output
    return args.output / f'DRC-{args.geometry}'


def report_import_layout(project_dir, export_dir, geometry, design, mdat_path):
    """Say whether the project directory imports as it stands, and under which
    identity. The web UI takes a directory holding exactly one `<name>.txts`
    folder together with its matching `<name>.mdat` -- anything else is "No
    unique .txts/.mdat pair found" -- and reads the geometry and design ID back
    out of the two names. Checking both here puts the answer next to the run
    that produced it, while the fix is still one flag away."""
    exports = sorted(entry for entry in project_dir.iterdir()
                     if entry.is_dir() and entry.name.lower().endswith('.txts'))
    session_of = lambda entry: project_dir / f'{entry.name[:-len(".txts")]}.mdat'
    pairs = [entry for entry in exports if session_of(entry).is_file()]
    expected = session_of(export_dir)

    print(f'\nProject directory: {project_dir}')
    print(f'  {export_dir.name}/ ({len(list(export_dir.iterdir()))} exported files)')
    for entry in sorted(project_dir.iterdir()):
        if entry.is_file() and entry.name.lower().endswith('.mdat'):
            print(f'  {entry.name}')
    if mdat_path is not None and mdat_path != expected:
        print(f'  session saved outside the pair: {mdat_path}')

    problems = []
    if not expected.is_file():
        problems.append(
            f'{expected.name} is not here. Rerun with --save-mdat (no argument), or '
            f'save the session from REW under that exact name -- without it there is '
            f'no pair to import and no measurements to hash the design against')
    if len(pairs) > 1:
        problems.append(
            'more than one .txts/.mdat pair here ('
            + ', '.join(entry.name for entry in pairs)
            + '). Give each run its own --output directory')
    if problems:
        print('\nNot importable yet -- the web UI would report '
              '"No unique .txts/.mdat pair found":')
        for problem in problems:
            print(f'  - {problem}')
        return
    print(f'\nImports as geometry {geometry!r}, design {design!r}, both read off '
          f'the names above -- no override to fill in.')
    print(f'  web UI: Configuration -> filter design -> pick {project_dir.name}/ '
          f'(the .mdat is attached by itself)')
    print(f'  command line: python3 scripts/new_filter_design.py {export_dir}')


def run_pipeline(args):
    client = RewClient(args.api_url)
    try:
        client.ping()
    except RewError as e:
        print(f'ERROR: {e}', file=sys.stderr)
        print('Start REW with its API enabled and reachable, then retry.', file=sys.stderr)
        return 2
    client.set_blocking(True)

    if args.session:
        if args.replace_session:
            print('Closing all currently loaded measurements before loading input session ...')
            client.delete_all_measurements()
        titles = client.titles()
        if args.center_l not in titles:
            print(f'Loading session {args.session} ...')
            client.load(str(args.session.resolve()))
        else:
            print(f'Session measurements already present, not reloading {args.session}')

    if args.raw_only_session:
        retain_raw_inputs(client, args)

    tag = args.tag
    t = lambda name: tagged(name, tag)

    center_l = client.find(args.center_l)
    center_r = client.find(args.center_r)
    pos_l = [client.find(args.pos_l_pattern.format(n=n)) for n in range(1, args.num_positions + 1)]
    pos_r = [client.find(args.pos_r_pattern.format(n=n)) for n in range(1, args.num_positions + 1)]
    all_l = [center_l] + pos_l
    all_r = [center_r] + pos_r

    clean_tag(client, tag, args.num_positions)

    print('Pre-flight: geometry comments on the input measurements ...')
    check_geometry_comments(client, center_l, center_r)

    print(f'FDW {args.fdw_cycles:g} cycles on {len(all_l) + len(all_r)} raw captures ...')
    for idx in all_l + all_r:
        client.set_fdw(idx, args.fdw_cycles)

    print('Forming the mono sum at each position (Vector average) ...')
    sum_c_title = args.sum_c_title or f'{args.center_l}+{args.center_r}'
    try:
        real_sum_c = client.find(sum_c_title)
        print(f'  found real simultaneous sum {sum_c_title!r}, normalising -6.0206 dB ...')
        sum_c = build(client, t('SUM.0'), lambda: client.response_copy(real_sum_c))
        client.set_fdw(sum_c, args.fdw_cycles)
        client.add_spl_offset(sum_c, -6.0206)
    except RewError:
        sum_c = build(client, t('SUM.0'), lambda: client.vector_average([center_l, center_r]))
    sum_pos = [build(client, t(f'SUM.{i}'), lambda li=li, ri=ri: client.vector_average([li, ri]))
               for i, (li, ri) in enumerate(zip(pos_l, pos_r), start=1)]
    sum_idx = [sum_c] + sum_pos

    print('Spatial RMS average of each family (L, R, SUM) ...')
    l_sp = build(client, t('L-SP'), lambda: client.rms_average(all_l))
    r_sp = build(client, t('R-SP'), lambda: client.rms_average(all_r))
    sum_sp = build(client, t('SUM-SP'), lambda: client.rms_average(sum_idx))

    print(f'Loading crossover reference {args.x801_title!r} ...')
    try:
        x801 = client.find(args.x801_title)
    except RewError:
        x801 = client.import_impulse_response(args.x801_wav.resolve(), rename_to=args.x801_title)
    x801_offsets = normalize_x801(client, x801, args.x801_spl_offset)
    x801_windows = configure_x801_windows(
        client, x801, args.x801_window_type,
        args.x801_left_window_ms, args.x801_right_window_ms)

    print('Baking crossover correction into channel averages (X801) ...')
    lx = build(client, t('LX'), lambda: client.arithmetic('A * B', l_sp, x801))
    rx = build(client, t('RX'), lambda: client.arithmetic('A * B', r_sp, x801))
    verify_product_is_unity(client, l_sp, lx, 'LX versus L-SP')
    verify_product_is_unity(client, r_sp, rx, 'RX versus R-SP')

    lf1 = (args.lf1_corner, args.lf1_slope)
    hf1 = (args.hf1_corner, args.hf1_slope) if args.hf1_corner is not None else None
    print(f'Minimum phase #1: cal included, LF tail {args.lf1_corner:g} Hz @ {args.lf1_slope:g} dB/oct, '
          f'HF tail {"off" if hf1 is None else f"{args.hf1_corner:g} Hz @ {args.hf1_slope:g} dB/oct"} ...')
    lx_mp = build(client, t('LX-MP'), lambda: client.minimum_phase_version(
        lx, include_cal=True, lf_tail=lf1, hf_tail=hf1,
        frequency_warping=args.hf1_warping, replicate_data=args.replicate_data))
    rx_mp = build(client, t('RX-MP'), lambda: client.minimum_phase_version(
        rx, include_cal=True, lf_tail=lf1, hf_tail=hf1,
        frequency_warping=args.hf1_warping, replicate_data=args.replicate_data))
    sum_mp = build(client, t('SUM-SP-MP'), lambda: client.minimum_phase_version(
        sum_sp, include_cal=True, lf_tail=lf1, hf_tail=hf1,
        frequency_warping=args.hf1_warping, replicate_data=args.replicate_data))

    if args.verify:
        verify_minimum_phase(client, [(lx, lx_mp, 'LX-MP'), (rx, rx_mp, 'RX-MP'),
                                       (sum_sp, sum_mp, 'SUM-SP-MP')])

    target = resolve_target(client, args, build, t, lx, rx)

    print(f'Dividing: common {args.common_low:g}-{args.common_split:g} Hz, '
          f'per-channel {args.common_split:g}-{args.upper:g} Hz, max gain 0 dB ...')
    f_common = build(client, t('F.common'), lambda: client.arithmetic(
        'A / B', target, sum_mp, max_gain=0.0, lower_limit=args.common_low, upper_limit=args.common_split))
    fper_l = build(client, t('Fper_L'), lambda: client.arithmetic(
        'A / B', target, lx_mp, max_gain=0.0, lower_limit=args.common_split, upper_limit=args.upper))
    fper_r = build(client, t('Fper_R'), lambda: client.arithmetic(
        'A / B', target, rx_mp, max_gain=0.0, lower_limit=args.common_split, upper_limit=args.upper))

    fl = build(client, t('FL'), lambda: client.arithmetic('A * B', f_common, fper_l))
    fr = build(client, t('FR'), lambda: client.arithmetic('A * B', f_common, fper_r))

    peq82 = peq530 = peq_both = None
    fl_for_final, fr_for_final = fl, fr
    if args.refinement_peq:
        print(f'Building refinement PEQs: {args.peq82_frequency:g} Hz '
              f'{args.peq82_gain:+g} dB Q {args.peq82_q:g}; '
              f'{args.peq530_frequency:g} Hz {args.peq530_gain:+g} dB '
              f'Q {args.peq530_q:g} ...')
        pk82 = {'type': 'PK', 'frequency': args.peq82_frequency,
                'gaindB': args.peq82_gain, 'q': args.peq82_q}
        pk530 = {'type': 'PK', 'frequency': args.peq530_frequency,
                 'gaindB': args.peq530_gain, 'q': args.peq530_q}
        # Generate all three responses explicitly so REW can show the two
        # experiments separately as well as their combined candidate.
        peq82 = build(client, t('PEQ.82'), lambda: client.generate_filters_measurement(fl, [pk82]))
        peq530 = build(client, t('PEQ.530'), lambda: client.generate_filters_measurement(fr, [pk530]))
        peq_both = build(client, t('PEQ.both'),
                         lambda: client.generate_filters_measurement(fl, [pk82, pk530]))
        fl_for_final = build(client, t('FL.exp'), lambda: client.arithmetic('A * B', fl, peq_both))
        fr_for_final = build(client, t('FR.exp'), lambda: client.arithmetic('A * B', fr, peq_both))

    lf2 = (args.lf2_corner, args.lf2_slope)
    hf2 = (args.hf2_corner, args.hf2_slope) if args.hf2_corner is not None else None
    print(f'Minimum phase #2: cal excluded, LF tail {args.lf2_corner:g} Hz @ {args.lf2_slope:g} dB/oct, '
          f'HF tail {"off" if hf2 is None else f"{args.hf2_corner:g} Hz @ {args.hf2_slope:g} dB/oct"} ...')
    lfilter = build(client, t('LFilter'), lambda: client.minimum_phase_version(
        fl_for_final, include_cal=False, lf_tail=lf2, hf_tail=hf2,
        frequency_warping=args.hf2_warping, replicate_data=args.replicate_data))
    rfilter = build(client, t('RFilter'), lambda: client.minimum_phase_version(
        fr_for_final, include_cal=False, lf_tail=lf2, hf_tail=hf2,
        frequency_warping=args.hf2_warping, replicate_data=args.replicate_data))

    print('Baking crossover correction in, last (X801 x LFilter/RFilter) ...')
    flx = build(client, t('FLX'), lambda: client.arithmetic('A * B', x801, lfilter))
    frx = build(client, t('FRX'), lambda: client.arithmetic('A * B', x801, rfilter))

    print('Trimming to set latency ...')
    flx_trimmed = build(client, t('FLX-trimmed'), lambda: client.trim_to_windows(flx))
    frx_trimmed = build(client, t('FRX-trimmed'), lambda: client.trim_to_windows(frx))

    # The ten deployable files land in <name>.txts inside the project directory
    # and nothing else does; the session is saved beside it as <name>.mdat
    # further down. See the module docstring -- that is the one shape the
    # directory import accepts, and the one it can read an identity out of.
    project_dir = project_directory(args)
    export_dir = project_dir / f'{args.export_name}.txts'
    export_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for label, uuid in (('FLX-trimmed-48k', flx_trimmed), ('FRX-trimmed-48k', frx_trimmed)):
        path, samples, fs = write_wav(client, uuid, export_dir / f'{label}.wav')
        files[label] = path
        print(f'Wrote {path} ({len(samples)} samples @ {fs:g} Hz)')
        txt_label = label.replace('-48k', '')
        write_filter_text(samples, fs, export_dir / f'{txt_label}.txt')

    print('Freezing no-FDW copies of the centre capture for verification '
          '(everything above is already frozen, so this is now safe) ...')
    client.disable_fdw(center_l)
    client.disable_fdw(center_r)
    raw_l = build(client, t('L.nofdw'), lambda: client.response_copy(center_l))
    raw_r = build(client, t('R.nofdw'), lambda: client.response_copy(center_r))
    # "Response copy" does not carry the source's notes (only its own
    # "Copy of <title>" line) -- copy them over explicitly so the geometry
    # comments (front-wall/speaker distance, marker colour) survive into
    # L.txt/R.txt for open-media-drc's provenance regexes.
    for raw, center in ((raw_l, center_l), (raw_r, center_r)):
        source_notes = client.get(f'/measurements/{center}')['notes'] or ''
        copy_notes = client.get(f'/measurements/{raw}')['notes'] or ''
        client.set_notes(raw, f'{copy_notes}\n{source_notes}'.strip())

    print('Verification: raw (no-FDW) centre capture x finished filter ...')
    l_filtered = build(client, t('L.filtered'), lambda: client.arithmetic('A * B', raw_l, flx_trimmed))
    r_filtered = build(client, t('R.filtered'), lambda: client.arithmetic('A * B', raw_r, frx_trimmed))
    verify_no_level_explosion(client, raw_l, l_filtered, 'L.filtered')
    verify_no_level_explosion(client, raw_r, r_filtered, 'R.filtered')
    lr_filtered = build(client, t('LR.filtered'), lambda: client.vector_average([l_filtered, r_filtered]))
    raw_lr = build(client, t('LR'), lambda: client.vector_average([raw_l, raw_r]))

    baseline = {}
    variants = {}
    if args.refinement_peq:
        # REW defaults to at most 60 loaded measurements. These construction
        # traces have already been folded into the spatial divisors and MP
        # responses, so release their slots for the comparison families while
        # retaining raw captures, common/per-channel filters, target, finished
        # filters and every result the user needs to inspect.
        print('Removing disposable construction traces to make room for comparisons ...')
        for uuid in [*sum_idx, lx, rx]:
            client.delete_measurement(uuid)
        print('Building baseline and per-experiment predictions for side-by-side REW comparison ...')
        # The base finished response is reconstructed through the same MP/X801/
        # trim sequence as the experimental candidate, but without either PEQ.
        blf = build(client, t('LFilter.baseline'), lambda: client.minimum_phase_version(
            fl, include_cal=False, lf_tail=lf2, hf_tail=hf2,
            frequency_warping=args.hf2_warping, replicate_data=args.replicate_data))
        brf = build(client, t('RFilter.baseline'), lambda: client.minimum_phase_version(
            fr, include_cal=False, lf_tail=lf2, hf_tail=hf2,
            frequency_warping=args.hf2_warping, replicate_data=args.replicate_data))
        bflx = build(client, t('FLX.baseline'), lambda: client.arithmetic('A * B', x801, blf))
        bfrx = build(client, t('FRX.baseline'), lambda: client.arithmetic('A * B', x801, brf))
        bflxt = build(client, t('FLX-trimmed.baseline'), lambda: client.trim_to_windows(bflx))
        bfrxt = build(client, t('FRX-trimmed.baseline'), lambda: client.trim_to_windows(bfrx))
        bl = build(client, t('L.filtered.baseline'), lambda: client.arithmetic('A * B', raw_l, bflxt))
        br = build(client, t('R.filtered.baseline'), lambda: client.arithmetic('A * B', raw_r, bfrxt))
        blr = build(client, t('LR.filtered.baseline'), lambda: client.vector_average([bl, br]))
        baseline = {'L': bl, 'R': br, 'LR': blr}
        for label, peq in (('eq82', peq82), ('eq530', peq530)):
            vl = build(client, t(f'L.filtered.{label}'), lambda peq=peq: client.arithmetic('A * B', bl, peq))
            vr = build(client, t(f'R.filtered.{label}'), lambda peq=peq: client.arithmetic('A * B', br, peq))
            vlr = build(client, t(f'LR.filtered.{label}'), lambda vl=vl, vr=vr: client.vector_average([vl, vr]))
            variants[label] = {'L': vl, 'R': vr, 'LR': vlr}

    # open-media-drc's new_filter_design.py resolves these exact names (case-
    # insensitive, ".txt" optional): L/R/LR before correction, L.filtered/
    # R.filtered/LR.filtered after -- see FILTERS_AND_DRC.md and
    # scripts/new_filter_design.py's TXT_NAMES/AGGREGATE_NAMES.
    for label, uuid in (('L', raw_l), ('R', raw_r), ('LR', raw_lr),
                         ('L.filtered', l_filtered), ('R.filtered', r_filtered),
                         ('LR.filtered', lr_filtered)):
        path = write_freq_text(client, uuid, export_dir / f'{label}.txt')
        print(f'Wrote {path}')

    manifest = {
        'parameters': {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        'x801_spl_offset': x801_offsets,
        'x801_windows': x801_windows,
        'measurement_uuids': {
            'raw_l_no_fdw': raw_l, 'raw_r_no_fdw': raw_r, 'raw_lr_no_fdw': raw_lr,
            'centre_l': center_l, 'centre_r': center_r, 'pos_l': pos_l, 'pos_r': pos_r,
            'sum_positions': sum_idx,
            'L-SP': l_sp, 'R-SP': r_sp, 'SUM-SP': sum_sp, 'LX': lx, 'RX': rx,
            'LX-MP': lx_mp, 'RX-MP': rx_mp, 'SUM-SP-MP': sum_mp, 'target': target, 'x801': x801,
            'F.common': f_common, 'Fper_L': fper_l, 'Fper_R': fper_r, 'FL': fl, 'FR': fr,
            'LFilter': lfilter, 'RFilter': rfilter, 'FLX': flx, 'FRX': frx,
            'FLX-trimmed': flx_trimmed, 'FRX-trimmed': frx_trimmed,
            'L.Filtered': l_filtered, 'R.Filtered': r_filtered, 'LR.Filtered': lr_filtered,
            'PEQ.82': peq82, 'PEQ.530': peq530, 'PEQ.both': peq_both,
            'baseline': baseline, 'individual_variants': variants,
        },
    }
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    mdat_path = None
    if args.save_mdat:
        mdat_path = (args.save_mdat if args.save_mdat != Path('-')
                     else project_dir / f'{args.export_name}.mdat')
        client.save_all(mdat_path.resolve(), f'rew_pipeline.py {tag}: FDW {args.fdw_cycles:g} cycles')
        print(f'Saved session to {mdat_path} -- open it in REW and export '
              f'{t("FLX-trimmed")} / {t("FRX-trimmed")} from the GUI for bit-exact WAVs '
              f'(the API cannot export WAV; see RewClient.impulse_response)')

    print(f'Running acceptance tests ({args.acceptance}) ...')
    cmd = [sys.executable, str(args.acceptance.resolve()),
           str(files['FLX-trimmed-48k']), str(files['FRX-trimmed-48k'])]
    if args.plot:
        cmd += ['--plot', str(args.output / 'acceptance.png')]
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout)
    (args.output / 'acceptance.txt').write_text(result.stdout)
    if result.returncode == 0:
        print(f'PASS -- {args.output}')
    else:
        print(f'FAIL (exit {result.returncode}) -- {args.output}')
    report_import_layout(project_dir, export_dir, args.geometry, args.design, mdat_path)
    return result.returncode


def resolve_target(client, args, build, t, lx, rx):
    """Reuse an existing target (e.g. one already tuned by hand in REW, or
    built by an earlier run at a different --tag) if --target-title matches
    one; otherwise build a default one: RMS average of LX/RX, REW's own
    auto-calculated target level, optional house curve and LF cutoff. See
    REW-INVERSION.md step 5 -- the house curve choice is a judgment call,
    this only supplies a reasonable default.

    Saved under the plain, untagged --target-title (not `t(...)`) so that a
    later run with a *different* --tag finds and reuses the same target
    instead of building its own -- REW-INVERSION.md's guide holds the
    target fixed while FDW cycles are compared, and a tagged name would
    silently defeat that on every rerun.
    """
    try:
        existing = client.find(args.target_title)
        _, target_mag = response_band(client, existing)
        target_median = float(np.median(target_mag))
        if 30.0 <= target_median <= 130.0:
            print(f'Reusing target {args.target_title!r} (20-225 Hz median '
                  f'{target_median:.2f} dB SPL)')
            return existing
        print(f'Existing target {args.target_title!r} has implausible 20-225 Hz '
              f'median {target_median:.2f} dB SPL; deleting and rebuilding it')
        client.delete_measurement(existing)
    except RewError as error:
        if not str(error).startswith('No measurement named'):
            raise
    print(f'No existing target {args.target_title!r}, building one (LF cutoff '
          f'{args.target_lf_cutoff:g} Hz @ {args.target_lf_slope:g} dB/oct) ...')
    lr_rms = build(client, t('L-R RMS average'), lambda: client.rms_average([lx, rx]))
    if args.house_curve is not None:
        client.house_curve(str(args.house_curve.resolve()), log_interpolation=args.house_curve_log_interpolation)
    client.set_target_settings(lr_rms, shape='Full range',
                                lowFreqCutoffHz=int(args.target_lf_cutoff),
                                lowFreqSlopedBPerOctave=int(args.target_lf_slope))
    client.eq_command(lr_rms, 'Calculate target level')
    calculated_level = client.target_level(lr_rms)
    if not 30.0 <= calculated_level <= 130.0:
        raise RewError(
            f'REW calculated an implausible target level of {calculated_level:.2f} dB SPL; '
            'stopping before filter division')
    print(f'  calculated target level: {calculated_level:.2f} dB SPL')
    target = client.eq_command(lr_rms, 'Generate target measurement')
    if target is None:
        raise RewError('"Generate target measurement" produced no new measurement')
    client.rename(target, args.target_title)
    _, target_mag = response_band(client, target)
    target_median = float(np.median(target_mag))
    if not 30.0 <= target_median <= 130.0:
        raise RewError(f'Generated target has implausible 20-225 Hz median '
                       f'{target_median:.2f} dB SPL')
    return target


def verify_minimum_phase(client, triples):
    """Step 6a: a minimum-phase copy must preserve |H|. Compare source vs
    -MP magnitude over 20-225 Hz and warn if they disagree by more than a
    fraction of a dB (a real deviation means the LF tail is set wrong).

    Each measurement's frequency-response grid is anchored to its own
    native start frequency (an -MP copy typically starts near DC, its
    source much higher), so the two arrays are interpolated onto a common
    log-frequency axis rather than compared index-for-index.
    """
    for src_idx, mp_idx, label in triples:
        f0, ppo0, mag0 = client.frequency_response(src_idx, unit='SPL', ppo=96)
        f1, ppo1, mag1 = client.frequency_response(mp_idx, unit='SPL', ppo=96)
        freqs0 = f0 * 2.0 ** (np.arange(len(mag0)) / ppo0)
        freqs1 = f1 * 2.0 ** (np.arange(len(mag1)) / ppo1)
        band = (freqs0 >= 20) & (freqs0 <= 225)
        if not np.any(band):
            continue
        mag1_on_grid0 = np.interp(np.log(freqs0[band]), np.log(freqs1), mag1)
        delta = mag1_on_grid0 - mag0[band]
        max_abs = float(np.max(np.abs(delta)))
        flag = '' if max_abs < 0.5 else '  <-- check LF tail (want ~0.03 dB, see REW-INVERSION.md step 6a)'
        print(f'  6a check {label}: max |delta| = {max_abs:.3f} dB over 20-225 Hz{flag}')


#: (toml table, toml key) -> argparse dest. Kept next to parse_args so the
#: mapping and the flags it feeds can't silently drift apart; also the
#: single source of truth for rew_pipeline.example.toml's structure.
_CONFIG_KEYS = {
    ('measurements', 'center_l'): 'center_l',
    ('measurements', 'center_r'): 'center_r',
    ('measurements', 'pos_l_pattern'): 'pos_l_pattern',
    ('measurements', 'pos_r_pattern'): 'pos_r_pattern',
    ('measurements', 'num_positions'): 'num_positions',
    ('measurements', 'sum_c_title'): 'sum_c_title',
    ('measurements', 'x801_title'): 'x801_title',
    ('measurements', 'x801_wav'): 'x801_wav',
    ('measurements', 'x801_spl_offset_db'): 'x801_spl_offset',
    ('measurements', 'x801_window_type'): 'x801_window_type',
    ('measurements', 'x801_left_window_ms'): 'x801_left_window_ms',
    ('measurements', 'x801_right_window_ms'): 'x801_right_window_ms',
    ('target', 'target_title'): 'target_title',
    ('target', 'lf_cutoff_hz'): 'target_lf_cutoff',
    ('target', 'lf_slope_db_per_oct'): 'target_lf_slope',
    ('target', 'house_curve'): 'house_curve',
    ('target', 'house_curve_log_interpolation'): 'house_curve_log_interpolation',
    ('minphase1', 'lf_tail_corner_hz'): 'lf1_corner',
    ('minphase1', 'lf_tail_slope_db_per_oct'): 'lf1_slope',
    ('minphase1', 'hf_tail_corner_hz'): 'hf1_corner',
    ('minphase1', 'hf_tail_slope_db_per_oct'): 'hf1_slope',
    ('minphase1', 'hf_tail_frequency_warping'): 'hf1_warping',
    ('minphase2', 'lf_tail_corner_hz'): 'lf2_corner',
    ('minphase2', 'lf_tail_slope_db_per_oct'): 'lf2_slope',
    ('minphase2', 'hf_tail_corner_hz'): 'hf2_corner',
    ('minphase2', 'hf_tail_slope_db_per_oct'): 'hf2_slope',
    ('minphase2', 'hf_tail_frequency_warping'): 'hf2_warping',
    ('minphase', 'replicate_data'): 'replicate_data',
    ('division', 'common_low_hz'): 'common_low',
    ('division', 'common_split_hz'): 'common_split',
    ('division', 'upper_hz'): 'upper',
    ('experiments', 'enabled'): 'refinement_peq',
    ('experiments', 'peq82_frequency_hz'): 'peq82_frequency',
    ('experiments', 'peq82_gain_db'): 'peq82_gain',
    ('experiments', 'peq82_q'): 'peq82_q',
    ('experiments', 'peq530_frequency_hz'): 'peq530_frequency',
    ('experiments', 'peq530_gain_db'): 'peq530_gain',
    ('experiments', 'peq530_q'): 'peq530_q',
    ('fdw', 'cycles'): 'fdw_cycles',
    ('export', 'geometry'): 'geometry',
    ('export', 'name'): 'export_name',
}
_CONFIG_PATH_DESTS = {'x801_wav', 'house_curve'}


def load_config(path):
    """Read a TOML config (see rew_pipeline.example.toml) into a dict of
    argparse dest -> value, applied as new argparse defaults so the command
    line still overrides anything given explicitly. A key simply absent
    from the file leaves the script's own built-in default untouched --
    there is no separate "unset" sentinel to get wrong.
    """
    import tomllib
    with open(path, 'rb') as f:
        data = tomllib.load(f)
    defaults = {}
    for (table, key), dest in _CONFIG_KEYS.items():
        if table in data and key in data[table]:
            value = data[table][key]
            if dest in _CONFIG_PATH_DESTS and value:
                value = Path(value)
            defaults[dest] = value
    unknown_tables = set(data) - {table for table, _ in _CONFIG_KEYS}
    unknown_keys = [f'{t}.{k}' for t in data for k in data[t]
                    if (t, k) not in _CONFIG_KEYS and t not in unknown_tables]
    if unknown_tables or unknown_keys:
        names = sorted(unknown_tables) + unknown_keys
        raise SystemExit(f'{path}: unknown config key(s), check spelling: {", ".join(names)}')
    return defaults


def parse_args():
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument('--config', type=Path, default=None)
    pre_args, _ = pre.parse_known_args()
    config_path = pre_args.config
    if config_path is None and Path('rew_pipeline.toml').is_file():
        config_path = Path('rew_pipeline.toml')  # picked up automatically if present, CLI flags still win
    config_defaults = load_config(config_path) if config_path else {}

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', type=Path, default=config_path,
                   help='TOML file of defaults (see rew_pipeline.example.toml); auto-loaded from '
                        './rew_pipeline.toml if this flag is omitted and that file exists. '
                        'Command-line flags always override it.')
    p.add_argument('--api-url', default='http://127.0.0.1:4735')
    p.add_argument('--session', type=Path, default=None,
                   help='mdat to load if the raw captures are not already present')
    p.add_argument('--replace-session', action='store_true',
                   help='remove all currently loaded REW measurements before loading --session')
    p.add_argument('--raw-only-session', action='store_true',
                   help='after loading, retain only the configured raw L/R captures and simultaneous centre sum')
    p.add_argument('--tag', required=True,
                   help='suffix for measurements this run creates, e.g. "fdw12" -> "LX [fdw12]"; '
                        'reruns with the same tag replace their own prior measurements')
    p.add_argument('--output', type=Path, required=True,
                   help='directory for this run. The importable DRC-<geometry> project '
                        'directory is created inside it -- one run per --output, because '
                        'the UI imports a project holding exactly one .txts/.mdat pair')
    p.add_argument('--geometry', default=default_geometry(),
                   help='room name open-media-drc installs the design under; default: this '
                        'project directory without its DRC- prefix (%(default)s)')
    p.add_argument('--export-name', default=None, metavar='NAME',
                   help='stem shared by the exported NAME.txts folder and its NAME.mdat '
                        '(default: <geometry>.<tag>, which is what lets the UI read the '
                        'geometry and the design ID off the path)')
    p.add_argument('--acceptance', type=Path, default=Path(__file__).resolve().parent.parent / 'drc_acceptance.py')
    p.add_argument('--plot', action='store_true', help='ask ../drc_acceptance.py for a PNG plot (needs matplotlib)')
    p.add_argument('--save-mdat', type=Path, nargs='?', const=Path('-'), default=None,
                   metavar='PATH',
                   help='save the whole REW session to a .mdat when done (bare flag puts it '
                        'beside the export folder as <export-name>.mdat, where the directory '
                        'import needs it). Open it in REW to export the filters from the GUI: '
                        'those WAVs are bit-exact, which API-fetched samples cannot be')

    p.add_argument('--fdw-cycles', type=float, default=8.0)
    p.add_argument('--center-l', default='L0')
    p.add_argument('--center-r', default='R0')
    p.add_argument('--sum-c-title', default=None,
                   help='a real simultaneous L+R sweep at centre, e.g. "L0+R0"; '
                        'default: <center-l>+<center-r>. Falls back to vector-average(L0,R0) if absent')
    p.add_argument('--pos-l-pattern', default='L{n}')
    p.add_argument('--pos-r-pattern', default='R{n}')
    p.add_argument('--num-positions', type=int, default=4, choices=range(0, 5),
                   help='extra position pairs beyond the centre, 0-4')

    p.add_argument('--x801-title', default='X801')
    p.add_argument('--x801-wav', type=Path, default=Path('X801.wav'),
                   help='imported only if --x801-title is not already loaded')
    p.add_argument('--x801-spl-offset', type=float, default=3.0,
                   help='required REW splOffsetdB metadata for the unit-magnitude X801 IR; '
                        'a fresh 120 dB import therefore receives -117 dB (default: 3)')
    p.add_argument('--x801-window-type', default='Tukey 0.25',
                   help='left/right window type carried by reference X801 (default: Tukey 0.25)')
    p.add_argument('--x801-left-window-ms', type=float, default=100.0,
                   help='reference X801 left window width (default: 100 ms)')
    p.add_argument('--x801-right-window-ms', type=float, default=500.0,
                   help='reference X801 right window width (default: 500 ms)')

    p.add_argument('--target-title', default='Target LR.RMS.AVG',
                   help='reused as-is if already loaded (e.g. hand-tuned in REW); '
                        'otherwise auto-built from LX/RX with the options below')
    p.add_argument('--target-lf-cutoff', type=float, default=10.0)
    p.add_argument('--target-lf-slope', type=float, default=24.0)
    p.add_argument('--house-curve', type=Path, default=None,
                   help='a REW house-curve text file (freq/dB pairs), loaded before the target '
                        'is auto-built; only used when --target-title is not already loaded')
    p.add_argument('--house-curve-log-interpolation', action='store_true', default=True,
                   help='REW\'s house-curve log-interpolation flag, set explicitly since the API '
                        'has no way to read back a prior value (default on)')
    p.add_argument('--no-house-curve-log-interpolation', dest='house_curve_log_interpolation',
                   action='store_false')

    p.add_argument('--lf1-corner', type=float, default=16.0)
    p.add_argument('--lf1-slope', type=float, default=12.0)
    p.add_argument('--hf1-corner', type=float, default=None, help='enable an HF tail on minimum phase #1')
    p.add_argument('--hf1-slope', type=float, default=-18.0)
    p.add_argument('--hf1-warping', action='store_true')

    p.add_argument('--lf2-corner', type=float, default=16.0)
    p.add_argument('--lf2-slope', type=float, default=0.0)
    p.add_argument('--hf2-corner', type=float, default=None, help='enable an HF tail on minimum phase #2')
    p.add_argument('--hf2-slope', type=float, default=-18.0)
    p.add_argument('--hf2-warping', action='store_true')

    p.add_argument('--replicate-data', action='store_true',
                   help='REW "replicate data" flag used whenever a tail is disabled; '
                        'default off, check with --verify if unsure')

    p.add_argument('--common-low', type=float, default=25.0)
    p.add_argument('--common-split', type=float, default=80.0)
    p.add_argument('--upper', type=float, default=225.0)

    p.add_argument('--refinement-peq', action='store_true',
                   help='add the 82 Hz and 530 Hz cut experiments and retain baseline/individual predictions in REW')
    p.add_argument('--peq82-frequency', type=float, default=82.0)
    p.add_argument('--peq82-gain', type=float, default=-1.0)
    p.add_argument('--peq82-q', type=float, default=2.0)
    p.add_argument('--peq530-frequency', type=float, default=530.0)
    p.add_argument('--peq530-gain', type=float, default=-1.5)
    p.add_argument('--peq530-q', type=float, default=2.0)

    p.add_argument('--verify', action='store_true', default=True,
                   help='run the step-6a |H| preservation check after each minimum-phase pass (default on)')
    p.add_argument('--no-verify', dest='verify', action='store_false')

    if config_defaults:
        p.set_defaults(**config_defaults)
    args = p.parse_args()
    # Resolved and checked before REW is touched: a name open-media-drc cannot
    # split back into geometry and design ID is a directory that imports with
    # both fields typed in by hand, and that is worth failing a second into the
    # run rather than an hour later.
    if not _SAFE_NAME.fullmatch(args.geometry or ''):
        p.error(f'--geometry must match {_SAFE_NAME.pattern} (got {args.geometry!r}); '
                'pass it explicitly when the project directory is named something else')
    args.export_name = args.export_name or f'{args.geometry}.{args.tag}'
    args.design = args.export_name[len(args.geometry) + 1:] if (
        args.export_name[:len(args.geometry) + 1].casefold()
        in (f'{args.geometry}.'.casefold(), f'{args.geometry}@'.casefold())) else ''
    if args.design == 'default':
        p.error('design ID "default" is reserved by open-media-drc for the geometry\'s '
                'own base filters; pick another --tag or --export-name')
    if not _SAFE_NAME.fullmatch(args.design):
        p.error(f'--export-name {args.export_name!r} does not read as '
                f'<geometry>.<design-id> for geometry {args.geometry!r}, so the importer '
                f'would have no design ID to infer from it; the part after the geometry '
                f'must match {_SAFE_NAME.pattern}')
    if not 0 < args.common_low < args.common_split < args.upper:
        p.error('require 0 < common-low < common-split < upper')
    if args.replace_session and args.session is None:
        p.error('--replace-session requires --session')
    if args.peq82_gain > 0 or args.peq530_gain > 0:
        p.error('refinement PEQs must be cut-only (gain <= 0 dB)')
    if args.peq82_q <= 0 or args.peq530_q <= 0:
        p.error('refinement PEQ Q values must be positive')
    if (args.hf1_corner is not None and args.hf1_slope > 0) or (args.hf2_corner is not None and args.hf2_slope > 0):
        p.error('hf tail slope must be <= 0 dB/octave')
    return args


if __name__ == '__main__':
    sys.exit(run_pipeline(parse_args()))
