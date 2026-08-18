# All-pass phase-cancellation study tool — user manual

`allpass_tool.py` diagnoses destructive interference between the left and
right channels of a stereo pair, designs the 2nd-order all-pass that fixes
it, and quantifies what that correction costs in timing. It also proposes
parametric EQ toward a house curve, and exports everything for REW, rePhase
and BruteFIR.

---

## 1. Running it

```
cd /home/giacomo/devel/DRC/DRC-185
python3 allpass_tool.py -l L0.txt -r R0.txt -s LR.txt
```

With no arguments it looks for `L0.txt` / `R0.txt` / `LR.txt` in the current
directory. `-s` (the measured L+R) is optional: without it the tool warns and
uses the calculated complex sum instead.

**Dependencies** — nothing exotic, no virtualenv needed:

| package | why | install |
|---|---|---|
| numpy | all the DSP | `pkg install py312-numpy` |
| PySide6 | the GUI (Qt 6) | `pkg install py312-pyside6` |
| pyqtgraph | the plots (pure Python) | `python3.12 -m pip install --user pyqtgraph` |

`audio_io.py` must sit next to `allpass_tool.py`.

> **Name the interpreter version in the pip command.** Qt comes from
> `py312-pyside6`, so the tool must run on **Python 3.12** — but on this host
> every `pip` on `PATH` (`/usr/local/bin/pip`, `~/.local/bin/pip3`) is
> shebanged `#!/usr/local/bin/python3.11`. A bare `pip install --user
> pyqtgraph` installs into `~/.local/lib/python3.11/site-packages`, which
> `python3` (3.12) never reads, and the tool fails with
> `ModuleNotFoundError: No module named 'pyqtgraph'` while pip cheerfully
> reports success. Always spell it `python3.12 -m pip`.
>
> **If 3.12 has no pip.** Only `py311-pip` is packaged here, so
> `python3.12 -m pip` may itself report `No module named pip`. Bootstrap it
> into your home directory — no root, nothing system-wide:
>
> ```
> python3.12 -m ensurepip --user
> python3.12 -m pip install --user pyqtgraph
> ```
>
> `pkg install py312-pip` does the same thing if you would rather have it
> system-wide.

Verify the result rather than trusting pip's exit status — this is the check
that actually matters:

```
python3 -c "import pyqtgraph, PySide6, numpy; print(pyqtgraph.__file__)"
```

The path it prints must contain **`python3.12`**. If it says `python3.11`, or
raises `ModuleNotFoundError`, you have hit the version split above.

**`PYTHONPATH` — leave it out of this.** The tool needs none. Watch out if
your shell sets one for unrelated reasons: on this host it carries
`/usr/local/cumbia-libs/lib/python3.11/site-packages`, a **3.11** directory
that lands on **3.12**'s `sys.path`. Pure-Python packages there will import;
anything with a compiled extension is built against the wrong ABI and will
either fail or shadow a correct 3.12 copy. Harmless for this tool today, but
it is the first thing to unset when an import misbehaves.

**Text size.** Qt 6 hands out a 12 pt UI font by default (Noto Sans, a 22 px
line box at 96 dpi) — about a third larger than a conventional desktop, and
costly in a layout this dense. The tool sets **9 pt** instead. Override with
`--font-size 11`, or at runtime with **Ctrl+plus / Ctrl+minus / Ctrl+0**
(View menu).

**The log folds away.** Both the main window's log and the Auto EQ dialog's
diagnostics sit behind a **Log** / **Details** disclosure button; collapsed
they cost one button's height and the plot takes the rest. `Ctrl+L` toggles
the main log (View → Show log).

> Install pyqtgraph with pip (see above), **not** `pkg install py312-pyqtgraph`: the
> FreeBSD port depends on PyQt5 and drags in the whole Qt5 stack plus scipy,
> matplotlib and h5py. pyqtgraph is binding-agnostic and picks up whichever Qt
> is already imported, and this tool imports PySide6 first, so it always runs
> on Qt6.

---

## 2. The measurements must share a time reference

The entire analysis rests on the **phase difference between L and R**. If the
two sweeps were not measured against a common time reference, that difference
is meaningless — every channel gets an arbitrary time offset, and the tool
would confidently "detect" cancellations that are pure measurement artifact.

Two gates therefore refuse to proceed:

1. **Header check** — if a REW header is present and does not mention a timing
   reference, loading fails with an error telling you to re-measure. (Files
   with no REW header at all only get a warning; there is nothing to check.)
