from decimal import Decimal
from app_module.execution_slippage_model import TaiwanStockTickSlippageModel


def test_taiwan_stock_tick_slippage_boundaries():
    model = TaiwanStockTickSlippageModel(ticks=1)

    # Boundary 1: price < 10 (tick = 0.01)
    # Buy 9.99 -> 10.00
    assert model.calculate_fill_price(Decimal("9.99"), "buy") == Decimal("10.00")
    # Sell 9.99 -> 9.98
    assert model.calculate_fill_price(Decimal("9.99"), "sell") == Decimal("9.98")

    # Boundary 2: 10 <= price < 50 (tick = 0.05)
    # Buy 10.00 -> 10.05
    assert model.calculate_fill_price(Decimal("10.00"), "buy") == Decimal("10.05")
    # Buy 49.95 -> 50.00
    assert model.calculate_fill_price(Decimal("49.95"), "buy") == Decimal("50.00")
    # Sell 49.95 -> 49.90
    assert model.calculate_fill_price(Decimal("49.95"), "sell") == Decimal("49.90")

    # Boundary 3: 50 <= price < 100 (tick = 0.10)
    # Buy 50.00 -> 50.10
    assert model.calculate_fill_price(Decimal("50.00"), "buy") == Decimal("50.10")
    # Buy 99.90 -> 100.00
    assert model.calculate_fill_price(Decimal("99.90"), "buy") == Decimal("100.00")
    # Sell 99.90 -> 99.80
    assert model.calculate_fill_price(Decimal("99.90"), "sell") == Decimal("99.80")

    # Boundary 4: 100 <= price < 500 (tick = 0.50)
    # Buy 100.00 -> 100.50
    assert model.calculate_fill_price(Decimal("100.00"), "buy") == Decimal("100.50")
    # Buy 499.50 -> 500.00
    assert model.calculate_fill_price(Decimal("499.50"), "buy") == Decimal("500.00")
    # Sell 499.50 -> 499.00
    assert model.calculate_fill_price(Decimal("499.50"), "sell") == Decimal("499.00")

    # Boundary 5: 500 <= price < 1000 (tick = 1.00)
    # Buy 500.00 -> 501.00
    assert model.calculate_fill_price(Decimal("500.00"), "buy") == Decimal("501.00")
    # Buy 999.00 -> 1000.00
    assert model.calculate_fill_price(Decimal("999.00"), "buy") == Decimal("1000.00")
    # Sell 999.00 -> 998.00
    assert model.calculate_fill_price(Decimal("999.00"), "sell") == Decimal("998.00")

    # Boundary 6: 1000 <= price (tick = 5.00)
    # Buy 1000.00 -> 1005.00
    assert model.calculate_fill_price(Decimal("1000.00"), "buy") == Decimal("1005.00")
    # Sell 1000.00 -> 995.00
    assert model.calculate_fill_price(Decimal("1000.00"), "sell") == Decimal("995.00")
    
    # 確保不會變成負數
    assert model.calculate_fill_price(Decimal("0.00"), "sell") == Decimal("0.01")
