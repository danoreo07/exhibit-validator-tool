import json
import argparse
import pandas as pd
from collections import defaultdict

VERDICTS = ["ok", "suspicious", "wrong"]

def load_manual(path: str) -> dict:
    """Load manual ground truth (supports both .csv and .jsonl)"""
    data = {}
    if path.endswith('.csv'):
        df = pd.read_csv(path)
        for _, row in df.iterrows():
            rid = str(row.get("id", "")).strip()
            if rid:
                data[rid] = {
                    "name": str(row.get("name", "")),
                    "verdict": str(row.get("verdict", "wrong")).strip().lower()
                }
    else:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    rid = str(rec.get("id", "")).strip()
                    if rid:
                        data[rid] = rec
    return data

def load_system(path: str) -> dict:
    """Load system output (.json)"""
    data = {}
    with open(path, encoding="utf-8") as f:
        content = json.load(f)
        for r in content.get("records", []):
            rid = str(r.get("id", "")).strip()
            if rid:
                data[rid] = r.get("verdict", "unknown")
    return data

def main(manual_path: str, system_path: str):
    manual_data = load_manual(manual_path)
    system_data = load_system(system_path)

    cm = defaultdict(int)
    matched_count = 0
    disagreements = []

    for rid, m in manual_data.items():
        if rid not in system_data:
            continue
        
        matched_count += 1
        mv = m["verdict"]
        sv = system_data[rid]
        
        if mv == "out_of_scope": 
            mv = "wrong"
        if sv == "unknown": 
            sv = "suspicious"

        cm[(mv, sv)] += 1
        if mv != sv:
            disagreements.append(f"[{mv:10} -> {sv:10}] ID:{rid} - {m.get('name', '')}")

    # Print Report
    print(f"Matched: {matched_count}/{len(manual_data)} records by ID\n")
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

    acc = sum(cm[(v, v)] for v in VERDICTS) / matched_count if matched_count else 0
    print("-" * 50)
    print(f"Overall accuracy: {acc:.2%}\n")
    
    if disagreements:
        print(f"Disagreements ({len(disagreements)}):")
        for d in disagreements[:50]: # Only print max 50 to avoid screen overflow
            print(" ", d)
        if len(disagreements) > 50:
            print(f"  ... and {len(disagreements) - 50} more.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manual", required=True, help="Path to manual review file (.csv or .jsonl)")
    parser.add_argument("--system", required=True, help="Path to system output (.json)")
    args = parser.parse_args()
    main(args.manual, args.system)