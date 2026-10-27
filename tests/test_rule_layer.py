from exhibit_validator.layers.rule_layer import rule_check, load_taxonomy, load_intent

TAXONOMY = load_taxonomy("configs/taxonomy.yaml")
INTENT = load_intent("configs/intents/tourist_attraction.yaml")


def test_shopping_record_is_excluded():
    record = {"id": "1", "name": "361度OUTLET", "typecode": "061101", "address": "..."}
    result = rule_check(record, INTENT, TAXONOMY)
    assert result is not None
    assert result["verdict"] == "wrong"
    assert "typecode" in result["suspicious_fields"]


def test_scenic_record_passes():
    record = {"id": "2", "name": "西湖", "typecode": "110000", "address": "..."}
    assert rule_check(record, INTENT, TAXONOMY) is None


def test_missing_fields_are_flagged():
    record = {"id": "3", "name": "", "typecode": "110000", "address": ""}
    result = rule_check(record, INTENT, TAXONOMY)
    assert result is not None
    assert result["verdict"] == "suspicious"
    assert "name" in result["suspicious_fields"]