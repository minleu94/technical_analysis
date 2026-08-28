import sys
import os
import json
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import logging
from typing import Callable, Optional, Sequence

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_module.config import TWStockConfig
from data_module.db_manager import DBManager
from data_module.p0_candidate_repository import validate_candidate_working_copy_path
from data_module.official_phase3c_fetcher import (
    fetch_institutional_flows,
    fetch_credit_transactions,
    fetch_tdcc_shareholding,
    safe_request,
)
from data_module.p0_official_source_parsers import (
    OfficialParserResult,
    RawFetchEnvelope,
    parse_tdcc_shareholding,
    parse_tpex_credit_openapi,
    parse_tpex_institutional_openapi,
    parse_twse_credit,
    parse_twse_disposition,
    parse_twse_ex_dividend,
    parse_twse_full_delivery,
    parse_twse_halt_resume,
    parse_twse_institutional,
    parse_twse_periodic_call_auction,
    parse_twse_reduction,
    parse_twse_limit_lock,
    parse_monthly_revenue_open_data,
)
from data_module.phase3c_backfill_runner import (
    APPLY_CONFIRM_TOKEN,
    Phase3CBackfillRunner,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# Keep only bounded, non-secret response metadata in candidate diagnostics.
# HTTP headers are useful for an owner to reconcile transport behaviour, but
# they are never publication/available-time evidence and must not be promoted
# into a PIT timestamp by any downstream inspector.
_HTTP_EVIDENCE_HEADERS: tuple[tuple[str, str], ...] = (
    ("http_date", "Date"),
    ("last_modified", "Last-Modified"),
    ("etag", "ETag"),
    ("content_type", "Content-Type"),
)
_MAX_HTTP_EVIDENCE_VALUE_LENGTH = 512


OFFICIAL_PROBE_ROUTE_IDS: dict[str, str] = {
    "twse:T86": "twse.T86",
    "twse:MI_MARGN": "twse.MI_MARGN",
    "tdcc:1-5": "tdcc.legacy_1-5_csv",
    "twse:announcement:punish": "twse.announcement.punish",
    "twse:exchangeReport:TWT85U": "twse.TWT85U",
    "twse:exchangeReport:TWTAWU": "twse.TWTAWU",
    "twse:exchangeReport:TWT49U": "twse.TWT49U",
    "twse:exchangeReport:TWTAUU": "twse.TWTAUU",
    "twse:opendata:t187ap05_L": "twse.openapi.t187ap05_L",
    "tpex:openapi:mopsfin_t187ap05_O": "tpex.openapi.mopsfin_t187ap05_O",
    "tpex:openapi:tpex_3insti_daily_trading": "tpex.tpex_3insti_daily_trading",
    "tpex:openapi:tpex_mainboard_margin_balance": "tpex.tpex_mainboard_margin_balance",
    "twse:exchangeReport:TWT84U": "twse.TWT84U",
}


OFFICIAL_PROBE_FALLBACKS: dict[
    str,
    tuple[
        str,
        str,
        str,
        str,
        dict[str, str],
        Callable[[RawFetchEnvelope], OfficialParserResult],
    ],
] = {
    "twse_institutional": (
        "tpex-3insti-openapi.v1",
        "tpex:openapi:tpex_3insti_daily_trading",
        "tpex.tpex_3insti_daily_trading",
        "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading",
        {},
        parse_tpex_institutional_openapi,
    ),
    "twse_credit": (
        "tpex-mainboard-margin-openapi.v1",
        "tpex:openapi:tpex_mainboard_margin_balance",
        "tpex.tpex_mainboard_margin_balance",
        "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance",
        {},
        parse_tpex_credit_openapi,
    ),
    "tdcc_shareholding": (
        "tdcc-openapi-1-5.v1",
        "tdcc:openapi:1-5",
        "tdcc.openapi_1-5",
        "https://openapi.tdcc.com.tw/v1/opendata/1-5",
        {},
        parse_tdcc_shareholding,
    ),
    "twse_monthly_revenue": (
        "mopsfin-t187ap05_L-csv.v1",
        "mopsfin:csv:t187ap05_L",
        "mopsfin.csv.t187ap05_L",
        "https://mopsfin.twse.com.tw/opendata/t187ap05_L.csv",
        {},
        parse_monthly_revenue_open_data,
    ),
    "tpex_monthly_revenue": (
        "mopsfin-t187ap05_O-csv.v1",
        "mopsfin:csv:t187ap05_O",
        "mopsfin.csv.t187ap05_O",
        "https://mopsfin.twse.com.tw/opendata/t187ap05_O.csv",
        {},
        parse_monthly_revenue_open_data,
    ),
}


def run_bounded_official_probe(probe_date: date) -> dict:
    """對三個官方端點做單日、唯讀、無落盤 probe，僅回報工程 diagnostics。"""
    date_ce = probe_date.strftime("%Y%m%d")
    event_start_ce = (probe_date - timedelta(days=35)).strftime("%Y%m%d")
    probe_requests: tuple[
        tuple[
            str,
            str,
            str,
            str,
            dict[str, str],
            Callable[[RawFetchEnvelope], OfficialParserResult],
        ],
        ...,
    ] = (
        (
            "twse_institutional",
            "twse-T86.v1",
            "twse:T86",
            "https://www.twse.com.tw/fund/T86",
            {"response": "json", "date": date_ce, "selectType": "ALL"},
            parse_twse_institutional,
        ),
        (
            "twse_credit",
            "twse-MI_MARGN.v1",
            "twse:MI_MARGN",
            "https://www.twse.com.tw/exchangeReport/MI_MARGN",
            {"response": "json", "date": date_ce, "selectType": "ALL"},
            parse_twse_credit,
        ),
        (
            "tdcc_shareholding",
            "tdcc-1-5.v1",
            "tdcc:1-5",
            "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5",
            {},
            parse_tdcc_shareholding,
        ),
        (
            "twse_disposition",
            "twse-punish.v1",
            "twse:announcement:punish",
            "https://www.twse.com.tw/announcement/punish",
            {"response": "json", "startDate": date_ce, "endDate": date_ce},
            parse_twse_disposition,
        ),
        (
            "twse_periodic_call_auction",
            "twse-punish.v1",
            "twse:announcement:punish",
            "https://www.twse.com.tw/announcement/punish",
            {"response": "json", "startDate": date_ce, "endDate": date_ce},
            parse_twse_periodic_call_auction,
        ),
        (
            "twse_full_delivery",
            "twse-TWT85U.v1",
            "twse:exchangeReport:TWT85U",
            "https://www.twse.com.tw/exchangeReport/TWT85U",
            {"response": "json", "date": date_ce},
            parse_twse_full_delivery,
        ),
        (
            "twse_halt_resume",
            "twse-TWTAWU.v1",
            "twse:exchangeReport:TWTAWU",
            "https://www.twse.com.tw/exchangeReport/TWTAWU",
            {"response": "json", "date": date_ce},
            parse_twse_halt_resume,
        ),
        (
            "twse_ex_dividend",
            "twse-TWT49U.v1",
            "twse:exchangeReport:TWT49U",
            "https://www.twse.com.tw/exchangeReport/TWT49U",
            {"response": "json", "startDate": event_start_ce, "endDate": date_ce},
            parse_twse_ex_dividend,
        ),
        (
            "twse_reduction",
            "twse-TWTAUU.v1",
            "twse:exchangeReport:TWTAUU",
            "https://www.twse.com.tw/exchangeReport/TWTAUU",
            {"response": "json", "startDate": event_start_ce, "endDate": date_ce},
            parse_twse_reduction,
        ),
        ("twse_monthly_revenue", "twse-t187ap05_L.v1", "twse:opendata:t187ap05_L", "https://openapi.twse.com.tw/v1/opendata/t187ap05_L", {}, parse_monthly_revenue_open_data),
        ("tpex_monthly_revenue", "tpex-mopsfin_t187ap05_O.v1", "tpex:openapi:mopsfin_t187ap05_O", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O", {}, parse_monthly_revenue_open_data),
        ("twse_limit_lock", "twse-TWT84U.v1", "twse:exchangeReport:TWT84U", "https://www.twse.com.tw/exchangeReport/TWT84U", {"response": "json", "date": date_ce, "selectType": "ALLBUT0999"}, parse_twse_limit_lock),
    )
    diagnostics: list[dict] = []
    for source_id, source_version, endpoint_id, url, params, parser in probe_requests:
        fetched_at = datetime.now(timezone.utc)
        primary_endpoint_id = endpoint_id
        primary_route_id = OFFICIAL_PROBE_ROUTE_IDS[endpoint_id]
        acquisition_route_id = primary_route_id
        fallback_evidence: dict[str, object] = {"fallback_used": False}
        try:
            response = safe_request(
                url,
                params or None,
                timeout_seconds=8,
                max_attempts=1,
            )
            payload = bytes(response.content)
        except Exception as primary_exc:
            fallback = OFFICIAL_PROBE_FALLBACKS.get(source_id)
            if fallback is None:
                diagnostics.append(
                    _network_failure_diagnostic(
                        source_id=source_id,
                        endpoint_id=endpoint_id,
                        acquisition_route_id=acquisition_route_id,
                        fetched_at=fetched_at,
                        primary_exc=primary_exc,
                    )
                )
                continue
            (
                source_version,
                endpoint_id,
                acquisition_route_id,
                url,
                params,
                parser,
            ) = fallback
            try:
                response = safe_request(
                    url,
                    params or None,
                    timeout_seconds=8,
                    max_attempts=1,
                )
                payload = bytes(response.content)
                fallback_evidence = {
                    "fallback_used": True,
                    "fallback_from_endpoint_id": primary_endpoint_id,
                    "fallback_from_acquisition_route_id": primary_route_id,
                    "primary_error_type": type(primary_exc).__name__,
                    "primary_error": str(primary_exc),
                }
            except Exception as fallback_exc:
                diagnostics.append(
                    _network_failure_diagnostic(
                        source_id=source_id,
                        endpoint_id=endpoint_id,
                        acquisition_route_id=acquisition_route_id,
                        fetched_at=fetched_at,
                        primary_exc=primary_exc,
                        fallback_exc=fallback_exc,
                        fallback_from_endpoint_id=primary_endpoint_id,
                        fallback_from_acquisition_route_id=primary_route_id,
                    )
                )
                continue

        envelope = RawFetchEnvelope(
            source_id=source_id,
            source_version=source_version,
            endpoint_id=endpoint_id,
            request_parameters=params,
            fetched_at=fetched_at,
            http_status=int(response.status_code),
            http_headers=dict(response.headers),
            payload=payload,
        )
        raw_evidence = {
            "source_id": source_id,
            "endpoint_id": endpoint_id,
            "acquisition_route_id": acquisition_route_id,
            **fallback_evidence,
            "network_status": "reachable",
            "http_status": int(response.status_code),
            "payload_sha256": sha256(payload).hexdigest(),
            "payload_size_bytes": len(payload),
            "fetched_at": fetched_at.isoformat(),
        }
        raw_evidence.update(_capture_http_evidence(response))
        official_no_data = _official_no_data_status(payload)
        fallback_result: OfficialParserResult | None = None
        if official_no_data is not None:
            fallback = OFFICIAL_PROBE_FALLBACKS.get(source_id)
            fallback_attempt: dict[str, object] = {}
            if fallback is not None and not bool(fallback_evidence["fallback_used"]):
                (
                    fallback_source_version,
                    fallback_endpoint_id,
                    fallback_route_id,
                    fallback_url,
                    fallback_params,
                    fallback_parser,
                ) = fallback
                fallback_attempt = {
                    "fallback_attempted": True,
                    "fallback_endpoint_id": fallback_endpoint_id,
                    "fallback_acquisition_route_id": fallback_route_id,
                    "fallback_from_endpoint_id": primary_endpoint_id,
                    "fallback_from_acquisition_route_id": primary_route_id,
                }
                fallback_response = None
                try:
                    fallback_response = safe_request(
                        fallback_url,
                        fallback_params or None,
                        timeout_seconds=8,
                        max_attempts=1,
                    )
                    fallback_payload = bytes(fallback_response.content)
                    fallback_attempt.update(
                        {
                            "fallback_http_status": int(fallback_response.status_code),
                            "fallback_payload_sha256": sha256(fallback_payload).hexdigest(),
                            "fallback_payload_size_bytes": len(fallback_payload),
                            **{
                                f"fallback_{key}": value
                                for key, value in _capture_http_evidence(fallback_response).items()
                            },
                        }
                    )
                    fallback_no_data = _official_no_data_status(fallback_payload)
                    if fallback_no_data is not None:
                        fallback_attempt.update(
                            {
                                "fallback_probe_outcome": "official_no_data",
                                "fallback_official_status": fallback_no_data,
                            }
                        )
                    else:
                        fallback_envelope = RawFetchEnvelope(
                            source_id=source_id,
                            source_version=fallback_source_version,
                            endpoint_id=fallback_endpoint_id,
                            request_parameters=fallback_params,
                            fetched_at=fetched_at,
                            http_status=int(fallback_response.status_code),
                            http_headers=dict(fallback_response.headers),
                            payload=fallback_payload,
                        )
                        candidate_result = fallback_parser(fallback_envelope)
                        candidate_dates = {
                            observation.observation_date
                            for observation in candidate_result.accepted
                        }
                        requested_date = probe_date.isoformat()
                        if source_id in {"twse_institutional", "twse_credit"} and (
                            not candidate_dates or candidate_dates != {requested_date}
                        ):
                            fallback_attempt.update(
                                {
                                    "fallback_probe_outcome": "date_mismatch",
                                    "fallback_observation_dates": sorted(candidate_dates),
                                    "fallback_requested_date": requested_date,
                                }
                            )
                        elif not candidate_result.accepted:
                            fallback_attempt.update(
                                {
                                    "fallback_probe_outcome": "no_accepted_rows",
                                    "fallback_quarantine_reasons": sorted(
                                        {
                                            record.reason_code
                                            for record in candidate_result.quarantine
                                        }
                                    ),
                                }
                            )
                        else:
                            response = fallback_response
                            payload = fallback_payload
                            source_version = fallback_source_version
                            endpoint_id = fallback_endpoint_id
                            acquisition_route_id = fallback_route_id
                            params = fallback_params
                            parser = fallback_parser
                            fallback_evidence = {
                                "fallback_used": True,
                                "fallback_from_endpoint_id": primary_endpoint_id,
                                "fallback_from_acquisition_route_id": primary_route_id,
                                "primary_official_status": official_no_data,
                            }
                            envelope = fallback_envelope
                            raw_evidence = {
                                "source_id": source_id,
                                "endpoint_id": endpoint_id,
                                "acquisition_route_id": acquisition_route_id,
                                **fallback_evidence,
                                "network_status": "reachable",
                                "http_status": int(response.status_code),
                                "payload_sha256": sha256(payload).hexdigest(),
                                "payload_size_bytes": len(payload),
                                "fetched_at": fetched_at.isoformat(),
                            }
                            raw_evidence.update(_capture_http_evidence(response))
                            fallback_result = candidate_result
                except Exception as fallback_exc:
                    fallback_failure_kind = (
                        "network_error" if fallback_response is None else "schema_mismatch"
                    )
                    fallback_attempt.update(
                        {
                            "fallback_probe_outcome": fallback_failure_kind,
                            "fallback_error_type": type(fallback_exc).__name__,
                            "fallback_error": str(fallback_exc),
                        }
                    )
            if fallback_result is None:
                no_data_diagnostic = {
                    **raw_evidence,
                    "probe_outcome": "official_no_data",
                    "availability_status": "official_no_data",
                    "official_status": official_no_data,
                    "schema_status": "no_data",
                    "timestamp_evidence": "unavailable",
                    "raw_row_count": 0,
                    "accepted_row_count": 0,
                    "duplicate_row_count": 0,
                    "quarantine_row_count": 0,
                    "blocked_row_count": 0,
                    "quarantine_reasons": [],
                }
                no_data_diagnostic.update(fallback_attempt)
                diagnostics.append(no_data_diagnostic)
                continue
        try:
            result = fallback_result if fallback_result is not None else parser(envelope)
            if bool(fallback_evidence["fallback_used"]) and source_id in {
                "twse_institutional",
                "twse_credit",
            }:
                fallback_dates = {
                    observation.observation_date for observation in result.accepted
                }
                requested_date = probe_date.isoformat()
                if not result.accepted or fallback_dates != {requested_date}:
                    raise ValueError(
                        "fallback observation date mismatch: "
                        f"expected {requested_date}, got {sorted(fallback_dates)}"
                    )
            evidence_kinds = {
                row.availability_evidence_kind for row in result.accepted
            }
            timestamp_evidence = (
                next(iter(evidence_kinds))
                if len(evidence_kinds) == 1
                else "mixed_or_unavailable"
            )
            diagnostics.append(
                {
                    **raw_evidence,
                    "probe_outcome": "observed",
                    "availability_status": "observed",
                    "schema_status": "matched",
                    "timestamp_evidence": timestamp_evidence,
                    "raw_row_count": result.raw_row_count,
                    "accepted_row_count": result.accepted_row_count,
                    "duplicate_row_count": result.duplicate_row_count,
                    "quarantine_row_count": result.quarantine_row_count,
                    "blocked_row_count": result.blocked_row_count,
                    "quarantine_reasons": sorted(
                        {record.reason_code for record in result.quarantine}
                    ),
                }
            )
        except Exception as exc:
            diagnostics.append(
                {
                    **raw_evidence,
                    "probe_outcome": "schema_mismatch",
                    "availability_status": "schema_mismatch",
                    "schema_status": "mismatch",
                    "timestamp_evidence": "unavailable",
                    "raw_row_count": 0,
                    "accepted_row_count": 0,
                    "duplicate_row_count": 0,
                    "quarantine_row_count": 0,
                    "blocked_row_count": 0,
                    "quarantine_reasons": [],
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
    return {
        "probe_date": probe_date.isoformat(),
        "probe_mode": "bounded_official_read_only",
        "sources": diagnostics,
        "license_accepted": False,
        "source_accepted": False,
        "downstream_eligibility": "none",
        "production_scheduler_allowed": False,
        "human_decision": "requires_human_acceptance",
    }


def _network_failure_diagnostic(
    *,
    source_id: str,
    endpoint_id: str,
    acquisition_route_id: str,
    fetched_at: datetime,
    primary_exc: Exception,
    fallback_exc: Exception | None = None,
    fallback_from_endpoint_id: str | None = None,
    fallback_from_acquisition_route_id: str | None = None,
) -> dict:
    error = fallback_exc or primary_exc
    diagnostic = {
        "source_id": source_id,
        "endpoint_id": endpoint_id,
        "acquisition_route_id": acquisition_route_id,
        "fallback_used": fallback_exc is not None,
        "network_status": "failed",
        "probe_outcome": "network_error",
        "availability_status": "network_error",
        "http_status": None,
        "payload_sha256": None,
        "payload_size_bytes": 0,
        "fetched_at": fetched_at.isoformat(),
        "http_date": None,
        "last_modified": None,
        "etag": None,
        "content_type": None,
        "schema_status": "unavailable",
        "timestamp_evidence": "unavailable",
        "raw_row_count": 0,
        "accepted_row_count": 0,
        "duplicate_row_count": 0,
        "quarantine_row_count": 0,
        "blocked_row_count": 0,
        "quarantine_reasons": [],
        "error_type": type(error).__name__,
        "error": str(error),
    }
    if fallback_exc is not None:
        diagnostic.update(
            {
                "fallback_from_endpoint_id": fallback_from_endpoint_id,
                "fallback_from_acquisition_route_id": fallback_from_acquisition_route_id,
                "primary_error_type": type(primary_exc).__name__,
                "primary_error": str(primary_exc),
            }
        )
    return diagnostic


def _capture_http_evidence(response: object) -> dict[str, str | None]:
    """Return a small allowlisted response-header projection.

    ``requests`` exposes a case-insensitive mapping, while tests and alternate
    transports may provide a plain mapping.  Read both forms defensively and
    bound each value so an unexpected header implementation cannot inflate a
    candidate artifact.  The caller stores this only as transport evidence;
    the P0 audit explicitly keeps HTTP headers outside PIT publication gates.
    """

    headers = getattr(response, "headers", None)
    if headers is None:
        return {key: None for key, _ in _HTTP_EVIDENCE_HEADERS}

    def lookup(header_name: str) -> str | None:
        value: object | None = None
        try:
            getter = getattr(headers, "get", None)
            if callable(getter):
                value = getter(header_name)
        except (AttributeError, TypeError, ValueError):
            value = None
        if value is None:
            try:
                items = headers.items()
            except (AttributeError, TypeError, ValueError):
                items = ()
            for key, candidate in items:
                if str(key).casefold() == header_name.casefold():
                    value = candidate
                    break
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return text[:_MAX_HTTP_EVIDENCE_VALUE_LENGTH]

    return {key: lookup(header_name) for key, header_name in _HTTP_EVIDENCE_HEADERS}


def _official_no_data_status(payload: bytes) -> str | None:
    """Classify a valid official no-data reply without calling it schema drift."""

    try:
        decoded = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    status = decoded.get("stat")
    if not isinstance(status, str) or not status.strip():
        return None
    normalized = status.strip()
    if normalized.casefold() in {"ok", "success"}:
        return None
    has_rows = isinstance(decoded.get("data"), list) or isinstance(
        decoded.get("tables"), list
    )
    if has_rows:
        return None
    return normalized


def update_phase3c_candidates(
    decision_date: date,
    dry_run: bool = True,
    db_path: Optional[str] = None,
    sources: Sequence[str] = ("institutional", "credit"),
    rate_limit_seconds: float = 3.0,
    include_latest_tdcc_snapshot: bool = False,
    confirm_token: Optional[str] = None,
):
    """單日 Phase 3C 資料回補包裝函式。"""
    return update_phase3c_candidates_range(
        start_date=decision_date.isoformat(),
        end_date=decision_date.isoformat(),
        dry_run=dry_run,
        db_path=db_path,
        sources=sources,
        rate_limit_seconds=rate_limit_seconds,
        include_latest_tdcc_snapshot=include_latest_tdcc_snapshot,
        confirm_token=confirm_token,
    )


def update_phase3c_candidates_range(
    start_date: str,
    end_date: str,
    dry_run: bool = True,
    db_path: Optional[str] = None,
    sources: Sequence[str] = ("institutional", "credit"),
    rate_limit_seconds: float = 3.0,
    allow_online_calendar_probe: bool = False,
    include_latest_tdcc_snapshot: bool = False,
    progress_callback=None,
    confirm_token: Optional[str] = None,
):
    """官方交易日驅動之受控 Phase 3C 區間資料回補。"""
    st_date = date.fromisoformat(start_date)
    ed_date = date.fromisoformat(end_date)

    prod_root = Path(os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data"))
    if not dry_run and not db_path:
        raise ValueError("apply 必須提供 explicit --db-path，且路徑不得位於正式 DATA_ROOT")
    # dry-run 不建立 DB；只使用隔離的暫定路徑承載摘要輸出。
    default_cand_db = project_root.parent / "technical_analysis_candidate_data" / "phase3c_candidate.db"
    target_db = Path(db_path) if db_path else default_cand_db

    runner = Phase3CBackfillRunner(
        candidate_db_path=target_db,
        sources=sources,
        production_data_root=prod_root,
        production_db_path=prod_root / "sqlite" / "twstock.db",
        rate_limit_seconds=rate_limit_seconds,
        allow_online_calendar_probe=allow_online_calendar_probe,
        include_latest_tdcc_snapshot=include_latest_tdcc_snapshot,
    )

    summary = runner.run_backfill(
        start_date=st_date,
        end_date=ed_date,
        dry_run=dry_run,
        confirm_token=confirm_token,
        progress_callback=progress_callback,
    )

    return {
        "success": summary.failed_days_count == 0,
        "summary": summary,
        "message": f"成功處理 {summary.total_days} 天 ({summary.succeeded_days_count} 成功, {summary.skipped_days_count} 跳過, {summary.failed_days_count} 待重試)",
    }


if __name__ == "__main__":
    import argparse

    # Windows 傳統主控台可能仍使用 cp1252；先固定成 UTF-8，讓中文 help 與
    # 自動化 log 不會因 UnicodeEncodeError 中斷。
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Update Phase 3C Source Candidates (Institutional, Credit, TDCC)")
    parser.add_argument("--date", type=str, help="YYYY-MM-DD, 預設為今天", default=None)
    parser.add_argument("--start-date", type=str, help="YYYY-MM-DD 起始日", default=None)
    parser.add_argument("--end-date", type=str, help="YYYY-MM-DD 結束日", default=None)
    parser.add_argument("--sources", type=str, help="逗號分隔來源, 如: institutional,credit", default="institutional,credit")
    parser.add_argument("--db-path", type=str, help="指定寫入的 Candidate DB 路徑 (不可為正式 twstock.db)", default=None)
    parser.add_argument("--confirm", type=str, help=f"必須填入 {APPLY_CONFIRM_TOKEN} 才能實際寫入 DB", default=None)
    parser.add_argument("--rate-limit-seconds", type=float, help="請求間隔秒數 (預設 3.0 秒)", default=3.0)
    parser.add_argument(
        "--allow-online-calendar-probe",
        action="store_true",
        help="僅在本地官方交易日證據缺失時，允許一次 TWSE 查詢；預設不連線猜測。",
    )
    parser.add_argument(
        "--include-latest-tdcc",
        action="store_true",
        help="另外取得 TDCC 最新一週 snapshot；不假造逐日歷史資料。",
    )
    parser.add_argument("--dry-run", action="store_true", help="強制 dry-run", default=True)
    args = parser.parse_args()

    is_dry_run = True
    confirm_token = None
    if args.confirm == APPLY_CONFIRM_TOKEN:
        is_dry_run = False
        confirm_token = args.confirm

    sources_list = [s.strip() for s in args.sources.split(",") if s.strip()]

    st_str = args.start_date
    ed_str = args.end_date

    if not st_str:
        target_d = date.fromisoformat(args.date) if args.date else date.today()
        st_str = target_d.isoformat()
        ed_str = target_d.isoformat()
    elif not ed_str:
        ed_str = date.today().isoformat()

    res = update_phase3c_candidates_range(
        start_date=st_str,
        end_date=ed_str,
        dry_run=is_dry_run,
        db_path=args.db_path,
        sources=sources_list,
        rate_limit_seconds=args.rate_limit_seconds,
        allow_online_calendar_probe=args.allow_online_calendar_probe,
        include_latest_tdcc_snapshot=args.include_latest_tdcc,
        confirm_token=confirm_token,
    )
    logger.info(res["message"])
