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
        fetch_rows: Callable[[], list[Mapping[str, Any]]] | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.fetch_rows = fetch_rows or self._fetch_official_rows

    def update_for_date(self, date_value: str) -> TpexDailyPriceUpdateResult:
        requested_date = _date_key(date_value)
        try:
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

    def _fetch_official_rows(self) -> list[Mapping[str, Any]]:
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = requests.get(
                    TPEX_DAILY_CLOSE_URL,
                    headers={"User-Agent": "Mozilla/5.0"},
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

