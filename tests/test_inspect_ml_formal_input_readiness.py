from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import inspect_ml_formal_input_readiness as readiness


def test_readiness_is_fail_closed_when_all_formal_inputs_are_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    for name in (
        readiness.PORTFOLIO_LEDGER_ENV,
        readiness.RULE_HISTORY_ENV,
        readiness.SECTOR_MEMBERSHIP_ENV,
        readiness.RULE_HMAC_KEY_ENV,
        readiness.RULE_STORE_ID_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        readiness,
        "discover_valid_sector_membership",
        lambda **_: None,
    )

    report = readiness.build_readiness_report(
        output_root=output_root,
        training_as_of="2026-08-13T08:30:00+08:00",
    )

    assert report["status"] == "waiting_for_formal_inputs"
    assert report["formal_oos_allowed"] is False
    assert report["production_alpha_bp"] == 0
    assert report["broker_order_allowed"] is False
    assert [item["state"] for item in report["inputs"]] == [
        "missing",
        "missing",
        "missing",
    ]
    assert report["ready_input_ratio"] == "0/3"
    assert report["ready_input_count"] == 0
    assert report["input_count"] == 3
    assert report["runtime_attestation"]["secret_values_emitted"] is False


def test_missing_prospective_path_exposes_stale_configured_clock_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    stale_root = (
        tmp_path
        / "formal_prospective"
        / "clock-20260819"
        / "portfolio_ledger"
        / "manifest.json"
    )
    monkeypatch.setenv(readiness.PORTFOLIO_LEDGER_ENV, str(stale_root))
    for name in (
        readiness.RULE_HISTORY_ENV,
        readiness.SECTOR_MEMBERSHIP_ENV,
        readiness.RULE_HMAC_KEY_ENV,
        readiness.RULE_STORE_ID_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        readiness,
        "discover_valid_sector_membership",
        lambda **_: None,
    )

    report = readiness.build_readiness_report(
        output_root=output_root,
        training_as_of="2026-08-28T08:30:00+08:00",
    )

    portfolio = report["inputs"][0]
    assert portfolio["reason"] == "prospective_output_not_published"
    assert portfolio["source_lane"] == "prospective_formal_simulation"
    assert portfolio["configured_clock_id"] == "clock-20260819"
    assert portfolio["configured_clock_date"] == "2026-08-19"
    assert portfolio["training_as_of_date"] == "2026-08-28"
    assert portfolio["configured_clock_date_before_training_as_of"] is True
    assert "update the explicit path" in portfolio["diagnostic"]


def test_readiness_reports_prospective_staging_without_adopting_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "output"
    prospective_root = output_root / "formal_prospective" / "clock-20260828"
    (prospective_root / "clock").mkdir(parents=True)
    (prospective_root / "staging").mkdir()
    (prospective_root / "clock" / "manifest.json").write_text(
        "{}",
        encoding="utf-8",
    )
    output_root.mkdir(exist_ok=True)
    for name in (
        readiness.PORTFOLIO_LEDGER_ENV,
        readiness.RULE_HISTORY_ENV,
        readiness.SECTOR_MEMBERSHIP_ENV,
        readiness.RULE_HMAC_KEY_ENV,
        readiness.RULE_STORE_ID_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        readiness,
        "discover_valid_sector_membership",
        lambda **_: None,
    )

    report = readiness.build_readiness_report(
        output_root=output_root,
        training_as_of="2026-08-28T08:30:00+08:00",
    )

    observation = report["prospective_output_observation"]
    assert observation["status"] == "staging_or_prospective_observed"
    assert observation["candidate_clock_count"] == 1
    candidate = observation["candidate_clocks"][0]
    assert candidate["clock_id"] == "clock-20260828"
    assert candidate["staging_present"] is True
    assert candidate["formal_consumer_compatible"] is False
    assert candidate["authority"] == "diagnostic_only"
    assert report["status"] == "waiting_for_formal_inputs"


