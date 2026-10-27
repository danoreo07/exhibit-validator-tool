from typing import Tuple

EXCLUDED_KEYWORDS = [
    "学校", "学院", "大学", "小学", "中学", "幼儿园", "校区",
    "培训", "辅导", "补习", "音乐培训", "美术培训",
]

SHOPPING_FOOD_KEYWORDS = [
    "小卖部", "便利店", "超市", "面馆", "餐厅", "饭馆",
    "专卖店", "特产", "服装店", "摄影服务", "租赁",
]

def needs_llm_judge(record: dict) -> Tuple[bool, str]:
        text = " ".join([
        str(record.get("name", "")),
        str(record.get("address", "")),
        str(record.get("keytag", "")),
    ])

    for kw in EXCLUDED_KEYWORDS:
        if kw in text:
            return True, f"Tripwire: keyword '{kw}' in name/address/keytag"
    for kw in SHOPPING_FOOD_KEYWORDS:
        if kw in text:
            return True, f"Tripwire: keyword '{kw}' in name/address/keytag"
    return False, ""