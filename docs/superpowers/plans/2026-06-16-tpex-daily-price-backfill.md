# TPEX Daily Price Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a controlled TPEX daily price backfill workflow so OTC stocks such as `3207` can enter `daily_prices` without faking company registry or fundamental records.

**Architecture:** Add a small data module that normalizes TPEX OpenAPI quote rows into the existing `daily_prices` schema, plans inserts on a DB working copy, and applies only with explicit confirmation plus DB backup. The workflow writes only `daily_prices`; it does not alter `companies.csv`, fundamental tables, technical indicators, or recommendation scoring.

**Tech Stack:** Python, pytest, SQLite, `requests`, `Decimal`, `pathlib.Path`, existing `TWStockConfig`.

---

## File Structure

- Create `data_module/tpex_daily_price_backfill.py`: normalize TPEX rows, build dry-run plans, apply `daily_prices` upserts with backup / rollback.
- Create `scripts/backfill_tpex_daily_prices.py`: CLI for source-json dry-run, official endpoint dry-run, and guarded apply.
- Create `tests/test_tpex_daily_price_backfill.py`: unit tests for parser, duplicate handling, and DB upsert.
- Create `tests/test_tpex_daily_price_backfill_cli.py`: CLI tests for dry-run no-write and apply confirmation.
- Modify docs:
  - `docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md`
  - `docs/07_guides/APPLICATION_MANUAL.md`
  - `docs/00_core/PROJECT_SNAPSHOT.md`
  - `docs/00_core/ROADMAP_6M_ENGINEERING.md`
  - `docs/01_architecture/system_architecture.md`

## Task 1: TPEX Parser and Plan

**Files:**
- Create: `data_module/tpex_daily_price_backfill.py`
- Test: `tests/test_tpex_daily_price_backfill.py`

- [x] **Step 1: Write failing parser tests**

Create `tests/test_tpex_daily_price_backfill.py`:

```python
import sqlite3
from pathlib import Path

from data_module.tpex_daily_price_backfill import (
    build_tpex_daily_price_plan,
    normalize_tpex_daily_price_rows,
)


def test_normalize_tpex_daily_price_rows_maps_quote_fields():
    result = normalize_tpex_daily_price_rows(
        [
            {
                "Date": "1150616",
                "SecuritiesCompanyCode": "3207",
                "CompanyName": "耀勝",
                "Close": "42.50",
                "Open": "42.00",
                "High": "43.00",
                "Low": "41.50",
                "TradingShares": "1,234,000",
                "TransactionAmount": "52,445,000",
                "TransactionNumber": "901",
                "Change": "+0.50",
                "LastBestBidPrice": "42.45",
                "LastBestBidVolume": "3",
                "LastBestAskPrice": "42.50",
                "LastBestAskVolume": "2",
                "PERatio": "12.34",
            }
        ],
        fallback_date="2026-06-16",
    )

    assert result.diagnostics == ()
    assert result.rows == (
        {
            "日期": "20260616",
            "證券代號": "3207",
            "證券名稱": "耀勝",
            "成交股數": 1234000,
            "成交筆數": 901,
            "成交金額": 52445000,
            "開盤價": "42.00",
            "最高價": "43.00",
            "最低價": "41.50",
            "收盤價": "42.50",
            "漲跌": "+",
            "漲跌價差": "0.50",
            "最後揭示買價": "42.45",
            "最後揭示買量": 3,
            "最後揭示賣價": "42.50",
            "最後揭示賣量": 2,
            "本益比": "12.34",
        },
    )


def test_normalize_tpex_daily_price_rows_reports_invalid_price():
    result = normalize_tpex_daily_price_rows(
        [
            {
                "Date": "1150616",
                "SecuritiesCompanyCode": "3207",
                "CompanyName": "耀勝",
                "Close": "--",
            }
        ],
        fallback_date="2026-06-16",
    )

    assert result.rows == ()
    assert result.diagnostics[0].code == "tpex_daily_price.invalid_price"


def test_build_tpex_daily_price_plan_skips_existing_rows(tmp_path):
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            'CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT, "收盤價" REAL, PRIMARY KEY ("證券代號", "日期"))'
        )
        conn.execute('INSERT INTO daily_prices ("日期", "證券代號", "收盤價") VALUES ("20260616", "3207", 40.0)')

    result = build_tpex_daily_price_plan(
        db_file=db_file,
        source_rows=[
            {
                "Date": "1150616",
                "SecuritiesCompanyCode": "3207",
                "CompanyName": "耀勝",
                "Close": "42.50",
            }
        ],
        fallback_date="2026-06-16",
    )

    assert result.ready_for_apply is False
    assert result.existing_count == 1
    assert result.insert_count == 0
```

