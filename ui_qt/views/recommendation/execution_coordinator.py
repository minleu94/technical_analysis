"""RecommendationView 執行驗證與 service request。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


ProgressCallback = Callable[[str, int], None]


@dataclass(frozen=True)
class RecommendationExecutionRequest:
    config: dict[str, Any]
    max_stocks: int = 200
    top_n: int = 50

    def validation_error(self) -> str | None:
        if not self.config.get("patterns", {}).get("selected", []):
            return "請至少選擇一個圖形模式"
        if not self.config.get("signals", {}).get("technical_indicators", []):
            return "請至少選擇一個技術指標"
        return None

    def execute(
        self,
        recommendation_service: Any,
        progress_callback: ProgressCallback | None = None,
    ) -> Any:
        if progress_callback:
            progress_callback("讀取股票數據...", 10)
        recommendations = recommendation_service.run_recommendation(
            config=self.config,
            max_stocks=self.max_stocks,
            top_n=self.top_n,
        )
        if progress_callback:
            progress_callback("分析完成", 100)
        return recommendations
