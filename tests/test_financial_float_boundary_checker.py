from dataclasses import FrozenInstanceError

import pytest

from scripts.check_financial_float_boundaries import (
    ALLOWED_CATEGORIES,
    BoundaryCheckError,
    Violation,
    scan_source,
)


def test_allowed_categories_are_exact() -> None:
    assert ALLOWED_CATEGORIES == frozenset(
        {"dto", "analytics", "visualization"}
    )
    assert isinstance(ALLOWED_CATEGORIES, frozenset)


def test_violation_is_frozen_and_exposes_fields() -> None:
    violation = Violation(
        path="sample.py",
        line=2,
        column=3,
        rule="NFB001",
        expression="float(...)",
        message="message",
    )

    assert (
        violation.path,
        violation.line,
        violation.column,
        violation.rule,
        violation.expression,
        violation.message,
    ) == ("sample.py", 2, 3, "NFB001", "float(...)", "message")
    with pytest.raises(FrozenInstanceError):
        violation.line = 4  # type: ignore[misc]


def test_scan_source_uses_memory_as_default_path() -> None:
    violations = scan_source("value = float(raw)\n")

    assert [item.path for item in violations] == ["<memory>"]


def test_unmarked_float_call_is_reported() -> None:
    violations = scan_source("value = float(raw)\n", path="sample.py")

    assert [(item.rule, item.line, item.expression) for item in violations] == [
        ("NFB001", 1, "float(...)")
    ]


@pytest.mark.parametrize("category", ["dto", "analytics", "visualization"])
def test_supported_boundary_categories_allow_same_line_float(category: str) -> None:
    source = f"value = float(raw)  # numeric-boundary: {category}\n"

    assert scan_source(source, path="sample.py") == []


def test_compact_valid_boundary_marker_is_allowed() -> None:
    source = "value = float(raw)  #numeric-boundary:dto\n"

    assert scan_source(source, path="sample.py") == []


def test_invalid_boundary_category_is_reported_once() -> None:
    violations = scan_source(
        "left = float(a); right = float(b)  # numeric-boundary: allow\n",
        path="sample.py",
    )

    assert [(item.rule, item.line) for item in violations] == [("NFB004", 1)]


def test_malformed_boundary_marker_is_reported_once() -> None:
    violations = scan_source(
        "left = float(a); right = float(b)  # numeric-boundary dto\n",
        path="sample.py",
    )

    assert [(item.rule, item.line) for item in violations] == [("NFB004", 1)]


@pytest.mark.parametrize(
    "source",
    [
        "# The numeric-boundary checker documents policy\n",
        "# not-a-numeric-boundary: dto\n",
    ],
)
def test_unrelated_numeric_boundary_comments_are_ignored(source: str) -> None:
    assert scan_source(source, path="sample.py") == []


@pytest.mark.parametrize(
    ("source", "rule", "expression"),
    [
        ("values.astype(float)\n", "NFB002", ".astype(float)"),
        ('values.astype("float")\n', "NFB002", ".astype(float)"),
        ("pd.Series(values, dtype=float)\n", "NFB003", "dtype=float"),
        ('pd.Series(values, dtype="float")\n', "NFB003", "dtype=float"),
    ],
)
def test_numpy_pandas_float_boundaries_are_reported(
    source: str,
    rule: str,
    expression: str,
) -> None:
    violations = scan_source(source, path="sample.py")

    assert [(item.rule, item.expression) for item in violations] == [
        (rule, expression)
    ]


@pytest.mark.parametrize(
    ("source", "rule", "expected_line"),
    [
        (
            "pd.Series(\n"
            "    values,\n"
            "    dtype=float,\n"
            ")\n",
            "NFB003",
            3,
        ),
        (
            "values.astype(\n"
            "    float,\n"
            ")\n",
            "NFB002",
            2,
        ),
        (
            "value = float(\n"
            "    raw,\n"
            ")\n",
            "NFB001",
            1,
        ),
    ],
)
def test_multiline_boundary_is_reported_on_managed_float_token_line(
    source: str,
    rule: str,
    expected_line: int,
) -> None:
    violations = scan_source(source, path="sample.py")

    assert [(item.rule, item.line) for item in violations] == [
        (rule, expected_line)
    ]


@pytest.mark.parametrize(
    "source",
    [
        (
            "pd.Series(\n"
            "    values,\n"
            "    dtype=float,  # numeric-boundary: analytics\n"
            ")\n"
        ),
        (
            "values.astype(\n"
            "    float,  # numeric-boundary: analytics\n"
            ")\n"
        ),
        (
            "value = float(  # numeric-boundary: dto\n"
            "    raw,\n"
            ")\n"
        ),
    ],
)
def test_multiline_boundary_marker_applies_to_managed_float_token_line(
    source: str,
) -> None:
    assert scan_source(source, path="sample.py") == []


def test_comments_strings_and_previous_line_marker_do_not_hide_violation() -> None:
    source = (
        "# float(raw)\n"
        'message = "float(raw)"\n'
        "# numeric-boundary: dto\n"
        "value = float(raw)\n"
    )

    violations = scan_source(source, path="sample.py")

    assert [(item.rule, item.line) for item in violations] == [("NFB001", 4)]


def test_violations_are_sorted_by_line_column_and_rule() -> None:
    source = (
        "right = float(b); left = float(a)\n"
        "values.astype(float)\n"
        "pd.Series(values, dtype=float)\n"
    )

    violations = scan_source(source, path="sample.py")

    assert [
        (item.line, item.column, item.rule)
        for item in violations
    ] == sorted(
        (item.line, item.column, item.rule)
        for item in violations
    )


def test_syntax_error_raises_boundary_check_error() -> None:
    with pytest.raises(BoundaryCheckError, match="無法解析"):
        scan_source("value = float(\n", path="broken.py")


def test_tokenize_error_raises_boundary_check_error() -> None:
    with pytest.raises(BoundaryCheckError, match="無法解析註解"):
        scan_source("value = (\n", path="broken.py")
