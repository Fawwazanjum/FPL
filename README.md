# fpl-model

Personal FPL decision-support tool for team **mainooaise** (FPL team ID `1062551`).
Built across GW1-2 of the 2026/27 season. All 5 planned phases are complete.

## Where things are

| What | Where |
|---|---|
| **This folder** | `C:\Users\44736\fpl-model` — the whole project: code, tests, config, local data |
| **Code backup / history** | https://github.com/Fawwazanjum/FPL (every change ever made, with commit messages explaining why) |
| **Dashboard** (visual report) | https://claude.ai/code/artifact/d334b638-3786-4cbd-bec9-42c8a80fa136 — ask Claude to redeploy this after a fresh run to update it |
| **Your squad/settings** | `config.yaml` (gitignored — this file only exists here, not on GitHub, since it's personal) |
| **Live database** | `data/fpl_model.db` (SQLite — squad history, player stats, fixtures, everything ingested) |
| **Generated reports** | `reports/latest.json` (most recent run) and `reports/report_gw*_*.json` (timestamped history) |
| **Build plan / design decisions** | `C:\Users\44736\.claude\plans\imperative-inventing-cat.md` |

## What this does

Ingests your live FPL squad, scores every player on blended current/last-season
form, forecasts points per fixture (attacking / clean sheet / DEFCON / bonus,
position-aware), tracks club-level attack/defense strength vs underlying xG,
recommends transfers (with a conservative hit policy — won't suggest a hit
unless it clearly beats banking), picks your best XI and captain, times all
four chips, and optionally folds in Understat data and manually-researched
team news.

See `src/fpl_model/` for the code — each module has a docstring explaining
its role; `analysis/` and `optimizer/` are the core logic, `data/` is
ingestion, `report/` is the output layer.

## Running it

```
cd C:\Users\44736\fpl-model
.venv\Scripts\python.exe -m fpl_model.run_update
```

Add `--force-refresh` to bypass the cache and pull everything fresh. Output
lands in `reports/latest.json`. Ask Claude to read that and rebuild the
dashboard artifact if you want the visual version updated.

`config.yaml` holds your team ID and all the tunable thresholds (hit margin,
wildcard gates, differential/template cutoffs, etc.) — see
`config.example.yaml` for what each one does.

## Picking this back up later

Point Claude at this folder (or just say "check my FPL model") and ask it to
read `README.md` and the plan file above for full context — it also keeps
its own memory of this project's design decisions and open questions between
sessions.
