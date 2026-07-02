import unicodedata

from PySide6.QtWidgets import QPushButton, QWidget

_EMOJI_FORMAT_CHARS = {"\ufe0e", "\ufe0f", "\u200d"}
_LEADING_SYMBOL_CATEGORIES = {"So", "Sk"}


def strip_leading_symbol_icon(text: str) -> str:
    """Remove emoji-style prefix icons that can render as tofu on Windows Qt."""
    value = str(text or "")
    index = 0
    removed_icon = False

    while index < len(value):
        char = value[index]
        category = unicodedata.category(char)
        if category in _LEADING_SYMBOL_CATEGORIES or char in _EMOJI_FORMAT_CHARS:
            removed_icon = True
            index += 1
            continue
        if removed_icon and char.isspace():
            index += 1
            continue
        break

    return value[index:] if removed_icon else value


def remove_symbol_icons(text: str) -> str:
    cleaned = []
    for char in str(text or ""):
        category = unicodedata.category(char)
        if category in _LEADING_SYMBOL_CATEGORIES or char in _EMOJI_FORMAT_CHARS:
            continue
        cleaned.append(char)
    return "".join(cleaned)


def sanitize_button_texts(root: QWidget) -> None:
    for button in root.findChildren(QPushButton):
        cleaned = strip_leading_symbol_icon(button.text())
        if cleaned != button.text():
            button.setText(cleaned)
