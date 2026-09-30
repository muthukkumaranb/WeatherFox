# SkyGuard Evaluation — Arms Side-by-Side Comparison

**Context:** Final test, run once: 2024 data + stations unseen in training, 375 GHCNh stations in India, 1,215,428 readings, 21,346 injected faults (synthetic injections on real observations). Trained detector (LightGBM forecaster + neighbour fusion + conformal alpha 0.001/0.01 per variable, calibrated on val_cal). Code: person-a e06b96b plus the fixes in 'Integrate the trained detector'. One CPU core in a cloud container, 3.21 ms/reading. Ingest-level faults (comms_gap, duplicate, power, timeshift; 7,600 events) are handled by the replay/ingest layer and are not scored by the batch scorer, so they count as misses for every arm. Recall counts 'anomaly' verdicts only.
**Git SHA:** `e06b96b6b7b98c95313bf574f577b43dbe70cd34` | **Split SHA256:** `229c3e71cc86b8e05f8948ec4f29f7e64319b078a21bb4ca63be2dee600b0ccd`

| Metric | skyguard | rules_only | zscore | isolation_forest |
|---| --- | --- | --- | --- |
| Total Fault Events | 21346 | 21346 | 21346 | 21346 |
| Event Recall | 0.1860 | 0.1486 | 0.2117 | 0.1430 |
| Incident Precision | 0.7007 | 0.5425 | 0.1817 | 0.1209 |
| F1 Score | **0.2940** | **0.2333** | **0.1956** | **0.1310** |
| Clean Anomaly Rate | 0.0011 | 0.0001 | 0.0357 | 0.0633 |
| Clean Uncertain Rate | 0.0442 | 0.0037 | 0.0000 | 0.0000 |
| Recall @ Alert Budget (<=0.05 FAs/st-day) | 0.1860 | 0.1486 | 0.0000 | 0.0000 |
| Genuine Event FA / 100 st-days | 2.08 | 0.07 | 143.89 | 108.00 |
