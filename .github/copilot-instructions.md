# SkyGuard AI: master instructions for AI coding assistants

Use this file as the standing context for every task in this repo (Copilot, Claude, Cursor, or pasted as a system prompt).

## 1. What we are building
SkyGuard AI is a real-time anomaly detector for Automatic Weather Stations (SIH26073). It uses ONLY temperature (°C), pressure (hPa) and relative humidity (%) to:
- detect sensor faults, spikes, frozen values, drift and communication errors,
- tell genuine weather events (heat wave, cyclone, fog, squall) apart from sensor faults,
- give confidence, severity, root cause, an explanation and an optional corrected value,
- track sensor health and predict maintenance,
- run at scale (100 to 10,000 stations) and, in reduced form, on an ESP32.

Judges score: innovation 25%, detection accuracy 20%, real-time 15%, explainability 10%, scalability 10%, deployability 10%, dashboard 5%, energy 5%. Evaluation is on anomaly-injected data. Spend effort in that order.

Deliverables: fully executable code with example usage (one-command demo), and a use-case document.

## 2. Hard rules (never break these)
1. **India-only data.** Train and evaluate on Indian data: GHCNh (Indian stations), HadISD (Indian stations), and optionally ERA5 clipped to India. Do not add datasets from other countries. Note: `asos1min` exists as a `source` value in the contract, but no foreign data is used for training unless the team decides otherwise.
2. **The contract is frozen.** Schemas live in `schemas/`, validation in `skyguard/contract.py`. Do not change a field, enum or rule without the team agreeing. Validate every record you produce.
3. **Package name is `skyguard/`.** Never create `pramaan/` or any second package.
4. **No leakage.**
   - `qc` (upstream GHCNh quality codes) is stripped only by `to_model_input()` in `skyguard/contract.py`. Call it. Never write a second stripper. Never use `qc` as a model feature.
   - Injection labels live in a separate file. Never add `is_injected`, fault type or split to input rows.
   - The test split is locked by hash of `station_id` and by time. Never tune on it.
5. **Final test set is run once**, near the end, and the numbers are frozen. During development use validation only.
6. **Never suppress genuine extremes.** A heat wave, cyclone or fog event that neighbours confirm is `normal` with `genuine_event: true`.
7. **Honest reporting.** Label anything not measured on real hardware or real IMD data as "estimated" or "synthetic". Report counts, not only percentages, for small classes.

## 3. The contract in brief
- Input row: `schema_v "1.0"`, `station_id`, `ts_utc`, optional `ingest_ts_utc` and `seq`, `T`, `Td`, `RH`, `P` (null = missing), `P_type` (slp | altimeter | station), optional `batt_v`, `cadence_min`, `source` (ghcnh_synop | ghcnh_metar | ghcnh_speci | asos1min | esp32), optional `qc`. Units: °C, %, hPa. Faulty values (RH 130, T 55) must be representable, so the schema has no physical range limits.
- Verdict: per-variable blocks under `vars` with keys **exactly T, RH, P**. Td is internal: a humidity-sensor fault is detected on Td and reported under RH; corrected RH comes from corrected T and Td.
  - Overall `label` is the worst variable label: anomaly > uncertain > normal.
  - Per variable: `label`, `confidence` (calibrated probability of fault for anomaly, 1 minus that for normal), `p_value` (conformal), `root_cause`, `severity`, `severity_score`, `reasons[]` (feature, value, contribution, text), `action`, `corrected {value, sigma, method}`.
  - `phase` is `provisional` or `final`. Only `final` verdicts are scored.
  - `genuine_event: true` only with `label: normal` and `spatial_support: neighbours_also_deviating`.
  - `no_neighbours` means `n_neighbours = 0` and lowers confidence (label may be `uncertain`).
  - `health` per sensor: `score`, `trend`, `ttm_days` (null when trend is `insufficient_history`).
- Root causes: spike, frozen, drift, offset, noise, out_of_range, radiation, power, comms_gap, duplicate, timeshift, unknown.
  - `duplicate`, `timeshift`, `comms_gap` are decided by ingest rules, not the classifier.
  - `power` is assigned only when `batt_v` is present.
- Injection label (separate file, one line per fault): `injection_id, station_id, variable, root_cause, start_ts, end_ts, params, difficulty, seed, split`.

## 4. Detector interface
```python
score(station_window: dict[str, list[dict]], target: str | None = None) -> dict   # returns a verdict
# station_window = {station_id: [contract rows, oldest -> newest]}  for the target AND its neighbours
# target defaults to the first key
```
- The replay engine keeps the rolling buffers (at least 24 h of history per station) and builds the window. The neighbour list comes from the station registry (lat, lon, elevation), not from the input row.
- Neighbour support is computed INSIDE the detector from the neighbours' actual values. It is never passed in as a count or a flag.
- `skyguard/fake_score.py` has the same signature and is used until the real detector is plugged in. Swapping is a one-line import change. Always call `validate_window()` and `validate_verdict()` at the boundary.

