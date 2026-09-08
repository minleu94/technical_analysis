from datetime import date
import json
from datetime import date
from pathlib import Path

import pytest

from scripts import build_mops_statement_pit_candidate as candidate
from scripts import enrich_mops_statement_item_codes as enrich


def test_parse_balance_sheet_extracts_requested_period_amount_in_integer_units() -> None:
    result = candidate.parse_statement_table(
        """
        <div>合併資產負債表 民國115年第2季 單位：新台幣仟元</div>
        <table>
          <tr><th>會計項目</th><th>115年06月30日</th><th>114年12月31日</th></tr>
          <tr><th></th><th>金額</th><th>金額</th></tr>
          <tr><td>流動資產</td><td></td><td></td></tr>
          <tr><td>現金及約當現金</td><td>3,134,218,213</td><td>2,767,856,402</td></tr>
        </table>
        """,
        statement_type="balance_sheet",
        roc_year=115,
        season=2,
    )

    assert result.endpoint == "ajax_t164sb03"
    assert result.rows[0]["item_name"] == "現金及約當現金"
    assert result.rows[0]["value"] == 3_134_218_213_000
    assert result.rows[0]["value_unit"] == "TWD"
    assert result.rows[0]["value_scale"] == 1000
    assert result.period_start is None
    assert result.period_end == date(2026, 6, 30)
    assert result.period_basis == "period_end_snapshot"
    assert result.named_row_count == 2
    assert result.excluded_rows[0]["reason"] == "empty_or_unavailable_value"


def test_parse_individual_statement_requires_individual_title_and_records_scope() -> None:
    result = candidate.parse_statement_table(
        """
        <div>個別資產負債表 民國115年第2季 單位：新台幣仟元</div>
        <table>
          <tr><th>會計項目</th><th>115年06月30日</th></tr>
          <tr><td>現金及約當現金</td><td>1,234</td></tr>
        </table>
        """,
        statement_type="balance_sheet",
        roc_year=115,
        season=2,
        report_basis="individual",
    )

    assert result.report_basis == "individual"
    assert result.rows[0]["value"] == 1_234_000
    with pytest.raises(ValueError, match="expected=合併資產負債表"):
        candidate.parse_statement_table(
            """
            <div>個別資產負債表 民國115年第2季</div>
            <table><tr><th>會計項目</th><th>115年06月30日</th></tr>
            <tr><td>現金及約當現金</td><td>1</td></tr></table>
            """,
            statement_type="balance_sheet",
            roc_year=115,
            season=2,
        )


@pytest.mark.parametrize(
    ("statement_type", "header", "endpoint", "title"),
    [
        ("income_statement", "115年第2季", "ajax_t164sb04", "合併綜合損益表"),
        (
            "cash_flows_statement",
            "115年01月01日至115年06月30日",
            "ajax_t164sb05",
            "合併現金流量表",
        ),
    ],
)
def test_parse_statement_table_keeps_statement_type_and_period_header(
    statement_type: str,
    header: str,
    endpoint: str,
    title: str,
) -> None:
    result = candidate.parse_statement_table(
        f"""
        <div>{title} 民國115年第2季 單位：新台幣仟元</div>
        <table>
          <tr><th>會計項目</th><th>{header}</th><th>比較期</th></tr>
          <tr><th></th><th>金額</th><th>金額</th></tr>
          <tr><td>本期淨利（淨損）</td><td>1,279,041,690</td><td>923,930,616</td></tr>
        </table>
        """,
        statement_type=statement_type,
        roc_year=115,
        season=2,
    )

    assert result.endpoint == endpoint
    assert result.statement_type == statement_type
    assert result.rows[0]["value"] == 1_279_041_690_000
    if statement_type == "income_statement":
        assert result.period_start == date(2026, 4, 1)
        assert result.period_basis == "quarter_single"
    else:
        assert result.period_start == date(2026, 1, 1)
        assert result.period_basis == "year_to_date"


def test_parse_income_statement_keeps_eps_in_cents_per_share() -> None:
    result = candidate.parse_statement_table(
        """
        <div>合併綜合損益表 民國115年第2季 單位：新台幣仟元</div>
        <table>
          <tr><th>會計項目</th><th>115年第2季</th><th>比較期</th></tr>
          <tr><th></th><th>金額</th><th>金額</th></tr>
          <tr><td>基本每股盈餘</td><td>-0.14</td><td>0.20</td></tr>
        </table>
        """,
        statement_type="income_statement",
        roc_year=115,
        season=2,
    )

    assert result.rows[0]["value"] == -14
    assert result.rows[0]["value_unit"] == "TWD_per_share"
    assert result.rows[0]["value_scale"] == 100


def test_parse_income_statement_treats_continuing_eps_label_as_per_share() -> None:
    result = candidate.parse_statement_table(
        """
        <div>合併綜合損益表 民國115年第2季 單位：新台幣仟元</div>
        <table>
          <tr><th>會計項目</th><th>115年第2季</th><th>比較期</th></tr>
          <tr><th></th><th>金額</th><th>金額</th></tr>
          <tr><td>繼續營業單位淨利（淨損）</td><td>1.67</td><td>1.04</td></tr>
        </table>
        """,
        statement_type="income_statement",
        roc_year=115,
        season=2,
    )
    assert result.rows[0]["value"] == 167
    assert result.rows[0]["value_unit"] == "TWD_per_share"
    assert result.rows[0]["value_scale"] == 100


def test_statement_fetcher_follows_unique_company_selector_response(monkeypatch) -> None:
    selector = '''
      <form><table>
        <tr><th>公司代號</th><th>公司名稱</th></tr>
        <tr><td>2881</td><td>富邦金</td><td><input onclick='document.fm1.co_id.value="2881";ajax1(this.form,"table01");'></td></tr>
        <tr><td>28810001</td><td>富邦保</td><td><input onclick='document.fm1.co_id.value="5828";ajax1(this.form,"table01");'></td></tr>
      </table></form>
    '''.encode("utf-8")
    detail = "<h2>合併資產負債表</h2> 民國115年第2季".encode("utf-8")
    calls: list[dict[str, str]] = []

    class FakeResponse:
        encoding = "utf-8"

        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            return None

    def fake_post(url, *, data, headers, timeout):
        calls.append(dict(data))
        return FakeResponse(selector if len(calls) == 1 else detail)

    monkeypatch.setattr(candidate.requests, "post", fake_post)
    result = candidate._fetch_statement_response(
        stock_code="2881",
        market="sii",
        roc_year=115,
        season=2,
        statement_type="balance_sheet",
        timeout_seconds=3,
    )
    assert result == detail
    assert calls[0]["step"] == "1"
    assert calls[0]["co_id"] == "2881"
    assert calls[1]["step"] == "2"
    assert calls[1]["co_id"] == "2881"


def test_statement_fetcher_rejects_selector_without_exact_requested_company(monkeypatch) -> None:
    selector = "<table><tr><td>28810001</td><td>富邦保</td><td><input onclick='co_id.value=\"5828\"'></td></tr></table>".encode("utf-8")

    class FakeResponse:
        encoding = "utf-8"
        content = selector

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(candidate.requests, "post", lambda *args, **kwargs: FakeResponse())
    with pytest.raises(ValueError, match="expected official title"):
        candidate._fetch_statement_response(
            stock_code="2881",
            market="sii",
            roc_year=115,
            season=2,
            statement_type="balance_sheet",
            timeout_seconds=3,
        )


def test_resolve_official_item_code_uses_explicit_virtual_currency_alias() -> None:
    detail = candidate.OfficialItemCode(
        item_code="3199",
        official_item_name="權益─具證券性質之虛擬通貨合計",
        xbrl_concept="tifrs-bsci-ci:EquitySecurityTokenOffer",
        reported_value="0",
        indent_depth=4,
    )
    resolved = candidate.resolve_official_item_code(
        "權益─具證券性質之虛擬通貨",
        {"權益─具證券性質之虛擬通貨合計": (detail,)},
        statement_type="balance_sheet",
        candidate_value=0,
        candidate_scale=1000,
        candidate_indent_depth=4,
    )
    assert resolved is detail