2. **Physical check** — the complex sum of L and R is compared with the
   measured L+R. If the median difference over 20–300 Hz exceeds 3 dB, the set
   is not coherent and loading fails.

On the reference dataset the second check passes at **0.16 dB median**
(3.8 dB max, at the steep edges of the null), which is what a properly
referenced set looks like.

In REW: use an acoustic timing reference (or a loopback) for every sweep in
the set.

---

## 3. The decision framework

Three rules, in order. They are the reason the tool is shaped the way it is.

**1. Establish the cause before choosing the cure.** A dip in the combined
response can be a *level* problem (a null in one channel, a modal
cancellation, a directivity loss) or an *interference* problem (L and R
arriving in opposition). Only the second can be fixed by an all-pass. The tool
separates them by coherence:

```
coherence  G(f) = |L + R| / (|L| + |R|)
```

`G = 1` means the channels add perfectly in phase; `G = 0` means they cancel
completely. A deep dip with `G ≈ 1` is a level problem. A deep dip with
`G ≈ 0` **and** L and R at comparable levels is interference.

**2. EQ first, all-pass last.** Anything that is not interference is EQ's job.
Minimum-phase EQ is the better tool where it applies, because cutting a modal
peak also shortens that mode's decay — you fix the magnitude and the timing at
once. An all-pass fixes nothing in the magnitude domain and always costs
group delay.

**3. Manipulate phase as little as the correction allows.** Group delay and
ringing both grow with the all-pass's Q. Between two filters that fill the
null equally well, the one with less delay is strictly better. This is why the
tool never presents a single "optimal" answer — see §6.

---

## 4. What the analysis reports

On loading, the log records every step and its evidence. On the reference
dataset:

- **Cancellation detected, 40.3–46.5 Hz.** At 43.2 Hz the combination sits
  23.8 dB below the in-phase sum of L and R (coherence 6%) while L and R are
  within 0.1 dB of each other. Comparable levels plus near-zero coherence is
  the signature of destructive interference, not of a level shortfall.
- **f0 evidence: 42.6 Hz** — where the L−R phase difference passes through
  180°, full opposition. The *Evidence: why this f0* page plots exactly this,
  with the ±180° lines marked and the cancellation band shaded, plus the
  coherence collapse underneath. If no exact 180° crossing exists inside the
  region, the coherence minimum is used and the log says so.
- **Which channel** — below f0 the phase difference (L minus R) is about
  +112°, so **L leads**. The all-pass goes on the leading channel: its −180°
  at f0 rotates it back onto the other one. The optimiser independently
  confirms the choice by trying both channels; if it disagrees with the
  phase-lead reading, it says so and follows the optimiser.
- **EQ candidates** — bumps and dips greater than 6 dB from the home curve
  that are *not* interference, each labelled with what to do about it.

---

## 5. The two target curves — do not confuse them

| curve | what it is | what it is for |
|---|---|---|
| **coherent ceiling** (green, dashed) | 1/3-octave power average of \|L\|+\|R\| | the optimiser's reference |
| **home target curve** (grey, dashed) | Flat / Harman / B&K, anchored to your measurement | evaluation, EQ, EQ-candidate detection |

The distinction matters physically. **An all-pass cannot create level.** The
most it can ever recover is the in-phase sum |L|+|R| — that is a hard bound.
Optimising an all-pass against "flat" would chase a target it cannot reach and
would simply drive Q up for nothing. So the all-pass is optimised against the
ceiling, while the home curve judges the result and drives the EQ.

**Home curve options** (Edit → Target home curve):

- **Flat** — 0 dB everywhere.
- **Harman in-room** — +6.6 dB low shelf around 105 Hz, −3.5 dB high shelf
  around 2.5 kHz.
- **B&K 1974** — flat to 400 Hz, then −1 dB/octave.
- **Hide** — removes it from the plots.

**Anchoring.** The shape carries no absolute level, so it is placed at the
measured combination's level over 200 Hz–2 kHz (above the modal region, below
where directivity dominates). That anchor is a **power average**, not an
average of decibels. This is not a detail: on the reference dataset 18.8% of
the midrange lies below 70 dB in narrow nulls (deepest 41 dB), and an
arithmetic dB mean is dragged 1.7 dB low by them (73.3 dB instead of 75.0 dB).
A −41 dB null counts as −41 in a dB mean but as almost nothing in an energy
mean — which is how it sounds.

