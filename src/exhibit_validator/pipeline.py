import json, glob, os, time, hashlib, threading
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from .layers.rule_layer import rule_check, load_taxonomy, strong_ok, hard_type_hit, name_has_ok
from .layers.match_layer import find_clusters          # TODO: still not called, see notes
from .layers.llm_layer import llm_judge, parse_intent_with_llm, slim_record
from .layers.decision_engine import decide
from .layers.tripwire import needs_llm_judge
from .models.schema import normalize_output
from .utils.normalizer import normalize_record

VALID = {"ok", "wrong", "suspicious"}

# ---- Source adapter: one place that knows about a dataset's column names -------------
CSV_COLUMN_MAP = {            # canonical field -> candidate column names (first non-empty wins)
    "title":    ["Museum Name", "name", "Name", "title"],
    "category": ["Museum Type", "category", "type", "typecode"],
    "street":   ["Street Address (Physical Location)", "Street Address (Administrative Location)", "address"],
    "city":     ["City (Physical Location)", "City (Administrative Location)", "city"],
    "state":    ["State (Physical Location)", "State (Administrative Location)", "state"],
    "zip":      ["Zip Code (Physical Location)", "Zip Code (Administrative Location)", "zip"],
    "typecode": ["typecode", "Typecode", "type_code"],
    "latitude": ["Latitude", "latitude", "lat"],
    "longitude": ["Longitude", "longitude", "lng", "lon"],
}

def _pick(row, cols):
    for c in cols:
        v = row.get(c)
        if v is not None and str(v).strip() and str(v).lower() != "nan":
            return str(v).strip()
    return ""

def _load_csv(file_path):
    stem = os.path.splitext(os.path.basename(file_path))[0]
    df = pd.read_csv(file_path, dtype=str, keep_default_na=False)   # str: keeps typecode "060100" intact
    recs = []
    for i, row in enumerate(df.to_dict(orient="records")):
        street = _pick(row, CSV_COLUMN_MAP["street"])
        addr = ", ".join(p for p in [street] + [_pick(row, CSV_COLUMN_MAP[k]) for k in ("city", "state", "zip")] if p)
        recs.append({
            "id": f"{stem}_{i}",                       # was csv_{i}: collided across files
            "title": _pick(row, CSV_COLUMN_MAP["title"]),
            "address": addr,
            "category": _pick(row, CSV_COLUMN_MAP["category"]),
            "typecode": _pick(row, CSV_COLUMN_MAP["typecode"]),
            "latitude": _pick(row, CSV_COLUMN_MAP["latitude"]),
            "longitude": _pick(row, CSV_COLUMN_MAP["longitude"]),
            "address_is_mailing": street.upper().startswith(("PO BOX", "P.O. BOX", "BOX ")),
        })
    return recs

# ---- Guard: LLM may not output ok/wrong without evidence from config -------------------
def _contains_any(text, kws):
    t = (text or "").lower()
    return any(k.lower() in t for k in kws)       # substring: works for CJK and German compounds

def guard_verdict(rec, llm_res, intent):
    v = llm_res.get("verdict")
    if v not in VALID:
        return {**llm_res, "verdict": "suspicious", "reason": f"LLM unavailable/invalid ({v!r}): {llm_res.get('reason', '')}"}
    name, cat = rec.get("title") or rec.get("name", ""), rec.get("category", "")
    ok_kw, wrong_kw = intent.get("ok_keywords"), intent.get("wrong_keywords")
    excl_cat = intent.get("excluded_categories", [])
    if v == "ok" and ok_kw and not name_has_ok(name, intent):
        return {**llm_res, "verdict": "suspicious", "reason": "guard: ok without museum/gallery/exhibition keyword in name"}
    if v == "wrong" and wrong_kw is not None and not (_contains_any(name, wrong_kw) or cat.upper() in [c.upper() for c in excl_cat] or hard_type_hit(rec, intent)):
        return {**llm_res, "verdict": "suspicious", "reason": "guard: wrong without excluded keyword/category"}
    return llm_res

CACHE_PATH = os.getenv("LLM_CACHE_PATH", "data/outputs/.llm_cache.jsonl")

