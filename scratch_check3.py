import pandas as pd
import math

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

reg = pd.read_csv('data/station_registry.csv')
target = reg[reg['station_id'] == 'INI0000VEBN'].iloc[0]

found = False
for _, row in reg.iterrows():
    if row['station_id'] != target['station_id']:
        d = haversine(target['lat'], target['lon'], row['lat'], row['lon'])
        if d <= 250:
            print(f"{row['station_id']} is {d:.1f} km away")
            found = True

if not found:
    print("No neighbours found!")
