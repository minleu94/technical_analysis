"""Create and bind immutable forward position thesis candidate packets.

This module is the small operations boundary between the research-only
recommendation snapshot and the later Paper position-health source.  A
recommendation is recorded as an observation packet at its real decision
clock.  It is never promoted to a human thesis, a broker instruction, or a
Paper ledger record.  A separate, read-only binder can later attach the
packet to a position only when the daily Paper health baseline carries a
verified flat-to-positive entry lineage.

The implementation intentionally keeps policy optional.  The recommendation
producer does not know a valid invalidation rule or holding horizon merely
because one would be useful, so a missing policy remains an explicit missing
state.  All files written here are repository-isolated derived artifacts and
are create-only by candidate identity.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any
from zoneinfo import ZoneInfo

from app_module.position_thesis_contract import PositionInvalidationRule
from data_module.official_trading_calendar import OfficialTradingCalendar


UTC = timezone.utc
TAIPEI = ZoneInfo("Asia/Taipei")
SCHEMA_VERSION = "forward-position-thesis-candidate.v1"
POLICY_SCHEMA_VERSION = "forward-position-policy.v1"
BINDING_SCHEMA_VERSION = "forward-position-entry-binding.v1"
_SHA256_PREFIX = "sha256:"
_RECOMMENDATION_SCORE_FIELDS = (
    ("close_price", "收盤價"),
    ("price_change", "漲幅%"),
    ("total_score", "總分"),
    ("indicator_score", "指標分"),
    ("pattern_score", "圖形分"),
    ("volume_score", "成交量分"),
)


class ForwardPositionThesisError(ValueError):
    """A source, policy, or entry binding contract failed closed."""


@dataclass(frozen=True)
class _PolicySnapshot:
    policy_id: str
    version: str
    source: str
    actor: str
    path: Path
    effective_from: date
    available_at: datetime
    file_sha256: str
    calendar_path: Path
    calendar_sha256: str
    rules: tuple[PositionInvalidationRule, ...]
    holding_horizon_trading_days: int
    review_cadence_trading_days: int
    next_review_date: date
    source_trace: tuple[str, ...]


@dataclass(frozen=True)
class _RecommendationSource:
    payload: Mapping[str, Any]
    path: Path
    file_sha256: str
    content_sha256: str
    result_id: str
    decision_date: date
    decision_at: datetime
    created_at: datetime
    config_sha256: str


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(raw: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(raw).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith(_SHA256_PREFIX):
        return False
    digest = value[len(_SHA256_PREFIX) :]
    if len(digest) != 64:
        return False
    try:
        int(digest, 16)
    except ValueError:
        return False
    return True


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ForwardPositionThesisError(f"{field_name}_missing")
    return text


def _parse_date(value: object, field_name: str) -> date:
    text = _required_text(value, field_name)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ForwardPositionThesisError(f"{field_name}_invalid") from exc
    if parsed.isoformat() != text:
        raise ForwardPositionThesisError(f"{field_name}_must_be_iso_date")
    return parsed


def _parse_aware(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = _required_text(value, field_name).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ForwardPositionThesisError(f"{field_name}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ForwardPositionThesisError(f"{field_name}_must_be_timezone_aware")
    return parsed.astimezone(UTC)


def _decimal_text(value: object, field_name: str, *, allow_float: bool = False) -> str:
    if value is None or isinstance(value, bool):
        raise ForwardPositionThesisError(f"{field_name}_missing")
    if isinstance(value, float) and not allow_float:
        raise ForwardPositionThesisError(f"{field_name}_must_be_decimal_text")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ForwardPositionThesisError(f"{field_name}_invalid") from exc
    if not parsed.is_finite():
        raise ForwardPositionThesisError(f"{field_name}_non_finite")
    return str(parsed)


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ForwardPositionThesisError(f"{field_name}_invalid")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        raise ForwardPositionThesisError(f"{field_name}_invalid")
    if parsed < 0:
        raise ForwardPositionThesisError(f"{field_name}_invalid")
    return parsed


def _read_json_with_hash(path: Path, field_name: str) -> tuple[dict[str, Any], str]:
    try:
        before = path.read_bytes()
        payload = json.loads(before.decode("utf-8-sig"))
        after = path.read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ForwardPositionThesisError(f"{field_name}_unreadable") from exc
    if before != after:
        raise ForwardPositionThesisError(f"{field_name}_changed_during_read")
    if not isinstance(payload, Mapping):
        raise ForwardPositionThesisError(f"{field_name}_must_be_object")
    return dict(payload), _sha256_bytes(before)


def _read_file_hash(path: Path, field_name: str) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise ForwardPositionThesisError(f"{field_name}_unreadable") from exc


def _write_create_only(path: Path, raw: bytes) -> str:
    """Create a file atomically, returning created/same/conflict."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise ForwardPositionThesisError(
                    "immutable_candidate_existing_read_failed"
                ) from exc
            return "same" if existing == raw else "conflict"
        return "created"
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> tuple[Path, str, str]:
    body = _canonical_bytes(dict(payload))
    encoded = (
        _canonical_bytes(
            {
                **dict(payload),
                "content_sha256": _sha256_bytes(body),
            }
        )
        + b"\n"
    )
    target = path
    outcome = _write_create_only(target, encoded)
    if outcome == "conflict":
        suffix = hashlib.sha256(encoded).hexdigest()[:16]
        target = path.with_name(f"{path.stem}_{suffix}{path.suffix}")
        outcome = _write_create_only(target, encoded)
        if outcome == "conflict":
            raise ForwardPositionThesisError("immutable_candidate_filename_collision")
    return target, _sha256_bytes(encoded), outcome


def _write_atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _next_review_date(
    *,
    decision_date: date,
    horizon: int,
    calendar: Any,
) -> date:
    current = decision_date
    counted = 0
    # A 10-year bound prevents a broken calendar adapter from looping forever.
    for _ in range(3660):
        current += timedelta(days=1)
        result = calendar.is_official_trading_day(current, allow_online_probe=False)
        if isinstance(result, tuple):
            is_trading, _reason = result
        else:
            is_trading = result
        if is_trading is None:
            raise ForwardPositionThesisError("official_calendar_day_unknown")
        if is_trading is True:
            counted += 1
            if counted >= horizon:
                return current
    raise ForwardPositionThesisError("official_calendar_horizon_not_reached")


def _calendar_path_from_policy(policy: Mapping[str, Any], fallback: Path | None) -> Path:
    raw = policy.get("calendar_cache_path")
    if raw is None:
        calendar = policy.get("calendar")
        if isinstance(calendar, Mapping):
            raw = calendar.get("path")
    if raw is None and fallback is not None:
        return fallback.expanduser().resolve()
    return Path(_required_text(raw, "calendar_cache_path")).expanduser().resolve()


def _calendar_hash_from_policy(policy: Mapping[str, Any]) -> str:
    raw = policy.get("calendar_cache_hash")
    if raw is None:
        calendar = policy.get("calendar")
        if isinstance(calendar, Mapping):
            raw = calendar.get("file_sha256") or calendar.get("sha256")
    if not _is_sha256(raw):
        raise ForwardPositionThesisError("calendar_cache_hash_invalid")
    return str(raw)


