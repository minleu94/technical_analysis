"""TASK-03：歷史推薦、負面證據與跨卡 replay 接點的行為契約。"""

from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app_module.dtos import RecommendationResultDTO
from app_module.recommendation_service import RecommendationService
from app_module.recommendation_replay_service import RecommendationReplayService
from app_module.recommendation_save_coordinator import RecommendationSaveRequest
from decision_module.scoring_engine import ScoringEngine


def market_frame(codes=("2330", "2317"), start="2026-05-01", periods=20):
    return pd.DataFrame([
        {"日期": day, "available_date": day, "證券代號": code, "收盤價": 100,
         "成交股數": 1000, "證券名稱": code}
        for code in codes for day in pd.date_range(start, periods=periods)
    ])


def make_service(tmp_path, frame, *, scores=None):
    mapper = MagicMock()
    mapper.get_stock_industries.return_value = []
    service = RecommendationService(
        SimpleNamespace(db_file=tmp_path / "missing.db", use_sqlite=False),
        industry_mapper=mapper, market_data_provider=lambda: frame,
        regime_detector=MagicMock(),
    )

    def evaluate(stock_df, config):
        config.setdefault("filters", {})["mutated_by_engine"] = True
        score = (scores or {}).get(str(stock_df.iloc[-1]["證券代號"]), Decimal("70.01"))
        return pd.DataFrame({"FinalScore": [score], "TotalScore": [score], "收盤價": [Decimal("100.00")]})

    service.strategy_configurator.generate_recommendations = evaluate
    return service


def test_future_append_and_late_revision_preserve_historical_result(tmp_path):
    original = market_frame()
    late = original.iloc[[-1]].copy()
    late["available_date"] = pd.Timestamp("2026-06-01")
    late["收盤價"] = 9999
    future = market_frame(("0000",), "2026-06-01")
    expanded = pd.concat([future, original, late], ignore_index=True)
    config = {"profile_id": "momentum", "profile_version": "1.0", "signals": {"weights": {"technical": 10000}}}
    a, b = make_service(tmp_path, original), make_service(tmp_path, expanded)
    first = a.run_recommendation(config, as_of_date="2026-05-20", max_stocks=2, top_n=1)
    second = b.run_recommendation(config, as_of_date="2026-05-20", max_stocks=2, top_n=1)
    assert [r.to_dict() for r in first] == [r.to_dict() for r in second]
    assert a.last_run_context == b.last_run_context
    assert a.last_why_not_payload_json == b.last_why_not_payload_json
    assert first[0].eligible_universe_size == 2
    assert "mutated_by_engine" not in config.get("filters", {})
    assert "mutated_by_engine" not in a.last_run_context["strategy_config"].get("filters", {})


@pytest.mark.parametrize("score", [None, Decimal("NaN"), Decimal("Infinity")])
def test_unknown_score_is_excluded_with_serializable_why_not(tmp_path, score):
    service = make_service(tmp_path, market_frame(), scores={"2330": score})
    recs = service.run_recommendation({}, as_of_date="2026-05-20")
    assert [r.stock_code for r in recs] == ["2317"]
    assert service.last_exclusion_quality == "degraded"
    row = service.last_why_not_payload_json[0]
    assert row["reason_codes"] == ["total_score_missing_or_nonfinite"]
    assert row["quality"] == "missing"
    assert row["as_of_date"] == "2026-05-20"
    assert len(row["data_fingerprint"]) == 64
    json.dumps(row, allow_nan=False)


def test_universe_is_applied_after_point_in_time_filter(tmp_path):
    service = make_service(tmp_path, market_frame())
    recs = service.run_recommendation({}, as_of_date="2026-05-20", universe=["2317"])
    assert [r.stock_code for r in recs] == ["2317"]
    assert service.last_run_context["universe_spec"]["codes"] == ["2317"]
    assert recs[0].eligible_universe_size == 1


