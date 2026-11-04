import re, yaml

def load_taxonomy(path: str) -> dict:
    if not path: return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f).get("categories", {})

# Defaults mirror the old hardcoded behaviour; override them in museum.yaml (see museum_patched.yaml)
DEFAULTS = {
    "allowed_typecodes":       ["140100", "140200", "140400", "110204"],
    "hard_exclude_typecodes":  ["141100", "141200", "141400"],   # media, schools, training (old code missed 141400)
    "review_typecodes":        ["140300"],                        # convention/expo centers: ambiguous -> human
    "excluded_categories":     ["shopping", "food", "accommodation"],   # certain -> wrong
    "review_categories":       ["scenic", "sports"],                    # ambiguous -> suspicious
    # museum-like but ambiguous words: a scenic/sports POI containing one goes to the LLM instead of being rejected
    "museumish_keywords":      ["故居", "旧居", "遗址", "旧址", "纪念", "陈列", "展", "艺术", "文化", "遗产", "古迹", "非遗",
                                "Heritage", "Memorial", "Historic", "Art"],
    # certain non-museum types, matched against the Chinese `type` path / `keytag` text (verifiable in your data)
    "hard_exclude_type_keywords": ["学校", "高等院校", "中学", "小学", "幼儿园", "成人教育", "职业技术学校",
                                   "科研机构", "培训机构", "传媒机构", "图书馆", "档案馆", "文艺团体"],
    # inside review typecodes (e.g. 140300 convention centers): meeting rooms / hotels are certainly not museums
    "review_wrong_keywords":   ["会议", "议事", "宴会", "宾馆", "酒店", "饭店", "山庄", "度假", "大厦", "礼堂", "会堂", "影视厅", "报告厅", "教室"],
    # categories where a museum can legitimately be typed; any OTHER known/unknown category is not a museum
    "museum_possible_categories": ["culture", "scenic"],
    # narrow museum-like words: in an excluded category they send the POI to the LLM instead of auto-wrong
    "strong_museumish_keywords": ["故居", "旧居", "旧址", "陈列", "展览", "展示", "遗址", "纪念", "非遗", "遗产"],
    "ok_suffixes": ["展"],            # name ENDING with 展 = an exhibition (not 发展/进展/开展...)
    "ok_keywords":             ["博物馆", "博物院", "美术馆", "展览馆", "纪念馆", "画廊", "陈列馆", "陈列室", "展陈馆", "展示馆", "艺术展", "大展", "特展", "非遗馆", "展览", "艺廊", "博展馆", "Museum", "Gallery", "Exhibition"],
}

def _cfg(intent, key):
    return intent.get(key) or DEFAULTS[key]

_NOT_EXHIBITION = ("发展", "进展", "开展", "扩展", "舒展", "伸展", "拓展")

def name_has_ok(name: str, intent: dict) -> bool:
    """Explicit museum/gallery/exhibition wording: keyword anywhere, or name ending in 展 (brackets ignored)."""
    n = str(name or "").lower()
    if any(k.lower() in n for k in _cfg(intent, "ok_keywords")):
        return True
    core = re.sub(r"[（(][^）)]*[）)]\s*$", "", n).strip()
    return any(core.endswith(suf) for suf in _cfg(intent, "ok_suffixes")) and not core.endswith(_NOT_EXHIBITION)

def _stems(codes):                       # "140100" -> "1401", "110204" -> "110204"
    return tuple(c.rstrip("0") or c for c in codes)

def normalize_typecodes(raw) -> list[str]:
    """Handle '140100', 140100.0, 60100 (lost leading zero), and 'a|b' multi-codes."""
    out = []
    for part in str(raw or "").replace(",", "|").split("|"):
        p = part.strip()
        if p.endswith(".0"): p = p[:-2]
        if p.isdigit():
            out.append(p.zfill(6) if len(p) == 5 else p)
    return out