def test_virtual_currency_alias_requires_unique_amount_match() -> None:
    first = candidate.OfficialItemCode(
        item_code="3199",
        official_item_name="權益─具證券性質之虛擬通貨合計",
        xbrl_concept="tifrs-bsci-ci:EquitySecurityTokenOffer",
        reported_value="0",
        indent_depth=4,
    )
    second = candidate.OfficialItemCode(
        item_code="3198",
        official_item_name="權益─具證券性質之虛擬通貨合計",
        xbrl_concept="tifrs-bsci-ci:EquitySecurityTokenOfferOther",
        reported_value="0",
        indent_depth=4,
    )
    codes = {"權益─具證券性質之虛擬通貨合計": (first, second)}
    assert candidate.resolve_official_item_code(
        "權益─具證券性質之虛擬通貨",
        codes,
        statement_type="balance_sheet",
        candidate_value=0,
        candidate_scale=1000,
        candidate_indent_depth=4,
    ) is None
    assert candidate.resolve_official_item_code(
        "權益─具證券性質之虛擬通貨",
        {"權益─具證券性質之虛擬通貨合計": (first,)},
        statement_type="balance_sheet",
        candidate_value=1_000,
        candidate_scale=1000,
        candidate_indent_depth=4,
    ) is None


def test_resolve_official_item_code_uses_verified_financial_asset_net_alias() -> None:
    detail = candidate.OfficialItemCode(
        item_code="12300",
        official_item_name="避險之金融資產－淨額",
        xbrl_concept="ifrs-full:HedgingAssets",
        reported_value="10141404",
        indent_depth=2,
    )
    resolved = candidate.resolve_official_item_code(
        "避險之金融資產",
        {"避險之金融資產-淨額": (detail,)},
        statement_type="balance_sheet",
        candidate_value=10_141_404_000,
        candidate_scale=1000,
        candidate_indent_depth=2,
    )
    assert resolved is detail


def test_resolve_official_item_code_accepts_verified_financial_balance_total_code() -> None:
    detail = candidate.OfficialItemCode(
        item_code="3X2XX",
        official_item_name="負債及權益總計",
        xbrl_concept="tifrs-bsci:LiabilitiesAndEquity",
        reported_value="1376540289",
        indent_depth=0,
    )
    resolved = candidate.resolve_official_item_code(
        "負債及權益總計",
        {"負債及權益總計": (detail,)},
        statement_type="balance_sheet",
        candidate_value=1_376_540_289_000,
        candidate_scale=1000,
        candidate_indent_depth=0,
    )
    assert resolved is detail


def test_resolve_official_item_code_uses_verified_operating_expense_alias() -> None:
    detail = candidate.OfficialItemCode(
        item_code="58500",
        official_item_name="營業費用合計",
        xbrl_concept="tifrs-bsci:OperatingExpenses",
        reported_value="20717396",
        indent_depth=0,
    )
    assert candidate.resolve_official_item_code(
        "營業費用",
        {"營業費用合計": (detail,)},
        statement_type="income_statement",
        candidate_value=20_717_396_000,
        candidate_scale=1000,
    ) is detail


def test_resolve_official_item_code_uses_verified_service_revenue_total_alias() -> None:
    detail = candidate.OfficialItemCode(
        item_code="4600",
        official_item_name="勞務收入合計",
        xbrl_concept="tifrs-bsci-ci:ServiceRevenue",
        reported_value="6089",
        indent_depth=2,
    )
    assert candidate.resolve_official_item_code(
        "勞務收入",
        {"勞務收入合計": (detail,)},
        statement_type="income_statement",
        candidate_value=6_089_000,
        candidate_scale=1000,
        candidate_indent_depth=2,
    ) is detail


def test_resolve_official_item_code_uses_verified_service_cost_total_alias() -> None:
    detail = candidate.OfficialItemCode(
        item_code="5600",
        official_item_name="勞務成本合計",
        xbrl_concept="tifrs-bsci-ci:CostOfServices",
        reported_value="818",
        indent_depth=1,
    )
    assert candidate.resolve_official_item_code(
        "勞務成本",
        {"勞務成本合計": (detail,)},
        statement_type="income_statement",
        candidate_value=818_000,
        candidate_scale=1000,
        candidate_indent_depth=1,
    ) is detail


def test_resolve_official_item_code_uses_verified_pretax_profit_alias() -> None:
    detail = candidate.OfficialItemCode(
        item_code="61000",
        official_item_name="繼續營業單位稅前淨利（淨損）",
        xbrl_concept="tifrs-bsci:ProfitLossFromContinuingOperationsBeforeTax",
        reported_value="75623995",
        indent_depth=0,
    )
    assert candidate.resolve_official_item_code(
        "繼續營業單位稅前損益",
        {"繼續營業單位稅前淨利(淨損)": (detail,)},
        statement_type="income_statement",
        candidate_value=75_623_995_000,
        candidate_scale=1000,
    ) is detail


def test_resolve_official_item_code_uses_verified_after_tax_profit_alias() -> None:
    detail = candidate.OfficialItemCode(
        item_code="69000",
        official_item_name="本期淨利（淨損）",
        xbrl_concept="tifrs-bsci:ProfitLoss",
        reported_value="64218493",
        indent_depth=0,
    )
    assert candidate.resolve_official_item_code(
        "本期稅後淨利(淨損)",
        {"本期淨利(淨損)": (detail,)},
        statement_type="income_statement",
        candidate_value=64_218_493_000,
        candidate_scale=1000,
    ) is detail


def test_resolve_official_item_code_uses_verified_oci_section_aliases() -> None:
    items = {
        "不重分類至損益之項目總額(稅後)": (
            candidate.OfficialItemCode(
                item_code="69560",
                official_item_name="不重分類至損益之項目總額（稅後）",
                xbrl_concept="tifrs-bsci:OtherComprehensiveIncomeLossNetOfTaxThatWillNotBeReclassifiedToProfitOrLoss",
                reported_value="210936236",
                indent_depth=1,
            ),
        ),
        "後續可能重分類至損益之項目總額(稅後)": (
            candidate.OfficialItemCode(
                item_code="69570",
                official_item_name="後續可能重分類至損益之項目總額（稅後）",
                xbrl_concept="tifrs-bsci:OtherComprehensiveIncomeLossNetOfTaxThatMayBeReclassifiedToProfitOrLoss",
                reported_value="37744528",
                indent_depth=1,
            ),
        ),
    }
    assert candidate.resolve_official_item_code(
        "不重分類至損益之項目（稅後）",
        items,
        statement_type="income_statement",
        candidate_value=210_936_236_000,
        candidate_scale=1000,
        candidate_indent_depth=1,
    ) is items["不重分類至損益之項目總額(稅後)"][0]
    assert candidate.resolve_official_item_code(
        "後續可能重分類至損益之項目（稅後）",
        items,
        statement_type="income_statement",
        candidate_value=37_744_528_000,
        candidate_scale=1000,
        candidate_indent_depth=1,
    ) is items["後續可能重分類至損益之項目總額(稅後)"][0]


def test_resolve_official_item_code_uses_verified_oci_total_alias() -> None:
    detail = candidate.OfficialItemCode(
        item_code="69500",
        official_item_name="本期其他綜合損益",
        xbrl_concept="tifrs-bsci:OtherComprehensiveIncomeLossNetOfTax",
        reported_value="248680764",
        indent_depth=0,
    )
    assert candidate.resolve_official_item_code(
        "本期其他綜合損益（稅後淨額）",
        {"本期其他綜合損益": (detail,)},
        statement_type="income_statement",
        candidate_value=248_680_764_000,
        candidate_scale=1000,
    ) is detail


