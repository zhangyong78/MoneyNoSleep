from __future__ import annotations


def round_lot_quantity(raw_quantity: float, lot_size: int = 100) -> int:
    if raw_quantity <= 0:
        return 0
    return int(raw_quantity // lot_size * lot_size)


def fixed_cash_quantity(cash: float, price: float, lot_size: int = 100) -> int:
    if price <= 0:
        return 0
    return round_lot_quantity(cash / price, lot_size=lot_size)
