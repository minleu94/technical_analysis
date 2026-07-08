from __future__ import annotations

import json

from app_module.threshold_robustness_read_model import (
    BUY_SCORE_THRESHOLDS,
    CONFIRMATION_DAYS,
    COOLDOWN_DAYS,
    SELL_SCORE_THRESHOLDS,
    ThresholdRobustnessObservation,
    ThresholdRobustnessReadModel,
)
from scripts.inspect_score_effectiveness import main as inspect_score_effectiveness_main


def _observation(
    buy_score: int,
    sell_score: int,
    confirmation_days: int,
    cooldown_days: int,
    benchmark_excess_bp: int,
) -> ThresholdRobustnessObservation:
    return ThresholdRobustnessObservation(
        buy_score=buy_score,
        sell_score=sell_score,
        confirmation_days=confirmation_days,
        cooldown_days=cooldown_days,
        ready_outcome_count=10,
        benchmark_excess_bp=benchmark_excess_bp,
        forward_return_bp=benchmark_excess_bp + 10,
    )


def test_threshold_matrix_contains_all_fixed_settings_and_read_only_boundary() -> None:
    report = ThresholdRobustnessReadModel(observations=()).build_report()
    payload = report.to_dict()

    assert len(payload["rows"]) == (
        len(BUY_SCORE_THRESHOLDS)
        * len(SELL_SCORE_THRESHOLDS)
        * len(CONFIRMATION_DAYS)
        * len(COOLDOWN_DAYS)
    )
    assert {row["buy_score"] for row in payload["rows"]} == set(BUY_SCORE_THRESHOLDS)
    assert {row["sell_score"] for row in payload["rows"]} == set(SELL_SCORE_THRESHOLDS)
    assert {row["confirmation_days"] for row in payload["rows"]} == set(CONFIRMATION_DAYS)
    assert {row["cooldown_days"] for row in payload["rows"]} == set(COOLDOWN_DAYS)
    assert {row["label"] for row in payload["rows"]} == {"inconclusive"}
    assert payload["access_boundary"]["writes_allowed"] is False
    assert payload["access_boundary"]["threshold_promotion_allowed"] is False
    assert payload["access_boundary"]["production_scheduler_allowed"] is False
    assert "threshold_replay_input_missing" in payload["diagnostics"]


def test_threshold_labels_distinguish_stable_fragile_harmful_and_inconclusive() -> None:
    observations = [
        _observation(60, 40, 2, 3, 120),
        _observation(58, 40, 2, 3, 90),
        _observation(62, 40, 2, 3, 100),
        _observation(65, 45, 2, 3, 80),
        _observation(70, 50, 3, 5, -60),
    ]

    report = ThresholdRobustnessReadModel(observations=observations, min_sample_size=5).build_report()
    by_config = {
        (
            row.buy_score,
            row.sell_score,
            row.confirmation_days,
            row.cooldown_days,
        ): row
        for row in report.rows
    }

    assert by_config[(60, 40, 2, 3)].label == "stable_positive"
    assert by_config[(65, 45, 2, 3)].label == "fragile"
    assert by_config[(70, 50, 3, 5)].label == "harmful_or_noisy"
    assert by_config[(58, 38, 1, 2)].label == "inconclusive"


def test_score_effectiveness_cli_can_include_threshold_matrix(tmp_path, capsys) -> None:
    output_path = tmp_path / "score_effectiveness_with_thresholds.json"

    assert (
        inspect_score_effectiveness_main(
            [
                "--sample",
                "--include-threshold-robustness",
                "--format",
                "json",
                "--output",
                str(output_path),
            ]
        )
        == 0
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["threshold_robustness"]["access_boundary"]["threshold_promotion_allowed"] is False
    assert len(payload["threshold_robustness"]["rows"]) == 225
    assert {row["label"] for row in payload["threshold_robustness"]["rows"]} >= {
        "stable_positive",
        "fragile",
        "harmful_or_noisy",
        "inconclusive",
    }
    _ = capsys.readouterr()
