import json
import csv
import os
import math
import re
from pathlib import Path

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def main():
    registry_path = Path("data/station_registry.csv")
    ghcn_stations = {}
    ghcn_by_wmo = {}
    
    with open(registry_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = row["station_id"]
            lat = float(row["lat"])
            lon = float(row["lon"])
            ghcn_stations[sid] = (lat, lon)
            
            m = re.search(r'\d{5}$', sid)
            if m:
                wmo_id = m.group(0)
                ghcn_by_wmo[wmo_id] = sid
                
    wigos_coords = {}
    for filename in ["live_page.json", "raw_page1.json", "raw_page2.json"]:
        filepath = Path("data/wis2") / filename
        if not filepath.exists():
            continue
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            for feat in data.get("features", []):
                w_id = feat.get("properties", {}).get("wigos_station_identifier")
                geom = feat.get("geometry")
                coords = geom.get("coordinates") if geom else None
                if w_id and coords and len(coords) >= 2:
                    wigos_coords[w_id] = (coords[1], coords[0]) # lat, lon
                    
    input_file = Path("data/stream/wis2_latest.jsonl")
    unique_wigos = set()
    with open(input_file, "r", encoding="utf-8") as fin:
        for line in fin:
            row = json.loads(line)
            w_id = row.get("station_id")
            if w_id:
                unique_wigos.add(w_id)
                
    matched_wmo = 0
    matched_dist = 0
    unmatched = 0
    
    out_file = Path("data/wis2/wis2_to_ghcnh.csv")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(out_file, "w", encoding="utf-8", newline="") as fout:
        writer = csv.writer(fout)
        writer.writerow(["wigos_id", "wmo_index", "ghcnh_id", "distance_km", "method"])
        
        for w_id in sorted(unique_wigos):
            parts = w_id.split("-")
            wmo_index = parts[-1] if len(parts) >= 4 else ""
            
            if wmo_index in ghcn_by_wmo:
                ghcn_id = ghcn_by_wmo[wmo_index]
                
                # calc distance if we have coords
                dist_km = ""
                if w_id in wigos_coords:
                    w_lat, w_lon = wigos_coords[w_id]
                    g_lat, g_lon = ghcn_stations[ghcn_id]
                    dist_km = round(haversine(w_lat, w_lon, g_lat, g_lon), 3)
                    
                writer.writerow([w_id, wmo_index, ghcn_id, dist_km, "WMO"])
                matched_wmo += 1
                continue
                
            # fallback to distance
            if w_id in wigos_coords:
                w_lat, w_lon = wigos_coords[w_id]
                best_dist = float('inf')
                best_ghcn = None
                
                for g_id, (g_lat, g_lon) in ghcn_stations.items():
                    d = haversine(w_lat, w_lon, g_lat, g_lon)
                    if d < best_dist:
                        best_dist = d
                        best_ghcn = g_id
                        
                if best_dist <= 5.0:
                    writer.writerow([w_id, wmo_index, best_ghcn, round(best_dist, 3), "Distance"])
                    matched_dist += 1
                    continue
                    
            writer.writerow([w_id, wmo_index, "", "", "Unmatched"])
            unmatched += 1

    print(f"Matched by WMO: {matched_wmo}")
    print(f"Matched by distance: {matched_dist}")
    print(f"Unmatched: {unmatched}")

if __name__ == "__main__":
    main()
