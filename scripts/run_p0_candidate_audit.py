"""產生 13 項 P0 候選資料來源的唯讀品質稽核總覽。"""

from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.p0_source_contract_registry import P0_SOURCE_IDS
from scripts.update_phase3c_candidates import run_bounded_official_probe


LIVE_PROBE_SOURCE_MAP = {
    "institutional_flows": "twse_institutional",
    "credit_transactions": "twse_credit",
    "tdcc_shareholding": "tdcc_shareholding",
    "microstructure.disposition_stock": "twse_disposition",
    "corporate_action.ex_dividend_timeline": "twse_ex_dividend",
    "corporate_action.reduction_split_par_value": "twse_reduction",
}


def build_p0_candidate_audit(
    decision_date: date,
    *,
    probe_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """投影候選品質；只探測已接線的三個官方來源，絕不寫入資料庫。"""
    report = dict(
        probe_report
        if probe_report is not None
        else run_bounded_official_probe(decision_date)
    )
    probe_items = _validate_probe_report(report, decision_date)
    probe_report_sha256 = _probe_report_sha256(report)
    items: list[dict[str, Any]] = []
    for source_id in P0_SOURCE_IDS:
        probe_source_id = LIVE_PROBE_SOURCE_MAP.get(source_id)
        if probe_source_id is None:
            items.append(
                {
                    "source_id": source_id,
                    "audit_status": "not_started_no_candidate_adapter",
                    "quality_status": "missing",
                    "row_count": 0,
                    "accepted_row_count": 0,
                    "blockers": ["candidate_adapter_not_implemented"],
                }
            )
            continue
        probe = probe_items.get(probe_source_id)
        if probe is None:
            items.append(
                {
                    "source_id": source_id,
                    "audit_status": "probe_not_returned",
                    "quality_status": "missing",
                    "row_count": 0,
                    "accepted_row_count": 0,
                    "blockers": ["official_probe_not_returned"],
                }
            )
            continue
        counts = _validated_probe_counts(probe)
        timestamp_evidence = str(probe.get("timestamp_evidence", "unavailable"))
        items.append(
            {
                "source_id": source_id,
                "audit_status": "observed_candidate" if probe.get("schema_status") == "matched" else "schema_blocked",
                "quality_status": "verified" if timestamp_evidence == "official_publication_timestamp" else "degraded",
                "row_count": counts["raw_row_count"],
                "accepted_row_count": counts["accepted_row_count"],
                "timestamp_evidence": timestamp_evidence,
                "payload_sha256": probe.get("payload_sha256"),
                "blockers": (["official_publication_timestamp_missing"] if timestamp_evidence == "first_observed_only" else []),
            }
        )
    return {
        "schema_version": "p0-candidate-audit.v1",
        "decision_date": decision_date.isoformat(),
        "mode": "bounded_official_read_only",
        "lineage": {
            "probe_date": decision_date.isoformat(),
            "probe_mode": "bounded_official_read_only",
            "probe_report_sha256": f"sha256:{probe_report_sha256}",
        },
        "items": items,
        "formal_oos_allowed": False,
        "production_scheduler_allowed": False,
        "downstream_eligibility": "none",
        "human_decision": "requires_human_acceptance",
    }


def _validate_probe_report(
    report: Mapping[str, Any],
    decision_date: date,
) -> dict[str, dict[str, Any]]:
    expected = {
        "probe_date": decision_date.isoformat(),
        "probe_mode": "bounded_official_read_only",
        "license_accepted": False,
        "source_accepted": False,
        "downstream_eligibility": "none",
        "production_scheduler_allowed": False,
        "human_decision": "requires_human_acceptance",
    }
    for key, expected_value in expected.items():
        if report.get(key) != expected_value:
            raise ValueError(f"probe report {key} mismatch")
    raw_sources = report.get("sources")
    if not isinstance(raw_sources, Sequence) or isinstance(raw_sources, (str, bytes)):
        raise ValueError("probe report sources must be an array")
    probe_items: dict[str, dict[str, Any]] = {}
    for raw_item in raw_sources:
        if not isinstance(raw_item, Mapping):
            raise ValueError("probe source row must be an object")
        source_id = raw_item.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("probe source_id is required")
        if source_id in probe_items:
            raise ValueError(f"duplicate probe source_id: {source_id}")
        if source_id not in LIVE_PROBE_SOURCE_MAP.values():
            raise ValueError(f"unknown probe source_id: {source_id}")
        _validated_probe_counts(raw_item)
        _validate_payload_sha256(raw_item)
        probe_items[source_id] = dict(raw_item)
    return probe_items


def _validated_probe_counts(probe: Mapping[str, Any]) -> dict[str, int]:
    names = (
        "raw_row_count",
        "accepted_row_count",
        "duplicate_row_count",
        "quarantine_row_count",
        "blocked_row_count",
    )
    counts: dict[str, int] = {}
    for name in names:
        value = probe.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"probe {name} must be a non-negative integer")
        counts[name] = value
    classified = (
        counts["accepted_row_count"]
        + counts["duplicate_row_count"]
        + counts["quarantine_row_count"]
        + counts["blocked_row_count"]
    )
    if counts["raw_row_count"] != classified:
        raise ValueError("probe row conservation violated")
    return counts


def _validate_payload_sha256(probe: Mapping[str, Any]) -> None:
    payload_sha256 = probe.get("payload_sha256")
    if probe.get("schema_status") == "matched":
        if not isinstance(payload_sha256, str) or len(payload_sha256) != 64:
            raise ValueError("matched probe payload_sha256 must be a SHA-256 hex digest")
        try:
            int(payload_sha256, 16)
        except ValueError as exc:
            raise ValueError("matched probe payload_sha256 must be a SHA-256 hex digest") from exc


def _probe_report_sha256(report: Mapping[str, Any]) -> str:
    canonical = dict(report)
    sources = canonical.get("sources")
    if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes)):
        canonical["sources"] = sorted(
            (dict(item) for item in sources if isinstance(item, Mapping)),
            key=lambda item: str(item.get("source_id", "")),
        )
    rendered = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(rendered.encode("utf-8")).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-date", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    payload = build_p0_candidate_audit(args.decision_date)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
