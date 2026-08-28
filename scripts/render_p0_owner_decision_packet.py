"""Render an existing P0 evidence audit as a bounded owner-review packet.

The renderer is deliberately read-only: it consumes a previously captured
``p0-source-evidence-audit.v1`` JSON artifact and produces a human-readable
summary of the five grouped owner questions.  It never infers an acceptance
decision, changes downstream eligibility, or opens a registry/database.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


AUDIT_SCHEMA_VERSION = "p0-source-evidence-audit.v1"
_PRODUCTION_DEFAULT = "D:/Min/Python/Project/FA_Data"


def render_owner_decision_packet(payload: Mapping[str, Any]) -> str:
    """Render grouped owner questions without exposing raw rows."""

    _validate_audit_payload(payload)
    summary = payload.get("machine_vs_owner_blocker_summary")
    assert isinstance(summary, Mapping)
    safety = payload.get("safety_flags")
    assert isinstance(safety, Mapping)
    groups = payload["grouped_owner_decision_packet"]
    assert isinstance(groups, list)
    machine_matrix = payload.get("machine_evidence_matrix")
    machine_by_source = {
        str(item.get("source_id")): item
        for item in machine_matrix
        if isinstance(item, Mapping) and str(item.get("source_id") or "").strip()
    } if isinstance(machine_matrix, list) else {}

    lines = [
        "# P0 Owner Decision Packet",
        "",
        "> 唯讀人工審查包；本文件只整理既有 machine evidence，不代表任何來源已 accepted 或 limited。",
        "",
        f"- Schema: `{AUDIT_SCHEMA_VERSION}`",
        f"- Decision date: `{payload.get('decision_date', 'unknown')}`",
        f"- Machine sources: `{summary.get('total_sources', 'unknown')}`",
        f"- Machine verified / degraded / missing: `{summary.get('machine_verified_sources', 0)} / {summary.get('degraded_sources', 0)} / {summary.get('missing_sources', 0)}`",
        f"- Grouped owner questions: `{len(groups)}`",
        f"- Human decision: `{safety.get('human_decision', 'requires_human_acceptance')}`",
        "- Boundary: `formal_oos_allowed=false`, `production_allowed=false`, `scheduler_allowed=false`, `downstream_eligibility=none`",
        "",
        "## Owner 回覆規則",
        "",
        "每組只需由具名 Owner／License reviewer 回覆內部研究用途、授權範圍、公開／再散布限制、PIT／coverage 證據與 rollback reference。未具名、缺 evidence 或仍有 blocker 時，系統必須維持 deferred／blocked；本工具不會代填決議。",
        "",
    ]

    for index, raw_group in enumerate(groups, start=1):
        if not isinstance(raw_group, Mapping):
            continue
        group_id = str(raw_group.get("group_id") or f"group-{index}")
        title = str(raw_group.get("title") or group_id)
        provider = str(raw_group.get("provider") or "未提供")
        covered = raw_group.get("covered_source_ids")
        covered_ids = [str(item) for item in covered] if isinstance(covered, list) else []
        status = raw_group.get("group_status_summary")
        status_map = status if isinstance(status, Mapping) else {}

        lines.extend(
            [
                f"## {index}. {title}",
                "",
                f"- `group_id`: `{group_id}`",
                f"- Provider: {provider}",
                f"- Sources: {', '.join(f'`{item}`' for item in covered_ids) or '未提供'}",
                "- Machine status: "
                f"verified={status_map.get('verified_sources', 0)}, "
                f"degraded={status_map.get('degraded_sources', 0)}, "
                f"missing={status_map.get('missing_sources', 0)}",
                "",
                f"**Owner question**：{raw_group.get('owner_question', '未提供')}",
                "",
            ]
        )

        machine_items = [
            machine_by_source[source_id]
            for source_id in covered_ids
            if source_id in machine_by_source
        ]
        if machine_items:
            lines.extend(
                [
                    "**Machine route evidence（唯讀）**",
                    "",
                    "| Source | Actual／candidate routes | Fallback | Probe／availability | PIT／timestamp | HTTP headers（唯讀） | Rows raw／accepted／blocked | License URL(s) |",
                    "|---|---|---|---|---|---|---:|---|",
                ]
            )
            for machine_item in machine_items:
                route_cells = _machine_route_cells(machine_item)
                fallback_attempted = machine_item.get("fallback_attempted")
                if fallback_attempted is None:
                    fallback_attempted = machine_item.get("fallback_used")
                fallback_label = (
                    "attempted"
                    if fallback_attempted is True
                    else "not_used"
                    if fallback_attempted is False
                    else "unknown"
                )
                rows = (
                    f"{machine_item.get('raw_row_count', 0)} / "
                    f"{machine_item.get('accepted_row_count', 0)} / "
                    f"{machine_item.get('blocked_row_count', 0)}"
                )
                lines.append(
                    f"| `{_markdown_cell(machine_item.get('source_id', 'unknown'))}` | "
                    f"{_markdown_cell('<br>'.join(route_cells) or '未提供')} | "
                    f"`{fallback_label}` | "
                    f"`{_markdown_cell(machine_item.get('probe_outcome', 'unknown'))}` / "
                    f"`{_markdown_cell(machine_item.get('availability', 'unknown'))}` | "
                    f"`{_markdown_cell(machine_item.get('pit_status', 'unknown'))}` / "
                    f"`{_markdown_cell(machine_item.get('timestamp_kind', 'unknown'))}` | "
                    f"{_markdown_cell('<br>'.join(_machine_http_headers(machine_item)) or '未提供')} | "
                    f"`{_markdown_cell(rows)}` | "
                    f"{_markdown_cell('<br>'.join(_machine_license_urls(machine_item)) or '待補')} |"
                )
            lines.append("")

        recommendations = raw_group.get("source_recommendations")
        if isinstance(recommendations, list) and recommendations:
            lines.extend(
                [
                    "| Source | Machine recommendation | Timestamp class | Machine blockers | Human blockers |",
                    "|---|---|---|---|---|",
                ]
            )
            for raw_recommendation in recommendations:
                if not isinstance(raw_recommendation, Mapping):
                    continue
                machine_blockers = ", ".join(
                    str(item) for item in raw_recommendation.get("machine_blockers", [])
                ) or "None"
                human_blockers = ", ".join(
                    str(item) for item in raw_recommendation.get("human_blockers", [])
                ) or "None"
                lines.append(
                    f"| `{raw_recommendation.get('source_id', 'unknown')}` | "
                    f"`{raw_recommendation.get('machine_recommendation', 'deferred')}` | "
                    f"`{raw_recommendation.get('timestamp_evidence_class', 'unknown')}` | "
                    f"{machine_blockers} | {human_blockers} |"
                )
            lines.append("")

        lines.extend(
            [
                "**人工填寫欄位**",
                "",
                "- Owner decision: `deferred` / `rejected` / `disabled`，或依完整 governance 流程提出 `limited` / `accepted`。",
                "- Source owner / license reviewer: `待填`",
                "- License／quality／PIT evidence IDs: `待填`",
                "- Effective scope／再散布限制／rollback reference: `待填`",
                "",
            ]
        )

    lines.extend(
        [
            "## 固定安全邊界",
            "",
            "即使完成這份 packet，也不會自動寫入 SourceAcceptanceDecisionRegistry、正式 SQLite、Formal input、Scoring、Advice、Portfolio、scheduler 或 broker。",
            "",
        ]
    )
    return "\n".join(lines)


def _validate_audit_payload(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != AUDIT_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported P0 audit schema: {payload.get('schema_version')}"
        )
    groups = payload.get("grouped_owner_decision_packet")
    if not isinstance(groups, list) or not groups or len(groups) > 5:
        raise ValueError("P0 audit grouped owner packet must contain 1..5 groups")
    summary = payload.get("machine_vs_owner_blocker_summary")
    if not isinstance(summary, Mapping):
        raise ValueError("P0 audit machine blocker summary is required")
    safety = payload.get("safety_flags")
    if not isinstance(safety, Mapping):
        raise ValueError("P0 audit safety_flags are required")
    expected_false = (
        "formal_oos_allowed",
        "formal_evidence_credit_authorized",
        "production_allowed",
        "training_allowed",
        "promotion_allowed",
        "scheduler_allowed",
        "unblind_allowed",
    )
    for key in expected_false:
        if safety.get(key) is not False:
            raise ValueError(f"P0 audit safety boundary must remain false: {key}")
    if safety.get("production_blend_alpha_bp") != 0:
        raise ValueError("P0 audit production_blend_alpha_bp must remain zero")
    if safety.get("downstream_eligibility") != "none":
        raise ValueError("P0 audit downstream_eligibility must remain none")


def _markdown_cell(value: object) -> str:
    """Keep machine-provided packet cells on one safe Markdown table row."""

    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _machine_route_cells(machine_item: Mapping[str, Any]) -> list[str]:
    routes = machine_item.get("acquisition_routes")
    cells: list[str] = []
    if isinstance(routes, list):
        for route in routes:
            if not isinstance(route, Mapping):
                continue
            route_id = str(route.get("route_id") or "").strip()
            if not route_id:
                continue
            provider = str(route.get("provider") or "").strip()
            endpoint = str(route.get("endpoint") or "").strip()
            label = route_id
            if provider:
                label += f" ({provider})"
            if endpoint:
                label += f" — {endpoint}"
            cell = _markdown_cell(label)
            if cell not in cells:
                cells.append(cell)
    actual_route = str(machine_item.get("acquisition_route_id") or "").strip()
    if actual_route and not any(actual_route in cell for cell in cells):
        cells.insert(0, _markdown_cell(actual_route))
    return cells


def _machine_license_urls(machine_item: Mapping[str, Any]) -> list[str]:
    routes = machine_item.get("acquisition_routes")
    urls: list[str] = []
    if isinstance(routes, list):
        for route in routes:
            if not isinstance(route, Mapping):
                continue
            url = str(route.get("license_evidence_url") or "").strip()
            if url and url not in urls:
                urls.append(url)
    return urls


def _machine_http_headers(machine_item: Mapping[str, Any]) -> list[str]:
    """Render bounded transport headers without treating them as PIT proof."""

    labels = (
        ("Date", "http_date"),
        ("Last-Modified", "last_modified"),
        ("ETag", "etag"),
        ("Content-Type", "content_type"),
    )
    values: list[str] = []
    for label, field_name in labels:
        value = str(machine_item.get(field_name) or "").strip()
        if value:
            values.append(_markdown_cell(f"{label}={value}"))
    if values:
        return values
    return ["headers_missing; never_publication"]


def _require_non_production_output(path: Path) -> None:
    production_root = Path(os.environ.get("DATA_ROOT", _PRODUCTION_DEFAULT)).resolve()
    try:
        path.resolve().relative_to(production_root)
    except ValueError:
        return
    raise ValueError("output must remain outside DATA_ROOT")


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="既有 p0-source-evidence-audit.v1 JSON")
    parser.add_argument("--output", type=Path, help="非正式輸出的 Markdown 路徑；未指定時輸出 stdout")
    args = parser.parse_args(argv)

    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("P0 audit JSON root must be an object")
        rendered = render_owner_decision_packet(payload)
        if args.output is None:
            print(rendered, end="")
        else:
            _require_non_production_output(args.output)
            if args.output.resolve() == args.input.resolve():
                raise ValueError("output must differ from input audit artifact")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"P0 owner packet rendering blocked: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
