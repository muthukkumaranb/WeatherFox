# SkyGuard AI

Anomaly detection for AWS temperature / pressure / humidity streams (SIH26073).

## Contract (frozen)
- `skyguard/schemas/input_row.schema.json`: one reading. Never carries injection labels. `qc` is stripped before the detector (`to_model_input`).
- `skyguard/schemas/verdict.schema.json`: per-variable verdicts (T, RH, P), overall label = worst variable (`anomaly` > `uncertain` > `normal`), `phase: provisional | final`. Score only `final`.
- `skyguard/schemas/injection_label.schema.json`: written by the injector to a separate file, one line per fault.
- All three schemas carry `schema_v: "1.0"`. `P_type`: slp | altimeter | station. `source`: ghcnh_synop | ghcnh_metar | ghcnh_speci | asos1min | esp32.
- Detector interface: `score(station_window, target) -> verdict`, where `station_window = {station_id: [recent contract rows, oldest -> newest]}` for the target and its neighbours (neighbour list comes from the station registry; the replay engine keeps the rolling buffers). `target` is **required** — there is no "first key" fallback. Neighbour support is computed inside the model from the neighbours' actual values. `skyguard/fake_score.py` has the same signature and is the stand-in until the real models are plugged in.
- Verdict `vars` keys are exactly T, RH, P. Td is internal: a humidity fault is detected on Td and reported under RH.
- `qc` is stripped only by `to_model_input()` in `skyguard/contract.py`. Never write a second stripper.

## Scorer (single swap point)
All modules import `score` from `skyguard.scorer`. The backend is chosen by
the `SKYGUARD_SCORER` environment variable:
- `"fake"` (default): uses `skyguard.fake_score.score`
- `"real"`: lazily imports `skyguard.verdict.api.score`

Never silently falls back; invalid values raise `ValueError`.

## Rules enforced in `skyguard/contract.py`
- Overall `label` equals the worst variable label.
- `genuine_event: true` only with `label: normal` and `spatial_support: neighbours_also_deviating`.
- `spatial_support: no_neighbours` requires `n_neighbours: 0`.
- `ttm_days` is `null` when `trend` is `insufficient_history`.
- `duplicate`, `timeshift`, `comms_gap` are decided by ingest rules, not the classifier.
- `power` is assigned only when `batt_v` is present.

## Run
```
pip install -r requirements.txt
python -m pytest -q
```
