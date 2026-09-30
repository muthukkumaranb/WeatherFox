# WeatherFox (SkyGuard AI) — Judge Q&A Reference Guide

15 likely questions from SIH hackathon judges with short, direct, and transparent answers.

---

### Q1: What data sources does WeatherFox use, and what are its boundaries?
**A**: WeatherFox is evaluated on GHCNh (Global Historical Climatology Network hourly) synoptic and airport observations across India, supplemented by ASOS 1-minute validation datasets. It is evaluated on public synoptic stations, not proprietary internal IMD hardware streams.

---

### Q2: What is the current status of the machine learning detector models?
**A**: Full ML detector model evaluation is **pending final evaluation**. The system currently uses the fast C rule gate and `fake_score` detector engine for demonstration and contract verification, with model evaluation scripts ready to run when final model weights are merged.

---

### Q3: How does WeatherFox distinguish a real heat wave from a broken sensor?
**A**: Through spatial-temporal neighbour corroboration. If a single station reports 47 °C while surrounding stations report 30 °C, WeatherFox flags a sensor fault. If surrounding stations within 150–200 km also show matching warm anomalies, WeatherFox protects the reading as a genuine extreme weather event (`genuine_event = True`).

---

### Q4: How does WeatherFox minimize the false-alarm rate during sudden weather changes?
**A**: By combining a fast rule gate with multi-station spatial context and conformal prediction bounds. Isolated single-reading jumps trigger soft `suspect` flags first; hard `anomaly` alerts require spatial divergence or persistent physical bound violations.

---

### Q5: What edge microcontrollers are supported, and how is the edge C code compiled?
**A**: The core quality control logic is written in pure C99 (`rule_gate.c` and `tiny_tree.c`). It is designed to compile directly onto ESP32 and STM32 microcontrollers using standard GCC cross-compilers with zero external dependencies.

---

### Q6: What are the exact binary memory footprints on edge hardware?
**A**: As measured in `reports/edge/edge.json`: `rule_gate.o` compiles to **4,288 Bytes (4.3 KB)** and `tiny_tree.o` compiles to **2,664 Bytes (2.7 KB)**, easily fitting within ESP32 SRAM (520 KB available).

---

### Q7: What is the execution speed of the edge C code?
**A**: Host-measured benchmarking in `reports/edge/edge.json` demonstrates **2.043 µs per reading** (GCC 13.3.0 host estimate), enabling sub-millisecond real-time filtering directly on data loggers.

---

### Q8: Does the C edge code produce the exact same results as the Python cloud pipeline?
**A**: Yes. Verification testing across 10,000 synthetic reading windows demonstrates **10,000 / 10,000 (100.0%) exact parity** between C `rg_check()` and Python `rule_gate.check()`.

---

### Q9: How well does the edge decision tree perform on fault classification?
**A**: The 6-depth decision tree (`tiny_tree.c`) achieves **0.9455 (94.55%) held-out accuracy** on synthetic weather fault datasets containing spikes, frozen readings, calibration drifts, and dewpoint anomalies.

---

### Q10: How scalable is the cloud pipeline for nationwide AWS networks?
**A**: In-process scale testing (`reports/scale/results.json`) demonstrates **117.60 readings/sec** throughput for a 10,000-station network with **7.89 ms p50 latency** and **1.08 MB peak RAM**, exceeding IMD's hourly reporting throughput requirement (2.78 readings/sec) by over 40x.

---

### Q11: How does WeatherFox handle missing or corrupted data values?
**A**: Telemetry rows with missing parameters (e.g. null temperature or missing dewpoint) pass schema validation without crashing. Missing readings trigger `comms_gap` verdicts, prompting maintenance action without corrupting spatial median calculations.

---

### Q12: How does WeatherFox detect daytime solar heating error (radiation shield fault)?
**A**: By evaluating daytime positive temperature residuals relative to spatial neighbours while verifying that nighttime temperature residuals return to zero, matching the physical signature of an unventilated solar radiation shield.

---

### Q13: Can WeatherFox ingest live WMO WIS 2.0 data streams?
**A**: Yes. WeatherFox includes a native WIS 2.0 ingest client (`skyguard.ingest.wis2`) that fetches live synoptic observations from IMD's WIS 2.0 nodes via OGC Environmental Data Retrieval (EDR) APIs.

---

### Q14: How does an operator interact with WeatherFox alerts?
**A**: Operators use the glassmorphic web dashboard to view live network maps and alert inboxes. Operators can inspect explainability feature contributions (e.g., residual magnitude) and acknowledge, resolve, or reject flags via the `/alerts/{id}/ack` REST API.

---

### Q15: How can WeatherFox be deployed operationally within IMD infrastructure?
**A**: WeatherFox supports dual-mode deployment: (1) **Edge mode** flashed directly to ESP32 AWS data loggers for zero-latency pre-transmission filtering, and (2) **Central mode** deployed as containerized FastAPI microservices consuming WIS 2.0 / MQTT telemetry streams.
