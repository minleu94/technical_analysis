"""
QA Validation script for Phase 4.1: Portfolio & Journal MVP.
This script tests both service APIs, domain rules, and checks basic UI smoke initialization.
"""

import sys
import os
import shutil
import tempfile
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_module.config import TWStockConfig
from app_module.portfolio_service import PortfolioService
from app_module.journal_service import JournalService
from portfolio_module import PortfolioValidationError, rebuild_positions, Trade

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_service_tests(temp_dir: Path):
    logger.info("=== Running Service & Domain Tests ===")
    
    # 1. Setup config using temp dir
    config = TWStockConfig(
        data_root=temp_dir / "data",
        output_root=temp_dir / "output",
        profile="unit"
    )
    
    portfolio_service = PortfolioService(config)
    journal_service = JournalService(config)
    
    # 2. Record buy trades
    logger.info("Recording buy trade for TSMC (2330)...")
    trade1 = portfolio_service.record_trade(
        stock_code="2330",
        stock_name="台積電",
        side="buy",
        quantity=1000,
        price=600.0,
        trade_date="2026-01-02",
        notes="First buy TSMC",
        source_type="recommendation",
        source_id="rec_001",
        source_snapshot_hash="hash_rec_001",
        source_summary={"profile_id": "aggressive_short", "total_score": 82.5},
    )
    assert trade1.stock_code == "2330"
    assert trade1.side == "buy"
    assert trade1.quantity == 1000.0
    assert trade1.price == 600.0
    
    # Add another buy to check cost averaging
    logger.info("Recording second buy trade for TSMC...")
    portfolio_service.record_trade(
        stock_code="2330",
        stock_name="台積電",
        side="buy",
        quantity=1000,
        price=620.0,
        trade_date="2026-01-03",
        notes="Add to TSMC",
    )
    
    # Check derived positions
    positions = portfolio_service.list_positions()
    assert len(positions) == 1, f"Expected 1 position, got {len(positions)}"
    pos = positions[0]
    assert pos.stock_code == "2330"
    assert pos.quantity == 2000.0
    assert pos.average_cost == 610.0, f"Expected cost 610.0, got {pos.average_cost}"
    assert pos.invested_amount == 1220000.0
    assert pos.source_type == "recommendation"
    assert pos.source_id == "rec_001"
    assert pos.source_snapshot_hash == "hash_rec_001"
    assert pos.source_summary["profile_id"] == "aggressive_short"
    
    # 3. Record sell trade
    logger.info("Recording partial sell trade for TSMC...")
    portfolio_service.record_trade(
        stock_code="2330",
        stock_name="台積電",
        side="sell",
        quantity=500,
        price=650.0,
        trade_date="2026-01-04"
    )
    
    positions = portfolio_service.list_positions()
    pos = positions[0]
    assert pos.quantity == 1500.0
    # Average cost should remain 610.0
    assert pos.average_cost == 610.0
    # Realized PnL: (650 - 610) * 500 = 40 * 500 = 20,000
    assert pos.realized_pnl == 20000.0, f"Expected realized PnL 20000.0, got {pos.realized_pnl}"
    
    # 4. Check domain validation rules
    logger.info("Verifying domain exception for over-selling...")
    try:
        portfolio_service.record_trade(
            stock_code="2330",
            stock_name="台積電",
            side="sell",
            quantity=2000,  # Exceeds current 1500
            price=660.0,
            trade_date="2026-01-05"
        )
        raise AssertionError("Should have raised PortfolioValidationError for over-selling")
    except PortfolioValidationError as e:
        logger.info(f"Successfully caught expected validation error: {e}")
        
    # Check sell without open position
    logger.info("Verifying domain exception for selling without holding...")
    try:
        portfolio_service.record_trade(
            stock_code="2317",
            stock_name="鴻海",
            side="sell",
            quantity=1000,
            price=150.0,
            trade_date="2026-01-05"
        )
        raise AssertionError("Should have raised PortfolioValidationError for selling without open position")
    except PortfolioValidationError as e:
        logger.info(f"Successfully caught expected validation error: {e}")

    # 5. Check Journal entries
    logger.info("Testing journal service entries...")
    journal_service.add_journal_entry(
        title="TSMC Entry Thesis",
        body="Strong technical breakdown support, buy and hold strategy",
        stock_code="2330",
        linked_type="trade",
        linked_id=trade1.trade_id,
        source_type="recommendation",
        source_id="rec_001"
    )
    
    journal_service.add_journal_entry(
        title="General Note",
        body="Market looks volatile, keep positions tight",
        stock_code="",
    )
    
    entries_tsmc = journal_service.list_journal_entries(stock_code="2330")
    assert len(entries_tsmc) == 1
    assert entries_tsmc[0].title == "TSMC Entry Thesis"
    assert entries_tsmc[0].linked_id == trade1.trade_id
    
    all_entries = journal_service.list_journal_entries()
    assert len(all_entries) == 2
    
    logger.info("Service and domain rules verification: PASSED")


def run_ui_smoke_tests():
    logger.info("=== Running UI Smoke Import Tests ===")
    
    try:
        from PySide6.QtWidgets import QApplication
        
        # Check PySide6 QApplication instantiation
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
            
        logger.info("QApplication created successfully")
        
        # Import PortfolioView
        logger.info("Importing PortfolioView...")
        from ui_qt.views.portfolio_view import PortfolioView
        logger.info("PortfolioView class imported successfully")
        
        # Instantiate PortfolioView with mocked services
        logger.info("Instantiating PortfolioView with dummy config...")
        temp_dir = Path(tempfile.mkdtemp())
        try:
            config = TWStockConfig(
                data_root=temp_dir / "data",
                output_root=temp_dir / "output",
                profile="unit"
            )
            portfolio_service = PortfolioService(config)
            journal_service = JournalService(config)
            
            # Smoke initialize view without showing it
            view = PortfolioView(
                portfolio_service=portfolio_service,
                journal_service=journal_service,
                parent=None
            )
            assert view is not None
            logger.info("PortfolioView smoke instantiation: PASSED")
        finally:
            shutil.rmtree(temp_dir)
            
    except Exception as e:
        logger.error(f"UI smoke validation FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    temp_dir = Path(tempfile.mkdtemp())
    try:
        run_service_tests(temp_dir)
        run_ui_smoke_tests()
        logger.info("=== All QA validations PASSED successfully! ===")
    finally:
        # Shutdown logging to release log file handle on Windows
        logging.shutdown()
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
