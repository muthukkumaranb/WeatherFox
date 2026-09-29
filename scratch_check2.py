import pandas as pd
from skyguard.scorer import score
import os

os.environ['SKYGUARD_SCORER'] = 'real'
df = pd.read_parquet('data/stream/injected_test.parquet')

# Get heat wave rows
hw = df[(df['ts_utc'] == '2024-05-30T06:00:00Z') & (df['T'] >= 45.0)]
if len(hw) > 0:
    r_hw = hw.iloc[0]
    target_sid = r_hw['station_id']
    ts = r_hw['ts_utc']
    
    # Get all stations up to this timestamp
    history = df[df['ts_utc'] <= ts].copy()
    history.drop(columns=['lat', 'lon', 'name'], errors='ignore', inplace=True)
    
    window = {}
    for sid, group in history.groupby('station_id'):
        window[sid] = group.tail(25).to_dict('records')
        
    v_hw = score(window, target_sid)
    print(f"Heat wave {ts} T={r_hw['T']} at {target_sid}")
    print(f"Verdict label: {v_hw['label']}")
    print(f"Verdict genuine_event: {v_hw['genuine_event']}")
    print(f"Verdict spatial_support: {v_hw['spatial_support']}")

# 70C injection
inj = df[df['T'] == 70.0]
if len(inj) > 0:
    r_inj = inj.iloc[0]
    target_sid = r_inj['station_id']
    ts = r_inj['ts_utc']
    
    history = df[df['ts_utc'] <= ts].copy()
    history.drop(columns=['lat', 'lon', 'name'], errors='ignore', inplace=True)
    
    window = {}
    for sid, group in history.groupby('station_id'):
        window[sid] = group.tail(25).to_dict('records')
        
    v_inj = score(window, target_sid)
    print(f"\nInjection {ts} T={r_inj['T']} at {target_sid}")
    print(f"Verdict label: {v_inj['label']}")
    print(f"Verdict genuine_event: {v_inj['genuine_event']}")
    print(f"Verdict spatial_support: {v_inj['spatial_support']}")
