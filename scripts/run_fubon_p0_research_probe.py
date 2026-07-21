"""手動執行富邦唯讀 P0 research probe；只輸出指定 TEMP JSON。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.fubon_marketdata_research import (
    FubonResearchProjection,
    project_capital_changes,
    project_dividends,
    project_ticker,
)
from data_module.fubon_readonly_runtime import load_fubon_readonly_runtime

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", action="append", required=True, help="股票代號；可重複指定")
    parser.add_argument("--start-date", required=True, help="公司行動查詢起日 YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="公司行動查詢迄日 YYYY-MM-DD")
    parser.add_argument("--output", type=Path, required=True, help="明確指定 TEMP JSON 輸出位置")
    args = parser.parse_args(argv)

    credentials = _load_credentials()
    if credentials is None:
        print("missing Fubon read-only credentials (environment or Windows Credential Manager)")
        return 2

    from fubon_neo.sdk import FubonSDK

    sdk = FubonSDK()
    login = sdk.apikey_login(
        credentials.personal_id,
        credentials.api_key,
        credentials.cert_path,
        credentials.cert_pass,
    )
    if not login.is_success:
        print(f"login failed: {login.message}")
        return 1
    sdk.init_realtime()
    stock = sdk.marketdata.rest_client.stock
    fetched_at = datetime.now(timezone.utc)
    projections: list[FubonResearchProjection] = []
    for symbol in dict.fromkeys(args.symbol):
        ticker = stock.intraday.ticker(symbol=symbol)
        quote = stock.intraday.quote(symbol=symbol)
        projections.append(project_ticker(ticker, fetched_at=fetched_at, quote_payload=quote))

    # v2.2.8 documented corporate-action endpoints.  Attribute lookup fails closed
    # if an installed SDK is older than the declared source version.
    corporate_actions = stock.corporate_actions
    dividends = corporate_actions.dividends(start_date=args.start_date, end_date=args.end_date)
    capital_changes = corporate_actions.capital_changes(start_date=args.start_date, end_date=args.end_date)
    projections.extend(
        (
            project_dividends(_data_rows(dividends), fetched_at=fetched_at),
            project_capital_changes(_data_rows(capital_changes), fetched_at=fetched_at),
        )
    )
    result = _combine(projections, fetched_at)
    _write_temp_json(args.output, result.to_dict())
    print(f"research-only Fubon P0 projection written: {args.output}")
    return 0


def _load_credentials():
    from keyring import get_password
    import os

    return load_fubon_readonly_runtime(os.environ, get_password)


def _data_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Fubon corporate-actions response must contain data array")
    rows = payload["data"]
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("Fubon corporate-actions data contains non-object row")
    return rows


def _combine(projections: list[FubonResearchProjection], fetched_at: datetime) -> FubonResearchProjection:
    observations = tuple(row for projection in projections for row in projection.observations)
    diagnostics = tuple(dict.fromkeys(diagnostic for projection in projections for diagnostic in projection.diagnostics))
    return FubonResearchProjection(observations=observations, diagnostics=diagnostics)


def _write_temp_json(path: Path, payload: dict[str, Any]) -> None:
    target = path.resolve(strict=False)
    if target.suffix.lower() != ".json":
        raise ValueError("output must be a .json TEMP artifact")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
