def resolve_ml_column(columns, reverse_mapping, eng_name):
    chinese_name = reverse_mapping.get(eng_name)
    if chinese_name in columns:
        return chinese_name
    if eng_name in columns:
        return eng_name
    return None
