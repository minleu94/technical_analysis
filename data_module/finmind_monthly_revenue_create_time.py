"""FinMind 月營收 create_time 候選抓取器。

create_time 代表 FinMind 觀測/入庫時間，不等同官方 MOPS 公告日。本模組只輸出
候選觀測檔與分組檔，不寫入正式 availability mapping 或 SQLite。
"""

from __future__ import annotations

import csv
import ctypes
import ctypes.wintypes
import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen


FINMIND_SOURCE = "finmind.monthly_revenue_create_time"
FINMIND_SOURCE_VERSION_PREFIX = "finmind-taiwan-stock-month-revenue"
FINMIND_MONTHLY_REVENUE_URL = "https://api.finmindtrade.com/api/v4/data"
FINMIND_ROWS_COLUMNS = [
    "stock_code",
    "period",
    "date",
    "revenue_year",
    "revenue_month",
    "revenue",
    "create_time",
    "available_date_candidate",
    "source",
    "source_version",
]
FINMIND_GROUP_COLUMNS = ["create_time", "stock_count", "stock_codes"]


@dataclass(frozen=True)
class FinMindCreateTimeHarvestResult:
    rows: list[dict[str, str]]
    group_rows: list[dict[str, str]]
    state: dict[str, list[str]]
    requested_stock_count: int
    fetched_stock_count: int
    failed_stock_count: int
    row_output: Path | None = None
    group_output: Path | None = None
    state_file: Path | None = None

    def to_markdown(self, sample_size: int = 5) -> str:
        lines = [
            "# FinMind Monthly Revenue Create Time Candidate",
            "",
            f"- requested_stock_count: {self.requested_stock_count}",
            f"- fetched_stock_count: {self.fetched_stock_count}",
            f"- failed_stock_count: {self.failed_stock_count}",
            f"- parsed_rows: {len(self.rows)}",
            f"- create_time_groups: {len(self.group_rows)}",
            "",
            "## Sample Rows",
        ]
        for row in self.rows[:sample_size]:
            lines.append(
                "- "
                + ", ".join(
                    f"{key}={row[key]}"
                    for key in (
                        "stock_code",
                        "period",
                        "create_time",
                        "available_date_candidate",
                        "source_version",
                    )
                )
            )
        if not self.rows:
            lines.append("- none")
        return "\n".join(lines)


def harvest_finmind_monthly_revenue_create_time(
    *,
    stock_codes: tuple[str, ...],
    start_date: str,
    end_date: str,
    token: str,
    fetch_rows: Callable[[str, str, str, str], list[dict]] = None,
    output_dir: Path | None = None,
    state_file: Path | None = None,
    resume: bool = False,
    fetch_date: date | None = None,
    sleep_seconds: float = 0.0,
) -> FinMindCreateTimeHarvestResult:
    fetcher = fetch_rows or fetch_finmind_monthly_revenue_rows
    fetch_date = fetch_date or date.today()
    output_dir = Path(output_dir) if output_dir is not None else None
    state_file = Path(state_file) if state_file is not None else (
        output_dir / "finmind_monthly_revenue_fetch_state.json" if output_dir else None
    )
    state = _load_state(state_file) if resume and state_file is not None else _empty_state()
    completed = set(state["completed_stock_codes"])
    failed = set(state["failed_stock_codes"])
    rows: list[dict[str, str]] = []
    fetched_stock_count = 0
    source_version = f"{FINMIND_SOURCE_VERSION_PREFIX}-{fetch_date.isoformat()}"

    for index, stock_code in enumerate(stock_codes):
        if resume and stock_code in completed:
            continue
        try:
            source_rows = fetcher(stock_code, start_date, end_date, token)
        except Exception:
            failed.add(stock_code)
            state["failed_stock_codes"] = sorted(failed)
            _write_state(state_file, state)
            continue
        fetched_stock_count += 1
        completed.add(stock_code)
        failed.discard(stock_code)
        rows.extend(_normalize_finmind_rows(source_rows, stock_code, source_version))
        state["completed_stock_codes"] = sorted(completed)
        state["failed_stock_codes"] = sorted(failed)
        _write_state(state_file, state)
        if sleep_seconds > 0 and index < len(stock_codes) - 1:
            time.sleep(sleep_seconds)

    rows.sort(key=lambda row: (row["stock_code"], row["period"]))
    group_rows = _build_group_rows(rows)
    row_output = None
    group_output = None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        row_output = output_dir / f"finmind_monthly_revenue_create_time_{fetch_date.isoformat()}.csv"
        group_output = output_dir / f"finmind_create_time_groups_{fetch_date.isoformat()}.csv"
        _write_csv(row_output, FINMIND_ROWS_COLUMNS, rows)
        _write_csv(group_output, FINMIND_GROUP_COLUMNS, group_rows)
    return FinMindCreateTimeHarvestResult(
        rows=rows,
        group_rows=group_rows,
        state=state,
        requested_stock_count=len(stock_codes),
        fetched_stock_count=fetched_stock_count,
        failed_stock_count=len(failed),
        row_output=row_output,
        group_output=group_output,
        state_file=state_file,
    )


