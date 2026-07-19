import pytest
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock
import pandas as pd

from data_module.p0_candidate_repository import ProductionPathRejectedError
from scripts.update_phase3c_candidates import update_phase3c_candidates
from scripts.update_phase3c_candidates import run_bounded_official_probe

@pytest.fixture
def mock_fetchers():
    with patch('scripts.update_phase3c_candidates.fetch_institutional_flows') as mock_inst, \
         patch('scripts.update_phase3c_candidates.fetch_credit_transactions') as mock_credit, \
         patch('scripts.update_phase3c_candidates.fetch_tdcc_shareholding') as mock_tdcc:

        mock_inst.return_value = pd.DataFrame([{
            'stock_code': '2330', 'decision_date': '2026-07-08', 'available_date': '2026-07-09',
            'source_version': 'twse-official-T86', 'quality': 'degraded',
            'foreign_investor_buy': 100, 'foreign_investor_sell': 50, 'foreign_investor_net': 50,
            'investment_trust_buy': 0, 'investment_trust_sell': 0, 'investment_trust_net': 0,
            'dealer_buy': 0, 'dealer_sell': 0, 'dealer_net': 0
        }])

        mock_credit.return_value = pd.DataFrame([{
            'stock_code': '2330', 'decision_date': '2026-07-08', 'available_date': '2026-07-09',
            'source_version': 'twse-official-MI_MARGN', 'quality': 'degraded',
            'margin_purchase': 10, 'margin_balance': 100, 'short_sale': 5, 'short_balance': 50,
            'financing': None, 'securities_lending': None
        }])

        mock_tdcc.return_value = pd.DataFrame([{
            'stock_code': '2330', 'decision_date': '2026-07-08', 'available_date': '2026-07-11',
            'source_version': 'tdcc-official-od-1-5', 'quality': 'observed',
            'shareholding_tiers': 'weekly_distribution_available',
            'large_holder_ratio_bp': 8000, 'retail_holder_ratio_bp': 500, 'dispersion_index_bp': -7500
        }])
        yield mock_inst, mock_credit, mock_tdcc

def test_dry_run_does_not_create_db(tmp_path, mock_fetchers):
    """Dry-run must not create a DB or initialize Phase 3C tables."""
    db_path = tmp_path / "test_twstock.db"

    with patch('scripts.update_phase3c_candidates.DBManager') as MockDBManager, \
         patch('scripts.update_phase3c_candidates.TWStockConfig') as MockConfig:
        update_phase3c_candidates(date(2026, 7, 8), dry_run=True, db_path=str(db_path))

        assert not db_path.exists()
        MockDBManager.assert_not_called()
        MockConfig.assert_not_called()


def test_apply_rejects_data_root_descendant_before_config_or_db_initialization(
    tmp_path, mock_fetchers, monkeypatch
):
    """即使檔案已存在，正式 DATA_ROOT 內的目標也必須先拒絕。"""
    data_root = tmp_path / "formal-data"
    db_path = data_root / "candidate" / "working.sqlite"
    db_path.parent.mkdir(parents=True)
    db_path.touch()
    monkeypatch.setenv("DATA_ROOT", str(data_root))

    with patch('scripts.update_phase3c_candidates.DBManager') as MockDBManager, \
         patch('scripts.update_phase3c_candidates.TWStockConfig') as MockConfig:
        with pytest.raises(ProductionPathRejectedError):
            update_phase3c_candidates(
                date(2026, 7, 8),
                dry_run=False,
                db_path=str(db_path),
            )

        MockDBManager.assert_not_called()
        MockConfig.assert_not_called()

def test_apply_without_db_aborts(tmp_path, mock_fetchers, caplog):
    """Apply mode must fail closed when the target DB does not exist."""
    db_path = tmp_path / "non_existent.db"

    update_phase3c_candidates(date(2026, 7, 8), dry_run=False, db_path=str(db_path))

    assert not db_path.exists()
    assert any("dry-run / apply" in record.message for record in caplog.records)

