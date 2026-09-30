# WeatherFox (SIH26073) — 2-Minute Judge Walkthrough

**Start before the judges arrive:** `python -m skyguard.demo` (synthetic replay, 16 stations in 4 regional
clusters) or `python -m skyguard.demo --replay live` (IMD WIS 2.0 data fetched earlier with
`python -m skyguard.ingest.wis2 --hours 24`). Open `http://127.0.0.1:8000/`. The amber
"DEMO MODE · STAND-IN SCORER" badge must stay visible: it tells judges the rule-based stand-in scorer is
running, not the trained model. The dashboard needs no internet (fonts, icons, map and charts are local).
The previous dashboard is still at `/classic`.

Keep the demo on the stand-in scorer: the demo and live station IDs are not in the trained model's
registry, so `--scorer real` on them gives meaningless forecasts. The trained model's results are shown
on the Evaluation page.

---

### Step 1 — The problem (0:00 – 0:20)
* **Screen:** 01 Overview.
* **Say:** *"In May 2024 Delhi's Mungeshpur station reported 52.9 °C, and IMD later confirmed it was a
  sensor error. Faulty readings like that reach forecasts and headlines. WeatherFox checks every reading
  from every station and tells operators which ones to trust."*

### Step 2 — The network (0:20 – 0:35)
* **Screen:** 01 Overview map. Point at the clusters (Delhi NCR, Mumbai–Pune, Chennai, Kolkata) and the
  KPI tiles.
* **Say:** *"Each dot is a station, compared every hour with its own history and with its neighbours.
  WeatherFox also reads IMD's public WIS 2.0 feed — about 320 SYNOP stations reporting every three hours —
  and for history we use NOAA's GHCNh records for Indian stations."*

### Step 3 — A sensor fault (0:35 – 0:55)
* **Click:** 05 Simulation Lab → pick a station → **Temperature stuck at 55 °C** → **Inject into replay**.
  Within a few seconds the right panel shows **Flagged as sensor fault**. Click **Open incident**.
* **Say:** *"One sensor jumps to 55 °C while its neighbours stay normal. The incident panel answers four
  questions: what happened, why it was flagged, how sure the system is, and what to do — all taken from
  the verdict itself."* Press **Acknowledge**.

### Step 4 — Real weather is protected (0:55 – 1:15)
* **Click:** 05 Simulation Lab → **Real heat wave (station + neighbours)** → **Inject into replay**.
  The panel shows **Protected as real weather**; on 01 Overview the stations turn blue with a dashed ring.
* **Say:** *"Now a heat wave hits a whole cluster. The scorer sees the neighbours moving together and marks
  it as real weather — no false alarm. That is the hardest part of this problem: a heat wave and a broken
  sensor can show the same number."*

### Step 5 — Your own data (1:15 – 1:35)
* **Click:** 05 Simulation Lab → **Sample CSV** (last 24 real replay readings with one 55 °C value) →
  drop it back into the upload box.
* **Say:** *"Operators can score any CSV. Here 24 readings go in and exactly the one bad value comes out,
  with its reason."*

### Step 6 — Honest numbers (1:35 – 2:00)
* **Click:** 06 Evaluation.
* **Say:** *"Everything on this page is read from the report files the code produced. The trained model
  was tested once on 2024 data and stations it never saw, against three baselines on the same rows. It has
  the best F1 and precision and is the only arm besides plain rules that stays within the alert budget.
  Humidity faults and slow drift are still weak, and the page says so. The C rule gate for stations is
  measured on a laptop CPU, not yet on ESP32 hardware."*

---

**If asked "is this your model?"** — *"The live demo runs the stand-in scorer, shown in the badge, because
the demo stations are not in the trained model's station registry. The trained LightGBM model plugs into
the same interface; its final-test results are on the Evaluation page."*
