from __future__ import annotations

from enum import StrEnum


class WatchStatus(StrEnum):
    WATCHING = "WATCHING"
    PULLBACK = "PULLBACK"
    READY = "READY"
    BOUGHT = "BOUGHT"
    INVALID = "INVALID"
    REMOVED = "REMOVED"
