from __future__ import annotations

from datetime import date

import pytest

import scripts.capture_mops_ezsearch_statement_availability as capture_module
from scripts.capture_mops_ezsearch_statement_availability import (
    _build_stock_evidence,
    _default_query_start_date,
    _resolve_query_window,
)


@pytest.mark.parametrize(
    ("period_year", "season", "expected"),
    (
        (2026, 1, date(2026, 4, 1)),
        (2026, 2, date(2026, 7, 1)),
        (2026, 3, date(2026, 10, 1)),
        (2026, 4, date(2027, 1, 1)),
    ),
)
def test_default_query_window_starts_after_statement_period_end(
    period_year: int,
    season: int,
    expected: date,
) -> None:
    """預設公告窗必須涵蓋期末翌日起的延後公告。"""

    assert _default_query_start_date(period_year, season) == expected


def test_default_query_window_is_not_the_fixed_august_cutoff_for_q2() -> None:
    assert _default_query_start_date(2026, 2) < date(2026, 8, 1)


def test_default_query_window_freezes_one_taipei_end_date_across_a_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = []

    def fake_taipei_today() -> date:
        observed.append(len(observed))
        return date(2026, 9, 8) if len(observed) == 1 else date(2026, 9, 9)

    monkeypatch.setattr(capture_module, "_taipei_today", fake_taipei_today)
    start_date, end_date = _resolve_query_window(
        2026,
        2,
        explicit_start=None,
        explicit_end=None,
    )

    assert start_date == date(2026, 7, 1)
    assert end_date == date(2026, 9, 8)
    assert observed == [0]


def test_future_quarter_rejects_before_output_or_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(capture_module, "_taipei_today", lambda: date(2026, 9, 8))
    monkeypatch.setattr(
        capture_module,
        "_capture_item",
        lambda **_: pytest.fail("future quarter must fail before network"),
    )
    output_dir = tmp_path / "future-quarter"

    with pytest.raises(ValueError, match="end date must not be earlier"):
        capture_module.main(
            [
                "--request",
                "3526:otc:2026-Q3",
                "--output-dir",
                str(output_dir),
            ]
        )

    assert not output_dir.exists()


def test_stock_evidence_preserves_transport_error_instead_of_calling_it_no_match() -> None:
    evidence = _build_stock_evidence(
        stock_code="3465",
        market="otc",
        period="2026-Q2",
        period_end=date(2026, 6, 30),
        item_records={
            "F26": {
                "announcement_item": "F26",
                "statement_type": "balance_sheet",
                "status": "transport_error",
                "error_type": "ConnectionError",
                "error": "WinError 10013",
            }
        },
    )

    assert evidence["records"][0]["status"] == "transport_error"
    assert evidence["errors"] == [
        {"announcement_item": "F26", "reason": "transport_error"}
    ]
