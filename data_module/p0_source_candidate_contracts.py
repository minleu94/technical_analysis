"""P0 官方來源 candidate 的正規化唯讀契約。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping


def _require_aware(value: datetime, *, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} 必須包含 timezone")


def _require_sha256(value: str, *, field_name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
        raise ValueError(f"{field_name} 必須是 64 字元 SHA-256")


@dataclass(frozen=True)
class AvailabilityEvidence:
    """來源可得時間證據；禁止由交易日或 period end 推算。"""

    publication_at: datetime | None
    first_observed_at: datetime
    available_at: datetime
    quality: str
    evidence_kind: str
    warnings: tuple[str, ...]

    @classmethod
    def resolve(
        cls,
        *,
        publication_at: datetime | None,
        first_observed_at: datetime,
    ) -> "AvailabilityEvidence":
        _require_aware(first_observed_at, field_name="first_observed_at")
        if publication_at is not None:
            _require_aware(publication_at, field_name="publication_at")
            return cls(
                publication_at=publication_at,
                first_observed_at=first_observed_at,
                available_at=publication_at,
                quality="verified",
                evidence_kind="official_publication_timestamp",
                warnings=(),
            )
        return cls(
            publication_at=None,
            first_observed_at=first_observed_at,
            available_at=first_observed_at,
            quality="degraded",
            evidence_kind="first_observed_only",
            warnings=("official_publication_timestamp_missing",),
        )


@dataclass(frozen=True)
class NormalizedP0Observation:
    """Consumer 唯一可見的 canonical P0 candidate row。"""

    source_id: str
    source_version: str
    symbol: str
    observation_date: str
    period: str
    publication_at: datetime | None
    first_observed_at: datetime
    available_at: datetime
    raw_payload_sha256: str
    normalized_content_sha256: str
    quality: str
    availability_evidence_kind: str
    quantities: Mapping[str, int]
    metadata: Mapping[str, Any]
    warnings: tuple[str, ...]
    downstream_eligibility: str = "none"
    human_decision: str = "requires_human_acceptance"
    production_scheduler_allowed: bool = False

    @classmethod
    def build(
        cls,
        *,
        source_id: str,
        source_version: str,
        symbol: str,
        observation_date: str,
        period: str,
        publication_at: datetime | None,
        first_observed_at: datetime,
        raw_payload_sha256: str,
        quantities: Mapping[str, int],
        metadata: Mapping[str, Any] | None = None,
        warnings: tuple[str, ...] = (),
    ) -> "NormalizedP0Observation":
        _require_sha256(raw_payload_sha256, field_name="raw_payload_sha256")
        if not symbol.strip():
            raise ValueError("symbol 不可為空")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in quantities.values()):
            raise TypeError("quantities 僅允許明確 integer units")

        evidence = AvailabilityEvidence.resolve(
            publication_at=publication_at,
            first_observed_at=first_observed_at,
        )
        frozen_quantities = MappingProxyType(dict(sorted(quantities.items())))
        frozen_metadata = MappingProxyType(dict(metadata or {}))
        combined_warnings = tuple(dict.fromkeys((*warnings, *evidence.warnings)))
        hash_payload = {
            "source_id": source_id,
            "source_version": source_version,
            "symbol": symbol.strip(),
            "observation_date": observation_date,
            "period": period,
            "publication_at": publication_at.isoformat() if publication_at else None,
            "first_observed_at": first_observed_at.isoformat(),
            "available_at": evidence.available_at.isoformat(),
            "raw_payload_sha256": raw_payload_sha256,
            "quantities": dict(frozen_quantities),
            "metadata": dict(frozen_metadata),
            "warnings": list(combined_warnings),
        }
        normalized_hash = sha256(
            json.dumps(hash_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return cls(
            source_id=source_id,
            source_version=source_version,
            symbol=symbol.strip(),
            observation_date=observation_date,
            period=period,
            publication_at=publication_at,
            first_observed_at=first_observed_at,
            available_at=evidence.available_at,
            raw_payload_sha256=raw_payload_sha256,
            normalized_content_sha256=normalized_hash,
            quality=evidence.quality,
            availability_evidence_kind=evidence.evidence_kind,
            quantities=frozen_quantities,
            metadata=frozen_metadata,
            warnings=combined_warnings,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_version": self.source_version,
            "symbol": self.symbol,
            "observation_date": self.observation_date,
            "period": self.period,
            "publication_at": self.publication_at.isoformat() if self.publication_at else None,
            "first_observed_at": self.first_observed_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "raw_payload_sha256": self.raw_payload_sha256,
            "normalized_content_sha256": self.normalized_content_sha256,
            "quality": self.quality,
            "availability_evidence_kind": self.availability_evidence_kind,
            "quantities": dict(self.quantities),
            "metadata": dict(self.metadata),
            "warnings": list(self.warnings),
            "downstream_eligibility": self.downstream_eligibility,
            "human_decision": self.human_decision,
            "production_scheduler_allowed": self.production_scheduler_allowed,
        }
