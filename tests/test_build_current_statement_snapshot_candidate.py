"""Current quarterly statement candidate is bounded, Decimal and PIT explicit."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from scripts.apply_current_statement_snapshot import apply_candidate, review_candidate
from scripts.build_current_statement_snapshot_candidate import build_candidate


def test_builder_handles_mixed_tpex_identity_and_marks_income_ytd(tmp_path: Path) -> None:
    openapi = tmp_path / "openapi"
    openapi.mkdir()
    income = [
        {
            "出表日期": "1150909",
            "年度": "115",
            "季別": "2",
            "公司代號": "1101",
            "公司名稱": "台泥",
            "營業收入": "1,234.00",
            "基本每股盈餘（元）": "0.38",
        }
    ]
    balance = [
        {
            "Date": "1150908",
            "年度": "115",
            "季別": "2",
            "SecuritiesCompanyCode": "1240",
            "CompanyName": "茂生農經",
            "資產總計": "99.00",
        }
    ]
    _write_json(openapi / "twse_income.json", income)
    _write_json(openapi / "tpex_balance.json", balance)
    manifest = {
        "schema_version": "official-openapi-statement-endpoints.v1",
        "captured_at": "2026-09-08T10:00:00+00:00",
        "endpoints": {
            "twse_income.json": _endpoint(openapi / "twse_income.json", "twse", "income"),
            "tpex_balance.json": _endpoint(openapi / "tpex_balance.json", "tpex", "balance"),
        },
    }
    _write_json(openapi / "endpoint_manifest.json", manifest)
    availability = tmp_path / "availability"
    availability.mkdir()
    _write_mapping(
        availability / "mapping.csv",
        [
            ("1101", "income_statement"),
            ("1240", "balance_sheet"),
        ],
    )

    output = tmp_path / "candidate"
    result = build_candidate(
        openapi_root=openapi,
        availability_roots=(availability,),
        output_root=output,
        period="2026-Q2",
        observed_at=datetime(2026, 9, 8, 10, tzinfo=timezone.utc),
    )

    assert result["coverage"]["current_stock_count"] == 2
    assert result["coverage"]["current_identity_missing_announcement_evidence_count"] == 0
    assert result["source_policy"]["formal_pit_eligible"] is False
    with (output / "statement_current_observations.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    income_rows = [row for row in rows if row["stock_code"] == "1101"]
    assert income_rows
    assert all(row["item_code"].startswith("income_statement:") for row in income_rows)
    assert all("損益表:YTD:" in row["item_name"] for row in income_rows)
    assert next(row for row in income_rows if "每股" in row["item_name"])["unit"] == "TWD/share"
    assert next(row for row in income_rows if "營業收入" in row["item_name"])["value"] == "1234000.00"
    balance_row = next(row for row in rows if row["stock_code"] == "1240")
    assert balance_row["item_code"].startswith("balance_sheet:")
    assert balance_row["item_name"].startswith("資產負債表:期末:")


def test_builder_quarantines_conflicting_duplicate_values(tmp_path: Path) -> None:
    openapi = tmp_path / "openapi"
    openapi.mkdir()
    first = [
        {"出表日期": "1150909", "年度": "115", "季別": "2", "公司代號": "1101", "營業收入": "1"}
    ]
    second = [
        {"出表日期": "1150909", "年度": "115", "季別": "2", "公司代號": "1101", "營業收入": "2", "營業成本": "3"}
    ]
    _write_json(openapi / "first.json", first)
    _write_json(openapi / "second.json", second)
    _write_json(
        openapi / "endpoint_manifest.json",
        {
            "captured_at": "2026-09-08T10:00:00+00:00",
            "endpoints": {
                "first.json": _endpoint(openapi / "first.json", "twse", "income"),
                "second.json": _endpoint(openapi / "second.json", "twse", "income"),
            },
        },
    )
    availability = tmp_path / "availability"
    availability.mkdir()
    _write_mapping(availability / "mapping.csv", [("1101", "income_statement")])

    result = build_candidate(
        openapi_root=openapi,
        availability_roots=(availability,),
        output_root=tmp_path / "candidate",
        period="2026-Q2",
        observed_at=datetime(2026, 9, 8, 10, tzinfo=timezone.utc),
    )
    assert result["diagnostics"]["conflicting_value_count"] == 1
    with (tmp_path / "candidate" / "statement_current_observations.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    assert not any(row["item_code"] == "income_statement:營業收入" for row in rows)
    assert any(row["item_code"] == "income_statement:營業成本" for row in rows)


def test_apply_review_and_sqlite_backup_are_safe(tmp_path: Path) -> None:
    openapi = tmp_path / "openapi"
    openapi.mkdir()
    source = [
        {"出表日期": "1150909", "年度": "115", "季別": "2", "公司代號": "1101", "營業收入": "1"}
    ]
    _write_json(openapi / "income.json", source)
    _write_json(
        openapi / "endpoint_manifest.json",
        {
            "captured_at": "2026-09-08T10:00:00+00:00",
            "endpoints": {"income.json": _endpoint(openapi / "income.json", "twse", "income")},
        },
    )
    availability = tmp_path / "availability"
    availability.mkdir()
    _write_mapping(availability / "mapping.csv", [("1101", "income_statement")])
    output = tmp_path / "candidate"
    build_candidate(
        openapi_root=openapi,
        availability_roots=(availability,),
        output_root=output,
        period="2026-Q2",
        observed_at=datetime(2026, 9, 8, 10, tzinfo=timezone.utc),
    )
    candidate = output / "statement_current_observations.csv"
    manifest = output / "statement_current_candidate.json"
    reviewed = review_candidate(candidate, manifest)
    assert reviewed["database_written"] is False

    database = tmp_path / "db.sqlite"
    sqlite3.connect(database).close()
    applied = apply_candidate(
        candidate=candidate,
        manifest=manifest,
        db_file=database,
        backup_dir=tmp_path / "backup",
    )
    assert applied["inserted_count"] == 1
    with sqlite3.connect(database) as connection:
        value = connection.execute(
            "SELECT value FROM fundamental_current_observations WHERE stock_code='1101'"
        ).fetchone()[0]
        assert value == "1000"
    with sqlite3.connect(applied["backup"]) as backup:
        assert backup.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_apply_review_rejects_future_observed_at(tmp_path: Path) -> None:
    openapi = tmp_path / "openapi"
    openapi.mkdir()
    source = [
        {"出表日期": "1150909", "年度": "115", "季別": "2", "公司代號": "1101", "營業收入": "1"}
    ]
    _write_json(openapi / "income.json", source)
    _write_json(
        openapi / "endpoint_manifest.json",
        {
            "captured_at": "2026-09-08T10:00:00+00:00",
            "endpoints": {"income.json": _endpoint(openapi / "income.json", "twse", "income")},
        },
    )
    availability = tmp_path / "availability"
    availability.mkdir()
    _write_mapping(availability / "mapping.csv", [("1101", "income_statement")])
    output = tmp_path / "candidate"
    build_candidate(
        openapi_root=openapi,
        availability_roots=(availability,),
        output_root=output,
        period="2026-Q2",
        observed_at=datetime(2026, 9, 8, 10, tzinfo=timezone.utc),
    )
    candidate = output / "statement_current_observations.csv"
    manifest = output / "statement_current_candidate.json"
    text = candidate.read_text(encoding="utf-8-sig").replace(
        "2026-09-08T10:00:00+00:00", "2099-01-01T00:00:00+00:00"
    )
    candidate.write_text(text, encoding="utf-8-sig", newline="")
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["artifacts"]["observations_csv_sha256"] = (
        "sha256:" + hashlib.sha256(candidate.read_bytes()).hexdigest()
    )
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="future observed_at"):
        review_candidate(candidate, manifest)


def _endpoint(path: Path, exchange: str, statement_type: str) -> dict[str, object]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "exchange": exchange,
        "statement_type": statement_type,
        "endpoint": "fixture",
        "url": f"https://example.invalid/{path.name}",
        "http_status": 200,
        "byte_count": path.stat().st_size,
        "sha256": digest,
        "row_count": 1,
        "status": "ok",
    }


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_mapping(path: Path, identities: list[tuple[str, str]]) -> None:
    fieldnames = [
        "stock_code",
        "statement_type",
        "period",
        "as_of_date",
        "announced_date",
        "available_date",
        "source",
        "source_version",
        "availability_contract_version",
        "evidence_class",
        "source_hash",
        "revision",
        "parent_revision",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for stock_code, statement_type in identities:
            writer.writerow(
                {
                    "stock_code": stock_code,
                    "statement_type": statement_type,
                    "period": "2026-Q2",
                    "as_of_date": "2026-06-30",
                    "announced_date": "2026-08-12",
                    "available_date": "2026-08-13",
                    "source": "mops.ezsearch.statement_publication",
                    "source_version": "fixture",
                    "availability_contract_version": "formal-availability.v2",
                    "evidence_class": "official_announcement",
                    "source_hash": "sha256:" + "1" * 64,
                    "revision": "1",
                    "parent_revision": "",
                }
            )
