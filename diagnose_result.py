"""python diagnose_result.py data/outputs/xihu_result.json"""
import json, re, sys, collections, random
random.seed(1)
recs = json.load(open(sys.argv[1], encoding="utf-8"))["records"]
tc = lambda r: str(r.get("typecode", ""))[:4] or "none"
print("verdicts:", dict(collections.Counter(r["verdict"] for r in recs)))

print("\n== SUSPICIOUS by typecode (first 4 digits) ==")
sus = [r for r in recs if r["verdict"] == "suspicious"]
for k, n in collections.Counter(tc(r) for r in sus).most_common(12):
    ex = [r["name"] for r in sus if tc(r) == k][:3]
    print(f"{n:5d}  {k}   e.g. {ex}")

print("\n== SUSPICIOUS by last 2 chars of name ==")
for k, n in collections.Counter(r["name"][-2:] for r in sus).most_common(12): print(f"{n:5d}  {k}")

print("\n== SUSPICIOUS by layer ==")
for k, n in collections.Counter(r.get("source_layer") for r in sus).most_common(): print(f"{n:5d}  {k}")

err = [r for r in recs if "LLM unavailable" in r.get("reason", "")]
print(f"\nLLM errors turned into suspicious: {len(err)}  -> rerun (cache skips finished rows); details in data/outputs/llm_errors.jsonl")

SCHOOLISH = ["学院", "大学", "校区", "学校"]
MUSEUMISH = ["博物", "美术馆", "展览", "纪念馆", "故居", "遗址", "画廊", "陈列", "Museum", "Gallery"]
bad = [r for r in recs if r["verdict"] == "wrong" and any(k in r["name"] for k in MUSEUMISH) and not any(k in r["name"] for k in SCHOOLISH)]
print(f"\n'wrong' rows with museum-like names (excluding schools; should be ~0): {len(bad)}")
for r in bad[:15]: print("  ", r["id"], r["name"], "|", r.get("typecode"), "|", r["reason"][:60])

print("\n== AUDIT: 30 random 'wrong' (read these; every one must be clearly not a museum/gallery/exhibition) ==")
wr = [r for r in recs if r["verdict"] == "wrong"]
for r in random.sample(wr, min(30, len(wr))): print("  ", r.get("typecode"), r["name"])