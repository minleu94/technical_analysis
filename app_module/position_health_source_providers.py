"""Governed source adapters for the daily position-health evaluator.

The daily evaluator deliberately accepts domain objects instead of opening
arbitrary files.  This module is the small custody boundary that turns
immutable derived artifacts into those objects.  Every adapter verifies the
artifact bytes, the decision clock, and the position identity before returning
anything to the evaluator.  A missing artifact is a degraded input; a supplied
but malformed or future artifact is an integrity blocker.

No adapter writes the Paper state, the Formal store, or the configured raw data
root.  The thesis writer in this module only writes the explicit derived
registry requested by a human operator.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timezone, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import time as time_module
from typing import Any
from zoneinfo import ZoneInfo

from app_module.position_health_state_machine import PositionHealthMetric
from app_module.position_thesis_contract import (
    PositionInvalidationRule,
    PositionThesisContract,
)
from data_module.official_trading_calendar import OfficialTradingCalendar


SCHEMA_VERSION = "position-health-source-providers.v1"
THESIS_REGISTRY_SCHEMA_VERSION = "position-thesis-registry.v1"
CONDITION_SOURCE_SCHEMA_VERSION = "position-health-condition-source.v1"
METRICS_SOURCE_SCHEMA_VERSION = "position-health-metrics-source.v1"
FORWARD_BINDING_SCHEMA_VERSION = "forward-position-entry-binding.v1"
FROZEN_RULE_POLICY_STATUS_SCHEMA_VERSION = (
    "prospective-formal-rule-source-machine-revalidation.v3"
)
FROZEN_RULE_POLICY_MANIFEST_SCHEMA_VERSION = (
    "prospective-formal-simulated-portfolio-clock.v1"
)
TAIPEI = ZoneInfo("Asia/Taipei")
UTC = timezone.utc
_SHA256_PREFIX = "sha256:"
_POSITION_ID_KEYS = ("position_id", "entry_lineage_id", "lineage_id")
_HEALTH_STATES = frozenset(
    {"HEALTHY", "WATCH", "REDUCE_CANDIDATE", "EXIT_CANDIDATE", "CLOSED"}
)


@dataclass(frozen=True)
class SourceProviderResult:
    """One provider result with explicit missing/warning/blocker custody."""

    values: Mapping[str, Any]
    provenance: Mapping[str, Any]
    missing: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class PositionHealthSourceBundle:
    """All optional source maps consumed by one evaluator request."""

    thesis_by_position: Mapping[str, PositionThesisContract | None]
    conditions_by_position: Mapping[str, Any]
    metrics_by_position: Mapping[str, Sequence[PositionHealthMetric]]
    forward_binding_by_position: Mapping[str, Mapping[str, Any]]
    machine_thesis_by_position: Mapping[str, PositionThesisContract]
    trading_dates: tuple[str, ...] | None
    provenance: Mapping[str, Any]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()


class FrozenRulePolicySourceProvider:
    """Read the already frozen machine Rule policy as Health provenance.

    The Formal Rule source is a machine policy identity, not a position thesis.
    This adapter therefore returns policy metadata only.  It never fabricates
    invalidation rules, a holding horizon, or human rationale, and it never
    changes a position's health state by itself.  A missing explicit position
    thesis remains a degraded input in the evaluator.
    """

    def __init__(self, source_path: str | Path) -> None:
        self.path = Path(source_path).expanduser().resolve()

    def read(
        self,
        *,
        decision_date: str,
        decision_at: datetime,
        observed_at: datetime,
    ) -> SourceProviderResult:
        try:
            before = self.path.read_bytes()
            payload = _read_json_object(before, field_name="frozen_rule_policy_source")
            after = self.path.read_bytes()
            if before != after:
                raise ValueError("frozen_rule_policy_source_changed_during_read")
            policy = self._read_and_verify(
                payload,
                decision_date=decision_date,
                decision_at=decision_at,
                observed_at=observed_at,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return SourceProviderResult(
                values={},
                provenance={
                    "provider": type(self).__name__,
                    "path": str(self.path),
                    "status": "blocked" if self.path.exists() else "missing",
                    "file_sha256": _safe_file_hash(self.path),
                },
                missing=("policy",),
                warnings=(
                    ()
                    if self.path.exists()
                    else ("frozen_rule_policy_source_missing",)
                ),
                blockers=(
                    ()
                    if not self.path.exists()
                    else (f"frozen_rule_policy_source_blocked:{type(exc).__name__}:{exc}",)
                ),
            )

        policy_hash = str(policy["policy_hash"])
        return SourceProviderResult(
            values={"policy": policy, "policy_hash": policy_hash},
            provenance={
                "provider": type(self).__name__,
                "path": str(self.path),
                "status": "verified",
                "file_sha256": _sha256(before),
                **policy,
            },
            warnings=(
                "frozen_rule_policy_machine_only",
                "position_thesis_policy_not_supplied_by_formal_rule",
            ),
        )

    def _read_and_verify(
        self,
        payload: Mapping[str, Any],
        *,
        decision_date: str,
        decision_at: datetime,
        observed_at: datetime,
    ) -> dict[str, Any]:
        """Verify the stable scheduler receipt and all three immutable inputs."""

        status_schema = str(payload.get("schema_version") or "")
        if status_schema != FROZEN_RULE_POLICY_STATUS_SCHEMA_VERSION:
            raise ValueError("frozen_rule_policy_source_schema_invalid")
        status = str(payload.get("status") or "")
        if status not in {"rule_source_bundle_reused", "rule_source_created"}:
            raise ValueError("frozen_rule_policy_source_status_invalid")
        for field in (
            "candidate_only",
            "formal_oos_allowed",
            "promotion_eligible",
            "broker_order_allowed",
            "writes_formal_controlled_paths",
            "writes_market_database",
        ):
            expected = field in {"candidate_only"}
            if payload.get(field) is not expected:
                raise ValueError(f"frozen_rule_policy_{field}_boundary_invalid")

        status_observed = _aware(payload.get("observed_at"))
        if status_observed > observed_at or status_observed > decision_at:
            raise ValueError("frozen_rule_policy_source_observed_at_future")
        activation_date = _date_text(payload.get("taipei_date"))
        decision = _date_text(decision_date)
        if activation_date > decision:
            raise ValueError("frozen_rule_policy_activation_date_future")

        manifest_path = Path(
            _required_text(payload.get("clock_manifest"), "clock_manifest_path")
        ).expanduser().resolve()
        owner_path = Path(
            _required_text(payload.get("owner_acceptance"), "owner_acceptance_path")
        ).expanduser().resolve()
        receipt_path = Path(
            _required_text(
                payload.get("machine_revalidation_receipt"),
                "machine_revalidation_receipt_path",
            )
        ).expanduser().resolve()
        manifest, _manifest_raw, manifest_file_hash = _read_stable_json_file(
            manifest_path, "frozen_rule_clock_manifest"
        )
        owner, _owner_raw, owner_file_hash = _read_stable_json_file(
            owner_path, "frozen_rule_owner_acceptance"
        )
        receipt, _receipt_raw, receipt_file_hash = _read_stable_json_file(
            receipt_path, "frozen_rule_revalidation_receipt"
        )
        if manifest.get("schema_version") != FROZEN_RULE_POLICY_MANIFEST_SCHEMA_VERSION:
            raise ValueError("frozen_rule_clock_manifest_schema_invalid")
        declared_manifest_hash = _required_sha256(manifest.get("manifest_hash"))
        manifest_body = dict(manifest)
        manifest_body.pop("manifest_hash", None)
        if _sha256_json(manifest_body) != declared_manifest_hash:
            raise ValueError("frozen_rule_clock_manifest_hash_mismatch")
        if payload.get("clock_manifest_hash") != declared_manifest_hash:
            raise ValueError("frozen_rule_status_manifest_hash_mismatch")

        policy_hash = _required_sha256(manifest.get("policy_hash"))
        policy_version = _required_text(manifest.get("policy_version"), "policy_version")
        strategy_version = _required_text(
            manifest.get("strategy_version"), "strategy_version"
        )
        source_window_hash = _required_sha256(payload.get("source_window_hash"))
        if receipt.get("clock_manifest_hash") != declared_manifest_hash:
            raise ValueError("frozen_rule_receipt_manifest_hash_mismatch")
        if receipt.get("source_window_hash") != source_window_hash:
            raise ValueError("frozen_rule_receipt_source_window_hash_mismatch")
        if receipt.get("status") != "machine_revalidated_candidate_only":
            raise ValueError("frozen_rule_revalidation_status_invalid")
        receipt_observed = _aware(receipt.get("observed_at"))
        if receipt_observed > decision_at or receipt_observed > observed_at:
            raise ValueError("frozen_rule_revalidation_observed_at_future")
        available_at = max(status_observed, receipt_observed)
        if available_at > decision_at or available_at > observed_at:
            raise ValueError("frozen_rule_policy_available_at_future")

        if owner.get("policy_hash") != policy_hash:
            raise ValueError("frozen_rule_owner_policy_hash_mismatch")
        if owner.get("accepted_policy_version") != policy_version:
            raise ValueError("frozen_rule_owner_policy_version_mismatch")
        if owner.get("accepted_strategy_version") != strategy_version:
            raise ValueError("frozen_rule_owner_strategy_version_mismatch")
        for field in (
            "formal_oos_allowed",
            "promotion_eligible",
            "broker_order_allowed",
        ):
            if owner.get(field) is not False:
                raise ValueError(f"frozen_rule_owner_{field}_boundary_invalid")
        if receipt.get("owner_acceptance_hash") != _sha256(_owner_raw):
            raise ValueError("frozen_rule_receipt_owner_hash_mismatch")

        return {
            "policy_hash": policy_hash,
            "policy_version": policy_version,
            "strategy_version": strategy_version,
            "activation_trading_day": activation_date,
            "available_at": available_at.isoformat(),
            "status_observed_at": status_observed.isoformat(),
            "revalidation_observed_at": receipt_observed.isoformat(),
            "source_window_hash": source_window_hash,
            "clock_manifest_hash": declared_manifest_hash,
            "clock_manifest_file_sha256": manifest_file_hash,
            "owner_acceptance_file_sha256": owner_file_hash,
            "machine_revalidation_receipt_file_sha256": receipt_file_hash,
            "source_window_path": payload.get("source_window"),
            "position_thesis_policy_status": "missing",
            "position_invalidation_rules_status": "missing",
            "holding_horizon_status": "missing",
            "candidate_only": True,
            "formal_oos_allowed": False,
            "promotion_eligible": False,
            "broker_order_allowed": False,
        }


class PositionThesisRegistryProvider:
    """Read and verify an append-only human thesis registry."""

    def __init__(self, registry_path: str | Path) -> None:
        self.path = Path(registry_path).expanduser().resolve()

    def read_for_positions(
        self,
        positions: Sequence[Mapping[str, Any]],
        *,
        decision_date: str,
        decision_at: datetime,
    ) -> SourceProviderResult:
        identities = _position_identity_rows(positions)
        if not self.path.exists():
            return SourceProviderResult(
                values={key: None for key in identities},
                provenance={
                    "provider": type(self).__name__,
                    "path": str(self.path),
                    "status": "missing",
                },
                missing=tuple(sorted(identities)),
                warnings=("thesis_registry_missing",),
            )
        try:
            raw = self.path.read_bytes()
            payload = _read_json_object(raw, field_name="thesis_registry")
            records = payload.get("records")
            if payload.get("schema_version") != THESIS_REGISTRY_SCHEMA_VERSION:
                raise ValueError("thesis_registry_schema_version_invalid")
            if not isinstance(records, list):
                raise ValueError("thesis_registry_records_invalid")
            parsed = self._parse_records(
                records,
                decision_date=decision_date,
                decision_at=decision_at,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return SourceProviderResult(
                values={key: None for key in identities},
                provenance={
                    "provider": type(self).__name__,
                    "path": str(self.path),
                    "status": "blocked",
                    "file_sha256": _safe_file_hash(self.path),
                },
                blockers=(f"thesis_registry_blocked:{type(exc).__name__}:{exc}",),
            )

        values: dict[str, PositionThesisContract | None] = {
            key: None for key in identities
        }
        missing: list[str] = []
        warnings: list[str] = []
        selected: list[dict[str, Any]] = []
        for lookup_key, (position_id, lineage_id, stock_code) in identities.items():
            if not position_id:
                missing.append(lookup_key)
                warnings.append(f"position_lineage_missing:{stock_code or lookup_key}")
                continue
            candidates = [
                item
                for item in parsed
                if item["position_id"] == position_id
                and item["stock_code"] == stock_code
                and (
                    not lineage_id
                    or item["entry_lineage_id"] == lineage_id
                )
            ]
            if not candidates:
                missing.append(lookup_key)
                continue
            candidates.sort(
                key=lambda item: (
                    _date_text(item["effective_from"]),
                    _aware(item["available_at"]),
                    str(item["version_id"]),
                )
            )
            latest_effective = candidates[-1]["effective_from"]
            same_effective = [
                item for item in candidates if item["effective_from"] == latest_effective
            ]
            if len(same_effective) > 1:
                hashes = {str(item["record_sha256"]) for item in same_effective}
                if len(hashes) > 1:
                    return SourceProviderResult(
                        values=values,
                        provenance={
                            "provider": type(self).__name__,
                            "path": str(self.path),
                            "status": "blocked",
                            "file_sha256": _sha256(raw),
                            "selected_records": selected,
                        },
                        blockers=(
                            "thesis_registry_conflicting_versions:"
                            f"{position_id}:{latest_effective}",
                        ),
                    )
            chosen = same_effective[-1]
            values[lookup_key] = chosen["contract"]
            selected.append(
                {
                    "lookup_key": lookup_key,
                    "position_id": position_id,
                    "entry_lineage_id": chosen["entry_lineage_id"],
                    "stock_code": stock_code,
                    "version_id": chosen["version_id"],
                    "effective_from": chosen["effective_from"],
                    "available_at": chosen["available_at"],
                    "record_sha256": chosen["record_sha256"],
                }
            )
        return SourceProviderResult(
            values=values,
            provenance={
                "provider": type(self).__name__,
                "path": str(self.path),
                "status": "verified",
                "file_sha256": _sha256(raw),
                "records_count": len(parsed),
                "selected_records": selected,
            },
            missing=tuple(sorted(set(missing))),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def _parse_records(
        self,
        records: list[Any],
        *,
        decision_date: str,
        decision_at: datetime,
    ) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []
        decision = _date_text(decision_date)
        for index, raw_record in enumerate(records):
            if not isinstance(raw_record, Mapping):
                raise ValueError(f"thesis_registry_record_{index}_not_object")
            record = dict(raw_record)
            declared_hash = record.pop("record_sha256", None)
            if not _is_sha256(declared_hash):
                raise ValueError(f"thesis_registry_record_{index}_hash_invalid")
            if declared_hash != _sha256_json(record):
                raise ValueError(f"thesis_registry_record_{index}_hash_mismatch")
            position_id = _required_text(record.get("position_id"), "position_id")
            lineage_id = _required_text(record.get("entry_lineage_id"), "entry_lineage_id")
            stock_code = _required_text(record.get("stock_code"), "stock_code")
            version_id = _required_text(record.get("version_id"), "version_id")
            effective_from = _date_text(record.get("effective_from"))
            available_at = _aware(record.get("available_at"))
            authored_at = _aware(record.get("authored_at"))
            recorded_at = _aware(record.get("recorded_at"))
            if available_at > decision_at:
                raise ValueError(f"thesis_registry_record_{index}_available_at_future")
            if authored_at > available_at:
                raise ValueError(f"thesis_registry_record_{index}_authored_after_available")
            if recorded_at > decision_at:
                # A late manual entry may describe an older idea, but it cannot
                # retroactively receive PIT credit for this decision cutoff.
                continue
            if effective_from > decision:
                continue
            contract_raw = record.get("contract")
            if not isinstance(contract_raw, Mapping):
                raise ValueError(f"thesis_registry_record_{index}_contract_invalid")
            contract = PositionThesisContract.from_dict(contract_raw)
            if contract.position_id != position_id or contract.stock_code != stock_code:
                raise ValueError(f"thesis_registry_record_{index}_identity_mismatch")
            if contract.decision_date[:10] > decision:
                continue
            parsed.append(
                {
                    "position_id": position_id,
                    "entry_lineage_id": lineage_id,
                    "stock_code": stock_code,
                    "version_id": version_id,
                    "effective_from": effective_from,
                    "available_at": available_at,
                    "record_sha256": declared_hash,
                    "contract": contract,
                }
            )
        return parsed


class ForwardPositionThesisBindingProvider:
    """Consume a verified candidate-to-entry binding for Health provenance.

    A binding never supplies a human thesis and never authorizes a transition.
    It only proves that the position-health row can refer to the same
    recommendation and Paper entry lineage.  Missing or awaiting bindings are
    explicit degraded inputs; an internally inconsistent bound artifact is an
    integrity blocker.
    """

    def __init__(self, binding_path: str | Path, *, calendar: Any | None = None) -> None:
        self.path = Path(binding_path).expanduser().resolve()
        self.calendar = calendar

    def read_for_positions(
        self,
        positions: Sequence[Mapping[str, Any]],
        *,
        decision_date: str,
        decision_at: datetime,
        observed_at: datetime,
    ) -> SourceProviderResult:
        try:
            if self.path.is_dir():
                return self._read_directory_for_positions(
                    positions,
                    decision_date=decision_date,
                    decision_at=decision_at,
                    observed_at=observed_at,
                )
            return self._read_for_positions(
                positions,
                decision_date=decision_date,
                decision_at=decision_at,
                observed_at=observed_at,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return SourceProviderResult(
                values={key: None for key in _position_identity_rows(positions)},
                provenance={
                    "provider": type(self).__name__,
                    "path": str(self.path),
                    "status": "blocked",
                    "file_sha256": _safe_file_hash(self.path),
                },
                blockers=(f"forward_binding_blocked:{type(exc).__name__}:{exc}",),
            )

    def _read_directory_for_positions(
        self,
        positions: Sequence[Mapping[str, Any]],
        *,
        decision_date: str,
        decision_at: datetime,
        observed_at: datetime,
    ) -> SourceProviderResult:
        """Read all immutable binding receipts so one run covers the portfolio."""

        identities = _position_identity_rows(positions)
        paths = sorted(item for item in self.path.glob("*.json") if item.is_file())
        if not paths:
            return SourceProviderResult(
                values={key: None for key in identities},
                provenance={
                    "provider": type(self).__name__,
                    "path": str(self.path),
                    "status": "missing",
                    "files": [],
                },
                missing=tuple(sorted(identities)),
                warnings=("forward_position_thesis_binding_directory_empty",),
            )
        bound: dict[str, Mapping[str, Any]] = {}
        waiting: dict[str, Mapping[str, Any]] = {}
        warnings: list[str] = []
        blockers: list[str] = []
        file_statuses: list[dict[str, Any]] = []
        for path in paths:
            relevance = self._directory_file_relevance(path, identities)
            if relevance == "historical":
                file_statuses.append(
                    {
                        "path": str(path),
                        "file_sha256": _safe_file_hash(path),
                        "status": "ignored_historical",
                    }
                )
                continue
            result = ForwardPositionThesisBindingProvider(
                path,
                calendar=self.calendar,
            )._read_for_positions(
                positions,
                decision_date=decision_date,
                decision_at=decision_at,
                observed_at=observed_at,
            )
            file_statuses.append(
                {
                    "path": str(path),
                    "file_sha256": _safe_file_hash(path),
                    "status": result.provenance.get("status"),
                }
            )
            blockers.extend(result.blockers)
            warnings.extend(result.warnings)
            status = str(result.provenance.get("status") or "")
            if status == "verified":
                for key, value in result.values.items():
                    if not isinstance(value, Mapping):
                        continue
                    if key in bound and dict(bound[key]) != dict(value):
                        blockers.append(f"forward_binding_duplicate_position:{key}")
                    else:
                        bound[key] = value
            else:
                for key, value in result.values.items():
                    if isinstance(value, Mapping) and key not in bound and key not in waiting:
                        waiting[key] = value
        if blockers:
            return SourceProviderResult(
                values={key: None for key in identities},
                provenance={
                    "provider": type(self).__name__,
                    "path": str(self.path),
                    "status": "blocked",
                    "files": file_statuses,
                },
                warnings=tuple(dict.fromkeys(warnings)),
                blockers=tuple(dict.fromkeys(blockers)),
            )
        values: dict[str, Mapping[str, Any]] = dict(waiting)
        values.update(bound)
        return SourceProviderResult(
            values=values,
            provenance={
                "provider": type(self).__name__,
                "path": str(self.path),
                "status": "verified" if bound else "awaiting",
                "files": file_statuses,
                "bound_positions": sorted(bound),
            },
            missing=tuple(sorted(set(identities) - set(bound))),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    @staticmethod
    def _directory_file_relevance(
        path: Path,
        identities: Mapping[str, tuple[str, str, str]],
    ) -> str:
        """Exclude valid receipts for closed/re-entered identities from a run."""

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            # The per-file reader will fail closed for an unreadable file.  It
            # is therefore still inspected when its identity cannot be known.
            return "unknown"
        if not isinstance(payload, Mapping):
            return "unknown"
        if payload.get("schema_version") != FORWARD_BINDING_SCHEMA_VERSION:
            return "unknown"
        status = str(payload.get("status") or "")
        stock_code = str(payload.get("stock_code") or "").strip()
        if status != "bound":
            return (
                "relevant"
                if stock_code and any(identity[2] == stock_code for identity in identities.values())
                else "historical"
            )
        handoff = payload.get("health_handoff")
        entry = payload.get("entry")
        if not isinstance(handoff, Mapping) or not isinstance(entry, Mapping):
            return "unknown"
        position_id = str(handoff.get("position_id") or "").strip()
        lineage_id = str(handoff.get("entry_lineage_id") or "").strip()
        entry_stock = str(entry.get("stock_code") or stock_code).strip()
        return (
            "relevant"
            if any(
                identity[0] == position_id
                and identity[1] == lineage_id
                and identity[2] == entry_stock
                for identity in identities.values()
            )
            else "historical"
        )

    def _read_for_positions(
        self,
        positions: Sequence[Mapping[str, Any]],
        *,
        decision_date: str,
        decision_at: datetime,
        observed_at: datetime,
    ) -> SourceProviderResult:
        identities = _position_identity_rows(positions)
        empty = {key: None for key in identities}
        if not self.path.exists():
            return SourceProviderResult(
                values=empty,
                provenance={
                    "provider": type(self).__name__,
                    "path": str(self.path),
                    "status": "missing",
                },
                missing=tuple(sorted(identities)),
                warnings=("forward_position_thesis_binding_missing",),
            )
        try:
            before = self.path.read_bytes()
            payload = _read_json_object(before, field_name="forward_binding")
            after = self.path.read_bytes()
            if before != after:
                raise ValueError("forward_binding_changed_during_read")
            if payload.get("schema_version") != FORWARD_BINDING_SCHEMA_VERSION:
                raise ValueError("forward_binding_schema_version_invalid")
            status = _required_text(payload.get("status"), "forward_binding_status")
            candidate_date = _date_text(
                payload.get("candidate_decision_date"),
            )
            if date.fromisoformat(candidate_date) > date.fromisoformat(decision_date):
                raise ValueError("forward_binding_candidate_date_future")
            candidate_available = _aware(payload.get("candidate_available_at"))
            if candidate_available > decision_at or candidate_available > observed_at:
                raise ValueError("forward_binding_candidate_available_at_future")
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return SourceProviderResult(
                values=empty,
                provenance={
                    "provider": type(self).__name__,
                    "path": str(self.path),
                    "status": "blocked",
                    "file_sha256": _safe_file_hash(self.path),
                },
                blockers=(f"forward_binding_blocked:{type(exc).__name__}:{exc}",),
            )

        if status != "bound":
            if status not in {
                "awaiting_paper_fill",
                "ambiguous",
                "rejected_preexisting",
                "blocked",
            }:
                return SourceProviderResult(
                    values=empty,
                    provenance={
                        "provider": type(self).__name__,
                        "path": str(self.path),
                        "status": "blocked",
                        "file_sha256": _sha256(before),
                    },
                    blockers=("forward_binding_status_invalid",),
                )
            waiting = {
                key: {
                    "status": status,
                    "binding_file_sha256": _sha256(before),
                }
                for key in identities
            }
            return SourceProviderResult(
                values=waiting,
                provenance={
                    "provider": type(self).__name__,
                    "path": str(self.path),
                    "status": status,
                    "file_sha256": _sha256(before),
                    "candidate_id": payload.get("candidate_id"),
                },
                missing=tuple(sorted(identities)),
                warnings=(f"forward_position_thesis_binding_{status}",),
            )

        if payload.get("candidate_only") is not True or payload.get("research_only") is not True:
            return SourceProviderResult(
                values=empty,
                provenance={
                    "provider": type(self).__name__,
                    "path": str(self.path),
                    "status": "blocked",
                    "file_sha256": _sha256(before),
                },
                blockers=("forward_binding_boundary_invalid",),
            )
        if payload.get("auto_action_allowed") is not False or payload.get("writes_paper_state") is not False:
            return SourceProviderResult(
                values=empty,
                provenance={
                    "provider": type(self).__name__,
                    "path": str(self.path),
                    "status": "blocked",
                    "file_sha256": _sha256(before),
                },
                blockers=("forward_binding_action_boundary_invalid",),
            )
        handoff = payload.get("health_handoff")
        entry = payload.get("entry")
        if not isinstance(handoff, Mapping) or not isinstance(entry, Mapping):
            return SourceProviderResult(
                values=empty,
                provenance={
                    "provider": type(self).__name__,
                    "path": str(self.path),
                    "status": "blocked",
                    "file_sha256": _sha256(before),
                },
                blockers=("forward_binding_health_handoff_missing",),
            )
        if handoff.get("human_thesis_registry_required") is not True or handoff.get(
            "transition_apply_allowed"
        ) is not False:
            return SourceProviderResult(
                values=empty,
                provenance={
                    "provider": type(self).__name__,
                    "path": str(self.path),
                    "status": "blocked",
                    "file_sha256": _sha256(before),
                },
                blockers=("forward_binding_health_boundary_invalid",),
            )
        position_id = _required_text(handoff.get("position_id"), "forward_binding_position_id")
        lineage_id = _required_text(
            handoff.get("entry_lineage_id"),
            "forward_binding_entry_lineage_id",
        )
        entry_position_id = _required_text(entry.get("position_id"), "forward_binding_entry_position_id")
        entry_lineage_id = _required_text(
            entry.get("entry_lineage_id"),
            "forward_binding_entry_lineage_id",
        )
        if (entry_position_id, entry_lineage_id) != (position_id, lineage_id):
            return SourceProviderResult(
                values=empty,
                provenance={
                    "provider": type(self).__name__,
                    "path": str(self.path),
                    "status": "blocked",
                    "file_sha256": _sha256(before),
                },
                blockers=("forward_binding_handoff_entry_mismatch",),
            )
        stock_code = _required_text(payload.get("stock_code"), "forward_binding_stock_code")
        entry_stock_code = _required_text(entry.get("stock_code"), "forward_binding_entry_stock_code")
        if stock_code != entry_stock_code:
            raise ValueError("forward_binding_stock_code_mismatch")
        candidate_path_value = payload.get("candidate_path")
        candidate_hash = payload.get("candidate_file_sha256")
        if not isinstance(candidate_path_value, str) or not _is_sha256(candidate_hash):
            raise ValueError("forward_binding_candidate_proof_missing")
        candidate_path = Path(candidate_path_value).expanduser().resolve()
        if _safe_file_hash(candidate_path) != candidate_hash:
            raise ValueError("forward_binding_candidate_file_hash_mismatch")
        candidate_raw = candidate_path.read_bytes()
        candidate_payload = _read_json_object(candidate_raw, field_name="forward_candidate")
        if candidate_payload.get("schema_version") != "forward-position-thesis-candidate.v1":
            raise ValueError("forward_binding_candidate_schema_invalid")
        declared_candidate_content = candidate_payload.get("content_sha256")
        if not _is_sha256(declared_candidate_content):
            raise ValueError("forward_binding_candidate_content_hash_missing")
        candidate_body = dict(candidate_payload)
        candidate_body.pop("content_sha256", None)
        if _sha256_json(candidate_body) != declared_candidate_content:
            raise ValueError("forward_binding_candidate_content_hash_mismatch")
        if str(candidate_payload.get("candidate_id") or "") != str(payload.get("candidate_id") or ""):
            raise ValueError("forward_binding_candidate_id_mismatch")
        candidate_instrument = candidate_payload.get("instrument")
        candidate_source = candidate_payload.get("recommendation_source")
        if not isinstance(candidate_instrument, Mapping) or not isinstance(candidate_source, Mapping):
            raise ValueError("forward_binding_candidate_source_missing")
        if str(candidate_instrument.get("stock_code") or "") != stock_code:
            raise ValueError("forward_binding_candidate_stock_mismatch")

        lookup = None
        for key, identity in identities.items():
            if identity[0] == position_id and identity[1] == lineage_id and identity[2] == stock_code:
                lookup = key
                break
        if lookup is None:
            raise ValueError("forward_binding_position_identity_not_in_baseline")
        paper_candidate_path_value = entry.get("paper_execution_candidate_path")
        paper_candidate_file_hash = entry.get("paper_execution_candidate_file_sha256")
        paper_candidate_content_hash = entry.get("paper_execution_candidate_content_sha256")
        paper_recommendation_file_hash = entry.get("paper_recommendation_file_sha256")
        paper_recommendation_content_hash = entry.get("paper_recommendation_content_sha256")
        fill_id = _required_text(entry.get("entry_fill_id"), "forward_binding_entry_fill_id")
        source_event_id = _required_text(
            entry.get("entry_source_event_id"),
            "forward_binding_entry_source_event_id",
        )
        entry_date = _date_text(entry.get("entry_date"))
        entry_evidence_hash = _required_sha256(entry.get("entry_evidence_hash"))
        if (
            not isinstance(paper_candidate_path_value, str)
            or not _is_sha256(paper_candidate_file_hash)
            or not _is_sha256(paper_candidate_content_hash)
            or not _is_sha256(paper_recommendation_file_hash)
            or not _is_sha256(paper_recommendation_content_hash)
        ):
            raise ValueError("forward_binding_entry_proof_missing")
        entry_date_value = date.fromisoformat(entry_date)
        if entry_date_value > date.fromisoformat(decision_date):
            raise ValueError("forward_binding_entry_date_future")
        if entry_date_value <= date.fromisoformat(candidate_date):
            raise ValueError("forward_binding_entry_precedes_candidate")
        from app_module.forward_position_thesis_candidate_producer import (
            ForwardPositionThesisCandidateProducer,
        )

        candidate_source_result_id = _required_text(
            candidate_source.get("result_id"),
            "forward_binding_recommendation_result_id",
        )
        candidate_source_file_hash = _required_sha256(
            candidate_source.get("file_sha256")
        )
        candidate_source_content_hash = _required_sha256(
            candidate_source.get("content_sha256")
        )
        if candidate_source_file_hash != paper_recommendation_file_hash:
            raise ValueError("forward_binding_candidate_recommendation_file_hash_mismatch")
        if candidate_source_content_hash != paper_recommendation_content_hash:
            raise ValueError("forward_binding_candidate_recommendation_content_hash_mismatch")
        verified = ForwardPositionThesisCandidateProducer(candidate_path.parent).verify_paper_execution_candidate(
            Path(paper_candidate_path_value).expanduser().resolve(),
            result_id=candidate_source_result_id,
            recommendation_file_sha256=candidate_source_file_hash,
            recommendation_content_sha256=candidate_source_content_hash,
            stock_code=stock_code,
            position_id=position_id,
            entry_date=entry_date_value,
            fill_id=fill_id,
            source_event_id=source_event_id,
            evidence_hash=entry_evidence_hash,
        )
        if verified["file_hash"] != paper_candidate_file_hash:
            raise ValueError("forward_binding_paper_candidate_file_hash_mismatch")
        if verified["content_sha256"] != paper_candidate_content_hash:
            raise ValueError("forward_binding_paper_candidate_content_hash_mismatch")
        if verified["recommendation_file_sha256"] != paper_recommendation_file_hash:
            raise ValueError("forward_binding_paper_recommendation_file_hash_mismatch")
        if verified["recommendation_content_sha256"] != paper_recommendation_content_hash:
            raise ValueError("forward_binding_paper_recommendation_content_hash_mismatch")
        machine_thesis = self._build_machine_thesis_contract(
            candidate_payload=candidate_payload,
            candidate_path=candidate_path,
            candidate_file_sha256=str(candidate_hash),
            binding_file_sha256=_sha256(before),
            entry=entry,
            position_id=position_id,
            lineage_id=lineage_id,
            stock_code=stock_code,
            verified_paper_candidate=verified,
            decision_at=decision_at,
            observed_at=observed_at,
        )
        bound_value: dict[str, Any] = {
            "status": "bound",
            "binding_file_sha256": _sha256(before),
            "candidate_id": payload.get("candidate_id"),
            "candidate_path": str(candidate_path),
            "candidate_file_sha256": str(candidate_hash),
            "candidate_decision_date": candidate_date,
            "position_id": position_id,
            "entry_lineage_id": lineage_id,
            "stock_code": stock_code,
            "entry_date": entry.get("entry_date"),
            "entry_fill_id": entry.get("entry_fill_id"),
            "entry_source_event_id": entry.get("entry_source_event_id"),
            "entry_evidence_hash": entry.get("entry_evidence_hash"),
            "paper_execution_candidate_path": str(
                Path(paper_candidate_path_value).expanduser().resolve()
            ),
            "paper_execution_candidate_file_sha256": str(paper_candidate_file_hash),
            "paper_execution_candidate_content_sha256": str(paper_candidate_content_hash),
            "paper_recommendation_file_sha256": str(paper_recommendation_file_hash),
            "paper_recommendation_content_sha256": str(paper_recommendation_content_hash),
        }
        if machine_thesis is not None:
            # The dataclass is intentionally kept in-memory at this custody
            # boundary.  The immutable binding receipt remains JSON-only; the
            # bundle/evaluator receives the exact contract only after the
            # candidate, policy, calendar, and Paper proof have been reread.
            bound_value["machine_thesis_contract"] = machine_thesis
            binding_warning = (
                "forward_position_thesis_binding_machine_policy_available_human_approval_required",
            )
        else:
            binding_warning = (
                "forward_position_thesis_binding_human_thesis_still_required",
            )
        return SourceProviderResult(
            values={lookup: bound_value},
            provenance={
                "provider": type(self).__name__,
                "path": str(self.path),
                "status": "verified",
                "file_sha256": _sha256(before),
                "candidate_id": payload.get("candidate_id"),
                "position_id": position_id,
                "entry_lineage_id": lineage_id,
            },
            missing=tuple(sorted(set(identities) - {lookup})),
            warnings=binding_warning,
        )

    def _build_machine_thesis_contract(
        self,
        *,
        candidate_payload: Mapping[str, Any],
        candidate_path: Path,
        candidate_file_sha256: str,
        binding_file_sha256: str,
        entry: Mapping[str, Any],
        position_id: str,
        lineage_id: str,
        stock_code: str,
        verified_paper_candidate: Mapping[str, str],
        decision_at: datetime,
        observed_at: datetime,
    ) -> PositionThesisContract | None:
        """Build a machine policy contract only for a verified new entry.

        Candidate packets without an explicit policy intentionally return
        ``None`` and remain degraded in Health.  Once a packet claims an
        explicit policy, every policy byte and custody field is re-read here;
        a mismatch is an integrity blocker rather than a best-effort thesis.
        """

        if str(candidate_payload.get("status") or "") != "candidate_ready":
            return None
        invalidation = candidate_payload.get("invalidation")
        horizon = candidate_payload.get("holding_horizon")
        source = candidate_payload.get("recommendation_source")
        thesis = candidate_payload.get("thesis")
        if not isinstance(invalidation, Mapping):
            raise ValueError("forward_machine_thesis_invalidation_invalid")
        if not isinstance(horizon, Mapping):
            raise ValueError("forward_machine_thesis_horizon_invalid")
        if not isinstance(source, Mapping):
            raise ValueError("forward_machine_thesis_source_invalid")
        if not isinstance(thesis, Mapping):
            raise ValueError("forward_machine_thesis_candidate_payload_invalid")
        if invalidation.get("status") != "explicit_policy" or horizon.get(
            "status"
        ) != "explicit_policy":
            return None

        policy_path = Path(
            _required_text(invalidation.get("policy_path"), "forward_policy_path")
        ).expanduser().resolve()
        policy, policy_raw, policy_file_sha256 = _read_stable_json_file(
            policy_path,
            "forward_machine_policy",
        )
        del policy_raw
        if policy.get("schema_version") != "forward-position-policy.v1":
            raise ValueError("forward_machine_policy_schema_invalid")
        declared_policy_sha256 = _required_sha256(invalidation.get("policy_hash"))
        if policy_file_sha256 != declared_policy_sha256:
            raise ValueError("forward_machine_policy_file_hash_mismatch")

        candidate_id = _required_text(
            candidate_payload.get("candidate_id"),
            "forward_machine_thesis_candidate_id",
        )
        result_id = _required_text(source.get("result_id"), "forward_machine_result_id")
        candidate_decision_date = _date_text(
            source.get("decision_date")
        )
        candidate_decision_at = _aware(source.get("decision_at"))
        candidate_available_at = _aware(source.get("available_at"))
        entry_date = _date_text(entry.get("entry_date"))
        entry_available_raw = entry.get("entry_available_at")
        if entry_available_raw is None:
            raise ValueError("forward_machine_thesis_entry_available_at_missing")
        entry_available_at = _aware(entry_available_raw)
        if candidate_available_at > entry_available_at:
            raise ValueError("forward_machine_thesis_candidate_after_entry")
        if candidate_decision_at > entry_available_at:
            raise ValueError("forward_machine_thesis_decision_after_entry")
        if candidate_decision_date >= entry_date:
            raise ValueError("forward_machine_thesis_entry_not_after_candidate")

        policy_available_at = _aware(policy.get("available_at"))
        if policy_available_at > decision_at or policy_available_at > observed_at:
            raise ValueError("forward_machine_thesis_policy_available_at_future")
        if policy_available_at > entry_available_at:
            raise ValueError("forward_machine_thesis_policy_after_entry")
        effective_from = _date_text(policy.get("effective_from"))
        if effective_from > entry_date:
            raise ValueError("forward_machine_thesis_policy_effective_after_entry")

        policy_id = _required_text(policy.get("policy_id"), "forward_policy_id")
        policy_version = _required_text(policy.get("version"), "forward_policy_version")
        policy_source = _required_text(policy.get("source"), "forward_policy_source")
        policy_actor = _required_text(
            policy.get("actor")
            or invalidation.get("policy_actor")
            or "forward_position_policy_producer",
            "forward_policy_actor",
        )
        if invalidation.get("policy_id") != policy_id:
            raise ValueError("forward_machine_thesis_policy_id_mismatch")
        if invalidation.get("policy_version") != policy_version:
            raise ValueError("forward_machine_thesis_policy_version_mismatch")
        if invalidation.get("policy_source") != policy_source:
            raise ValueError("forward_machine_thesis_policy_source_mismatch")
        declared_actor = invalidation.get("policy_actor")
        if declared_actor is not None and str(declared_actor) != policy_actor:
            raise ValueError("forward_machine_thesis_policy_actor_mismatch")

        rules = _parse_machine_policy_rules(policy.get("invalidation_rules"))
        candidate_rules = _parse_machine_policy_rules(invalidation.get("rules"))
        if tuple(rule.to_dict() for rule in rules) != tuple(
            rule.to_dict() for rule in candidate_rules
        ):
            raise ValueError("forward_machine_thesis_policy_rules_mismatch")
        raw_horizon = policy.get("holding_horizon_trading_days")
        if (
            isinstance(raw_horizon, bool)
            or not isinstance(raw_horizon, int)
            or raw_horizon <= 0
        ):
            raise ValueError("forward_machine_thesis_policy_horizon_invalid")
        raw_cadence = policy.get("review_cadence_trading_days", raw_horizon)
        if (
            isinstance(raw_cadence, bool)
            or not isinstance(raw_cadence, int)
            or raw_cadence <= 0
            or raw_cadence > raw_horizon
        ):
            raise ValueError("forward_machine_thesis_policy_review_cadence_invalid")
        if horizon.get("trading_days") != raw_horizon or horizon.get(
            "review_cadence_trading_days", raw_horizon
        ) != raw_cadence:
            raise ValueError("forward_machine_thesis_horizon_mismatch")

        policy_calendar_path = Path(
            _required_text(policy.get("calendar_cache_path"), "forward_policy_calendar_path")
        ).expanduser().resolve()
        candidate_calendar_path = Path(
            _required_text(
                invalidation.get("calendar_cache_path"),
                "forward_candidate_calendar_path",
            )
        ).expanduser().resolve()
        if candidate_calendar_path != policy_calendar_path:
            raise ValueError("forward_machine_thesis_calendar_path_mismatch")
        policy_calendar_hash = _required_sha256(policy.get("calendar_cache_hash"))
        candidate_calendar_hash = _required_sha256(
            invalidation.get("calendar_cache_hash")
        )
        if policy_calendar_hash != candidate_calendar_hash:
            raise ValueError("forward_machine_thesis_calendar_hash_mismatch")
        actual_calendar_hash = _safe_file_hash(policy_calendar_path)
        if actual_calendar_hash != policy_calendar_hash:
            raise ValueError("forward_machine_thesis_calendar_file_hash_mismatch")
        calendar = self.calendar or OfficialTradingCalendar(
            db_path=policy_calendar_path,
            calendar_cache_path=policy_calendar_path,
        )
        next_review = _next_machine_review_date(
            entry_date=date.fromisoformat(entry_date),
            cadence=raw_cadence,
            calendar=calendar,
        )
        raw_policy_trace = policy.get("source_trace")
        if not isinstance(raw_policy_trace, list) or not raw_policy_trace or not all(
            isinstance(item, str) and item.strip() for item in raw_policy_trace
        ):
            raise ValueError("forward_machine_thesis_policy_source_trace_invalid")
        candidate_trace = thesis.get("source_trace")
        if not isinstance(candidate_trace, list) or not all(
            isinstance(item, str) and item.strip() for item in candidate_trace
        ):
            raise ValueError("forward_machine_thesis_candidate_source_trace_invalid")
        if any(item not in candidate_trace for item in raw_policy_trace):
            raise ValueError("forward_machine_thesis_policy_trace_not_bound")

        verified_paper_file_hash = _required_sha256(
            verified_paper_candidate.get("file_hash")
        )
        verified_paper_content_hash = _required_sha256(
            verified_paper_candidate.get("content_sha256")
        )
        verified_recommendation_file_hash = _required_sha256(
            verified_paper_candidate.get("recommendation_file_sha256")
        )
        verified_recommendation_content_hash = _required_sha256(
            verified_paper_candidate.get("recommendation_content_sha256")
        )
        if verified_recommendation_file_hash != _required_sha256(
            source.get("file_sha256")
        ) or verified_recommendation_content_hash != _required_sha256(
            source.get("content_sha256")
        ):
            raise ValueError("forward_machine_thesis_recommendation_hash_mismatch")

        available_date = max(
            candidate_available_at.astimezone(TAIPEI).date(),
            policy_available_at.astimezone(TAIPEI).date(),
        )
        trace = tuple(
            dict.fromkeys(
                (
                    f"machine_candidate:{candidate_id}",
                    f"machine_candidate_file_sha256:{candidate_file_sha256}",
                    f"machine_binding_file_sha256:{binding_file_sha256}",
                    f"recommendation_result:{result_id}",
                    f"recommendation_file_sha256:{verified_recommendation_file_hash}",
                    f"recommendation_content_sha256:{verified_recommendation_content_hash}",
                    f"recommendation_config_sha256:{source.get('config_sha256')}",
                    f"paper_candidate_file_sha256:{verified_paper_file_hash}",
                    f"paper_candidate_content_sha256:{verified_paper_content_hash}",
                    f"entry_position_id:{position_id}",
                    f"entry_lineage_id:{lineage_id}",
                    f"entry_fill_id:{entry.get('entry_fill_id')}",
                    f"entry_source_event_id:{entry.get('entry_source_event_id')}",
                    f"entry_evidence_hash:{entry.get('entry_evidence_hash')}",
                    f"policy_id:{policy_id}",
                    f"policy_version:{policy_version}",
                    f"policy_source:{policy_source}",
                    f"policy_actor:{policy_actor}",
                    f"policy_file_sha256:{policy_file_sha256}",
                    f"policy_available_at:{policy_available_at.isoformat()}",
                    f"policy_effective_from:{effective_from}",
                    f"calendar_cache_sha256:{policy_calendar_hash}",
                    f"entry_available_at:{entry_available_at.isoformat()}",
                    f"entry_review_date:{next_review.isoformat()}",
                    *raw_policy_trace,
                )
            )
        )
        return PositionThesisContract(
            position_id=position_id,
            stock_code=stock_code,
            entry_date=entry_date,
            # The candidate's recommendation decision date stays in the
            # source trace.  Contract dates describe the new entry's own
            # effective review horizon, which must never precede entry.
            decision_date=entry_date,
            available_date=available_date.isoformat(),
            entry_thesis=(
                f"machine_policy_candidate:{candidate_id}; "
                "source-bound observation; no human investment rationale supplied"
            ),
            holding_horizon_trading_days=raw_horizon,
            next_review_date=next_review.isoformat(),
            source_trace=trace,
            invalidation_rules=rules,
            auto_exit_allowed=False,
            source_type="machine_policy",
            source_actor=policy_actor,
        )


class PITConditionSourceProvider:
    """Read a hash-bound PIT condition/current-snapshot artifact."""

    def __init__(self, source_path: str | Path) -> None:
        self.path = Path(source_path).expanduser().resolve()

    def read_for_positions(
        self,
        positions: Sequence[Mapping[str, Any]],
        *,
        decision_date: str,
        decision_at: datetime,
        observed_at: datetime,
    ) -> SourceProviderResult:
        identities = _position_identity_rows(positions)
        if not self.path.exists():
            return SourceProviderResult(
                values={},
                provenance={"provider": type(self).__name__, "path": str(self.path), "status": "missing"},
                missing=tuple(sorted(identities)),
                warnings=("pit_condition_source_missing",),
            )
        try:
            raw = self.path.read_bytes()
            payload = _read_hashed_document(
                raw,
                expected_schema=CONDITION_SOURCE_SCHEMA_VERSION,
                field_name="pit_condition_source",
            )
            source_id = _required_text(payload.get("source_id"), "source_id")
            snapshot_hash = _required_sha256(payload.get("source_snapshot_hash"))
            as_of_date = _date_text(payload.get("as_of_date"))
            available_at = _aware(payload.get("available_at"))
            if as_of_date > _date_text(decision_date):
                raise ValueError("pit_condition_source_future_dated")
            if available_at > decision_at or available_at > observed_at:
                raise ValueError("pit_condition_source_available_at_future")
            rows = payload.get("positions")
            if not isinstance(rows, list):
                raise ValueError("pit_condition_source_positions_invalid")
            parsed_rows = self._parse_rows(
                rows,
                identities=identities,
                source_id=source_id,
                source_snapshot_hash=snapshot_hash,
                as_of_date=as_of_date,
                available_at=available_at,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return SourceProviderResult(
                values={},
                provenance={
                    "provider": type(self).__name__,
                    "path": str(self.path),
                    "status": "blocked",
                    "file_sha256": _safe_file_hash(self.path),
                },
                blockers=(f"pit_condition_source_blocked:{type(exc).__name__}:{exc}",),
            )
        values = {item["lookup_key"]: item["observation"] for item in parsed_rows}
        missing = tuple(sorted(set(identities) - set(values)))
        return SourceProviderResult(
            values=values,
            provenance={
                "provider": type(self).__name__,
                "path": str(self.path),
                "status": "verified",
                "file_sha256": _sha256(raw),
                "source_id": source_id,
                "source_snapshot_hash": snapshot_hash,
                "as_of_date": as_of_date,
                "available_at": available_at.isoformat(),
                "selected_positions": [item["lookup_key"] for item in parsed_rows],
            },
            missing=missing,
        )

    @staticmethod
    def _parse_rows(
        rows: list[Any],
        *,
        identities: Mapping[str, tuple[str, str, str]],
        source_id: str,
        source_snapshot_hash: str,
        as_of_date: str,
        available_at: datetime,
    ) -> list[dict[str, Any]]:
        from app_module.position_health_transition_evaluator import PITConditionObservation
        from app_module.portfolio_condition_monitor import (
            PortfolioConditionResult,
            PortfolioCurrentSnapshot,
        )

        expected_by_identity = {
            (position_id, lineage_id, stock_code): lookup_key
            for lookup_key, (position_id, lineage_id, stock_code) in identities.items()
            if position_id
        }
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, raw_row in enumerate(rows):
            if not isinstance(raw_row, Mapping):
                raise ValueError(f"pit_condition_row_{index}_not_object")
            row = dict(raw_row)
            position_id = _required_text(row.get("position_id"), "position_id")
            lineage_id = _required_text(row.get("entry_lineage_id"), "entry_lineage_id")
            stock_code = _required_text(row.get("stock_code"), "stock_code")
            lookup_key = expected_by_identity.get((position_id, lineage_id, stock_code))
            if lookup_key is None:
                raise ValueError(f"pit_condition_row_{index}_identity_mismatch")
            if lookup_key in seen:
                raise ValueError(f"pit_condition_row_{index}_duplicate")
            seen.add(lookup_key)
            result_raw = row.get("result")
            snapshot_raw = row.get("current_snapshot")
            if not isinstance(result_raw, Mapping) or not isinstance(snapshot_raw, Mapping):
                raise ValueError(f"pit_condition_row_{index}_shape_invalid")
            current_price: Any = None
            if snapshot_raw.get("current_price") is not None:
                current_price = _decimal(snapshot_raw.get("current_price"), "current_price")
            current_snapshot = PortfolioCurrentSnapshot(
                current_regime=str(snapshot_raw.get("current_regime") or ""),
                current_total_score=(
                    None
                    if snapshot_raw.get("current_total_score") is None
                    else _decimal(snapshot_raw.get("current_total_score"), "current_total_score")
                ),
                current_price=current_price,
            )
            reasons = row.get("reasons", result_raw.get("reasons", []))
            if not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons):
                raise ValueError(f"pit_condition_row_{index}_reasons_invalid")
            details = result_raw.get("details", {})
            if not isinstance(details, Mapping):
                raise ValueError(f"pit_condition_row_{index}_details_invalid")
            condition_result = PortfolioConditionResult(
                stock_code=stock_code,
                status=str(result_raw.get("status") or ""),
                label=str(result_raw.get("label") or ""),
                source_label=str(result_raw.get("source_label") or ""),
                entry_regime=str(result_raw.get("entry_regime") or ""),
                current_regime=str(result_raw.get("current_regime") or ""),
                entry_total_score=str(result_raw.get("entry_total_score") or ""),
                current_total_score=str(result_raw.get("current_total_score") or ""),
                reasons=list(reasons),
                details=dict(details),
            )
            result.append(
                {
                    "lookup_key": lookup_key,
                    "observation": PITConditionObservation(
                        result=condition_result,
                        current_snapshot=current_snapshot,
                        source_id=source_id,
                        source_snapshot_hash=source_snapshot_hash,
                        as_of_date=as_of_date,
                        available_at=available_at.isoformat(),
                        quality=str(row.get("quality") or "observed"),
                        source_trace=(
                            f"pit_condition:{source_id}",
                            f"pit_condition_hash:{source_snapshot_hash}",
                        ),
                    ),
                }
            )
        return result


class DecimalMetricSourceProvider:
    """Read a hash-bound, string-encoded Decimal metric artifact."""

    def __init__(self, source_path: str | Path) -> None:
        self.path = Path(source_path).expanduser().resolve()

    def read_for_positions(
        self,
        positions: Sequence[Mapping[str, Any]],
        *,
        decision_date: str,
        decision_at: datetime,
        observed_at: datetime,
    ) -> SourceProviderResult:
        identities = _position_identity_rows(positions)
        if not self.path.exists():
            return SourceProviderResult(
                values={},
                provenance={"provider": type(self).__name__, "path": str(self.path), "status": "missing"},
                missing=tuple(sorted(identities)),
                warnings=("decimal_metric_source_missing",),
            )
        try:
            raw = self.path.read_bytes()
            payload = _read_hashed_document(
                raw,
                expected_schema=METRICS_SOURCE_SCHEMA_VERSION,
                field_name="decimal_metric_source",
            )
            source_id = _required_text(payload.get("source_id"), "source_id")
            source_hash = _required_sha256(payload.get("source_snapshot_hash"))
            root_available = _aware(payload.get("available_at"))
            if root_available > decision_at or root_available > observed_at:
                raise ValueError("decimal_metric_source_available_at_future")
            records = payload.get("metrics")
            if not isinstance(records, list):
                raise ValueError("decimal_metric_source_metrics_invalid")
            parsed = self._parse_records(
                records,
                identities=identities,
                decision_date=decision_date,
                decision_at=decision_at,
                source_id=source_id,
                source_hash=source_hash,
                root_available=root_available,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return SourceProviderResult(
                values={},
                provenance={
                    "provider": type(self).__name__,
                    "path": str(self.path),
                    "status": "blocked",
                    "file_sha256": _safe_file_hash(self.path),
                },
                blockers=(f"decimal_metric_source_blocked:{type(exc).__name__}:{exc}",),
            )
        values: dict[str, tuple[PositionHealthMetric, ...]] = {}
        for lookup_key, metric_rows in parsed.items():
            values[lookup_key] = tuple(item["metric"] for item in metric_rows)
        missing = tuple(sorted(set(identities) - set(values)))
        return SourceProviderResult(
            values=values,
            provenance={
                "provider": type(self).__name__,
                "path": str(self.path),
                "status": "verified",
                "file_sha256": _sha256(raw),
                "source_id": source_id,
                "source_snapshot_hash": source_hash,
                "available_at": root_available.isoformat(),
                "selected_positions": sorted(values),
            },
            missing=missing,
        )

    @staticmethod
    def _parse_records(
        records: list[Any],
        *,
        identities: Mapping[str, tuple[str, str, str]],
        decision_date: str,
        decision_at: datetime,
        source_id: str,
        source_hash: str,
        root_available: datetime,
    ) -> dict[str, list[dict[str, Any]]]:
        expected_by_identity = {
            (position_id, lineage_id, stock_code): lookup_key
            for lookup_key, (position_id, lineage_id, stock_code) in identities.items()
            if position_id
        }
        values: dict[str, list[dict[str, Any]]] = {}
        seen: set[tuple[str, str]] = set()
        for index, raw_record in enumerate(records):
            if not isinstance(raw_record, Mapping):
                raise ValueError(f"decimal_metric_record_{index}_not_object")
            record = dict(raw_record)
            position_id = _required_text(record.get("position_id"), "position_id")
            lineage_id = _required_text(record.get("entry_lineage_id"), "entry_lineage_id")
            stock_code = _required_text(record.get("stock_code"), "stock_code")
            lookup_key = expected_by_identity.get((position_id, lineage_id, stock_code))
            if lookup_key is None:
                raise ValueError(f"decimal_metric_record_{index}_identity_mismatch")
            metric_id = _required_text(record.get("metric_id"), "metric_id")
            pair = (lookup_key, metric_id)
            if pair in seen:
                raise ValueError(f"decimal_metric_record_{index}_duplicate")
            seen.add(pair)
            raw_value = record.get("value")
            if not isinstance(raw_value, str):
                raise ValueError(f"decimal_metric_record_{index}_value_must_be_decimal_text")
            value = _decimal(raw_value, "metric_value")
            available_date = _date_text(record.get("available_date"))
            if available_date > _date_text(decision_date):
                raise ValueError(f"decimal_metric_record_{index}_future_date")
            available_at = root_available
            if record.get("available_at") is not None:
                available_at = _aware(record.get("available_at"))
            if available_at > decision_at:
                raise ValueError(f"decimal_metric_record_{index}_future_available_at")
            values.setdefault(lookup_key, []).append(
                {
                    "metric": PositionHealthMetric(
                        metric_id=metric_id,
                        value=value,
                        available_date=available_date,
                    ),
                    "source_id": source_id,
                    "source_hash": source_hash,
                    "available_at": available_at.isoformat(),
                }
            )
        return values


class OfficialCalendarSourceProvider:
    """Resolve a complete trading-day range from verified offline annual cache."""

    def __init__(
        self,
        *,
        calendar_cache_path: str | Path,
        temporary_closure_path: str | Path | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        self.calendar_cache_path = Path(calendar_cache_path).expanduser().resolve()
        self.temporary_closure_path = (
            None
            if temporary_closure_path is None
            else Path(temporary_closure_path).expanduser().resolve()
        )
        self.db_path = None if db_path is None else Path(db_path).expanduser().resolve()

    def read_range(
        self,
        *,
        start_date: str,
        end_date: str,
        decision_at: datetime,
        observed_at: datetime,
    ) -> SourceProviderResult:
        try:
            start = date.fromisoformat(start_date[:10])
            end = date.fromisoformat(end_date[:10])
            if start > end:
                raise ValueError("official_calendar_range_invalid")
            calendar = OfficialTradingCalendar(
                # Supplying an explicit path avoids constructing TWStockConfig
                # (which would initialise the D: log path) for this cache-only
                # read.  The cache is the required evidence; the fallback DB is
                # never consulted when a verified annual cache is present.
                db_path=self.db_path or self.calendar_cache_path,
                calendar_cache_path=self.calendar_cache_path,
                temporary_closure_path=self.temporary_closure_path,
            )
            rows = calendar.get_trading_days_in_range(
                start,
                end,
                allow_online_probe=False,
            )
            if any(row.get("is_trading_day") is None for row in rows):
                unknown = [
                    str(row.get("date_str"))
                    for row in rows
                    if row.get("is_trading_day") is None
                ]
                raise ValueError("official_calendar_unknown:" + ",".join(unknown[:5]))
            evidence_by_year: dict[int, dict[str, Any]] = {}
            for year in sorted({item.year for item in _date_range(start, end)}):
                sample = next(
                    (item for item in _date_range(start, end) if item.year == year and item.weekday() < 5),
                    date(year, 1, 2) if date(year, 1, 2).weekday() < 5 else date(year, 1, 3),
                )
                evidence = dict(calendar.evidence_for(sample))
                if evidence.get("mode") != "hash_bound_official_calendar_cache":
                    raise ValueError(f"official_calendar_not_hash_bound:{year}")
                available_at = _aware(evidence.get("available_at"))
                captured_at = _aware(evidence.get("captured_at"))
                expires_at = _aware(evidence.get("expires_at"))
                if available_at > decision_at:
                    raise ValueError(f"official_calendar_available_at_future:{year}")
                if captured_at > observed_at:
                    raise ValueError(f"official_calendar_capture_future:{year}")
                if expires_at <= observed_at:
                    raise ValueError(f"official_calendar_cache_expired:{year}")
                cache_hash = _required_sha256(evidence.get("cache_file_sha256"))
                source_hash = _required_sha256(evidence.get("source_hash"))
                evidence_by_year[year] = {
                    "calendar_year": year,
                    "path": str(evidence.get("path") or ""),
                    "cache_file_sha256": cache_hash,
                    "source_hash": source_hash,
                    "available_at": available_at.isoformat(),
                    "captured_at": captured_at.isoformat(),
                    "expires_at": expires_at.isoformat(),
                    "coverage": evidence.get("coverage"),
                }
            trading_dates = tuple(
                str(row["date_str"])
                for row in rows
                if row.get("is_trading_day") is True
            )
        except (OSError, TypeError, ValueError) as exc:
            return SourceProviderResult(
                values={},
                provenance={
                    "provider": type(self).__name__,
                    "calendar_cache_path": str(self.calendar_cache_path),
                    "status": "blocked",
                },
                blockers=(f"official_calendar_blocked:{type(exc).__name__}:{exc}",),
            )
        provenance = {
            "provider": type(self).__name__,
            "calendar_cache_path": str(self.calendar_cache_path),
            "temporary_closure_path": (
                None if self.temporary_closure_path is None else str(self.temporary_closure_path)
            ),
            "status": "verified",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "trading_dates_count": len(trading_dates),
            "years": evidence_by_year,
        }
        return SourceProviderResult(
            values={"trading_dates": trading_dates},
            provenance=provenance,
        )


def build_position_health_source_bundle(
    *,
    positions: Sequence[Mapping[str, Any]],
    decision_date: str,
    decision_at: datetime,
    observed_at: datetime,
    thesis_registry_path: str | Path | None = None,
    forward_binding_path: str | Path | None = None,
    condition_source_path: str | Path | None = None,
    metrics_source_path: str | Path | None = None,
    policy_source_path: str | Path | None = None,
    calendar_cache_path: str | Path | None = None,
    temporary_closure_path: str | Path | None = None,
    calendar_db_path: str | Path | None = None,
    calendar_start_date: str | None = None,
    forward_calendar: Any | None = None,
) -> PositionHealthSourceBundle:
    """Load all explicitly configured sources for one evaluator request."""

    thesis_result = (
        PositionThesisRegistryProvider(thesis_registry_path).read_for_positions(
            positions,
            decision_date=decision_date,
            decision_at=decision_at,
        )
        if thesis_registry_path is not None
        else SourceProviderResult(
            values={},
            provenance={"provider": "PositionThesisRegistryProvider", "status": "not_configured"},
            missing=tuple(sorted(_position_identity_rows(positions))),
            warnings=("thesis_registry_not_configured",),
        )
    )
    condition_result = (
        PITConditionSourceProvider(condition_source_path).read_for_positions(
            positions,
            decision_date=decision_date,
            decision_at=decision_at,
            observed_at=observed_at,
        )
        if condition_source_path is not None
        else SourceProviderResult(
            values={},
            provenance={"provider": "PITConditionSourceProvider", "status": "not_configured"},
            missing=tuple(sorted(_position_identity_rows(positions))),
            warnings=("pit_condition_source_not_configured",),
        )
    )
    forward_binding_result = (
        ForwardPositionThesisBindingProvider(
            forward_binding_path,
            calendar=forward_calendar,
        ).read_for_positions(
            positions,
            decision_date=decision_date,
            decision_at=decision_at,
            observed_at=observed_at,
        )
        if forward_binding_path is not None
        else SourceProviderResult(
            values={},
            provenance={
                "provider": "ForwardPositionThesisBindingProvider",
                "status": "not_configured",
            },
        )
    )
    metric_result = (
        DecimalMetricSourceProvider(metrics_source_path).read_for_positions(
            positions,
            decision_date=decision_date,
            decision_at=decision_at,
            observed_at=observed_at,
        )
        if metrics_source_path is not None
        else SourceProviderResult(
            values={},
            provenance={"provider": "DecimalMetricSourceProvider", "status": "not_configured"},
            missing=tuple(sorted(_position_identity_rows(positions))),
            warnings=("decimal_metric_source_not_configured",),
        )
    )
    policy_result = (
        FrozenRulePolicySourceProvider(policy_source_path).read(
            decision_date=decision_date,
            decision_at=decision_at,
            observed_at=observed_at,
        )
        if policy_source_path is not None
        else SourceProviderResult(
            values={},
            provenance={
                "provider": "FrozenRulePolicySourceProvider",
                "status": "not_configured",
            },
        )
    )
    if calendar_cache_path is not None:
        start = calendar_start_date or _earliest_entry_date(thesis_result.values) or decision_date
        calendar_result = OfficialCalendarSourceProvider(
            calendar_cache_path=calendar_cache_path,
            temporary_closure_path=temporary_closure_path,
            db_path=calendar_db_path,
        ).read_range(
            start_date=start,
            end_date=decision_date,
            decision_at=decision_at,
            observed_at=observed_at,
        )
    else:
        calendar_result = SourceProviderResult(
            values={},
            provenance={"provider": "OfficialCalendarSourceProvider", "status": "not_configured"},
            warnings=("official_calendar_not_configured",),
        )

    warnings = tuple(
        dict.fromkeys(
            [
                *thesis_result.warnings,
                *condition_result.warnings,
                *forward_binding_result.warnings,
                *metric_result.warnings,
                *policy_result.warnings,
                *calendar_result.warnings,
            ]
        )
    )
    blockers = tuple(
        dict.fromkeys(
            [
                *thesis_result.blockers,
                *condition_result.blockers,
                *forward_binding_result.blockers,
                *metric_result.blockers,
                *policy_result.blockers,
                *calendar_result.blockers,
            ]
        )
    )
    human_thesis_by_position = {
        str(key): value
        for key, value in thesis_result.values.items()
        if isinstance(value, PositionThesisContract)
    }
    machine_thesis_by_position: dict[str, PositionThesisContract] = {}
    for key, value in forward_binding_result.values.items():
        if not isinstance(value, Mapping):
            continue
        machine = value.get("machine_thesis_contract")
        if isinstance(machine, PositionThesisContract):
            machine_thesis_by_position[str(key)] = machine
    # A human-reviewed contract remains authoritative when both sources cover
    # the same current lineage.  Machine policy contracts are a forward-only
    # fallback and never overwrite a human registry record.
    thesis_by_position = {
        **machine_thesis_by_position,
        **human_thesis_by_position,
    }
    return PositionHealthSourceBundle(
        thesis_by_position=thesis_by_position,
        conditions_by_position={
            str(key): value for key, value in condition_result.values.items()
        },
        metrics_by_position={
            str(key): value
            for key, value in metric_result.values.items()
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
        },
        forward_binding_by_position={
            str(key): value
            for key, value in forward_binding_result.values.items()
            if isinstance(value, Mapping)
        },
        machine_thesis_by_position=machine_thesis_by_position,
        trading_dates=(
            tuple(str(item) for item in calendar_result.values["trading_dates"])
            if "trading_dates" in calendar_result.values
            else None
        ),
        provenance={
            "schema_version": SCHEMA_VERSION,
            "thesis": dict(thesis_result.provenance),
            "condition": dict(condition_result.provenance),
            "forward_binding": dict(forward_binding_result.provenance),
            "machine_thesis": {
                "status": "verified" if machine_thesis_by_position else "missing",
                "position_count": len(machine_thesis_by_position),
                "source": "forward_position_thesis_binding",
            },
            "metrics": dict(metric_result.provenance),
            "policy": dict(policy_result.provenance),
            "official_calendar": dict(calendar_result.provenance),
            "missing": {
                "thesis": list(thesis_result.missing),
                "condition": list(condition_result.missing),
                "forward_binding": list(forward_binding_result.missing),
                "metrics": list(metric_result.missing),
                "policy": list(policy_result.missing),
            },
            "source_provider_warnings": list(warnings),
            "source_provider_blockers": list(blockers),
        },
        warnings=warnings,
        blockers=blockers,
    )


class PositionThesisRegistryWriter:
    """Append one explicit human thesis version to a derived registry."""

    def __init__(self, registry_path: str | Path, *, now_provider: Any = None) -> None:
        self.path = Path(registry_path).expanduser().resolve()
        self._now_provider = now_provider or (lambda: datetime.now(UTC))

    def append(
        self,
        *,
        contract: PositionThesisContract,
        entry_lineage_id: str,
        version_id: str,
        authored_by: str,
        authored_at: datetime | str,
        available_at: datetime | str,
    ) -> dict[str, Any]:
        if contract.source_type != "human_reviewed":
            raise ValueError("thesis_registry_requires_human_source")
        lineage = _required_text(entry_lineage_id, "entry_lineage_id")
        version = _required_text(version_id, "version_id")
        author = _required_text(authored_by, "authored_by")
        authored = _aware(authored_at)
        available = _aware(available_at)
        recorded = _aware(self._now_provider())
        decision_at = datetime.combine(
            date.fromisoformat(contract.decision_date[:10]),
            time.max,
            tzinfo=TAIPEI,
        )
        if available > decision_at:
            raise ValueError("thesis_available_at_after_contract_decision")
        if authored > available:
            raise ValueError("thesis_authored_at_after_available_at")
        lock = _RegistryFileLock(self.path.with_name(self.path.name + ".lock"))
        with lock:
            existing_payload: dict[str, Any]
            existing_records: list[Any]
            if self.path.exists():
                raw_existing = self.path.read_bytes()
                existing_payload = _read_json_object(raw_existing, field_name="thesis_registry")
                if existing_payload.get("schema_version") != THESIS_REGISTRY_SCHEMA_VERSION:
                    raise ValueError("thesis_registry_schema_version_invalid")
                raw_records = existing_payload.get("records")
                if not isinstance(raw_records, list):
                    raise ValueError("thesis_registry_records_invalid")
                # Revalidate every prior record before appending, so an operator
                # cannot silently repair or rewrite registry history.
                PositionThesisRegistryProvider(self.path)._parse_records(
                    raw_records,
                    decision_date=contract.decision_date,
                    decision_at=decision_at,
                )
                existing_records = [
                    dict(item) for item in raw_records if isinstance(item, Mapping)
                ]
            else:
                existing_payload = {
                    "schema_version": THESIS_REGISTRY_SCHEMA_VERSION,
                    "registry_id": "position-thesis-registry",
                }
                existing_records = []
            record: dict[str, Any] = {
                "version_id": version,
                "position_id": contract.position_id,
                "entry_lineage_id": lineage,
                "stock_code": contract.stock_code,
                "effective_from": contract.decision_date[:10],
                "available_at": available.isoformat(),
                "authored_at": authored.isoformat(),
                "recorded_at": recorded.isoformat(),
                "authored_by": author,
                "contract": contract.to_dict(),
            }
            record_hash = _sha256_json(record)
            record["record_sha256"] = record_hash
            for previous in existing_records:
                if str(previous.get("version_id")) == version:
                    # ``recorded_at`` is storage provenance, not human-authored
                    # thesis meaning.  A retried submission can reach this
                    # writer with a later process clock; it must remain
                    # idempotent and preserve the first record's bytes/hash and
                    # actual recorded_at rather than minting a new version.
                    if _without_hash_and_recorded_at(previous) == _without_hash_and_recorded_at(
                        record
                    ):
                        return {
                            "status": "idempotent",
                            "version_id": version,
                            "record_sha256": previous.get("record_sha256"),
                            "recorded_at": previous.get("recorded_at"),
                            "registry_sha256": _safe_file_hash(self.path),
                            "registry_path": str(self.path),
                        }
                    raise ValueError("thesis_registry_version_conflict")
                if (
                    str(previous.get("position_id")) == contract.position_id
                    and str(previous.get("effective_from")) == contract.decision_date[:10]
                    and str(previous.get("record_sha256")) != record_hash
                ):
                    raise ValueError("thesis_registry_effective_version_conflict")
            payload = dict(existing_payload)
            payload["records"] = [*existing_records, record]
            _atomic_write_json(self.path, payload)
            return {
                "status": "written",
                "version_id": version,
                "record_sha256": record_hash,
                "recorded_at": recorded.isoformat(),
                "registry_sha256": _safe_file_hash(self.path),
                "registry_path": str(self.path),
            }


def _position_identity_rows(
    positions: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[str, str, str]]:
    result: dict[str, tuple[str, str, str]] = {}
    for index, position in enumerate(positions):
        if not isinstance(position, Mapping):
            continue
        position_id = str(position.get("position_id") or "").strip()
        lineage_id = str(position.get("entry_lineage_id") or position.get("lineage_id") or "").strip()
        stock_code = str(position.get("stock_code") or "").strip()
        lookup = position_id or lineage_id or stock_code or f"row-{index}"
        result[lookup] = (position_id or lineage_id, lineage_id, stock_code)
    return result


def _earliest_entry_date(values: Mapping[str, Any]) -> str | None:
    dates: list[str] = []
    for value in values.values():
        if isinstance(value, PositionThesisContract):
            dates.append(value.entry_date[:10])
    return min(dates) if dates else None


def _parse_machine_policy_rules(value: object) -> tuple[PositionInvalidationRule, ...]:
    """Parse policy rules through the Decimal-only thesis contract boundary."""

    if not isinstance(value, list) or not value:
        raise ValueError("forward_machine_thesis_policy_rules_invalid")
    rules: list[PositionInvalidationRule] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise ValueError(f"forward_machine_thesis_policy_rule_{index}_invalid")
        threshold = raw.get("threshold")
        if isinstance(threshold, bool) or isinstance(threshold, float) or threshold is None:
            raise ValueError(
                f"forward_machine_thesis_policy_rule_{index}_threshold_invalid"
            )
        rules.append(
            PositionInvalidationRule(
                metric_id=_required_text(raw.get("metric_id"), "metric_id"),
                operator=_required_text(raw.get("operator"), "operator"),
                threshold=_decimal(
                    threshold,
                    f"forward_machine_thesis_policy_rule_{index}_threshold",
                ),
                action=str(raw.get("action") or "exit"),
            )
        )
    return tuple(rules)


def _next_machine_review_date(
    *,
    entry_date: date,
    cadence: int,
    calendar: Any,
) -> date:
    """Find the next review after entry using only explicit official sessions."""

    current = entry_date
    counted = 0
    for _ in range(3660):
        current += timedelta(days=1)
        result = calendar.is_official_trading_day(current, allow_online_probe=False)
        is_trading = result[0] if isinstance(result, tuple) else result
        if is_trading is None:
            raise ValueError("forward_machine_thesis_review_calendar_day_unknown")
        if is_trading is True:
            counted += 1
            if counted >= cadence:
                return current
    raise ValueError("forward_machine_thesis_review_calendar_horizon_not_reached")


def _read_json_object(raw: bytes, *, field_name: str) -> dict[str, Any]:
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name}_must_be_object")
    return dict(value)


def _read_stable_json_file(
    path: Path,
    field_name: str,
) -> tuple[dict[str, Any], bytes, str]:
    """Read one JSON document and prove that its bytes stayed stable."""

    before = path.read_bytes()
    payload = _read_json_object(before, field_name=field_name)
    after = path.read_bytes()
    if before != after:
        raise ValueError(f"{field_name}_changed_during_read")
    return payload, before, _sha256(before)


def _read_hashed_document(
    raw: bytes,
    *,
    expected_schema: str,
    field_name: str,
) -> dict[str, Any]:
    payload = _read_json_object(raw, field_name=field_name)
    if payload.get("schema_version") != expected_schema:
        raise ValueError(f"{field_name}_schema_version_invalid")
    declared = payload.pop("content_sha256", None)
    if not _is_sha256(declared) or declared != _sha256_json(payload):
        raise ValueError(f"{field_name}_content_hash_mismatch")
    return payload


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name}_missing")
    return text


def _date_text(value: object) -> str:
    text = str(value or "")[:10]
    return date.fromisoformat(text).isoformat()


def _aware(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("datetime_must_be_timezone_aware")
    return parsed.astimezone(UTC)


def _decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"{field_name}_must_be_decimal_text")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name}_invalid_decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name}_non_finite")
    return parsed


def _required_sha256(value: object) -> str:
    text = str(value or "").strip().lower()
    if not _is_sha256(text):
        raise ValueError("source_hash_invalid")
    return text


def _is_sha256(value: object) -> bool:
    text = str(value or "").strip().lower()
    if not text.startswith(_SHA256_PREFIX) or len(text) != len(_SHA256_PREFIX) + 64:
        return False
    try:
        int(text[len(_SHA256_PREFIX) :], 16)
    except ValueError:
        return False
    return True


def _sha256(raw: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(raw).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: object) -> str:
    return _sha256(_canonical_json(value).encode("utf-8"))


def _safe_file_hash(path: Path) -> str | None:
    try:
        return _sha256(path.read_bytes())
    except OSError:
        return None


def _without_hash(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): item for key, item in value.items() if key != "record_sha256"}


def _without_hash_and_recorded_at(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return the user-semantic registry payload used for retry identity."""

    return {
        str(key): item
        for key, item in value.items()
        if key not in {"record_sha256", "recorded_at"}
    }


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{hashlib.sha256(str(id(payload)).encode()).hexdigest()[:12]}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


class _RegistryFileLock:
    """Small cross-process create-only lock for registry append operations."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    def __enter__(self) -> "_RegistryFileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time_module.monotonic() + 30.0
        while True:
            try:
                self._fd = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(self._fd, f"pid={os.getpid()}\n".encode("ascii"))
                return self
            except FileExistsError:
                if time_module.monotonic() >= deadline:
                    raise TimeoutError("thesis_registry_lock_timeout")
                time_module.sleep(0.01)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _date_range(start: date, end: date) -> tuple[date, ...]:
    return tuple(start + timedelta(days=index) for index in range((end - start).days + 1))
