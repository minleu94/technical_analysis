from datetime import datetime
from types import SimpleNamespace

from app_module.dtos import RecommendationDTO
from app_module.recommendation_save_coordinator import RecommendationSaveRequest


def _recommendation() -> RecommendationDTO:
    return RecommendationDTO(
        stock_code="2330",
        stock_name="台積電",
        close_price=100,
        price_change=1,
        total_score=80,
        indicator_score=80,
        pattern_score=80,
        volume_score=80,
        recommendation_reasons="test",
        industry="半導體",
        regime_match=True,
    )


def test_save_request_builds_profile_regime_and_negative_evidence_snapshot() -> None:
    service = SimpleNamespace(
        last_excluded_candidates_json=[{"stock": "x"}],
        last_screening_matrix=[{"stock": "2330"}],
        last_why_not_payload_json=[{"reason": "none"}],
        last_liquidity_gate_payload_json=[{"status": "pass"}],
        last_exclusion_quality="observed",
        last_exclusion_warnings_json=[],
    )
    regime_service = SimpleNamespace(
        detect_regime=lambda: SimpleNamespace(
            regime="Trend",
            regime_name_cn="趨勢",
            confidence="0.8",
            details={"score": 1},
        )
    )
    request = RecommendationSaveRequest(
        result_name="研究結果",
        config={"filters": {}},
        recommendations=(_recommendation(),),
        current_profile="balanced",
        profile_meta={"name": "平衡", "version": "2.0"},
        current_regime="Trend",
    )

    result = request.build_result(
        recommendation_service=service,
        regime_service=regime_service,
        now=lambda: datetime(2026, 7, 11, 12, 0),
    )

    assert result.config["profile_id"] == "balanced"
    assert result.config["profile_version"] == "2.0"
    assert result.config["regime_snapshot"]["regime"] == "Trend"
    assert result.excluded_candidates_json == [{"stock": "x"}]


def test_save_request_builds_watchlist_payload_after_repository_id() -> None:
    request = RecommendationSaveRequest(
        result_name="研究結果",
        config={},
        recommendations=(_recommendation(),),
        current_profile="balanced",
        profile_meta={},
        current_regime="Trend",
    )

    assert request.watchlist_payload("result-1") == {
        "name": "研究結果",
        "codes": ["2330"],
        "source": "recommendation",
        "description": "來自推薦結果: result-1\nProfile: balanced\nRegime: Trend\n股票數量: 1",
    }


def test_save_request_persists_result_and_soft_fails_watchlist() -> None:
    request = RecommendationSaveRequest(
        result_name="研究結果",
        config={},
        recommendations=(_recommendation(),),
        current_profile=None,
        profile_meta={},
        current_regime=None,
    )
    repository = SimpleNamespace(save_result=lambda result: "result-1")
    universe = SimpleNamespace(
        save_watchlist=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("watchlist"))
    )

    outcome = request.persist(
        recommendation_repository=repository,
        universe_service=universe,
        recommendation_service=SimpleNamespace(),
        regime_service=SimpleNamespace(),
    )

    assert outcome.result_id == "result-1"
    assert outcome.watchlist_id is None
    assert outcome.watchlist_error == "watchlist"
