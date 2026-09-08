import pytest

from scripts.build_mops_numeric_pit_candidate import parse_listing_event, parse_ratio_rows
from scripts.build_mops_numeric_pit_candidate import parse_ratio_rows_with_diagnostics


def test_parse_ratio_rows_uses_integer_units_without_float() -> None:
    rows = parse_ratio_rows(
        "<table><tr><td>2330</td><td>台積電</td><td>592,640.25</td>"
        "<td>53.20</td><td>42.10</td><td>40.00</td><td>38.75</td></tr></table>"
    )

    assert rows == [{
        "stock_code": "2330", "company_name": "台積電", "revenue_million_twd": "592,640.25",
        "gross_margin_pct": "53.20", "operating_margin_pct": "42.10", "pretax_margin_pct": "40.00",
        "net_margin_pct": "38.75", "source_row_sha256": rows[0]["source_row_sha256"],
        "statement_items": {
            "revenue_twd_cents": 59_264_025_000_000,
            "gross_margin_bp": 5320,
            "operating_margin_bp": 4210,
            "pretax_margin_bp": 4000,
            "net_margin_bp": 3875,
        },
    }]


def test_parse_ratio_rows_keeps_empty_company_rows_out_of_numeric_acceptance() -> None:
    rows, excluded, stock_row_count, table_row_count = parse_ratio_rows_with_diagnostics(
        "<table>"
        "<tr><td>2816</td><td>旺旺保</td><td></td><td></td><td></td><td></td><td></td></tr>"
        "<tr><td>2330</td><td>台積電</td><td>592,640.25</td>"
        "<td>53.20</td><td>42.10</td><td>40.00</td><td>38.75</td></tr>"
        "</table>"
    )

    assert [row["stock_code"] for row in rows] == ["2330"]
    assert excluded == ({
        "stock_code": "2816",
        "statement_type": "financial_ratio",
        "reason": "empty_numeric_cells",
    },)
    assert stock_row_count == 2
    assert table_row_count == 2


def test_parse_ratio_rows_rejects_partially_missing_company_row() -> None:
    with pytest.raises(ValueError, match="not a decimal value"):
        parse_ratio_rows(
            "<table><tr><td>2330</td><td>台積電</td><td>592,640.25</td>"
            "<td></td><td>42.10</td><td>40.00</td><td>38.75</td></tr></table>"
        )


def test_parse_listing_event_preserves_publication_and_no_correction() -> None:
    listing = """
    <table><tr><td>2330</td><td>114 年 第一季</td><td>財務報告書</td><td></td><td></td>
    <td>IFRSs合併財報</td><td></td><td>202501_2330_AI1.pdf</td><td>5,715,493</td>
    <td>114/05/15 13:40:15</td><td>無</td></tr></table>
    """.encode("big5")

    event = parse_listing_event(listing, stock_code="2330", roc_year=114, season=1)

    assert event["period"] == "2025-Q1"
    assert event["publication_timestamp"] == "2025-05-15T13:40:15+08:00"
    assert event["correction_status"] == "none"