def test_resolve_official_item_code_uses_verified_attributable_profit_alias() -> None:
    detail = candidate.OfficialItemCode(
        item_code="69901",
        official_item_name="母公司業主",
        xbrl_concept="tifrs-bsci:ProfitLossAttributableToOwnersOfParent",
        reported_value="63839675",
        indent_depth=1,
    )
    assert candidate.resolve_official_item_code(
        "母公司業主（淨利／淨損）",
        {"母公司業主": (detail,)},
        statement_type="income_statement",
        candidate_value=63_839_675_000,
        candidate_scale=1000,
        candidate_indent_depth=1,
    ) is detail


def test_resolve_official_item_code_uses_verified_attribution_aliases() -> None:
    details = {
        "非控制權益": candidate.OfficialItemCode(
            item_code="69903",
            official_item_name="非控制權益",
            xbrl_concept="tifrs-bsci:ProfitLossAttributableToNoncontrollingInterests",
            reported_value="378818",
            indent_depth=1,
        ),
        "母公司業主": candidate.OfficialItemCode(
            item_code="69951",
            official_item_name="母公司業主",
            xbrl_concept="tifrs-bsci:ComprehensiveIncomeLossAttributableToOwnersOfParent",
            reported_value="312028869",
            indent_depth=1,
        ),
        "非控制股權": candidate.OfficialItemCode(
            item_code="69953",
            official_item_name="非控制股權",
            xbrl_concept="tifrs-bsci:ComprehensiveIncomeLossAttributableToNoncontrollingInterests",
            reported_value="870388",
            indent_depth=1,
        ),
    }
    assert candidate.resolve_official_item_code(
        "非控制權益（淨利／淨損）",
        {"非控制權益": (details["非控制權益"],)},
        statement_type="income_statement",
        candidate_value=378_818_000,
        candidate_scale=1000,
        candidate_indent_depth=1,
    ) is details["非控制權益"]
    assert candidate.resolve_official_item_code(
        "母公司業主（綜合損益）",
        {"母公司業主": (details["母公司業主"],)},
        statement_type="income_statement",
        candidate_value=312_028_869_000,
        candidate_scale=1000,
        candidate_indent_depth=1,
    ) is details["母公司業主"]
    assert candidate.resolve_official_item_code(
        "非控制股權（綜合損益）",
        {"非控制股權": (details["非控制股權"],)},
        statement_type="income_statement",
        candidate_value=870_388_000,
        candidate_scale=1000,
        candidate_indent_depth=1,
    ) is details["非控制股權"]
    assert candidate.resolve_official_item_code(
        "非控制權益（綜合損益）",
        {"非控制股權": (details["非控制股權"],)},
        statement_type="income_statement",
        candidate_value=870_388_000,
        candidate_scale=1000,
        candidate_indent_depth=1,
    ) is details["非控制股權"]


def test_resolve_official_item_code_uses_verified_eps_occurrence_for_duplicate_label() -> None:
    basic = candidate.OfficialItemCode(
        item_code="9710",
        official_item_name="繼續營業單位淨利（淨損）",
        xbrl_concept="ifrs-full:BasicEarningsLossPerShareFromContinuingOperations",
        reported_value="1.67",
        indent_depth=1,
    )
    diluted = candidate.OfficialItemCode(
        item_code="9810",
        official_item_name="繼續營業單位淨利（淨損）",
        xbrl_concept="ifrs-full:DilutedEarningsLossPerShareFromContinuingOperations",
        reported_value="1.67",
        indent_depth=1,
    )
    item_codes = {"繼續營業單位淨利(淨損)": (basic, diluted)}
    assert candidate.resolve_official_item_code(
        "繼續營業單位淨利（淨損）",
        item_codes,
        statement_type="income_statement",
        candidate_value=167,
        candidate_scale=100,
        candidate_indent_depth=1,
        candidate_occurrence=0,
    ) is basic
    assert candidate.resolve_official_item_code(
        "繼續營業單位淨利（淨損）",
        item_codes,
        statement_type="income_statement",
        candidate_value=167,
        candidate_scale=100,
        candidate_indent_depth=1,
        candidate_occurrence=1,
    ) is diluted


def test_resolve_discontinued_eps_uses_official_basic_and_diluted_codes() -> None:
    basic = candidate.OfficialItemCode(
        item_code="9720",
        official_item_name="停業單位淨利（淨損）",
        xbrl_concept="ifrs-full:BasicEarningsLossPerShareFromDiscontinuedOperations",
        reported_value="0.00",
        indent_depth=1,
    )
    diluted = candidate.OfficialItemCode(
        item_code="9820",
        official_item_name="停業單位淨利（淨損）",
        xbrl_concept="ifrs-full:DilutedEarningsLossPerShareFromDiscontinuedOperations",
        reported_value="0.00",
        indent_depth=1,
    )
    item_codes = {"停業單位淨利(淨損)": (basic, diluted)}
    assert candidate.resolve_official_item_code(
        "停業單位淨利（淨損）",
        item_codes,
        statement_type="income_statement",
        candidate_value=0,
        candidate_scale=100,
        candidate_indent_depth=1,
        candidate_occurrence=0,
    ) is basic
    assert candidate.resolve_official_item_code(
        "停業單位淨利（淨損）",
        item_codes,
        statement_type="income_statement",
        candidate_value=0,
        candidate_scale=100,
        candidate_indent_depth=1,
        candidate_occurrence=1,
    ) is diluted


def test_discontinued_eps_is_parsed_as_cents_per_share() -> None:
    parsed = candidate.parse_statement_table(
        """
        <div>合併綜合損益表 民國115年第2季 單位：新台幣仟元</div>
        <table>
          <tr><th>會計項目</th><th>115年第2季</th><th>比較期</th></tr>
          <tr><th></th><th>金額</th><th>金額</th></tr>
          <tr><td>停業單位淨利（淨損）</td><td>0.00</td><td>0.00</td></tr>
        </table>
        """,
        statement_type="income_statement",
        roc_year=115,
        season=2,
    )
    assert parsed.rows[0]["value"] == 0
    assert parsed.rows[0]["value_unit"] == "TWD_per_share"
    assert parsed.rows[0]["value_scale"] == 100


