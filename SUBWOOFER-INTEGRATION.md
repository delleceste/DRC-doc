# Subwoofer integration — what the measurements say, and what to do

Working notes, 2026-08-13. Everything here is measured from files in this
repository or its siblings; where something is an inference rather than a
measurement it is labelled as such.

---

## 1. The problem subs would solve: 42 Hz is the room, not the speaker

At roughly 180–185 cm from the front wall, **three different loudspeakers over
nine years put a hole in the same place**:

| configuration | date | dip in 33–50 Hz | rms 22–200 Hz | peak-peak |
|---|---|---|---|---|
| B&W 803 D2, no subs | Jan 2017 | **−25.0 dB @ 40 Hz** | 8.06 | 33.07 |
| Nautilus 801, no subs | Feb 2023 | **−28.3 dB @ 43 Hz** | 8.35 | 36.94 |
| Nautilus 801, no subs | Oct 2024 | **−23.6 dB @ 42 Hz** | 7.59 | 32.35 |

*(L+R at the seat, each normalised to its own 100–250 Hz level.)*

Different cabinets, different drivers, different years, same hole to within
3 Hz. **This is a property of the room and the listening position**, not of any
speaker, and no amount of loudspeaker choice will change it.

Two mechanisms overlap there:

- **SBIR** — front-wall reflection. `f_null = c / 4d`, so 1.85 m gives
  **46.4 Hz**.
- **An L/R cancellation** — at 185 cm the two channels arrive **142° apart** at
  40 Hz and subtract. Decomposed at 41 Hz: each channel already −6.0 dB from
  SBIR, then a further −7.3 dB from mutual cancellation, total −13.1 dB.

Moving the speakers to **120 cm** pushes the SBIR null to **71.5 Hz**, which is
why the current configuration measures better — the hole moved to a frequency
where it is shallower and better damped. It did not go away; it became the
74 Hz feature that the correction filter still fights.

---

## 2. What two subwoofers actually did about it

Measured, 2017–2018: B&W 803 D2 plus **two B&W DB3D** sealed subs.

| configuration | dip 33–50 Hz | rms 22–200 Hz | peak-peak |
|---|---|---|---|
| 803 D2 alone | **−25.0 dB** | 8.06 | 33.07 |
| \+ 2 subs, 70 cm from the wall | **−5.3 dB** | 3.91 | 15.70 |
| \+ 2 subs, against the wall | **−1.1 dB** | 4.69 | 20.71 |

**A 25 dB hole became 1 dB.** Overall unevenness halved. The 2018 note in the
user's own hand reads *"test with subs attached to the front wall. You can see
a gain around 40 Hz"* — followed by *"but a major overall irregular response"*,
which the numbers also show: the wall position introduced a **−5.4 dB dip near
125 Hz** that the 70 cm position did not have.

**Why the wall position wins at 42 Hz.** SBIR null frequency is set by distance
from the boundary:

| source | distance | first null |
|---|---|---|
| mains at 185 cm | 1.85 m | 46 Hz |
| mains at 120 cm | 1.20 m | 71 Hz |
| sub at 70 cm | 0.70 m | 122 Hz |
| **sub at 30 cm** | 0.30 m | **286 Hz** |
| sub against the wall | 0.05 m | 1715 Hz |

A sub 30 cm from the wall has **no boundary null in its passband at all**. The
mains cannot do this because they need to be out in the room for imaging; a sub
does not image, so it is free to sit where the interference is harmless.

> ### The single most important consequence
> The 2017 advantage came from having **four bass sources instead of two**, not
> from the 803 D2 being a better loudspeaker. Distributed sources excite room
> modes differently and partially fill each other's nulls. The Nautilus 801s
> with two subs would collect the same benefit.

---

## 3. What the 2017 measurements cannot tell us

**Nothing about timing.** Two independent reasons, either sufficient:

1. **Every one of the eleven files says `With no timing reference`.** A pure
   delay is a linear phase term, and without a reference REW has no anchor for
   it — t=0 comes from the impulse peak, which is arbitrary with respect to
   when the sweep started.
2. **All eleven are full-system measurements** — mains and subs together. Even
   with a perfect timing reference you cannot extract the sub/main offset from
   a combined measurement. The two contributions are already summed.

