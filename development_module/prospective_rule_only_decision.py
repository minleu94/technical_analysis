"""Activation-time Rule-only source producer for a prospective formal clock.

This producer is deliberately separate from the historical formal-observation
lane.  The accepted prospective clock owner decision is the binding authority;
the producer reads only the frozen clock universe and prior daily prices, then
persists a TEMP source plus a controlled-store HMAC artifact for the existing
prospective Rule-history publisher.  It never writes the market database,
Recommendation, Portfolio, evidence ledger, or broker state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, time, timezone
import json
import os
from pathlib import Path
from typing import Any

from zoneinfo import ZoneInfo

from app_module.external_evidence_contracts import ExternalEvidenceDecisionSnapshot
from data_module.prospective_formal_clock import (
    ProspectiveFormalClock,
    file_sha256,
    load_clock_manifest_for_capture,
    payload_hash,
)
from data_module.rule_champion_snapshot_service import (
    PersistedFormalDecisionArtifactRepository,
    RuleChampionSnapshotService,
)
from development_module.manual_rule_only_decision import (
    RULE_POLICY_VERSION,
    RULE_STRATEGY_VERSION,
    TAIPEI_TIME_ZONE,
    ManualRuleOnlyDecisionError,
    _RULE_CONFIGURATION,
    _controlled_store_attestation_config,
    _signed_persisted_decision_artifact,
    _write_new_canonical,
    load_read_only_daily_price_window,
    rank_rule_only_candidates,
    require_development_temp_root,
    sha256_identifier,
)


PROSPECTIVE_RULE_DECISION_SCHEMA_VERSION = (
    "prospective-formal-rule-only-decision-output.v1"
)
PROSPECTIVE_RULE_RESTRICTIONS_SCHEMA_VERSION = (
    "prospective-formal-rule-only-restrictions.v1"
)
PROSPECTIVE_RULE_RUN_DIRECTORY = "prospective_formal_rule_only"
TAIWAN_REGULAR_SESSION_OPEN = time(9, 0)
TAIWAN_REGULAR_SESSION_CLOSE = time(13, 30)


class ProspectiveRuleOnlyDecisionError(ValueError):
    """Prospective activation Rule source failed closed."""


class _SinglePersistedArtifactLoader:
    """Read exactly one canonical artifact written by this producer."""

    def __init__(self, snapshot_id: str, path: Path) -> None:
        self._snapshot_id = snapshot_id
        self._path = path

    def load_registered_formal_decision_bytes(
        self,
        decision_snapshot_id: str,
    ) -> bytes | None:
        if decision_snapshot_id != self._snapshot_id:
            return None
        return self._path.read_bytes()


def produce_prospective_rule_only_decision(
    *,
    development_output_root: str | Path,
    market_db: str | Path,
    clock_manifest_path: str | Path,
    universe_symbols_json: str | Path,
    owner_acceptance_json: str | Path,
    now: datetime | None = None,
) -> dict[str, object]:
    """Create one real activation-time prospective Rule-only source.

    ``now`` exists for focused tests only.  The CLI does not expose a timestamp
    override, so a caller cannot replay or backdate a prospective decision.
    """

    try:
        root = require_development_temp_root(development_output_root)
        observed = _require_taipei_session(now or datetime.now(TAIPEI_TIME_ZONE))
        clock = load_clock_manifest_for_capture(
            Path(clock_manifest_path), now=observed
        )
        _validate_activation_boundary(clock, observed)
        acceptance, acceptance_hash = _load_owner_acceptance(
            Path(owner_acceptance_json), clock
        )
        symbols = _load_clock_symbols(Path(universe_symbols_json))
        window = load_read_only_daily_price_window(
            market_db,
            decision_session=observed.date(),
        )
        max_available = datetime.fromisoformat(window.max_available_timestamp)
        if max_available > observed.astimezone(timezone.utc):
            raise ProspectiveRuleOnlyDecisionError(
                "market_db_timestamp_later_than_decision_time"
            )
        candidates = rank_rule_only_candidates(window, eligible_symbols=symbols)
        if len(candidates) != len(symbols):
            raise ProspectiveRuleOnlyDecisionError(
                "clock_bound_rule_universe_incomplete_t1_history"
            )
        key, store_id = _controlled_store_attestation_config()
        return _persist_prospective_source(
            root=root,
            clock=clock,
            acceptance=acceptance,
            acceptance_hash=acceptance_hash,
            symbols=symbols,
            universe_symbols_path=Path(universe_symbols_json).expanduser().resolve(),
            observed=observed,
            window=window,
            candidates=candidates,
            store_id=store_id,
            key=key,
        )
    except (OSError, TypeError, ValueError, KeyError) as error:
        if isinstance(error, ProspectiveRuleOnlyDecisionError):
            raise
        if isinstance(error, ManualRuleOnlyDecisionError):
            raise ProspectiveRuleOnlyDecisionError(str(error)) from error
        raise ProspectiveRuleOnlyDecisionError(str(error)) from error


def _persist_prospective_source(
    *,
    root: Path,
    clock: ProspectiveFormalClock,
    acceptance: Mapping[str, object],
    acceptance_hash: str,
    symbols: tuple[str, ...],
    universe_symbols_path: Path,
    observed: datetime,
    window: Any,
    candidates: Sequence[Any],
    store_id: str,
    key: bytes,
) -> dict[str, object]:
    selected = candidates[0]
    observed_timestamp = observed.isoformat(timespec="microseconds")
    run_id = f"prospective-rule-only-{observed.strftime('%Y%m%dT%H%M%S%f')}"
    source_manifest: dict[str, object] = {
        "schema_version": PROSPECTIVE_RULE_DECISION_SCHEMA_VERSION,
        "run_id": run_id,
        "clock_id": clock.clock_id,
        "clock_manifest_hash": clock.manifest_hash,
        "owner_decision_id": clock.payload["owner_decision_id"],
        "owner_acceptance_hash": acceptance_hash,
        "decision_timestamp": observed_timestamp,
        "decision_session": observed.date().isoformat(),
        "data_as_of_date": window.data_as_of_date,
        "max_available_timestamp": window.max_available_timestamp,
        "source_versions": {"daily_prices": window.source_hash},
        "source_window_sessions": list(window.session_dates),
        "candidate_count": len(candidates),
        "candidate_scores": [
            {
                "symbol": candidate.symbol,
                "latest_date": candidate.latest_date,
                "score_bp": candidate.score_bp,
                "trend_bp": candidate.trend_bp,
                "momentum_bp": candidate.momentum_bp,
                "volume_delta_bp": candidate.volume_delta_bp,
            }
            for candidate in candidates
        ],
        "selected_candidate": selected.to_dict(),
        "score_configuration": _RULE_CONFIGURATION,
        "universe": {
            "symbol_count": len(symbols),
            "universe_hash": clock.payload["universe_hash"],
            "symbols_file": str(universe_symbols_path),
            "symbols_file_hash": file_sha256(universe_symbols_path),
        },
        "safety": {
            "formal_rule_only": True,
            "formal_oos_allowed": False,
            "formal_evidence_credit_authorized": False,
            "production_blend_alpha_bp": 0,
            "promotion_eligible": False,
            "broker_order_allowed": False,
            "market_database_write_performed": False,
            "recommendation_repository_write_performed": False,
            "portfolio_repository_write_performed": False,
            "evidence_ledger_write_performed": False,
            "scheduler_used": False,
            "ml_used": False,
            "training_used": False,
            "production_action_allowed": False,
        },
    }
    source_lineage_hash = sha256_identifier(source_manifest)
    source_lineage_artifact_id = (
        f"decision-output:{run_id}:{source_lineage_hash}"
    )
    restrictions_hash = sha256_identifier(
        {
            "schema_version": PROSPECTIVE_RULE_RESTRICTIONS_SCHEMA_VERSION,
            "clock_id": clock.clock_id,
            "clock_manifest_hash": clock.manifest_hash,
            "owner_decision_id": clock.payload["owner_decision_id"],
            "owner_acceptance_hash": acceptance_hash,
            "allowed_source_ids": ["daily_prices"],
            "used_source_ids": ["daily_prices"],
            "rule_configuration_hash": sha256_identifier(_RULE_CONFIGURATION),
            "formal_oos_allowed": False,
            "formal_evidence_credit_authorized": False,
            "production_blend_alpha_bp": 0,
            "scheduler_allowed": False,
            "training_allowed": False,
            "promotion_allowed": False,
            "unblind_allowed": False,
            "broker_order_allowed": False,
        }
    )
    decision_snapshot_id = f"decision:{run_id}:{selected.symbol}"
    persisted_artifact = _signed_persisted_decision_artifact(
        decision_snapshot_id=decision_snapshot_id,
        decision_timestamp=observed_timestamp,
        symbol=selected.symbol,
        rule_score_bp=selected.score_bp,
        source_lineage_artifact_id=source_lineage_artifact_id,
        source_lineage_hash=source_lineage_hash,
        restrictions_hash=restrictions_hash,
        registered_store_id=store_id,
        key=key,
    )

    run_directory = root / PROSPECTIVE_RULE_RUN_DIRECTORY / run_id
    if run_directory.exists():
        raise ProspectiveRuleOnlyDecisionError("prospective_rule_run_id_already_exists")
    run_directory.mkdir(parents=True, exist_ok=False)
    source_path = run_directory / "decision_output.json"
    artifact_path = run_directory / "formal_rule_decision_rank_1.json"
    champion_path = run_directory / "rule_champion_snapshot.json"
    snapshot_path = run_directory / "manual_observed.json"
    requests_path = run_directory / "requests.json"
    artifacts_path = run_directory / "artifacts.json"
    _write_new_canonical(source_path, source_manifest)
    _write_new_canonical(artifact_path, persisted_artifact)

    repository = PersistedFormalDecisionArtifactRepository(
        _SinglePersistedArtifactLoader(decision_snapshot_id, artifact_path)
    )
    champion = RuleChampionSnapshotService().build(
        strategy_version=RULE_STRATEGY_VERSION,
        policy_version=RULE_POLICY_VERSION,
        score_configuration_hash=str(acceptance["score_configuration_hash"]),
        universe_hash=str(clock.payload["universe_hash"]),
        selection_capacity=1,
        repository=repository,
        decision_snapshot_ids=(decision_snapshot_id,),
    )
    _write_new_canonical(champion_path, champion.to_manifest())

    snapshot_payload = ExternalEvidenceDecisionSnapshot.create(
        decision_timestamp=observed_timestamp,
        data_as_of_date=window.data_as_of_date,
        max_available_timestamp=window.max_available_timestamp,
        source_versions={"daily_prices": window.source_hash},
        strategy_version=RULE_STRATEGY_VERSION,
        policy_version=RULE_POLICY_VERSION,
        rule_champion_snapshot_id=champion.champion_snapshot_family_id,
        universe_id=clock.clock_id,
        universe_hash=str(clock.payload["universe_hash"]),
        symbol=selected.symbol,
        score_bp=selected.score_bp,
        score_status="observed",
        rank=1,
        action_or_prompt="RULE_ONLY_OBSERVED_NO_TRADE",
        why=(
            f"20個有效觀測相對均價 {selected.trend_bp}bp",
            f"20個有效觀測動能 {selected.momentum_bp}bp",
            f"相對平均成交量 {selected.volume_delta_bp}bp",
        ),
        why_not=(),
        risk_reasons=(
            "僅限 prospective Rule-only 觀測，不構成交易或持倉動作",
            "僅使用決策日前完整日資料；缺 close 的無成交列未前填",
        ),
        market_regime="not_used_by_rule_only_profile",
        liquidity_state="daily_volume_ranked_not_execution_liquidity",
        restriction_state="prospective_rule_only_no_trade_no_formal_credit",
        evidence_tier="prospective_formal_rule_only_source",
        missing_sources=(),
        degraded_reasons=(),
        parent_artifact_ids=(
            source_lineage_artifact_id,
            f"rule-champion:{champion.champion_snapshot_family_id}:{champion.content_hash}",
        ),
        capture_kind="manual_observed",
    ).to_dict()
    snapshot_payload.pop("snapshot_id", None)
    _write_new_canonical(snapshot_path, snapshot_payload)
    _write_new_canonical_value(
        requests_path,
        [
            {
                "decision_date": observed.date().isoformat(),
                "decision_snapshot_ids": [decision_snapshot_id],
            }
        ],
    )
    _write_new_canonical_value(
        artifacts_path, {decision_snapshot_id: persisted_artifact}
    )

    return {
        "status": "prospective_rule_only_source_created",
        "write_performed": True,
        "run_id": run_id,
        "clock_id": clock.clock_id,
        "clock_manifest_hash": clock.manifest_hash,
        "decision_session": observed.date().isoformat(),
        "decision_timestamp": observed_timestamp,
        "data_as_of_date": window.data_as_of_date,
        "candidate_count": len(candidates),
        "symbol": selected.symbol,
        "score_bp": selected.score_bp,
        "strategy_version": RULE_STRATEGY_VERSION,
        "policy_version": RULE_POLICY_VERSION,
        "score_configuration_hash": str(acceptance["score_configuration_hash"]),
        "universe_hash": str(clock.payload["universe_hash"]),
        "registered_store_id": store_id,
        "decision_output_json": str(source_path),
        "formal_rule_decision_json": str(artifact_path),
        "rule_champion_snapshot_json": str(champion_path),
        "manual_observed_json": str(snapshot_path),
        "requests_json": str(requests_path),
        "artifacts_json": str(artifacts_path),
        "source_lineage_hash": source_lineage_hash,
        "restrictions_hash": restrictions_hash,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "secret_values_emitted": False,
    }


def _require_taipei_session(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProspectiveRuleOnlyDecisionError("decision_clock_requires_timezone")
    observed = value.astimezone(TAIPEI_TIME_ZONE)
    if not TAIWAN_REGULAR_SESSION_OPEN <= observed.timetz().replace(
        tzinfo=None
    ) <= TAIWAN_REGULAR_SESSION_CLOSE:
        raise ProspectiveRuleOnlyDecisionError("outside_taiwan_regular_session")
    return observed


def _validate_activation_boundary(
    clock: ProspectiveFormalClock,
    observed: datetime,
) -> None:
    if observed.date() != clock.activation_trading_day:
        raise ProspectiveRuleOnlyDecisionError("prospective_rule_session_mismatch")
    decision_time = time.fromisoformat(str(clock.payload["decision_time"]))
    if observed.timetz().replace(tzinfo=None) < decision_time:
        raise ProspectiveRuleOnlyDecisionError("before_clock_decision_boundary")


def _load_owner_acceptance(
    path: Path,
    clock: ProspectiveFormalClock,
) -> tuple[dict[str, object], str]:
    resolved = path.expanduser().resolve()
    try:
        payload: Any = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProspectiveRuleOnlyDecisionError("owner_acceptance_unreadable") from error
    if not isinstance(payload, dict):
        raise ProspectiveRuleOnlyDecisionError("owner_acceptance_invalid")
    expected = {
        "decision_id": clock.payload["owner_decision_id"],
        "accepted_strategy_version": clock.payload["strategy_version"],
        "accepted_policy_version": clock.payload["policy_version"],
        "policy_hash": clock.payload["policy_hash"],
        "universe_hash": clock.payload["universe_hash"],
        "score_configuration_hash": _required_clock_score_hash(payload, clock),
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise ProspectiveRuleOnlyDecisionError(
                f"owner_acceptance_{field}_mismatch"
            )
    return payload, file_sha256(resolved)


def _required_clock_score_hash(
    acceptance: Mapping[str, object],
    clock: ProspectiveFormalClock,
) -> str:
    value = acceptance.get("score_configuration_hash")
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ProspectiveRuleOnlyDecisionError("owner_acceptance_score_configuration_hash_invalid")
    if len(value) != 71 or any(char not in "0123456789abcdef" for char in value[7:]):
        raise ProspectiveRuleOnlyDecisionError("owner_acceptance_score_configuration_hash_invalid")
    if value != "sha256:1a11086fb3551ba24acb58e4f880eafa49c1e49fc87187ff8e7be02999e891c4":
        raise ProspectiveRuleOnlyDecisionError("owner_acceptance_score_configuration_not_frozen_champion")
    if value != sha256_identifier(_RULE_CONFIGURATION):
        raise ProspectiveRuleOnlyDecisionError("rule_configuration_hash_mismatch")
    if clock.payload["strategy_version"] != RULE_STRATEGY_VERSION:
        raise ProspectiveRuleOnlyDecisionError("prospective_clock_strategy_mismatch")
    if clock.payload["policy_version"] != RULE_POLICY_VERSION:
        raise ProspectiveRuleOnlyDecisionError("prospective_clock_policy_mismatch")
    return value


def _load_clock_symbols(path: Path) -> tuple[str, ...]:
    resolved = path.expanduser().resolve()
    try:
        payload: Any = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProspectiveRuleOnlyDecisionError("clock_universe_symbols_unreadable") from error
    if not isinstance(payload, list) or not payload:
        raise ProspectiveRuleOnlyDecisionError("clock_universe_symbols_invalid")
    symbols = tuple(str(item).strip() for item in payload)
    if any(not item for item in symbols) or symbols != tuple(sorted(set(symbols))):
        raise ProspectiveRuleOnlyDecisionError("clock_universe_symbols_not_sorted_unique")
    return symbols


def _write_new_canonical_value(path: Path, payload: object) -> None:
    data = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProspectiveRuleOnlyDecisionError(
            "immutable_artifact_already_exists"
        ) from error
