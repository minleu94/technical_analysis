from __future__ import annotations

import json
from pathlib import Path

import app_module.broker_branch_update_service as broker_module
from scripts.qa_broker_bounded_fetch_acceptance import _render_metric_html
from scripts.qa_broker_real_http_canary import (
    combine_with_broker_baseline,
    main,
    measure_real_http_canary,
)


class _Response:
    status_code = 200

    def __init__(self) -> None:
        self.content = _render_metric_html("lots").encode("big5")

    def raise_for_status(self) -> None:
        return None


def _branch() -> dict[str, str]:
    return {
        "branch_system_key": "1030_1030",
        "branch_broker_code": "1030",
        "branch_code": "1030",
        "branch_display_name": "土銀",
        "url_param_a": "1030",
        "url_param_b": "1030",
    }


def test_real_http_canary_requires_confirmation_without_request(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        broker_module.requests,
        "get",
        lambda *args, **kwargs: calls.append(str(args[0])),
    )
    staging = tmp_path / "staging"
    protected = tmp_path / "protected"
    staging.mkdir()
    protected.mkdir()

    report = measure_real_http_canary(
        staging_root=staging,
        protected_roots=[protected],
        branch_info=_branch(),
        date_str="2026-08-28",
        metric="lots",
    )

    assert report["status"] == "confirmation_required"
    assert report["network_enabled"] is False
    assert calls == []


def test_real_http_canary_uses_one_fake_request_and_cleans_staging(tmp_path, monkeypatch):
    calls: list[str] = []

    def fake_get(url: str, **kwargs):
        calls.append(url)
        assert kwargs["timeout"] == 15
        return _Response()

    monkeypatch.setattr(broker_module.requests, "get", fake_get)
    staging = tmp_path / "staging"
    protected = tmp_path / "protected"
    staging.mkdir()
    protected.mkdir()

    report = measure_real_http_canary(
        staging_root=staging,
        protected_roots=[protected],
        branch_info=_branch(),
        date_str="2026-08-28",
        metric="lots",
        confirm_real_http_canary=True,
    )

    assert report["status"] == "measured"
    assert report["network_enabled"] is True
    assert report["real_http_attempted"] is True
    assert report["request_count"] == 1
    assert report["row_count"] == 1
    assert report["selenium_invocations"] == 0
    assert report["production_write_attempted"] is False
    assert report["cleanup_succeeded"] is True
    assert len(calls) == 1


def test_main_rejects_output_inside_protected_root_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr(
        broker_module.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network called")),
    )
    staging = tmp_path / "staging"
    protected = tmp_path / "protected"
    staging.mkdir()
    protected.mkdir()

    assert (
        main(
            [
                "--staging-root",
                str(staging),
                "--protected-root",
                str(protected),
                "--branch-system-key",
                "1030_1030",
                "--branch-broker-code",
                "1030",
                "--branch-code",
                "1030",
                "--branch-display-name",
                "土銀",
                "--url-param-a",
                "1030",
                "--url-param-b",
                "1030",
                "--date",
                "2026-08-28",
                "--metric",
                "lots",
                "--confirm-real-http-canary",
                "--output-json",
                str(protected / "report.json"),
            ]
        )
        == 2
    )


def test_combine_with_baseline_preserves_offline_contract(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "status": "measured",
                "network_enabled": False,
                "staging_fetch_pool_enabled": True,
                "production_fetch_pool_enabled": False,
                "production_write_attempted": False,
                "bounded_fetch_acceptance": {"status": "measured", "checks": {"ok": True}},
            }
        ),
        encoding="utf-8",
    )
    canary = {"status": "measured", "network_enabled": True, "row_count": 100}

    combined = combine_with_broker_baseline(baseline, canary)

    assert combined["schema_version"] == "broker-performance-baseline.v2"
    assert combined["network_enabled"] is True
    assert combined["real_http_canary"] == canary
    assert combined["bounded_fetch_acceptance"]["status"] == "measured"
