import json
import yaml
import glob
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .layers.rule_layer import rule_check, load_taxonomy, load_intent
from .layers.match_layer import find_clusters
from .layers.llm_layer import llm_judge
from .layers.decision_engine import decide


def run_pipeline(
    input_path: str,
    intent_path: str,
    taxonomy_path: str,
    use_llm: bool = False,
    threshold: float = 0.75,
) -> dict:
    intent = load_intent(intent_path)
    taxonomy = load_taxonomy(taxonomy_path)
    
    all_records = []
    seen_ids = set()
    
    # 1. Load data (handle single file or directory)
    if os.path.isdir(input_path):
        json_files = glob.glob(os.path.join(input_path, "*.json"))
    else:
        json_files = [input_path]

    for file_path in json_files:
        print(f"Loading {file_path}...")
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
                records = data.get("points", data) if isinstance(data, dict) else data
                
                # Safety check: ensure records is a list
                if not isinstance(records, list):
                    print(f"Warning: {file_path} does not contain a list of records. Skipping.")
                    continue
                    
                for rec in records:
                    # Safety check: ensure rec is a dictionary
                    if not isinstance(rec, dict):
                        continue
                        
                    rec_id = rec.get("id")
                    # Deduplicate based on ID to avoid processing the same record twice
                    if rec_id and rec_id not in seen_ids:
                        seen_ids.add(rec_id)
                        all_records.append(rec)
        except Exception as e:
            print(f"Error loading {file_path}: {e}")

    print(f"Total unique records loaded: {len(all_records)}")
    records = all_records

    results = {}
    passed = []

    # 2. Layer 1: Rule check (Deterministic)
    for rec in records:
        verdict = rule_check(rec, intent, taxonomy)
        if verdict:
            results[rec["id"]] = {**verdict, "name": rec.get("name", "")}
        else:
            passed.append(rec)

    # 3. Layer 2: Matching (Clustering duplicates)
    clusters, pair_flags = find_clusters(passed, threshold=threshold)
    for cluster in clusters:
        for rid in cluster:
            results.setdefault(rid, {
                "verdict": "ok",
                "reason": f"Belongs to duplicate cluster: {cluster}",
                "suspicious_fields": [],
                "suggested_action": f"merge_with: {[x for x in cluster if x != rid]}",
                "source_layer": "matching",
                "name": next(r["name"] for r in passed if r["id"] == rid),
            })

    force_llm, tripwire_reason = needs_llm_judge(record)
    if force_llm:
        # Ép buộc gọi LLM Judge dù Layer 2 báo ok
        l3_result = llm_judge(record, extra_context=tripwire_reason) 
        results.append(l3_result)
        continue

    if l2_verdict == "suspicious":
        l3_result = llm_judge(record)
        results.append(l3_result) 
        
    # 4. Layer 3: LLM judge for ambiguous cases
    if use_llm:
        # Identify records flagged as suspicious by the Rule layer
        ambiguous_ids = [
            rid for rid, res in results.items() 
            if res.get("verdict") == "suspicious"
        ]
        
        print(f"Sending {len(ambiguous_ids)} records to LLM Judge...")
        
        # Helper function to process a single record with LLM
        def process_record(rid):
            rec = next((r for r in records if r["id"] == rid), None)
            if not rec:
                return rid, None
            
            # Add a 0.5s delay between requests to prevent Rate Limiting (429 errors)
            time.sleep(0.5) 
            llm_result = llm_judge(rec, intent)
            return rid, llm_result

        # Execute LLM calls in parallel (max 5 workers at a time)
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(process_record, rid): rid for rid in ambiguous_ids}
            
            completed = 0
            for future in as_completed(futures):
                rid, llm_result = future.result()
                if llm_result:
                    rule_result = results.get(rid)
                    final = decide(rule_result, llm_result)
                    results[rid] = {**final, "name": next(r.get("name", "") for r in records if r["id"] == rid)}
                
                completed += 1
                # Print progress every 10 records to avoid spamming the console
                if completed % 10 == 0:
                    print(f"Progress: {completed}/{len(ambiguous_ids)} processed...")

    # 5. Handle records that passed all layers without any issues
    for rec in passed:
        if rec["id"] not in results:
            results[rec["id"]] = {
                "verdict": "ok",
                "reason": "All checks passed.",
                "suspicious_fields": [],
                "suggested_action": "keep",
                "source_layer": "matching",
                "name": rec.get("name", ""),
            }

    # 6. Generate summary statistics
    summary = {
        "total": len(records),
        "wrong": sum(1 for v in results.values() if v["verdict"] == "wrong"),
        "suspicious": sum(1 for v in results.values() if v["verdict"] == "suspicious"),
        "ok": sum(1 for v in results.values() if v["verdict"] == "ok"),
    }

    return {
        "summary": summary,
        "pair_flags": pair_flags,
        "records": list(results.values()),
    }