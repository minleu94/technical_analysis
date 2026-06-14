"""
推薦權重契約 (Recommendation Weight Contract)
定義推薦與打分權重的合約規範，限制使用整數基點 (bp) 且總和固定為 10000 bp。
"""

import logging
import json
from typing import Dict, Any, Optional
from decimal import Decimal

logger = logging.getLogger(__name__)


class InvalidWeightError(ValueError):
    """權重格式或數值不合規異常"""
    pass


class WeightMigrationError(ValueError):
    """舊版權重遷移失敗異常"""
    pass


class RecommendationWeightContract:
    """打分與推薦權重合約 (限整數基點 bp)"""

    # 預設權重 (以 bp 為單位)
    DEFAULT_WEIGHTS = {
        'pattern': 3000,
        'technical': 5000,
        'volume': 2000
    }

    def __init__(self, weights: Optional[Dict[str, int]] = None):
        """
        初始化權重合約
        
        Args:
            weights: 權重字典，其值必須為整數 bp，總和必須為 10000
        """
        self._weights = self.validate_and_enforce(weights or self.DEFAULT_WEIGHTS)

    @property
    def weights(self) -> Dict[str, int]:
        """獲取以基點為單位的整數權重"""
        return self._weights

    @classmethod
    def validate_enforce_single(cls, val: Any, name: str) -> int:
        """驗證單一權重是否為合規的整數 bp"""
        if isinstance(val, bool):
            raise InvalidWeightError(f"權重 {name} 不可為 bool。")
        if not isinstance(val, int):
            raise InvalidWeightError(f"權重 {name} 必須為整數 (實際為 {type(val)})。")
        if val < 0:
            raise InvalidWeightError(f"權重 {name} 不可小於 0 (實際為 {val})。")
        return val

    @classmethod
    def validate_and_enforce(cls, weights: Dict[str, Any]) -> Dict[str, int]:
        """
        驗證權重是否合規。若總和不為 10000 bp 或含有非整數，直接拋出 InvalidWeightError，不進行任何微調。
        """
        if not isinstance(weights, dict):
            raise InvalidWeightError("權重配置必須為字典格式。")

        required_keys = {'pattern', 'technical', 'volume'}
        actual_keys = set(weights.keys())
        if actual_keys != required_keys:
            raise InvalidWeightError(f"權重鍵值不匹配。預期: {required_keys}，實際: {actual_keys}。")

        sanitized = {}
        for k in required_keys:
            sanitized[k] = cls.validate_enforce_single(weights[k], k)

        # 驗證總和
        total = sum(sanitized.values())
        if total != 10000:
            raise InvalidWeightError(f"權重基點總和必須嚴格等於 10000 bp (實際總和: {total})，拒絕執行。")

        return sanitized

    def to_json(self) -> str:
        """序列化為 JSON"""
        return json.dumps(self._weights)

    @classmethod
    def from_json(cls, json_str: str) -> 'RecommendationWeightContract':
        """從 JSON 反序列化"""
        try:
            w = json.loads(json_str)
            return cls(w)
        except Exception as e:
            if isinstance(e, InvalidWeightError):
                raise e
            raise InvalidWeightError(f"JSON 反序列化權重失敗: {e}")

    def to_dict(self) -> Dict[str, int]:
        """轉換為字典"""
        return self._weights.copy()


class LegacyWeightMigrationAdapter:
    """舊版浮點數權重遷移適配器"""

    @classmethod
    def migrate_float_to_bp(cls, float_weights: Dict[str, float]) -> Dict[str, int]:
        """
        使用 Decimal 將舊的浮點數權重無損且嚴格轉換為整數 bp。
        若乘積非整數或總和不等於 10000 bp，直接拋出 WeightMigrationError。
        """
        if not isinstance(float_weights, dict) or not float_weights:
            raise WeightMigrationError("輸入的浮點數權重必須為非空字典。")

        required_keys = {'pattern', 'technical', 'volume'}
        actual_keys = set(float_weights.keys())
        if actual_keys != required_keys:
            raise WeightMigrationError(
                f"浮點數權重鍵值不匹配。預期: {required_keys}，實際: {actual_keys}。"
            )

        bp_weights = {}
        factor = Decimal('10000')

        for k in ['pattern', 'technical', 'volume']:
            val = float_weights[k]
            try:
                # 採用 Decimal(str(value)) 無損高精度轉換
                dec_val = Decimal(str(val))
                product = dec_val * factor
                
                # 校驗乘積是否為整數
                if product != product.to_integral_value():
                    raise WeightMigrationError(f"權重 {k} 轉換後含有小數點: {product}")
                
                bp_weights[k] = int(product)
            except Exception as e:
                if isinstance(e, WeightMigrationError):
                    raise e
                raise WeightMigrationError(f"舊版權重 {k} 的值 {val} 轉換失敗: {e}")

        # 校驗總和
        total = sum(bp_weights.values())
        if total != 10000:
            raise WeightMigrationError(
                f"浮點數權重轉換基點後，總和不為 10000 bp (實際總和: {total})，拒絕自動微調補差額。"
            )

        logger.info(f"[WeightMigration] 成功將舊版浮點數權重 {float_weights} 遷移至 bp: {bp_weights}")
        return bp_weights
