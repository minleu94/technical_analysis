import pytest
from decimal import Decimal
from decision_module.weight_contract import (
    RecommendationWeightContract,
    InvalidWeightError,
    LegacyWeightMigrationAdapter,
    WeightMigrationError
)

def test_recommendation_weight_contract_success():
    # 合法的整數 bp，總和為 10000
    weights = {'pattern': 3000, 'technical': 5000, 'volume': 2000}
    contract = RecommendationWeightContract(weights)
    assert contract.weights['pattern'] == 3000
    assert contract.weights['technical'] == 5000
    assert contract.weights['volume'] == 2000

def test_recommendation_weight_contract_invalid_sum():
    # 總和不等於 10000
    weights = {'pattern': 3000, 'technical': 5000, 'volume': 1999}
    with pytest.raises(InvalidWeightError) as excinfo:
        RecommendationWeightContract(weights)
    assert "總和必須嚴格等於 10000 bp" in str(excinfo.value)

def test_recommendation_weight_contract_non_integer():
    # 含有非整數 bp
    weights = {'pattern': 3000, 'technical': 5000.5, 'volume': 1999} # 即使總和是 10000 也不行
    with pytest.raises(InvalidWeightError) as excinfo:
        RecommendationWeightContract(weights)
    assert "必須為整數" in str(excinfo.value)

def test_legacy_weight_migration_success():
    # 正常的舊版浮點數權重遷移 (無損)
    float_weights = {'pattern': 0.3, 'technical': 0.5, 'volume': 0.2}
    bp_weights = LegacyWeightMigrationAdapter.migrate_float_to_bp(float_weights)
    assert bp_weights['pattern'] == 3000
    assert bp_weights['technical'] == 5000
    assert bp_weights['volume'] == 2000

def test_legacy_weight_migration_precision_loss():
    # 轉換後乘積有小數點（非整數 bp），一律拋出 WeightMigrationError 拒絕
    float_weights = {'pattern': 0.33333, 'technical': 0.5, 'volume': 0.16667}
    # 0.33333 * 10000 = 3333.3 非整數 bp
    with pytest.raises(WeightMigrationError) as excinfo:
        LegacyWeightMigrationAdapter.migrate_float_to_bp(float_weights)
    assert "轉換後含有小數點" in str(excinfo.value)

def test_legacy_weight_migration_invalid_sum():
    # 轉換後總和不為 10000 bp，拋出 WeightMigrationError 拒絕
    float_weights = {'pattern': 0.3, 'technical': 0.5, 'volume': 0.199} # 總和 0.999 -> 9990 bp
    with pytest.raises(WeightMigrationError) as excinfo:
        LegacyWeightMigrationAdapter.migrate_float_to_bp(float_weights)
    assert "總和不為 10000 bp" in str(excinfo.value)
