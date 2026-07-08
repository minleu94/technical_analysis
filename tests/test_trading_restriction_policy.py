import sqlite3
import contextlib
from pathlib import Path
from tempfile import TemporaryDirectory

from app_module.trading_restriction_policy import TradingRestrictionProvider, TradingRestrictionPolicy


def test_provider_returns_source_not_ingested_when_db_missing():
    provider = TradingRestrictionProvider(Path("missing_db.sqlite"))
    restrictions, diagnostics = provider.get_restrictions("2330", "2026-06-01", "2026-06-10")
    
    assert restrictions == []
    assert diagnostics == ["source_not_ingested"]


def test_provider_returns_source_not_ingested_when_table_missing():
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            conn.execute("CREATE TABLE dummy (id INTEGER)")
            
        provider = TradingRestrictionProvider(db_path)
        restrictions, diagnostics = provider.get_restrictions("2330", "2026-06-01", "2026-06-10")
        
        assert restrictions == []
        assert diagnostics == ["source_not_ingested"]


def test_provider_returns_restrictions_within_gap():
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE microstructure_restriction_events (
                    stock_code TEXT,
                    restriction_type TEXT,
                    effective_date TEXT
                )
                """
            )
            # Insert some events
            conn.execute("INSERT INTO microstructure_restriction_events VALUES ('2330', 'disposition', '2026-06-15')")
            conn.execute("INSERT INTO microstructure_restriction_events VALUES ('2330', 'limit_lock', '2026-06-18')")
            conn.execute("INSERT INTO microstructure_restriction_events VALUES ('2317', 'suspended', '2026-06-16')")
            conn.commit()
            
        provider = TradingRestrictionProvider(db_path)
        
        # Test within range
        restrictions, diagnostics = provider.get_restrictions("2330", "2026-06-10", "2026-06-19")
        assert len(restrictions) == 2
        assert "disposition" in restrictions
        assert "limit_lock" in restrictions
        assert diagnostics == []

        # Test out of range
        restrictions, diagnostics = provider.get_restrictions("2330", "2026-06-01", "2026-06-10")
        assert restrictions == []


def test_policy_appends_warning_on_gap():
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            conn.execute("CREATE TABLE microstructure_restriction_events (stock_code TEXT, restriction_type TEXT, effective_date TEXT)")
            conn.execute("INSERT INTO microstructure_restriction_events VALUES ('2330', 'disposition', '2026-06-15')")
            conn.commit()
            
        provider = TradingRestrictionProvider(db_path)
        policy = TradingRestrictionPolicy(provider)
        
        warnings = policy.check_restriction_gap("2330", "2026-06-10", "2026-06-20")
        assert "trading_restriction_gap_detected" in warnings

        warnings = policy.check_restriction_gap("2330", "2026-06-20", "2026-06-30")
        assert warnings == []


def test_policy_maps_restrictions_to_reasons_on_date():
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            conn.execute("CREATE TABLE microstructure_restriction_events (stock_code TEXT, restriction_type TEXT, effective_date TEXT)")
            conn.execute("INSERT INTO microstructure_restriction_events VALUES ('2330', 'limit_lock', '2026-06-15')")
            conn.execute("INSERT INTO microstructure_restriction_events VALUES ('2317', 'disposition', '2026-06-15')")
            conn.execute("INSERT INTO microstructure_restriction_events VALUES ('2454', 'suspended', '2026-06-15')")
            conn.commit()
            
        provider = TradingRestrictionProvider(db_path)
        policy = TradingRestrictionPolicy(provider)
        
        # limit_lock -> rejected_price_limit_locked
        reasons = policy.check_restrictions("2330", "2026-06-15")
        assert reasons == ["rejected_price_limit_locked"]
        
        # disposition -> rejected_trading_restricted
        reasons = policy.check_restrictions("2317", "2026-06-15")
        assert reasons == ["rejected_trading_restricted"]
        
        # suspended -> rejected_trading_restricted
        reasons = policy.check_restrictions("2454", "2026-06-15")
        assert reasons == ["rejected_trading_restricted"]
        
        # nothing
        reasons = policy.check_restrictions("2330", "2026-06-16")
        assert reasons == []