- [x] **Step 2: Run parser tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_tpex_daily_price_backfill.py -q -o addopts=
```

Expected: collection fails with `ModuleNotFoundError: No module named 'data_module.tpex_daily_price_backfill'`.

- [x] **Step 3: Implement parser and plan**

Create `data_module/tpex_daily_price_backfill.py` with these public APIs:

```python
@dataclass(frozen=True)
class TpexDailyPriceNormalizeResult:
    rows: tuple[dict[str, object], ...]
    diagnostics: tuple[FactorDiagnostic, ...] = ()


@dataclass(frozen=True)
class TpexDailyPriceBackfillPlan:
    rows: tuple[dict[str, object], ...]
    diagnostics: tuple[FactorDiagnostic, ...]
    existing_count: int
    insert_count: int
    db_file: Path

    @property
    def ready_for_apply(self) -> bool:
        return self.insert_count > 0 and not self.diagnostics
```

Implementation requirements:

- Accept both official English TPEX keys and common alternate keys:
  - stock: `SecuritiesCompanyCode`, `Code`
  - name: `CompanyName`, `CompanyAbbreviation`, `Name`
  - date: `Date`, fallback `fallback_date`
  - OHLC: `Open`, `High`, `Low`, `Close`
  - volume / amount / trades: `TradingShares`, `TransactionAmount`, `TransactionNumber`
  - bid / ask: `LastBestBidPrice`, `LastBestBidVolume`, `LastBestAskPrice`, `LastBestAskVolume`
  - P/E: `PERatio`, `PE`, `P/E`
- Parse ROC date `1150616` to `20260616`.
- Convert commas, blanks, `--`, `N/A`, and empty strings safely.
- Require a four-digit stock code and positive close price.
- Split signed change like `+0.50` into `漲跌="+"` and `漲跌價差="0.50"`.
- Use SQLite to skip rows already present by primary key `(證券代號, 日期)`.

- [x] **Step 4: Run parser tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_tpex_daily_price_backfill.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile data_module\tpex_daily_price_backfill.py
```

Expected: all tests pass and py_compile exits 0.

- [x] **Step 5: Commit parser milestone**

```powershell
git add data_module/tpex_daily_price_backfill.py tests/test_tpex_daily_price_backfill.py
git commit -m "market-data: add tpex daily price backfill planner"
```

## Task 2: Guarded CLI and Apply

**Files:**
- Modify: `data_module/tpex_daily_price_backfill.py`
- Create: `scripts/backfill_tpex_daily_prices.py`
- Test: `tests/test_tpex_daily_price_backfill_cli.py`

- [x] **Step 1: Add failing apply and CLI tests**

Append to `tests/test_tpex_daily_price_backfill.py`:

```python
from data_module.tpex_daily_price_backfill import apply_tpex_daily_price_backfill


def test_apply_tpex_daily_price_backfill_inserts_rows_and_backs_up(tmp_path):
    db_file = tmp_path / "twstock.db"
    backup_dir = tmp_path / "backup"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            'CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT, "證券名稱" TEXT, "收盤價" REAL, PRIMARY KEY ("證券代號", "日期"))'
        )

    result = apply_tpex_daily_price_backfill(
        db_file=db_file,
        backup_dir=backup_dir,
        source_rows=[
            {
                "Date": "1150616",
                "SecuritiesCompanyCode": "3207",
                "CompanyName": "耀勝",
                "Close": "42.50",
            }
        ],
        fallback_date="2026-06-16",
    )

    assert result.applied is True
    assert result.backup_file is not None
    assert result.backup_file.exists()
    with sqlite3.connect(db_file) as conn:
        rows = conn.execute('SELECT "證券代號", "日期", "收盤價" FROM daily_prices').fetchall()
    assert rows == [("3207", "20260616", 42.5)]
```

