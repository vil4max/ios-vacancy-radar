import copy
import json

from scripts.evaluate_search_quality import DEFAULT_DATASET, evaluate


def test_curated_admission_and_duplicate_regressions():
    report = evaluate(json.loads(DEFAULT_DATASET.read_text()))
    assert report["errors"] == []
    assert report["false_positive"] == report["false_negative"] == 0


def test_benchmark_detects_wrong_admission_warning_and_duplicate_expectations():
    dataset = copy.deepcopy(json.loads(DEFAULT_DATASET.read_text()))
    next(case for case in dataset["cases"] if case["id"] == "ios-remote")["expected_inbox"] = False
    unknown = next(case for case in dataset["cases"] if case["id"] == "ios-unknown-location")
    unknown["expected_attention"] = False
    dataset["duplicate_groups"][0]["expected_urls"] = ["https://example.com/wrong"]
    report = evaluate(dataset)
    assert report["false_positive"] == 1
    assert any("location warning" in error for error in report["errors"])
    assert any("selected URLs" in error for error in report["errors"])
