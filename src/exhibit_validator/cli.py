import typer
from pathlib import Path
import json
import dotenv
from .pipeline import run_pipeline
from dotenv import load_dotenv
load_dotenv()
app = typer.Typer()


@app.command()
def validate(
    input_path: Path = typer.Argument(..., help="Path to the input JSON file"),
    intent_path: Path = typer.Option("configs/intents/tourist_attraction.yaml", help="Path to the intent YAML"),
    taxonomy_path: Path = typer.Option("configs/taxonomy.yaml", help="Path to the taxonomy YAML"),
    output_path: Path = typer.Option("data/outputs/result.json", help="Path to write the output JSON"),
    use_llm: bool = typer.Option(False, "--llm/--no-llm", help="Enable the LLM judge layer"),
    threshold: float = typer.Option(0.75, help="Similarity threshold for duplicate clustering"),
):
    result = run_pipeline(
        input_path=str(input_path),
        intent_path=str(intent_path),
        taxonomy_path=str(taxonomy_path),
        use_llm=use_llm,
        threshold=threshold,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"Done. Summary: {result['summary']}")


if __name__ == "__main__":
    app()