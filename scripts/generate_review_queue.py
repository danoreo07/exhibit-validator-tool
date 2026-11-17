#!/usr/bin/env python3
"""Build a CSV review queue from a pipeline result JSON file."""

import argparse
import csv
import json
from pathlib import Path
from typing import Any

DEFAULT_INPUT = "data/outputs/museum_llm.json"
DEFAULT_OUTPUT = "data/outputs/review_queue.csv"
CSV_FIELDS = [
    "id",
    "name",
    "verdict",
    "confidence",
    "reason",
    "reason_en",
    "reason_code",
    "ambiguity_signals",
]


def load_records(path: str) -> list[dict[str, Any]]:
    """Load records from a pipeline result dict or a raw record list."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        rows = data.get("records", [])
    elif isinstance(data, list):
        rows = data
    else:
        raise ValueError(f"Unsupported JSON structure in {path}")
    return [row for row in rows if isinstance(row, dict)]


def as_text(value: Any) -> str:
    return "" if value is None else str(value)


def as_confidence(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 1.0


def as_signals(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value:
        return [str(value)]
    return []


def is_review_candidate(record: dict[str, Any]) -> bool:
    verdict = as_text(record.get("verdict"))
    confidence = as_confidence(record.get("confidence", 1.0))
    return (
        verdict in {"needs_review", "suspicious"}
        or confidence < 0.6
        or bool(as_signals(record.get("ambiguity_signals")))
    )


def review_sort_key(record: dict[str, Any]) -> tuple[float, str]:
    return (as_confidence(record.get("confidence", 1.0)), as_text(record.get("id")))


def to_csv_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": as_text(record.get("id")),
        "name": as_text(record.get("name") or record.get("title")),
        "verdict": as_text(record.get("verdict")),
        "confidence": as_confidence(record.get("confidence", 1.0)),
        "reason": as_text(record.get("reason")),
        "reason_en": as_text(record.get("reason_en") or record.get("reason")),
        "reason_code": as_text(record.get("reason_code")),
        "ambiguity_signals": "; ".join(as_signals(record.get("ambiguity_signals"))),
    }


def write_queue(records: list[dict[str, Any]], output_path: str) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(to_csv_row(record) for record in records)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        nargs="?",
        default=DEFAULT_INPUT,
        help="Pipeline result JSON file (default: %(default)s)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT,
        help="Output CSV path (default: %(default)s)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = load_records(args.input)
    queue = sorted(
        (record for record in records if is_review_candidate(record)),
        key=review_sort_key,
    )
    write_queue(queue, args.output)
    print(f"Review queue: {len(queue)} of {len(records)} records -> {args.output}")


if __name__ == "__main__":
    main()
