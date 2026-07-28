"""每日人工 MOPS 研究用財報發布 Freshness、Outage 與 Revision 診斷 CLI 腳本。

僅輸出至顯式 TEMP／shadow root；支援離線 Fixture 比對與顯式 live唯讀抓取模式。
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.mops_daily_research_freshness import (
    run_mops_daily_freshness_diagnostics,
)
from data_module.mops_ezsearch_statement_availability import (
    MOPSQueryResult,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", type=date.fromisoformat, required=True, help="YYYY-MM-DD")
    parser.add_argument("--output-root", type=Path, required=True, help="TEMP 輸出根目錄")
    parser.add_argument("--prior-artifact", type=Path, help="先前 immutable run artifact JSON 路徑")
    parser.add_argument("--expected-through", type=date.fromisoformat, help="預期涵蓋截止日 YYYY-MM-DD")
    parser.add_argument("--live", action="store_true", help="啟用 MOPS 官方 HTTPS 唯讀查詢")
    parser.add_argument("--confirm-live-readonly", action="store_true", help="確認為 live 唯讀查詢")
    parser.add_argument("--fixture-file", type=Path, help="離線測試用的 query results fixture JSON 路徑")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args(argv)

    if args.live and not args.confirm-live-readonly:
        parser.error("使用 --live 時必須同時指定 --confirm-live-readonly")

    query_results: list[MOPSQueryResult] | None = None
    if args.fixture_file:
        if not args.fixture_file.is_file():
            parser.error(f"fixture file not found: {args.fixture_file}")
        query_results = _load_fixture(args.fixture_file)

    res = run_mops_daily_freshness_diagnostics(
        start_date=args.start_date,
        end_date=args.end_date,
        output_root=args.output_root,
        query_results=query_results,
        prior_artifact_path=args.prior_artifact,
        expected_through_date=args.expected_through,
        live_readonly=args.live and args.confirm-live-readonly,
        timeout_seconds=args.timeout_seconds,
    )

    print(json.dumps(res.summary, ensure_ascii=False, indent=2))
    return res.exit_code


def _load_fixture(path: Path) -> list[MOPSQueryResult]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("fixture root must be a list of MOPSQueryResult objects")
    results = []
    for item in data:
        results.append(
            MOPSQueryResult(
                market=str(item["market"]),
                announcement_item=str(item["announcement_item"]),
                rows=tuple(dict(r) for r in item.get("rows", [])),
                response_sha256=str(item.get("response_sha256", "")),
                source_status=str(item.get("source_status", "success")),
            )
        )
    return results


if __name__ == "__main__":
    raise SystemExit(main())