def test_build_candidate_emits_the_complete_adapter_contract(tmp_path, monkeypatch) -> None:
    statements = {
        "balance_sheet": """
          <div>合併資產負債表 民國115年第2季 單位：新台幣仟元</div>
          <table>
            <tr><th>會計項目</th><th>115年06月30日</th><th>比較期</th></tr>
            <tr><th></th><th>金額</th><th>金額</th></tr>
            <tr><td>現金及約當現金</td><td>1</td><td>0</td></tr>
          </table>
        """,
        "income_statement": """
          <div>合併綜合損益表 民國115年第2季 單位：新台幣仟元</div>
          <table>
            <tr><th>會計項目</th><th>115年第2季</th><th>比較期</th></tr>
            <tr><th></th><th>金額</th><th>金額</th></tr>
            <tr><td>營業收入合計</td><td>2</td><td>0</td></tr>
          </table>
        """,
        "cash_flows_statement": """
          <div>合併現金流量表 民國115年第2季 單位：新台幣仟元</div>
          <table>
            <tr><th>會計項目</th><th>115年01月01日至115年06月30日</th><th>比較期</th></tr>
            <tr><th></th><th>金額</th><th>金額</th></tr>
            <tr><td>繼續營業單位稅前淨利（淨損）</td><td>3</td><td>0</td></tr>
          </table>
        """,
    }
    xbrl = """
      <ix:hidden>
        <ix:nonNumeric name="tifrs-notes:CompanyID">2330</ix:nonNumeric>
        <ix:nonNumeric name="tifrs-notes:Year">2026</ix:nonNumeric>
        <ix:nonNumeric name="tifrs-notes:Quarter">2</ix:nonNumeric>
        <ix:nonNumeric name="tifrs-notes:ReportCategory">Consolidated report</ix:nonNumeric>
        <ix:nonNumeric name="tifrs-notes:Market">Listed company</ix:nonNumeric>
      </ix:hidden>
      <table>
        <tr><td>1100</td><td><span class="zh">現金及約當現金</span></td>
            <td><ix:nonFraction name="ifrs-full:CashAndCashEquivalents">1</ix:nonFraction></td></tr>
        <tr><td>4000</td><td><span class="zh">營業收入合計</span></td>
            <td><ix:nonFraction name="ifrs-full:Revenue">2</ix:nonFraction></td></tr>
        <tr><td>A00010</td><td><span class="zh">繼續營業單位稅前淨利（淨損）</span></td>
            <td><ix:nonFraction name="ifrs-full:ProfitLossBeforeTax">3</ix:nonFraction></td></tr>
      </table>
    """.encode("big5hkscs")
    listing = """
      <table><tr>
        <td>2330</td><td>115 年 第 二季</td><td>x</td><td>x</td><td>x</td>
        <td>IFRSs合併財報</td><td>x</td><td>202602_2330_AI1.pdf</td><td>123</td>
        <td>115/08/14 13:59:44</td><td>無</td>
      </tr></table>
    """.encode("big5")
    canonical_manifest = tmp_path / "canonical-manifest.csv"
    canonical_dataset = tmp_path / "canonical-dataset.csv"
    canonical_manifest.write_text("manifest", encoding="utf-8")
    canonical_dataset.write_text("dataset", encoding="utf-8")
    listing_path = tmp_path / "t57-2330.html"
    listing_path.write_bytes(listing)
    listing_event = candidate.parse_listing_event(
        listing,
        stock_code="2330",
        roc_year=115,
        season=2,
    )
    listing_evidence_path = tmp_path / "t57-2330-evidence.json"
    listing_evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "v4-official-fallback-t57-evidence.v2",
                "request_url": "https://doc.twse.com.tw/server-java/t57sb01?step=1&colorchg=1&mtype=A&co_id=2330&year=115",
                "request": {"co_id": "2330", "roc_year": 115, "season": 2},
                "http": {
                    "status": 200,
                    "byte_count": len(listing),
                    "sha256": candidate._file_sha256_reference(listing_path),
                },
                "event": listing_event,
                "research_only": True,
                "formal_oos_allowed": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        candidate,
        "_fetch_statement_response",
        lambda **kwargs: statements[kwargs["statement_type"]].encode("utf-8"),
    )
    monkeypatch.setattr(candidate, "_fetch_xbrl_response", lambda **kwargs: xbrl)
    monkeypatch.setattr(candidate, "_fetch_listing_response", lambda **kwargs: listing)
    clock = iter(
        (
            "2026-09-07T15:59:59+00:00",
            "2026-09-07T16:00:00+00:00",
            "2026-09-07T16:00:00+00:00",
            "2026-09-07T16:00:00+00:00",
            "2026-09-07T16:00:00+00:00",
            "2026-09-07T16:00:00+00:00",
            "2026-09-07T16:00:00+00:00",
            "2026-09-07T16:00:01+00:00",
        )
    )
    real_datetime = candidate.datetime

    class FakeDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime.fromisoformat(next(clock))

    monkeypatch.setattr(candidate, "datetime", FakeDateTime)

    paths = candidate.build_candidate(
        stock_code="2330",
        roc_year=115,
        season=2,
        market="sii",
        output_root=tmp_path / "research-output",
        run_id="adapter-contract-test-2330",
        canonical_manifest=canonical_manifest,
        canonical_dataset=canonical_dataset,
        timeout_seconds=1,
        listing_response_path=listing_path,
        listing_evidence_path=listing_evidence_path,
    )

    payload = json.loads(paths["candidate"].read_text(encoding="utf-8"))
    assert all("item_code_lineage_sha256" in row for row in payload["rows"])
    assert payload["capture_started_at"] == "2026-09-07T15:59:59+00:00"
    assert payload["capture_completed_at"] == "2026-09-07T16:00:01+00:00"
    assert candidate._capture_session_available_date(payload["capture_started_at"]) == date(
        2026, 9, 8
    )
    assert candidate._capture_session_available_date(payload["capture_completed_at"]) == date(
        2026, 9, 9
    )
    assert all(
        row["numeric_available_at"] == "2026-09-07T16:00:01+00:00"
        for row in payload["rows"]
    )
    assert {row["numeric_available_date"] for row in payload["rows"]} == {"2026-09-09"}
    availability = json.loads(
        (paths["output_directory"] / "availability-source.json").read_text(encoding="utf-8")
    )
    assert availability["evidence_status"] == "verified_saved_response"
    assert availability["evidence"]["status"] == "verified_saved_response"
    run_manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert "raw_mops_t57sb01_2330_115.evidence.json" in run_manifest["files"]
    from data_module.mops_statement_candidate_adapter import load_mops_statement_candidate

    rows = load_mops_statement_candidate(paths["candidate"], decision_date=date(2026, 9, 9))
    assert len(rows) == 3
    assert {row.item_code for row in rows} == {"1100", "4000", "A00010"}


def test_build_candidate_preserves_replayable_partial_after_listing_failure(
    tmp_path, monkeypatch
) -> None:
    """三張 t164 與 XBRL 已取得時，listing 失敗仍須留下 immutable partial。"""

    statements = {
        "balance_sheet": """
          <div>合併資產負債表 民國115年第2季 單位：新台幣仟元</div>
          <table>
            <tr><th>會計項目</th><th>115年06月30日</th></tr>
            <tr><td>現金及約當現金</td><td>1</td></tr>
          </table>
        """,
        "income_statement": """
          <div>合併綜合損益表 民國115年第2季 單位：新台幣仟元</div>
          <table>
            <tr><th>會計項目</th><th>115年第2季</th></tr>
            <tr><td>營業收入合計</td><td>2</td></tr>
          </table>
        """,
        "cash_flows_statement": """
          <div>合併現金流量表 民國115年第2季 單位：新台幣仟元</div>
          <table>
            <tr><th>會計項目</th><th>115年01月01日至115年06月30日</th></tr>
            <tr><td>繼續營業單位稅前淨利（淨損）</td><td>3</td></tr>
          </table>
        """,
    }
    xbrl = """
      <ix:hidden>
        <ix:nonNumeric name="tifrs-notes:CompanyID">2330</ix:nonNumeric>
        <ix:nonNumeric name="tifrs-notes:Year">2026</ix:nonNumeric>
        <ix:nonNumeric name="tifrs-notes:Quarter">2</ix:nonNumeric>
        <ix:nonNumeric name="tifrs-notes:ReportCategory">Consolidated report</ix:nonNumeric>
        <ix:nonNumeric name="tifrs-notes:Market">Listed company</ix:nonNumeric>
      </ix:hidden>
      <table>
        <tr><td>1100</td><td>現金及約當現金</td>
            <td><ix:nonFraction name="ifrs-full:CashAndCashEquivalents">1</ix:nonFraction></td></tr>
        <tr><td>4000</td><td>營業收入合計</td>
            <td><ix:nonFraction name="ifrs-full:Revenue">2</ix:nonFraction></td></tr>
        <tr><td>A00010</td><td>繼續營業單位稅前淨利（淨損）</td>
            <td><ix:nonFraction name="ifrs-full:ProfitLossBeforeTax">3</ix:nonFraction></td></tr>
      </table>
    """.encode("big5hkscs")
    canonical_manifest = tmp_path / "canonical-manifest.csv"
    canonical_dataset = tmp_path / "canonical-dataset.csv"
    canonical_manifest.write_text("manifest", encoding="utf-8")
    canonical_dataset.write_text("dataset", encoding="utf-8")

    monkeypatch.setattr(
        candidate,
        "_fetch_statement_response",
        lambda **kwargs: statements[kwargs["statement_type"]].encode("utf-8"),
    )
    monkeypatch.setattr(candidate, "_fetch_xbrl_response", lambda **kwargs: xbrl)

    def fail_listing(**kwargs):
        raise ValueError("listing validation failure")

    monkeypatch.setattr(candidate, "_fetch_listing_response", fail_listing)

    output_root = tmp_path / "research-output"
    run_id = "partial-preserve-2330"
    with pytest.raises(ValueError, match="listing validation failure"):
        candidate.build_candidate(
            stock_code="2330",
            roc_year=115,
            season=2,
            market="sii",
            output_root=output_root,
            run_id=run_id,
            canonical_manifest=canonical_manifest,
            canonical_dataset=canonical_dataset,
            timeout_seconds=1,
            partial_output_root=output_root / "_partial",
        )

    partial_root = output_root / "_partial" / run_id
    receipt_path = partial_root / "partial-failure.json"
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["phase"] == "listing_fetch"
    assert receipt["replay_ready"] is True
    assert {item["basename"] for item in receipt["raw_files"]} == {
        "ajax_t164sb03_2330_115Q2.html",
        "ajax_t164sb04_2330_115Q2.html",
        "ajax_t164sb05_2330_115Q2.html",
        "evidence.json",
        "mops_t164sb01_xbrl_2330_115Q2.html",
    }
    assert not (output_root / run_id).exists()


