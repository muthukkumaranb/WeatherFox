# WeatherFox (SkyGuard AI - SIH26073) — 2-Minute Judge Walkthrough Script

**Speaker Role**: Presenter / Demo Lead  
**App URL**: `http://localhost:8000/` (or dashboard landing page)

---

### Step 1 — The Mungeshpur Hook (0:00 - 0:20)
* **Action (Click)**: Open `http://localhost:8000/` landing page showing the Mungeshpur 52.9 °C headline banner.
* **Sentence to Say**: *"On May 29, 2024, IMD's Mungeshpur station reported an unprecedented 52.9 °C in Delhi—triggering headlines worldwide before an IMD investigation revealed a 3 °C sensor calibration drift. WeatherFox was built to catch these sensor faults in real time before they contaminate weather products."*

---

### Step 2 — Live Spatial Map & Real-Time Stream (0:20 - 0:40)
* **Action (Click)**: Click **"Live Network Map"** in the top navigation bar to view real-time station markers across India.
* **Sentence to Say**: *"WeatherFox ingests high-frequency surface observations across IMD AWS/ARG networks and WIS 2.0 nodes, continually validating incoming readings against spatial neighbours and physical bounds."*

---

### Step 3 — Single Station 55 °C Fault Injection (0:40 - 1:00)
* **Action (Click)**: Click **"Inject Fault"** dropdown -> select **"55.0 °C Sensor Spike"** on station `sA` -> click **"Apply Injection"**.
* **Sentence to Say**: *"When a single sensor spikes to an unphysical 55 °C while surrounding stations remain at 30 °C, WeatherFox instantly flags an out-of-range anomaly with full explainability reasons."*

---

### Step 4 — Genuine Heat Wave Protection (1:00 - 1:20)
* **Action (Click)**: Click **"Preset Scenarios"** -> select **"NW India Heat Wave May 2024"** -> click **"Run Scenario"**.
* **Sentence to Say**: *"Crucially, when extreme 47 °C heat is corroborated across neighbouring stations during a regional heat wave, WeatherFox protects the reading as a genuine extreme weather event without raising a false alarm."*

---

### Step 5 — Radiation Shield Heating Fault (1:20 - 1:40)
* **Action (Click)**: Click **"Inject Fault"** -> select **"Daytime Radiation Bias"** -> view the **Alert Details** card.
* **Sentence to Say**: *"For subtle daytime-only solar heating errors, WeatherFox detects radiation shield bias and automatically generates a spatial median correction."*

---

### Step 6 — Edge Hardware & Scale Benchmark (1:40 - 2:00)
* **Action (Click)**: Click **"Benchmark & Scale"** in the navigation bar to open the performance dashboard.
* **Sentence to Say**: *"WeatherFox scales to 10,000 stations with 117 readings per second on host CPU and deploys tiny decision trees directly to ESP32 edge microcontrollers in 4.2 KB of memory with 2 µs latency per reading."*
