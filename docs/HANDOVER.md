# SkyGuard AI — Handover Document

## Source of truth
This document is the source of truth for design decisions, contracts,
and claims.  Where anything (including `.github/copilot-instructions.md`)
disagrees with it, **HANDOVER wins**.

## Key decisions
- All scoring goes through `skyguard.scorer.score(station_window, target)`.
- `SKYGUARD_SCORER=fake` (default) or `real` (when Person A's models exist).
- Thresholds live in `config/skyguard.toml`; add sections, never delete keys.
- All timestamps are UTC; units: °C, %, hPa.
- Honest labelling: anything not measured on real hardware or real IMD data
  is labelled "estimated" / "synthetic".

## Contract
- Input row: `skyguard/schemas/input_row.schema.json`
- Verdict: `skyguard/schemas/verdict.schema.json`
- Injection label: `skyguard/schemas/injection_label.schema.json`
- Vocabularies and validation: `skyguard/contract.py`

## Ownership boundaries
- Person A: `skyguard/data/`, `skyguard/detect/`, `skyguard/verdict/`,
  `skyguard/validate/`, `skyguard/schemas/`
- Person B: `skyguard/api/`, `skyguard/ingest/`, `skyguard/eval/`,
  `skyguard/edge/`, `skyguard/fake_score.py`, `skyguard/scorer.py`,
  `dashboard/`, `config/`, `tests/`, `scripts/`, `docs/`
