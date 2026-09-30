# WeatherFox (SIH26073) — 2-Minute Judge Walkthrough

**Start before the judges arrive:** `python -m skyguard.demo` (synthetic replay, 16 stations in 4 regional
clusters) or `python -m skyguard.demo --replay live` (IMD WIS 2.0 data fetched earlier with
`python -m skyguard.ingest.wis2 --hours 24`). Open `http://127.0.0.1:8000/`. The amber banner
"DEMO MODE: fake scorer" must stay visible: it tells judges the rule-based stand-in scorer is running,
not the trained model.

---

### Step 1 — The problem (0:00 – 0:20)
* **Screen:** Live Map tab.
* **Say:** *"In May 2024 Delhi's Mungeshpur station reported 52.9 °C, and IMD later confirmed it was a
  sensor error. Faulty readings like that reach forecasts and headlines. WeatherFox checks every reading
  from every station and tells operators which ones to trust."*

### Step 2 — The live network (0:20 – 0:35)
* **Screen:** Live Map. Point at the station clusters (Delhi NCR, Mumbai–Pune, Chennai, Kolkata).
* **Say:** *"Each dot is a station, compared every hour with its own history and with its neighbours.
  WeatherFox also reads IMD's public WIS 2.0 feed — about 320 SYNOP stations reporting every three hours —
  and for history we use NOAA's GHCNh records for Indian stations."*

### Step 3 — A sensor fault (0:35 – 0:55)
* **Click:** **⚡ Fault Injector** tab → **⚡ Inject 55 °C Sensor Fault** → back to **🗺️ Live Map**
  (the station turns red) → **🚨 Alerts**.
* **Say:** *"One sensor jumps to 55 °C while its neighbours stay normal. WeatherFox raises an alert with the
  cause — out of range — the reason, and what the operator should do."*

### Step 4 — Real weather is protected (0:55 – 1:15)
* **Click:** **⚡ Fault Injector** → **🌪️ Inject Genuine Storm** → **🗺️ Live Map**
  (the station and its neighbours turn blue, no red).
* **Say:** *"Now a heat wave hits a whole cluster. The scorer sees the neighbours moving together and marks
  it as genuine weather — no false alarm. That is the hardest part of this problem: a heat wave and a
  broken sensor can show the same number."*

### Step 5 — A subtle fault (1:15 – 1:35)
* **Click:** **⚡ Fault Injector** → **🌡️ Mungeshpur Shield Heating**, then open the station
  (**View 48h Series** on its map marker).
* **Say:** *"The hard faults are subtle: a badly ventilated radiation shield adds a few degrees only in
  sunlight. WeatherFox flags a warm bias that appears by day and disappears at night, and shows a
  corrected value from the neighbours."*

### Step 6 — Honest numbers (1:35 – 2:00)
* **Click:** **📊 Benchmark** tab.
* **Say:** *"Everything here comes from files the code produced. The rule gate is ported to C for ESP32
  stations: about 7 KB of code, around 2 microseconds per reading measured on a laptop CPU, identical
  results to the server on 10,000 readings — not yet run on ESP32 hardware. The server handles 10,000
  stations on one laptop core, about 40 times the rate hourly reporting needs. The trained model's
  results are marked pending until its final test is complete."*

---

**If asked "is this your model?"** — *"The demo runs the rule-based stand-in scorer, shown in the banner.
The trained LightGBM model plugs into the same interface; its evaluation is in progress and we only show
numbers from completed runs."*
