"""將 MOPS 財報 research candidates 寫入受隔離 SQLite 並輸出讀回證據。

此入口只接受已完成官方 XBRL row code 與時間語意驗證的 candidate；adapter
會在任何建立目錄或 SQLite 連線前拒絕正式 DATA_ROOT、正式資料庫、alias 與
未標記既有資料庫。它不會寫入正式 SQLite 或 D 槽 raw。
"""

from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.mops_statement_candidate_adapter import (
    _resolve_report_basis,
    materialize_mops_statement_candidates,
    validate_research_output_path,
)
from scripts.plan_mops_statement_universe import (
    _load_supersession_records,
    _verify_child_artifacts,
    load_universe_plan,
)


_BATCH_SCHEMA_VERSION = "mops-statement-pit-batch-manifest.v2"
_CHILD_SCHEMA_VERSIONS = frozenset(
    {"mops-statement-pit-run-manifest.v1", "mops-statement-pit-run-manifest.v2"}
)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _resolve_regular_file(path: Path, *, description: str) -> Path:
    """讀取 manifest 時拒絕 symlink、junction 與不存在的路徑。"""

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


def _load_object(path: Path, *, description: str) -> dict[str, Any]:
    resolved = _resolve_regular_file(path, description=description)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{description} is not valid UTF-8 JSON") from error
    if not isinstance(payload, Mapping):
        raise ValueError(f"{description} must be a JSON object")
    return dict(payload)