def test_saved_listing_evidence_rejects_a_raw_hash_mismatch(tmp_path) -> None:
    listing = """
      <table><tr>
        <td>2330</td><td>115 年 第 二季</td><td>x</td><td>x</td><td>x</td>
        <td>IFRSs合併財報</td><td>x</td><td>202602_2330_AI1.pdf</td><td>123</td>
        <td>115/08/14 13:59:44</td><td>無</td>
      </tr></table>
    """.encode("big5")
    listing_path = tmp_path / "listing.html"
    listing_path.write_bytes(listing)
    event = candidate.parse_listing_event(
        listing,
        stock_code="2330",
        roc_year=115,
        season=2,
    )
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "request_url": "https://doc.twse.com.tw/server-java/t57sb01?step=1&colorchg=1&mtype=A&co_id=2330&year=115",
                "request": {"co_id": "2330", "roc_year": 115, "season": 2},
                "http": {"status": 200, "byte_count": len(listing), "sha256": "0" * 64},
                "event": event,
                "research_only": True,
                "formal_oos_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="hash does not match"):
        candidate._validate_saved_listing_evidence(
            evidence_path,
            listing_path=listing_path,
            listing_hash=candidate._file_sha256_reference(listing_path),
            stock_code="2330",
            roc_year=115,
            season=2,
            listing_event=event,
        )


def _write_browser_listing_fixture(tmp_path):
    publication_dom = """
      <table><tr>
        <th>證券代號</th><th>資料年度</th><th>資料類型</th><th>結案類型</th><th>性質</th>
        <th>資料細節說明</th><th>備註</th><th>電子檔案</th><th>檔案大小</th>
        <th>上傳日期</th><th>財務報告更(補)正</th>
      </tr><tr>
        <td>2881</td><td>115 年 第二季</td><td>財務報告書</td><td></td><td></td>
        <td>IFRSs合併財報</td><td></td><td>202602_2881_AI1.pdf</td><td>4,099,984</td>
        <td>115/08/28 14:09:26</td><td>無</td>
      </tr></table>
    """
    selector_dom = "<html><body><table><tr><td>2881</td><td>富邦金</td></tr></table></body></html>"
    selector_path = tmp_path / "selector-dom.html"
    selector_path.write_bytes(selector_dom.encode("utf-8"))
    publication_path = tmp_path / "publication-dom.html"
    publication_path.write_bytes(publication_dom.encode("utf-8"))
    listing_path = tmp_path / "browser-listing.big5.html"
    listing_path.write_bytes(publication_dom.encode("utf-8").decode("utf-8").encode("big5"))
    listing_event = candidate.parse_listing_event(
        listing_path.read_bytes(),
        stock_code="2881",
        roc_year=115,
        season=2,
    )
    evidence_path = tmp_path / "browser-evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "v4-mops-t57-browser-listing-observation.v2",
                "capture_basis": "Chrome rendered DOM observation",
                "observed_at": "2026-09-07T11:56:25.120Z",
                "capture_completed_at": "2026-09-07T12:00:36.646Z",
                "request": {
                    "method": "GET",
                    "url": "https://doc.twse.com.tw/server-java/t57sb01?step=1&colorchg=1&mtype=A&co_id=2881&year=115",
                    "stock_code": "2881",
                    "market": "sii",
                    "roc_year": 115,
                    "season": 2,
                },
                "selector_response": {
                    "saved_dom_artifact": selector_path.name,
                    "saved_dom_artifact_bytes": selector_path.stat().st_size,
                    "saved_dom_artifact_sha256": candidate._file_sha256_reference(selector_path),
                    "raw_http_bytes_saved": False,
                },
                "selector_observation": {
                    "exact_requested_company": {"stock_code": "2881", "name": "富邦金"},
                },
                "publication_listing_response": {
                    "raw_http_bytes_saved": False,
                    "result_url": "https://doc.twse.com.tw/server-java/t57sb01",
                    "observed_at": "2026-09-07T12:00:36.646Z",
                    "saved_dom_artifact": publication_path.name,
                    "saved_dom_artifact_bytes": publication_path.stat().st_size,
                    "saved_dom_artifact_sha256": candidate._file_sha256_reference(publication_path),
                    "encoding_replay_basis": "strict_utf8_decode_then_big5_encode_of_saved_dom_artifact",
                    "encoding_replay_artifact": listing_path.name,
                    "encoding_replay_artifact_bytes": listing_path.stat().st_size,
                    "encoding_replay_artifact_sha256": candidate._file_sha256_reference(listing_path),
                    "row": {
                        "stock_code": "2881",
                        "period": "2026-Q2",
                        "period_end": "2026-06-30",
                        "upload_timestamp": "2026-08-28T14:09:26+08:00",
                        "file_name": "202602_2881_AI1.pdf",
                        "file_size_bytes": 4099984,
                        "listing_row_sha256": listing_event["listing_row_sha256"],
                    },
                },
                "research_only": True,
                "formal_oos_allowed": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return listing_path, selector_path, publication_path, evidence_path, listing_event


def _validate_browser_fixture(tmp_path):
    listing_path, selector_path, publication_path, evidence_path, listing_event = (
        _write_browser_listing_fixture(tmp_path)
    )
    validated = candidate._validate_browser_listing_observation(
        evidence_path,
        listing_path=listing_path,
        listing_hash=candidate._file_sha256_reference(listing_path),
        stock_code="2881",
        market="sii",
        roc_year=115,
        season=2,
        listing_event=listing_event,
    )
    return listing_path, selector_path, publication_path, evidence_path, listing_event, validated


def test_browser_listing_observation_binds_publication_row_without_raw_credit(tmp_path) -> None:
    listing_path, selector_path, publication_path, evidence_path, listing_event, validated = (
        _validate_browser_fixture(tmp_path)
    )

    assert validated["status"] == "browser_observed_response"
    assert validated["raw_custody"] is False
    assert validated["http_status"] is None
    assert validated["event"] == listing_event
    assert validated["browser_dom_artifacts"] == {
        "selector": selector_path.name,
        "publication": publication_path.name,
    }


def test_browser_listing_observation_rejects_dom_hash_mismatch(tmp_path) -> None:
    _, _, publication_path, evidence_path, listing_event, _ = _validate_browser_fixture(tmp_path)
    publication_path.write_bytes(
        publication_path.read_bytes().replace(b"4,099,984", b"4,099,985")
    )
    listing_path = tmp_path / "browser-listing.big5.html"
    with pytest.raises(ValueError, match="publication DOM hash"):
        candidate._validate_browser_listing_observation(
            evidence_path,
            listing_path=listing_path,
            listing_hash=candidate._file_sha256_reference(listing_path),
            stock_code="2881",
            market="sii",
            roc_year=115,
            season=2,
            listing_event=listing_event,
        )


def test_browser_listing_observation_rejects_nonmatching_encoding_replay(tmp_path) -> None:
    listing_path, _, _, evidence_path, listing_event, _ = _validate_browser_fixture(tmp_path)
    listing_path.write_bytes(listing_path.read_bytes().replace(b"4,099,984", b"4,099,985"))
    with pytest.raises(ValueError, match="strict encoding"):
        candidate._validate_browser_listing_observation(
            evidence_path,
            listing_path=listing_path,
            listing_hash=candidate._file_sha256_reference(listing_path),
            stock_code="2881",
            market="sii",
            roc_year=115,
            season=2,
            listing_event=listing_event,
        )


