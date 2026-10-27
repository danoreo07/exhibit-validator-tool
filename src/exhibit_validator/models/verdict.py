from dataclasses import dataclass, field
from typing import Literal

@dataclass
class Verdict:
    id: str
    name: str
    verdict: Literal["ok", "suspicious", "wrong"]
    reason: str
    suspicious_fields: list[str] = field(default_factory=list)
    suggested_action: str = "keep"
    source_layer: Literal["rule", "matching", "llm_judge"] = "rule"