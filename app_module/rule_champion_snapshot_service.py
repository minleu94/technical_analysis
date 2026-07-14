"""Rule Champion 的受控儲存 attestation 與不可變 snapshot 契約。

此模組不會重算 Rule 分數，也不會讀取 outcome。正式 Champion 只接受
受控 runtime 設定的 HMAC-SHA256 驗證過之 canonical persisted bytes。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from typing import Any, Literal, NoReturn, Protocol


FORMAL_RULE_ONLY: Literal["formal_rule_only"] = "formal_rule_only"
FORMAL_RULE_ONLY_IMMUTABLE_DECISION_SNAPSHOT: Literal[
    "formal_rule_only_immutable_decision_snapshot"
] = "formal_rule_only_immutable_decision_snapshot"
_HMAC_KEY_ENV = "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY"
_STORE_ID_ENV = "RULE_CHAMPION_CONTROLLED_STORE_ID"
_ATTESTATION_PREFIX = "hmac-sha256:"


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
