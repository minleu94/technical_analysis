from datetime import date
from decimal import Decimal

from app_module.factor_service import FactorService
from app_module.research_run_dtos import ResearchRunMetadataDTO
from decision_module.factors.factor_adapters import (
    build_technical_total_score_factor,
    build_volume_ratio_factor,
)


def test_factor_service_builds_snapshot_with_gate_diagnostics():
    service = FactorService()
    records = [
        build_technical_total_score_factor(
            stock_code="2330",
            as_of_date=date(2026, 6, 12),
            available_date=date(2026, 6, 12),
            total_score=Decimal("80"),
        )
    ]

    snapshot = service.build_snapshot(records, decision_date=date(2026, 6, 14))

    assert snapshot["schema_version"] == 1
    assert snapshot["decision_date"] == "2026-06-14"
    assert snapshot["factor_set_version"] == "factor-layer-v1"
    assert snapshot["records"][0]["factor_name"] == "technical.total_score"
    assert snapshot["neutralized"] == []
    assert snapshot["skipped"] == []
    assert snapshot["diagnostics"] == []


def test_factor_service_snapshot_keeps_neutralized_records():
    service = FactorService()
    record = build_volume_ratio_factor(
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 15),
        volume_ratio=Decimal("0.8"),
    )

    snapshot = service.build_snapshot([record], decision_date=date(2026, 6, 14))

    assert snapshot["records"] == []
    assert snapshot["neutralized"][0]["quality"] == "neutral"
    assert snapshot["neutralized"][0]["score_bp"] == 5000
    assert snapshot["diagnostics"][0]["code"] == "factor.neutralized_lookahead"


def test_factor_service_builds_contributions_from_snapshot():
    service = FactorService()
    records = [
        build_technical_total_score_factor(
            stock_code="2330",
            as_of_date=date(2026, 6, 12),
            available_date=date(2026, 6, 12),
            total_score=Decimal("80"),
        ),
        build_volume_ratio_factor(
            stock_code="2317",
            as_of_date=date(2026, 6, 12),
            available_date=date(2026, 6, 15),
            volume_ratio=Decimal("0.8"),
        ),
    ]

    snapshot = service.build_snapshot(records, decision_date=date(2026, 6, 14))
    contributions = service.build_contributions(snapshot)

    assert contributions["schema_version"] == 1
    assert contributions["by_stock"]["2330"][0]["state"] == "accepted"
    assert contributions["by_stock"]["2317"][0]["state"] == "neutralized"
    assert contributions["summary_by_factor"]["technical.total_score"] == {
        "accepted_count": 1,
        "neutralized_count": 0,
        "skipped_count": 0,
        "diagnostic_count": 0,
    }
    assert contributions["summary_by_factor"]["volume.volume_ratio"][
        "diagnostic_count"
    ] == 1


def test_research_run_metadata_stores_factor_snapshot_in_data_manifest():
    metadata = ResearchRunMetadataDTO(
        run_id="run-factor-1",
        run_name="factor run",
        run_type="backtest",
        data_manifest={
            "factor_snapshot": {
                "schema_version": 1,
                "decision_date": "2026-06-14",
                "records": [],
            }
        },
    )

    assert metadata.factor_snapshot["schema_version"] == 1
    assert metadata.factor_contributions == {}


def test_research_run_metadata_rejects_non_object_factor_snapshot():
    metadata = ResearchRunMetadataDTO(
        run_id="run-factor-1",
        run_name="factor run",
        run_type="backtest",
        data_manifest={"factor_snapshot": []},
    )

    try:
        metadata.factor_snapshot
    except ValueError as exc:
        assert "factor_snapshot" in str(exc)
    else:
        raise AssertionError("factor_snapshot must reject non-object payloads")
