# DRC-doc

Guides, studies and tooling for the room correction of a pair of B&W Nautilus
801 in a 1905 house. Geometry-specific studies carry a configuration suffix;
no measurement data lives here.

| document | what it is | PDF |
|---|---|---|
| [`REW-INVERSION.md`](REW-INVERSION.md) | step-by-step room correction by inversion in REW | 52 pp |
| [`NOTES.md`](NOTES.md) | the working history, including the retractions | 38 pp |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | taking a finished filter into `omdrc-801N` — rates, headroom, provenance | 8 pp |
| [`SUBWOOFER-INTEGRATION.md`](SUBWOOFER-INTEGRATION.md) | integrating subs under a single-DAC constraint | 6 pp |
| [`GIK-SCREEN-PANEL-PLACEMENT-120cm.md`](GIK-SCREEN-PANEL-PLACEMENT-120cm.md) | reflection geometry and measured panel-order study for the 120 cm configuration | 7 pp |
| [`MANUAL.md`](MANUAL.md) | `allpass_tool.py` user manual | — |
| [`HANDOFF.md`](HANDOFF.md) | resuming this work on another machine | — |

```sh
./make-pdf.sh REW-INVERSION.md      # default target is NOTES.md
```

## Claude skill

`.claude/skills/rew-inversion-audit/` — invoke with `/rew-inversion-audit`,
or just ask Claude to review a filter export / explain a `drc_acceptance.py`
failure and it triggers on its own. Audits REW inversion-method exports
against `REW-INVERSION.md`'s procedure and runs/explains the acceptance
tests. See the skill file for the full brief.

## Tools

| | |
|---|---|
| `allpass_tool.py` | L/R phase-cancellation study, all-pass and EQ design (Qt) |
| `drc_acceptance.py` | the three-test build-quality gate for a filter WAV |
| `drc_export_preflight.py` | sanity-checks a REW `.txts` export directory before deployment — naming, `LR`/`L+R` conflicts, unsmoothed, ≤24 kHz |
| `roomgeom.py` | single source of truth for the listening-room geometry |
| `gik_screen_panel_placement-120cm.py` | generates the 120 cm ScreenPanel placement and measurement figures |
| `housecurve.py` | generates REW-loadable house curves |
| `fig*.py` | the figures in the documents |

## The measurements

Live in the geometry repositories beside this one — `../DRC-185` (185 cm) and
`../DRC-120.blue` (120 cm). The deployed coefficients live in the site
repository `~/devel/omdrc-801N`; `open-media-drc` is the public engine and
ships only the uncorrected `flat` set.
The scripts here reach them by relative path; see `CLAUDE.md`.
