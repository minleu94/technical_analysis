"""Clock-bound publisher for prospective formal Rule Champion history.

這個 publisher 不重算 Rule 分數，也不自行持有 HMAC secret。每個 decision row
仍由既有 ``RuleChampionSnapshotService`` 從 controlled-store persisted bytes 驗證
HMAC、immutable snapshot hash、store identity 與 contiguous rank；本模組只把已
驗證的 ``RuleChampionSnapshot.v1`` 包在 prospective clock binding 內，以 canonical
bytes 一次性寫成不可覆寫的 history manifest。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from data_module.prospective_formal_clock import (
    ProspectiveFormalClock,
    canonical_json,
    file_sha256,
    payload_hash,
)
from data_module.rule_champion_snapshot_service import (
    FORMAL_RULE_ONLY,
    PersistedFormalDecisionArtifactRepository,
    RuleChampionSnapshot,
    RuleChampionSnapshotService,
)


PROSPECTIVE_RULE_HISTORY_SCHEMA_VERSION = (
    "prospective-formal-rule-champion-snapshot-history.v1"
)
PROSPECTIVE_RULE_HISTORY_RESULT_SCHEMA_VERSION = (
    "prospective-formal-rule-champion-history-publish-result.v1"
)
RULE_CHAMPION_CONTROLLED_STORE_ID_ENV = "RULE_CHAMPION_CONTROLLED_STORE_ID"
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")

_HISTORY_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "formal_source_only",
        "research_only",
        "formal_consumer_compatible",
        "promotion_eligible",
        "rule_only_proof",
        "consumer_mode",
        "historical_backfill_claimed",
        "clock_id",
        "clock_manifest_hash",
        "activation_trading_day",
        "decision_timezone",
        "decision_time",
        "registered_store_id",
        "strategy_version",
        "policy_version",
        "score_configuration_hash",
        "universe_hash",
        "selection_capacity",
        "decision_dates",
        "snapshot_count",
        "snapshots",
        "manifest_hash",
    }
)


class ProspectiveRuleChampionPublisherError(ValueError):
    """Prospective Rule history 不符合 clock／custody 契約。"""


@dataclass(frozen=True)
class ProspectiveRuleSnapshotRequest:
    """一個決策日要由 controlled store 驗證的 snapshot ids。"""

    decision_date: str
    decision_snapshot_ids: tuple[str, ...]


@dataclass(frozen=True)
class ProspectiveRuleHistoryPublishResult:
    """不含 secret 的 publish 結果。"""

    manifest_path: Path
    manifest_hash: str
    manifest_file_hash: str
    clock_id: str
    decision_dates: tuple[str, ...]
    snapshot_count: int
    registered_store_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": PROSPECTIVE_RULE_HISTORY_RESULT_SCHEMA_VERSION,
            "status": "published",
            "manifest_path": str(self.manifest_path),
            "manifest_hash": self.manifest_hash,
            "manifest_file_hash": self.manifest_file_hash,
            "clock_id": self.clock_id,
            "decision_dates": list(self.decision_dates),
            "snapshot_count": self.snapshot_count,
            "registered_store_id": self.registered_store_id,
            "secret_values_emitted": False,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "broker_order_allowed": False,
        }


def publish_prospective_rule_history(
    *,
    clock: ProspectiveFormalClock,
    output_path: Path,
    now: datetime,
    strategy_version: str,
    policy_version: str,
    score_configuration_hash: str,
    universe_hash: str,
    selection_capacity: int,
    repository: PersistedFormalDecisionArtifactRepository,
    requests: Sequence[ProspectiveRuleSnapshotRequest],
) -> ProspectiveRuleHistoryPublishResult:
    """驗證並一次性發布一份 clock-bound Rule Champion history。

    ``requests`` 必須只包含 activation day 之後、且已經真實到達 ``now`` 的
    decision timestamps。這個函式不接受手工分數、未簽章 row 或 outcome；output
    parent 必須事先存在，既有檔案也不會被覆寫。
    """

    _validate_now(now)
    if not isinstance(clock, ProspectiveFormalClock):
        raise ProspectiveRuleChampionPublisherError("validated prospective clock is required")
    if not isinstance(repository, PersistedFormalDecisionArtifactRepository):
        raise ProspectiveRuleChampionPublisherError(
            "controlled persisted formal-decision repository is required"
        )
    strategy_version = _required_text(strategy_version, "strategy_version")
    policy_version = _required_text(policy_version, "policy_version")
    expected_strategy = str(clock.payload["strategy_version"])
    expected_policy = str(clock.payload["policy_version"])
    if strategy_version != expected_strategy:
        raise ProspectiveRuleChampionPublisherError(
            "strategy_version does not match prospective clock"
        )
    if policy_version != expected_policy:
        raise ProspectiveRuleChampionPublisherError(
            "policy_version does not match prospective clock"
        )
    _require_sha256(score_configuration_hash, "score_configuration_hash")
    _require_sha256(universe_hash, "universe_hash")
    if universe_hash != str(clock.payload["universe_hash"]):
        raise ProspectiveRuleChampionPublisherError(
            "universe_hash does not match prospective clock"
        )
    if isinstance(selection_capacity, bool) or not isinstance(selection_capacity, int):
        raise ProspectiveRuleChampionPublisherError("selection_capacity must be an integer")
    if selection_capacity <= 0:
        raise ProspectiveRuleChampionPublisherError(
            "selection_capacity must be positive"
        )
    if not requests:
        raise ProspectiveRuleChampionPublisherError(
            "at least one prospective Rule snapshot request is required"
        )
    store_id = _runtime_store_id()
    decision_time = _clock_decision_time(clock)
    now_taipei = now.astimezone(TAIPEI_TIMEZONE)
    activation_day = clock.activation_trading_day
    normalized_requests = tuple(requests)
    dates: list[str] = []
    snapshots: list[RuleChampionSnapshot] = []
    seen_ids: set[str] = set()
    for request in normalized_requests:
        if not isinstance(request, ProspectiveRuleSnapshotRequest):
            raise ProspectiveRuleChampionPublisherError(
                "requests must contain ProspectiveRuleSnapshotRequest values"
            )
        requested_day = _parse_date(request.decision_date, "decision_date")
        if requested_day < activation_day:
            raise ProspectiveRuleChampionPublisherError(
                "Rule snapshot decision date precedes prospective activation"
            )
        if requested_day > now_taipei.date():
            raise ProspectiveRuleChampionPublisherError(
                "Rule snapshot decision date is in the future"
            )
        if dates and requested_day.isoformat() <= dates[-1]:
            raise ProspectiveRuleChampionPublisherError(
                "Rule snapshot decision dates must be unique and sorted"
            )
        ids = _normalize_snapshot_ids(request.decision_snapshot_ids)
        if seen_ids.intersection(ids):
            raise ProspectiveRuleChampionPublisherError(
                "decision_snapshot_id cannot be reused across dates"
            )
        seen_ids.update(ids)
        snapshot = RuleChampionSnapshotService().build(
            strategy_version=strategy_version,
            policy_version=policy_version,
            score_configuration_hash=score_configuration_hash,
            universe_hash=universe_hash,
            selection_capacity=selection_capacity,
            repository=repository,
            decision_snapshot_ids=ids,
        )
        local_timestamp = _parse_taipei_timestamp(snapshot.decision_timestamp)
        if local_timestamp.date() != requested_day:
            raise ProspectiveRuleChampionPublisherError(
                "Rule Champion decision timestamp does not match requested date"
            )
        if local_timestamp.timetz().replace(tzinfo=None) != decision_time:
            raise ProspectiveRuleChampionPublisherError(
                "Rule Champion decision timestamp does not match clock decision_time"
            )
        if local_timestamp > now_taipei:
            raise ProspectiveRuleChampionPublisherError(
                "Rule Champion decision timestamp is after capture now"
            )
        if snapshot.strategy_version != strategy_version:
            raise ProspectiveRuleChampionPublisherError("snapshot strategy identity mismatch")
        if snapshot.policy_version != policy_version:
            raise ProspectiveRuleChampionPublisherError("snapshot policy identity mismatch")
        if snapshot.universe_hash != universe_hash:
            raise ProspectiveRuleChampionPublisherError("snapshot universe hash mismatch")
        if any(row.registered_store_id != store_id for row in snapshot.decision_rows):
            raise ProspectiveRuleChampionPublisherError(
                "snapshot controlled-store identity mismatch"
            )
        dates.append(requested_day.isoformat())
        snapshots.append(snapshot)

    body: dict[str, object] = {
        "schema_version": PROSPECTIVE_RULE_HISTORY_SCHEMA_VERSION,
        "status": "complete",
        "formal_source_only": True,
        "research_only": False,
        "formal_consumer_compatible": True,
        "promotion_eligible": False,
        "rule_only_proof": FORMAL_RULE_ONLY,
        "consumer_mode": "prospective_formal_simulation",
        "historical_backfill_claimed": False,
        "clock_id": clock.clock_id,
        "clock_manifest_hash": clock.manifest_hash,
        "activation_trading_day": activation_day.isoformat(),
        "decision_timezone": "Asia/Taipei",
        "decision_time": decision_time.isoformat(),
        "registered_store_id": store_id,
        "strategy_version": strategy_version,
        "policy_version": policy_version,
        "score_configuration_hash": score_configuration_hash,
        "universe_hash": universe_hash,
        "selection_capacity": selection_capacity,
        "decision_dates": dates,
        "snapshot_count": len(snapshots),
        "snapshots": [snapshot.to_manifest() for snapshot in snapshots],
    }
    manifest = {**body, "manifest_hash": payload_hash(body)}
    _validate_manifest_shape(manifest)
    output = output_path.expanduser().resolve()
    if not output.parent.exists():
        raise ProspectiveRuleChampionPublisherError(
            "output parent directory must already exist"
        )
    _write_immutable_json(output, manifest)
    return ProspectiveRuleHistoryPublishResult(
        manifest_path=output,
        manifest_hash=str(manifest["manifest_hash"]),
        manifest_file_hash=file_sha256(output),
        clock_id=clock.clock_id,
        decision_dates=tuple(dates),
        snapshot_count=len(snapshots),
        registered_store_id=store_id,
    )


def _validate_manifest_shape(manifest: Mapping[str, object]) -> None:
    if set(manifest) != _HISTORY_FIELDS:
        raise ProspectiveRuleChampionPublisherError(
            "prospective Rule history manifest fields mismatch"
        )
    if manifest.get("schema_version") != PROSPECTIVE_RULE_HISTORY_SCHEMA_VERSION:
        raise ProspectiveRuleChampionPublisherError("prospective Rule history schema mismatch")
    body = dict(manifest)
    supplied = body.pop("manifest_hash", None)
    if not isinstance(supplied, str) or supplied != payload_hash(body):
        raise ProspectiveRuleChampionPublisherError(
            "prospective Rule history manifest hash mismatch"
        )


def _runtime_store_id() -> str:
    value = os.environ.get(RULE_CHAMPION_CONTROLLED_STORE_ID_ENV)
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveRuleChampionPublisherError(
            "controlled runtime registered_store_id is missing"
        )
    return value


def _clock_decision_time(clock: ProspectiveFormalClock) -> time:
    value = clock.payload.get("decision_time")
    if not isinstance(value, str):
        raise ProspectiveRuleChampionPublisherError("clock decision_time is invalid")
    try:
        parsed = time.fromisoformat(value)
    except ValueError as error:
        raise ProspectiveRuleChampionPublisherError(
            "clock decision_time is invalid"
        ) from error
    if parsed.tzinfo is not None:
        raise ProspectiveRuleChampionPublisherError(
            "clock decision_time must not contain timezone"
        )
    return parsed


def _normalize_snapshot_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ProspectiveRuleChampionPublisherError(
            "decision_snapshot_ids must be a tuple"
        )
    if not value:
        raise ProspectiveRuleChampionPublisherError(
            "decision_snapshot_ids cannot be empty"
        )
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ProspectiveRuleChampionPublisherError(
            "decision_snapshot_ids must contain non-empty text"
        )
    if len(value) != len(set(value)):
        raise ProspectiveRuleChampionPublisherError(
            "decision_snapshot_ids must be unique"
        )
    return value


def _parse_date(value: object, field_name: str) -> date:
    if not isinstance(value, str):
        raise ProspectiveRuleChampionPublisherError(
            f"{field_name} must be an ISO date"
        )
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ProspectiveRuleChampionPublisherError(
            f"{field_name} must be an ISO date"
        ) from error
    if parsed.isoformat() != value:
        raise ProspectiveRuleChampionPublisherError(
            f"{field_name} must use YYYY-MM-DD"
        )
    return parsed


def _parse_taipei_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ProspectiveRuleChampionPublisherError(
            "decision_timestamp must be timezone-aware ISO datetime"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProspectiveRuleChampionPublisherError(
            "decision_timestamp is invalid"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProspectiveRuleChampionPublisherError(
            "decision_timestamp must include timezone"
        )
    return parsed.astimezone(TAIPEI_TIMEZONE)


def _validate_now(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ProspectiveRuleChampionPublisherError("now must include timezone")


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveRuleChampionPublisherError(
            f"{field_name} must be non-empty text"
        )
    return value


def _require_sha256(value: object, field_name: str) -> None:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        raise ProspectiveRuleChampionPublisherError(
            f"{field_name} must be sha256"
        )
    if any(char not in "0123456789abcdef" for char in value[7:]):
        raise ProspectiveRuleChampionPublisherError(
            f"{field_name} must be sha256"
        )


def _write_immutable_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = canonical_json(payload).encode("utf-8")
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProspectiveRuleChampionPublisherError(
            "prospective Rule history output already exists"
        ) from error


class JsonPersistedFormalArtifactLoader:
    """CLI fixture loader；每個 artifact bytes 仍交給既有 HMAC verifier。"""

    def __init__(self, artifact_index_path: Path) -> None:
        resolved = artifact_index_path.expanduser().resolve()
        try:
            value: Any = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProspectiveRuleChampionPublisherError(
                "fixture artifact index is unreadable"
            ) from error
        if not isinstance(value, dict):
            raise ProspectiveRuleChampionPublisherError(
                "fixture artifact index must be an object"
            )
        self._artifacts = value

    def load_registered_formal_decision_bytes(
        self,
        decision_snapshot_id: str,
    ) -> bytes | None:
        value = self._artifacts.get(decision_snapshot_id)
        if not isinstance(value, dict):
            return None
        return canonical_json(value).encode("utf-8")
