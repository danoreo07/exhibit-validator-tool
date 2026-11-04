"""
Step 1:  python label_check.py make  data/outputs/result.json [data/inputs/original.json]   -> label_sheet.csv (blind) + label_key.csv
         (pass the ORIGINAL input json as 3rd arg to fill typecode / type / address in the sheet)
Step 2:  open label_sheet.csv, fill column `my_label` with ok / wrong / unsure  (ok = museum, gallery or exhibition venue)
Step 3:  python label_check.py check                                   -> error report
Later:   python label_check.py rescore data/outputs/new_result.json    -> same labeled ids, NEW verdicts (no relabeling)
"""
import csv, json, random, sys, collections
QUOTA = {"ok": 30, "wrong": 50, "suspicious": 20}

def make(path, src=None):
    random.seed(7)
    extra = {}
    if src:
        d = json.load(open(src, encoding="utf-8"))
        for p in (d.get("points", d) if isinstance(d, dict) else d):
            extra[str(p.get("id"))] = p
    recs = json.load(open(path, encoding="utf-8"))["records"]
    pick = []
    for v, n in QUOTA.items():
        rows = [r for r in recs if r["verdict"] == v]
        pick += random.sample(rows, min(n, len(rows)))
    random.shuffle(pick)
    with open("label_sheet.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["id", "name", "typecode", "type", "address", "my_label"])
        for r in pick:
            o = extra.get(str(r["id"]), {})
            w.writerow([r["id"], r["name"], o.get("typecode") or r.get("typecode", ""), o.get("type", ""), o.get("address") or r.get("address", ""), ""])
    with open("label_key.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["id", "verdict", "source_layer", "reason"])
        for r in pick: w.writerow([r["id"], r["verdict"], r.get("source_layer", ""), r.get("reason", "")[:120]])
    print(f"{len(pick)} rows -> label_sheet.csv (fill my_label), label_key.csv (do not open before labeling)")

def rescore(path):
    recs = {r["id"]: r for r in json.load(open(path, encoding="utf-8"))["records"]}
    ids = [r["id"] for r in csv.DictReader(open("label_sheet.csv", encoding="utf-8-sig"))]
    with open("label_key.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["id", "verdict", "source_layer", "reason"])
        for i in ids:
            r = recs.get(i, {"verdict": "missing", "source_layer": "", "reason": "id not in new result"})
            w.writerow([i, r["verdict"], r.get("source_layer", ""), r.get("reason", "")[:120]])
    print(f"label_key.csv rebuilt from {path} for {len(ids)} ids; now run: python label_check.py check")

def check():
    key = {r["id"]: r for r in csv.DictReader(open("label_key.csv", encoding="utf-8-sig"))}
    rows = list(csv.DictReader(open("label_sheet.csv", encoding="utf-8-sig")))
    done = [r for r in rows if r["my_label"].strip().lower() in ("ok", "wrong", "unsure")]
    print(f"labeled {len(done)}/{len(rows)}")
    m = collections.Counter((key[r["id"]]["verdict"], r["my_label"].strip().lower()) for r in done)
    print("\nsystem verdict (rows) vs my label (columns)")
    print(f"{'':12s}{'ok':>6s}{'wrong':>7s}{'unsure':>8s}")
    for v in ("ok", "wrong", "suspicious"):
        print(f"{v:12s}{m[(v,'ok')]:6d}{m[(v,'wrong')]:7d}{m[(v,'unsure')]:8d}")
    for title, sv, lab in [("FALSE OK  (system ok, I say wrong)  -> target 0", "ok", "wrong"),
                           ("FALSE WRONG (system wrong, I say ok) -> target 0", "wrong", "ok")]:
        bad = [r for r in done if key[r["id"]]["verdict"] == sv and r["my_label"].strip().lower() == lab]
        print(f"\n{title}: {len(bad)}")
        for r in bad: print("  ", r["id"], r["name"], "|", key[r["id"]]["source_layer"], "|", key[r["id"]]["reason"])
    risky = [r for r in done if key[r["id"]]["verdict"] in ("ok", "wrong") and r["my_label"].strip().lower() == "unsure"]
    print(f"\nsystem said ok/wrong but I was unsure: {len(risky)}  (decided on an ambiguous case = possible guess; review these)")
    for r in risky: print("  ", key[r["id"]]["verdict"], r["name"], "|", key[r["id"]]["source_layer"], "|", key[r["id"]]["reason"])
    easy = [r for r in done if key[r["id"]]["verdict"] == "suspicious" and r["my_label"].strip().lower() in ("ok", "wrong")]
    print(f"\nsuspicious rows I could decide myself: {len(easy)}  (each is a candidate for a new rule)")
    for r in easy: print("  ", r["my_label"], r["name"], "|", r["typecode"])

if __name__ == "__main__":
    {"make": lambda: make(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None), "rescore": lambda: rescore(sys.argv[2]), "check": check}[sys.argv[1]]()