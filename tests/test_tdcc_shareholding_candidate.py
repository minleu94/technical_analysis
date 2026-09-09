from __future__ import annotations

from datetime import datetime, timezone
import csv
import io
import json
import sqlite3
from types import SimpleNamespace

import pytest

from data_module.p0_tdcc_distribution_shadow_adapter import TDCCDistributionShadowAdapter
from data_module.tdcc_shareholding_candidate import (
    TDCCPayloadError,
    normalize_tdcc_payload,
    p0_shadow_row,
)
from app_module.stock_research_report_service import StockResearchReportReadService


def _payload(*, mismatch: bool = False) -> bytes:
    fields = ["資料日期", "證券代號", "持股分級", "人數", "股數", "占集保庫存數比例%"]
    rows = []
    values = ["1.00"] * 16
    values[0] = "2.00"
    values[1] = "3.00"
    values[14] = "83.00"
    values[15] = "0.00"
    if mismatch:
        values[5] = "20.00"
    for tier, value in enumerate(values, 1):
        rows.append(["20260904", "2330", str(tier), "10", "100", value])
    rows.append(["20260904", "2330", "17", "10", "1000", "100.00"])
    handle = io.StringIO()
    writer = csv.writer(handle)
    writer.writerow(fields)
    writer.writerows(rows)
    return handle.getvalue().encode("utf-8-sig")


def test_normalizes_full_tiers_and_preserves_report_vs_observed() -> None:
    observed = datetime(2026, 9, 9, 5, 3, tzinfo=timezone.utc)
    result = normalize_tdcc_payload(_payload(), observed_at=observed)
    assert result.report_date == "2026-09-04"
    assert result.symbol_count == 1
    assert len(result.tier_rows) == 17
    assert result.tier_rows[-1]["tier_role"] == "official_total"
    row = result.aggregate_rows[0]
    assert row["period_end"] == "2026-09-04"
    assert row["available_date"] == "2026-09-10"
    assert row["first_observed_at"] == "2026-09-09T05:03:00Z"
    assert row["candidate_status"] == "shadow_ready"
    assert json.loads(row["shareholding_tiers"])[-1]["tier"] == 17
    shadow = p0_shadow_row(row)
    observation = TDCCDistributionShadowAdapter().adapt(row=shadow, decision_date="2026-09-10")
    assert observation.status == "shadow_ready"
    assert observation.effective_from == "2026-09-04"
    assert "weekly_period_end_is_not_available_date" in observation.diagnostics


def test_distribution_mismatch_keeps_full_tiers_but_blocks_aggregate() -> None:
    result = normalize_tdcc_payload(
        _payload(mismatch=True),
        observed_at=datetime(2026, 9, 9, 5, 3, tzinfo=timezone.utc),
    )
    assert len(result.tier_rows) == 17
    assert len(result.quarantine_rows) == 1
    assert result.aggregate_rows[0]["candidate_status"] == "blocked"
    assert "source_distribution_total_mismatch" in result.aggregate_rows[0]["diagnostics"]
    shadow = p0_shadow_row(result.aggregate_rows[0])
    observation = TDCCDistributionShadowAdapter().adapt(row=shadow, decision_date="2026-09-10")
    assert observation.status == "blocked"
    assert any(
        code in observation.diagnostics
        for code in ("holder_ratio_total_not_10000bp", "invalid_other_holder_ratio_bp")
    )


def test_duplicate_level_is_rejected_without_silent_drop() -> None:
    payload = _payload() + "20260904,2330,16,10,100,1.00\n".encode("utf-8")
    with pytest.raises(TDCCPayloadError, match="重複列"):
        normalize_tdcc_payload(payload, observed_at=datetime(2026, 9, 9, tzinfo=timezone.utc))


def test_naive_observed_at_is_rejected() -> None:
    with pytest.raises(TDCCPayloadError, match="timezone"):
        normalize_tdcc_payload(_payload(), observed_at=datetime(2026, 9, 9))


def test_individual_research_reader_respects_safe_date_and_surfaces_all_tiers(tmp_path) -> None:
    database = tmp_path / "twstock.db"
    with sqlite3.connect(database) as conn:
        conn.execute("""CREATE TABLE tdcc_shareholding (
            stock_code TEXT, decision_date TEXT, available_date TEXT, source_version TEXT,
            quality TEXT, shareholding_tiers TEXT, large_holder_ratio_bp INTEGER,
            retail_holder_ratio_bp INTEGER, dispersion_index_bp INTEGER,
            PRIMARY KEY (stock_code, decision_date))""")
        result = normalize_tdcc_payload(
            _payload(), observed_at=datetime(2026, 9, 9, 5, 3, tzinfo=timezone.utc)
        )
        row = result.aggregate_rows[0]
        conn.execute(
            "INSERT INTO tdcc_shareholding VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["stock_code"], row["decision_date"], row["available_date"], row["source_version"],
                row["quality"], row["shareholding_tiers"], row["large_holder_ratio_bp"],
                row["retail_holder_ratio_bp"], row["dispersion_index_bp"],
            ),
        )
    config = SimpleNamespace(db_file=database, data_root=tmp_path, output_root=tmp_path / "output")
    service = StockResearchReportReadService(config)
    early = service.read_report("2330", as_of_date="2026-09-09")
    assert early.shareholding == ()
    report = service.read_report("2330", as_of_date="2026-09-10")
    tier_metric = next(metric for metric in report.shareholding if metric.key == "shareholding_tiers")
    assert len(json.loads(tier_metric.value_text)) == 17
    assert tier_metric.data_as_of == "2026-09-04"
