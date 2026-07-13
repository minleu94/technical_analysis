from decimal import Decimal
from pathlib import Path

import pytest

from app_module.paper_equal_weight_benchmark_ledger import (
    EqualWeightBenchmarkLedger,
    EqualWeightBenchmarkService,
)
from app_module.paper_portfolio_daily_runner import PaperPriceObservation


def test_benchmark_freezes_initial_constituents_and_marks_equally(tmp_path: Path) -> None:
    ledger = EqualWeightBenchmarkLedger(tmp_path / "benchmark.sqlite")
    service = EqualWeightBenchmarkService()
    baseline = service.create_baseline(
        benchmark_id="paper-main-equal",
        decision_date="2026-07-10",
        capital=Decimal("100000"),
        prices={"2330": Decimal("1000"), "2317": Decimal("100")},
    )
    ledger.append(baseline)

    marked = service.mark(
        prior=baseline,
        decision_date="2026-07-11",
        prices=(
            PaperPriceObservation("2330", "2026-07-11", "2026-07-11", Decimal("1010")),
            PaperPriceObservation("2317", "2026-07-11", "2026-07-11", Decimal("90")),
            PaperPriceObservation("2454", "2026-07-11", "2026-07-11", Decimal("999")),
        ),
    )
    ledger.append(marked)

    assert marked.constituents == baseline.constituents
    assert marked.total_value == Decimal("95500.00")
    assert ledger.list("paper-main-equal") == (baseline, marked)


def test_missing_constituent_price_fails_closed() -> None:
    baseline = EqualWeightBenchmarkService().create_baseline(
        benchmark_id="b",
        decision_date="2026-07-10",
        capital=Decimal("100000"),
        prices={"2330": Decimal("1000"), "2317": Decimal("100")},
    )

    with pytest.raises(ValueError, match="missing causal benchmark price"):
        EqualWeightBenchmarkService().mark(
            prior=baseline,
            decision_date="2026-07-11",
            prices=(PaperPriceObservation("2330", "2026-07-11", "2026-07-11", Decimal("1010")),),
        )


def test_duplicate_benchmark_date_cannot_overwrite(tmp_path: Path) -> None:
    ledger = EqualWeightBenchmarkLedger(tmp_path / "benchmark.sqlite")
    entry = EqualWeightBenchmarkService().create_baseline(
        benchmark_id="b",
        decision_date="2026-07-10",
        capital=Decimal("100000"),
        prices={"2330": Decimal("1000")},
    )
    ledger.append(entry)
    with pytest.raises(ValueError, match="already exists"):
        ledger.append(entry)