def _cache_key(rec):
    return rec["id"] + ":" + hashlib.md5(json.dumps(slim_record(rec), ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:10]

def _load_cache():
    cache = {}
    if os.path.exists(CACHE_PATH):
        for line in open(CACHE_PATH, encoding="utf-8"):
            try:
                d = json.loads(line); cache[d["key"]] = d["res"]
            except Exception:
                pass
    return cache

def run_pipeline(input_path, intent, taxonomy_path="configs/taxonomy.yaml", use_llm=False):
    if use_llm and "semantic_checks" not in intent:
        # NOTE: LLM-parsed rules differ per run. Save the result to yaml, review once, then freeze.
        intent.update(parse_intent_with_llm(intent["objective"]))

    if use_llm and not os.getenv("DASHSCOPE_API_KEY"):
        raise RuntimeError("use_llm=True but DASHSCOPE_API_KEY is not set")   # fail fast, not 'ok' per record

    taxonomy = load_taxonomy(taxonomy_path) if os.path.exists(taxonomy_path) else {}

    files = (glob.glob(os.path.join(input_path, "*.json")) + glob.glob(os.path.join(input_path, "*.csv"))
             if os.path.isdir(input_path) else [input_path])
    all_records = []
    for fp in files:
        print(f"Loading {fp}...")
        try:
            if fp.endswith(".csv"):
                records = _load_csv(fp)
            else:
                with open(fp, encoding="utf-8") as f:
                    data = json.load(f)
                records = data.get("points", data) if isinstance(data, dict) else data
            for rec in records:
                if isinstance(rec, dict):
                    extra = {k: rec[k] for k in ("address_is_mailing",) if k in rec}
                    rec = {**normalize_record(rec), **extra}
                    if rec.get("id"):
                        all_records.append(rec)
        except Exception as e:
            print(f"Error loading {fp}: {e}")

    order = {r["id"]: i for i, r in enumerate(all_records)}
    id_to_rec = {r["id"]: r for r in all_records}
    results, passed, llm_queue = {}, [], []

    for rec in all_records:                              # Layer 1
        verdict = rule_check(rec, intent, taxonomy)
        if verdict:
            results[rec["id"]] = {**verdict, "name": rec.get("name", "")}
        else:
            passed.append(rec)

    pair_flags = []                                      # Layer 2: still disabled, see notes

    for rec in passed:                                   # Layer 2.5 / 3
        rid = rec["id"]
        force_llm, reason = needs_llm_judge(rec)
        if not force_llm and strong_ok(rec, intent, taxonomy):     # typecode + keyword agree, nothing flagged
            results[rid] = {"verdict": "ok", "reason": "Allowed museum typecode and explicit museum keyword in name",
                            "suspicious_fields": [], "suggested_action": "keep", "source_layer": "rule+typecode",
                            "name": rec.get("name", "")}
            continue
        if use_llm:
            trip = {"verdict": "suspicious", "reason": reason, "source_layer": "tripwire"} if force_llm else None
            llm_queue.append({"rid": rid, "rec": rec, "reason": reason if force_llm else "", "trip": trip})
        else:
            # never default to "ok": no evidence means a human looks at it
            results[rid] = {"verdict": "suspicious",
                            "reason": reason if force_llm else "no rule matched (LLM disabled)",
                            "suggested_action": "review", "source_layer": "tripwire", "name": rec.get("name", "")}

    if use_llm and llm_queue:
        print(f"Sending {len(llm_queue)} records to LLM Judge...")
        cache, lock = _load_cache(), threading.Lock()
        os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
        print(f"Cache: {len(cache)} verdicts already stored ({CACHE_PATH})")

        def process(item):
            key = _cache_key(item["rec"])
            if key in cache:
                return cache[key]
            time.sleep(0.5)
            res = llm_judge(item["rec"], intent, extra_context=item["reason"])
            if res and res.get("verdict") in VALID:        # only cache real answers, never errors
                with lock, open(CACHE_PATH, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"key": key, "res": res}, ensure_ascii=False) + "\n")
            return res

        with ThreadPoolExecutor(max_workers=2) as ex:
            futures = {ex.submit(process, it): it for it in llm_queue}
            for n, fut in enumerate(as_completed(futures), 1):
                it = futures[fut]; rid, rec = it["rid"], it["rec"]
                err = "empty response"
                try:
                    llm_res = fut.result()
                except Exception as e:
                    llm_res, err = None, str(e)
                if llm_res:
                    final = decide(it["trip"], guard_verdict(rec, llm_res, intent))
                else:   # failure must never drop the record silently
                    final = {"verdict": "suspicious", "reason": f"llm_error: {err}",
                             "suggested_action": "review", "source_layer": "llm_error"}
                results[rid] = {**final, "name": rec.get("name", "")}
                if n % 10 == 0:
                    print(f"Progress: {n}/{len(llm_queue)}")

    for rid, res in results.items():
        res.setdefault("id", rid)
    missing = [r for r in order if r not in results]    # safety net: every input record gets a verdict
    for rid in missing:
        results[rid] = {"id": rid, "verdict": "suspicious", "reason": "missing result", "name": id_to_rec[rid].get("name", ""),
                        "suggested_action": "review", "source_layer": "safety_net"}

    ordered = sorted(results.values(), key=lambda r: order.get(r["id"], 1e9))   # stable input order
    summary = {"total": len(all_records)}
    summary.update({k: sum(1 for v in ordered if v["verdict"] == k) for k in ("wrong", "suspicious", "ok")})
    assert sum(summary[k] for k in VALID) == summary["total"], "summary does not add up"
    return {"summary": summary, "pair_flags": pair_flags, "records": normalize_output(ordered)}