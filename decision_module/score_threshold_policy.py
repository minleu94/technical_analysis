import bisect
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Sequence, Union
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class ScoreThresholdResult:
    score_bp: pd.Series
    buy_threshold_score_bp: pd.Series
    sell_threshold_score_bp: pd.Series
    warmup_ready: pd.Series
    buy_candidate: pd.Series
    sell_candidate: pd.Series

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame({
            "score_bp": self.score_bp,
            "buy_threshold_score_bp": self.buy_threshold_score_bp,
            "sell_threshold_score_bp": self.sell_threshold_score_bp,
            "threshold_warmup_ready": self.warmup_ready,
            "buy_threshold_hit": self.buy_candidate,
            "sell_threshold_hit": self.sell_candidate,
        })

def quantize_score_to_basis_points(value: object) -> Optional[int]:
    if value is None or pd.isna(value):
        return None
    # If the value is a float, convert to string first to avoid floating point precision issues
    score = Decimal(str(value))
    if score < Decimal("0") or score > Decimal("100"):
        raise ValueError("score must be between 0 and 100")
    return int((score * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def nearest_rank(sorted_values: Sequence[int], quantile_bp: int) -> int:
    if not sorted_values:
        raise ValueError("sorted_values cannot be empty")
    rank = max(1, (len(sorted_values) * quantile_bp + 9999) // 10000)
    return sorted_values[rank - 1]

class ScoreThresholdPolicy:
    def __init__(self, params: dict):
        if not isinstance(params, dict):
            raise ValueError("params must be a dict")
        
        self.threshold_mode = params.get("threshold_mode", "fixed")
        if self.threshold_mode not in ["fixed", "quantile"]:
            raise ValueError(f"Invalid threshold_mode: {self.threshold_mode}")
        
        if self.threshold_mode == "fixed":
            self.buy_score = params.get("buy_score", 60.0)
            self.sell_score = params.get("sell_score", 40.0)
        else:  # quantile
            required_keys = [
                "buy_quantile_bp",
                "sell_quantile_bp",
                "quantile_warmup_observations",
                "quantile_method",
            ]
            for key in required_keys:
                if key not in params:
                    raise ValueError(f"Missing required quantile parameter: {key}")
            
            self.buy_quantile_bp = params["buy_quantile_bp"]
            self.sell_quantile_bp = params["sell_quantile_bp"]
            self.warmup_observations = params["quantile_warmup_observations"]
            self.quantile_method = params["quantile_method"]
            
            if self.quantile_method != "nearest_rank":
                raise ValueError(f"Unsupported quantile_method: {self.quantile_method}")
            
            if not (0 <= self.buy_quantile_bp <= 10000):
                raise ValueError("buy_quantile_bp must be between 0 and 10000")
            if not (0 <= self.sell_quantile_bp <= 10000):
                raise ValueError("sell_quantile_bp must be between 0 and 10000")
            if self.buy_quantile_bp == self.sell_quantile_bp:
                raise ValueError("buy_quantile_bp and sell_quantile_bp cannot be equal")
            if self.warmup_observations <= 0:
                raise ValueError("quantile_warmup_observations must be positive")

    def evaluate(self, scores: pd.Series) -> ScoreThresholdResult:
        if not isinstance(scores, pd.Series):
            raise ValueError("scores must be a pandas Series")
        
        score_bp = scores.apply(quantize_score_to_basis_points)
        
        if self.threshold_mode == "fixed":
            buy_candidate = scores >= self.buy_score
            sell_candidate = scores <= self.sell_score
            
            # For fixed mode, buy_threshold_score_bp and sell_threshold_score_bp are filled with fixed values
            buy_threshold_val = quantize_score_to_basis_points(self.buy_score)
            sell_threshold_val = quantize_score_to_basis_points(self.sell_score)
            
            buy_threshold_score_bp = pd.Series(buy_threshold_val, index=scores.index)
            sell_threshold_score_bp = pd.Series(sell_threshold_val, index=scores.index)
            
            warmup_ready = pd.Series(True, index=scores.index)
        else:  # quantile
            buy_threshold_score_bp = pd.Series(np.nan, index=scores.index)
            sell_threshold_score_bp = pd.Series(np.nan, index=scores.index)
            warmup_ready = pd.Series(False, index=scores.index)
            buy_candidate = pd.Series(False, index=scores.index)
            sell_candidate = pd.Series(False, index=scores.index)
            
            history = []
            for position, raw_score in enumerate(scores):
                current_bp = quantize_score_to_basis_points(raw_score)
                if len(history) >= self.warmup_observations and current_bp is not None:
                    buy_threshold = nearest_rank(history, self.buy_quantile_bp)
                    sell_threshold = nearest_rank(history, self.sell_quantile_bp)
                    
                    buy_threshold_score_bp.iloc[position] = buy_threshold
                    sell_threshold_score_bp.iloc[position] = sell_threshold
                    
                    buy_candidate.iloc[position] = current_bp >= buy_threshold
                    sell_candidate.iloc[position] = current_bp <= sell_threshold
                    warmup_ready.iloc[position] = True
                    
                if current_bp is not None:
                    bisect.insort(history, current_bp)
                    
        return ScoreThresholdResult(
            score_bp=score_bp,
            buy_threshold_score_bp=buy_threshold_score_bp,
            sell_threshold_score_bp=sell_threshold_score_bp,
            warmup_ready=warmup_ready,
            buy_candidate=buy_candidate,
            sell_candidate=sell_candidate,
        )
