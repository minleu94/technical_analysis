from datetime import date, timedelta
import sqlite3

import pandas as pd

from app_module.decision_desk_dtos import DecisionDeskQuality
from app_module.sector_rotation_service import SectorRotationService, SQLiteIndustryIndexSectorRotationProvider


def _build_history_frame(
    sector_histories: dict[str, list[float]],
    target_date: date,
    date_fmt: str = "%Y-%m-%d",
) -> pd.DataFrame:
    rows = []
    first_date = target_date - timedelta(days=len(next(iter(sector_histories.values()))) - 1)
    for sector, history in sector_histories.items():
        for offset, close in enumerate(history):
            current = first_date + timedelta(days=offset)
            rows.append(
                {
                    "date": current.strftime(date_fmt),
                    "sector": sector,
                    "close": float(close),
                }
            )
    return pd.DataFrame(rows)


class FakeSectorProvider:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def fetch(self, as_of_date: date) -> pd.DataFrame:
        return self.frame.copy()


class BrokenSectorProvider:
    def fetch(self, as_of_date: date) -> pd.DataFrame:
        raise RuntimeError("sector data feed unavailable")


def test_sector_rotation_service_outputs_leading_trailing_and_stable_ranking():
    frame = _build_history_frame(
        {
            "semi": [80 + 2.5 * i for i in range(21)],
            "financial": [90 + i for i in range(21)],
            "electronics": [95 + 0.5 * i for i in range(21)],
        },
        date(2026, 6, 15),
    )
    service = SectorRotationService(FakeSectorProvider(frame))
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.leading_sector == "semi"
    assert snapshot.trailing_sector == "electronics"
    assert snapshot.rotation_intensity_bp is not None
    assert snapshot.rotation_intensity_bp > 2000
    assert snapshot.warnings == ()

    ranking = snapshot.meta["sector_ranking"]
    assert ranking[0]["sector"] == "semi"
    assert ranking[1]["sector"] == "financial"
    assert ranking[2]["sector"] == "electronics"
    assert isinstance(ranking[0]["relative_strength_bp"], int)
    assert isinstance(ranking[0]["change_5d_bp"], int)
    assert isinstance(ranking[0]["change_20d_bp"], int)


def test_sector_rotation_service_tie_breaker_is_deterministic_with_same_strength():
    frame = _build_history_frame(
        {"A": [100 + i for i in range(21)], "B": [100 + i for i in range(21)]},
        date(2026, 6, 15),
    )
    service = SectorRotationService(FakeSectorProvider(frame))
    snapshot = service.build_snapshot(date(2026, 6, 15))

    ranking = snapshot.meta["sector_ranking"]
    assert snapshot.quality == DecisionDeskQuality.OBSERVED
    assert ranking[0]["sector"] == "A"
    assert ranking[1]["sector"] == "B"


def test_sector_rotation_service_supports_numeric_yyyymmdd_without_crash():
    base = date(2026, 6, 15)
    frame = _build_history_frame(
        {
            "A": [100 + i for i in range(21)],
            "B": [200 + i * 0.5 for i in range(21)],
        },
        base,
        date_fmt="%Y%m%d",
    ).copy()
    frame["date"] = frame["date"].astype(int)

    service = SectorRotationService(FakeSectorProvider(frame))
    snapshot = service.build_snapshot(base)

    assert snapshot.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.leading_sector == "A"
    assert snapshot.trailing_sector == "B"
    assert snapshot.rotation_intensity_bp is not None
    assert snapshot.meta["sector_ranking"][0]["change_5d_bp"] is not None


def test_sector_rotation_service_supports_string_yyyymmdd_and_dash_dates():
    frame = _build_history_frame(
        {
            "A": [100 + i for i in range(21)],
            "B": [120 + i * 0.2 for i in range(21)],
        },
        date(2026, 6, 15),
    )
    frame.loc[0, "date"] = "20200101"
    frame.loc[1, "date"] = "2019-06-02"

    service = SectorRotationService(FakeSectorProvider(frame))
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality in {DecisionDeskQuality.OBSERVED, DecisionDeskQuality.DEGRADED}
    assert snapshot.leading_sector == "A"
    assert snapshot.as_of_date == date(2026, 6, 15)


def test_sector_rotation_service_degrades_when_sector_data_insufficient():
    frame = pd.concat(
        [
            _build_history_frame(
                {"good_sector": [100 + i for i in range(21)]},
                date(2026, 6, 15),
            ),
            _build_history_frame(
                {"weak_sector": [100 + i for i in range(5)]},
                date(2026, 6, 15),
            ),
        ],
        ignore_index=True,
    ).rename(columns={"sector": "產業別", "close": "收盤指數"})

    service = SectorRotationService(FakeSectorProvider(frame))
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.DEGRADED
    assert snapshot.leading_sector == "good_sector"
    assert snapshot.trailing_sector is None
    assert snapshot.rotation_intensity_bp is None
    assert any("sector_rotation_data_insufficient:weak_sector" in w for w in snapshot.warnings)


