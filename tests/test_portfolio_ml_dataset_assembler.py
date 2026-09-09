from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from data_module import portfolio_ml_dataset_assembler as assembler_module
from data_module.ml_pit_year_shard_exporter import (
    PITYearShardBuildRequest,
    PITYearShardExporter,
)
from data_module.official_market_event_backfill import (
    OfficialMarketEventBackfillBuilder,
    OfficialMarketEventBackfillRequest,
)
from data_module.portfolio_ml_dataset_assembler import (
    SECTOR_MEMBERSHIP_MANIFEST_SCHEMA_VERSION,
    SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
    PortfolioMLDatasetAssembler,
    PortfolioMLDatasetAssemblyRequest,
    _CurrentFeatureCache,
    _Label,
    _advance_current_features,
    _base_feature_definitions,
    _build_cash_only_portfolio_state_replay,
    _build_label_spool,
    _current_values,
    _initialize_spool,
    _insert_observations,
    _insert_prices,
    _load_corporate_action_custody,
    _required_json_bool,
    _spool_sector_memberships,
    _teacher_candidates,
    _validate_raw_dataset_manifest,
)
from tests.test_corporate_action_availability_history import (
    _OFFICIAL_FIXTURE_ROOT,
    _OfficialFixtureFetcher,
)
from scripts.train_ml_allocation_copilot import (
    _load_frozen_shard,
    _merge_shards,
    main as train_main,
)


# 小型合成資料驗證使用可控容量；實體低空間另由專用capacity tests驗證。
pytestmark = pytest.mark.usefixtures("synthetic_ml_capacity")


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE daily_prices (
                日期 TEXT NOT NULL,
                證券代號 TEXT NOT NULL,
                證券名稱 TEXT,
                成交股數 INTEGER,
                開盤價 TEXT,
                最高價 TEXT,
                最低價 TEXT,
                收盤價 TEXT,
                本益比 TEXT
            );
            CREATE TABLE market_indices (
                日期 TEXT NOT NULL,
                指數名稱 TEXT NOT NULL,
                開盤價 TEXT,
                最高價 TEXT,
                最低價 TEXT,
                收盤價 TEXT
            );
            CREATE TABLE fundamental_monthly_revenues (
                stock_code TEXT NOT NULL,
                period TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                revenue TEXT,
                available_at TEXT,
                first_observed_at TEXT,
                revision_id TEXT,
                quality TEXT
            );
            """
        )
        start = date(2024, 1, 1)
        stock_rows: list[tuple[object, ...]] = []
        market_rows: list[tuple[object, ...]] = []
        for index in range(240):
            day = (start + timedelta(days=index)).strftime("%Y%m%d")
            market_open = 1000 + index
            market_close = market_open + 1
            market_rows.append(
                (
                    day,
                    "TAIEX",
                    str(market_open),
                    str(market_close + 2),
                    str(market_open - 2),
                    str(market_close),
                )
            )
            positive_open = 100 + index
            negative_open = 400 - index
            stock_rows.extend(
                (
                    (
                        day,
                        "2330",
                        "正向",
                        1_000_000 + index,
                        str(positive_open),
                        str(positive_open + 3),
                        str(positive_open - 2),
                        str(positive_open + 2),
                        None if index % 17 == 0 else "20.5",
                    ),
                    (
                        day,
                        "2317",
                        "反向",
                        900_000 + index,
                        str(negative_open),
                        str(negative_open + 2),
                        str(negative_open - 3),
                        str(negative_open - 1),
                        None if index % 19 == 0 else "12.0",
                    ),
                )
            )
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            stock_rows,
        )
        connection.executemany(
            "INSERT INTO market_indices VALUES (?, ?, ?, ?, ?, ?)",
            market_rows,
        )
        connection.executemany(
            """
            INSERT INTO fundamental_monthly_revenues VALUES
            (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    "2330",
                    "2024-01",
                    "2024-01-31",
                    "100.00",
                    "2024-02-20T18:00:00+08:00",
                    "2024-02-20T18:00:00+08:00",
                    "r1",
                    "accepted",
                ),
                (
                    "2330",
                    "2024-01",
                    "2024-01-31",
                    "110.00",
                    "2024-04-20T18:00:00+08:00",
                    "2024-04-20T18:00:00+08:00",
                    "r2",
                    "accepted",
                ),
            ),
        )


def _raw_publication(tmp_path: Path):
    database = tmp_path / "source.db"
    _database(database)
    return PITYearShardExporter().build(
        PITYearShardBuildRequest(
            database_path=database,
            output_root=tmp_path / "raw",
            decision_at="2024-09-01T08:30:00+08:00",
            history_start_date="2024-01-01",
            symbols=None,
            years=(2024,),
            batch_size=31,
        )
    )


