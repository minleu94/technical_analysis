from __future__ import annotations

from datetime import date

import pytest
import requests

from data_module.mops_ezsearch_statement_availability import (
    MOPSQueryResult,
    MOPS_STATEMENT_AVAILABILITY_SOURCE,
    build_query_payload,
    build_statement_availability_artifact,
    query_mops_ezsearch,
)


def _row(
    *,
    item: str = "F26",
    subject: str = "115年第2季資產負債表",
    clock: str = "18:17:06",
) -> dict[str, str]:
    return {
        "CDATE": "115/07/27",
        "CTIME": clock,
        "TYPEK": "上市",
        "COMPANY_ID": "3321",
        "COMPANY_NAME": "同泰",
        "CODE_NAME": "電子零組件業",
        "AN_CODE": item,
        "AN_NAME": "資產負債表",
        "SUBJECT": subject,
        "HYPERLINK": (
            "https://mopsov.twse.com.tw/mops/web/ajax_t164sb03?"
            "co_id=3321&year=115&season=2"
        ),
    }


def _result(*rows: dict[str, str], item: str = "F26") -> MOPSQueryResult:
    return MOPSQueryResult(
        market="sii",
        announcement_item=item,
        rows=rows,
        response_sha256="a" * 64,
        source_status="success",
    )


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, *, data, headers, timeout):
        self.calls.append((url, data, headers, timeout))
        return _Response(self.payload)


def test_build_query_payload_uses_roc_dates_and_leaves_industry_blank() -> None:
    payload = build_query_payload(
        market="sii",
        announcement_item="F26",
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 28),
    )

    assert payload["TYPEK"] == "sii"
    assert payload["CO_MARKET"] == ""
    assert payload["SDATE"] == "115/07/27"
    assert payload["EDATE"] == "115/07/28"


def test_query_mops_ezsearch_preserves_manifest_hash_and_readonly_headers() -> None:
    session = _Session({"status": "success", "message": ["回傳成功"], "data": [_row()]})

    result = query_mops_ezsearch(
        session,
        market="sii",
        announcement_item="F26",
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 28),
    )

    assert result.rows == (_row(),)
    assert len(result.response_sha256) == 64
    assert result.query_start_date == date(2026, 7, 27)
    assert result.query_end_date == date(2026, 7, 28)
    assert session.calls[0][1]["CO_MARKET"] == ""
    assert session.calls[0][2]["Referer"].endswith("/ezsearch")


def test_artifact_preserves_official_timestamp_and_projects_next_day() -> None:
    artifact = build_statement_availability_artifact(
        [_result(_row())],
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 28),
        captured_at="2026-07-28T12:00:00+08:00",
    )

    event = artifact["rows"][0]
    mapping = artifact["availability_projection"][0]
    assert event["announcement_at"] == "2026-07-27T18:17:06+08:00"
    assert event["period"] == "2026-Q2"
    assert event["period_end"] == "2026-06-30"
    assert event["source_hash"] == "sha256:" + "a" * 64
    assert mapping == {
        "stock_code": "3321",
        "statement_type": "balance_sheet",
        "period": "2026-Q2",
        "as_of_date": "2026-06-30",
        "announced_date": "2026-07-27",
        "available_date": "2026-07-28",
        "source": MOPS_STATEMENT_AVAILABILITY_SOURCE,
        "source_version": "mops-ezsearch-statement-publication.v1",
        "availability_contract_version": "formal-availability.v2",
        "evidence_class": "official_announcement",
        "source_hash": "sha256:" + "a" * 64,
        "revision": "1",
        "parent_revision": "",
    }
    assert artifact["formal_oos_allowed"] is False
    assert artifact["formal_credit_authorized"] is False
    assert artifact["production_blend_alpha_bp"] == 0
    assert "M31" in artifact["excluded_umbrella_items"]


def test_artifact_deduplicates_exact_events_but_keeps_earliest_revision() -> None:
    later = _row(clock="19:30:00")
    artifact = build_statement_availability_artifact(
        [_result(_row(), _row(), later)],
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 28),
        captured_at="2026-07-28T12:00:00+08:00",
    )

    assert artifact["quality_summary"]["event_count"] == 2
    assert artifact["quality_summary"]["duplicate_event_count"] == 1
    assert artifact["quality_summary"]["projection_count"] == 1
    assert artifact["availability_projection"][0]["announced_date"] == "2026-07-27"


def test_artifact_rejects_m31_meeting_notice_as_statement_publication() -> None:
    result = _result(
        _row(
            item="M31",
            subject="公告本公司115年第二季財務報告董事會預計召開日期",
        )
    )

    with pytest.raises(ValueError, match="announcement item"):
        build_statement_availability_artifact(
            [result],
            start_date=date(2026, 7, 27),
            end_date=date(2026, 7, 28),
            captured_at="2026-07-28T12:00:00+08:00",
        )


def test_artifact_rejects_future_timestamp() -> None:
    with pytest.raises(ValueError, match="later than captured_at"):
        build_statement_availability_artifact(
            [_result(_row())],
            start_date=date(2026, 7, 27),
            end_date=date(2026, 7, 28),
            captured_at="2026-07-27T10:00:00+08:00",
        )


def test_artifact_rejects_non_sha256_source_hash() -> None:
    with pytest.raises(ValueError, match="response_sha256"):
        build_statement_availability_artifact(
            [
                MOPSQueryResult(
                    market="sii",
                    announcement_item="F26",
                    rows=(_row(),),
                    response_sha256="not-a-hash",
                    source_status="success",
                )
            ],
            start_date=date(2026, 7, 27),
            end_date=date(2026, 7, 28),
            captured_at="2026-07-28T12:00:00+08:00",
        )


