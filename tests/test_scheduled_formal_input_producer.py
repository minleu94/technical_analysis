from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import sys

import pytest

import data_module.formal_daily_input_producer as formal_producer
from data_module.formal_daily_input_producer import OfficialSourceResponse
from data_module.prospective_official_pit_source import (
    OFFICIAL_COMPANY_SOURCE_DEFINITIONS,
)
from scripts.scheduled import run_formal_input_producer_daily as runner
from tests.test_formal_daily_input_producer import (
    _CaptureCalendar,
    _market_db,
    _pit_raw_payloads,
)


WRAPPER = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "scheduled"
    / "run_formal_input_producer_daily.cmd"
)


def test_scheduled_formal_wrapper_uses_durable_publication_and_no_clock_override() -> None:
    text = WRAPPER.read_text(encoding="utf-8").lower()

    assert "run_formal_input_producer_daily.py" in text
    assert "formal_daily_publication_root" in text
    assert "--now" not in text
    assert "--confirm" not in text
    assert "broker" not in text
    assert "formal_daily_paper_trade_ledger_db" in text
    assert "paper_execution_eod_replay" in text
    assert "formal_daily_rule_source_root" in text


def test_missing_source_configuration_is_durable_and_observable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in runner._REQUIRED_SOURCE_ENV:
        monkeypatch.delenv(name, raising=False)
    observed_paths: list[object] = []

    def fake_run(paths: object) -> dict[str, object]:
        observed_paths.append(paths)
        return {
            "status": "candidate_only",
            "formal_ready_input_count": 0,
            "formal_consumer_compatible_count": 0,
            "machine_candidate_input_count": 1,
            "inputs": {
                "pit_candidate": {
                    "status": "machine_verified_candidate",
                    "candidate_only": True,
                }
            },
            "blockers": ["rule_clock_source_missing"],
        }

    monkeypatch.setattr(runner, "run_daily_formal_input_producer", fake_run)
    publication_root = tmp_path / "publication"
    status, exit_code = runner.run_from_environment(
        publication_root=publication_root,
        status_root=publication_root / "scheduler",
    )

    assert exit_code == 2
    assert status["status"] == "candidate_only"
    assert status["formal_ready_input_count"] == 0
    assert status["human_review_required"] is False
    assert len(observed_paths) == 1
    paths = observed_paths[0]
    assert getattr(paths, "clock_manifest") is None
    assert getattr(paths, "universe_symbols") is None
    assert getattr(paths, "owner_acceptance") is None
    configuration = status["scheduled_source_configuration"]
    assert isinstance(configuration, dict)
    assert configuration["missing_rule_sources_do_not_block_pit_capture"] is True
    stored = json.loads(
        (publication_root / "scheduler" / "latest_status.json").read_text(
            encoding="utf-8"
        )
    )
    assert stored == status
    attempt_log = Path(str(status["attempt_log_path"]))
    assert attempt_log == publication_root / "scheduler" / "attempts.jsonl"
    attempts = [
        json.loads(line)
        for line in attempt_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt["status"] == "candidate_only"
    assert attempt["exit_code"] == 2
    assert attempt["working_directory"] == str(Path.cwd().resolve())
    assert attempt["arguments"] == list(sys.argv[1:])
    assert attempt["wrapper_command"][0:3] == ["cmd.exe", "/d", "/c"]


def test_candidate_only_run_is_not_reported_as_scheduled_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in runner._REQUIRED_SOURCE_ENV:
        monkeypatch.setenv(name, str(tmp_path / f"{name.lower()}.json"))
    monkeypatch.setenv("FORMAL_DAILY_OUTPUT_ROOT", str(tmp_path / "candidate"))
    monkeypatch.setenv(
        "FORMAL_DAILY_DEVELOPMENT_OUTPUT_ROOT",
        str(tmp_path / "technical_analysis_development_output"),
    )
    monkeypatch.setenv("FORMAL_DAILY_MARKET_DB", str(tmp_path / "market.sqlite"))
    candidate_result: dict[str, object] = {
        "status": "candidate_only",
        "formal_ready_input_count": 0,
        "formal_consumer_compatible_count": 0,
        "machine_candidate_input_count": 2,
        "candidate_only": True,
        "inputs": {},
        "blockers": ["formal_rule_source_missing"],
    }
    monkeypatch.setattr(
        runner,
        "run_daily_formal_input_producer",
        lambda _paths: candidate_result,
    )
    publication_root = tmp_path / "publication"
    status, exit_code = runner.run_from_environment(
        publication_root=publication_root,
        status_root=publication_root / "scheduler",
    )

    assert exit_code == 2
    assert status["status"] == "candidate_only"
    assert status["schedule_exit_policy"].startswith("zero_only_for_formal_inputs")
    assert status["writes_formal_controlled_paths"] is False
    assert (publication_root / "scheduler" / "latest_status.json").is_file()


def test_runtime_paths_auto_resolve_verified_current_pit_publications(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "FORMAL_DAILY_FORMAL_SECTOR_PATH",
        "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH",
        "FORMAL_DAILY_PIT_EXPECTED_UNIVERSE",
        "BALDR_ML_PIT_EXPECTED_UNIVERSE_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    denominator = tmp_path / "pit_denominator" / "denominator.json"
    sidecar = tmp_path / "pit_sector_membership_formal" / "sidecar.json"
    monkeypatch.setattr(
        runner,
        "_find_current_verified_pit_denominator",
        lambda _root, *, observed: (denominator, "verified_current_natural_day"),
    )
    monkeypatch.setattr(
        runner,
        "_find_current_verified_pit_sidecar",
        lambda _root, *, observed: (sidecar, "verified_current_formal_pit_sidecar"),
    )

    paths = runner._build_paths(
        source_paths={},
        publication_root=tmp_path / "publication",
        observed=datetime(2026, 8, 17, 1, 0, tzinfo=timezone.utc),
    )

    assert paths.pit_expected_universe_path == denominator
    assert paths.formal_sector_path == sidecar


def test_scheduled_source_root_ignores_existing_legacy_formal_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """新 source root 存在時，舊 activation 檔不得遮蔽目前 publication resolver。"""

    legacy_root = tmp_path / "legacy-clock"
    legacy_root.mkdir()
    legacy_paths = {
        (
            "FORMAL_DAILY_FORMAL_SECTOR_PATH",
            "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH",
        ): legacy_root / "sector.json",
        (
            "FORMAL_DAILY_FORMAL_RULE_HISTORY_PATH",
            "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH",
        ): legacy_root / "rule.json",
        (
            "FORMAL_DAILY_FORMAL_LEDGER_PATH",
            "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH",
        ): legacy_root / "ledger.json",
        (
            "FORMAL_DAILY_PIT_EXPECTED_UNIVERSE",
            "BALDR_ML_PIT_EXPECTED_UNIVERSE_PATH",
        ): legacy_root / "universe.json",
    }
    for (primary, legacy), path in legacy_paths.items():
        path.write_text("legacy", encoding="utf-8")
        monkeypatch.setenv(legacy, str(path))
        monkeypatch.delenv(primary, raising=False)
    monkeypatch.setenv("FORMAL_DAILY_RULE_SOURCE_ROOT", str(tmp_path / "source-root"))

    denominator = tmp_path / "current" / "denominator.json"
    sidecar = tmp_path / "current" / "sidecar.json"
    rule_history = tmp_path / "current" / "rule-manifest.json"
    ledger = tmp_path / "current" / "ledger-manifest.json"
    for path in (denominator, sidecar, rule_history, ledger):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("current", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "_find_current_verified_pit_denominator",
        lambda _root, *, observed: (denominator, "verified_current_natural_day"),
    )
    monkeypatch.setattr(
        runner,
        "_find_current_verified_pit_sidecar",
        lambda _root, *, observed: (sidecar, "verified_current_formal_pit_sidecar"),
    )
    monkeypatch.setattr(
        runner,
        "_find_current_verified_formal_rule_history",
        lambda _root, *, observed: (rule_history, "verified_current_formal_rule_history"),
    )
    monkeypatch.setattr(
        runner,
        "_find_latest_verified_formal_ledger",
        lambda _root, *, observed: (ledger, "verified_current_formal_ledger"),
    )

    paths = runner._build_paths(
        source_paths={},
        publication_root=tmp_path / "publication",
        observed=datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc),
    )

    assert paths.pit_expected_universe_path == denominator
    assert paths.formal_sector_path == sidecar
    assert paths.formal_rule_history_path == rule_history
    assert paths.formal_ledger_path == ledger
    configuration = runner._rule_source_configuration(
        source_paths={},
        missing=list(runner._REQUIRED_SOURCE_ENV),
    )
    assert configuration["mode"] == "auto_discovery_failed"
    assert configuration["legacy_environment_policy"] == (
        "ignored_when_formal_daily_rule_source_root_is_configured"
    )
    assert set(configuration["legacy_environment_present"]) == {
        legacy for _, legacy in legacy_paths
    }


def test_rule_source_discovery_failure_reason_is_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """自動解析失敗要保留 bundle／驗證階段／原始原因。"""

    for name in runner._REQUIRED_SOURCE_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FORMAL_DAILY_RULE_SOURCE_ROOT", str(tmp_path / "source-root"))
    discovery_reason = (
        "rule_source_bundle_not_verified:"
        "clock-20260827-v2:universe_identity_FileNotFoundError:"
        "[Errno 2] No such file or directory: universe_identity.json,"
        "clock-20260828:market_revalidation_ValueError:"
        "rule source window hash does not match universe identity"
    )
    monkeypatch.setattr(
        runner,
        "_discover_latest_rule_source_paths",
        lambda **_kwargs: ({}, discovery_reason),
    )
    monkeypatch.setattr(
        runner,
        "run_daily_formal_input_producer",
        lambda _paths: {
            "status": "blocked",
            "formal_ready_input_count": 0,
            "formal_consumer_compatible_count": 0,
            "machine_candidate_input_count": 0,
            "inputs": {},
            "blockers": ["rule_source_bundle_not_verified"],
        },
    )

    publication_root = tmp_path / "publication"
    status, exit_code = runner.run_from_environment(
        publication_root=publication_root,
        status_root=publication_root / "scheduler",
    )

    assert exit_code == 2
    configuration = status["scheduled_source_configuration"]
    assert isinstance(configuration, dict)
    resolution = configuration["rule_source_resolution"]
    assert isinstance(resolution, dict)
    assert resolution["mode"] == "auto_discovery_failed"
    assert resolution["discovery_reason"] == discovery_reason
    stored = json.loads(
        (publication_root / "scheduler" / "latest_status.json").read_text(
            encoding="utf-8"
        )
    )
    stored_resolution = stored["scheduled_source_configuration"]["rule_source_resolution"]
    assert stored_resolution["discovery_reason"] == discovery_reason


def test_formal_runner_defaults_to_isolated_paper_ledger_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "FORMAL_DAILY_PAPER_TRADE_LEDGER_DB",
        "BALDR_ML_PAPER_TRADE_LEDGER_DB_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))

    paths = runner._build_paths(
        source_paths={},
        publication_root=tmp_path / "publication",
        observed=datetime(2026, 8, 17, 1, 0, tzinfo=timezone.utc),
    )

    assert paths.paper_trade_ledger_db_path == runner._default_isolated_paper_trade_ledger_path()
    assert "paper_execution_eod_replay" in str(paths.paper_trade_ledger_db_path)
    assert "FA_Data" not in str(paths.paper_trade_ledger_db_path)


def test_configured_candidate_parents_create_unique_empty_roots_each_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in runner._REQUIRED_SOURCE_ENV:
        monkeypatch.setenv(name, str(tmp_path / f"{name.lower()}.json"))
    candidate_parent = tmp_path / "candidate-parent"
    development_parent = tmp_path / "development-parent"
    monkeypatch.setenv("FORMAL_DAILY_OUTPUT_ROOT", str(candidate_parent))
    monkeypatch.setenv(
        "FORMAL_DAILY_DEVELOPMENT_OUTPUT_ROOT",
        str(development_parent),
    )
    monkeypatch.setattr(
        runner,
        "run_daily_formal_input_producer",
        lambda _paths: {
            "status": "candidate_only",
            "formal_ready_input_count": 0,
            "formal_consumer_compatible_count": 0,
            "machine_candidate_input_count": 1,
            "inputs": {},
            "blockers": [],
        },
    )
    publication_root = tmp_path / "publication"

    first, first_exit = runner.run_from_environment(
        publication_root=publication_root,
        status_root=publication_root / "scheduler",
    )
    second, second_exit = runner.run_from_environment(
        publication_root=publication_root,
        status_root=publication_root / "scheduler",
    )

    assert first_exit == second_exit == 2
    first_candidate = Path(str(first["candidate_output_root"]))
    second_candidate = Path(str(second["candidate_output_root"]))
    first_development = Path(str(first["development_output_root"]))
    second_development = Path(str(second["development_output_root"]))
    assert first_candidate != second_candidate
    assert first_development != second_development
    assert first_candidate.parent == second_candidate.parent == candidate_parent.resolve()
    assert first_development.parent.parent == second_development.parent.parent == development_parent.resolve()
    assert first_candidate.is_dir() and not any(first_candidate.iterdir())
    assert second_candidate.is_dir() and not any(second_candidate.iterdir())
    assert first_development.name == second_development.name == "technical_analysis_development_output"


def test_scheduled_entrypoint_runs_real_pit_producer_without_rule_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in runner._REQUIRED_SOURCE_ENV:
        monkeypatch.delenv(name, raising=False)
    for name in (
        "FORMAL_DAILY_FORMAL_LEDGER_PATH",
        "FORMAL_DAILY_FORMAL_RULE_HISTORY_PATH",
        "FORMAL_DAILY_FORMAL_SECTOR_PATH",
        "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH",
        "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH",
        "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH",
        "BALDR_ML_PAPER_PORTFOLIO_SNAPSHOT_DB_PATH",
        "BALDR_ML_PAPER_TRADE_LEDGER_DB_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(
        "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY",
        "scheduled-pit-test-key",
    )
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "scheduled-pit-test")
    market_path = _market_db(tmp_path)
    monkeypatch.setenv("FORMAL_DAILY_MARKET_DB", str(market_path))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("OUTPUT_ROOT", str(tmp_path / "data-output"))

    captured_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    raw = _pit_raw_payloads()
    responses = {
        OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market].endpoint: OfficialSourceResponse(
            body=raw[market],
            metadata={
                "requested_url": OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market].endpoint,
                "final_url": OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market].endpoint,
                "http_status": 200,
                "content_type": "application/json",
                "http_date": None,
                "http_last_modified": None,
                "captured_at": captured_at.isoformat(),
            },
        )
        for market in ("twse", "tpex")
    }
    observed = captured_at + timedelta(seconds=1)

    def real_producer(paths: object) -> dict[str, object]:
        assert isinstance(paths, runner.DailyFormalInputPaths)
        return formal_producer.run_daily_formal_input_producer(
            paths,
            now=observed,
            calendar=_CaptureCalendar(
                market_path,
                result=None,
                reason="scheduled_fixture_calendar_unavailable",
            ),
            fetch_source=lambda url: responses[url],
        )

    monkeypatch.setattr(runner, "run_daily_formal_input_producer", real_producer)
    publication_root = tmp_path / "publication"

    first, first_exit = runner.run_from_environment(
        publication_root=publication_root,
        status_root=publication_root / "scheduler",
    )
    second, second_exit = runner.run_from_environment(
        publication_root=publication_root,
        status_root=publication_root / "scheduler",
    )

    assert first_exit == second_exit == 2
    for status in (first, second):
        assert status["status"] == "candidate_only"
        assert status["formal_ready_input_count"] == 0
        inputs = status["inputs"]
        assert isinstance(inputs, dict)
        pit = inputs["pit_candidate"]
        assert isinstance(pit, dict)
        assert pit["status"] == "machine_verified_candidate"
        assert pit["consumer_verified"] is True
        assert pit["candidate_only"] is True
        assert pit["formal_consumer_compatible"] is False
        assert Path(str(pit["publication_path"])).is_file()
        assert Path(str(pit["receipt_path"])).is_file()
        assert Path(str(pit["operational_path"])).is_file()
        archive = pit["durable_archive"]
        assert isinstance(archive, dict)
        assert archive["archive_readback_verified"] is True
        assert Path(str(archive["archive_manifest_path"])).is_file()
        assert archive["row_count"] == 4
    assert first["candidate_output_root"] != second["candidate_output_root"]
    preflight = first["preflight"]
    assert isinstance(preflight, dict)
    pit_preflight = preflight["pit_capture"]
    assert isinstance(pit_preflight, dict)
    assert pit_preflight["capture_eligible"] is True
    assert pit_preflight["trading_decision_eligible"] is False
    assert pit_preflight["trading_decision_blockers"] == [
        "pit_official_trading_day_not_proven"
    ]


