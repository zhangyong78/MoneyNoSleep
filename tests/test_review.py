import pandas as pd

from mns.data.duckdb_store import DuckDBStore
from mns.review.problem_analyzer import count_problem_tags
from mns.review.trade_reviewer import TradeReview, TradeReviewer


def test_problem_tag_counts():
    reviews = pd.DataFrame(
        [
            {"problem_tags": "追高,板块退潮"},
            {"problem_tags": "追高"},
            {"problem_tags": None},
        ]
    )

    result = count_problem_tags(reviews)

    assert result.iloc[0].to_dict() == {"problem_tag": "追高", "count": 2}


def test_trade_reviewer_builds_pending_record():
    review = TradeReviewer().build_pending(trade_id="t1", run_id="r1", stock_code="600000.SH")
    record = review.to_record()

    assert record["review_status"] == "PENDING_REVIEW"
    assert record["review_id"]
    assert record["review_time"]


def test_trade_review_round_trips_through_duckdb(tmp_path):
    store = DuckDBStore(tmp_path / "mns.duckdb")
    review = TradeReview(
        trade_id="t1",
        run_id="r1",
        stock_code="600000.SH",
        review_status="APPROVED",
        buy_point_rating="GOOD",
        sell_point_rating="TOO_EARLY",
        problem_tags="追高,卖早",
        reviewed_by="tester",
    )

    store.replace_trade_review(review.to_record())
    rows = store.get_run_trade_reviews("r1")

    assert len(rows) == 1
    assert rows.iloc[0]["review_status"] == "APPROVED"
    assert rows.iloc[0]["stock_code"] == "600000.SH"
    assert rows.iloc[0]["problem_tags"] == "追高,卖早"