class ForwardPositionThesisCandidateProducer:
    """Produce candidate packets and bind them to verified Paper entries."""

    def __init__(
        self,
        output_root: str | Path,
        *,
        calendar_cache_path: str | Path | None = None,
        calendar: Any | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.output_root = Path(output_root).expanduser().resolve()
        self.calendar_cache_path = (
            None
            if calendar_cache_path is None
            else Path(calendar_cache_path).expanduser().resolve()
        )
        self.calendar = calendar
        self.now_provider = now_provider or (lambda: datetime.now(UTC))

    def produce(
        self,
        recommendation_path: str | Path,
        *,
        policy_path: str | Path | None = None,
        decision_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Create one immutable packet per recommendation row.

        With no policy file, packets are still useful observation records but
        remain ``awaiting_explicit_policy``.  A supplied policy is validated
        against its actual bytes and the official calendar before any packet
        is written.
        """

        source_path = Path(recommendation_path).expanduser().resolve()
        try:
            source_payload, source_hash = _read_json_with_hash(
                source_path, "recommendation_source"
            )
            source = self._parse_recommendation_source(
                source_payload,
                source_path=source_path,
                source_hash=source_hash,
                decision_at=decision_at,
            )
        except (ForwardPositionThesisError, OSError, ValueError) as exc:
            return self._blocked_result(
                operation="produce",
                blockers=(f"recommendation_source_blocked:{type(exc).__name__}:{exc}",),
                source_path=source_path,
            )

        policy: _PolicySnapshot | None = None
        policy_error: str | None = None
        if policy_path is not None:
            try:
                policy_payload, policy_hash = _read_json_with_hash(
                    Path(policy_path).expanduser().resolve(), "forward_policy"
                )
                policy = self._parse_policy(
                    policy_payload,
                    policy_hash=policy_hash,
                    policy_path=Path(policy_path).expanduser().resolve(),
                    decision_date=source.decision_date,
                    decision_at=source.decision_at,
                )
            except (ForwardPositionThesisError, OSError, ValueError) as exc:
                policy_error = f"forward_policy_blocked:{type(exc).__name__}:{exc}"

        if policy_error is not None:
            return self._blocked_result(
                operation="produce",
                blockers=(policy_error,),
                source_path=source.path,
                source_hash=source.file_sha256,
                result_id=source.result_id,
                decision_date=source.decision_date.isoformat(),
            )

        recommendations = source.payload.get("recommendations")
        if not isinstance(recommendations, list):
            return self._blocked_result(
                operation="produce",
                blockers=("recommendations_must_be_list",),
                source_path=source.path,
                source_hash=source.file_sha256,
                result_id=source.result_id,
                decision_date=source.decision_date.isoformat(),
            )

        packets: list[dict[str, Any]] = []
        outcomes: list[dict[str, Any]] = []
        for rank, raw_recommendation in enumerate(recommendations, start=1):
            try:
                packet = self._build_packet(
                    source=source,
                    raw_recommendation=raw_recommendation,
                    rank=rank,
                    policy=policy,
                )
            except (ForwardPositionThesisError, TypeError, ValueError) as exc:
                return self._blocked_result(
                    operation="produce",
                    blockers=(
                        f"recommendation_row_{rank}_blocked:{type(exc).__name__}:{exc}",
                    ),
                    source_path=source.path,
                    source_hash=source.file_sha256,
                    result_id=source.result_id,
                    decision_date=source.decision_date.isoformat(),
                )
            candidate_id = str(packet["candidate_id"])
            file_name = _safe_file_name(candidate_id) + ".json"
            dated_root = self.output_root / source.decision_date.isoformat()
            target, file_hash, outcome = _write_immutable_json(
                dated_root / file_name,
                packet,
            )
            packets.append(
                {
                    "candidate_id": candidate_id,
                    "status": packet["status"],
                    "path": str(target),
                    "file_sha256": file_hash,
                    "write_outcome": outcome,
                }
            )
            outcomes.append({"candidate_id": candidate_id, "status": packet["status"]})

        warnings = []
        if policy is None and packets:
            warnings.append("explicit_forward_policy_missing")
        if not packets:
            warnings.append("recommendation_source_has_no_candidates")
        overall = "passed"
        if any(item["status"] == "awaiting_explicit_policy" for item in packets):
            overall = "degraded"
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "operation": "produce",
            "status": overall,
            "result_id": source.result_id,
            "decision_date": source.decision_date.isoformat(),
            "decision_at": source.decision_at.isoformat(),
            "recommendation_source": {
                "path": str(source.path),
                "file_sha256": source.file_sha256,
                "content_sha256": source.content_sha256,
                "created_at": source.created_at.isoformat(),
                "available_at": source.created_at.isoformat(),
                "decision_date": source.decision_date.isoformat(),
                "config_sha256": source.config_sha256,
            },
            "policy": _policy_to_dict(policy),
            "candidate_count": len(packets),
            "candidates": packets,
            "warnings": warnings,
            "blockers": [],
            "candidate_only": True,
            "human_approval_required": True,
            "auto_action_allowed": False,
            "research_only": True,
            "writes_paper_state": False,
            "writes_formal_state": False,
            "writes_broker": False,
        }
        self._persist_receipt(receipt, source.decision_date)
        return receipt

    def bind(
        self,
        candidate_path: str | Path,
        baseline_path: str | Path,
        *,
        paper_candidate_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Bind a candidate only to a verified new Paper entry lineage."""

        candidate_file = Path(candidate_path).expanduser().resolve()
        baseline_file = Path(baseline_path).expanduser().resolve()
        try:
            candidate, candidate_hash = _read_json_with_hash(
                candidate_file, "candidate_packet"
            )
            baseline, baseline_hash = _read_json_with_hash(
                baseline_file, "health_baseline"
            )
            result = self._bind_payload(
                candidate=candidate,
                candidate_hash=candidate_hash,
                candidate_path=candidate_file,
                baseline=baseline,
                baseline_hash=baseline_hash,
                baseline_path=baseline_file,
                paper_candidate_path=(
                    None
                    if paper_candidate_path is None
                    else Path(paper_candidate_path).expanduser().resolve()
                ),
            )
        except (ForwardPositionThesisError, OSError, ValueError, TypeError, sqlite3.Error) as exc:
            result = {
                "schema_version": BINDING_SCHEMA_VERSION,
                "operation": "bind",
                "status": "blocked",
                "candidate_path": str(candidate_file),
                "candidate_file_sha256": _safe_hash(candidate_file),
                "baseline_path": str(baseline_file),
                "baseline_file_sha256": _safe_hash(baseline_file),
                "blockers": [f"entry_binding_blocked:{type(exc).__name__}:{exc}"],
                "warnings": [],
                "research_only": True,
                "candidate_only": True,
                "human_approval_required": True,
                "auto_action_allowed": False,
            }
        self._persist_binding_receipt(result)
        return result

    def _parse_recommendation_source(
        self,
        payload: Mapping[str, Any],
        *,
        source_path: Path,
        source_hash: str,
        decision_at: datetime | str | None,
    ) -> _RecommendationSource:
        result_id = _required_text(payload.get("result_id"), "recommendation_result_id")
        config = payload.get("config")
        if not isinstance(config, Mapping):
            raise ForwardPositionThesisError("recommendation_config_invalid")
        decision_date = _parse_date(config.get("decision_date"), "decision_date")
        created_at = _parse_aware(payload.get("created_at"), "recommendation_created_at")
        current = _parse_aware(self.now_provider(), "observed_at")
        if created_at > current:
            raise ForwardPositionThesisError("recommendation_created_at_future")
        effective_decision_at = (
            created_at
            if decision_at is None
            else _parse_aware(decision_at, "decision_at")
        )
        if effective_decision_at > current:
            raise ForwardPositionThesisError("recommendation_decision_at_future")
        if created_at > effective_decision_at:
            raise ForwardPositionThesisError("recommendation_available_after_decision")
        if created_at.astimezone(TAIPEI).date() != decision_date:
            raise ForwardPositionThesisError("recommendation_created_date_mismatch")
        return _RecommendationSource(
            payload=payload,
            path=source_path,
            file_sha256=source_hash,
            content_sha256=_sha256_json(payload),
            result_id=result_id,
            decision_date=decision_date,
            decision_at=effective_decision_at,
            created_at=created_at,
            config_sha256=_sha256_json(dict(config)),
        )

    def _parse_policy(
        self,
        payload: Mapping[str, Any],
        *,
        policy_hash: str,
        policy_path: Path,
        decision_date: date,
        decision_at: datetime,
    ) -> _PolicySnapshot:
        if payload.get("schema_version") != POLICY_SCHEMA_VERSION:
            raise ForwardPositionThesisError("forward_policy_schema_invalid")
        policy_id = _required_text(payload.get("policy_id"), "policy_id")
        version = _required_text(payload.get("version"), "policy_version")
        source = _required_text(payload.get("source"), "policy_source")
        actor = _required_text(
            payload.get("actor") or "forward_position_policy_producer",
            "policy_actor",
        )
        effective_from = _parse_date(payload.get("effective_from"), "policy_effective_from")
        if effective_from > decision_date:
            raise ForwardPositionThesisError("forward_policy_not_yet_effective")
        available_at = _parse_aware(payload.get("available_at"), "policy_available_at")
        if available_at > decision_at:
            raise ForwardPositionThesisError("forward_policy_available_after_decision")
        raw_rules = payload.get("invalidation_rules")
        if not isinstance(raw_rules, list) or not raw_rules:
            raise ForwardPositionThesisError("forward_policy_invalidation_rules_missing")
        rules: list[PositionInvalidationRule] = []
        for index, raw_rule in enumerate(raw_rules):
            if not isinstance(raw_rule, Mapping):
                raise ForwardPositionThesisError(f"forward_policy_rule_{index}_invalid")
            threshold = raw_rule.get("threshold")
            if not isinstance(threshold, str):
                raise ForwardPositionThesisError(
                    f"forward_policy_rule_{index}_threshold_must_be_decimal_text"
                )
            try:
                parsed_threshold = Decimal(threshold)
            except (InvalidOperation, ValueError) as exc:
                raise ForwardPositionThesisError(
                    f"forward_policy_rule_{index}_threshold_invalid"
                ) from exc
            rules.append(
                PositionInvalidationRule(
                    metric_id=_required_text(raw_rule.get("metric_id"), "metric_id"),
                    operator=_required_text(raw_rule.get("operator"), "operator"),
                    threshold=parsed_threshold,
                    action=str(raw_rule.get("action") or "exit"),
                )
            )
        horizon = payload.get("holding_horizon_trading_days")
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon <= 0:
            raise ForwardPositionThesisError("forward_policy_horizon_invalid")
        calendar_path = _calendar_path_from_policy(payload, self.calendar_cache_path)
        calendar_hash = _calendar_hash_from_policy(payload)
        actual_calendar_hash = _read_file_hash(calendar_path, "calendar_cache")
        if actual_calendar_hash != calendar_hash:
            raise ForwardPositionThesisError("calendar_cache_hash_mismatch")
        calendar = self.calendar or OfficialTradingCalendar(
            db_path=calendar_path,
            calendar_cache_path=calendar_path,
        )
        review_cadence = payload.get(
            "review_cadence_trading_days",
            horizon,
        )
        if (
            isinstance(review_cadence, bool)
            or not isinstance(review_cadence, int)
            or review_cadence <= 0
            or review_cadence > horizon
        ):
            raise ForwardPositionThesisError("forward_policy_review_cadence_invalid")
        next_review = _next_review_date(
            decision_date=decision_date,
            horizon=review_cadence,
            calendar=calendar,
        )
        trace = payload.get("source_trace", [])
        if not isinstance(trace, list) or not all(isinstance(item, str) and item.strip() for item in trace):
            raise ForwardPositionThesisError("forward_policy_source_trace_invalid")
        return _PolicySnapshot(
            policy_id=policy_id,
            version=version,
            source=source,
            actor=actor,
            path=policy_path,
            effective_from=effective_from,
            available_at=available_at,
            file_sha256=policy_hash,
            calendar_path=calendar_path,
            calendar_sha256=calendar_hash,
            rules=tuple(rules),
            holding_horizon_trading_days=horizon,
            review_cadence_trading_days=review_cadence,
            next_review_date=next_review,
            source_trace=tuple(trace),
        )

    def _build_packet(
        self,
        *,
        source: _RecommendationSource,
        raw_recommendation: object,
        rank: int,
        policy: _PolicySnapshot | None,
    ) -> dict[str, Any]:
        if not isinstance(raw_recommendation, Mapping):
            raise ForwardPositionThesisError("recommendation_row_must_be_object")
        code = str(raw_recommendation.get("stock_code", raw_recommendation.get("證券代號", ""))).strip()
        name = str(raw_recommendation.get("stock_name", raw_recommendation.get("證券名稱", ""))).strip()
        if not code:
            raise ForwardPositionThesisError("recommendation_stock_code_missing")
        reasons_value = raw_recommendation.get(
            "recommendation_reasons", raw_recommendation.get("推薦理由", "")
        )
        if isinstance(reasons_value, list):
            if not all(isinstance(item, str) for item in reasons_value):
                raise ForwardPositionThesisError("recommendation_reasons_invalid")
            reasons = list(reasons_value)
            reason_text = "\n".join(reasons)
        else:
            reason_text = str(reasons_value or "")
            reasons = [reason_text] if reason_text else []
        score_values: dict[str, str] = {}
        for field, legacy_key in _RECOMMENDATION_SCORE_FIELDS:
            raw_value = raw_recommendation.get(field, raw_recommendation.get(legacy_key))
            score_values[field] = _decimal_text(
                raw_value,
                f"recommendation_{field}",
                allow_float=True,
            )
        regime_match_value = raw_recommendation.get(
            "regime_match", raw_recommendation.get("Regime匹配", False)
        )
        regime_match = (
            regime_match_value == "是"
            if isinstance(regime_match_value, str)
            else bool(regime_match_value)
        )
        candidate_id = f"candidate:{source.result_id}:{code}"
        if policy is None:
            invalidation: dict[str, Any] = {
                "status": "missing",
                "policy_id": None,
                "policy_hash": None,
                "rules": [],
            }
            horizon: dict[str, Any] = {
                "status": "missing",
                "trading_days": None,
                "next_review_date": None,
            }
            status = "awaiting_explicit_policy"
            policy_trace: tuple[str, ...] = ()
        else:
            invalidation = {
                "status": "explicit_policy",
                "policy_id": policy.policy_id,
                "policy_version": policy.version,
                "policy_source": policy.source,
                "policy_actor": policy.actor,
                "policy_path": str(policy.path),
                "policy_hash": policy.file_sha256,
                "effective_from": policy.effective_from.isoformat(),
                "available_at": policy.available_at.isoformat(),
                "rules": [rule.to_dict() for rule in policy.rules],
                "calendar_cache_path": str(policy.calendar_path),
                "calendar_cache_hash": policy.calendar_sha256,
            }
            horizon = {
                "status": "explicit_policy",
                "trading_days": policy.holding_horizon_trading_days,
                "review_cadence_trading_days": policy.review_cadence_trading_days,
                "next_review_date": policy.next_review_date.isoformat(),
            }
            status = "candidate_ready"
            policy_trace = policy.source_trace
        return {
            "schema_version": SCHEMA_VERSION,
            "candidate_id": candidate_id,
            "status": status,
            "candidate_only": True,
            "human_approval_required": True,
            "auto_action_allowed": False,
            "research_only": True,
            "recommendation_source": {
                "result_id": source.result_id,
                "path": str(source.path),
                "file_sha256": source.file_sha256,
                "content_sha256": source.content_sha256,
                "created_at": source.created_at.isoformat(),
                "available_at": source.created_at.isoformat(),
                "decision_at": source.decision_at.isoformat(),
                "decision_date": source.decision_date.isoformat(),
                "config_sha256": source.config_sha256,
            },
            "instrument": {"stock_code": code, "stock_name": name},
            "decision_observation": {
                "rank": rank,
                "recommendation_reasons": reason_text,
                "reasons": reasons,
                "scores": score_values,
                "industry": str(raw_recommendation.get("industry", raw_recommendation.get("產業", "")) or ""),
                "regime_match": regime_match,
                "threshold_mode": str(raw_recommendation.get("threshold_mode", "fixed")),
            },
            "thesis": {
                "kind": "machine_observation",
                "statement": "machine_observation_only; no human investment thesis supplied",
                "source_trace": [
                    f"recommendation:{source.result_id}",
                    f"recommendation_source_hash:{source.file_sha256}",
                    f"recommendation_config_hash:{source.config_sha256}",
                    *policy_trace,
                ],
            },
            "invalidation": invalidation,
            "holding_horizon": horizon,
            "entry_binding": {
                "status": "awaiting_paper_fill",
                "position_id": None,
                "entry_lineage_id": None,
                "fill_id": None,
                "entry_source_event_id": None,
                "entry_evidence_hash": None,
            },
            "warnings": [] if policy is not None else ["explicit_forward_policy_missing"],
        }

    def _bind_payload(
        self,
        *,
        candidate: Mapping[str, Any],
        candidate_hash: str,
        candidate_path: Path,
        baseline: Mapping[str, Any],
        baseline_hash: str,
        baseline_path: Path,
        paper_candidate_path: Path | None,
    ) -> dict[str, Any]:
        if candidate.get("schema_version") != SCHEMA_VERSION:
            raise ForwardPositionThesisError("candidate_schema_invalid")
        if candidate.get("candidate_only") is not True or candidate.get("auto_action_allowed") is not False:
            raise ForwardPositionThesisError("candidate_boundary_invalid")
        candidate_id = _required_text(candidate.get("candidate_id"), "candidate_id")
        source = candidate.get("recommendation_source")
        instrument = candidate.get("instrument")
        if not isinstance(source, Mapping) or not isinstance(instrument, Mapping):
            raise ForwardPositionThesisError("candidate_source_or_instrument_invalid")
        source_path = Path(_required_text(source.get("path"), "recommendation_source_path")).expanduser().resolve()
        declared_source_hash = source.get("file_sha256")
        if not _is_sha256(declared_source_hash):
            raise ForwardPositionThesisError("candidate_source_hash_invalid")
        declared_source_content_hash = source.get("content_sha256")
        if not _is_sha256(declared_source_content_hash):
            raise ForwardPositionThesisError("candidate_source_content_hash_invalid")
        actual_source_hash = _read_file_hash(source_path, "recommendation_source")
        if actual_source_hash != declared_source_hash:
            raise ForwardPositionThesisError("recommendation_source_hash_mismatch")
        decision_date = _parse_date(source.get("decision_date"), "candidate_decision_date")
        available_at = _parse_aware(source.get("available_at"), "candidate_available_at")
        stock_code = _required_text(instrument.get("stock_code"), "candidate_stock_code")
        if baseline.get("schema_version") != "position-health-daily-refresh.v1":
            raise ForwardPositionThesisError("health_baseline_schema_invalid")
        if baseline.get("status") != "fresh":
            raise ForwardPositionThesisError("health_baseline_not_fresh")
        if baseline.get("research_only") is not True or baseline.get("auto_action_allowed") is not False:
            raise ForwardPositionThesisError("health_baseline_boundary_invalid")
        snapshot_date = _parse_date(baseline.get("source_snapshot_date"), "health_snapshot_date")
        if snapshot_date < decision_date:
            raise ForwardPositionThesisError("health_snapshot_before_candidate")
        positions = baseline.get("positions")
        if not isinstance(positions, list):
            raise ForwardPositionThesisError("health_baseline_positions_invalid")
        matches = [item for item in positions if isinstance(item, Mapping) and str(item.get("stock_code") or "").strip() == stock_code]
        if len(matches) > 1:
            return self._binding_result(
                candidate=candidate,
                candidate_hash=candidate_hash,
                candidate_path=candidate_path,
                baseline=baseline,
                baseline_hash=baseline_hash,
                baseline_path=baseline_path,
                status="ambiguous",
                stock_code=stock_code,
                blockers=("multiple_health_rows_for_stock_code",),
            )
        if not matches:
            return self._binding_result(
                candidate=candidate,
                candidate_hash=candidate_hash,
                candidate_path=candidate_path,
                baseline=baseline,
                baseline_hash=baseline_hash,
                baseline_path=baseline_path,
                status="awaiting_paper_fill",
                stock_code=stock_code,
                warnings=("paper_entry_not_observed",),
            )
        row = matches[0]
        identity = row.get("position_identity_source")
        if not isinstance(identity, Mapping):
            return self._binding_result(
                candidate=candidate,
                candidate_hash=candidate_hash,
                candidate_path=candidate_path,
                baseline=baseline,
                baseline_hash=baseline_hash,
                baseline_path=baseline_path,
                status="awaiting_paper_fill",
                stock_code=stock_code,
                warnings=("paper_entry_identity_not_verified",),
            )
        identity_status = str(identity.get("status") or row.get("entry_lineage_status") or "").strip()
        if identity_status in {"ambiguous", "unproven", "closed_prior_not_projected"}:
            return self._binding_result(
                candidate=candidate,
                candidate_hash=candidate_hash,
                candidate_path=candidate_path,
                baseline=baseline,
                baseline_hash=baseline_hash,
                baseline_path=baseline_path,
                status="ambiguous" if identity_status == "ambiguous" else "awaiting_paper_fill",
                stock_code=stock_code,
                warnings=(f"paper_entry_identity_{identity_status or 'unproven'}",),
            )
        if identity_status != "natural_entry_verified":
            return self._binding_result(
                candidate=candidate,
                candidate_hash=candidate_hash,
                candidate_path=candidate_path,
                baseline=baseline,
                baseline_hash=baseline_hash,
                baseline_path=baseline_path,
                status="awaiting_paper_fill",
                stock_code=stock_code,
                warnings=(f"paper_entry_identity_status_not_new:{identity_status}",),
            )
        entry_date = _parse_date(identity.get("entry_date"), "entry_date")
        if entry_date <= decision_date:
            return self._binding_result(
                candidate=candidate,
                candidate_hash=candidate_hash,
                candidate_path=candidate_path,
                baseline=baseline,
                baseline_hash=baseline_hash,
                baseline_path=baseline_path,
                status="rejected_preexisting",
                stock_code=stock_code,
                entry=identity,
                warnings=("paper_entry_precedes_or_matches_candidate_decision",),
            )
        if paper_candidate_path is None:
            return self._binding_result(
                candidate=candidate,
                candidate_hash=candidate_hash,
                candidate_path=candidate_path,
                baseline=baseline,
                baseline_hash=baseline_hash,
                baseline_path=baseline_path,
                status="awaiting_paper_fill",
                stock_code=stock_code,
                warnings=("paper_execution_candidate_proof_missing",),
            )
        position_id = _required_text(identity.get("position_id"), "position_id")
        lineage_id = _required_text(identity.get("entry_lineage_id"), "entry_lineage_id")
        fill_id = _required_text(identity.get("entry_fill_id"), "entry_fill_id")
        source_event_id = _required_text(identity.get("entry_source_event_id"), "entry_source_event_id")
        evidence_hash = identity.get("entry_evidence_hash")
        if not _is_sha256(evidence_hash):
            raise ForwardPositionThesisError("entry_evidence_hash_invalid")
        identity_available = identity.get("available_at")
        if identity_available is not None and _parse_aware(identity_available, "entry_available_at") < available_at:
            raise ForwardPositionThesisError("candidate_available_after_entry_source")
        paper_candidate = self.verify_paper_execution_candidate(
            paper_candidate_path,
            result_id=_required_text(source.get("result_id"), "recommendation_result_id"),
            recommendation_file_sha256=str(declared_source_hash),
            recommendation_content_sha256=str(declared_source_content_hash),
            stock_code=stock_code,
            position_id=position_id,
            entry_date=entry_date,
            fill_id=fill_id,
            source_event_id=source_event_id,
            evidence_hash=str(evidence_hash),
        )
        entry = {
            "position_id": position_id,
            "entry_lineage_id": lineage_id,
            "stock_code": stock_code,
            "entry_date": entry_date.isoformat(),
            "entry_fill_id": fill_id,
            "entry_source_event_id": source_event_id,
            "entry_evidence_hash": evidence_hash,
            # This is the Paper identity producer's actual availability clock.
            # The downstream machine-thesis binder uses it to prove that the
            # policy was visible before the new entry, rather than giving an
            # old policy retroactive credit from the entry date alone.
            "entry_available_at": identity_available,
            "identity_status": identity_status,
            "identity_source": identity.get("identity_source"),
            "source_ledger_rows_sha256": identity.get("source_ledger_rows_sha256"),
            "coverage_status_file_sha256": identity.get("coverage_status_file_sha256"),
            "paper_execution_candidate_path": str(paper_candidate_path),
            "paper_execution_candidate_file_sha256": paper_candidate["file_hash"],
            "paper_execution_candidate_content_sha256": paper_candidate["content_sha256"],
            "paper_recommendation_file_sha256": paper_candidate["recommendation_file_sha256"],
            "paper_recommendation_content_sha256": paper_candidate["recommendation_content_sha256"],
        }
        return self._binding_result(
            candidate=candidate,
            candidate_hash=candidate_hash,
            candidate_path=candidate_path,
            baseline=baseline,
            baseline_hash=baseline_hash,
            baseline_path=baseline_path,
            status="bound",
            stock_code=stock_code,
            entry=entry,
        )

    def verify_paper_execution_candidate(
        self,
        path: Path,
        *,
        result_id: str,
        recommendation_file_sha256: str,
        recommendation_content_sha256: str,
        stock_code: str,
        position_id: str,
        entry_date: date,
        fill_id: str,
        source_event_id: str,
        evidence_hash: str,
    ) -> dict[str, str]:
        """Verify recommendation -> Paper candidate -> ledger fill custody."""

        payload, file_hash = _read_json_with_hash(path, "paper_execution_candidate")
        if payload.get("schema_version") != "paper-execution-daily-candidate.v1":
            raise ForwardPositionThesisError("paper_execution_candidate_schema_invalid")
        if payload.get("candidate_only") is not True or payload.get("research_only") is not True:
            raise ForwardPositionThesisError("paper_execution_candidate_boundary_invalid")
        if payload.get("broker_execution") is not False or payload.get("broker_order_allowed") is not False:
            raise ForwardPositionThesisError("paper_execution_candidate_broker_boundary_invalid")
        portfolio_id = _required_text(payload.get("portfolio_id"), "paper_execution_portfolio_id")
        if not position_id.startswith(f"paper:{portfolio_id}:"):
            raise ForwardPositionThesisError("paper_execution_portfolio_position_mismatch")
        declared_content = payload.get("content_sha256")
        if not _is_sha256(declared_content):
            raise ForwardPositionThesisError("paper_execution_candidate_content_hash_invalid")
        body = dict(payload)
        body.pop("content_sha256", None)
        if _sha256_json(body) != declared_content:
            raise ForwardPositionThesisError("paper_execution_candidate_content_hash_mismatch")
        recommendation = payload.get("recommendation")
        if not isinstance(recommendation, Mapping):
            raise ForwardPositionThesisError("paper_execution_candidate_recommendation_missing")
        if str(recommendation.get("result_id") or "") != result_id:
            raise ForwardPositionThesisError("paper_recommendation_result_id_mismatch")
        recommendation_content_hash = recommendation.get("content_hash")
        if not _is_sha256(recommendation_content_hash):
            raise ForwardPositionThesisError("paper_recommendation_content_hash_invalid")
        recommendation_path_value = recommendation.get("path")
        recommendation_file_hash = recommendation.get("file_hash")
        if not isinstance(recommendation_path_value, str) or not _is_sha256(recommendation_file_hash):
            raise ForwardPositionThesisError("paper_recommendation_file_proof_missing")
        recommendation_path = Path(recommendation_path_value).expanduser().resolve()
        recommendation_payload, actual_recommendation_file_hash = _read_json_with_hash(
            recommendation_path,
            "paper_recommendation",
        )
        actual_recommendation_content_hash = _sha256_json(recommendation_payload)
        if actual_recommendation_file_hash != recommendation_file_hash:
            raise ForwardPositionThesisError("paper_recommendation_file_hash_mismatch")
        if actual_recommendation_file_hash != recommendation_file_sha256:
            raise ForwardPositionThesisError("paper_recommendation_candidate_file_hash_mismatch")
        if actual_recommendation_content_hash != str(recommendation_content_hash):
            raise ForwardPositionThesisError("paper_recommendation_content_hash_mismatch")
        if actual_recommendation_content_hash != recommendation_content_sha256:
            raise ForwardPositionThesisError("paper_recommendation_candidate_content_hash_mismatch")
        execution_date = _parse_date(payload.get("execution_date"), "paper_execution_date")
        if execution_date != entry_date:
            raise ForwardPositionThesisError("paper_execution_entry_date_mismatch")
        fills = payload.get("fills")
        if not isinstance(fills, list):
            raise ForwardPositionThesisError("paper_execution_candidate_fills_invalid")
        matching = [
            item
            for item in fills
            if isinstance(item, Mapping)
            and str(item.get("fill_id") or "") == fill_id
        ]
        if len(matching) != 1:
            raise ForwardPositionThesisError("paper_execution_entry_fill_not_unique")
        fill = matching[0]
        if str(fill.get("stock_code") or "") != stock_code:
            raise ForwardPositionThesisError("paper_execution_entry_stock_mismatch")
        if str(fill.get("side") or "") != "buy":
            raise ForwardPositionThesisError("paper_execution_entry_side_invalid")
        fill_status = str(fill.get("status") or "")
        if fill_status not in {"filled", "partially_filled"}:
            raise ForwardPositionThesisError("paper_execution_entry_not_filled")
        filled_quantity = _non_negative_int(fill.get("filled_quantity"), "paper_entry_filled_quantity")
        if filled_quantity <= 0:
            raise ForwardPositionThesisError("paper_execution_entry_zero_quantity")
        if str(fill.get("source_event_id") or "") != source_event_id:
            raise ForwardPositionThesisError("paper_execution_entry_source_event_mismatch")
        if str(fill.get("order_id") or "") != source_event_id.replace(
            "paper-execution:", "paper-order:", 1
        ):
            raise ForwardPositionThesisError("paper_execution_entry_order_mismatch")
        expected_prefix = (
            f"paper-execution:{execution_date.isoformat()}:"
            f"{str(recommendation_content_hash)[len(_SHA256_PREFIX):][:16]}:"
        )
        if not source_event_id.startswith(expected_prefix):
            raise ForwardPositionThesisError("paper_execution_entry_recommendation_binding_mismatch")
        ledger = payload.get("ledger")
        if not isinstance(ledger, Mapping) or ledger.get("readback_verified") is not True:
            raise ForwardPositionThesisError("paper_execution_ledger_readback_missing")
        ledger_path_value = ledger.get("path")
        fill_ids = ledger.get("fill_ids")
        if not isinstance(ledger_path_value, str) or not isinstance(fill_ids, list) or fill_id not in fill_ids:
            raise ForwardPositionThesisError("paper_execution_ledger_entry_proof_missing")
        ledger_path = Path(ledger_path_value).expanduser().resolve()
        ledger_row = self._read_ledger_fill(ledger_path, fill_id)
        if ledger_row is None:
            raise ForwardPositionThesisError("paper_execution_ledger_fill_missing")
        if ledger_row["portfolio_id"] != portfolio_id:
            raise ForwardPositionThesisError("paper_execution_ledger_portfolio_mismatch")
        if ledger_row["stock_code"] != stock_code or ledger_row["side"] != "buy":
            raise ForwardPositionThesisError("paper_execution_ledger_identity_mismatch")
        if ledger_row["event_date"] != entry_date.isoformat() or ledger_row["source_event_id"] != source_event_id:
            raise ForwardPositionThesisError("paper_execution_ledger_event_mismatch")
        if ledger_row["filled_quantity"] != filled_quantity:
            raise ForwardPositionThesisError("paper_execution_ledger_quantity_mismatch")
        actual_evidence_hash = _sha256_json(ledger_row["canonical"])
        if actual_evidence_hash != evidence_hash:
            raise ForwardPositionThesisError("paper_execution_entry_evidence_hash_mismatch")
        return {
            "file_hash": file_hash,
            "content_sha256": str(declared_content),
            "recommendation_file_sha256": str(recommendation_file_hash),
            "recommendation_content_sha256": str(recommendation_content_hash),
            "ledger_file_sha256": ledger_row["file_sha256"],
        }

    @staticmethod
    def _read_ledger_fill(path: Path, fill_id: str) -> dict[str, Any] | None:
        try:
            before = _sha256_bytes(path.read_bytes())
            uri = f"file:{path.as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                row = connection.execute(
                    "SELECT * FROM paper_trade_ledger WHERE fill_id = ?",
                    (fill_id,),
                ).fetchone()
            after = _sha256_bytes(path.read_bytes())
        except (OSError, sqlite3.Error) as exc:
            raise ForwardPositionThesisError("paper_execution_ledger_unreadable") from exc
        if before != after:
            raise ForwardPositionThesisError("paper_execution_ledger_changed_during_read")
        if row is None:
            return None
        required = (
            "schema_version", "fill_id", "order_id", "portfolio_id", "event_date",
            "stock_code", "side", "requested_quantity", "filled_quantity",
            "reference_price", "fill_price", "commission", "tax", "slippage_cost",
            "turnover_bp", "execution_gap_bp", "status", "source_event_id",
            "override_reason", "source_type", "research_only", "broker_order_allowed",
            "auto_rebalance_allowed",
        )
        if any(field not in row.keys() for field in required):
            raise ForwardPositionThesisError("paper_execution_ledger_schema_missing")
        canonical = {field: row[field] for field in required}
        if int(row["research_only"] or 0) != 1 or int(row["broker_order_allowed"] or 0) != 0 or int(row["auto_rebalance_allowed"] or 0) != 0:
            raise ForwardPositionThesisError("paper_execution_ledger_boundary_invalid")
        return {
            "stock_code": str(row["stock_code"] or ""),
            "side": str(row["side"] or ""),
            "event_date": str(row["event_date"] or ""),
            "source_event_id": str(row["source_event_id"] or ""),
            "portfolio_id": str(row["portfolio_id"] or ""),
            "filled_quantity": _non_negative_int(row["filled_quantity"], "paper ledger filled_quantity"),
            "canonical": canonical,
            "file_sha256": before,
        }

    def _binding_result(
        self,
        *,
        candidate: Mapping[str, Any],
        candidate_hash: str,
        candidate_path: Path,
        baseline: Mapping[str, Any],
        baseline_hash: str,
        baseline_path: Path,
        status: str,
        stock_code: str,
        entry: Mapping[str, Any] | None = None,
        warnings: Sequence[str] = (),
        blockers: Sequence[str] = (),
    ) -> dict[str, Any]:
        source = candidate.get("recommendation_source")
        assert isinstance(source, Mapping)
        result: dict[str, Any] = {
            "schema_version": BINDING_SCHEMA_VERSION,
            "operation": "bind",
            "status": status,
            "candidate_id": candidate.get("candidate_id"),
            "candidate_path": str(candidate_path),
            "candidate_file_sha256": candidate_hash,
            "candidate_decision_date": source.get("decision_date"),
            "candidate_available_at": source.get("available_at"),
            "baseline_path": str(baseline_path),
            "baseline_file_sha256": baseline_hash,
            "baseline_snapshot_id": baseline.get("source_snapshot_id"),
            "baseline_snapshot_date": baseline.get("source_snapshot_date"),
            "stock_code": stock_code,
            "entry": None if entry is None else dict(entry),
            "health_handoff": None,
            "warnings": list(dict.fromkeys(str(item) for item in warnings)),
            "blockers": list(dict.fromkeys(str(item) for item in blockers)),
            "candidate_only": True,
            "human_approval_required": True,
            "auto_action_allowed": False,
            "research_only": True,
            "writes_paper_state": False,
            "writes_formal_state": False,
            "writes_broker": False,
        }
        if entry is not None and status == "bound":
            result["health_handoff"] = {
                "position_id": entry["position_id"],
                "entry_lineage_id": entry["entry_lineage_id"],
                "next_consumers": [
                    "position_health_daily_refresh_service",
                    "position_health_market_source_producer",
                    "daily_position_health_transition_evaluator",
                ],
                "human_thesis_registry_required": True,
                "transition_apply_allowed": False,
            }
        return result

    def _persist_receipt(self, receipt: Mapping[str, Any], decision_date: date) -> None:
        receipt_root = self.output_root / "receipts"
        receipt_root.mkdir(parents=True, exist_ok=True)
        receipt_hash = hashlib.sha256(_canonical_bytes(dict(receipt))).hexdigest()[:20]
        target = receipt_root / f"produce_{decision_date.strftime('%Y%m%d')}_{receipt_hash}.json"
        _write_create_only(
            target,
            (json.dumps(dict(receipt), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        )
        _write_atomic_json(self.output_root / "latest_status.json", dict(receipt))

    def _persist_binding_receipt(self, receipt: Mapping[str, Any]) -> None:
        receipt_root = self.output_root / "bindings"
        receipt_root.mkdir(parents=True, exist_ok=True)
        candidate_id = _safe_file_name(str(receipt.get("candidate_id") or "unknown"))
        target = receipt_root / f"{candidate_id}.json"
        raw = (json.dumps(dict(receipt), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        outcome = _write_create_only(target, raw)
        if outcome == "conflict":
            suffix = hashlib.sha256(raw).hexdigest()[:16]
            target = receipt_root / f"{candidate_id}_{suffix}.json"
            _write_create_only(target, raw)
        latest = dict(receipt)
        latest["receipt_path"] = str(target)
        _write_atomic_json(self.output_root / "latest_binding_status.json", latest)

    def _blocked_result(
        self,
        *,
        operation: str,
        blockers: Sequence[str],
        source_path: Path,
        source_hash: str | None = None,
        result_id: str | None = None,
        decision_date: str | None = None,
    ) -> dict[str, Any]:
        result = {
            "schema_version": BINDING_SCHEMA_VERSION if operation == "bind" else SCHEMA_VERSION,
            "operation": operation,
            "status": "blocked",
            "result_id": result_id,
            "decision_date": decision_date,
            "recommendation_source": {
                "path": str(source_path),
                "file_sha256": source_hash,
            },
            "candidate_count": 0,
            "candidates": [],
            "warnings": [],
            "blockers": list(dict.fromkeys(str(item) for item in blockers)),
            "candidate_only": True,
            "human_approval_required": True,
            "auto_action_allowed": False,
            "research_only": True,
            "writes_paper_state": False,
            "writes_formal_state": False,
            "writes_broker": False,
        }
        try:
            self._persist_receipt(result, date.fromisoformat(decision_date) if decision_date else date.today())
        except (OSError, ValueError):
            pass
        return result


def bind_available_candidates(
    *,
    candidate_root: str | Path,
    baseline_path: str | Path,
    paper_candidate_root: str | Path | None = None,
) -> dict[str, Any]:
    """Bind current-baseline candidates from one natural Health run.

    Candidate packets are selected from date directories up to the current
    baseline snapshot and only for stock codes present in that snapshot.  The
    Paper candidate index is read-only and bounded to immutable candidate
    files; the actual binder still performs the complete recommendation,
    source-event, ledger and evidence verification.  Existing historical
    bindings for closed identities are therefore not replayed by the daily
    caller.
    """

    root = Path(candidate_root).expanduser().resolve()
    baseline_file = Path(baseline_path).expanduser().resolve()
    paper_root = (
        None
        if paper_candidate_root is None
        else Path(paper_candidate_root).expanduser().resolve()
    )
    try:
        baseline, _ = _read_json_with_hash(baseline_file, "health_baseline")
        snapshot_date = _parse_date(
            baseline.get("source_snapshot_date") or baseline.get("as_of_date"),
            "health_snapshot_date",
        )
        positions = baseline.get("positions")
        if not isinstance(positions, list):
            raise ForwardPositionThesisError("health_baseline_positions_invalid")
        current_codes = {
            str(item.get("stock_code") or "").strip()
            for item in positions
            if isinstance(item, Mapping) and str(item.get("stock_code") or "").strip()
        }
    except (ForwardPositionThesisError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {
            "status": "blocked",
            "candidate_root": str(root),
            "baseline_path": str(baseline_file),
            "paper_candidate_root": None if paper_root is None else str(paper_root),
            "candidate_count": 0,
            "bound_count": 0,
            "awaiting_count": 0,
            "blocked_count": 1,
            "results": [],
            "warnings": [],
            "blockers": [f"forward_daily_binding_selection_blocked:{type(exc).__name__}:{exc}"],
        }

    paper_index: dict[tuple[str, str], set[Path]] = {}
    paper_entry_index: dict[tuple[str, str, str], set[Path]] = {}
    # Keep the Paper recommendation identity alongside each deduplicated
    # path.  ``result_id`` alone is not a custody key: a stale or replaced
    # recommendation file may legally reuse an identifier while its bytes
    # differ.  The binder will fail closed on a related hash conflict; an
    # unrelated historical recommendation is never sent to the binder.
    paper_recommendation_identity: dict[Path, tuple[str, str, str]] = {}
    paper_paths: list[Path] = []
    if paper_root is not None:
        if paper_root.is_file():
            paper_paths = [paper_root]
        elif paper_root.is_dir():
            paper_paths = sorted(
                item
                for item in paper_root.rglob("paper_execution_candidate.json")
                if item.is_file()
            )
    for path in paper_paths:
        try:
            payload, _ = _read_json_with_hash(path, "paper_execution_candidate")
            recommendation = payload.get("recommendation")
            fills = payload.get("fills")
            if not isinstance(recommendation, Mapping) or not isinstance(fills, list):
                continue
            result_id = str(recommendation.get("result_id") or "").strip()
            recommendation_file_hash = str(recommendation.get("file_hash") or "").strip()
            recommendation_content_hash = str(recommendation.get("content_hash") or "").strip()
            for fill in fills:
                if not isinstance(fill, Mapping):
                    continue
                code = str(fill.get("stock_code") or "").strip()
                if result_id and code:
                    paper_index.setdefault((result_id, code), set()).add(path)
                    paper_recommendation_identity[path] = (
                        result_id,
                        recommendation_file_hash,
                        recommendation_content_hash,
                    )
                    fill_id = str(fill.get("fill_id") or "").strip()
                    source_event_id = str(fill.get("source_event_id") or "").strip()
                    if fill_id and source_event_id:
                        paper_entry_index.setdefault(
                            (fill_id, source_event_id, code),
                            set(),
                        ).add(path)
        except (ForwardPositionThesisError, OSError, ValueError, TypeError, json.JSONDecodeError):
            continue

    candidate_paths: list[Path] = []
    if root.is_dir():
        for directory in sorted(item for item in root.iterdir() if item.is_dir()):
            try:
                directory_date = date.fromisoformat(directory.name)
            except ValueError:
                continue
            if directory_date > snapshot_date:
                continue
            candidate_paths.extend(
                sorted(item for item in directory.glob("candidate_*.json") if item.is_file())
            )

    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    blockers: list[str] = []
    producer = ForwardPositionThesisCandidateProducer(root)
    current_entries_by_stock: dict[str, set[tuple[str, str]]] = {}
    for item in positions:
        if not isinstance(item, Mapping):
            continue
        code = str(item.get("stock_code") or "").strip()
        identity = item.get("position_identity_source")
        if not code or not isinstance(identity, Mapping):
            continue
        identity_status = str(identity.get("status") or item.get("entry_lineage_status") or "")
        fill_id = str(identity.get("entry_fill_id") or "").strip()
        source_event_id = str(identity.get("entry_source_event_id") or "").strip()
        if identity_status in {"natural_entry_verified", "carried_verified"} and fill_id and source_event_id:
            current_entries_by_stock.setdefault(code, set()).add((fill_id, source_event_id))
    for candidate_path in candidate_paths:
        try:
            candidate, _ = _read_json_with_hash(candidate_path, "candidate_packet")
            instrument = candidate.get("instrument")
            source = candidate.get("recommendation_source")
            if not isinstance(instrument, Mapping) or not isinstance(source, Mapping):
                continue
            stock_code = str(instrument.get("stock_code") or "").strip()
            result_id = str(source.get("result_id") or "").strip()
            candidate_date = _parse_date(source.get("decision_date"), "candidate_decision_date")
            if stock_code not in current_codes or candidate_date > snapshot_date:
                continue
            entry_paths: set[Path] = set()
            for fill_id, source_event_id in current_entries_by_stock.get(stock_code, set()):
                entry_paths.update(
                    paper_entry_index.get((fill_id, source_event_id, stock_code), set())
                )
            entry_matches = paper_index.get((result_id, stock_code), set()).intersection(
                entry_paths
            )
            source_file_hash = str(source.get("file_sha256") or "").strip()
            source_content_hash = str(source.get("content_sha256") or "").strip()
            exact_matches = {
                path
                for path in entry_matches
                if paper_recommendation_identity.get(path)
                == (result_id, source_file_hash, source_content_hash)
            }
            mismatched_matches = entry_matches - exact_matches
            # A matching fill/event with a different recommendation identity
            # is a relevant custody conflict.  Select it deterministically so
            # ``bind`` records the concrete hash blocker.  A valid exact
            # match with no conflict remains eligible; a set of duplicate
            # paths is ambiguous only when all paths carry the same identity.
            paper_path: Path | None
            if mismatched_matches:
                paper_matches = mismatched_matches
                paper_path = sorted(mismatched_matches)[0]
            else:
                paper_matches = exact_matches
                paper_path = next(iter(paper_matches)) if len(paper_matches) == 1 else None
            if len(paper_matches) > 1 and not mismatched_matches:
                warnings.append(f"paper_candidate_ambiguous:{result_id}:{stock_code}")
            if not entry_matches:
                # A same-stock recommendation without the current verified
                # entry chain is historical/unrelated; leave it untouched so
                # it cannot turn into a false binding or a daily blocker.
                continue
            binding = producer.bind(
                candidate_path,
                baseline_file,
                paper_candidate_path=paper_path,
            )
            status = str(binding.get("status") or "unknown")
            results.append(
                {
                    "candidate_path": str(candidate_path),
                    "candidate_id": candidate.get("candidate_id"),
                    "stock_code": stock_code,
                    "result_id": result_id,
                    "paper_candidate_path": None if paper_path is None else str(paper_path),
                    "status": status,
                    "binding_path": binding.get("receipt_path"),
                    "warnings": list(binding.get("warnings") or []),
                    "blockers": list(binding.get("blockers") or []),
                }
            )
            warnings.extend(str(item) for item in binding.get("warnings") or [])
            blockers.extend(str(item) for item in binding.get("blockers") or [])
        except (ForwardPositionThesisError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            blockers.append(f"forward_daily_binding_candidate_blocked:{candidate_path.name}:{type(exc).__name__}:{exc}")

    bound_count = sum(1 for item in results if item.get("status") == "bound")
    blocked_count = sum(1 for item in results if item.get("status") == "blocked")
    awaiting_count = len(results) - bound_count - blocked_count
    if not results:
        warnings.append("forward_daily_binding_no_current_entry_candidates")
    status = "blocked" if blockers else "degraded" if awaiting_count or not results else "passed"
    return {
        "status": status,
        "candidate_root": str(root),
        "baseline_path": str(baseline_file),
        "paper_candidate_root": None if paper_root is None else str(paper_root),
        "snapshot_date": snapshot_date.isoformat(),
        "candidate_count": len(results),
        "bound_count": bound_count,
        "awaiting_count": awaiting_count,
        "blocked_count": blocked_count,
        "results": results,
        "warnings": list(dict.fromkeys(warnings)),
        "blockers": list(dict.fromkeys(blockers)),
        "candidate_only": True,
        "research_only": True,
        "auto_action_allowed": False,
    }


def _policy_to_dict(policy: _PolicySnapshot | None) -> dict[str, Any] | None:
    if policy is None:
        return None
    return {
        "policy_id": policy.policy_id,
        "version": policy.version,
        "source": policy.source,
        "effective_from": policy.effective_from.isoformat(),
        "available_at": policy.available_at.isoformat(),
        "file_sha256": policy.file_sha256,
        "calendar_cache_path": str(policy.calendar_path),
        "calendar_cache_hash": policy.calendar_sha256,
        "holding_horizon_trading_days": policy.holding_horizon_trading_days,
        "review_cadence_trading_days": policy.review_cadence_trading_days,
        "next_review_date": policy.next_review_date.isoformat(),
        "rules": [rule.to_dict() for rule in policy.rules],
        "source_trace": list(policy.source_trace),
    }


def _safe_hash(path: Path) -> str | None:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        return None


def _safe_file_name(value: str) -> str:
    # ``:`` is intentionally excluded: Windows treats it as a drive/stream
    # separator and candidate IDs contain colons by contract.
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


__all__ = [
    "BINDING_SCHEMA_VERSION",
    "ForwardPositionThesisCandidateProducer",
    "ForwardPositionThesisError",
    "POLICY_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "bind_available_candidates",
]