def test_browser_listing_observation_rejects_observation_after_capture_completion(tmp_path) -> None:
    listing_path, _, _, evidence_path, listing_event, _ = _validate_browser_fixture(tmp_path)
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["capture_completed_at"] = "2026-09-07T11:59:00+00:00"
    evidence_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="after capture completion"):
        candidate._validate_browser_listing_observation(
            evidence_path,
            listing_path=listing_path,
            listing_hash=candidate._file_sha256_reference(listing_path),
            stock_code="2881",
            market="sii",
            roc_year=115,
            season=2,
            listing_event=listing_event,
        )


def test_parse_statement_table_rejects_response_for_another_period() -> None:
    with pytest.raises(ValueError, match="period marker"):
        candidate.parse_statement_table(
            "<div>合併資產負債表 民國115年第1季</div>",
            statement_type="balance_sheet",
            roc_year=115,
            season=2,
        )


def test_capture_session_date_is_next_taipei_day_and_requires_timezone() -> None:
    assert candidate._capture_session_available_date("2026-09-07T07:59:59+00:00") == date(2026, 9, 8)
    assert candidate._capture_session_available_date("2026-09-07T08:00:00+00:00") == date(2026, 9, 8)
    assert candidate._capture_session_available_date("2026-09-07T15:59:59+00:00") == date(2026, 9, 8)
    with pytest.raises(ValueError, match="timezone"):
        candidate._capture_session_available_date("2026-09-07T08:00:00")


def test_parse_xbrl_item_codes_preserves_ix_nonfraction_negative_sign() -> None:
    codes = candidate.parse_xbrl_item_codes(
        """
        <table><tr>
          <td>49850</td><td><span class="zh">　除列按攤銷後成本衡量之金融資產損益</span></td>
          <td><ix:nonfraction name="ifrs-full:GainLossArisingFromDerecognitionOfFinancialAssetsMeasuredAtAmortisedCost" sign="-">321,360</ix:nonfraction></td>
        </tr></table>
        """
    )
    detail = codes["除列按攤銷後成本衡量之金融資產損益"][0]
    assert detail.item_code == "49850"
    assert detail.reported_value == "-321,360"
    assert candidate.resolve_official_item_code(
        "除列按攤銷後成本衡量之金融資產損益",
        codes,
        statement_type="income_statement",
        candidate_value=-321_360_000,
        candidate_scale=1000,
    ) is detail


def test_parse_xbrl_item_codes_preserves_parenthesized_negative_sign() -> None:
    codes = candidate.parse_xbrl_item_codes(
        """
        <table><tr>
          <td>3500</td><td><span class="zh">　　　庫藏股票</span></td>
          <td><pre>(<ix:nonFraction name="ifrs-full:TreasuryShares">28,362</ix:nonFraction>)</pre></td>
        </tr></table>
        """
    )
    detail = codes["庫藏股票"][0]
    assert detail.reported_value == "-28,362"
    assert candidate.resolve_official_item_code(
        "庫藏股票",
        codes,
        statement_type="balance_sheet",
        candidate_value=-28_362_000,
        candidate_scale=1000,
        candidate_indent_depth=3,
    ) is detail


def test_parse_xbrl_item_codes_keeps_official_code_concept_value_and_indent() -> None:
    codes = candidate.parse_xbrl_item_codes(
        """
        <h1>2330 2026年第2季 Statements of Financial Position</h1>
        <table>
          <tr><td>1100</td><td><span class="zh">　　現金及約當現金</span><span class="en">Cash</span></td>
              <td><ix:nonFraction name="ifrs-full:CashAndCashEquivalents">1,234</ix:nonFraction></td></tr>
          <tr><td>4000</td><td><span class="zh">　營業收入合計</span><span class="en">Revenue</span></td>
              <td><ix:nonFraction name="ifrs-full:Revenue">9,876</ix:nonFraction></td></tr>
          <tr><td>9750</td><td><span class="zh">　基本每股盈餘合計</span><span class="en">Basic EPS</span></td>
              <td><ix:nonFraction name="ifrs-full:BasicEarningsLossPerShare">27.25</ix:nonFraction></td></tr>
          <tr><td>A00010</td><td><span class="zh">　繼續營業單位稅前淨利（淨損）</span></td>
              <td><ix:nonFraction name="ifrs-full:ProfitLossBeforeTax">1,000</ix:nonFraction></td></tr>
        </table>
        """
    )

    cash = candidate.resolve_official_item_code(
        "現金及約當現金",
        codes,
        statement_type="balance_sheet",
        candidate_value=1_234_000,
        candidate_scale=1000,
        candidate_indent_depth=2,
    )
    eps = candidate.resolve_official_item_code(
        "基本每股盈餘",
        codes,
        statement_type="income_statement",
        candidate_value=2725,
        candidate_scale=100,
        candidate_indent_depth=1,
    )
    assert cash is not None and cash.item_code == "1100"
    assert cash.xbrl_concept == "ifrs-full:CashAndCashEquivalents"
    assert cash.reported_value == "1,234"
    assert cash.indent_depth == 2
    assert eps is not None and eps.item_code == "9750"


def test_decode_mops_xbrl_accepts_official_big5_hkscs_extension() -> None:
    body = "<html>𨭎</html>".encode("big5hkscs")
    assert candidate._decode_mops_xbrl(body) == "<html>𨭎</html>"


def test_decode_mops_xbrl_requires_explicit_declared_big5_control_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"<META HTTP-EQUIV='Content-Type' CONTENT='text/html; charset=big5'>"
    body += b"\n".join(
        [
            b"\n\x84P row-1",
            b"\x84P row-2",
            b"\x84P row-3",
            b"\x84P row-4",
            b"\x84P row-5",
            b"\x84P row-6",
        ]
    )
    body += _xbrl_identity_markup(company="2063", market="Over-the-counter").encode("big5")
    offsets = tuple(index for index, value in enumerate(body) if value == 0x84)
    assert len(offsets) == 6
    monkeypatch.setitem(
        candidate._XBRL_C1_REPAIR_SOURCE_RULES,
        candidate.sha256(body).hexdigest(),
        offsets,
    )
    with pytest.raises(ValueError, match="strict Big5/HKSCS"):
        candidate._decode_mops_xbrl(body)
    decoded = candidate._decode_mops_xbrl(
        body,
        encoding_repair=candidate._XBRL_ENCODING_REPAIR_C1,
    )
    assert "\x84" not in decoded
    assert candidate.parse_xbrl_metadata(decoded)["companyid"] == "2063"
    assert candidate._xbrl_encoding_lineage(
        body,
        encoding_repair=candidate._XBRL_ENCODING_REPAIR_C1,
    )["removed_byte_count"] == 6


def test_decode_mops_xbrl_rejects_c1_inside_numeric_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = (
        b"<META HTTP-EQUIV='Content-Type' CONTENT='text/html; charset=big5'>"
        + b"<td>12\x8434</td>"
    )
    offset = body.index(b"\x84")
    monkeypatch.setitem(
        candidate._XBRL_C1_REPAIR_SOURCE_RULES,
        candidate.sha256(body).hexdigest(),
        (offset,),
    )
    with pytest.raises(ValueError, match="unverified 0x84 position"):
        candidate._decode_mops_xbrl(
            body,
            encoding_repair=candidate._XBRL_ENCODING_REPAIR_C1,
        )


def test_decode_mops_xbrl_strict_input_has_no_fake_repair_lineage() -> None:
    body = (
        b"<META HTTP-EQUIV='Content-Type' CONTENT='text/html; charset=big5'>"
        + b"<html>strict</html>"
    )
    assert candidate._decode_mops_xbrl(
        body,
        encoding_repair=candidate._XBRL_ENCODING_REPAIR_C1,
    ).endswith("<html>strict</html>")
    lineage = candidate._xbrl_encoding_lineage(
        body,
        encoding_repair=candidate._XBRL_ENCODING_REPAIR_C1,
    )
    assert lineage["repair"] is None
    assert lineage["removed_byte_count"] == 0
    assert lineage["decoder"] in {"big5hkscs", "big5"}


