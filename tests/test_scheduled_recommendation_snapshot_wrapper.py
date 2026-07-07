from __future__ import annotations

import json
from pathlib import Path

from app_module.dtos import RecommendationDTO
from scripts.scheduled import run_scheduled_recommendation_snapshot


class FakeRecommendationService:
    instances: list["FakeRecommendationService"] = []

    def __init__(self, config) -> None:
        self.config = config
        self.last_screening_matrix = [
            {
                "stock_code": "2330",
                "stock_name": "TSMC",
                "status": "pass",
                "reason_codes": ["recommendation_selected"],
                "quality": "observed",
            }
        ]
        self.last_excluded_candidates_json = []
        self.last_why_not_payload_json = [
            {
                "stock_code": "2317",
                "status": "fail",
                "reason_codes": ["recommendation_outside_top_n"],
                "quality": "observed",
            }
        ]
        self.last_liquidity_gate_payload_json = []
        self.last_exclusion_quality = "observed"
        self.last_exclusion_warnings_json = ["screening_matrix_persisted_v1"]
        self.calls: list[dict[str, object]] = []
        FakeRecommendationService.instances.append(self)

    def run_recommendation(
        self,
        *,
        config: dict[str, object],
        max_stocks: int,
        top_n: int,
    ) -> list[RecommendationDTO]:
        self.calls.append({"config": config, "max_stocks": max_stocks, "top_n": top_n})
        return [
            RecommendationDTO(
                stock_code="2330",
                stock_name="TSMC",
                close_price=100,
                price_change=1,
                total_score=80,
                indicator_score=30,
                pattern_score=30,
                volume_score=20,
                recommendation_reasons="fixture",
                industry="Semiconductor",
                regime_match=True,
            )
        ]


class FakeRecommendationRepository:
    saved_results: list[object] = []

    def __init__(self, config) -> None:
        self.config = config
        self.db_path = Path(config.output_root) / "recommendation" / "runs" / "recommendation_runs.db"
        self.runs_dir = self.db_path.parent
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def save_result(self, result) -> str:
        result.result_id = result.result_id or "scheduled_rec_fixture"
        FakeRecommendationRepository.saved_results.append(result)
        return result.result_id


def test_scheduled_recommendation_snapshot_saves_result_and_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    FakeRecommendationService.instances.clear()
    FakeRecommendationRepository.saved_results.clear()
    monkeypatch.setattr(run_scheduled_recommendation_snapshot, "RecommendationService", FakeRecommendationService)
    monkeypatch.setattr(
        run_scheduled_recommendation_snapshot,
        "RecommendationRepository",
        FakeRecommendationRepository,
    )
    monkeypatch.setattr(
        run_scheduled_recommendation_snapshot,
        "_build_result_id",
        lambda _now: "scheduled_rec_fixture",
    )

    output_root = tmp_path / "output"
    exit_code = run_scheduled_recommendation_snapshot.main(
        [
            "--data-root",
            str(tmp_path / "data"),
            "--output-root",
            str(output_root),
            "--max-stocks",
            "25",
            "--top-n",
            "5",
        ]
    )

    status_path = output_root / "scheduled" / "recommendation_snapshot" / "latest_status.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["status"] == "passed"
    assert payload["task"] == "baldr-recommendation-snapshot-daily"
    assert payload["result_id"] == "scheduled_rec_fixture"
    assert payload["recommendations_count"] == 1
    assert payload["screening_matrix_rows"] == 1
    assert payload["why_not_payload_rows"] == 1
    assert payload["writes_recommendation_result"] is True
    assert payload["writes_evidence_db"] is False
    assert payload["auto_trading"] is False
    assert payload["lifecycle_action"] is False
    assert payload["confirm"] is False
    assert FakeRecommendationService.instances[0].calls[0]["max_stocks"] == 25
    assert FakeRecommendationService.instances[0].calls[0]["top_n"] == 5

    saved = FakeRecommendationRepository.saved_results[0]
    assert saved.config["scheduled_snapshot"] is True
    assert saved.config["research_only"] is True
    assert saved.screening_matrix_json
    assert saved.why_not_payload_json
