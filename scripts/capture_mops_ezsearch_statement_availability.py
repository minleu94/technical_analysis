"""保存 MOPS EZSearch 季度財報公告事件的研究用 raw evidence。

EZSearch 是獨立的公告時間來源，不能偽裝成 t57 文件 listing。這個工具只
保存官方 JSON 回應與指定公司／期別的精確事件列，供後續候選 builder 在
數值 raw 與公告時間分離的情況下重建 immutable candidate。
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.mops_statement_candidate_adapter import validate_research_output_path


EZSEARCH_URL = "https://mopsov.twse.com.tw/mops/web/ezsearch_query"
EZSEARCH_REFERER = "https://mopsov.twse.com.tw/mops/web/ezsearch"
ITEMS: dict[str, tuple[str, str]] = {
    "F26": ("balance_sheet", "資產負債表"),
    "F27": ("income_statement", "綜合損益表"),
    "F28": ("cash_flows_statement", "現金流量表"),
}
MARKET_NAMES = {"sii": "上市", "otc": "上櫃", "rotc": "興櫃", "pub": "公開發行"}
_REQUEST_RE = re.compile(r"^(?P<stock>\d{4,6}):(?P<market>sii|otc|rotc|pub):(?P<period>\d{4}-Q[1-4])$")
_MAX_REQUESTS = 8
_TAIPEI_ZONE = ZoneInfo("Asia/Taipei")


def _sha256_reference(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _taipei_today() -> date:
    """取得本次執行所採用的台北曆日。"""

    return datetime.now(_TAIPEI_ZONE).date()


def _request_parts(value: str) -> tuple[str, str, int, int]:
    match = _REQUEST_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError("--request must be STOCK:MARKET:YYYY-Qn")
    stock = match.group("stock")
    market = match.group("market")
    year_text, season_text = match.group("period").split("-Q", 1)
    return stock, market, int(year_text), int(season_text)


def _roc_date(value: date) -> str:
    return f"{value.year - 1911:03d}/{value.month:02d}/{value.day:02d}"


def _default_query_start_date(period_year: int, season: int) -> date:
    """季度公告查詢預設從財報期末翌日開始，涵蓋延後公告列。"""

    period_end = date(
        period_year,
        season * 3,
        (31, 30, 30, 31)[season - 1],
    )
    return period_end + timedelta(days=1)


def _resolve_query_window(
    period_year: int,
    season: int,
    *,
    explicit_start: date | None,
    explicit_end: date | None,
) -> tuple[date, date]:
    """在單次執行凍結公告查詢窗口，避免跨日取得不一致的終點。"""

    start_date = explicit_start or _default_query_start_date(period_year, season)
    end_date = explicit_end or _taipei_today()
    if end_date < start_date:
        raise ValueError("end date must not be earlier than start date")
    return start_date, end_date


def _parse_json_response(body: bytes) -> Mapping[str, Any]:
    text = body.decode("utf-8-sig", errors="strict")
    stripped = text.strip()
    if not stripped.startswith("{"):
        raise ValueError("EZSearch response does not start with a JSON object")
    parsed = json.loads(stripped)
    if not isinstance(parsed, Mapping):
        raise ValueError("EZSearch response must be a JSON object")
    return parsed


def _canonical_row_hash(row: Mapping[str, Any]) -> str:
    material = json.dumps(
        {str(key): str(value) for key, value in sorted(row.items())},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_reference(material)


def _query_payload(*, market: str, announcement_item: str, start: date, end: date) -> dict[str, str]:
    return {
        "step": "00",
        "RADIO_CM": "1",
        "TYPEK": market,
        "CO_MARKET": "",
        "CO_ID": "",
        "PRO_ITEM": announcement_item,
        "SUBJECT": "",
        "SDATE": _roc_date(start),
        "EDATE": _roc_date(end),
        "lang": "TW",
        "AN": "",
    }


def _capture_item(
    *,
    output_dir: Path,
    market: str,
    announcement_item: str,
    start: date,
    end: date,
    requests_session: requests.Session,
    timeout_seconds: int,
) -> dict[str, Any]:
    payload = _query_payload(
        market=market,
        announcement_item=announcement_item,
        start=start,
        end=end,
    )
    started_at = _utc_now()
    raw_name = f"ezsearch_{market}_{announcement_item}_{start.isoformat()}_{end.isoformat()}.json"
    raw_path = output_dir / raw_name
    try:
        response = requests_session.post(
            EZSEARCH_URL,
            data=payload,
            headers={
                "Referer": EZSEARCH_REFERER,
                "User-Agent": "technical-analysis-research-readonly/1.0",
            },
            timeout=timeout_seconds,
        )
        received_at = _utc_now()
        body = response.content
        if raw_path.exists():
            raise FileExistsError(raw_path)
        raw_path.write_bytes(body)
        response_record: dict[str, Any] = {
            "announcement_item": announcement_item,
            "statement_type": ITEMS[announcement_item][0],
            "request": {
                "method": "POST",
                "url": EZSEARCH_URL,
                "data": payload,
            },
            "request_started_at": started_at,
            "response_received_at": received_at,
            "raw_file": raw_name,
            "http": {
                "status": response.status_code,
                "reason": response.reason,
                "content_type": response.headers.get("Content-Type"),
                "byte_count": len(body),
                "sha256": _sha256_reference(body),
            },
            "research_only": True,
            "formal_oos_allowed": False,
        }
        if response.status_code != 200:
            response_record["status"] = "http_error"
            return response_record
        try:
            parsed = _parse_json_response(body)
        except (UnicodeError, ValueError, json.JSONDecodeError) as error:
            response_record.update(
                {
                    "status": "invalid_json",
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )
            return response_record
        rows = parsed.get("data")
        if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
            response_record.update(
                {
                    "status": "invalid_data",
                    "error": "EZSearch data must be a list of objects",
                }
            )
            return response_record
        response_record["source_status"] = str(parsed.get("status", ""))
        response_record["response_row_count"] = len(rows)
        response_record["status"] = "success" if parsed.get("status") == "success" else "official_no_data"
        response_record["parsed_rows"] = [
            {str(key): str(value) for key, value in row.items()}
            for row in rows
        ]
        return response_record
    except Exception as error:
        response_record = {
            "announcement_item": announcement_item,
            "statement_type": ITEMS[announcement_item][0],
            "request": {
                "method": "POST",
                "url": EZSEARCH_URL,
                "data": payload,
            },
            "request_started_at": started_at,
            "status": "transport_error",
            "error_type": type(error).__name__,
            "error": str(error),
            "research_only": True,
            "formal_oos_allowed": False,
        }
        return response_record


def _build_stock_evidence(
    *,
    stock_code: str,
    market: str,
    period: str,
    period_end: date,
    item_records: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    matched: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for announcement_item, record in item_records.items():
        base = {
            key: value
            for key, value in record.items()
            if key not in {"parsed_rows"}
        }
        base["raw_response"] = {
            "basename": record.get("raw_file"),
            "sha256": record.get("http", {}).get("sha256") if isinstance(record.get("http"), Mapping) else None,
            "byte_count": record.get("http", {}).get("byte_count") if isinstance(record.get("http"), Mapping) else None,
            "artifact_kind": "http_response_bytes",
            "raw_custody": True,
        }
        query_status = str(record.get("status", "")).strip()
        if query_status != "success":
            # Transport／HTTP／解碼錯誤不能被誤標成「查詢成功但無匹配」。
            reason = query_status or "missing_query_status"
            errors.append({"announcement_item": announcement_item, "reason": reason})
            base["status"] = reason
            base["matched_row"] = None
            matched.append(base)
            continue
        rows = record.get("parsed_rows")
        row_candidates: list[Mapping[str, Any]] = []
        if isinstance(rows, list):
            row_candidates = [
                row
                for row in rows
                if isinstance(row, Mapping)
                and str(row.get("COMPANY_ID", "")).strip() == stock_code
                and str(row.get("AN_CODE", "")).strip() == announcement_item
                and str(row.get("SUBJECT", "")).replace(" ", "") == f"{period_end.year - 1911}年第{period[-1]}季{ITEMS[announcement_item][1]}"
                and str(row.get("TYPEK", "")).strip() == MARKET_NAMES[market]
            ]
        if len(row_candidates) != 1:
            reason = "no_matching_company_period_row" if not row_candidates else "duplicate_company_period_rows"
            errors.append({"announcement_item": announcement_item, "reason": reason})
            base["status"] = reason
            base["matched_row"] = None
            matched.append(base)
            continue
        selected = {str(key): str(value) for key, value in row_candidates[0].items()}
        base["status"] = "matched"
        base["matched_row"] = selected
        base["matched_row_sha256"] = _canonical_row_hash(selected)
        matched.append(base)
    return {
        "schema_version": "v4-mops-ezsearch-statement-availability-observation.v1",
        "stock_code": stock_code,
        "market": market,
        "period": period,
        "period_end": period_end.isoformat(),
        "source_url": EZSEARCH_URL,
        "source_id": "mops.ezsearch.statement_publication",
        "source_version": "mops-ezsearch-statement-publication.v1",
        "records": matched,
        "matched_record_count": sum(1 for record in matched if record.get("status") == "matched"),
        "error_count": len(errors),
        "errors": errors,
        "research_only": True,
        "formal_oos_allowed": False,
        "formal_credit_authorized": False,
        "pit_credit": "none",
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", action="append", required=True, metavar="STOCK:MARKET:YYYY-Qn")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=None,
        help="公告查詢起日；省略時從指定季度期末翌日開始，避免漏掉延後公告",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None,
        help="公告查詢終日；省略時凍結為本次執行的 Asia/Taipei 曆日",
    )
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args(argv)
    if len(args.request) > _MAX_REQUESTS:
        raise ValueError("request count exceeds the explicit batch limit")
    if not 1 <= args.timeout_seconds <= 60:
        raise ValueError("timeout seconds must be between 1 and 60")
    requests_list = [_request_parts(value) for value in args.request]
    if len(set(requests_list)) != len(requests_list):
        raise ValueError("duplicate company/market/period request")
    period_values = {(year, season) for _, _, year, season in requests_list}
    if len(period_values) != 1:
        raise ValueError("all requests in one EZSearch capture must use one period")
    period_year, season = next(iter(period_values))
    period = f"{period_year:04d}-Q{season}"
    period_end = date(period_year, season * 3, (31, 30, 30, 31)[season - 1])
    start_date, end_date = _resolve_query_window(
        period_year,
        season,
        explicit_start=args.start_date,
        explicit_end=args.end_date,
    )
    output_dir = Path(args.output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = Path.cwd() / output_dir
    output_dir = output_dir.resolve(strict=False)
    validate_research_output_path(output_dir, allow_existing=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    stocks = {stock for stock, _, _, _ in requests_list}
    markets = {market for _, market, _, _ in requests_list}
    if len(markets) != 1:
        raise ValueError("one EZSearch capture must use one market")
    market = next(iter(markets))
    item_records: dict[str, dict[str, Any]] = {}
    with requests.Session() as session:
        for announcement_item in ITEMS:
            item_records[announcement_item] = _capture_item(
                output_dir=output_dir,
                market=market,
                announcement_item=announcement_item,
                start=start_date,
                end=end_date,
                requests_session=session,
                timeout_seconds=args.timeout_seconds,
            )

    evidence_paths: list[str] = []
    for stock_code, stock_market, _, _ in requests_list:
        evidence = _build_stock_evidence(
            stock_code=stock_code,
            market=stock_market,
            period=period,
            period_end=period_end,
            item_records=item_records,
        )
        evidence_path = output_dir / f"ezsearch-evidence-{stock_code}.json"
        if evidence_path.exists():
            raise FileExistsError(evidence_path)
        evidence_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        evidence_paths.append(str(evidence_path))

    manifest = {
        "schema_version": "v4-mops-ezsearch-availability-capture-manifest.v1",
        "captured_at": _utc_now(),
        "request_count": len(requests_list),
        "requests": [
            {
                "stock_code": stock_code,
                "market": stock_market,
                "period": period,
                "evidence": str(output_dir / f"ezsearch-evidence-{stock_code}.json"),
            }
            for stock_code, stock_market, _, _ in requests_list
        ],
        "query_window": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "source_url": EZSEARCH_URL,
        "raw_files": {
            path.name: _sha256_reference(path.read_bytes())
            for path in sorted(output_dir.glob("ezsearch_*.json"))
        },
        "evidence_files": {
            Path(path).name: _sha256_reference(Path(path).read_bytes())
            for path in sorted(evidence_paths)
        },
        "research_only": True,
        "formal_oos_allowed": False,
    }
    manifest_path = output_dir / "capture-manifest.json"
    if manifest_path.exists():
        raise FileExistsError(manifest_path)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
