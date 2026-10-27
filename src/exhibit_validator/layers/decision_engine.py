def decide(rule_result: dict | None, llm_result: dict | None) -> dict:
    # 1. Rule says wrong -> reject immediately (LLM is not called for this)
    if rule_result and rule_result["verdict"] == "wrong":
        return {**rule_result, "final_action": "reject"}

    # 2. If LLM ran successfully and gave a verdict
    if llm_result and llm_result.get("verdict") in ("ok", "suspicious", "wrong"):
        # Override the layer to always show LLM made the final call
        final_action = "accept" if llm_result["verdict"] == "ok" else "needs_review"
        
        return {
            "verdict": llm_result["verdict"],
            "reason": llm_result.get("reason", "No reason provided."),
            "suspicious_fields": llm_result.get("suspicious_fields", []),
            "final_action": final_action,
            "source_layer": "llm_judge",  # Always tag as LLM
        }

    # 3. Fallback: Rule says suspicious, but LLM failed/unknown
    if rule_result and rule_result["verdict"] == "suspicious":
        return {**rule_result, "final_action": "needs_review"}

    # 4. All checks passed
    return {
        "verdict": "ok",
        "reason": "All checks passed.",
        "suspicious_fields": [],
        "final_action": "accept",
        "source_layer": "decision",
    }