def _raw_publication_with_partial_price_gap(tmp_path: Path):
    database = tmp_path / "source-partial-gap.db"
    _database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE daily_prices
            SET 最高價=NULL
            WHERE 日期='20240110' AND 證券代號='2330'
            """
        )
    return PITYearShardExporter().build(
        PITYearShardBuildRequest(
            database_path=database,
            output_root=tmp_path / "raw-partial-gap",
            decision_at="2024-09-01T08:30:00+08:00",
            history_start_date="2024-01-01",
            symbols=None,
            years=(2024,),
            batch_size=31,
        )
    )


def _official_corporate_action_publication(tmp_path: Path):
    payload = json.loads(
        (
            _OFFICIAL_FIXTURE_ROOT / "twse_twt49u_2024.json"
        ).read_text(encoding="utf-8")
    )
    fields = payload["fields"]
    payload["data"][0][fields.index("資料日期")] = "113年01月10日"
    payload["data"][0][fields.index("股票代號")] = "2330"
    payload["data"][0][fields.index("股票名稱")] = "台積電"
    override = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return OfficialMarketEventBackfillBuilder(
        fetcher=_OfficialFixtureFetcher(
            overrides={"twse_twt49u.v1": override}
        ),
        now=lambda: datetime(
            2026,
            7,
            30,
            16,
            30,
            tzinfo=timezone.utc,
        ),
        sleep=lambda _: None,
    ).build(
        OfficialMarketEventBackfillRequest(
            output_root=tmp_path / "official-market-events",
            start_year=2024,
            end_year=2024,
            request_delay_seconds=0,
        )
    )


def _records(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _manifest_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _sector_membership_row(
    *,
    symbol: str = "2330",
    sector_id: str = "SEMI",
    available_at: str = "2023-12-31T18:00:00+08:00",
    effective_from: str = "2024-01-01",
    status: str = "accepted",
    source_id: str = "twse:historical-sector-membership",
    license_id: str = "twse-open-data-license-v1",
    source_hash: str = "sha256:" + ("a" * 64),
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "sector_id": sector_id,
        "available_at": available_at,
        "effective_from": effective_from,
        "effective_to": None,
        "status": status,
        "source_id": source_id,
        "license_id": license_id,
        "source_hash": source_hash,
    }


def _write_sector_membership_sidecar(
    path: Path,
    rows: list[dict[str, object]],
) -> str:
    manifest_without_hash: dict[str, object] = {
        "schema_version": SECTOR_MEMBERSHIP_MANIFEST_SCHEMA_VERSION,
        "row_count": len(rows),
        "rows_hash": _manifest_hash(rows),
    }
    canonical_hash = _manifest_hash(
        {
            "sidecar_schema_version": (
                SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION
            ),
            "manifest": manifest_without_hash,
        }
    )
    payload = {
        "schema_version": SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
        "manifest": {
            **manifest_without_hash,
            "canonical_hash": canonical_hash,
        },
        "rows": rows,
    }
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return canonical_hash


def _horizon_poison_labels(
    *,
    poison_after_horizon: bool = False,
    omit_after_horizon: bool = False,
    corporate_action_effective_date: str | None = None,
    exclusion_sink: list[dict[str, object]] | None = None,
    progress_events: list[str] | None = None,
    batch_size: int = 100,
) -> dict[int, dict[str, object]]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    _initialize_spool(connection)
    start = date(2024, 1, 2)
    days = tuple(
        (start + timedelta(days=index)).isoformat()
        for index in range(7)
    )
    market_rows: list[tuple[object, ...]] = []
    stock_rows: list[tuple[object, ...]] = []
    for index, day in enumerate(days):
        available_at = f"{day}T16:00:00+08:00"
        market_open = 1_000 + index
        market_rows.append(
            (
                "market",
                "TAIEX",
                day,
                available_at,
                market_open,
                1,
                market_open + 3,
                1,
                market_open - 2,
                1,
                market_open + 1,
                1,
                f"sha256:{index + 1:064x}",
            )
        )
        if omit_after_horizon and index == 2:
            continue
        stock_open = 100 + index
        stock_high = stock_open + 4
        stock_low = stock_open - 3
        stock_close = stock_open + 2
        source_suffix = 100 + index
        if poison_after_horizon and index == 2:
            stock_high = 900
            stock_low = 10
            stock_close = 850
            source_suffix = 999
        stock_rows.append(
            (
                "stock",
                "2330",
                day,
                available_at,
                stock_open,
                1,
                stock_high,
                1,
                stock_low,
                1,
                stock_close,
                1,
                f"sha256:{source_suffix:064x}",
            )
        )
    _insert_prices(connection, (*market_rows, *stock_rows))
    connection.commit()
    _build_label_spool(
        connection=connection,
        benchmark_entity_id="TAIEX",
        cutoff=datetime.fromisoformat("2024-02-01T08:30:00+08:00"),
        horizons=(2, 4),
        batch_size=batch_size,
        corporate_action_effective_dates=(
            {}
            if corporate_action_effective_date is None
            else {"2330": (corporate_action_effective_date,)}
        ),
        progress_callback=(
            None if progress_events is None else progress_events.append
        ),
    )
    rows = tuple(
        connection.execute(
            """
            SELECT *
            FROM labels
            WHERE symbol='2330' AND decision_date=?
            ORDER BY horizon
            """,
            (days[0],),
        )
    )
    if exclusion_sink is not None:
        exclusion_sink.extend(
            {
                key: row[key]
                for key in row.keys()
            }
            for row in connection.execute(
                """
                SELECT *
                FROM label_exclusions
                WHERE symbol='2330' AND decision_date=?
                ORDER BY horizon
                """,
                (days[0],),
            )
        )
    connection.close()
    return {
        int(row["horizon"]): {
            key: row[key]
            for key in row.keys()
        }
        for row in rows
    }


def test_spool_prices_do_not_create_duplicate_primary_key_index() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        _initialize_spool(connection)
        indexes = {
            str(row[1])
            for row in connection.execute("PRAGMA index_list('prices')")
        }
        assert "idx_prices_scope_entity_date" not in indexes

        query_plan = list(
            connection.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT event_date FROM prices "
                "WHERE scope=? AND entity_key=? ORDER BY event_date",
                ("stock", "2330"),
            )
        )
        assert any(
            "PRIMARY KEY" in str(row[-1]).upper()
            for row in query_plan
        )
    finally:
        connection.close()


def test_assembler_emits_direct_training_jsonl_with_strict_pit_and_folds(
    tmp_path: Path,
    capsys,
) -> None:
    raw = _raw_publication(tmp_path)
    request = PortfolioMLDatasetAssemblyRequest(
        dataset_manifest_path=raw.dataset_manifest_paths[
            "all_field_enriched"
        ],
        output_root=tmp_path / "training",
        training_as_of="2024-09-01T08:30:00+08:00",
        benchmark_entity_id="TAIEX",
        minimum_train_dates=65,
        test_date_count=21,
        purge_trading_days=60,
        embargo_trading_days=5,
        batch_size=29,
    )

    publication = PortfolioMLDatasetAssembler().build(request)
    replay = PortfolioMLDatasetAssembler().build(request)

    assert replay.publication_id == publication.publication_id
    assert replay.manifest_hash == publication.manifest_hash
    manifest = json.loads(
        publication.manifest_path.read_text(encoding="utf-8")
    )
    assert manifest["direct_training_input"] is True
    assert manifest["fold_count"] >= 4
    assert manifest["safety"]["available_at_lte_decision_at"] is True
    assert manifest["safety"]["price_and_technical_t_minus_1"] is True
    assert manifest["safety"]["future_labels_only"] is True
    assert manifest["safety"]["same_day_advice_read"] is False
    assert manifest["safety"]["oracle_portfolio_state"] is False
    assert manifest["execution"]["raw_streaming_gzip_jsonl"] is True
    assert manifest["execution"]["temporary_sqlite_spool"] is True
    assert (
        "pit_sector_membership_missing_teacher_new_positions_disabled"
        in manifest["assembly_blockers"]
    )
    assert not tuple(request.output_root.glob(".portfolio-ml-*"))

    records = _records(publication.shard_paths[0])
    header = records[0]
    sample = records[1]["sample"]
    assert header["schema_version"] == "allocation-training-jsonl-v2"
    assert header["direct_training_input"] is True
    assert len(header["folds"]) >= 4
    assert all(
        fold["purge_trading_days"] >= 60
        and fold["embargo_trading_days"] >= 5
        for fold in header["folds"]
    )
    assert sample["row"]["decision_at"].endswith("08:30:00+08:00")
    assert (
        sample["row"]["portfolio_state"]["as_of_date"]
        < sample["row"]["decision_at"][:10]
    )
    assert sample["row"]["portfolio_state"]["weights"]["cash_bp"] == 10_000
    assert (
        sample["row"]["portfolio_state"]["weights"]["positions_bp"] == []
    )
    assert sample["row"]["targets"]["cash_bp"] == 10_000
    assert sample["row"]["targets"]["target_weights"]["positions_bp"] == []

    feature_by_id = {
        feature["feature_id"]: feature
        for feature in sample["row"]["features"]
    }
    close_feature = feature_by_id["daily_prices.收盤價"]
    assert close_feature["event_at"][:10] < sample["row"]["decision_at"][:10]
    assert close_feature["available_at"] <= sample["row"]["decision_at"]
    assert "daily_prices.本益比" in feature_by_id
    if not feature_by_id["daily_prices.本益比"]["observed"]:
        assert "price_liquidity_technical" in sample["row"]["missing_family_ids"]
    assert any(
        feature_id.startswith("data_quality.")
        for feature_id in feature_by_id
    )
    assert {
        label["horizon_trading_days"]
        for label in records[-1]["sample"]["horizon_labels"]
    } == {5, 10, 20, 60}
    assert all(
        label["available_at"] <= request.training_as_of
        for label in records[-1]["sample"]["horizon_labels"]
    )
    for label in records[-1]["sample"]["horizon_labels"]:
        assert isinstance(label["benchmark_excess_return_bp"], int)
        assert label["sector_excess_return_bp"] is None
        assert label["sector_excess_observed"] is False
        assert label["sector_excess_missing_reason"] in {
            "pit_sector_membership_unavailable_at_decision",
            "pit_sector_benchmark_price_unavailable",
        }
        assert isinstance(label["downside_observed"], bool)
        assert isinstance(label["mae_bp"], int)
        assert isinstance(label["mfe_bp"], int)
        assert isinstance(label["realized_volatility_bp"], int)
        assert isinstance(label["max_drawdown_bp"], int)
        assert isinstance(label["tail_loss_bp"], int)
        assert isinstance(label["fill_feasible_observed"], bool)
    samples = [
        record["sample"]
        for record in records
        if record["record_type"] == "sample"
        and record["sample"]["row"]["symbol"] == "2330"
    ]
    before_revision = next(
        row
        for row in samples
        if row["row"]["decision_at"].startswith("2024-03-01")
    )
    after_revision = next(
        row
        for row in samples
        if row["row"]["decision_at"].startswith("2024-05-01")
    )
    for formal_row in (before_revision, after_revision):
        assert all(
            feature["feature_id"]
            != "fundamental_monthly_revenues.revenue"
            for feature in formal_row["row"]["features"]
        ), "research-shadow revenue must not leak into formal training shards"

    frozen = _load_frozen_shard(publication.shard_paths[0])
    merged = _merge_shards((frozen,))
    assert frozen.direct_training_input is True
    assert len(merged.folds) >= 4
    assert all(fold.purge_trading_days >= 60 for fold in merged.folds)
    assert all(fold.embargo_trading_days >= 5 for fold in merged.folds)
    assert all(fold.train_rows and fold.test_rows for fold in merged.folds)

    training_artifact = tmp_path / "allocation.joblib"
    training_audit = tmp_path / "allocation.audit.json"
    training_manifest = tmp_path / "allocation.manifest.json"
    assert train_main(
        [
            "--input",
            str(publication.shard_paths[0]),
            "--artifact-output",
            str(training_artifact),
            "--audit-output",
            str(training_audit),
            "--manifest-output",
            str(training_manifest),
            "--hgb-max-iter",
            "2",
        ]
    ) == 0
    training_stdout = json.loads(capsys.readouterr().out)
    assert training_stdout["status"] == "training_completed"
    trained = json.loads(training_manifest.read_text(encoding="utf-8"))
    assert trained["production_alpha_bp"] == 0
    assert trained["production_action_allowed"] is False
    assert not any(
        blocker.startswith("actual_db_dataset_assembly_not_performed")
        for blocker in trained["blockers"]
    )


def test_assembler_consumes_shard_price_contract_without_bridging_labels(
    tmp_path: Path,
) -> None:
    raw = _raw_publication_with_partial_price_gap(tmp_path)
    raw_manifest = json.loads(
        raw.dataset_manifest_paths["all_field_enriched"].read_text(
            encoding="utf-8"
        )
    )
    raw_shard = (
        raw.dataset_manifest_paths["all_field_enriched"].parent.parent
        / raw_manifest["shards"][0]["path"]
    )
    raw_rows = _records(raw_shard)
    source_row = next(
        row
        for row in raw_rows
        if row["source_table"] == "daily_prices"
        and row["entity_id"] == "2330"
        and row["event_at"].startswith("2024-01-10")
        and "price_availability_contract" in row
    )
    assert source_row["price_availability_contract"]["status"] == (
        "price_unavailable"
    )

    publication = PortfolioMLDatasetAssembler().build(
        PortfolioMLDatasetAssemblyRequest(
            dataset_manifest_path=raw.dataset_manifest_paths[
                "all_field_enriched"
            ],
            output_root=tmp_path / "training-partial-gap",
            training_as_of="2024-09-01T08:30:00+08:00",
            benchmark_entity_id="TAIEX",
            minimum_train_dates=65,
            test_date_count=21,
            purge_trading_days=60,
            embargo_trading_days=5,
            batch_size=29,
        )
    )
    manifest = json.loads(
        publication.manifest_path.read_text(encoding="utf-8")
    )
    assert manifest["price_availability"]["gap_count"] == 1
    assert manifest["price_availability"]["formal_training_allowed"] is False
    assert manifest["safety"]["price_availability_contract_verified"] is True
    assert manifest["safety"]["price_gap_horizons_are_not_bridged"] is True

    records = _records(publication.shard_paths[0])
    samples = [
        record["sample"]
        for record in records
        if record["record_type"] == "sample"
        and record["sample"]["row"]["symbol"] == "2330"
    ]
    decisions = {
        sample["row"]["decision_at"][:10]
        for sample in samples
    }
    assert not decisions.intersection(
        {f"2024-01-{day:02d}" for day in range(6, 11)}
    )
    resumed = next(
        sample
        for sample in samples
        if sample["row"]["decision_at"].startswith("2024-01-11")
    )
    feature_by_id = {
        feature["feature_id"]: feature
        for feature in resumed["row"]["features"]
    }
    # The assembler consumes the partial shard row at the T-1 feature cutoff,
    # preserving the missing field instead of filling it from an older day.
    assert feature_by_id["daily_prices.最高價"]["observed"] is False
    assert feature_by_id["daily_prices.最高價"]["value_int"] is None
    assert {label["horizon_trading_days"] for label in resumed["horizon_labels"]} == {
        5,
        10,
        20,
        60,
    }


def test_assembler_rejects_research_only_raw_source_quality(
    tmp_path: Path,
) -> None:
    raw = _raw_publication(tmp_path)
    manifest_path = raw.dataset_manifest_paths["all_field_enriched"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_quality"] = {
        "research_only": True,
        "formal_training_allowed": False,
    }
    manifest.pop("manifest_hash")
    manifest["manifest_hash"] = _manifest_hash(manifest)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    request = PortfolioMLDatasetAssemblyRequest(
        dataset_manifest_path=manifest_path,
        output_root=tmp_path / "training-research-only",
        training_as_of="2024-09-01T08:30:00+08:00",
        benchmark_entity_id="TAIEX",
        minimum_train_dates=65,
        test_date_count=21,
        purge_trading_days=60,
        embargo_trading_days=5,
    )

    with pytest.raises(ValueError, match="research-only"):
        PortfolioMLDatasetAssembler().build(request)


def test_training_loader_rejects_research_only_source_quality(
    tmp_path: Path,
) -> None:
    raw = _raw_publication(tmp_path)
    publication = PortfolioMLDatasetAssembler().build(
        PortfolioMLDatasetAssemblyRequest(
            dataset_manifest_path=raw.dataset_manifest_paths[
                "all_field_enriched"
            ],
            output_root=tmp_path / "training-loader-research-only",
            training_as_of="2024-09-01T08:30:00+08:00",
            benchmark_entity_id="TAIEX",
            minimum_train_dates=65,
            test_date_count=21,
            purge_trading_days=60,
            embargo_trading_days=5,
        )
    )
    shard_path = publication.shard_paths[0]
    records = _records(shard_path)
    records[0]["source_quality"] = {
        "research_only": True,
        "formal_training_allowed": False,
    }
    with gzip.open(shard_path, "wt", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )

    with pytest.raises(ValueError, match="research-only"):
        _load_frozen_shard(shard_path)


def test_corporate_action_manifest_binds_identity_and_excludes_samples(
    tmp_path: Path,
) -> None:
    raw = _raw_publication(tmp_path)
    official = _official_corporate_action_publication(tmp_path)
    custody = _load_corporate_action_custody(
        official.manifest_path,
        training_as_of=datetime.fromisoformat(
            "2024-09-01T08:30:00+08:00"
        ),
    )
    assert custody.manifest_hash == official.manifest_hash
    assert custody.canonical_events_hash == official.canonical_events_hash
    assert custody.effective_dates_by_symbol["2330"] == ("2024-01-10",)
    assert custody.official_trade_restriction_timeline_present is True
    assert custody.trade_restriction_source_count == 2
    assert custody.trade_restriction_source_coverage_complete is True
    assert custody.trade_restriction_ambiguity_count == 0
    assert custody.trade_restriction_events_by_symbol["2330"]

    common = {
        "dataset_manifest_path": raw.dataset_manifest_paths[
            "all_field_enriched"
        ],
        "training_as_of": "2024-09-01T08:30:00+08:00",
        "benchmark_entity_id": "TAIEX",
        "minimum_train_dates": 65,
        "test_date_count": 21,
        "purge_trading_days": 60,
        "embargo_trading_days": 5,
        "batch_size": 29,
    }
    baseline = PortfolioMLDatasetAssembler().build(
        PortfolioMLDatasetAssemblyRequest(
            output_root=tmp_path / "training-baseline",
            **common,
        )
    )
    guarded = PortfolioMLDatasetAssembler().build(
        PortfolioMLDatasetAssemblyRequest(
            output_root=tmp_path / "training-corporate-action",
            corporate_action_manifest_path=official.manifest_path,
            **common,
        )
    )

    baseline_manifest = json.loads(
        baseline.manifest_path.read_text(encoding="utf-8")
    )
    guarded_manifest = json.loads(
        guarded.manifest_path.read_text(encoding="utf-8")
    )
    assert (
        baseline_manifest["dataset_identity_hash"]
        != guarded_manifest["dataset_identity_hash"]
    )
    assert guarded_manifest["corporate_action_custody"]["manifest_hash"] == (
        official.manifest_hash
    )
    assert guarded_manifest["corporate_action_excluded_label_count"] > 0
    assert (
        "corporate_action_adjustment_timeline_not_in_raw_publication_"
        "labels_are_research_shadow"
        not in guarded_manifest["assembly_blockers"]
    )
    assert (
        guarded_manifest["safety"][
            "corporate_action_affected_horizons_excluded"
        ]
        is True
    )
    assert (
        guarded_manifest["safety"][
            "post_event_corporate_action_used_as_feature"
        ]
        is False
    )
    assert [
        official.manifest_hash
    ] == [
        source_hash
        for source_id, source_hash in guarded_manifest[
            "source_manifest_hashes"
        ]
        if source_id == "sidecar:official_corporate_action_ledger"
    ]

    baseline_samples = [
        record["sample"]
        for record in _records(baseline.shard_paths[0])
        if record["record_type"] == "sample"
    ]
    guarded_records = _records(guarded.shard_paths[0])
    guarded_samples = [
        record["sample"]
        for record in guarded_records
        if record["record_type"] == "sample"
    ]
    assert any(
        sample["row"]["symbol"] == "2330"
        and sample["row"]["decision_at"].startswith("2024-01-02")
        for sample in baseline_samples
    )
    assert not any(
        sample["row"]["symbol"] == "2330"
        and sample["row"]["decision_at"].startswith("2024-01-02")
        for sample in guarded_samples
    )
    assert all(
        "corporate_action" not in feature["feature_id"]
        for sample in guarded_samples
        for feature in sample["row"]["features"]
    )
    header = guarded_records[0]
    assert header["corporate_action_custody"]["manifest_hash"] == (
        official.manifest_hash
    )
    assert (
        header["label_policy"][
            "post_event_corporate_action_used_as_feature"
        ]
        is False
    )


def test_assembler_accepts_canonical_accepted_sector_membership_sidecar(
    tmp_path: Path,
) -> None:
    raw = _raw_publication(tmp_path)
    sidecar_path = tmp_path / "pit_sector_membership.json"
    expected_manifest_hash = _write_sector_membership_sidecar(
        sidecar_path,
        [
            _sector_membership_row(),
            _sector_membership_row(
                symbol="2317",
                sector_id="ELECTRONICS",
                source_hash="sha256:" + ("b" * 64),
            ),
        ],
    )
    publication = PortfolioMLDatasetAssembler().build(
        PortfolioMLDatasetAssemblyRequest(
            dataset_manifest_path=raw.dataset_manifest_paths[
                "all_field_enriched"
            ],
            output_root=tmp_path / "training-with-sector",
            training_as_of="2024-09-01T08:30:00+08:00",
            benchmark_entity_id="TAIEX",
            sector_membership_path=sidecar_path,
            minimum_train_dates=65,
            test_date_count=21,
        )
    )

    manifest = json.loads(
        publication.manifest_path.read_text(encoding="utf-8")
    )
    assert manifest["sector_membership_count"] == 2
    assert manifest["sector_manifest_hash"] == expected_manifest_hash
    assert (
        "pit_sector_membership_missing_teacher_new_positions_disabled"
        not in manifest["assembly_blockers"]
    )
    assert manifest["safety"]["sector_membership_accepted_only"] is True
    assert (
        manifest["safety"][
            "sector_membership_canonical_manifest_verified"
        ]
        is True
    )
    assert (
        manifest["safety"]["current_company_snapshot_backfill_allowed"]
        is False
    )


@pytest.mark.parametrize(
    "status",
    ("research_shadow", "rejected", "unknown"),
)
def test_sector_membership_sidecar_rejects_nonaccepted_status(
    tmp_path: Path,
    status: str,
) -> None:
    sidecar_path = tmp_path / f"{status}.json"
    _write_sector_membership_sidecar(
        sidecar_path,
        [_sector_membership_row(status=status)],
    )
    connection = sqlite3.connect(":memory:")
    _initialize_spool(connection)

    with pytest.raises(
        ValueError,
        match="blocker:sector_membership_status_not_accepted",
    ):
        _spool_sector_memberships(
            connection,
            sidecar_path,
            training_as_of=datetime.fromisoformat(
                "2024-09-01T08:30:00+08:00"
            ),
        )
    connection.close()


@pytest.mark.parametrize(
    "missing_field",
    ("status", "source_id", "license_id", "source_hash"),
)
def test_sector_membership_sidecar_rejects_missing_custody_field(
    tmp_path: Path,
    missing_field: str,
) -> None:
    row = _sector_membership_row()
    row.pop(missing_field)
    sidecar_path = tmp_path / f"missing-{missing_field}.json"
    _write_sector_membership_sidecar(sidecar_path, [row])
    connection = sqlite3.connect(":memory:")
    _initialize_spool(connection)

    with pytest.raises(
        (TypeError, ValueError),
        match=missing_field,
    ):
        _spool_sector_memberships(
            connection,
            sidecar_path,
            training_as_of=datetime.fromisoformat(
                "2024-09-01T08:30:00+08:00"
            ),
        )
    connection.close()


def test_sector_membership_sidecar_rejects_missing_or_tampered_manifest(
    tmp_path: Path,
) -> None:
    legacy_path = tmp_path / "legacy-array.json"
    legacy_path.write_text(
        json.dumps([_sector_membership_row()]),
        encoding="utf-8",
    )
    connection = sqlite3.connect(":memory:")
    _initialize_spool(connection)
    with pytest.raises(TypeError, match="sidecar must be an object"):
        _spool_sector_memberships(connection, legacy_path)

    tampered_path = tmp_path / "tampered.json"
    _write_sector_membership_sidecar(
        tampered_path,
        [_sector_membership_row()],
    )
    tampered = json.loads(tampered_path.read_text(encoding="utf-8"))
    tampered["rows"][0]["sector_id"] = "FORGED"
    tampered_path.write_text(
        json.dumps(tampered, ensure_ascii=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="rows hash mismatch"):
        _spool_sector_memberships(connection, tampered_path)
    connection.close()


def test_sector_membership_rejects_current_snapshot_backfill_poison(
    tmp_path: Path,
) -> None:
    current_snapshot_path = tmp_path / "current-snapshot.json"
    _write_sector_membership_sidecar(
        current_snapshot_path,
        [
            _sector_membership_row(
                source_id="file:meta_data/companies.csv",
            )
        ],
    )
    connection = sqlite3.connect(":memory:")
    _initialize_spool(connection)
    with pytest.raises(
        ValueError,
        match="blocker:current_companies_snapshot_not_historical_pit",
    ):
        _spool_sector_memberships(
            connection,
            current_snapshot_path,
            training_as_of=datetime.fromisoformat(
                "2024-09-01T08:30:00+08:00"
            ),
        )

    future_first_seen_path = tmp_path / "future-first-seen.json"
    _write_sector_membership_sidecar(
        future_first_seen_path,
        [
            _sector_membership_row(
                available_at="2026-07-30T08:30:00+08:00",
                effective_from="2014-01-01",
            )
        ],
    )
    with pytest.raises(
        ValueError,
        match="blocker:sector_membership_available_after_training_as_of",
    ):
        _spool_sector_memberships(
            connection,
            future_first_seen_path,
            training_as_of=datetime.fromisoformat(
                "2024-09-01T08:30:00+08:00"
            ),
        )
    connection.close()


def test_training_loader_recomputes_direct_shard_and_manifest_hashes(
    tmp_path: Path,
) -> None:
    raw = _raw_publication(tmp_path)
    publication = PortfolioMLDatasetAssembler().build(
        PortfolioMLDatasetAssemblyRequest(
            dataset_manifest_path=raw.dataset_manifest_paths[
                "all_field_enriched"
            ],
            output_root=tmp_path / "training",
            training_as_of="2024-09-01T08:30:00+08:00",
            benchmark_entity_id="TAIEX",
            minimum_train_dates=65,
            test_date_count=21,
            purge_trading_days=60,
            embargo_trading_days=5,
        )
    )
    shard_path = publication.shard_paths[0]
    records = _records(shard_path)
    records[0]["dataset_identity_hash"] = "sha256:" + ("f" * 64)
    with gzip.open(shard_path, "wt", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )

    with pytest.raises(ValueError, match="does not match|hash mismatch"):
        _load_frozen_shard(shard_path)


def test_assembler_rejects_training_cutoff_after_raw_freeze(
    tmp_path: Path,
) -> None:
    raw = _raw_publication(tmp_path)
    request = PortfolioMLDatasetAssemblyRequest(
        dataset_manifest_path=raw.dataset_manifest_paths[
            "all_field_enriched"
        ],
        output_root=tmp_path / "training",
        training_as_of="2024-09-02T08:30:00+08:00",
        benchmark_entity_id="TAIEX",
        minimum_train_dates=65,
        test_date_count=21,
    )

    try:
        PortfolioMLDatasetAssembler().build(request)
    except ValueError as exc:
        assert "raw publication decision_at" in str(exc)
    else:
        raise AssertionError("future training cutoff must fail closed")


def test_assembler_rejects_manifest_observation_source_id_mismatch(
    tmp_path: Path,
) -> None:
    raw = _raw_publication(tmp_path)
    manifest_path = raw.dataset_manifest_paths["all_field_enriched"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    feature = next(
        item
        for item in manifest["features"]
        if item["feature_id"].startswith("daily_prices.")
    )
    feature["source_id"] = "forged:lineage"
    manifest.pop("manifest_hash")
    manifest["manifest_hash"] = _manifest_hash(manifest)
    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    request = PortfolioMLDatasetAssemblyRequest(
        dataset_manifest_path=manifest_path,
        output_root=tmp_path / "training",
        training_as_of="2024-09-01T08:30:00+08:00",
        benchmark_entity_id="TAIEX",
        minimum_train_dates=65,
        test_date_count=21,
    )

    with pytest.raises(
        ValueError,
        match="blocker:manifest_observation_source_id_mismatch",
    ):
        PortfolioMLDatasetAssembler().build(request)

    assert not (request.output_root / "latest_manifest.json").exists()


def test_horizon_label_is_prefix_invariant_to_later_price_poison() -> None:
    baseline = _horizon_poison_labels()
    poisoned = _horizon_poison_labels(poison_after_horizon=True)

    assert baseline[2] == poisoned[2]
    assert baseline[4] != poisoned[4]


def test_label_spool_progress_callback_reports_lifecycle() -> None:
    events: list[str] = []

    _horizon_poison_labels(progress_events=events)

    assert events[0].startswith("label_spool_starting_")
    assert any(
        event.startswith("label_spool_symbols_1_of_1_processed")
        for event in events
    )
    assert events[-1] == "label_spool_complete"


def test_label_spool_progress_callback_reports_persisted_batches() -> None:
    events: list[str] = []

    _horizon_poison_labels(progress_events=events, batch_size=1)

    assert "label_spool_labels_batch_written" in events


def test_raw_spool_progress_callback_reports_time_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.portfolio_ml_ooc_support import _long_raw_publication

    raw = _long_raw_publication(tmp_path)
    raw_manifest_path = raw.dataset_manifest_paths["all_field_enriched"]
    manifest = json.loads(raw_manifest_path.read_text(encoding="utf-8"))
    assert isinstance(manifest, dict)
    events: list[str] = []
    monotonic_value = 0

    def fake_monotonic_ns() -> int:
        nonlocal monotonic_value
        monotonic_value += 1
        return monotonic_value

    # This test isolates assembler telemetry; Direct tests keep the
    # production constants so its dependency fingerprint remains meaningful.
    monkeypatch.setattr(
        assembler_module,
        "_RAW_SPOOL_PROGRESS_INTERVAL",
        1_000_000,
    )
    monkeypatch.setattr(
        assembler_module,
        "_RAW_SPOOL_PROGRESS_CHECK_INTERVAL",
        64,
    )
    monkeypatch.setattr(
        assembler_module,
        "_RAW_SPOOL_PROGRESS_MAX_SILENCE_NS",
        1,
    )
    monkeypatch.setattr(assembler_module, "monotonic_ns", fake_monotonic_ns)
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        _initialize_spool(connection)
        raw_rows, raw_values = assembler_module.PortfolioMLDatasetAssembler()._spool_raw_observations(
            connection=connection,
            dataset_manifest_path=raw_manifest_path,
            manifest=manifest,
            definitions=_base_feature_definitions(manifest),
            source_digest=hashlib.sha256(),
            batch_size=61,
            progress_callback=events.append,
        )
    finally:
        connection.close()

    assert raw_rows > 0
    assert raw_values > 0
    assert any(event.endswith("rows_64_processed") for event in events)


def test_assembly_progress_callback_reports_same_decision_multiple_samples(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.portfolio_ml_ooc_support import _long_raw_publication

    raw = _long_raw_publication(tmp_path)
    events: list[str] = []
    monkeypatch.setattr(assembler_module, "_ASSEMBLY_PROGRESS_INTERVAL", 1)
    publication = PortfolioMLDatasetAssembler().build(
        PortfolioMLDatasetAssemblyRequest(
            dataset_manifest_path=(
                raw.dataset_manifest_paths["all_field_enriched"]
            ),
            output_root=tmp_path / "training",
            training_as_of="2026-04-01T08:30:00+08:00",
            benchmark_entity_id="TAIEX",
            minimum_train_dates=65,
            test_date_count=65,
            purge_trading_days=60,
            embargo_trading_days=5,
            batch_size=29,
            capacity_callback=events.append,
        )
    )

    assert publication.sample_count > 0
    assembly_events = [
        event
        for event in events
        if event.startswith("assembly_decision_")
    ]
    decision_dates = [
        event.removeprefix("assembly_decision_").split("_rows_", 1)[0]
        for event in assembly_events
    ]
    assert len(assembly_events) > len(set(decision_dates))
    assert "assembly_samples_complete" in events


def test_later_horizon_gap_does_not_discard_valid_short_horizon_label() -> None:
    baseline = _horizon_poison_labels()
    with_later_gap = _horizon_poison_labels(omit_after_horizon=True)

    assert with_later_gap[2] == baseline[2]
    assert 4 not in with_later_gap


def test_corporate_action_horizon_is_explicitly_missing_and_excluded() -> None:
    exclusions: list[dict[str, object]] = []
    labels = _horizon_poison_labels(
        corporate_action_effective_date="2024-01-04",
        exclusion_sink=exclusions,
    )

    assert set(labels) == {2}
    assert [row["horizon"] for row in exclusions] == [4]
    assert exclusions[0]["reason"] == (
        "corporate_action_effective_within_label_horizon"
    )
    assert exclusions[0]["event_effective_date"] == "2024-01-04"


def test_price_future_prefix_poison_is_not_applied_to_decision_snapshot() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    _initialize_spool(connection)
    source_hash = "sha256:" + ("a" * 64)
    _insert_observations(
        connection,
        (
            (
                "stock",
                "2330",
                "daily_prices.收盤價",
                "daily_prices",
                "sqlite.daily_prices",
                "price_liquidity_technical",
                "2024-01-02T14:30:00+08:00",
                # 故意偽造為決策前已可見；event_at T 當日仍須被 T-1 gate 擋下。
                "2024-01-01T18:00:00+08:00",
                "poison-r1",
                "accepted",
                source_hash,
                source_hash,
                1_000_000,
                10_000,
                7,
                1,
                0,
                0,
            ),
        ),
    )
    connection.commit()

    _advance_current_features(
        connection,
        previous_cutoff="0001-01-01T00:00:00+08:00",
        decision_at="2024-01-02T08:30:00+08:00",
        decision_date="2024-01-02",
        batch_size=10,
    )

    assert _current_values(
        connection,
        scope="stock",
        entity_key="2330",
        decision_at="2024-01-02T08:30:00+08:00",
    ) == {}
    connection.close()


def test_cash_only_fallback_replay_is_chained_and_disables_learning_claims() -> None:
    replay = _build_cash_only_portfolio_state_replay(
        calendar=("2024-01-01", "2024-01-02", "2024-01-03"),
        decision_dates=("2024-01-02", "2024-01-03"),
    )

    custody = replay.custody_payload()
    assert custody["cash_only_fallback"] is True
    assert custody["ledger_present"] is False
    assert custody["teacher_targets_replayed_into_state"] is False
    assert custody["turnover_learning_claim_allowed"] is False
    assert custody["cooldown_learning_claim_allowed"] is False
    assert custody["transition_count"] == 2
    assert replay.entries[0].state.as_of_date == "2024-01-01"
    assert replay.entries[1].state.as_of_date == "2024-01-02"
    assert replay.entries[0].state.weights.cash_bp == 10_000
    assert replay.entries[1].state.weights.cash_bp == 10_000
    assert replay.entries[0].transition_hash != replay.entries[1].transition_hash
    assert replay.entries[0].state.state_hash != replay.entries[1].state.state_hash


def test_teacher_candidate_cvar_uses_tail_loss_instead_of_mae() -> None:
    label = _Label(
        horizon=20,
        horizon_end_date="2024-02-01",
        available_at="2024-02-01T18:00:00+08:00",
        excess_return_bp=120,
        sector_excess_return_bp=80,
        sector_excess_observed=True,
        sector_excess_missing_reason=None,
        downside_observed=True,
        mae_loss_bp=900,
        mfe_gain_bp=300,
        realized_volatility_bp=140,
        max_drawdown_bp=450,
        tail_loss_bp=320,
        fill_feasible_observed=True,
        source_hash="sha256:" + ("b" * 64),
    )

    candidate = _teacher_candidates(
        labels_by_symbol={"2330": (label,)},
        sectors={"2330": "SEMI"},
    )[0]

    assert candidate.cvar_loss_bp == 320
    assert candidate.cvar_loss_bp != label.mae_loss_bp


def test_current_features_choose_period_before_late_revision_of_old_period() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    _initialize_spool(connection)
    source_row_hash = "sha256:" + ("c" * 64)
    observations = (
        ("2024-01-31T14:30:00+08:00", "2024-02-01T18:00:00+08:00", "r1", 100),
        ("2024-02-29T14:30:00+08:00", "2024-03-01T18:00:00+08:00", "r1", 200),
        ("2024-02-29T14:30:00+08:00", "2024-03-02T18:00:00+08:00", "r2", 250),
        ("2024-01-31T14:30:00+08:00", "2024-04-01T18:00:00+08:00", "r2", 999),
    )
    _insert_observations(
        connection,
        tuple(
            (
                "stock",
                "2330",
                "fundamental_monthly_revenues.revenue",
                "fundamental_monthly_revenues",
                "sqlite.fundamental_monthly_revenues",
                "fundamental",
                event_at,
                available_at,
                revision_id,
                "accepted",
                source_row_hash,
                "sha256:" + hashlib.sha256(
                    f"{event_at}|{available_at}|{revision_id}|{value}".encode()
                ).hexdigest(),
                value,
                1,
                120,
                1,
                0,
                0,
            )
            for event_at, available_at, revision_id, value in observations
        ),
    )
    connection.commit()

    decision_at = "2024-04-02T08:30:00+08:00"
    current_feature_cache: _CurrentFeatureCache = {
        "stock": {},
        "market": {},
        "industry": {},
    }
    _advance_current_features(
        connection,
        previous_cutoff="0001-01-01T00:00:00+08:00",
        decision_at=decision_at,
        decision_date="2024-04-02",
        batch_size=2,
        current_feature_cache=current_feature_cache,
    )

    assert connection.execute(
        "SELECT COUNT(*) FROM current_features"
    ).fetchone()[0] == 2
    current = _current_values(
        connection,
        scope="stock",
        entity_key="2330",
        decision_at=decision_at,
    )["fundamental_monthly_revenues.revenue"]
    assert current.event_at == "2024-02-29T14:30:00+08:00"
    assert current.available_at == "2024-03-02T18:00:00+08:00"
    assert current.revision_id == "r2"
    assert current.value_int == 250
    assert current_feature_cache["stock"]["2330"] == {
        "fundamental_monthly_revenues.revenue": current,
    }
    connection.close()


def test_current_feature_cache_can_skip_redundant_sqlite_history() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    _initialize_spool(connection)
    source_hash = "sha256:" + ("d" * 64)
    _insert_observations(
        connection,
        (
            (
                "stock",
                "2330",
                "fundamental_monthly_revenues.revenue",
                "fundamental_monthly_revenues",
                "sqlite.fundamental_monthly_revenues",
                "fundamental",
                "2024-01-31T14:30:00+08:00",
                "2024-02-01T18:00:00+08:00",
                "r1",
                "accepted",
                source_hash,
                source_hash,
                100,
                1,
                120,
                1,
                0,
                0,
            ),
        ),
    )
    connection.commit()
    current_feature_cache: _CurrentFeatureCache = {
        "stock": {},
        "market": {},
        "industry": {},
    }

    _advance_current_features(
        connection,
        previous_cutoff="0001-01-01T00:00:00+08:00",
        decision_at="2024-02-02T08:30:00+08:00",
        decision_date="2024-02-02",
        batch_size=10,
        current_feature_cache=current_feature_cache,
        persist_current_history=False,
    )

    assert connection.execute(
        "SELECT COUNT(*) FROM current_features"
    ).fetchone()[0] == 0
    cached = current_feature_cache["stock"]["2330"][
        "fundamental_monthly_revenues.revenue"
    ]
    assert cached.value_int == 100
    assert cached.revision_id == "r1"
    connection.close()


@pytest.mark.parametrize("value", [1, 0, "true", None, []])
def test_required_json_bool_rejects_bool_like_values(value: object) -> None:
    with pytest.raises(TypeError, match="must be a JSON boolean"):
        _required_json_bool(value, field_name="safety.flag")


def test_required_json_bool_accepts_only_real_booleans() -> None:
    assert _required_json_bool(True, field_name="safety.flag") is True
    assert _required_json_bool(False, field_name="safety.flag") is False


def test_raw_manifest_rejects_integer_in_json_boolean_field() -> None:
    payload: dict[str, object] = {
        "schema_version": "ml-pit-year-shard-dataset.v1",
        "stage": "raw_pit_observations",
        "format": "gzip_jsonl",
        "safety": {
            "formal_dataset": 1,
            "unreviewed_included": False,
            "excluded_leakage_included": False,
            "research_shadow_isolated": True,
            "raw_float_persistence_allowed": False,
        },
        "features": [],
    }
    payload["manifest_hash"] = _manifest_hash(payload)

    with pytest.raises(
        TypeError,
        match=r"safety\.formal_dataset must be a JSON boolean",
    ):
        _validate_raw_dataset_manifest(payload)
