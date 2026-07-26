"""Fubon Point-in-Time (PIT) observation validator and normalizer.

Enforces available_at <= decision_timestamp rules, fail-closed handling for missing timestamps,
revision conflict detection, hash validation, non-float quantity enforcement, and idempotency/quarantine logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any, Sequence


@dataclass(frozen=True)
class FubonPITObservation:
    """Read-only Point-in-Time observation representation for Fubon market data."""

    source_id: str
    source_version: str
    symbol: str
    market_timestamp: str | None
    published_at: str | None
    first_observed_at: str | None
    available_at: str
    decision_timestamp: str
    revision_id: str
    raw_payload_sha256: str
    normalized_content_sha256: str
    quality_status: str
    missing_or_degraded_reasons: tuple[str, ...]
    quarantine_status: str
    quantities: dict[str, str | int]

    @property
    def available_date(self) -> str:
        return self.available_at[:10]

    @property
    def decision_date(self) -> str:
        return self.decision_timestamp[:10]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "fubon-pit-observation.v1",
            "source_id": self.source_id,
            "source_version": self.source_version,
            "symbol": self.symbol,
            "market_timestamp": self.market_timestamp,
            "published_at": self.published_at,
            "first_observed_at": self.first_observed_at,
            "available_at": self.available_at,
            "decision_timestamp": self.decision_timestamp,
            "revision_id": self.revision_id,
            "raw_payload_sha256": self.raw_payload_sha256,
            "normalized_content_sha256": self.normalized_content_sha256,
            "quality_status": self.quality_status,
            "missing_or_degraded_reasons": list(self.missing_or_degraded_reasons),
            "quarantine_status": self.quarantine_status,
            "quantities": dict(self.quantities),
        }


@dataclass(frozen=True)
class FubonPITValidationResult:
    """Result of PIT validation batch."""

    accepted_observations: tuple[FubonPITObservation, ...]
    degraded_observations: tuple[FubonPITObservation, ...]
    quarantined_observations: tuple[FubonPITObservation, ...]
    rejected_count: int
    diagnostics: tuple[str, ...]


ALLOWED_SOURCE_IDS: set[str] = {
    "fubon.marketdata",
    "microstructure.disposition_stock",
    "microstructure.periodic_call_auction",
    "microstructure.suspended_halt_resume",
    "microstructure.limit_lock",
    "corporate_action.ex_dividend_timeline",
    "corporate_action.reduction_split_par_value",
}


class FubonPITObservationValidator:
    """Fail-closed Point-in-Time validator for Fubon market data."""

    def validate_observation(
        self,
        raw_input: dict[str, Any],
        decision_timestamp: str,
    ) -> tuple[FubonPITObservation | None, list[str]]:
        """Validate a single Fubon observation against decision_timestamp."""
        diagnostics: list[str] = []

        # 1. Required text fields & Source ID allowlist
        symbol = str(raw_input.get("symbol", "")).strip()
        if not symbol:
            return None, ["rejected_missing_symbol"]

        source_id = str(raw_input.get("source_id", "fubon.marketdata")).strip()
        if source_id not in ALLOWED_SOURCE_IDS:
            return None, [f"rejected_unauthorized_source_id:{source_id}"]

        source_version = str(raw_input.get("source_version", "fubon-neo-marketdata.v2.2.8")).strip()
        revision_id = str(raw_input.get("revision_id", "rev-1")).strip()

        # 2. Extract timestamps & published_at missing reason
        market_timestamp = _optional_str(raw_input.get("market_timestamp"))
        published_at = _optional_str(raw_input.get("published_at"))
        first_observed_at = _optional_str(raw_input.get("first_observed_at"))

        # availability timestamp resolution
        available_at = _optional_str(raw_input.get("available_at") or raw_input.get("available_date"))
        if available_at is None and first_observed_at is not None:
            available_at = first_observed_at
            diagnostics.append("fubon_availability_fallback_to_first_observed")

        if available_at is None:
            diagnostics.append("fubon_missing_availability_timestamp")
            return None, diagnostics

        # 3. PIT comparison: date-only values use date semantics; datetimes must
        # both be aware or both be naive. A timezone is never guessed.
        available_lte_decision = _timestamp_lte(available_at, decision_timestamp)
        if available_lte_decision is None:
            return None, ["rejected_invalid_available_at"]
        if _parse_iso_timestamp_or_date(decision_timestamp) is None:
            return None, ["rejected_invalid_decision_timestamp"]
        if available_lte_decision is False:
            return None, ["rejected_future_observation_pit_violation"]

        # Timestamp sequence consistency check
        if published_at is not None and first_observed_at is not None:
            published_lte_observed = _timestamp_lte(published_at, first_observed_at)
            if published_lte_observed is not True:
                diagnostics.append(
                    "fubon_timestamp_sequence_inconsistency:published_after_first_observed"
                )

        quantities_raw = raw_input.get("quantities", {})
        quantities: dict[str, str | int] = {}
        if not isinstance(quantities_raw, dict):
            return None, ["rejected_invalid_quantities"]
        for key, value in quantities_raw.items():
            if isinstance(value, bool):
                return None, [f"rejected_boolean_quantity:{key}"]
            if isinstance(value, float):
                diagnostics.append("fubon_raw_float_quantity_converted")
                quantities[str(key)] = str(Decimal(str(value)))
            elif isinstance(value, (int, str)):
                quantities[str(key)] = value
            else:
                return None, [f"rejected_unsupported_quantity_type:{key}"]

        # 4. Hash verification. Declaration fields are excluded from the
        # canonical raw payload so a supplied digest can actually be verified.
        raw_payload_sha256 = str(raw_input.get("raw_payload_sha256", "")).strip()
        calculated_raw_hash = _raw_payload_hash(raw_input)
        raw_hash_mismatch = bool(
            raw_payload_sha256 and raw_payload_sha256 != calculated_raw_hash
        )
        if not raw_payload_sha256:
            raw_payload_sha256 = calculated_raw_hash

        normalized_content_sha256 = str(raw_input.get("normalized_content_sha256", "")).strip()
        expected_norm_hash = _payload_hash(quantities)
        normalized_hash_mismatch = bool(
            normalized_content_sha256
            and normalized_content_sha256 != expected_norm_hash
        )
        quarantine_reasons: list[str] = []
        if raw_hash_mismatch:
            diagnostics.append("fubon_raw_hash_mismatch")
            quarantine_reasons.append("raw_hash_mismatch")
        if normalized_hash_mismatch:
            diagnostics.append("fubon_normalized_hash_mismatch")
            quarantine_reasons.append("normalized_hash_mismatch")
        if any(reason.startswith("fubon_timestamp_sequence_inconsistency") for reason in diagnostics):
            quarantine_reasons.append("timestamp_sequence_inconsistency")

        if quarantine_reasons:
            obs = FubonPITObservation(
                source_id=source_id,
                source_version=source_version,
                symbol=symbol,
                market_timestamp=market_timestamp,
                published_at=published_at,
                first_observed_at=first_observed_at,
                available_at=available_at,
                decision_timestamp=decision_timestamp,
                revision_id=revision_id,
                raw_payload_sha256=raw_payload_sha256,
                normalized_content_sha256=expected_norm_hash,
                quality_status="quarantined",
                missing_or_degraded_reasons=tuple(
                    dict.fromkeys(quarantine_reasons + diagnostics)
                ),
                quarantine_status="quarantined",
                quantities=quantities,
            )
            return obs, diagnostics

        normalized_content_sha256 = expected_norm_hash

        # 5. Determine Quality Status
        quality_status = "observed"
        missing_reasons: list[str] = list(diagnostics)
        if published_at is None:
            quality_status = "degraded"
            missing_reasons.append("fubon_missing_official_publication_time")

        obs = FubonPITObservation(
            source_id=source_id,
            source_version=source_version,
            symbol=symbol,
            market_timestamp=market_timestamp,
            published_at=published_at,
            first_observed_at=first_observed_at,
            available_at=available_at,
            decision_timestamp=decision_timestamp,
            revision_id=revision_id,
            raw_payload_sha256=raw_payload_sha256,
            normalized_content_sha256=normalized_content_sha256,
            quality_status=quality_status,
            missing_or_degraded_reasons=tuple(dict.fromkeys(missing_reasons)),
            quarantine_status="clean",
            quantities=quantities,
        )
        return obs, diagnostics

    def validate_batch(
        self,
        raw_inputs: Sequence[dict[str, Any]],
        decision_timestamp: str,
    ) -> FubonPITValidationResult:
        """Validate a batch of observations with idempotency & duplicate conflict checks."""
        accepted: list[FubonPITObservation] = []
        degraded: list[FubonPITObservation] = []
        quarantined: list[FubonPITObservation] = []
        rejected_count = 0
        diagnostics: list[str] = []

        seen_keys: dict[tuple[str, str, str], FubonPITObservation] = {}

        for raw_input in raw_inputs:
            obs, obs_diag = self.validate_observation(raw_input, decision_timestamp)
            diagnostics.extend(obs_diag)
            if obs is None:
                rejected_count += 1
                continue

            dedup_key = (obs.source_id, obs.symbol, obs.available_at)
            if dedup_key in seen_keys:
                existing = seen_keys[dedup_key]
                if existing.normalized_content_sha256 == obs.normalized_content_sha256:
                    # Idempotent duplicate: skip without penalty
                    diagnostics.append(f"fubon_idempotent_duplicate_skipped:{obs.symbol}")
                    continue
                else:
                    # Conflicting duplicate: quarantine
                    diagnostics.append(f"fubon_conflicting_duplicate_quarantined:{obs.symbol}")
                    quarantined_obs = FubonPITObservation(
                        source_id=obs.source_id,
                        source_version=obs.source_version,
                        symbol=obs.symbol,
                        market_timestamp=obs.market_timestamp,
                        published_at=obs.published_at,
                        first_observed_at=obs.first_observed_at,
                        available_at=obs.available_at,
                        decision_timestamp=obs.decision_timestamp,
                        revision_id=obs.revision_id,
                        raw_payload_sha256=obs.raw_payload_sha256,
                        normalized_content_sha256=obs.normalized_content_sha256,
                        quality_status="quarantined",
                        missing_or_degraded_reasons=tuple(
                            dict.fromkeys(list(obs.missing_or_degraded_reasons) + ["conflicting_duplicate"])
                        ),
                        quarantine_status="quarantined",
                        quantities=obs.quantities,
                    )
                    quarantined.append(quarantined_obs)
                    continue

            seen_keys[dedup_key] = obs
            if obs.quarantine_status == "quarantined":
                quarantined.append(obs)
            elif obs.quality_status == "degraded":
                degraded.append(obs)
            else:
                accepted.append(obs)

        return FubonPITValidationResult(
            accepted_observations=tuple(accepted),
            degraded_observations=tuple(degraded),
            quarantined_observations=tuple(quarantined),
            rejected_count=rejected_count,
            diagnostics=tuple(dict.fromkeys(diagnostics)),
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _parse_iso_timestamp_or_date(value: str) -> datetime | None:
    value_clean = value.strip().replace("Z", "+00:00")
    if len(value_clean) == 10:
        try:
            d = date.fromisoformat(value_clean)
            return datetime(d.year, d.month, d.day)
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(value_clean)
    except ValueError:
        return None


def _timestamp_lte(left: str, right: str) -> bool | None:
    left_value = _parse_iso_timestamp_or_date(left)
    right_value = _parse_iso_timestamp_or_date(right)
    if left_value is None or right_value is None:
        return None
    if _is_date_only(left) or _is_date_only(right):
        return left_value.date() <= right_value.date()
    if (left_value.tzinfo is None) != (right_value.tzinfo is None):
        return None
    return left_value <= right_value


def _is_date_only(value: str) -> bool:
    return len(value.strip()) == 10


def _payload_hash(data: Any) -> str:
    rendered = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return f"sha256:{sha256(rendered.encode('utf-8')).hexdigest()}"


def _raw_payload_hash(raw_input: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in raw_input.items()
        if key not in {"raw_payload_sha256", "normalized_content_sha256"}
    }
    return _payload_hash(payload)
