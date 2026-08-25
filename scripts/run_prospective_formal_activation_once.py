"""Run one low-CPU prospective formal activation and strict readiness handoff.

The command is intentionally one-shot.  It uses the immutable v3 clock, the
already staged official raw custody, the accepted Rule Champion identity, and
the real T-1 market database state.  It never starts a watcher or a model
pipeline and it refuses to overwrite any formal output.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import date, datetime, time
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Sequence
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.formal_simulated_portfolio_ledger import (  # noqa: E402
    ZERO_CHAIN_HASH,
    append_simulated_transition,
    build_simulated_transition,
)
from data_module.prospective_capture_readiness import (  # noqa: E402
    ProspectiveCaptureReadinessError,
    build_prospective_capture_readiness_report,
    write_immutable_capture_readiness_report,
)
from data_module.prospective_formal_clock import (  # noqa: E402
    ProspectiveFormalClock,
    file_sha256,
    load_clock_manifest_for_capture,
    payload_hash,
)
from data_module.prospective_official_pit_source import (  # noqa: E402
    build_official_first_seen_capture,
)
from data_module.prospective_pit_sector_membership import (  # noqa: E402
    capture_prospective_pit_sector_membership,
)
from data_module.prospective_rule_champion_publisher import (  # noqa: E402
    JsonPersistedFormalArtifactLoader,
    ProspectiveRuleSnapshotRequest,
    publish_prospective_rule_history,
)
from data_module.prospective_simulated_ledger_manifest import (  # noqa: E402
    build_prospective_simulated_ledger_manifest,
    load_clock_for_ledger_manifest,
    publish_prospective_simulated_ledger_manifest,
)
from development_module.prospective_rule_only_decision import (  # noqa: E402
    produce_prospective_rule_only_decision,
)
from ml_module.allocation_contracts import (  # noqa: E402
    AllocationWeightContract,
    CausalPortfolioState,
)


TAIPEI = ZoneInfo("Asia/Taipei")
PIT_TIME = time(8, 30)
DECISION_TIME = time(9, 0)
PORTFOLIO_WEIGHT_BP = 1_500
PORTFOLIO_COST_BP = 25


class ProspectiveActivationOnceError(ValueError):
    """One-shot activation failed closed."""


def run_activation_once(
    *,
    output_root: Path,
    development_output_root: Path,
    market_db: Path,
    calibration_policy: Path,
    clock_manifest: Path,
    universe_symbols: Path,
    owner_acceptance: Path,
    source_metadata: Path,
    pit_staging_package: Path,
    twse_raw: Path,
    tpex_raw: Path,
    now: datetime | None = None,
) -> dict[str, object]:
    """Capture all three formal inputs and publish strict readiness once."""

    observed = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    clock = load_clock_manifest_for_capture(clock_manifest, now=observed)
    _require_activation_boundary(clock, observed)
    symbols = _read_symbols(universe_symbols)
    paths = _formal_paths(output_root)
    _refuse_existing_formal_outputs(paths)
    _require_market_t1(market_db, clock.activation_trading_day)

    # Produce the owner-bound Rule source first.  It writes only TEMP source
    # custody; no formal path is touched until the HMAC artifact is ready.
    rule_source = produce_prospective_rule_only_decision(
        development_output_root=development_output_root,
        market_db=market_db,
        clock_manifest_path=clock_manifest,
        universe_symbols_json=universe_symbols,
        owner_acceptance_json=owner_acceptance,
        now=observed,
    )

    pit_capture = _build_pit_capture(
        clock=clock,
        symbols=symbols,
        source_metadata=source_metadata,
        pit_staging_package=pit_staging_package,
        twse_raw=twse_raw,
        tpex_raw=tpex_raw,
        now=observed,
    )
    pit_time = _clock_timestamp(clock, "pit_decision_time")
    pit_result = capture_prospective_pit_sector_membership(
        clock=clock,
        output_path=paths["pit"],
        decision_timestamp=pit_time,
        now=observed,
        rows=pit_capture.rows,
        source_registry=pit_capture.source_registry,
        expected_symbols=symbols,
    )

    requests = _read_requests(Path(str(rule_source["requests_json"])))
    artifacts = JsonPersistedFormalArtifactLoader(
        Path(str(rule_source["artifacts_json"]))
    )
    from data_module.rule_champion_snapshot_service import (  # noqa: PLC0415
        PersistedFormalDecisionArtifactRepository,
    )

    repository = PersistedFormalDecisionArtifactRepository(artifacts)
    rule_result = publish_prospective_rule_history(
        clock=clock,
        output_path=paths["rule"],
        now=observed,
        strategy_version=str(rule_source["strategy_version"]),
        policy_version=str(rule_source["policy_version"]),
        score_configuration_hash=str(rule_source["score_configuration_hash"]),
        universe_hash=str(rule_source["universe_hash"]),
        selection_capacity=1,
        repository=repository,
        requests=requests,
    )

    previous_trading_day = _previous_trading_day(clock.activation_trading_day)
    input_state = CausalPortfolioState.create(
        as_of_date=previous_trading_day.isoformat(),
        weights=AllocationWeightContract(positions_bp=(), cash_bp=10_000),
        weekly_turnover_used_bp=0,
    )
    selected_symbol = str(rule_source["symbol"])
    desired_weights = AllocationWeightContract(
        positions_bp=((selected_symbol, PORTFOLIO_WEIGHT_BP),),
        cash_bp=10_000 - PORTFOLIO_WEIGHT_BP,
    )
    feature_input_hash = payload_hash(
        {
            "schema_version": "prospective-formal-portfolio-feature-input.v1",
            "clock_id": clock.clock_id,
            "clock_manifest_hash": clock.manifest_hash,
            "rule_history_file_hash": rule_result.manifest_file_hash,
            "pit_sidecar_file_hash": pit_result.sidecar_file_hash,
            "daily_prices_source_hash": rule_source["source_lineage_hash"],
            "decision_date": clock.activation_trading_day.isoformat(),
            "previous_trading_day": previous_trading_day.isoformat(),
            "ml_used": False,
            "formal_oos_allowed": False,
        }
    )
    transition = build_simulated_transition(
        clock=clock,
        decision_date=clock.activation_trading_day.isoformat(),
        decision_at=_clock_timestamp(clock, "decision_time"),
        previous_trading_day=previous_trading_day.isoformat(),
        input_state=input_state,
        desired_weights=desired_weights,
        feature_input_hash=feature_input_hash,
        estimated_cost_bp=PORTFOLIO_COST_BP,
        output_weekly_turnover_used_bp=PORTFOLIO_WEIGHT_BP,
        previous_chain_hash=ZERO_CHAIN_HASH,
    )
    append_simulated_transition(paths["portfolio_sqlite"], transition)
    ledger_clock = load_clock_for_ledger_manifest(clock_manifest, now=observed)
    ledger_manifest = build_prospective_simulated_ledger_manifest(
        clock=ledger_clock,
        sqlite_path=paths["portfolio_sqlite"],
        manifest_path=paths["portfolio"],
        now=observed,
    )
    ledger_file_hash = publish_prospective_simulated_ledger_manifest(
        paths["portfolio"], ledger_manifest
    )

    decision_timestamp = str(rule_result.decision_dates[0])
    # The publisher result intentionally exposes only dates; read the
    # canonical snapshot timestamp from the already-written source custody.
    rule_snapshot_timestamp = _read_rule_timestamp(
        Path(str(rule_source["rule_champion_snapshot_json"]))
    )
    readiness = build_prospective_capture_readiness_report(
        clock_manifest_path=clock_manifest,
        calibration_policy_path=calibration_policy,
        decision_timestamp=rule_snapshot_timestamp,
        pit_decision_timestamp=pit_time,
        now=observed,
        expected_symbols=symbols,
        portfolio_ledger_manifest_path=paths["portfolio"],
        rule_history_path=paths["rule"],
        pit_sector_membership_path=paths["pit"],
        active_clock=True,
    )
    readiness_file_hash = write_immutable_capture_readiness_report(
        paths["readiness"], readiness
    )
    if readiness.get("status") != "ready":
        raise ProspectiveActivationOnceError(
            "strict readiness did not reach ready after all three manifests"
        )
    return {
        "status": "complete",
        "clock_id": clock.clock_id,
        "clock_manifest_hash": clock.manifest_hash,
        "pit_manifest": str(paths["pit"]),
        "pit_manifest_file_hash": pit_result.sidecar_file_hash,
        "rule_manifest": str(paths["rule"]),
        "rule_manifest_file_hash": rule_result.manifest_file_hash,
        "portfolio_manifest": str(paths["portfolio"]),
        "portfolio_manifest_file_hash": ledger_file_hash,
        "readiness": str(paths["readiness"]),
        "readiness_file_hash": readiness_file_hash,
        "decision_timestamp": rule_snapshot_timestamp,
        "pit_decision_timestamp": pit_time,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "secret_values_emitted": False,
    }


def _build_pit_capture(
    *,
    clock: ProspectiveFormalClock,
    symbols: tuple[str, ...],
    source_metadata: Path,
    pit_staging_package: Path,
    twse_raw: Path,
    tpex_raw: Path,
    now: datetime,
):
    metadata = _read_object(source_metadata)
    license_ids, license_urls, publication_at = _source_metadata(metadata)
    staged = _read_object(pit_staging_package)
    source_registry = staged.get("source_registry")
    if not isinstance(source_registry, list) or not source_registry:
        raise ProspectiveActivationOnceError("PIT staging source registry is invalid")
    available_values = [
        datetime.fromisoformat(str(item["available_at"]))
        for item in source_registry
        if isinstance(item, Mapping) and isinstance(item.get("available_at"), str)
    ]
    if len(available_values) != 2:
        raise ProspectiveActivationOnceError("PIT source available_at lineage is incomplete")
    available_at = max(available_values)
    raw_payloads = {"twse": twse_raw.read_bytes(), "tpex": tpex_raw.read_bytes()}
    return build_official_first_seen_capture(
        raw_payloads=raw_payloads,
        license_ids=license_ids,
        license_urls=license_urls,
        publication_at=publication_at,
        expected_symbols=symbols,
        clock_id=clock.clock_id,
        clock_manifest_hash=clock.manifest_hash,
        universe_hash=str(clock.payload["universe_hash"]),
        available_at=available_at,
        effective_from=clock.activation_trading_day,
        now=now,
    )


def _formal_paths(output_root: Path) -> dict[str, Path]:
    root = output_root.expanduser().resolve()
    paths = {
        "pit": root / "pit_sector_membership" / "manifest.json",
        "rule": root / "rule_champion_history" / "manifest.json",
        "portfolio": root / "portfolio_ledger" / "manifest.json",
        "portfolio_sqlite": root / "portfolio_ledger" / "simulated_portfolio.sqlite",
        "readiness": root / "readiness" / "strict_readiness.json",
    }
    if any(not path.parent.is_dir() for path in paths.values()):
        raise ProspectiveActivationOnceError("formal output parent directory is missing")
    return paths


def _refuse_existing_formal_outputs(paths: Mapping[str, Path]) -> None:
    for name, path in paths.items():
        if path.exists():
            raise ProspectiveActivationOnceError(f"formal_output_already_exists:{name}")


def _require_activation_boundary(clock: ProspectiveFormalClock, now: datetime) -> None:
    if now.date() != clock.activation_trading_day:
        raise ProspectiveActivationOnceError("activation_date_mismatch")
    if now.timetz().replace(tzinfo=None) < DECISION_TIME:
        raise ProspectiveActivationOnceError("before_rule_portfolio_boundary")


def _require_market_t1(path: Path, activation_day: date) -> None:
    previous = _previous_trading_day(activation_day).strftime("%Y%m%d")
    try:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only = ON")
        row = connection.execute(
            "SELECT 1 FROM daily_prices WHERE TRIM(CAST([日期] AS TEXT)) IN (?, ?) LIMIT 1",
            (previous, f"{previous[:4]}-{previous[4:6]}-{previous[6:]}"),
        ).fetchone()
    except (OSError, sqlite3.Error) as error:
        raise ProspectiveActivationOnceError("market_db_t1_read_failed") from error
    finally:
        try:
            connection.close()
        except UnboundLocalError:
            pass
    if row is None:
        raise ProspectiveActivationOnceError("market_db_t1_state_missing")


def _previous_trading_day(activation_day: date) -> date:
    # v3 calendar explicitly reserved 2026-08-26 as the complete preparation
    # day; no historical fallback or calendar inference is permitted here.
    previous = activation_day.fromordinal(activation_day.toordinal() - 1)
    if activation_day.isoformat() == "2026-08-27" and previous.isoformat() != "2026-08-26":
        raise ProspectiveActivationOnceError("v3_t1_calendar_contract_invalid")
    return previous


def _clock_timestamp(clock: ProspectiveFormalClock, field: str) -> str:
    value = clock.payload.get(field)
    if field == "pit_decision_time":
        value = clock.payload.get(field, clock.payload["decision_time"])
    if not isinstance(value, str):
        raise ProspectiveActivationOnceError(f"clock_{field}_invalid")
    return f"{clock.activation_trading_day.isoformat()}T{value}+08:00"


def _read_rule_timestamp(path: Path) -> str:
    value = _read_object(path)
    timestamp = value.get("decision_timestamp")
    if not isinstance(timestamp, str) or not timestamp:
        raise ProspectiveActivationOnceError("Rule snapshot decision timestamp missing")
    return timestamp


def _read_requests(path: Path) -> tuple[ProspectiveRuleSnapshotRequest, ...]:
    value = _read_json(path)
    if not isinstance(value, list) or not value:
        raise ProspectiveActivationOnceError("Rule requests are invalid")
    result: list[ProspectiveRuleSnapshotRequest] = []
    for item in value:
        if not isinstance(item, dict):
            raise ProspectiveActivationOnceError("Rule request row is invalid")
        ids = item.get("decision_snapshot_ids")
        if not isinstance(item.get("decision_date"), str) or not isinstance(ids, list):
            raise ProspectiveActivationOnceError("Rule request fields are invalid")
        result.append(
            ProspectiveRuleSnapshotRequest(
                decision_date=str(item["decision_date"]),
                decision_snapshot_ids=tuple(str(item_id) for item_id in ids),
            )
        )
    return tuple(result)


def _read_symbols(path: Path) -> tuple[str, ...]:
    value = _read_json(path)
    if not isinstance(value, list) or not value:
        raise ProspectiveActivationOnceError("clock universe symbols are invalid")
    symbols = tuple(str(item).strip() for item in value)
    if any(not item for item in symbols) or symbols != tuple(sorted(set(symbols))):
        raise ProspectiveActivationOnceError("clock universe symbols are not sorted unique")
    return symbols


def _source_metadata(
    value: dict[str, object],
) -> tuple[dict[str, str], dict[str, str], dict[str, datetime]]:
    license_ids: dict[str, str] = {}
    license_urls: dict[str, str] = {}
    publication_at: dict[str, datetime] = {}
    for market, item in value.items():
        if not isinstance(item, dict):
            raise ProspectiveActivationOnceError("PIT source metadata entry is invalid")
        license_id = item.get("license_id")
        license_url = item.get("license_url")
        publication = item.get("publication_at")
        if (
            not isinstance(license_id, str)
            or not license_id.strip()
            or not isinstance(license_url, str)
            or not license_url.strip()
            or not isinstance(publication, str)
            or not publication.strip()
        ):
            raise ProspectiveActivationOnceError("PIT source metadata is incomplete")
        license_ids[market] = license_id
        license_urls[market] = license_url
        publication_at[market] = datetime.fromisoformat(publication)
    return license_ids, license_urls, publication_at


def _read_object(path: Path) -> dict[str, object]:
    value = _read_json(path)
    if not isinstance(value, dict):
        raise ProspectiveActivationOnceError(f"JSON object expected: {path}")
    return value


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProspectiveActivationOnceError(f"JSON unreadable: {path}") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--development-output-root", type=Path, required=True)
    parser.add_argument("--market-db", type=Path, required=True)
    parser.add_argument("--calibration-policy", type=Path, required=True)
    parser.add_argument("--clock-manifest", type=Path, required=True)
    parser.add_argument("--universe-symbols", type=Path, required=True)
    parser.add_argument("--owner-acceptance", type=Path, required=True)
    parser.add_argument("--source-metadata", type=Path, required=True)
    parser.add_argument("--pit-staging-package", type=Path, required=True)
    parser.add_argument("--twse-raw", type=Path, required=True)
    parser.add_argument("--tpex-raw", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_activation_once(
            output_root=args.output_root,
            development_output_root=args.development_output_root,
            market_db=args.market_db,
            calibration_policy=args.calibration_policy,
            clock_manifest=args.clock_manifest,
            universe_symbols=args.universe_symbols,
            owner_acceptance=args.owner_acceptance,
            source_metadata=args.source_metadata,
            pit_staging_package=args.pit_staging_package,
            twse_raw=args.twse_raw,
            tpex_raw=args.tpex_raw,
        )
    except (OSError, TypeError, ValueError, KeyError, sqlite3.Error) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "formal_oos_allowed": False,
                    "production_blend_alpha_bp": 0,
                    "promotion_eligible": False,
                    "broker_order_allowed": False,
                    "secret_values_emitted": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())