**Why the curve still looks low.** Even correctly anchored, a jagged response
*reads* higher than its average, because the peaks are wide and the nulls are
narrow spikes that occupy almost no width on screen. The band's real
distribution on this measurement is p25 = 71.2 dB, median = 74.4 dB,
p75 = 76.9 dB. The **Home level** trim in the Display panel exists for this:
the anchor is shown, and you add your own offset in dB. Everything downstream
— the home-deviation column, the live readout, the EQ-candidate detection —
re-evaluates as you move it.

---

## 6. Correction versus timing: the trade-off ladder

There is no single right filter, so the tool does not pretend there is. It
computes, for each amount of correction you are willing to give up, the filter
with the **least group delay** that stays within it. The table in the right
pane is clickable; each row applies instantly and is logged with its full
diagnostics.

Reference dataset, all-pass on L:

| give up | f0 | Q | RMS shortfall | delay at f0 | cycles | T60 |
|---|---|---|---|---|---|---|
| best | 43.3 Hz | 2.75 | 2.11 dB | 40 ms | 1.75 | 139 ms |
| 0.25 dB | 41.8 Hz | 1.55 | 2.35 dB | 24 ms | 0.99 | 81 ms |
| 0.50 dB | 40.3 Hz | 1.15 | 2.60 dB | 18 ms | 0.73 | 63 ms |
| 1.00 dB | 35.8 Hz | 0.65 | 3.11 dB | 12 ms | 0.41 | 40 ms |
| 2.00 dB | 38.3 Hz | 0.40 | 4.11 dB | 7 ms | 0.25 | 23 ms |

Read the second row carefully: **giving up a quarter of a decibel halves the
group delay**. If you care about kick-drum attack more than about the last
fraction of a dB in the null, that is the trade to make. Pick the highest row
whose delay you cannot hear.

**Add correction** puts your own current f0/Q/channel into the same table,
evaluated by the same code, so a manual setting can be compared like for like.
Right-click removes user rows (computed rows are protected).

### The two numbers that quantify the cost

Both are closed forms, verified numerically:

```
group delay at f0   τ(f0) = 4Q / ω0        (this is also its maximum)
tail decay          T60   = 2.2 · Q / f0
```

The T60 formula agrees with Schroeder backward integration of the real biquad
impulse response to within 1% for Q from 1 to 10.

### The smearing verdict

The status block grades group delay at f0 in **cycles**: ≤1 good, 1–2 warning,
2–3 serious, >3 critical. These thresholds are a rule of thumb, not a
measurement, so the underlying numbers are always displayed next to them.

### Seeing it rather than trusting a number

For an all-pass, the raw impulse response is misleading: the tail sits ~48 dB
below the direct impulse and its apparent level is a sampling artifact. The
**Ringing / bass smearing** page instead sends a 1/3-octave Gaussian tone
burst at f0 through the filter and shows it going in and coming out, as an
envelope and as a waveform, annotated with the peak delay, the peak level
change (energy spread over time) and the decay. That is rate-independent and
shows the actual perceptual effect.

---

## 7. Display controls (they never affect the analysis)

Everything in the Display panel changes what you see, never what is computed
or exported. The log says so on every change.

### The legend, the cursor and markers

**Curve visibility is the checkable legend under each plot** — small
colour-coded boxes that wrap onto as many rows as they need (one row at a
typical window width, two if you narrow it). It replaced the side pane's
*Curves* box, which cost a full column of window height for something a
15-pixel strip carries, so the plot keeps the space.

Directly above the legend is the **readout line**, and on the plot a pair of
dashed cross hairs:

| action | effect |
|---|---|
| move the pointer | cross hairs follow it; the readout shows the frequency, the cursor's own value, and **the value of every visible curve at that frequency**, each in its curve's colour |
| **click** | freezes the cross hairs where they are, so you can read the numbers without holding the mouse still. The readout says *(frozen)*. Click again to release |
| **Ctrl+click** | drops a marker |
| **Ctrl+click on a marker** | removes it |
| right-click → *Clear markers* | removes all of them on that plot |

