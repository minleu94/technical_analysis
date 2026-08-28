"""Inspect the Gate 3 P0 Source Control Center as a read-only projection.

The command accepts an optional candidate/evidence audit JSON and an optional
JSON list of source-acceptance decision revisions. It never opens the decision
registry and never writes a database. Without inputs it still emits all
thirteen contract rows, explicitly marked as awaiting evidence and human
acceptance.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_module.p0_source_control_center import P0SourceControlCenterService
from data_module.source_acceptance_decision_registry import (
    SourceAcceptanceDecisionRevision,
    parse_source_acceptance_decisions,
)


def inspect_p0_source_control_center(
    *,
    audit_path: Path | None = None,
    decision_path: Path | None = None,
) -> dict[str, Any]:
    audit_payload = _read_json_object(audit_path) if audit_path is not None else None
    decisions = _read_decisions(decision_path) if decision_path is not None else ()
    return P0SourceControlCenterService().build(
        candidate_audit=audit_payload,
        decisions=decisions,
    ).to_dict()


def render_markdown(payload: Mapping[str, Any]) -> str:
    boundary = payload.get("boundary", {})
    rows = payload.get("rows", [])
    lines = [
        "# P0 Data Source Control Center",
        "",
        "> 唯讀治理投影；不會自動接受來源、不寫入正式資料、不啟用排程器。",
        "",
        f"- P0 source count: {payload.get('p0_source_count', 'Unknown')}",
        f"- Status counts: `{json.dumps(payload.get('status_counts', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- Decision counts: `{json.dumps(payload.get('decision_status_counts', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- Accepted / limited: {payload.get('accepted_count', 0)} / {payload.get('limited_count', 0)}",
        f"- Downstream eligible: {payload.get('downstream_eligible_count', 0)}",
        f"- Boundary: read_only={boundary.get('read_only')} writes_allowed={boundary.get('writes_allowed')} "
        f"formal_oos_allowed={boundary.get('formal_oos_allowed')} auto_accept_allowed={boundary.get('auto_accept_allowed')}",
        "",
        "| Source | Status | Machine / Audit | Rows | Decision | Eligibility | Blockers |",
        "|---|---|---|---:|---|---|---|",
    ]
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, Mapping):
            continue
        blockers = "; ".join(str(value) for value in row.get("blockers", ())) or "None"
        lines.append(
            "| {source} | {status} | {machine} / {audit} | {rows} | {decision} | {eligibility} | {blockers} |".format(
                source=row.get("source_id", "Unknown"),
                status=row.get("governance_status", "Unknown"),
                machine=row.get("machine_status", "Unknown"),
                audit=row.get("audit_status", "Unknown"),
                rows=row.get("observed_rows") if row.get("observed_rows") is not None else "Unknown",
                decision=row.get("decision_status", "Unknown"),
                eligibility=row.get("downstream_eligibility", "Unknown"),
                blockers=blockers,
            )
        )
    lines.extend(
        [
            "",
            "## Global blockers",
            "",
            *(
                f"- {value}"
                for value in payload.get("global_blockers", ())
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-json", type=Path, help="候選或 P0 source evidence audit JSON（唯讀）")
    parser.add_argument("--decision-json", type=Path, help="source acceptance decision revisions JSON（唯讀）")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path, help="輸出報告路徑；未指定時輸出至 stdout")
    args = parser.parse_args(argv)

    try:
        payload = inspect_p0_source_control_center(
            audit_path=args.audit_json,
            decision_path=args.decision_json,
        )
        rendered = (
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            if args.format == "json"
            else render_markdown(payload)
        )
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"p0 source control center blocked: {error}", file=sys.stderr)
        return 2
    return 0


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            continue


def _read_json_object(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"JSON artifact is unreadable: {path}") from error
    if not isinstance(payload, Mapping):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return payload


def _read_decisions(path: Path) -> tuple[SourceAcceptanceDecisionRevision, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"decision JSON is unreadable: {path}") from error
    return parse_source_acceptance_decisions(payload)


if __name__ == "__main__":
    raise SystemExit(main())
