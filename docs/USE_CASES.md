# WeatherFox Use Cases & System Architecture Specifications

WeatherFox (SkyGuard AI - SIH26073) is an automated quality control system designed for India Meteorological Department (IMD) Automatic Weather Stations (AWS) and Automatic Rain Gauges (ARG).

---

## 1. Primary Deployment Use Cases

### UC-1: Real-Time Stream Quality Control & Sensor Fault Filtering
* **Goal**: Detect gross range errors, frozen sensor outputs, calibration drift, and step spikes in real-time telemetry streams before contaminated readings enter national numerical weather prediction (NWP) models.
* **Mechanism**: Ingested telemetry is processed through a fast, lightweight C rule gate and spatial-temporal window scorer. Anomalous values are flagged with exact root-cause classifications (`out_of_range`, `frozen`, `spike`, `radiation`, `comms_gap`).

### UC-2: Genuine Extreme Weather Event Protection
* **Goal**: Prevent false alarms during genuine regional weather events (e.g., severe heat waves, squalls, monsoonal pressure drops).
* **Mechanism**: When extreme readings (e.g., 47 °C) are corroborated across multiple spatial neighbours with matching anomaly directions, WeatherFox labels the reading as `normal` with `genuine_event = True` and spatial support `neighbours_also_deviating`.

### UC-3: Microcontroller / ESP32 Edge Quality Control
* **Goal**: Run low-power, zero-latency quality control directly on AWS data logger hardware (e.g. ESP32 microcontrollers) prior to satellite/cellular transmission.
* **Mechanism**: The lightweight C rule gate (`rule_gate.o`, 4.3 KB) and exported sklearn decision tree (`tiny_tree.o`, 2.7 KB) execute in **2.043 µs per reading** with **100% agreement (10,000/10,000 parity)** with Python cloud logic.

---

## 2. Committed Benchmark Performance Metrics

### Network Scaling Benchmark (`reports/scale/results.json`)
* **100 Stations**: 74.82 readings/sec (p50: 12.93 ms, p95: 20.13 ms, RAM: 0.25 MB)
* **1,000 Stations**: 102.08 readings/sec (p50: 9.48 ms, p95: 13.14 ms, RAM: 0.34 MB)
* **10,000 Stations**: 117.60 readings/sec (p50: 7.89 ms, p95: 12.04 ms, RAM: 1.08 MB)

### Edge Hardware Benchmark (`reports/edge/edge.json`)
* **C Rule Gate Binary**: 4,288 B (4.3 KB)
* **Tiny Decision Tree Binary**: 2,664 B (2.7 KB)
* **Execution Latency**: 2.043 µs / reading (GCC 13.3.0 host estimate)
* **C vs Python Parity**: 10,000 / 10,000 (100.0%)
* **Edge Tree Held-Out Accuracy**: 0.9455 (94.55% on synthetic fault dataset)

### Full Model Pipeline Evaluation
* **Status**: **pending final evaluation** (full ML detector evaluation pending final test completion).
