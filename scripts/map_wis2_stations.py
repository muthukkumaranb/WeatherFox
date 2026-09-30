import json
import csv
import os
import shutil
from pathlib import Path

def main():
    registry_path = Path("data/station_registry.csv")
    wigos_to_ghcn = {}
    
    with open(registry_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        has_wigos = "wigos_id" in reader.fieldnames
        for row in reader:
            sid = row["station_id"]
            if has_wigos and row.get("wigos_id"):
                wigos_to_ghcn[row["wigos_id"]] = sid
            else:
                import re
                m = re.search(r'\d{5}$', sid)
                if m:
                    wmo_id = m.group(0)
                    wigos_to_ghcn[f"0-20000-0-{wmo_id}"] = sid
                    wigos_to_ghcn[f"0-20000-0-{wmo_id.lstrip('0')}"] = sid
                    
    input_file = Path("data/stream/wis2_latest.jsonl")
    temp_file = Path("data/stream/wis2_latest.tmp")
    mapped = 0
    total = 0
    
    if not input_file.exists():
        print("Input file not found.")
        return
        
    with open(input_file, "r", encoding="utf-8") as fin, \
         open(temp_file, "w", encoding="utf-8") as fout:
        for line in fin:
            total += 1
            row = json.loads(line)
            w_id = row.get("station_id")
            
            if w_id in wigos_to_ghcn:
                row["station_id"] = wigos_to_ghcn[w_id]
                fout.write(json.dumps(row) + "\n")
                mapped += 1

    shutil.move(temp_file, input_file)
    print(f"Mapped {mapped} messages out of {total}.")

if __name__ == "__main__":
    main()
