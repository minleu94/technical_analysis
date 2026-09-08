"""Build a bounded, read-only repository map for the LUNA B handoff.

The command separates Git tracked/untracked/ignored paths and keeps generated
manifests outside the repository.  It is intentionally an inventory/evidence
tool, not a cleanup command: it never deletes, moves, stages, or rewrites repo
files.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_TEXT_SUFFIXES = {
    ".bat",
    ".cmd",
    ".ini",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".pyi",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_DYNAMIC_IMPORT_MARKERS = (
    "importlib.import_module",
    "__import__(",
    "import_module(",
)
_CANDIDATE_REVIEWS = (
    {
        "candidate": "SignalCombiner shared analysis flow",
        "decision": "merge",
        "paths": [
            "analysis_module/signal_combiner_support.py",
            "analysis_module/pattern_analysis/signal_combiner.py",
            "analysis_module/signal_analysis/signal_combiner.py",
        ],
        "tokens": ["SignalCombinationMixin", "SignalCombiner"],
        "tests": [
            "tests/test_analysis/test_signal_analysis_column_support.py",
            "tests/test_pattern_analysis/test_signal_combiner.py",
        ],
        "docs": [
            "docs/06_qa/PROJECT_CONSOLIDATION_REVIEW_2026_09_07.md",
            "docs/07_guides/LUNA_PROMPT_B_ARCHITECTURE_2026_09_07.md",
        ],
        "reason": "兩個入口的共同分析流程已共用；可靠性與 backtest policy 仍保留在各自入口。",
    },
    {
        "candidate": "analysis column resolver primitive",
        "decision": "merge",
        "paths": [
            "analysis_module/column_support.py",
            "analysis_module/pattern_analysis/pattern_column_support.py",
            "analysis_module/technical_analysis/technical_column_support.py",
            "analysis_module/ml_analysis/ml_column_support.py",
        ],
        "tokens": [
            "resolve_column",
            "resolve_pattern_column",
            "resolve_technical_column",
            "resolve_ml_column",
        ],
        "tests": [
            "tests/test_analysis/test_technical_column_support.py",
            "tests/test_ml_analysis/test_ml_column_support.py",
            "tests/test_pattern_analysis/test_pattern_column_support.py",
        ],
        "docs": ["docs/07_guides/LUNA_PROMPT_B_ARCHITECTURE_2026_09_07.md"],
        "reason": "完全相同的 lookup order 收斂為單一 primitive，保留三個歷史 facade 名稱與 API。",
    },
    {
        "candidate": "SignalCombiner reliability and backtest policies",
        "decision": "keep",
        "paths": [
            "analysis_module/pattern_analysis/signal_combiner.py",
            "analysis_module/signal_analysis/signal_combiner.py",
        ],
        "tokens": ["_evaluate_signal_reliability", "backtest_strategy"],
        "tests": [
            "tests/test_pattern_analysis/test_signal_combiner.py",
            "tests/test_signal_analysis/test_signal_combiner.py",
        ],
        "docs": ["docs/07_guides/LUNA_PROMPT_B_ARCHITECTURE_2026_09_07.md"],
        "reason": "同名方法含不同可靠性、同日成交與輸出政策；沒有現行依賴證據支持默默切換。",
    },
    {
        "candidate": "legacy manual diagnostic scripts",
        "decision": "remove",
        "paths": [
            "tests/manual/legacy_diagnostics/check_columns.py",
            "tests/manual/legacy_diagnostics/check_processed_file.py",
            "tests/manual/legacy_diagnostics/check_saved_file.py",
            "tests/manual/legacy_diagnostics/check_signals_file.py",
            "tests/manual/legacy_diagnostics/run_market_index_test.py",
            "tests/manual/legacy_diagnostics/run_technical_calc_test.py",
            "tests/manual/legacy_diagnostics/run_tests.py",
        ],
        "tokens": ["legacy_diagnostics"],
        "tests": ["tests/test_full_app_healthcheck_test_inventory.py"],
        "docs": [
            "docs/06_qa/PROJECT_CONSOLIDATION_REVIEW_2026_09_07.md",
            "docs/07_guides/LUNA_PROMPT_B_ARCHITECTURE_2026_09_07.md",
        ],
        "reason": "固定正式資料路徑或失效 runner，現行清冊與 filesystem 均已證明不存在；不刪其他歷史 manual。",
    },
    {
        "candidate": "technical_indicators.clean_price_series nested duplicates",
        "decision": "defer",
        "paths": ["analysis_module/technical_analysis/technical_indicators.py"],
        "tokens": ["clean_price_series"],
        "tests": ["tests/test_technical_indicators.py"],
        "docs": ["docs/07_guides/LUNA_PROMPT_B_ARCHITECTURE_2026_09_07.md"],
        "reason": "AST 顯示同檔重複，但位於不同指標流程；需先建立輸入缺失／NaN parity oracle，避免把局部策略清理語意誤合。",
    },
)


def _run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed with exit {result.returncode}: "
            f"{result.stderr.decode('utf-8', errors='replace').strip()}"
        )
    return result.stdout.decode("utf-8", errors="surrogateescape")


def _git_paths(*args: str) -> list[str]:
    raw = _run_git(*args)
    return sorted(path for path in raw.split("\0") if path)


def _relative_path(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()


def _path_kind(relative_path: str) -> str:
    path = Path(relative_path)
    if relative_path == "tests" or relative_path.startswith("tests/"):
        return "tests"
    if relative_path == "scripts" or relative_path.startswith("scripts/"):
        return "scripts"
    if relative_path == "docs" or relative_path.startswith("docs/"):
        return "docs"
    if path.suffix.lower() in {".py", ".pyi", ".js", ".ts", ".tsx", ".java", ".sql"}:
        return "code"
    if path.suffix.lower() in {".md", ".rst", ".txt"}:
        return "docs"
    return "other"


def _read_text(relative_path: str) -> str | None:
    path = PROJECT_ROOT / relative_path
    try:
        if path.stat().st_size > 2_000_000:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _reference_evidence(paths: Sequence[str], tokens: Sequence[str]) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for token in tokens:
        callers: set[str] = set()
        tests: set[str] = set()
        docs: set[str] = set()
        occurrences = 0
        for relative_path in paths:
            if Path(relative_path).suffix.lower() not in _TEXT_SUFFIXES:
                continue
            content = _read_text(relative_path)
            if content is None:
                continue
            for line in content.splitlines():
                if token not in line:
                    continue
                occurrences += 1
                if relative_path.startswith("tests/"):
                    tests.add(relative_path)
                elif relative_path.startswith("docs/"):
                    docs.add(relative_path)
                else:
                    callers.add(relative_path)
        evidence[token] = {
            "occurrences": occurrences,
            "callers": sorted(callers),
            "tests": sorted(tests),
            "docs": sorted(docs),
        }
    return evidence


def _file_sha256(relative_path: str) -> str | None:
    path = PROJECT_ROOT / relative_path
    try:
        digest = sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    return digest


def _analysis_ast_duplicate_groups() -> list[list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    analysis_root = PROJECT_ROOT / "analysis_module"
    for path in analysis_root.rglob("*.py"):
        relative_path = _relative_path(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = ast.dump(
                ast.Module(body=node.body, type_ignores=[]),
                annotate_fields=True,
                include_attributes=False,
            )
            digest = sha256(body.encode("utf-8")).hexdigest()
            groups.setdefault(digest, []).append(
                {"path": relative_path, "name": node.name, "line": node.lineno}
            )
    return [
        sorted(items, key=lambda item: (item["path"], item["line"]))
        for items in groups.values()
        if len(items) > 1
    ]


def _dynamic_import_hits(paths: Sequence[str]) -> list[str]:
    hits: list[str] = []
    for relative_path in paths:
        if Path(relative_path).suffix.lower() not in {".py", ".pyi"}:
            continue
        content = _read_text(relative_path)
        if content is None:
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            if any(marker in line for marker in _DYNAMIC_IMPORT_MARKERS):
                hits.append(f"{relative_path}:{line_number}:{line.strip()}")
    return hits


def _classifications(paths: Sequence[str]) -> dict[str, list[str]]:
    visible = sorted(set(paths))
    return {
        "package_markers": [path for path in visible if Path(path).name == "__init__.py"],
        "compatibility_facades": [
            path
            for path in visible
            if Path(path).suffix.lower() == ".py"
            and ("compat" in Path(path).stem.lower() or "_legacy" in path)
        ],
        "manual_scripts": [
            path
            for path in visible
            if path.startswith("tests/manual/") and Path(path).suffix.lower() == ".py"
        ],
        "formal_tests": [
            path
            for path in visible
            if path.startswith("tests/")
            and Path(path).suffix.lower() == ".py"
            and "formal" in Path(path).stem.lower()
        ],
        "qa_evidence": [
            path
            for path in visible
            if path.startswith("docs/06_qa/")
        ],
    }


def _candidate_reviews(visible_paths: Sequence[str]) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for candidate in _CANDIDATE_REVIEWS:
        paths = sorted(set(visible_paths) | set(candidate["paths"]))
        reviews.append(
            {
                **candidate,
                "sha256": {
                    path: _file_sha256(path) for path in candidate["paths"]
                },
                "reference_evidence": _reference_evidence(paths, candidate["tokens"]),
                "path_presence": {
                    path: (PROJECT_ROOT / path).exists() for path in candidate["paths"]
                },
            }
        )
    return reviews


def _write_path_manifest(output_path: Path, kind: str, paths: Iterable[str]) -> str:
    manifest_path = output_path.with_name(f"{output_path.stem}.{kind}.txt")
    manifest_path.write_text("\n".join(paths) + "\n", encoding="utf-8")
    return str(manifest_path)


def build_repo_map() -> dict[str, Any]:
    tracked = _git_paths("ls-files", "-z")
    untracked = _git_paths("ls-files", "--others", "--exclude-standard", "-z")
    ignored = _git_paths("ls-files", "--others", "--ignored", "--exclude-standard", "-z")
    dirty_status = [
        line for line in _run_git("status", "--short", "--untracked-files=all").splitlines()
        if line.strip()
    ]
    visible = sorted(set(tracked) | set(untracked))
    category_counts = Counter(_path_kind(path) for path in visible)
    return {
        "schema_version": "luna-b-repo-map.v1",
        "project_root": str(PROJECT_ROOT),
        "git": {
            "head": _run_git("rev-parse", "HEAD").strip(),
            "branch": _run_git("branch", "--show-current").strip(),
            "tracked_count": len(tracked),
            "untracked_count": len(untracked),
            "ignored_count": len(ignored),
            "dirty_path_count": len(dirty_status),
            "dirty_status_lines": dirty_status,
        },
        "path_manifests": {
            "tracked": tracked,
            "untracked": untracked,
            "ignored_sample": ignored[:200],
        },
        "visible_path_counts": dict(sorted(category_counts.items())),
        "classifications": _classifications(visible),
        "analysis_ast_duplicate_groups": _analysis_ast_duplicate_groups(),
        "dynamic_import_hits": _dynamic_import_hits(visible),
        "candidate_reviews": _candidate_reviews(visible),
        "existing_graphify": {
            "path": "graphify-out/graph.json",
            "exists": (PROJECT_ROOT / "graphify-out" / "graph.json").exists(),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the read-only LUNA B repository map")
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args(argv)
    output_path = args.output_json
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = build_repo_map()
    report["path_manifests"]["tracked_file"] = _write_path_manifest(
        output_path, "tracked", report["path_manifests"].pop("tracked")
    )
    report["path_manifests"]["untracked_file"] = _write_path_manifest(
        output_path, "untracked", report["path_manifests"].pop("untracked")
    )
    report["path_manifests"]["ignored_file"] = _write_path_manifest(
        output_path, "ignored", _git_paths("ls-files", "--others", "--ignored", "--exclude-standard", "-z")
    )
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    counts = report["visible_path_counts"]
    git_counts = report["git"]
    print(
        "LUNA B repo map: "
        f"tracked={git_counts['tracked_count']} "
        f"untracked={git_counts['untracked_count']} "
        f"ignored={git_counts['ignored_count']} "
        f"code={counts.get('code', 0)} docs={counts.get('docs', 0)} "
        f"tests={counts.get('tests', 0)} scripts={counts.get('scripts', 0)}"
    )
    print(f"JSON: {output_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
