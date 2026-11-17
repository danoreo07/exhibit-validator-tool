import argparse
import csv
import json
import math
import random
import collections
import sys
from typing import List, Tuple, Dict, Any

def load_gold(path: str) -> dict:
    """Loads gold standard from CSV or JSON."""
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        rows = d.get("records", d) if isinstance(d, dict) else d
    else:
        with open(path, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    
    out = {}
    for r in rows:
        t = str(r.get("truth", "")).strip().lower()
        # Any label that is not explicitly ok/wrong is treated as 'unsure'
        out[str(r["id"])] = {**r, "truth": "unsure" if t in ("suspicious", "unsure", "needs_review", "") else t}
    return out

def side(v: str) -> str:
    """Maps system verdict to stratum: ok, wrong, or abstain."""
    v = str(v).lower().strip()
    if v in ("ok", "wrong"):
        return v
    return "abstain"

def wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Calculates Wilson score interval for binomial proportion."""
    if n == 0: return (float("nan"),) * 2
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)

def cohens_kappa(y_true: List[str], y_pred: List[str]) -> float:
    """Calculates Cohen's Kappa for inter-annotator agreement (e.g., Rule vs LLM vs Gold)."""
    if not y_true or len(y_true) != len(y_pred): return float('nan')
    n = len(y_true)
    po = sum(1 for t, p in zip(y_true, y_pred) if t == p) / n
    pe = sum(y_true.count(k) * y_pred.count(k) for k in set(y_true) | set(y_pred)) / (n * n)
    if pe == 1.0: return 1.0
    return (po - pe) / (1 - pe)

def estimates(rows: List[Tuple[str, str]], N: Dict[str, int]) -> Tuple[Dict[str, float], Any]:
    """Estimates population metrics using stratified sampling weights."""
    n = collections.Counter(s for _, s in rows)
    W = collections.defaultdict(float)
    for t, s in rows:
        W[(t, s)] += N[s] / n[s] if n[s] else 0
        
    g = lambda t, s: W[(t, s)]
    tot_t = lambda t: sum(g(t, s) for s in ("ok", "wrong", "abstain"))
    dec = N["ok"] + N["wrong"]; tot = dec + N["abstain"]
    
    m = {
        "false_ok": g("wrong", "ok"), 
        "false_wrong": g("ok", "wrong"),
        "ok_unsure_decided": g("unsure", "ok"), 
        "wrong_unsure_decided": g("unsure", "wrong"),
        "ok_recall": g("ok", "ok") / tot_t("ok") if tot_t("ok") else float("nan"),
        "wrong_recall": g("wrong", "wrong") / tot_t("wrong") if tot_t("wrong") else float("nan"),
        "coverage": dec / tot if tot else float("nan"),
        "needless_abstain": (g("ok", "abstain") + g("wrong", "abstain")) / N["abstain"] if N["abstain"] else float("nan"),
        "sel_error_lenient": (g("wrong", "ok") + g("ok", "wrong")) / dec if dec else float("nan"),
        "sel_error_strict": (g("wrong", "ok") + g("ok", "wrong") + g("unsure", "ok") + g("unsure", "wrong")) / dec if dec else float("nan"),
    }
    return m, W

def compute_risk_coverage(pairs: List[Tuple[dict, dict]]) -> Tuple[float, float]:
    """Computes AURC (Area Under Risk-Coverage) and SAC (Selective Accuracy Constraint)."""
    # Extract confidence and determine if prediction is correct (truth == prediction, ignoring unsure)
    scored_preds = []
    for g, r in pairs:
        if g["truth"] == "unsure":
            continue
        conf = float(r.get("confidence", 1.0 if side(r.get("verdict")) in ("ok", "wrong") else 0.5))
        pred = side(r.get("verdict"))
        is_error = (g["truth"] == "ok" and pred == "wrong") or (g["truth"] == "wrong" and pred == "ok")
        scored_preds.append((conf, is_error))

    if not scored_preds:
        return float('nan'), float('nan')

    # Sort by confidence descending (highest confidence first)
    scored_preds.sort(key=lambda x: x[0], reverse=True)
    
    cum_errors = 0
    risk_values = []
    sac_at_95 = None
    
    for i, (conf, is_error) in enumerate(scored_preds):
        if is_error: cum_errors += 1
        coverage = (i + 1) / len(scored_preds)
        risk = cum_errors / (i + 1)
        risk_values.append(risk)
        
        # Selective Accuracy Constraint: Find max coverage where error rate <= 5% (accuracy >= 95%)
        if sac_at_95 is None and (1 - risk) >= 0.95:
            sac_at_95 = coverage
            
    aurc = sum(risk_values) / len(risk_values) if risk_values else 0
    return aurc, sac_at_95 or 0.0

def bootstrap_ci(rows: List[Tuple[str, str]], N: Dict[str, int], iters: int = 1000) -> Dict[str, Tuple[float, float]]:
    """Computes 95% Bootstrap Confidence Intervals for population estimates."""
    if not rows: return {}
    random.seed(42)
    by_stratum = collections.defaultdict(list)
    for r in rows: by_stratum[r[1]].append(r)
    
    metrics_history = collections.defaultdict(list)
    
    for _ in range(iters):
        # Resample within each stratum to maintain population distribution
        samp = []
        for s in ("ok", "wrong", "abstain"):
            if N.get(s, 0) > 0 and by_stratum[s]:
                samp.extend(random.choice(by_stratum[s]) for _ in range(len(by_stratum[s])))
        mm, _ = estimates(samp, N)
        for k, v in mm.items():
            if not math.isnan(v):
                metrics_history[k].append(v)
                
    ci = {}
    for k, v in metrics_history.items():
        v.sort()
        ci[k] = (v[max(0, int(0.025 * len(v)))], v[min(len(v)-1, int(0.975 * len(v)) - 1)])
    return ci

def main():
    ap = argparse.ArgumentParser(description="Advanced Validator Metrics Evaluator")
    ap.add_argument("--gold", required=True, help="Path to gold truth (csv/json)")
    ap.add_argument("--result", required=True, help="Path to validator result (json)")
    ap.add_argument("--cost-false-ok", type=float, default=10)
    ap.add_argument("--cost-false-wrong", type=float, default=3)
    ap.add_argument("--cost-review", type=float, default=1)
    ap.add_argument("--boot", type=int, default=1000, help="Bootstrap iterations")
    ap.add_argument("--top", type=int, default=20, help="Max errors to print")
    ap.add_argument("--json-out", type=str, default=None, help="Path to save metrics as JSON")
    a = ap.parse_args()

    gold = load_gold(a.gold)
    with open(a.result, encoding="utf-8") as f:
        res_data = json.load(f)
    res = {str(r["id"]): r for r in res_data.get("records", [])}

    N = collections.Counter(side(r.get("verdict")) for r in res.values())
    for k in ("ok", "wrong", "abstain"):
        N.setdefault(k, 0)
        
    pairs = [(gold[i], res[i]) for i in gold if i in res]
    rows = [(g["truth"], side(r.get("verdict"))) for g, r in pairs]
    total = sum(N.values())

    print(f"metrics.py | gold={a.gold} | result={a.result}")
    print(f"result rows: {total} | labeled & matched: {len(pairs)} | unmatched gold ids: {len(set(gold) - set(res))}\n")

    # --- 1. SYSTEM ACTIONS ---
    print("== 1. WHAT THE SYSTEM DID (all rows) ==")
    for k, lab in (("ok", "ok (publish)"), ("wrong", "wrong (discard)"), ("abstain", "abstain (human review)")):
        pct = 100 * N[k] / total if total else 0
        print(f"  {lab:34s}{N[k]:7d}  {pct:5.1f}%")
    coverage = 100 * (N['ok'] + N['wrong']) / total if total else 0
    print(f"  automation (coverage) = {coverage:.1f}%   review load = {100 * N['abstain'] / total if total else 0:.1f}%\n")

    # --- 2. CONFUSION MATRIX ---
    print("== 2. CONFUSION (labeled rows, raw counts) ==")
    c = collections.Counter(rows)
    print(f"  {'truth \\ system':16s}{'ok':>6s}{'wrong':>7s}{'abstain':>9s}")
    for t in ("ok", "unsure", "wrong"): 
        print(f"  {t:16s}{c[(t,'ok')]:6d}{c[(t,'wrong')]:7d}{c[(t,'abstain')]:9d}")
    print()

    # --- 3. STRATIFIED ESTIMATES & BOOTSTRAP ---
    m, _ = estimates(rows, N)
    ci = bootstrap_ci(rows, N, a.boot) if not (len(pairs) == total) else {}

    print("== 3. POPULATION ESTIMATES (95% Bootstrap CI) ==")
    def show(name, key, pct=True):
        v = m[key]
        s = f"{100*v:.1f}%" if pct and not math.isnan(v) else f"{v:.0f}" if not pct and not math.isnan(v) else "nan"
        if ci and key in ci:
            l, h = ci[key]
            s += f"   CI [{100*l:.1f}%, {100*h:.1f}%]" if pct else f"   CI [{l:.0f}, {h:.0f}]"
        print(f"  {name:56s}{s}")

    show("ok recall (valid items that reach 'ok')", "ok_recall")
    show("wrong recall (junk removed automatically)", "wrong_recall")
    show("needless abstentions (clear cases sent to humans)", "needless_abstain")
    show("selective error, lenient", "sel_error_lenient")
    show("selective error, strict", "sel_error_strict")
    show("estimated FALSE OK rows in whole result", "false_ok", pct=False)
    show("estimated FALSE WRONG rows in whole result", "false_wrong", pct=False)

    # --- 4. RISK-COVERAGE & AURC ---
    aurc, sac = compute_risk_coverage(pairs)
    print("\n== 4. RISK-COVERAGE CURVE ==")
    print(f"  AURC (Area Under Risk-Coverage) : {aurc:.4f} (Lower is better)")
    print(f"  SAC (Coverage at >=95% accuracy): {100*sac:.1f}%")

    # --- 5. CALIBRATION (LLM Judge vs Gold) ---
    y_true = [g["truth"] for g in gold.values() if g["truth"] != "unsure"]
    y_pred = [side(res[i].get("verdict")) for i in gold if i in res and gold[i]["truth"] != "unsure"]
    kappa = cohens_kappa(y_true, y_pred)
    print(f"\n== 5. CALIBRATION (Cohen's Kappa) ==")
    print(f"  Agreement between Gold & System: {kappa:.4f}")
    print("  ( >0.8 Excellent, 0.6-0.8 Good, <0.6 Needs Improvement )\n")

    # --- 6. COST FUNCTION ---
    cost = a.cost_false_ok * m["false_ok"] + a.cost_false_wrong * m["false_wrong"] + a.cost_review * N["abstain"]
    print(f"== 6. BUSINESS COST ==")
    print(f"  Cost = {a.cost_false_ok:g} * false_ok + {a.cost_false_wrong:g} * false_wrong + {a.cost_review:g} * reviewed")
    print(f"  Total Cost: {cost:.0f}   ({1000*cost/total if total else 0:.0f} per 1000 rows)\n")

    # --- 7. ERRORS TO READ ---
    print(f"== 7. ERRORS TO READ ==")
    for title, cond in (("FALSE OK (system ok, truth wrong)", lambda g, r: side(r.get("verdict")) == "ok" and g["truth"] == "wrong"),
                        ("FALSE WRONG (system wrong, truth ok)", lambda g, r: side(r.get("verdict")) == "wrong" and g["truth"] == "ok")):
        bad = [(g, r) for g, r in pairs if cond(g, r)]
        print(f"  {title}: {len(bad)}")
        for g, r in bad[:a.top]: 
            print(f"     {g.get('name', r.get('name', ''))} | {r.get('source_layer')} | {r.get('reason_en', r.get('reason', ''))[:70]}")

    # --- OUTPUT JSON ---
    if a.json_out:
        out_data = {
            "overall_estimates": dict(m),
            "risk_coverage": {"aurc": aurc, "sac_at_95": sac},
            "agreement_kappa": kappa,
            "raw_counts": {f"{t}_{s}": c[(t,s)] for t in ("ok", "unsure", "wrong") for s in ("ok", "wrong", "abstain")},
            "system_action_counts": dict(N),
            "cost": cost,
            "total_rows": total,
            "labeled_rows": len(pairs),
            "is_census": len(pairs) == total
        }
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(out_data, f, indent=2, ensure_ascii=False)
        print(f"\n[+] Saved detailed metrics JSON to {a.json_out}")

if __name__ == "__main__":
    main()