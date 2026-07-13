from __future__ import annotations

import argparse
from pathlib import Path

from mns import __version__
from mns.data.duckdb_store import DuckDBStore
from mns.data.khquant_cache import DEFAULT_KHQUANT_SOURCE_PATH, DEFAULT_SCREENING_CACHE_PATH, rebuild_screening_cache
from mns.data.parquet_store import ParquetStore
from mns.launcher import start_streamlit_ui
from mns.market.sector_provider import SectorSyncConfig, SectorSyncService, build_sector_provider
from mns.data.providers.akshare_provider import AKShareProvider
from mns.data.providers.baostock_provider import BaoStockProvider
from mns.data.providers.csv_provider import CSVPublicProvider
from mns.data.providers.qmt_provider import QMTProvider
from mns.data.sync import DailyKlineSyncService
from mns.backtest.ema_cross import EmaCrossBacktestConfig, EmaCrossBacktestRunner
from mns.backtest.semiconductor_ema import SemiconductorEmaBacktestRunner, SemiconductorEmaBaseConfig
from mns.backtest.two_stage_trend import TwoStageTrendBacktestConfig
from mns.pipelines.condition_screening import (
    ConditionCombo1Config,
    ConditionCombo1Runner,
    ConditionGroupConfig,
    ConditionTimelineConfig,
    ConditionTimelineRunner,
)
from mns.pipelines.daily_review import DailyReviewConfig, DailyReviewRunner
from mns.pipelines.daily_trend_following_review import DailyTrendFollowingReviewConfig, DailyTrendFollowingReviewRunner
from mns.pipelines.intraday_pullback_review import IntradayPullbackReviewConfig, IntradayPullbackReviewRunner
from mns.pipelines.two_stage_trend_review import TwoStageTrendReviewConfig, TwoStageTrendReviewRunner
from mns.pipelines.stock_feature_store import StockFeatureStoreBuilder, StockFeatureStoreConfig
from mns.strategies.two_stage_trend import TwoStageTrendStrategyConfig
from mns.review.bulk_screenshot_exporter import BulkScreenshotExporter
from mns.review.html_report_exporter import HtmlReviewReportExporter
from mns.review.screenshot_exporter import ScreenshotExporter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mns", description="Moneynosleep command line tools")
    parser.add_argument("--version", action="store_true", help="Show package version.")

    subparsers = parser.add_subparsers(dest="command")
    init_db = subparsers.add_parser("init-db", help="Initialize the DuckDB schema.")
    init_db.add_argument("--path", default="data/duckdb/mns.duckdb", help="DuckDB database path.")

    start_ui = subparsers.add_parser("start-ui", help="Start the Streamlit UI in the background.")
    start_ui.add_argument("--db", default="data/duckdb/mns.duckdb", help="DuckDB database path.")
    start_ui.add_argument("--host", default="127.0.0.1", help="Host address to bind the UI server.")
    start_ui.add_argument("--port", type=int, default=8501, help="Preferred UI server port.")
    start_ui.add_argument("--log-root", default="data/logs", help="UI log directory.")

    subparsers.add_parser("start-qt", help="Start the PySide6 Qt backtest workbench.")
    subparsers.add_parser("start-qt-local-data", help="Start the PySide6 local data sync and lookup workbench.")

    sync_csv = subparsers.add_parser("sync-csv-kline", help="Sync local CSV K-line data into DuckDB and Parquet.")
    sync_csv.add_argument("--root", default="data/raw/public", help="CSV provider root directory.")
    sync_csv.add_argument("--db", default="data/duckdb/mns.duckdb", help="DuckDB database path.")
    sync_csv.add_argument("--parquet-root", default="data/parquet", help="Parquet root directory.")
    sync_csv.add_argument("--stock-codes", required=True, help="Comma-separated stock codes, e.g. 600000.SH,000001.SZ.")
    sync_csv.add_argument("--start", required=True, help="Start date, YYYY-MM-DD.")
    sync_csv.add_argument("--end", required=True, help="End date, YYYY-MM-DD.")
    sync_csv.add_argument("--timeframe", default="1d", help="K-line timeframe.")
    sync_csv.add_argument("--allow-quality-issues", action="store_true", help="Write data even when quality issues exist.")

    sync_baostock = subparsers.add_parser("sync-baostock-kline", help="Sync BaoStock public K-line data into DuckDB and Parquet.")
    sync_baostock.add_argument("--db", default="data/duckdb/mns.duckdb", help="DuckDB database path.")
    sync_baostock.add_argument("--parquet-root", default="data/parquet", help="Parquet root directory.")
    sync_baostock.add_argument("--stock-codes", required=True, help="Comma-separated stock codes, e.g. 600000.SH,000001.SZ.")
    sync_baostock.add_argument("--start", required=True, help="Start date, YYYY-MM-DD.")
    sync_baostock.add_argument("--end", required=True, help="End date, YYYY-MM-DD.")
    sync_baostock.add_argument("--timeframe", default="1d", help="K-line timeframe: 1d, 5m, 15m, 30m, 60m.")
    sync_baostock.add_argument("--user-id", default=None, help="BaoStock user id. Default uses library anonymous login.")
    sync_baostock.add_argument("--password", default=None, help="BaoStock password. Default uses library anonymous login.")
    sync_baostock.add_argument("--adjustflag", default="2", help="BaoStock adjustment flag: 1 back adjusted, 2 front adjusted, 3 raw.")
    sync_baostock.add_argument("--allow-quality-issues", action="store_true", help="Write data even when quality issues exist.")

    sync_akshare = subparsers.add_parser("sync-akshare-kline", help="Sync AKShare public K-line data into DuckDB and Parquet.")
    sync_akshare.add_argument("--db", default="data/duckdb/mns.duckdb", help="DuckDB database path.")
    sync_akshare.add_argument("--parquet-root", default="data/parquet", help="Parquet root directory.")
    sync_akshare.add_argument("--stock-codes", required=True, help="Comma-separated stock codes, e.g. 600000.SH,000001.SZ.")
    sync_akshare.add_argument("--start", required=True, help="Start date, YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.")
    sync_akshare.add_argument("--end", required=True, help="End date, YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.")
    sync_akshare.add_argument("--timeframe", default="1d", help="K-line timeframe: 1d, 1m, 5m, 15m, 30m, 1h.")
    sync_akshare.add_argument("--adjust", default="qfq", help="AKShare adjustment: empty string, qfq, or hfq.")
    sync_akshare.add_argument("--allow-quality-issues", action="store_true", help="Write data even when quality issues exist.")

    qmt_test = subparsers.add_parser("test-qmt-connection", help="Test local miniQMT/xtquant connectivity.")
    qmt_test.add_argument("--ip", default="", help="miniQMT data service IP. Default uses local remembered address.")
    qmt_test.add_argument("--port", type=int, default=None, help="miniQMT data service port.")

    sync_qmt = subparsers.add_parser("sync-qmt-kline", help="Sync miniQMT local K-line data into DuckDB and Parquet.")
    sync_qmt.add_argument("--db", default="data/duckdb/mns.duckdb", help="DuckDB database path.")
    sync_qmt.add_argument("--parquet-root", default="data/parquet", help="Parquet root directory.")
    sync_qmt.add_argument("--stock-codes", required=True, help="Comma-separated stock codes, e.g. 600000.SH,000001.SZ.")
    sync_qmt.add_argument("--start", required=True, help="Start date, YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.")
    sync_qmt.add_argument("--end", required=True, help="End date, YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.")
    sync_qmt.add_argument("--timeframe", default="1d", help="K-line timeframe: 1d, 1m, 5m, 15m, 30m, 1h (60m alias supported).")
    sync_qmt.add_argument("--dividend-type", default="front", help="Dividend type: front/qfq, back/hfq, none/raw.")
    sync_qmt.add_argument("--ip", default="", help="miniQMT data service IP. Default uses local remembered address.")
    sync_qmt.add_argument("--port", type=int, default=None, help="miniQMT data service port.")
    sync_qmt.add_argument("--allow-quality-issues", action="store_true", help="Write data even when quality issues exist.")

    review = subparsers.add_parser("run-daily-review", help="Run local daily screening and quick review backtest.")
    review.add_argument("--db", default="data/duckdb/mns.duckdb", help="DuckDB database path.")
    review.add_argument("--start", required=True, help="Local K-line start date, YYYY-MM-DD.")
    review.add_argument("--end", required=True, help="Local K-line end date, YYYY-MM-DD.")
    review.add_argument("--as-of", required=True, help="Screening signal date, YYYY-MM-DD.")
    review.add_argument("--volume-ratio-min", type=float, default=1.0, help="Minimum 5-day volume ratio.")
    review.add_argument("--hold-days", type=int, default=5, help="Number of bars to hold after entry.")
    review.add_argument("--initial-cash", type=float, default=1_000_000, help="Initial capital.")
    review.add_argument("--per-trade-cash", type=float, default=100_000, help="Cash allocated to each quick-review trade.")
    review.add_argument("--commission-rate", type=float, default=0.0, help="Commission rate for quick review backtest.")
    review.add_argument("--stamp-tax-rate", type=float, default=0.0, help="Stamp tax rate for sells.")
    review.add_argument("--transfer-fee-rate", type=float, default=0.0, help="Transfer fee rate.")
    review.add_argument("--slippage-rate", type=float, default=0.0, help="Slippage rate applied to buy and sell prices.")
    review.add_argument("--export-root", default="data/reports/exports", help="CSV export directory.")

    trend_review = subparsers.add_parser("run-daily-trend-following-review", help="Run daily long-trend following backtest.")
    trend_review.add_argument("--db", default="data/duckdb/mns.duckdb", help="DuckDB database path.")
    trend_review.add_argument("--start", required=True, help="Local K-line start date, YYYY-MM-DD.")
    trend_review.add_argument("--end", required=True, help="Local K-line end date, YYYY-MM-DD.")
    trend_review.add_argument("--stock-codes", default="", help="Optional comma-separated stock codes filter.")
    trend_review.add_argument("--min-bias", type=float, default=0.02, help="Minimum EMA20 vs EMA50 bias.")
    trend_review.add_argument("--min-close-above-ema20", type=float, default=0.002, help="Minimum close above EMA20 for condition A.")
    trend_review.add_argument("--pullback-floor", type=float, default=0.995, help="Condition B pullback floor vs EMA20.")
    trend_review.add_argument("--min-volume-ratio", type=float, default=1.2, help="Minimum volume vs prior 20-day average.")
    trend_review.add_argument("--atr-stop-multiple", type=float, default=1.5, help="ATR multiple for initial stop.")
    trend_review.add_argument("--initial-cash", type=float, default=1_000_000, help="Initial capital.")
    trend_review.add_argument("--risk-per-trade-pct", type=float, default=0.008, help="Risk budget per trade as fraction of equity.")
    trend_review.add_argument("--max-position-pct", type=float, default=0.20, help="Maximum single-position fraction of equity.")
    trend_review.add_argument("--max-total-risk-pct", type=float, default=0.025, help="Maximum total open risk fraction of equity.")
    trend_review.add_argument("--high-volatility-threshold", type=float, default=0.06, help="ATR/price threshold for half size.")
    trend_review.add_argument("--high-volatility-size-factor", type=float, default=0.5, help="Position multiplier when volatility is high.")
    trend_review.add_argument("--commission-rate", type=float, default=0.0005, help="Commission rate.")
    trend_review.add_argument("--stamp-tax-rate", type=float, default=0.001, help="Stamp tax rate for sells.")
    trend_review.add_argument("--transfer-fee-rate", type=float, default=0.0, help="Transfer fee rate.")
    trend_review.add_argument("--slippage-rate", type=float, default=0.001, help="Slippage rate.")
    trend_review.add_argument("--stage2-timeout-days", type=int, default=15, help="Days without reaching +2R before timeout trend exit logic.")
    trend_review.add_argument("--export-root", default="data/reports/exports", help="CSV export directory.")

    intraday_review = subparsers.add_parser("run-intraday-pullback-review", help="Run 5-minute EMA21/MA55 pullback quick review.")
    intraday_review.add_argument("--db", default="data/duckdb/mns.duckdb", help="DuckDB database path.")
    intraday_review.add_argument("--start", required=True, help="Local K-line start date, YYYY-MM-DD.")
    intraday_review.add_argument("--end", required=True, help="Local K-line end date, YYYY-MM-DD.")
    intraday_review.add_argument("--as-of", required=True, help="Signal date, YYYY-MM-DD.")
    intraday_review.add_argument("--stock-codes", default="", help="Optional comma-separated stock codes filter.")
    intraday_review.add_argument("--pullback-tolerance", type=float, default=0.003, help="Allowed EMA21 pullback tolerance.")
    intraday_review.add_argument("--atr-stop-multiple", type=float, default=1.0, help="ATR multiple used for stop loss.")
    intraday_review.add_argument("--reward-multiple", type=float, default=2.0, help="ATR multiple used for take profit.")
    intraday_review.add_argument("--max-hold-bars", type=int, default=12, help="Maximum bars to hold when no stop/take-profit is hit.")
    intraday_review.add_argument("--initial-cash", type=float, default=1_000_000, help="Initial capital.")
    intraday_review.add_argument("--per-trade-cash", type=float, default=100_000, help="Cash cap allocated to each trade.")
    intraday_review.add_argument("--risk-per-trade", type=float, default=5_000, help="Maximum cash risk budget per trade.")
    intraday_review.add_argument("--commission-rate", type=float, default=0.0, help="Commission rate.")
    intraday_review.add_argument("--stamp-tax-rate", type=float, default=0.0, help="Stamp tax rate for sells.")
    intraday_review.add_argument("--transfer-fee-rate", type=float, default=0.0, help="Transfer fee rate.")
    intraday_review.add_argument("--slippage-rate", type=float, default=0.0, help="Slippage rate applied to buy and sell prices.")
    intraday_review.add_argument("--export-root", default="data/reports/exports", help="CSV export directory.")

    semiconductor_ema = subparsers.add_parser(
        "run-semiconductor-ema-backtest",
        help="Run daily THS semiconductor EMA21/EMA55 pullback backtest and export detailed files.",
    )
    semiconductor_ema.add_argument("--db", default="data/duckdb/mns.duckdb", help="DuckDB database path.")
    semiconductor_ema.add_argument("--start", default=None, help="Optional local K-line start date, YYYY-MM-DD.")
    semiconductor_ema.add_argument("--end", default=None, help="Optional local K-line end date, YYYY-MM-DD.")
    semiconductor_ema.add_argument("--board-name", default="半导体", help="THS industry board name.")
    semiconductor_ema.add_argument("--board-code", default=None, help="Optional THS industry board code.")
    semiconductor_ema.add_argument("--output-root", default="data/reports/semiconductor_ema", help="Report output root.")
    semiconductor_ema.add_argument("--initial-cash", type=float, default=1_000_000, help="Initial capital.")
    semiconductor_ema.add_argument("--risk-pct", type=float, default=0.01, help="Risk budget per trade as fraction of equity.")
    semiconductor_ema.add_argument("--ema55-slope-days", type=int, default=5, help="Slope lookback when the slope filter is enabled.")
    semiconductor_ema.add_argument("--lot-size", type=int, default=100, help="Board lot size.")
    semiconductor_ema.add_argument("--commission-rate", type=float, default=0.0, help="Commission rate.")
    semiconductor_ema.add_argument("--slippage-rate", type=float, default=0.0, help="Slippage rate.")
    semiconductor_ema.add_argument(
        "--constituent-source",
        default="ths_live",
        help="Constituent source: ths_live or local_sector_store.",
    )
    semiconductor_ema.add_argument("--sector-source", default="", help="Sector source filter when constituent-source=local_sector_store.")
    semiconductor_ema.add_argument("--sector-type", default="industry", help="Sector type filter when constituent-source=local_sector_store.")

    ema_cross = subparsers.add_parser(
        "run-ema-cross-backtest",
        help="Run EMA cross backtest with fixed-risk sizing and staged trailing stop.",
    )
    ema_cross.add_argument("--db", default="data/duckdb/mns.duckdb", help="DuckDB database path.")
    ema_cross.add_argument("--timeframe", default="1h", help="Local K-line timeframe, e.g. 1h. 60m is accepted as an alias.")
    ema_cross.add_argument("--start", required=True, help="Local K-line start date, YYYY-MM-DD.")
    ema_cross.add_argument("--end", required=True, help="Local K-line end date, YYYY-MM-DD.")
    ema_cross.add_argument("--stock-codes", required=True, help="Comma-separated stock codes, e.g. 600000.SH.")
    ema_cross.add_argument("--fast-period", type=int, default=21, help="Fast EMA period.")
    ema_cross.add_argument("--slow-period", type=int, default=55, help="Slow EMA period.")
    ema_cross.add_argument("--initial-cash", type=float, default=1_000_000, help="Initial capital.")
    ema_cross.add_argument("--risk-per-trade", type=float, default=5_000, help="Fixed risk budget per trade.")
    ema_cross.add_argument("--lot-size", type=int, default=100, help="Board lot size.")
    ema_cross.add_argument("--commission-rate", type=float, default=0.0003, help="Commission rate.")
    ema_cross.add_argument("--stamp-tax-rate", type=float, default=0.0, help="Stamp tax rate for sells.")
    ema_cross.add_argument("--transfer-fee-rate", type=float, default=0.0, help="Transfer fee rate.")
    ema_cross.add_argument("--slippage-rate", type=float, default=0.0005, help="Slippage rate.")
    ema_cross.add_argument("--export-root", default="data/reports/exports", help="CSV export directory.")

    sync_sector = subparsers.add_parser("sync-sector-data", help="Fetch and persist normalized sector data from a provider.")
    sync_sector.add_argument("--db", default="data/duckdb/mns.duckdb", help="DuckDB database path.")
    sync_sector.add_argument("--provider", default="akshare", help="Sector provider: akshare, qmt, custom, tushare, pywencai.")
    sync_sector.add_argument("--sector-types", default="industry,concept", help="Comma-separated sector types.")
    sync_sector.add_argument("--sector-names", default="", help="Optional comma-separated sector names filter.")
    sync_sector.add_argument("--max-sectors", type=int, default=None, help="Optional max sector count for a bounded sync.")
    sync_sector.add_argument("--skip-daily", action="store_true", help="Skip sector daily snapshot and derived strength tables.")
    sync_sector.add_argument("--qmt-raw-path", default="", help="Optional local QMT/raw sector snapshot path (JSON/CSV/dir).")

    screenshots = subparsers.add_parser("export-screenshots", help="Export marked K-line screenshots for every trade in a run.")
    screenshots.add_argument("--db", default="data/duckdb/mns.duckdb", help="DuckDB database path.")
    screenshots.add_argument("--run-id", required=True, help="Backtest run id.")
    screenshots.add_argument("--timeframe", default="1d", help="K-line timeframe.")
    screenshots.add_argument("--root", default="data/reports/screenshots", help="Screenshot output root.")

    html_report = subparsers.add_parser("export-html-report", help="Export a standalone HTML review report for a run.")
    html_report.add_argument("--db", default="data/duckdb/mns.duckdb", help="DuckDB database path.")
    html_report.add_argument("--run-id", required=True, help="Backtest run id.")
    html_report.add_argument("--root", default="data/reports/html", help="HTML report output root.")

    screening = subparsers.add_parser("run-condition-screening", help="Run condition screening for the first combo rule set.")
    screening.add_argument("--db", default="data/duckdb/mns.duckdb", help="DuckDB database path.")
    screening.add_argument(
        "--khquant-cache",
        default=DEFAULT_SCREENING_CACHE_PATH,
        help="Local screening cache DuckDB path.",
    )
    screening.add_argument("--signal-date", required=True, help="Signal date, YYYY-MM-DD.")
    screening.add_argument("--universe", default="all_a", help="Universe: all_a, hs300, zz500, sz50.")
    screening.add_argument("--ema-period", type=int, default=21, help="EMA period.")
    screening.add_argument("--enable-ema-breakout", action="store_true", help="Enable close-above-EMA breakout filter.")
    screening.add_argument("--volume-ma-window", type=int, default=20, help="Volume moving average window.")
    screening.add_argument("--disable-volume-ratio", action="store_true", help="Disable volume ratio filter.")
    screening.add_argument("--volume-ratio-min", type=float, default=3.0, help="Minimum volume ratio.")
    screening.add_argument("--daily-k-angle-window", type=int, default=5, help="Daily K angle rolling window.")
    screening.add_argument("--disable-daily-k-angle", action="store_true", help="Disable daily K angle filter.")
    screening.add_argument("--daily-k-angle-min", type=float, default=40.0, help="Minimum daily K angle in degrees.")
    screening.add_argument("--relative-low-window", type=int, default=120, help="Relative low rolling window.")
    screening.add_argument("--disable-relative-low", action="store_true", help="Disable relative low filter.")
    screening.add_argument("--relative-low-position-max", type=float, default=0.30, help="Maximum relative low position, 0-1.")
    screening.add_argument("--disable-earnings-filter", action="store_true", help="Disable earnings filter.")
    screening.add_argument("--earnings-forecast-change-min", type=float, default=20.0, help="Minimum earnings forecast change percent.")
    screening.add_argument("--earnings-yoy-min", type=float, default=10.0, help="Minimum earnings YoY percent.")
    screening.add_argument("--disable-price-max", action="store_true", help="Disable price cap filter.")
    screening.add_argument("--price-max", type=float, default=50.0, help="Maximum closing price.")
    screening.add_argument("--disable-turnover", action="store_true", help="Disable turnover filter.")
    screening.add_argument("--turnover-min", type=float, default=10.0, help="Minimum turnover percent.")
    screening.add_argument("--enable-recent-volume-spike", action="store_true", help="Require at least one large-amount day in the recent window.")
    screening.add_argument("--recent-volume-spike-window", type=int, default=20, help="Recent trading-day window used for the large-amount check.")
    screening.add_argument("--recent-volume-spike-min", type=float, default=1_000_000_000.0, help="Minimum daily amount for the large-amount check.")
    screening.add_argument("--enable-limit-up-count", action="store_true", help="Enable recent limit-up count filter.")
    screening.add_argument("--limit-up-count-window", type=int, default=30, help="Recent trading-day window used for the limit-up count filter.")
    screening.add_argument("--limit-up-count-min", type=int, default=1, help="Minimum number of limit-up days in the recent window.")
    screening.add_argument("--enable-upper-shadow-count", action="store_true", help="Enable recent upper-shadow count filter.")
    screening.add_argument("--upper-shadow-window", type=int, default=30, help="Recent trading-day window used for the upper-shadow count filter.")
    screening.add_argument("--upper-shadow-threshold-pct", type=float, default=5.0, help="Minimum upper-shadow percent counted in the recent upper-shadow filter.")
    screening.add_argument("--upper-shadow-count-min", type=int, default=1, help="Minimum number of recent upper-shadow days.")
    screening.add_argument("--enable-lower-shadow-count", action="store_true", help="Enable recent lower-shadow count filter.")
    screening.add_argument("--lower-shadow-window", type=int, default=30, help="Recent trading-day window used for the lower-shadow count filter.")
    screening.add_argument("--lower-shadow-threshold-pct", type=float, default=5.0, help="Minimum lower-shadow percent counted in the recent lower-shadow filter.")
    screening.add_argument("--lower-shadow-count-min", type=int, default=1, help="Minimum number of recent lower-shadow days.")
    screening.add_argument("--enable-amount-followup", action="store_true", help="Enable recent amount-spike followup filter.")
    screening.add_argument("--amount-followup-lookback-window", type=int, default=30, help="Lookback window for matured amount-spike followup events.")
    screening.add_argument("--amount-followup-trigger-min", type=float, default=1_000_000_000.0, help="Minimum trigger-day amount for the followup event.")
    screening.add_argument("--amount-followup-sum-min", type=float, default=5_000_000_000.0, help="Minimum next-5-day amount sum for the followup event.")
    screening.add_argument("--amount-followup-days", type=int, default=5, help="Number of trading days used in the amount followup event.")
    screening.add_argument("--enable-breakout-sequence", action="store_true", help="Enable sequential MA20 and MA55 breakout filter.")
    screening.add_argument("--breakout-ma20-within-days", type=int, default=10, help="Maximum trading days since the MA20 breakout.")
    screening.add_argument("--breakout-ma55-within-days", type=int, default=5, help="Maximum trading days since the MA55 breakout.")
    screening.add_argument("--enable-sector-strength-filter", action="store_true", help="Filter hits by local sector-strength context.")
    screening.add_argument("--sector-source", default="", help="Optional sector source filter, e.g. qmt or akshare.")
    screening.add_argument("--sector-type", default="", help="Optional sector type filter, e.g. industry or concept.")
    screening.add_argument("--max-sector-rank", type=int, default=0, help="Maximum allowed sector rank. 0 disables rank filtering.")
    screening.add_argument("--min-sector-strength-score", type=float, default=0.0, help="Minimum allowed sector strength score.")
    screening.add_argument("--required-sector-name-keywords", default="", help="Optional comma-separated keywords that sector names must match.")
    screening.add_argument("--hold-days", type=int, default=0, help="Optional forward hold-day review.")
    screening.add_argument("--include-st", action="store_true", help="Include ST stocks.")
    screening.add_argument("--combine-mode", default="any", help="Combine mode for groups: any or all.")
    screening.add_argument("--export-root", default="data/reports/exports", help="CSV export directory.")

    timeline = subparsers.add_parser("run-condition-timeline", help="Run historical timeline screening for the first combo rule set.")
    timeline.add_argument("--db", default="data/duckdb/mns.duckdb", help="DuckDB database path.")
    timeline.add_argument(
        "--khquant-cache",
        default=DEFAULT_SCREENING_CACHE_PATH,
        help="Local screening cache DuckDB path.",
    )
    timeline.add_argument("--start-date", required=True, help="Start date, YYYY-MM-DD.")
    timeline.add_argument("--end-date", required=True, help="End date, YYYY-MM-DD.")
    timeline.add_argument("--universe", default="all_a", help="Universe: all_a, hs300, zz500, sz50.")
    timeline.add_argument("--ema-period", type=int, default=21, help="EMA period.")
    timeline.add_argument("--enable-ema-breakout", action="store_true", help="Enable close-above-EMA breakout filter.")
    timeline.add_argument("--volume-ma-window", type=int, default=20, help="Volume moving average window.")
    timeline.add_argument("--disable-volume-ratio", action="store_true", help="Disable volume ratio filter.")
    timeline.add_argument("--volume-ratio-min", type=float, default=3.0, help="Minimum volume ratio.")
    timeline.add_argument("--daily-k-angle-window", type=int, default=5, help="Daily K angle rolling window.")
    timeline.add_argument("--disable-daily-k-angle", action="store_true", help="Disable daily K angle filter.")
    timeline.add_argument("--daily-k-angle-min", type=float, default=40.0, help="Minimum daily K angle in degrees.")
    timeline.add_argument("--relative-low-window", type=int, default=120, help="Relative low rolling window.")
    timeline.add_argument("--disable-relative-low", action="store_true", help="Disable relative low filter.")
    timeline.add_argument("--relative-low-position-max", type=float, default=0.30, help="Maximum relative low position, 0-1.")
    timeline.add_argument("--disable-earnings-filter", action="store_true", help="Disable earnings filter.")
    timeline.add_argument("--earnings-forecast-change-min", type=float, default=20.0, help="Minimum earnings forecast change percent.")
    timeline.add_argument("--earnings-yoy-min", type=float, default=10.0, help="Minimum earnings YoY percent.")
    timeline.add_argument("--disable-price-max", action="store_true", help="Disable price cap filter.")
    timeline.add_argument("--price-max", type=float, default=50.0, help="Maximum closing price.")
    timeline.add_argument("--disable-turnover", action="store_true", help="Disable turnover filter.")
    timeline.add_argument("--turnover-min", type=float, default=10.0, help="Minimum turnover percent.")
    timeline.add_argument("--enable-recent-volume-spike", action="store_true", help="Require at least one large-amount day in the recent window.")
    timeline.add_argument("--recent-volume-spike-window", type=int, default=20, help="Recent trading-day window used for the large-amount check.")
    timeline.add_argument("--recent-volume-spike-min", type=float, default=1_000_000_000.0, help="Minimum daily amount for the large-amount check.")
    timeline.add_argument("--enable-limit-up-count", action="store_true", help="Enable recent limit-up count filter.")
    timeline.add_argument("--limit-up-count-window", type=int, default=30, help="Recent trading-day window used for the limit-up count filter.")
    timeline.add_argument("--limit-up-count-min", type=int, default=1, help="Minimum number of limit-up days in the recent window.")
    timeline.add_argument("--enable-upper-shadow-count", action="store_true", help="Enable recent upper-shadow count filter.")
    timeline.add_argument("--upper-shadow-window", type=int, default=30, help="Recent trading-day window used for the upper-shadow count filter.")
    timeline.add_argument("--upper-shadow-threshold-pct", type=float, default=5.0, help="Minimum upper-shadow percent counted in the recent upper-shadow filter.")
    timeline.add_argument("--upper-shadow-count-min", type=int, default=1, help="Minimum number of recent upper-shadow days.")
    timeline.add_argument("--enable-lower-shadow-count", action="store_true", help="Enable recent lower-shadow count filter.")
    timeline.add_argument("--lower-shadow-window", type=int, default=30, help="Recent trading-day window used for the lower-shadow count filter.")
    timeline.add_argument("--lower-shadow-threshold-pct", type=float, default=5.0, help="Minimum lower-shadow percent counted in the recent lower-shadow filter.")
    timeline.add_argument("--lower-shadow-count-min", type=int, default=1, help="Minimum number of recent lower-shadow days.")
    timeline.add_argument("--enable-amount-followup", action="store_true", help="Enable recent amount-spike followup filter.")
    timeline.add_argument("--amount-followup-lookback-window", type=int, default=30, help="Lookback window for matured amount-spike followup events.")
    timeline.add_argument("--amount-followup-trigger-min", type=float, default=1_000_000_000.0, help="Minimum trigger-day amount for the followup event.")
    timeline.add_argument("--amount-followup-sum-min", type=float, default=5_000_000_000.0, help="Minimum next-5-day amount sum for the followup event.")
    timeline.add_argument("--amount-followup-days", type=int, default=5, help="Number of trading days used in the amount followup event.")
    timeline.add_argument("--enable-breakout-sequence", action="store_true", help="Enable sequential MA20 and MA55 breakout filter.")
    timeline.add_argument("--breakout-ma20-within-days", type=int, default=10, help="Maximum trading days since the MA20 breakout.")
    timeline.add_argument("--breakout-ma55-within-days", type=int, default=5, help="Maximum trading days since the MA55 breakout.")
    timeline.add_argument("--enable-sector-strength-filter", action="store_true", help="Filter hits by local sector-strength context.")
    timeline.add_argument("--sector-source", default="", help="Optional sector source filter, e.g. qmt or akshare.")
    timeline.add_argument("--sector-type", default="", help="Optional sector type filter, e.g. industry or concept.")
    timeline.add_argument("--max-sector-rank", type=int, default=0, help="Maximum allowed sector rank. 0 disables rank filtering.")
    timeline.add_argument("--min-sector-strength-score", type=float, default=0.0, help="Minimum allowed sector strength score.")
    timeline.add_argument("--required-sector-name-keywords", default="", help="Optional comma-separated keywords that sector names must match.")
    timeline.add_argument("--hold-days", type=int, default=0, help="Optional forward hold-day review.")
    timeline.add_argument("--include-st", action="store_true", help="Include ST stocks.")
    timeline.add_argument("--combine-mode", default="any", help="Combine mode for groups: any or all.")
    timeline.add_argument("--export-root", default="data/reports/exports", help="CSV export directory.")

    two_stage = subparsers.add_parser("run-two-stage-trend-backtest", help="Run ST-excluded daily watch-then-buy trend backtest.")
    two_stage.add_argument("--db", default="data/duckdb/mns.duckdb")
    two_stage.add_argument("--khquant-cache", default=DEFAULT_SCREENING_CACHE_PATH)
    two_stage.add_argument("--start", required=True)
    two_stage.add_argument("--end", required=True)
    two_stage.add_argument("--initial-cash", type=float, default=200_000)
    two_stage.add_argument("--max-positions", type=int, default=10)
    two_stage.add_argument("--per-position-cash", type=float, default=None, help="Optional fixed cash target per new position.")
    two_stage.add_argument("--initial-stop-pct", type=float, default=0.10)
    two_stage.add_argument("--atr-multiple", type=float, default=2.0)
    two_stage.add_argument("--ma20-exit-mode", choices=("off", "always", "profit_only"), default="off", help="MA20 exit: off, always, or only when profitable.")
    two_stage.add_argument("--attention-window", type=int, default=60)
    two_stage.add_argument("--entry-volume-ratio", type=float, default=1.2)
    two_stage.add_argument("--entry-volume-ratio-max", type=float, default=3.0)
    two_stage.add_argument("--entry-breakout-pct-max", type=float, default=0.03)
    two_stage.add_argument("--max-chase-pct", type=float, default=0.12)
    two_stage.add_argument("--export-root", default="data/reports/exports")

    rebuild_cache = subparsers.add_parser("rebuild-screening-cache", help="Build or rebuild Moneynosleep local screening cache.")
    rebuild_cache.add_argument("--target", default=DEFAULT_SCREENING_CACHE_PATH, help="Target local screening cache path.")
    rebuild_cache.add_argument("--source", default=DEFAULT_KHQUANT_SOURCE_PATH, help="Source cache path used for seeding.")

    feature_store = subparsers.add_parser("build-stock-features", help="Build per-trade-date stock feature snapshots for screening and replay.")
    feature_store.add_argument("--db", default="data/duckdb/mns.duckdb", help="DuckDB database path.")
    feature_store.add_argument("--start-date", default=None, help="Optional feature snapshot start date, YYYY-MM-DD.")
    feature_store.add_argument("--end-date", default=None, help="Optional feature snapshot end date, YYYY-MM-DD.")
    feature_store.add_argument("--stock-codes", default="", help="Optional comma-separated stock codes filter.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    if args.command == "init-db":
        store = DuckDBStore(Path(args.path))
        store.initialize()
        print(f"Initialized DuckDB schema at {store.path}")
        return 0

    if args.command == "start-ui":
        result = start_streamlit_ui(
            app_path=Path("ui/app.py"),
            db_path=args.db,
            host=args.host,
            preferred_port=args.port,
            log_root=args.log_root,
        )
        print(f"UI started: {result['url']}")
        print(f"pid: {result['pid']}")
        print(f"stdout_log: {result['stdout_log']}")
        print(f"stderr_log: {result['stderr_log']}")
        if not result["started"]:
            print("warning: UI process was started, but the HTTP endpoint did not become ready within the wait window.")
        return 0

    if args.command == "start-qt":
        from mns.qt_backtest.app import main as qt_main

        return qt_main()

    if args.command == "start-qt-local-data":
        from mns.qt_local_data.app import main as qt_local_data_main

        return qt_local_data_main()

    if args.command == "sync-csv-kline":
        service = DailyKlineSyncService(
            provider=CSVPublicProvider(args.root),
            duckdb_store=DuckDBStore(args.db),
            parquet_store=ParquetStore(args.parquet_root),
            strict_quality=not args.allow_quality_issues,
        )
        result = service.sync(
            stock_codes=[code.strip() for code in args.stock_codes.split(",") if code.strip()],
            start_time=__import__("datetime").datetime.fromisoformat(args.start),
            end_time=__import__("datetime").datetime.fromisoformat(args.end),
            timeframe=args.timeframe,
        )
        print(
            f"Synced {result.rows_written} rows, "
            f"{len(result.parquet_files)} parquet partitions, "
            f"{result.quality_issue_count} quality issues."
        )
        return 0

    if args.command == "sync-baostock-kline":
        provider = BaoStockProvider(
            adjustflag=args.adjustflag,
            user_id=args.user_id,
            password=args.password,
        )
        try:
            service = DailyKlineSyncService(
                provider=provider,
                duckdb_store=DuckDBStore(args.db),
                parquet_store=ParquetStore(args.parquet_root),
                strict_quality=not args.allow_quality_issues,
            )
            result = service.sync(
                stock_codes=[code.strip() for code in args.stock_codes.split(",") if code.strip()],
                start_time=__import__("datetime").datetime.fromisoformat(args.start),
                end_time=__import__("datetime").datetime.fromisoformat(args.end),
                timeframe=args.timeframe,
            )
        finally:
            provider.logout()
        print(
            f"Synced {result.rows_written} rows from BaoStock, "
            f"{len(result.parquet_files)} parquet partitions, "
            f"{result.quality_issue_count} quality issues."
        )
        return 0

    if args.command == "sync-akshare-kline":
        service = DailyKlineSyncService(
            provider=AKShareProvider(adjust=args.adjust),
            duckdb_store=DuckDBStore(args.db),
            parquet_store=ParquetStore(args.parquet_root),
            strict_quality=not args.allow_quality_issues,
        )
        result = service.sync(
            stock_codes=[code.strip() for code in args.stock_codes.split(",") if code.strip()],
            start_time=__import__("datetime").datetime.fromisoformat(args.start),
            end_time=__import__("datetime").datetime.fromisoformat(args.end),
            timeframe=args.timeframe,
        )
        print(
            f"Synced {result.rows_written} rows from AKShare, "
            f"{len(result.parquet_files)} parquet partitions, "
            f"{result.quality_issue_count} quality issues."
        )
        return 0

    if args.command == "test-qmt-connection":
        provider = QMTProvider(ip=args.ip, port=args.port)
        info = provider.connection_info()
        print("miniQMT connection OK")
        for key, value in info.items():
            print(f"{key}: {value}")
        return 0

    if args.command == "sync-qmt-kline":
        service = DailyKlineSyncService(
            provider=QMTProvider(
                dividend_type=args.dividend_type,
                ip=args.ip,
                port=args.port,
            ),
            duckdb_store=DuckDBStore(args.db),
            parquet_store=ParquetStore(args.parquet_root),
            strict_quality=not args.allow_quality_issues,
        )
        result = service.sync(
            stock_codes=[code.strip() for code in args.stock_codes.split(",") if code.strip()],
            start_time=__import__("datetime").datetime.fromisoformat(args.start),
            end_time=__import__("datetime").datetime.fromisoformat(args.end),
            timeframe=args.timeframe,
        )
        print(
            f"Synced {result.rows_written} rows from miniQMT, "
            f"{len(result.parquet_files)} parquet partitions, "
            f"{result.quality_issue_count} quality issues."
        )
        return 0

    if args.command == "run-daily-review":
        runner = DailyReviewRunner(
            DailyReviewConfig(
                db_path=args.db,
                start_date=args.start,
                end_date=args.end,
                as_of_date=args.as_of,
                volume_ratio_min=args.volume_ratio_min,
                hold_days=args.hold_days,
                initial_cash=args.initial_cash,
                per_trade_cash=args.per_trade_cash,
                commission_rate=args.commission_rate,
                stamp_tax_rate=args.stamp_tax_rate,
                transfer_fee_rate=args.transfer_fee_rate,
                slippage_rate=args.slippage_rate,
                export_root=args.export_root,
            )
        )
        result = runner.run()
        print(
            f"Run {result['run_id']}: "
            f"{len(result['candidates'])} candidates, "
            f"{len(result['signals'])} signals, "
            f"{len(result['trades'])} trades."
        )
        for name, path in result["outputs"].items():
            print(f"{name}: {path}")
        return 0

    if args.command == "run-daily-trend-following-review":
        runner = DailyTrendFollowingReviewRunner(
            DailyTrendFollowingReviewConfig(
                db_path=args.db,
                start_date=args.start,
                end_date=args.end,
                stock_codes=[code.strip() for code in args.stock_codes.split(",") if code.strip()] or None,
                min_bias=args.min_bias,
                min_close_above_ema20=args.min_close_above_ema20,
                pullback_floor=args.pullback_floor,
                min_volume_ratio=args.min_volume_ratio,
                atr_stop_multiple=args.atr_stop_multiple,
                initial_cash=args.initial_cash,
                risk_per_trade_pct=args.risk_per_trade_pct,
                max_position_pct=args.max_position_pct,
                max_total_risk_pct=args.max_total_risk_pct,
                high_volatility_threshold=args.high_volatility_threshold,
                high_volatility_size_factor=args.high_volatility_size_factor,
                commission_rate=args.commission_rate,
                stamp_tax_rate=args.stamp_tax_rate,
                transfer_fee_rate=args.transfer_fee_rate,
                slippage_rate=args.slippage_rate,
                stage2_timeout_days=args.stage2_timeout_days,
                export_root=args.export_root,
            )
        )
        result = runner.run()
        print(
            f"Run {result['run_id']}: "
            f"{len(result['candidates'])} candidates, "
            f"{len(result['signals'])} signals, "
            f"{len(result['trades'])} trades."
        )
        print(f"summary: {result['summary']}")
        for name, path in result["outputs"].items():
            print(f"{name}: {path}")
        return 0

    if args.command == "run-intraday-pullback-review":
        runner = IntradayPullbackReviewRunner(
            IntradayPullbackReviewConfig(
                db_path=args.db,
                start_date=args.start,
                end_date=args.end,
                as_of_date=args.as_of,
                stock_codes=[code.strip() for code in args.stock_codes.split(",") if code.strip()] or None,
                pullback_tolerance=args.pullback_tolerance,
                atr_stop_multiple=args.atr_stop_multiple,
                reward_multiple=args.reward_multiple,
                max_hold_bars=args.max_hold_bars,
                initial_cash=args.initial_cash,
                per_trade_cash=args.per_trade_cash,
                risk_per_trade=args.risk_per_trade,
                commission_rate=args.commission_rate,
                stamp_tax_rate=args.stamp_tax_rate,
                transfer_fee_rate=args.transfer_fee_rate,
                slippage_rate=args.slippage_rate,
                export_root=args.export_root,
            )
        )
        result = runner.run()
        print(
            f"Run {result['run_id']}: "
            f"{len(result['signals'])} signals, "
            f"{len(result['trades'])} trades."
        )
        for name, path in result["outputs"].items():
            print(f"{name}: {path}")
        return 0

    if args.command == "run-semiconductor-ema-backtest":
        runner = SemiconductorEmaBacktestRunner(
            SemiconductorEmaBaseConfig(
                db_path=args.db,
                start_date=args.start,
                end_date=args.end,
                board_name=args.board_name,
                board_code=args.board_code,
                output_root=args.output_root,
                initial_cash=args.initial_cash,
                risk_pct=args.risk_pct,
                ema55_slope_days=args.ema55_slope_days,
                lot_size=args.lot_size,
                commission_rate=args.commission_rate,
                slippage_rate=args.slippage_rate,
                constituent_source=args.constituent_source,
                sector_source=args.sector_source,
                sector_type=args.sector_type,
            )
        )
        result = runner.run()
        print(f"Run {result['run_id']}")
        print(f"output_root: {result['output_root']}")
        print(f"ths_board_snapshot: {result['board_snapshot_path']}")
        print(f"parameter_grid_summary: {result['parameter_grid_summary_path']}")
        print(f"analyst_brief: {result['analyst_brief_path']}")
        print(f"board_constituent_count: {result['board_constituent_count']}")
        print(f"date_range: {result['date_range']['start']} -> {result['date_range']['end']}")
        if result["focus_summary"] is not None:
            print(f"focus_summary: {result['focus_summary']}")
        return 0

    if args.command == "run-ema-cross-backtest":
        runner = EmaCrossBacktestRunner(
            EmaCrossBacktestConfig(
                db_path=args.db,
                timeframe=args.timeframe,
                start_date=args.start,
                end_date=args.end,
                stock_codes=[code.strip() for code in args.stock_codes.split(",") if code.strip()] or None,
                fast_period=args.fast_period,
                slow_period=args.slow_period,
                initial_cash=args.initial_cash,
                risk_per_trade=args.risk_per_trade,
                lot_size=args.lot_size,
                commission_rate=args.commission_rate,
                stamp_tax_rate=args.stamp_tax_rate,
                transfer_fee_rate=args.transfer_fee_rate,
                slippage_rate=args.slippage_rate,
                export_root=args.export_root,
            )
        )
        result = runner.run()
        print(f"Run {result['run_id']}")
        print(f"signals: {len(result['signals'])}")
        print(f"trades: {len(result['trades'])}")
        print(f"summary: {result['summary']}")
        for name, path in result["outputs"].items():
            print(f"{name}: {path}")
        return 0

    if args.command == "sync-sector-data":
        provider_kwargs = {}
        if args.provider.strip().lower() == "qmt" and args.qmt_raw_path:
            provider_kwargs["raw_snapshot_path"] = args.qmt_raw_path
        provider = build_sector_provider(args.provider, **provider_kwargs)
        result = SectorSyncService(
            provider=provider,
            config=SectorSyncConfig(
                db_path=args.db,
                sector_types=[item.strip() for item in args.sector_types.split(",") if item.strip()] or None,
                sector_names=[item.strip() for item in args.sector_names.split(",") if item.strip()] or None,
                include_daily=not args.skip_daily,
                max_sectors=args.max_sectors,
            ),
        ).run()
        for key, value in result.items():
            print(f"{key}: {value}")
        return 0

    if args.command == "run-condition-screening":
        runner = ConditionCombo1Runner(
            ConditionCombo1Config(
                db_path=args.db,
                khquant_cache_path=args.khquant_cache,
                export_root=args.export_root,
                signal_date=args.signal_date,
                universe=args.universe,
                ema_period=args.ema_period,
                enable_ema_breakout=args.enable_ema_breakout,
                volume_ma_window=args.volume_ma_window,
                enable_volume_ratio=not args.disable_volume_ratio,
                volume_ratio_min=args.volume_ratio_min,
                daily_k_angle_window=args.daily_k_angle_window,
                enable_daily_k_angle=not args.disable_daily_k_angle,
                daily_k_angle_min=args.daily_k_angle_min,
                relative_low_window=args.relative_low_window,
                enable_relative_low=not args.disable_relative_low,
                relative_low_position_max=args.relative_low_position_max,
                enable_earnings_filter=not args.disable_earnings_filter,
                earnings_forecast_change_min=args.earnings_forecast_change_min,
                earnings_yoy_min=args.earnings_yoy_min,
                enable_price_max=not args.disable_price_max,
                price_max=args.price_max,
                enable_turnover=not args.disable_turnover,
                turnover_min=args.turnover_min,
                enable_recent_volume_spike=args.enable_recent_volume_spike,
                recent_volume_spike_window=args.recent_volume_spike_window,
                recent_volume_spike_min=args.recent_volume_spike_min,
                enable_limit_up_count=args.enable_limit_up_count,
                limit_up_count_window=args.limit_up_count_window,
                limit_up_count_min=args.limit_up_count_min,
                enable_upper_shadow_count=args.enable_upper_shadow_count,
                upper_shadow_window=args.upper_shadow_window,
                upper_shadow_threshold_pct=args.upper_shadow_threshold_pct,
                upper_shadow_count_min=args.upper_shadow_count_min,
                enable_lower_shadow_count=args.enable_lower_shadow_count,
                lower_shadow_window=args.lower_shadow_window,
                lower_shadow_threshold_pct=args.lower_shadow_threshold_pct,
                lower_shadow_count_min=args.lower_shadow_count_min,
                enable_amount_followup=args.enable_amount_followup,
                amount_followup_lookback_window=args.amount_followup_lookback_window,
                amount_followup_trigger_min=args.amount_followup_trigger_min,
                amount_followup_sum_min=args.amount_followup_sum_min,
                amount_followup_days=args.amount_followup_days,
                enable_breakout_sequence=args.enable_breakout_sequence,
                breakout_ma20_within_days=args.breakout_ma20_within_days,
                breakout_ma55_within_days=args.breakout_ma55_within_days,
                enable_sector_strength_filter=args.enable_sector_strength_filter,
                sector_source=args.sector_source,
                sector_type=args.sector_type,
                max_sector_rank=args.max_sector_rank,
                min_sector_strength_score=args.min_sector_strength_score,
                required_sector_name_keywords=args.required_sector_name_keywords,
                hold_days=args.hold_days,
                exclude_st=not args.include_st,
            )
        )
        result = runner.run()
        print(
            f"Run {result['run_id']}: "
            f"{result['summary']['hit_count']} hits "
            f"out of {result['summary']['universe_size']} stocks."
        )
        print(f"export: {result['export_path']}")
        return 0

    if args.command == "rebuild-screening-cache":
        result = rebuild_screening_cache(target_path=args.target, source_path=args.source)
        print(f"Rebuilt screening cache: {result['target_path']}")
        for table_name, row_count in result.items():
            if table_name == "target_path":
                continue
            print(f"{table_name}: {row_count}")
        return 0

    if args.command == "build-stock-features":
        result = StockFeatureStoreBuilder(
            StockFeatureStoreConfig(
                db_path=args.db,
                start_date=args.start_date,
                end_date=args.end_date,
                stock_codes=[code.strip() for code in args.stock_codes.split(",") if code.strip()] or None,
            )
        ).run()
        print(
            f"Built stock features: {result['feature_rows']} feature rows, "
            f"{result['followup_rows']} followup rows, "
            f"{result['stock_count']} stocks, "
            f"{result['start_date']} -> {result['end_date']}."
        )
        return 0

    if args.command == "run-condition-timeline":
        group = ConditionGroupConfig(
            name="组合1",
            enabled=True,
            ema_period=args.ema_period,
            enable_ema_breakout=args.enable_ema_breakout,
            volume_ma_window=args.volume_ma_window,
            enable_volume_ratio=not args.disable_volume_ratio,
            volume_ratio_min=args.volume_ratio_min,
            daily_k_angle_window=args.daily_k_angle_window,
            enable_daily_k_angle=not args.disable_daily_k_angle,
            daily_k_angle_min=args.daily_k_angle_min,
            relative_low_window=args.relative_low_window,
            enable_relative_low=not args.disable_relative_low,
            relative_low_position_max=args.relative_low_position_max,
            enable_earnings_filter=not args.disable_earnings_filter,
            earnings_forecast_change_min=args.earnings_forecast_change_min,
            earnings_yoy_min=args.earnings_yoy_min,
            enable_price_max=not args.disable_price_max,
            price_max=args.price_max,
            enable_turnover=not args.disable_turnover,
            turnover_min=args.turnover_min,
            enable_recent_volume_spike=args.enable_recent_volume_spike,
            recent_volume_spike_window=args.recent_volume_spike_window,
            recent_volume_spike_min=args.recent_volume_spike_min,
            enable_limit_up_count=args.enable_limit_up_count,
            limit_up_count_window=args.limit_up_count_window,
            limit_up_count_min=args.limit_up_count_min,
            enable_upper_shadow_count=args.enable_upper_shadow_count,
            upper_shadow_window=args.upper_shadow_window,
            upper_shadow_threshold_pct=args.upper_shadow_threshold_pct,
            upper_shadow_count_min=args.upper_shadow_count_min,
            enable_lower_shadow_count=args.enable_lower_shadow_count,
            lower_shadow_window=args.lower_shadow_window,
            lower_shadow_threshold_pct=args.lower_shadow_threshold_pct,
            lower_shadow_count_min=args.lower_shadow_count_min,
            enable_amount_followup=args.enable_amount_followup,
            amount_followup_lookback_window=args.amount_followup_lookback_window,
            amount_followup_trigger_min=args.amount_followup_trigger_min,
            amount_followup_sum_min=args.amount_followup_sum_min,
            amount_followup_days=args.amount_followup_days,
            enable_breakout_sequence=args.enable_breakout_sequence,
            breakout_ma20_within_days=args.breakout_ma20_within_days,
            breakout_ma55_within_days=args.breakout_ma55_within_days,
            enable_sector_strength_filter=args.enable_sector_strength_filter,
            sector_source=args.sector_source,
            sector_type=args.sector_type,
            max_sector_rank=args.max_sector_rank,
            min_sector_strength_score=args.min_sector_strength_score,
            required_sector_name_keywords=args.required_sector_name_keywords,
            hold_days=args.hold_days,
        )
        runner = ConditionTimelineRunner(
            ConditionTimelineConfig(
                db_path=args.db,
                khquant_cache_path=args.khquant_cache,
                export_root=args.export_root,
                start_date=args.start_date,
                end_date=args.end_date,
                universe=args.universe,
                exclude_st=not args.include_st,
                combine_mode=args.combine_mode,
                groups=[group],
            )
        )
        result = runner.run()
        print(
            f"Run {result['run_id']}: "
            f"{result['summary']['hit_count']} total hits, "
            f"{result['summary']['unique_stock_count']} unique stocks."
        )
        print(f"export: {result['export_path']}")
        return 0

    if args.command == "run-two-stage-trend-backtest":
        result = TwoStageTrendReviewRunner(
            TwoStageTrendReviewConfig(
                db_path=args.db, khquant_cache_path=args.khquant_cache, start_date=args.start, end_date=args.end,
                initial_cash=args.initial_cash, max_positions=args.max_positions, export_root=args.export_root,
                strategy=TwoStageTrendStrategyConfig(
                    attention_window=args.attention_window,
                    entry_volume_ratio=args.entry_volume_ratio,
                    entry_volume_ratio_max=args.entry_volume_ratio_max,
                    entry_breakout_pct_max=args.entry_breakout_pct_max,
                    max_chase_pct=args.max_chase_pct,
                ),
                backtest=TwoStageTrendBacktestConfig(
                    initial_stop_pct=args.initial_stop_pct,
                    atr_multiple=args.atr_multiple,
                    per_position_cash=args.per_position_cash,
                    ma20_exit_mode=args.ma20_exit_mode,
                ),
            )
        ).run()
        print(f"Run {result['run_id']}: {len(result['signals'])} signals, {len(result['trades'])} trades.")
        print(f"summary: {result['summary']}")
        for name, path in result["outputs"].items():
            print(f"{name}: {path}")
        return 0

    if args.command == "export-screenshots":
        exporter = BulkScreenshotExporter(
            store=DuckDBStore(args.db),
            screenshot_exporter=ScreenshotExporter(args.root),
        )
        records = exporter.export_run(args.run_id, timeframe=args.timeframe)
        print(f"Exported {len(records)} screenshots for run {args.run_id}.")
        return 0

    if args.command == "export-html-report":
        path = HtmlReviewReportExporter(
            store=DuckDBStore(args.db),
            root=args.root,
        ).export_run(args.run_id)
        print(f"Exported HTML report: {path}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
