from __future__ import annotations

from mns.data.market_scope import filter_stock_codes_by_market_groups, normalize_market_groups


def test_normalize_market_groups_keeps_supported_values_once():
    assert normalize_market_groups(["all_a", "SH_A", "all_a", "bad"]) == ["all_a", "sh_a"]


def test_filter_stock_codes_by_market_groups_matches_a_shares_and_etfs():
    codes = [
        "600000.SH",
        "688981.SH",
        "000001.SZ",
        "301312.SZ",
        "830799.BJ",
        "510300.SH",
        "159915.SZ",
        "000016.SH",
    ]

    assert filter_stock_codes_by_market_groups(codes, ["all_a"]) == [
        "600000.SH",
        "688981.SH",
        "000001.SZ",
        "301312.SZ",
        "830799.BJ",
    ]
    assert filter_stock_codes_by_market_groups(codes, ["sh_etf", "sz_etf"]) == [
        "510300.SH",
        "159915.SZ",
    ]
    assert filter_stock_codes_by_market_groups(codes, ["sh_a"]) == [
        "600000.SH",
        "688981.SH",
    ]
