"""券商分點 registry 的純文字與分類規則。"""

from typing import Optional


MOJIBAKE_MARKERS = ("æ", "Ã", "â€", "â€™", "â€œ", "Ã©", "Ã¨")
HEADQUARTERS_KEYWORDS = (
    "證券",
    "環球",
    "瑞銀",
    "麥格理",
    "野村",
    "匯豐",
    "高盛",
    "摩根士丹利",
    "摩根大通",
    "土銀",
    "大和國泰",
    "美林",
    "康和",
    "凱基",
)


def detect_mojibake(text: str) -> bool:
    if not text or not isinstance(text, str):
        return False
    return any(marker in text for marker in MOJIBAKE_MARKERS)


def fix_mojibake(text: str) -> Optional[str]:
    if not text or not isinstance(text, str):
        return None
    try:
        fixed = text.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    return fixed if not detect_mojibake(fixed) else None


def decode_unicode_hex(value: str) -> str:
    if not value or not isinstance(value, str):
        return value
    normalized = value.strip()
    if 12 <= len(normalized) < 16 and all(
        char in "0123456789abcdefABCDEF" for char in normalized
    ):
        normalized = normalized.zfill(16)
    if len(normalized) != 16 or not all(
        char in "0123456789abcdefABCDEF" for char in normalized
    ):
        return value
    try:
        return "".join(
            chr(int(normalized[index : index + 4], 16))
            for index in range(0, len(normalized), 4)
        )
    except (ValueError, OverflowError):
        return value


def is_headquarters(broker_code: str, branch_code: str, display_name: str) -> bool:
    if broker_code == branch_code:
        return True
    if "-" in display_name or "分公司" in display_name or "分行" in display_name:
        return False
    return any(keyword in display_name for keyword in HEADQUARTERS_KEYWORDS)
