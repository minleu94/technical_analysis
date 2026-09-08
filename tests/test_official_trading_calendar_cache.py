from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from data_module.official_trading_calendar import OfficialTradingCalendar
from data_module.official_trading_calendar_cache import (
    OfficialCalendarCacheError,
    TWSE_NEWS_CONTENT_URL,
    TWSE_NEWS_DETAIL_URL,
    TWSE_NEWS_LIST_URL,
    TWSE_TEMPORARY_CLOSURE_POLICY_URL,
    build_twse_calendar_cache,
    build_twse_temporary_closure_cache,
    bytes_hash,
    load_verified_twse_calendar_cache,
    load_verified_twse_temporary_closure_cache,
    payload_hash,
    refresh_twse_calendar_cache,
    refresh_twse_temporary_closure_events,
    write_twse_temporary_closure_cache,
    write_twse_calendar_cache,
)
from scripts.capture_official_trading_calendar_cache import main


def _official_payload(year: int = 2026) -> list[dict[str, str]]:
    roc_year = year - 1911
    return [
        {
            "Name": "中華民國開國紀念日",
            "Date": f"{roc_year:03d}0101",
            "Weekday": "四",
            "Description": "依規定放假1日。",
        },
        {
            "Name": "國曆新年開始交易日",
            "Date": f"{roc_year:03d}0102",
            "Weekday": "五",
            "Description": "國曆新年開始交易。",
        },
    ]


