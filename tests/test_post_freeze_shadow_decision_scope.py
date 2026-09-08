from __future__ import annotations

from pathlib import Path

import pytest

from ml_module.allocation_contracts import (
    AllocationWeightContract,
    CausalPortfolioState,
    PITFeatureValue,
    PortfolioMLDatasetRow,
    post_freeze_shadow_decision_scope,
)
from scripts import build_ml_allocation_post_freeze_shadow_input as post_freeze


_HASH = "sha256:" + "a" * 64


def _row_kwargs() -> dict[str, object]:
    return {
        "row_id": "row:post-freeze-shadow:2026-09-07:1101",
        "decision_at": "2026-09-07T18:00:00+08:00",
        "symbol": "1101",
        "features": (
            PITFeatureValue(
                feature_id="daily_prices.close",
                family_id="price_liquidity_technical",
                source_id="sqlite.daily_prices",
                value_int=100,
                scale=1,
                event_at="2026-09-07T14:30:00+08:00",
                available_at="2026-09-07T14:30:00+08:00",
                revision_id="official:20260907:1101",
                quality="observed",
                content_hash=_HASH,
                observed=True,
            ),
        ),
        "missing_family_ids": (),
        "portfolio_state": CausalPortfolioState.create(
            as_of_date="2026-09-06",
            weights=AllocationWeightContract(positions_bp=(), cash_bp=10_000),
            weekly_turnover_used_bp=0,
        ),
        "dataset_identity_hash": _HASH,
        "feature_registry_hash": _HASH,
        "source_manifest_hashes": (("sqlite.daily_prices", _HASH),),
        "targets": None,
    }


def test_post_freeze_scope_allows_actual_time_without_changing_formal_contract() -> None:
    with pytest.raises(ValueError, match="08:30"):
        PortfolioMLDatasetRow(**_row_kwargs())

    with post_freeze_shadow_decision_scope():
        row = PortfolioMLDatasetRow(**_row_kwargs())

    assert row.decision_at == "2026-09-07T18:00:00+08:00"

    with pytest.raises(ValueError, match="08:30"):
        PortfolioMLDatasetRow(**_row_kwargs())


def test_post_freeze_scope_cannot_relax_target_row_schedule() -> None:
    payload = _row_kwargs()
    payload["targets"] = object()
    with post_freeze_shadow_decision_scope(), pytest.raises(
        ValueError,
        match="08:30",
    ):
        PortfolioMLDatasetRow(**payload)

    payload = _row_kwargs()
    payload["row_id"] = "row:unrelated-shadow:2026-09-07:1101"
    with post_freeze_shadow_decision_scope(), pytest.raises(
        ValueError,
        match="08:30",
    ):
        PortfolioMLDatasetRow(**payload)


def test_machine_shadow_cli_accepts_only_past_timestamp() -> None:
    decision = post_freeze._requested_decision_datetime(
        "2026-08-01T18:00:00+08:00",
        machine_operational_path=Path("machine.json"),
    )
    assert decision.isoformat() == "2026-08-01T18:00:00+08:00"

    with pytest.raises(ValueError, match="future-dated"):
        post_freeze._requested_decision_datetime(
            "2099-01-01T18:00:00+08:00",
            machine_operational_path=Path("machine.json"),
        )
    with pytest.raises(ValueError, match="requires a timestamp"):
        post_freeze._requested_decision_datetime(
            "2026-08-01",
            machine_operational_path=Path("machine.json"),
        )
    with pytest.raises(ValueError, match="08:30"):
        post_freeze._requested_decision_datetime(
            "2026-08-01T18:00:00+08:00",
            machine_operational_path=None,
        )
