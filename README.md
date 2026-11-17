# Exhibit Validator

A robust 3-layer validation pipeline designed to identify legitimate museums, galleries, and exhibition venues from noisy, real-world Point of Interest (POI) data (e.g., Amap). 

The system is specifically engineered to distinguish between **genuine cultural venues** and **commercial entities masquerading as museums** (e.g., retail shops, restaurants, or homestays that use "Museum" in their names for marketing).

## 🏛️ System Architecture

The system uses a "Funnel Architecture" to maximize accuracy while minimizing LLM API costs. It processes data in three main layers:

1. **Rule Layer (Deterministic Filter):** 
   - Uses hardcoded typecodes (e.g., schools, hospitals) and a strict dictionary of excluded keywords (e.g., "restaurant", "shop").
   - **Action:** Instantly discards obvious non-museums (`wrong`). Returns `None` for anything that has potential or is ambiguous.
2. **Tripwire (Anomaly Detector):** 
   - Scans for conflicting signals before sending data to the LLM.
   - **Action:** Flags records that contain both museum keywords and commercial keywords (e.g., "Museum Cafe") or street/station names (e.g., "Museum Road").
3. **LLM Judge (Semantic Arbiter):** 
   - The core intelligence. It receives the full context (name, typecode, address, keytag) and applies semantic reasoning.
   - **Action:** Differentiates between a genuine public museum and a commercial masquerade. Outputs `ok`, `wrong`, or `suspicious`, along with a confidence score and detailed reasoning.
4. **Decision Engine:** Merges the outputs from the layers into a final, auditable verdict.

## 🚀 Installation & Setup

### Prerequisites
- Python 3.10 or higher
- An API Key for an LLM provider (e.g., Alibaba DashScope / OpenAI) and an Amap API Key.

### Step 1: Clone & Install
```bash
git clone https://github.com/danoreo07/exhibit-validator-tool.git
cd exhibit-validator-tool
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate
pip install -e .

### Step 2: Environment Variables
Copy the example environment file and fill in your API keys:
```bash
cp .env.example .env
DASHSCOPE_API_KEY=your_llm_api_key_here
AMAP_KEY=your_amap_api_key_here

💻 Usage Guide
1. Run the Validation Pipeline
To validate a dataset and output the results to a JSON file, use the following command:

On Windows (PowerShell):
$env:PYTHONPATH = "src"
python src/exhibit_validator/pipeline.py --input data/raw/sample.json --intent configs/intents/museum.yaml --output data/outputs/result.json --use-llm

On Linux/Mac:
export PYTHONPATH=src
python src/exhibit_validator/pipeline.py --input data/raw/sample.json --intent configs/intents/museum.yaml --output data/outputs/result.json --use-llm

2. Evaluate the System (Metrics)
To measure how well the system performed, you can generate a "Gold Standard" using the LLM and calculate advanced metrics.
# Step A: Generate the Gold Standard labels
python eval/generate_gold.py data/raw/sample.json data/ground_truth/gold.csv
# Step B: Run the metrics evaluation
python eval/metrics.py --gold data/ground_truth/gold.csv --result data/outputs/result.json --json-out data/outputs/metrics_report.json

Understanding the Metrics Output:
FALSE OK: The most dangerous error (System says ok, but it's actually junk). Target: 0.
FALSE WRONG: System discarded a genuine museum. Target: 0.
Recall: How many true museums/junk items were successfully identified.
Cohen's Kappa: Agreement between the System and the Gold Standard ( >0.6 is Good, >0.8 is Excellent).
Automation (Coverage): The percentage of records the system confidently handled automatically without human review


📂 Project Structure
exhibit-validator-tool/
├── configs/
│   ├── intents/            # YAML configs defining what to look for (e.g., museum.yaml)
│   └── taxonomy.yaml       # Amap category definitions
├── data/
│   ├── raw/                # Raw input JSON files (ignored by Git)
│   ├── outputs/            # Validation results (ignored by Git)
│   └── ground_truth/       # Generated gold standard labels (ignored by Git)
├── eval/
│   ├── generate_gold.py    # Script to auto-generate ground truth labels
│   └── metrics.py          # Advanced evaluation script
├── scripts/
│   ├── collect_amap.py     # Utility to crawl POI data from Amap
│   └── safe_merge.py       # Utility to merge multiple crawled files
├── src/
│   └── exhibit_validator/
│       ├── layers/         # Core logic (rule, tripwire, llm, decision)
│       ├── models/         # Data schemas and enums
│       ├── utils/          # Normalization helpers
│       └── pipeline.py     # Main orchestration file
└── tests/                  # Unit tests


⚙️ Customization (Adding New Domains)
To validate a different type of entity (e.g., Parks or Libraries), simply create a new YAML file in configs/intents/.
For example, parks.yaml:
objective: "Identify and keep legitimate public parks."
ok_keywords: ["公园", "植物园", "Park", "Garden"]
wrong_keywords: ["小区", "花园洋房", "停车场"]
allowed_typecodes: ["110100", "110200"]
Then run the pipeline by passing --intent configs/intents/parks.yaml.