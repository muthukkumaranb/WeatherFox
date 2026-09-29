# Person C plan — SkyGuard AI (WeatherFox) — live data, edge, scale, deployment & story

Person C works **in parallel** with Person A (data + ML) and Person B (API, dashboard, harness).
Each new Copilot chat starts with: **"Read docs/PERSON_C_PLAN.md and docs/HANDOVER.md. Do STEP N."**
One step per chat. At the end of each step: `python -m pytest -q` (ALL tests green — everyone's, not just
yours), the step's check, `git add -A`, commit on branch **`person-c`**, push, open/refresh a pull request
into `main`, then STOP and summarise in ≤ 8 lines (what changed, test count, what the check printed).

## Ownership rules (so we never collide)
- You own ONLY these paths: `skyguard/ingest/wis2.py`, `skyguard/edge/`, `skyguard/eval/scale.py`,
  `skyguard/api/upload.py`, `dashboard/upload.html`, `deploy/`, `docs/USE_CASES.md`, `docs/DEMO_SCRIPT.md`,
  `docs/REPRODUCE.md`, `scripts/reproduce.py`, `scripts/scale_test.py`, `tests/test_c_*.py`, plus new files you
  create under those folders.
- Never edit Person A's folders (`skyguard/data/`, `skyguard/detect/`, `skyguard/verdict/`, `skyguard/validate/`)
  or Person B's files (`skyguard/contract.py`, `skyguard/schemas/`, `skyguard/scorer.py`,
  `skyguard/fake_score.py`, `skyguard/ingest/rule_gate.py|rules.py|buffers.py|replay.py`,
  `skyguard/api/main.py`, `dashboard/index.html`, `skyguard/eval/harness.py|baselines.py|leak_check.py|feedback.py`,
  `config/skyguard.toml`). If you need a hook there (one import line, one config key, one enum value), STOP and
  write the exact line for the owner in your summary.
- Add new config under a section you own in a NEW file `config/person_c.toml` (read it with tomllib).
- All scoring goes through `skyguard.scorer.score(station_window, target)`; works with SKYGUARD_SCORER=fake now,
  =real later. Window format: `{station_id: [contract row dicts, oldest -> newest]}`.
- Every input row you produce must pass `skyguard.contract.validate_input_row`.
- Honest labelling (HANDOVER §10): anything not measured on real hardware or real IMD data is "estimated" /
  "synthetic"; never invent numbers; figures come only from files your scripts produce.

---

## STEP 1 — Live official IMD data via WIS 2.0 (`skyguard/ingest/wis2.py`)
IMD runs a public WMO WIS 2.0 node (OGC API, GeoJSON, no API key): primary `https://wis2box.imd.gov.in/oapi`,
standby `https://wis2boxstdby.imd.gov.in/oapi`. SYNOP collection id:
`urn:wmo:md:in-imd:surface-based-observations.synop`.
- Station metadata: `GET {base}/collections/stations/items?limit=500&f=json` → features with WIGOS id
  (e.g. `0-20000-0-42182`), name, coordinates (lon, lat[, elev]).
- Observations for a UTC window (≤ 24 h per request):
  `GET {base}/collections/{collection}/items?f=json&limit=1000&datetime=START/END` (ISO `...Z`), optionally
  `&wigos_station_identifier=<id>`. Follow the `links` entry with `rel == "next"` for more pages.
- Each feature is ONE parameter of one report. Group by (`properties.wigos_station_identifier`,
  `properties.reportId`); time = `properties.reportTime` (else `phenomenonTime`); parameter name =
  `properties.name`, value = `properties.value`, units = `properties.units`.
  Map: `air_temperature` → T, `dewpoint_temperature` → Td, `relative_humidity` → RH,
  `pressure_reduced_to_mean_sea_level` → P with P_type "slp", else `non_coordinate_pressure` → P with P_type
  "station". **Convert by units**: K → °C (−273.15), Pa → hPa (÷100). If RH is missing, compute from T and Td
  (Magnus a=17.625, b=243.04), clip 0–100.
