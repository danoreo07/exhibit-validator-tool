VALID = ("ok", "suspicious", "wrong")

def decide(rule_result: dict | None, llm_result: dict | None) -> dict:
    """Combine layers. Principle: 'ok' needs every layer to agree. Any conflict or gap -> suspicious."""
    rule_v = (rule_result or {}).get("verdict")

    # 1. Hard rule says wrong -> reject (LLM not needed)
    if rule_v == "wrong":
        return {**rule_result, "final_action": "reject"}

    llm_v = (llm_result or {}).get("verdict")
    llm_v = llm_v.strip().lower() if isinstance(llm_v, str) else None

    # 2. LLM missing / "unknown" / invalid -> never ok
    if llm_v not in VALID:
        why = (llm_result or {}).get("reason", "no LLM result")
        extra = f"; rule: {rule_result['reason']}" if rule_v == "suspicious" else ""
        return {"verdict": "suspicious", "reason": f"LLM unavailable ({why}){extra}",
                "suspicious_fields": [], "final_action": "needs_review", "source_layer": "decision"}

    # 3. LLM says ok but a rule/tripwire raised a flag -> conflict -> suspicious
    if llm_v == "ok" and rule_v == "suspicious":
        return {"verdict": "suspicious",
                "reason": f"LLM said ok but {rule_result.get('source_layer', 'rule')} flagged: {rule_result.get('reason', '')}",
                "suspicious_fields": (llm_result or {}).get("suspicious_fields", []),
                "final_action": "needs_review", "source_layer": "decision"}

    # 4. Otherwise trust the LLM verdict (already passed guard_verdict upstream)
    return {"verdict": llm_v,
            "reason": llm_result.get("reason", "No reason provided."),
            "suspicious_fields": llm_result.get("suspicious_fields", []),
            "final_action": "accept" if llm_v == "ok" else "needs_review",
            "source_layer": "llm_judge"}
    # NOTE: the old step 4 ("All checks passed" -> ok) is removed on purpose: no evidence must never mean ok.