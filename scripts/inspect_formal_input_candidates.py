"""唯讀盤點 Formal/ML input 候選 manifest，絕不升格或改接正式輸入。

這個工具補足 ``inspect_ml_formal_input_readiness.py`` 的一個操作缺口：
readiness inspector 必須只相信 owner 明確指定的三個 path，因此不會掃描
release／prospective 目錄。候選盤點則要求呼叫端明確指定一個候選根目錄，
只讀取 bounded 的 ``manifest.json``，把研究 artifact、prospective staging、
正式 schema candidate 與無關 manifest 分類，讓 owner 看見「目前找到什麼、
為什麼仍不能消費」而不會誤以為檔案存在就等於 formal ready。

不讀取資料列、不執行 loader、不建立 SQLite、不修改環境變數、不寫正式資料。
報告輸出必須位於候選根目錄之外，避免把盤點結果混進受觀察的資料樹。
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


READINESS_SCHEMA_VERSION = "ml-formal-input-candidate-inventory.v1"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_MANIFESTS = 512
EXPECTED_SCHEMA_BY_INPUT = {
    "causal_non_cash_portfolio_ledger": "causal-portfolio-ledger.v1",
    "formal_rule_champion_snapshot_history": "rule-champion-snapshot-history.v1",
    "pit_sector_membership": "pit-sector-membership-sidecar-v1",
}
_PROSPECTIVE_MARKERS = (
    "prospective-formal",
    "prospective_formal",
    "prospectiveformal",
)
_RESEARCH_MARKERS = (
    "research",
    "shadow",
    "fixture",
)
_SAFE_FIELDS = (
    "schema_version",
    "status",
    "mode",
    "consumer_mode",
    "scope",
    "formal_consumer_compatible",
    "formal_oos_allowed",
    "research_only",
    "promotion_eligible",
    "production_action_allowed",
    "direct_training_input",
    "decision_date_count",
    "non_cash_state_day_count",
    "sample_count",
    "row_count",
    "coverage_start",
    "coverage_end",
    "training_as_of",
    "target_cli",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _safe_projection(payload: Mapping[str, object]) -> dict[str, object]:
    """保留有限的 manifest facts，不把任意欄位或 secret 帶入報告。"""

    result: dict[str, object] = {}
    for field_name in _SAFE_FIELDS:
        value = payload.get(field_name)
        if isinstance(value, (str, bool, int)):
            result[field_name] = value
    causal_ledger = payload.get("causal_ledger")
    if isinstance(causal_ledger, Mapping):
        nested: dict[str, object] = {}
        for field_name in (
            "schema_version",
            "non_cash_state_day_count",
            "decision_day_count",
            "formal_consumer_compatible",
            "formal_oos_allowed",
            "research_only",
        ):
            value = causal_ledger.get(field_name)
            if isinstance(value, (str, bool, int)):
                nested[field_name] = value
        if nested:
            result["causal_ledger"] = nested
    return result


def _path_tokens(path: Path) -> tuple[str, ...]:
    return tuple(part.casefold().replace("-", "_") for part in path.parts)


def _classify_manifest(
    path: Path,
    payload: Mapping[str, object],
) -> tuple[str, str, str | None]:
    """回傳 lane、穩定原因與可能對應的正式 input 名稱。"""

    schema = (_text(payload.get("schema_version")) or "").casefold()
    mode = " ".join(
        item.casefold()
        for item in (
            _text(payload.get("mode")) or "",
            _text(payload.get("consumer_mode")) or "",
            _text(payload.get("scope")) or "",
        )
    )
    tokens = _path_tokens(path)
    path_text = " ".join(tokens)
    prospective = any(marker in schema or marker in mode for marker in _PROSPECTIVE_MARKERS)
    prospective = prospective or any(
        marker in path_text for marker in ("formal_prospective", "prospective_formal")
    )
    if prospective:
        lane = "prospective_only"
        reason = "prospective_artifact_is_diagnostic_only"
    else:
        nested_ledger = payload.get("causal_ledger")
        nested_schema = (
            _text(nested_ledger.get("schema_version"))
            if isinstance(nested_ledger, Mapping)
            else None
        )
        research = payload.get("research_only") is True
        research = research or any(marker in schema for marker in _RESEARCH_MARKERS)
        research = research or any(marker in path_text for marker in _RESEARCH_MARKERS)
        research = research or (
            nested_schema is not None and "research" in nested_schema.casefold()
        )
        if research:
            lane = "research_only"
            reason = "research_artifact_cannot_be_promoted_to_formal"
        elif schema in {
            value.casefold() for value in EXPECTED_SCHEMA_BY_INPUT.values()
        }:
            lane = "formal_schema_candidate"
            reason = "formal_schema_observed_but_owner_custody_and_loader_validation_required"
        else:
            lane = "other"
            reason = "manifest_is_not_one_of_the_three_formal_input_schemas"

    candidate_input = None
    for input_name, expected_schema in EXPECTED_SCHEMA_BY_INPUT.items():
        if schema == expected_schema.casefold():
            candidate_input = input_name
            break
    if candidate_input is None:
        nested_ledger = payload.get("causal_ledger")
        nested_schema = (
            _text(nested_ledger.get("schema_version"))
            if isinstance(nested_ledger, Mapping)
            else None
        )
        if nested_schema and nested_schema.casefold() == "research-causal-baseline-ledger.v1":
            candidate_input = "causal_non_cash_portfolio_ledger"
            reason = "research_causal_ledger_not_formal_source"
    return lane, reason, candidate_input


def _walk_manifest_paths(root: Path, *, limit: int) -> tuple[list[Path], bool]:
    paths: list[Path] = []
    truncated = False
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in {".git", "__pycache__"}
        )
        if "manifest.json" not in files:
            continue
        path = Path(current) / "manifest.json"
        paths.append(path)
        if len(paths) >= limit:
            truncated = True
            break
    return sorted(paths, key=lambda item: str(item).casefold()), truncated


def inspect_candidates(
    *,
    candidate_root: Path,
    max_manifests: int = MAX_MANIFESTS,
) -> dict[str, Any]:
    root = candidate_root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    if not isinstance(max_manifests, int) or not 1 <= max_manifests <= MAX_MANIFESTS:
        raise ValueError(f"max_manifests must be between 1 and {MAX_MANIFESTS}")

    paths, truncated = _walk_manifest_paths(root, limit=max_manifests)
    candidates: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    for path in paths:
        relative = path.relative_to(root)
        relative_text = relative.as_posix()
        try:
            size = path.stat().st_size
            if size > MAX_MANIFEST_BYTES:
                skipped.append(
                    {
                        "path": relative_text,
                        "reason": "manifest_too_large",
                        "size_bytes": size,
                    }
                )
                continue
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, Mapping):
                raise TypeError("manifest JSON must be an object")
            lane, reason, candidate_input = _classify_manifest(path, payload)
            row: dict[str, object] = {
                "path": relative_text,
                "manifest_sha256": _sha256(path),
                "size_bytes": size,
                "lane": lane,
                "reason": reason,
                "candidate_input": candidate_input,
                "formal_consumer_compatible": payload.get("formal_consumer_compatible")
                if isinstance(payload.get("formal_consumer_compatible"), bool)
                else None,
                "formal_oos_allowed": payload.get("formal_oos_allowed")
                if isinstance(payload.get("formal_oos_allowed"), bool)
                else None,
                "safe_projection": _safe_projection(payload),
            }
            candidates.append(row)
        except (OSError, UnicodeError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            skipped.append(
                {
                    "path": relative_text,
                    "reason": "manifest_unreadable_or_invalid",
                    "error_type": type(error).__name__,
                }
            )

    lane_counts = Counter(str(item["lane"]) for item in candidates)
    input_counts = Counter(
        str(item["candidate_input"])
        for item in candidates
        if item.get("candidate_input")
    )
    expected_schema_observed = {
        input_name: sum(
            item.get("candidate_input") == input_name
            and item.get("lane") == "formal_schema_candidate"
            for item in candidates
        )
        for input_name in EXPECTED_SCHEMA_BY_INPUT
    }
    return {
        "schema_version": READINESS_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate_root": str(root),
        "read_only": True,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
        "promotion_eligible": False,
        "manifest_limit": max_manifests,
        "manifest_count": len(candidates),
        "skipped_count": len(skipped),
        "truncated": truncated,
        "lane_counts": dict(sorted(lane_counts.items())),
        "candidate_input_counts": dict(sorted(input_counts.items())),
        "expected_schema_observed": expected_schema_observed,
        "formal_ready_input_count": 0,
        "candidates": candidates,
        "skipped": skipped,
        "next_action": (
            "將可用 machine evidence 交給 owner；由 owner-controlled publisher "
            "建立三份 expected schema manifest，再以 inspect_ml_formal_input_readiness.py "
            "做 loader／hash／cutoff 重驗。prospective／research candidate 不得改名或直接接線。"
        ),
    }


def _write_report(path: Path, payload: Mapping[str, object], *, root: Path) -> None:
    target = path.expanduser().resolve()
    if target == root or target.is_relative_to(root):
        raise ValueError("report output must be outside candidate_root")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--max-manifests", type=int, default=MAX_MANIFESTS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = inspect_candidates(
            candidate_root=args.candidate_root,
            max_manifests=args.max_manifests,
        )
        if args.output is not None:
            _write_report(args.output, report, root=Path(str(report["candidate_root"])))
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "schema_version": READINESS_SCHEMA_VERSION,
                    "status": "blocked",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "read_only": True,
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _configure_utf8_stdio() -> None:
    """讓 Windows CP1252 主控台也能安全輸出繁中診斷。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


if __name__ == "__main__":
    raise SystemExit(main())
