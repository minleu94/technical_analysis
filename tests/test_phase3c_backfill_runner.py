from datetime import date
import sqlite3
from unittest.mock import patch

import pandas as pd
import pytest

from data_module import phase3c_backfill_runner as runner_module
from data_module.p0_candidate_repository import ProductionPathRejectedError
from data_module.phase3c_backfill_runner import APPLY_CONFIRM_TOKEN, Phase3CBackfillRunner
from scripts.update_phase3c_candidates import update_phase3c_candidates_range


def _production_db(tmp_path):
    prod_root = tmp_path / "FA_Data"
    prod_db = prod_root / "sqlite" / "twstock.db"
    prod_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(prod_db) as conn:
        conn.execute("CREATE TABLE market_indices (trade_date TEXT, index_name TEXT)")
        conn.execute("INSERT INTO market_indices VALUES ('20240722', 'TAIEX')")
    return prod_root, prod_db


def _institutional_frame():
    return pd.DataFrame([{
        "stock_code": "2330", "decision_date": "2024-07-22", "source_version": "test-v1",
        "publication_at": None, "first_observed_at": "2024-07-22T10:00:00Z",
        "available_at": "2024-07-22T10:00:00Z", "available_date": None, "quality": "degraded",
        "foreign_investor_buy": 100, "foreign_investor_sell": 50, "foreign_investor_net": 50,
        "investment_trust_buy": 10, "investment_trust_sell": 5, "investment_trust_net": 5,
        "dealer_buy": 20, "dealer_sell": 10, "dealer_net": 10,
    }])


def _credit_frame():
    return pd.DataFrame([{
        "stock_code": "2330", "decision_date": "2024-07-22", "source_version": "test-v1",
        "publication_at": None, "first_observed_at": "2024-07-22T10:00:00Z",
        "available_at": "2024-07-22T10:00:00Z", "available_date": None, "quality": "degraded",
        "margin_purchase": 100, "margin_balance": 200, "short_sale": 10, "short_balance": 20,
        "financing": None, "securities_lending": None,
    }])


def _tdcc_frame():
    return pd.DataFrame([{
        "stock_code": "2330", "decision_date": "2024-07-19", "source_version": "test-v1",
        "publication_at": None, "first_observed_at": "2024-07-22T10:00:00Z",
        "available_at": "2024-07-22T10:00:00Z", "available_date": None, "quality": "degraded",
        "shareholding_tiers": "weekly_distribution_available",
        "large_holder_ratio_bp": 6000, "retail_holder_ratio_bp": 1200,
        "dispersion_index_bp": -4800,
    }])


def test_runner_rejects_production_db_path(tmp_path):
    prod_root, prod_db = _production_db(tmp_path)
    with pytest.raises(ProductionPathRejectedError):
        Phase3CBackfillRunner(prod_db, production_data_root=prod_root, production_db_path=prod_db)


def test_runner_rejects_unknown_source(tmp_path):
    prod_root, prod_db = _production_db(tmp_path)
    with pytest.raises(ValueError, match="sources 必須"):
        Phase3CBackfillRunner(
            tmp_path / "candidate.db", sources=("unknown",),
            production_data_root=prod_root, production_db_path=prod_db,
        )


def test_apply_requires_explicit_candidate_db_path():
    with pytest.raises(ValueError, match="explicit --db-path"):
        update_phase3c_candidates_range(
            "2024-07-22", "2024-07-22", dry_run=False, db_path=None
        )


def test_configured_candidate_db_uses_persisted_user_environment_when_process_is_stale(
    tmp_path,
    monkeypatch,
):
    candidate = tmp_path / "candidate.db"
    monkeypatch.delenv("PHASE3C_CANDIDATE_DB_PATH", raising=False)
    monkeypatch.setattr(
        runner_module,
        "_persisted_user_environment_value",
        lambda _name: str(candidate),
    )

    assert runner_module.configured_candidate_db_path() == candidate


def test_process_candidate_environment_overrides_persisted_user_value(
    tmp_path,
    monkeypatch,
):
    process_candidate = tmp_path / "process.db"
    monkeypatch.setenv(
        "PHASE3C_CANDIDATE_DB_PATH",
        str(process_candidate),
    )
    monkeypatch.setattr(
        runner_module,
        "_persisted_user_environment_value",
        lambda _name: str(tmp_path / "persisted.db"),
    )

    assert runner_module.configured_candidate_db_path() == process_candidate


def test_runner_dry_run_leaves_candidate_db_untouched(tmp_path):
    prod_root, prod_db = _production_db(tmp_path)
    cand_db = tmp_path / "candidate.db"
    runner = Phase3CBackfillRunner(
        cand_db, sources=("institutional",), production_data_root=prod_root,
        production_db_path=prod_db, rate_limit_seconds=0,
    )
    with patch("data_module.phase3c_backfill_runner.fetch_institutional_flows", return_value=_institutional_frame()):
        summary = runner.run_backfill(date(2024, 7, 22), date(2024, 7, 22), dry_run=True)

    assert summary.succeeded_days_count == 1
    assert not cand_db.exists()


