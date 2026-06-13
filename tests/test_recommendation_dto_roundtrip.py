import pytest
from app_module.dtos import RecommendationDTO, RecommendationResultDTO

def test_recommendation_dto_roundtrip():
    dto = RecommendationDTO(
        stock_code="1101",
        stock_name="台泥",
        close_price=45.5,
        price_change=1.2,
        total_score=85.5,
        indicator_score=80.0,
        pattern_score=90.0,
        volume_score=85.0,
        recommendation_reasons="均線多頭排列",
        industry="水泥工業",
        regime_match=True,
        score_percentile_bp=8000,
        eligible_universe_size=50,
        eligible_universe_date="2026-06-12",
        ranking_method="nearest_rank",
        threshold_mode="quantile"
    )
    
    serialized = dto.to_dict()
    assert serialized["score_percentile_bp"] == 8000
    assert serialized["eligible_universe_size"] == 50
    assert serialized["eligible_universe_date"] == "2026-06-12"
    assert serialized["ranking_method"] == "nearest_rank"
    assert serialized["threshold_mode"] == "quantile"
    
    # 檢查中文 key
    assert serialized["百分位"] == "80.00%"
    assert serialized["母體數"] == 50
    assert serialized["門檻模式"] == "百分位"
    
    deserialized = RecommendationDTO.from_dict(serialized)
    assert deserialized.stock_code == "1101"
    assert deserialized.stock_name == "台泥"
    assert deserialized.close_price == 45.5
    assert deserialized.price_change == 1.2
    assert deserialized.total_score == 85.5
    assert deserialized.score_percentile_bp == 8000
    assert deserialized.threshold_mode == "quantile"

def test_recommendation_dto_compat_with_legacy_and_chinese_keys():
    # 只有中文 key，且缺少任何 metadata 欄位（歷史 JSON 格式）
    legacy_data = {
        "證券代號": "2330",
        "證券名稱": "台積電",
        "收盤價": 600.0,
        "漲幅%": 2.5,
        "總分": 90.0,
        "指標分": 85.0,
        "圖形分": 95.0,
        "成交量分": 90.0,
        "推薦理由": "W底形成",
        "產業": "半導體業",
        "Regime匹配": "是"
    }
    
    deserialized = RecommendationDTO.from_dict(legacy_data)
    assert deserialized.stock_code == "2330"
    assert deserialized.stock_name == "台積電"
    assert deserialized.close_price == 600.0
    assert deserialized.price_change == 2.5
    assert deserialized.total_score == 90.0
    assert deserialized.regime_match is True
    # 預設值
    assert deserialized.score_percentile_bp is None
    assert deserialized.threshold_mode == "fixed"

def test_recommendation_result_dto_roundtrip():
    result_dto = RecommendationResultDTO(
        result_id="rec_20260613_120000",
        result_name="推薦結果_測試",
        config={"param1": "val1"},
        recommendations=[
            RecommendationDTO(
                stock_code="1101",
                stock_name="台泥",
                close_price=45.5,
                price_change=1.2,
                total_score=85.5,
                indicator_score=80.0,
                pattern_score=90.0,
                volume_score=85.0,
                recommendation_reasons="均線多頭",
                industry="水泥",
                regime_match=True,
                score_percentile_bp=8000,
                threshold_mode="quantile"
            )
        ],
        regime="Trend",
        created_at="2026-06-13T12:00:00",
        notes="測試記錄"
    )
    
    serialized = result_dto.to_dict()
    deserialized = RecommendationResultDTO.from_dict(serialized)
    
    assert deserialized.result_id == "rec_20260613_120000"
    assert len(deserialized.recommendations) == 1
    assert deserialized.recommendations[0].stock_code == "1101"
    assert deserialized.recommendations[0].score_percentile_bp == 8000
    assert deserialized.recommendations[0].threshold_mode == "quantile"
