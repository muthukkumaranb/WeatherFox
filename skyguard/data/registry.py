import csv
import math
from pathlib import Path

def load_registry(path: str) -> dict[str, dict]:
    """Load station metadata keyed by station_id."""
    registry = {}
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = row['station_id']
            registry[sid] = {
                'name': row.get('name', ''),
                'lat': float(row['lat']),
                'lon': float(row['lon']),
                'elevation': float(row.get('elev_m', 0.0)),
                'cadence_min': int(row.get('cadence_min', 60)),
                'P_type': row.get('P_type', 'slp'),
                'reports_per_year': int(row.get('reports_per_year', 0))
            }
    return registry

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def neighbours(station_id: str, registry: dict[str, dict], *, max_km: float = 200.0) -> list[str]:
    """Return station_ids of neighbours within *max_km* km, sorted by distance."""
    if station_id not in registry:
        return []
        
    target = registry[station_id]
    t_lat = target['lat']
    t_lon = target['lon']
    t_elev = target['elevation']
    
    # max_neighbours from config.detector.max_neighbours
    import tomllib
    try:
        config_path = Path(__file__).resolve().parent.parent.parent / "config" / "skyguard.toml"
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
            max_n = config.get("detector", {}).get("max_neighbours", 10)
    except Exception:
        max_n = 10

    distances = []
    for sid, info in registry.items():
        if sid == station_id:
            continue
            
        d_xy = haversine(t_lat, t_lon, info['lat'], info['lon'])
        d_z_km = (info['elevation'] - t_elev) / 1000.0
        # effective distance sqrt(d² + (100·Δz_km)²)
        eff_d = math.sqrt(d_xy**2 + (100 * d_z_km)**2)
        
        if eff_d <= max_km:
            distances.append((eff_d, sid))
            
    distances.sort(key=lambda x: x[0])
    return [sid for d, sid in distances[:max_n]]

def get_neighbour_distance(station_id: str, neighbour_id: str, registry: dict[str, dict]) -> float:
    if station_id not in registry or neighbour_id not in registry:
        return None
    target = registry[station_id]
    nb = registry[neighbour_id]
    d_xy = haversine(target['lat'], target['lon'], nb['lat'], nb['lon'])
    d_z_km = (nb['elevation'] - target['elevation']) / 1000.0
    return math.sqrt(d_xy**2 + (100 * d_z_km)**2)
