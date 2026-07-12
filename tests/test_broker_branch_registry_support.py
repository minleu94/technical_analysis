from app_module.broker_branch_registry import (
    decode_unicode_hex,
    detect_mojibake,
    fix_mojibake,
    is_headquarters,
)


def test_registry_text_helpers_preserve_decode_and_mojibake_contract() -> None:
    assert decode_unicode_hex("3800380038004b") == "888K"
    assert decode_unicode_hex("not-hex") == "not-hex"
    assert detect_mojibake("æ¸¬è©¦") is True
    assert fix_mojibake("æ¸¬è©¦") == "測試"


def test_headquarters_detection_preserves_code_and_display_name_rules() -> None:
    assert is_headquarters("9A00", "9A00", "永豐金證券") is True
    assert is_headquarters("9A00", "9A01", "永豐金-台中") is False
    assert is_headquarters("A", "B", "瑞銀") is True
