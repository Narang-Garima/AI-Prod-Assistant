import json
from pathlib import Path


def test_retrieval_evaluation_dataset_has_unique_well_formed_cases():
    dataset_path = Path(__file__).resolve().parents[1] / "evaluation" / "retrieval_eval_dataset.json"
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))

    assert len(cases) >= 5
    assert len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        assert set(case) == {"id", "category", "question"}
        assert case["id"].strip()
        assert case["category"].strip()
        assert case["question"].strip().endswith("?")
