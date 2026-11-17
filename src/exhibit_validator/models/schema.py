from typing import Literal

from pydantic import BaseModel, Field, model_validator

VerdictType = Literal["ok", "suspicious", "wrong", "needs_review", "out_of_scope"]
ActionType = Literal["keep", "review", "exclude"]


class RecordResult(BaseModel):
    """Normalized per-record verdict.

    ``reason`` is the human-readable message for end users and is written in
    Chinese. ``reason_en`` carries the same rationale in English for debugging.
    All machine-readable identifiers and codes (``verdict``, ``reason_code``,
    ``rule_id``) are English ASCII.
    """

    id: str
    name: str
    typecode: str
    address: str
    verdict: VerdictType
    reason: str
    reason_en: str = ""
    suspicious_fields: list[str] = Field(default_factory=list)

    # Unified action field
    suggested_action: ActionType = "keep"

    source_layer: str = "rule"
    in_scope: bool = True

    # Additive fields: defaults keep legacy payloads valid.
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Verdict confidence: 1.0 for rule-based results, 0.5 for LLM judgement.",
    )
    reason_code: str = Field(
        default="",
        description="Machine-readable reason code, e.g. 'ambiguous_typecode' or 'missing_field'.",
    )
    rule_id: str = Field(default="", description="ID of the rule that triggered, if any.")
    ambiguity_signals: list[str] = Field(
        default_factory=list,
        description="Signals that made the verdict ambiguous.",
    )
    tripwire_flag: bool = Field(
        default=False,
        description="Tripwire raised a flag. Advisory only: the LLM verdict stands.",
    )

    @model_validator(mode="before")
    @classmethod
    def _apply_confidence_default(cls, data: object) -> object:
        """Derive the default confidence from ``source_layer`` when it is absent."""
        if isinstance(data, dict) and data.get("confidence") is None:
            source = str(data.get("source_layer") or "rule").lower()
            return {**data, "confidence": 0.5 if source.startswith("llm") else 1.0}
        return data


def normalize_output(raw_results: list[dict]) -> list[dict]:
    """
    Ensures all results from different layers (even if they return messy dicts)
    are forced into a standard format before writing to JSON.
    """
    ACTION_MAP = {
        "accept": "keep",
        "needs_review": "review",
        "exclude": "exclude",
        "reject": "exclude",
        "keep": "keep",
        "review": "review"
    }

    normalized = []
    for r in raw_results:
        # Handle legacy action fields (prioritize suggested_action, fallback to final_action)
        raw_action = r.get("suggested_action") or r.get("final_action") or "review"
        action = ACTION_MAP.get(raw_action, "review")

        # Determine in_scope based on verdict
        v = r.get("verdict", "suspicious")
        in_scope = v in ("ok", "suspicious", "needs_review")

        res = RecordResult(
            id=r.get("id", "MISSING_ID"),
            name=r.get("name", ""),
            typecode=r.get("typecode", ""),
            address=r.get("address", ""),
            verdict=v,
            reason=r.get("reason", ""),
            reason_en=r.get("reason_en") or r.get("reason", ""),
            suspicious_fields=r.get("suspicious_fields", []),
            suggested_action=action,
            source_layer=r.get("source_layer", "rule"),
            in_scope=in_scope,
            confidence=r.get("confidence"),
            reason_code=r.get("reason_code") or "",
            rule_id=r.get("rule_id") or "",
            ambiguity_signals=r.get("ambiguity_signals") or [],
            tripwire_flag=bool(r.get("tripwire_flag", False)),
        )
        normalized.append(res.model_dump())

    return normalized
