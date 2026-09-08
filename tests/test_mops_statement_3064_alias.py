from scripts import build_mops_statement_pit_candidate as candidate


def test_3064_display_name_alias_requires_exact_official_income_code_and_value() -> None:
    official = candidate.OfficialItemCode(
        item_code="4600",
        official_item_name="勞務收入合計",
        xbrl_concept="ifrs-full:RevenueFromRenderingOfServices",
        reported_value="19,635",
        indent_depth=2,
    )

    resolved = candidate.resolve_official_item_code(
        "勞務收入淨額",
        {"勞務收入合計": (official,)},
        statement_type="income_statement",
        candidate_value=19_635_000,
        candidate_scale=1000,
        candidate_indent_depth=2,
    )

    assert resolved is official


def test_3064_display_name_alias_does_not_accept_wrong_period_value() -> None:
    official = candidate.OfficialItemCode(
        item_code="4600",
        official_item_name="勞務收入合計",
        xbrl_concept="ifrs-full:RevenueFromRenderingOfServices",
        reported_value="18,894",
        indent_depth=2,
    )

    resolved = candidate.resolve_official_item_code(
        "勞務收入淨額",
        {"勞務收入合計": (official,)},
        statement_type="income_statement",
        candidate_value=19_635_000,
        candidate_scale=1000,
        candidate_indent_depth=2,
    )

    assert resolved is None


def test_3064_display_name_alias_can_resolve_verified_total_after_exact_name_ambiguity() -> None:
    detail = candidate.OfficialItemCode(
        item_code="4610",
        official_item_name="勞務收入",
        xbrl_concept="ifrs-full:RevenueFromRenderingOfServices",
        reported_value="46,177",
        indent_depth=2,
    )
    nested_detail = candidate.OfficialItemCode(
        item_code="4611",
        official_item_name="勞務收入",
        xbrl_concept="tifrs-bsci-ci:ServiceRevenue-ServiceRevenue-ServiceRevenue",
        reported_value="46,177",
        indent_depth=3,
    )
    verified_total = candidate.OfficialItemCode(
        item_code="4600",
        official_item_name="勞務收入合計",
        xbrl_concept="tifrs-bsci-ci:ServiceRevenue",
        reported_value="46,177",
        indent_depth=2,
    )

    resolved = candidate.resolve_official_item_code(
        "勞務收入",
        {
            "勞務收入": (detail, nested_detail),
            "勞務收入合計": (verified_total,),
        },
        statement_type="income_statement",
        candidate_value=46_177_000,
        candidate_scale=1000,
        candidate_indent_depth=1,
    )

    assert resolved is verified_total


def test_3252_display_name_alias_requires_exact_official_income_code_and_value() -> None:
    official = candidate.OfficialItemCode(
        item_code="4410",
        official_item_name="餐旅服務收入",
        xbrl_concept="ifrs-full:RevenueFromHotelOperations",
        reported_value="102,346",
        indent_depth=2,
    )

    resolved = candidate.resolve_official_item_code(
        "餐旅服務收入淨額",
        {"餐旅服務收入": (official,)},
        statement_type="income_statement",
        candidate_value=102_346_000,
        candidate_scale=1000,
        candidate_indent_depth=2,
    )

    assert resolved is official


def test_3252_display_name_alias_rejects_total_or_wrong_period_value() -> None:
    total = candidate.OfficialItemCode(
        item_code="4400",
        official_item_name="旅遊服務收入合計",
        xbrl_concept="tifrs-bsci-ci:TravelServiceRevenue",
        reported_value="102,346",
        indent_depth=2,
    )
    wrong_period = candidate.OfficialItemCode(
        item_code="4410",
        official_item_name="餐旅服務收入",
        xbrl_concept="ifrs-full:RevenueFromHotelOperations",
        reported_value="111,173",
        indent_depth=2,
    )

    assert (
        candidate.resolve_official_item_code(
            "餐旅服務收入淨額",
            {"旅遊服務收入合計": (total,)},
            statement_type="income_statement",
            candidate_value=102_346_000,
            candidate_scale=1000,
            candidate_indent_depth=2,
        )
        is None
    )
    assert (
        candidate.resolve_official_item_code(
            "餐旅服務收入淨額",
            {"餐旅服務收入": (wrong_period,)},
            statement_type="income_statement",
            candidate_value=102_346_000,
            candidate_scale=1000,
            candidate_indent_depth=2,
        )
        is None
    )


