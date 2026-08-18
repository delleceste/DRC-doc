# DRC-doc

Guides, studies and tooling for the room correction of a pair of B&W Nautilus
801 in a 1905 house. Geometry-specific studies carry a configuration suffix;
no measurement data lives here.

| document | what it is | PDF |
|---|---|---|
| [`REW-INVERSION.md`](REW-INVERSION.md) | step-by-step room correction by inversion in REW | 42 pp |
| [`NOTES.md`](NOTES.md) | the working history, including the retractions | 38 pp |
| [`SUBWOOFER-INTEGRATION.md`](SUBWOOFER-INTEGRATION.md) | integrating subs under a single-DAC constraint | 6 pp |
| [`GIK-SCREEN-PANEL-PLACEMENT-120cm.md`](GIK-SCREEN-PANEL-PLACEMENT-120cm.md) | reflection geometry and measured panel-order study for the 120 cm configuration | 7 pp |
| [`MANUAL.md`](MANUAL.md) | `allpass_tool.py` user manual | — |
| [`HANDOFF.md`](HANDOFF.md) | resuming this work on another machine | — |

```sh
./make-pdf.sh REW-INVERSION.md      # default target is NOTES.md
```

## Tools

| | |
|---|---|
| `allpass_tool.py` | L/R phase-cancellation study, all-pass and EQ design (Qt) |
| `drc_acceptance.py` | the three-test build-quality gate for a filter WAV |
| `roomgeom.py` | single source of truth for the listening-room geometry |
| `gik_screen_panel_placement-120cm.py` | generates the 120 cm ScreenPanel placement and measurement figures |
| `housecurve.py` | generates REW-loadable house curves |
| `fig*.py` | the figures in the documents |

## The measurements

Live in the geometry repositories beside this one — `../DRC-185` (185 cm) and
`../DRC-120.blue` (120 cm) — and the deployed coefficients in `open-media-drc`.
The scripts here reach them by relative path; see `CLAUDE.md`.
