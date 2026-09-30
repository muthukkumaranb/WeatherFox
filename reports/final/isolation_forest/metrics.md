# SkyGuard Evaluation Metrics Report

## Summary & Headline Metrics

| Metric | Value |
|---|---|
| Total Fault Events | 21346 |
| Event-wise Recall | 0.1430 |
| Incident-wise Precision | 0.1209 |
| **F1 Score** | **0.1310** |
| False Alarm Incidents / 100 station-days | 20.52 |
| Recall @ Alert Budget (0.05 FAs/st-day) | **0.0000** |
| Clean False Alarm Rate | 0.0633 (61658/974431) |
| Clean Uncertain Rate | 0.0000 (0/974431) |
| Genuine Event FA / 100 station-days | 108.00 |

## Per-Class Breakdown (Variable x Root Cause)

| Class | Events | Detected | Recall | Delay p50 (s) | Delay p90 (s) |
|---|---|---|---|---|---|
| P x offset | 551 | 0 | 0.00% | N/A | N/A |
| RH x out_of_range | 606 | 0 | 0.00% | N/A | N/A |
| T x noise | 890 | 600 | 67.42% | 5400.0 | 32400.0 |
| all x power | 1916 | 0 | 0.00% | N/A | N/A |
| T x frozen | 569 | 96 | 16.87% | 18000.0 | 64800.0 |
| all x timeshift | 1914 | 0 | 0.00% | N/A | N/A |
| P x spike | 622 | 0 | 0.00% | N/A | N/A |
| RH x spike | 622 | 0 | 0.00% | N/A | N/A |
| T x spike | 623 | 611 | 98.07% | 0.0 | 0.0 |
| P x frozen | 619 | 0 | 0.00% | N/A | N/A |
| T x radiation | 1750 | 348 | 19.89% | 5400.0 | 32400.0 |
| T x out_of_range | 568 | 558 | 98.24% | 0.0 | 0.0 |
| all x comms_gap | 1887 | 0 | 0.00% | N/A | N/A |
| RH x unknown | 786 | 0 | 0.00% | N/A | N/A |
| all x duplicate | 1883 | 0 | 0.00% | N/A | N/A |
| T x unknown | 876 | 302 | 34.47% | 19800.0 | 66600.0 |
| T x offset | 509 | 282 | 55.40% | 1800.0 | 72000.0 |
| RH x frozen | 541 | 0 | 0.00% | N/A | N/A |
| RH x offset | 532 | 0 | 0.00% | N/A | N/A |
| P x out_of_range | 651 | 0 | 0.00% | N/A | N/A |
| RH x drift | 803 | 0 | 0.00% | N/A | N/A |
| T x drift | 739 | 256 | 34.64% | 36000.0 | 147600.0 |
| RH x noise | 889 | 0 | 0.00% | N/A | N/A |

## Genuine Events Breakdown

| Event | Stations in BBox | Station-Days | FA Incidents | FA / 100 Station-Days | Genuine Event Flag Share | Skipped (No Coords) |
|---|---|---|---|---|---|---|
| heatwave_nw_india_2024 | 95 | 760.0 | 1472 | 193.68 | 0.0% | 0 |
| cyclone_remal_2024 | 44 | 176.0 | 184 | 104.55 | 0.0% | 0 |
| cyclone_fengal_2024 | 43 | 215.0 | 14 | 6.51 | 0.0% | 0 |
| fog_igp_jan_2024 | 84 | 1596.0 | 1342 | 84.09 | 0.0% | 0 |
| cyclone_michaung_2023 | 7 | 42.0 | 0 | 0.00 | 0.0% | 0 |

## Sensor Drift Detection Delay

| Drift Rate Bin | Events | Median Delay (Days) |
|---|---|---|
| <0.03 °C/day | 0 | N/A |
| 0.03–0.1 °C/day | 1542 | 0.42 |
| >0.1 °C/day | 0 | N/A |
