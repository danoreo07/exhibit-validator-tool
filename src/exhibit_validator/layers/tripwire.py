import re

# Trap 1: Museum keyword used as a street, station, or parking lot name
ZH_TRAP = re.compile(r"(博物馆|美术馆|展览馆|纪念馆)(路|街|站|停车场|地铁|公交|附近|旁|对面)")

# Trap 2: English exclusions
EN_FLAGS = re.compile(r"\b(school|university|hotel|inn|restaurant|cafe|shop|store|parking|station|zoo|aquarium)\b", re.I)

# Trap 3: Commercial entities masquerading as museums
COMMERCIAL_TRAPS = ["店", "公司", "民宿", "婚纱", "火腿", "百货", "购物中心", "美食", "办公", "中心", "商城"]

def needs_llm_judge_bilingual(record: dict, intent: dict = None) -> tuple[bool, str, str]:
    name = str(record.get("name") or record.get("title") or "")
    
    m = ZH_TRAP.search(name)
    if m:
        return (
            True, 
            f"预检：'{m.group(0)}' 看起来像街道/车站", 
            f"Tripwire: '{m.group(0)}' looks like a street/station"
        )

    # If the name has a museum keyword, check for commercial traps
    if any(k in name for k in ["博物馆", "美术馆"]):
        found_trap = next((t for t in COMMERCIAL_TRAPS if t in name), None)
        if found_trap:
            return (
                True, 
                f"预检：名称疑似商业场所（含“{found_trap}”）", 
                f"Tripwire: Commercial trap detected ('{found_trap}')"
            )
        return False, "", "" 

    m = EN_FLAGS.search(name)
    if m:
        return (
            True, 
            f"预检：名称含 '{m.group(0)}'", 
            f"Tripwire: '{m.group(0)}' found in name"
        )
        
    return False, "", ""