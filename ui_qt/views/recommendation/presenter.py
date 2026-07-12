"""RecommendationView 的純文字呈現規則。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional, Sequence
from typing import Any


def format_regime_names(regimes: Sequence[Optional[str]]) -> str:
    regime_names = {
        "Trend": "Trend / 趨勢追蹤",
        "Reversion": "Reversion / 均值回歸",
        "Breakout": "Breakout / 突破準備",
    }
    names = [regime_names.get(regime, regime or "未知") for regime in regimes if regime]
    return "、".join(names) if names else "未指定"


def _decimal_value(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def format_profile_weight(value: Any) -> str:
    if value is None:
        return "N/A"
    numeric = _decimal_value(value)
    if numeric is None:
        return str(value)
    if numeric <= Decimal("1"):
        return f"{numeric * Decimal('100'):.0f}%"
    if numeric <= Decimal("100"):
        return f"{numeric:.0f}"
    return f"{int(numeric)}bp"


def format_profile_filter_value(value: Any) -> str:
    numeric = _decimal_value(value)
    if numeric is None:
        return str(value)
    return f"{numeric.normalize():g}"


def profile_filter_summary(filters: dict[str, Any]) -> str:
    parts: list[str] = []
    if "price_change_min" in filters or "price_change_max" in filters:
        min_value = filters.get("price_change_min", "N/A")
        max_value = filters.get("price_change_max", "N/A")
        parts.append(
            f"漲幅 {format_profile_filter_value(min_value)}% ~ "
            f"{format_profile_filter_value(max_value)}%"
        )
    if "volume_ratio_min" in filters:
        parts.append(
            f"成交量 >= {format_profile_filter_value(filters.get('volume_ratio_min'))} 倍"
        )
    if filters.get("industry"):
        parts.append(f"產業 {filters.get('industry')}")
    return "、".join(parts) if parts else "未指定"


def profile_advanced_summary(config: dict[str, Any]) -> str:
    signals = config.get("signals", {})
    weights = signals.get("weights", {})
    indicators = signals.get("technical_indicators", [])
    patterns = config.get("patterns", {}).get("selected", [])
    weight_text = (
        f"型態 {format_profile_weight(weights.get('pattern'))} / "
        f"技術 {format_profile_weight(weights.get('technical'))} / "
        f"量能 {format_profile_weight(weights.get('volume'))}"
    )
    indicator_text = "、".join(indicators) if indicators else "未指定"
    pattern_preview = "、".join(str(pattern) for pattern in patterns[:5])
    if len(patterns) > 5:
        pattern_preview += f" 等 {len(patterns)} 種"
    elif pattern_preview:
        pattern_preview += f"（共 {len(patterns)} 種）"
    else:
        pattern_preview = "未指定"
    return (
        f"權重 {weight_text}；"
        f"技術分類 {indicator_text}；"
        f"型態 {pattern_preview}；"
        f"主要篩選 {profile_filter_summary(config.get('filters', {}))}"
    )


def format_recommendation_reason(
    reason_text: str,
    *,
    technical_descriptions: dict[str, Any],
    pattern_descriptions: dict[str, Any],
) -> str:
    """格式化推薦理由，使用 Tag/關鍵詞高亮顯示，並加入可反推線索

    Args:
        reason_text: 原始推薦理由文字

    Returns:
        str: 格式化後的推薦理由（使用 HTML 格式以便高亮）
    """
    if not reason_text:
        return "無推薦理由"

    # 從集中資料結構建立關鍵詞映射（技術指標）
    technical_keywords = {}
    for key, desc in technical_descriptions.items():
        # 建立名稱映射
        name_map = {
            'ma': ['移動平均', '均線', 'MA'],
            'adx': ['ADX'],
            'macd': ['MACD'],
            'rsi': ['RSI'],
            'kd': ['KD'],
            'bollinger': ['布林', '布林通道'],
            'atr': ['ATR']
        }
        for name in name_map.get(key, []):
            technical_keywords[name] = {
                'display': f'<b style="color: #2563eb;">{name}</b>',
                'category': desc.get('category', ''),
                'tags': desc.get('tags', [])
            }

    # 從集中資料結構建立關鍵詞映射（圖形模式）
    pattern_keywords = {}
    for key, desc in pattern_descriptions.items():
        # 建立名稱映射
        name_map = {
            'w_bottom': ['W底'],
            'head_shoulder_bottom': ['頭肩底'],
            'double_bottom': ['雙底'],
            'v_reversal': ['V形反轉', 'V形'],
            'rounding_bottom': ['圓底'],
            'flag': ['旗形'],
            'wedge': ['楔形'],
            'rectangle': ['矩形'],
            'triangle': ['三角形'],
            'head_shoulder_top': ['頭肩頂'],
            'double_top': ['雙頂'],
            'rounding_top': ['圓頂']
        }
        for name in name_map.get(key, []):
            category = desc.get('category', '')
            if category == 'Reversal':
                icon = ''
                color = '#16a34a'
            elif category == 'Continuation':
                icon = ''
                color = '#16a34a'
            elif category == 'Consolidation':
                icon = ''
                color = '#7c3aed'
            else:  # Bearish
                icon = ''
                color = '#dc2626'

            pattern_keywords[name] = {
                'display': f'<b style="color: {color};">{name}</b>',
                'category': category,
                'tags': desc.get('tags', [])
            }

    # 替換關鍵詞
    formatted_text = reason_text
    all_keywords = {**technical_keywords, **pattern_keywords}

    # 按長度排序，先替換長關鍵詞
    sorted_keywords = sorted(all_keywords.keys(), key=len, reverse=True)
    for keyword in sorted_keywords:
        if keyword in formatted_text:
            formatted_text = formatted_text.replace(keyword, all_keywords[keyword]['display'])

    # 其他標籤映射
    other_tags = {
        '趨勢': '<b style="color: #2563eb;">趨勢</b>',
        '動能': '<b style="color: #2563eb;">動能</b>',
        '波動': '<b style="color: #2563eb;">波動</b>',
        '反轉': '<b style="color: #16a34a;">反轉</b>',
        '延續': '<b style="color: #16a34a;">延續</b>',
        '盤整': '<b style="color: #16a34a;">盤整</b>',
        '超買': '<span style="color: #dc2626;">超買</span>',
        '超賣': '<span style="color: #16a34a;">超賣</span>',
        '金叉': '<span style="color: #16a34a;">金叉</span>',
        '死叉': '<span style="color: #dc2626;">死叉</span>',
        '多頭': '<span style="color: #16a34a;">多頭</span>',
        '空頭': '<span style="color: #dc2626;">空頭</span>',
        '成交量': '<b style="color: #2563eb;">成交量</b>',
    }

    for keyword, replacement in other_tags.items():
        formatted_text = formatted_text.replace(keyword, replacement)

    # 解析理由文字，提取觸發來源
    # 如果理由文字包含 "、" 分隔符，則按分隔符拆分
    if '、' in formatted_text:
        parts = formatted_text.split('、')
        formatted_parts = []
        triggered_indicators = []
        triggered_patterns = []

        for part in parts:
            part = part.strip()
            if part:
                # 移除 + 或 - 符號
                clean_part = part.replace('+', '').replace('-', '')

                # 檢查是否包含技術指標
                for keyword, info in technical_keywords.items():
                    if keyword in clean_part:
                        if keyword not in triggered_indicators:
                            triggered_indicators.append(keyword)

                # 檢查是否包含圖形模式
                for keyword, info in pattern_keywords.items():
                    if keyword in clean_part:
                        if keyword not in triggered_patterns:
                            triggered_patterns.append(keyword)

                formatted_parts.append(f"• {clean_part}")

        # 組合為 HTML 格式
        html_text = "<div style='line-height: 1.6;'>"
        html_text += "<p style='margin: 5px 0;'><b>推薦理由：</b></p>"

        # 顯示觸發來源（可反推線索）
        if triggered_indicators or triggered_patterns:
            html_text += "<p style='margin: 5px 0; font-size: 0.9em; color: #666;'><b>觸發來源：</b>"
            if triggered_indicators:
                indicators_display = '、'.join([all_keywords[k]['display'] for k in triggered_indicators if k in all_keywords])
                html_text += f"技術指標：{indicators_display}"
            if triggered_patterns:
                if triggered_indicators:
                    html_text += " | "
                patterns_display = '、'.join([all_keywords[k]['display'] for k in triggered_patterns if k in all_keywords])
                html_text += f"圖形訊號：{patterns_display}"
            html_text += "</p>"

        html_text += "<ul style='margin: 5px 0; padding-left: 20px;'>"
        for part in formatted_parts:
            html_text += f"<li style='margin: 3px 0;'>{part}</li>"
        html_text += "</ul>"
        html_text += "</div>"
        return html_text
    else:
        # 單一理由，直接格式化
        html_text = "<div style='line-height: 1.6;'>"
        html_text += f"<p style='margin: 5px 0;'><b>推薦理由：</b>{formatted_text}</p>"
        html_text += "</div>"
        return html_text


def ranking_value_label(kind: str, value: Any) -> str:
    text = str(value or "")
    mappings = {
        "threshold_mode": {"fixed": "固定門檻", "quantile": "百分位排名"},
        "ranking_method": {"nearest_rank": "最近名次法"},
    }
    return mappings.get(kind, {}).get(text, text or "未設定")


def generate_explain_panel(recommendation: Any) -> str:
    """生成 Explain 面板 v1：推薦分數拆解 + 風險點（Phase 3.3）

    Args:
        recommendation: 推薦股票 DTO

    Returns:
        str: Explain 面板 HTML 內容
    """
    html_text = "<div style='line-height: 1.6;'>"
    html_text += "<p style='margin: 5px 0;'><b>分數拆解：</b></p>"
    html_text += "<table style='width: 100%; border-collapse: collapse; margin: 5px 0;'>"

    # 總分
    total_score = recommendation.total_score
    score_color = '#16a34a' if total_score >= 60 else '#f59e0b' if total_score >= 50 else '#dc2626'
    html_text += f"""
    <tr style='background-color: #2d2d2d;'>
        <td style='padding: 5px; border: 1px solid #444;'><b>總分</b></td>
        <td style='padding: 5px; border: 1px solid #444; text-align: right;'>
            <span style='color: {score_color}; font-weight: bold; font-size: 1.1em;'>{total_score:.1f}</span>
        </td>
    </tr>
    """

    # 各子分數
    indicator_score = recommendation.indicator_score
    pattern_score = recommendation.pattern_score
    volume_score = recommendation.volume_score

    # 指標分數
    indicator_color = '#16a34a' if indicator_score >= 60 else '#f59e0b' if indicator_score >= 50 else '#dc2626'
    html_text += f"""
    <tr style='background-color: #1e1e1e;'>
        <td style='padding: 5px; border: 1px solid #444;'>技術指標分數</td>
        <td style='padding: 5px; border: 1px solid #444; text-align: right;'>
            <span style='color: {indicator_color};'>{indicator_score:.1f}</span>
        </td>
    </tr>
    """

    # 圖形分數
    pattern_color = '#16a34a' if pattern_score >= 60 else '#f59e0b' if pattern_score >= 50 else '#dc2626'
    html_text += f"""
    <tr style='background-color: #1e1e1e;'>
        <td style='padding: 5px; border: 1px solid #444;'>圖形模式分數</td>
        <td style='padding: 5px; border: 1px solid #444; text-align: right;'>
            <span style='color: {pattern_color};'>{pattern_score:.1f}</span>
        </td>
    </tr>
    """

    # 成交量分數
    volume_color = '#16a34a' if volume_score >= 60 else '#f59e0b' if volume_score >= 50 else '#dc2626'
    html_text += f"""
    <tr style='background-color: #1e1e1e;'>
        <td style='padding: 5px; border: 1px solid #444;'>成交量分數</td>
        <td style='padding: 5px; border: 1px solid #444; text-align: right;'>
            <span style='color: {volume_color};'>{volume_score:.1f}</span>
        </td>
    </tr>
    """

    html_text += "</table>"

    html_text += "<p style='margin: 10px 0 5px 0;'><b>排名門檻：</b></p>"
    html_text += "<ul style='margin: 5px 0; padding-left: 20px;'>"
    html_text += f"<li>門檻模式：{ranking_value_label('threshold_mode', recommendation.threshold_mode)}</li>"
    if recommendation.ranking_method:
        html_text += f"<li>排名方法：{ranking_value_label('ranking_method', recommendation.ranking_method)}</li>"
    if recommendation.score_percentile_bp is not None:
        html_text += f"<li>分數百分位：{recommendation.score_percentile_bp / 100:.1f}%</li>"
    if recommendation.eligible_universe_size is not None:
        html_text += f"<li>合格母體數：{recommendation.eligible_universe_size} 檔</li>"
    html_text += "</ul>"

    # 風險點提示
    html_text += "<p style='margin: 10px 0 5px 0;'><b>風險點：</b></p>"
    html_text += "<ul style='margin: 5px 0; padding-left: 20px;'>"

    risk_points = []

    # 檢查各項分數是否偏低
    if indicator_score < 50:
        risk_points.append(f"技術指標分數偏低（{indicator_score:.1f}），可能缺乏技術面支撐")
    if pattern_score < 40:
        risk_points.append(f"圖形模式分數偏低（{pattern_score:.1f}），圖形尚未完全形成")
    if volume_score < 50:
        risk_points.append(f"成交量分數偏低（{volume_score:.1f}），可能缺乏資金關注")

    # 檢查總分
    if total_score < 50:
        risk_points.append(f"總分偏低（{total_score:.1f}），綜合評分不足，建議謹慎")
    elif total_score < 60:
        risk_points.append(f"總分中等（{total_score:.1f}），建議觀察後續表現")

    # 檢查 Regime 匹配
    if not recommendation.regime_match:
        risk_points.append("市場狀態不匹配，策略可能不適用當前市場環境")

    # 檢查價格變化
    if recommendation.price_change < 0:
        risk_points.append(f"價格下跌（{recommendation.price_change:.1f}%），需注意趨勢反轉風險")
    elif recommendation.price_change > 10:
        risk_points.append(f"價格漲幅較大（{recommendation.price_change:.1f}%），需注意追高風險")

    if not risk_points:
        risk_points.append("✓ 各項指標表現良好，風險較低")

    for risk in risk_points:
        html_text += f"<li style='margin: 3px 0; color: #e0e0e0;'>{risk}</li>"

    html_text += "</ul>"
    html_text += "</div>"

    return html_text


def generate_why_not(recommendation: Any, config: dict[str, Any]) -> str:
    """生成 Why Not（反向解釋）：為什麼分數不夠高或可能被其他股票超越

    Args:
        recommendation: 推薦股票 DTO
        config: 策略配置

    Returns:
        str: Why Not 說明文字（HTML 格式）
    """
    why_not_items = []

    # 檢查各子分數（相對於理想值）
    # 理想值：各子分數都應該在 60 以上才算優秀
    ideal_score = 60.0

    if recommendation.indicator_score < ideal_score:
        gap = ideal_score - recommendation.indicator_score
        why_not_items.append({
            'item': '技術指標分數',
            'current': f'{recommendation.indicator_score:.1f}',
            'ideal': f'{ideal_score:.1f}',
            'gap': f'{gap:.1f}',
            'severity': 'high' if gap > 20 else 'medium' if gap > 10 else 'low',
            'hint': '可考慮等待更多技術指標訊號'
        })

    if recommendation.pattern_score < ideal_score:
        gap = ideal_score - recommendation.pattern_score
        why_not_items.append({
            'item': '圖形模式分數',
            'current': f'{recommendation.pattern_score:.1f}',
            'ideal': f'{ideal_score:.1f}',
            'gap': f'{gap:.1f}',
            'severity': 'high' if gap > 20 else 'medium' if gap > 10 else 'low',
            'hint': '圖形模式尚未完全形成'
        })

    if recommendation.volume_score < ideal_score:
        gap = ideal_score - recommendation.volume_score
        why_not_items.append({
            'item': '成交量分數',
            'current': f'{recommendation.volume_score:.1f}',
            'ideal': f'{ideal_score:.1f}',
            'gap': f'{gap:.1f}',
            'severity': 'medium' if gap > 15 else 'low',
            'hint': '成交量可能尚未明顯放大'
        })

    # 檢查篩選條件（如果不符合會被直接過濾）
    filters = config.get('filters', {})
    price_change_min = filters.get('price_change_min', 0.0)
    if recommendation.price_change < price_change_min:
        gap = price_change_min - recommendation.price_change
        why_not_items.append({
            'item': '漲幅篩選',
            'current': f'{recommendation.price_change:.1f}%',
            'required': f'{price_change_min:.1f}%',
            'gap': f'{gap:.1f}%',
            'severity': 'high',
            'hint': '不符合漲幅篩選條件，可能被過濾'
        })

    price_change_max = filters.get('price_change_max', 100.0)
    if recommendation.price_change > price_change_max:
        gap = recommendation.price_change - price_change_max
        why_not_items.append({
            'item': '漲幅上限',
            'current': f'{recommendation.price_change:.1f}%',
            'required': f'{price_change_max:.1f}%',
            'gap': f'{gap:.1f}%',
            'severity': 'medium',
            'hint': '漲幅過大，可能不符合策略要求'
        })

    # 檢查 Regime 匹配
    if not recommendation.regime_match:
        why_not_items.append({
            'item': '市場狀態匹配',
            'current': '不匹配',
            'required': '匹配',
            'gap': '需等待市場狀態變化',
            'severity': 'medium',
            'hint': '當前市場狀態與策略不匹配，分數可能被降權'
        })

    # 總分相對排名提示（如果總分較低）
    if recommendation.total_score < 50:
        why_not_items.append({
            'item': '總分偏低',
            'current': f'{recommendation.total_score:.1f}',
            'ideal': '60.0+',
            'gap': f'{60 - recommendation.total_score:.1f}',
            'severity': 'high',
            'hint': '總分較低，可能排名較後'
        })

    # 格式化輸出
    if not why_not_items:
        return "<div style='line-height: 1.6;'><p style='color: #16a34a;'><b>✓ 所有條件均符合，分數表現優秀</b></p></div>"

    html_text = "<div style='line-height: 1.6;'>"
    html_text += "<p style='margin: 5px 0;'><b>可能影響排名的因素：</b></p>"
    html_text += "<ul style='margin: 5px 0; padding-left: 20px;'>"

    for item in why_not_items:
        severity_color = {
            'high': '#dc2626',
            'medium': '#f59e0b',
            'low': '#6b7280'
        }.get(item['severity'], '#6b7280')

        html_text += f"<li style='margin: 5px 0;'>"
        html_text += f"<span style='color: {severity_color}; font-weight: bold;'>{item['item']}</span><br/>"
        html_text += f"&nbsp;&nbsp;目前：{item['current']}"
        if 'ideal' in item:
            html_text += f"，理想：{item['ideal']}"
        elif 'required' in item:
            html_text += f"，需要：{item['required']}"
        html_text += f"，差距：{item['gap']}<br/>"
        if 'hint' in item:
            html_text += f"&nbsp;&nbsp;<span style='color: #6b7280; font-size: 0.9em;'>{item['hint']}</span>"
        html_text += "</li>"

    html_text += "</ul>"
    html_text += "</div>"

    return html_text
