"""Build a research-only PIT source artifact from a saved MOPS document listing."""
from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any


SOURCE_ID = "mops.statement.publication"
SOURCE_VERSION = "mops-electronic-document-listing.v1"
LISTING_URL_PREFIX = "https://doc.twse.com.tw/server-java/t57sb01"


def build_artifact(*, listing_html: Path, primary_pdf: Path, captured_at: str) -> dict[str, Any]:
    """Parse one Chinese consolidated MOPS listing row; fail closed on ambiguity."""
    _parse_iso_timestamp(captured_at)
    text = listing_html.read_bytes().decode("big5")
    source_url = _extract_source_url(text)
    stock_code = _one(re.findall(r'name="co_id" value="(\d+)"', text), "stock code")
    company_rows = re.findall(
        r"<tr>\s*<td align=\"center\">" + re.escape(stock_code) + r"</td>(.*?)</tr>",
        text,
        re.DOTALL,
    )
    row = _one(
        [candidate for candidate in company_rows if "IFRSs合併財報" in candidate and "IFRSs英文版" not in candidate],
        "Chinese IFRSs consolidated report row",
    )
    year = int(_one(re.findall(r"(\d{3})\s*年\s*第[一二三四]季", row), "ROC year in report row"))
    filename = _one(re.findall(r'readfile2\([^)]*&quot;([^&]+\.pdf)&quot;', row), "primary document filename")
    if primary_pdf.name != filename:
        raise ValueError("primary PDF filename does not match MOPS listing")
    upload = _one(re.findall(r"(\d{3})/(\d{2})/(\d{2})\s+(\d{2}:\d{2}:\d{2})", row), "upload timestamp")
    announcement_at = _roc_timestamp_to_iso(upload)
    if not re.search(r">\s*無\s*</td>\s*$", row):
        raise ValueError("listing row is corrected or correction status is ambiguous")
    quarter = _one(re.findall(r"(第[一二三四]季)", row), "quarter")
    period, period_end = _period_for(year, quarter)
    listing_hash = _sha256_file(listing_html)
    document_hash = _sha256_file(primary_pdf)
    return {
        "source_id": SOURCE_ID,
        "source_version": SOURCE_VERSION,
        "captured_at": captured_at,
        "research_only": True,
        "formal_oos_allowed": False,
        "production_scheduler_allowed": False,
        "downstream_eligibility": "none",
        "source_url": source_url,
        "listing_sha256": listing_hash,
        "rows": [{
            "stock_code": stock_code,
            "statement_type": "financial_report",
            "statement_scope": "consolidated",
            "period": period,
            "period_end": period_end,
            "announcement_date": announcement_at,
            "available_date": announcement_at,
            "revision": 1,
            "content_hash": document_hash,
            "document_filename": filename,
            "document_size_bytes": primary_pdf.stat().st_size,
            "listing_sha256": listing_hash,
            "correction_status": "none",
        }],
    }


def _extract_source_url(text: str) -> str:
    value = _one(re.findall(r"<!-- saved from url=\(\d+\)(https://[^ ]+) -->", text), "saved source URL")
    if not value.startswith(LISTING_URL_PREFIX):
        raise ValueError("unexpected MOPS listing URL")
    return value


def _one(values: list[Any], label: str) -> Any:
    unique = list(dict.fromkeys(values))
    if len(unique) != 1:
        raise ValueError(f"expected exactly one {label}")
    return unique[0]


def _roc_timestamp_to_iso(parts: tuple[str, str, str, str]) -> str:
    year, month, day, clock = parts
    return f"{int(year) + 1911:04d}-{month}-{day}T{clock}+08:00"


def _period_for(roc_year: int, quarter: str) -> tuple[str, str]:
    number = {"第一季": 1, "第二季": 2, "第三季": 3, "第四季": 4}.get(quarter)
    if number is None:
        raise ValueError("unsupported quarter")
    end_month = number * 3
    end_day = (31, 30, 30, 31)[number - 1]
    gregorian_year = roc_year + 1911
    return f"{gregorian_year}-Q{number}", f"{gregorian_year:04d}-{end_month:02d}-{end_day:02d}"


def _parse_iso_timestamp(value: str) -> None:
    if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
        raise ValueError("captured_at must include a timezone")


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listing-html", type=Path, required=True)
    parser.add_argument("--primary-pdf", type=Path, required=True)
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args(argv)
    artifact = build_artifact(listing_html=args.listing_html, primary_pdf=args.primary_pdf, captured_at=args.captured_at)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