def test_3252_display_name_aliases_match_official_total_names() -> None:
    revenue_total = candidate.OfficialItemCode(
        item_code="4400",
        official_item_name="旅遊服務收入合計",
        xbrl_concept="tifrs-bsci-ci:TravelServiceRevenue",
        reported_value="102,346",
        indent_depth=2,
    )
    cost_total = candidate.OfficialItemCode(
        item_code="5400",
        official_item_name="旅遊服務成本(觀光飯店業適用)合計",
        xbrl_concept="tifrs-bsci-ci:CostOfTravelServicesForHotelBusiness",
        reported_value="63,368",
        indent_depth=2,
    )

    assert (
        candidate.resolve_official_item_code(
            "旅遊服務收入",
            {"旅遊服務收入合計": (revenue_total,)},
            statement_type="income_statement",
            candidate_value=102_346_000,
            candidate_scale=1000,
            candidate_indent_depth=1,
        )
        is revenue_total
    )
    assert (
        candidate.resolve_official_item_code(
            "旅遊服務成本",
            {"旅遊服務成本(觀光飯店業適用)合計": (cost_total,)},
            statement_type="income_statement",
            candidate_value=63_368_000,
            candidate_scale=1000,
            candidate_indent_depth=1,
        )
        is cost_total
    )


def test_3379_3402_engineering_revenue_alias_requires_official_code_value_and_indent() -> None:
    official = candidate.OfficialItemCode(
        item_code="4520",
        official_item_name="工程收入",
        xbrl_concept="tifrs-bsci-ci:EngineeringServiceRevenue",
        reported_value="12,787",
        indent_depth=2,
    )

    resolved = candidate.resolve_official_item_code(
        "工程收入淨額",
        {"工程收入": (official,)},
        statement_type="income_statement",
        candidate_value=12_787_000,
        candidate_scale=1000,
        candidate_indent_depth=2,
    )

    assert resolved is official


def test_engineering_revenue_alias_rejects_wrong_value_or_ambiguous_rows() -> None:
    wrong_value = candidate.OfficialItemCode(
        item_code="4520",
        official_item_name="工程收入",
        xbrl_concept="tifrs-bsci-ci:EngineeringServiceRevenue",
        reported_value="1,571,381",
        indent_depth=2,
    )
    duplicate = candidate.OfficialItemCode(
        item_code="4500",
        official_item_name="工程收入",
        xbrl_concept="ifrs-full:RevenueFromConstructionContracts",
        reported_value="12,787",
        indent_depth=2,
    )

    assert (
        candidate.resolve_official_item_code(
            "工程收入淨額",
            {"工程收入": (wrong_value,)},
            statement_type="income_statement",
            candidate_value=12_787_000,
            candidate_scale=1000,
            candidate_indent_depth=2,
        )
        is None
    )
    correct_value_duplicate = candidate.OfficialItemCode(
        item_code="4521",
        official_item_name="工程收入",
        xbrl_concept="tifrs-bsci-ci:EngineeringServiceRevenueOther",
        reported_value="12,787",
        indent_depth=2,
    )
    assert (
        candidate.resolve_official_item_code(
            "工程收入淨額",
            {"工程收入": (duplicate, correct_value_duplicate)},
            statement_type="income_statement",
            candidate_value=12_787_000,
            candidate_scale=1000,
            candidate_indent_depth=2,
        )
        is None
    )


def test_construction_engineering_revenue_alias_uses_verified_total_row() -> None:
    official = candidate.OfficialItemCode(
        item_code="4500",
        official_item_name="營建工程收入合計",
        xbrl_concept="ifrs-full:RevenueFromConstructionContracts",
        reported_value="12,787",
        indent_depth=1,
    )

    assert (
        candidate.resolve_official_item_code(
            "營建工程收入",
            {"營建工程收入合計": (official,)},
            statement_type="income_statement",
            candidate_value=12_787_000,
            candidate_scale=1000,
            candidate_indent_depth=1,
        )
        is official
    )


def test_construction_engineering_cost_alias_uses_verified_total_row() -> None:
    official = candidate.OfficialItemCode(
        item_code="5500",
        official_item_name="營建工程成本合計",
        xbrl_concept="tifrs-bsci-ci:CostOfConstructionAndEngineeringServiceSales",
        reported_value="12,186",
        indent_depth=1,
    )

    assert (
        candidate.resolve_official_item_code(
            "營建工程成本",
            {"營建工程成本合計": (official,)},
            statement_type="income_statement",
            candidate_value=12_186_000,
            candidate_scale=1000,
            candidate_indent_depth=1,
        )
        is official
    )
