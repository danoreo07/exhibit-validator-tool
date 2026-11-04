import json, os, re, time
from openai import OpenAI

api_key = os.getenv("DASHSCOPE_API_KEY")
model_name = os.getenv("DASHSCOPE_MODEL", "deepseek-v4.1-flash-1017")
client = OpenAI(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                api_key=api_key, timeout=60.0, max_retries=2)

VALID = {"ok", "wrong", "suspicious"}
DEFAULT_OK = ["Museum", "Gallery", "Exhibition", "博物馆", "博物院", "美术馆", "展览馆", "纪念馆", "画廊"]
DEFAULT_WRONG = ["Zoo", "Aquarium", "Wildlife Conservation", "Theme Park", "Shop", "Store", "School", "Hotel",
                 "动物园", "水族馆", "海洋馆", "游乐园", "学校", "酒店", "培训"]

def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)

def parse_intent_with_llm(objective: str) -> dict:
    """Run ONCE, review the output, save it to yaml and freeze it. Do not call on every run."""
    prompt = f"""Objective: "{objective}"
Return ONLY JSON: {{"semantic_checks":[{{"field":"name","rule":"..."}}]}}
Rules must be strict: a name is valid only with an explicit keyword for the target entity.
Never treat vague words (art, heritage, center, house) as sufficient."""
    try:
        r = client.chat.completions.create(model=model_name, temperature=0, max_tokens=1024,
                                           messages=[{"role": "user", "content": prompt}])
        return _parse_json(r.choices[0].message.content)
    except Exception as e:
        print(f"[!] Failed to parse intent via LLM: {e}; using strict fallback.")
        return {"semantic_checks": [{"field": "name", "rule":
                "Valid only if name contains museum/gallery/exhibition keyword. Invalid only if it explicitly names zoo, aquarium, shop, school. Otherwise suspicious."}]}

# Only fields with classification value. Excluded on purpose: photos, rating, open_time, location,
# childtype and `description` (rule-generated from name/address/type, so it adds no evidence).
LLM_FIELDS = ("name", "title", "typecode", "type", "keytag", "category", "address", "cityname", "adname")

def slim_record(record: dict) -> dict:
    return {k: record[k] for k in LLM_FIELDS if record.get(k)}

def build_prompt(record: dict, intent: dict, extra_context: str = "") -> str:
    ok_kw = ", ".join(intent.get("ok_keywords") or DEFAULT_OK)
    wrong_kw = ", ".join(intent.get("wrong_keywords") or DEFAULT_WRONG)
    hint = f"\n[PRE-CHECK FLAG]\n{extra_context}\n(Treat this flag as a reason to doubt; it can never turn the answer into 'ok'.)\n" if extra_context else ""
    return f"""You classify whether a place is a Museum, Art Gallery, or Exhibition venue.

[OBJECTIVE]
{intent.get("objective", "Validate the record.")}

[RECORD]
{json.dumps(slim_record(record), ensure_ascii=False)}
{hint}
[OUTPUT] JSON only: {{"verdict": "ok"|"suspicious"|"wrong", "reason": "short", "suspicious_fields": []}}

[RULES, apply in order]
1. 'name' (title) is the primary evidence. Missing address is never a reason for 'suspicious'. A mailing address (PO Box) says nothing about the venue.
2. 'ok' ONLY IF the name contains an explicit keyword meaning museum, gallery or exhibition, e.g.: {ok_kw}; or a name that ENDS with 展 (an exhibition, not 发展/开展).
   Vague words (Art, Center, Institute, House, Hall, Heritage, Collection, Studio, Cultural) are NOT enough.
3. 'wrong' ONLY IF the name explicitly names an excluded entity, e.g.: {wrong_kw}.
4. 'suspicious' in ALL other cases, including: a keyword that is only part of a street, station, parking lot, entrance, cafe or shop name (博物馆路, 博物馆站, Museum Cafe); company showrooms/sales centers (展厅, 展示中心); ambiguous organizations (Historical Society, Foundation, Association, Trust, Guild, Institute, Cultural Center); names with BOTH an ok and a wrong keyword; empty or unreadable names; names matching no rule.
5. 'category', 'typecode' and 'type' (a category path such as 风景名胜;旅游景点) are secondary signals; they can NEVER create 'ok' or 'wrong' by themselves. Scenic-spot or sports categories do NOT conflict with a museum name (many museums sit in scenic areas): judge by the name. Output 'suspicious' only when the category strongly contradicts the name (shop, restaurant, hotel, school, training, zoo, aquarium).
6. If not highly certain, output 'suspicious'. A wrong 'suspicious' is cheap; a wrong 'ok'/'wrong' is costly.

[EXAMPLES]
"National Museum of History" -> ok
"城市动物园" -> wrong
"Museum Gift Shop" -> suspicious
"博物馆地铁站" -> suspicious
"XX汽车展厅" -> suspicious
"某某美术培训中心" -> wrong
"Lincoln County Historical Society" -> suspicious
"Anchorage Clay Arts Guild" (category: ART MUSEUM) -> suspicious
"Alaska Sealife Center" (category: ZOO, AQUARIUM) -> suspicious
"""

ERROR_LOG = os.getenv("LLM_ERROR_LOG", "data/outputs/llm_errors.jsonl")

def _log_error(record, stage, detail, raw=""):
    try:
        os.makedirs(os.path.dirname(ERROR_LOG) or ".", exist_ok=True)
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": record.get("id"), "stage": stage, "detail": str(detail)[:300],
                                "raw": (raw or "")[:500]}, ensure_ascii=False) + "\n")
    except Exception:
        pass

def _lenient(raw: str):
    """Last resort: pull the verdict out of messy text."""
    m = re.search(r'"?verdict"?\s*[:：]\s*"?(ok|wrong|suspicious)', raw or "", re.I)
    if not m: return None
    r = re.search(r'"?reason"?\s*[:：]\s*"([^"]{0,300})', raw, re.S)
    return {"verdict": m.group(1).lower(), "reason": (r.group(1) if r else "parsed leniently"), "suspicious_fields": []}

def llm_judge(record: dict, intent: dict, extra_context: str = "", attempts: int = 3) -> dict:
    if not api_key:
        return {"verdict": "unknown", "reason": "Missing API Key", "source_layer": "llm_judge"}
    prompt = build_prompt(record, intent, extra_context)
    last = "unknown error"
    for a in range(attempts):
        raw = ""
        kwargs = dict(model=model_name, temperature=0, max_tokens=1024,
                      messages=[{"role": "user", "content": prompt}])
        if a == 0:
            kwargs["response_format"] = {"type": "json_object"}   # retries drop it: some models choke on it
        try:                                                      # stage 1: HTTP / SDK
            r = client.chat.completions.create(**kwargs)
            raw = (r.choices[0].message.content or "")
        except Exception as e:
            last = f"api: {e}"; _log_error(record, "api", e)
            time.sleep(2 ** a); continue
        try:                                                      # stage 2: parsing
            result = _parse_json(raw)
        except Exception as e:
            result = _lenient(raw)
            if result is None:
                last = f"parse: {e}"; _log_error(record, "parse", e, raw)
                time.sleep(1 + a); continue
        v = str(result.get("verdict", "")).strip().lower()
        if v not in VALID:
            last = f"bad verdict {v!r}"; _log_error(record, "verdict", v, raw); continue
        result["verdict"], result["source_layer"] = v, "llm_judge"
        return result
    return {"verdict": "unknown", "reason": last, "source_layer": "llm_judge"}