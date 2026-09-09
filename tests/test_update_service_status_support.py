from app_module.update_service_status_support import compose_sqlite_status_read_model


def _statuses():
    return {
        "daily_data": {"latest_date": "2026-07-10", "total_records": 10, "status": "ok"},
        "market_index": {"latest_date": "2026-07-10", "total_records": 2, "status": "ok"},
        "industry_index": {"latest_date": "2026-07-10", "total_records": 3, "status": "ok"},
        "broker_branch": {"latest_date": "2026-07-10", "broker_count": 1, "status": "summary"},
        "technical_indicators": {"latest_date": "2026-07-10", "file_count": 4, "status": "summary"},
        "monthly_revenue": {"latest_date": "2026-06", "total_records": 5, "status": "ok"},
    }


def test_compose_sqlite_status_read_model_preserves_detail_payloads():
    statuses = _statuses()

    result = compose_sqlite_status_read_model(statuses)

    assert list(result) == list(statuses)
    assert result == statuses
    assert all("is_overview" not in payload for payload in result.values())


def test_compose_sqlite_status_read_model_marks_copied_overview_payloads():
    statuses = _statuses()

    result = compose_sqlite_status_read_model(statuses, is_overview=True)

    assert list(result) == list(statuses)
    assert all(payload["is_overview"] is True for payload in result.values())
    assert all("is_overview" not in payload for payload in statuses.values())


def test_compose_sqlite_status_read_model_marks_date_lag_only_when_requested():
    statuses = _statuses()
    statuses["market_index"]["latest_date"] = "2026-07-09"

    unchanged = compose_sqlite_status_read_model(statuses)
    assert unchanged["market_index"]["status"] == "ok"

    result = compose_sqlite_status_read_model(statuses, is_overview=True, apply_freshness=True)
    assert result["daily_data"]["freshness_status"] == "reference"
    assert result["market_index"]["freshness_status"] == "lagging"
    assert result["market_index"]["freshness_reference_date"] == "2026-07-10"
    assert result["market_index"]["status"] == "lagging"
    # input mapping 必須維持唯讀／不被副作用修改。
    assert statuses["market_index"]["status"] == "ok"


def test_compose_sqlite_status_read_model_projects_explicit_freshness_receipt():
    statuses = _statuses()
    receipt = {
        "status": "degraded",
        "checked_at": "2026-07-10T05:00:00-07:00",
        "source_statuses": [
            {
                "source_id": "sqlite.market_indices",
                "freshness_status": "partial",
                "reason": "missing official session",
                "expected_period": "20260710",
                "actual_period": "20260709",
                "available_at": "2026-07-10T05:00:00-07:00",
                "coverage": {"observed_official_sessions": 9},
                "missing_periods": ["20260708"],
            },
        ],
    }

    result = compose_sqlite_status_read_model(
        statuses,
        apply_freshness=True,
        freshness_receipt=receipt,
    )

    assert result["market_index"]["freshness_status"] == "partial"
    assert result["market_index"]["freshness_reason"] == "missing official session"
    assert result["market_index"]["freshness_expected_period"] == "20260710"
    assert result["market_index"]["freshness_missing_periods"] == ["20260708"]
    assert result["market_index"]["status"] == "lagging"
    assert result["market_index"]["freshness_probe_checked_at"] == receipt["checked_at"]
    assert statuses["market_index"]["status"] == "ok"
