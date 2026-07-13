from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path
from uuid import uuid4

import pandas as pd

os.environ.setdefault("QT_API", "pyside6")

from mns.qt_backtest.charts import build_portfolio_chart_html, render_review_chart
from mns.qt_backtest.review_widget import FastReviewChartPanel
from mns.qt_backtest.service import QtBacktestRequest, QtBacktestResult, QtBacktestService


try:
    from PySide6.QtCore import QThread, Qt, QTimer, QUrl, Signal
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QDoubleSpinBox,
        QFileDialog,
        QFormLayout,
        QGroupBox,
        QHeaderView,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QProgressBar,
        QSplitter,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QTextBrowser,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit("PySide6 is required. Install with `pip install -e .[qt]`.") from exc

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ModuleNotFoundError:  # pragma: no cover
    QWebEngineView = None

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure


DEFAULT_DB_PATH = "data/duckdb/mns.duckdb"
DEFAULT_STRATEGY_ID = "ema_cross"
DEFAULT_TIMEFRAME = "15m"
DEFAULT_STOCK_CODES = "588000.SH"
DEFAULT_START_DATE = "2025-01-01"
DEFAULT_END_DATE = "2026-06-22"


class BacktestThread(QThread):
    completed = Signal(object)
    failed = Signal(str, str)

    def __init__(self, service: QtBacktestService, request: QtBacktestRequest) -> None:
        super().__init__()
        self.service = service
        self.request = request

    def run(self) -> None:
        try:
            self.completed.emit(self.service.run_backtest(self.request))
        except Exception as exc:  # pragma: no cover
            self.failed.emit(str(exc), traceback.format_exc())


class ReviewChartPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.figure = Figure(figsize=(13, 8), dpi=100)
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas)

        self._chart_axes: list = []
        self._bar_times: list[pd.Timestamp] = []
        self._data_count = 0
        self._default_window = 0
        self._right_padding = 3.2
        self._drag_start_pixel_x: float | None = None
        self._drag_start_xlim: tuple[float, float] | None = None
        self._pending_xlim: tuple[float, float] | None = None
        self._drag_timer = QTimer(self)
        self._drag_timer.setSingleShot(True)
        self._drag_timer.setInterval(16)
        self._drag_timer.timeout.connect(self._flush_drag_frame)

        self._connect_interactions()
        self.show_message("运行回测后，这里会显示复盘图。按住左键可拖动，滚轮可缩放，双击可重置。")

    def set_result(
        self,
        *,
        result: QtBacktestResult,
        request: QtBacktestRequest | None,
        stock_code: str | None,
    ) -> None:
        request = request or QtBacktestRequest()
        params = request.params or {}
        if result.strategy_id == "ema_cross":
            fast_period = int(params.get("fast_period", 21))
            slow_period = int(params.get("slow_period", 55))
            risk_per_trade = float(params.get("risk_per_trade", 5_000.0))
        else:
            fast_period = 20
            slow_period = 50
            risk_per_trade = float(request.initial_cash) * float(params.get("risk_per_trade_pct", 0.008))

        chart_state = render_review_chart(
            self.figure,
            kline=result.kline,
            signals=result.signals,
            trades=result.trades,
            portfolio=result.portfolio_snapshots,
            stock_code=stock_code,
            run_id=result.run_id,
            strategy_id=result.strategy_id,
            timeframe=request.timeframe,
            summary=result.summary,
            initial_cash=request.initial_cash,
            fast_period=fast_period,
            slow_period=slow_period,
            risk_per_trade=risk_per_trade,
        )
        self._chart_axes = list(self.figure.axes[:3])
        self._bar_times = list(chart_state.get("bar_times", []))
        self._data_count = int(chart_state.get("data_count", 0))
        self._default_window = int(chart_state.get("default_window", 0))
        self._right_padding = float(chart_state.get("right_padding", 3.2))
        self._apply_default_view()
        self.canvas.draw_idle()

    def show_message(self, message: str) -> None:
        self.figure.clear()
        self._chart_axes = []
        self._bar_times = []
        self._data_count = 0
        self._default_window = 0
        self._drag_start_pixel_x = None
        self._drag_start_xlim = None
        self._pending_xlim = None
        self._drag_timer.stop()

        axis = self.figure.add_subplot(111)
        axis.set_xticks([])
        axis.set_yticks([])
        for spine in axis.spines.values():
            spine.set_visible(False)
        axis.set_facecolor("#f8fafc")
        axis.text(0.5, 0.5, message, ha="center", va="center", fontsize=11, color="#64748b", transform=axis.transAxes)
        self.canvas.draw_idle()

    def _connect_interactions(self) -> None:
        self.canvas.mpl_connect("button_press_event", self._on_mouse_press)
        self.canvas.mpl_connect("button_release_event", self._on_mouse_release)
        self.canvas.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.canvas.mpl_connect("scroll_event", self._on_mouse_scroll)

    def _on_mouse_press(self, event) -> None:
        if not self._chart_axes or event.inaxes not in self._chart_axes or event.button != 1:
            return
        if getattr(event, "dblclick", False):
            self._apply_default_view()
            return
        self._drag_start_pixel_x = float(event.x)
        self._drag_start_xlim = tuple(self._chart_axes[0].get_xlim())
        self._pending_xlim = None
        self._drag_timer.stop()

    def _on_mouse_release(self, event) -> None:
        if self._pending_xlim is not None:
            left, right = self._pending_xlim
            self._pending_xlim = None
            self._set_shared_xlim(left, right, refresh_ticks=True, immediate=True)
        elif self._chart_axes:
            left, right = self._chart_axes[0].get_xlim()
            self._set_shared_xlim(left, right, refresh_ticks=True, immediate=True)
        self._drag_start_pixel_x = None
        self._drag_start_xlim = None

    def _on_mouse_move(self, event) -> None:
        if self._drag_start_pixel_x is None or self._drag_start_xlim is None or not self._chart_axes:
            return
        axis = self._chart_axes[0]
        width_pixels = max(float(axis.bbox.width), 1.0)
        start_left, start_right = self._drag_start_xlim
        visible_width = start_right - start_left
        shift = ((self._drag_start_pixel_x - float(event.x)) / width_pixels) * visible_width
        left, right = self._clamp_xlim(start_left + shift, start_right + shift)
        self._pending_xlim = (left, right)
        if not self._drag_timer.isActive():
            self._drag_timer.start()

    def _on_mouse_scroll(self, event) -> None:
        if not self._chart_axes or event.inaxes not in self._chart_axes:
            return
        axis = self._chart_axes[0]
        current_left, current_right = axis.get_xlim()
        current_width = current_right - current_left
        min_width = min(max(25.0, self._default_window / 6 if self._default_window else 25.0), max(float(self._data_count), 25.0))
        max_width = max(float(self._data_count) + self._right_padding + 1.0, current_width)
        scale = 0.86 if event.button == "up" else 1.18
        target_width = min(max(current_width * scale, min_width), max_width)
        center = float(event.xdata) if event.xdata is not None else (current_left + current_right) / 2.0
        ratio = 0.5 if current_width <= 0 else (center - current_left) / current_width
        left = center - (target_width * ratio)
        right = left + target_width
        left, right = self._clamp_xlim(left, right)
        self._pending_xlim = None
        self._set_shared_xlim(left, right, refresh_ticks=True, immediate=True)

    def _apply_default_view(self) -> None:
        if not self._chart_axes or self._data_count <= 0:
            return
        if self._default_window <= 0:
            left, right = self._clamp_xlim(-1.0, float(self._data_count) + self._right_padding)
        else:
            left = max(-1.0, float(self._data_count - self._default_window - 1))
            right = float(self._data_count) + self._right_padding
        self._pending_xlim = None
        self._set_shared_xlim(left, right, refresh_ticks=True, immediate=True)

    def _set_shared_xlim(self, left: float, right: float, *, refresh_ticks: bool = True, immediate: bool = False) -> None:
        if not self._chart_axes:
            return
        for axis in self._chart_axes:
            axis.set_xlim(left, right)
        if refresh_ticks:
            self._refresh_x_ticks()
        if immediate:
            self.canvas.draw()
        else:
            self.canvas.draw_idle()

    def _flush_drag_frame(self) -> None:
        if self._pending_xlim is None:
            return
        left, right = self._pending_xlim
        self._set_shared_xlim(left, right, refresh_ticks=False, immediate=False)

    def _refresh_x_ticks(self) -> None:
        if len(self._chart_axes) < 3 or not self._bar_times or self._data_count <= 0:
            return
        axis = self._chart_axes[2]
        left, right = self._chart_axes[0].get_xlim()
        start_index = max(0, int(left))
        end_index = min(self._data_count - 1, int(right))
        if end_index <= start_index:
            return

        visible = max(end_index - start_index + 1, 1)
        target_labels = min(8, max(4, visible // 40 + 1))
        if target_labels <= 1:
            tick_positions = [start_index]
        else:
            tick_positions = [
                int(round(start_index + ((end_index - start_index) * index / (target_labels - 1))))
                for index in range(target_labels)
            ]
        tick_positions = sorted(set(position for position in tick_positions if 0 <= position < self._data_count))
        if not tick_positions:
            return

        intraday = any(timestamp.hour != 0 or timestamp.minute != 0 for timestamp in self._bar_times)
        fmt = "%m-%d\n%H:%M" if intraday else "%Y-%m-%d"
        axis.set_xticks(tick_positions)
        axis.set_xticklabels([self._bar_times[position].strftime(fmt) for position in tick_positions])

    def _clamp_xlim(self, left: float, right: float) -> tuple[float, float]:
        min_left = -1.0
        max_right = float(self._data_count) + self._right_padding
        width = right - left
        total_width = max_right - min_left
        if width >= total_width:
            return min_left, max_right
        if left < min_left:
            right += min_left - left
            left = min_left
        if right > max_right:
            left -= right - max_right
            right = max_right
        if left < min_left:
            left = min_left
        if right > max_right:
            right = max_right
        return left, right


class HtmlPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._html_root = Path(tempfile.gettempdir()) / "mns_qt_backtest_html"
        self._html_root.mkdir(parents=True, exist_ok=True)
        self._html_path: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if QWebEngineView is None:
            self.view = QTextBrowser()
            self.set_html("<p>当前环境缺少 Qt WebEngine，无法渲染交互式资金图。</p>")
        else:
            self.view = QWebEngineView()
        layout.addWidget(self.view)

    def set_html(self, html: str) -> None:
        if isinstance(self.view, QTextBrowser):
            self.view.setHtml(html)
            return
        self._html_path = self._write_html_file(html)
        self.view.setUrl(QUrl.fromLocalFile(str(self._html_path.resolve())))

    def _write_html_file(self, html: str) -> Path:
        path = self._html_root / f"{uuid4().hex}.html"
        path.write_text(html, encoding="utf-8")
        return path


class QtBacktestWindow(QMainWindow):
    def __init__(self, service: QtBacktestService | None = None) -> None:
        super().__init__()
        self.service = service or QtBacktestService()
        self.current_result: QtBacktestResult | None = None
        self.current_request: QtBacktestRequest | None = None
        self.worker: BacktestThread | None = None

        self.setWindowTitle("Moneynosleep Qt 回测工作台")
        self.resize(1480, 900)
        self._build_ui()
        self._load_strategy_options()
        self._refresh_timeframes()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_control_panel())
        splitter.addWidget(self._build_workspace())
        splitter.setSizes([360, 1120])
        root_layout.addWidget(splitter)
        self.setCentralWidget(root)

    def _build_control_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        data_box = QGroupBox("数据源")
        data_form = QFormLayout(data_box)
        db_row = QHBoxLayout()
        self.db_input = QLineEdit(DEFAULT_DB_PATH)
        browse_btn = QPushButton("浏览")
        browse_btn.clicked.connect(self._browse_db)
        db_row.addWidget(self.db_input, 1)
        db_row.addWidget(browse_btn)
        data_form.addRow("DuckDB", db_row)

        self.timeframe_combo = QComboBox()
        self.timeframe_combo.addItems(["1d", "5m", "15m", "30m", "1h"])
        data_form.addRow("周期", self.timeframe_combo)

        refresh_btn = QPushButton("刷新周期")
        refresh_btn.clicked.connect(self._refresh_timeframes)
        data_form.addRow("", refresh_btn)
        layout.addWidget(data_box)

        strategy_box = QGroupBox("策略")
        strategy_form = QFormLayout(strategy_box)
        self.strategy_combo = QComboBox()
        self.strategy_combo.currentIndexChanged.connect(self._on_strategy_changed)
        strategy_form.addRow("内置策略", self.strategy_combo)

        self.stock_codes_input = QLineEdit(DEFAULT_STOCK_CODES)
        self.stock_codes_input.setPlaceholderText("例如 000001.SZ,600000.SH；留空表示全市场")
        strategy_form.addRow("股票代码", self.stock_codes_input)

        self.start_input = QLineEdit(DEFAULT_START_DATE)
        self.end_input = QLineEdit(DEFAULT_END_DATE)
        strategy_form.addRow("开始日期", self.start_input)
        strategy_form.addRow("结束日期", self.end_input)
        layout.addWidget(strategy_box)

        cash_box = QGroupBox("资金与成本")
        cash_form = QFormLayout(cash_box)
        self.initial_cash_input = self._money_spin(1_000_000, 10_000_000_000)
        self.commission_input = self._rate_spin(0.0005)
        self.stamp_tax_input = self._rate_spin(0.001)
        self.transfer_fee_input = self._rate_spin(0.0)
        self.slippage_input = self._rate_spin(0.001)
        cash_form.addRow("初始资金", self.initial_cash_input)
        cash_form.addRow("佣金率", self.commission_input)
        cash_form.addRow("印花税率", self.stamp_tax_input)
        cash_form.addRow("过户费率", self.transfer_fee_input)
        cash_form.addRow("滑点率", self.slippage_input)
        layout.addWidget(cash_box)

        params_box = QGroupBox("策略参数")
        params_form = QFormLayout(params_box)
        self.param_a = self._rate_spin(0.02)
        self.param_b = self._rate_spin(1.2, maximum=100.0)
        self.param_c = self._rate_spin(0.008)
        params_form.addRow("参数 A", self.param_a)
        params_form.addRow("参数 B", self.param_b)
        params_form.addRow("参数 C", self.param_c)
        self.params_hint = QLabel()
        self.params_hint.setWordWrap(True)
        params_form.addRow("", self.params_hint)
        layout.addWidget(params_box)

        live_box = QGroupBox("实盘预留")
        live_layout = QVBoxLayout(live_box)
        self.live_status = QLabel("当前状态：回测验证模式，实盘下单未启用")
        self.live_status.setWordWrap(True)
        self.qmt_status = QLabel("miniQMT：后续作为独立连接通道接入")
        self.qmt_status.setWordWrap(True)
        live_layout.addWidget(self.live_status)
        live_layout.addWidget(self.qmt_status)
        layout.addWidget(live_box)

        self.run_button = QPushButton("运行回测")
        self.run_button.clicked.connect(self._run_backtest)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.run_button)
        layout.addWidget(self.progress)
        layout.addStretch(1)
        return panel

    def _build_workspace(self) -> QWidget:
        workspace = QWidget()
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)

        top = QHBoxLayout()
        self.run_id_label = QLabel("批次：")
        self.summary_label = QLabel("等待运行")
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.run_id_label)
        top.addWidget(self.summary_label, 1)
        layout.addLayout(top)

        self.tabs = QTabWidget()
        self.kline_panel = FastReviewChartPanel()
        self.portfolio_panel = HtmlPanel()
        self.trades_table = QTableWidget()
        self._configure_trade_table(self.trades_table)
        self.signals_table = QTableWidget()
        self.log_panel = QTextEdit()
        self.log_panel.setReadOnly(True)
        self.tabs.addTab(self.kline_panel, "K线与买卖点")
        self.tabs.addTab(self.portfolio_panel, "资金曲线")
        self.tabs.addTab(self.trades_table, "交易流水")
        self.tabs.addTab(self.signals_table, "信号列表")
        self.tabs.addTab(self.log_panel, "日志")
        layout.addWidget(self.tabs, 1)
        return workspace

    def _load_strategy_options(self) -> None:
        self.strategy_combo.clear()
        for spec in self.service.list_strategies():
            self.strategy_combo.addItem(spec.display_name, spec.strategy_id)
        default_index = self.strategy_combo.findData(DEFAULT_STRATEGY_ID)
        if default_index >= 0:
            self.strategy_combo.setCurrentIndex(default_index)
        else:
            self._on_strategy_changed()

    def _refresh_timeframes(self) -> None:
        current = self.timeframe_combo.currentText()
        values = self.service.list_timeframes(self.db_input.text().strip())
        if values:
            self.timeframe_combo.clear()
            self.timeframe_combo.addItems(values)
        preferred = current or DEFAULT_TIMEFRAME
        index = self.timeframe_combo.findText(preferred)
        if index < 0:
            index = self.timeframe_combo.findText(DEFAULT_TIMEFRAME)
        if index >= 0:
            self.timeframe_combo.setCurrentIndex(index)
        self._log(f"已刷新周期：{', '.join(values) if values else '使用默认周期列表'}")

    def _browse_db(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 DuckDB 数据库", str(Path.cwd()), "DuckDB (*.duckdb);;All Files (*)")
        if path:
            self.db_input.setText(path)
            self._refresh_timeframes()

    def _on_strategy_changed(self) -> None:
        strategy_id = str(self.strategy_combo.currentData())
        if strategy_id == "ema_cross":
            self._configure_param_spin(self.param_a, minimum=2, maximum=250, decimals=0, step=1)
            self._configure_param_spin(self.param_b, minimum=3, maximum=500, decimals=0, step=1)
            self._configure_param_spin(self.param_c, minimum=100, maximum=10_000_000, decimals=2, step=100)
            self.param_a.setValue(21)
            self.param_b.setValue(55)
            self.param_c.setValue(5000)
            self.params_hint.setText("参数 A=快线周期，参数 B=慢线周期，参数 C=单笔风险金额")
            self._set_timeframe_if_present("15m")
            return

        self._configure_param_spin(self.param_a, minimum=0.001, maximum=1.0, decimals=6, step=0.0001)
        self._configure_param_spin(self.param_b, minimum=0.1, maximum=100.0, decimals=6, step=0.1)
        self._configure_param_spin(self.param_c, minimum=0.001, maximum=1.0, decimals=6, step=0.0001)
        self.param_a.setValue(0.02)
        self.param_b.setValue(1.2)
        self.param_c.setValue(0.008)
        self.params_hint.setText("参数 A=EMA20/EMA50 最小乖离，参数 B=最小量比，参数 C=单笔风险比例")
        self._set_timeframe_if_present("1d")

    def _set_timeframe_if_present(self, value: str) -> None:
        index = self.timeframe_combo.findText(value)
        if index >= 0:
            self.timeframe_combo.setCurrentIndex(index)

    def _run_backtest(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        request = self._build_request()
        self.current_request = request
        self.run_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self._log(f"开始回测：{request.strategy_id} {request.start_date} -> {request.end_date}")
        self.worker = BacktestThread(self.service, request)
        self.worker.completed.connect(self._on_backtest_completed)
        self.worker.failed.connect(self._on_backtest_failed)
        self.worker.start()

    def _build_request(self) -> QtBacktestRequest:
        strategy_id = str(self.strategy_combo.currentData())
        params = self._strategy_params(strategy_id)
        return QtBacktestRequest(
            db_path=self.db_input.text().strip(),
            strategy_id=strategy_id,
            timeframe=self.timeframe_combo.currentText().strip(),
            start_date=self.start_input.text().strip() or None,
            end_date=self.end_input.text().strip() or None,
            stock_codes=self.service.parse_stock_codes(self.stock_codes_input.text()),
            initial_cash=float(self.initial_cash_input.value()),
            commission_rate=float(self.commission_input.value()),
            stamp_tax_rate=float(self.stamp_tax_input.value()),
            transfer_fee_rate=float(self.transfer_fee_input.value()),
            slippage_rate=float(self.slippage_input.value()),
            params=params,
        )

    def _strategy_params(self, strategy_id: str) -> dict[str, float | int]:
        if strategy_id == "ema_cross":
            return {
                "fast_period": int(self.param_a.value()),
                "slow_period": int(self.param_b.value()),
                "risk_per_trade": float(self.param_c.value()),
            }
        return {
            "min_bias": float(self.param_a.value()),
            "min_volume_ratio": float(self.param_b.value()),
            "risk_per_trade_pct": float(self.param_c.value()),
        }

    def _on_backtest_completed(self, result: QtBacktestResult) -> None:
        self.current_result = result
        self.run_button.setEnabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.run_id_label.setText(f"批次：{result.run_id}")
        self.summary_label.setText(self._format_summary(result.summary))

        stock_code = self._default_chart_stock(result)
        self.kline_panel.set_result(result=result, request=self.current_request, stock_code=stock_code)
        self.portfolio_panel.set_html(build_portfolio_chart_html(result.portfolio_snapshots))
        self._fill_trade_table(self.trades_table, result.trades)
        self._fill_table(self.signals_table, result.signals)
        self._log(f"完成回测：run_id={result.run_id}，信号 {len(result.signals)} 条，成交 {len(result.trades)} 笔。")

    def _on_backtest_failed(self, user_message: str, detail: str) -> None:
        self.run_button.setEnabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self._log(detail)
        QMessageBox.critical(self, "回测失败", user_message[-4000:])

    @staticmethod
    def _default_chart_stock(result: QtBacktestResult) -> str | None:
        for frame in (result.trades, result.signals, result.kline):
            if not frame.empty and "stock_code" in frame.columns:
                values = frame["stock_code"].dropna()
                if not values.empty:
                    return str(values.iloc[0])
        return None

    @staticmethod
    def _fill_table(table: QTableWidget, frame: pd.DataFrame, limit: int = 500) -> None:
        display = frame.head(limit).copy()
        table.clear()
        table.setRowCount(len(display))
        table.setColumnCount(len(display.columns))
        table.setHorizontalHeaderLabels([str(column) for column in display.columns])
        for row_index, (_, row) in enumerate(display.iterrows()):
            for col_index, value in enumerate(row.tolist()):
                item = QTableWidgetItem("" if pd.isna(value) else str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row_index, col_index, item)
        table.resizeColumnsToContents()

    def _fill_trade_table(self, table: QTableWidget, frame: pd.DataFrame, limit: int = 1000) -> None:
        display = self._build_trade_display(frame.head(limit).copy())
        table.clear()
        table.setRowCount(len(display))
        table.setColumnCount(len(display.columns))
        table.setHorizontalHeaderLabels([str(column) for column in display.columns])

        numeric_columns = {"进场价格", "止损值", "ATR值", "开仓数量", "出场价格", "手续费", "盈亏", "R倍数"}
        centered_columns = {"序号", "方向", "进场时间", "出场时间", "原因"}

        for row_index, (_, row) in enumerate(display.iterrows()):
            for col_index, (column_name, value) in enumerate(row.items()):
                item = QTableWidgetItem("" if pd.isna(value) else str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column_name in numeric_columns:
                    item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                elif column_name in centered_columns:
                    item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
                table.setItem(row_index, col_index, item)

        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.resizeColumnsToContents()
        for column_name, width in {
            "序号": 60,
            "方向": 70,
            "进场时间": 135,
            "进场价格": 110,
            "止损值": 110,
            "ATR值": 90,
            "开仓数量": 100,
            "出场时间": 135,
            "出场价格": 110,
            "手续费": 95,
            "原因": 80,
            "盈亏": 110,
            "R倍数": 90,
        }.items():
            if column_name in display.columns:
                table.setColumnWidth(display.columns.get_loc(column_name), width)

    @staticmethod
    def _configure_trade_table(table: QTableWidget) -> None:
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(False)
        table.setWordWrap(False)
        table.setCornerButtonEnabled(False)

    @staticmethod
    def _build_trade_display(frame: pd.DataFrame) -> pd.DataFrame:
        columns = ["序号", "方向", "进场时间", "进场价格", "止损值", "ATR值", "开仓数量", "出场时间", "出场价格", "手续费", "原因", "盈亏", "R倍数"]
        if frame.empty:
            return pd.DataFrame(columns=columns)

        display = pd.DataFrame(index=frame.index)
        display["序号"] = range(1, len(frame) + 1)
        display["方向"] = frame.apply(QtBacktestWindow._trade_direction, axis=1)
        display["进场时间"] = frame.apply(lambda row: QtBacktestWindow._format_trade_time(QtBacktestWindow._first_present(row, "buy_time", "entry_time")), axis=1)
        display["进场价格"] = frame.apply(lambda row: QtBacktestWindow._format_trade_number(QtBacktestWindow._first_present(row, "buy_price", "entry_price"), 4), axis=1)
        display["止损值"] = frame.apply(lambda row: QtBacktestWindow._format_trade_number(row.get("stop_loss"), 4), axis=1)
        display["ATR值"] = frame.apply(lambda row: QtBacktestWindow._format_trade_number(QtBacktestWindow._trade_atr_value(row), 4), axis=1)
        display["开仓数量"] = frame.apply(lambda row: QtBacktestWindow._format_trade_number(QtBacktestWindow._first_present(row, "quantity", "position_size"), 4), axis=1)
        display["出场时间"] = frame.apply(lambda row: QtBacktestWindow._format_trade_time(QtBacktestWindow._first_present(row, "sell_time", "exit_time")), axis=1)
        display["出场价格"] = frame.apply(lambda row: QtBacktestWindow._format_trade_number(QtBacktestWindow._first_present(row, "sell_price", "exit_price"), 4), axis=1)
        display["手续费"] = frame.apply(lambda row: QtBacktestWindow._format_trade_number(QtBacktestWindow._first_present(row, "total_cost", "commission"), 4), axis=1)
        display["原因"] = frame.apply(QtBacktestWindow._trade_reason_text, axis=1)
        display["盈亏"] = frame.apply(lambda row: QtBacktestWindow._format_trade_number(row.get("pnl"), 4), axis=1)
        display["R倍数"] = frame.apply(lambda row: QtBacktestWindow._format_trade_number(QtBacktestWindow._trade_r_value(row), 4), axis=1)
        return display[columns]

    @staticmethod
    def _first_present(row: pd.Series, *keys: str) -> object:
        for key in keys:
            value = row.get(key)
            if pd.notna(value):
                return value
        return None

    @staticmethod
    def _trade_direction(row: pd.Series) -> str:
        action = str(row.get("action", "")).upper()
        if "SHORT" in action or str(row.get("signal", "")).lower() == "short":
            return "做空"
        return "做多"

    @staticmethod
    def _trade_atr_value(row: pd.Series) -> float | None:
        for key in ("atr_14", "atr14", "entry_atr10", "risk_per_share"):
            value = pd.to_numeric(row.get(key), errors="coerce")
            if pd.notna(value):
                return float(value)
        return None

    @staticmethod
    def _trade_r_value(row: pd.Series) -> float | None:
        direct_value = pd.to_numeric(row.get("r_multiple"), errors="coerce")
        if pd.notna(direct_value):
            return float(direct_value)

        pnl = pd.to_numeric(row.get("pnl"), errors="coerce")
        quantity = pd.to_numeric(QtBacktestWindow._first_present(row, "quantity", "position_size"), errors="coerce")
        risk_per_share = pd.to_numeric(row.get("risk_per_share"), errors="coerce")
        if pd.isna(risk_per_share):
            entry_price = pd.to_numeric(QtBacktestWindow._first_present(row, "buy_price", "entry_price"), errors="coerce")
            stop_loss = pd.to_numeric(row.get("stop_loss"), errors="coerce")
            if pd.notna(entry_price) and pd.notna(stop_loss):
                risk_per_share = float(entry_price) - float(stop_loss)
        if pd.notna(pnl) and pd.notna(quantity) and pd.notna(risk_per_share) and float(quantity) != 0 and float(risk_per_share) > 0:
            return float(pnl) / (float(quantity) * float(risk_per_share))
        return None

    @staticmethod
    def _trade_reason_text(row: pd.Series) -> str:
        raw_reason = str(row.get("exit_reason") or row.get("exit_type") or row.get("reason") or "").strip()
        mapping = {
            "INITIAL_STOP": "止损",
            "ATR_STOP": "止损",
            "trend_stop": "趋势",
            "TREND_STOP": "趋势",
            "BREAKEVEN_STOP": "保本",
            "breakeven_stop": "保本",
            "END_OF_TEST": "平仓",
            "EMA_DEAD_CROSS": "死叉",
            "take_profit": "止盈",
        }
        if raw_reason in mapping:
            return mapping[raw_reason]
        if raw_reason.upper().startswith("TRAILING_STOP_"):
            return raw_reason.upper().replace("TRAILING_STOP_", "")
        if raw_reason.startswith("entry_"):
            return raw_reason.replace("entry_", "").upper()
        if raw_reason:
            return raw_reason
        return ""

    @staticmethod
    def _format_trade_time(value: object) -> str:
        timestamp = pd.to_datetime(value, errors="coerce")
        if pd.isna(timestamp):
            return ""
        return timestamp.strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _format_trade_number(value: object, decimals: int) -> str:
        numeric = pd.to_numeric(value, errors="coerce")
        if pd.isna(numeric):
            return ""
        return f"{float(numeric):.{decimals}f}"

    @staticmethod
    def _format_summary(summary: dict[str, float | int]) -> str:
        if not summary:
            return "无摘要"

        pieces: list[str] = []
        mapping = {
            "trade_count": "交易",
            "total_pnl": "盈亏",
            "win_rate": "胜率",
            "max_drawdown": "最大回撤",
            "ending_equity": "期末权益",
        }
        for key, label in mapping.items():
            if key not in summary:
                continue
            value = summary[key]
            if key in {"win_rate", "max_drawdown"}:
                pieces.append(f"{label} {float(value):.2%}")
            elif isinstance(value, float):
                pieces.append(f"{label} {value:,.2f}")
            else:
                pieces.append(f"{label} {value}")
        return " | ".join(pieces) or str(summary)

    @staticmethod
    def _money_spin(value: float, maximum: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(2)
        spin.setRange(0, maximum)
        spin.setSingleStep(10_000)
        spin.setValue(value)
        return spin

    @staticmethod
    def _rate_spin(value: float, *, maximum: float = 1.0) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(6)
        spin.setRange(0, maximum)
        spin.setSingleStep(0.0001)
        spin.setValue(value)
        return spin

    @staticmethod
    def _configure_param_spin(
        spin: QDoubleSpinBox,
        *,
        minimum: float,
        maximum: float,
        decimals: int,
        step: float,
    ) -> None:
        spin.setDecimals(decimals)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)

    def _log(self, text: str) -> None:
        self.log_panel.append(text)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Moneynosleep Qt Backtest")
    window = QtBacktestWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