What *does* survive a missing timing reference: **group-delay variation**,
because a constant delay adds a constant to group delay and cancels when you
reference to a midband median. The 2017 files carry variation of comparable
quality to current measurements (IQR 28.1 ms vs 25.9 ms), so decay, ringing and
resonance behaviour are all legitimately readable from them.

---

## 4. Where things stand today — the honest comparison

**Magnitude at the seat, 20–200 Hz:**

| configuration | rms dev | peak-peak | ripple |
|---|---|---|---|
| 2017 803 D2 + 2 subs @ 70 cm | 4.06 | 15.74 | 2.30 |
| 2017 803 D2 + 2 subs @ wall | 4.93 | 20.71 | 2.65 |
| 185 cm 801, no sub, no filter | 7.46 | 32.28 | 4.55 |
| 120 cm 801, before filter | 3.72 | 16.02 | 2.35 |
| **120 cm 801 + 8-cycle filter** | **2.97** | **10.30** | **2.00** |

**Group-delay excursion at the seat, 20–200 Hz:**

| configuration | worst | at | rms |
|---|---|---|---|
| **2017 803 D2 + 2 subs @ 70 cm** | **+53.3 ms** | 28 Hz | 23.9 |
| 2017 803 D2 + 2 subs @ wall | +57.2 ms | 24 Hz | 24.1 |
| 185 cm 801, no sub, no filter | +89.8 ms | 44 Hz | 25.3 |
| 185 cm 801 + allpass on L | +60.6 ms | 44 Hz | 21.9 |
| 120 cm 801, before filter | +70.7 ms | 63 Hz | 23.4 |
| 120 cm 801 + 8-cycle filter | +79.2 ms | 63 Hz | 26.3 |

**Read these together.** Today's system is the best of everything measured on
**magnitude** — better than 2017 with two subs, on all three measures. The 2017
system was better on **group delay**, by about 25 ms.

That is exactly the trade you would predict: **extra sources fill nulls, which
helps group delay; correction flattens magnitude.** Neither system dominates,
and the 2017 result is a statement about source count, not about the 803 D2.

Note also where the worst group delay sits. For both 801 configurations it lands
on the **front-wall SBIR frequency** — 44 Hz against a predicted 46, and 63 Hz
on the shoulder of 71.5. In 2017 that peak is simply absent and the worst case
falls back to the lowest room mode at 24–28 Hz. That is the signature of
boundary cancellation being removed rather than corrected.

---

## 5. The complication the 801 brings

**The Nautilus 801 is harder to integrate with subs than the 803 D2 was.** The
803 D2 is roughly −6 dB near 32 Hz; the N801 reaches into the low twenties.
Running full-range, the 801 is still producing serious output across the sub's
entire band, so the overlap is far wider and there is more opportunity for
interference.

This is a real difficulty and it is the main argument for a **high-pass on the
mains** — which is the thing the current DAC cannot provide.

---

## 6. Option A — what is possible with the DAC8 **Stereo**

Two channels out, so **no digital crossover**. The realistic configuration is:

```
mains: full range, untouched
subs:  their own low-pass, level, phase/delay, polarity
```

**Do not use a subwoofer's line-level high-pass output to feed the amplifiers.**
It inserts an op-amp stage and a fixed 80 Hz / 12 dB per octave filter in front
of the 801s. Leaving the main signal path untouched is worth more than the
excursion relief.

### 6.1 The correction workflow is unchanged

Measure **mains + subs together** and correct that combined response with the
existing chain — one stereo filter, the same Steps 2–9. Nothing about the
procedure changes; the divisor simply describes a different system.

**What the filter cannot fix is a cancellation between sub and mains**, for the
same reason it cannot fix the SBIR null: a dip makes the filter want to boost,
and max gain 0 dB clamps it. **The phase alignment must be right before you
measure for the filter.**

### 6.2 The delay asymmetry — the hard constraint

**A subwoofer can only be delayed, never advanced.** With no processor in the
main path, if the sub arrives late the obvious correction is unavailable.

