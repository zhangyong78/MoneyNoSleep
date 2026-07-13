from __future__ import annotations


_CANONICAL_TIMEFRAME_BY_ALIAS = {
    "d": "1d",
    "1d": "1d",
    "daily": "1d",
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "60m": "1h",
    "1h": "1h",
}

_ALIASES_BY_CANONICAL = {
    "1d": ("1d", "d", "daily"),
    "1m": ("1m",),
    "5m": ("5m",),
    "15m": ("15m",),
    "30m": ("30m",),
    "1h": ("1h", "60m"),
}


def normalize_timeframe(timeframe: str) -> str:
    value = str(timeframe).strip()
    if not value:
        return value
    return _CANONICAL_TIMEFRAME_BY_ALIAS.get(value.lower(), value)


def timeframe_aliases(timeframe: str) -> tuple[str, ...]:
    canonical = normalize_timeframe(timeframe)
    return _ALIASES_BY_CANONICAL.get(canonical, (canonical,))
