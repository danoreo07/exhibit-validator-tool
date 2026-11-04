import re
from typing import Tuple

# Chinese: substring match (no word boundaries). Checked on name + address + keytag, like before.
ZH_FLAGS = [
    "学校", "学院", "大学", "小学", "中学", "幼儿园", "校区", "培训", "辅导", "补习", "画室",
    "小卖部", "便利店", "超市", "面馆", "餐厅", "饭馆", "专卖店", "特产", "服装店", "摄影", "租赁",
    "酒店", "宾馆", "别墅", "公司", "服务中心",
    "旧址", "咖啡", "文创", "纪念品", "礼品", "售楼", "样板间", "4S", "展示中心", "展厅", "体验馆",
]
# keyword used as part of a street / station / parking / entrance, e.g. 博物馆路, 博物馆地铁站
ZH_TRAP = re.compile(r"(博物馆|美术馆|展览馆|纪念馆)(路|街|站|停车场|地铁|公交|附近|旁|对面|[东南西北]?[门口])")

# English: whole-word match, NAME ONLY (addresses like '4101 University Drive' must not trigger)
EN_FLAGS = re.compile(r"\b(school|university|college|academy|training|hotel|inn|hostel|restaurant|cafe|"
                      r"shop|store|gift|showroom|parking|station|society|association|foundation|"
                      r"trust|guild|institute|zoo|aquarium)\b", re.I)

def needs_llm_judge(record: dict) -> Tuple[bool, str]:
    """Tripwire only ESCALATES to suspicious/LLM; it never decides ok or wrong."""
    name = str(record.get("name") or record.get("title") or "")
    zh_text = " ".join([name, str(record.get("address", "")), str(record.get("keytag", ""))])

    m = ZH_TRAP.search(name)
    if m: return True, f"Tripwire: '{m.group(0)}' looks like a street/station/parking/entrance, not the venue"
    for kw in ZH_FLAGS:
        if kw in zh_text: return True, f"Tripwire: keyword '{kw}' found in name/address/keytag"
    m = EN_FLAGS.search(name)
    if m: return True, f"Tripwire: keyword '{m.group(0)}' found in name"
    return False, ""