- Output contract rows: station_id = WIGOS id, ts_utc = report time, ingest_ts_utc = the feature's
  resultTime/publication time if present else fetch time, seq per station, cadence_min = 180 (synoptic; infer
  60 if a station reports hourly), source = value from `config/person_c.toml` [wis2] source (default
  "ghcnh_synop" until the team adds "imd_wis2" to the contract enum — flag this line for Person B:
  add `"imd_wis2"` to SOURCES in contract.py and the input_row schema enum).
- Also write a registry file `data/wis2/stations.csv` (station_id, name, lat, lon, elev_m, cadence_min, P_type)
  so B's replay can build neighbours.
- CLI: `python -m skyguard.ingest.wis2 --hours 24 --out data/stream/wis2_latest.jsonl` (resumable, polite:
  User-Agent header, 1 request/second, timeout 20 s, falls back to the standby node, never crashes on a bad
  page — logs and continues). Print a summary: stations, reports, rows written, time range.
- Tests with SAVED JSON fixtures only (no network in tests): grouping by reportId, K→°C, Pa→hPa, MSLP vs station
  pressure, RH derivation, `next`-link paging, every row passes validate_input_row.
Check: run the CLI for real for the last 24 h and paste the summary + 3 rows. In your summary, give Person B the
one line to make the replay use `data/stream/wis2_latest.jsonl` + `data/wis2/stations.csv` when present
("live mode"), and the contract enum line.
Honest wording for slides: "near-real-time official IMD synoptic observations via WMO WIS 2.0 (mostly 3-hourly
SYNOP stations, not the AWS network itself)".

## STEP 2 — ESP32 edge (`skyguard/edge/`)
- `edge/c/rule_gate.c` + `.h`: port of `skyguard/ingest/rule_gate.py` (range, per-cadence step table,
  hour-based frozen with fog exemption, Td ≤ T + 0.2; FAIL vs SUSPECT exactly as in Python). Thresholds are
  generated from `config/skyguard.toml` into `edge/c/thresholds.h` by `edge/gen_thresholds.py` (read-only use of
  the config).
- `edge/export.py`: train a small scikit-learn DecisionTree (max_depth ≤ 6) on edge-computable window features
  (1 h change, step vs previous, run length of identical values, T − Td, 6 h variance ratio) using injected data
  from Person A if present (`data/stream/injected_train.parquet` + labels), else a synthetic generator; export
  to C if/else code `edge/c/tiny_tree.c/.h` and report its accuracy on held-out rows.
- Host build with gcc if available (`edge/build_host.py`): parity test — C rule gate and tree vs Python on
  10,000 rows must agree exactly; report object size (bytes), RAM estimate, µs per reading →
  `reports/edge/edge.json`, labelled "host-measured estimate, not ESP32 hardware".
- Adaptive reporting energy estimate (`edge/energy.py`): calm → 15-min summaries; local anomaly or rapid change
  → 1-min for 2 h. Using datasheet figures stated in the file (ESP32 active/modem-sleep/deep-sleep currents,
  GPRS/Wi-Fi TX energy), compute radio-on seconds per hour and projected battery life (fixed vs adaptive) →
  `reports/edge/energy.json`, labelled "estimated from datasheet figures".
- `edge/esp32/skyguard_edge/skyguard_edge.ino`: Arduino sketch using the same C files; BME280 (T/RH/P) +
  battery ADC; MQTT publish of contract rows (source "esp32", batt_v, seq) to `aws/<network>/<station>/obs`;
  24 h ring buffer with store-and-forward; config constants at the top. (It must compile in principle; we have
  no board — say so.)
Check: paste `reports/edge/edge.json` and `energy.json` and the parity result.

## STEP 3 — Scale test (`skyguard/eval/scale.py`, `scripts/scale_test.py`)
Synthetic networks of 100, 1,000 and 10,000 stations (random Indian lat/lon, neighbours by distance, 24 h
hourly history) pushed through ingest validation + `skyguard.scorer.score` in-process (no HTTP): readings/s,
p50/p95 latency per reading, peak memory (tracemalloc), 3 runs each, fake and (if models exist) real scorer.
Save `reports/scale/results.json` + `reports/scale/scale.png` (throughput and p95 vs stations).
Check: paste results.json. Give Person B the one line to show it on the benchmark page.

