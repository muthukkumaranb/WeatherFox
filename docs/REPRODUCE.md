# REPRODUCE.md — WeatherFox (SIH26073) Reproducibility Guide

## Quick Start

```bash
# Clone & install (Python 3.10+ required)
git clone https://github.com/muthukkumaranb/WeatherFox.git
cd WeatherFox
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt

# Run the full reproducibility check (skip demo)
python scripts/reproduce.py --no-demo
```

---

## Commands by Platform

### Windows (PowerShell)

```powershell
# 1. Install dependencies
.venv\Scripts\activate
pip install -r requirements.txt

# 2. Run all tests
.venv\Scripts\python.exe -m pytest -q

# 3. Scale test (SKYGUARD_SCORER=fake, ~3-10 minutes for 10,000 stations)
$env:SKYGUARD_SCORER="fake"
.venv\Scripts\python.exe skyguard/eval/scale.py
# Results written to: reports/scale/results.json and reports/scale/scale.png

# 4. WIS2 ingest (requires internet)
.venv\Scripts\python.exe -m skyguard.ingest.wis2 --hours 1 --out /tmp/wis2.jsonl

# 5. Start the demo (synthetic mode, no real data required)
.venv\Scripts\python.exe -m skyguard.demo --synthetic
# Open http://localhost:8000 in browser

# 6. Upload/judge endpoint
#    POST http://localhost:8000/upload/score with a CSV file
#    See dashboard: http://localhost:8000/upload.html

# 7. Edge code (needs gcc — Linux only, see below)
# scripts/edge_measure.sh
```

### Linux / Codespaces / WSL

```bash
# 1. Install dependencies
source .venv/bin/activate
pip install -r requirements.txt

# 2. Run all tests
python -m pytest -q

# 3. Scale test
SKYGUARD_SCORER=fake python skyguard/eval/scale.py
# Results: reports/scale/results.json, reports/scale/scale.png

# 4. WIS2 ingest (requires internet)
python -m skyguard.ingest.wis2 --hours 1 --out /tmp/wis2.jsonl

# 5. Start demo (synthetic mode)
python -m skyguard.demo --synthetic

# 6. Edge code (requires gcc)
bash scripts/edge_measure.sh
# Results: reports/edge/edge.json
```

---

## Python Version

| Tested on | Notes |
|-----------|-------|
| Python 3.10 | Fully supported |
| Python 3.11 | Fully supported |
| Python 3.12 | Fully supported |
| Python 3.13 | Supported; some DLL restrictions on managed Windows |

---

## Expected Outputs

### `python -m pytest -q`
```
XX passed in Ys
```
All tests should pass. See [tests/](tests/) for the full suite.

### `python skyguard/eval/scale.py`
Writes:
- `reports/scale/results.json` — latency, throughput, memory per network size
- `reports/scale/scale.png` — chart of readings/s and p95 latency vs. stations

Example `results.json` excerpt:
```json
{
  "100": {
    "n_readings": 5000,
    "required_rate_per_sec": 0.0278,
    "readings_per_sec_mean": 1234.5,
    "p95_ms_mean": 1.23
  }
}
```

### `python scripts/reproduce.py --no-demo`
Prints a checklist:
```
  ✓ pytest               [PASS]  42 passed in 12.3s
  ⚠ wis2_ingest         [SKIP]  Network not reachable
  ✓ scale_test           [PASS]  results.json written to ...
  ⚠ demo_server         [SKIP]  --no-demo flag set
```

---

## Known Limits

| Limit | Description |
|-------|-------------|
| **No ESP32 hardware** | `reports/edge/edge.json` is produced only where gcc exists (the committed one was measured on Linux x86-64 with gcc 13.3). On Windows without gcc, run `scripts/edge_measure.sh` in a Codespace or WSL. The label in the JSON reads "host-measured estimate, not ESP32 hardware". |
| **Fake scorer** | Until the real ML model is merged (Person A's branch), `SKYGUARD_SCORER=fake` is used. The fake scorer is deterministic and validates the contract, but produces synthetic anomaly labels. |
| **WIS2 network** | The WIS2 ingest step requires internet access to `api.weather.gc.ca`. It is automatically skipped if offline. |
| **Pandas blocked** | On managed Windows machines with Application Control policies, `pandas` may be blocked. The upload endpoint uses only stdlib `csv`; no pandas required. |
| **10,000-station scale** | The neighbour-precompute step for 10,000 stations (O(n²) distance matrix) may take 2-5 minutes. The scale test auto-reduces to 2,000 readings/size if total estimated time exceeds 5 minutes. |

---

## Architecture Reference

```
skyguard/
  api/
    main.py        FastAPI app (Person B)
    upload.py      CSV upload & judge endpoint (Person C)
  contract.py      Shared schema & validation
  ingest/
    rule_gate.py   Python rule gate (gross range, frozen, step)
    replay.py      Historical replay stream
  scorer.py        Score dispatcher (fake / real)
  fake_score.py    Fake scorer for development
  eval/
    scale.py       Scale / throughput test (Person C)
  edge/
    export.py      sklearn → tiny_tree.c generator (Person C)
    build_host.py  gcc compile + parity check (Person C)
    c/             C source for ESP32 deployment
dashboard/
  index.html       Main dashboard
  upload.html      Data upload page
reports/
  scale/           Scale test outputs
  edge/            Edge benchmark (needs gcc)
scripts/
  reproduce.py     One-command reproducibility (this guide)
  edge_measure.sh  Edge build script (Linux)
```
