# Working notes for this repository

**DRC-doc** — the guides, the studies and the tooling for the room-correction
project. Split out of `DRC-185` on 2026-08-18 so that the documents no longer
live inside one geometry's measurement repo.

Room correction for B&W **Nautilus 801** (aluminium dome, *not* the Diamond
series) in a 1905 house, ~58 m³. Measurements in REW, filters convolved by
BruteFIR.

## The four repositories

| repo | role |
|---|---|
| **DRC-doc** (here) | documents, figures, analysis scripts, the PDF toolchain. **No measurement data at all** |
| **../DRC-185** | the 185 cm geometry: `L0.txt`, `R0.txt`, `LR.txt` (Oct 2024), the mdats and the 185-era filter builds |
| **../DRC-120.blue** | the lab: REW exports and filter WAVs for the 120 cm geometry |
| **../../open-media-drc** | the public engine: scripts, `drc.sh`, BruteFIR, the build, versioned by **release tag**. Ships only the uncorrected `flat` set. `REW2raw.sh` converts REW WAV → raw with an `input_rate/target_rate` coefficient scale |
| **~/devel/omdrc-801N** | the *site data* — **this room's** deployed `FLOAT64_LE` coefficients under `filters/<geometry>/<rate>/[@<design>/]`, plus manifests and configs. Split out of `open-media-drc` so engine and room version separately; reached via `OMDRC_SITE_ROOT` / `--site-root` / CMake's `OMDRC_SITE_DATA_DIRS` |

`../DRC-120` (no `.blue`) is **retired — never use it**. Older measurement
archives: `../803D2/`, `../803D2/2017-subs/`, `../801N.first.measurements/`.

**The rule for this repo:** anything a document or a script needs lives here;
measurements and their figures live with their geometry. Every trace plotted
here is read across a relative path into a geometry repo — see *Cross-repo
paths* below.

## The documents

- **`REW-INVERSION.md`** — the procedure. Clean, no history, no retractions.
  Its worked example is the 120 cm configuration, but the procedure is general.
- **`SUBWOOFER-INTEGRATION.md`** — the sub analysis, added 2026-08-13.
- **`room/GIK-SCREEN-PANEL-PLACEMENT-120cm.md`** — the completed 120 cm study of
  first-reflection geometry and the right-side panel reorder.

Do not let the working notes bleed into the guide; that separation is
deliberate. The guide is the current procedural reference; historical working notes are not part of this repository.

self-contained study may live here when its filename identifies the geometry,
it keeps the measurements in their geometry repository, and its scripts read
them through an explicit cross-repository path.

## Claude skill

