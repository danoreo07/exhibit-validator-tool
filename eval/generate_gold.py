import json
import csv
import os
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''
os.environ['ALL_PROXY'] = ''
os.environ['NO_PROXY'] = '*'
import time
from openai import OpenAI

# Configure Client (Using DashScope/DeepSeek as per your setup)
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    timeout=60.0,
    max_retries=3
)

# STRICT Chain-of-Thought Prompt for generating the Gold Standard
GOLD_PROMPT = """
You are a Senior Data Quality Auditor specializing in the Chinese POI (Point of Interest) database. 
Your task is to generate the absolute "Ground Truth" label for whether a given POI is a legitimate museum, gallery, or exhibition venue.

Input Data:
- Name: {name}
- Typecode: {typecode} (e.g., 140100 = Museum, 141200 = School, etc.)
- Address: {address}

Follow this strict Chain-of-Thought reasoning process:
1. Keyword Analysis: Does the name contain explicit museum-related keywords (e.g., 博物馆, 美术馆, 展览馆, Gallery, Museum)? 
2. Typecode Validation: Is the typecode valid for a cultural venue (e.g., 140100, 140200, 140400)?
3. Context Check: Does the address suggest it might be a false positive (e.g., located inside a university campus, a corporate office, a shop, or a hotel)?
4. Conflict Resolution: If the name is a museum but the typecode is a school/shop, it is likely a `wrong` POI (e.g., a museum shop or a training center). 

Output strictly in JSON format (do not include markdown formatting, just the raw JSON):
{{
  "truth": "ok" | "wrong" | "unsure",
  "reason_en": "Detailed reasoning in English",
  "reason_zh": "Detailed reasoning in Chinese"
}}
"""

def generate_gold(input_path: str, output_csv: str):
    print(f"Loading data from {input_path}...")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    points = data.get("points", [])
    results = []
    
    print(f"Found {len(points)} points. Generating machine labels...")
    
    for i, p in enumerate(points):
        name = p.get("name", "")
        typecode = p.get("typecode", "")
        address = p.get("address", "")
        
        prompt = GOLD_PROMPT.format(name=name, typecode=typecode, address=address)
        
        try:
            response = client.chat.completions.create(
                model="deepseek-v4.1-flash-1017", # Use your standard model
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0 # Strictly 0 for deterministic evaluation
            )
            
            res_content = response.choices[0].message.content
            res_json = json.loads(res_content)
            
            truth = res_json.get("truth", "unsure")
            reason_en = res_json.get("reason_en", "")
            reason_zh = res_json.get("reason_zh", "")
            
        except Exception as e:
            print(f"[!] Error processing {name}: {e}")
            truth = "unsure"
            reason_en = "LLM Error"
            reason_zh = "LLM 调用失败"
            time.sleep(2) # Rate limit backoff
            
        results.append({
            "id": p.get("id", ""),
            "name": name,
            "typecode": typecode,
            "address": address,
            "truth": truth,
            "reason_en": reason_en,
            "reason_zh": reason_zh
        })
        
        if (i + 1) % 10 == 0:
            print(f"Progress: {i + 1}/{len(points)}")

    # Export to CSV
    os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)
    with open(output_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "name", "typecode", "address", "truth", "reason_en", "reason_zh"])
        writer.writeheader()
        writer.writerows(results)
        
    print(f"[+] Successfully saved {len(results)} machine-generated gold labels to {output_csv}")

if __name__ == "__main__":
    import sys
    # Default paths if not provided via CLI
    input_json = sys.argv[1] if len(sys.argv) > 1 else "data/raw/test_national_museum.json"
    output_csv = sys.argv[2] if len(sys.argv) > 2 else "data/ground_truth/gold_machine.csv"
    generate_gold(input_json, output_csv)