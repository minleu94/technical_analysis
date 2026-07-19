from datetime import date

from data_module.tpex_disposal_artifact import parse_s46_disposal_csv


def test_s46_uses_official_t_plus_one_availability() -> None:
    payload = "公告日期,股票代號,處置起日,處置迄日,處置原因,處置內容\n20260717,1234,20260718,20260731,reason,content\n\n資料日期: 20260717\n資料產製時間: 20260717 18:30:00\n資料筆數: 1\n".encode()
    row = parse_s46_disposal_csv(payload=payload)[0]
    assert row["available_date"] == "2026-07-18"
    assert row["symbol"] == "1234"
