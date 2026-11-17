"""
Collect POIs around a place with Amap's OFFICIAL Web API (v5 around-search) and save them in the same
JSON layout as 西湖点位.json, so the validator can read the file directly.

Needs a free Amap Web-Service key (https://console.amap.com). No third-party packages.

  python collect_amap.py "798艺术区" --key YOUR_KEY --radius 3000 --out data/raw/798.json
  python collect_amap.py "故宫博物院" --radius 2000 --out data/raw/gugong.json      (key from env AMAP_KEY)
  python collect_amap.py "x" --center 116.4966,39.9846 --radius 2000 --out data/raw/x.json   (skip geocoding)
  add --dry-run to only print how many API calls would be made.
"""
import argparse, json, math, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

BASE = "https://restapi.amap.com"
# Top-level categories (same 2-digit families as taxonomy.yaml + 09 health). A 6-digit code ending in 0000
# asks for the whole family; without `types` Amap only returns food / business-residential / life services.
DEFAULT_TYPES = ["140000", "110000", "060000", "050000", "070000", "080000", "090000", "100000",
                 "120000", "130000", "160000", "170000"]

def fetch_json(url):
    # Try up to 3 times if connection drops
    for attempt in range(3):
        try:
            # Use a standard browser User-Agent to avoid being blocked
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"[!] Attempt {attempt + 1} failed: {e}")
            if attempt < 2:
                print("[!] Retrying in 2 seconds...")
                time.sleep(2) # Wait before retrying
            else:
                sys.exit(f"[x] Failed after 3 attempts. Please check your network or try a different connection. Error: {e}")

def api(path, **params):
    return fetch_json(f"{BASE}{path}?{urllib.parse.urlencode(params)}")

def check(resp, what):
    if str(resp.get("status")) != "1":
        code, info = resp.get("infocode"), resp.get("info")
        sys.exit(f"[x] Amap error during {what}: {info} (infocode {code}). "
                 "Quota/limit codes mean: stop and try again later; invalid-key codes mean: check --key.")
    return resp

def geocode(name, key):
    r = check(api("/v3/geocode/geo", key=key, address=name), "geocoding")
    if not r.get("geocodes"):
        sys.exit(f"[x] Could not find '{name}'. Try a more specific Chinese name or pass --center lng,lat.")
    g = r["geocodes"][0]
    lng, lat = map(float, g["location"].split(","))
    return lng, lat, g.get("formatted_address", name)

def grid_centers(lng, lat, radius, step):
    dlat = step / 111320.0
    dlng = step / (111320.0 * math.cos(math.radians(lat)))
    n = int(radius // step) + 1
    out = []
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            if math.hypot(i * step, j * step) <= radius + step * 0.5:
                out.append((lng + j * dlng, lat + i * dlat))
    return out

def as_list(pois):
    if isinstance(pois, dict):              # docs show {"poi": [...]}; the live API normally returns a list
        pois = pois.get("poi", [])
    return pois or []

def flat(v):
    return "" if isinstance(v, (list, dict)) and not v else v

def to_record(p):
    b = p.get("business") or {}
    lng, lat = (p.get("location") or ",").split(",")[:2]
    return {
        "id": p.get("id", ""), "name": p.get("name", ""), "type": p.get("type", ""), "typecode": p.get("typecode", ""),
        "biz_type": flat(p.get("biz_type", "")), "keytag": flat(b.get("keytag", "")),
        "business_area": flat(b.get("business_area", "")), "childtype": flat(p.get("childtype", "")),
        "rating": flat(b.get("rating", "")), "open_time": flat(b.get("opentime_today", "")),
        "address": flat(p.get("address", "")), "location": p.get("location", ""),
        "longitude": float(lng) if lng else None, "latitude": float(lat) if lat else None,
        "cityname": p.get("cityname", ""), "adname": p.get("adname", ""), "source": "amap",
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("venue", help="place name, e.g. 798艺术区")
    ap.add_argument("--key", default=os.getenv("AMAP_KEY"))
    ap.add_argument("--center", help="lng,lat (skips geocoding)")
    ap.add_argument("--radius", type=int, default=2000, help="metres around the centre (default 2000)")
    ap.add_argument("--step", type=int, default=1000, help="grid cell size in metres; smaller = more complete, more calls")
    ap.add_argument("--types", default=",".join(DEFAULT_TYPES), help="comma-separated 6-digit type codes")
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--max-calls", type=int, default=1500, help="safety cap on API calls")
    ap.add_argument("--sleep", type=float, default=0.4, help="pause between calls (rate limit)")
    ap.add_argument("--out")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not a.out and not a.dry_run:
        sys.exit("[x] Provide --out path for the JSON file.")
    if not a.key and not a.dry_run:
        sys.exit("[x] Provide --key or set env AMAP_KEY.")

    if a.center:
        lng, lat = map(float, a.center.split(",")); title = a.venue
    elif a.dry_run and not a.key:
        sys.exit("[x] dry-run needs --center (or a key) to know the area.")
    else:
        lng, lat, title = geocode(a.venue, a.key)
    types = [t.strip() for t in a.types.split(",") if t.strip()]
    cells = grid_centers(lng, lat, a.radius, a.step)
    cell_r = int(a.step * 0.75)
    est = len(cells) * len(types)
    print(f"Centre {lng:.6f},{lat:.6f} | {len(cells)} cells x {len(types)} types = at least {est} calls (more with paging)")
    if a.dry_run:
        return

    seen, calls = {}, 0
    for ci, (clng, clat) in enumerate(cells, 1):
        for t in types:
            for page in range(1, a.max_pages + 1):
                if calls >= a.max_calls:
                    print(f"[!] Reached --max-calls={a.max_calls}; saving what we have."); break
                r = check(api("/v5/place/around", key=a.key, location=f"{clng:.6f},{clat:.6f}", radius=cell_r,
                              types=t, page_size=25, page_num=page, show_fields="business"), "place search")
                calls += 1; time.sleep(a.sleep)
                pois = as_list(r.get("pois"))
                for p in pois:
                    if p.get("id") and p["id"] not in seen:
                        seen[p["id"]] = to_record(p)
                if len(pois) < 25:
                    break
            else:
                continue
            break
        print(f"cell {ci}/{len(cells)} done | unique POIs so far: {len(seen)} | calls: {calls}")
        if calls >= a.max_calls:
            break

    out = {"status": "SUCCEEDED", "venue": a.venue, "collected_at": datetime.now(timezone.utc).isoformat(),
           "center": {"longitude": lng, "latitude": lat}, "main_poi": {"name": title, "typecode": ""},
           "points": list(seen.values())}
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Saved {len(seen)} POIs to {a.out}")

if __name__ == "__main__":
    main()