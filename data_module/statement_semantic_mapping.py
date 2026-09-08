"""官方 MOPS 財報 row code 到 factor 語意碼的受限相容映射。

研究 consumer 的 SQLite 主表保留官方 row code；factor adapter 只在這一層
建立語意視圖。映射必須同時符合來源版本、報表類型、report basis、官方
名稱、XBRL concept 與 row-code 來源，不能以任意名稱相似度猜測。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from data_module.fundamental_statement_data import StatementItemRecord
from decision_module.factors.factor_dtos import FactorDiagnostic


_REPORT_BASES = frozenset({"consolidated", "individual"})
_ROW_CODE_SOURCE = "mops.t164sb01.xbrl.row_code"
_MAPPING_CONTRACT_VERSION = "mops.t164sb01.xbrl.row_code-to-factor-semantic.v1"


@dataclass(frozen=True)
class OfficialStatementSemanticMapping:
    """一個可核對的官方 row code 語意映射。"""

    source_version: str
    statement_type: str
    report_basis: str
    industry_category: str
    official_item_code: str
    semantic_item_code: str
    official_item_name: str
    xbrl_concept: str
    item_code_source: str = _ROW_CODE_SOURCE


@dataclass(frozen=True)
class StatementSemanticMappingResult:
    """語意映射結果與 fail-closed 診斷。"""

    records: tuple[StatementItemRecord, ...]
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


_SOURCE_CONTRACTS = (
    (
        "mops-t164-consolidated-statements-with-mops-ezsearch-publication-xbrl-row-codes.v1",
        "consolidated",
    ),
    (
        "mops-t164-consolidated-statements-with-mops-ezsearch-publication-xbrl-row-codes.v3",
        "consolidated",
    ),
    (
        "mops-t164-consolidated-statements-with-t57sb01-xbrl-row-codes.v2",
        "consolidated",
    ),
    (
        "mops-t164-consolidated-statements-with-t57sb01-xbrl-row-codes.v3",
        "consolidated",
    ),
    (
        "mops-t164-individual-statements-with-mops-ezsearch-publication-xbrl-row-codes.v3",
        "individual",
    ),
)

_SEMANTIC_DEFINITIONS = (
    (
        "income_statement",
        "EPS",
        "9750",
        "基本每股盈餘合計",
        "ifrs-full:BasicEarningsLossPerShare",
    ),
    (
        "income_statement",
        "Revenue",
        "4000",
        "營業收入合計",
        "ifrs-full:Revenue",
    ),
    (
        "income_statement",
        "GrossProfit",
        "5950",
        "營業毛利（毛損）淨額",
        "ifrs-full:GrossProfit",
    ),
    (
        "income_statement",
        "OperatingIncome",
        "6900",
        "營業利益（損失）",
        "ifrs-full:ProfitLossFromOperatingActivities",
    ),
    (
        "income_statement",
        "IncomeBeforeIncomeTax",
        "7900",
        "繼續營業單位稅前淨利（淨損）",
        "ifrs-full:ProfitLossBeforeTax",
    ),
    (
        "income_statement",
        "NetIncome",
        "8200",
        "本期淨利（淨損）",
        "ifrs-full:ProfitLoss",
    ),
    (
        "balance_sheet",
        "Equity",
        "3XXX",
        "權益總計",
        "ifrs-full:Equity",
    ),
)


OFFICIAL_STATEMENT_SEMANTIC_MAPPINGS: tuple[
    OfficialStatementSemanticMapping, ...
] = tuple(
    OfficialStatementSemanticMapping(
        source_version=source_version,
        statement_type=statement_type,
        report_basis=report_basis,
        industry_category="*",
        official_item_code=official_item_code,
        semantic_item_code=semantic_item_code,
        official_item_name=official_item_name,
        xbrl_concept=xbrl_concept,
    )
    for source_version, report_basis in _SOURCE_CONTRACTS
    for statement_type, semantic_item_code, official_item_code, official_item_name, xbrl_concept in _SEMANTIC_DEFINITIONS
    if report_basis in _REPORT_BASES
)

_OFFICIAL_CODES = frozenset(
    mapping.official_item_code for mapping in OFFICIAL_STATEMENT_SEMANTIC_MAPPINGS
)
_SEMANTIC_CODES = frozenset(
    mapping.semantic_item_code for mapping in OFFICIAL_STATEMENT_SEMANTIC_MAPPINGS
)


def map_statement_items_for_factors(
    records: Iterable[StatementItemRecord],
) -> StatementSemanticMappingResult:
    """把已核對的 MOPS row code 轉成 factor adapter 所需語意碼。

    未達完整來源契約的 row 會原樣保留，並附上診斷；呼叫端因此仍可看見
    原始資料，但不會把未核對的數字拿去計算 factor。
    """

    mapped: list[StatementItemRecord] = []
    diagnostics: list[FactorDiagnostic] = []
    for record in records:
        mapped_record, diagnostic = _map_one(record)
        mapped.append(mapped_record)
        if diagnostic is not None:
            diagnostics.append(diagnostic)

    deduplicated, duplicate_diagnostics = _deduplicate_semantic_records(mapped)
    diagnostics.extend(duplicate_diagnostics)
    return StatementSemanticMappingResult(
        records=tuple(deduplicated),
        diagnostics=tuple(diagnostics),
    )


def _map_one(
    record: StatementItemRecord,
) -> tuple[StatementItemRecord, FactorDiagnostic | None]:
    raw_item_code = record.raw_item_code or record.item_code
    if raw_item_code in _SEMANTIC_CODES and record.item_code == raw_item_code:
        return record, None
    if raw_item_code not in _OFFICIAL_CODES:
        return record, None

    candidates = tuple(
        mapping
        for mapping in OFFICIAL_STATEMENT_SEMANTIC_MAPPINGS
        if mapping.official_item_code == raw_item_code
        and mapping.statement_type == record.statement_type
        and mapping.report_basis == record.report_basis.strip()
        and mapping.source_version
        == (record.candidate_source_version or record.source_version)
        and _industry_matches(mapping.industry_category, record.industry_category)
        and record.item_code_source == mapping.item_code_source
        and record.official_item_name == mapping.official_item_name
        and record.xbrl_concept == mapping.xbrl_concept
    )
    if len(candidates) != 1:
        if len(candidates) > 1:
            code = "fundamental_statement.semantic_mapping_ambiguous"
            message = (
                "official statement row matches multiple semantic mappings; "
                f"statement_type={record.statement_type}; item_code={raw_item_code}; "
                f"period={record.period}"
            )
        else:
            code = "fundamental_statement.semantic_mapping_unproven"
            message = (
                "official statement row lacks a complete semantic mapping contract; "
                f"statement_type={record.statement_type}; item_code={raw_item_code}; "
                f"period={record.period}; source_version="
                f"{record.candidate_source_version or record.source_version}"
            )
        return record, FactorDiagnostic(
            code=code,
            factor_name="fundamental.statement",
            stock_code=record.stock_code,
            message=message,
        )

    mapping = candidates[0]
    return (
        replace(
            record,
            item_code=mapping.semantic_item_code,
            raw_item_code=raw_item_code,
            semantic_mapping_source=_MAPPING_CONTRACT_VERSION,
        ),
        None,
    )


def _industry_matches(mapping_industry: str, record_industry: str | None) -> bool:
    if mapping_industry == "*":
        return True
    return record_industry == mapping_industry


def _deduplicate_semantic_records(
    records: list[StatementItemRecord],
) -> tuple[list[StatementItemRecord], list[FactorDiagnostic]]:
    grouped: dict[tuple[str, str, str, str, str], list[StatementItemRecord]] = {}
    for record in records:
        key = (
            record.stock_code,
            record.statement_type,
            record.period,
            record.item_code,
            record.report_basis.strip(),
        )
        grouped.setdefault(key, []).append(record)

    output: list[StatementItemRecord] = []
    diagnostics: list[FactorDiagnostic] = []
    for key in sorted(grouped):
        matches = grouped[key]
        content = {
            (
                record.value,
                record.as_of_date,
                record.announced_date,
                record.available_date,
                record.item_name,
                record.raw_item_code or record.item_code,
                record.period_start,
                record.period_end,
                record.period_basis,
                record.value_unit,
                record.value_scale,
            )
            for record in matches
        }
        if len(content) > 1:
            diagnostics.append(
                FactorDiagnostic(
                    code="fundamental_statement.revision_ambiguous",
                    factor_name="fundamental.statement",
                    stock_code=key[0],
                    message=(
                        "semantic statement item has conflicting revisions; "
                        f"statement_type={key[1]}; period={key[2]}; "
                        f"item_code={key[3]}; report_basis={key[4]}"
                    ),
                )
            )
            continue
        output.append(
            min(
                matches,
                key=lambda record: (
                    record.available_date,
                    record.source_version,
                    record.raw_item_code or record.item_code,
                ),
            )
        )
    return output, diagnostics
