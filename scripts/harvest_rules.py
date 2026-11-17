#!/usr/bin/env python3
"""Harvest rule candidates from LLM-wrong records that the rule layer skipped.

Records are matched by id from pipeline result JSON files. Rule replay uses the
fields available in those results.
"""

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CACHE = "data/outputs/.llm_cache.jsonl"
DEFAULT_OUTPUT_DIR = "data/outputs"
DEFAULT_INTENT = "configs/intents/museum.yaml"
DEFAULT_TAXONOMY = "configs/taxonomy.yaml"
STOPWORDS = {"the", "and", "of", "for", "with", "from", "this", "that"}

RuleCheck = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any]],
    dict[str, Any] | None,
]


def load_cache(path: str) -> dict[str, dict[str, Any]]:
    """Load LLM cache entries keyed by cache key."""
    entries: dict[str, dict[str, Any]] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = item.get("key")
            result = item.get("res")
            if isinstance(key, str) and isinstance(result, dict):
                entries[key] = result
    return entries


def load_result_records(paths: list[str]) -> dict[str, dict[str, Any]]:
    """Load pipeline result records keyed by record id."""
    records: dict[str, dict[str, Any]] = {}
    for path in paths:
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[!] Skipping {path}: {exc}")
            continue
        rows = data.get("records", []) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            record_id = row.get("id")
            if record_id is not None:
                records[str(record_id)] = row
    return records


def load_intent(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def discover_result_paths(output_dir: str) -> list[str]:
    return [str(path) for path in sorted(Path(output_dir).glob("*.json"))]


def extract_keywords(name: str) -> list[str]:
    """Extract English words and Chinese 2-4 character n-grams from a name."""
    text = (name or "").lower()
    tokens: set[str] = set()
    tokens.update(
        token
        for token in re.findall(r"[a-z][a-z0-9]{1,}", text)
        if token not in STOPWORDS
    )
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(run) <= 8:
            tokens.add(run)
        for size in range(2, min(4, len(run)) + 1):
            for start in range(len(run) - size + 1):
                tokens.add(run[start:start + size])
    return sorted(tokens)


def find_missed_records(
    cache: dict[str, dict[str, Any]],
    records: dict[str, dict[str, Any]],
    intent: dict[str, Any],
    taxonomy: dict[str, Any],
    rule_check_fn: RuleCheck,
) -> tuple[list[dict[str, Any]], int, int]:
    """Return (missed records, matched cache entries, skipped cache entries)."""
    missed: list[dict[str, Any]] = []
    matched = 0
    skipped = 0
    for key, result in cache.items():
        if str(result.get("verdict", "")).lower() != "wrong":
            continue
        record_id = key.rsplit(":", 1)[0] if ":" in key else key
        record = records.get(record_id)
        if record is None:
            skipped += 1
            continue
        matched += 1
        if rule_check_fn(record, intent, taxonomy) is None:
            missed.append(record)
    return missed, matched, skipped


def print_report(
    missed: list[dict[str, Any]], matched: int, skipped: int, top: int
) -> None:
    typecodes = Counter(str(record.get("typecode") or "<empty>") for record in missed)
    keywords: Counter[str] = Counter()
    for record in missed:
        name = str(record.get("name") or record.get("title") or "")
        keywords.update(extract_keywords(name))

    print("Top typecodes/keywords missed by rules but caught by LLM:")
    print(f"  Matched cache entries: {matched}")
    print(f"  Missed by rule layer: {len(missed)}")
    print(f"  Skipped cache entries without result record: {skipped}")

    print("\nTop typecodes:")
    if typecodes:
        for typecode, count in typecodes.most_common(top):
            print(f"  {typecode}: {count}")
    else:
        print("  (none)")

    print("\nTop name keywords:")
    if keywords:
        for keyword, count in keywords.most_common(top):
            print(f"  {keyword}: {count}")
    else:
        print("  (none)")


def _load_rule_layer() -> tuple[
    Callable[[str], dict[str, Any]], RuleCheck
]:
    project_root = Path(__file__).resolve().parents[1]
    src_dir = project_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    from exhibit_validator.layers.rule_layer import load_taxonomy, rule_check

    return load_taxonomy, rule_check


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache",
        default=DEFAULT_CACHE,
        help="LLM cache JSONL path (default: %(default)s)",
    )
    parser.add_argument(
        "--results",
        nargs="*",
        default=None,
        help="Pipeline result JSON files (default: all *.json in --output-dir)",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory scanned when --results is omitted (default: %(default)s)",
    )
    parser.add_argument(
        "--intent",
        default=DEFAULT_INTENT,
        help="Intent YAML path (default: %(default)s)",
    )
    parser.add_argument(
        "--taxonomy",
        default=DEFAULT_TAXONOMY,
        help="Taxonomy YAML path (default: %(default)s)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of typecodes/keywords to show (default: %(default)s)",
    )
    args = parser.parse_args()
    if args.top <= 0:
        parser.error("--top must be positive")
    return args


def main() -> None:
    args = parse_args()
    result_paths = args.results or discover_result_paths(args.output_dir)
    if not result_paths:
        print("[!] No result JSON files found. Pass --results <pipeline_output.json>.")
        return

    cache = load_cache(args.cache)
    records = load_result_records(result_paths)
    if not records:
        print("[!] No records with ids found in result files.")
        return

    load_taxonomy, rule_check = _load_rule_layer()
    intent = load_intent(args.intent)
    taxonomy = load_taxonomy(args.taxonomy)
    missed, matched, skipped = find_missed_records(
        cache, records, intent, taxonomy, rule_check
    )
    print_report(missed, matched, skipped, args.top)


if __name__ == "__main__":
    main()
