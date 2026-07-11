from collections.abc import Collection, Mapping


def resolve_pattern_column(
    columns: Collection[str],
    reverse_mapping: Mapping[str, str],
    eng_name: str,
) -> str | None:
    """依既有優先順序解析圖形分析欄位名稱。"""
    chinese_name = reverse_mapping.get(eng_name)
    if chinese_name in columns:
        return chinese_name
    if eng_name in columns:
        return eng_name
    return None
