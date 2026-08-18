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
| **../../open-media-drc** | the product: deployed `FLOAT64_LE` coefficients under `filters/<geometry>/<rate>/`, versioned by **release tag**. `REW2raw.sh` converts REW WAV → raw with an `input_rate/target_rate` coefficient scale |

`../DRC-120` (no `.blue`) is **retired — never use it**. Older measurement
archives: `../803D2/`, `../803D2/2017-subs/`, `../801N.first.measurements/`.

**The rule for this repo:** anything a document or a script needs lives here;
measurements and their figures live with their geometry. Every trace plotted
here is read across a relative path into a geometry repo — see *Cross-repo
paths* below.

## The documents

- **`REW-INVERSION.md`** — the procedure. Clean, no history, no retractions.
  Its worked example is the 120 cm configuration, but the procedure is general.
- **`NOTES.md`** — the history *and* the retractions, through 2026-08-18.
- **`SUBWOOFER-INTEGRATION.md`** — the sub analysis, added 2026-08-13.
- **`GIK-SCREEN-PANEL-PLACEMENT-120cm.md`** — the completed 120 cm study of
  first-reflection geometry and the right-side panel reorder.
- **`MANUAL.md`** — `allpass_tool.py` user manual. Finished reference.
- **`HANDOFF.md`** — resuming on another machine; the environment traps.

Do not let the working notes bleed into the guide; that separation is
deliberate. The guide is clean *because* the retractions are in `NOTES.md`,
which is why the two travel together and must stay in the same repo.

Forward, geometry-specific working notes are written in that geometry's own
notes: `../DRC-185/NOTES.md`, `../DRC-120.blue/NOTES.md`. A completed,
self-contained study may live here when its filename identifies the geometry,
it keeps the measurements in their geometry repository, and its scripts read
them through an explicit cross-repository path.

## Building the PDFs

```sh
./make-pdf.sh REW-INVERSION.md          # default target is NOTES.md
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
python3 drc_acceptance.py ../DRC-120.blue/FLX-trimmed-48k.wav
```

Three tests: sharpest feature (**Q ≤ 12**, not FFT bins — bin spacing is
`fs/n`, so a bin threshold depends on file length), group-delay excursion
(10 ms, 20–200 Hz), and gated-tone tails (median over nine tone lengths; a
single length is not reproducible). `X801.wav` passes all three and is the
known-good control.

The thresholds are a **build-quality gate, not a verdict on audibility**. R8 of
the guide carries the audibility figures separately.

### Two sharpness rules that look contradictory and are not

| | object judged | metric | why |
|---|---|---|---|
| guide **step 6b** | the *divisor* (`LX-MP`) inside REW | ~30 FFT bins ≈ 11 Hz | REW's display grid is fixed at 0.366 Hz, so bins are a stable unit there |
| `drc_acceptance.py` | the *exported filter WAV* | **Q ≤ 12** | bin spacing is `fs/n`; a bin threshold would pass or fail the same filter depending on file length |

Both are correct. `fig-chain.png` shows the bin form because it depicts step 6.
Do not "reconcile" them.

## Cross-repo paths

No script here reads a local data file. What each one opens:

| script | reads | writes |
|---|---|---|
| `figbass.py` | `../DRC-120.blue/120.blue.Rscreen.txts/` | `fig-common-bass.png` |
| `figconv.py` | `../DRC-120.blue/` + `120.blue-with-inversion.txts/` | `fig-convolution.png` |
| `figwin.py`, `figfdw.py` | `../DRC-120.blue/LEFT-measured.csv` | `fig-window-shapes.png`, `fig-fdw.png` |
| `figchain.py` | nothing — it draws | `fig-chain.png` |
| `figroom.py` | `roomgeom.py`, traced from `room-form-with-panels.png` | `room-form.pdf` (2 pages), `room-form.png`, `room-form-panels.png` |
| `figreflect.py` | `roomgeom.py` | `reflections-L-R.pdf`, `reflections-L.png`, `reflections-R.png` |
| `gik_screen_panel_placement-120cm.py` | `roomgeom.py`, `../DRC-120.blue/foam.screens.opendoor.mdat`, `../DRC-120.blue/120.blue.Rscreen.txts.boh/` | `panel-placement-*-120cm.png` |
| `housecurve.py` | nothing | `house-curve-C2.txt`, `house-curve-C3.txt` |
| `allpass_tool.py` | `-l/-r/-s`, default `L0/R0/LR.txt` **in the cwd** | — |

`allpass_tool.py` defaults to filenames that now live next door. Run it as:

```sh
python3 allpass_tool.py -l ../DRC-185/L0.txt -r ../DRC-185/R0.txt -s ../DRC-185/LR.txt
```

`room.png` and `room-form-with-panels.png` are **inputs** — the pencil plan and
the hand-annotated panel sketch. The `room-form*` outputs are generated.

### The 2026-08-14 export-directory rename

`DRC-120.blue` renamed its export directories; older text referred to the old
names, and every reference here was corrected on 2026-08-18:

| old name | now |
|---|---|
| `txt/` | `120.blue-with-inversion.txts/` |
| `new.filters.txts/` | `120.blue.Rscreen.txts/` |

The pre-rename snapshot of the second one survives at
`../DRC-120.blue/archive/2026-08-12-noLFtail/new.filters.txts/` — that is the
**no-LF-tail build**, kept because it fails the minimum-phase property. Do not
read figures from it. Its measured traces are identical to the live ones
(0.000 dB); only the target differs, by +0.03 dB.

## Room geometry

`roomgeom.py` is the single source of truth, imported by `figroom.py` and
`figreflect.py` so they cannot drift. Distances are to the **tweeter**, measured
2026-08-10. Room length 7.40 m, the 1.80 m opening, the corridor and the
ceiling slant are still **from the sketch, not measured** — treat as
indicative.

## Naming and versioning

- **Stable names for the current build**: `FLX-48k.wav`, `FLX-trimmed-48k.wav`.
- **Suffix only while two builds must coexist** for comparison (`FLX8` vs
  `FLX`), then collapse to the stable name once one wins.
- **Deployments are versioned by `open-media-drc` release tags**, not by
  filenames and not by DRC-120.blue. That repo already answers "what was in
  service".

## A habit worth keeping

Several conclusions this project reached were wrong on first pass and were
caught by carrying a number through to the thing that actually ships. Before
acting on a discrepancy in a divisor, a measurement or a metric, **carry it
through `min(Target − divisor, 0)` and see whether it survives the clamp.** It
usually does not.
