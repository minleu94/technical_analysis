"""Rule Champion 的受控儲存 attestation 與不可變 snapshot 契約。

此模組不會重算 Rule 分數，也不會讀取 outcome。正式 Champion 只接受
受控 runtime 設定的 HMAC-SHA256 驗證過之 canonical persisted bytes。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any, Literal, NoReturn, Protocol, Sequence
from zoneinfo import ZoneInfo


FORMAL_RULE_ONLY: Literal["formal_rule_only"] = "formal_rule_only"
FORMAL_RULE_ONLY_IMMUTABLE_DECISION_SNAPSHOT: Literal[
    "formal_rule_only_immutable_decision_snapshot"
] = "formal_rule_only_immutable_decision_snapshot"
_HMAC_KEY_ENV = "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY"
_STORE_ID_ENV = "RULE_CHAMPION_CONTROLLED_STORE_ID"
_ATTESTATION_PREFIX = "hmac-sha256:"
RULE_CHAMPION_HISTORY_SCHEMA_VERSION = "rule-champion-snapshot-history.v1"
_TAIPEI = ZoneInfo("Asia/Taipei")
_HISTORY_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "formal_source_only",
        "research_only",
        "formal_consumer_compatible",
        "promotion_eligible",
        "rule_only_proof",
        "registered_store_id",
        "decision_dates",
        "snapshot_count",
        "snapshots",
        "manifest_hash",
    }
)
_SNAPSHOT_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "champion_snapshot_family_id",
        "source_kind",
        "strategy_version",
        "policy_version",
        "score_configuration_hash",
        "universe_hash",
        "selection_capacity",
        "decision_timestamp",
        "decision_snapshot_ids",
        "source_lineage_artifact_ids",
        "rule_only_proof",
        "decision_rows",
        "content_hash",
    }
)


def _needs_human_decision(blocker: str) -> NoReturn:
    raise ValueError(f"needs_human_decision: {blocker}")


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _require_sha256(value: str, *, field_name: str) -> None:
    digest = value[7:] if value.startswith("sha256:") else ""
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")


def _payload_hash(payload: Mapping[str, object]) -> str:
    return f"sha256:{hashlib.sha256(_canonical_bytes(payload)).hexdigest()}"


def _runtime_attestation_config() -> tuple[bytes, str]:
    """僅從受控 runtime environment 取得 verification secret 與 store identity。"""
    key = os.environ.get(_HMAC_KEY_ENV)
    store_id = os.environ.get(_STORE_ID_ENV)
    if not key:
        _needs_human_decision("missing controlled runtime attestation key")
    if not store_id or not store_id.strip():
        _needs_human_decision("missing controlled runtime registered_store_id")
    return key.encode("utf-8"), store_id


@dataclass(frozen=True)
class FormalRuleDecisionSnapshot:
    """已驗證的 formal Rule-only persisted artifact。"""

    decision_snapshot_id: str
    decision_timestamp: str
    symbol: str
    rule_score_bp: int | None
    rule_rank: int
    source_artifact_kind: str
    source_lineage_artifact_id: str
    source_lineage_hash: str
    restrictions_hash: str
    immutable_snapshot_hash: str
    registered_store_id: str
    attestation_signature: str

    def __post_init__(self) -> None:
        for field_name in (
            "decision_snapshot_id",
            "decision_timestamp",
            "symbol",
            "source_artifact_kind",
            "source_lineage_artifact_id",
            "registered_store_id",
            "attestation_signature",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} is required")
        if self.source_artifact_kind != FORMAL_RULE_ONLY_IMMUTABLE_DECISION_SNAPSHOT:
            raise ValueError("source_artifact_kind must be a formal rule-only immutable decision snapshot")
        if self.rule_score_bp is None or isinstance(self.rule_score_bp, bool) or not isinstance(self.rule_score_bp, int):
            raise ValueError("rule_score_bp must be a persisted integer basis-point score")
        if isinstance(self.rule_rank, bool) or not isinstance(self.rule_rank, int) or self.rule_rank <= 0:
            raise ValueError("rule_rank must be a positive integer")
        _require_sha256(self.source_lineage_hash, field_name="source_lineage_hash")
        _require_sha256(self.restrictions_hash, field_name="restrictions_hash")
        _require_sha256(self.immutable_snapshot_hash, field_name="immutable_snapshot_hash")
        if self.immutable_snapshot_hash != _payload_hash(self._immutable_payload()):
            raise ValueError("immutable_snapshot_hash must verify the complete formal decision snapshot")

    def _immutable_payload(self) -> dict[str, object]:
        return {
            "schema_version": "FormalRuleDecisionSnapshot.v1",
            "source_artifact_kind": self.source_artifact_kind,
            "rule_only_proof": FORMAL_RULE_ONLY,
            "decision_snapshot_id": self.decision_snapshot_id,
            "decision_timestamp": self.decision_timestamp,
            "symbol": self.symbol,
            "rule_score_bp": self.rule_score_bp,
            "rule_rank": self.rule_rank,
            "source_lineage_artifact_id": self.source_lineage_artifact_id,
            "source_lineage_hash": self.source_lineage_hash,
            "restrictions_hash": self.restrictions_hash,
        }

    def to_manifest_row(self) -> dict[str, object]:
        return {
            **self._immutable_payload(),
            "immutable_snapshot_hash": self.immutable_snapshot_hash,
            "registered_store_id": self.registered_store_id,
            "attestation_signature": self.attestation_signature,
        }


class PersistedFormalDecisionArtifactLoader(Protocol):
    """受控 repository adapter；只能回傳原始 persisted artifact bytes。"""

    def load_registered_formal_decision_bytes(self, decision_snapshot_id: str) -> bytes | None:
        """傳回註冊 identity 的 canonical persisted bytes；找不到時傳回 ``None``。"""


_PERSISTED_ARTIFACT_FIELDS = frozenset(
    {
        "schema_version",
        "source_artifact_kind",
        "rule_only_proof",
        "decision_snapshot_id",
        "decision_timestamp",
        "symbol",
        "rule_score_bp",
        "rule_rank",
        "source_lineage_artifact_id",
        "source_lineage_hash",
        "restrictions_hash",
        "immutable_snapshot_hash",
        "registered_store_id",
        "attestation_signature",
    }
)


@dataclass(frozen=True)
class PersistedFormalDecisionArtifactRepository:
    """在建立 Champion 前驗證受控 store 的 artifact bytes 與 keyed attestation。"""

    loader: PersistedFormalDecisionArtifactLoader

    def __post_init__(self) -> None:
        if not callable(getattr(self.loader, "load_registered_formal_decision_bytes", None)):
            raise ValueError("needs_human_decision: controlled persisted formal-decision byte loader is required")

    def load_verified(self, decision_snapshot_id: str) -> FormalRuleDecisionSnapshot:
        if not isinstance(decision_snapshot_id, str) or not decision_snapshot_id.strip():
            _needs_human_decision("decision_snapshot_id is required")
        key, expected_store_id = _runtime_attestation_config()
        artifact_bytes = self.loader.load_registered_formal_decision_bytes(decision_snapshot_id)
        if not isinstance(artifact_bytes, bytes) or not artifact_bytes:
            _needs_human_decision("registered formal-decision artifact bytes are missing")
        artifact = _parse_canonical_artifact(artifact_bytes)
        if "attestation_signature" not in artifact:
            _needs_human_decision("attestation_signature is missing")
        if set(artifact) != _PERSISTED_ARTIFACT_FIELDS:
            _needs_human_decision("persisted formal-decision artifact has an unexpected schema")
        if artifact["schema_version"] != "FormalRuleDecisionSnapshot.v1":
            _needs_human_decision("persisted formal-decision artifact schema_version is invalid")
        if artifact["decision_snapshot_id"] != decision_snapshot_id:
            _needs_human_decision("persisted formal-decision artifact identity does not match the request")
        if artifact["registered_store_id"] != expected_store_id:
            _needs_human_decision("registered_store_id does not match controlled runtime identity")
        if artifact["rule_only_proof"] != FORMAL_RULE_ONLY:
            _needs_human_decision("persisted formal-decision artifact lacks rule-only proof")
        _verify_attestation(artifact, key)
        try:
            return FormalRuleDecisionSnapshot(
                decision_snapshot_id=_required_str(artifact, "decision_snapshot_id"),
                decision_timestamp=_required_str(artifact, "decision_timestamp"),
                symbol=_required_str(artifact, "symbol"),
                rule_score_bp=_required_int(artifact, "rule_score_bp"),
                rule_rank=_required_int(artifact, "rule_rank"),
                source_artifact_kind=_required_str(artifact, "source_artifact_kind"),
                source_lineage_artifact_id=_required_str(artifact, "source_lineage_artifact_id"),
                source_lineage_hash=_required_str(artifact, "source_lineage_hash"),
                restrictions_hash=_required_str(artifact, "restrictions_hash"),
                immutable_snapshot_hash=_required_str(artifact, "immutable_snapshot_hash"),
                registered_store_id=_required_str(artifact, "registered_store_id"),
                attestation_signature=_required_str(artifact, "attestation_signature"),
            )
        except ValueError as error:
            _needs_human_decision(str(error))


def _parse_canonical_artifact(artifact_bytes: bytes) -> dict[str, object]:
    try:
        parsed = json.loads(artifact_bytes.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _needs_human_decision("persisted formal-decision artifact bytes are invalid")
    if not isinstance(parsed, dict):
        _needs_human_decision("persisted formal-decision artifact must be a JSON object")
    if artifact_bytes != _canonical_bytes(parsed):
        _needs_human_decision("persisted formal-decision artifact bytes are not canonical")
    return parsed


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate artifact key")
        result[key] = value
    return result


def _verify_attestation(artifact: Mapping[str, object], key: bytes) -> None:
    signature = artifact.get("attestation_signature")
    if not isinstance(signature, str) or not signature.startswith(_ATTESTATION_PREFIX):
        _needs_human_decision("attestation_signature is missing or invalid")
    digest = signature[len(_ATTESTATION_PREFIX) :]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        _needs_human_decision("attestation_signature is missing or invalid")
    signing_payload = {name: value for name, value in artifact.items() if name != "attestation_signature"}
    expected = hmac.new(key, _canonical_bytes(signing_payload), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, expected):
        _needs_human_decision("controlled-store attestation verification failed")


def _required_str(artifact: Mapping[str, object], field_name: str) -> str:
    value = artifact[field_name]
    if not isinstance(value, str):
        raise ValueError(f"persisted formal-decision artifact {field_name} must be a string")
    return value


def _required_int(artifact: Mapping[str, object], field_name: str) -> int:
    value = artifact[field_name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"persisted formal-decision artifact {field_name} must be an integer")
    return value


@dataclass(frozen=True)
class RuleChampionSnapshot:
    """不可變 formal Rule Champion identity。"""

    champion_snapshot_family_id: str
    source_kind: Literal["formal_rule_only"]
    strategy_version: str
    policy_version: str
    score_configuration_hash: str
    universe_hash: str
    selection_capacity: int
    decision_timestamp: str
    decision_snapshot_ids: tuple[str, ...]
    source_lineage_artifact_ids: tuple[str, ...]
    decision_rows: tuple[FormalRuleDecisionSnapshot, ...]
    content_hash: str
    rule_only_proof: Literal["formal_rule_only"] = FORMAL_RULE_ONLY
    schema_version: Literal["RuleChampionSnapshot.v1"] = "RuleChampionSnapshot.v1"

    def to_manifest(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "champion_snapshot_family_id": self.champion_snapshot_family_id,
            "source_kind": self.source_kind,
            "strategy_version": self.strategy_version,
            "policy_version": self.policy_version,
            "score_configuration_hash": self.score_configuration_hash,
            "universe_hash": self.universe_hash,
            "selection_capacity": self.selection_capacity,
            "decision_timestamp": self.decision_timestamp,
            "decision_snapshot_ids": list(self.decision_snapshot_ids),
            "source_lineage_artifact_ids": list(self.source_lineage_artifact_ids),
            "rule_only_proof": self.rule_only_proof,
            "decision_rows": [row.to_manifest_row() for row in self.decision_rows],
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class RuleChampionSnapshotHistoryCustody:
    """已驗證的正式 Rule Champion history；不含未驗證的 fallback。"""

    manifest_path: Path
    manifest_file_hash: str
    manifest_hash: str
    decision_dates: tuple[str, ...]
    snapshots: tuple[RuleChampionSnapshot, ...]
    registered_store_id: str

    @property
    def snapshot_by_date(self) -> Mapping[str, RuleChampionSnapshot]:
        return {
            _taipei_date(snapshot.decision_timestamp): snapshot
            for snapshot in self.snapshots
        }

    def custody_payload(self) -> dict[str, object]:
        return {
            "schema_version": RULE_CHAMPION_HISTORY_SCHEMA_VERSION,
            "manifest_path": str(self.manifest_path),
            "manifest_file_hash": self.manifest_file_hash,
            "manifest_hash": self.manifest_hash,
            "decision_dates": list(self.decision_dates),
            "snapshot_count": len(self.snapshots),
            "registered_store_id": self.registered_store_id,
            "formal_source_only": True,
            "research_only": False,
            "formal_consumer_compatible": True,
            "promotion_eligible": False,
            "rule_only_proof": FORMAL_RULE_ONLY,
        }


class RuleChampionSnapshotService:
    """僅由受控 store 的 formal Rule decision records 建立 sidecar identity。"""

    def build(
        self,
        *,
        strategy_version: str,
        policy_version: str,
        score_configuration_hash: str,
        universe_hash: str,
        selection_capacity: int,
        repository: PersistedFormalDecisionArtifactRepository | None,
        decision_snapshot_ids: tuple[str, ...],
    ) -> RuleChampionSnapshot:
        for field_name, value in {"strategy_version": strategy_version, "policy_version": policy_version}.items():
            if not isinstance(value, str) or not value.strip():
                _needs_human_decision(f"{field_name} is required")
        try:
            _require_sha256(score_configuration_hash, field_name="score_configuration_hash")
            _require_sha256(universe_hash, field_name="universe_hash")
        except ValueError as error:
            _needs_human_decision(str(error))
        if isinstance(selection_capacity, bool) or not isinstance(selection_capacity, int) or selection_capacity <= 0:
            _needs_human_decision("selection_capacity must be a positive integer")
        if not isinstance(repository, PersistedFormalDecisionArtifactRepository):
            _needs_human_decision("a controlled persisted formal-decision repository is required")
        if not decision_snapshot_ids:
            _needs_human_decision("formal rule-only snapshot requires persisted decision rows")
        if any(not isinstance(snapshot_id, str) or not snapshot_id.strip() for snapshot_id in decision_snapshot_ids):
            _needs_human_decision("decision_snapshot_ids cannot contain empty values")
        if len(decision_snapshot_ids) != len(set(decision_snapshot_ids)):
            _needs_human_decision("decision_snapshot_id values must be unique")
        rows = tuple(repository.load_verified(snapshot_id) for snapshot_id in decision_snapshot_ids)
        if len(rows) > selection_capacity:
            _needs_human_decision("selection_capacity cannot be smaller than persisted decision rows")
        ranks = tuple(row.rule_rank for row in rows)
        if ranks != tuple(range(1, len(rows) + 1)):
            _needs_human_decision("persisted formal rule-only rows must use contiguous ascending ranks")
        decision_timestamps = {row.decision_timestamp for row in rows}
        if len(decision_timestamps) != 1:
            _needs_human_decision("Rule Champion rows must share the same decision_timestamp")
        decision_timestamp = rows[0].decision_timestamp
        snapshot_ids = tuple(row.decision_snapshot_id for row in rows)
        lineage_artifact_ids = tuple(row.source_lineage_artifact_id for row in rows)
        payload: dict[str, object] = {
            "schema_version": "RuleChampionSnapshot.v1",
            "source_kind": FORMAL_RULE_ONLY,
            "strategy_version": strategy_version,
            "policy_version": policy_version,
            "score_configuration_hash": score_configuration_hash,
            "universe_hash": universe_hash,
            "selection_capacity": selection_capacity,
            "decision_timestamp": decision_timestamp,
            "decision_snapshot_ids": list(snapshot_ids),
            "source_lineage_artifact_ids": list(lineage_artifact_ids),
            "rule_only_proof": FORMAL_RULE_ONLY,
            "decision_rows": [row.to_manifest_row() for row in rows],
        }
        content_hash = _payload_hash(payload)
        return RuleChampionSnapshot(
            champion_snapshot_family_id=f"champion:{strategy_version}:{content_hash[7:19]}",
            source_kind=FORMAL_RULE_ONLY,
            strategy_version=strategy_version,
            policy_version=policy_version,
            score_configuration_hash=score_configuration_hash,
            universe_hash=universe_hash,
            selection_capacity=selection_capacity,
            decision_timestamp=decision_timestamp,
            decision_snapshot_ids=snapshot_ids,
            source_lineage_artifact_ids=lineage_artifact_ids,
            decision_rows=rows,
            content_hash=content_hash,
        )


def load_verified_rule_champion_snapshot_history(
    manifest_path: Path,
    *,
    decision_dates: Sequence[str] | None = None,
    training_as_of: str | None = None,
) -> RuleChampionSnapshotHistoryCustody:
    """驗證受控 store 發布的 Rule Champion history manifest。

    History manifest 只攜帶已簽章的 snapshot rows；每一列仍必須通過既有
    controlled runtime HMAC、immutable snapshot hash、rank 與 timestamp
    驗證。這裡不接受研究 ledger、未簽章 JSON 或以目前公司清單回填的資料。
    """

    resolved_path = manifest_path.resolve()
    if not resolved_path.is_file():
        raise FileNotFoundError(
            f"formal Rule Champion history manifest is missing: {resolved_path}"
        )
    payload = _read_history_json(resolved_path)
    _validate_history_manifest(payload)
    manifest_hash = _history_sha256(payload.get("manifest_hash"), "manifest_hash")
    body = dict(payload)
    body.pop("manifest_hash", None)
    if _payload_hash(body) != manifest_hash:
        _needs_human_decision("Rule Champion history manifest hash mismatch")
    manifest_file_hash = _file_hash(resolved_path)

    expected_store_id = _history_str(
        payload.get("registered_store_id"),
        "registered_store_id",
    )
    _key, runtime_store_id = _runtime_attestation_config()
    if expected_store_id != runtime_store_id:
        _needs_human_decision("Rule Champion history store identity mismatch")
    declared_dates = _history_dates(
        payload.get("decision_dates"),
        field_name="decision_dates",
    )
    snapshots_value = payload.get("snapshots")
    if not isinstance(snapshots_value, list):
        _needs_human_decision("Rule Champion history snapshots must be an array")
    snapshots = tuple(
        _snapshot_from_manifest(
            item,
            key=_key,
            expected_store_id=expected_store_id,
        )
        for item in snapshots_value
    )
    if _history_int(payload.get("snapshot_count"), "snapshot_count") != len(
        snapshots
    ):
        _needs_human_decision("Rule Champion history snapshot_count mismatch")
    if len(snapshots) != len(set(declared_dates)):
        _needs_human_decision("Rule Champion history snapshot coverage is incomplete")
    observed_dates = tuple(
        _taipei_date(snapshot.decision_timestamp) for snapshot in snapshots
    )
    if observed_dates != declared_dates:
        _needs_human_decision("Rule Champion history decision dates are not sorted")
    if decision_dates is not None:
        expected_dates = _history_dates(
            list(decision_dates),
            field_name="expected_decision_dates",
        )
        if declared_dates != expected_dates:
            _needs_human_decision(
                "Rule Champion history does not cover assembly decision dates"
            )
    if training_as_of is not None:
        cutoff = _history_datetime(training_as_of, field_name="training_as_of")
        if any(
            _history_datetime(snapshot.decision_timestamp, field_name="decision_timestamp")
            > cutoff
            for snapshot in snapshots
        ):
            _needs_human_decision(
                "Rule Champion history contains a snapshot after training_as_of"
            )

    return RuleChampionSnapshotHistoryCustody(
        manifest_path=resolved_path,
        manifest_file_hash=manifest_file_hash,
        manifest_hash=manifest_hash,
        decision_dates=declared_dates,
        snapshots=snapshots,
        registered_store_id=expected_store_id,
    )


def _snapshot_from_manifest(
    value: object,
    *,
    key: bytes,
    expected_store_id: str,
) -> RuleChampionSnapshot:
    if not isinstance(value, dict):
        _needs_human_decision("Rule Champion snapshot must be an object")
    if set(value) != _SNAPSHOT_MANIFEST_FIELDS:
        _needs_human_decision("Rule Champion snapshot fields mismatch")
    if value.get("schema_version") != "RuleChampionSnapshot.v1":
        _needs_human_decision("Rule Champion snapshot schema_version is invalid")
    if value.get("source_kind") != FORMAL_RULE_ONLY:
        _needs_human_decision("Rule Champion snapshot source_kind is invalid")
    if value.get("rule_only_proof") != FORMAL_RULE_ONLY:
        _needs_human_decision("Rule Champion snapshot lacks rule-only proof")
    strategy_version = _history_str(value.get("strategy_version"), "strategy_version")
    policy_version = _history_str(value.get("policy_version"), "policy_version")
    score_configuration_hash = _history_sha256(
        value.get("score_configuration_hash"),
        "score_configuration_hash",
    )
    universe_hash = _history_sha256(value.get("universe_hash"), "universe_hash")
    selection_capacity = _history_int(
        value.get("selection_capacity"),
        "selection_capacity",
    )
    if selection_capacity <= 0:
        _needs_human_decision("Rule Champion selection_capacity must be positive")
    decision_timestamp = _history_str(
        value.get("decision_timestamp"),
        "decision_timestamp",
    )
    _history_datetime(decision_timestamp, field_name="decision_timestamp")
    decision_ids = _history_text_sequence(
        value.get("decision_snapshot_ids"),
        field_name="decision_snapshot_ids",
    )
    lineage_ids = _history_text_sequence(
        value.get("source_lineage_artifact_ids"),
        field_name="source_lineage_artifact_ids",
    )
    rows_value = value.get("decision_rows")
    if not isinstance(rows_value, list) or not rows_value:
        _needs_human_decision("Rule Champion snapshot decision_rows are required")
    rows = tuple(
        _verified_history_row(
            item,
            key=key,
            expected_store_id=expected_store_id,
        )
        for item in rows_value
    )
    if len(rows) > selection_capacity:
        _needs_human_decision("Rule Champion selection_capacity is too small")
    if tuple(row.decision_snapshot_id for row in rows) != decision_ids:
        _needs_human_decision("Rule Champion decision_snapshot_ids mismatch")
    if tuple(row.source_lineage_artifact_id for row in rows) != lineage_ids:
        _needs_human_decision("Rule Champion source lineage ids mismatch")
    if tuple(row.rule_rank for row in rows) != tuple(range(1, len(rows) + 1)):
        _needs_human_decision("Rule Champion rows must use contiguous ranks")
    if {row.decision_timestamp for row in rows} != {decision_timestamp}:
        _needs_human_decision("Rule Champion rows must share decision_timestamp")

    content_payload = {
        "schema_version": "RuleChampionSnapshot.v1",
        "source_kind": FORMAL_RULE_ONLY,
        "strategy_version": strategy_version,
        "policy_version": policy_version,
        "score_configuration_hash": score_configuration_hash,
        "universe_hash": universe_hash,
        "selection_capacity": selection_capacity,
        "decision_timestamp": decision_timestamp,
        "decision_snapshot_ids": list(decision_ids),
        "source_lineage_artifact_ids": list(lineage_ids),
        "rule_only_proof": FORMAL_RULE_ONLY,
        "decision_rows": [row.to_manifest_row() for row in rows],
    }
    content_hash = _payload_hash(content_payload)
    if value.get("content_hash") != content_hash:
        _needs_human_decision("Rule Champion snapshot content hash mismatch")
    expected_family = f"champion:{strategy_version}:{content_hash[7:19]}"
    if value.get("champion_snapshot_family_id") != expected_family:
        _needs_human_decision("Rule Champion snapshot family id mismatch")
    return RuleChampionSnapshot(
        champion_snapshot_family_id=expected_family,
        source_kind=FORMAL_RULE_ONLY,
        strategy_version=strategy_version,
        policy_version=policy_version,
        score_configuration_hash=score_configuration_hash,
        universe_hash=universe_hash,
        selection_capacity=selection_capacity,
        decision_timestamp=decision_timestamp,
        decision_snapshot_ids=decision_ids,
        source_lineage_artifact_ids=lineage_ids,
        decision_rows=rows,
        content_hash=content_hash,
    )


def _verified_history_row(
    value: object,
    *,
    key: bytes,
    expected_store_id: str,
) -> FormalRuleDecisionSnapshot:
    if not isinstance(value, dict):
        _needs_human_decision("Rule Champion decision row must be an object")
    if set(value) != _PERSISTED_ARTIFACT_FIELDS:
        _needs_human_decision("Rule Champion decision row fields mismatch")
    if value.get("schema_version") != "FormalRuleDecisionSnapshot.v1":
        _needs_human_decision("Rule Champion decision row schema_version is invalid")
    if value.get("source_artifact_kind") != FORMAL_RULE_ONLY_IMMUTABLE_DECISION_SNAPSHOT:
        _needs_human_decision("Rule Champion decision row source kind is invalid")
    if value.get("rule_only_proof") != FORMAL_RULE_ONLY:
        _needs_human_decision("Rule Champion decision row lacks rule-only proof")
    if value.get("registered_store_id") != expected_store_id:
        _needs_human_decision("Rule Champion decision row store identity mismatch")
    _verify_attestation(value, key)
    try:
        return FormalRuleDecisionSnapshot(
            decision_snapshot_id=_history_str(value.get("decision_snapshot_id"), "decision_snapshot_id"),
            decision_timestamp=_history_str(value.get("decision_timestamp"), "decision_timestamp"),
            symbol=_history_str(value.get("symbol"), "symbol"),
            rule_score_bp=_history_int(value.get("rule_score_bp"), "rule_score_bp"),
            rule_rank=_history_int(value.get("rule_rank"), "rule_rank"),
            source_artifact_kind=_history_str(value.get("source_artifact_kind"), "source_artifact_kind"),
            source_lineage_artifact_id=_history_str(
                value.get("source_lineage_artifact_id"),
                "source_lineage_artifact_id",
            ),
            source_lineage_hash=_history_str(value.get("source_lineage_hash"), "source_lineage_hash"),
            restrictions_hash=_history_str(value.get("restrictions_hash"), "restrictions_hash"),
            immutable_snapshot_hash=_history_str(
                value.get("immutable_snapshot_hash"),
                "immutable_snapshot_hash",
            ),
            registered_store_id=_history_str(value.get("registered_store_id"), "registered_store_id"),
            attestation_signature=_history_str(
                value.get("attestation_signature"),
                "attestation_signature",
            ),
        )
    except ValueError as error:
        _needs_human_decision(str(error))


def _validate_history_manifest(payload: Mapping[str, object]) -> None:
    if set(payload) != _HISTORY_FIELDS:
        _needs_human_decision("Rule Champion history manifest fields mismatch")
    if payload.get("schema_version") != RULE_CHAMPION_HISTORY_SCHEMA_VERSION:
        _needs_human_decision("Rule Champion history schema_version is invalid")
    if payload.get("status") != "complete":
        _needs_human_decision("Rule Champion history is not complete")
    if payload.get("formal_source_only") is not True:
        _needs_human_decision("Rule Champion history must be formal_source_only")
    if payload.get("research_only") is not False:
        _needs_human_decision("research-only Rule Champion history is rejected")
    if payload.get("formal_consumer_compatible") is not True:
        _needs_human_decision("Rule Champion history must be consumer compatible")
    if payload.get("promotion_eligible") is not False:
        _needs_human_decision("Rule Champion history is not a promotion artifact")
    if payload.get("rule_only_proof") != FORMAL_RULE_ONLY:
        _needs_human_decision("Rule Champion history lacks rule-only proof")


def _read_history_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        _needs_human_decision(f"Rule Champion history JSON is invalid: {error}")
    if not isinstance(value, dict):
        _needs_human_decision("Rule Champion history manifest must be an object")
    return value


def _history_dates(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        _needs_human_decision(f"{field_name} must be an array")
    dates: list[str] = []
    for item in value:
        text = _history_str(item, field_name)
        try:
            date.fromisoformat(text[:10])
        except ValueError:
            _needs_human_decision(f"{field_name} contains an invalid date")
        dates.append(text[:10])
    if tuple(dates) != tuple(sorted(set(dates))):
        _needs_human_decision(f"{field_name} must be unique and sorted")
    return tuple(dates)


def _history_text_sequence(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        _needs_human_decision(f"{field_name} must be an array")
    return tuple(_history_str(item, field_name) for item in value)


def _history_datetime(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        _needs_human_decision(f"{field_name} must be an ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _needs_human_decision(f"{field_name} must include timezone")
    return parsed.astimezone(_TAIPEI)


def _taipei_date(value: str) -> str:
    return _history_datetime(value, field_name="decision_timestamp").date().isoformat()


def _history_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _needs_human_decision(f"{field_name} is required")
    return value


def _history_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _needs_human_decision(f"{field_name} must be an integer")
    return value


def _history_sha256(value: object, field_name: str) -> str:
    result = _history_str(value, field_name)
    try:
        _require_sha256(result, field_name=field_name)
    except ValueError as error:
        _needs_human_decision(str(error))
    return result


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"