@pytest.mark.parametrize("kind", ["future_only", "industry", "universe"])
def test_empty_candidate_set_is_valid(tmp_path, kind):
    service = make_service(tmp_path, market_frame())
    config = {"filters": {"industry": "不存在"}} if kind == "industry" else {}
    service.industry_mapper.filter_stocks_by_industry.return_value = []
    service.industry_mapper.get_all_industries.return_value = []
    recs = service.run_recommendation(config, as_of_date="2026-04-01" if kind == "future_only" else "2026-05-20", universe=[] if kind == "universe" else None)
    assert recs == []
    assert service.last_run_context["eligible_universe_size"] == 0


def test_explicit_cutoff_uses_readonly_db_window_not_global_latest(tmp_path):
    db_file = tmp_path / "market.db"
    history = market_frame().drop(columns="available_date")
    future = market_frame(("9999",), "2026-09-01").drop(columns="available_date")
    data = pd.concat([history, future])
    data["日期"] = data["日期"].dt.strftime("%Y%m%d")
    with sqlite3.connect(db_file) as conn:
        data.to_sql("daily_prices", conn, index=False)
    before = hashlib.sha256(db_file.read_bytes()).hexdigest()
    service = make_service(tmp_path, history)
    from app_module.recommendation_market_data_provider import DefaultRecommendationMarketDataProvider
    service.config = SimpleNamespace(db_file=db_file, use_sqlite=True)
    service.market_data_provider = DefaultRecommendationMarketDataProvider(service.config)
    assert len(service.run_recommendation({}, as_of_date="2026-05-20")) == 2
    assert [rec.stock_code for rec in service.run_recommendation({})] == ["9999"]
    assert hashlib.sha256(db_file.read_bytes()).hexdigest() == before


def test_missing_fundamental_database_is_not_created(tmp_path):
    service = make_service(tmp_path, market_frame(("2330",)))
    assert service.run_recommendation({"filters": {"pe_ratio_max": "15"}}, as_of_date="2026-05-20") == []
    assert not service.config.db_file.exists()
    assert service.last_why_not_payload_json[0]["quality"] == "missing"


def test_pe_future_append_candidate_quality_and_input_fingerprint(tmp_path):
    from data_module.fundamental_schema import apply_fundamental_schema
    service = make_service(tmp_path, market_frame(("2330",)))
    with sqlite3.connect(service.config.db_file) as conn:
        apply_fundamental_schema(conn)
        conn.execute("INSERT INTO fundamental_valuation_metrics(stock_code, as_of_date, available_date, metric_name, value, source, source_version, quality) VALUES ('2330','2026-05-01','2026-05-02','pe','12.00','fixture','v1','observed')")
    config = {"filters": {"pe_ratio_max": "15"}}
    assert service.run_recommendation(config, as_of_date="2026-05-20")
    original = deepcopy(service.last_run_context)
    with sqlite3.connect(service.config.db_file) as conn:
        conn.execute("INSERT INTO fundamental_valuation_metrics(stock_code, as_of_date, available_date, metric_name, value, source, source_version, quality) VALUES ('2330','2026-05-19','2026-05-21','pe','99.00','fixture','v2','observed')")
        conn.execute("INSERT INTO fundamental_valuation_metrics(stock_code, as_of_date, available_date, metric_name, value, source, source_version, quality) VALUES ('2330','2026-05-18','2026-05-18','pe','99.00','fixture','candidate','candidate')")
    assert service.run_recommendation(config, as_of_date="2026-05-20")
    assert service.last_run_context == original
    assert service.last_run_context["fundamental_inputs"][0]["source_version"] == "v1"
    assert service.run_recommendation(config, as_of_date="2026-05-21") == []
    assert service.last_run_context["data_fingerprint"] != original["data_fingerprint"]


def test_price_dto_roundtrip_keeps_exact_decimal():
    from app_module.dtos import RecommendationDTO
    dto = RecommendationDTO.from_dict({"收盤價": "100.00000000000000000001"})
    assert dto.close_price == Decimal("100.00000000000000000001")
    assert RecommendationDTO.from_dict(dto.to_dict()).close_price == dto.close_price