def _cache(
    path: Path,
    *,
    captured_at: datetime | None = None,
    year: int = 2026,
) -> dict[str, object]:
    captured = captured_at or datetime.now(timezone.utc) - timedelta(hours=1)
    requested = captured - timedelta(seconds=1)
    raw = json.dumps(
        _official_payload(year),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    cache = build_twse_calendar_cache(
        calendar_year=year,
        raw_response=raw,
        requested_at=requested,
        captured_at=captured,
        response_status=200,
        response_headers={
            "Content-Type": "application/json",
            "ETag": '"cache-test"',
        },
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    write_twse_calendar_cache(path, cache, allowed_root=path.parents[2])
    return cache


def test_cache_is_hash_bound_full_year_and_used_without_network(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "calendar" / "twse_holiday_schedule_2026_test.json"
    cache = _cache(cache_path)

    with patch(
        "data_module.official_trading_calendar.safe_request",
        side_effect=AssertionError("valid cache must avoid the network"),
    ):
        calendar = OfficialTradingCalendar(
            tmp_path / "missing-market.sqlite",
            calendar_cache_path=cache_path.parent,
        )
        assert calendar.is_official_trading_day(date(2026, 1, 2)) == (
            True,
            "twse_holiday_schedule_cache_explicit_open",
        )
        assert calendar.is_official_trading_day(date(2026, 1, 5)) == (
            True,
            "twse_holiday_schedule_cache_open",
        )

    evidence = calendar.evidence_for(date(2026, 1, 5))
    assert evidence["mode"] == "hash_bound_official_calendar_cache"
    assert evidence["source_hash"] == cache["source"]["response_sha256"]
    assert evidence["coverage"]["complete_year"] is True  # type: ignore[index]
    assert evidence["coverage"]["day_count"] == 365  # type: ignore[index]


def test_cache_rejects_rehashed_payload_with_changed_raw_response(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "calendar" / "cache.json"
    _cache(cache_path)
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    body = dict(payload)
    body["raw_response_base64"] = base64.b64encode(b"[]").decode("ascii")
    body["content_sha256"] = payload_hash({key: value for key, value in body.items() if key != "content_sha256"})
    cache_path.write_text(
        json.dumps(body, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(
        OfficialCalendarCacheError,
        match="response hash mismatch",
    ):
        load_verified_twse_calendar_cache(
            cache_path,
            calendar_year=2026,
        )


def test_expired_cache_keeps_calendar_unknown_when_network_is_unavailable(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "calendar" / "cache.json"
    _cache(
        cache_path,
        captured_at=datetime.now(timezone.utc) - timedelta(days=8),
    )
    with patch(
        "data_module.official_trading_calendar.safe_request",
        side_effect=RuntimeError("network unavailable"),
    ):
        result = OfficialTradingCalendar(
            tmp_path / "missing-market.sqlite",
            calendar_cache_path=cache_path,
        ).is_official_trading_day(date(2026, 1, 5))

    assert result == (None, "twse_holiday_schedule_cache_expired")


def test_wrong_year_cache_is_not_used_for_requested_year(tmp_path: Path) -> None:
    cache_path = tmp_path / "calendar" / "cache.json"
    _cache(cache_path, year=2025)
    with patch(
        "data_module.official_trading_calendar.safe_request",
        side_effect=RuntimeError("network unavailable"),
    ):
        result = OfficialTradingCalendar(
            tmp_path / "missing-market.sqlite",
            calendar_cache_path=cache_path,
        ).is_official_trading_day(date(2026, 1, 5))

    assert result == (None, "twse_holiday_schedule_cache_wrong_year")


def test_missing_cache_is_reported_when_official_request_is_unavailable(
    tmp_path: Path,
) -> None:
    with patch(
        "data_module.official_trading_calendar.safe_request",
        side_effect=RuntimeError("network unavailable"),
    ):
        result = OfficialTradingCalendar(
            tmp_path / "missing-market.sqlite",
            calendar_cache_path=tmp_path / "calendar-cache",
        ).is_official_trading_day(date(2026, 1, 5))

    assert result == (None, "twse_holiday_schedule_cache_missing")


def test_cache_capture_cli_is_bounded_and_create_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "output").mkdir(parents=True)
    output = repo / "output" / "calendar" / "twse_holiday_schedule_2026.json"
    output.parent.mkdir()
    raw = json.dumps(
        _official_payload(),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    response = SimpleNamespace(
        content=raw,
        status_code=200,
        headers={"Content-Type": "application/json"},
    )

    with patch(
        "scripts.capture_official_trading_calendar_cache.ROOT",
        repo,
    ), patch(
        "scripts.capture_official_trading_calendar_cache.safe_request",
        return_value=response,
    ) as request:
        assert main(
            [
                "--year",
                "2026",
                "--output",
                str(output),
                "--confirm-network",
            ]
        ) == 0
        request.assert_called_once()

    loaded = load_verified_twse_calendar_cache(output, calendar_year=2026)
    assert loaded.evidence["source_hash"] == bytes_hash(raw)
    assert loaded.evidence["coverage"]["complete_year"] is True  # type: ignore[index]
    assert main(
        [
            "--year",
            "2026",
            "--output",
            str(output),
            "--confirm-network",
        ]
    ) == 2


def test_refresh_reuses_valid_cache_without_network(tmp_path: Path) -> None:
    cache_path = tmp_path / "calendar" / "twse_holiday_schedule_2026_existing.json"
    _cache(cache_path, captured_at=datetime.now(timezone.utc) - timedelta(hours=1))

    with patch("data_module.official_trading_calendar_cache.safe_request") as request:
        result = refresh_twse_calendar_cache(
            calendar_year=2026,
            cache_root=cache_path.parent,
            allowed_root=tmp_path,
            observed_at=datetime.now(timezone.utc),
        )

    assert result["status"] == "cache_valid"
    assert result["network_attempts"] == 0
    request.assert_not_called()


def test_refresh_after_expiry_creates_new_cache_and_retains_old_file(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 7, 19, 0, tzinfo=timezone.utc)
    old_path = tmp_path / "calendar" / "twse_holiday_schedule_2026_old.json"
    _cache(old_path, captured_at=now - timedelta(days=8))
    raw = json.dumps(
        _official_payload(),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    response = SimpleNamespace(
        content=raw,
        status_code=200,
        headers={"Content-Type": "application/json"},
    )
    clock_values = iter((now, now))
    with patch(
        "data_module.official_trading_calendar_cache.safe_request",
        return_value=response,
    ) as request:
        result = refresh_twse_calendar_cache(
            calendar_year=2026,
            cache_root=old_path.parent,
            allowed_root=tmp_path,
            observed_at=now,
            now_provider=lambda: next(clock_values),
        )

    assert result["status"] == "refreshed"
    assert result["network_attempts"] == 1
    assert result["retained_previous_cache"] is True
    assert old_path.exists()
    refreshed_path = Path(str(result["cache_path"]))
    assert refreshed_path.exists()
    assert refreshed_path != old_path
    request.assert_called_once()
    load_verified_twse_calendar_cache(
        refreshed_path,
        calendar_year=2026,
        observed_at=now,
    )


def test_refresh_is_bounded_and_preserves_expired_cache_on_network_failure(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 7, 19, 0, tzinfo=timezone.utc)
    old_path = tmp_path / "calendar" / "twse_holiday_schedule_2026_old.json"
    _cache(old_path, captured_at=now - timedelta(days=8))
    with patch(
        "data_module.official_trading_calendar_cache.safe_request",
        side_effect=RuntimeError("network unavailable"),
    ) as request:
        result = refresh_twse_calendar_cache(
            calendar_year=2026,
            cache_root=old_path.parent,
            allowed_root=tmp_path,
            observed_at=now,
            now_provider=lambda: now,
            max_attempts=2,
        )

    assert result["status"] == "refresh_blocked"
    assert result["network_attempts"] == 2
    assert result["retained_previous_cache"] is True
    assert old_path.exists()
    assert len(list(old_path.parent.glob("twse_holiday_schedule_2026_*.json"))) == 1
    assert request.call_count == 2


def test_refresh_rejects_wrong_year_candidate_before_bounded_retry(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 7, 19, 0, tzinfo=timezone.utc)
    wrong_path = tmp_path / "calendar" / "twse_holiday_schedule_2026_wrong.json"
    _cache(wrong_path, captured_at=now - timedelta(hours=1), year=2025)
    with patch(
        "data_module.official_trading_calendar_cache.safe_request",
        side_effect=RuntimeError("network unavailable"),
    ) as request:
        result = refresh_twse_calendar_cache(
            calendar_year=2026,
            cache_root=wrong_path.parent,
            allowed_root=tmp_path,
            observed_at=now,
            now_provider=lambda: now,
        )

    assert result["status"] == "refresh_blocked"
    assert result["network_attempts"] == 2
    assert result["previous_cache"][0]["reason"].startswith(  # type: ignore[index]
        "OfficialCalendarCacheError:calendar cache year mismatch"
    )
    assert request.call_count == 2


def test_annual_cache_declares_temporary_closure_limit(tmp_path: Path) -> None:
    cache_path = tmp_path / "calendar" / "twse_holiday_schedule_2026_scope.json"
    cache = _cache(cache_path)
    coverage = cache["coverage"]
    assert isinstance(coverage, dict)
    assert coverage["temporary_closure_coverage"] == "not_covered"
    policy = coverage["temporary_closure_policy_source"]
    assert isinstance(policy, dict)
    assert policy["url"] == TWSE_TEMPORARY_CLOSURE_POLICY_URL
    assert policy["event_evidence_required"] is True

    calendar = OfficialTradingCalendar(
        tmp_path / "missing-market.sqlite",
        calendar_cache_path=cache_path,
    )
    evidence = calendar.evidence_for(date(2026, 7, 13))
    assert evidence["temporary_closure_scope"]["event_evidence_required"] is True  # type: ignore[index]
    assert evidence["annual_schedule_scope"] == "planned_annual_closures"


def test_official_temporary_closure_event_overrides_annual_plan(
    tmp_path: Path,
) -> None:
    path = tmp_path / "calendar" / "twse_temporary_closure_20260710.json"
    source_url = (
        "https://www.twse.com.tw/zh/announcement/announcement/detail.html?id=abc"
    )
    raw = (
        "<html>臺灣證券交易所集中交易市場於115年7月10日全日休市一天，"
        "因颱風影響。</html>"
    ).encode("utf-8")
    captured = datetime(2026, 7, 9, 1, 0, tzinfo=timezone.utc)
    cache = build_twse_temporary_closure_cache(
        closure_date=date(2026, 7, 10),
        raw_response=raw,
        source_url=source_url,
        requested_at=captured - timedelta(seconds=1),
        captured_at=captured,
        response_status=200,
        response_headers={"Content-Type": "text/html"},
        response_url=source_url,
    )
    path.parent.mkdir(parents=True)
    write_twse_temporary_closure_cache(path, cache, allowed_root=tmp_path)
    loaded = load_verified_twse_temporary_closure_cache(
        path,
        observed_at=captured + timedelta(minutes=1),
    )
    assert loaded.closure_date == date(2026, 7, 10)

    calendar = OfficialTradingCalendar(
        tmp_path / "missing-market.sqlite",
        temporary_closure_path=path,
    )
    assert calendar.is_official_trading_day(date(2026, 7, 10)) == (
        False,
        "twse_temporary_closure_official",
    )
    evidence = calendar.evidence_for(date(2026, 7, 10))
    assert evidence["mode"] == "hash_bound_official_temporary_closure"
    assert evidence["annual_schedule_override"] is True


def test_temporary_closure_policy_page_or_missing_statement_cannot_be_event(
    tmp_path: Path,
) -> None:
    closure_date = date(2026, 7, 10)
    captured = datetime(2026, 7, 9, tzinfo=timezone.utc)
    policy_url = TWSE_TEMPORARY_CLOSURE_POLICY_URL
    with pytest.raises(OfficialCalendarCacheError, match="announcement"):
        build_twse_temporary_closure_cache(
            closure_date=closure_date,
            raw_response=(
                "台北市全日停止上班時，集中交易市場全日休市。"
            ).encode("utf-8"),
            source_url=policy_url,
            requested_at=captured,
            captured_at=captured,
            response_status=200,
        )
    with pytest.raises(OfficialCalendarCacheError, match="does not mention"):
        build_twse_temporary_closure_cache(
            closure_date=closure_date,
            raw_response="市場休市一天。".encode("utf-8"),
            source_url=(
                "https://www.twse.com.tw/zh/announcement/announcement/detail.html?id=abc"
            ),
            requested_at=captured,
            captured_at=captured,
            response_status=200,
        )


def test_operational_news_discovery_captures_official_single_day_event(
    tmp_path: Path,
) -> None:
    """公告清單→明細→sidecar→consumer readback 必須是一條可重驗鏈。"""

    announcement_id = "8a8216d69ef76943019f46cb86bf0111"
    detail_url = f"{TWSE_NEWS_DETAIL_URL}?id={announcement_id}"
    list_url = (
        f"{TWSE_NEWS_LIST_URL}?tag=%E4%BC%91%E5%B8%82&response=json"
    )
    list_raw = json.dumps(
        {
            "stat": "OK",
            "fields": ["序號", "標題", "發布日期", "zhId"],
            "data": [
                [
                    "1",
                    "臺灣證券交易所集中交易市場115年7月10日休市一天",
                    "115年07月09日",
                    announcement_id,
                ],
                [
                    "2",
                    "中華民國115年集中交易市場開休市日期",
                    "115年02月12日",
                    "8a8216d69ef76943019f46cb86bf0112",
                ],
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    detail_raw = (
        "<html><h2>臺灣證券交易所集中交易市場115年7月10日休市一天</h2>"
        "<p>發布日期︰民國 115年07月09日 20:11</p>"
        "<p>因颱風影響，當日全日休市。</p></html>"
    ).encode("utf-8")
    now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    clock_values = iter((now, now, now, now))

    def request(url: str, **kwargs: object) -> SimpleNamespace:
        if url == TWSE_NEWS_LIST_URL:
            assert kwargs["params"] == {"tag": "休市", "response": "json"}
            return SimpleNamespace(
                content=list_raw,
                status_code=200,
                headers={"Content-Type": "application/json"},
                url=list_url,
            )
        assert url == detail_url
        return SimpleNamespace(
            content=detail_raw,
            status_code=200,
            headers={"Content-Type": "text/html"},
            url=detail_url,
        )

    result = refresh_twse_temporary_closure_events(
        calendar_year=2026,
        cache_root=tmp_path / "calendar",
        allowed_root=tmp_path,
        observed_at=now,
        now_provider=lambda: next(clock_values),
        request_fn=request,
    )

    assert result["status"] == "temporary_closure_events_updated"
    assert result["network_attempts"] == 2
    assert result["detail_requests"] == 1
    events = result["events"]
    assert isinstance(events, list) and len(events) == 1
    event_path = Path(str(events[0]["path"]))  # type: ignore[index]
    assert event_path.exists()
    loaded = load_verified_twse_temporary_closure_cache(
        event_path,
        observed_at=now,
    )
    assert loaded.closure_date == date(2026, 7, 10)
    source = loaded.evidence["source"]
    assert isinstance(source, dict)
    discovery = source["discovery"]
    assert isinstance(discovery, dict)
    assert discovery["announcement_id"] == announcement_id
    assert discovery["closure_date"] == "2026-07-10"
    assert discovery["captured_at_utc"] == now.isoformat()


def test_operational_news_discovery_is_bounded_and_observable_when_unavailable(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)

    def unavailable(*args: object, **kwargs: object) -> object:
        raise RuntimeError("official endpoint unavailable")

    result = refresh_twse_temporary_closure_events(
        calendar_year=2026,
        cache_root=tmp_path / "calendar",
        allowed_root=tmp_path,
        observed_at=now,
        now_provider=lambda: now,
        request_fn=unavailable,
    )

    assert result["status"] == "temporary_closure_discovery_blocked"
    assert result["network_attempts"] == 1
    assert result["detail_requests"] == 0
    assert result["events"] == []
    assert list((tmp_path / "calendar").glob("*.json")) == []


def test_operational_news_discovery_rejects_wrong_final_url(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    raw = '{"stat":"OK","fields":["標題","zhId"],"data":[]}'.encode(
        "utf-8"
    )

    def redirected(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            content=raw,
            status_code=200,
            headers={},
            url="https://example.invalid/rwd/zh/news/newsList?tag=x",
        )

    result = refresh_twse_temporary_closure_events(
        calendar_year=2026,
        cache_root=tmp_path / "calendar",
        allowed_root=tmp_path,
        observed_at=now,
        now_provider=lambda: now,
        request_fn=redirected,
    )

    assert result["status"] == "temporary_closure_discovery_blocked"
    assert "final URL" in str(result["errors"])
    assert list((tmp_path / "calendar").glob("*.json")) == []


def test_operational_news_discovery_rehashed_list_tamper_is_rejected(
    tmp_path: Path,
) -> None:
    announcement_id = "8a8216d69ef76943019f46cb86bf0111"
    title = "臺灣證券交易所集中交易市場115年7月10日休市一天"
    now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    list_raw = json.dumps(
        {
            "stat": "OK",
            "fields": ["標題", "zhId"],
            "data": [[title, announcement_id]],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    detail_raw = (
        f"{title}。發布日期︰民國 115年07月09日 20:11，當日全日休市。"
    ).encode("utf-8")
    discovery = {
        "provider": "TWSE",
        "endpoint": TWSE_NEWS_LIST_URL,
        "request_url": (
            f"{TWSE_NEWS_LIST_URL}?tag=%E4%BC%91%E5%B8%82&response=json"
        ),
        "response_url": (
            f"{TWSE_NEWS_LIST_URL}?tag=%E4%BC%91%E5%B8%82&response=json"
        ),
        "http_status": 200,
        "response_sha256": bytes_hash(list_raw),
        "raw_response_base64": base64.b64encode(list_raw).decode("ascii"),
        "requested_at_utc": now.isoformat(),
        "captured_at_utc": now.isoformat(),
        "tag": "休市",
        "announcement_id": announcement_id,
        "title": title,
        "closure_date": "2026-07-10",
    }
    cache = build_twse_temporary_closure_cache(
        closure_date=date(2026, 7, 10),
        raw_response=detail_raw,
        source_url=f"{TWSE_NEWS_DETAIL_URL}?id={announcement_id}",
        requested_at=now,
        captured_at=now,
        response_status=200,
        response_url=f"{TWSE_NEWS_DETAIL_URL}?id={announcement_id}",
        discovery_evidence=discovery,
    )
    path = tmp_path / "calendar" / "event.json"
    path.parent.mkdir()
    write_twse_temporary_closure_cache(path, cache, allowed_root=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    source = payload["source"]
    tampered_list = (
        '{"stat":"OK","fields":["標題","zhId"],"data":[]}'.encode(
            "utf-8"
        )
    )
    source["discovery"]["raw_response_base64"] = base64.b64encode(
        tampered_list
    ).decode("ascii")
    source["discovery"]["response_sha256"] = bytes_hash(tampered_list)
    body = dict(payload)
    body.pop("content_sha256")
    body["content_sha256"] = payload_hash(body)
    path.write_text(
        json.dumps(body, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(
        OfficialCalendarCacheError,
        match="does not match event",
    ):
        load_verified_twse_temporary_closure_cache(path, observed_at=now)
