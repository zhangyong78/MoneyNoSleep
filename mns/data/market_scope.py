from __future__ import annotations

from typing import Iterable


MARKET_GROUP_LABELS: dict[str, str] = {
    "all_a": "全A股",
    "sh_a": "上证A股",
    "sz_a": "深证A股",
    "bj_a": "北交所",
    "sh_etf": "上证ETF",
    "sz_etf": "深证ETF",
    "all_etf": "全ETF",
}


def normalize_market_groups(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        key = str(value).strip().lower()
        if key and key in MARKET_GROUP_LABELS and key not in result:
            result.append(key)
    return result


def filter_stock_codes_by_market_groups(stock_codes: Iterable[str], market_groups: Iterable[str]) -> list[str]:
    groups = normalize_market_groups(market_groups)
    unique_codes = []
    seen: set[str] = set()
    for stock_code in stock_codes:
        code = str(stock_code).strip().upper()
        if not code or code in seen:
            continue
        if not groups or any(_matches_market_group(code, group) for group in groups):
            unique_codes.append(code)
            seen.add(code)
    return unique_codes


def _matches_market_group(stock_code: str, group: str) -> bool:
    symbol, _, exchange = stock_code.partition(".")
    if not symbol or not exchange:
        return False
    exchange = exchange.upper()
    if group == "all_a":
        return any(
            _matches_market_group(stock_code, child_group)
            for child_group in ("sh_a", "sz_a", "bj_a")
        )
    if group == "all_etf":
        return any(
            _matches_market_group(stock_code, child_group)
            for child_group in ("sh_etf", "sz_etf")
        )
    if group == "sh_a":
        return exchange == "SH" and symbol.startswith(("600", "601", "603", "605", "688"))
    if group == "sz_a":
        return exchange == "SZ" and symbol.startswith(("000", "001", "002", "003", "300", "301"))
    if group == "bj_a":
        return exchange == "BJ" and symbol.startswith(("4", "8"))
    if group == "sh_etf":
        return exchange == "SH" and symbol.startswith("5")
    if group == "sz_etf":
        return exchange == "SZ" and symbol.startswith("15")
    return False
