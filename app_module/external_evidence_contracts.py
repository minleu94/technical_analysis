"""Fail-closed, shadow-only contracts for causal external-evidence capture.

These contracts deliberately do not read market data, alter recommendations, or
claim forward maturity.  A caller may only create a snapshot from an already
observed decision artifact whose latest available input is no later than the
decision timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Literal, Mapping


ScoreStatus = Literal["observed", "not_applicable", "missing"]
OutcomeRevisionStatus = Literal["pending_maturity", "verified", "invalid"]
CaptureKind = Literal["manual_observed"]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _parse_timestamp(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed


def _parse_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _require_nonempty(value: str, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _normalized_mapping(value: Mapping[str, str], *, field_name: str) -> dict[str, str]:
    normalized = {str(key).strip(): str(item).strip() for key, item in value.items()}
    if not normalized or any(not key or not item for key, item in normalized.items()):
        raise ValueError(f"{field_name} must contain non-empty entries")
    return normalized


@dataclass(frozen=True)
class ExternalEvidenceDecisionSnapshot:
    """Immutable representation of one actually observed decision.

    ``evidence_tier`` remains descriptive only; it never authorizes a forward
    evidence claim or any production behaviour.
    """

    snapshot_id: str
    decision_timestamp: str
    data_as_of_date: str
    max_available_timestamp: str
    source_versions: Mapping[str, str]
    strategy_version: str
    policy_version: str
    rule_champion_snapshot_id: str
    universe_id: str
    universe_hash: str
    symbol: str
    score_bp: int | None
    score_status: ScoreStatus
    rank: int | None
    action_or_prompt: str
    why: tuple[str, ...]
    why_not: tuple[str, ...]
    risk_reasons: tuple[str, ...]
    market_regime: str
    liquidity_state: str
    restriction_state: str
    evidence_tier: str
    missing_sources: tuple[str, ...]
    degraded_reasons: tuple[str, ...]
    parent_artifact_ids: tuple[str, ...]
    capture_kind: CaptureKind

    def __post_init__(self) -> None:
        if self.capture_kind != "manual_observed":
            raise ValueError("capture_kind must be manual_observed")
        object.__setattr__(
            self,
            "source_versions",
            MappingProxyType(_normalized_mapping(self.source_versions, field_name="source_versions")),
        )

    @classmethod
    def create(
        cls,
        *,
        decision_timestamp: str,
        data_as_of_date: str,
        max_available_timestamp: str,
        source_versions: Mapping[str, str],
        strategy_version: str,
        policy_version: str,
        rule_champion_snapshot_id: str,
        universe_id: str,
        universe_hash: str,
        symbol: str,
        score_bp: int | None,
        score_status: ScoreStatus,
        rank: int | None,
        action_or_prompt: str,
        why: tuple[str, ...],
        why_not: tuple[str, ...],
        risk_reasons: tuple[str, ...],
        market_regime: str,
        liquidity_state: str,
        restriction_state: str,
        evidence_tier: str,
        missing_sources: tuple[str, ...],
        degraded_reasons: tuple[str, ...],
        parent_artifact_ids: tuple[str, ...],
        capture_kind: CaptureKind,
    ) -> "ExternalEvidenceDecisionSnapshot":
        decision_at = _parse_timestamp(decision_timestamp, field_name="decision_timestamp")
        available_at = _parse_timestamp(max_available_timestamp, field_name="max_available_timestamp")
        as_of = _parse_date(data_as_of_date, field_name="data_as_of_date")
        if available_at > decision_at:
            raise ValueError("max available timestamp cannot be later than decision timestamp")
        if as_of > decision_at.date():
            raise ValueError("data_as_of_date cannot be later than decision date")
        if score_status not in ("observed", "not_applicable", "missing"):
            raise ValueError("score_status is invalid")
        if score_status == "observed" and (score_bp is None or rank is None):
            raise ValueError("observed score requires score_bp and rank")
        if score_status != "observed" and score_bp is not None:
            raise ValueError("non-observed score must not substitute a numeric score")
        if rank is not None and rank < 1:
            raise ValueError("rank must be positive when present")
        identity = {
            "decision_timestamp": decision_timestamp,
            "data_as_of_date": data_as_of_date,
            "max_available_timestamp": max_available_timestamp,
            "source_versions": _normalized_mapping(source_versions, field_name="source_versions"),
            "strategy_version": _require_nonempty(strategy_version, field_name="strategy_version"),
            "policy_version": _require_nonempty(policy_version, field_name="policy_version"),
            "rule_champion_snapshot_id": _require_nonempty(rule_champion_snapshot_id, field_name="rule_champion_snapshot_id"),
            "universe_id": _require_nonempty(universe_id, field_name="universe_id"),
            "universe_hash": _require_nonempty(universe_hash, field_name="universe_hash"),
            "symbol": _require_nonempty(symbol, field_name="symbol"),
            "score_bp": score_bp,
            "score_status": score_status,
            "rank": rank,
            "action_or_prompt": _require_nonempty(action_or_prompt, field_name="action_or_prompt"),
            "why": tuple(str(item) for item in why),
            "why_not": tuple(str(item) for item in why_not),
            "risk_reasons": tuple(str(item) for item in risk_reasons),
            "market_regime": _require_nonempty(market_regime, field_name="market_regime"),
            "liquidity_state": _require_nonempty(liquidity_state, field_name="liquidity_state"),
            "restriction_state": _require_nonempty(restriction_state, field_name="restriction_state"),
            "evidence_tier": _require_nonempty(evidence_tier, field_name="evidence_tier"),
            "missing_sources": tuple(str(item) for item in missing_sources),
            "degraded_reasons": tuple(str(item) for item in degraded_reasons),
            "parent_artifact_ids": tuple(str(item) for item in parent_artifact_ids),
            "capture_kind": capture_kind,
        }
        snapshot_hash = sha256(_canonical_json(identity).encode("utf-8")).hexdigest()
        snapshot_id = f"snapshot:{identity['symbol']}:{decision_at:%Y%m%d}:{snapshot_hash[:16]}"
        return cls(
            snapshot_id=snapshot_id,
            decision_timestamp=decision_timestamp,
            data_as_of_date=data_as_of_date,
            max_available_timestamp=max_available_timestamp,
            source_versions=_normalized_mapping(source_versions, field_name="source_versions"),
            strategy_version=_require_nonempty(strategy_version, field_name="strategy_version"),
            policy_version=_require_nonempty(policy_version, field_name="policy_version"),
            rule_champion_snapshot_id=_require_nonempty(
                rule_champion_snapshot_id, field_name="rule_champion_snapshot_id"
            ),
            universe_id=_require_nonempty(universe_id, field_name="universe_id"),
            universe_hash=_require_nonempty(universe_hash, field_name="universe_hash"),
            symbol=_require_nonempty(symbol, field_name="symbol"),
            score_bp=score_bp,
            score_status=score_status,
            rank=rank,
            action_or_prompt=_require_nonempty(action_or_prompt, field_name="action_or_prompt"),
            why=tuple(str(item) for item in why),
            why_not=tuple(str(item) for item in why_not),
            risk_reasons=tuple(str(item) for item in risk_reasons),
            market_regime=_require_nonempty(market_regime, field_name="market_regime"),
            liquidity_state=_require_nonempty(liquidity_state, field_name="liquidity_state"),
            restriction_state=_require_nonempty(restriction_state, field_name="restriction_state"),
            evidence_tier=_require_nonempty(evidence_tier, field_name="evidence_tier"),
            missing_sources=tuple(str(item) for item in missing_sources),
            degraded_reasons=tuple(str(item) for item in degraded_reasons),
            parent_artifact_ids=tuple(str(item) for item in parent_artifact_ids),
            capture_kind=capture_kind,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "decision_timestamp": self.decision_timestamp,
            "data_as_of_date": self.data_as_of_date,
            "max_available_timestamp": self.max_available_timestamp,
            "source_versions": dict(self.source_versions),
            "strategy_version": self.strategy_version,
            "policy_version": self.policy_version,
            "rule_champion_snapshot_id": self.rule_champion_snapshot_id,
            "universe_id": self.universe_id,
            "universe_hash": self.universe_hash,
            "symbol": self.symbol,
            "score_bp": self.score_bp,
            "score_status": self.score_status,
            "rank": self.rank,
            "action_or_prompt": self.action_or_prompt,
            "why": self.why,
            "why_not": self.why_not,
            "risk_reasons": self.risk_reasons,
            "market_regime": self.market_regime,
            "liquidity_state": self.liquidity_state,
            "restriction_state": self.restriction_state,
            "evidence_tier": self.evidence_tier,
            "missing_sources": self.missing_sources,
            "degraded_reasons": self.degraded_reasons,
            "parent_artifact_ids": self.parent_artifact_ids,
            "capture_kind": self.capture_kind,
        }


@dataclass(frozen=True)
class EvidenceOutcomeRevision:
    """One immutable outcome observation or correction in the sidecar ledger."""

    revision_id: str
    parent_revision_id: str | None
    snapshot_id: str
    window_trading_days: int
    return_basis: str
    status: OutcomeRevisionStatus
    observed_at: str
    data_as_of_date: str
    return_bp: int | None
    benchmark_return_bp: int | None
    reason_code: str
    source_hashes: Mapping[str, str]
    content_hash: str

    def __post_init__(self) -> None:
        _require_nonempty(self.revision_id, field_name="revision_id")
        _require_nonempty(self.snapshot_id, field_name="snapshot_id")
        _require_nonempty(self.return_basis, field_name="return_basis")
        _require_nonempty(self.reason_code, field_name="reason_code")
        _parse_timestamp(self.observed_at, field_name="observed_at")
        _parse_date(self.data_as_of_date, field_name="data_as_of_date")
        object.__setattr__(
            self,
            "source_hashes",
            MappingProxyType(_normalized_mapping(self.source_hashes, field_name="source_hashes")),
        )
        if self.window_trading_days < 1:
            raise ValueError("window_trading_days must be positive")
        if self.status not in ("pending_maturity", "verified", "invalid"):
            raise ValueError("status is invalid")
        if self.status == "pending_maturity" and (self.return_bp is not None or self.benchmark_return_bp is not None):
            raise ValueError("pending_maturity cannot carry outcome values")
        if self.status == "verified" and self.return_bp is None:
            raise ValueError("verified revision requires return_bp")
        if not self.content_hash.startswith("sha256:"):
            raise ValueError("content_hash must be a sha256 identifier")

    def to_dict(self) -> dict[str, object]:
        return {
            "revision_id": self.revision_id,
            "parent_revision_id": self.parent_revision_id,
            "snapshot_id": self.snapshot_id,
            "window_trading_days": self.window_trading_days,
            "return_basis": self.return_basis,
            "status": self.status,
            "observed_at": self.observed_at,
            "data_as_of_date": self.data_as_of_date,
            "return_bp": self.return_bp,
            "benchmark_return_bp": self.benchmark_return_bp,
            "reason_code": self.reason_code,
            "source_hashes": dict(self.source_hashes),
            "content_hash": self.content_hash,
        }
