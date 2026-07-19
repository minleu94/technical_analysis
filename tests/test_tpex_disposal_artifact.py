from datetime import date

from data_module.tpex_disposal_artifact import parse_s46_disposal_csv


def test_s46_uses_official_t_plus_one_availability() -> None:
    payload = "公布日期,證券代號,處置開始日期,處置結束日期,處置原因(英文說明),處置內容(英文說明)\n20260717,1234,20260718,20260731,reason,content\n".encode()
    row = parse_s46_disposal_csv(payload=payload, production_date=date(2026, 7, 17))[0]
    assert row["available_date"] == "2026-07-18"
    assert row["symbol"] == "1234"
