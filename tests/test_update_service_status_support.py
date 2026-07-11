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
