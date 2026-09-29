import json
import requests
import urllib3
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

base_url = "https://wis2box.imd.gov.in/oapi/collections/urn:wmo:md:in-imd:surface-based-observations.synop/items"

now = datetime.now(timezone.utc)
start = now - timedelta(hours=24)
start_ts = start.strftime("%Y-%m-%dT%H:%M:%SZ")
end_ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")

os.makedirs("data/wis2", exist_ok=True)

params = {
    "f": "json",
    "limit": 1000,
    "datetime": f"{start_ts}/{end_ts}"
}

print("Fetching page 1...")
r1 = requests.get(base_url, params=params, verify=False, timeout=20)
p1 = r1.json()
with open("data/wis2/raw_page1.json", "w") as f:
    json.dump(p1, f, indent=2)

print("Fetching page 2...")
# get next link
next_url = None
for link in p1.get("links", []):
    if link.get("rel") == "next":
        next_url = link.get("href")
        break

p2 = {}
if next_url:
    # next_url might be relative
    if not next_url.startswith("http"):
        next_url = "https://wis2box.imd.gov.in" + next_url
    
    # params shouldn't be added again as they are in the next_url
    r2 = requests.get(next_url, verify=False, timeout=20)
    p2 = r2.json()
    with open("data/wis2/raw_page2.json", "w") as f:
        json.dump(p2, f, indent=2)

pages = [p1, p2]
features_per_page = [len(p.get("features", [])) for p in pages]
wigos_ids = set()
report_ids = set()
name_units = Counter()

station_42516_props = []

for i, p in enumerate(pages):
    for f in p.get("features", []):
        props = f.get("properties", {})
        w_id = props.get("wigos_station_identifier")
        r_id = props.get("reportId")
        if w_id:
            wigos_ids.add(w_id)
        if r_id:
            report_ids.add(r_id)
            
        name = props.get("name")
        units = props.get("units")
        name_units[(name, units)] += 1
        
        if w_id == "0-20000-0-42516":
            station_42516_props.append(props)

print(f"Features per page: {features_per_page}")
print(f"Distinct WIGOS IDs: {len(wigos_ids)}")
print(f"Distinct Report IDs: {len(report_ids)}")
print("\nHistogram of (name, units):")
for k, v in name_units.most_common():
    print(f"  {k}: {v}")

print("\nProperties for 0-20000-0-42516:")
for p in station_42516_props:
    print(json.dumps(p, indent=2))
