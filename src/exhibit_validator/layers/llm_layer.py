import json
import os
import time
from openai import OpenAI


def build_prompt(record: dict, intent: dict, extra_context: str = "") -> str:
    """Construct the prompt to send to the LLM."""
    checks = "\n".join(
        f"- {c['field']}: {c['rule']}" for c in intent.get("semantic_checks", [])
    )
    
    warning = f"\n⚠️ WARNING/TRIPWIRE: {extra_context}\n" if extra_context else ""
    
    return f"""You are a data quality judge for a POI collection task.

Objective: {intent['objective']}

Record: {json.dumps(record, ensure_ascii=False)}

Additional checks:
{checks}
{warning}

Evaluate:
1. Does the record match the objective? 
2. If the record is a hall or pavilion INSIDE a museum (e.g., contains '馆' and address has '博物馆'), consider it 'ok' even if typecode is 110000.
3. If the record is clearly a hotel, shop, photo studio, or company (e.g., contains '酒店', '摄影', '别墅', '专卖店'), mark it as 'wrong'.
4. Are there internal inconsistencies? Which specific fields are suspicious?

Return JSON only:
{{"verdict": "ok|suspicious|wrong", "reason": "...", "suspicious_fields": [...]}}
"""


def llm_judge(record: dict, intent: dict, extra_context: str = "") -> dict:
    """Send the record to the LLM and return its verdict."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("\n[!] ERROR: OPENROUTER_API_KEY is missing in environment variables.")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    try:
        resp = client.chat.completions.create(
            # Use the free model router
            model="openrouter/free", 
            messages=[{"role": "user", "content": build_prompt(record, intent, extra_context)}],
            response_format={"type": "json_object"},
            temperature=0,
        )

        content = resp.choices[0].message.content

        # Guard: OpenRouter free-tier models sometimes return null content 
        if content is None or content.strip() == "":
            print(f"\n[!] LLM returned empty content for record {record.get('id')}.")
            return {
                "verdict": "unknown",
                "reason": "LLM returned empty content (possibly free-tier rate limit).",
                "suspicious_fields": [],
                "suggested_action": "review",
                "source_layer": "llm_judge",
            }

        result = json.loads(content)
        result["source_layer"] = "llm_judge"
        return result

    except json.JSONDecodeError as e:
        print(f"\n[!] JSON decode error for record {record.get('id')}: {e}")
        return {
            "verdict": "unknown",
            "reason": f"Failed to parse LLM response as JSON: {e}",
            "suspicious_fields": [],
            "suggested_action": "review",
            "source_layer": "llm_judge",
        }
    except Exception as e:
        print(f"\n[!] LLM API ERROR: {e}\n")
        return {
            "verdict": "unknown",
            "reason": f"LLM call failed: {e}",
            "suspicious_fields": [],
            "suggested_action": "review",
            "source_layer": "llm_judge",
        }