Markers **snap to the nearest visible curve**, so what you get is a real
measured value rather than wherever the pointer happened to be, and each is
labelled with its frequency, its value and which curve it came from. Hide
everything except the one curve you care about and every marker will land on
it. Pages with stacked plots (phase under amplitude, the filter page's three)
carry an independent cursor on each, all reporting into the same line.

### Smoothing

REW's definitions, with REW's **Gaussian kernel**:

| mode | bandwidth |
|---|---|
| 1/48 … 1/1 octave | constant, power (energy) average |
| **Variable** | 1/48 oct below 100 Hz, 1/6 at 1 kHz, 1/3 above 10 kHz |
| **Psychoacoustic** | 1/3 oct below 100 Hz to 1/6 above 1 kHz, **cubic mean** so peaks weigh more than dips |
| **ERB** | one auditory-filter bandwidth (Glasberg & Moore): ~1 octave at 40 Hz, ~1/5 octave at 1 kHz |

The kernel shape matters more than it sounds. A rectangular window's transfer
function is a sinc whose first sidelobe is only −13 dB down, so ripple leaks
straight through it; a Gaussian rolls off monotonically. At identical nominal
bandwidth the Gaussian measures **2.2× smoother**. It is implemented as three
cascaded moving averages (central-limit approximation), scaled so the
equivalent rectangular bandwidth still matches the nominal figure.

**Variable is deliberately almost unsmoothed in the bass** — 1/48 octave at
40 Hz is a 0.58 Hz window, about 1.6 points of a REW 0.366 Hz grid. That is
not a bug: REW recommends Variable *for responses that are to be equalised*,
where you want exact modal detail. For judging balance use **ERB** or 1/1;
for a perceptually weighted view use **Psychoacoustic**.

Peak-to-peak ripple, 40–80 Hz, reference dataset: unsmoothed 36.6 dB,
Variable 36.6 dB, Psychoacoustic 18.1 dB, 1/3 oct 20.0 dB, ERB 5.2 dB.

### Phase smoothing

Phase is smoothed in the **complex domain** — the response itself is
vector-averaged and the angle of the result is taken. Never average wrapped
degrees: the mean across a ±180° jump is garbage. Complex averaging is
coherent averaging, so where reflections randomise the phase the vectors
partially cancel and the wild detail fades toward the trend. Measured effect
at 1/3 octave: high-frequency phase roughness drops from 16.2 to 0.3 degrees
per display point.

### Phase delay removal

`Keep` / `Auto` / `Manual`, in milliseconds. A bulk delay only makes the phase
trace spiral; removing it leaves the **excess phase**, which is what carries
the information about the speaker and the room. It is applied before the
smoothing, so the two reinforce each other (less rotation, less vector
cancellation).

The estimator uses **coherent alignment** — it finds the τ maximising
|Σ H(f)·e^{j2πfτ}| — and never unwraps. This is not fussiness: the textbook
unwrapped-phase-slope fit reports **5.2 ms** on this dataset, where the
impulse response says **0**, because room-measurement phase wraps
unpredictably in the high-frequency noise floor and `unwrap` picks the wrong
branch. Coherent alignment is exact to under a microsecond on synthetic
delays from 0 to ±20 ms and returns 0.08 ms here.

**The L−R phase difference is deliberately exempt.** A delay common to both
channels cancels identically in it, so removing one would inject a fake tilt
into the one curve your f0 decision rests on.

---

## 8. Auto EQ

**Edit → Auto EQ… (Ctrl+E).** Greedy parametric fit toward the home curve
using RBJ/REW analogue peaking bells: find the largest remaining deviation,
estimate its Q from the half-gain bandwidth, place a bell, subtract, repeat.

### Guard rails

- **Never EQ the interference regions** (on by default). A cancellation
  between L and R is not a level problem; EQ cannot fill it and boosting there
  only burns headroom. Turn the guard off and the fitter immediately places
  filters in the null — which is exactly what you do not want.
- **Max boost defaults to +3 dB**; set it to 0 for cuts only. Boosting a room
  mode lengthens its decay even when the magnitude looks right afterwards.
- **Fits on smoothed data** (default 1/6 octave), so it does not chase narrow
  nulls that move when the microphone moves.
- The summary states how much level to give back if there are boosts.

### Order and channel

**Order in the signal chain is free.** All-pass and EQ are LTI filters and
commute exactly (verified to 6.6 × 10⁻¹⁶ relative).

**Which channel each acts on is what matters.**

- *Both channels (common)* — the EQ phase shift is identical in L and R and
  cancels exactly in their difference. Measured change in the L−R phase
  difference: 5.7 × 10⁻¹⁴ degrees; in coherence: 6.7 × 10⁻¹⁶. It cannot
  disturb the all-pass, full stop.
- *L and R separately* — the usual REW technique, and it is sound. Correcting
  both channels toward the **same** home curve makes their minimum-phase
  components converge, and since minimum phase means phase follows magnitude,
  their phase converges too. Measured on the reference dataset: the L−R phase
  difference moves 8.8° mean (59° peak), coherence in the null goes 0.065 →
  0.064 (unchanged), and the optimal all-pass moves from f0 43.25/Q 2.75 to
  43.00/Q 2.75. What EQ cannot touch is the excess phase — which is precisely
  the all-pass's job.

  It is not mathematically zero the way common EQ is, so the dialog measures
  and reports the actual effect every time. Re-check the all-pass afterwards.

#### How the fit works, and two things it gets right on purpose

The placement is greedy — find the largest remaining error, put one bell on
it, subtract, repeat — but with two corrections that matter:

**It ranks by what a filter can achieve, not by the raw error.** A single
channel's largest deviations are its own deep narrow nulls, and those are
capped by *Max boost* (often to nothing). Ranking on raw error spends the
whole filter budget on holes it is not allowed to fill and never reaches the
bumps a cut could actually remove. Measured on the reference data, ranking
naively left **7 of 12 per-channel filters as clamped +3 dB boosts** and a
**+3.8 dB bump standing at 62–87 Hz**; ranking by achievable gain cuts that
to 3 of 12 and **+1.3 dB**.

**It re-solves every gain at once after placement.** The greedy pass fits
each filter against the error left by its predecessors, so a wide cut
overshoots on its shoulders and a later filter gets spent putting them back.
A Gauss-Newton refit with the frequencies and Qs held fixed (on the real
filter chain, since a peaking filter's dB response is only roughly
proportional to its gain) lets every filter be chosen knowing what the
others do, and the self-repair filters stop being needed.

Together these bring a 6-filters-per-channel fit to within 0.1 dB of what
*unlimited* per-channel flattening would achieve in the problem band.

#### Ringing: the column that stops you making the room worse

The filter table's last column is **rings** — the filter's own T60, `2.2·Q/f0`.
The sign is the point:

- a **cut** at a room mode is that mode's inverse, so it **takes decay away**.
  Shown green with a minus sign. A long number here is a *good* thing.
- a **boost is a resonance** and **adds** that much decay. Shown amber, or red
  past 150 ms.

**The column shows `2.2·Q/f0`, which is an upper bound, not the real
figure.** That formula is the decay of a *pure* resonance. A peaking bell has
a zero sitting next to its pole, and the two nearly cancel at modest gains, so
a mild bell rings far less than the formula says. Measured to −60 dB of the
filter's own energy:

| filter | 2.2·Q/f0 | actually rings |
|---|---|---|
| +3 dB Q 8 @ 97 Hz | 181 ms | **73 ms** |
| +3 dB Q 3 @ 97 Hz | 68 ms | 33 ms |
| +6 dB Q 8 @ 97 Hz | 181 ms | 118 ms |
| +10 dB Q 8 @ 97 Hz | 181 ms | 180 ms |
| −11 dB Q 2.9 @ 76 Hz | 84 ms | 26 ms |
| all-pass 43.3 Hz Q 2.75 | 140 ms | 85 ms |

Only large gains approach the formula. Read the column as "worst case", and
compare filters with it rather than trusting the absolute number.

**Q on boosts is capped at 3** while cuts keep the full range up to 8. The
honest justification is *not* that a mild boost rings badly — it doesn't. It
is that a narrow boost chases a deep narrow null, and such nulls are the most
microphone-position-dependent feature in the room: you burn headroom and add
what ringing there is to fix something that moves when you move your head.
The cap costs 0.36 dB of flatness on the reference data.

If you care more about decay than the last dB, set **Max boost to 0** (cuts
only). On the reference data that costs a further 0.33 dB in the problem band
and leaves a filter set where every filter shortens the decay.

#### Which of the two should you use?

Neither, globally — **the right answer depends on frequency**, which is why the
control sits next to the band limits. Split each channel's deviation from its
own level into a *common-mode* part (what one shared filter can reach) and a
*differential* part (what only separate filters can reach), and the reference
dataset says:

| band | common RMS | differential RMS | differential share | largest \|L−R\| |
|---|---|---|---|---|
| 20–80 Hz | 5.26 dB | 2.41 dB | 17% | 9.18 dB @ 28.9 Hz |
| 80–200 Hz | 3.23 dB | 1.28 dB | 14% | 5.45 dB @ 96.7 Hz |
| 200–500 Hz | 1.28 dB | 1.60 dB | 61% | 7.06 dB @ 457.8 Hz |
| 500–2 kHz | 1.64 dB | 0.83 dB | 21% | 4.68 dB |
| 2–8 kHz | 1.99 dB | 0.29 dB | 2% | 1.37 dB |
| 8–20 kHz | 3.51 dB | 0.17 dB | 0% | 0.61 dB |

Equivalently, what an *ideal, unlimited* common filter must leave behind:
2.41 dB RMS from 20–80 Hz, 1.28 from 80–200, 1.60 from 200–500, but only
0.22 dB above 2 kHz.

- **Below ~300 Hz — separately.** The differential is large and physical: L and
  R stand at different distances from the boundaries and couple to the modes
  differently. That is a property of the installation, not of the microphone.
  A common filter cannot reach it. Imaging is not at risk, because below a few
  hundred Hz localization is ITD- and room-dominated.
- **300 Hz – 1 kHz — separately, but well smoothed** (1/6 or 1/3 octave). This
  is the awkward band: the differential share peaks here (61%), yet its fine
  structure is already partly position-specific. Correct the broad trend only.
- **Above ~1–2 kHz — common, or leave it alone.** There is almost nothing
  differential left (0.29 → 0.17 dB RMS). Separate fits up here chase
  measurement noise at one microphone position, and every dB by which the L
  filter differs from the R filter becomes an inter-channel level difference
  at the frequencies the ear uses for lateral localization — roughly 1 dB of
  ILD is an audible image pull. You would be trading nothing for a smeared
  centre image.

**How the commercial packages handle this** (checked against their
documentation — an earlier draft of this manual claimed they become
"increasingly channel-common" above the transition frequency, which is
wrong):

They keep **per-channel filters across the whole range**. What they do
instead is remove the position-specific fine structure by other means, so
that a per-channel fit has nothing spurious left to chase:

- **Acourate** applies *frequency-dependent windowing*: above the transition
  (~500 Hz) the correction sees only the direct sound, so the high-frequency
  correction is inherently broad and mild rather than a fit to the measured
  fine structure.
- **Dirac Live** measures ~9 positions and builds its model from their
  average, explicitly "avoiding corrections that might improve response at
  one location but degrade it elsewhere."

The distinction matters for how you use this tool. Those protections are
what make full-range per-channel EQ safe; a single-position measurement,
which is what this tool reads, has neither. So the guidance above stands,
but the better fix above ~1 kHz is not to make the filters common — it is to
*earn* the right to per-channel filters by measuring several positions and
averaging, or failing that by smoothing heavily. Common EQ up there is the
fallback for when you only have one position, not the ideal.

The dialog therefore defaults to **L and R separately**, because its default
band is 20–500 Hz. If you widen the band into the treble, switch to common —
or better, run two passes with different settings.

**Seeing it.** In the Auto EQ dialog, tick **Show L and R separately** next to
the legend. On the main window's amplitude and phase pages, the curve list
carries *L corrected (own filters)* and *R corrected (own filters)* alongside
*L+R corrected*. Both are off by default and computed only while visible.
Each shows one channel carrying exactly what its own amplifier will receive:
its share of the EQ (common filters plus the ones addressed to it) and, on
the target channel only, the all-pass. Switch them on with the raw *L* and
*R* curves to read before-and-after per channel, and compare against the
summed curve to see how the two combine.

**Per-channel EQ will not fix an interference null, and must not try.** At the
reference dataset's 42 Hz null L and R match within 0.1 dB: it is a
differential *phase* problem, not a differential magnitude problem. This is
what the "Never EQ the interference regions" guard is for. Leave it on.

**Design order is all-pass first, then EQ**, because the all-pass changes the
magnitude the EQ must correct, but common EQ changes nothing the all-pass
depends on. A one-way dependency: one pass converges, no iteration.

The exported filter files carry the channel placement in their header, because
applying a per-channel set to the wrong channel is a silent, expensive
mistake — measured at 31–36° of relative phase error.

---

## 9. Import and export

**File → Import impulse response** reads WAV (PCM 8/16/24/32, IEEE float
32/64), RAW (format auto-detected) and TXT. Import as a filter to compare
(overlaid on the All-pass filter page) or as a reference curve. An impulse
response cannot replace a calibrated SPL measurement — it carries no absolute
level — so it is always added as a reference.

**File → Export** writes:

- the all-pass as WAV / RAW / TXT, any of float32/64 or int32/24/16, at any
  rate, **causal from t = 0** so it adds no latency;
- REW-format frequency responses of the all-pass, the corrected channel, the
  corrected and uncorrected sums, the coherent ceiling and the home curve;
- (from the Auto EQ dialog) REW "Filter Settings" text, one file per channel
  in per-channel mode.

The tap-count suggestion is sized from the filter's own T60, and the dialog
warns if the chosen length would truncate the tail.

### Sample rate

The analysis is rate-independent; only generated impulse responses care. The
default working rate is **48 kHz** (matches rePhase's text export and REW
import). Select **192 kHz** for the BruteFIR chain in this project — the
biquad coefficients are computed directly at whatever rate you choose, so it
is exact, never resampled.

### Verified interoperability

- The generated all-pass reproduces a rePhase "normal" all-pass export
  (`ap_L_42p5_Q2p5.txt`) to within **5 × 10⁻⁵ per tap** at 48 kHz. rePhase's
  all-pass is an RBJ all-pass biquad.
- The tool's predicted corrected sum matches REW's own trace arithmetic
  (`L_ap+R0.txt`) to within **0.22 dB** (median 0.01 dB) over 25–100 Hz. The
  whole chain — model → filter → acoustic sum — is verified against
  measurement.
- rePhase file formats found in this project: 48 kHz exports are **IEEE
  float64** WAV, 131072 taps, centred; 192 kHz exports are **int32 PCM** WAV
  plus a headerless **int32 little-endian** `.raw`, 524289 taps.

---

## 10. Reference

### The all-pass model

rePhase "normal" convention, second order:

```
H(s) = (s² − s/Q + 1) / (s² + s/Q + 1),      s = j·f/f0
```

Magnitude is exactly 1 at every frequency; phase runs 0 → −360° and passes
through **−180° exactly at f0**.

### Pages

| page | shows |
|---|---|
| Amplitude | L, R, measured and calculated L+R, corrected sum, ceiling, home curve, EQ result |
| Phase | the same responses' phase |
| Evidence: why this f0 | L−R phase difference against ±180°, and the coherence collapse |
| All-pass filter | magnitude (flat), phase (−180° at f0 marked), group delay with its peak |
| Ringing / bass smearing | tone-burst in/out, envelope and waveform |
| L, R, L+R measured, L+R calculated, L+R corrected | amplitude and phase of one response each |

Curve visibility, the plot selector, overlays and the filter controls all live
in the right-hand pane. Interference regions are shaded red, EQ candidates
amber; both toggle independently.

### Performance

Dragging a slider recomputes and repaints in ~20–30 ms. If it ever feels
sluggish again, the cause is almost certainly painting, not arithmetic — the
DSP costs about 2.5 ms. Curves are decimated to a log-spaced min/max envelope
(~1300 points from 65495, preserving narrow features), phase gets a denser
grid (320 points/octave — on a coarse grid fast high-frequency rotation
exceeds 180° per point and the wrap-break blanks whole octaves), pens are
1 px, and during a drag every pen drops to a non-antialiased hairline.
Antialiased pens wider than 1 px lose Qt's fast path and cost about 8× more.

---

## 11. Working with REW alongside this tool

This tool does not replace REW; it does the one thing REW has no view for —
deciding whether the L+R null is interference or level, and sizing the
all-pass. Everything else is REW's job, and REW stays the arbiter, because
REW measures and this tool only predicts.

### The loop

1. **Measure in REW.** L alone, R alone, and L+R. **Every measurement must
   use an acoustic timing reference** — the tool refuses to load files whose
   REW header does not say so, because without a shared clock the L−R phase
   difference is meaningless and every conclusion below is void.
2. **Export as text** (File → Export → *Export measurement as text*), keeping
   the phase column. That is the tool's input.
3. **Design** the all-pass and the EQ here.
4. **Export** the filters as REW *Filter Settings* text and the all-pass as
   WAV / RAW / TXT.
5. **Verify in REW** — see below. Do not trust step 3 until step 5 agrees.
6. **Re-measure** the corrected system and start again if needed.

### Verifying a prediction in REW (trace arithmetic)

This is the step that keeps everyone honest, and it is how every number in
this manual was checked.

- **Apply the all-pass to a channel:** import the exported all-pass impulse
  response as a measurement, then *All SPL → Trace arithmetic → A × B* with
  A = the channel, B = the all-pass. That is your `LxAP`.
- **Sum two channels:** *Trace arithmetic → A + B*. This is a complex sum, the
  same operation the tool performs, so the results are directly comparable.
- **Apply EQ per channel first, then sum**, in that order — per-channel EQ
  acts before the summation and cannot be applied to an already-summed trace.

Measured agreement on the reference dataset: the tool's predicted corrected
L+R matched REW's own trace arithmetic (`L_ap+R0.txt`) to **0.22 dB maximum
and 0.01 dB median over 25–100 Hz**.

### Three traps when reading REW graphs after correction

**1. Group delay explodes at a cancellation, and that is an artifact.**
Where L and R cancel, |H| → 0, phase is undefined, and group delay — a
derivative of phase — goes to infinity. The huge spike at the null in the
*uncorrected* trace is not a defect the correction removed; it is the
measurement having nothing to work with. Its *absence* after correction is
the real result: the null is filled, so phase is defined again.

**2. Group delay below the passband is noise, not data.** Below about 20 Hz
the speaker has no output, the sweep has no signal-to-noise ratio, and group
delay is the noisiest quantity you can plot. Excursions of tens of
milliseconds down there mean nothing. Read group delay from ~20 Hz up.

**3. Do not judge RT60 on a trace-arithmetic result.** This one cost this
project a wrong conclusion, so it is worth stating carefully.

A corrected trace built with trace arithmetic contains **the same room** as
the measurement it came from — the decay cannot physically have changed. The
whole filter chain's own energy is gone in 26–85 ms (measured), so it cannot
add hundreds of milliseconds either. Yet on this project the arithmetic
result read **0.53 → 0.92 s at 50 Hz and 0.34 → 0.60 s at 125 Hz**.

Candidate mechanisms, and their status:

- *Filter ringing* — **refuted.** Convolving a room mode of the measured
  decay with the filter chain changes T20 by ≤0.01 s.
- *Low SNR after a cut* — **plausible but not sufficient.** A cut lowers
  signal and noise together in-band, and the artifact is a cliff: at 45 dB
  SNR an 11 dB cut biases T20 by 0.01 s, at 35 dB it explodes to 3.2 s.
- *All-pass group delay spread across the analysis band* — **fits 50 Hz,
  fails 125 Hz.** The spread is 27.5 ms across the 50 Hz third-octave but
  only 0.3 ms at 125 Hz, where a large change was still seen.
- *Trace arithmetic itself* — the result is a **synthesised** measurement
  whose impulse response is reconstructed, with a different noise floor and
  time window from a real one. RT60 estimation is sensitive to exactly those.

No mechanism tested here accounts for all the bands. The practical rule
follows regardless: **RT60 is only trustworthy on a real measurement with the
filters in the signal chain.** Re-measure. And prefer the spectrogram or
waterfall, where you can *see* whether something rings, over a fitted number
that can be wrong without looking wrong.

Two more REW settings that change what you conclude:

- **Judge EQ results at 1/3 octave or ERB smoothing, never Variable or None.**
  Variable is 1/48 octave below 100 Hz — deliberately almost unsmoothed,
  because REW intends it for *finding* what to EQ, not for judging the
  result. The same corrected response reads 0.85 dB peak-to-peak under ERB
  and 6.03 dB under Variable. Nothing changed but the ruler.
- **Read group delay with no smoothing or 1/6.** At 1/3 octave the 801's
  20 Hz group delay reads 17.75 ms instead of its true 23.90 ms.

### Where the tool deliberately differs from REW's own EQ

| | this tool | REW auto EQ |
|---|---|---|
| measurements without a timing reference | **refused** | accepted |
| EQ inside an interference null | **never** (a cancellation is not a level problem) | will try |
| Q on boost filters | **capped at 3** (a narrow boost rings) | uncapped |
| gains after placement | re-solved jointly | as placed |
| target | coherent ceiling for the optimiser, home curve for evaluation | one target curve |

### Agreements verified numerically

| what | agreement |
|---|---|
| all-pass vs rePhase's `ap_L_42p5_Q2p5.txt` | 5 × 10⁻⁵ per tap at 48 kHz |
| predicted corrected L+R vs REW trace arithmetic | 0.22 dB max, 0.01 dB median (25–100 Hz) |
| smoothing kernel | Gaussian, as REW (not a boxcar — measured 2.2× difference) |
| peaking EQ | RBJ / REW analogue form |
| per-channel EQ then sum | reproduces the REW workflow: 28.6 → 10.0 dB peak-to-peak, 20–200 Hz |
| all-pass group delay at f0 | 4Q/ω₀, and T60 = 2.2Q/f0 within 1% of Schroeder integration |