def fetch_finmind_monthly_revenue_rows(
    stock_code: str,
    start_date: str,
    end_date: str,
    token: str,
) -> list[dict]:
    query = urlencode(
        {
            "dataset": "TaiwanStockMonthRevenue",
            "data_id": stock_code,
            "start_date": start_date,
            "end_date": end_date,
        }
    )
    request = Request(
        f"{FINMIND_MONTHLY_REVENUE_URL}?{query}",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "technical-analysis-month5/1.0",
        },
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8-sig"))
    if not payload.get("status"):
        raise RuntimeError(str(payload.get("msg") or "FinMind request failed"))
    data = payload.get("data") or []
    if not isinstance(data, list):
        raise RuntimeError("FinMind response data is not a list")
    return data


def load_finmind_token(token_file: Path | None = None) -> str:
    env_token = os.environ.get("FINMIND_TOKEN", "").strip()
    if env_token:
        return env_token
    path = token_file or _default_token_file()
    if not path.exists():
        raise RuntimeError(
            "FinMind token missing; set FINMIND_TOKEN or provide the DPAPI token file."
        )
    return decode_dpapi_hex_token(path.read_text(encoding="utf-8-sig"))


def decode_dpapi_hex_token(
    hex_text: str,
    *,
    unprotect: Callable[[bytes], bytes] | None = None,
) -> str:
    protected = bytes.fromhex("".join(str(hex_text).split()))
    plain = (unprotect or _crypt_unprotect_data)(protected)
    for encoding in ("utf-16le", "utf-8"):
        try:
            token = plain.decode(encoding).strip("\ufeff\x00\r\n\t ")
        except UnicodeDecodeError:
            continue
        if token and "\x00" not in token:
            return token
    return plain.decode("utf-16le", errors="ignore").strip("\ufeff\x00\r\n\t ")


def load_stock_codes_from_raw_monthly_revenue_dir(raw_dir: Path) -> tuple[str, ...]:
    codes = []
    for path in Path(raw_dir).glob("*_monthly_revenue.csv"):
        stock_code = path.name.split("_", maxsplit=1)[0]
        if stock_code.isdigit():
            codes.append(stock_code)
    return tuple(sorted(set(codes)))


def calculate_sleep_seconds(max_requests_per_hour: int) -> float:
    if max_requests_per_hour <= 0:
        return 0.0
    return 3600.0 / max_requests_per_hour


def _normalize_finmind_rows(
    source_rows: Iterable[dict],
    stock_code: str,
    source_version: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for source_row in source_rows:
        date_text = str(source_row.get("date") or "")
        period = _period_from_finmind_row(source_row, date_text)
        create_time = str(source_row.get("create_time") or "").strip()
        rows.append(
            {
                "stock_code": str(source_row.get("stock_id") or stock_code),
                "period": period,
                "date": date_text,
                "revenue_year": str(source_row.get("revenue_year") or ""),
                "revenue_month": str(source_row.get("revenue_month") or ""),
                "revenue": str(source_row.get("revenue") or ""),
                "create_time": create_time,
                "available_date_candidate": _candidate_available_date(create_time),
                "source": FINMIND_SOURCE,
                "source_version": source_version,
            }
        )
    return rows


def _period_from_finmind_row(source_row: dict, date_text: str) -> str:
    year = source_row.get("revenue_year")
    month = source_row.get("revenue_month")
    if year and month:
        return f"{int(year):04d}-{int(month):02d}"
    return date_text[:7]


def _candidate_available_date(create_time: str) -> str:
    if not create_time:
        return ""
    day_text = create_time[:10]
    try:
        observed_day = datetime.fromisoformat(day_text).date()
    except ValueError:
        return ""
    return (observed_day + timedelta(days=1)).isoformat()


def _build_group_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    grouped: dict[str, set[str]] = {}
    for row in rows:
        create_time = row.get("create_time", "")
        if not create_time:
            continue
        grouped.setdefault(create_time, set()).add(row["stock_code"])
    return [
        {
            "create_time": create_time,
            "stock_count": str(len(stock_codes)),
            "stock_codes": ",".join(sorted(stock_codes)),
        }
        for create_time, stock_codes in sorted(grouped.items())
    ]


def _empty_state() -> dict[str, list[str]]:
    return {"completed_stock_codes": [], "failed_stock_codes": []}


def _load_state(path: Path | None) -> dict[str, list[str]]:
    if path is None or not path.exists():
        return _empty_state()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "completed_stock_codes": sorted(payload.get("completed_stock_codes") or []),
        "failed_stock_codes": sorted(payload.get("failed_stock_codes") or []),
    }


def _write_state(path: Path | None, state: dict[str, list[str]]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _default_token_file() -> Path:
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return appdata / "technical_analysis" / "secrets" / "finmind_token.dpapi"


def _crypt_unprotect_data(protected: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("DPAPI token files can only be decrypted on Windows.")

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    in_buffer = ctypes.create_string_buffer(protected)
    in_blob = DATA_BLOB(
        len(protected),
        ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    out_blob = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
