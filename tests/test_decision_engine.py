from exhibit_validator.layers.decision_engine import decide

def test_rule_wrong_immediate_reject():
    rule = {"verdict": "wrong", "reason": "Shopping category excluded.","source_layer": "rule"}
    final = decide(rule, None)
    assert final["final_action"] == "reject"
    assert final["source_layer"] == "rule"

def test_llm_overrides_rule_suspicious():
    rule = {"verdict": "suspicious", "reason": "Typecode mismatch."}
    llm = {"verdict": "ok", "reason": "Name and address confirm it is a museum.", "source_layer": "llm_judge"}
    final = decide(rule, llm)
    assert final["verdict"] == "ok"
    assert final["source_layer"] == "llm_judge" 
    assert "Name and address confirm" in final["reason"]