def test_runner_sources_filter_excludes_tdcc_and_writes_checkpoints(tmp_path):
    prod_root, prod_db = _production_db(tmp_path)
    cand_db = tmp_path / "candidate.db"
    runner = Phase3CBackfillRunner(
        cand_db, sources=("institutional", "credit"), production_data_root=prod_root,
        production_db_path=prod_db, rate_limit_seconds=0,
    )
    with patch("data_module.phase3c_backfill_runner.fetch_institutional_flows", return_value=_institutional_frame()) as institutional, patch(
        "data_module.phase3c_backfill_runner.fetch_credit_transactions", return_value=_credit_frame()
    ) as credit:
        summary = runner.run_backfill(
            date(2024, 7, 22), date(2024, 7, 22), dry_run=False,
            confirm_token=APPLY_CONFIRM_TOKEN,
        )

    assert {r["source"] for r in summary.daily_results} == {"institutional", "credit"}
    assert institutional.call_count == 1
    assert credit.call_count == 1
    with sqlite3.connect(cand_db) as conn:
        checkpoints = conn.execute(
            "SELECT source, status FROM phase3c_backfill_checkpoints ORDER BY source"
        ).fetchall()
    assert checkpoints == [("credit", "SUCCESS"), ("institutional", "SUCCESS")]


def test_runner_resume_uses_success_checkpoint_without_refetch(tmp_path):
    prod_root, prod_db = _production_db(tmp_path)
    runner = Phase3CBackfillRunner(
        tmp_path / "candidate.db", sources=("institutional",), production_data_root=prod_root,
        production_db_path=prod_db, rate_limit_seconds=0,
    )
    with patch("data_module.phase3c_backfill_runner.fetch_institutional_flows", return_value=_institutional_frame()) as fetch:
        runner.run_backfill(date(2024, 7, 22), date(2024, 7, 22), dry_run=False, confirm_token=APPLY_CONFIRM_TOKEN)
        resumed = runner.run_backfill(date(2024, 7, 22), date(2024, 7, 22), dry_run=False, confirm_token=APPLY_CONFIRM_TOKEN)

    assert fetch.call_count == 1
    assert resumed.daily_results[0]["status"] == "SKIPPED_ALREADY_EXISTS"


def test_runner_tdcc_default_preserves_historical_block(tmp_path):
    prod_root, prod_db = _production_db(tmp_path)
    runner = Phase3CBackfillRunner(
        tmp_path / "candidate.db", sources=("tdcc",), production_data_root=prod_root,
        production_db_path=prod_db, rate_limit_seconds=0,
    )

    with patch("data_module.phase3c_backfill_runner.fetch_latest_tdcc_shareholding") as fetch:
        summary = runner.run_backfill(
            date(2024, 7, 22), date(2024, 7, 22), dry_run=False,
            confirm_token=APPLY_CONFIRM_TOKEN,
        )

    fetch.assert_not_called()
    assert summary.daily_results[0]["status"] == "BLOCKED_NO_HISTORICAL_ENDPOINT"
    assert summary.succeeded_days_count == 0
    assert summary.skipped_days_count == 1


def test_runner_latest_tdcc_snapshot_uses_payload_date_and_checkpoint(tmp_path):
    prod_root, prod_db = _production_db(tmp_path)
    cand_db = tmp_path / "candidate.db"
    runner = Phase3CBackfillRunner(
        cand_db, sources=("tdcc",), production_data_root=prod_root,
        production_db_path=prod_db, rate_limit_seconds=0,
        include_latest_tdcc_snapshot=True,
    )

    with patch(
        "data_module.phase3c_backfill_runner.fetch_latest_tdcc_shareholding",
        return_value=_tdcc_frame(),
    ) as fetch:
        summary = runner.run_backfill(
            date(2024, 7, 19), date(2024, 7, 22), dry_run=False,
            confirm_token=APPLY_CONFIRM_TOKEN,
        )

    fetch.assert_called_once_with()
    assert len(summary.daily_results) == 1
    assert summary.daily_results[0]["decision_date"] == "2024-07-19"
    assert summary.daily_results[0]["status"] == "SUCCESS"
    assert summary.total_rows_inserted == 1
    assert "LATEST_SNAPSHOT_ENABLED" in summary.tdcc_historical_status
    with sqlite3.connect(cand_db) as conn:
        tdcc_rows = conn.execute(
            "SELECT stock_code, decision_date FROM tdcc_shareholding"
        ).fetchall()
        checkpoint = conn.execute(
            "SELECT decision_date, source, status, row_count "
            "FROM phase3c_backfill_checkpoints"
        ).fetchone()
    assert tdcc_rows == [("2330", "2024-07-19")]
    assert checkpoint == ("2024-07-19", "tdcc", "SUCCESS", 1)
