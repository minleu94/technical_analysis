"""Foreground-only Rule-only decision source for the formal observation lane.

This module deliberately creates no recommendation, portfolio, market-database,
or evidence-ledger record.  It provides the missing *source artifact* that an
owner may manually produce during the bound Taiwan trading session, then hand
to the existing shadow-only evidence capture command.

The decision is intentionally small and auditable: it ranks securities from a
read-only ``daily_prices`` window ending before the decision session.  It does
not use ML, intraday data, fundamentals, candidate sources, or a scheduler.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from app_module.external_evidence_contracts import ExternalEvidenceDecisionSnapshot
from app_module.rule_champion_snapshot_service import (
    PersistedFormalDecisionArtifactRepository,
    RuleChampionSnapshotService,
)
from development_module.formal_observation_lane import (
    FormalObservationLaneDecision,
    load_formal_observation_lane_decision,
)


DEVELOPMENT_OUTPUT_ROOT_NAME = "technical_analysis_development_output"
MANUAL_CONFIRMATION = "produce-manual-rule-only-decision"
TAIPEI_TIME_ZONE = ZoneInfo("Asia/Taipei")
TAIWAN_REGULAR_SESSION_OPEN = time(9, 0)
TAIWAN_REGULAR_SESSION_CLOSE = time(13, 30)

RULE_STRATEGY_VERSION = "manual-rule-only-daily-rank-v1"
RULE_POLICY_VERSION = "foreground-owner-bound-v1"
RULE_SOURCE_ID = "daily_prices"
_HMAC_KEY_ENV = "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY"
_STORE_ID_ENV = "RULE_CHAMPION_CONTROLLED_STORE_ID"

_RULE_CONFIGURATION: dict[str, object] = {
    "schema_version": "manual-rule-only-daily-rank-config.v1",
    "source_ids": [RULE_SOURCE_ID],
    "look_ahead_boundary": "daily_prices.date < decision_session_date",
    "minimum_history_sessions": 20,
    "source_window_sessions": 60,
    "ranking": "score_desc_then_symbol_asc",
    "score_basis": "integer_basis_points",
    "score_formula": {
        "base_bp": 5000,
        "trend_component": "clamp(latest_close_vs_20_session_average_bp,-2500,2500)",
        "momentum_component": "clamp(latest_close_vs_20_session_oldest_bp,-2500,2500)",
        "volume_component": "clamp(latest_volume_vs_20_session_average_bp_div_2,-1000,1000)",
        "final": "clamp(base_plus_components,0,10000)",
    },
    "selection_capacity": 1,
    "action": "RULE_ONLY_OBSERVED_NO_TRADE",
    "ml_used": False,
    "scheduler_allowed": False,
    "market_database_write_allowed": False,
    "formal_evidence_credit_authorized": False,
    "production_blend_alpha_bp": 0,
}


class ManualRuleOnlyDecisionError(ValueError):
    """A fail-closed validation error safe to present to an operator."""


@dataclass(frozen=True)
class RuleOnlyCandidate:
    """One deterministic Rule-only ranking row, represented only in bp/Decimal."""

    symbol: str
    latest_date: str
    score_bp: int
    trend_bp: int
    momentum_bp: int
    volume_delta_bp: int
    source_window: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "latest_date": self.latest_date,
            "score_bp": self.score_bp,
            "trend_bp": self.trend_bp,
            "momentum_bp": self.momentum_bp,
            "volume_delta_bp": self.volume_delta_bp,
            "source_window": [dict(row) for row in self.source_window],
        }


@dataclass(frozen=True)
class ReadOnlyDailyPriceWindow:
    """A hash-addressed, read-only prior-session input window."""

    records: tuple[dict[str, object], ...]
    session_dates: tuple[str, ...]
    data_as_of_date: str
    source_hash: str
    max_available_timestamp: str


class _SinglePersistedArtifactLoader:
    """Read back exactly the bytes just persisted in the controlled TEMP store."""

    def __init__(self, decision_snapshot_id: str, path: Path) -> None:
        self._decision_snapshot_id = decision_snapshot_id
        self._path = path

    def load_registered_formal_decision_bytes(self, decision_snapshot_id: str) -> bytes | None:
        if decision_snapshot_id != self._decision_snapshot_id:
            return None
        return self._path.read_bytes()


def canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    """Canonical JSON matching the existing Rule Champion persisted-byte contract."""
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_identifier(payload: Mapping[str, object]) -> str:
    return f"sha256:{sha256(canonical_json_bytes(payload)).hexdigest()}"


def now_in_taipei() -> datetime:
    """The CLI's only decision clock; callers cannot inject an observed time."""
    return datetime.now(TAIPEI_TIME_ZONE)


