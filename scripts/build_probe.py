"""Build a small probe set from a previous run: all errors + a sample of correct rows.

Iterating a prompt on the full 268-row set costs ~230k tokens per attempt. This cuts a
probe of ~30 records so each prompt revision costs ~10x less; run the full set only once
the probe looks right.

    python scripts/build_probe.py \
        --result data/outputs/result_300.json \
        --gold   data/ground_truth/gold_300.csv \
        --raw    data/raw/test_tianhe_300.json \
        --out-raw data/raw/probe_30.json \
        --out-gold data/ground_truth/probe_30_gold.csv \
        --controls 10
"""

import argparse
import csv
import json


def label(value: str) -> str:
    v = str(value or "").strip().lower()
    return "unsure" if v in ("unsure", "suspicious", "") else v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out-raw", required=True)
    ap.add_argument("--out-gold", required=True)
    ap.add_argument("--controls", type=int, default=10, help="correct rows per label")
    args = ap.parse_args()

    result = {str(r["id"]): r for r in json.load(open(args.result, encoding="utf-8"))["records"]}
    gold = {str(r["id"]): label(r.get("truth")) for r in csv.DictReader(open(args.gold, encoding="utf-8-sig"))}

    raw = json.load(open(args.raw, encoding="utf-8"))
    rows = raw.get("points", raw) if isinstance(raw, dict) else raw
    by_id = {str(r["id"]): r for r in rows}

    errors = []
    for rid, truth in gold.items():
        if rid not in result:
            continue
        predicted = result[rid]["verdict"]
        if (truth == "wrong" and predicted == "ok") or (truth == "ok" and predicted == "wrong"):
            errors.append(rid)

    control_ok = [i for i in sorted(gold) if gold[i] == "ok" and i not in errors][: args.controls]
    control_wrong = [i for i in sorted(gold) if gold[i] == "wrong" and i not in errors][: args.controls]

    picked = errors + control_ok + control_wrong
    with open(args.out_raw, "w", encoding="utf-8") as f:
        json.dump({"points": [by_id[i] for i in picked if i in by_id]}, f, ensure_ascii=False, indent=2)
    with open(args.out_gold, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "truth"])
        for i in picked:
            if i in by_id:
                w.writerow([i, by_id[i].get("name", ""), gold[i]])

    print(f"errors={len(errors)} controls_ok={len(control_ok)} controls_wrong={len(control_wrong)} total={len(picked)}")
    print(f"wrote {args.out_raw} and {args.out_gold}")


if __name__ == "__main__":
    main()