Create `tests/test_tpex_daily_price_backfill_cli.py`:

```python
import json
import sqlite3

from scripts.backfill_tpex_daily_prices import main


def test_tpex_daily_price_cli_dry_run_does_not_write(tmp_path, capsys):
    db_file = tmp_path / "twstock.db"
    source_json = tmp_path / "tpex.json"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            'CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT, "證券名稱" TEXT, "收盤價" REAL, PRIMARY KEY ("證券代號", "日期"))'
        )
    source_json.write_text(
        json.dumps([{"Date": "1150616", "SecuritiesCompanyCode": "3207", "CompanyName": "耀勝", "Close": "42.50"}]),
        encoding="utf-8",
    )

    exit_code = main(["--db-file", str(db_file), "--source-json", str(source_json), "--date", "2026-06-16", "--dry-run"])

    assert exit_code == 0
    assert "ready_for_apply: true" in capsys.readouterr().out
    with sqlite3.connect(db_file) as conn:
        assert conn.execute("SELECT count(*) FROM daily_prices").fetchone()[0] == 0


def test_tpex_daily_price_cli_apply_requires_confirm(tmp_path):
    db_file = tmp_path / "twstock.db"
    source_json = tmp_path / "tpex.json"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            'CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT, "證券名稱" TEXT, "收盤價" REAL, PRIMARY KEY ("證券代號", "日期"))'
        )
    source_json.write_text(
        json.dumps([{"Date": "1150616", "SecuritiesCompanyCode": "3207", "CompanyName": "耀勝", "Close": "42.50"}]),
        encoding="utf-8",
    )

    assert main(["--db-file", str(db_file), "--source-json", str(source_json), "--date", "2026-06-16", "--apply"]) == 2
```

- [x] **Step 2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_tpex_daily_price_backfill.py tests\test_tpex_daily_price_backfill_cli.py -q -o addopts=
```

Expected: import errors or missing `apply_tpex_daily_price_backfill`.

- [x] **Step 3: Implement apply and CLI**

Implement in `data_module/tpex_daily_price_backfill.py`:

```python
@dataclass(frozen=True)
class TpexDailyPriceBackfillApplyResult:
    applied: bool
    inserted_count: int
    backup_file: Path | None
    plan: TpexDailyPriceBackfillPlan


def apply_tpex_daily_price_backfill(*, db_file: Path, backup_dir: Path, source_rows: list[Mapping[str, object]], fallback_date: str) -> TpexDailyPriceBackfillApplyResult:
    plan = build_tpex_daily_price_plan(db_file=db_file, source_rows=source_rows, fallback_date=fallback_date)
    if not plan.ready_for_apply:
        return TpexDailyPriceBackfillApplyResult(False, 0, None, plan)
    backup_file = _backup_db(db_file, backup_dir)
    try:
        inserted_count = _insert_daily_price_rows(db_file, plan.rows)
    except Exception:
        shutil.copy2(backup_file, db_file)
        raise
    return TpexDailyPriceBackfillApplyResult(True, inserted_count, backup_file, plan)
```

Create `scripts/backfill_tpex_daily_prices.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.config import TWStockConfig
from data_module.tpex_daily_price_backfill import (
    apply_tpex_daily_price_backfill,
    build_tpex_daily_price_plan,
)