def require_development_temp_root(output_root: str | Path) -> Path:
    """Allow only the named development output root beneath a TEMP location."""
    root = Path(output_root).expanduser().resolve()
    if root.name != DEVELOPMENT_OUTPUT_ROOT_NAME:
        raise ManualRuleOnlyDecisionError(
            "development_output_root_name_must_be_technical_analysis_development_output"
        )
    allowed_bases = (Path(tempfile.gettempdir()).resolve(), Path("C:/Temp").resolve())
    if not any(_is_relative_to(root, base) for base in allowed_bases):
        raise ManualRuleOnlyDecisionError("development_output_root_must_be_under_temp")
    return root


def load_read_only_daily_price_window(
    market_db: str | Path,
    *,
    decision_session: date,
) -> ReadOnlyDailyPriceWindow:
    """Read a prior-session SQLite window without opening the market DB for writing.

    The SQL predicate is intentionally strict: even a same-day EOD row cannot
    become available to this morning's decision.
    """
    db_path = Path(market_db).expanduser().resolve()
    if not db_path.is_file():
        raise ManualRuleOnlyDecisionError("market_db_missing")

    decision_key = decision_session.strftime("%Y%m%d")
    try:
        connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ManualRuleOnlyDecisionError("market_db_readonly_open_failed") from exc

    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        columns = _daily_price_columns(connection)
        if "日期" not in columns or "證券代號" not in columns:
            raise ManualRuleOnlyDecisionError("daily_prices_required_columns_missing")

        date_expression = "REPLACE(REPLACE(TRIM(CAST(日期 AS TEXT)), '-', ''), '/', '')"
        session_rows = connection.execute(
            f"""
            SELECT DISTINCT {date_expression} AS date_key
            FROM daily_prices
            WHERE {date_expression} < ?
            ORDER BY date_key DESC
            LIMIT 60
            """,
            (decision_key,),
        ).fetchall()
        session_keys = tuple(_compact_date_key(row["date_key"]) for row in session_rows)
        if len(session_keys) < 20:
            raise ManualRuleOnlyDecisionError("daily_prices_history_under_20_sessions")

        placeholders = ",".join("?" for _ in session_keys)
        rows = connection.execute(
            f"""
            SELECT *
            FROM daily_prices
            WHERE {date_expression} IN ({placeholders})
            ORDER BY {date_expression} ASC, CAST(證券代號 AS TEXT) ASC
            """,
            session_keys,
        ).fetchall()
    except sqlite3.Error as exc:
        raise ManualRuleOnlyDecisionError("daily_prices_read_failed") from exc
    finally:
        connection.close()

    if not rows:
        raise ManualRuleOnlyDecisionError("daily_prices_window_empty")
    records = tuple(
        {
            column: _canonical_sql_value(row[column])
            for column in columns
        }
        for row in rows
    )
    ascending_dates = tuple(_require_date_key(item) for item in sorted(session_keys))
    source_payload: dict[str, object] = {
        "schema_version": "manual-rule-only-daily-price-window.v1",
        "source_id": RULE_SOURCE_ID,
        "decision_session": decision_session.isoformat(),
        "session_dates": list(ascending_dates),
        "records": [dict(record) for record in records],
    }
    return ReadOnlyDailyPriceWindow(
        records=records,
        session_dates=ascending_dates,
        data_as_of_date=ascending_dates[-1],
        source_hash=sha256_identifier(source_payload),
        max_available_timestamp=datetime.fromtimestamp(
            db_path.stat().st_mtime, tz=timezone.utc
        ).isoformat(timespec="microseconds"),
    )


