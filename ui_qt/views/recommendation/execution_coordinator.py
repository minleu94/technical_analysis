"""RecommendationView 執行驗證與 service request。"""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any, Callable


ProgressCallback = Callable[[str, int], None]
CancellationCallback = Callable[[], bool]


def _supports_named_keyword(method: Any, name: str) -> bool:
    """檢查 service 是否支援指定 callback keyword，保留舊替身相容性。"""

    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.name == name
        or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )


def _supports_explicit_keyword(method: Any, name: str) -> bool:
    """只接受明確宣告的 keyword，避免舊 variadic double 改變呼叫形狀。"""

    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(parameter.name == name for parameter in parameters)


def _invoke_with_optional_cancellation(
    method: Any,
    *,
    cancellation_callback: CancellationCallback | None,
    progress_callback: ProgressCallback | None = None,
    **kwargs: Any,
) -> Any:
    """只對新版 service 傳遞合作式取消 callback。

    RecommendationService 的既有介面沒有取消參數；透過簽章檢查只在
    service 明確支援時注入 callback，讓舊 service double 與既有呼叫契約
    維持不變。
    """

    call_kwargs = dict(kwargs)
    if progress_callback is not None and _supports_explicit_keyword(method, "progress_callback"):
        call_kwargs["progress_callback"] = progress_callback
    if cancellation_callback is not None:
        if _supports_named_keyword(method, "cancel_callback"):
            call_kwargs["cancel_callback"] = cancellation_callback
        elif _supports_named_keyword(method, "cancellation_callback"):
            call_kwargs["cancellation_callback"] = cancellation_callback
    return method(**call_kwargs)


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
        *,
        cancellation_callback: CancellationCallback | None = None,
        detailed_progress: bool = False,
    ) -> Any:
        if progress_callback:
            progress_callback("讀取股票數據...", 10)
        if cancellation_callback is not None and cancellation_callback():
            if progress_callback:
                progress_callback("已取消：推薦分析尚未開始", 10)
            return []

        # 舊 callback 只收到原本的兩個 checkpoint；UI 另行要求詳細進度時，
        # 才加入可量化的候選範圍、規則分析與結果整理階段。
        if detailed_progress and progress_callback:
            progress_callback("建立分析範圍...", 25)
            progress_callback("執行推薦規則...", 35)

        recommendations = _invoke_with_optional_cancellation(
            recommendation_service.run_recommendation,
            cancellation_callback=cancellation_callback,
            progress_callback=progress_callback,
            config=self.config,
            max_stocks=self.max_stocks,
            top_n=self.top_n,
        )
        if cancellation_callback is not None and cancellation_callback():
            if progress_callback:
                progress_callback("已取消：推薦分析結果未套用", 90)
            return []
        if detailed_progress and progress_callback:
            progress_callback("整理推薦結果...", 90)
        if progress_callback:
            progress_callback("分析完成", 100)
        return recommendations
