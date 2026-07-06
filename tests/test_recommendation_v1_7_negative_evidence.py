from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from app_module.dtos import RecommendationDTO, RecommendationResultDTO
from app_module.evidence_event_dtos import EvidenceEventType
from app_module.evidence_event_importer_dtos import EvidenceCaptureRequest
from app_module.evidence_event_importers import RecommendationEvidenceImporter
from app_module.recommendation_service import RecommendationService
from tests.test_recommendation_evidence_importer import FakeRecommendationRepository


def _stock_frame() -> pd.DataFrame:
    dates = pd.date_range("2026-06-01", periods=20)
    rows: list[dict[str, object]] = []
    for stock_code in ("PASS", "FAIL", "SKIP", "DEGRADED"):
        for trade_date in dates:
            rows.append(
                {
                    "日期": trade_date,
                    "證券代號": stock_code,
                    "證券名稱": f"{stock_code}_NAME",
                    "收盤價": 100.0,
                    "成交股數": 1000,
                }
            )
    for trade_date in dates[:10]:
        rows.append(
            {
                "日期": trade_date,
                "證券代號": "MISSING",
                "證券名稱": "MISSING_NAME",
                "收盤價": 100.0,
                "成交股數": 1000,
            }
        )
    return pd.DataFrame(rows)


def test_recommendation_result_preserves_screening_matrix_roundtrip() -> None:
    result = RecommendationResultDTO(
        result_id="rec-v17",
        result_name="V1.7 fixture",
        config={},
        recommendations=[],
        screening_matrix_json=[
            {
                "stock_code": "1101",
                "status": "fail",
                "reason_codes": ["recommendation_score_below_threshold"],
                "quality": "observed",
            }
        ],
    )

    reloaded = RecommendationResultDTO.from_dict(result.to_dict())

    assert reloaded.screening_matrix_json == result.screening_matrix_json


@patch("pandas.read_csv")
def test_recommendation_service_records_full_screening_matrix_statuses(mock_read_csv) -> None:
    config = MagicMock()
    config.use_sqlite = False
    config.stock_data_file.exists.return_value = True
    config.stock_data_file.stat.return_value.st_size = 1024
    config.all_stocks_data_file.exists.return_value = False
    mock_read_csv.return_value = _stock_frame()
    service = RecommendationService(config, industry_mapper=MagicMock())

    def side_effect(stock_df: pd.DataFrame, _config: dict[str, object]) -> pd.DataFrame:
        stock_code = str(stock_df["證券代號"].iloc[0])
        if stock_code == "SKIP":
            return pd.DataFrame()
        if stock_code == "DEGRADED":
            raise RuntimeError("fixture failure")
        scores = {"PASS": 90.0, "FAIL": 40.0}
        return pd.DataFrame(
            {
                "TotalScore": [scores[stock_code]],
                "FinalScore": [scores[stock_code]],
                "收盤價": [100.0],
                "成交股數": [1000],
            }
        )

    service.strategy_configurator.generate_recommendations = side_effect

    recommendations = service.run_recommendation(
        config={
            "recommendation_ranking": {
                "threshold_mode": "quantile",
                "recommendation_min_percentile_bp": 8000,
                "recommendation_min_universe_size": 2,
                "recommendation_ranking_method": "nearest_rank",
            }
        },
        max_stocks=5,
        top_n=1,
    )

    statuses = {row["stock_code"]: row["status"] for row in service.last_screening_matrix}
    assert [rec.stock_code for rec in recommendations] == ["PASS"]
    assert statuses == {
        "PASS": "pass",
        "FAIL": "fail",
        "SKIP": "skipped",
        "DEGRADED": "degraded",
        "MISSING": "missing",
    }
    assert service.last_why_not_payload_json
    assert any(row["status"] == "fail" for row in service.last_why_not_payload_json)


def test_recommendation_importer_maps_screening_matrix_events() -> None:
    result = RecommendationResultDTO(
        result_id="rec-v17",
        result_name="V1.7 fixture",
        config={"profile_id": "balanced"},
        recommendations=[
            RecommendationDTO(
                stock_code="PASS",
                stock_name="PASS_NAME",
                close_price=100.0,
                price_change=1.0,
                total_score=90.0,
                indicator_score=30.0,
                pattern_score=30.0,
                volume_score=30.0,
                recommendation_reasons="rank_top",
                industry="Semi",
                regime_match=True,
            )
        ],
        screening_matrix_json=[
            {"stock_code": "PASS", "stock_name": "PASS_NAME", "status": "pass", "quality": "observed"},
            {"stock_code": "FAIL", "status": "fail", "reason_codes": ["below_threshold"], "quality": "observed"},
            {"stock_code": "SKIP", "status": "skipped", "reason_codes": ["strategy_filter_no_signal"], "quality": "degraded"},
            {"stock_code": "DEGRADED", "status": "degraded", "reason_codes": ["screening_exception"], "quality": "degraded"},
            {"stock_code": "MISSING", "status": "missing", "reason_codes": ["insufficient_history"], "quality": "missing"},
        ],
    )
    importer = RecommendationEvidenceImporter(FakeRecommendationRepository(result))

    collected = importer.collect(EvidenceCaptureRequest(source="recommendation", result_id="rec-v17"))

    event_types = {payload["event_type"] for payload in collected.event_payloads}
    assert EvidenceEventType.SCREENING_MATRIX_PASS in event_types
    assert EvidenceEventType.SCREENING_MATRIX_FAIL in event_types
    assert EvidenceEventType.SCREENING_MATRIX_SKIPPED in event_types
    assert EvidenceEventType.SCREENING_MATRIX_DEGRADED in event_types
    assert EvidenceEventType.SCREENING_MATRIX_MISSING in event_types
    assert "source_missing_screening_matrix" not in collected.diagnostics_by_code
