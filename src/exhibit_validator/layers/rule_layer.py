import re
import yaml

def load_taxonomy(path: str) -> dict:
    if not path: return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f).get("categories", {})

DEFAULTS = {
    "allowed_typecodes": ["140100", "140200", "140400", "110204"],
    "hard_exclude_typecodes": ["141100", "141200", "141400"],
    "excluded_categories": ["shopping", "food", "accommodation"],
    "ok_keywords": ["博物馆", "博物院", "美术馆", "展览馆", "纪念馆", "画廊", "Museum", "Gallery", "Exhibition"],
    "wrong_keywords": [
        "动物园", "水族馆", "游乐园", "学校", "大学", "学院", "图书馆", "公司", "医院", "宾馆", "酒店", 
        "商店", "餐厅", "咖啡", "茶楼", "办公", "培训", "店", "民宿", "火腿", "婚纱", "百货", "购物中心", "美食", "隔热膜"
    ],
}

def _cfg(intent, key):
    return intent[key] if key in intent else DEFAULTS.get(key, [])

def normalize_typecodes(raw) -> list[str]:
    out = []
    for part in str(raw or "").replace(",", "|").split("|"):
        p = part.strip()
        if p.endswith(".0"): p = p[:-2]
        if p.isdigit(): out.append(p.zfill(6) if len(p) == 5 else p)
    return out

def _kind(code, intent, taxonomy):
    if code.startswith(tuple(c.rstrip("0") or c for c in _cfg(intent, "allowed_typecodes"))): return "allowed"
    if code.startswith(tuple(c.rstrip("0") or c for c in _cfg(intent, "hard_exclude_typecodes"))): return "hard"
    cat = taxonomy.get(code[:2], {}).get("name", "unknown")
    if cat in _cfg(intent, "excluded_categories"): return "hard"
    return "none"

def name_has_ok(name: str, intent: dict) -> bool:
    n = str(name or "").lower()
    return any(k.lower() in n for k in _cfg(intent, "ok_keywords"))

def rule_check(record: dict, intent: dict, taxonomy: dict) -> dict | None:
    codes = normalize_typecodes(record.get("typecode"))
    kinds = {_kind(c, intent, taxonomy) for c in codes}
    shown = "|".join(codes)
    name = str(record.get("name") or record.get("title") or "").lower()
    
    # 1. Structural hard exclude. A record carrying both an allowed museum code
    #    and an excluded code is ambiguous, not "hard" -> let the LLM judge it.
    if "hard" in kinds and "allowed" not in kinds and not name_has_ok(name, intent):
        return {
            "verdict": "wrong", "rule_id": "hard_exclude_typecode", "reason_code": "excluded_typecode",
            "reason": f"类型码 {shown} 属于排除类别", "reason_en": f"Typecode {shown} excluded",
            "source_layer": "rule"
        }

    # 2. Keyword-based Hard Exclude
    hit_wrong = next((k for k in _cfg(intent, "wrong_keywords") if k.lower() in name), "")
    if hit_wrong:
        # If name contains BOTH good and bad keywords, let LLM decide (e.g., "Museum Shop")
        if any(k.lower() in name for k in _cfg(intent, "ok_keywords")):
            return None 
        return {
            "verdict": "wrong", "rule_id": "wrong_keyword_in_name", "reason_code": "excluded_keyword_in_name",
            "reason": f"名称包含排除词“{hit_wrong}”", "reason_en": f"Name contains '{hit_wrong}'",
            "source_layer": "rule"
        }

    # 3. FORCE EVERYTHING ELSE TO LLM
    # Never return "ok" or "suspicious". Return None so pipeline sends it to LLM.
    return None

def strong_ok(record: dict, intent: dict, taxonomy: dict) -> bool:
    return False