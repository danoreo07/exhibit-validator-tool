from pydantic import BaseModel, Field
from typing import List, Literal

VerdictType = Literal["ok", "suspicious", "wrong", "out_of_scope"]
ActionType = Literal["keep", "review", "exclude"]

class RecordResult(BaseModel):
    id: str
    name: str
    typecode: str
    address: str
    verdict: VerdictType
    reason: str
    suspicious_fields: List[str] = Field(default_factory=list)
    
    # Unified action field
    suggested_action: ActionType = "keep" 
    
    source_layer: str = "rule"
    in_scope: bool = True

def normalize_output(raw_results: list[dict]) -> list[dict]:
    """
    Ensures all results from different layers (even if they return messy dicts)
    are forced into a standard format before writing to JSON.
    """
    ACTION_MAP = {
        "accept": "keep",
        "needs_review": "review",
        "exclude": "exclude",
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
        in_scope = (v in ["ok", "suspicious"])
        
        res = RecordResult(
            id=r.get("id", "MISSING_ID"),
            name=r.get("name", ""),
            typecode=r.get("typecode", ""),
            address=r.get("address", ""),
            verdict=v,
            reason=r.get("reason", ""),
            suspicious_fields=r.get("suspicious_fields", []),
            suggested_action=action,
            source_layer=r.get("source_layer", "rule"),
            in_scope=in_scope
        )
        normalized.append(res.model_dump())
        
    return normalized