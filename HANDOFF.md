# Handoff — resuming this work on another machine

Read this first, then `NOTES.md` (running state and open threads), then
`MANUAL.md` (finished reference). Between them they carry everything; nothing
required to continue lives outside this repository.

> **Why this file exists.** Claude Code's memory and session transcripts are
> stored per-machine under `~/.claude/projects/…`. They do **not** travel with
> a `git clone`. Everything below was lifted out of that memory so the work is
> reconstructable from the repository alone.

---

## 1. What this project is

Room correction for **B&W Nautilus 801** at the 185 cm listening position
(green floor marks), BruteFIR convolution chain at 192 kHz, measurements in
**REW**, parametric filter design in **rePhase**.

The specific problem: the combined L+R response has a **deep null at
40.3–46.5 Hz** — 23.8 dB below the in-phase sum, coherence 6%, with L and R
matched within 0.1 dB. That signature means **destructive interference
between the channels**, not a level shortfall, so it is an all-pass problem
rather than an EQ problem.

`allpass_tool.py` was written to diagnose exactly that and to size the
all-pass, because REW has no view that separates interference from level.

## 2. Environment

- Host is **FreeBSD 15**. Qt comes from `pkg`, not pip.
- `pkg install py312-numpy py312-pyside6`
- `python3.12 -m ensurepip --user` *(once — see the version trap below)*
- `python3.12 -m pip install --user pyqtgraph` — **pip, not pkg**: the FreeBSD
  pyqtgraph port pulls PyQt5 and the whole Qt5 stack plus scipy, matplotlib
  and h5py. pyqtgraph is binding-agnostic and picks up whichever Qt is
  already imported; this tool imports PySide6 first, so it runs on Qt6.
- Run: `python3 allpass_tool.py -l L0.txt -r R0.txt -s LR.txt`
  (falls back to those names in the current directory). The tool needs no
  `PYTHONPATH`. `audio_io.py` must sit beside it.

### The Python-version trap — cost an hour on 2026-08-03

Qt is `py312-pyside6`, so the tool **must** run on Python 3.12. But every
`pip` on `PATH` here belongs to 3.11:

```
/usr/local/bin/pip    →  #!/usr/local/bin/python3.11
~/.local/bin/pip3     →  #!/usr/local/bin/python3.11
```

A bare `pip install --user pyqtgraph` therefore installs into
`~/.local/lib/python3.11/site-packages` — invisible to `python3` (3.12) —
and **reports success** while the tool dies with `ModuleNotFoundError: No
module named 'pyqtgraph'`.

The obvious escape, `python3 -m pip …`, fails too: only `py311-pip` is
packaged, so **3.12 has no pip module at all**. `python3.12 -m ensurepip
--user` bootstraps one into `~/.local` without root (`pkg install py312-pip`
if you prefer it system-wide). Then install with the version spelled out.

Check the result — pip's exit status does not tell you:

```
python3 -c "import pyqtgraph, PySide6, numpy; print(pyqtgraph.__file__)"
```

The path must contain **`python3.12`**. Working set as of 2026-08-03:
pyqtgraph 0.14.0, PySide6 6.11.1, numpy 2.4.6.

**Related hazard:** the shell here exports
`PYTHONPATH=/usr/local/cumbia-libs/lib/python3.11/site-packages` for
unrelated (cumbia) reasons. That **3.11** directory lands on **3.12**'s
`sys.path`. Pure-Python packages import fine; compiled extensions are built
against the wrong ABI and will fail or shadow a correct 3.12 copy. It does
not currently break this tool — but unset it first if any import misbehaves.

## 3. Files

| file | what it is |
|---|---|
| `allpass_tool.py` | the GUI tool — analysis, all-pass design, Auto EQ, export |
| `audio_io.py` | dependency-free WAV/RAW/TXT I/O (PCM 8/16/24/32, float 32/64) |
| `MANUAL.md` | finished reference: how it works and why, 11 sections |
| `NOTES.md` | running investigation state and open threads |
| `L0.txt` `R0.txt` `LR.txt` | the reference measurements (REW text exports) |
| `L_ap+R0.txt` | REW trace arithmetic, used to validate predictions |
| `ap_L_42p5_Q2p5.txt` | rePhase all-pass, used to validate the filter model |
| `Xo801.wav` | rePhase phase-linearisation filter for the 801 |
| `L-EP.txt` `R-EP.txt` | **excess phase** exports (magnitude 0 dB) — *not* a second mic position |

## 4. Validated numbers — do not re-derive these

- Null 40.3–46.5 Hz, coherence 6%, −23.8 dB vs the in-phase sum. Δφ(L−R)
  crosses 180° at **42.6 Hz**; **L leads**, so the all-pass goes on **L**.
- rePhase "all pass normal" **is** the RBJ all-pass biquad — reproduced
  `ap_L_42p5_Q2p5.txt` to **5 × 10⁻⁵ per tap** at 48 kHz.
  `H(s) = (s² − s/Q + 1)/(s² + s/Q + 1)`, `s = jf/f0`; −180° exactly at f0.
