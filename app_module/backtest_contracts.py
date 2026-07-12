"""回測服務使用的結構型輸入契約。"""

from __future__ import annotations

from typing import Any, Dict, Protocol


class WalkForwardResultContract(Protocol):
    """BacktestService 計算過擬合風險所需的最小 Walk-forward 介面。"""

    train_metrics: Dict[str, Any]
    test_metrics: Dict[str, Any]
