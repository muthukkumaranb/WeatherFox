import json
from pathlib import Path

# Datasheet figures (ESP32 / typical cellular modem)
I_DEEP_SLEEP_MA = 0.01  # 10 uA
I_MODEM_SLEEP_MA = 20.0 # 20 mA
I_ACTIVE_MA = 40.0      # 40 mA
I_TX_WIFI_MA = 240.0    # 240 mA
I_TX_GPRS_MA = 400.0    # 400 mA (average during burst)

# Battery
BATT_CAPACITY_MAH = 3000.0
BATT_VOLTAGE = 3.7

def calculate_energy():
    # Fixed 15-min reporting
    reports_per_hour = 4
    tx_seconds_per_report = 2.0
    active_seconds_per_report = 1.0
    
    total_tx_sec = reports_per_hour * tx_seconds_per_report
    total_active_sec = reports_per_hour * active_seconds_per_report
    total_sleep_sec = 3600 - total_tx_sec - total_active_sec
    
    avg_ma_fixed = (total_tx_sec * I_TX_GPRS_MA + total_active_sec * I_ACTIVE_MA + total_sleep_sec * I_DEEP_SLEEP_MA) / 3600.0
    life_days_fixed = BATT_CAPACITY_MAH / (avg_ma_fixed * 24)
    
    # Adaptive: 15-min calm, but assume 1 local anomaly per day causing 2h of 1-min reporting
    # Over 24 hours: 22h calm (4 reports/h) + 2h active (60 reports/h)
    daily_reports_adaptive = 22 * 4 + 2 * 60
    reports_per_hour_adaptive = daily_reports_adaptive / 24.0
    
    total_tx_sec_adapt = reports_per_hour_adaptive * tx_seconds_per_report
    total_active_sec_adapt = reports_per_hour_adaptive * active_seconds_per_report
    total_sleep_sec_adapt = 3600 - total_tx_sec_adapt - total_active_sec_adapt
    
    avg_ma_adaptive = (total_tx_sec_adapt * I_TX_GPRS_MA + total_active_sec_adapt * I_ACTIVE_MA + total_sleep_sec_adapt * I_DEEP_SLEEP_MA) / 3600.0
    life_days_adaptive = BATT_CAPACITY_MAH / (avg_ma_adaptive * 24)
    
    return {
        "note": "estimated from datasheet figures",
        "fixed_15m": {
            "radio_on_seconds_per_hour": float(total_tx_sec),
            "average_current_mA": float(avg_ma_fixed),
            "battery_life_days": float(life_days_fixed)
        },
        "adaptive_anomaly": {
            "radio_on_seconds_per_hour": float(total_tx_sec_adapt),
            "average_current_mA": float(avg_ma_adaptive),
            "battery_life_days": float(life_days_adaptive)
        }
    }

def main():
    root = Path(__file__).resolve().parent.parent.parent
    out_dir = root / "reports" / "edge"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    data = calculate_energy()
    with open(out_dir / "energy.json", "w") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote energy.json")

if __name__ == "__main__":
    main()