TPEX_DAILY_CLOSE_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run or apply TPEX daily price backfill.")
    parser.add_argument("--db-file", type=Path, default=None)
    parser.add_argument("--backup-dir", type=Path, default=None)
    parser.add_argument("--source-json", type=Path, default=None)
    parser.add_argument("--date", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", choices=["apply-tpex-daily-price-backfill"], default=None)
    args = parser.parse_args(argv)

    config = TWStockConfig()
    db_file = args.db_file or config.db_file
    backup_dir = args.backup_dir or config.backup_dir
    source_rows = _load_source_rows(args.source_json)

    if args.apply:
        if args.confirm != "apply-tpex-daily-price-backfill":
            print("Applying TPEX daily price backfill requires --confirm apply-tpex-daily-price-backfill")
            return 2
        result = apply_tpex_daily_price_backfill(
            db_file=db_file,
            backup_dir=backup_dir,
            source_rows=source_rows,
            fallback_date=args.date,
        )
        print(result.plan.to_markdown())
        print(f"- applied: {str(result.applied).lower()}")
        print(f"- inserted_count: {result.inserted_count}")
        print(f"- backup_file: {result.backup_file or 'none'}")
        return 0 if result.applied else 1

    plan = build_tpex_daily_price_plan(db_file=db_file, source_rows=source_rows, fallback_date=args.date)
    print(plan.to_markdown())
    for diagnostic in plan.diagnostics:
        print(f"- {diagnostic.code}: {diagnostic.stock_code} {diagnostic.message}".rstrip())
    return 0 if plan.ready_for_apply else 1


def _load_source_rows(source_json: Path | None) -> list[dict[str, Any]]:
    if source_json is not None:
        data = json.loads(Path(source_json).read_text(encoding="utf-8"))
    else:
        response = requests.get(TPEX_DAILY_CLOSE_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, list):
        raise ValueError("TPEX daily close response is not a list")
    return data


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 4: Run focused tests and py_compile**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_tpex_daily_price_backfill.py tests\test_tpex_daily_price_backfill_cli.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile data_module\tpex_daily_price_backfill.py scripts\backfill_tpex_daily_prices.py
```

Expected: all tests pass and py_compile exits 0.

- [x] **Step 5: Commit CLI milestone**

```powershell
git add data_module/tpex_daily_price_backfill.py scripts/backfill_tpex_daily_prices.py tests/test_tpex_daily_price_backfill.py tests/test_tpex_daily_price_backfill_cli.py
git commit -m "market-data: add guarded tpex daily price backfill cli"
```

## Task 3: Formal Dry-Run, Apply, Verification, Docs

**Files:**
- Modify docs listed in File Structure.

- [x] **Step 1: Run formal dry-run**

```powershell
.\.venv\Scripts\python.exe scripts\backfill_tpex_daily_prices.py --date 2026-06-16 --dry-run
```

Expected: output includes `ready_for_apply: true` if official endpoint has rows missing from SQLite. If endpoint has no rows or all rows already exist, stop and document the result.

- [x] **Step 2: Apply with explicit confirmation**

```powershell
.\.venv\Scripts\python.exe scripts\backfill_tpex_daily_prices.py --date 2026-06-16 --apply --confirm apply-tpex-daily-price-backfill
```

Expected: output includes a non-empty `backup_file`, `applied: true`, and `inserted_count > 0`.

- [x] **Step 3: Verify formal DB integrity**

Run a read-only SQLite check confirming:

- `daily_prices` has rows for `3207`.
- No duplicate `(證券代號, 日期)` keys.
- Existing `9935` rows remain present.
- Latest TPEX date inserted matches the CLI `--date` or normalized official row date.
- Formal DB backup exists.

- [x] **Step 4: Update docs**

Document:

- TPEX daily quote source and CLI.
- This backfill writes `daily_prices`, not `companies.csv` or fundamental tables.
- `3207` root cause and resolution status.
- Apply backup and verification results.

- [x] **Step 5: Run final verification**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_tpex_daily_price_backfill.py tests\test_tpex_daily_price_backfill_cli.py tests\test_update_service_status.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile data_module\tpex_daily_price_backfill.py scripts\backfill_tpex_daily_prices.py
git status --short --branch
```

- [x] **Step 6: Commit docs and formal verification**

```powershell
git add docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md docs/07_guides/APPLICATION_MANUAL.md docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/01_architecture/system_architecture.md
git commit -m "docs: document tpex daily price backfill"
```

## Final Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_tpex_daily_price_backfill.py tests\test_tpex_daily_price_backfill_cli.py tests\test_update_service_status.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile data_module\tpex_daily_price_backfill.py scripts\backfill_tpex_daily_prices.py
git status --short --branch
```

The branch is complete only after formal apply, read-only DB verification, docs sync, and all commits are present.