def test_sector_rotation_service_returns_missing_when_no_match_date():
    frame = pd.DataFrame(
        {
            "date": ["2026-06-10", "2026-06-11"],
            "sector": ["半導體", "金融保險"],
            "close": [100.0, 120.0],
        }
    )
    service = SectorRotationService(FakeSectorProvider(frame))
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.MISSING
    assert snapshot.warnings == ("sector_rotation_missing",)
    assert snapshot.leading_sector is None


def test_sector_rotation_service_degraded_on_provider_failure():
    service = SectorRotationService(BrokenSectorProvider())
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.DEGRADED
    assert snapshot.leading_sector is None
    assert any("sector_rotation_provider_error" in w for w in snapshot.warnings)


def test_sector_rotation_service_handles_non_contiguous_index_and_observes_ranking():
    frame = _build_history_frame(
        {
            "A": [100 + i for i in range(21)],
            "B": [200 + i * 0.5 for i in range(21)],
        },
        date(2026, 6, 15),
    )
    frame.index = [i * 2 for i in range(len(frame))]

    service = SectorRotationService(FakeSectorProvider(frame))
    snapshot = service.build_snapshot(date(2026, 6, 15))

    assert snapshot.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.leading_sector == "A"
    assert snapshot.trailing_sector == "B"
    assert snapshot.rotation_intensity_bp is not None
    ranking = snapshot.meta["sector_ranking"]
    assert ranking[0]["sector"] == "A"
    assert ranking[1]["sector"] == "B"


def test_sqlite_industry_index_provider_builds_sector_rotation_from_sqlite(tmp_path):
    target_date = date(2026, 6, 15)
    db_path = tmp_path / "twstock.db"
    rows = []
    first_date = target_date - timedelta(days=20)
    for offset in range(21):
        current = first_date + timedelta(days=offset)
        date_key = current.strftime("%Y%m%d")
        rows.extend(
            [
                (date_key, "半導體", 100 + offset * 2.5),
                (date_key, "金融保險", 100 + offset * 1.0),
                (date_key, "水泥", 100 + offset * 0.2),
            ]
        )

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE industry_indices (
                日期 TEXT,
                指數名稱 TEXT,
                收盤指數 REAL,
                PRIMARY KEY (指數名稱, 日期)
            )
            """
        )
        conn.executemany(
            "INSERT INTO industry_indices (日期, 指數名稱, 收盤指數) VALUES (?, ?, ?)",
            rows,
        )

    service = SectorRotationService(SQLiteIndustryIndexSectorRotationProvider(db_path))
    snapshot = service.build_snapshot(target_date)

    assert snapshot.quality == DecisionDeskQuality.OBSERVED
    assert snapshot.as_of_date == target_date
    assert snapshot.leading_sector == "半導體"
    assert snapshot.trailing_sector == "水泥"
    assert snapshot.rotation_intensity_bp is not None
    assert snapshot.meta["source"] == "sqlite_industry_indices"


def test_sqlite_industry_index_provider_uses_latest_available_date_with_warning(tmp_path):
    latest_date = date(2026, 6, 12)
    requested_date = date(2026, 6, 15)
    db_path = tmp_path / "twstock.db"
    rows = []
    first_date = latest_date - timedelta(days=20)
    for offset in range(21):
        current = first_date + timedelta(days=offset)
        date_key = current.strftime("%Y%m%d")
        rows.extend(
            [
                (date_key, "半導體", 100 + offset * 2.0),
                (date_key, "金融保險", 100 + offset * 1.0),
            ]
        )

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE industry_indices (
                日期 TEXT,
                指數名稱 TEXT,
                收盤指數 REAL,
                PRIMARY KEY (指數名稱, 日期)
            )
            """
        )
        conn.executemany(
            "INSERT INTO industry_indices (日期, 指數名稱, 收盤指數) VALUES (?, ?, ?)",
            rows,
        )

    service = SectorRotationService(SQLiteIndustryIndexSectorRotationProvider(db_path))
    snapshot = service.build_snapshot(requested_date)

    assert snapshot.quality == DecisionDeskQuality.DEGRADED
    assert snapshot.as_of_date == latest_date
    assert snapshot.leading_sector == "半導體"
    assert "sector_rotation_as_of_fallback:2026-06-12" in snapshot.warnings