def _kind(code, intent, taxonomy):
    if code.startswith(_stems(_cfg(intent, "allowed_typecodes"))):       return "allowed"
    if code.startswith(_stems(_cfg(intent, "hard_exclude_typecodes"))):  return "hard"
    if code.startswith(_stems(_cfg(intent, "review_typecodes"))):        return "review"
    cat = taxonomy.get(code[:2], {}).get("name", "unknown")
    if cat in _cfg(intent, "excluded_categories"):                       return "hard"
    if cat in _cfg(intent, "review_categories"):                         return "review_cat"
    if taxonomy and cat not in _cfg(intent, "museum_possible_categories"): return "hard"   # life service, medical, company, ... (incl. unknown prefixes)
    return "none"

def _res(verdict, reason, code):
    return {"verdict": verdict, "reason": reason, "suspicious_fields": ["typecode"],
            "suggested_action": "exclude" if verdict == "wrong" else "review", "source_layer": "rule"}

def hard_type_hit(record: dict, intent: dict) -> str:
    text = f'{record.get("type", "")};{record.get("keytag", "")}'
    return next((k for k in _cfg(intent, "hard_exclude_type_keywords") if k in text), "")

def rule_check(record: dict, intent: dict, taxonomy: dict) -> dict | None:
    codes = normalize_typecodes(record.get("typecode"))
    kinds = {_kind(c, intent, taxonomy) for c in codes}
    shown = "|".join(codes)
    th = hard_type_hit(record, intent)
    if th:
        kinds.add("hard"); shown = shown or f"type:{th}"
    kinds.discard("none")                 # a neutral typecode (e.g. other 14xxxx) is no evidence either way
    if not kinds:
        # No typecode/type evidence. Explicit Chinese excluded keyword, and nothing museum-like in the name -> wrong.
        name = str(record.get("name") or record.get("title") or "").lower()
        hit = next((k for k in intent.get("wrong_keywords", []) if any("\u4e00" <= ch <= "\u9fff" for ch in k) and k in name), "")
        if hit and not (name_has_ok(name, intent) or any(k.lower() in name for k in _cfg(intent, "museumish_keywords"))):
            return _res("wrong", f"Name contains excluded keyword '{hit}' and nothing museum-like", hit)
        return None                       # otherwise the LLM decides

    if "allowed" in kinds:
        # allowed code wins, but a conflicting second code is a human question
        return _res("suspicious", f"Typecodes {shown} conflict (allowed + excluded/review)", shown) if kinds & {"hard", "review"} else None

    name = str(record.get("name") or record.get("title") or "").lower()
    name_ok = name_has_ok(name, intent)

    if "hard" in kinds:
        if name_ok:   # museum-like name but excluded typecode: never decide alone
            return _res("suspicious", f"Name has museum keyword but typecode {shown} is excluded", shown)
        if any(k in name for k in _cfg(intent, "strong_museumish_keywords")):
            return None   # heritage/exhibit wording in an excluded category: let the LLM look
        return _res("wrong", f"Typecode {shown} is an excluded type/category and name has no museum keyword", shown)
    if "review" in kinds:                 # specific typecode that is truly ambiguous (e.g. 140300 expo centers)
        if not name_ok and not any(k in name for k in ("会展", "博览", "展")) and any(k in name for k in _cfg(intent, "review_wrong_keywords")):
            return _res("wrong", f"Typecode {shown} is ambiguous but the name is a meeting room/hotel/building", shown)
        return _res("suspicious", f"Typecode {shown} is ambiguous for this objective", shown)
    if "review_cat" in kinds:             # scenic / sports: certain non-museum category unless the name hints otherwise
        museumish = any(k.lower() in name for k in _cfg(intent, "museumish_keywords"))
        if name_ok or museumish:
            return None                   # let tripwire + LLM look at it
        return _res("wrong", f"Typecode {shown} is a scenic/sports category and the name has no museum-like word", shown)
    return None

def strong_ok(record: dict, intent: dict, taxonomy: dict) -> bool:
    """Two independent signals agree: allowed museum typecode AND an explicit museum keyword in the name.
    (The caller must still make sure the tripwire did not fire.)"""
    codes = normalize_typecodes(record.get("typecode"))
    if not codes or {_kind(c, intent, taxonomy) for c in codes} != {"allowed"}:
        return False
    return name_has_ok(record.get("name") or record.get("title") or "", intent)