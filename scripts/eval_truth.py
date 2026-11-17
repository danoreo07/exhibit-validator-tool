"""Score a result file against 798_truth.csv.
   python eval_truth.py 798_truth_auto.json data/outputs/798_result.json    (truth may be .json or .csv)
Truth labels were written by Claude from name + Amap type/keytag (see `basis`: 'reviewed' = looked at one by one,
'assumed_wrong' = only keyword-scanned). 'unsure' rows are never counted as errors."""
import csv, json, sys, collections
print(f"eval_truth.py | truth file: {sys.argv[1]} | result file: {sys.argv[2]}")
def load_truth(path):
    if path.lower().endswith(".json"):
        d = json.load(open(path, encoding="utf-8")); d = d["records"] if isinstance(d, dict) else d
        return {str(r["id"]): r for r in d}
    return {str(r["id"]): r for r in csv.DictReader(open(path, encoding="utf-8-sig"))}
truth = load_truth(sys.argv[1])
for r in truth.values():                       # the oracle writes 'suspicious'; hand labels write 'unsure' (both = not scored)
    if r["truth"] == "suspicious": r["truth"] = "unsure"
    r.setdefault("basis", "")
recs = {str(r["id"]): r for r in json.load(open(sys.argv[2], encoding="utf-8"))["records"]}
missing = [i for i in truth if i not in recs]
if missing: print(f"[!] {len(missing)} truth ids are not in the result file (first: {missing[:3]})")
rows = [(truth[i], recs[i]) for i in truth if i in recs]
m = collections.Counter((t["truth"], r["verdict"]) for t, r in rows)
print(f"{len(rows)} rows compared\n\n{'truth \\ system':16s}{'ok':>6s}{'wrong':>7s}{'suspicious':>12s}")
for tr in ("ok", "unsure", "wrong"):
    print(f"{tr:16s}{m[(tr,'ok')]:6d}{m[(tr,'wrong')]:7d}{m[(tr,'suspicious')]:12d}")

def lst(title, sel, show=40):
    bad = [(t, r) for t, r in rows if sel(t, r)]
    print(f"\n{title}: {len(bad)}")
    for t, r in bad[:show]:
        print(f"   {t['name']} | typecode={t['typecode']} | {r.get('source_layer')}: {r['reason'][:70]}")
lst("FALSE OK  (system ok, truth wrong)  -> target 0", lambda t, r: r["verdict"] == "ok" and t["truth"] == "wrong")
lst("FALSE WRONG (system wrong, truth ok) -> target 0", lambda t, r: r["verdict"] == "wrong" and t["truth"] == "ok")

n_ok = sum(1 for t, _ in rows if t["truth"] == "ok")
if n_ok:
    print(f"\nOf {n_ok} true museums/galleries/exhibition spaces:")
    for v, label in (("ok", "found (ok)"), ("suspicious", "sent to human review"), ("wrong", "LOST (wrong)")):
        print(f"   {label:24s}{m[('ok', v)]:4d}  ({100*m[('ok', v)]/n_ok:.0f}%)")
sus = [(t, r) for t, r in rows if r["verdict"] == "suspicious"]
print(f"\nSuspicious rows: {len(sus)} -> truth ok {sum(t['truth']=='ok' for t,_ in sus)}, "
      f"unsure {sum(t['truth']=='unsure' for t,_ in sus)}, wrong {sum(t['truth']=='wrong' for t,_ in sus)} "
      f"(the 'wrong' ones are review work that a rule could remove)")
err = [r for _, r in rows if "LLM unavailable" in r.get("reason", "")]
print(f"LLM errors turned into suspicious: {len(err)}" + ("   <-- LLM did not really run for these" if err else ""))
lst("System decided ok/wrong on rows where truth is 'unsure' (possible guesses)", lambda t, r: t["truth"] == "unsure" and r["verdict"] != "suspicious", show=15)
a = sum(1 for t, _ in rows if t["basis"] == "assumed_wrong")
if a: print(f"\nNote: {a} rows were only keyword-scanned (assumed wrong); a few real galleries could hide there.")
if any("lean" in t for t, _ in rows):
    soft = collections.Counter((t.get("lean", ""), r["verdict"]) for t, r in rows if t["truth"] == "unsure" and t.get("lean"))
    print("\nSOFT view of the oracle's unsure rows (weak hints, NOT ground truth):")
    for lean in ("ok", "wrong"):
        tot = sum(v for (l, _), v in soft.items() if l == lean)
        if tot: print(f"   oracle leans {lean:5s} ({tot} rows): system ok {soft[(lean,'ok')]}, wrong {soft[(lean,'wrong')]}, suspicious {soft[(lean,'suspicious')]}")