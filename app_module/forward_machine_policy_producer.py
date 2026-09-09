"""Create a future-effective, research-only Paper machine policy artifact.

The producer owns the small approval-to-bytes boundary for the forward Paper
thesis path.  It does not infer thresholds from historical returns and it does
not edit an existing policy.  A policy is immutable once written; a calendar
replacement or an explicit policy supersession requires a new version and a
new pinned source hash.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from zoneinfo import ZoneInfo

from data_module.official_trading_calendar import OfficialTradingCalendar


UTC = timezone.utc
TAIPEI = ZoneInfo("Asia/Taipei")
POLICY_SCHEMA_VERSION = "forward-position-policy.v1"
PRODUCER_SCHEMA_VERSION = "forward-machine-policy-producer.v1"
DEFAULT_POLICY_ID = "paper-machine-thesis-benchmark-v1"
DEFAULT_VERSION = "2026-09-08-approved-v1"
DEFAULT_SOURCE = "root_approved_forward_machine_policy_engineering_baseline"
DEFAULT_ACTOR = "forward_position_policy_producer"
DEFAULT_RULES: tuple[dict[str, str], ...] = (
    {
        "metric_id": "macd_hist",
        "operator": "lte",
        "threshold": "0",
        "action": "reduce",
    },
    {
        "metric_id": "rsi",
        "operator": "lte",
        "threshold": "30",
        "action": "reduce",
    },
    {
        "metric_id": "adx",
        "operator": "lt",
        "threshold": "15",
        "action": "reduce",
    },
)


class ForwardMachinePolicyError(ValueError):
    """A policy or official-calendar custody check failed closed."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ForwardMachinePolicyError(f"{field_name}_missing")
    return text


