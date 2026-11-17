"""Flag-only ambiguity detection for conflicts between typecodes and text fields.

The detector runs after the rule layer and before the LLM layer. It never
changes a verdict; it only returns English, machine-readable signal names.
"""

import re

from .rule_layer import DEFAULTS, normalize_typecodes

# Config keywords are data, so their English signal labels are mapped here.
# Unknown ASCII keywords are slugified; unknown non-ASCII keywords fall back
# to the generic "keyword" label.
_KEYWORD_LABELS = {
    # wrong_keywords: excluded entities and facilities
    "动物园": "zoo",
    "水族馆": "aquarium",
    "海洋馆": "oceanarium",
    "游乐园": "amusement_park",
    "学校": "school",
    "大学": "university",
    "学院": "college",
    "中学": "middle_school",
    "小学": "primary_school",
    "校区": "campus",
    "研究所": "research_institute",
    "研究院": "research_academy",
    "研究中心": "research_center",
    "实验室": "laboratory",
    "图书馆": "library",
    "文明实践": "civic_practice_center",
    "杂志社": "magazine_office",
    "集团": "group",
    "美发": "hair_salon",
    "美容": "beauty_salon",
    "分析室": "analysis_room",
    "工作室": "studio",
    "日报社": "daily_news_office",
    "报社": "newspaper_office",
    "公司": "company",
    "医疗": "medical",
    "医院": "hospital",
    "诊所": "clinic",
    "遗址": "heritage_site",
    "纪念园": "memorial_park",
    "特种设备": "special_equipment",
    "会议": "conference",
    "宾馆": "hotel",
    "酒店": "hotel",
    "培训": "training",
    "商店": "shop",
    "超市": "supermarket",
    "便利店": "convenience_store",
    "小卖部": "kiosk",
    "专卖店": "specialty_store",
    "餐厅": "restaurant",
    "饭店": "restaurant",
    "餐馆": "restaurant",
    "咖啡馆": "cafe",
    "酒吧": "bar",
    "茶楼": "tea_house",
    "商场": "shopping_mall",
    "购物中心": "shopping_center",
    "停车场": "parking_lot",
    "售票处": "ticket_office",
    "游客中心": "visitor_center",
    "卫生间": "restroom",
    "厕所": "toilet",
    "入口": "entrance",
    "出口": "exit",
    "广场": "plaza",
    "公园": "park",
    "花园": "garden",
    "小区": "residential_community",
    "公寓": "apartment",
    "写字楼": "office_building",
    "办公室": "office",
    "仓库": "warehouse",
    "工厂": "factory",
    "车间": "workshop",
    "机场": "airport",
    "火车站": "railway_station",
    "地铁站": "metro_station",
    "公交站": "bus_stop",
    "中心": "center",
    # ok_keywords: museum/gallery/exhibition wording
    "博物馆": "museum",
    "博物院": "museum",
    "美术馆": "art_gallery",
    "展览馆": "exhibition_hall",
    "纪念馆": "memorial_hall",
    "画廊": "gallery",
    "陈列馆": "exhibition_hall",
    "陈列室": "exhibition_room",
    "展陈馆": "exhibition_hall",
    "展示馆": "exhibition_hall",
    "艺术展": "art_exhibition",
    "特展": "special_exhibition",
    "非遗馆": "intangible_heritage_hall",
    "艺廊": "art_gallery",
    "博展馆": "exhibition_hall",
    "纪念堂": "memorial_hall",
}


def _cfg(intent: dict, key: str) -> list[str]:
    return intent[key] if key in intent else DEFAULTS[key]


def _stems(codes: list[str]) -> tuple[str, ...]:
    return tuple(code.rstrip("0") or code for code in codes)


def _matches_group(code: str, group: list[str]) -> bool:
    stems = _stems(group)
    return bool(stems) and code.startswith(stems)


def _label(keyword: str) -> str:
    label = _KEYWORD_LABELS.get(keyword)
    if label:
        return label
    label = re.sub(r"[^a-z0-9]+", "_", keyword.lower()).strip("_")
    return label or "keyword"


def _hits(text: str, keywords: list[str]) -> list[str]:
    """Return matching keywords, preferring the most specific overlapping one."""
    lower_text = text.lower()
    matches = sorted(
        (keyword for keyword in keywords if keyword.lower() in lower_text),
        key=len,
        reverse=True,
    )
    selected: list[str] = []
    for keyword in matches:
        if any(keyword.lower() in chosen.lower() for chosen in selected):
            continue
        selected.append(keyword)
    return selected


def detect_ambiguities(record: dict, intent: dict) -> list[str]:
    """Return English conflict signals for a record without changing its verdict."""
    codes = normalize_typecodes(record.get("typecode"))
    if not codes:
        return []

    allowed_typecodes = _cfg(intent, "allowed_typecodes")
    review_typecodes = _cfg(intent, "review_typecodes")
    wrong_keywords = _cfg(intent, "wrong_keywords")
    ok_keywords = _cfg(intent, "ok_keywords")

    name = str(record.get("name") or record.get("title") or "")
    address = str(record.get("address") or "")

    signals: list[str] = []
    for code in codes:
        if _matches_group(code, allowed_typecodes):
            for keyword in _hits(name, wrong_keywords):
                signals.append(f"allowed_typecode_but_name_is_{_label(keyword)}")
            for keyword in _hits(address, wrong_keywords):
                signals.append(f"allowed_typecode_but_address_is_{_label(keyword)}")
        if _matches_group(code, review_typecodes):
            for keyword in _hits(name, ok_keywords):
                signals.append(f"review_typecode_but_name_is_{_label(keyword)}")

    return list(dict.fromkeys(signals))
