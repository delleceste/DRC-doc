---
name: rew-inversion-audit
description: >
  Use this skill whenever asked to analyze, review, or audit REW-exported
  measurement/filter .txt or .wav files from a DRC-by-inversion session —
  e.g. "analyze the txt measurements and filters under
  DRC-120.green.multipt.txts", "check this filter export", "why did
  drc_acceptance.py fail on FLX", "is this correction curve safe to deploy",
  or any request touching a `<geometry>/<geometry>.multipt.txts/` (or
  `.multi.pt.txts/`) directory, `X801.wav`, `Fcommon`/`Fper_L`/`Fper_R`,
  `LFilter`/`RFilter`, `FLX`/`FRX`, or REW trace-arithmetic exports for a
  BruteFIR/open-media-drc room-correction filter. Also use to run and
  interpret `drc_acceptance.py`, and to explain FAILURES it reports
  (sharp Q, group-delay excursion, gated-tone tail) against
  REW-INVERSION.md's procedure and thresholds.
---

# REW Inversion & DRC Acceptance Auditor

Audits REW room-correction work (the "inversion" method) against the
project's own written procedure, and runs/interprets the numerical
acceptance test. It does not replace REW — it reviews what REW produced.

## Canonical references (read before judging anything)

- **`REW-INVERSION.md`** (this repo's root) — the procedure, in full. Load
  it (or the specific section you need) before commenting on any step.
  Structure:
  - Part I (§1–5): what a *minimum-phase* inversion can and cannot fix, and
    the failure mode this whole guide exists to prevent (a 38 dB null
    inverted literally into a Q≈40 resonator that rang for 1.3 s).
  - Part II (§6–12): the decisions taken *before* measuring — multi-position
    averaging, FDW cycles, smoothing, correction band, correcting the sum
    below 80 Hz vs. each channel above it.
  - **Part III — the 11-step procedure** (`## Step 1` … `## Step 11`, plus
    the TL;DR at the top of Part III). This is the checklist to compare a
    given export against:
    1. Measure 5 positions (C, F20/B20/L20/R20), one shared acoustic timing
       reference speaker for every sweep.
    2. Same IR window (FDW, ~12 cycles) applied to **every original capture
       before any averaging** — the single step a later failure always
       traces back to.
    3. Reduce to three divisors: `L-SP`, `R-SP` (RMS-averaged per channel),
       `SUM-SP` (mono sum, position-averaged).
    4. First minimum-phase pass on `LX`/`RX`/`SUM-SP`.
    5. Build the target (house curve).
    6. Stop and check the `-MP` copies for narrow dips before dividing by
       them (a dip here becomes a boost downstream).
    7. Divide: target ÷ `SUM-MP` → `Fcommon` (20–80 Hz, or 20-225 depending
       on project); target ÷ `LX-MP`/`RX-MP` → `Fper_L`/`Fper_R` (80–225 Hz).
       `Max gain` on, 0 dB (cut-only). Multiply into `Fl`/`Fr`.
    8. Second minimum-phase pass → `LFilter`/`RFilter`.
    9. Bake in the crossover correction last: `X801 × LFilter` → `FLX` (and
       `FRX`).
    10. Trim/export 48 kHz, 32-bit float WAV.
    11. **`drc_acceptance.py` on both channels. A failure sends you back to
        step 2 — never a post-hoc patch on the WAV.**
  - Part IV / Reference (`R1`–`R11`): field-by-field dialog reference,
    window-shape choice, the two places minimum phase is taken (and the one
    place it must not be), `÷` vs `1/A` vs `1/|A|`, boost guards, X801's role
    (**R7** — flat magnitude, corrects crossover all-pass only, do not
    re-derive it from the `.rephase` project on disk, it's stale), and
    **R8 — the acceptance tests themselves**, with worked pass/fail numbers.
  - Glossary at R11 for any unfamiliar REW term (FDW, Ref Time, RMS vs Vector
    average, etc).

- **Reference example trees** — real, complete exports to compare structure
  and naming against:
  - `../DRC-120.blue/120.blue.multi.pt.txts/` — the Blue geometry's
    multi-position export (Nautilus 801, 120 cm from front wall).
  - `../DRC-120.green/120.green.multipt.txts/` — the Green geometry's export.
  - Both follow the same naming: `L …`/`R …` per-position captures, `L.txt`/
    `R.txt`/`LR.txt` spatial averages, `LX`/`RX`/`X801` (crossover-corrected
    minimum-phase divisors), `Fcommon`/`Fper_L`/`Fper_R`/`Fl`/`Fr` (division
    stage), `L.Filter`/`R.Filter` and `L.Filtered`/`R.Filtered`, `FLX`/`FRX`
    and `FLX-trimmed-48k.wav`/`FRX-trimmed-48k.wav` (final export, what
    BruteFIR actually loads), plus `Target LR.RMS.txt`. When a new export is
    missing a file this family expects, or a trace is named unexpectedly,
    flag it — it usually means a step was skipped or run out of order.

## Running the acceptance script

```sh
drc_acceptance.py <geometry>-trimmed-48k.wav [second-channel.wav] [--plot out.png]
```

(`drc_acceptance.py` lives at this repo's root; adjust the path when run
from another checkout.) Run it on the WAV BruteFIR will actually load
(`FLX-trimmed-48k.wav` / `FRX-trimmed-48k.wav`), not on an intermediate
trace. If you want to separate room-correction ringing from the crossover
filter's own contribution, also run it on `LFilter`/`RFilter` alone —
`X801.wav` passes all three tests on its own by construction (flat
magnitude), so any failure on the combined `FLX`/`FRX` file is coming from
the room-correction (inversion) part.

### The three tests, and how to read a FAILURE

| test | what it measures | threshold | what a failure means |
|---|---|---|---|
| **sharpest feature below 200 Hz** | Q = centre-frequency ÷ bandwidth of the narrowest peak/notch in the filter's *own* magnitude | Q ≤ 12 | The filter contains a feature narrower than an N-cycle FDW (8–12 cycles) can legitimately produce → it inverted a null/spike that was too sharp to be a real room mode (interference, not acoustics) rather than a regularised correction. Q is dimensionless and length-independent by design — don't second-guess a failure by pointing at the "bins" figure, that column is legacy/reference only. |
| **group delay excursion, 20–200 Hz** | peak \|group delay\| in that band, referenced to the 200–400 Hz median | ≤ 10 ms | A correction filter should show a few ms; tens of ms means a resonator was built. This is the one test with a direct one-graph REW equivalent (import the WAV, look at Group Delay). |
| **gated-tone tail** | time for a 1 s tone + silence, convolved with the filter, to fall 40 dB (median over 9 tone lengths, control-subtracted against a matched-latency pure delay) | ≤ max(100 ms, 3×control, 4000/f₀ ms) | The direct numerical form of "the music stops and the woofers keep moving". Distrust any single-length tail; read the `spread`/IQR column, and treat entries flagged `noisy` as inconclusive either way. If the printed `control` column is not monotonically decreasing as frequency rises, something is wrong with the run itself (a collapsed control silently lowers the limit) — say so rather than trusting the tails. |

When explaining a FAILURE line to the user:
1. State which test failed, the reported value vs. threshold, and the
   frequency it occurred at.
2. Cross-reference REW-INVERSION.md R8's worked table (Q 73 / +80 ms /
   1348 ms was the canonical September-2025 deployed-filter failure) to say
   whether this looks like *that* class of defect.
3. Point at the procedure step most likely responsible — per §2/step 2, a
   defect that appears at 20–30 Hz and is razor-thin is almost always a
   windowing-before-averaging problem or an under-regularised divide (step
   2/7), not something fixable by re-exporting; per R8's worked example, a
   failure that has moved to a broad, physically-explicable feature (an SBIR
   null with matching geometry) is a different kind of failure — a judgment
   call about how hard to correct, not a bug.
4. Never suggest patching the exported WAV directly. The fix is always to
   redo the REW chain from the implicated step (usually step 2 or 7), per
   step 11's rule.
5. A "marginal" Q (roughly 12–15) or a group-delay excursion a few ms over
   threshold at a frequency where the audibility table in R8 (~45 ms @20 Hz
   down to ~6 ms @1 kHz) is not exceeded is worth flagging as *pass the
   audibility bar but fail the build-quality gate* — read a script failure
   as "look at this", not automatically as "this will be audible".

## Remediation — "why did it fail, and will X fix it?"

This is the most common follow-up (e.g. "why does the acceptance test fail
on `<geometry>.multipt.txts` and would reducing the FDW cycles help?").
Answer from `REW-INVERSION.md` §8 and R10, not from general DSP intuition:

- **§8 pins the FDW cycle count (N) between two constraints, not one.**
  N must be **≳ 12** so as not to truncate genuine modal decay (a real mode's
  Q, from the room's T60, floors N), and **≪ 40** so it does not preserve
  position-specific interference nulls as if they were resonances (the
  September-2025 deployed failure was exactly a Q≈40 null taken literally).
  12 cycles is the default starting point and sits inside both bounds.
- **So "reduce the FDW cycles" is not a universal fix — first identify what
  the failing feature *is*:**
  - If it's a genuine **room mode** (present in more than one channel /
    position, physically plausible Q from the room's T60 via R6) — lowering
    N below its own Q would *widen and misrepresent* it, not fix anything.
    Don't reduce N here; the fix is elsewhere (usually more spatial
    positions, §6, or checking step 6/7 band limits).
  - If it's a **boundary cancellation / interference null** (Q too high for
    the room's volume to sustain that long a decay, visible in one channel
    only, or predictable from source-mic geometry, e.g. the project's own
    74 Hz SBIR example) — the modal floor doesn't apply to it, and §8's own
    worked comparison shows dropping from **12 → 8 cycles** measurably fixed
    exactly this class of failure: narrowest-feature Q went from failing to
    passing on both channels, group delay dropped ~7 ms, gated-tone failures
    dropped from 2/5 to 1/0 — at a cost of only ~0.6–0.8 dB rms change to the
    correction curve, concentrated near the null itself. **Yes, in that
    case, reducing FDW cycles is the right fix** — but verify the feature is
    a cancellation first (R10 row: "Deep null got *deeper* after the FDW" —
    if so it's early-arrival and real; do not try to fill it by changing N).
  - Going too low (N ≲ 4) starts to erode real structure and is its own
    failure mode — §8 is explicit this is a three-way pinned choice, not a
    dial to turn until the script passes.
- **Cross-check against R10's troubleshooting table** before proposing a
  fix — most FAILURE causes are *not* the FDW at all: unset frequency limits
  in the divide (step 7), a stale/snapshotted trace from changing an input
  after the arithmetic was already run (redo from step 3), `Vector average`
  used across positions instead of `RMS average` (must be RMS, §6/3d), or the
  FDW applied to spatial averages instead of the original captures (step 2 —
  window every capture *first*, average second; this is the "single step a
  later failure always traces back to").
- Always state which of these you believe applies and why, tying the
  diagnosis to something observable in the `.txt`/`.wav` files or the
  acceptance-script output (which channel, which frequency, single-position
  vs. multi-position, Q value) — not as a generic checklist recitation.

## The ecosystem these filters run in

This project is REW-side of `open-media-drc`, a room-correction stack that
turns REW exports into a real-time convolution chain:

- **`open-media-drc`** (`~/devel/open-media-drc`) — the public engine: build
  system, `drc.sh`, and the scripts that turn a REW WAV export into
  per-sample-rate BruteFIR coefficients. Ships only a flat/identity filter
  set; real per-room filters live in a separate site-data checkout.
- **BruteFIR** — the convolution engine that actually applies the exported
  filters (`FLX`/`FRX`) to program audio in real time. It reads only the raw
  coefficient files the build produces from the REW WAV — never a REW
  project or intermediate trace directly.
- **MPD (Music Player Daemon)**, under FreeBSD — the playback source feeding
  the audio chain.
- **virtual_oss**, on FreeBSD — provides the virtual OSS device(s) that let
  MPD's output and BruteFIR's convolution sit in the same audio path on a
  FreeBSD box.
- **ALSA / `alsaloop`**, on Linux — the Linux-side equivalents: ALSA as the
  audio subsystem, `alsaloop` to route/loop audio between devices (e.g.
  between a player and BruteFIR) the way `virtual_oss` does on FreeBSD.

Keep this map in mind when a question is about *why* a filter is built the
way it is (minimum-phase, cut-only, 48 kHz float export) — those constraints
come from what BruteFIR and the playback chain can and must consume, not
just from REW's own defaults.

## Working method

1. If asked to "analyze the txt measurements and filters under
   `<geometry>.multipt.txts`" (or similarly named) directory: list it,
   identify which files map to which step of the 11-step procedure (using
   the naming table above as the key), and check that the expected set is
   complete and internally consistent (e.g. `FLX`/`FRX` exist and are newer
   than `LFilter`/`RFilter`, which are newer than `Fl`/`Fr`, etc. — a stale
   downstream file is a sign a step was rerun out of order).
2. If a `-trimmed-48k.wav` pair is present, run `drc_acceptance.py` on it and
   report PASS/FAIL per test as above.
3. Tie any anomaly back to a specific step or R-section of
   `REW-INVERSION.md` rather than speaking in the abstract — this is a
   procedure document with worked numbers; use them for comparison.
4. When in doubt about scope (e.g. whether a request wants a full step-by-step
   audit vs. just the acceptance numbers), ask, rather than assuming the
   larger job.
