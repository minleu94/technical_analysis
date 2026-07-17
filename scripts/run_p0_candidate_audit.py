"""產生 13 項 P0 候選資料來源的唯讀品質稽核總覽。"""

from __future__ import annotations

import argparse
from datetime import date
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
}


def build_p0_candidate_audit(
    decision_date: date,
    *,
    probe_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """投影候選品質；只探測已接線的三個官方來源，絕不寫入資料庫。"""
    report = dict(probe_report or run_bounded_official_probe(decision_date))
    probe_items = {
        str(item["source_id"]): dict(item)
        for item in report.get("sources", ())
    }
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
        timestamp_evidence = str(probe.get("timestamp_evidence", "unavailable"))
        items.append(
            {
                "source_id": source_id,
                "audit_status": "observed_candidate" if probe.get("schema_status") == "matched" else "schema_blocked",
                "quality_status": "verified" if timestamp_evidence == "official_publication_timestamp" else "degraded",
                "row_count": int(probe.get("raw_row_count", 0)),
                "accepted_row_count": int(probe.get("accepted_row_count", 0)),
                "timestamp_evidence": timestamp_evidence,
                "payload_sha256": probe.get("payload_sha256"),
                "blockers": (["official_publication_timestamp_missing"] if timestamp_evidence == "first_observed_only" else []),
            }
        )
    return {
        "schema_version": "p0-candidate-audit.v1",
        "decision_date": decision_date.isoformat(),
        "mode": "bounded_official_read_only",
        "items": items,
        "formal_oos_allowed": False,
        "production_scheduler_allowed": False,
        "downstream_eligibility": "none",
        "human_decision": "requires_human_acceptance",
    }


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