`.claude/skills/rew-inversion-audit/SKILL.md` — audits REW inversion-method
exports (the `<geometry>.multipt.txts/` trees) and `tools/drc_acceptance.py`
output against this repo's own procedure (`REW-INVERSION.md`'s 11 steps and
`R1`–`R11`), knows the open-media-drc/BruteFIR/MPD/virtual_oss/alsa
ecosystem, and carries remediation guidance (e.g. when reducing FDW cycles
actually helps vs. when it doesn't — §8/R10). Triggers automatically on
requests like "analyze the txt measurements under `<geometry>.multipt.txts`"
or "why did the acceptance test fail", or invoke directly with
`/rew-inversion-audit`.

## Building the PDFs

```sh
./make-pdf.sh REW-INVERSION.md          # default target is REW-INVERSION.md
```

Three traps, all hit more than once:

1. **`tail` masks the exit status.** `./make-pdf.sh X.md | tail -2` always
   succeeds. Use `${PIPESTATUS[0]}` or the commit will take a stale PDF.
2. **`≤` is not in the font** although `≥` is. Reword rather than fight it.
   Check new glyphs before building:
   ```sh
   python3 -c "print(sorted({c for c in open('F.md').read() if ord(c)>127}))"
   ```
   and add `\newunicodechar` lines to `pdf-header.tex` as needed.
3. **BSD userland** — `sed -i` needs a backup suffix, `ls --time-style` and
   `du --apparent-size` do not exist, and there is no `shuf`. Prefer the Edit
   tool or Python over `sed -i`.

The engine is **pdflatex**, not xelatex — there is no xelatex here, which is
exactly why trap 2 exists.

## Verifying a filter

```sh
python3 tools/drc_acceptance.py ../DRC-120.blue/FLX-trimmed-48k.wav
```

Three tests: sharpest feature (**Q ≤ 12**, not FFT bins — bin spacing is
`fs/n`, so a bin threshold depends on file length), group-delay excursion
(10 ms, 20–200 Hz), and gated-tone tails (median over nine gate phases; a
single phase is not reproducible). `X801.wav` passes all three and is the
known-good control. `python3 -m unittest test_drc_acceptance` covers the
estimator.

The thresholds are a **build-quality gate, not a verdict on audibility**. R8 of
the guide carries the audibility figures separately.

### The tail estimator was rewritten on 2026-09-13 — revision 1 under-reported

Revision 1 reported the **first** −40 dB crossing, so a rebound afterwards did
not count; it `np.roll`ed the impulse before a **linear** convolution, which
could move late ringing in front of the main peak and out of the measurement;
its observation window silently shrank by the filter's own latency; and it
dropped never-settled trials from the median. **Do not compare a tail printed
before that date with one printed after** — the two are different quantities,
and the old one is the smaller.

The estimator is anchored at both ends: it reproduces the Sept 2025 filter at
**1349 ms** against the **1348 ms** on record, and measures `X801.wav` at the
analysis floor exactly, at every tone.

Each tail is judged as **control + 100 ms**, never a multiple of the control.
The estimator has a floor of its own — a pure delay, which rings not at all,
still measures 132 ms at 28.7 Hz and 5 ms at 180 Hz — and that floor is the
noisiest quantity in the test: at 79 Hz its nine gate phases span 2–54 ms while
the filter's span 105–125. The old `3 × control` rule tracked that noise
straight into the verdict, passing or failing the same filter on a change of
gate ramp. Read the **`excess`** column: it is the quantity actually judged,
and a filter that adds no ringing of its own scores 0.

### Two sharpness rules that look contradictory and are not

| | object judged | metric | why |
|---|---|---|---|
| guide **step 6b** | the *divisor* (`LX-MP`) inside REW | ~30 FFT bins ≈ 11 Hz | REW's display grid is fixed at 0.366 Hz, so bins are a stable unit there |
| `tools/drc_acceptance.py` | the *exported filter WAV* | **Q ≤ 12** | bin spacing is `fs/n`; a bin threshold would pass or fail the same filter depending on file length |

Both are correct. `figures/rew-inversion/fig-chain.png` shows the bin form because it depicts step 6.
Do not "reconcile" them.

## Cross-repo paths

No script here reads a local data file. What each one opens:

| script | reads | writes |
|---|---|---|
| `figures/rew-inversion/figbass.py` | `../DRC-120.blue/120.blue.Rscreen.txts/` | `fig-common-bass.png` |
| `figures/rew-inversion/figconv.py` | `../DRC-120.blue/` + `120.blue.txts/` | `fig-convolution.png` |
| `figures/rew-inversion/figwin.py`, `figures/rew-inversion/figfdw.py` | `../DRC-120.blue/LEFT-measured.csv` | `fig-window-shapes.png`, `fig-fdw.png` |
| `figures/rew-inversion/figchain.py` | nothing — it draws | `figures/rew-inversion/fig-chain.png` |
| `room/figroom.py` | `room/roomgeom.py`, traced from `room/room-form-with-panels.png` | `room-form.pdf` (2 pages), `room-form.png`, `room-form-panels.png` |
| `room/figreflect.py` | `room/roomgeom.py` | `reflections-L-R.pdf`, `reflections-L.png`, `reflections-R.png` |
| `room/gik_screen_panel_placement-120cm.py` | `room/roomgeom.py`, `../DRC-120.blue/foam.screens.opendoor.mdat`, `../DRC-120.blue/120.blue.Rscreen.txts.boh/` | `panel-placement-*-120cm.png` |

`room/room.png` and `room/room-form-with-panels.png` are **inputs** — the pencil plan and
the hand-annotated panel sketch. The `room-form*` outputs are generated.

### The `DRC-120.blue` renames

`DRC-120.blue` renamed its session and export names twice; older text referred
to the old names. The 2026-08-14 batch was corrected here on 2026-08-18, the
2026-09-01 batch on 2026-09-01:

| old name | now | when |
|---|---|---|
| `txt/` | `120.blue-with-inversion.txts/` | 2026-08-14 |
| `new.filters.txts/` | `120.blue.Rscreen.txts/` | 2026-08-14 |
| `120.blue-with-inversion.txts/` | **`120.blue.txts/`** | 2026-09-01 |
| `120-blue-with-inversion.mdat` | **`120.blue.mdat`** | 2026-09-01 |

The 2026-09-01 session rename came with a **clean** — measurements made by
other techniques were removed and everything re-exported — so `120.blue.mdat`
is a different file from the one `open-media-drc` audited, not merely a
renamed one. The deployed chain (`FLX`, `FRX`, `…-trimmed`,
`X801 (revised)`) re-exports numerically identical; the measurement traces are
now unsmoothed instead of 96 ppo Psychoacoustic. Details and the recovery hash
are in `../DRC-120.blue/CLAUDE.md`.

The pre-rename snapshot of the second one survives at
`../DRC-120.blue/archive/2026-08-12-noLFtail/new.filters.txts/` — that is the
**no-LF-tail build**, kept because it fails the minimum-phase property. Do not
read figures from it. Its measured traces are identical to the live ones
(0.000 dB); only the target differs, by +0.03 dB.

## Room geometry

`room/roomgeom.py` is the single source of truth, imported by `room/figroom.py` and
`room/figreflect.py` so they cannot drift. Distances are to the **tweeter**, measured
2026-08-10. Room length 7.40 m, the 1.80 m opening, the corridor and the
ceiling slant are still **from the sketch, not measured** — treat as
indicative.

## Naming and versioning

- **Stable names for the current build**: `FLX-48k.wav`, `FLX-trimmed-48k.wav`.
- **Suffix only while two builds must coexist** for comparison (`FLX8` vs
  `FLX`), then collapse to the stable name once one wins.
- **Deployments are versioned by annotated tags and bundle IDs**, not by
  filenames and not by DRC-120.blue. `omdrc-801N` answers "what is in service";
  `open-media-drc` release tags version the engine, not the filters.

## A habit worth keeping

Several conclusions this project reached were wrong on first pass and were
caught by carrying a number through to the thing that actually ships. Before
acting on a discrepancy in a divisor, a measurement or a metric, **carry it
through `min(Target − divisor, 0)` and see whether it survives the clamp.** It
usually does not.