| sub position | path from seat | arrival vs mains |
|---|---|---|
| front corner, 0.3 m from wall | 4.24 m | **+4.5 ms late** |
| beside a main speaker | 3.50 m | +2.4 ms late |
| same distance as mains | 2.69 m | 0.0 |
| beside the sofa | 1.50 m | **−3.5 ms early** |

Add the sub's own group delay near its corner — 2–6 ms sealed, 10–20 ms ported
— and **a front-corner sub is typically 7–25 ms late in total.**

Phase error that produces at the crossover:

| offset | 40 Hz | 60 Hz | **80 Hz** | 100 Hz |
|---|---|---|---|---|
| 2 ms | 29° | 43° | 58° | 72° |
| 4 ms | 58° | 86° | 115° | 144° |
| **6 ms** | 86° | 130° | **173°** | 216° |
| 12 ms | 173° | 259° | 346° | 72° |

6 ms is 173° at 80 Hz — near-total cancellation exactly where the two sources
overlap.

### 6.3 Two ways round it

**Wrap around to the next period.** Add delay until the sub is one full cycle
late instead of a fraction of one. It works, but only near one frequency:

| aligned at | 40 Hz | 50 Hz | 60 Hz | 70 Hz | 80 Hz |
|---|---|---|---|---|---|
| 50 Hz | 288° | **0°** | 72° | 144° | 216° |
| 60 Hz | 240° | 300° | **0°** | 60° | 120° |
| 70 Hz | 206° | 257° | 309° | **0°** | 51° |

Aligned at 60 Hz you are still within 72° at 50 and 60° at 70 — acceptable
across a narrow band, hopeless across a wide one. **So use a steep low-pass on
the sub**, keeping the overlap tight enough that alignment only has to hold
where both sources actually contribute.

**Or place the sub closer than the mains so it arrives early**, then delay it
into alignment properly — which gives broadband alignment rather than
one-frequency alignment. That means beside the sofa rather than at the front
wall. It costs boundary loading and makes the sub easier to localise, but it is
the only route to a *correct* time alignment with this hardware.

**Also try polarity inversion.** 180° is free, and a polarity flip plus a small
delay often beats a large delay.

### 6.4 Best-effort starting procedure

1. Subs **against the front wall** (or as close as the furniture allows —
   30 cm puts their own SBIR null at 286 Hz, out of the way).
2. Sub low-pass as **steep as the unit offers**, corner around **60 Hz**.
3. Measure **mains alone**, **subs alone**, and **both together**, all with an
   **acoustic timing reference**. This is the step that was missing in 2017.
4. Read the offset from the two impulse peaks. If the sub is early, set that
   delay directly. If late, set `(period at crossover) − offset` to wrap, and
   test polarity both ways.
5. Verify with **Trace Arithmetic `A + B`** against the measured sum. On the
   185 cm data a computed complex sum matched a measured `L+R` to **0.50 dB
   rms over 20–250 Hz**, so the prediction is trustworthy enough to tune
   against and confirm rather than search physically.
6. Only then measure the combined system and build the correction filter.

---

## 7. Option B — what an 8-channel DAC would unlock

With multichannel output the crossover moves into BruteFIR, and the whole
problem changes character.

```
L → steep FIR high-pass → main L        L → FIR low-pass → sub L
R → steep FIR high-pass → main R        R → FIR low-pass → sub R
```

**A 48 dB/oct FIR high-pass at 55 Hz** puts the mains ~20 dB down at 46 Hz —
enough that the null stops mattering — while the 801s keep everything from
55 Hz up. You give up about a third of an octave, not the octave and a half
that an 80 Hz bass-management crossover would take.

That slope is not available from an analogue crossover, where 24 dB/oct at
55 Hz still leaves meaningful output at 46 Hz.

**What this buys:**

- The 46 Hz (or 74 Hz) null stops existing rather than being corrected around.
- The overlap becomes narrow enough to align properly instead of negotiating.
- Correction splits into two easier problems: subs below 55–60 Hz, mains above.
- No mono summing, so interchannel correlation is preserved (see §8).
- The crossover is phase-coherent by construction because both halves come out
  of the same FIR design.

**MSO** (Multi-Sub Optimizer, free) is the right tool for the sub half — it
optimises placement, delay and EQ across multiple subs against the summed
response at the seats.