def rank_rule_only_candidates(
    window: ReadOnlyDailyPriceWindow,
    *,
    eligible_symbols: Sequence[str] | None = None,
) -> tuple[RuleOnlyCandidate, ...]:
    """Rank complete 20-session daily-price histories using the fixed bp rule.

    ``eligible_symbols`` is an optional clock-bound company universe.  When it
    is supplied, every symbol must have a complete T-1 history; silently
    dropping a missing symbol would change the frozen universe hash, so the
    function fails closed instead.
    """
    normalized_eligible = (
        _normalize_eligible_symbols(eligible_symbols)
        if eligible_symbols is not None
        else None
    )
    eligible_set = set(normalized_eligible or ())
    rows_by_symbol: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in window.records:
        symbol = _normalized_symbol(record.get("證券代號"))
        record_date = _require_date_key(record.get("日期"))
        normalized = dict(record)
        normalized["證券代號"] = symbol
        normalized["日期"] = record_date
        rows_by_symbol[symbol].append(normalized)

    candidates: list[RuleOnlyCandidate] = []
    for symbol, rows in rows_by_symbol.items():
        if eligible_set and symbol not in eligible_set:
            continue
        ordered_rows = sorted(rows, key=lambda item: str(item["日期"]))
        _reject_duplicate_symbol_dates(symbol, ordered_rows)
        # A suspended or otherwise non-trading security may not have a row on
        # the latest market session.  It is still causal to rank its latest
        # twenty observed sessions, all of which are strictly before the
        # decision session; requiring a same-day row would silently change the
        # frozen universe and turn ordinary coverage gaps into universe drift.
        if not ordered_rows or str(ordered_rows[-1]["日期"]) > window.data_as_of_date:
            continue
        # A no-trade row can legitimately carry no close.  It is not an
        # observation and must not be forward-filled or otherwise imputed;
        # use the latest twenty valid observed sessions inside the frozen
        # sixty-session causal window instead.  Non-empty malformed values
        # still reach _candidate_from_rows and reject that security.
        observed_rows = tuple(
            row
            for row in ordered_rows
            if row.get("收盤價") is not None
            and str(row.get("收盤價")).strip()
            and row.get("成交股數") is not None
            and str(row.get("成交股數")).strip()
        )
        if len(observed_rows) < 20:
            continue
        try:
            candidates.append(_candidate_from_rows(symbol, observed_rows[-20:]))
        except ManualRuleOnlyDecisionError:
            # A malformed security row must never be substituted with a value.
            continue

    if normalized_eligible is not None:
        candidate_symbols = {candidate.symbol for candidate in candidates}
        if candidate_symbols != set(normalized_eligible):
            raise ManualRuleOnlyDecisionError(
                "clock_bound_rule_universe_incomplete_t1_history"
            )
    if not candidates:
        raise ManualRuleOnlyDecisionError("no_complete_rule_only_candidate")
    return tuple(sorted(candidates, key=lambda item: (-item.score_bp, item.symbol)))