def test_status_root_cannot_escape_publication_root(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="must be under"):
        runner._status_root(
            tmp_path / "publication",
            tmp_path / "outside",
        )


def test_rule_source_auto_discovery_fails_closed_without_market_db(
    tmp_path: Path,
) -> None:
    """沒有 market DB 時，production discovery 不得跳過 source hash 驗證。"""

    from tests.test_prospective_rule_only_decision import _clock

    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    clock_path, symbols_path, owner_path, score_hash = _clock(fixture_root)
    bundle_root = tmp_path / "source" / "clock-20260817"
    (bundle_root / "clock").mkdir(parents=True)
    (bundle_root / "metadata").mkdir(parents=True)
    (bundle_root / "clock" / "manifest.json").write_bytes(clock_path.read_bytes())
    (bundle_root / "metadata" / "universe_symbols.json").write_bytes(
        symbols_path.read_bytes()
    )
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    (bundle_root / "metadata" / "owner_acceptance.json").write_text(
        json.dumps(owner), encoding="utf-8"
    )
    symbols = json.loads(symbols_path.read_text(encoding="utf-8"))
    identity = {
        "schema_version": "manual-rule-only-universe.v1",
        "symbols": symbols,
        "universe_hash": json.loads(clock_path.read_text(encoding="utf-8"))["universe_hash"],
        "candidate_count": len(symbols),
        "data_as_of_date": "2026-08-14",
        "decision_session": "2026-08-17",
        "session_dates": ["2026-08-13", "2026-08-14"],
        "source_id": "daily_prices",
        "source_window_hash": "sha256:" + "b" * 64,
        "formal_oos_allowed": False,
        "historical_backfill_claimed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
    }
    (bundle_root / "metadata" / "universe_identity.json").write_text(
        json.dumps(identity), encoding="utf-8"
    )
    observed = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)
    discovered, reason = runner._discover_latest_rule_source_paths(
        source_root=tmp_path / "source",
        observed=observed,
    )
    assert discovered == {}
    assert reason == "rule_source_discovery_market_db_not_configured"
    assert owner["score_configuration_hash"] == score_hash


