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
from urllib.parse import unquote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from qa.full_app_healthcheck.test_inventory import (
    TEST_INVENTORY,
    get_candidate_bridge_files,
    get_direct_bridge_files,
    get_files_by_category,
)

GOVERNANCE_MARKDOWN_PATHS = (
    "PROJECT_NAVIGATION.md",
    "PROJECT_INVENTORY.md",
    "docs/00_core/DOCUMENTATION_INDEX.md",
    "docs/07_guides/LUNA_PARALLEL_PLAN_2026_09_07.md",
    "docs/07_guides/LUNA_PROMPT_B_ARCHITECTURE_2026_09_07.md",
    "docs/07_guides/LUNA_B_ENVIRONMENT_2026_09_07.md",
    "docs/06_qa/PROJECT_CONSOLIDATION_REVIEW_2026_09_07.md",
    "docs/06_qa/LUNA_B_HANDOFF_2026_09_07.md",
)
FORMAL_ENTRY_REFERENCES = (
    "PROJECT_SNAPSHOT.md",
    "DEVELOPMENT_ROADMAP.md",
    "system_architecture.md",
    "target_system_architecture.md",
    "APPLICATION_MANUAL.md",
    "FORMAL_INPUT_READINESS_REFRESH_2026_08_30.md",
)
_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)\n]+)\)")
_CURRENT_SECTION_TOKENS = ("current", "machine refresh", "目前", "現在")


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
    governance_markdown_paths = [
        PROJECT_ROOT / relative_path for relative_path in GOVERNANCE_MARKDOWN_PATHS
    ]
    markdown_link_errors, nonportable_markdown_links = _find_markdown_link_errors(
        governance_markdown_paths,
        project_root=PROJECT_ROOT,
    )
    duplicate_current_sections = _find_duplicate_current_sections(
        governance_markdown_paths,
        project_root=PROJECT_ROOT,
    )
    formal_entry_reference_errors = _find_formal_entry_reference_errors(
        PROJECT_ROOT / "docs" / "00_core" / "DOCUMENTATION_INDEX.md",
        project_root=PROJECT_ROOT,
    )

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
    if markdown_link_errors:
        machine_checkable_blockers.append(
            f"markdown_link_errors:{len(markdown_link_errors)}"
        )
    if duplicate_current_sections:
        machine_checkable_blockers.append(
            f"duplicate_current_sections:{len(duplicate_current_sections)}"
        )
    if formal_entry_reference_errors:
        machine_checkable_blockers.append(
            f"formal_entry_reference_errors:{len(formal_entry_reference_errors)}"
        )

    overall_status = "passed" if not machine_checkable_blockers else "failed"

    return {
        "schema_version": "test-inventory-audit.v2",
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
        "governance_markdown_paths": [
            path.relative_to(PROJECT_ROOT).as_posix()
            for path in governance_markdown_paths
        ],
        "markdown_link_errors": markdown_link_errors,
        "nonportable_markdown_links": nonportable_markdown_links,
        "duplicate_current_sections": duplicate_current_sections,
        "formal_entry_reference_errors": formal_entry_reference_errors,
        "machine_checkable_blockers": machine_checkable_blockers,
        "human_decision_required": human_decision_required,
        "automatic_fail_closed_dispositions": automatic_fail_closed_dispositions,
        "waiting_for_time": waiting_for_time,
        "external_environment_required": external_environment_required,
        "overall_status": overall_status,
    }


def _find_markdown_link_errors(
    paths: Sequence[Path],
    *,
    project_root: Path,
) -> tuple[list[str], list[str]]:
    """Check explicit local Markdown links and report absolute-path warnings."""
    errors: list[str] = []
    nonportable: list[str] = []
    root = project_root.resolve()
    for source_path in paths:
        try:
            content = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{source_path}:read_error:{type(exc).__name__}")
            continue
        source_label = _relative_label(source_path, root)
        for match in _MARKDOWN_LINK_RE.finditer(content):
            raw_target = match.group(1).strip()
            if raw_target.startswith("<") and ">" in raw_target:
                target = raw_target[1 : raw_target.index(">")]
            else:
                target = raw_target.split(maxsplit=1)[0]
            target = unquote(target)
            if (
                not target
                or target.startswith(("#", "http://", "https://", "mailto:", "codex://", "app://"))
            ):
                continue
            target = target.split("#", maxsplit=1)[0].split("?", maxsplit=1)[0]
            if not target:
                continue
            if re.match(r"^[A-Za-z]:[\\/]", target):
                candidate = Path(target)
                nonportable.append(f"{source_label}:{target}")
            elif target.startswith("/"):
                candidate = root / target.lstrip("/\\")
            else:
                candidate = source_path.parent / target
            if not candidate.exists():
                errors.append(f"{source_label}:missing_local_link:{target}")
    return sorted(errors), sorted(nonportable)


def _find_duplicate_current_sections(
    paths: Sequence[Path],
    *,
    project_root: Path,
) -> list[str]:
    """Find repeated current-status headings within one governance document."""
    heading_re = re.compile(r"^(#{1,6})\s+(.+?)\s*$", flags=re.MULTILINE)
    duplicates: list[str] = []
    root = project_root.resolve()
    for source_path in paths:
        try:
            content = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        seen: dict[tuple[int, str], int] = {}
        for match in heading_re.finditer(content):
            title = re.sub(r"\s+", " ", match.group(2).strip()).casefold()
            if not any(token in title for token in _CURRENT_SECTION_TOKENS):
                continue
            level = len(match.group(1))
            key = (level, title)
            line = content.count("\n", 0, match.start()) + 1
            previous_line = seen.get(key)
            if previous_line is not None:
                duplicates.append(
                    f"{_relative_label(source_path, root)}:duplicate_current_section:"
                    f"line_{previous_line}_and_{line}:{match.group(2).strip()}"
                )
            else:
                seen[key] = line
    return sorted(duplicates)


def _find_formal_entry_reference_errors(
    index_path: Path,
    *,
    project_root: Path,
) -> list[str]:
    """Ensure the core Index retains the current/formal navigation anchors."""
    try:
        content = index_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{_relative_label(index_path, project_root.resolve())}:read_error:{type(exc).__name__}"]
    label = _relative_label(index_path, project_root.resolve())
    return [
        f"{label}:missing_formal_entry_reference:{reference}"
        for reference in FORMAL_ENTRY_REFERENCES
        if reference not in content
    ]


def _relative_label(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


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
    marker_match = re.search(
        r"^## \d{4}-\d{2}-\d{2} machine refresh\s*$",
        content,
        flags=re.MULTILINE,
    )
    if marker_match is None:
        return {}
    remaining = content[marker_match.end():]
    next_section = re.search(r"^## ", remaining, flags=re.MULTILINE)
    section = remaining[:next_section.start()] if next_section is not None else remaining
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