def test_readiness_adopts_late_windows_owner_deposit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    ledger_path = tmp_path / "ledger" / "manifest.json"
    history_path = tmp_path / "history" / "manifest.json"
    sector_path = tmp_path / "sector" / "sidecar.json"
    for path in (ledger_path, history_path, sector_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")

    class _FakeKey:
        def __init__(self, values: dict[str, str]) -> None:
            self.values = values

        def __enter__(self) -> "_FakeKey":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    class _FakeWinreg:
        HKEY_CURRENT_USER = "user"
        HKEY_LOCAL_MACHINE = "machine"
        REG_EXPAND_SZ = 2

        def __init__(self) -> None:
            self.values = {
                self.HKEY_CURRENT_USER: {
                    readiness.PORTFOLIO_LEDGER_ENV: str(ledger_path.resolve()),
                    readiness.RULE_HISTORY_ENV: str(history_path.resolve()),
                    readiness.SECTOR_MEMBERSHIP_ENV: str(sector_path.resolve()),
                    readiness.RULE_HMAC_KEY_ENV: "late-secret",
                    readiness.RULE_STORE_ID_ENV: "late-store",
                }
            }

        def OpenKey(self, hive: str, _subkey: str) -> _FakeKey:
            if hive not in self.values:
                raise OSError("registry key missing")
            return _FakeKey(self.values[hive])

        def QueryValueEx(
            self,
            key: _FakeKey,
            name: str,
        ) -> tuple[str, int]:
            try:
                return key.values[name], 1
            except KeyError as exc:
                raise OSError("registry value missing") from exc

        def ExpandEnvironmentStrings(self, value: str) -> str:
            return value

    fake_winreg = _FakeWinreg()
    monkeypatch.setattr(readiness.os, "name", "nt")
    monkeypatch.setattr(readiness, "winreg", fake_winreg)
    monkeypatch.setattr(
        readiness,
        "_INITIAL_CONTROLLED_RUNTIME_ENVIRONMENT",
        {name: None for name in readiness._CONTROLLED_RUNTIME_ENVIRONMENT_NAMES},
    )
    monkeypatch.setattr(
        readiness,
        "_ADOPTED_CONTROLLED_RUNTIME_ENVIRONMENT",
        {},
    )
    for name in readiness._CONTROLLED_RUNTIME_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setattr(
        readiness,
        "load_formal_portfolio_state_ledger",
        lambda _: SimpleNamespace(
            decision_dates=("2026-08-13",),
            ledger_manifest_hash="sha256:" + "a" * 64,
            transition_chain_hash="sha256:" + "b" * 64,
            non_cash_state_day_count=1,
        ),
    )
    monkeypatch.setattr(
        readiness,
        "load_verified_rule_champion_snapshot_history",
        lambda *_, **__: SimpleNamespace(
            manifest_file_hash="sha256:" + "c" * 64,
            manifest_hash="sha256:" + "d" * 64,
            registered_store_id="late-store",
            decision_dates=("2026-08-13",),
            snapshots=(object(),),
        ),
    )
    monkeypatch.setattr(
        readiness,
        "discover_valid_sector_membership",
        lambda **_: sector_path,
    )

    report = readiness.build_readiness_report(
        output_root=output_root,
        training_as_of="2026-08-13T08:30:00+08:00",
    )

    assert report["status"] == "ready"
    assert [item["state"] for item in report["inputs"]] == [
        "ready",
        "ready",
        "ready",
    ]
    assert report["ready_input_ratio"] == "3/3"
    assert os.environ[readiness.PORTFOLIO_LEDGER_ENV] == str(
        ledger_path.resolve()
    )
    assert os.environ[readiness.RULE_HMAC_KEY_ENV] == "late-secret"
    assert "late-secret" not in json.dumps(report, ensure_ascii=False)


def test_readiness_reports_hash_bound_ready_inputs_without_emitting_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    ledger_path = tmp_path / "ledger" / "manifest.json"
    history_path = tmp_path / "history" / "manifest.json"
    sector_path = tmp_path / "sector" / "sidecar.json"
    for path in (ledger_path, history_path, sector_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")
    monkeypatch.setenv(readiness.PORTFOLIO_LEDGER_ENV, str(ledger_path))
    monkeypatch.setenv(readiness.RULE_HISTORY_ENV, str(history_path))
    monkeypatch.setenv(readiness.SECTOR_MEMBERSHIP_ENV, str(sector_path))
    monkeypatch.setenv(readiness.RULE_HMAC_KEY_ENV, "secret-value")
    monkeypatch.setenv(readiness.RULE_STORE_ID_ENV, "controlled-store")

    monkeypatch.setattr(
        readiness,
        "load_formal_portfolio_state_ledger",
        lambda _: SimpleNamespace(
            decision_dates=("2026-08-13",),
            ledger_manifest_hash="sha256:" + "a" * 64,
            transition_chain_hash="sha256:" + "b" * 64,
            non_cash_state_day_count=1,
        ),
    )
    monkeypatch.setattr(
        readiness,
        "load_verified_rule_champion_snapshot_history",
        lambda *_, **__: SimpleNamespace(
            manifest_file_hash="sha256:" + "c" * 64,
            manifest_hash="sha256:" + "d" * 64,
            registered_store_id="controlled-store",
            decision_dates=("2026-08-13",),
            snapshots=(object(),),
        ),
    )
    monkeypatch.setattr(
        readiness,
        "discover_valid_sector_membership",
        lambda **_: sector_path,
    )

    report = readiness.build_readiness_report(
        output_root=output_root,
        training_as_of="2026-08-13T08:30:00+08:00",
    )

    assert report["status"] == "ready"
    assert [item["state"] for item in report["inputs"]] == [
        "ready",
        "ready",
        "ready",
    ]
    assert report["runtime_attestation"]["hmac_key_configured"] is True
    assert report["runtime_attestation"]["registered_store_id_configured"] is True
    assert "secret-value" not in json.dumps(report, ensure_ascii=False)
    declared_hash = report["readiness_hash"]
    body = dict(report)
    del body["readiness_hash"]
    assert declared_hash == readiness._payload_hash(body)


def test_readiness_marks_prospective_wrappers_incompatible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    ledger_path = tmp_path / "formal_prospective" / "portfolio_ledger" / "manifest.json"
    history_path = tmp_path / "formal_prospective" / "rule_champion_history" / "manifest.json"
    sector_path = tmp_path / "formal_prospective" / "pit_sector_membership" / "manifest.json"
    for path in (ledger_path, history_path, sector_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        json.dumps(
            {
                "schema_version": (
                    "prospective-formal-simulated-portfolio-ledger-manifest.v1"
                ),
                "consumer_mode": "prospective_formal_simulation",
            }
        ),
        encoding="utf-8",
    )
    history_path.write_text(
        json.dumps(
            {
                "schema_version": (
                    "prospective-formal-rule-champion-snapshot-history.v1"
                ),
                "consumer_mode": "prospective_formal_simulation",
            }
        ),
        encoding="utf-8",
    )
    sector_path.write_text(
        json.dumps(
            {
                "schema_version": "pit-sector-membership-sidecar-v1",
                "manifest": {
                    "schema_version": (
                        "pit-sector-membership-prospective-manifest-v1"
                    ),
                    "scope": "prospective_only",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(readiness.PORTFOLIO_LEDGER_ENV, str(ledger_path))
    monkeypatch.setenv(readiness.RULE_HISTORY_ENV, str(history_path))
    monkeypatch.setenv(readiness.SECTOR_MEMBERSHIP_ENV, str(sector_path))
    monkeypatch.setenv(readiness.RULE_HMAC_KEY_ENV, "secret-value")
    monkeypatch.setenv(readiness.RULE_STORE_ID_ENV, "controlled-store")

    report = readiness.build_readiness_report(
        output_root=output_root,
        training_as_of="2026-08-28T08:30:00+08:00",
    )

    assert report["status"] == "waiting_for_formal_inputs"
    assert [item["state"] for item in report["inputs"]] == [
        "invalid",
        "invalid",
        "invalid",
    ]
    assert all(
        item["reason"]
        == "prospective_manifest_requires_formal_consumer_publication"
        for item in report["inputs"]
    )
    assert all(
        item["source_lane"] == "prospective_formal_simulation"
        and item["formal_consumer_compatible"] is False
        for item in report["inputs"]
    )
    assert report["formal_oos_allowed"] is False
    assert report["broker_order_allowed"] is False


def test_configured_sector_path_is_authoritative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    ledger_path = tmp_path / "ledger.json"
    history_path = tmp_path / "history.json"
    configured_sector_path = tmp_path / "configured-sector.json"
    discovered_sector_path = tmp_path / "other-sector.json"
    for path in (
        ledger_path,
        history_path,
        configured_sector_path,
        discovered_sector_path,
    ):
        path.write_text(path.name, encoding="utf-8")
    monkeypatch.setenv(readiness.PORTFOLIO_LEDGER_ENV, str(ledger_path))
    monkeypatch.setenv(readiness.RULE_HISTORY_ENV, str(history_path))
    monkeypatch.setenv(
        readiness.SECTOR_MEMBERSHIP_ENV,
        str(configured_sector_path),
    )
    monkeypatch.setenv(readiness.RULE_HMAC_KEY_ENV, "secret-value")
    monkeypatch.setenv(readiness.RULE_STORE_ID_ENV, "controlled-store")
    monkeypatch.setattr(
        readiness,
        "load_formal_portfolio_state_ledger",
        lambda _: SimpleNamespace(
            decision_dates=("2026-08-28",),
            ledger_manifest_hash="sha256:" + "a" * 64,
            transition_chain_hash="sha256:" + "b" * 64,
            non_cash_state_day_count=1,
        ),
    )
    monkeypatch.setattr(
        readiness,
        "load_verified_rule_champion_snapshot_history",
        lambda *_, **__: SimpleNamespace(
            manifest_file_hash="sha256:" + "c" * 64,
            manifest_hash="sha256:" + "d" * 64,
            registered_store_id="controlled-store",
            decision_dates=("2026-08-28",),
            snapshots=(object(),),
        ),
    )
    monkeypatch.setattr(
        readiness,
        "discover_valid_sector_membership",
        lambda **_: discovered_sector_path,
    )

    report = readiness.build_readiness_report(
        output_root=output_root,
        training_as_of="2026-08-28T08:30:00+08:00",
    )

    sector_result = report["inputs"][2]
    assert report["status"] == "waiting_for_formal_inputs"
    assert sector_result["state"] == "invalid"
    assert sector_result["candidate_discovery"] == (
        "configured_path_not_authoritative"
    )
    assert sector_result["path"] == str(configured_sector_path.resolve())
    assert sector_result["formal_consumer_compatible"] is False