def test_rule_source_auto_discovery_revalidates_scored_universe_against_readonly_db(
    tmp_path: Path,
) -> None:
    """resolver 會重跑既有分數 hash；市場 bytes 變更時不會沿用舊 bundle。"""

    from data_module.prospective_formal_clock import build_clock_manifest
    from development_module.manual_rule_only_decision import (
        _universe_hash,
        load_read_only_daily_price_window,
        rank_rule_only_candidates,
    )
    from tests.test_prospective_rule_only_decision import _clock, _market_db

    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    original_clock, symbols_path, owner_path, score_hash = _clock(fixture_root)
    market_db = _market_db(tmp_path)
    symbols = json.loads(symbols_path.read_text(encoding="utf-8"))
    window = load_read_only_daily_price_window(
        market_db,
        decision_session=datetime(2026, 7, 26).date(),
    )
    candidates = rank_rule_only_candidates(window, eligible_symbols=symbols)
    universe_hash = _universe_hash(candidates)

    clock_payload = json.loads(original_clock.read_text(encoding="utf-8"))
    clock_payload["universe_hash"] = universe_hash
    clock_payload.pop("manifest_hash", None)
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    owner["universe_hash"] = universe_hash
    bundle_root = tmp_path / "source" / "clock-20260817"
    (bundle_root / "clock").mkdir(parents=True)
    (bundle_root / "metadata").mkdir(parents=True)
    (bundle_root / "clock" / "manifest.json").write_text(
        json.dumps(build_clock_manifest(clock_payload)), encoding="utf-8"
    )
    (bundle_root / "metadata" / "universe_symbols.json").write_bytes(
        symbols_path.read_bytes()
    )
    (bundle_root / "metadata" / "owner_acceptance.json").write_text(
        json.dumps(owner), encoding="utf-8"
    )
    identity = {
        "schema_version": "manual-rule-only-universe.v1",
        "symbols": symbols,
        "universe_hash": universe_hash,
        "candidate_count": len(symbols),
        "data_as_of_date": window.data_as_of_date,
        "decision_session": "2026-07-26",
        "session_dates": list(window.session_dates),
        "source_id": "daily_prices",
        "source_window_hash": window.source_hash,
        "formal_oos_allowed": False,
        "historical_backfill_claimed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
    }
    (bundle_root / "metadata" / "universe_identity.json").write_text(
        json.dumps(identity), encoding="utf-8"
    )
    observed = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)
    discovered, reason = runner._discover_latest_rule_source_paths(
        source_root=tmp_path / "source",
        observed=observed,
        market_db=market_db,
    )
    assert reason == "auto_discovered_latest_verified_bundle"
    assert discovered["FORMAL_DAILY_CLOCK_MANIFEST"].is_file()
    assert owner["score_configuration_hash"] == score_hash

    # 即使重封套 clock，symbols 檔改動仍必須失敗；持久 identity 必須綁定
    # 完整 symbols 與 universe hash。
    symbols_file = bundle_root / "metadata" / "universe_symbols.json"
    original_symbols_bytes = symbols_file.read_bytes()
    symbols_file.write_text(json.dumps(["2317", "9999"]), encoding="utf-8")
    rejected_symbols, rejected_symbols_reason = runner._discover_latest_rule_source_paths(
        source_root=tmp_path / "source",
        observed=observed,
        market_db=market_db,
    )
    assert rejected_symbols == {}
    assert rejected_symbols_reason.startswith("rule_source_bundle_not_verified:")
    symbols_file.write_bytes(original_symbols_bytes)

    with sqlite3.connect(market_db) as connection:
        connection.execute(
            'UPDATE daily_prices SET "收盤價" = ? WHERE "證券代號" = ? AND "日期" = ?',
            # 這列在 20-session scoring window 之外，因此分數排序保持不變；
            # source window hash 仍必須因資料內容改變而拒絕。
            ("9999", "2317", "20260701"),
        )
    tampered_window = load_read_only_daily_price_window(
        market_db,
        decision_session=datetime(2026, 7, 26).date(),
    )
    tampered_candidates = rank_rule_only_candidates(
        tampered_window,
        eligible_symbols=symbols,
    )
    assert _universe_hash(tampered_candidates) == universe_hash
    assert tampered_window.source_hash != window.source_hash
    rejected, rejected_reason = runner._discover_latest_rule_source_paths(
        source_root=tmp_path / "source",
        observed=observed,
        market_db=market_db,
    )
    assert rejected == {}
    assert (
        "market_revalidation_ValueError:rule source window hash does not match"
        " universe identity"
    ) in rejected_reason
