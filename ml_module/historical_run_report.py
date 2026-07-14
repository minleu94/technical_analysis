"""Immutable report contract for historical ML shadow runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping


_RESULT_STATUSES = frozenset({"reject", "continue_shadow", "shadow_candidate"})
_EVIDENCE_TIERS = frozenset({"historical_locked_oos", "historical_research_rehearsal"})


@dataclass(frozen=True)
class HistoricalMLShadowRunReport:
    run_id: str
    dataset_id: str
    model_id: str
    training_end_date: str
    oos_start_date: str
    oos_end_date: str
    accepted_rows: int
    excluded_rows: int
    fold_ids: tuple[str, ...]
    metrics_bp: Mapping[str, int]
    artifact_hashes: Mapping[str, str]
    blockers: tuple[str, ...]
    evidence_tier: str
    result_status: str
    report_hash: str
    schema_version: str = "historical-ml-shadow-run-report.v1"
    shadow_only: bool = True
    production_eligible: bool = False
    production_action_allowed: bool = False

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        dataset_id: str,
        model_id: str,
        training_end_date: str,
        oos_start_date: str,
        oos_end_date: str,
        accepted_rows: int,
        excluded_rows: int,
        fold_ids: tuple[str, ...],
        metrics_bp: Mapping[str, int],
        artifact_hashes: Mapping[str, str],
        blockers: tuple[str, ...],
        evidence_tier: str,
        result_status: str,
    ) -> "HistoricalMLShadowRunReport":
        for field_name, value in {
            "run_id": run_id,
            "dataset_id": dataset_id,
            "model_id": model_id,
        }.items():
            if not value or not value.strip():
                raise ValueError(f"{field_name} is required")
        training_end = date.fromisoformat(training_end_date[:10])
        oos_start = date.fromisoformat(oos_start_date[:10])
        oos_end = date.fromisoformat(oos_end_date[:10])
        if training_end >= oos_start or oos_start > oos_end:
            raise ValueError("historical run report date range is incoherent")
        for count_name, count in {
            "accepted_rows": accepted_rows,
            "excluded_rows": excluded_rows,
        }.items():
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError(f"{count_name} must be a non-negative integer")
        if accepted_rows == 0:
            raise ValueError("accepted_rows must be positive")
        if not fold_ids or any(not fold_id for fold_id in fold_ids):
            raise ValueError("fold_ids must be non-empty")
        if len(fold_ids) != len(set(fold_ids)):
            raise ValueError("fold_ids must be unique")
        normalized_metrics = _normalize_metrics(metrics_bp)
        normalized_hashes = _normalize_hashes(artifact_hashes)
        if any(not blocker for blocker in blockers):
            raise ValueError("blockers must not contain empty values")
        if evidence_tier not in _EVIDENCE_TIERS:
            raise ValueError("unsupported evidence_tier")
        if result_status not in _RESULT_STATUSES:
            raise ValueError("unsupported result_status")
        payload = {
            "schema_version": "historical-ml-shadow-run-report.v1",
            "run_id": run_id,
            "dataset_id": dataset_id,
            "model_id": model_id,
            "training_end_date": training_end_date,
            "oos_start_date": oos_start_date,
            "oos_end_date": oos_end_date,
            "accepted_rows": accepted_rows,
            "excluded_rows": excluded_rows,
            "fold_ids": list(fold_ids),
            "metrics_bp": normalized_metrics,
            "artifact_hashes": normalized_hashes,
            "blockers": list(blockers),
            "evidence_tier": evidence_tier,
            "result_status": result_status,
            "shadow_only": True,
            "production_eligible": False,
            "production_action_allowed": False,
        }
        return cls(
            run_id=run_id,
            dataset_id=dataset_id,
            model_id=model_id,
            training_end_date=training_end_date,
            oos_start_date=oos_start_date,
            oos_end_date=oos_end_date,
            accepted_rows=accepted_rows,
            excluded_rows=excluded_rows,
            fold_ids=fold_ids,
            metrics_bp=MappingProxyType(normalized_metrics),
            artifact_hashes=MappingProxyType(normalized_hashes),
            blockers=blockers,
            evidence_tier=evidence_tier,
            result_status=result_status,
            report_hash=_hash_payload(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "dataset_id": self.dataset_id,
            "model_id": self.model_id,
            "training_end_date": self.training_end_date,
            "oos_start_date": self.oos_start_date,
            "oos_end_date": self.oos_end_date,
            "accepted_rows": self.accepted_rows,
            "excluded_rows": self.excluded_rows,
            "fold_ids": list(self.fold_ids),
            "metrics_bp": dict(self.metrics_bp),
            "artifact_hashes": dict(self.artifact_hashes),
            "blockers": list(self.blockers),
            "evidence_tier": self.evidence_tier,
            "result_status": self.result_status,
            "report_hash": self.report_hash,
            "shadow_only": self.shadow_only,
            "production_eligible": self.production_eligible,
            "production_action_allowed": self.production_action_allowed,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "HistoricalMLShadowRunReport":
        if payload.get("schema_version") != "historical-ml-shadow-run-report.v1":
            raise ValueError("unsupported historical run report schema_version")
        if (
            payload.get("shadow_only") is not True
            or payload.get("production_eligible") is not False
            or payload.get("production_action_allowed") is not False
        ):
            raise ValueError("historical run report shadow flags are invalid")
        report = cls.create(
            run_id=str(payload["run_id"]),
            dataset_id=str(payload["dataset_id"]),
            model_id=str(payload["model_id"]),
            training_end_date=str(payload["training_end_date"]),
            oos_start_date=str(payload["oos_start_date"]),
            oos_end_date=str(payload["oos_end_date"]),
            accepted_rows=int(payload["accepted_rows"]),
            excluded_rows=int(payload["excluded_rows"]),
            fold_ids=tuple(str(item) for item in payload["fold_ids"]),
            metrics_bp=payload["metrics_bp"],
            artifact_hashes=payload["artifact_hashes"],
            blockers=tuple(str(item) for item in payload["blockers"]),
            evidence_tier=str(payload["evidence_tier"]),
            result_status=str(payload["result_status"]),
        )
        if report.report_hash != payload.get("report_hash"):
            raise ValueError("historical run report hash mismatch")
        return report


def _normalize_metrics(metrics: Mapping[str, int]) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for metric_id, value in sorted(metrics.items()):
        if (
            not metric_id
            or isinstance(value, bool)
            or not isinstance(value, int)
        ):
            raise TypeError("metrics_bp requires non-empty ids and integer values")
        normalized[metric_id] = value
    return normalized


def _normalize_hashes(hashes: Mapping[str, str]) -> dict[str, str]:
    if not hashes:
        raise ValueError("artifact_hashes are required")
    normalized: dict[str, str] = {}
    for artifact_id, value in sorted(hashes.items()):
        prefix = "sha256:"
        digest = value[len(prefix) :] if value.startswith(prefix) else ""
        if (
            not artifact_id
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError("artifact_hashes must contain lowercase sha256 digests")
        normalized[artifact_id] = value
    return normalized


def _hash_payload(payload: object) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"
