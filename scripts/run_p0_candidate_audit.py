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
    "microstructure.periodic_call_auction": "twse_periodic_call_auction",
    "microstructure.full_delivery": "twse_full_delivery",
    "microstructure.suspended_halt_resume": "twse_halt_resume",
    "twse.monthly_revenue_announcement": "twse_monthly_revenue",
    "tpex.monthly_revenue_announcement": "tpex_monthly_revenue",
    "corporate_action.ex_dividend_timeline": "twse_ex_dividend",
    "corporate_action.reduction_split_par_value": "twse_reduction",
}


def build_p0_candidate_audit(
    decision_date: date,
    *,
    probe_report: Mapping[str, Any] | None = None,
    fubon_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """投影候選品質；只探測已接線的三個官方來源，絕不寫入資料庫。"""
    report = dict(
        probe_report
        if probe_report is not None
        else run_bounded_official_probe(decision_date)
    )
    probe_items = _validate_probe_report(report, decision_date)
    fubon_items = _validate_fubon_projection(fubon_projection) if fubon_projection is not None else {}
    probe_report_sha256 = _probe_report_sha256(report)
    items: list[dict[str, Any]] = []
    for source_id in P0_SOURCE_IDS:
        probe_source_id = LIVE_PROBE_SOURCE_MAP.get(source_id)
        if probe_source_id is None:
            item = {
                    "source_id": source_id,
                    "audit_status": "not_started_no_candidate_adapter",
                    "quality_status": "missing",
                    "row_count": 0,
                    "accepted_row_count": 0,
                    "blockers": ["candidate_adapter_not_implemented"],
                }
            _attach_fubon_research_supplement(item, fubon_items.get(source_id))
            items.append(item)
            continue
        probe = probe_items.get(probe_source_id)
        if probe is None:
            item = {
                    "source_id": source_id,
                    "audit_status": "probe_not_returned",
                    "quality_status": "missing",
                    "row_count": 0,
                    "accepted_row_count": 0,
                    "blockers": ["official_probe_not_returned"],
                }
            _attach_fubon_research_supplement(item, fubon_items.get(source_id))
            items.append(item)
            continue
        counts = _validated_probe_counts(probe)
        timestamp_evidence = str(probe.get("timestamp_evidence", "unavailable"))
        item = {
                "source_id": source_id,
                "audit_status": "observed_candidate" if probe.get("schema_status") == "matched" else "schema_blocked",
                "quality_status": "verified" if timestamp_evidence == "official_publication_timestamp" else "degraded",
                "row_count": counts["raw_row_count"],
                "accepted_row_count": counts["accepted_row_count"],
                "timestamp_evidence": timestamp_evidence,
                "payload_sha256": probe.get("payload_sha256"),
                "blockers": (["official_publication_timestamp_missing"] if timestamp_evidence == "first_observed_only" else []),
            }
        _attach_fubon_research_supplement(item, fubon_items.get(source_id))
        items.append(item)
    return {
        "schema_version": "p0-candidate-audit.v1",
        "decision_date": decision_date.isoformat(),
        "mode": "bounded_official_read_only",
        "lineage": {
            "probe_date": decision_date.isoformat(),
            "probe_mode": "bounded_official_read_only",
            "probe_report_sha256": f"sha256:{probe_report_sha256}",
            "fubon_research_projection_present": fubon_projection is not None,
        },
        "items": items,
        "formal_oos_allowed": False,
        "production_scheduler_allowed": False,
        "downstream_eligibility": "none",
        "human_decision": "requires_human_acceptance",
    }


def _attach_fubon_research_supplement(
    item: dict[str, Any], rows: Sequence[Mapping[str, Any]] | None
) -> None:
    """Expose a bounded research supplement without upgrading official evidence."""
    if not rows:
        return
    if item["audit_status"] in {"not_started_no_candidate_adapter", "probe_not_returned"}:
        # A captured Fubon projection is a real, but explicitly non-official,
        # candidate path.  Do not leave it indistinguishable from no adapter.
        item["audit_status"] = "observed_research_only"
        item["quality_status"] = "degraded"
        item["timestamp_evidence"] = "first_observed_only"
    item["fubon_research_supplement"] = {
        "status": "observed_research_only",
        "row_count": len(rows),
        "quality": "degraded",
        "availability_evidence": "first_observed_only",
        "blockers": [
            "not_official_announcement_evidence",
            "formal_oos_not_allowed",
        ],
    }


def _validate_fubon_projection(
    projection: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    expected = {
        "schema_version": "fubon-p0-research-projection.v1",
        "source": "fubon.marketdata",
        "research_only": True,
        "formal_oos_allowed": False,
        "production_scheduler_allowed": False,
        "production_blend_alpha_bp": 0,
    }
    for key, value in expected.items():
        if projection.get(key) != value:
            raise ValueError(f"Fubon projection {key} mismatch")
    raw_rows = projection.get("observations")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise ValueError("Fubon projection observations must be an array")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in raw_rows:
        if not isinstance(row, Mapping):
            raise ValueError("Fubon projection observation must be an object")
        source_id = row.get("source_id")
        if source_id not in P0_SOURCE_IDS:
            raise ValueError("Fubon projection source_id must be a P0 source")
        if row.get("quality") != "degraded" or row.get("availability_evidence_kind") != "first_observed_only":
            raise ValueError("Fubon projection must remain first_observed_only degraded")
        if row.get("downstream_eligibility") != "none" or row.get("production_scheduler_allowed") is not False:
            raise ValueError("Fubon projection access boundary mismatch")
        grouped.setdefault(str(source_id), []).append(dict(row))
    return grouped


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
    parser.add_argument("--fubon-projection", type=Path, help="唯讀載入手動富邦 research JSON")
    args = parser.parse_args(argv)
    fubon_projection = (
        json.loads(args.fubon_projection.read_text(encoding="utf-8"))
        if args.fubon_projection is not None
        else None
    )
    payload = build_p0_candidate_audit(args.decision_date, fubon_projection=fubon_projection)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
