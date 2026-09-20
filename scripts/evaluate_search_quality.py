"""Offline admission regression benchmark; never collect or deliver vacancies."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parser.deduplicate import deduplicate
from config.paths import workspace_path
from parser.normalize import is_inbox_candidate, location_attention, normalize_raw, vacancy_labels

DEFAULT_DATASET = ROOT / "tests/fixtures/search_quality.json"


def evaluate(dataset: dict) -> dict:
    cases = dataset["cases"]
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Quality cases must have unique IDs and cannot be empty")
    counts = dict(true_positive=0, true_negative=0, false_positive=0, false_negative=0)
    errors = []
    for case in cases:
        expected = case["expected_inbox"]
        if not isinstance(expected, bool):
            raise ValueError("expected_inbox must be boolean")
        vacancy = normalize_raw(case["raw"])
        actual = vacancy is not None and is_inbox_candidate(vacancy)
        key = ("true_" if actual == expected else "false_") + ("positive" if actual else "negative")
        counts[key] += 1
        if actual != expected:
            errors.append(f"{case['id']}: inbox={actual}, expected={expected}")
        if expected and actual:
            attention = location_attention(vacancy.location, vacancy.remote)
            if attention != case.get("expected_attention", False):
                errors.append(f"{case['id']}: location warning={attention}")
            labels = vacancy_labels(vacancy)
            for name, value in case.get("expected_labels", {}).items():
                if labels.get(name) != value:
                    errors.append(f"{case['id']}: label {name}={labels.get(name)}")
    for group in dataset["duplicate_groups"]:
        # Reverse the inputs too: discovery order must not change selection.
        for inputs in (group["raw"], list(reversed(group["raw"]))):
            normalized = [normalize_raw(raw) for raw in inputs]
            if any(item is None for item in normalized):
                errors.append(f"{group['id']}: a duplicate variant did not normalize")
                continue
            unique, removed = deduplicate(normalized)
            actual_urls = sorted(item.url for item in unique)
            if actual_urls != sorted(group["expected_urls"]) or removed != len(inputs) - len(group["expected_urls"]):
                errors.append(f"{group['id']}: selected URLs={actual_urls}, removed={removed}")
    predicted = counts["true_positive"] + counts["false_positive"]
    positives = counts["true_positive"] + counts["false_negative"]
    return {
        "scope": "curated offline admission regressions, not live market coverage",
        "cases": len(cases), "duplicate_groups": len(dataset["duplicate_groups"]),
        **counts,
        "precision": counts["true_positive"] / predicted if predicted else None,
        "recall": counts["true_positive"] / positives if positives else None,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=None)
    args = parser.parse_args()
    try:
        dataset = workspace_path(args.dataset) if args.dataset is not None else DEFAULT_DATASET
    except ValueError as error:
        parser.error(str(error))
    report = evaluate(json.loads(dataset.read_text(encoding="utf-8")))
    print(json.dumps(report, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
