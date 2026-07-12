"""MoneyDJ 分點 transport request 的純建構規則。"""

from typing import Any, Dict


def build_branch_url(
    branch_info: Dict[str, Any],
    start_date: str,
    end_date: str,
    metric: str = "lots",
) -> str:
    url_param_a = str(branch_info.get("url_param_a", ""))
    url_param_b = str(branch_info.get("url_param_b", ""))
    if not url_param_b:
        raise ValueError(
            f"url_param_b 為空: {branch_info.get('branch_system_key', 'UNKNOWN')}"
        )
    metric_codes = {"lots": "E", "amount": "B"}
    if metric not in metric_codes:
        raise ValueError(f"不支援的 MoneyDJ 指標: {metric}")
    return (
        "https://5850web.moneydj.com/z/zg/zgb/zgb0.djhtm"
        f"?a={url_param_a}&b={url_param_b}&c={metric_codes[metric]}"
        f"&e={start_date}&f={end_date}"
    )
