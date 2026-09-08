from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

from app_module.fundamental_factor_service import FundamentalFactorService
from data_module.fundamental_schema import apply_fundamental_schema
from data_module.fundamental_statement_data import StatementItemRecord
from data_module.statement_semantic_mapping import map_statement_items_for_factors
from decision_module.factors.factor_dtos import FactorQuality


_SOURCE_VERSION = (
    "mops-t164-consolidated-statements-with-mops-ezsearch-publication-xbrl-row-codes.v3"
)
_MATERIALIZED_SOURCE_VERSION = _SOURCE_VERSION + ":content:" + "a" * 64
_LINEAGE = "sha256:" + "b" * 64


def _official_record(
    *,
    item_code: str = "4000",
    semantic_name: str = "Revenue",
    value: str = "1000",
    xbrl_concept: str = "ifrs-full:Revenue",
) -> StatementItemRecord:
    return StatementItemRecord(
        stock_code="2330",
        statement_type="income_statement",
        period="2026-Q2",
        as_of_date=date(2026, 6, 30),
        announced_date=date(2026, 8, 15),
        available_date=date(2026, 9, 8),
        item_code=item_code,
        item_name="營業收入合計",
        value=Decimal(value),
        source="mops.t164sb01.statement",
        source_version=_MATERIALIZED_SOURCE_VERSION,
        quality=FactorQuality.OBSERVED,
        report_basis="consolidated",
        item_code_source="mops.t164sb01.xbrl.row_code",
        item_code_lineage_sha256=_LINEAGE,
        official_item_name="營業收入合計",
        xbrl_concept=xbrl_concept,
        candidate_source_version=_SOURCE_VERSION,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
        period_basis="quarter_single",
        value_unit="TWD",
        value_scale=1,
    )


def test_official_row_code_maps_to_semantic_code_and_keeps_lineage() -> None:
    result = map_statement_items_for_factors((_official_record(),))

    assert result.diagnostics == ()
    mapped = result.records[0]
    assert mapped.item_code == "Revenue"
    assert mapped.raw_item_code == "4000"
    assert mapped.item_code_source == "mops.t164sb01.xbrl.row_code"
    assert mapped.item_code_lineage_sha256 == _LINEAGE
    assert mapped.semantic_mapping_source == (
        "mops.t164sb01.xbrl.row_code-to-factor-semantic.v1"
    )
    assert mapped.value == Decimal("1000")


def test_official_row_code_with_wrong_xbrl_identity_is_not_mapped() -> None:
    result = map_statement_items_for_factors(
        (_official_record(xbrl_concept="ifrs-full:GrossProfit"),)
    )

    assert result.records[0].item_code == "4000"
    assert result.diagnostics[0].code == (
        "fundamental_statement.semantic_mapping_unproven"
    )


def test_conflicting_mapped_revisions_are_removed_fail_closed() -> None:
    result = map_statement_items_for_factors(
        (
            _official_record(value="1000"),
            _official_record(value="1001"),
        )
    )

    assert result.records == ()
    assert result.diagnostics[0].code == "fundamental_statement.revision_ambiguous"


def test_factor_service_reads_official_codes_through_compat_mapping(
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "consumer.db"
    with sqlite3.connect(db_file) as conn:
        apply_fundamental_schema(conn)
        conn.executescript(
            """
            CREATE TABLE mops_statement_consumer_metadata (
                stock_code TEXT NOT NULL,
                statement_type TEXT NOT NULL,
                report_basis TEXT NOT NULL,
                period TEXT NOT NULL,
                item_code TEXT NOT NULL,
                materialized_source_version TEXT NOT NULL,
                candidate_source_version TEXT,
                official_item_name TEXT,
                item_code_source TEXT,
                xbrl_concept TEXT,
                item_code_lineage_sha256 TEXT,
                period_start TEXT,
                period_end TEXT,
                period_basis TEXT,
                value_unit TEXT,
                value_scale INTEGER,
                PRIMARY KEY (
                    stock_code, statement_type, period, item_code,
                    materialized_source_version
                )
            );
            """
        )
        rows = (
            ("income_statement", "9750", "基本每股盈餘合計", "1.25", "ifrs-full:BasicEarningsLossPerShare"),
            ("income_statement", "4000", "營業收入合計", "1000", "ifrs-full:Revenue"),
            ("income_statement", "5950", "營業毛利（毛損）淨額", "400", "ifrs-full:GrossProfit"),
            ("income_statement", "6900", "營業利益（損失）", "250", "ifrs-full:ProfitLossFromOperatingActivities"),
            ("income_statement", "7900", "繼續營業單位稅前淨利（淨損）", "300", "ifrs-full:ProfitLossBeforeTax"),
            ("income_statement", "8200", "本期淨利（淨損）", "200", "ifrs-full:ProfitLoss"),
            ("balance_sheet", "3XXX", "權益總計", "2000", "ifrs-full:Equity"),
        )
        for statement_type, item_code, item_name, value, concept in rows:
            conn.execute(
                """
                INSERT INTO fundamental_statement_items(
                    stock_code, statement_type, period, as_of_date,
                    announced_date, available_date, item_code, item_name,
                    value, source, source_version, quality
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "2330",
                    statement_type,
                    "2026-Q2",
                    "2026-06-30",
                    "2026-08-15",
                    "2026-09-08",
                    item_code,
                    item_name,
                    value,
                    "mops.t164sb01.statement",
                    _MATERIALIZED_SOURCE_VERSION,
                    "observed",
                ),
            )
            conn.execute(
                """
                INSERT INTO mops_statement_consumer_metadata(
                    stock_code, statement_type, report_basis, period,
                    item_code, materialized_source_version,
                    candidate_source_version, official_item_name,
                    item_code_source, xbrl_concept, item_code_lineage_sha256,
                    period_start, period_end, period_basis, value_unit, value_scale
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "2330",
                    statement_type,
                    "consolidated",
                    "2026-Q2",
                    item_code,
                    _MATERIALIZED_SOURCE_VERSION,
                    _SOURCE_VERSION,
                    item_name,
                    "mops.t164sb01.xbrl.row_code",
                    concept,
                    _LINEAGE,
                    "2026-04-01",
                    "2026-06-30",
                    "quarter_single",
                    "TWD_per_share" if item_code == "9750" else "TWD",
                    100 if item_code == "9750" else 1,
                ),
            )

    snapshot = FundamentalFactorService(db_file).build_snapshot(
        stock_code="2330",
        decision_date=date(2026, 9, 9),
    )

    factor_names = {record.factor_name for record in snapshot.records}
    assert {
        "fundamental.statement.eps",
        "fundamental.statement.gross_margin",
        "fundamental.statement.operating_margin",
        "fundamental.statement.roe",
        "fundamental.statement.non_operating_income_ratio",
    } <= factor_names
    eps = next(
        record
        for record in snapshot.records
        if record.factor_name == "fundamental.statement.eps"
    )
    assert eps.value == Decimal("1.25")
    assert eps.metadata["raw_item_codes"] == ("9750",)
    assert eps.metadata["item_code_lineage_sha256s"] == (_LINEAGE,)
    assert eps.metadata["period_bases"] == ("quarter_single",)