**What it does not fix:** room modes remain, everything above the crossover is
still the mains' problem — and that is where most of the current filter's work
happens, since the 100–160 Hz lump was 9.4 dB.

---

## 8. Does mono summing cost anything? Measured: almost nothing

A single sub fed from L+R sums the channels, which discards the difference
signal. Measured across **352 tracks** of this library (loudest 45 s of each,
band-limited 20–80 Hz):

| genre | n | median correlation r |
|---|---|---|
| Classica | 134 | +0.65 |
| Jazz | 60 | +0.99 |
| Pop Rock | 50 | +0.96 |
| Elettronica | 65 | +0.96 |
| Progressive | 22 | +0.92 |
| Hard Rock | 15 | +0.86 |
| **ALL** | **346** | **+0.84** |

Restricted to tracks that actually have bass (>3 % of energy below 80 Hz,
n=180), the median is **+0.95**. The genre with by far the most low-frequency
content — Elettronica at 29 % of total energy — is also one of the most
correlated.

**Mono summing loses energy in only 11 of 352 tracks (3 %)**, median +2.60 dB
against the +3.01 dB ideal. Worst cases are Shostakovich's 1st & 15th
(−2.43 dB, r = −0.57) and Bartók's Concerto for Orchestra (−1.54 dB).

**Conclusion: a single mono sub is acceptable.** Stereo subs are better and
avoid the question entirely, but this is not a reason to prefer them.

**Panning is a non-issue**: median L−R balance below 80 Hz is −0.04 dB, within
±3 dB on 80 % of tracks. Low frequencies radiate omnidirectionally into both
microphones of any pair, so bass is never hard-panned regardless of where the
double basses sit.

---

## 9. Decision summary

| | Option A — stereo DAC | Option B — 8-channel DAC |
|---|---|---|
| mains | full range | steep FIR high-pass at ~55 Hz |
| overlap | wide, 20–80 Hz | narrow, ~40–75 Hz |
| alignment | wrap-around only, one frequency | true, broadband |
| sub placement | forced trade: wall (late, uncorrectable) vs near-seat (early, correctable) | free — wall, because delay is available |
| correction | one filter on the combined response | two easier problems |
| mono summing | required if one sub | not required |
| cost | subs only | subs + DAC8 Pro |
| expected result | recovers most of the 42 Hz hole; crossover region fiddly | clean |

**Recommended order:**

1. **Borrow one sub and take the four measurements** (mains alone, sub alone,
   both together at the computed delay, both together at a deliberately wrong
   delay) at the **185 cm** position, with a timing reference. That answers the
   whole question for one afternoon and no purchase. The fourth measurement
   shows how sharp the optimum is, which tells you how much placement tolerance
   you have.
2. If it works, buy subs and run **Option A** properly.
3. Add the multichannel DAC when the crossover region proves to be the limit —
   which, on the 2017 evidence (the −5.4 dB dip at 125 Hz with the subs at the
   wall), it will.

**Note on the 185 vs 120 question.** Subs suit the 185 cm position *better*
than 120 cm, because at 185 the hole sits at 41–46 Hz where a subwoofer
naturally operates, while at 120 cm it moved to 71.5 Hz where a sub crossed low
enough to stay unlocalised is already rolling off. If subs are going in,
**moving the speakers back to 185 cm is worth reconsidering** — you would be
handing the sub a problem it is good at.

---

## Appendix — files behind these numbers

| what | where |
|---|---|
| 803 D2 alone, Jan 2017 | `../803D2/txts/gen 29 18_15_42.txt` (L+R) |
| 803 D2 + 2 DB3D, Dec 2017 / Oct 2018 | `../803D2/2017-subs/*.txt` (11 files, all L+R, none with a timing reference) |
| room photo, 803 D2 + DB3D | `../803D2/2017-subs/BW803D2+DB3D.jpg` |
| N801 at 185 cm, Feb 2023 | `../801N.first.measurements/txts/LEFT+RIGHT Feb 5.txt` |
| N801 at 185 cm, Oct 2024 | `L0.txt`, `R0.txt`, `LR.txt` in this directory |
| N801 at 120 cm, Aug 2026 | `../DRC-120.blue/120.blue.Rscreen.txts/` |