def test_unverified_historical_industry_membership_cannot_supply_reason(tmp_path):
    service = make_service(tmp_path, market_frame(("2330",)))
    service.industry_mapper.get_stock_industries.return_value = ["半導體"]
    service.industry_mapper.get_industry_performance.return_value = None
    assert service.run_recommendation({}, as_of_date="2026-05-20")
    service.industry_mapper.get_industry_performance.assert_not_called()
    assert "industry_membership_not_point_in_time" in service.last_run_context["warnings"]
    assert service.run_recommendation({"filters": {"industry": "半導體"}}, as_of_date="2026-05-20") == []
    assert service.last_why_not_payload_json[0]["reason_codes"] == ["industry_membership_pit_unavailable"]


def test_existing_save_coordinator_preserves_run_context_and_why_not(tmp_path):
    service = make_service(tmp_path, market_frame(), scores={"2330": None})
    recs = service.run_recommendation({}, as_of_date="2026-05-20")
    request = RecommendationSaveRequest("測試", {"_recommendation_run_context": service.last_run_context}, tuple(recs), "momentum", {"version": "1.0"}, None)
    dto = request.build_result(recommendation_service=service, regime_service=MagicMock())
    exported = dto.to_dict()
    roundtrip = RecommendationResultDTO.from_dict(json.loads(json.dumps(exported, default=str, allow_nan=False)))
    service.last_run_context["strategy_config"]["new"] = "later"
    assert roundtrip.run_context == dto.run_context
    assert "new" not in dto.run_context["strategy_config"]
    assert roundtrip.why_not_payload_json == dto.why_not_payload_json
    assert "_recommendation_run_context" not in dto.config
    assert RecommendationResultDTO.from_dict({}).run_context == {}


def test_profile_replay_sends_frozen_config_and_pit_frame():
    from ui_qt.views.recommendation_view import build_recommendation_portfolio_backtest_config
    config = {"signals": {"weights": {"technical": 10000}}, "filters": {"industry": "全部"}}
    payload = build_recommendation_portfolio_backtest_config("momentum", "動能", config, None)
    original = deepcopy(config)
    config["filters"]["industry"] = "later"
    assert payload["strategy_config"] == original
    assert "stock_list" not in payload
    frames = []

    def provider(frame, passed_config, top_n):
        frames.append(frame)
        passed_config["filters"]["industry"] = "mutated"
        return [{"stock_code": "2330", "total_score": "70.01"}]

    history = market_frame(("2330",))
    late = history.iloc[[-1]].copy()
    late["available_date"] = pd.Timestamp("2026-06-01")
    snapshot = RecommendationReplayService(provider).run_snapshot("2026-05-20", payload["profile_id"], payload["strategy_config"], pd.concat([history, late]), ["2330"], 1)
    assert snapshot.profile_id == "momentum"
    assert snapshot.strategy_config == original
    assert len(frames[0]) == 20


def test_weighted_score_preserves_decimal_quantum(monkeypatch):
    engine = ScoringEngine()
    for method, value in [("calculate_indicator_score", "70.01"), ("calculate_pattern_score", "30.02"), ("calculate_volume_score", "90.03")]:
        monkeypatch.setattr(engine, method, lambda df, *args, _value=value, **kwargs: pd.Series([Decimal(_value)], index=df.index))
    result = engine.calculate_total_score(pd.DataFrame({"收盤價": [100]}), {"weights": {"technical": 3333, "pattern": 3333, "volume": 3334}})
    assert result.iloc[-1]["TotalScore"] == Decimal("63.36")
    assert isinstance(result.iloc[-1]["FinalScore"], Decimal)