def test_apply_with_existing_db_writes(tmp_path, mock_fetchers):
    """Apply mode writes only to the explicitly supplied existing DB."""
    db_path = tmp_path / "test_twstock.db"
    db_path.touch() # Mock existing DB

    with patch('scripts.update_phase3c_candidates.DBManager') as MockDBManager:
        mock_db_instance = MockDBManager.return_value

        update_phase3c_candidates(date(2026, 7, 8), dry_run=False, db_path=str(db_path))

        assert MockDBManager.call_args.args[0].db_file == db_path
        mock_db_instance.ensure_phase3c_candidate_tables.assert_called_once()
        assert mock_db_instance.write_dataframe.call_count == 3

        call_args_list = mock_db_instance.write_dataframe.call_args_list
        tables_written = [args[0][0] for args in call_args_list]
        assert "institutional_flows" in tables_written
        assert "credit_transactions" in tables_written
        assert "tdcc_shareholding" in tables_written

def test_optional_fields_are_none():
    """Missing optional credit fields stay None instead of being filled with zero."""
    from data_module.official_phase3c_fetcher import fetch_credit_transactions
    mock_credit = pd.DataFrame([{
        'stock_code': '2330', 'financing': None, 'securities_lending': None
    }])
    assert mock_credit['financing'].iloc[0] is None
    assert mock_credit['securities_lending'].iloc[0] is None


def test_bounded_probe_reports_schema_timestamp_and_conservation_without_acceptance(tmp_path):
    fixture_root = Path(__file__).parent / "fixtures" / "p0_official_sources"
    responses = []
    for filename, content_type in (
        ("twse_institutional.json", "application/json"),
        ("twse_credit.json", "application/json"),
        ("tdcc_shareholding.csv", "text/csv"),
        ("twse_disposition.json", "application/json"),
    ):
        response = MagicMock()
        response.content = (fixture_root / filename).read_bytes()
        response.headers = {"Content-Type": content_type}
        response.status_code = 200
        responses.append(response)

    before = tuple(tmp_path.rglob("*"))
    with patch("scripts.update_phase3c_candidates.safe_request", side_effect=responses):
        report = run_bounded_official_probe(date(2026, 7, 10))

    assert tuple(tmp_path.rglob("*")) == before
    assert report["license_accepted"] is False
    assert report["source_accepted"] is False
    assert report["downstream_eligibility"] == "none"
    assert report["production_scheduler_allowed"] is False
    assert {item["source_id"] for item in report["sources"]} == {
        "twse_institutional",
        "twse_credit",
        "tdcc_shareholding",
        "twse_disposition",
    }
    for item in report["sources"]:
        assert item["raw_row_count"] == (
            item["accepted_row_count"]
            + item["duplicate_row_count"]
            + item["quarantine_row_count"]
            + item["blocked_row_count"]
        )
        assert item["schema_status"] == "matched"
        assert item["timestamp_evidence"] in {
            "official_publication_timestamp",
            "first_observed_only",
        }


def test_bounded_probe_preserves_raw_http_evidence_when_parser_detects_schema_drift():
    fixture_root = Path(__file__).parent / "fixtures" / "p0_official_sources"
    drifted = MagicMock()
    drifted.content = b'{"stat":"No data"}'
    drifted.headers = {"Content-Type": "application/json"}
    drifted.status_code = 200
    valid_credit = MagicMock()
    valid_credit.content = (fixture_root / "twse_credit.json").read_bytes()
    valid_credit.headers = {"Content-Type": "application/json"}
    valid_credit.status_code = 200
    valid_tdcc = MagicMock()
    valid_tdcc.content = (fixture_root / "tdcc_shareholding.csv").read_bytes()
    valid_tdcc.headers = {"Content-Type": "text/csv"}
    valid_tdcc.status_code = 200

    with patch(
        "scripts.update_phase3c_candidates.safe_request",
        side_effect=[drifted, valid_credit, valid_tdcc],
    ):
        report = run_bounded_official_probe(date(2026, 7, 10))

    institutional = next(
        item for item in report["sources"] if item["source_id"] == "twse_institutional"
    )
    assert institutional["network_status"] == "reachable"
    assert institutional["http_status"] == 200
    assert institutional["payload_size_bytes"] == len(drifted.content)
    assert len(institutional["payload_sha256"]) == 64
    assert institutional["schema_status"] == "mismatch"
    assert institutional["error_type"] == "ValueError"
