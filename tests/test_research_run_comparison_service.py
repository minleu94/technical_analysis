import pandas as pd

from app_module.research_run_dtos import ResearchRunMetadataDTO
from app_module.research_run_comparison_service import (
    ComparabilityStatus,
    ResearchRunComparisonService,
)


def _metadata(
    run_id: str,
    *,
    data_fingerprint: str = "sha256:data",
    universe: list[str] | None = None,
    start_date: str = "2026-01-02",
    end_date: str = "2026-01-08",
    capital_cents: int = 1_000_000_00,
    fee_bp_x100: int = 1425,
    slippage_bp_x100: int = 500,
    execution_price: str = "next_open",
    sizing_mode: str = "fixed_amount",
    benchmark_results: dict | None = None,
) -> ResearchRunMetadataDTO:
    return ResearchRunMetadataDTO(
        run_id=run_id,
        run_name=run_id,
        run_type="single_backtest",
        strategy_id="baseline_score",
        universe=universe or ["2330", "2317"],
        start_date=start_date,
        end_date=end_date,
        data_fingerprint=data_fingerprint,
        capital_cents=capital_cents,
        fee_bp_x100=fee_bp_x100,
        slippage_bp_x100=slippage_bp_x100,
        execution_price=execution_price,
        sizing_mode=sizing_mode,
        benchmark_results=benchmark_results or {},
        payload_hash=f"sha256:{run_id}",
        created_at="2026-06-14T12:00:00",
    )


def test_comparability_marks_identical_contracts_comparable():
    service = ResearchRunComparisonService()

    result = service.evaluate_comparability(
        [_metadata("run-a"), _metadata("run-b")]
    )

    assert result.status == ComparabilityStatus.COMPARABLE
    assert result.reasons == []


def test_comparability_marks_period_universe_or_cost_differences_caution():
    service = ResearchRunComparisonService()

    result = service.evaluate_comparability(
        [
            _metadata("run-a"),
            _metadata(
                "run-b",
                universe=["2330"],
                start_date="2026-01-03",
                fee_bp_x100=2000,
            ),
        ]
    )

    assert result.status == ComparabilityStatus.CAUTION
    assert result.reasons == [
        "universe differs",
        "date range differs",
        "cost model differs",
    ]


def test_comparability_marks_data_execution_or_sizing_differences_incompatible():
    service = ResearchRunComparisonService()

    result = service.evaluate_comparability(
        [
            _metadata("run-a"),
            _metadata(
                "run-b",
                data_fingerprint="sha256:other-data",
                execution_price="close",
                sizing_mode="equal_weight",
            ),
        ]
    )

    assert result.status == ComparabilityStatus.INCOMPATIBLE
    assert result.reasons == [
        "data fingerprint differs",
        "execution price differs",
        "sizing mode differs",
    ]


def test_normalized_equity_uses_explicit_date_intersection_without_forward_fill():
    service = ResearchRunComparisonService()
    equity_by_run = {
        "run-a": pd.DataFrame(
            {
                "日期": ["2026-01-02", "2026-01-05", "2026-01-06"],
                "portfolio_value": [1000, 1100, 1210],
            }
        ),
        "run-b": pd.DataFrame(
            {
                "date": ["2026-01-05", "2026-01-06", "2026-01-07"],
                "portfolio_value": [2000, 1800, 2100],
            }
        ),
    }

    result = service.build_normalized_equity(equity_by_run)

    assert result.date_intersection == ["2026-01-05", "2026-01-06"]
    assert result.excluded_dates["run-a"] == ["2026-01-02"]
    assert result.excluded_dates["run-b"] == ["2026-01-07"]
    assert result.normalized["run-a"].to_dict(orient="records") == [
        {"date": "2026-01-05", "normalized_value": 10000},
        {"date": "2026-01-06", "normalized_value": 11000},
    ]
    assert result.normalized["run-b"].to_dict(orient="records") == [
        {"date": "2026-01-05", "normalized_value": 10000},
        {"date": "2026-01-06", "normalized_value": 9000},
    ]


def test_benchmark_attribution_reads_saved_benchmark_results_only():
    service = ResearchRunComparisonService()
    runs = [
        _metadata(
            "run-a",
            benchmark_results={
                "taiex": {
                    "total_return_bp": 1200,
                    "excess_return_bp": 300,
                }
            },
        ),
        _metadata("run-b"),
    ]

    result = service.collect_benchmark_attribution(runs)

    assert result == {
        "run-a": {
            "taiex": {
                "total_return_bp": 1200,
                "excess_return_bp": 300,
            }
        },
        "run-b": {},
    }
