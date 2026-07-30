"""Deterministic, read-only test inventory audit CLI tool.

Scans the filesystem test files, cross-references qa/full_app_healthcheck/test_inventory.py,
detects missing/stale entries, reports category counts, exact duplicate test groups, and
synthesizes machine-checkable blockers and genuine human/time gaps.
"""

from __future__ import annotations

import argparse
import ast
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from qa.full_app_healthcheck.test_inventory import (
    TEST_INVENTORY,
    get_candidate_bridge_files,
    get_direct_bridge_files,
    get_files_by_category,
)


def run_test_inventory_audit(
    *,
    include_pytest_collection: bool = False,
) -> dict[str, Any]:
    """Perform deterministic audit of the test inventory."""
    tests_dir = PROJECT_ROOT / "tests"

    found_files: list[str] = []
    for root, dirs, files in os.walk(str(tests_dir)):
        if "__pycache__" in root or ".pytest_cache" in root:
            continue
        for file in files:
            if file.endswith(".py"):
                full_path = Path(root) / file
                rel_path = full_path.relative_to(PROJECT_ROOT).as_posix()
                found_files.append(rel_path)

    found_files.sort()

    missing_inventory_paths = [f for f in found_files if f not in TEST_INVENTORY]
    stale_inventory_paths = [f for f in TEST_INVENTORY if not (PROJECT_ROOT / f).exists()]

    category_counts: dict[str, int] = {}
    for cat in set(TEST_INVENTORY.values()):
        category_counts[cat] = len(get_files_by_category(cat))

    manual_only_files = sorted(list(get_files_by_category("manual-only")))
    legacy_files = sorted(list(get_files_by_category("legacy-or-low-priority")))
    write_risk_files = sorted(list(get_files_by_category("write-risk-dry-run-required")))
    candidate_bridge_files = sorted(list(get_candidate_bridge_files()))
    direct_bridge_files = sorted(list(get_direct_bridge_files()))

    duplicate_groups, parse_errors = _find_exact_duplicate_test_groups(found_files)
    documented_counts = _read_documented_current_counts()
    expected_counts = {"total": len(TEST_INVENTORY), **category_counts}
    documentation_count_drift = {
        key: {"documented": documented_counts.get(key), "actual": actual}
        for key, actual in sorted(expected_counts.items())
        if documented_counts.get(key) != actual
    }

    collected_test_count: int | None = None
    collection_errors = list(parse_errors)
    if include_pytest_collection:
        collected_test_count, pytest_collection_error = _collect_pytest_count()
        if pytest_collection_error:
            collection_errors.append(pytest_collection_error)

    # Gate 2-7 不再等待人工簽核：無法自動證明 license / PIT 的來源會
    # fail closed 為 research_shadow / blocked_no_provenance，而不是阻擋
    # Rule operational production。
    human_decision_required: list[str] = []
    automatic_fail_closed_dispositions = [
        "unverified_source_license_or_pit_to_research_shadow",
        "missing_provenance_to_blocked_no_provenance",
    ]
    waiting_for_time = [
        "forward_performance_close_to_close_maturity_days",
    ]
    external_environment_required = [
        "fubon_realtime_network_connection_probe",
        "mops_quarterly_official_announcement_availability",
    ]

    machine_checkable_blockers = []
    if missing_inventory_paths:
        machine_checkable_blockers.append(f"unregistered_test_files:{len(missing_inventory_paths)}")
    if stale_inventory_paths:
        machine_checkable_blockers.append(f"stale_inventory_files:{len(stale_inventory_paths)}")
    if documentation_count_drift:
        machine_checkable_blockers.append(
            f"documentation_count_drift:{len(documentation_count_drift)}"
        )
    if collection_errors:
        machine_checkable_blockers.append(
            f"collection_errors:{len(collection_errors)}"
        )

    overall_status = "passed" if not machine_checkable_blockers else "failed"

    return {
        "schema_version": "test-inventory-audit.v1",
        "filesystem_test_file_count": len(found_files),
        "inventory_entry_count": len(TEST_INVENTORY),
        "collected_test_count": collected_test_count,
        "missing_inventory_paths": missing_inventory_paths,
        "stale_inventory_paths": stale_inventory_paths,
        "category_counts": category_counts,
        "exact_duplicate_test_groups": duplicate_groups,
        "collection_errors": collection_errors,
        "manual_only_files": manual_only_files,
        "legacy_files": legacy_files,
        "write_risk_files": write_risk_files,
        "candidate_bridge_files": candidate_bridge_files,
        "direct_bridge_files": direct_bridge_files,
        "documentation_count_drift": documentation_count_drift,
        "machine_checkable_blockers": machine_checkable_blockers,
        "human_decision_required": human_decision_required,
        "automatic_fail_closed_dispositions": automatic_fail_closed_dispositions,
        "waiting_for_time": waiting_for_time,
        "external_environment_required": external_environment_required,
        "overall_status": overall_status,
    }


def _find_exact_duplicate_test_groups(
    found_files: Sequence[str],
) -> tuple[list[list[str]], list[str]]:
    groups: dict[str, list[str]] = {}
    errors: list[str] = []
    for relative_path in found_files:
        path = PROJECT_ROOT / relative_path
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            errors.append(f"{relative_path}:{type(exc).__name__}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            body = ast.dump(
                ast.Module(body=node.body, type_ignores=[]),
                include_attributes=False,
            )
            digest = sha256(body.encode("utf-8")).hexdigest()
            groups.setdefault(digest, []).append(f"{relative_path}::{node.name}")
    duplicates = [
        sorted(group)
        for group in groups.values()
        if len(group) > 1
    ]
    return sorted(duplicates, key=lambda group: (-len(group), group)), sorted(errors)


def _read_documented_current_counts() -> dict[str, int]:
    path = (
        PROJECT_ROOT
        / "docs"
        / "06_qa"
        / "TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md"
    )
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    marker = "## 2026-07-30 machine refresh"
    if marker not in content:
        return {}
    section = content.split(marker, 1)[1].split("## ", 1)[0]
    counts: dict[str, int] = {}
    total_match = re.search(r"Current filesystem Python files:\s*`(\d+)`", section)
    if total_match:
        counts["total"] = int(total_match.group(1))
    for category, value in re.findall(r"\| `([^`]+)` \| (\d+) \|", section):
        counts[category] = int(value)
    return counts


def _collect_pytest_count() -> tuple[int | None, str | None]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-o",
            "addopts=",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    match = re.search(r"(\d+) tests? collected", combined)
    if result.returncode != 0:
        tail = "\n".join(combined.splitlines()[-20:])
        return None, f"pytest_collect_failed:{result.returncode}:{tail}"
    if match is None:
        return None, "pytest_collect_count_missing"
    return int(match.group(1)), None


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    parser = argparse.ArgumentParser(description="Test Inventory Audit CLI")
    parser.add_argument("--output-json", type=Path, help="Optional output JSON file path")
    parser.add_argument(
        "--skip-pytest-collection",
        action="store_true",
        help="Skip the subprocess collect-only count for a fast audit.",
    )
    args = parser.parse_args(argv)

    report = run_test_inventory_audit(
        include_pytest_collection=not args.skip_pytest_collection
    )
    output_str = json.dumps(report, ensure_ascii=False, indent=2)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(output_str, encoding="utf-8")

    print(output_str)
    return 0 if report["overall_status"] == "passed" else 1


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
