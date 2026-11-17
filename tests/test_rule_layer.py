import yaml

from exhibit_validator.layers.rule_layer import load_taxonomy, rule_check

TAXONOMY = load_taxonomy("configs/taxonomy.yaml")
with open("configs/intents/tourist_attraction.yaml", encoding="utf-8") as f:
    INTENT = yaml.safe_load(f)


def test_shopping_record_is_excluded():
    record = {"id": "1", "name": "361度OUTLET", "typecode": "061101", "address": "..."}
    result = rule_check(record, INTENT, TAXONOMY)
    assert result is not None
    assert result["verdict"] == "wrong"
    assert result["rule_id"] == "hard_exclude_typecode"


def test_scenic_record_passes():
    record = {"id": "2", "name": "西湖", "typecode": "110000", "address": "..."}
    assert rule_check(record, INTENT, TAXONOMY) is None


def test_unprovable_record_is_left_to_the_llm():
    # The rule layer only rejects; anything it cannot prove wrong must reach the LLM.
    record = {"id": "3", "name": "", "typecode": "110000", "address": ""}
    assert rule_check(record, INTENT, TAXONOMY) is None
