"""將 PIT mappings 投影為下一版 dataset 可選擇消費的 eligibility artifact。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

from data_module.corporate_action_policy import (
    CORPORATE_ACTION_LABEL_POLICY_VERSION,
    evaluate_corporate_action_label_window,
)


@dataclass(frozen=True)
class P0MLEligibilityArtifact:
    schema_version: str
    policy_version: str
    mode: str
    mapping_hashes: tuple[tuple[str, str], ...]
    source_coverage: tuple[tuple[str, str, str, str], ...]
    eligible_keys: tuple[str, ...]
    blocked_keys: tuple[str, ...]
    degraded_keys: tuple[str, ...]
    reason_counts: dict[str, int]
    formal_oos_allowed: bool
    canonical_hash: str

    def payload(self, *, include_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "mode": self.mode,
            "mapping_hashes": dict(self.mapping_hashes),
            "source_coverage": [
                {
                    "source_id": source_id,
                    "coverage_start": start,
                    "coverage_end": end,
                    "quality": quality,
                }
                for source_id, start, end, quality in self.source_coverage
            ],
            "eligible_keys": list(self.eligible_keys),
            "blocked_keys": list(self.blocked_keys),
            "degraded_keys": list(self.degraded_keys),
            "reason_counts": dict(sorted(self.reason_counts.items())),
            "formal_oos_allowed": self.formal_oos_allowed,
        }
        if include_hash:
            payload["canonical_hash"] = self.canonical_hash
        return payload


def project_p0_ml_eligibility(
    *,
    candidates: Iterable[Mapping[str, object]],
    mapping_hashes: Mapping[str, str],
    corporate_coverage: Iterable[Mapping[str, object]],
    mode: str,
) -> P0MLEligibilityArtifact:
    if mode not in {"strict", "research"}:
        raise ValueError("mode must be strict or research")
    coverage = {
        str(row.get("source_id") or ""): (
            str(row.get("coverage_start") or ""),
            str(row.get("coverage_end") or ""),
            str(row.get("quality") or "unknown"),
        )
        for row in corporate_coverage
    }
    eligible: list[str] = []
    blocked: list[str] = []
    degraded: list[str] = []
    reason_counts: dict[str, int] = {}

    for row in candidates:
        natural_key = str(row.get("natural_key") or "")
        available_at = date.fromisoformat(str(row.get("available_at") or ""))
        feature_cutoff = date.fromisoformat(str(row.get("feature_cutoff") or ""))
        tier = str(row.get("quality_tier") or "")
        reasons: list[str] = []
        if tier == "retroactive_baseline" and available_at == date(2026, 6, 17):
            reasons.append("retroactive_backfill_not_historical_availability")
        if available_at > feature_cutoff:
            reasons.append("available_after_feature_cutoff")
        if tier not in {"official", "observed_only"}:
            reasons.append("mapping_quality_not_eligible")

        source_id = str(row.get("corporate_source_id") or "")
        start, end, quality = coverage.get(source_id, ("", "", "unknown"))
        label_result = evaluate_corporate_action_label_window(
            label_start=str(row.get("label_start") or ""),
            label_end=str(row.get("label_end") or ""),
            coverage_start=start or None,
            coverage_end=end or None,
            coverage_quality=quality,
            mode=mode,
        )
        if label_result.reasons:
            reasons.extend(label_result.reasons)

        for reason in sorted(set(reasons)):
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if any(reason != "coverage_unknown" for reason in reasons):
            blocked.append(natural_key)
        elif label_result.quality == "blocked":
            blocked.append(natural_key)
        elif label_result.quality == "degraded":
            degraded.append(natural_key)
        else:
            eligible.append(natural_key)

    base = {
        "schema_version": "p0-ml-eligibility.v1",
        "policy_version": CORPORATE_ACTION_LABEL_POLICY_VERSION,
        "mode": mode,
        "mapping_hashes": dict(sorted(mapping_hashes.items())),
        "source_coverage": [
            {
                "source_id": source_id,
                "coverage_start": values[0],
                "coverage_end": values[1],
                "quality": values[2],
            }
            for source_id, values in sorted(coverage.items())
        ],
        "eligible_keys": sorted(eligible),
        "blocked_keys": sorted(blocked),
        "degraded_keys": sorted(degraded),
        "reason_counts": dict(sorted(reason_counts.items())),
        "formal_oos_allowed": not blocked and not degraded,
    }
    canonical_hash = hashlib.sha256(
        json.dumps(base, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return P0MLEligibilityArtifact(
        schema_version="p0-ml-eligibility.v1",
        policy_version=CORPORATE_ACTION_LABEL_POLICY_VERSION,
        mode=mode,
        mapping_hashes=tuple(sorted(mapping_hashes.items())),
        source_coverage=tuple(
            (source_id, values[0], values[1], values[2])
            for source_id, values in sorted(coverage.items())
        ),
        eligible_keys=tuple(sorted(eligible)),
        blocked_keys=tuple(sorted(blocked)),
        degraded_keys=tuple(sorted(degraded)),
        reason_counts=reason_counts,
        formal_oos_allowed=not blocked and not degraded,
        canonical_hash=canonical_hash,
    )


def write_p0_ml_eligibility(
    artifact: P0MLEligibilityArtifact,
    *,
    output_root: Path,
) -> Path:
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "p0-ml-eligibility.v1.json"
    path.write_text(
        json.dumps(artifact.payload(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
