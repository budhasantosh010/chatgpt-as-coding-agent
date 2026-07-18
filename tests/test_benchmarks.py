"""Phase 9 benchmark pack is fixed, reproducible, and honestly reported."""

import json
from pathlib import Path

from bench.verify import evaluate


ROOT = Path(__file__).parents[1]


def test_benchmark_manifest_has_five_fixed_one_variable_cases():
    manifest = json.loads((ROOT / "bench" / "cases.json").read_text(encoding="utf-8"))
    cases = manifest["cases"]

    assert [case["kind"] for case in cases] == [
        "targeted_bug", "multi_file_feature", "misleading_regression",
        "refactor", "security_fix",
    ]
    assert len({case["id"] for case in cases}) == 5
    for case in cases:
        baseline = case["baseline_contract"]
        variant = case["variant_contract"]
        changed = [key for key in baseline if baseline[key] != variant[key]]
        assert changed == [case["comparison_variable"]]


def test_seed_fixture_starts_with_all_five_objective_checks_failing():
    results = evaluate(ROOT / "bench" / "fixture_seed")

    assert set(results) == {"B01", "B02", "B03", "B04", "B05"}
    assert not any(item["passed"] for item in results.values())


def test_results_document_declares_n1_limit_and_required_measurements():
    text = (ROOT / "bench" / "results.md").read_text(encoding="utf-8")

    assert "n=1" in text
    for column in (
        "Correct", "Tests", "Credits by tier", "Wall clock",
        "Continue nudges", "Defects introduced",
    ):
        assert column in text