def produce_manual_rule_only_decision(
    *,
    development_output_root: str | Path,
    market_db: str | Path,
    lane_decision_json: str | Path,
    confirmation: str,
    observed_at: datetime | None = None,
    eligible_symbols: Sequence[str] | None = None,
) -> dict[str, object]:
    """Produce one real-time TEMP-only source artifact after explicit confirmation.

    ``observed_at`` exists only for focused tests.  The CLI never exposes it and
    always calls this function with the Taiwan wall clock.
    """
    root = require_development_temp_root(development_output_root)
    lane_path = Path(lane_decision_json).expanduser().resolve()
    if not _is_relative_to(lane_path, root):
        raise ManualRuleOnlyDecisionError("lane_decision_must_reside_under_development_output_root")
    try:
        lane = load_formal_observation_lane_decision(lane_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ManualRuleOnlyDecisionError("formal_observation_lane_invalid") from exc

    observed = _require_taipei_regular_session(observed_at or now_in_taipei())
    if observed.date().isoformat() != lane.first_eligible_session:
        raise ManualRuleOnlyDecisionError("manual_observed_session_mismatch")
    _require_valid_unconsumed_lane(root, lane, lane_path)

    preflight = {
        "status": "confirmation_required",
        "write_performed": False,
        "decision_session": observed.date().isoformat(),
        "observation_lane_id": lane.holdout_id,
        "formal_oos_allowed": False,
        "formal_evidence_credit_authorized": False,
        "production_blend_alpha_bp": 0,
        "next_step": "repeat_with_exact_confirmation",
    }
    if confirmation != MANUAL_CONFIRMATION:
        return preflight

    key, store_id = _controlled_store_attestation_config()
    window = load_read_only_daily_price_window(market_db, decision_session=observed.date())
    max_available = datetime.fromisoformat(window.max_available_timestamp)
    if max_available > observed.astimezone(timezone.utc):
        raise ManualRuleOnlyDecisionError("market_db_timestamp_later_than_decision_time")
    candidates = rank_rule_only_candidates(
        window,
        eligible_symbols=eligible_symbols,
    )
    selected = candidates[0]

    observed_timestamp = observed.isoformat(timespec="microseconds")
    run_id = f"manual-rule-only-{observed.strftime('%Y%m%dT%H%M%S%f')}"
    score_configuration_hash = sha256_identifier(_RULE_CONFIGURATION)
    source_manifest: dict[str, object] = {
        "schema_version": "manual-rule-only-decision-output.v1",
        "run_id": run_id,
        "decision_timestamp": observed_timestamp,
        "decision_session": observed.date().isoformat(),
        "data_as_of_date": window.data_as_of_date,
        "max_available_timestamp": window.max_available_timestamp,
        "source_versions": {RULE_SOURCE_ID: window.source_hash},
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
        "safety": {
            "rule_only_formal_path": True,
            "formal_oos_allowed": False,
            "formal_evidence_credit_authorized": False,
            "production_blend_alpha_bp": 0,
            "market_database_write_performed": False,
            "recommendation_repository_write_performed": False,
            "evidence_ledger_write_performed": False,
            "scheduler_used": False,
            "ml_used": False,
            "training_used": False,
            "production_action_allowed": False,
        },
    }
    source_lineage_hash = sha256_identifier(source_manifest)
    source_lineage_artifact_id = f"decision-output:{run_id}:{source_lineage_hash}"
    restrictions_hash = sha256_identifier(
        {
            "schema_version": "manual-rule-only-restrictions.v1",
            "lane_decision_id": lane.decision_id,
            "lane_decision_hash": lane.content_hash,
            "allowed_source_ids": list(lane.allowed_source_ids),
            "used_source_ids": [RULE_SOURCE_ID],
            "rule_configuration_hash": score_configuration_hash,
            "formal_oos_allowed": False,
            "formal_evidence_credit_authorized": False,
            "production_blend_alpha_bp": 0,
            "scheduler_allowed": False,
            "training_allowed": False,
            "promotion_allowed": False,
            "unblind_allowed": False,
            "production_action_allowed": False,
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

    run_directory = root / "formal_rule_only_manual" / run_id
    if run_directory.exists():
        raise ManualRuleOnlyDecisionError("manual_rule_only_run_id_already_exists")
    run_directory.mkdir(parents=True, exist_ok=False)
    source_manifest_path = run_directory / "decision_output.json"
    decision_artifact_path = run_directory / "formal_rule_decision_rank_1.json"
    champion_manifest_path = run_directory / "rule_champion_snapshot.json"
    snapshot_path = run_directory / "manual_observed.json"
    _write_new_canonical(source_manifest_path, source_manifest)
    _write_new_canonical(decision_artifact_path, persisted_artifact)

    repository = PersistedFormalDecisionArtifactRepository(
        _SinglePersistedArtifactLoader(decision_snapshot_id, decision_artifact_path)
    )
    champion = RuleChampionSnapshotService().build(
        strategy_version=RULE_STRATEGY_VERSION,
        policy_version=RULE_POLICY_VERSION,
        score_configuration_hash=score_configuration_hash,
        universe_hash=_universe_hash(candidates),
        selection_capacity=1,
        repository=repository,
        decision_snapshot_ids=(decision_snapshot_id,),
    )
    _write_new_canonical(champion_manifest_path, champion.to_manifest())

    snapshot = ExternalEvidenceDecisionSnapshot.create(
        decision_timestamp=observed_timestamp,
        data_as_of_date=window.data_as_of_date,
        max_available_timestamp=window.max_available_timestamp,
        source_versions={RULE_SOURCE_ID: window.source_hash},
        strategy_version=RULE_STRATEGY_VERSION,
        policy_version=RULE_POLICY_VERSION,
        rule_champion_snapshot_id=champion.champion_snapshot_family_id,
        universe_id="tw-daily-prices-complete-20-session-universe",
        universe_hash=_universe_hash(candidates),
        symbol=selected.symbol,
        score_bp=selected.score_bp,
        score_status="observed",
        rank=1,
        action_or_prompt="RULE_ONLY_OBSERVED_NO_TRADE",
        why=(
            f"20日相對均價 {selected.trend_bp}bp",
            f"20日動能 {selected.momentum_bp}bp",
            f"相對平均成交量 {selected.volume_delta_bp}bp",
        ),
        why_not=(),
        risk_reasons=(
            "僅限人工觀測，不構成交易或持倉動作",
            "僅使用決策日前完整日資料",
        ),
        market_regime="not_used_by_rule_only_profile",
        liquidity_state="daily_volume_ranked_not_execution_liquidity",
        restriction_state="rule_only_no_trade_no_formal_credit",
        evidence_tier="temp_manual_rule_only_source",
        missing_sources=(),
        degraded_reasons=(),
        parent_artifact_ids=(
            source_lineage_artifact_id,
            f"rule-champion:{champion.champion_snapshot_family_id}:{champion.content_hash}",
        ),
        capture_kind="manual_observed",
    )
    snapshot_payload = snapshot.to_dict()
    # The existing manual capture CLI accepts the constructor payload, not a
    # repository round-trip row.  It deterministically derives snapshot_id
    # itself, so persisting that derived field here would make the hand-off
    # invalid rather than more authoritative.
    snapshot_payload.pop("snapshot_id", None)
    _write_new_canonical(snapshot_path, snapshot_payload)

    return {
        "status": "manual_observed_source_created",
        "write_performed": True,
        "run_id": run_id,
        "decision_session": observed.date().isoformat(),
        "decision_timestamp": observed_timestamp,
        "symbol": selected.symbol,
        "score_bp": selected.score_bp,
        "snapshot_id": snapshot.snapshot_id,
        "data_as_of_date": window.data_as_of_date,
        "source_versions": {RULE_SOURCE_ID: window.source_hash},
        "decision_output_json": str(source_manifest_path),
        "formal_rule_decision_json": str(decision_artifact_path),
        "rule_champion_snapshot_json": str(champion_manifest_path),
        "manual_observed_json": str(snapshot_path),
        "evidence_ledger_write_performed": False,
        "formal_oos_allowed": False,
        "formal_evidence_credit_authorized": False,
        "production_blend_alpha_bp": 0,
        "next_step": "owner_may_run_existing_manual_shadow_capture_with_manual_observed_json",
    }


def _daily_price_columns(connection: sqlite3.Connection) -> tuple[str, ...]:
    rows = connection.execute("PRAGMA table_info(daily_prices)").fetchall()
    columns = tuple(str(row["name"]) for row in rows)
    if not columns:
        raise ManualRuleOnlyDecisionError("daily_prices_table_missing")
    return columns


def _candidate_from_rows(symbol: str, rows: Iterable[dict[str, object]]) -> RuleOnlyCandidate:
    ordered_rows = tuple(rows)
    if len(ordered_rows) != 20:
        raise ManualRuleOnlyDecisionError("candidate_history_must_have_20_sessions")
    prices = tuple(_decimal_field(row, "收盤價", symbol) for row in ordered_rows)
    volumes = tuple(_decimal_field(row, "成交股數", symbol, allow_zero=True) for row in ordered_rows)
    if any(value <= Decimal("0") for value in prices):
        raise ManualRuleOnlyDecisionError("candidate_close_price_not_positive")
    if any(value < Decimal("0") for value in volumes):
        raise ManualRuleOnlyDecisionError("candidate_volume_negative")

    latest_price = prices[-1]
    average_price = sum(prices, Decimal("0")) / Decimal(len(prices))
    latest_volume = volumes[-1]
    average_volume = sum(volumes, Decimal("0")) / Decimal(len(volumes))
    trend_bp = _relative_basis_points(latest_price, average_price)
    momentum_bp = _relative_basis_points(latest_price, prices[0])
    volume_delta_bp = _relative_basis_points(latest_volume, average_volume)
    score_bp = _clamp_int(
        5000
        + _clamp_int(trend_bp, -2500, 2500)
        + _clamp_int(momentum_bp, -2500, 2500)
        + _clamp_int(volume_delta_bp // 2, -1000, 1000),
        0,
        10000,
    )
    source_window = tuple(
        {
            "date": str(row["日期"]),
            "close_price": _decimal_text(price),
            "volume": _decimal_text(volume),
        }
        for row, price, volume in zip(ordered_rows, prices, volumes)
    )
    return RuleOnlyCandidate(
        symbol=symbol,
        latest_date=str(ordered_rows[-1]["日期"]),
        score_bp=score_bp,
        trend_bp=trend_bp,
        momentum_bp=momentum_bp,
        volume_delta_bp=volume_delta_bp,
        source_window=source_window,
    )


def _controlled_store_attestation_config() -> tuple[bytes, str]:
    key = os.environ.get(_HMAC_KEY_ENV)
    store_id = os.environ.get(_STORE_ID_ENV)
    if not key:
        raise ManualRuleOnlyDecisionError("controlled_runtime_attestation_key_missing")
    if not store_id or not store_id.strip():
        raise ManualRuleOnlyDecisionError("controlled_runtime_registered_store_id_missing")
    return key.encode("utf-8"), store_id.strip()


def _signed_persisted_decision_artifact(
    *,
    decision_snapshot_id: str,
    decision_timestamp: str,
    symbol: str,
    rule_score_bp: int,
    source_lineage_artifact_id: str,
    source_lineage_hash: str,
    restrictions_hash: str,
    registered_store_id: str,
    key: bytes,
) -> dict[str, object]:
    immutable: dict[str, object] = {
        "schema_version": "FormalRuleDecisionSnapshot.v1",
        "source_artifact_kind": "formal_rule_only_immutable_decision_snapshot",
        "rule_only_proof": "formal_rule_only",
        "decision_snapshot_id": decision_snapshot_id,
        "decision_timestamp": decision_timestamp,
        "symbol": symbol,
        "rule_score_bp": rule_score_bp,
        "rule_rank": 1,
        "source_lineage_artifact_id": source_lineage_artifact_id,
        "source_lineage_hash": source_lineage_hash,
        "restrictions_hash": restrictions_hash,
    }
    signed = {
        **immutable,
        "immutable_snapshot_hash": sha256_identifier(immutable),
        "registered_store_id": registered_store_id,
    }
    return {
        **signed,
        "attestation_signature": "hmac-sha256:"
        + hmac.new(key, canonical_json_bytes(signed), sha256).hexdigest(),
    }


def _require_valid_unconsumed_lane(
    root: Path,
    lane: FormalObservationLaneDecision,
    lane_path: Path,
) -> None:
    # Import here to keep the decision source free of a process-wide CLI import.
    from scripts.inspect_formal_clock_readiness import inspect_readiness

    report = inspect_readiness(root, lane_decision_json=lane_path)
    if report.get("consumption_registry") != "owner_attested_lane_binding_valid":
        blockers = report.get("formal_blockers")
        suffix = (
            str(blockers[0])
            if isinstance(blockers, list) and blockers
            else "observation_lane_binding_invalid"
        )
        raise ManualRuleOnlyDecisionError(f"observation_lane_unavailable:{suffix}")
    if report.get("formal_trading_session") != lane.first_eligible_session:
        raise ManualRuleOnlyDecisionError("observation_lane_session_binding_mismatch")


def _require_taipei_regular_session(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ManualRuleOnlyDecisionError("decision_clock_requires_timezone")
    observed = value.astimezone(TAIPEI_TIME_ZONE)
    if not TAIWAN_REGULAR_SESSION_OPEN <= observed.timetz().replace(tzinfo=None) <= TAIWAN_REGULAR_SESSION_CLOSE:
        raise ManualRuleOnlyDecisionError("outside_taiwan_regular_session")
    return observed


def _universe_hash(candidates: tuple[RuleOnlyCandidate, ...]) -> str:
    return sha256_identifier(
        {
            "schema_version": "manual-rule-only-universe.v1",
            "symbols": [candidate.symbol for candidate in candidates],
            "scores_bp": [candidate.score_bp for candidate in candidates],
        }
    )


def _write_new_canonical(path: Path, payload: Mapping[str, object]) -> None:
    data = canonical_json_bytes(payload)
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ManualRuleOnlyDecisionError("immutable_artifact_already_exists") from exc


def _canonical_sql_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int)):
        return value
    # SQLite REAL values cross the DB boundary as strings here, preventing an
    # implicit float calculation from entering the decision kernel.
    return str(value)


def _require_date_key(value: object) -> str:
    text = _compact_date_key(value)
    return text[:4] + "-" + text[4:6] + "-" + text[6:]


def _compact_date_key(value: object) -> str:
    text = str(value).strip().replace("-", "").replace("/", "")
    if len(text) != 8 or not text.isdigit():
        raise ManualRuleOnlyDecisionError("daily_prices_date_invalid")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise ManualRuleOnlyDecisionError("daily_prices_date_invalid") from exc
    return text


def _normalized_symbol(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text:
        raise ManualRuleOnlyDecisionError("daily_prices_symbol_invalid")
    return text


def _normalize_eligible_symbols(value: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ManualRuleOnlyDecisionError(
            "clock_bound_rule_universe_must_be_non_empty"
        )
    normalized = tuple(_normalized_symbol(item) for item in value)
    if normalized != tuple(sorted(set(normalized))):
        raise ManualRuleOnlyDecisionError(
            "clock_bound_rule_universe_must_be_sorted_and_unique"
        )
    return normalized


def _decimal_field(
    row: Mapping[str, object], field: str, symbol: str, *, allow_zero: bool = False
) -> Decimal:
    if field not in row:
        raise ManualRuleOnlyDecisionError(f"daily_prices_{field}_missing")
    raw = row[field]
    text = str(raw).strip().replace(",", "")
    if not text:
        raise ManualRuleOnlyDecisionError(f"daily_prices_{field}_invalid")
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ManualRuleOnlyDecisionError(f"daily_prices_{field}_invalid") from exc
    if not value.is_finite() or (not allow_zero and value <= Decimal("0")):
        raise ManualRuleOnlyDecisionError(f"daily_prices_{field}_invalid")
    return value


def _relative_basis_points(latest: Decimal, baseline: Decimal) -> int:
    if baseline <= Decimal("0"):
        raise ManualRuleOnlyDecisionError("rule_only_baseline_not_positive")
    return int(
        (((latest - baseline) * Decimal("10000")) / baseline).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _clamp_int(value: int, lower: int, upper: int) -> int:
    return min(max(value, lower), upper)


def _reject_duplicate_symbol_dates(symbol: str, rows: Iterable[Mapping[str, object]]) -> None:
    seen: set[str] = set()
    for row in rows:
        key = str(row["日期"])
        if key in seen:
            raise ManualRuleOnlyDecisionError(f"daily_prices_duplicate_symbol_date:{symbol}")
        seen.add(key)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
