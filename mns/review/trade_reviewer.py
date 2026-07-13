from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import uuid4


@dataclass(frozen=True)
class TradeReview:
    trade_id: str
    run_id: str
    stock_code: str
    review_status: str = "PENDING_REVIEW"
    buy_point_rating: str | None = None
    sell_point_rating: str | None = None
    risk_control_rating: str | None = None
    market_context_rating: str | None = None
    sector_context_rating: str | None = None
    manual_note: str | None = None
    problem_tags: str | None = None
    screenshot_path: str | None = None
    reviewed_by: str | None = None
    review_time: datetime | None = None
    review_id: str | None = None

    def to_record(self) -> dict:
        record = asdict(self)
        record["review_id"] = self.review_id or uuid4().hex
        record["review_time"] = self.review_time or datetime.now()
        return record


class TradeReviewer:
    def build_pending(self, *, trade_id: str, run_id: str, stock_code: str) -> TradeReview:
        return TradeReview(trade_id=trade_id, run_id=run_id, stock_code=stock_code)
