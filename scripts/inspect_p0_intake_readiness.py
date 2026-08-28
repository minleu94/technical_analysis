"""檢查 P0 來源治理 intake dossier 的完整性與 owner review readiness。

這個 CLI 只讀取明確指定的 JSON，將 13 個 authoritative P0 source dossier
投影成可供 owner 審查的報告。它不會建立或開啟 decision registry、不會寫入
正式資料、不會自動接受來源，也不會把 ``checklist_complete`` 轉成下游資格。

輸入格式為 ``p0-source-intake.v1``，內含完整 13 列
``source-acceptance-dossier.v1``。若尚未有輸入，可用明確的
``--template-output`` 產生帶有安全邊界的候選範本；範本不含任何 evidence 或
acceptance 決議。
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.p0_source_contract_registry import P0_SOURCE_IDS
from data_module.source_acceptance_governance import (
    SourceAcceptanceDossier,
    SourceAcceptanceGovernance,
)


P0_INTAKE_SCHEMA_VERSION = "p0-source-intake.v1"
_DOSSIER_SCHEMA_VERSION = "source-acceptance-dossier.v1"
_PRODUCTION_DEFAULT = "D:/Min/Python/Project/FA_Data"
_BOUNDARY = {
    "read_only": True,
    "writes_allowed": False,
    "formal_oos_allowed": False,
    "production_scheduler_allowed": False,
    "downstream_eligibility": "none",
    "auto_accept_allowed": False,
}
_SECRET_KEYS = frozenset(
    {"api_key", "authorization", "cookie", "credential", "password", "secret", "token"}
)
_DOSSIER_KEYS = frozenset(
    {
        "schema_version",
        "source_id",
        "source_owner_role",
        "license_owner_role",
        "license_status",
        "license_scope",
        "redistribution_policy",
        "source_status",
        "publication_time_policy",
        "timezone",
        "available_date_policy",
        "revision_policy",
        "pit_coverage_window",
        "coverage_numerator",
        "coverage_denominator",
        "missing_policy",
        "row_conservation_counts",
        "quarantine_policy",
        "quality_thresholds",
        "downstream_use_cases",
        "downstream_eligibility",
        "disable_conditions",
        "rollback_reference",
        "evidence_artifact_ids",
        "reviewer_role",
        "decision_timestamp",
        "decision_revision_id",
    }
)
_REQUIRED_TEXT_FIELDS = (
    "source_id",
    "source_owner_role",
    "license_owner_role",
    "license_status",
    "license_scope",
    "redistribution_policy",
    "source_status",
    "publication_time_policy",
    "timezone",
    "available_date_policy",
    "revision_policy",
    "pit_coverage_window",
    "missing_policy",
    "quarantine_policy",
    "rollback_reference",
)
_OPTIONAL_TEXT_FIELDS = ("reviewer_role", "decision_timestamp", "decision_revision_id")
_COLLECTION_FIELDS = ("downstream_use_cases", "disable_conditions", "evidence_artifact_ids")


def build_p0_intake_template() -> dict[str, Any]:
    """建立 13 列候選輸入範本；不產生任何 evidence 或 decision。"""

    dossiers = []
    for source_id in P0_SOURCE_IDS:
        dossier = SourceAcceptanceDossier(
            source_id=source_id,
            source_owner_role="",
            license_owner_role="",
            license_status="requires_review",
            license_scope="research_only",
            redistribution_policy="unverified",
            source_status="candidate",
            publication_time_policy="unverified",
            timezone="Asia/Taipei",
            available_date_policy="unverified",
            revision_policy="unverified",
            pit_coverage_window="unverified",
            coverage_numerator=0,
            coverage_denominator=0,
            missing_policy="fail_closed",
            row_conservation_counts={},
            quarantine_policy="quarantine_on_schema_error",
            quality_thresholds={"minimum_coverage_bp": 9500},
            downstream_use_cases=("research_backtest",),
            disable_conditions=("license_revoked", "pit_leakage"),
            rollback_reference="decision:initial-candidate",
            evidence_artifact_ids=(),
            downstream_eligibility="none",
        )
        dossiers.append(dossier.to_dict())
    return {
        "schema_version": P0_INTAKE_SCHEMA_VERSION,
        "safety_flags": dict(_BOUNDARY),
        "dossiers": dossiers,
    }


def audit_p0_intake_readiness() -> dict[str, Any]:
    """保留舊版程式入口，改以新的 template inspection 產生唯讀摘要。"""

    template = build_p0_intake_template()
    result = inspect_p0_intake(template)
    sources: list[dict[str, Any]] = []
    for row in result["rows"]:
        sources.append(
            {
                "source_id": row["source_id"],
                "checklist_complete": row["checklist_complete"],
                "status": row["status"],
                "downstream_eligibility": row["downstream_eligibility"],
                "active_blockers": row["active_blockers"],
                "missing_authority_evidence": row["missing_authority_evidence"],
                "missing_programmatic_evidence": row["missing_programmatic_evidence"],
                "content_hash": row["dossier_content_hash"],
                "review_template_preview": "",
            }
        )
    return {
        "p0_source_count": result["p0_source_count"],
        "all_deferred": all(item["status"] == "deferred" for item in sources),
        "all_downstream_none": all(
            item["downstream_eligibility"] == "none" for item in sources
        ),
        "sources": sources,
    }


def inspect_p0_intake(payload: Mapping[str, Any]) -> dict[str, Any]:
    """檢查一份 P0 intake JSON，回傳固定 13 列的唯讀診斷。"""

    _validate_intake_envelope(payload)
    raw_dossiers = payload["dossiers"]
    assert isinstance(raw_dossiers, list)

    by_source: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
    invalid_items: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_dossiers):
        if not isinstance(raw, Mapping):
            invalid_items.append(
                {"index": index, "source_id": None, "error": "dossier row must be an object"}
            )
            continue
        source_id = raw.get("source_id")
        source_text = source_id if isinstance(source_id, str) else None
        try:
            _validate_dossier_shape(raw)
        except (TypeError, ValueError) as error:
            invalid_items.append(
                {"index": index, "source_id": source_text, "error": str(error)}
            )
            continue
        assert isinstance(source_id, str)
        if source_id not in P0_SOURCE_IDS:
            invalid_items.append(
                {
                    "index": index,
                    "source_id": source_id,
                    "error": f"source_id outside authoritative P0 denominator: {source_id}",
                }
            )
            continue
        by_source.setdefault(source_id, []).append((index, raw))

    governance = SourceAcceptanceGovernance()
    rows: list[dict[str, Any]] = []
    for source_id in P0_SOURCE_IDS:
        entries = by_source.get(source_id, [])
        if not entries:
            rows.append(_missing_row(source_id, "dossier_not_supplied"))
            continue
        if len(entries) != 1:
            rows.append(_missing_row(source_id, "duplicate_source_id"))
            continue
        index, raw = entries[0]
        try:
            dossier = SourceAcceptanceDossier.from_dict(raw)
            diagnosis = governance.diagnose_dossier(dossier)
            decision_preview = governance.evaluate(dossier)
        except (TypeError, ValueError, KeyError, AttributeError) as error:
            invalid_items.append(
                {"index": index, "source_id": source_id, "error": str(error)}
            )
            rows.append(_missing_row(source_id, "invalid_dossier"))
            continue
        rows.append(
            {
                "source_id": source_id,
                "dossier_content_hash": dossier.content_hash,
                "checklist_complete": diagnosis.checklist_complete,
                "status": diagnosis.status,
                "ready_for_owner_review": diagnosis.checklist_complete,
                "missing_programmatic_evidence": list(diagnosis.missing_programmatic_evidence),
                "missing_authority_evidence": list(diagnosis.missing_authority_evidence),
                "active_blockers": list(diagnosis.active_blockers),
                "checklist": [dict(item) for item in diagnosis.checklist],
                "decision_preview": decision_preview.to_dict(),
                "downstream_eligibility": diagnosis.downstream_eligibility,
            }
        )

    supplied_ids = set(by_source)
    missing_ids = [source_id for source_id in P0_SOURCE_IDS if source_id not in supplied_ids]
    duplicate_ids = sorted(source_id for source_id, items in by_source.items() if len(items) > 1)
    ready_count = sum(bool(row["ready_for_owner_review"]) for row in rows)
    valid_count = sum(row["status"] == "deferred" for row in rows)
    deferred_count = sum(
        row["status"] == "deferred" and not row["ready_for_owner_review"] for row in rows
    )
    blockers: set[str] = {
        "p0_source_acceptance_pending",
        "downstream_eligibility_none",
        "formal_oos_disabled",
        "production_scheduler_disabled",
    }
    blockers.update(str(blocker) for row in rows for blocker in row.get("active_blockers", ()))
    blockers.update(f"missing_dossier:{source_id}" for source_id in missing_ids)
    blockers.update(f"duplicate_dossier:{source_id}" for source_id in duplicate_ids)
    blockers.update(f"invalid_dossier:{item['index']}" for item in invalid_items)

    invalid = bool(
        invalid_items
        or missing_ids
        or duplicate_ids
        or valid_count != len(P0_SOURCE_IDS)
    )
    if invalid:
        status = "invalid_input"
    elif ready_count == len(P0_SOURCE_IDS):
        status = "ready_for_owner_review"
    else:
        status = "deferred"
    return {
        "schema_version": P0_INTAKE_SCHEMA_VERSION,
        "status": status,
        "p0_source_count": len(P0_SOURCE_IDS),
        "supplied_dossier_count": len(raw_dossiers),
        "valid_dossier_count": valid_count,
        "invalid_dossier_count": len(invalid_items),
        "owner_review_ready_count": ready_count,
        "deferred_count": deferred_count,
        "missing_source_ids": missing_ids,
        "duplicate_source_ids": duplicate_ids,
        "invalid_items": invalid_items,
        "rows": rows,
        "global_blockers": sorted(blockers),
        "boundary": dict(_BOUNDARY),
        "input_payload_sha256": _payload_hash(payload),
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    """將 intake 診斷轉成 owner 可閱讀的摘要。"""

    lines = [
        "# P0 Source Intake Readiness",
        "",
        "> 唯讀 intake 診斷；`ready_for_owner_review` 不等於 accepted，也不授予下游資格。",
        "",
        f"- Status: `{payload.get('status', 'unknown')}`",
        f"- P0 sources: {payload.get('p0_source_count', 0)}",
        f"- Supplied / valid: {payload.get('supplied_dossier_count', 0)} / {payload.get('valid_dossier_count', 0)}",
        f"- Owner review ready: {payload.get('owner_review_ready_count', 0)}",
        f"- Deferred: {payload.get('deferred_count', 0)}",
        "- Boundary: read_only=true, writes_allowed=false, formal_oos_allowed=false, production_scheduler_allowed=false",
        "",
        "| Source | Status | Owner review | Programmatic gaps | Authority gaps | Blockers |",
        "|---|---|---|---|---|---|",
    ]
    rows = payload.get("rows", ())
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            programmatic = ", ".join(
                str(item) for item in row.get("missing_programmatic_evidence", ())
            ) or "None"
            authority = ", ".join(
                str(item) for item in row.get("missing_authority_evidence", ())
            ) or "None"
            blockers = ", ".join(str(item) for item in row.get("active_blockers", ())) or "None"
            lines.append(
                f"| `{row.get('source_id', 'unknown')}` | `{row.get('status', 'unknown')}` | "
                f"`{row.get('ready_for_owner_review', False)}` | {programmatic} | {authority} | {blockers} |"
            )
    lines.extend(["", "## Global blockers", ""])
    blockers = payload.get("global_blockers", ())
    if isinstance(blockers, list) and blockers:
        lines.extend(f"- {item}" for item in blockers)
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--input", type=Path, help="p0-source-intake.v1 JSON（唯讀）")
    mode.add_argument(
        "--template-output",
        type=Path,
        help="明確輸出的候選 dossier 範本；不含 evidence 或 acceptance",
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path, help="報告輸出路徑；未指定時輸出至 stdout")
    args = parser.parse_args(argv)

    if args.template_output is not None:
        if args.output is not None:
            parser.error("--template-output 與 --output 不可同時使用")
        try:
            _write_json_artifact(args.template_output, build_p0_intake_template())
        except (OSError, ValueError) as error:
            print(f"P0 intake template blocked: {error}", file=sys.stderr)
            return 2
        print(f"P0 intake template written: {args.template_output}")
        return 0

    assert args.input is not None
    try:
        payload = _read_json_object(args.input)
        result = inspect_p0_intake(payload)
        rendered = (
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
            if args.format == "json"
            else render_markdown(result)
        )
        if args.output is not None:
            _write_text_artifact(args.output, rendered)
        else:
            print(rendered, end="")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"P0 intake inspection blocked: {error}", file=sys.stderr)
        return 2
    return 0 if result["status"] != "invalid_input" else 2


def _validate_intake_envelope(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != P0_INTAKE_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported P0 intake schema: {payload.get('schema_version')}"
        )
    safety = payload.get("safety_flags")
    if not isinstance(safety, Mapping):
        raise ValueError("P0 intake safety_flags are required")
    for key, expected in _BOUNDARY.items():
        if safety.get(key) != expected:
            raise ValueError(f"P0 intake safety boundary mismatch: {key}")
    dossiers = payload.get("dossiers")
    if not isinstance(dossiers, list):
        raise ValueError("P0 intake dossiers must be an array")


def _validate_dossier_shape(raw: Mapping[str, Any]) -> None:
    unknown_keys = sorted(str(key) for key in raw if key not in _DOSSIER_KEYS)
    if unknown_keys:
        raise ValueError(f"dossier contains unsupported fields: {unknown_keys}")
    schema_version = raw.get("schema_version", _DOSSIER_SCHEMA_VERSION)
    if schema_version != _DOSSIER_SCHEMA_VERSION:
        raise ValueError(f"unsupported dossier schema: {schema_version}")
    for key in _SECRET_KEYS:
        if key in raw:
            raise ValueError(f"dossier contains forbidden secret-like field: {key}")
    for field_name in _REQUIRED_TEXT_FIELDS:
        value = raw.get(field_name)
        if not isinstance(value, str):
            raise TypeError(f"dossier field {field_name} must be a string")
    for field_name in _OPTIONAL_TEXT_FIELDS:
        if field_name in raw and not isinstance(raw[field_name], str):
            raise TypeError(f"dossier field {field_name} must be a string")
    for field_name in ("coverage_numerator", "coverage_denominator"):
        value = raw.get(field_name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"dossier field {field_name} must be an integer")
    for field_name in _COLLECTION_FIELDS:
        values = raw.get(field_name, ())
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise TypeError(f"dossier field {field_name} must be an array of strings")
        if any(not isinstance(value, str) for value in values):
            raise TypeError(f"dossier field {field_name} must contain strings")
    row_counts = raw.get("row_conservation_counts")
    if not isinstance(row_counts, Mapping):
        raise TypeError("dossier field row_conservation_counts must be an object")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in row_counts.values()
    ):
        raise ValueError("row_conservation_counts must contain non-negative integers")
    thresholds = raw.get("quality_thresholds")
    if not isinstance(thresholds, Mapping):
        raise TypeError("dossier field quality_thresholds must be an object")
    if raw.get("downstream_eligibility") != "none":
        raise ValueError("dossier downstream_eligibility must remain none")
    if raw.get("source_id") not in P0_SOURCE_IDS:
        raise ValueError(f"source_id outside authoritative P0 denominator: {raw.get('source_id')}")


def _missing_row(source_id: str, blocker: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "dossier_content_hash": None,
        "checklist_complete": False,
        "status": "invalid_input",
        "ready_for_owner_review": False,
        "missing_programmatic_evidence": [],
        "missing_authority_evidence": [],
        "active_blockers": [blocker],
        "checklist": [],
        "decision_preview": None,
        "downstream_eligibility": "none",
    }


def _payload_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"


def _read_json_object(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return payload


def _write_json_artifact(path: Path, payload: Mapping[str, Any]) -> None:
    _require_non_production_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_text_artifact(path: Path, rendered: str) -> None:
    _require_non_production_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def _require_non_production_output(path: Path) -> None:
    production_root = Path(os.environ.get("DATA_ROOT", _PRODUCTION_DEFAULT)).resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(production_root)
    except ValueError:
        return
    raise ValueError("output must remain outside DATA_ROOT")


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            continue


if __name__ == "__main__":
    raise SystemExit(main())