@pytest.mark.parametrize("value", [None, Decimal("NaN"), Decimal("Infinity")])
def test_enabled_indicator_missing_value_is_unknown_in_real_scoring(value):
    config = {"technical": {"momentum": {"rsi": {"enabled": True}}}}
    frame = pd.DataFrame({"收盤價": [100, 101], "RSI": [value, 50]})
    result = ScoringEngine().calculate_total_score(frame, config)
    assert result.iloc[0]["FinalScore"].is_nan()
    assert result.iloc[1]["FinalScore"].is_finite()


def test_quantile_without_any_known_scores_is_valid_empty_result(tmp_path):
    service = make_service(tmp_path, market_frame(), scores={"2330": None, "2317": None})
    config = {"recommendation_ranking": {"threshold_mode": "quantile", "recommendation_min_percentile_bp": 5000, "recommendation_min_universe_size": 2, "recommendation_ranking_method": "nearest_rank"}}
    assert service.run_recommendation(config, as_of_date="2026-05-20") == []
    assert len(service.last_why_not_payload_json) == 2


@pytest.mark.parametrize("outcome", ["failure", "skip"])
def test_recommendation_qa_rejects_failure_or_skip(tmp_path, monkeypatch, outcome):
    from scripts import qa_validate_recommendation_tab as qa

    def injected(root, result):
        if outcome == "failure":
            raise RuntimeError("注入失敗")
        result.add_skip("required_fixture", "注入缺件")

    monkeypatch.setattr(qa, "log_dir", tmp_path)
    monkeypatch.setattr(qa, "validate_isolated_recommendation_loop", injected)
    assert qa.main() == 1
    assert (tmp_path / "VALIDATION_REPORT.md").is_file()


@pytest.mark.parametrize("beginner", [True, False])
def test_ui_request_freezes_current_profile_identity(monkeypatch, beginner):
    from ui_qt.views import recommendation_view as module
    source = {"signals": {"weights": {"technical": 10000}}}
    captured = []

    def capture(config):
        captured.append(config)
        return SimpleNamespace(validation_error=lambda: "測試到參數邊界即停止")

    monkeypatch.setattr(module, "RecommendationExecutionRequest", capture)
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *args: None)
    view = SimpleNamespace(_collect_config=lambda: source, is_beginner_mode=beginner,
                           profile_combo=SimpleNamespace(currentData=lambda: "momentum"),
                           profiles={"momentum": {"version": "2.0"}})
    module.RecommendationView._execute_recommendation(view)
    assert captured[0].get("profile_id") == ("momentum" if beginner else None)
    assert captured[0].get("profile_version") == ("2.0" if beginner else None)
    assert "profile_id" not in source


def test_saved_result_identity_is_recorded_and_cleared_by_next_analysis(monkeypatch):
    from ui_qt.views import recommendation_view as module
    outcome = SimpleNamespace(result_id="saved-rec-001", watchlist_error="", watchlist_id=None)
    monkeypatch.setattr(module, "RecommendationSaveRequest", lambda **kwargs: SimpleNamespace(persist=lambda **kwargs: outcome))
    monkeypatch.setattr(module.QInputDialog, "getText", lambda *args, **kwargs: ("保存名稱", True))
    monkeypatch.setattr(module.QMessageBox, "information", lambda *args: None)
    errors = []
    monkeypatch.setattr(module.QMessageBox, "critical", lambda *args: errors.append(args))
    view = SimpleNamespace(recommendation_repository=object(), current_recommendations=[object()],
        current_config={"profile_id": "momentum"}, current_profile=None, current_regime=None,
        profiles={}, recommendation_service=SimpleNamespace(last_run_context={}), universe_service=None,
        regime_service=None, current_result_id="old-rec", execute_btn=MagicMock(),
        progress_bar=MagicMock(), progress_label=MagicMock())
    refreshed_result_ids = []
    view._update_research_context_banner = lambda: refreshed_result_ids.append(view.current_result_id)
    module.RecommendationView._save_recommendation_result(view)
    assert not errors and view.current_result_id == "saved-rec-001"
    module.RecommendationView._on_recommendation_finished(view, [])
    assert view.current_result_id == ""
    assert refreshed_result_ids == [""]
