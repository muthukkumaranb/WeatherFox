import pandas as pd
from skyguard.scorer import score
import os

os.environ['SKYGUARD_SCORER'] = 'real'
df = pd.read_parquet('data/stream/injected_test.parquet')
reg = pd.read_csv('data/station_registry.csv')

# Drop lat lon if exists in df to avoid _x _y
if 'lat' in df.columns:
    df.drop(columns=['lat', 'lon'], inplace=True)

df = df.merge(reg[['station_id', 'lat', 'lon']], on='station_id')

hw = df[
    (df['ts_utc'] >= '2024-05-25') & 
    (df['ts_utc'] <= '2024-05-31') & 
    (df['T'] >= 45) & 
    (df['T'] <= 50) &
    (df['lat'] >= 20.0) & (df['lat'] <= 30.0) &
    (df['lon'] >= 70.0) & (df['lon'] <= 80.0)
]

print('Found', len(hw), 'rows in heat wave zone >= 45C')
if len(hw) > 0:
    r_hw = hw.iloc[0]
    sid = r_hw['station_id']
    rows = df[(df['station_id'] == sid) & (df['ts_utc'] <= r_hw['ts_utc'])].tail(25).copy()
    rows.drop(columns=['lat', 'lon', 'name'], errors='ignore', inplace=True)
    window = {sid: rows.to_dict('records')}
    v_hw = score(window, sid)
    print(f"Heat wave {r_hw['ts_utc']} T={r_hw['T']} -> label: {v_hw['label']} genuine: {v_hw['genuine_event']}")