def test_artifact_counts_failed_queries_without_treating_them_as_empty_success() -> None:
    artifact = build_statement_availability_artifact(
        [
            _result(_row()),
            MOPSQueryResult(
                market="otc",
                announcement_item="F26",
                rows=(),
                response_sha256="b" * 64,
                source_status="error",
                error_code="network_timeout",
            ),
        ],
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 28),
        captured_at="2026-07-28T12:00:00+08:00",
    )

    assert artifact["quality_summary"]["successful_query_count"] == 1
    assert artifact["quality_summary"]["failed_query_count"] == 1
    assert artifact["query_manifest"][1]["error_code"] == "network_timeout"


def test_artifact_manifest_preserves_query_window_when_present() -> None:
    artifact = build_statement_availability_artifact(
        [
            MOPSQueryResult(
                market="sii",
                announcement_item="F26",
                rows=(_row(),),
                response_sha256="a" * 64,
                source_status="success",
                query_start_date=date(2026, 7, 27),
                query_end_date=date(2026, 7, 28),
            )
        ],
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 28),
        captured_at="2026-07-28T12:00:00+08:00",
    )

    assert artifact["query_manifest"][0]["query_start_date"] == "2026-07-27"
    assert artifact["query_manifest"][0]["query_end_date"] == "2026-07-28"


def test_artifact_separates_official_no_data_queries_from_transport_failures() -> None:
    artifact = build_statement_availability_artifact(
        [
            _result(_row()),
            MOPSQueryResult(
                market="otc",
                announcement_item="F26",
                rows=(),
                response_sha256="b" * 64,
                source_status="fail",
            ),
            MOPSQueryResult(
                market="rotc",
                announcement_item="F26",
                rows=(),
                response_sha256="c" * 64,
                source_status="error",
                error_code="network_timeout",
            ),
        ],
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 28),
        captured_at="2026-07-28T12:00:00+08:00",
    )

    quality = artifact["quality_summary"]
    assert quality["successful_query_count"] == 1
    assert quality["official_no_data_query_count"] == 1
    assert quality["failed_query_count"] == 1
    assert artifact["query_manifest"][1]["source_status"] == "fail"


def test_artifact_rejects_rows_on_official_no_data_query() -> None:
    with pytest.raises(ValueError, match="official no-data query must not contain rows"):
        build_statement_availability_artifact(
            [
                MOPSQueryResult(
                    market="sii",
                    announcement_item="F26",
                    rows=(_row(),),
                    response_sha256="a" * 64,
                    source_status="fail",
                )
            ],
            start_date=date(2026, 7, 27),
            end_date=date(2026, 7, 28),
            captured_at="2026-07-28T12:00:00+08:00",
        )


def test_fetch_cli_safe_query_converts_timeout_to_structured_failure() -> None:
    from scripts.fetch_mops_statement_availability import _safe_query

    class TimeoutSession:
        def post(self, *args, **kwargs):
            del args, kwargs
            raise requests.Timeout("timed out")

    result = _safe_query(
        TimeoutSession(),  # type: ignore[arg-type]
        market="sii",
        announcement_item="F26",
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 28),
        timeout_seconds=1,
    )

    assert result.source_status == "error"
    assert result.error_code == "network_timeout"
    assert result.rows == ()


def test_fetch_cli_date_windows_are_bounded_and_cover_range() -> None:
    from scripts.fetch_mops_statement_availability import _iter_date_windows

    windows = _iter_date_windows(
        date(2026, 5, 1),
        date(2026, 5, 31),
        window_days=7,
    )

    assert windows == (
        (date(2026, 5, 1), date(2026, 5, 7)),
        (date(2026, 5, 8), date(2026, 5, 14)),
        (date(2026, 5, 15), date(2026, 5, 21)),
        (date(2026, 5, 22), date(2026, 5, 28)),
        (date(2026, 5, 29), date(2026, 5, 31)),
    )


def test_fetch_cli_retries_failed_query_and_preserves_error_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import fetch_mops_statement_availability as fetch_cli

    failed = MOPSQueryResult(
        market="otc",
        announcement_item="F29",
        rows=(),
        response_sha256="b" * 64,
        source_status="error",
        error_code="network_error",
        query_start_date=date(2026, 5, 1),
        query_end_date=date(2026, 5, 7),
    )
    succeeded = MOPSQueryResult(
        market="otc",
        announcement_item="F29",
        rows=(_row(item="F29"),),
        response_sha256="c" * 64,
        source_status="success",
        query_start_date=date(2026, 5, 1),
        query_end_date=date(2026, 5, 7),
    )
    results = iter((failed, succeeded))
    monkeypatch.setattr(fetch_cli, "_safe_query", lambda *args, **kwargs: next(results))

    result = fetch_cli._query_with_retries(
        object(),  # type: ignore[arg-type]
        market="otc",
        announcement_item="F29",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 7),
        timeout_seconds=1,
        max_retries=2,
    )

    assert result.source_status == "success"
    assert result.attempt_count == 2
    assert result.retry_error_codes == ("network_error",)


def test_fetch_cli_configures_utf8_stdio_when_streams_support_reconfigure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import fetch_mops_statement_availability as fetch_cli

    class ReconfigurableStream:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        def reconfigure(self, **kwargs: str) -> None:
            self.calls.append(kwargs)

    stdout = ReconfigurableStream()
    stderr = ReconfigurableStream()
    monkeypatch.setattr(fetch_cli.sys, "stdout", stdout)
    monkeypatch.setattr(fetch_cli.sys, "stderr", stderr)

    fetch_cli._configure_utf8_stdio()

    assert stdout.calls == [{"encoding": "utf-8", "errors": "backslashreplace"}]
    assert stderr.calls == [{"encoding": "utf-8", "errors": "backslashreplace"}]
