import json
import glob
import os
import time
import hashlib
import threading
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from .layers.rule_layer import rule_check, load_taxonomy
from .layers.ambiguity_detector import detect_ambiguities
from .layers.llm_layer import build_prompt, llm_judge
from .layers.decision_engine import decide
from .layers.tripwire import needs_llm_judge_bilingual
from .models.schema import normalize_output
from .utils.normalizer import normalize_record

VALID = {"ok", "wrong", "suspicious"}

CSV_COLUMN_MAP = {
    "title": ["Museum Name", "name", "Name", "title"],
    "category": ["Museum Type", "category", "type", "typecode"],
    "street": ["Street Address (Physical Location)", "Street Address (Administrative Location)", "address"],
    "city": ["City (Physical Location)", "City (Administrative Location)", "city"],
    "state": ["State (Physical Location)", "State (Administrative Location)", "state"],
    "zip": ["Zip Code (Physical Location)", "Zip Code (Administrative Location)", "zip"],
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
    df = pd.read_csv(file_path, dtype=str, keep_default_na=False)
    recs = []
    for i, row in enumerate(df.to_dict(orient="records")):
        street = _pick(row, CSV_COLUMN_MAP["street"])
        addr = ", ".join(p for p in [street] + [_pick(row, CSV_COLUMN_MAP[k]) for k in ("city", "state", "zip")] if p)
        recs.append({
            "id": f"{stem}_{i}",
            "title": _pick(row, CSV_COLUMN_MAP["title"]),
            "address": addr,
            "category": _pick(row, CSV_COLUMN_MAP["category"]),
            "typecode": _pick(row, CSV_COLUMN_MAP["typecode"]),
            "latitude": _pick(row, CSV_COLUMN_MAP["latitude"]),
            "longitude": _pick(row, CSV_COLUMN_MAP["longitude"]),
            "address_is_mailing": street.upper().startswith(("PO BOX", "P.O. BOX", "BOX ")),
        })
    return recs

CACHE_PATH = os.getenv("LLM_CACHE_PATH", "data/outputs/.llm_cache.jsonl")

def _cache_key(rec, intent, extra_context=""):
    # Hash the exact prompt: editing the prompt or the objective invalidates old verdicts,
    # while reverting the prompt lets the matching old answers be reused.
    prompt = build_prompt(rec, intent, extra_context)
    return rec["id"] + ":" + hashlib.md5(prompt.encode()).hexdigest()[:10]

def _load_cache():
    cache = {}
    if os.path.exists(CACHE_PATH):
        for line in open(CACHE_PATH, encoding="utf-8"):
            try:
                d = json.loads(line)
                cache[d["key"]] = d["res"]
            except Exception:
                pass
    return cache

def run_pipeline(input_path, intent, taxonomy_path="configs/taxonomy.yaml", use_llm=False):
    # Rules come from the YAML config only; intent is never parsed by the LLM.
    if use_llm and not os.getenv("DASHSCOPE_API_KEY"):
        raise RuntimeError("use_llm=True but DASHSCOPE_API_KEY is not set")

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
    results, llm_queue = {}, []

    # Layer 1: rule check. Only an explicit "wrong" skips the LLM.
    for rec in all_records:
        verdict = rule_check(rec, intent, taxonomy)
        rec["ambiguity_signals"] = detect_ambiguities(rec, intent)

        if verdict and verdict.get("verdict") == "wrong":
            results[rec["id"]] = {
                **verdict,
                "name": rec.get("name", ""),
                "ambiguity_signals": rec["ambiguity_signals"],
            }
        else:
            # Everything else (including typecode 140100) goes to LLM for semantic judgement.
            force_llm, trip_reason_zh, trip_reason_en = needs_llm_judge_bilingual(rec, intent)
            
            if use_llm:
                trip = (
                    {
                        "verdict": "suspicious",
                        "reason": trip_reason_zh,
                        "reason_en": trip_reason_en,
                        "source_layer": "tripwire",
                        "rule_id": "tripwire_escalation",
                        "reason_code": "tripwire_flagged",
                    }
                    if force_llm else None
                )
                llm_queue.append({
                    "rid": rec["id"],
                    "rec": rec,
                    "reason": trip_reason_zh if force_llm else "",
                    "reason_en": trip_reason_en if force_llm else "",
                    "trip": trip,
                })
            else:
                results[rec["id"]] = {
                    "verdict": "suspicious",
                    "reason": trip_reason_zh if force_llm else "未启用 LLM",
                    "reason_en": trip_reason_en if force_llm else "LLM disabled",
                    "suggested_action": "review",
                    "source_layer": "fallback",
                    "name": rec.get("name", ""),
                    "ambiguity_signals": rec.get("ambiguity_signals", []),
                }

    if use_llm and llm_queue:
        print(f"Sending {len(llm_queue)} records to LLM Judge...")
        cache, lock = _load_cache(), threading.Lock()
        os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)

        def process(item):
            key = _cache_key(item["rec"], intent, item["reason"] or item["reason_en"])
            if key in cache:
                return cache[key]
            time.sleep(0.5)
            res = llm_judge(item["rec"], intent, extra_context=item["reason"] or item["reason_en"])
            if res and res.get("verdict") in VALID:
                with lock, open(CACHE_PATH, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"key": key, "res": res}, ensure_ascii=False) + "\n")
            return res

        with ThreadPoolExecutor(max_workers=2) as ex:
            futures = {ex.submit(process, it): it for it in llm_queue}
            for n, fut in enumerate(as_completed(futures), 1):
                it = futures[fut]
                rid, rec = it["rid"], it["rec"]
                try:
                    llm_res = fut.result()
                except Exception as e:
                    llm_res = None
                
                if llm_res:
                    # The LLM has the final say; a tripwire flag is reported, not enforced.
                    final = decide(it["trip"], llm_res)
                else:
                    final = {
                        "verdict": "suspicious",
                        "reason": "LLM 调用失败，需要人工复核",
                        "reason_en": "llm_error",
                        "suggested_action": "review",
                        "source_layer": "llm_error",
                        "rule_id": "",
                        "reason_code": "llm_error",
                    }
                
                results[rid] = {
                    **final,
                    "name": rec.get("name", ""),
                    "ambiguity_signals": rec.get("ambiguity_signals", []),
                    "tripwire_flag": bool(it["trip"]),
                }
                if n % 10 == 0:
                    print(f"Progress: {n}/{len(llm_queue)}")

    # Safety net: every input record gets a verdict, an id, and its source fields.
    for rid in order:
        rec = id_to_rec[rid]
        if rid not in results:
            results[rid] = {
                "verdict": "suspicious", "reason": "缺少结果", "reason_en": "missing result",
                "suggested_action": "review", "source_layer": "safety_net",
            }
        res = results[rid]
        res.setdefault("id", rid)
        res.setdefault("name", rec.get("name", ""))
        res.setdefault("typecode", rec.get("typecode", ""))
        res.setdefault("address", rec.get("address", ""))

    ordered = sorted(results.values(), key=lambda r: order.get(r["id"], 1e9))
    summary = {"total": len(all_records)}
    summary.update({k: sum(1 for v in ordered if v["verdict"] == k) for k in ("wrong", "suspicious", "ok")})
    
    return {"summary": summary, "records": normalize_output(ordered)}

# CLI entry point
if __name__ == "__main__":
    import argparse
    import yaml
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--intent", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--taxonomy", default="configs/taxonomy.yaml")
    parser.add_argument("--use-llm", action="store_true")
    args = parser.parse_args()

    with open(args.intent, "r", encoding="utf-8") as f:
        intent_config = yaml.safe_load(f)

    result = run_pipeline(args.input, intent_config, args.taxonomy, args.use_llm)
    
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Saved to {args.output}. Summary: {result['summary']}")