def _child_path(value: object, *, batch_path: Path, description: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{description} path is missing")
    path = Path(value)
    if not path.is_absolute():
        path = batch_path.parent / path
    return _resolve_regular_file(path, description=description)


def _collect_batch_candidates(
    batch_paths: tuple[Path, ...],
    *,
    expected_period: str,
) -> tuple[tuple[Path, ...], tuple[dict[str, Any], ...]]:
    """由 batch manifest 收集已完成 child，並在入庫前重驗完整 lineage。"""

    if not batch_paths:
        return (), ()
    collected: list[Path] = []
    seen: dict[tuple[str, str, str], tuple[Path, str, str]] = {}
    descriptors: list[dict[str, Any]] = []
    processed_batches: set[Path] = set()
    for requested_batch in batch_paths:
        batch_path = _resolve_regular_file(
            requested_batch,
            description="batch manifest",
        )
        if batch_path in processed_batches:
            continue
        processed_batches.add(batch_path)
        payload = _load_object(batch_path, description="batch manifest")
        if payload.get("schema_version") != _BATCH_SCHEMA_VERSION:
            raise ValueError("batch manifest schema is unsupported")
        if (
            payload.get("research_only") is not True
            or payload.get("formal_oos_allowed") is not False
        ):
            raise ValueError(
                "batch manifest must remain research_only and formal_oos disallowed"
            )
        child_runs = payload.get("child_runs")
        if not isinstance(child_runs, list):
            raise ValueError("batch manifest child_runs must be a list")
        observed_counts = {
            "succeeded": 0,
            "failed": 0,
            "integrity_error": 0,
            "pending": 0,
            "running": 0,
        }
        succeeded_scope: list[dict[str, Any]] = []
        incomplete_scope: list[dict[str, Any]] = []
        for child in child_runs:
            if not isinstance(child, Mapping):
                raise ValueError("batch manifest child must be an object")
            status = child.get("status")
            stock_code = child.get("stock_code")
            batch_market = child.get("market")
            period = child.get("period")
            run_id = child.get("run_id")
            if not all(
                isinstance(value, str) and value.strip()
                for value in (stock_code, batch_market, period, run_id)
            ):
                raise ValueError("batch manifest child identity is incomplete")
            if period != expected_period:
                raise ValueError("batch child period does not match --period")
            if status != "succeeded":
                if status not in {"pending", "running", "failed", "integrity_error"}:
                    raise ValueError("batch manifest contains an unknown child status")
                observed_counts[str(status)] += 1
                attempts = child.get("attempts")
                if attempts is not None and not isinstance(attempts, list):
                    raise ValueError("incomplete child attempts must be a list")
                last_attempt = (
                    attempts[-1]
                    if isinstance(attempts, list)
                    and attempts
                    and isinstance(attempts[-1], Mapping)
                    else {}
                )
                incomplete_scope.append(
                    {
                        "stock_code": stock_code,
                        "market": batch_market,
                        "period": period,
                        "run_id": run_id,
                        "status": status,
                        "attempt_count": len(attempts) if isinstance(attempts, list) else 0,
                        "error_type": last_attempt.get("error_type"),
                        "error": last_attempt.get("error"),
                        "failure_source": last_attempt.get("failure_source"),
                    }
                )
                # 未完成 child 仍由原 manifest 保存；本次 writer 只收集可驗證完成者。
                continue
            observed_counts["succeeded"] += 1
            candidate_path = _child_path(
                child.get("candidate"),
                batch_path=batch_path,
                description="candidate",
            )
            manifest_path = _child_path(
                child.get("manifest"),
                batch_path=batch_path,
                description="child manifest",
            )
            manifest_payload = _load_object(
                manifest_path,
                description="child manifest",
            )
            if manifest_payload.get("run_id") != run_id:
                raise ValueError(
                    "succeeded child run_id does not match child manifest"
                )
            details = _verify_child_artifacts(
                candidate_path,
                manifest_path,
                expected_period=expected_period,
            )
            if details["stock_code"] != stock_code or details["batch_market"] != batch_market:
                raise ValueError("succeeded child identity does not match its batch row")
            candidate_payload = _load_object(candidate_path, description="candidate")
            source_version = candidate_payload.get("source_version")
            if not isinstance(source_version, str) or not source_version.strip():
                raise ValueError("succeeded child candidate source_version is missing")
            candidate_basis = _resolve_report_basis(
                candidate_payload,
                source_version=source_version,
                label="candidate",
            )
            child_basis = _resolve_report_basis(
                child,
                source_version=source_version,
                label="batch child",
            )
            if candidate_basis != child_basis:
                raise ValueError("succeeded child report_basis does not match its batch row")
            for field, actual in (
                ("candidate_sha256", details["candidate_sha256"]),
                ("manifest_sha256", details["manifest_sha256"]),
            ):
                stored = child.get(field)
                if stored is not None and stored != actual:
                    raise ValueError(f"batch child {field} changed after completion")
            identity = (str(stock_code), str(batch_market), str(period))
            succeeded_scope.append(
                {
                    "stock_code": stock_code,
                    "market": batch_market,
                    "period": period,
                    "run_id": run_id,
                    "candidate_path": str(candidate_path),
                    "candidate_sha256": details["candidate_sha256"],
                    "manifest_path": str(manifest_path),
                    "manifest_sha256": details["manifest_sha256"],
                    "candidate_row_count": int(details["candidate_row_count"]),
                    "source_version": source_version,
                    "report_basis": candidate_basis,
                }
            )
            previous = seen.get(identity)
            if previous is not None:
                if previous[1:] != (
                    details["candidate_sha256"],
                    details["manifest_sha256"],
                ):
                    raise ValueError(
                        "batch manifests contain conflicting candidate revisions for "
                        f"{stock_code}:{batch_market}:{period}"
                    )
                continue
            seen[identity] = (
                candidate_path,
                details["candidate_sha256"],
                details["manifest_sha256"],
            )
            collected.append(candidate_path)
        descriptors.append(
            {
                "batch_manifest_path": str(batch_path),
                "batch_manifest_sha256": _sha256_file(batch_path),
                "schema_version": payload["schema_version"],
                "period": expected_period,
                "status": payload.get("status"),
                "request_count": payload.get("request_count"),
                "declared_counts": {
                    field: payload.get(field)
                    for field in (
                        "succeeded_count",
                        "failed_count",
                        "pending_count",
                    )
                },
                "observed_counts": observed_counts,
                "succeeded_scope": succeeded_scope,
                "incomplete_scope": incomplete_scope,
            }
        )
    if not collected:
        raise ValueError("batch manifests contain no succeeded children")
    return tuple(collected), tuple(descriptors)


def _collect_child_candidates(
    child_paths: tuple[Path, ...],
    *,
    expected_period: str,
) -> tuple[tuple[Path, ...], tuple[dict[str, Any], ...]]:
    """把舊版直接 child manifest 接到同一個 materializer，保留完整 lineage。"""

    collected: list[Path] = []
    seen_paths: set[Path] = set()
    seen_identity: dict[tuple[str, str, str], tuple[str, str]] = {}
    descriptors: list[dict[str, Any]] = []
    for requested_child in child_paths:
        manifest_path = _resolve_regular_file(
            requested_child,
            description="child manifest",
        )
        if manifest_path in seen_paths:
            continue
        seen_paths.add(manifest_path)
        manifest_payload = _load_object(manifest_path, description="child manifest")
        if manifest_payload.get("schema_version") not in _CHILD_SCHEMA_VERSIONS:
            raise ValueError("child manifest schema is unsupported")
        run_id = manifest_payload.get("run_id")
        if run_id is not None and run_id != manifest_path.parent.name:
            raise ValueError("child manifest run_id does not match its directory")
        candidate_path = _resolve_regular_file(
            manifest_path.parent / "statement-pit-candidate.json",
            description="candidate",
        )
        details = _verify_child_artifacts(
            candidate_path,
            manifest_path,
            expected_period=expected_period,
        )
        candidate_payload = _load_object(candidate_path, description="candidate")
        source_version = candidate_payload.get("source_version")
        if not isinstance(source_version, str) or not source_version.strip():
            raise ValueError("child candidate source_version is missing")
        report_basis = _resolve_report_basis(
            candidate_payload,
            source_version=source_version,
            label="child candidate",
        )
        identity = (
            details["stock_code"],
            details["batch_market"],
            details["period"],
        )
        candidate_hash = details["candidate_sha256"]
        manifest_hash = details["manifest_sha256"]
        previous = seen_identity.get(identity)
        if previous is not None:
            if previous != (candidate_hash, manifest_hash):
                raise ValueError(
                    "child manifests contain conflicting candidate revisions for "
                    f"{details['stock_code']}:{details['batch_market']}:{details['period']}"
                )
            continue
        seen_identity[identity] = (candidate_hash, manifest_hash)
        collected.append(candidate_path)
        descriptors.append(
            {
                "stock_code": details["stock_code"],
                "market": details["batch_market"],
                "period": details["period"],
                "run_id": str(run_id) if run_id is not None else None,
                "candidate_path": str(candidate_path),
                "candidate_sha256": candidate_hash,
                "manifest_path": str(manifest_path),
                "manifest_sha256": manifest_hash,
                "candidate_row_count": int(details["candidate_row_count"]),
                "source_version": source_version,
                "report_basis": report_basis,
                "schema_version": manifest_payload["schema_version"],
            }
        )
    return tuple(collected), tuple(descriptors)


def _collect_supersession_candidates(
    supersession_paths: tuple[Path, ...],
    *,
    expected_period: str,
) -> tuple[tuple[Path, ...], tuple[dict[str, Any], ...]]:
    """只收集更正 record 的 replacement，並在 receipt 保留舊 artifact 身分。"""

    records = _load_supersession_records(
        supersession_paths,
        expected_period=expected_period,
    )
    collected: list[Path] = []
    seen_paths: set[Path] = set()
    descriptors: list[dict[str, Any]] = []
    for record in records:
        replacement = record["replacement"]
        candidate_path = _resolve_regular_file(
            Path(str(replacement["candidate_path"])),
            description="supersession replacement candidate",
        )
        if candidate_path not in seen_paths:
            seen_paths.add(candidate_path)
            collected.append(candidate_path)
        descriptors.append(
            {
                "record_path": str(record["record_path"]),
                "record_sha256": str(record["record_sha256"]),
                "stock_code": str(record["stock_code"]),
                "registry_market": str(record["registry_market"]),
                "batch_market": str(record["batch_market"]),
                "period": str(record["period"]),
                "reason": str(record["reason"]),
                "superseded_candidate_path": str(record["superseded"]["candidate_path"]),
                "superseded_candidate_sha256": str(
                    record["superseded"]["candidate_sha256"]
                ),
                "replacement_candidate_path": str(replacement["candidate_path"]),
                "replacement_candidate_sha256": str(
                    replacement["candidate_sha256"]
                ),
                "replacement_manifest_path": str(replacement["manifest_path"]),
                "replacement_manifest_sha256": str(replacement["manifest_sha256"]),
            }
        )
    return tuple(collected), tuple(descriptors)


def _universe_plan_sources(
    universe_plan_path: Path,
    *,
    expected_period: str,
) -> tuple[tuple[Path, ...], tuple[Path, ...], tuple[Path, ...], dict[str, Any]]:
    """由最新 universe plan 展開 batch／child／supersession 三種已驗證來源。"""

    resolved_plan = _resolve_regular_file(
        universe_plan_path,
        description="universe plan",
    )
    plan = load_universe_plan(resolved_plan)
    scope = plan.get("scope")
    if not isinstance(scope, Mapping) or scope.get("period") != expected_period:
        raise ValueError("universe plan period does not match --period")
    references = plan.get("verified_completed_artifacts")
    if not isinstance(references, list) or not references:
        raise ValueError("universe plan has no verified artifact references")
    batch_paths: list[Path] = []
    child_paths: list[Path] = []
    supersession_paths: list[Path] = []
    seen: set[Path] = set()
    for reference in references:
        if not isinstance(reference, Mapping):
            raise ValueError("universe plan artifact reference is malformed")
        value = reference.get("artifact_path")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("universe plan artifact path is missing")
        artifact_path = _resolve_regular_file(
            Path(value),
            description="universe plan artifact",
        )
        if artifact_path in seen:
            continue
        seen.add(artifact_path)
        artifact = _load_object(artifact_path, description="universe plan artifact")
        schema_version = artifact.get("schema_version")
        if schema_version == _BATCH_SCHEMA_VERSION:
            batch_paths.append(artifact_path)
        elif schema_version in _CHILD_SCHEMA_VERSIONS:
            child_paths.append(artifact_path)
        elif schema_version == "mops-statement-artifact-correction.v1":
            supersession_paths.append(artifact_path)
        else:
            raise ValueError("universe plan artifact schema is unsupported")
    if not batch_paths and not child_paths and not supersession_paths:
        raise ValueError("universe plan has no supported verified artifacts")
    universe_summary = {
        "path": str(resolved_plan),
        "sha256": _sha256_file(resolved_plan),
        "plan_id": plan.get("plan_id"),
        "eligible_company_count": scope.get("eligible_company_count"),
        "verified_completed_company_count": scope.get(
            "verified_completed_company_count"
        ),
        "deferred_unresolved_company_count": scope.get(
            "deferred_unresolved_company_count"
        ),
        "total_unfinished_company_count": scope.get("total_unfinished_company_count"),
        "remaining_selectable_company_count": scope.get(
            "remaining_selectable_company_count"
        ),
        "caller_excluded_company_count": scope.get("caller_excluded_company_count"),
        "artifact_reference_count": len(references),
        "unique_artifact_path_count": len(seen),
    }
    return (
        tuple(batch_paths),
        tuple(child_paths),
        tuple(supersession_paths),
        universe_summary,
    )


def _unique_candidate_paths(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    """相同 immutable path 只送一次，避免輸入分母因 alias 參照重複。"""

    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = Path(path).expanduser().resolve(strict=True)
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(resolved)
    return tuple(result)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate",
        action="append",
        type=Path,
        default=[],
        help="一個或多個 research statement-pit-candidate.json",
    )
    parser.add_argument(
        "--batch-manifest",
        action="append",
        type=Path,
        default=[],
        help="一個或多個 v2 batch manifest；自動收集並重驗 succeeded child",
    )
    parser.add_argument(
        "--child-manifest",
        action="append",
        type=Path,
        default=[],
        help="一個或多個 v1/v2 直接 child manifest；保留舊版 raw lineage",
    )
    parser.add_argument(
        "--supersession-record",
        action="append",
        type=Path,
        default=[],
        help="一個或多個 immutable replacement record；只收集 replacement",
    )
    parser.add_argument(
        "--universe-plan",
        type=Path,
        help="由最新 universe plan 自動展開 batch、child 與 supersession artifact",
    )
    parser.add_argument(
        "--period",
        help="輸入來源的期別 YYYY-Qn；使用 manifest／universe plan 時必填",
    )
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument(
        "--decision-date",
        action="append",
        required=True,
        help="provider 可見性驗證日期，格式 YYYY-MM-DD，可重複指定",
    )
    parser.add_argument("--evidence-output", type=Path, required=True)
    args = parser.parse_args(argv)

    explicit_sources = (
        bool(args.candidate)
        or bool(args.batch_manifest)
        or bool(args.child_manifest)
        or bool(args.supersession_record)
    )
    if args.universe_plan is not None and explicit_sources:
        raise ValueError(
            "--universe-plan cannot be combined with explicit candidate or manifest inputs"
        )
    if not explicit_sources and args.universe_plan is None:
        raise ValueError(
            "at least one --candidate, manifest, or --universe-plan is required"
        )
    if (
        (args.batch_manifest or args.child_manifest or args.supersession_record or args.universe_plan)
        and (
        not isinstance(args.period, str) or not args.period.strip()
        )
    ):
        raise ValueError("--period is required when using manifest or --universe-plan")
    batch_paths = tuple(args.batch_manifest)
    child_paths = tuple(args.child_manifest)
    supersession_paths = tuple(args.supersession_record)
    universe_summary: dict[str, Any] | None = None
    if args.universe_plan is not None:
        (
            batch_paths,
            child_paths,
            supersession_paths,
            universe_summary,
        ) = _universe_plan_sources(
            args.universe_plan,
            expected_period=args.period.strip(),
        )
    candidate_paths = tuple(args.candidate)
    batch_descriptors: tuple[dict[str, Any], ...] = ()
    child_descriptors: tuple[dict[str, Any], ...] = ()
    supersession_descriptors: tuple[dict[str, Any], ...] = ()
    if batch_paths:
        batch_candidates, batch_descriptors = _collect_batch_candidates(
            batch_paths,
            expected_period=args.period.strip(),
        )
        candidate_paths += batch_candidates
    if child_paths:
        child_candidates, child_descriptors = _collect_child_candidates(
            child_paths,
            expected_period=args.period.strip(),
        )
        candidate_paths += child_candidates
    if supersession_paths:
        replacement_candidates, supersession_descriptors = _collect_supersession_candidates(
            supersession_paths,
            expected_period=args.period.strip(),
        )
        candidate_paths += replacement_candidates
    candidate_paths = _unique_candidate_paths(candidate_paths)

    try:
        decision_dates = tuple(date.fromisoformat(value) for value in args.decision_date)
    except ValueError as error:
        raise ValueError("--decision-date must use ISO dates") from error
    resolved_db_path = Path(args.db_path).expanduser().resolve(strict=False)
    marker_path = resolved_db_path.with_name(
        resolved_db_path.name + ".research-only.json"
    )
    evidence_path = validate_research_output_path(
        args.evidence_output,
        conflicts=tuple(args.candidate)
        + batch_paths
        + child_paths
        + supersession_paths
        + ((args.universe_plan,) if args.universe_plan is not None else ())
        + tuple(candidate_paths)
        + (resolved_db_path, marker_path),
    )
    report = materialize_mops_statement_candidates(
        candidate_paths,
        args.db_path,
        decision_dates=decision_dates,
    )
    batch_succeeded_scope = [
        child
        for descriptor in batch_descriptors
        for child in descriptor["succeeded_scope"]
    ]
    batch_incomplete_scope = [
        child
        for descriptor in batch_descriptors
        for child in descriptor["incomplete_scope"]
    ]
    direct_child_scope = list(child_descriptors)
    supersession_scope = list(supersession_descriptors)
    report.update(
        {
            "batch_sources": list(batch_descriptors),
            "child_manifest_sources": list(child_descriptors),
            "supersession_records": supersession_scope,
            "universe_plan": universe_summary,
            "batch_succeeded_child_count": (
                len(batch_succeeded_scope)
                + len(direct_child_scope)
                + len(supersession_scope)
            ),
            "batch_incomplete_child_count": len(batch_incomplete_scope),
            "direct_child_manifest_count": len(direct_child_scope),
            "supersession_replacement_count": len(supersession_scope),
            "batch_succeeded_scope": batch_succeeded_scope
            + direct_child_scope
            + supersession_scope,
            "batch_incomplete_scope": batch_incomplete_scope,
        }
    )
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    with evidence_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