- Group delay at f0 = `4Q/ω₀`, and it is the maximum.
- Predicted corrected L+R matches REW trace arithmetic (`L_ap+R0.txt`) to
  **0.22 dB max, 0.01 dB median** over 25–100 Hz.
- The REW export grid **is** an FFT grid (0.36621 Hz = 48000/131072, first
  bin k = 41). Zero-fill bins 0–40 and `irfft()` recovers the true impulse
  response. This is how the X801 and clarity work below was done.
- Recommended all-pass: **41.8 Hz / Q 1.55** (24 ms, 0.99 cycles) over the
  nominal best 43.3 Hz / Q 2.75 (40 ms, 1.75 cycles). Half the group delay
  for a quarter of a dB. **But see open thread 1 — a subwoofer beats both.**

## 5. The user's stated design philosophy

Carried forward from 2026-08-01, and it drives the tool's guard rails:

- **Manipulate phase as little as the correction allows.**
- **EQ first** for bumps and dips that are not interference; **all-pass only**
  for true inter-channel cancellation.
- Willing to **give up 1–2 dB of bass correction for timing accuracy** — kick
  drum attack and clarity beat a flatter magnitude.
- Normal working technique is to **EQ L and R individually in REW**, then
  combine with trace arithmetic. This was checked and is correct: correcting
  both channels to the *same* target makes their minimum-phase components
  converge, so coherence is preserved (0.065 → 0.064 measured).

## 6. Session of 2026-08-02 — the reasoning arc

Recorded in full because several conclusions **reversed earlier ones**, and
the reversals matter more than the conclusions.

### X801 / phase linearisation — RESOLVED, keep it in full

Initially I argued against full linearisation on pre-ringing grounds, using
the filter's own impulse response (32.9% pre-peak energy, −60 dB at 42 ms).
**That was the wrong object to measure.** A linearising filter's pre-ring is
what *cancels* the speaker's lag; what reaches the ear is the product.
Convolving the real room measurements with `Xo801.wav`:

| | pre-peak energy | −40 dB | −60 dB |
|---|---|---|---|
| X801 alone | 32.9% | 3.38 ms | 42.0 ms |
| L0 measured | 17.1% | 0.48 ms | 3.62 ms |
| **L0 × X801** | **6.3%** | 1.38 ms | 14.67 ms |
| **R0 × X801** | **1.8%** | 0.62 ms | 12.56 ms |

Pre-peak energy **falls** below the uncorrected speaker. Phase excursion
200 Hz–12 kHz: L 268.6° → 78.4°, R 341.1° → 70.7°.

> **General lesson: never judge a phase filter by its own impulse response.
> Always test it in the acoustic product.**

Where to see the 801's 23.9 ms lag in REW: **not** in the room measurement's
group delay (modes swing it +34.8 to −8.7 ms), and **not** in Excess Group
Delay (the bass rolloff is minimum phase, which that trace removes by
definition). Import `Xo801.wav` as an impulse response and read its Group
Delay — the mirror image, no room in it. Use no smoothing or 1/6.

### Per-channel vs common EQ — frequency-dependent

Splitting each channel's deviation into common-mode and differential parts:

| band | common RMS | differential RMS | largest \|L−R\| |
|---|---|---|---|
| 20–80 Hz | 5.26 dB | **2.41 dB** | 9.18 dB @ 28.9 Hz |
| 200–500 Hz | 1.28 dB | **1.60 dB** (61%) | 7.06 dB @ 457.8 Hz |
| 2–8 kHz | 1.99 dB | 0.29 dB | 1.37 dB |
| 8–20 kHz | 3.51 dB | 0.17 dB | 0.61 dB |

Per channel below ~300 Hz (real, physical, and a common filter cannot reach
it); common above ~1–2 kHz (nothing differential left, and unequal filters
become an inter-channel level difference — ~1 dB is an audible image pull).

**A claim I made and had to retract:** I said Acourate/Audiolense/Dirac become
"increasingly channel-common above the transition frequency." That is **not
in their documentation and is wrong.** They keep per-channel filters across
the whole range and instead remove position-specific fine structure by other
means — Acourate with frequency-dependent windowing, Dirac by averaging ~9
measurement positions. The lesson: full-range per-channel EQ is safe *if you
earn it* with windowing or spatial averaging. A single-position measurement
(what this tool reads) earns neither.

### Auto EQ — two real bugs found and fixed

Exposed when the user showed a REW per-channel result that reached the target
while the tool left a +3.8 dB bump at 62–87 Hz.

1. **Ranked by raw |error|.** A single channel's largest errors are its own
   deep narrow nulls, which Max boost caps to nothing — so the budget went on
   unfillable holes and never reached the fixable bumps (7 of 12 filters were
   clamped +3 dB boosts). **Fix:** rank by *achievable* gain,
   `min(|err|, limit)`.
