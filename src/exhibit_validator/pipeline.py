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

# Import Tripwire Layer 2.5
from .layers.tripwire import needs_llm_judge
# Import Schema Normalizer
from .models.schema import normalize_output

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
                
                if not isinstance(records, list):
                    print(f"Warning: {file_path} does not contain a list of records. Skipping.")
                    continue
                    
                for rec in records:
                    if not isinstance(rec, dict):
                        continue
                        
                    rec_id = rec.get("id")
                    if rec_id and rec_id not in seen_ids:
                        seen_ids.add(rec_id)
                        all_records.append(rec)
        except Exception as e:
            print(f"Error loading {file_path}: {e}")

    print(f"Total unique records loaded: {len(all_records)}")
    records = all_records

    results = {}
    passed = []
    
    # [MỚI] Tập hợp các record cần gọi LLM
    llm_queue = []
    
    # Dict để tra cứu record nhanh theo ID
    id_to_rec = {r["id"]: r for r in records}

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

    # 4. Layer 2.5 & Layer 3: Tripwire and LLM Judge
    for rec in passed:
        rid = rec["id"]
        if rid in results:
            continue # Đã được xử lý ở Layer 2 (matching)
            
        # Check Tripwire (Layer 2.5)
        force_llm, tripwire_reason = needs_llm_judge(rec)
        
        if force_llm:
            if use_llm:
                # Đưa vào hàng đợi LLM với lý do cụ thể
                llm_queue.append({"rid": rid, "rec": rec, "reason": tripwire_reason})
            else:
                # Nếu tắt LLM, đánh dấu là suspicious để user tự review
                results[rid] = {
                    "verdict": "suspicious",
                    "reason": tripwire_reason,
                    "suspicious_fields": ["name", "address", "keytag"],
                    "suggested_action": "review",
                    "source_layer": "tripwire",
                    "name": rec.get("name", ""),
                }
        else:
            # Nếu không bị tripwire, đánh dấu là ok (passed all checks)
            results[rid] = {
                "verdict": "ok",
                "reason": "All checks passed.",
                "suspicious_fields": [],
                "suggested_action": "keep",
                "source_layer": "matching",
                "name": rec.get("name", ""),
            }

    # 5. Layer 3: LLM judge for ambiguous cases
    if use_llm and llm_queue:
        print(f"Sending {len(llm_queue)} tripwire records to LLM Judge...")
        
        def process_record(item):
            rec = item["rec"]
            time.sleep(0.5) # Prevent rate limiting
            # Call LLM with extra context
            llm_result = llm_judge(rec, intent, extra_context=item["reason"])
            return item["rid"], llm_result

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(process_record, item): item["rid"] for item in llm_queue}
            
            completed = 0
            for future in as_completed(futures):
                rid, llm_result = future.result()
                if llm_result:
                    rule_result = results.get(rid, {})
                    # Sử dụng decision_engine để kết hợp rule & LLM result
                    final = decide(rule_result, llm_result)
                    results[rid] = {**final, "name": id_to_rec[rid].get("name", "")}
                
                completed += 1
                if completed % 10 == 0:
                    print(f"Progress: {completed}/{len(llm_queue)} processed...")

    # 6. Generate summary statistics
    summary = {
        "total": len(records),
        "wrong": sum(1 for v in results.values() if v["verdict"] == "wrong"),
        "suspicious": sum(1 for v in results.values() if v["verdict"] == "suspicious"),
        "ok": sum(1 for v in results.values() if v["verdict"] == "ok"),
    }

    # 7. [MỚI] Normalize Output trước khi trả về
    for rid, res in results.items():
        if "id" not in res:
            res["id"] = rid
            
    normalized_records = normalize_output(list(results.values()))

    return {
        "summary": summary,
        "pair_flags": pair_flags,
        "records": normalized_records,
    }