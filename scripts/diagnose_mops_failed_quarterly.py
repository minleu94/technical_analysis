"""保存 bounded MOPS 失敗 child 的官方 raw 與 HTTP 診斷證據。

此工具只重現一個已達批次嘗試上限的失敗步驟：2881 的資產負債表 POST
與 1301 的 XBRL row-code POST。它不建立 candidate、不略過科目，也不寫入
正式資料；raw 與 evidence 只能寫入 repo output 的全新目錄，供 parser fixture
修正與後續 immutable child 重試使用。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.mops_statement_candidate_adapter import validate_research_output_path
from scripts.build_mops_statement_pit_candidate import (
    MOPS_STATEMENT_BASE_URL,
    MOPS_XBRL_URL,
    _decode_mops_xbrl,
    _normalize_item_name,
    parse_xbrl_item_codes,
)


def _sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request_evidence(
    *,
    output_dir: Path,
    name: str,
    method: str,
    url: str,
    request_kwargs: dict[str, Any],
    expected_title: str | None = None,
    xbrl: bool = False,
    timeout_seconds: int,
) -> dict[str, Any]:
    started_at = _utc_now()
    response = requests.request(
        method,
        url,
        timeout=timeout_seconds,
        **request_kwargs,
    )
    received_at = _utc_now()
    body = response.content
    raw_path = validate_research_output_path(output_dir / f"{name}.html")
    raw_path.write_bytes(body)
    text = body.decode(response.encoding or ("big5hkscs" if xbrl else "utf-8"), errors="replace")
    result: dict[str, Any] = {
        "name": name,
        "request_started_at": started_at,
        "response_received_at": received_at,
        "method": method,
        "request_url": response.url,
        "request": {
            key: value
            for key, value in request_kwargs.items()
            if key in {"params", "data", "headers"}
        },
        "http": {
            "status": response.status_code,
            "reason": response.reason,
            "content_type": response.headers.get("Content-Type"),
            "byte_count": len(body),
            "sha256": f"sha256:{_sha256_bytes(body)}",
        },
        "raw_path": str(raw_path),
        "body_prefix": re.sub(r"\s+", " ", text[:1200]).strip(),
        "research_only": True,
        "formal_oos_allowed": False,
    }
    if expected_title is not None:
        result["expected_title"] = expected_title
        result["expected_title_present"] = expected_title in text
        marker = re.search(r".{0,180}資產負債.{0,260}", text, flags=re.DOTALL)
        result["title_context"] = re.sub(r"\s+", " ", marker.group(0)).strip() if marker else None
    if xbrl:
        try:
            decoded = _decode_mops_xbrl(body)
            result["xbrl_metadata"] = _extract_xbrl_metadata(decoded)
            result["target_item_code_matches"] = _extract_target_item_matches(decoded)
        except Exception as error:
            result["xbrl_parse_error"] = f"{type(error).__name__}: {error}"
    return result


def _extract_xbrl_metadata(text: str) -> dict[str, Any]:
    from scripts.build_mops_statement_pit_candidate import parse_xbrl_metadata

    try:
        return parse_xbrl_metadata(text)
    except Exception as error:
        return {"parse_error": f"{type(error).__name__}: {error}"}


def _extract_target_item_matches(text: str) -> list[dict[str, Any]]:
    try:
        item_codes = parse_xbrl_item_codes(text)
    except Exception as error:
        return [{"parse_error": f"{type(error).__name__}: {error}"}]
    target = _normalize_item_name("權益─具證券性質之虛擬通貨")
    matches: list[dict[str, Any]] = []
    for normalized_name, details in item_codes.items():
        if "虛擬通貨" in normalized_name or normalized_name == target:
            matches.extend(
                {
                    "normalized_name": normalized_name,
                    "item_code": detail.item_code,
                    "official_item_name": detail.official_item_name,
                    "xbrl_concept": detail.xbrl_concept,
                    "reported_value": detail.reported_value,
                    "indent_depth": detail.indent_depth,
                }
                for detail in details
            )
    return matches


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    args = parser.parse_args(argv)
    if not 1 <= args.timeout_seconds <= 60:
        raise ValueError("timeout-seconds must be between 1 and 60")

    output_dir = args.output_dir.expanduser().resolve(strict=False)
    evidence_path = validate_research_output_path(output_dir / "evidence.json")
    output_dir.mkdir(parents=True, exist_ok=True)
    results = [
        _request_evidence(
            output_dir=output_dir,
            name="2881-sii-2026q2-balance-sheet",
            method="POST",
            url=f"{MOPS_STATEMENT_BASE_URL}/ajax_t164sb03",
            request_kwargs={
                "data": {
                    "encodeURIComponent": "1",
                    "step": "1",
                    "firstin": "1",
                    "off": "1",
                    "co_id": "2881",
                    "TYPEK": "sii",
                    "year": "115",
                    "season": "2",
                },
                "headers": {
                    "Referer": f"{MOPS_STATEMENT_BASE_URL}/t164sb03",
                    "User-Agent": "technical-analysis-research-readonly/1.0",
                },
            },
            expected_title="合併資產負債表",
            timeout_seconds=args.timeout_seconds,
        ),
        _request_evidence(
            output_dir=output_dir,
            name="1301-sii-2026q2-xbrl",
            method="GET",
            url=MOPS_XBRL_URL,
            request_kwargs={
                "params": {
                    "step": "1",
                    "CO_ID": "1301",
                    "SYEAR": "2026",
                    "SSEASON": "2",
                    "REPORT_ID": "C",
                },
                "headers": {"User-Agent": "technical-analysis-research-readonly/1.0"},
            },
            xbrl=True,
            timeout_seconds=args.timeout_seconds,
        ),
    ]
    evidence = {
        "schema_version": "v4-mops-failed-quarterly-diagnostic.v1",
        "captured_at": _utc_now(),
        "purpose": "diagnose bounded child failures without relaxing official title or row-code gates",
        "requests": results,
        "research_only": True,
        "formal_oos_allowed": False,
    }
    with evidence_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
