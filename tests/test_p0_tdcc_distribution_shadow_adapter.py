from data_module.p0_tdcc_distribution_shadow_adapter import TDCCDistributionShadowAdapter


def _row() -> dict[str, object]:
    return {
        "symbol": "2330",
        "period_end": "2026-07-03",
        "available_date": "2026-07-08",
        "source_version": "tdcc-20260708",
        "large_holder_ratio_bp": 6200,
        "retail_holder_ratio_bp": 1800,
        "other_holder_ratio_bp": 2000,
    }


def test_tdcc_weekly_distribution_preserves_publication_date() -> None:
    observation = TDCCDistributionShadowAdapter().adapt(
        row=_row(), decision_date="2026-07-12"
    )

    assert observation.status == "shadow_ready"
    assert observation.available_date == "2026-07-08"
    assert observation.effective_from == "2026-07-03"
    assert observation.downstream_eligibility == "none"
    assert "weekly_period_end_is_not_available_date" in observation.diagnostics


def test_tdcc_future_publication_is_blocked() -> None:
    row = _row()
    row["available_date"] = "2026-07-13"

    observation = TDCCDistributionShadowAdapter().adapt(
        row=row, decision_date="2026-07-12"
    )

    assert observation.status == "blocked"
    assert "future_available_date" in observation.diagnostics


def test_tdcc_ratio_total_must_equal_full_basis_points() -> None:
    row = _row()
    row["other_holder_ratio_bp"] = 1999

    observation = TDCCDistributionShadowAdapter().adapt(
        row=row, decision_date="2026-07-12"
    )

    assert observation.status == "blocked"
    assert "holder_ratio_total_not_10000bp" in observation.diagnostics


def test_tdcc_ratios_must_be_integer_basis_points() -> None:
    row = _row()
    row["large_holder_ratio_bp"] = 62.0

    observation = TDCCDistributionShadowAdapter().adapt(
        row=row, decision_date="2026-07-12"
    )

    assert observation.status == "blocked"
    assert "invalid_large_holder_ratio_bp" in observation.diagnostics
