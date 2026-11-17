import json
import os
import re
import time
from openai import OpenAI

BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "deepseek-v4.1-flash-1017"

_client: OpenAI | None = None


def _get_api_key() -> str:
    return os.getenv("DASHSCOPE_API_KEY") or ""


def _get_model() -> str:
    return os.getenv("DASHSCOPE_MODEL") or DEFAULT_MODEL


def _get_client() -> OpenAI:
    """Build the client lazily so importing this module never needs credentials."""
    global _client
    if _client is None:
        api_key = _get_api_key()
        if not api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not set")
        _client = OpenAI(base_url=BASE_URL, api_key=api_key, timeout=60.0, max_retries=2)
    return _client

VALID = {"ok", "wrong", "suspicious"}

def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)

def parse_intent_with_llm(objective: str) -> dict:
    # Placeholder for future dynamic intent parsing
    return {"semantic_checks": [{"field": "name", "rule": "strict"}]}

LLM_FIELDS = ("name", "title", "typecode", "type", "keytag", "category", "address", "cityname", "adname")

def slim_record(record: dict) -> dict:
    return {k: record[k] for k in LLM_FIELDS if record.get(k)}

def build_prompt(record: dict, intent: dict, extra_context: str = "", detailed: bool = True) -> str:
    hint = f"\n[System Alert]\n{extra_context}\n" if extra_context else ""
    data = json.dumps(slim_record(record), ensure_ascii=False)

    if not detailed:
        # Cheaper retry prompt: same answer contract, far fewer input tokens.
        return f"""Classify this POI for a museum/gallery dataset as ok, wrong or suspicious.
ok = genuine public museum/gallery/exhibition venue. wrong = shop, restaurant, hotel, school,
office or other commercial/educational entity using a museum-like name. suspicious = only when a
concrete conflicting fact is present.
Record: {data}
{hint}
Reply with raw JSON only:
{{"verdict": "ok" | "wrong" | "suspicious", "reason": "...", "reason_en": "...",
  "reason_code": "...", "confidence": 0.9, "suspicious_fields": []}}
"""

    return f"""You are a Senior Data Quality Auditor. Your task is to determine if a POI is a LEGITIMATE museum, gallery, or exhibition venue.
The input data may be incomplete (missing typecode, missing address). You must base your decision on the available evidence.

**Core Rule (Semantic Analysis):**
1. **Legitimate Venue**: A public/non-profit entity whose PRIMARY PURPOSE is cultural, artistic, or scientific exhibition/education. 
2. **Commercial Masquerade (CRITICAL)**: Businesses (shops, restaurants, homestays, wedding dress stores, offices) often use words like "博物馆" (Museum) or "艺术中心" (Art Center) to attract customers. If the venue's primary purpose is selling goods/services, you MUST output `wrong`, EVEN IF the name contains "博物馆" or the typecode is 140100.
   - Examples: "西班牙火腿博物馆" (Ham shop), "婚纱博物馆" (Wedding dress store), "民宿-博物馆" (Homestay), "XX咖啡馆" (Cafe).

**Target Objective:** 
{intent.get("objective", "Validate if the record is a legitimate museum.")}

**Record Data:**
{data}
{hint}

**Output Format (JSON Only):**
{{
  "verdict": "ok" | "suspicious" | "wrong",
  "reason": "中文说明，面向最终用户",
  "reason_en": "English explanation for developers",
  "reason_code": "commercial_masquerade | genuine_museum | ambiguous_evidence | excluded_entity",
  "confidence": 0.95,
  "suspicious_fields": ["name", "keytag"]
}}

**Decision Rules:**
- Judge what the ENTITY is from its name and its Amap type/keytag. The address only tells you where it sits.
- `ok`: the name reads as a venue (contains 馆 / 博物院 / 画廊 / 展览 / 陈列), or it is a brand/abstract name located inside a cultural district or museum complex (e.g. "798艺术区"). Small private museums and exhibition halls inside shopping malls, office buildings or residential areas are legitimate: the location alone is NOT commercial evidence, and a branch suffix like "(…购物中心店)" marks a branch, not a shop.
- `wrong`:
  * internal or departmental history halls not open to the public: 局史馆, 校史馆, 厂史馆, 院史馆, 队史馆;
  * research, conservation or service units rather than exhibition venues: 文物保护…中心, 科技中心, 研究中心, 研究所;
  * a bare product or brand name with no venue word and no cultural-district address, even when the map typecode says museum;
  * a venue that is plainly a shop for one product (e.g. 火腿博物馆, 婚纱博物馆), or a school, restaurant, hotel, homestay, training centre or company.
- `suspicious`: use ONLY when two concrete facts genuinely conflict. Never abstain merely because the name is unfamiliar.
- The map typecode is a hint, never proof by itself.
- Do not output markdown, output raw JSON only.
"""

