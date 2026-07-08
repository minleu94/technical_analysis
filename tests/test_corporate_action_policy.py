import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from app_module.corporate_action_policy import CorporateActionProvider, CorporateActionPolicy


import contextlib

def test_provider_returns_source_not_ingested_when_db_missing():
    provider = CorporateActionProvider(Path("missing_db.sqlite"))
    dates, diagnostics = provider.get_ex_dividend_dates("2330", "2026-06-01", "2026-06-10")
    
    assert dates == []
    assert diagnostics == ["source_not_ingested"]


def test_provider_returns_source_not_ingested_when_table_missing():
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            conn.execute("CREATE TABLE dummy (id INTEGER)")
            
        provider = CorporateActionProvider(db_path)
        dates, diagnostics = provider.get_ex_dividend_dates("2330", "2026-06-01", "2026-06-10")
        
        assert dates == []
        assert diagnostics == ["source_not_ingested"]


def test_provider_returns_dates_when_corporate_action_exists():
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE corporate_action_events (
                    stock_code TEXT,
                    event_type TEXT,
                    event_date TEXT
                )
                """
            )
            # Insert some events
            conn.execute("INSERT INTO corporate_action_events VALUES ('2330', 'ex_dividend', '2026-06-15')")
            conn.execute("INSERT INTO corporate_action_events VALUES ('2330', 'ex_right', '2026-06-18')")
            conn.execute("INSERT INTO corporate_action_events VALUES ('2330', 'other', '2026-06-20')")
            conn.execute("INSERT INTO corporate_action_events VALUES ('2317', 'ex_dividend', '2026-06-16')")
            conn.commit()
            
        provider = CorporateActionProvider(db_path)
        
        # Test within range
        dates, diagnostics = provider.get_ex_dividend_dates("2330", "2026-06-10", "2026-06-19")
        assert len(dates) == 2
        assert "2026-06-15" in dates
        assert "2026-06-18" in dates
        assert diagnostics == []

        # Test out of range
        dates, diagnostics = provider.get_ex_dividend_dates("2330", "2026-06-01", "2026-06-10")
        assert dates == []
        
        # Test start exclusive, end inclusive
        dates, diagnostics = provider.get_ex_dividend_dates("2330", "2026-06-15", "2026-06-15")
        assert dates == []
        dates, diagnostics = provider.get_ex_dividend_dates("2330", "2026-06-14", "2026-06-15")
        assert dates == ["2026-06-15"]


def test_policy_appends_warning_on_gap():
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            conn.execute("CREATE TABLE corporate_action_events (stock_code TEXT, event_type TEXT, event_date TEXT)")
            conn.execute("INSERT INTO corporate_action_events VALUES ('2330', 'ex_dividend', '2026-06-15')")
            conn.commit()
            
        provider = CorporateActionProvider(db_path)
        policy = CorporateActionPolicy(provider)
        
        warnings = policy.check_corporate_action_gap("2330", "2026-06-10", "2026-06-20")
        assert "corporate_action_gap_detected" in warnings

        warnings = policy.check_corporate_action_gap("2330", "2026-06-20", "2026-06-30")
        assert warnings == []

        # Test with missing table
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            conn.execute("DROP TABLE corporate_action_events")
        
        # provider caches table existence, so create a new one
        provider2 = CorporateActionProvider(db_path)
        policy2 = CorporateActionPolicy(provider2)
        warnings2 = policy2.check_corporate_action_gap("2330", "2026-06-10", "2026-06-20")
        assert warnings2 == ["source_not_ingested"]
