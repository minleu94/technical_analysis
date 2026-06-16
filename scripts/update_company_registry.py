from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from requests import RequestException

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.company_registry import (
    build_company_registry_rows,
    write_company_registry_csv,
)
from data_module.config import TWStockConfig

TWSE_LISTED_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_OTC_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
TPEX_EMERGING_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_R"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run or apply official TWSE/TPEX companies.csv registry update."
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--backup-dir", type=Path, default=None)
    parser.add_argument("--source-json-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", choices=["apply-company-registry"], default=None)
    args = parser.parse_args(argv)

    config = TWStockConfig()
    output = args.output or (config.meta_data_dir / "companies.csv")
    backup_dir = args.backup_dir or config.backup_dir
    download_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sources = _load_sources(args.source_json_dir)

    result = build_company_registry_rows(
        twse_rows=sources["twse_listed"],
        tpex_rows=sources["tpex_otc"],
        emerging_rows=sources["tpex_emerging"],
        download_time=download_time if args.source_json_dir is None else "2026-06-16 12:00:00",
    )

    if args.apply:
        if args.confirm != "apply-company-registry":
            print("Applying company registry requires --confirm apply-company-registry")
            return 2
        if not result.ready_for_apply:
            print(result.to_markdown())
            for diagnostic in result.diagnostics:
                print(f"- {diagnostic.code}: {diagnostic.stock_code} {diagnostic.message}".rstrip())
            return 1
        backup_file = _backup_existing(output, backup_dir)
        write_company_registry_csv(output, result.rows)
        print(result.to_markdown())
        print(f"- applied: true")
        print(f"- output: {output}")
        print(f"- backup_file: {backup_file or 'none'}")
        return 0

    print(result.to_markdown())
    print(f"- output: {output}")
    for diagnostic in result.diagnostics:
        print(f"- {diagnostic.code}: {diagnostic.stock_code} {diagnostic.message}".rstrip())
    return 0 if result.ready_for_apply else 1


def _load_sources(source_json_dir: Path | None) -> dict[str, list[dict[str, Any]]]:
    if source_json_dir is not None:
        source_json_dir = Path(source_json_dir)
        return {
            "twse_listed": _load_json_file(source_json_dir / "twse_listed.json"),
            "tpex_otc": _load_json_file(source_json_dir / "tpex_otc.json"),
            "tpex_emerging": _load_json_file(source_json_dir / "tpex_emerging.json"),
        }
    return {
        "twse_listed": _fetch_json(TWSE_LISTED_URL),
        "tpex_otc": _fetch_json(TPEX_OTC_URL),
        "tpex_emerging": _fetch_json(TPEX_EMERGING_URL),
    }


def _fetch_json(url: str) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                raise ValueError(f"official registry response is not a list: {url}")
            return data
        except (RequestException, ValueError) as exc:
            last_error = exc
    raise RuntimeError(f"failed to fetch official registry after retries: {url}: {last_error}")


def _load_json_file(path: Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"source json is not a list: {path}")
    return data


def _backup_existing(output: Path, backup_dir: Path) -> Path | None:
    output = Path(output)
    if not output.exists():
        return None
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / f"{output.stem}_company_registry_{datetime.now().strftime('%Y%m%d_%H%M%S')}{output.suffix}"
    shutil.copy2(output, backup_file)
    return backup_file


if __name__ == "__main__":
    raise SystemExit(main())