def test_decode_mops_xbrl_real_2063_six_offsets_and_source_contract() -> None:
    path = Path(
        "output/v4_data_recovery_2026-09-07/quarterly/"
        "repair-r23-official-r2/mops_t164sb01_xbrl_2063_2026Q2.html"
    )
    if not path.is_file():
        pytest.skip("尚未提供本輪保存的 2063 官方 raw；離線來源測試不自行下載")
    body = path.read_bytes()
    decoded = candidate._decode_mops_xbrl(
        body,
        encoding_repair=candidate._XBRL_ENCODING_REPAIR_C1,
    )
    assert "\x84" not in decoded
    lineage = candidate._xbrl_encoding_lineage(
        body,
        encoding_repair=candidate._XBRL_ENCODING_REPAIR_C1,
    )
    assert lineage["removed_byte_offsets"] == [422759, 422935, 422998, 423354, 423751, 423827]
    assert lineage["removed_byte_count"] == 6


def test_decode_mops_xbrl_real_2063_mutated_source_is_rejected() -> None:
    path = Path(
        "output/v4_data_recovery_2026-09-07/quarterly/"
        "repair-r23-official-r2/mops_t164sb01_xbrl_2063_2026Q2.html"
    )
    if not path.is_file():
        pytest.skip("尚未提供本輪保存的 2063 官方 raw；離線來源測試不自行下載")
    body = bytearray(path.read_bytes())
    body[100] ^= 1
    with pytest.raises(ValueError, match="source-specific contract"):
        candidate._decode_mops_xbrl(
            bytes(body),
            encoding_repair=candidate._XBRL_ENCODING_REPAIR_C1,
        )


def test_decode_mops_xbrl_does_not_swallow_another_control_byte() -> None:
    body = (
        b"<META HTTP-EQUIV='Content-Type' CONTENT='text/html; charset=big5'>"
        + b"\x85"
        + _xbrl_identity_markup(company="2063", market="Over-the-counter").encode("big5")
    )
    with pytest.raises(ValueError, match="unsupported C1"):
        candidate._decode_mops_xbrl(
            body,
            encoding_repair=candidate._XBRL_ENCODING_REPAIR_C1,
        )


def test_xbrl_identity_accepts_only_verified_ezsearch_market_conflict() -> None:
    evidence = {
        "status": "verified_saved_ezsearch_response",
        "source_id": "mops.ezsearch.statement_publication",
        "source_version": "mops-ezsearch-statement-publication.v1",
        "source_url": candidate.MOPS_EZSEARCH_URL,
        "source_sha256": "sha256:" + "a" * 64,
        "event": {
            "stock_code": "1799",
            "period": "2026-Q2",
            "period_end": "2026-06-30",
            "announcement_items": ["F26", "F27", "F28"],
            "availability_event_sha256": "sha256:" + "b" * 64,
        },
    }
    conflict = candidate._validate_xbrl_identity(
        _xbrl_identity_markup(company="1799", market="Listed company"),
        stock_code="1799",
        period_year=2026,
        season=2,
        market="otc",
        market_identity_evidence=evidence,
    )
    assert conflict is not None
    assert conflict["xbrl_metadata_market"] == "Listed company"
    assert conflict["requested_market"] == "otc"
    with pytest.raises(ValueError, match="market"):
        candidate._validate_xbrl_identity(
            _xbrl_identity_markup(company="1799", market="Listed company"),
            stock_code="1799",
            period_year=2026,
            season=2,
            market="otc",
        )


def test_xbrl_duplicate_code_requires_value_and_indent_to_disambiguate() -> None:
    codes = candidate.parse_xbrl_item_codes(
        """
        <h1>6488 2026年第2季 Statements of Financial Position</h1>
        <table>
          <tr><td>2530</td><td><span class="zh">　　　應付公司債</span></td>
              <td><ix:nonFraction name="ifrs-full:Bonds">24,479,299</ix:nonFraction></td></tr>
          <tr><td>2531</td><td><span class="zh">　　　　應付公司債</span></td>
              <td><ix:nonFraction name="tifrs:Bonds">24,479,299</ix:nonFraction></td></tr>
        </table>
        """
    )
    assert candidate.resolve_official_item_code(
        "應付公司債",
        codes,
        statement_type="balance_sheet",
        candidate_value=24_479_299_000,
        candidate_scale=1000,
    ) is None
    resolved = candidate.resolve_official_item_code(
        "應付公司債",
        codes,
        statement_type="balance_sheet",
        candidate_value=24_479_299_000,
        candidate_scale=1000,
        candidate_indent_depth=3,
    )
    assert resolved is not None and resolved.item_code == "2530"


def test_resolve_official_item_code_uses_only_audited_receivables_alias() -> None:
    codes = candidate.parse_xbrl_item_codes(
        """
        <table>
          <tr><td>1200</td><td><span class="zh">其他應收款</span></td>
              <td><ix:nonFraction name="ifrs-full:OtherCurrentReceivables">41,556,408</ix:nonFraction></td></tr>
        </table>
        """
    )
    resolved = candidate.resolve_official_item_code(
        "其他應收款淨額",
        codes,
        statement_type="balance_sheet",
        candidate_value=41_556_408_000,
        candidate_scale=1000,
    )
    assert resolved is not None and resolved.item_code == "1200"


def test_resolve_official_item_code_uses_observed_1240_aliases() -> None:
    codes = candidate.parse_xbrl_item_codes(
        """
        <table>
          <tr><td>3998</td><td><span class="zh">預收股款（權益項下）之約當發行股數</span></td>
              <td><ix:nonFraction name="tifrs:EquivalentIssueShares">0</ix:nonFraction></td></tr>
          <tr><td>5110</td><td><span class="zh">銷貨成本合計</span></td>
              <td><ix:nonFraction name="ifrs-full:CostOfSales">660,725</ix:nonFraction></td></tr>
        </table>
        """
    )
    share_count = candidate.resolve_official_item_code(
        "預收股款（權益項下）之約當發行股數（單位：股）",
        codes,
        statement_type="balance_sheet",
        candidate_value=0,
        candidate_scale=1000,
        candidate_indent_depth=0,
    )
    cost = candidate.resolve_official_item_code(
        "銷貨成本",
        codes,
        statement_type="income_statement",
        candidate_value=660_725_000,
        candidate_scale=1000,
    )
    assert share_count is not None and share_count.item_code == "3998"
    assert cost is not None and cost.item_code == "5110"


def test_resolve_official_item_code_uses_verified_credit_impairment_net_alias() -> None:
    codes = candidate.parse_xbrl_item_codes(
        """
        <table>
          <tr><td>6450</td><td><span class="zh">預期信用減損損失（利益）</span></td>
              <td><ix:nonFraction name="ifrs-full:ImpairmentLosses">68</ix:nonFraction></td></tr>
          <tr><td>7055</td><td><span class="zh">預期信用減損損失（利益）淨額</span></td>
              <td><ix:nonFraction name="ifrs-full:ImpairmentLossesNet">-46</ix:nonFraction></td></tr>
        </table>
        """
    )
    resolved = candidate.resolve_official_item_code(
        "預期信用減損損失（利益）",
        codes,
        statement_type="income_statement",
        candidate_value=-46_000,
        candidate_scale=1000,
        candidate_indent_depth=2,
    )
    assert resolved is not None and resolved.item_code == "7055"


def _xbrl_identity_markup(
    *,
    company: str = "2330",
    year: int = 2026,
    quarter: int = 2,
    market: str = "Listed company",
    heading: str | None = None,
) -> str:
    heading = heading or f"{company} {year}年第{quarter}季 Statements of Financial Position"
    return f"""
    <h1>{heading}</h1>
    <ix:hidden>
      <ix:nonNumeric name="tifrs-notes:CompanyID">{company}</ix:nonNumeric>
      <ix:nonNumeric name="tifrs-notes:Year">{year}</ix:nonNumeric>
      <ix:nonNumeric name="tifrs-notes:Quarter">{quarter}</ix:nonNumeric>
      <ix:nonNumeric name="tifrs-notes:ReportCategory">Consolidated report</ix:nonNumeric>
      <ix:nonNumeric name="tifrs-notes:Market">{market}</ix:nonNumeric>
    </ix:hidden>
    """


