import json
import os
import click
import yaml
from dotenv import load_dotenv

load_dotenv()

from .pipeline import run_pipeline

@click.command()
@click.argument("input_path")
@click.option("--objective", required=True, help="Free-text objective")
@click.option("--intent-path", help="Optional: Path to a YAML config with predefined rules")
@click.option("--taxonomy-path", default="configs/taxonomy.yaml", help="Path to taxonomy")
@click.option("--output-path", default="data/outputs/result.json", help="Output JSON path")
@click.option("--use-llm", is_flag=True, help="Enable LLM validation")
def cli(input_path, objective, intent_path, taxonomy_path, output_path, use_llm):
    """Exhibit Validator CLI"""
    print(">>> Starting Exhibit Validator...")
    
    if intent_path and os.path.exists(intent_path):
        with open(intent_path, encoding="utf-8") as f:
            intent = yaml.safe_load(f)
        print(f">>> Loaded predefined rules from {intent_path}")
    else:
        intent = {"objective": objective}
        print(f">>> No YAML config provided. Using LLM to auto-generate rules for: '{objective}'")

    print(">>> Running pipeline...")
    result = run_pipeline(
        input_path=input_path,
        intent=intent,
        taxonomy_path=taxonomy_path,
        use_llm=use_llm
    )
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        
    print(f"\n>>> Done. Summary: {result['summary']}")
    print(f">>> Output saved to: {output_path}")

if __name__ == "__main__":
    cli()