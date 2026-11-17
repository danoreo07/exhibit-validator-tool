VALID = ("ok", "suspicious", "wrong")


def _reason_pair(result: dict | None, default_zh: str, default_en: str) -> tuple[str, str]:
    """Return (Chinese, English) reasons, falling back for legacy results."""
    result = result or {}
    reason_zh = result.get("reason") or default_zh
    reason_en = result.get("reason_en") or result.get("reason") or default_en
    return reason_zh, reason_en


def decide(rule_result: dict | None, llm_result: dict | None) -> dict:
    """Combine layers.

    Policy: only an explicit rule 'wrong' rejects a record. Every other layer
    (tripwire, soft rule flags) is advisory, and the LLM judgement is final.
    """
    rule_result = rule_result or {}
    llm_result = llm_result or {}
    rule_v = rule_result.get("verdict")

    # 1. Hard rule says wrong -> reject (LLM not needed)
    if rule_v == "wrong":
        reason_zh, reason_en = _reason_pair(
            rule_result, "规则判定为排除", "Rule marked the record as wrong"
        )
        return {
            **rule_result,
            "final_action": "reject",
            "reason": reason_zh,
            "reason_en": reason_en,
            "rule_id": rule_result.get("rule_id", ""),
            "reason_code": rule_result.get("reason_code", ""),
        }

    llm_v = llm_result.get("verdict")
    llm_v = llm_v.strip().lower() if isinstance(llm_v, str) else None

    # 2. LLM missing / "unknown" / invalid -> never ok
    if llm_v not in VALID:
        why_zh, why_en = _reason_pair(llm_result, "无 LLM 结果", "no LLM result")
        extra_zh = ""
        extra_en = ""
        if rule_v == "suspicious":
            rule_zh, rule_en = _reason_pair(rule_result, "未知原因", "unknown reason")
            extra_zh = f"；规则：{rule_zh}"
            extra_en = f"; rule: {rule_en}"
        return {
            "verdict": "suspicious",
            "reason": f"LLM 不可用（{why_zh}）{extra_zh}",
            "reason_en": f"LLM unavailable ({why_en}){extra_en}",
            "suspicious_fields": [],
            "final_action": "needs_review",
            "source_layer": "decision",
            "rule_id": rule_result.get("rule_id", ""),
            "reason_code": "llm_unavailable",
        }

    # 3. Otherwise the LLM verdict stands: tripwire/rule flags below 'wrong'
    #    are advisory and are reported separately, they never downgrade the LLM.
    reason_zh, reason_en = _reason_pair(llm_result, "未提供原因", "No reason provided.")
    return {
        "verdict": llm_v,
        "reason": reason_zh,
        "reason_en": reason_en,
        "suspicious_fields": llm_result.get("suspicious_fields", []),
        "final_action": "accept" if llm_v == "ok" else "needs_review",
        "source_layer": "llm_judge",
        "rule_id": llm_result.get("rule_id") or rule_result.get("rule_id", ""),
        "reason_code": (
            llm_result.get("reason_code") or rule_result.get("reason_code", "")
        ),
    }
    # NOTE: the old step 4 ("All checks passed" -> ok) is removed on purpose:
    # no evidence must never mean ok.
