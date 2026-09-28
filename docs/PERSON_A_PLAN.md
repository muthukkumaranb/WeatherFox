# Person A plan — SkyGuard AI (WeatherFox) — v2 (new Person A, 22:10)

This file is the standing plan for Person A's Copilot chats. Each new chat starts with:
"Read docs/PERSON_A_PLAN.md. Do STEP N."

You are building Person A's part (data + ML) of SkyGuard AI (repo WeatherFox), SIH26073: real-time anomaly
detection for Indian weather stations using Temperature, Dew point (internal), RH and Pressure. It separates
sensor/data faults from real weather events (heat wave, cyclone, fog) and outputs per reading: label, root
cause, confidence, severity, reasons, corrected value ± sigma, sensor health.

=== MY MACHINE ===
- Python 3.11 in a virtual env at .venv (already activated). Use `python -m ...` for everything.
  No `make`; write Python scripts in scripts/ instead, so everything works on Windows, macOS and Linux.
- Use pathlib for all paths (no hard-coded "/" or "\"). Open text files with encoding="utf-8".
- Heavy downloads run from my machine with internet; make them resumable and show progress.

=== CONTEXT (22:10, deadline ~09:00) ===
- I am taking over Person A's part from scratch; nothing of Person A's is in the repo yet.
- Person B has already built and pushed to main: skyguard/ingest/ (rule_gate with per-cadence step table,
  fail vs suspect; rules for duplicate/timeshift/comms_gap; buffers; replay), skyguard/api/main.py (FastAPI,
  background replay on a simulated clock, /ws/live, /inject-fault, scorer calls off the event loop), and
  dashboard/. B is now doing the evaluation harness, ESP32, scale test and demo. Don't edit B's files.
- Handovers to B: after STEP 1 → data/station_registry.csv + data/stream/sample_1day.jsonl (B's replay
  switches to real stations); after STEP 4 → real score() (SKYGUARD_SCORER=real). Tell me when each is ready.

HOW TO WORK: do ONE step at a time. After each step run `python -m pytest -q` until ALL tests pass
(Person B's existing tests + yours), then `git add -A`, `git commit`, `git push -u origin person-a`, then STOP
and summarise. Each step is done in its own chat; I will tell you which step to do. Add any new packages to requirements.txt.

=== WHAT ALREADY EXISTS (Person B's — do not edit) ===
- skyguard/contract.py: SCHEMA_VERSION, P_TYPES, SOURCES, LABELS, ROOT_CAUSES, INGEST_CLASSES,
  SPATIAL_SUPPORT, VARIABLES (T, RH, P), FORBIDDEN_FEATURES, ContractError, worst_label, validate_input_row,
  ingest_row, check_window, validate_injection, validate_verdict, to_model_input, assert_no_leak.
  Use these. Never write your own validator or qc stripper.
- skyguard/schemas/ (the only schema folder), skyguard/fake_score.py, skyguard/scorer.py (switch:
  SKYGUARD_SCORER=fake|real; real imports skyguard/verdict/api.py), skyguard/ingest/, skyguard/eval/,
  skyguard/api/, skyguard/edge/, dashboard/, skyguard/demo.py. If you believe any of these must change,
  STOP and tell me.
- config/skyguard.toml (B's): [data] raw_dir, clean_dir, registry_path; [paths]; [split] train_year,
  val_station_fraction, test_years, test_unseen_station_fraction, station_hash_salt; [detector]
  history_hours, max_neighbours, max_neighbour_km, metar_rounding_tolerance_C; [conformal] alpha_anomaly,
  alpha_uncertain; [health]; [genuine_events]. REUSE these keys. You may ADD new sections; never delete B's keys.
- Stubs owned by me (implement them, keep their existing function signatures working, add files as needed):
  skyguard/data/{download,clean,registry,split,export_stream,events,inject}.py,
  skyguard/detect/*, skyguard/verdict/*, skyguard/validate/hadisd.py.
- If .github/copilot-instructions.md disagrees with this prompt, THIS prompt and the actual repo files win.

=== RULES ===
- Thresholds only in config. Features causal (data at or before t), same code for training and streaming.
- UTC; °C, %, hPa; missing = NaN/None, never a sentinel. Tests use small FAKE data, no network.
- Window format everywhere: {station_id: [contract row dicts, oldest -> newest]}. Convert to DataFrames
  inside my code only.
- Detector: score(station_window, target) in skyguard/verdict/api.py; target required.
  Neighbour agreement is computed INSIDE the model from neighbour values.
- Verdict vars keys exactly T, RH, P. Td is internal: humidity faults are detected on Td and reported under
  RH; corrected RH comes from corrected T and Td. Overall label = worst_label(). Only phase "final" is scored.
- power only when batt_v present. duplicate/timeshift/comms_gap come from B's ingest rules, not my classifier.
- genuine_event true only with label normal + spatial_support neighbours_also_deviating.
- Training + headline metrics: Indian data only. Never tune on the test split. Never inject inside event windows.
- data/ and models/ are git-ignored; splits/ and reports/ are committed.

=== DATA SOURCE: GHCNh (NOAA) ===
- Station list (fixed width, 1-based cols): id 1–11, lat 13–20, lon 22–30, elev 32–37, state 39–40,
  name 42–71, gsn 73–75, hcn/crn 77–79, wmo 81–end; -999.9 = missing.
  https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-station-list.txt
- Per station-year: https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/access/by-year/{YEAR}/psv/GHCNh_{ID}_{YEAR}.psv
  404 = no data. Pipe-delimited, header row; lowercase all column names.
- Columns: station, station_name, date, year, month, day, hour, minute, latitude, longitude, elevation,
  temperature, dew_point_temperature, relative_humidity, station_level_pressure, sea_level_pressure,
  altimeter, sky_cover_layer_1..3 ("code:okta"); each variable has _measurement_code, _quality_code,
  _report_type, _source_code, _source_station_id.
- FM-12 SYNOP (0.1 °C, 3-hourly), FM-15 METAR (whole °C/hPa, half-hourly), FM-16 SPECI (irregular).
  Quality code "9" = no QC supplied, NOT missing. Station pressure is nearly empty: use SLP, else altimeter.
- India = id starts with "IN" and lat 6–37.5, lon 68–97.5.

=== STEP 1: DATA PIPELINE (skyguard/data/) ===
Add config sections [download] (years [2023, 2024], workers 8, retries 3, timeout_s 120), [stations]
(India filter, min_reports_per_year 2500), [clean] (extra_pass_codes ["0","1","4","5","9","A","U","P","I","M","C","R"],
gross limits T −40..60, Td −60..40, P 850..1085, report_priority synop>metar>speci>other), [grid]
(freq_min 60, snap_tol_min 30). Fill [genuine_events] as [[genuine_events.events]] (name, type, start,
end, lat_min, lat_max, lon_min, lon_max):
  heatwave_nw_india_2024 heat_wave 2024-05-25→2024-06-02 22,32,70,82
  cyclone_remal_2024 cyclone 2024-05-25→2024-05-29 20,27,85,93
  cyclone_fengal_2024 cyclone 2024-11-28→2024-12-03 9,15.5,76.5,81.5
  fog_igp_jan_2024 fog 2024-01-01→2024-01-20 24,32.5,73,88.5
  cyclone_michaung_2023 cyclone 2023-12-01→2023-12-07 11,17.5,78,82
Implement:
- download.py: station list + per-station-year PSV, thread pool, retries with backoff, resumable
  (skip existing files, write to a .part file then rename), 404 = missing, progress every 50 files,
  download_log.json; parse_to_rows() → contract rows.
  CLI: python -m skyguard.data.download [--years] [--limit] [--stations].
- clean.py: report type per row; a value is flagged if its quality code is neither the station-variable's
  most common code nor in extra_pass_codes → None in clean rows, keep raw code in qc; gross limits → None;
  P from SLP else altimeter, P_type per station by coverage; RH from T, Td (Magnus a=17.625 b=243.04) if
  missing; sky_okta kept in a side table (not in contract rows); dedup_metar_synop keeps SYNOP first;
  snap_to_grid hourly within 30 min, never using one report for two slots; assign_cadence (30/60/180).
  Write data/clean/obs/{id}.parquet (native) and data/clean/grid/{id}.parquet (hourly).
- registry.py: data/station_registry.csv (station_id, name, lat, lon, elev_m, cadence_min, P_type,
  reports per year); keep stations meeting min reports in every year; load_registry(); neighbours() by
  effective distance sqrt(d² + (100·Δz_km)²), up to max_neighbours within max_neighbour_km.
- split.py: assign_split(station_id, ts_utc) using sha256(station_hash_salt + station_id) for the station
  groups (train / val / test_unseen) and the years from [split]; split_rows(); write splits/split.json
  (station lists + periods + sha256 of the canonical JSON) and verify_split() that raises on tampering.
- export_stream.py: stream_rows() → contract rows (validated with contract.validate_input_row), sorted by
  ingest_ts_utc; fabricate_ingest(rows, seed): ingest_ts_utc = ts + lognormal delay (median 90 s), seq per
  station. Also write a 1-day sample data/stream/sample_1day.jsonl for Person B.
- events.py: read [[genuine_events.events]]; stations inside each bbox; in_event(station_id, ts);
  mark_genuine_events(); write data/labels/events.jsonl.
- tests/fixtures/make_fake_ghcnh.py: fake station list + PSV files (written to pytest's tmp_path) for ~12
  stations in 3 clusters (Delhi, Kolkata, Chennai): diurnal T/Td/SLP, METAR every 30 min (integer T), SYNOP
  every 3 h (0.1 T), some METAR+SYNOP at the same timestamp, bad quality codes, empty station pressure,
  sky cover strings. Tests: dedup keeps SYNOP; flagged values are None; grid never reuses a report; split
  hash detects tampering; exported rows pass contract.validate_input_row; event membership works.
- scripts/make_data.py (replaces make): runs download → clean → registry → split → events → export with
  --limit for a quick run and --skip-download to rebuild from files already on disk. Print a summary
  (stations kept, rows, date range) at the end.

=== STEP 2: FAULT INJECTOR (skyguard/data/inject.py) ===
inject_faults(...) keeps its stub signature working and returns (injected rows, labels). Splits: train
(2023 train stations, seed 1), val (2023 val stations, seed 2), test (2024 + unseen stations, seed 3,
"blind" profile with different parameter ranges). 1–3 % of rows faulty (config), spread over seasons, hours,
stations; never inside event windows; no overlaps on one variable. Classes with easy/medium/hard tiers:
spike, frozen (incl. near-saturation humidity), drift (T 0.01–0.2 °C/day, 7–60 days), offset, noise,
out_of_range, radiation (T += c·max(0, sin solar elevation)·(1 − okta/8), c 0.5–4 °C), power (only on
stations given batt_v: normal 12.4–13.2 V with daytime charging; night sag < 11 V + correlated T/Td shift +
dropouts), comms_gap (delete rows), duplicate (2–3 copies within 3 min, same seq), timeshift (±1 h,
±5.5 h, ±24 h). Re-round to the row's resolution after injecting; recompute RH. Every label passes
contract.validate_injection; injected rows still pass validate_input_row and are never marked as injected.
Write data/stream/injected_{split}.parquet and data/labels/injections_{split}.jsonl. Same seed = same output.
Add scripts/make_injections.py.

=== STEP 3: DETECTOR CORE (skyguard/detect/) ===
climatology.py: per station-variable (month, hour) median + MAD from TRAIN only.
forecaster.py: LightGBM per variable (T, Td, P) from the station's OWN past only (lags 1,2,3,6,12,24 h,
other variables' lags, climatology, hour/doy sin-cos, lat, lon, elev, cadence) + q05/q95; flagged inputs
replaced by last good value. Use n_jobs=-1 but keep models small enough to train in < 10 min on a laptop.
neighbours.py: separate LightGBM per variable predicting the target's anomaly from neighbour anomalies
(count, median, distance-weighted mean, spread); target never its own neighbour; add
metar_rounding_tolerance_C when METAR is involved.
event_rule.py: co_move = share of neighbours with same-sign 3 h change; target deviates from its forecast
AND co_move ≥ 0.6 (config) AND small neighbour residual → neighbours_also_deviating; < 2 valid neighbours →
no_neighbours with capped confidence.
conformal.py: score = max(|forecast resid|/σ, |neighbour resid|/σ); calibrate on the VAL split per
(variable × cadence); p = (1 + #cal ≥ s)/(n + 1); anomaly if p < alpha_anomaly, uncertain if p < alpha_uncertain.
detector.py: Detector.fit() (saves models/ + version) and score_batch(); phase provisional until the
neighbour slot is complete. Add scripts/train.py.
Tests: single-station 8 °C spike → tiny p-value + neighbours_normal; same jump at all cluster stations →
neighbours_also_deviating; isolated station → no_neighbours; false-alarm rate on clean val ≈ alpha.

=== STEP 4: VERDICTS + score() (skyguard/verdict/) ===
features_pattern.py (run length, step, variance ratio, 7/30-day residual slope, day/night asymmetry, T–Td
residual correlation, batt_v, gap length, seq/duplicate, ts − ingest); root_cause.py (LightGBM multiclass on
injected train labels; mask power without batt_v; confusion matrix); explain.py (LightGBM
pred_contrib=True → top 3 → plain sentences + action per root cause); correct.py (inverse-variance blend
of forecaster + neighbour estimates, sigma, method); health.py (daily neighbour residual → CUSUM + Kalman
bias, 30-day slope → ttm_days to tolerance T 0.3 °C, Td 0.5 °C, P 0.3 hPa; score 0–1; trend;
insufficient_history → ttm_days None); severity.py (0–100 + band); assemble.py (verdict exactly per
schema, through contract.validate_verdict). api.py: score(station_window, target) → runs
skyguard.ingest.rule_gate first (import it; if it's still a stub, skip it with a TODO), calls
contract.to_model_input on every row, then the models; also score_batch(). Call contract.assert_no_leak on
the feature list. Target < 50 ms per reading (timing test). Check end to end, with the environment
variable SKYGUARD_SCORER=real, that skyguard.scorer.score works.

=== STEP 5: EVALUATION ON VAL (never test) ===
Arms on the val split: full system, rules-only, z-score (|z| > 4), Isolation Forest; each writes verdict
JSONL. Weak-spot report: recall by root cause × difficulty × cadence × variable, drift recall vs rate,
false alarms per genuine event, confusion matrix, 30 worst misses → reports/val/. Add scripts/eval_val.py.

=== STEP 6: HADISD VALIDATION (skyguard/validate/hadisd.py) ===
First download the Indian stations (WMO blocks 420–433) of the current HadISD release from the Met Office
Hadley Centre HadISD download page (find the station list and per-station netCDF links there) into
data/raw/hadisd/, resumable (scripts/download_hadisd.py; add xarray + netCDF4 to requirements). Print one file's
variables first; map QC flag columns to test names and assert the mapping. 2015–Aug 2025 excluding 2023;
drop gap/month clean-up flags; group consecutive flags into events; streak→frozen, spike→spike,
climatological→out_of_range, variance→noise. Show dew point climatological flags by station and month
first. Report "detected x of n events" (counts, not %, when n < 50) → reports/hadisd/.

=== STEP 7: FINAL TEST (ONCE) ===
scripts/final_test.py runs only if verify_split() passes and refuses a second run. On the test split:
event-wise P/R/F1 per variable × root cause (no point-adjust), genuine-event false alarms per 100
station-days, provisional vs final, ECE, corrected-value RMSE + ±1σ coverage, latency p50/p95, model
sizes → reports/final/. scripts/sample_review.py: top 200 recent detections → reports/review.csv with
blank reviewer columns and the model's root cause hidden.