def _aware(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ForwardMachinePolicyError("available_at_must_be_timezone_aware")
    return parsed.astimezone(UTC)


def _write_create_only(path: Path, raw: bytes) -> str:
    """Atomically create one immutable file, never replace a prior version."""

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
                raise ForwardMachinePolicyError(
                    "policy_existing_bytes_unreadable"
                ) from exc
            return "same" if existing == raw else "conflict"
        return "created"
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_atomic(path: Path, raw: bytes) -> None:
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
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_json_object(path: Path) -> tuple[dict[str, Any], bytes]:
    """Read one JSON object and retain the exact bytes used for its hash."""

    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ForwardMachinePolicyError("policy_existing_bytes_unreadable") from exc
    if not isinstance(payload, dict):
        raise ForwardMachinePolicyError("policy_existing_payload_not_object")
    return payload, raw


def _is_official_trading_day(calendar: Any, target: date) -> bool:
    result = calendar.is_official_trading_day(target, allow_online_probe=False)
    value = result[0] if isinstance(result, tuple) else result
    if value is None:
        raise ForwardMachinePolicyError("effective_calendar_day_unknown")
    return value is True


def _next_effective_session(anchor: datetime, calendar: Any) -> date:
    """Choose the first official session whose 08:30 cutoff is future."""

    local_anchor = anchor.astimezone(TAIPEI)
    current = local_anchor.date()
    cutoff_time = time(8, 30, tzinfo=TAIPEI)
    for offset in range(3660):
        candidate = current + timedelta(days=offset)
        if not _is_official_trading_day(calendar, candidate):
            continue
        cutoff = datetime.combine(candidate, cutoff_time)
        if cutoff > anchor.astimezone(TAIPEI):
            return candidate
    raise ForwardMachinePolicyError("effective_calendar_horizon_not_reached")


def _validate_rules(rules: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    if not rules:
        raise ForwardMachinePolicyError("policy_rules_missing")
    validated: list[dict[str, str]] = []
    allowed_operators = {"gt", "gte", "lt", "lte", "eq"}
    allowed_actions = {"reduce", "exit"}
    for index, raw in enumerate(rules):
        metric_id = _required_text(raw.get("metric_id"), f"rule_{index}_metric_id")
        operator = _required_text(raw.get("operator"), f"rule_{index}_operator")
        action = _required_text(raw.get("action"), f"rule_{index}_action")
        threshold = raw.get("threshold")
        if operator not in allowed_operators:
            raise ForwardMachinePolicyError(f"rule_{index}_operator_invalid")
        if action not in allowed_actions:
            raise ForwardMachinePolicyError(f"rule_{index}_action_invalid")
        if not isinstance(threshold, str):
            raise ForwardMachinePolicyError(f"rule_{index}_threshold_must_be_decimal_text")
        try:
            parsed = Decimal(threshold)
        except Exception as exc:  # noqa: BLE001 - policy boundary
            raise ForwardMachinePolicyError(f"rule_{index}_threshold_invalid") from exc
        if not parsed.is_finite():
            raise ForwardMachinePolicyError(f"rule_{index}_threshold_non_finite")
        validated.append(
            {
                "metric_id": metric_id,
                "operator": operator,
                "threshold": str(parsed),
                "action": action,
            }
        )
    return validated


class ForwardMachinePolicyProducer:
    """Write one approved future-effective policy with pinned calendar bytes."""

    def __init__(
        self,
        output_root: str | Path,
        *,
        calendar_cache_path: str | Path,
        now_provider: Callable[[], datetime] | None = None,
        calendar: Any | None = None,
    ) -> None:
        self.output_root = Path(output_root).expanduser().resolve()
        self.calendar_cache_path = Path(calendar_cache_path).expanduser().resolve()
        self.now_provider = now_provider or (lambda: datetime.now(UTC))
        self.calendar = calendar or OfficialTradingCalendar(
            db_path=self.calendar_cache_path,
            calendar_cache_path=self.calendar_cache_path,
        )

    def create(
        self,
        *,
        policy_id: str = DEFAULT_POLICY_ID,
        version: str = DEFAULT_VERSION,
        source: str = DEFAULT_SOURCE,
        actor: str = DEFAULT_ACTOR,
        approval_reference: str,
        holding_horizon_trading_days: int = 20,
        review_cadence_trading_days: int = 5,
        rules: Sequence[Mapping[str, Any]] = DEFAULT_RULES,
    ) -> dict[str, Any]:
        """Create a policy and an activation receipt using the real clock."""

        observed_at: datetime | None = None
        try:
            observed_at = _aware(self.now_provider())
            policy_id = _required_text(policy_id, "policy_id")
            version = _required_text(version, "policy_version")
            source = _required_text(source, "policy_source")
            actor = _required_text(actor, "policy_actor")
            approval = _required_text(approval_reference, "approval_reference")
            if (
                isinstance(holding_horizon_trading_days, bool)
                or not isinstance(holding_horizon_trading_days, int)
                or holding_horizon_trading_days <= 0
            ):
                raise ForwardMachinePolicyError("holding_horizon_invalid")
            if (
                isinstance(review_cadence_trading_days, bool)
                or not isinstance(review_cadence_trading_days, int)
                or review_cadence_trading_days <= 0
                or review_cadence_trading_days > holding_horizon_trading_days
            ):
                raise ForwardMachinePolicyError("review_cadence_invalid")
            rule_payload = _validate_rules(rules)
            if not self.calendar_cache_path.is_file():
                raise ForwardMachinePolicyError("calendar_cache_file_missing")
            calendar_raw = self.calendar_cache_path.read_bytes()
            calendar_hash = _sha256(calendar_raw)
            target = self._policy_path(policy_id, version)

            # A retry after the first publication must observe and reuse the
            # immutable policy bytes.  ``available_at`` and ``recorded_at``
            # belong to the policy publication; the new wall clock belongs to
            # the separate activation observation receipt.
            if target.is_file():
                return self._reuse_existing_policy(
                    target=target,
                    observed_at=observed_at,
                    policy_id=policy_id,
                    version=version,
                    source=source,
                    actor=actor,
                    approval=approval,
                    holding_horizon_trading_days=holding_horizon_trading_days,
                    review_cadence_trading_days=review_cadence_trading_days,
                    rule_payload=rule_payload,
                    current_calendar_hash=calendar_hash,
                    current_calendar_path=self.calendar_cache_path,
                )

            effective_from = _next_effective_session(observed_at, self.calendar)
            if _sha256(self.calendar_cache_path.read_bytes()) != calendar_hash:
                raise ForwardMachinePolicyError("calendar_source_changed_during_read")
            snapshot_path = self._calendar_snapshot_path(
                policy_id, version, calendar_hash
            )
            snapshot_outcome = _write_create_only(snapshot_path, calendar_raw)
            if snapshot_outcome == "conflict":
                return self._blocked(
                    observed_at=observed_at,
                    policy_path=None,
                    policy_hash=None,
                    blockers=("calendar_snapshot_immutable_conflict",),
                )
            policy = {
                "schema_version": POLICY_SCHEMA_VERSION,
                "policy_id": policy_id,
                "version": version,
                "source": source,
                "actor": actor,
                "status": "active_future_effective",
                "effective_from": effective_from.isoformat(),
                "available_at": observed_at.isoformat(),
                "recorded_at": observed_at.isoformat(),
                "approval_reference": approval,
                "candidate_only": True,
                "research_only": True,
                "auto_action_allowed": False,
                "broker_order_allowed": False,
                "formal_credit": False,
                # ``calendar_cache_path`` is deliberately the immutable
                # snapshot.  The mutable source is retained only as custody
                # provenance and is never used to validate an old policy.
                "calendar_cache_path": str(snapshot_path),
                "calendar_cache_hash": calendar_hash,
                "calendar_source_path": str(self.calendar_cache_path),
                "calendar_source_sha256": calendar_hash,
                "invalidation_rules": rule_payload,
                "holding_horizon_trading_days": holding_horizon_trading_days,
                "review_cadence_trading_days": review_cadence_trading_days,
                "source_trace": [
                    f"policy_approval:{approval}",
                    f"policy_actor:{actor}",
                    f"calendar_cache_sha256:{calendar_hash}",
                    f"calendar_snapshot_path:{snapshot_path}",
                    "parameter_origin:forward_engineering_baseline_not_historical_fit",
                ],
            }
            raw = json.dumps(
                policy,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ).encode("utf-8") + b"\n"
            policy_hash = _sha256(raw)
            outcome = _write_create_only(target, raw)
            if outcome == "conflict":
                # Another process may have published the same semantic
                # version while this process was preparing its bytes.  Read
                # that winner and apply the same reuse/validation contract.
                return self._reuse_existing_policy(
                    target=target,
                    observed_at=observed_at,
                    policy_id=policy_id,
                    version=version,
                    source=source,
                    actor=actor,
                    approval=approval,
                    holding_horizon_trading_days=holding_horizon_trading_days,
                    review_cadence_trading_days=review_cadence_trading_days,
                    rule_payload=rule_payload,
                    current_calendar_hash=calendar_hash,
                    current_calendar_path=self.calendar_cache_path,
                )
            return self._write_activation_receipt(
                policy=policy,
                target=target,
                policy_hash=policy_hash,
                observed_at=observed_at,
                status="created" if outcome == "created" else "idempotent",
                calendar_observed_hash=calendar_hash,
                calendar_observed_path=self.calendar_cache_path,
                calendar_observed_effective_from=effective_from,
            )
        except (OSError, TypeError, ValueError, ForwardMachinePolicyError) as exc:
            return self._blocked(
                observed_at=(
                    observed_at
                    if observed_at is not None
                    else datetime.now(UTC)
                ),
                policy_path=None,
                policy_hash=None,
                blockers=(f"forward_machine_policy_blocked:{type(exc).__name__}:{exc}",),
            )

    def _policy_path(self, policy_id: str, version: str) -> Path:
        return (
            self.output_root
            / "policies"
            / f"{_safe_name(policy_id)}_{_safe_name(version)}.json"
        )

    def _calendar_snapshot_path(
        self, policy_id: str, version: str, calendar_hash: str
    ) -> Path:
        return (
            self.output_root
            / "calendar_snapshots"
            / (
                f"{_safe_name(policy_id)}_{_safe_name(version)}_"
                f"{_safe_name(calendar_hash[7:23])}.json"
            )
        )

    def _reuse_existing_policy(
        self,
        *,
        target: Path,
        observed_at: datetime,
        policy_id: str,
        version: str,
        source: str,
        actor: str,
        approval: str,
        holding_horizon_trading_days: int,
        review_cadence_trading_days: int,
        rule_payload: Sequence[Mapping[str, Any]],
        current_calendar_hash: str,
        current_calendar_path: Path,
    ) -> dict[str, Any]:
        try:
            policy, raw = _read_json_object(target)
            policy_hash = _sha256(raw)
            expected = {
                "schema_version": POLICY_SCHEMA_VERSION,
                "policy_id": policy_id,
                "version": version,
                "source": source,
                "actor": actor,
                "approval_reference": approval,
                "candidate_only": True,
                "research_only": True,
                "auto_action_allowed": False,
                "broker_order_allowed": False,
                "formal_credit": False,
                "holding_horizon_trading_days": holding_horizon_trading_days,
                "review_cadence_trading_days": review_cadence_trading_days,
                "invalidation_rules": list(rule_payload),
            }
            mismatches = [
                key for key, value in expected.items() if policy.get(key) != value
            ]
            if mismatches:
                return self._blocked(
                    observed_at=observed_at,
                    policy_path=target,
                    policy_hash=policy_hash,
                    blockers=(
                        "policy_version_immutable_conflict",
                        "policy_existing_request_mismatch:" + ",".join(mismatches),
                    ),
                )
            snapshot_raw_path = policy.get("calendar_cache_path")
            snapshot_path = Path(str(snapshot_raw_path or "")).expanduser().resolve()
            if snapshot_path == self.calendar_cache_path:
                raise ForwardMachinePolicyError(
                    "policy_existing_calendar_not_pinned"
                )
            if not snapshot_path.is_file():
                raise ForwardMachinePolicyError("policy_calendar_snapshot_missing")
            snapshot_hash = _sha256(snapshot_path.read_bytes())
            if snapshot_hash != policy.get("calendar_cache_hash"):
                raise ForwardMachinePolicyError("policy_calendar_snapshot_hash_mismatch")
            if not str(policy.get("effective_from") or "").strip():
                raise ForwardMachinePolicyError("policy_effective_from_missing")
            # The source cache may have been renewed since publication.  Keep
            # the old policy's snapshot/hash as historical custody, but
            # validate the current cache independently and record that
            # observation in the new receipt.  This preserves policy identity
            # across calendar renewal without mutating old bytes.
            current_effective_from = _next_effective_session(
                observed_at, self.calendar
            )
            if _sha256(current_calendar_path.read_bytes()) != current_calendar_hash:
                raise ForwardMachinePolicyError("calendar_source_changed_during_read")
            return self._write_activation_receipt(
                policy=policy,
                target=target,
                policy_hash=policy_hash,
                observed_at=observed_at,
                status="idempotent",
                calendar_observed_hash=current_calendar_hash,
                calendar_observed_path=current_calendar_path,
                calendar_observed_effective_from=current_effective_from,
            )
        except (OSError, TypeError, ValueError, ForwardMachinePolicyError) as exc:
            return self._blocked(
                observed_at=observed_at,
                policy_path=target,
                policy_hash=None,
                blockers=(f"policy_existing_invalid:{type(exc).__name__}:{exc}",),
            )

    def _write_activation_receipt(
        self,
        *,
        policy: Mapping[str, Any],
        target: Path,
        policy_hash: str,
        observed_at: datetime,
        status: str,
        calendar_observed_hash: str,
        calendar_observed_path: Path,
        calendar_observed_effective_from: date,
    ) -> dict[str, Any]:
        receipt = {
            "schema_version": PRODUCER_SCHEMA_VERSION,
            "status": status,
            "policy_observation": "published" if status == "created" else "reused",
            "policy_schema_version": POLICY_SCHEMA_VERSION,
            "policy_id": str(policy["policy_id"]),
            "policy_version": str(policy["version"]),
            "policy_path": str(target),
            "policy_file_sha256": policy_hash,
            "policy_bytes_immutable": True,
            "policy_status": str(policy["status"]),
            "effective_from": str(policy["effective_from"]),
            # Keep the policy's original custody timestamps stable.  The
            # receipt's ``observed_at``/``recorded_at`` are this invocation's
            # real wall clock and may advance on an idempotent retry.
            "available_at": str(policy["available_at"]),
            "policy_available_at": str(policy["available_at"]),
            "policy_recorded_at": str(policy["recorded_at"]),
            "observed_at": observed_at.isoformat(),
            "recorded_at": observed_at.isoformat(),
            "actor": str(policy["actor"]),
            "approval_reference": str(policy["approval_reference"]),
            "calendar_cache_path": str(policy["calendar_cache_path"]),
            "calendar_cache_sha256": str(policy["calendar_cache_hash"]),
            "calendar_source_path": str(policy.get("calendar_source_path") or ""),
            "calendar_source_sha256": str(
                policy.get("calendar_source_sha256")
                or policy["calendar_cache_hash"]
            ),
            "calendar_observed_path": str(calendar_observed_path),
            "calendar_observed_sha256": calendar_observed_hash,
            "calendar_observed_effective_from": calendar_observed_effective_from.isoformat(),
            "calendar_observation_validated": True,
            "research_only": True,
            "candidate_only": True,
            "auto_action_allowed": False,
            "broker_order_allowed": False,
            "formal_credit": False,
            "writes_paper_state": False,
            "writes_formal_state": False,
            "writes_market_database": False,
        }
        receipt_raw = json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8") + b"\n"
        receipt_hash = _sha256(receipt_raw)
        receipt_path = (
            self.output_root
            / "policy_activation"
            / (
                f"activation_{_safe_name(str(policy['policy_id']))}_"
                f"{_safe_name(str(policy['version']))}_{receipt_hash[7:23]}.json"
            )
        )
        _write_create_only(receipt_path, receipt_raw)
        latest = self.output_root / "policy_activation" / "latest.json"
        _write_atomic(
            latest,
            (
                json.dumps(
                    {
                        **receipt,
                        "receipt_path": str(receipt_path),
                        "receipt_sha256": receipt_hash,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            ).encode("utf-8"),
        )
        return {
            **receipt,
            "receipt_path": str(receipt_path),
            "latest_receipt_path": str(latest),
            "receipt_sha256": receipt_hash,
        }

    def _blocked(
        self,
        *,
        observed_at: datetime,
        policy_path: Path | None,
        policy_hash: str | None,
        blockers: Sequence[str],
    ) -> dict[str, Any]:
        return {
            "schema_version": PRODUCER_SCHEMA_VERSION,
            "status": "blocked",
            "observed_at": observed_at.isoformat(),
            "policy_path": None if policy_path is None else str(policy_path),
            "policy_file_sha256": policy_hash,
            "blockers": list(dict.fromkeys(str(item) for item in blockers)),
            "research_only": True,
            "candidate_only": True,
            "auto_action_allowed": False,
            "broker_order_allowed": False,
            "writes_paper_state": False,
            "writes_formal_state": False,
            "writes_market_database": False,
        }


def _safe_name(value: str) -> str:
    return "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_"
        for char in value
    )


__all__ = [
    "DEFAULT_ACTOR",
    "DEFAULT_POLICY_ID",
    "DEFAULT_RULES",
    "DEFAULT_SOURCE",
    "DEFAULT_VERSION",
    "ForwardMachinePolicyError",
    "ForwardMachinePolicyProducer",
    "POLICY_SCHEMA_VERSION",
    "PRODUCER_SCHEMA_VERSION",
]