2. **Greedy placement overshoots.** Each filter is fitted against its
   predecessors' residual, so a wide cut overshoots its shoulders and later
   filters get spent repairing them. **Fix:** `refine_gains()` — Gauss-Newton
   refit of all gains with f0/Q fixed, on the real chain.

Result: 78.82 → **76.33 dB** peak against an ideal-unlimited 76.25.

Also fixed: `_table_edited` was **off by one**, so editing a filter's
frequency silently rewrote its gain.

### Ringing and RT60 — TWO ERRORS OF MINE, both corrected

**Error 1.** I claimed `2.2·Q/f0` gives a peaking bell's ringing, and that a
+3 dB Q 8 boost at 97 Hz rings 182 ms "matching one-for-one" a measured RT60
rise. **Wrong.** That formula is the decay of a *pure* resonance; a peaking
bell has a zero next to its pole and barely rings at modest gain. Measured to
−60 dB: +3 dB Q8 @97 Hz = **73 ms**; −11 dB Q2.9 @76 Hz = 26 ms; all-pass
43.3/Q2.75 = 85 ms. Only +10 dB approaches the formula. The 97 Hz agreement
was coincidence.

The boost-Q cap (3 for boosts, 8 for cuts) was kept, but **re-justified**:
narrow boosts chase position-dependent nulls and burn headroom. Not ringing.

**Error 2.** I tried to explain an RT60 rise on the user's corrected trace.
The user then clarified the trace was **REW trace arithmetic, not a
re-measurement** — so it contains the *same room*, and the whole filter chain's
energy is gone in 26–85 ms. **A 390 ms rise cannot be physical.** I should
have said so before reaching for explanations.

Status of each candidate mechanism:

- filter ringing — **refuted** (changes T20 by ≤0.01 s)
- low SNR after a cut — plausible, insufficient (a cliff: negligible at 45 dB
  SNR, explodes to 3.2 s at 35 dB)
- all-pass group-delay spread across the analysis band — fits 50 Hz
  (27.5 ms spread), fails 125 Hz (0.3 ms spread, large change still seen)
- trace arithmetic itself producing a synthesised IR with a different noise
  floor and time window — untested, most likely

**Rule: RT60 is only trustworthy on a real re-measurement with the filters in
the signal chain. Prefer the spectrogram over a fitted number. Clarity (C50)
*is* reliable on arithmetic traces** — fixed-window energy ratio, no
noise-floor threshold — **and it barely moved, which is the consistent
reading.**

> Three synthetic decay models failed before this was settled (single sine;
> noise-floor truncation; random-phase mode sums returning T20 = 16 s).
> **Do not trust a synthesised decay test without validating it against a
> known answer.**

### Clarity vs the all-pass ladder

C50 in the 40 Hz third-octave, from the IR recovered off the REW grid:

| setting | group delay | C50 @40 Hz | null fill |
|---|---|---|---|
| no all-pass | — | **5.0 dB** | — |
| 43.3 Hz Q 2.75 | 40 ms | 1.5 dB | +21.1 dB |
| 41.8 Hz Q 1.55 | 24 ms | 2.4 dB | +21.0 dB |
| 42.0 Hz Q 0.40 | 6 ms | 0.6 dB | +21.1 dB |

**Every rung fills the null equally (+21 dB) and every rung costs 3–4 dB of
clarity.** The ranking *between* rows is not trustworthy (at 40 Hz one cycle
is 25 ms and the third-octave filter itself rings ~110 ms, so a 50 ms early
window holds two cycles). A subwoofer gives the same +21 dB at zero group
delay and therefore zero clarity cost.

## 7. Open threads, in priority order

1. **Subwoofer integration.** Now the top item. Fills the 40–47 Hz null by
   acoustic summation at no group-delay and no clarity cost — the same +21 dB
   without the −3 dB. Test placement, level and delay before accepting any
   all-pass at all.
2. **Re-measure RT60 properly** with the filters in the BruteFIR chain, and
   look at the spectrogram rather than a fitted T20. Settle whether the decay
   concern was ever real.
3. **Re-check the all-pass after per-channel EQ.** Small but not exactly zero
   (Δφ moves 8.8° mean; optimum 43.25 → 43.00 Hz).
4. **Possible tool extension:** phase-linearisation design inside
   `allpass_tool.py`, reusing the group-delay and burst-test machinery.
5. **Unanswered question:** in the user's RT60 screenshot a third (black)
   trace appears that is not one of the two ticked (15 yellow, 23 magenta).
   Identify it — if it is another correction variant it is worth comparing.

## 8. Open question for the user

Exporting REW traces **18 (`EQ LxAP`), 19 (`EQ R0`) and 20 (`A plus B`)** as
text would let the tool's per-channel prediction be validated numerically
against the real result — the same check that gave 0.22 dB max against
`L_ap+R0.txt`. That has not been done yet.
