"""驗證並彙整 MOPS 季報 candidate 的隔離 consumer 批次結果。

此工具讀取已完成的 batch／child manifest 與 adapter materialization receipt，
重新核對 child raw hash、candidate hash、SQLite 唯讀 quick_check、首次／重跑
冪等性及 date-only cutoff，最後只在 research output 建立一份新的摘要。它不
抓取網路、不寫入 SQLite，也不會把 failed 或 pending 公司算成完成。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.mops_statement_candidate_adapter import (
    _resolve_report_basis,
    validate_research_output_path,
)
from scripts.materialize_mops_statement_candidates import _universe_plan_sources
from scripts.plan_mops_statement_universe import (
    _load_supersession_records,
    _verify_child_artifacts,
    load_universe_plan,
)


_SUMMARY_SCHEMA_VERSION = "v4-quarterly-mops-consumer-batch-summary.v1"
_MATERIALIZATION_SCHEMA_VERSION = "v4-quarterly-isolated-materialization-evidence.v1"
_BATCH_SCHEMA_VERSION = "mops-statement-pit-batch-manifest.v2"
_CHILD_SCHEMA_VERSIONS = frozenset(
    {"mops-statement-pit-run-manifest.v1", "mops-statement-pit-run-manifest.v2"}
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _optional_count(value: object, *, field_name: str) -> int | None:
    """讀取 universe 計數；拒絕布林或其他未經驗證的型別。"""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"universe count {field_name} must be an integer")
    return value


def _resolved_regular_file(path: Path, *, description: str) -> Path:
    requested = Path(path).expanduser()
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    resolved = requested.resolve(strict=False)
    if (
        requested.is_symlink()
        or not requested.is_file()
        or resolved != requested
    ):
        raise ValueError(f"{description} must be a regular non-alias file")
    return resolved


def _sha256_reference(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _load_object(path: Path, *, description: str) -> dict[str, Any]:
    resolved = _resolved_regular_file(path, description=description)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{description} is not valid UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{description} must be a JSON object")
    return payload


def _period_from_candidate(candidate_path: Path) -> str:
    candidate = _load_object(candidate_path, description="candidate")
    summary = candidate.get("pit_coverage_summary")
    if not isinstance(summary, Mapping) or not isinstance(summary.get("period"), str):
        raise ValueError("candidate pit_coverage_summary.period is missing")
    return str(summary["period"])


def _verify_child(
    candidate_path: Path,
    manifest_path: Path,
    *,
    expected_period: str,
    origin: str,
) -> dict[str, Any]:
    candidate = _resolved_regular_file(candidate_path, description="candidate")
    manifest = _resolved_regular_file(manifest_path, description="child manifest")
    details = _verify_child_artifacts(
        candidate,
        manifest,
        expected_period=expected_period,
    )
    candidate_payload = _load_object(candidate, description="candidate")
    manifest_payload = _load_object(manifest, description="child manifest")
    manifest_files = manifest_payload.get("files")
    raw_file_count = (
        sum(
            1
            for name in manifest_files
            if isinstance(name, str) and name.startswith("raw_")
        )
        if isinstance(manifest_files, Mapping)
        else 0
    )
    raw_files = manifest_payload.get("raw_files")
    if isinstance(raw_files, Mapping):
        raw_file_count += len(raw_files)
    source_version = candidate_payload.get("source_version")
    if not isinstance(source_version, str) or not source_version.strip():
        raise ValueError("candidate source_version is missing")
    report_basis = _resolve_report_basis(
        candidate_payload,
        source_version=source_version,
        label="candidate",
    )
    return {
        "origin": origin,
        "stock_code": details["stock_code"],
        "registry_market": details["registry_market"],
        "batch_market": details["batch_market"],
        "period": details["period"],
        "candidate_path": str(candidate),
        "candidate_sha256": details["candidate_sha256"],
        "manifest_path": str(manifest),
        "manifest_sha256": details["manifest_sha256"],
        "candidate_row_count": int(details["candidate_row_count"]),
        "raw_file_count": raw_file_count,
        "source_version": source_version,
        "report_basis": report_basis,
    }


def _validate_batch_manifest(
    path: Path,
    *,
    expected_period: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    resolved = _resolved_regular_file(path, description="batch manifest")
    payload = _load_object(resolved, description="batch manifest")
    if payload.get("schema_version") != _BATCH_SCHEMA_VERSION:
        raise ValueError("consumer summary accepts only the v2 batch manifest")
    if payload.get("research_only") is not True or payload.get("formal_oos_allowed") is not False:
        raise ValueError("batch manifest must remain research_only and formal_oos disallowed")
    child_runs = payload.get("child_runs")
    if not isinstance(child_runs, list):
        raise ValueError("batch manifest child_runs must be a list")
    completed: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    for child in child_runs:
        if not isinstance(child, Mapping):
            raise ValueError("batch manifest child must be an object")
        status = child.get("status")
        stock_code = child.get("stock_code")
        market = child.get("market")
        period = child.get("period")
        run_id = child.get("run_id")
        if not all(isinstance(value, str) and value.strip() for value in (stock_code, market, period, run_id)):
            raise ValueError("batch manifest child identity is incomplete")
        if period != expected_period:
            raise ValueError("batch manifest child period does not match the summary scope")
        if status == "succeeded":
            candidate_value = child.get("candidate")
            manifest_value = child.get("manifest")
            if not isinstance(candidate_value, str) or not isinstance(manifest_value, str):
                raise ValueError("succeeded child is missing candidate or manifest path")
            details = _verify_child(
                Path(candidate_value),
                Path(manifest_value),
                expected_period=expected_period,
                origin=str(resolved),
            )
            if details["stock_code"] != stock_code or details["batch_market"] != market:
                raise ValueError("succeeded child identity does not match its batch row")
            child_basis = str(child.get("report_basis", "consolidated"))
            if details["report_basis"] != child_basis:
                raise ValueError("succeeded child report basis does not match its batch row")
            for field in ("candidate_sha256", "manifest_sha256"):
                stored = child.get(field)
                if stored is not None and stored != details[field]:
                    raise ValueError(f"batch child {field} changed after completion")
            completed.append(details)
            continue
        if status not in {"pending", "running", "failed", "integrity_error"}:
            raise ValueError("batch manifest contains an unknown child status")
        attempts = child.get("attempts")
        if attempts is not None and not isinstance(attempts, list):
            raise ValueError("incomplete child attempts must be a list")
        incomplete.append(
            {
                "origin": str(resolved),
                "stock_code": stock_code,
                "market": market,
                "period": period,
                "run_id": run_id,
                "status": status,
                "attempts": len(attempts) if isinstance(attempts, list) else 0,
                "error": (
                    attempts[-1].get("error")
                    if isinstance(attempts, list)
                    and attempts
                    and isinstance(attempts[-1], Mapping)
                    else None
                ),
                "failure_source": (
                    attempts[-1].get("failure_source")
                    if isinstance(attempts, list)
                    and attempts
                    and isinstance(attempts[-1], Mapping)
                    else None
                ),
            }
        )
    return (
        {
            "path": str(resolved),
            "sha256": _sha256_reference(resolved),
            "request_count": payload.get("request_count"),
            "status": payload.get("status"),
            "succeeded_count": payload.get("succeeded_count"),
            "failed_count": payload.get("failed_count"),
            "pending_count": payload.get("pending_count"),
        },
        completed,
        incomplete,
    )


def _validate_child_manifest(
    path: Path,
    *,
    expected_period: str,
) -> dict[str, Any]:
    resolved = _resolved_regular_file(path, description="child manifest")
    payload = _load_object(resolved, description="child manifest")
    if payload.get("schema_version") not in _CHILD_SCHEMA_VERSIONS:
        raise ValueError("child manifest schema is unsupported")
    if payload.get("research_only") is not True or payload.get("formal_oos_allowed") is not False:
        raise ValueError("child manifest must remain research_only and formal disallowed")
    candidate = resolved.parent / "statement-pit-candidate.json"
    candidate_period = _period_from_candidate(candidate)
    if candidate_period != expected_period:
        raise ValueError("child candidate period does not match the summary scope")
    details = _verify_child(
        candidate,
        resolved,
        expected_period=expected_period,
        origin=str(resolved),
    )
    if payload.get("run_id") is not None and payload.get("run_id") != candidate.parent.name:
        raise ValueError("child manifest run_id does not match its directory")
    return details


def _deduplicate_children(children: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for child in children:
        key = (str(child["stock_code"]), str(child["batch_market"]), str(child["period"]))
        previous = by_key.get(key)
        if previous is not None:
            if previous["candidate_sha256"] != child["candidate_sha256"]:
                raise ValueError(
                    "multiple completed revisions exist for one company/period; "
                    "consumer summary requires an explicit revision decision"
                )
            continue
        by_key[key] = child
    return {str(item["candidate_path"]): item for item in by_key.values()}


def _apply_supersession_records(
    children: list[dict[str, Any]],
    paths: list[Path],
    *,
    expected_period: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """將 immutable replacement 套到摘要輸入，保留舊 child 但不再計完成。"""

    corrections = _load_supersession_records(
        paths,
        expected_period=expected_period,
    )
    if not corrections:
        return children, []
    current = list(children)
    summaries: list[dict[str, Any]] = []
    for correction in corrections:
        target_key = (
            str(correction["stock_code"]),
            str(correction["batch_market"]),
            str(correction["period"]),
        )
        old_hash = str(correction["superseded"]["candidate_sha256"])
        replacement = correction["replacement"]
        new_hash = str(replacement["candidate_sha256"])
        retained: list[dict[str, Any]] = []
        found_replacement = False
        for child in current:
            child_key = (
                str(child["stock_code"]),
                str(child["batch_market"]),
                str(child["period"]),
            )
            child_hash = str(child["candidate_sha256"])
            if child_key != target_key:
                retained.append(child)
                continue
            if child_hash == old_hash:
                # 舊 candidate 仍在 immutable storage，只從目前完成集合移除。
                continue
            if child_hash != new_hash:
                raise ValueError(
                    "supersession record conflicts with a completed child: "
                    f"{target_key[0]}:{target_key[1]}"
                )
            found_replacement = True
            retained.append(child)
        if not found_replacement:
            replacement_details = _verify_child(
                Path(str(replacement["candidate_path"])),
                Path(str(replacement["manifest_path"])),
                expected_period=expected_period,
                origin=str(correction["record_path"]),
            )
            if replacement_details["candidate_sha256"] != new_hash:
                raise ValueError("supersession replacement hash changed")
            retained.append(replacement_details)
        current = retained
        summaries.append(
            {
                "record_path": correction["record_path"],
                "record_sha256": correction["record_sha256"],
                "stock_code": correction["stock_code"],
                "registry_market": correction["registry_market"],
                "period": correction["period"],
                "supersedes_candidate_sha256": old_hash,
                "replacement_candidate_sha256": new_hash,
                "reason": correction["reason"],
            }
        )
    return current, summaries


def _validate_marker(marker_path: Path, db_path: Path) -> tuple[Path, str]:
    marker = _resolved_regular_file(marker_path, description="SQLite isolation marker")
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("SQLite isolation marker is unreadable") from error
    if not isinstance(payload, Mapping):
        raise ValueError("SQLite isolation marker must be an object")
    marker_db = payload.get("db_path")
    if not isinstance(marker_db, str) or Path(marker_db).expanduser().resolve(strict=False) != db_path:
        raise ValueError("SQLite isolation marker targets another database")
    if payload.get("research_only") is not True or payload.get("formal_oos_allowed") is not False:
        raise ValueError("SQLite isolation marker must remain research-only")
    return marker, _sha256_reference(marker)


def _read_only_database_summary(
    db_path: Path,
    *,
    candidate_paths: set[Path],
) -> dict[str, Any]:
    resolved_db = _resolved_regular_file(db_path, description="isolated SQLite database")
    validate_research_output_path(
        resolved_db,
        conflicts=tuple(candidate_paths),
        allow_existing=True,
    )
    marker, marker_sha = _validate_marker(
        resolved_db.with_name(resolved_db.name + ".research-only.json"),
        resolved_db,
    )
    uri = f"file:{resolved_db.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        quick_check_row = connection.execute("PRAGMA quick_check").fetchone()
        quick_check = str(quick_check_row[0]) if quick_check_row else ""
        if quick_check != "ok":
            raise ValueError(f"isolated SQLite quick_check failed: {quick_check}")
        main_count = int(
            connection.execute("SELECT COUNT(*) FROM fundamental_statement_items").fetchone()[0]
        )
        sidecar_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM mops_statement_consumer_metadata"
            ).fetchone()[0]
        )
        eps_rows = [
            {
                "stock_code": str(row[0]),
                "item_code": str(row[1]),
                "value": str(row[2]),
                "value_unit": str(row[3]),
                "value_scale": int(row[4]),
                "period_basis": str(row[5]),
                "available_date": str(row[6]),
            }
            for row in connection.execute(
                """
                SELECT stock_code, item_code, value, value_unit, value_scale,
                       period_basis, available_date
                FROM mops_statement_consumer_metadata
                WHERE item_code IN ('9750', '9810')
                ORDER BY stock_code, item_code
                """
            ).fetchall()
        ]
    finally:
        connection.close()
    return {
        "path": str(resolved_db),
        "sha256": _sha256_reference(resolved_db),
        "marker_path": str(marker),
        "marker_sha256": marker_sha,
        "quick_check": quick_check,
        "main_count": main_count,
        "sidecar_count": sidecar_count,
        "eps_rows": eps_rows,
    }


def _validate_materialization_report(
    path: Path,
    *,
    label: str,
    expected_children: Mapping[str, dict[str, Any]],
    hidden_date: str,
    visible_date: str,
    first: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = _resolved_regular_file(path, description=f"materialization {label} receipt")
    payload = _load_object(resolved, description=f"materialization {label} receipt")
    if payload.get("schema_version") != _MATERIALIZATION_SCHEMA_VERSION:
        raise ValueError(f"materialization {label} receipt schema is unsupported")
    if payload.get("formal_db_written") is not False or payload.get("raw_data_modified") is not False:
        raise ValueError(f"materialization {label} receipt is not research-only")
    raw_paths = payload.get("candidate_paths")
    raw_hashes = payload.get("candidate_sha256")
    if not isinstance(raw_paths, list) or not isinstance(raw_hashes, Mapping):
        raise ValueError(f"materialization {label} candidate lineage is incomplete")
    actual_children: dict[str, dict[str, Any]] = {}
    total_rows = 0
    for raw_path in raw_paths:
        if not isinstance(raw_path, str):
            raise ValueError(f"materialization {label} candidate path is malformed")
        candidate = _resolved_regular_file(Path(raw_path), description="materialization candidate")
        key = str(candidate)
        details = expected_children.get(key)
        if details is None:
            raise ValueError(f"materialization {label} contains an unverified candidate")
        stored_hash = raw_hashes.get(raw_path)
        if stored_hash is None:
            stored_hash = raw_hashes.get(key)
        if stored_hash != details["candidate_sha256"] or _sha256_reference(candidate) != stored_hash:
            raise ValueError(f"materialization {label} candidate hash does not match child evidence")
        actual_children[key] = details
        total_rows += int(details["candidate_row_count"])
    if set(actual_children) != set(expected_children):
        raise ValueError(f"materialization {label} candidate set does not match completed children")
    if payload.get("input_row_count") != total_rows or payload.get("unique_input_row_count") != total_rows:
        raise ValueError(f"materialization {label} row denominator does not match candidates")
    if payload.get("duplicate_input_row_count") != 0:
        raise ValueError(f"materialization {label} contains duplicate input rows")
    if payload.get("materialized_row_count") != total_rows or payload.get("sidecar_row_count") != total_rows:
        raise ValueError(f"materialization {label} SQLite counts do not match candidates")
    if first:
        if payload.get("inserted_row_count") != total_rows or payload.get("idempotent_existing_row_count") != 0:
            raise ValueError("first materialization receipt does not prove a new insert")
    else:
        if payload.get("inserted_row_count") != 0 or payload.get("idempotent_existing_row_count") != total_rows:
            raise ValueError("retry materialization receipt does not prove idempotence")

    by_date = payload.get("provider_visible_rows_by_decision_date")
    by_stock_date = payload.get("provider_visible_rows_by_stock_date")
    if not isinstance(by_date, Mapping) or not isinstance(by_stock_date, Mapping):
        raise ValueError(f"materialization {label} provider cutoff evidence is incomplete")
    if by_date.get(hidden_date) != 0 or by_date.get(visible_date) != total_rows:
        raise ValueError(f"materialization {label} date-only cutoff is inconsistent")
    visible_by_stock = by_stock_date.get(visible_date)
    hidden_by_stock = by_stock_date.get(hidden_date)
    if not isinstance(visible_by_stock, Mapping) or not isinstance(hidden_by_stock, Mapping):
        raise ValueError(f"materialization {label} per-stock cutoff evidence is incomplete")
    expected_by_stock: dict[str, int] = {}
    for details in expected_children.values():
        stock = str(details["stock_code"])
        expected_by_stock[stock] = expected_by_stock.get(stock, 0) + int(details["candidate_row_count"])
    for stock, count in expected_by_stock.items():
        if visible_by_stock.get(stock) != count or hidden_by_stock.get(stock) != 0:
            raise ValueError(f"materialization {label} cutoff mismatch for stock {stock}")

    db_value = payload.get("db_path")
    if not isinstance(db_value, str):
        raise ValueError(f"materialization {label} database path is missing")
    db_summary = _read_only_database_summary(
        Path(db_value),
        candidate_paths={Path(key) for key in expected_children},
    )
    receipt = {
        "path": str(resolved),
        "sha256": _sha256_reference(resolved),
        "input_row_count": total_rows,
        "inserted_row_count": payload.get("inserted_row_count"),
        "idempotent_existing_row_count": payload.get("idempotent_existing_row_count"),
        "provider_visible_rows_by_decision_date": {
            str(hidden_date): by_date[hidden_date],
            str(visible_date): by_date[visible_date],
        },
        "db_path": db_summary["path"],
        "db_sha256": db_summary["sha256"],
    }
    return receipt, db_summary


def _build_summary(args: argparse.Namespace) -> dict[str, Any]:
    period = str(args.period)
    batch_manifest_paths = tuple(args.batch_manifest)
    child_manifest_paths = tuple(args.child_manifest)
    supersession_paths = tuple(args.supersession_record)
    if args.universe_plan is not None:
        if batch_manifest_paths or child_manifest_paths or supersession_paths:
            raise ValueError(
                "--universe-plan cannot be combined with explicit manifest inputs"
            )
        (
            batch_manifest_paths,
            child_manifest_paths,
            supersession_paths,
            _plan_source_summary,
        ) = _universe_plan_sources(
            args.universe_plan,
            expected_period=period,
        )
    batch_inputs: list[dict[str, Any]] = []
    completed_children: list[dict[str, Any]] = []
    incomplete_children: list[dict[str, Any]] = []
    for path in batch_manifest_paths:
        batch, completed, incomplete = _validate_batch_manifest(path, expected_period=period)
        batch_inputs.append(batch)
        completed_children.extend(completed)
        incomplete_children.extend(incomplete)
    for path in child_manifest_paths:
        completed_children.append(
            _validate_child_manifest(path, expected_period=period)
        )
    completed_children, correction_summaries = _apply_supersession_records(
        completed_children,
        list(supersession_paths),
        expected_period=period,
    )
    children = _deduplicate_children(completed_children)
    if not children:
        raise ValueError("consumer summary requires at least one completed child")

    universe_summary: dict[str, Any] | None = None
    if args.universe_plan is not None:
        plan_path = _resolved_regular_file(args.universe_plan, description="universe plan")
        plan = load_universe_plan(plan_path)
        if plan.get("scope", {}).get("period") != period:
            raise ValueError("universe plan period does not match the summary scope")
        scope = plan.get("scope")
        if not isinstance(scope, Mapping):
            raise ValueError("universe plan scope is malformed")
        universe_summary = {
            "path": str(plan_path),
            "sha256": _sha256_reference(plan_path),
            "plan_id": plan.get("plan_id"),
            "eligible_company_count": scope.get("eligible_company_count"),
            "verified_completed_company_count": scope.get("verified_completed_company_count"),
            "deferred_unresolved_company_count": scope.get(
                "deferred_unresolved_company_count",
                scope.get("caller_excluded_company_count"),
            ),
            "total_unfinished_company_count": scope.get(
                "total_unfinished_company_count",
                scope.get("unprocessed_eligible_company_count"),
            ),
            "remaining_selectable_company_count": scope.get("remaining_selectable_company_count"),
            "selected_company_count": scope.get("selected_company_count"),
            "selected_requests": plan.get("requests"),
        }

    first_receipt, first_db = _validate_materialization_report(
        args.materialization_first,
        label="first",
        expected_children=children,
        hidden_date=args.hidden_decision_date,
        visible_date=args.visible_decision_date,
        first=True,
    )
    retry_receipt, retry_db = _validate_materialization_report(
        args.materialization_retry,
        label="retry",
        expected_children=children,
        hidden_date=args.hidden_decision_date,
        visible_date=args.visible_decision_date,
        first=False,
    )
    if first_db["path"] != retry_db["path"] or first_db["sha256"] != retry_db["sha256"]:
        raise ValueError("first/retry receipts do not point to the same final SQLite identity")
    if first_receipt["db_sha256"] != first_db["sha256"] or retry_receipt["db_sha256"] != retry_db["sha256"]:
        raise ValueError("materialization receipt database hash is inconsistent")

    ordered_children = [
        {
            **details,
            "candidate_row_count": int(details["candidate_row_count"]),
        }
        for details in sorted(
            children.values(),
            key=lambda item: (str(item["batch_market"]), str(item["stock_code"])),
        )
    ]
    total_rows = sum(int(item["candidate_row_count"]) for item in ordered_children)
    completed_count = len(ordered_children)
    eligible_count = _optional_count(
        universe_summary.get("eligible_company_count") if universe_summary else None,
        field_name="eligible_company_count",
    )
    remaining_count = _optional_count(
        universe_summary.get("remaining_selectable_company_count")
        if universe_summary
        else None,
        field_name="remaining_selectable_company_count",
    )
    deferred_count = _optional_count(
        universe_summary.get("deferred_unresolved_company_count")
        if universe_summary
        else None,
        field_name="deferred_unresolved_company_count",
    )
    unfinished_count = _optional_count(
        universe_summary.get("total_unfinished_company_count")
        if universe_summary
        else None,
        field_name="total_unfinished_company_count",
    )
    verified_count = _optional_count(
        universe_summary.get("verified_completed_company_count")
        if universe_summary
        else None,
        field_name="verified_completed_company_count",
    )
    if (
        eligible_count is not None
        and verified_count is not None
        and remaining_count is not None
        and deferred_count is not None
        and unfinished_count is not None
    ):
        if unfinished_count != deferred_count + remaining_count:
            raise ValueError("universe summary unfinished/deferred/selectable denominator mismatch")
        if unfinished_count != eligible_count - verified_count:
            raise ValueError("universe summary unfinished denominator does not match verified count")
    coverage: dict[str, Any] = {
        "completed_company_count": completed_count,
        "candidate_row_count": total_rows,
        "materialized_main_count": first_db["main_count"],
        "materialized_sidecar_count": first_db["sidecar_count"],
        "eligible_company_count": eligible_count,
        "remaining_selectable_company_count": remaining_count,
        "scope_statement": "completed children are a bounded research slice; remaining universe is not restored",
    }
    if universe_summary is not None:
        coverage.update(
            {
                "verified_completed_company_count": universe_summary.get(
                    "verified_completed_company_count"
                ),
                "deferred_unresolved_company_count": deferred_count,
                "total_unfinished_company_count": unfinished_count,
            }
        )
    return {
        "schema_version": _SUMMARY_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "period": period,
        "research_only": True,
        "formal_db_written": False,
        "raw_data_modified": False,
        "batch_manifests": batch_inputs,
        "child_manifests": [
            {
                "path": str(_resolved_regular_file(path, description="child manifest")),
                "sha256": _sha256_reference(
                    _resolved_regular_file(path, description="child manifest")
                ),
            }
            for path in child_manifest_paths
        ],
        "artifact_corrections": correction_summaries,
        "universe_plan": universe_summary,
        "completed_children": ordered_children,
        "incomplete_children": sorted(
            incomplete_children,
            key=lambda item: (str(item["stock_code"]), str(item["market"]), str(item["origin"])),
        ),
        "coverage": coverage,
        "consumer": {
            "database": first_db,
            "first_materialization": first_receipt,
            "retry_materialization": retry_receipt,
            "cutoff": {
                "hidden_decision_date": args.hidden_decision_date,
                "visible_decision_date": args.visible_decision_date,
                "hidden_visible_row_counts": {
                    args.hidden_decision_date: 0,
                    args.visible_decision_date: total_rows,
                },
                "policy": "next_taipei_calendar_day; same-day use requires numeric_available_at comparison",
            },
            "eps_rows": first_db["eps_rows"],
        },
        "source_acceptance": {
            "numeric_lane": "MOPS t164 statement HTTP/XBRL raw responses",
            "availability_lane": "MOPS EZSearch statement publication response",
            "pit_credit": "none; numeric values use conservative capture-completion date-only availability",
        },
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", required=True, help="candidate period, YYYY-Qn")
    parser.add_argument(
        "--batch-manifest",
        action="append",
        type=Path,
        default=[],
        help="已完成或 partial 的 v2 batch manifest；可重複指定",
    )
    parser.add_argument(
        "--child-manifest",
        action="append",
        type=Path,
        default=[],
        help="不在 batch manifest 內的已完成 child manifest；可重複指定",
    )
    parser.add_argument("--universe-plan", type=Path)
    parser.add_argument(
        "--supersession-record",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help="immutable child replacement record；可重複指定",
    )
    parser.add_argument("--materialization-first", type=Path, required=True)
    parser.add_argument("--materialization-retry", type=Path, required=True)
    parser.add_argument("--hidden-decision-date", default="2026-09-07")
    parser.add_argument("--visible-decision-date", default="2026-09-08")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.batch_manifest and not args.child_manifest and args.universe_plan is None:
        raise ValueError("at least one batch, child, or universe plan is required")
    summary = _build_summary(args)
    conflicts = [args.materialization_first, args.materialization_retry]
    conflicts.extend(
        Path(str(item["path"]))
        for item in summary["batch_manifests"]
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    )
    conflicts.extend(
        Path(str(item["path"]))
        for item in summary["child_manifests"]
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    )
    conflicts.extend(
        Path(str(child["candidate_path"]))
        for child in summary["completed_children"]
        if isinstance(child, Mapping) and isinstance(child.get("candidate_path"), str)
    )
    if args.universe_plan is not None:
        conflicts.append(args.universe_plan)
    conflicts.extend(
        Path(str(correction["record_path"]))
        for correction in summary["artifact_corrections"]
        if isinstance(correction, Mapping) and isinstance(correction.get("record_path"), str)
    )
    db_path = Path(summary["consumer"]["database"]["path"])
    marker_path = Path(summary["consumer"]["database"]["marker_path"])
    output = validate_research_output_path(
        args.output,
        conflicts=tuple([*conflicts, db_path, marker_path]),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