## STEP 4 — Judge mode: "Upload your own data" (`skyguard/api/upload.py`, `dashboard/upload.html`)
- A FastAPI `APIRouter` (B includes it with one line): `POST /upload/score` accepts a CSV
  (station_id, ts_utc, T, RH, P, optional Td, optional lat, lon) and optional labels CSV/JSONL
  (station_id, variable, root_cause, start_ts, end_ts). It converts rows to contract rows (derive Td from T/RH if
  missing; P_type "slp"; cadence inferred), builds station windows (neighbours from lat/lon if given), scores
  every reading through `skyguard.scorer.score`, and returns: counts by label and root cause, the first 200
  alerts with reasons, and — if labels were given — metrics from `skyguard.eval.harness.evaluate`.
  Limits: ≤ 200k rows, clear error messages for bad columns/units.
- `dashboard/upload.html`: file pickers, a "Score it" button, results table + alert list + metrics table;
  a downloadable sample CSV with a few injected faults (generated by a small script) so judges can try it.
Check: upload the sample CSV via TestClient and paste the summary. Give B the include line and a nav-link line.

## STEP 5 — Hosted demo (`deploy/`)
Deploy the API + dashboard + replay to a free host (Render web service or Railway): `deploy/render.yaml`
(or `railway.json`), start command `uvicorn skyguard.api.main:create_app --factory --host 0.0.0.0 --port $PORT`,
Python version pinned, no secrets needed. Keep models small enough for the free tier; if the real scorer is too
heavy, deploy with the fake scorer and the "DEMO MODE" banner visible (never hide it). Write
`deploy/README.md` with the URL, how to redeploy, and cold-start note.
Check: paste the public URL and the output of `curl <url>/health`.

## STEP 6 — Reproducibility page (`scripts/reproduce.py`, `docs/REPRODUCE.md`)
`python scripts/reproduce.py [--quick]`: runs the pipeline steps that exist (data → injections → train →
eval on VAL → harness → scale → edge), and writes `reports/manifest.json` with, for every metric file: command,
git commit, data file hashes (sha256), split.json sha256, config hash, timestamp. `--quick` uses a small subset.
`docs/REPRODUCE.md` explains it in plain words. Never runs `final_test.py` (that runs once, by Person A).
Check: paste the manifest summary from a `--quick` run.

## STEP 7 — The story: use cases, demo script, video (docs only)
- `docs/USE_CASES.md` (PS-required deliverable): six use cases, each with Actor, Trigger, What SkyGuard does
  (step by step), What the operator sees (dashboard/API/screenshots), Value:
  1 Single-sensor fault (55 °C / Mungeshpur-type)  2 Power / battery fault (batt_v)
  3 Communication error (gap, INSAT triple-transmission duplicate, IST/UTC timeshift)
  4 Slow sensor drift → days to maintenance  5 Genuine heat wave vs faulty sensor (event protection, storm
  injection)  6 Multi-station outage. Plus: datasets & limits, method overview, evaluation protocol, results
  (ONLY from `reports/final/metrics.md`, else "pending final test"), future work (nightly retraining on
  verified-clean data, IMD GFS/NCUM live background, IMD AWS validation). Follow HANDOVER §10 say / don't-say.
- `docs/DEMO_SCRIPT.md`: 2-minute judge walkthrough: hook (Mungeshpur 52.9 °C was a sensor error per IMD) →
  live map (WIS2 / replay) → inject 55 °C → alert with reasons + corrected value → inject genuine storm → no
  alert, "genuine event" → reject-as-weather feedback → health board drift → WMO-flag export → upload-your-data
  → benchmark page → ESP32 numbers. Include exact clicks and what to say.
- Record the demo video from the hosted or local demo (screen recording + voice), ≤ 3 minutes; put the link in
  README and the slides. Fill the slide deck from `SkyGuard_PPT_Content.md` (numbers only from reports/).
Check: link to the video and the rendered USE_CASES.md.

---

### Hand-off lines Person C must send (collect them in each summary)
- B: add `"imd_wis2"` to SOURCES (contract.py) + input_row schema enum (team decision).
- B: replay "live mode" reads `data/stream/wis2_latest.jsonl` + `data/wis2/stations.csv` when present.
- B: include `skyguard.api.upload.router` in `create_app()` + nav link to `/upload.html`.
- B: show `reports/scale/results.json`, `reports/edge/*.json` on the benchmark page.
