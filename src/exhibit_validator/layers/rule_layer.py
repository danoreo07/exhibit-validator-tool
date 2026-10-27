import yaml

def load_taxonomy(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["categories"]

def load_intent(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

def rule_check(record: dict, intent: dict, taxonomy: dict) -> dict | None:
    """
    Return a verdict dict if the record is rejected or flagged,
    or None if it passes to the next layer.
    """
    typecode = record.get("typecode", "")
    prefix = typecode[:2] if typecode else ""
    category = taxonomy.get(prefix, {}).get("name", "unknown")

    # Excluded categories
    if category in intent.get("excluded_categories", []):
        return {
            "verdict": "wrong",
            "reason": f"Typecode {typecode} belongs to category '{category}', which is excluded by intent.",
            "suspicious_fields": ["typecode", "type"],
            "suggested_action": "exclude",
            "source_layer": "rule",
        }

    # Not in allowed categories
    if category not in intent.get("allowed_categories", []) and category != "unknown":
        return {
            "verdict": "suspicious",
            "reason": f"Typecode {typecode} belongs to category '{category}', which is not in the allowed list.",
            "suspicious_fields": ["typecode"],
            "suggested_action": "review",
            "source_layer": "rule",
        }

    # Subtype rules
    subtype = intent.get("subtype_rules", {})
    allowed_tcs = subtype.get("allowed_typecodes", [])
    excluded_tcs = subtype.get("excluded_typecodes", [])

    if excluded_tcs and typecode in excluded_tcs:
        return {
            "verdict": "wrong",
            "reason": f"Typecode {typecode} is explicitly excluded by subtype rules.",
            "suspicious_fields": ["typecode"],
            "suggested_action": "exclude",
            "source_layer": "rule",
        }

    if allowed_tcs and typecode not in allowed_tcs:
        return {
            "verdict": "suspicious",
            "reason": f"Typecode {typecode} is not in the allowed subtype list.",
            "suspicious_fields": ["typecode"],
            "suggested_action": "review",
            "source_layer": "rule",
        }

    # Missing required fields
    missing = [f for f in ["name", "typecode", "address"] if not record.get(f)]
    if missing:
        return {
            "verdict": "suspicious",
            "reason": f"Missing required fields: {missing}",
            "suspicious_fields": missing,
            "suggested_action": "review",
            "source_layer": "rule",
        }

    return None