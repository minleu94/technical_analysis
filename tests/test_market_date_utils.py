from data_module.market_date_utils import convert_date_format, convert_to_datetime, convert_roc_date
def test_date_utilities():
    assert convert_date_format("113/03/29") == "20240329"
    assert convert_date_format("2024-03-29", True) == "113/03/29"
    assert convert_to_datetime("20240329").strftime("%Y-%m-%d") == "2024-03-29"
    assert convert_roc_date("111/01/04") == "2022/01/04"
