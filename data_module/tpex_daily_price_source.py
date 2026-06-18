"""TPEX daily close quote source for daily price update workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable, Mapping, Any

import pandas as pd
import requests

from data_module.tpex_daily_price_backfill import normalize_tpex_daily_price_rows


TPEX_DAILY_CLOSE_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TPEX_AFTER_TRADING_OTC_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"


@dataclass(frozen=True)
class TpexDailyPriceUpdateResult:
    success: bool
    message: str
    requested_date: str
    source_date: str | None
    row_count: int
    skipped_count: int
    diagnostic_count: int
    output_file: Path | None = None


class TpexDailyPriceSource:
    """Fetch and persist official TPEX daily close quotes as daily price CSV files."""

    def __init__(
        self,
        output_dir: Path,
        fetch_rows: Callable[..., list[Mapping[str, Any]]] | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.fetch_rows = fetch_rows or self._fetch_official_rows

    def update_for_date(self, date_value: str) -> TpexDailyPriceUpdateResult:
        requested_date = _date_key(date_value)
        try:
            try:
                source_rows = self.fetch_rows(requested_date)
            except TypeError:
                source_rows = self.fetch_rows()
            normalized = normalize_tpex_daily_price_rows(
                source_rows,
                fallback_date=requested_date,
                strict=False,
            )
        except Exception as exc:
            return TpexDailyPriceUpdateResult(
                success=False,
                message=f"TPEX daily close quote fetch failed: {exc}",
                requested_date=requested_date,
                source_date=None,
                row_count=0,
                skipped_count=0,
                diagnostic_count=1,
            )

        source_dates = sorted({str(row.get("日期")) for row in normalized.rows if row.get("日期")})
        source_date = source_dates[-1] if source_dates else None
        rows_for_date = [row for row in normalized.rows if row.get("日期") == requested_date]
        skipped_count = max(len(source_rows) - len(normalized.rows), 0)

        if not rows_for_date:
            return TpexDailyPriceUpdateResult(
                success=False,
                message=(
                    f"TPEX daily close response does not contain requested date "
                    f"{requested_date}; source_date={source_date or 'unknown'}"
                ),
                requested_date=requested_date,
                source_date=source_date,
                row_count=0,
                skipped_count=skipped_count,
                diagnostic_count=len(normalized.diagnostics),
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_file = self.output_dir / f"{requested_date}.csv"
        pd.DataFrame(rows_for_date).to_csv(output_file, index=False, encoding="utf-8-sig")
        return TpexDailyPriceUpdateResult(
            success=True,
            message=(
                f"TPEX daily close quotes saved: {len(rows_for_date)} rows, "
                f"skipped {skipped_count} rows"
            ),
            requested_date=requested_date,
            source_date=source_date,
            row_count=len(rows_for_date),
            skipped_count=skipped_count,
            diagnostic_count=len(normalized.diagnostics),
            output_file=output_file,
        )

    def _fetch_official_rows(self, date_value: str | None = None) -> list[Mapping[str, Any]]:
        last_exc: Exception | None = None
        date_key = _date_key(date_value) if date_value else None
        params = None
        url = TPEX_DAILY_CLOSE_URL
        if date_key:
            url = TPEX_AFTER_TRADING_OTC_URL
            params = {
                "date": f"{date_key[:4]}/{date_key[4:6]}/{date_key[6:8]}",
                "type": "EW",
                "response": "json",
            }

        for attempt in range(1, 4):
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/mi-pricing.html",
                    },
                    timeout=(10, 90),
                )
                response.raise_for_status()
                break
            except (
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.HTTPError,
            ) as exc:
                last_exc = exc
                response_status = getattr(getattr(exc, "response", None), "status_code", None)
                if response_status is None:
                    response_status = getattr(locals().get("response", None), "status_code", None)
                transient_http_error = isinstance(exc, requests.exceptions.HTTPError) and (
                    response_status is None or int(response_status) >= 500
                )
                if isinstance(exc, requests.exceptions.HTTPError) and not transient_http_error:
                    raise
                if attempt >= 3:
                    raise
                time.sleep(1.5 * attempt)
        else:
            raise RuntimeError(f"TPEX daily close request failed: {last_exc}")

        data = response.json()
        if date_key and isinstance(data, dict):
            return _rows_from_after_trading_response(data, fallback_date=date_key)
        if not isinstance(data, list):
            raise ValueError("TPEX daily close response is not a list")
        return data


def _date_key(value: str) -> str:
    text = str(value).strip().replace("-", "").replace("/", "")
    if len(text) == 8 and text.isdigit():
        return text
    if len(text) == 7 and text.isdigit():
        year = int(text[:3]) + 1911
        return f"{year:04d}{text[3:5]}{text[5:7]}"
    raise ValueError(f"Unsupported TPEX date format: {value}")


def _rows_from_after_trading_response(
    payload: Mapping[str, Any],
    *,
    fallback_date: str,
) -> list[Mapping[str, Any]]:
    tables = payload.get("tables")
    if not isinstance(tables, list) or not tables:
        raise ValueError("TPEX afterTrading response has no tables")

    table = tables[0]
    if not isinstance(table, Mapping):
        raise ValueError("TPEX afterTrading table is invalid")

    fields = table.get("fields")
    data_rows = table.get("data")
    if not isinstance(fields, list) or not isinstance(data_rows, list):
        raise ValueError("TPEX afterTrading table is missing fields/data")

    source_date = _date_key(str(table.get("date") or fallback_date))
    field_names = [str(field) for field in fields]
    rows: list[Mapping[str, Any]] = []
    for values in data_rows:
        if not isinstance(values, list):
            continue
        raw = {field_names[idx]: values[idx] for idx in range(min(len(field_names), len(values)))}
        rows.append(
            {
                "Date": source_date,
                "SecuritiesCompanyCode": _first_field(raw, "代號"),
                "CompanyName": _first_field(raw, "名稱"),
                "Close": _first_field(raw, "收盤"),
                "Change": _first_field(raw, "漲跌"),
                "Open": _first_field(raw, "開盤"),
                "High": _first_field(raw, "最高"),
                "Low": _first_field(raw, "最低"),
                "TradingShares": _first_field(raw, "成交股數"),
                "TransactionAmount": _first_field(raw, "成交金額"),
                "TransactionNumber": _first_field(raw, "成交筆數"),
                "LatestBidPrice": _first_field(raw, "最後買價"),
                "LastBestBidVolume": _first_field(raw, "最後買量"),
                "LatesAskPrice": _first_field(raw, "最後賣價"),
                "LastBestAskVolume": _first_field(raw, "最後賣量"),
                "Capitals": _first_field(raw, "發行股數"),
            }
        )
    return rows


def _first_field(row: Mapping[str, Any], text: str) -> Any:
    for key, value in row.items():
        normalized_key = str(key).replace(" ", "").replace("<br>", "")
        if text in normalized_key:
            return value
    return ""
