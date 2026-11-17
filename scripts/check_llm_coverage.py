"""Check that every record the rule layer does not reject goes through the LLM.

``llm_judge`` is replaced with a stub, so this runs offline and needs no API key.
It asserts that:
  * records ruled 'wrong' skip the LLM,
  * every other record is sent to the LLM exactly once,
  * no record is marked 'ok' without the LLM having said so.

Run:  .venv\\Scripts\\python.exe scripts\\check_llm_coverage.py
"""

import json
import os
from collections import Counter

# The pipeline still refuses use_llm=True without the env var; a stub does not need a real key.
os.environ.setdefault("DASHSCOPE_API_KEY", "offline-stub-key")
# Keep stub verdicts out of the real cache, otherwise later real runs would replay them.
_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".verify_cache.jsonl")
os.environ["LLM_CACHE_PATH"] = _CACHE
if os.path.exists(_CACHE):
    os.remove(_CACHE)

import yaml  # noqa: E402

import exhibit_validator.pipeline as pipeline  # noqa: E402

INPUT = "data/raw/test_small_30.json"
INTENT = "configs/intents/museum.yaml"
TAXONOMY = "configs/taxonomy.yaml"

calls = []


def stub_judge(record, intent, extra_context="", attempts=3):
    calls.append(record.get("id"))
    name = str(record.get("name") or "")
    # Deterministic fake: names with an obvious non-museum word come back 'wrong'.
    if any(w in name for w in ("学校", "公司", "酒店", "商店")):
        return {"verdict": "wrong", "reason": "stub: non-museum", "reason_en": "stub: non-museum",
                "reason_code": "stub", "confidence": 0.5}
    return {"verdict": "ok", "reason": "stub: museum", "reason_en": "stub: museum",
            "reason_code": "stub", "confidence": 0.5}


pipeline.llm_judge = stub_judge

with open(INTENT, encoding="utf-8") as f:
    intent = yaml.safe_load(f)

result = pipeline.run_pipeline(INPUT, intent, TAXONOMY, use_llm=True)

with open(INPUT, encoding="utf-8") as f:
    raw = json.load(f)
records = raw.get("points", raw) if isinstance(raw, dict) else raw

counts = Counter(r["verdict"] for r in result["records"])
rule_wrong = sum(1 for r in result["records"] if r["source_layer"] == "rule")
print()
print("=" * 62)
print(f"input records          : {len(records)}")
print(f"llm_judge calls        : {len(calls)}")
print(f"rule 'wrong' (no LLM)  : {rule_wrong}")
print(f"verdicts               : {dict(counts)}")
print(f"summary from pipeline  : {result['summary']}")
missing_id = [r for r in result["records"] if not r.get("id")]
print(f"records missing id     : {len(missing_id)}")
print("=" * 62)

expected_llm = len(records) - rule_wrong
assert len(calls) == expected_llm, f"LLM saw {len(calls)} records, expected {expected_llm}"
assert len(calls) == len(set(calls)), "a record was sent to the LLM twice"
assert not missing_id, "output has records without id"
assert counts["ok"] <= len(calls), "more 'ok' verdicts than LLM answers"
if os.path.exists(_CACHE):
    os.remove(_CACHE)  # never leave stub verdicts behind
print("PASS: every non-wrong record went through the LLM; no free 'ok'.")
