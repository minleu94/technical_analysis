"""Build one TEMP-only numeric PIT candidate from official MOPS raw responses.

This tool deliberately captures a bounded company/quarter.  It keeps the MOPS
ratio response and the MOPS electronic-document listing as immutable raw files,
then records their hashes separately from the derived candidate.  It never
writes FA_Data, SQLite, recommendation, or formal-evidence state.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any, Mapping

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.config import TWStockConfig
from development_module.output_guard import validate_development_output_root
from scripts.validate_mops_quarterly_artifact import validate_artifact


MOPS_RATIO_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t163sb06"
MOPS_RATIO_PAGE_URL = "https://mopsov.twse.com.tw/mops/web/t163sb06"
MOPS_DOCUMENT_URL = "https://doc.twse.com.tw/server-java/t57sb01"
_STOCK_CODE_RE = re.compile(r"^\d{4,6}$")
_ROC_PERIOD_RE = re.compile(r"(\d{3})\s*年\s*第([一二三四])季")
_ROC_TIMESTAMP_RE = re.compile(r"(\d{3})/(\d{2})/(\d{2})\s+(\d{2}:\d{2}:\d{2})")
_QUARTER_NUMBER = {"一": 1, "二": 2, "三": 3, "四": 4}


class _TableRowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag.lower() == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def parse_ratio_rows(html_text: str) -> list[dict[str, Any]]:
    """Parse MOPS t163sb06 values using Decimal, never float."""
    parser = _TableRowParser()
    parser.feed(html_text)
    rows: list[dict[str, Any]] = []
    for cells in parser.rows:
        if len(cells) != 7 or not _STOCK_CODE_RE.fullmatch(cells[0]):
            continue
        revenue = _scaled_integer(cells[2], scale=100_000_000, field="revenue_million_twd")
        gross_margin = _scaled_integer(cells[3], scale=100, field="gross_margin_pct")
        operating_margin = _scaled_integer(cells[4], scale=100, field="operating_margin_pct")
        pretax_margin = _scaled_integer(cells[5], scale=100, field="pretax_margin_pct")
        net_margin = _scaled_integer(cells[6], scale=100, field="net_margin_pct")
        raw_cells = {
            "stock_code": cells[0],
            "company_name": cells[1],
            "revenue_million_twd": cells[2],
            "gross_margin_pct": cells[3],
            "operating_margin_pct": cells[4],
            "pretax_margin_pct": cells[5],
            "net_margin_pct": cells[6],
        }
        rows.append(
            {
                **raw_cells,
                "source_row_sha256": _canonical_sha256(raw_cells),
                "statement_items": {
                    "revenue_twd_cents": revenue,
                    "gross_margin_bp": gross_margin,
                    "operating_margin_bp": operating_margin,
                    "pretax_margin_bp": pretax_margin,
                    "net_margin_bp": net_margin,
                },
            }
        )
    if not rows:
        raise ValueError("MOPS t163sb06 response has no parseable numeric rows")
    return rows


def parse_listing_event(listing_html: bytes, *, stock_code: str, roc_year: int, season: int) -> dict[str, str]:
    """Extract the exact Chinese consolidated report row and its upload timestamp."""
    text = listing_html.decode("big5", errors="strict")
    parser = _TableRowParser()
    parser.feed(text)
    target_period = f"{roc_year} 年 第{'一二三四'[season - 1]}季"
    matches = [
        row for row in parser.rows
        if len(row) >= 11
        and row[0] == stock_code
        and target_period.replace(" ", "") in row[1].replace(" ", "")
        and row[5] == "IFRSs合併財報"
    ]
    if len(matches) != 1:
        raise ValueError("MOPS document listing must contain exactly one Chinese consolidated report row")
    cells = matches[0]
    timestamp = _ROC_TIMESTAMP_RE.fullmatch(cells[9])
    if timestamp is None:
        raise ValueError("MOPS document listing upload timestamp is invalid")
    correction = cells[10]
    if correction != "無":
        raise ValueError("MOPS document listing reports a correction; separate correction lineage is required")
    period_match = _ROC_PERIOD_RE.fullmatch(cells[1].replace(" ", ""))
    if period_match is None:
        raise ValueError("MOPS document listing period is invalid")
    return {
        "stock_code": stock_code,
        "period": f"{int(period_match.group(1)) + 1911}-Q{_QUARTER_NUMBER[period_match.group(2)]}",
        "period_end": _period_end(int(period_match.group(1)) + 1911, season).isoformat(),
        "publication_timestamp": _roc_timestamp_to_iso(
            (
                str(timestamp.group(1)),
                str(timestamp.group(2)),
                str(timestamp.group(3)),
                str(timestamp.group(4)),
            )
        ),
        "document_filename": cells[7],
        "document_size_bytes": cells[8].replace(",", ""),
        "correction_status": "none",
        "listing_row_sha256": _canonical_sha256(cells),
    }


def build_candidate(
    *,
    stock_code: str,
    roc_year: int,
    season: int,
    market: str,
    output_root: Path,
    run_id: str,
    canonical_manifest: Path,
    canonical_dataset: Path,
    timeout_seconds: int,
) -> dict[str, Path]:
    if not _STOCK_CODE_RE.fullmatch(stock_code):
        raise ValueError("stock_code must be a 4-to-6 digit security identifier")
    if season not in {1, 2, 3, 4}:
        raise ValueError("season must be 1 through 4")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,80}", run_id):
        raise ValueError("run_id must be 3-81 lowercase letters, digits, hyphens, or underscores")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    config = TWStockConfig()
    safe_root = validate_development_output_root(
        output_root,
        data_root=Path(config.data_root),
        formal_db=Path(config.db_file),
    )
    target = (safe_root / run_id).resolve()
    if target.exists():
        raise ValueError("run output already exists; immutable candidates must use a new run_id")
    for path in (canonical_manifest, canonical_dataset):
        if not path.is_file():
            raise ValueError(f"canonical input does not exist: {path}")

    captured_at = datetime.now(timezone.utc).isoformat()
    safe_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{run_id}.staging-", dir=safe_root))
    try:
        raw_dir = staging / "raw"
        raw_dir.mkdir()
        ratio_response = _fetch_ratio_response(market=market, roc_year=roc_year, season=season, timeout_seconds=timeout_seconds)
        listing_response = _fetch_listing_response(stock_code=stock_code, roc_year=roc_year, timeout_seconds=timeout_seconds)
        ratio_path = raw_dir / f"mops_t163sb06_{market}_{roc_year}Q{season}.html"
        listing_path = raw_dir / f"mops_t57sb01_{stock_code}_{roc_year}.html"
        ratio_path.write_bytes(ratio_response)
        listing_path.write_bytes(listing_response)

        numeric_rows = parse_ratio_rows(ratio_response.decode("utf-8", errors="strict"))
        numeric_row = next((row for row in numeric_rows if row["stock_code"] == stock_code), None)
        if numeric_row is None:
            raise ValueError("MOPS numeric ratio response does not contain the requested stock")
        listing_event = parse_listing_event(
            listing_response,
            stock_code=stock_code,
            roc_year=roc_year,
            season=season,
        )

        numeric_source = {
            "schema_version": "mops-t163sb06-numeric-source.v1",
            "source_id": "mops.t163sb06.financial_ratio",
            "source_version": "mops-t163sb06.v1",
            "source_url": MOPS_RATIO_URL,
            "request": {"TYPEK": market, "year": str(roc_year), "season": str(season)},
            "captured_at": captured_at,
            "raw_response": {
                "basename": ratio_path.name,
                "sha256": _file_sha256_reference(ratio_path),
                "byte_count": ratio_path.stat().st_size,
            },
            "rows": [numeric_row],
            "research_only": True,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
        }
        numeric_source_path = staging / "numeric-source.json"
        _write_json(numeric_source_path, numeric_source)

        availability = {
            "schema_version": "mops-document-listing-availability.v1",
            "source_id": "mops.document_listing.statement_publication",
            "source_version": "mops-t57sb01.v1",
            "source_url": _listing_url(stock_code=stock_code, roc_year=roc_year),
            "captured_at": captured_at,
            "raw_response": {
                "basename": listing_path.name,
                "sha256": _file_sha256_reference(listing_path),
                "byte_count": listing_path.stat().st_size,
            },
            "rows": [listing_event],
            "research_only": True,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
        }
        availability_path = staging / "availability-source.json"
        _write_json(availability_path, availability)

        available_date = (date.fromisoformat(listing_event["publication_timestamp"][:10]) + timedelta(days=1)).isoformat()
        manifest_hash = _file_sha256_reference(canonical_manifest)
        dataset_hash = _file_sha256_reference(canonical_dataset)
        coverage = _canonical_coverage(
            dataset=json.loads(canonical_dataset.read_text(encoding="utf-8")),
            stock_code=stock_code,
            available_date=available_date,
        )
        candidate_row = {
            "stock_code": stock_code,
            "symbol": stock_code,
            "statement_type": "financial_ratio",
            "statement_scope": "consolidated",
            "period": listing_event["period"],
            "period_end": listing_event["period_end"],
            "announcement_date": listing_event["publication_timestamp"],
            "publication_timestamp": listing_event["publication_timestamp"],
            "available_date": available_date,
            "revision": 1,
            "parent_revision": None,
            "revision_basis": "first immutable research capture of current MOPS listing state",
            "correction_status": listing_event["correction_status"],
            "correction_evidence": "MOPS t57sb01 listing correction column is 無",
            "content_hash": numeric_row["source_row_sha256"],
            "numeric_source_row_sha256": f"sha256:{numeric_row['source_row_sha256']}",
            "availability_event_sha256": f"sha256:{listing_event['listing_row_sha256']}",
            "statement_items": numeric_row["statement_items"],
        }
        candidate = {
            "schema_version": "mops-numeric-pit-candidate.v1",
            "source_id": "mops.statement.publication",
            "source_version": "mops-t163sb06-with-t57sb01-publication.v1",
            "captured_at": captured_at,
            "research_only": True,
            "read_only_source": True,
            "formal_oos_allowed": False,
            "formal_credit_authorized": False,
            "production_scheduler_allowed": False,
            "production_blend_alpha_bp": 0,
            "downstream_eligibility": "none",
            "rows": [candidate_row],
            "pit_coverage_summary": {
                "numeric_pit_ratios_supplied": True,
                **coverage,
                "coverage_interpretation": "bounded single-stock historical candidate; not a full-universe feature materialization",
            },
            "lineage": {
                "numeric_statement_source": {
                    "source_id": numeric_source["source_id"],
                    "source_version": numeric_source["source_version"],
                    "artifact_sha256": _file_sha256_reference(numeric_source_path),
                },
                "availability_artifact_sha256": _file_sha256_reference(availability_path),
                "canonical_dataset_lineage": {
                    "manifest_sha256": manifest_hash,
                    "dataset_sha256": dataset_hash,
                },
                "revision_correction_policy": "listing-reported correction status only; later captures must compare immutable prior candidates",
            },
        }
        candidate_path = staging / "numeric-pit-candidate.json"
        _write_json(candidate_path, candidate)
        validate_artifact(candidate)

        manifest = {
            "schema_version": "mops-numeric-pit-run-manifest.v1",
            "run_id": run_id,
            "captured_at": captured_at,
            "files": {
                "numeric_source": _file_sha256_reference(numeric_source_path),
                "availability_source": _file_sha256_reference(availability_path),
                "candidate": _file_sha256_reference(candidate_path),
                "raw_numeric_response": _file_sha256_reference(ratio_path),
                "raw_listing_response": _file_sha256_reference(listing_path),
            },
            "research_only": True,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
        }
        manifest_path = staging / "run-manifest.json"
        _write_json(manifest_path, manifest)
        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "output_directory": target,
        "candidate": target / "numeric-pit-candidate.json",
        "manifest": target / "run-manifest.json",
    }


def _fetch_ratio_response(*, market: str, roc_year: int, season: int, timeout_seconds: int) -> bytes:
    response = requests.post(
        MOPS_RATIO_URL,
        data={"step": "1", "firstin": "true", "off": "1", "isQuery": "Y", "TYPEK": market, "year": str(roc_year), "season": str(season)},
        headers={"Referer": MOPS_RATIO_PAGE_URL, "User-Agent": "technical-analysis-research-readonly/1.0"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    if b"\xe5\x85\xac\xe5\x8f\xb8\xe4\xbb\xa3\xe8\x99\x9f" not in response.content:
        raise ValueError("MOPS t163sb06 response does not contain the expected table header")
    return response.content


def _fetch_listing_response(*, stock_code: str, roc_year: int, timeout_seconds: int) -> bytes:
    response = requests.get(
        _listing_url(stock_code=stock_code, roc_year=roc_year),
        headers={"User-Agent": "technical-analysis-research-readonly/1.0"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    if b"IFRSs" not in response.content:
        raise ValueError("MOPS document listing does not contain financial-report rows")
    return response.content


def _listing_url(*, stock_code: str, roc_year: int) -> str:
    return f"{MOPS_DOCUMENT_URL}?step=1&colorchg=1&mtype=A&co_id={stock_code}&year={roc_year}"


def _canonical_coverage(*, dataset: Mapping[str, Any], stock_code: str, available_date: str) -> dict[str, int]:
    rows = [row for key in ("fit_rows", "evaluation_rows") for row in dataset.get(key, []) if isinstance(row, Mapping)]
    symbols = {str(row.get("symbol", "")) for row in rows if str(row.get("symbol", ""))}
    matching_rows = [row for row in rows if str(row.get("symbol", "")) == stock_code]
    eligible_rows = [row for row in matching_rows if str(row.get("decision_date", "")) >= available_date]
    return {
        "canonical_dataset_row_count": len(rows),
        "canonical_dataset_symbol_count": len(symbols),
        "canonical_matching_symbol_count": int(stock_code in symbols),
        "canonical_matching_decision_row_count": len(matching_rows),
        "canonical_pit_eligible_row_count": len(eligible_rows),
        "canonical_pit_eligible_coverage_bp": _ratio_bp(len(eligible_rows), len(rows)),
    }


def _scaled_integer(value: str, *, scale: int, field: str) -> int:
    normalized = unescape(value).replace(",", "").strip()
    try:
        result = Decimal(normalized) * Decimal(scale)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"MOPS {field} is not a decimal value") from exc
    if result != result.to_integral_value():
        raise ValueError(f"MOPS {field} cannot be represented as an integer at the required scale")
    return int(result)


def _period_end(year: int, season: int) -> date:
    month = season * 3
    return date(year, month, (31, 30, 30, 31)[season - 1])


def _roc_timestamp_to_iso(parts: tuple[str, str, str, str]) -> str:
    year, month, day, clock = parts
    return f"{int(year) + 1911:04d}-{month}-{day}T{clock}+08:00"


def _canonical_sha256(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _file_sha256_reference(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


def _ratio_bp(numerator: int, denominator: int) -> int:
    return 0 if denominator == 0 else numerator * 10_000 // denominator


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-code", required=True)
    parser.add_argument("--roc-year", type=int, required=True)
    parser.add_argument("--season", type=int, required=True, choices=(1, 2, 3, 4))
    parser.add_argument("--market", required=True, choices=("sii", "otc", "rotc", "pub"))
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--canonical-manifest", type=Path, required=True)
    parser.add_argument("--canonical-dataset", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args(argv)
    paths = build_candidate(
        stock_code=args.stock_code,
        roc_year=args.roc_year,
        season=args.season,
        market=args.market,
        output_root=args.output_root,
        run_id=args.run_id,
        canonical_manifest=args.canonical_manifest,
        canonical_dataset=args.canonical_dataset,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps({key: str(value) for key, value in paths.items()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
