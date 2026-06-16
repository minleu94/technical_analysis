"""Governed company registry builder for companies.csv."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from decision_module.factors.factor_dtos import FactorDiagnostic


COMPANY_REGISTRY_COLUMNS = (
    "industry_category",
    "stock_id",
    "stock_name",
    "type",
    "date",
    "download_time",
)

INDUSTRY_CODE_TO_CATEGORY = {
    "01": "水泥工業",
    "02": "食品工業",
    "03": "塑膠工業",
    "04": "紡織纖維",
    "05": "電機機械",
    "06": "電器電纜",
    "08": "玻璃陶瓷",
    "09": "造紙工業",
    "10": "鋼鐵工業",
    "11": "橡膠工業",
    "12": "汽車工業",
    "14": "建材營造",
    "15": "航運業",
    "16": "觀光餐旅",
    "17": "金融保險",
    "18": "貿易百貨",
    "20": "其他",
    "21": "化學生技醫療",
    "22": "生技醫療業",
    "23": "油電燃氣業",
    "24": "半導體業",
    "25": "電腦及週邊設備業",
    "26": "光電業",
    "27": "通信網路業",
    "28": "電子零組件業",
    "29": "電子通路業",
    "30": "資訊服務業",
    "31": "其他電子業",
    "32": "文化創意業",
    "33": "農業科技",
    "34": "電子商務",
    "35": "綠能環保",
    "36": "數位雲端",
    "37": "運動休閒",
    "38": "居家生活",
    "80": "管理股票",
    "91": "存託憑證",
}


@dataclass(frozen=True)
class CompanyRegistryRow:
    industry_category: str
    stock_id: str
    stock_name: str
    type: str
    date: str
    download_time: str

    def to_csv_row(self) -> dict[str, str]:
        return {
            "industry_category": self.industry_category,
            "stock_id": self.stock_id,
            "stock_name": self.stock_name,
            "type": self.type,
            "date": self.date,
            "download_time": self.download_time,
        }


@dataclass(frozen=True)
class CompanyRegistryBuildResult:
    rows: tuple[CompanyRegistryRow, ...]
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", tuple(self.rows))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    @property
    def ready_for_apply(self) -> bool:
        return bool(self.rows) and not self.diagnostics

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# Company Registry Build Result",
                "",
                f"- ready_for_apply: {str(self.ready_for_apply).lower()}",
                f"- row_count: {len(self.rows)}",
                f"- diagnostics: {len(self.diagnostics)}",
            ]
        )


def build_company_registry_rows(
    *,
    twse_rows: Iterable[Mapping[str, object]],
    tpex_rows: Iterable[Mapping[str, object]],
    emerging_rows: Iterable[Mapping[str, object]],
    download_time: str | None = None,
) -> CompanyRegistryBuildResult:
    download_time = download_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows: list[CompanyRegistryRow] = []
    diagnostics: list[FactorDiagnostic] = []

    for market, source_rows in (
        ("twse", twse_rows),
        ("tpex", tpex_rows),
        ("emerging", emerging_rows),
    ):
        for source_row in source_rows:
            record = _normalize_company_row(
                source_row,
                market=market,
                download_time=download_time,
            )
            if isinstance(record, FactorDiagnostic):
                diagnostics.append(record)
            else:
                rows.append(record)

    unique_rows = _deduplicate_rows(rows)
    market_order = {"twse": 0, "tpex": 1, "emerging": 2}
    return CompanyRegistryBuildResult(
        rows=tuple(sorted(unique_rows, key=lambda row: (market_order[row.type], row.stock_id))),
        diagnostics=tuple(diagnostics),
    )


def write_company_registry_csv(
    output_file: Path,
    rows: Iterable[CompanyRegistryRow],
) -> None:
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(COMPANY_REGISTRY_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_csv_row())


def _normalize_company_row(
    source_row: Mapping[str, object],
    *,
    market: str,
    download_time: str,
) -> CompanyRegistryRow | FactorDiagnostic:
    stock_code = _first(source_row, "公司代號", "SecuritiesCompanyCode")
    stock_name = _first(source_row, "公司簡稱", "CompanyAbbreviation", "公司名稱", "CompanyName")
    industry_code = _first(source_row, "產業別", "SecuritiesIndustryCode")
    source_date = _first(source_row, "出表日期", "Date")

    if not stock_code or not stock_name or not industry_code:
        return FactorDiagnostic(
            code="company_registry.invalid_row",
            factor_name="company_registry",
            stock_code=stock_code,
            message="official company registry row is missing stock code, name, or industry code",
        )

    industry_category = INDUSTRY_CODE_TO_CATEGORY.get(industry_code)
    if industry_category is None:
        return FactorDiagnostic(
            code="company_registry.unknown_industry_code",
            factor_name="company_registry",
            stock_code=stock_code,
            message=f"unknown official industry code: {industry_code}",
        )

    return CompanyRegistryRow(
        industry_category=industry_category,
        stock_id=stock_code,
        stock_name=stock_name,
        type=market,
        date=_normalize_source_date(source_date),
        download_time=download_time,
    )


def _deduplicate_rows(rows: Iterable[CompanyRegistryRow]) -> tuple[CompanyRegistryRow, ...]:
    selected: dict[tuple[str, str], CompanyRegistryRow] = {}
    for row in rows:
        key = (row.stock_id, row.type)
        if key not in selected or (row.date, row.download_time) > (
            selected[key].date,
            selected[key].download_time,
        ):
            selected[key] = row
    return tuple(selected.values())


def _first(source_row: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = source_row.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def _normalize_source_date(value: str) -> str:
    value = value.strip()
    if len(value) == 7 and value.isdigit():
        year = int(value[:3]) + 1911
        return f"{year:04d}-{value[3:5]}-{value[5:7]}"
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    return value