ERROR_LOG = os.getenv("LLM_ERROR_LOG", "data/outputs/llm_errors.jsonl")

def _log_error(record, stage, detail, raw=""):
    try:
        os.makedirs(os.path.dirname(ERROR_LOG) or ".", exist_ok=True)
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": record.get("id"), "stage": stage, "detail": str(detail)[:300], "raw": (raw or "")[:500]}, ensure_ascii=False) + "\n")
    except Exception:
        pass

def _normalize_reason_code(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")[:80] or "unspecified"

def _lenient(raw: str):
    m = re.search(r'"?verdict"?\s*[:：]\s*"?(ok|wrong|suspicious)', raw or "", re.I)
    if not m: 
        return None
    zh = re.search(r'"?reason"?\s*[:：]\s*"([^"]{0,300})', raw, re.S)
    en = re.search(r'"?reason_en"?\s*[:：]\s*"([^"]{0,300})', raw, re.S)
    rc = re.search(r'"?reason_code"?\s*[:：]\s*"([^"]{0,100})', raw, re.S)
    return {
        "verdict": m.group(1).lower(),
        "reason": zh.group(1) if zh else "解析成功，无原因",
        "reason_en": en.group(1) if en else "parsed leniently",
        "reason_code": _normalize_reason_code(rc.group(1) if rc else ""),
        "confidence": 0.5,
        "suspicious_fields": [],
    }

def llm_judge(record: dict, intent: dict, extra_context: str = "", attempts: int = 3) -> dict:
    if not _get_api_key():
        return {
            "verdict": "unknown", 
            "reason": "缺少 API Key", 
            "reason_en": "Missing API Key", 
            "reason_code": "missing_api_key", 
            "confidence": 0.0, 
            "source_layer": "llm_judge"
        }
    
    prompt = build_prompt(record, intent, extra_context)
    retry_prompt = build_prompt(record, intent, extra_context, detailed=False)
    last = "unknown error"
    for a in range(attempts):
        raw = ""
        # First attempt uses the full prompt; retries use the short one (fewer tokens).
        use_prompt = prompt if a == 0 else retry_prompt
        kwargs = dict(model=_get_model(), temperature=0, max_tokens=1024, messages=[{"role": "user", "content": use_prompt}])
        if a == 0:
            kwargs["response_format"] = {"type": "json_object"}
        
        try:
            r = _get_client().chat.completions.create(**kwargs)
            raw = (r.choices[0].message.content or "")
        except Exception as e:
            last = f"api: {e}"
            _log_error(record, "api", e)
            time.sleep(2 ** a)
            continue
        
        if not raw.strip():
            # An empty completion is not a parse error; re-sending the same prompt only burns tokens.
            last = "empty response"
            _log_error(record, "empty", "empty completion", raw)
            continue

        try:
            result = _parse_json(raw)
        except Exception as e:
            result = _lenient(raw)
            if result is None:
                last = f"parse: {e}"
                _log_error(record, "parse", e, raw)
                time.sleep(1 + a)
                continue
        
        v = str(result.get("verdict", "")).strip().lower()
        if v not in VALID:
            last = f"bad verdict {v!r}"
            _log_error(record, "verdict", v, raw)
            continue
            
        result["verdict"] = v
        result["source_layer"] = "llm_judge"
        result["reason"] = result.get("reason") or "未提供原因"
        result["reason_en"] = result.get("reason_en") or result.get("reason") or "No reason provided."
        result["reason_code"] = _normalize_reason_code(result.get("reason_code"))
        result["suspicious_fields"] = result.get("suspicious_fields") or []
        
        try:
            result["confidence"] = float(result.get("confidence", 0.5))
        except (ValueError, TypeError):
            result["confidence"] = 0.5
            
        return result
        
    return {
        "verdict": "unknown", 
        "reason": "LLM 调用失败，需要人工复核", 
        "reason_en": last, 
        "reason_code": "empty_response" if last == "empty response" else "llm_error", 
        "confidence": 0.0, 
        "source_layer": "llm_judge"
    }