def test_xbrl_fetch_checks_exact_company_and_period_metadata(monkeypatch) -> None:
    class _FakeResponse:
        content = _xbrl_identity_markup().encode("big5")

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(candidate.requests, "get", lambda *args, **kwargs: _FakeResponse())
    body = candidate._fetch_xbrl_response(
        stock_code="2330",
        roc_year=115,
        season=2,
        timeout_seconds=1,
        market="sii",
    )
    assert b"CompanyID" in body

    class _WrongResponse(_FakeResponse):
        # 回應正文另放入請求代號，證明不能用全文 substring 當公司身分。
        content = (
            _xbrl_identity_markup(company="6488")
            + "<table><td>2330</td></table>"
        ).encode("big5")

    monkeypatch.setattr(candidate.requests, "get", lambda *args, **kwargs: _WrongResponse())
    with pytest.raises(ValueError, match="company code"):
        candidate._fetch_xbrl_response(
            stock_code="2330",
            roc_year=115,
            season=2,
            timeout_seconds=1,
            market="sii",
        )


    class _WrongPeriodResponse(_FakeResponse):
        # 標題保留比較欄的 2026-Q2，隱藏 metadata 實際是 2025-Q2。
        content = _xbrl_identity_markup(
            year=2025,
            heading="2330 2026年第2季 Statements of Financial Position（比較期）",
        ).encode("big5")

    monkeypatch.setattr(
        candidate.requests,
        "get",
        lambda *args, **kwargs: _WrongPeriodResponse(),
    )
    with pytest.raises(ValueError, match="period"):
        candidate._fetch_xbrl_response(
            stock_code="2330",
            roc_year=115,
            season=2,
            timeout_seconds=1,
            market="sii",
        )


def test_xbrl_identity_requires_matching_report_basis() -> None:
    individual = _xbrl_identity_markup().replace(
        "Consolidated report", "Individual report"
    )
    candidate._validate_xbrl_identity(
        individual,
        stock_code="2330",
        period_year=2026,
        season=2,
        market="sii",
        report_basis="individual",
    )
    with pytest.raises(ValueError, match="report category"):
        candidate._validate_xbrl_identity(
            individual,
            stock_code="2330",
            period_year=2026,
            season=2,
            market="sii",
        )


def test_enrich_identity_rejects_numeric_collision_and_comparative_period() -> None:
    wrong_company = _xbrl_identity_markup(company="6488") + "<td>2330</td>"
    with pytest.raises(ValueError, match="company code"):
        enrich._validate_xbrl_identity(
            wrong_company,
            stock_code="2330",
            period_year=2026,
            season=2,
        )

    wrong_period = _xbrl_identity_markup(
        year=2025,
        heading="2330 2026年第2季 Statements of Financial Position（比較期）",
    )
    with pytest.raises(ValueError, match="period"):
        enrich._validate_xbrl_identity(
            wrong_period,
            stock_code="2330",
            period_year=2026,
            season=2,
        )


def _write_xbrl_browser_fixture(tmp_path):
    dom = (
        _xbrl_identity_markup(company="1240", market="Over-the-counter")
        + """
        <table><tr><td>1100</td><td><span class="zh">現金及約當現金</span></td>
        <td><ix:nonFraction name="ifrs-full:CashAndCashEquivalents">128,626</ix:nonFraction></td></tr></table>
        """
    ).encode("utf-8")
    dom_path = tmp_path / "xbrl-browser-dom.html"
    dom_path.write_bytes(dom)
    url = "https://mopsov.twse.com.tw/server-java/t164sb01?step=1&CO_ID=1240&SYEAR=2026&SSEASON=2&REPORT_ID=C"
    evidence = {
        "schema_version": "v4-mops-t164-browser-observation.v1",
        "capture_basis": "Chrome rendered DOM observation",
        "capture_time_basis": "local observation wrapper after CUA browser DOM read; browser network timestamp unavailable",
        "observed_at": "2026-09-07T13:00:00Z",
        "capture_completed_at": "2026-09-07T13:00:01Z",
        "request": {
            "method": "GET",
            "url": url,
            "stock_code": "1240",
            "market": "otc",
            "roc_year": 115,
            "season": 2,
        },
        "result_url": url,
        "saved_dom_artifact": dom_path.name,
        "saved_dom_artifact_bytes": len(dom),
        "saved_dom_artifact_sha256": candidate._file_sha256_reference(dom_path),
        "raw_http_bytes_saved": False,
        "identity": {
            "companyid": "1240",
            "year": "2026",
            "quarter": "2",
            "reportcategory": "Consolidated report",
            "market": "Over-the-counter",
        },
        "official_name_count": 1,
        "official_row_count": 1,
        "research_only": True,
        "formal_oos_allowed": False,
    }
    evidence_path = tmp_path / "xbrl-browser-evidence.json"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
    return dom_path, evidence_path


def test_browser_xbrl_observation_verifies_dom_identity_and_codes(tmp_path) -> None:
    dom_path, evidence_path = _write_xbrl_browser_fixture(tmp_path)
    result = candidate._validate_browser_xbrl_observation(
        evidence_path,
        dom_path=dom_path,
        stock_code="1240",
        market="otc",
        roc_year=115,
        season=2,
    )
    assert result["status"] == "browser_observed_response"
    assert result["raw_custody"] is False
    assert result["official_row_count"] == 1
    assert result["metadata"]["companyid"] == "1240"


def test_browser_xbrl_observation_rejects_dom_hash_mismatch(tmp_path) -> None:
    dom_path, evidence_path = _write_xbrl_browser_fixture(tmp_path)
    dom_path.write_bytes(dom_path.read_bytes().replace(b"128,626", b"128,627"))
    with pytest.raises(ValueError, match="DOM hash"):
        candidate._validate_browser_xbrl_observation(
            evidence_path,
            dom_path=dom_path,
            stock_code="1240",
            market="otc",
            roc_year=115,
            season=2,
        )


def test_browser_xbrl_observation_rejects_external_result_url(tmp_path) -> None:
    dom_path, evidence_path = _write_xbrl_browser_fixture(tmp_path)
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["result_url"] = "https://example.invalid/t164sb01?step=1"
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="official t164 endpoint"):
        candidate._validate_browser_xbrl_observation(
            evidence_path,
            dom_path=dom_path,
            stock_code="1240",
            market="otc",
            roc_year=115,
            season=2,
        )


def test_enriched_manifest_checks_all_files_and_raw_files_without_self_hash(tmp_path) -> None:
    candidate_file = tmp_path / "statement-pit-candidate.json"
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    raw_file = raw_dir / "t164.html"
    candidate_file.write_text("candidate", encoding="utf-8")
    raw_file.write_bytes(b"official raw")
    manifest = tmp_path / "run-manifest.json"
    valid_manifest = {
        "files": {
            candidate_file.name: candidate._file_sha256_reference(candidate_file),
        },
        "raw_files": {
            raw_file.name: candidate._file_sha256_reference(raw_file),
        },
    }
    manifest.write_text(json.dumps(valid_manifest), encoding="utf-8")
    enrich.validate_run_manifest(manifest)

    invalid_self_hash = {
        **valid_manifest,
        "files": {**valid_manifest["files"], "run-manifest.json": "sha256:unused"},
    }
    manifest.write_text(json.dumps(invalid_self_hash), encoding="utf-8")
    with pytest.raises(ValueError, match="hash itself"):
        enrich.validate_run_manifest(manifest)

    manifest.write_text(json.dumps(valid_manifest), encoding="utf-8")
    raw_file.write_bytes(b"tampered raw")
    with pytest.raises(ValueError, match="raw file hash mismatch"):
        enrich.validate_run_manifest(manifest)
