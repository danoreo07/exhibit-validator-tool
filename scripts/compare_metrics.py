import json
import argparse
from collections import defaultdict

VERDICTS = ["ok", "suspicious", "wrong"]

def main(manual_path: str, system_path: str):
    # 1. Load Manual Ground Truth (dict by ID)
    manual_by_id = {}
    with open(manual_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                manual_by_id[rec["id"]] = rec
                
    # Create a lookup by Name (since system output might lack IDs)
    manual_by_name = {r["name"]: r for r in manual_by_id.values()}

    # 2. Load System Output
    with open(system_path, encoding="utf-8") as f:
        system_data = json.load(f)
        system_records = system_data.get("records", [])
        
    # Map system by Name
    system_by_name = {r["name"]: r for r in system_records if "name" in r}

    # 3. Compare
    cm = defaultdict(int)
    matched_count = 0
    disagreements = []

    for name, m in manual_by_name.items():
        if name not in system_by_name:
            continue
        
        matched_count += 1
        s = system_by_name[name]
        
        mv = m["verdict"]
        if mv == "out_of_scope": 
            mv = "wrong" # Map out_of_scope to wrong for comparison
            
        sv = s.get("verdict", "unknown")

        cm[(mv, sv)] += 1
        if mv != sv:
            disagreements.append({
                "name": name,
                "manual": mv,
                "system": sv,
                "system_reason": s.get("reason", "")[:80] + "..."
            })

    # 4. Print Report
    print(f"Matched: {matched_count}/{len(manual_by_id)} records by name\n")
    print(f"{'verdict':12} {'P':>6} {'R':>6} {'F1':>6}  tp  fp  fn")
    print("-" * 50)
    
    for v in VERDICTS:
        tp = cm[(v, v)]
        fp = sum(cm[(m, v)] for m in VERDICTS if m != v)
        fn = sum(cm[(v, s)] for s in VERDICTS if s != v)
        
        p = tp / (tp + fp) if (tp + fp) else 0
        r = tp / (tp + fn) if (tp + fn) else 0
        f = 2 * p * r / (p + r) if (p + r) else 0
        
        print(f"{v:12} {p:6.3f} {r:6.3f} {f:6.3f}  {tp:2}  {fp:2}  {fn:2}")

    total_correct = sum(cm[(v, v)] for v in VERDICTS)
    acc = total_correct / matched_count if matched_count else 0
    print("-" * 50)
    print(f"Overall accuracy: {acc:.2%}\n")
    
    print(f"Disagreements ({len(disagreements)}):")
    for d in disagreements:
        print(f"  [{d['manual']:10} -> {d['system']:10}] {d['name']}")
        # Uncomment the line below if you want to see the system's reasoning
        # print(f"      Reason: {d['system_reason']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manual", default="data/ground_truth/manual_review_雷峰塔.jsonl", help="Path to manual ground truth JSONL")
    parser.add_argument("--system", default="data/outputs/museum_llm_v2.json", help="Path to system output JSON")
    args = parser.parse_args()
    
    main(args.manual, args.system)