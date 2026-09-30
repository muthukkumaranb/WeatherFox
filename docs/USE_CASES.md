# WeatherFox Use Cases & System Architecture Specifications

WeatherFox (SIH26073) is an automated quality control system for temperature, humidity and pressure from India Meteorological Department (IMD) Automatic Weather Stations (AWS). Rainfall is out of scope.

---

## 1. Primary Deployment Use Cases

### UC-1: Real-Time Stream Quality Control & Sensor Fault Filtering
* **Goal**: Detect gross range errors, frozen sensor outputs, calibration drift, and step spikes in real-time telemetry streams before contaminated readings enter national numerical weather prediction (NWP) models.
* **Mechanism**: Ingested telemetry is processed through a fast, lightweight C rule gate and spatial-temporal window scorer. Anomalous values are flagged with exact root-cause classifications (`out_of_range`, `frozen`, `spike`, `radiation`, `comms_gap`).

### UC-2: Genuine Extreme Weather Event Protection
* **Goal**: Prevent false alarms during genuine regional weather events (e.g., severe heat waves, squalls, monsoonal pressure drops).
* **Mechanism**: When extreme readings (e.g., 47 °C) are corroborated across multiple spatial neighbours with matching anomaly directions, WeatherFox labels the reading as `normal` with `genuine_event = True` and spatial support `neighbours_also_deviating`.

### UC-3: Microcontroller / ESP32 Edge Quality Control
* **Goal**: Run low-power quality control on the station's data logger (e.g. ESP32) before satellite/cellular transmission. Status: C port done and tested on a laptop; not yet run on ESP32 hardware.
* **Mechanism**: The lightweight C rule gate (`rule_gate.o`, 4.3 KB) and exported sklearn decision tree (`tiny_tree.o`, 2.7 KB) run in about **2 µs per reading on a laptop CPU** (host estimate) with **100 % agreement (10,000/10,000)** with the server's Python rule gate.

---

## 2. Committed Benchmark Performance Metrics

### Network Scaling Benchmark (`reports/scale/results.json`)
Measured with the rule-based stand-in scorer on one Windows laptop core, 5,000 readings × 3 runs per network size.

* **100 Stations**: 74.82 readings/sec (p50: 12.93 ms, p95: 20.13 ms, RAM: 0.25 MB)
* **1,000 Stations**: 102.08 readings/sec (p50: 9.48 ms, p95: 13.14 ms, RAM: 0.34 MB)
* **10,000 Stations**: 117.60 readings/sec (p50: 7.89 ms, p95: 12.04 ms, RAM: 1.08 MB)

### Edge Hardware Benchmark (`reports/edge/edge.json`)
* **C Rule Gate Binary**: 4,288 B (4.3 KB)
* **Tiny Decision Tree Binary**: 2,664 B (2.7 KB)
* **Execution Latency**: 2.043 µs / reading (laptop CPU, gcc 13.3.0; not ESP32)
* **C vs Python Parity**: 10,000 / 10,000 (100.0%)
* **Edge Tree (held-out, synthetic faults)**: catches 74 % of faults at 84 % precision (accuracy 94.55 % with 88.5 % normal rows, so accuracy alone is misleading)

### Full Model Pipeline Evaluation
* **Status**: **pending final evaluation** (full ML detector evaluation pending final test completion).
