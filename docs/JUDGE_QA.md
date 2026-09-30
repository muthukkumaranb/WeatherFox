# WeatherFox — Judge Q&A Reference Guide

15 likely questions from SIH hackathon judges with short, direct, and transparent answers.

---

### Q1: What data sources does WeatherFox use, and what are its boundaries?
**A**: History comes from NOAA GHCNh (hourly synoptic and airport observations for Indian stations); live data comes from IMD's public WIS 2.0 feed (about 320 SYNOP stations, every 3 hours). Sensor faults are injected synthetically for training and testing. We have not used IMD's internal AWS streams; validating on them is the next step.

---

### Q2: What is the current status of the machine learning detector models?
**A**: Full ML detector model evaluation is **pending final evaluation**. The system currently uses the fast C rule gate and `fake_score` detector engine for demonstration and contract verification, with model evaluation scripts ready to run when final model weights are merged.

---

### Q3: How does WeatherFox distinguish a real heat wave from a broken sensor?
**A**: Through spatial-temporal neighbour corroboration. If a single station reports 47 °C while surrounding stations report 30 °C, WeatherFox flags a sensor fault. If surrounding stations within 150–200 km also show matching warm anomalies, WeatherFox protects the reading as a genuine extreme weather event (`genuine_event = True`).

---

### Q4: How does WeatherFox minimize the false-alarm rate during sudden weather changes?
**A**: The rule gate only hard-fails physically impossible values; step and frozen checks raise `suspect`. Alerts need disagreement with neighbours at the same timestamp, and changes shared by neighbours are treated as weather. In the trained model, conformal p-values set the alert threshold (designed; results pending).

---

### Q5: What edge microcontrollers are supported, and how is the edge C code compiled?
**A**: The rule gate and decision tree are plain C (`rule_gate.c`, `tiny_tree.c`) with no dependencies, compiled and tested on a laptop with gcc. An Arduino/ESP32 sketch is included, but the code has not yet been built or run on ESP32 hardware.

---

### Q6: What are the exact binary memory footprints on edge hardware?
**A**: As measured in `reports/edge/edge.json`: `rule_gate.o` compiles to **4,288 Bytes (4.3 KB)** and `tiny_tree.o` compiles to **2,664 Bytes (2.7 KB)**, which fits easily in ESP32 flash (compiled on x86-64; ESP32 size not yet measured).

---

### Q7: What is the execution speed of the edge C code?
**A**: Host-measured benchmarking in `reports/edge/edge.json` demonstrates **2.043 µs per reading** on a laptop CPU (gcc 13.3.0, upper bound including process start). This is a host estimate; ESP32 timing has not been measured.

---

### Q8: Does the C edge code produce the exact same results as the Python cloud pipeline?
**A**: Yes. Verification testing across 10,000 synthetic reading windows demonstrates **10,000 / 10,000 (100.0%) exact parity** between C `rg_check()` and Python `rule_gate.check()`.

---

### Q9: How well does the edge decision tree perform on fault classification?
**A**: On a held-out split of synthetic data with injected spikes, frozen readings, drift/offset and dew-point faults, the depth-6 tree catches **74 % of faults with 84 % precision**. Overall accuracy is 94.55 %, but 88.5 % of rows are normal, so accuracy alone is misleading.

---

### Q10: How scalable is the cloud pipeline for nationwide AWS networks?
**A**: `reports/scale/results.json`: with 10,000 synthetic stations the server processes **117.6 readings/s** (p50 7.9 ms) on one Windows laptop core using the rule-based stand-in scorer — about 40× the 2.8 readings/s that 10,000 stations reporting hourly would need. The trained model's speed will be measured separately.

---

### Q11: How does WeatherFox handle missing or corrupted data values?
**A**: Telemetry rows with missing parameters (e.g. null temperature or missing dewpoint) pass schema validation without crashing. Missing readings trigger `comms_gap` verdicts, prompting maintenance action without corrupting spatial median calculations.

---

### Q12: How does WeatherFox detect daytime solar heating error (radiation shield fault)?
**A**: By evaluating daytime positive temperature residuals relative to spatial neighbours while verifying that nighttime temperature residuals return to zero, matching the physical signature of an unventilated solar radiation shield.

---

### Q13: Can WeatherFox ingest live WMO WIS 2.0 data streams?
**A**: Yes. WeatherFox includes a native WIS 2.0 ingest client (`skyguard.ingest.wis2`) that fetches live synoptic observations from IMD's WIS 2.0 nodes via its OGC API endpoint (`wis2box.imd.gov.in/oapi`), converting units and checking plausibility.

---

### Q14: How does an operator interact with WeatherFox alerts?
**A**: Operators use the glassmorphic web dashboard to view live network maps and alert inboxes. Operators can inspect explainability feature contributions (e.g., residual magnitude) and acknowledge, resolve, or reject flags via the `/alerts/{id}/ack` REST API.

---

### Q15: How can WeatherFox be deployed operationally within IMD infrastructure?
**A**: WeatherFox supports dual-mode deployment: (1) **Central mode**: the FastAPI service consuming WIS 2.0 (working today) or MQTT/HTTP/CSV feeds; and (2) **Edge mode**: the C rule gate on station data loggers before transmission (ported and tested on a laptop; not yet deployed on hardware).
