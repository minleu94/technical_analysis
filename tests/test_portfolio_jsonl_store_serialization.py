from decimal import Decimal

from app_module.portfolio_store import PortfolioJsonlStore


def test_portfolio_jsonl_store_serializes_decimal_without_float(tmp_path):
    store = PortfolioJsonlStore(tmp_path)

    store.append_trade({
        "stock_code": "2330",
        "quantity": Decimal("1000"),
        "price": Decimal("123.45"),
        "metadata": {
            "score": Decimal("0.12345678901234567890"),
            "weights": [Decimal("1.25")],
        },
    })

    raw = store.trades_file.read_text(encoding="utf-8")
    assert '"0.12345678901234567890"' in raw
    assert "0.12345678901234568" not in raw

    loaded = store.load_trades()[0]
    assert loaded["metadata"]["score"] == "0.12345678901234567890"


def test_portfolio_jsonl_store_overwrite_serializes_nested_decimals(tmp_path):
    store = PortfolioJsonlStore(tmp_path)

    store.overwrite_trades([
        {"stock_code": "2330", "source_summary": {"total_score": Decimal("88.0001")}},
    ])

    assert '"88.0001"' in store.trades_file.read_text(encoding="utf-8")