## 5. Package layout
```
skyguard/
  contract.py        vocabularies, validators, leak guards (single source of truth)
  fake_score.py      stand-in detector
  data/              GHCNh + HadISD download, cleaning, dedup, time-grid snapping, station registry
  inject/            fault injector (all 12 classes), genuine-event windows, writes the injection-label file
  models/            forecaster, rule gate, conformal thresholds, root-cause classifier
  spatial/           neighbour model, event-protection rule, isolated-station handling
  explain/           SHAP to alert text and action
  health/            CUSUM drift, sensor health, ttm_days
  ingest/            duplicate / timeshift / comms-gap rules, replay engine, rolling buffers
  api/               FastAPI + WebSocket + inject-fault endpoint
  eval/              harness: per-variable, per-class, event-wise metrics; genuine-event false-alarm rate
  edge/              tiny tree model exported to C for ESP32
dashboard/           single-page UI served by the API
schemas/  examples/  tests/  scripts/
```
If the team's layout differs, the only rename is the package name: it stays `skyguard/`.

## 6. Data rules
- Base data: GHCNh, Indian stations with at least about 2,500 reports per year, 2023 to 2024 (plus 2026 for the replay demo). HadISD India up to Aug 2025 for silver labels.
- Pressure: use SLP or altimeter (`P_type`); station pressure is almost empty in 2026.
- METAR is whole °C and whole hPa. Model that quantisation in the injector, and augment training with random rounding.
- De-duplicate METAR/SYNOP at the same timestamp (keep the synoptic value). Snap to a common time grid with a tolerance of about 30 minutes. Never reuse one neighbour report for two time slots.
- Cadence differs by station (30 min vs 3 h). Pass `cadence_min` through and train or calibrate per cadence group.
- Split by station (hash) and by time. Hold out entire stations and a full period.

## 7. Modelling rules
- Layers: rule gate, then forecaster (LightGBM on lags, climatology and neighbour features), then neighbour check and event-protection rule, then root-cause classifier, then health/drift, then imputation.
- The forecaster and anomaly signal are trained on NORMAL data only; the classifier is trained on residual features plus injected faults. Do not let the model see injection metadata.
- Event-protection rule: if the station and enough neighbours (or the ERA5 residual, replay only) deviate in the same direction, it is a regional event, not a fault. A lone deviation with calm neighbours is a fault.
- Neighbour comparison tolerates about ±1 °C (METAR rounding). With no usable neighbours, output `no_neighbours` and reduce confidence.
- Corrected value: blend forecaster and neighbour predictions; always give `sigma` and `method`.
- Thresholds: conformal, calibrated on a validation slice (never the test set). Keep them rolling.
- Explainability: TreeSHAP on the classifier, turned into plain-language `reasons[].text` and an `action`.
- Randomise fault magnitude, duration and rate in training, and keep some fault types or ranges unseen for testing.

## 8. Evaluation rules
- Build the harness first, then measure every model change with it.
- Event-wise metrics per variable and per root cause (precision, recall, F1, detection delay), plus the false-alarm rate on genuine-event windows (heat wave, cyclone, fog). The genuine-event false-alarm result is never cut.
- Baselines: rule gate alone, z-score, Isolation Forest, HadISD flags.
- Report latency per reading and throughput; report provisional vs final separately; the harness fails loudly if `qc` or injection metadata reaches the model's features.
- Final untouched test: once, frozen.

## 9. Coding conventions
- Python 3.11+, type hints, small pure functions, no global state. Use `pathlib`, `logging` (no prints), and seeds for all randomness.
- Every module has a pytest test that runs offline in seconds on tiny fixtures. Run `python -m pytest -q` before saying a task is done.
- Config in one YAML or dataclass, not hard-coded paths. Data lives under `data/` and is git-ignored.
- Anything written to disk or sent over the API goes through the contract validators.
- Keep the demo one command: `python -m skyguard.demo` (replay + API + dashboard).

## 10. Handover points
- 10:45 contract frozen. 15:00 sample real verdicts to the dashboard. 20:00 real `score()` handed over. 05:00 numbers frozen.
- If time runs short, cut in this order: ESP32 export, scalability test, HadISD comparison. Never cut: the genuine-event false-alarm result, the working demo, the one-command run.

## 11. How the assistant should behave
- Read this file and `skyguard/contract.py` before writing code. If a request conflicts with a rule above, say so and propose the closest compliant option.
- Ask before adding a dependency, a dataset, or a change to the contract. Otherwise make reasonable choices, state them in one line, and keep going.
- Write the test with the code. Show how to run it. Keep explanations short.
