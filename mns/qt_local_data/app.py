from __future__ import annotations

import os
import subprocess
import sys
import traceback
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pandas as pd

os.environ.setdefault("QT_API", "pyside6")

try:
    from PySide6.QtCore import QDateTime, QThread, Qt, Signal
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDateTimeEdit,
        QFileDialog,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QSpinBox,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QTextBrowser,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit("PySide6 is required. Install with `pip install -e .[qt]`.") from exc

from mns.data.market_scope import MARKET_GROUP_LABELS
from mns.qt_local_data.service import (
    DEFAULT_BAOSTOCK_STATE_PATH,
    MARKET_GROUP_DISPLAY_ORDER,
    LocalDataWorkbenchService,
)


DEFAULT_DB_PATH = "data/duckdb/mns.duckdb"
DEFAULT_PARQUET_ROOT = "data/parquet"
DEFAULT_START = datetime(2020, 1, 2, 9, 30, 0)
DEFAULT_END = datetime.now().replace(hour=15, minute=0, second=0, microsecond=0)


class BaoStockSyncThread(QThread):
    line_emitted = Signal(str)
    completed = Signal(int)
    failed = Signal(str, str)

    def __init__(self, *, command: list[str], workdir: str) -> None:
        super().__init__()
        self.command = command
        self.workdir = workdir
        self._process: subprocess.Popen[str] | None = None
        self._stop_requested = False

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    def request_stop(self) -> None:
        self._stop_requested = True
        if self._process is None:
            return
        if self._process.poll() is None:
            try:
                self._process.terminate()
            except Exception:
                pass

    def run(self) -> None:
        try:
            process = subprocess.Popen(
                self.command,
                cwd=self.workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self._process = process
            assert process.stdout is not None
            for line in process.stdout:
                self.line_emitted.emit(line.rstrip())
            process.wait()
            self.completed.emit(int(process.returncode or 0))
        except Exception as exc:  # pragma: no cover
            self.failed.emit(str(exc), traceback.format_exc())
        finally:
            self._process = None


class ConvertThread(QThread):
    completed = Signal(object)
    failed = Signal(str, str)
    progress = Signal(object)

    def __init__(self, *, service: LocalDataWorkbenchService, kwargs: dict) -> None:
        super().__init__()
        self.service = service
        self.kwargs = kwargs

    def run(self) -> None:
        try:
            self.completed.emit(
                self.service.convert_local_timeframes(
                    **self.kwargs,
                    progress_callback=lambda payload: self.progress.emit(payload),
                )
            )
        except Exception as exc:  # pragma: no cover
            self.failed.emit(str(exc), traceback.format_exc())


class QMTSyncThread(QThread):
    line_emitted = Signal(str)
    progress = Signal(object)
    completed = Signal(object)
    failed = Signal(str, str)

    def __init__(self, *, service: LocalDataWorkbenchService, kwargs: dict) -> None:
        super().__init__()
        self.service = service
        self.kwargs = kwargs

    def run(self) -> None:
        try:
            self.completed.emit(
                self.service.sync_qmt_kline(
                    **self.kwargs,
                    progress_callback=lambda payload: self.progress.emit(payload),
                    log_callback=lambda line: self.line_emitted.emit(line),
                )
            )
        except Exception as exc:  # pragma: no cover
            self.failed.emit(str(exc), traceback.format_exc())


class LocalDataWorkbenchWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._sync_thread: BaoStockSyncThread | None = None
        self._convert_thread: ConvertThread | None = None
        self._qmt_sync_thread: QMTSyncThread | None = None
        self.setWindowTitle("本地数据同步与检索")
        self.resize(1540, 980)

        central = QWidget(self)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        root_layout.addWidget(self._build_workspace_group())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_query_tab(), "本地检索")
        self.tabs.addTab(self._build_sync_tab(), "同步数据")
        self.tabs.addTab(self._build_convert_tab(), "周期转换")
        self.tabs.addTab(self._build_qmt_sync_tab(), "miniQMT同步")
        root_layout.addWidget(self.tabs, stretch=1)

        self.setCentralWidget(central)
        self._refresh_local_overview()
        self._set_convert_idle_state()

    def _build_workspace_group(self) -> QWidget:
        group = QGroupBox("工作区")
        layout = QGridLayout(group)

        self.db_path_edit = QLineEdit(DEFAULT_DB_PATH)
        self.parquet_root_edit = QLineEdit(DEFAULT_PARQUET_ROOT)

        db_browse_button = QPushButton("选择 DB")
        db_browse_button.clicked.connect(self._choose_db_path)
        parquet_browse_button = QPushButton("选择目录")
        parquet_browse_button.clicked.connect(self._choose_parquet_root)

        note = QLabel("说明：同步页当前直接接入 BaoStock 断点同步工具，并发数固定为 1。")
        note.setStyleSheet("color: #475569;")

        layout.addWidget(QLabel("DuckDB"), 0, 0)
        layout.addWidget(self.db_path_edit, 0, 1)
        layout.addWidget(db_browse_button, 0, 2)
        layout.addWidget(QLabel("Parquet Root"), 1, 0)
        layout.addWidget(self.parquet_root_edit, 1, 1)
        layout.addWidget(parquet_browse_button, 1, 2)
        layout.addWidget(note, 2, 0, 1, 3)
        return group

    def _build_query_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        filters = QGroupBox("查询条件")
        form = QGridLayout(filters)

        self.query_timeframe_combo = QComboBox()
        self.query_timeframe_combo.addItems(["", "1m", "5m", "15m", "30m", "1h", "1d"])
        self.query_timeframe_combo.setCurrentText("15m")
        self.query_stock_codes_edit = QLineEdit()
        self.query_stock_codes_edit.setPlaceholderText("多个代码用逗号分隔，例如 600000.SH,000001.SZ")
        self.query_start_edit = self._make_datetime_edit(DEFAULT_START)
        self.query_end_edit = self._make_datetime_edit(DEFAULT_END)
        self.query_summary_limit_spin = self._make_spin(500, 1, 10000)
        self.query_bar_limit_spin = self._make_spin(300, 1, 10000)
        self.query_market_checkboxes = self._build_market_group_checkboxes(default_checked=["all_a"])

        refresh_overview_button = QPushButton("刷新概览")
        refresh_overview_button.clicked.connect(self._refresh_local_overview)
        summary_button = QPushButton("查询汇总")
        summary_button.clicked.connect(self._run_summary_query)
        bars_button = QPushButton("查询明细")
        bars_button.clicked.connect(self._run_bar_query)

        form.addWidget(QLabel("周期"), 0, 0)
        form.addWidget(self.query_timeframe_combo, 0, 1)
        form.addWidget(QLabel("股票代码"), 0, 2)
        form.addWidget(self.query_stock_codes_edit, 0, 3)
        form.addWidget(QLabel("开始时间"), 1, 0)
        form.addWidget(self.query_start_edit, 1, 1)
        form.addWidget(QLabel("结束时间"), 1, 2)
        form.addWidget(self.query_end_edit, 1, 3)
        form.addWidget(QLabel("汇总行数"), 2, 0)
        form.addWidget(self.query_summary_limit_spin, 2, 1)
        form.addWidget(QLabel("明细行数"), 2, 2)
        form.addWidget(self.query_bar_limit_spin, 2, 3)
        form.addWidget(QLabel("市场范围"), 3, 0, alignment=Qt.AlignTop)
        form.addWidget(self.query_market_checkboxes, 3, 1, 1, 3)

        button_row = QHBoxLayout()
        button_row.addWidget(refresh_overview_button)
        button_row.addWidget(summary_button)
        button_row.addWidget(bars_button)
        button_row.addStretch(1)
        form.addLayout(button_row, 4, 0, 1, 4)

        self.local_overview_browser = QTextBrowser()
        self.local_overview_browser.setMinimumHeight(110)

        self.summary_table = QTableWidget()
        self.summary_table.setAlternatingRowColors(True)
        self.summary_table.setSortingEnabled(False)

        self.bars_table = QTableWidget()
        self.bars_table.setAlternatingRowColors(True)
        self.bars_table.setSortingEnabled(False)

        layout.addWidget(filters)
        layout.addWidget(QLabel("本地概览"))
        layout.addWidget(self.local_overview_browser)
        layout.addWidget(QLabel("本地汇总"))
        layout.addWidget(self.summary_table, stretch=1)
        layout.addWidget(QLabel("K线明细"))
        layout.addWidget(self.bars_table, stretch=1)
        return widget

    def _build_sync_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        controls = QGroupBox("BaoStock 同步参数")
        grid = QGridLayout(controls)

        self.sync_all_checkbox = QCheckBox("同步全部股票")
        self.sync_stock_codes_edit = QLineEdit()
        self.sync_stock_codes_edit.setPlaceholderText("为空时可配合市场组使用；多个代码用逗号分隔")
        self.sync_market_checkboxes = self._build_market_group_checkboxes(default_checked=["all_a"])
        self.sync_start_edit = self._make_datetime_edit(DEFAULT_START)
        self.sync_end_edit = self._make_datetime_edit(DEFAULT_END)
        self.sync_fetch_timeframe_checks = self._build_timeframe_checkboxes(
            ["5m", "15m", "30m", "1h", "1d"],
            default_checked=["5m", "1d"],
        )
        self.sync_derive_source_combo = QComboBox()
        self.sync_derive_source_combo.addItems(["5m", "15m", "30m", "1h"])
        self.sync_derive_source_combo.setCurrentText("5m")
        self.sync_derive_target_checks = self._build_timeframe_checkboxes(
            ["15m", "30m", "1h", "1d"],
            default_checked=["15m", "30m", "1h"],
        )
        self.sync_adjust_combo = QComboBox()
        self.sync_adjust_combo.addItem("前复权 (2)", "2")
        self.sync_adjust_combo.addItem("后复权 (1)", "1")
        self.sync_adjust_combo.addItem("不复权 (3)", "3")
        self.sync_adjust_combo.setCurrentIndex(0)
        self.sync_retry_spin = self._make_spin(2, 0, 20)
        self.sync_state_path_edit = QLineEdit(DEFAULT_BAOSTOCK_STATE_PATH)
        self.sync_reset_state_checkbox = QCheckBox("重置状态文件后重跑")
        self.sync_allow_quality_checkbox = QCheckBox("允许质量检查问题继续写入")
        self.sync_user_edit = QLineEdit()
        self.sync_password_edit = QLineEdit()
        self.sync_password_edit.setEchoMode(QLineEdit.Password)

        state_browse_button = QPushButton("选择状态文件")
        state_browse_button.clicked.connect(self._choose_state_path)
        command_button = QPushButton("生成命令")
        command_button.clicked.connect(self._preview_sync_command)
        self.sync_start_button = QPushButton("开始同步")
        self.sync_start_button.clicked.connect(self._start_baostock_sync)
        self.sync_pause_button = QPushButton("暂停同步")
        self.sync_pause_button.setEnabled(False)
        self.sync_pause_button.clicked.connect(self._pause_baostock_sync)
        state_summary_button = QPushButton("查看状态摘要")
        state_summary_button.clicked.connect(self._refresh_state_summary)

        grid.addWidget(self.sync_all_checkbox, 0, 0, 1, 2)
        grid.addWidget(QLabel("股票代码"), 1, 0)
        grid.addWidget(self.sync_stock_codes_edit, 1, 1, 1, 3)
        grid.addWidget(QLabel("市场范围"), 2, 0, alignment=Qt.AlignTop)
        grid.addWidget(self.sync_market_checkboxes, 2, 1, 1, 3)
        grid.addWidget(QLabel("开始时间"), 3, 0)
        grid.addWidget(self.sync_start_edit, 3, 1)
        grid.addWidget(QLabel("结束时间"), 3, 2)
        grid.addWidget(self.sync_end_edit, 3, 3)
        grid.addWidget(QLabel("抓取周期"), 4, 0, alignment=Qt.AlignTop)
        grid.addWidget(self.sync_fetch_timeframe_checks, 4, 1)
        grid.addWidget(QLabel("派生源周期"), 4, 2)
        grid.addWidget(self.sync_derive_source_combo, 4, 3)
        grid.addWidget(QLabel("派生目标周期"), 5, 0, alignment=Qt.AlignTop)
        grid.addWidget(self.sync_derive_target_checks, 5, 1)
        grid.addWidget(QLabel("复权方式"), 5, 2)
        grid.addWidget(self.sync_adjust_combo, 5, 3)
        grid.addWidget(QLabel("重试次数"), 6, 0)
        grid.addWidget(self.sync_retry_spin, 6, 1)
        grid.addWidget(self.sync_reset_state_checkbox, 6, 2, 1, 2)
        grid.addWidget(QLabel("BaoStock 账号"), 7, 0)
        grid.addWidget(self.sync_user_edit, 7, 1)
        grid.addWidget(QLabel("BaoStock 密码"), 7, 2)
        grid.addWidget(self.sync_password_edit, 7, 3)
        grid.addWidget(QLabel("状态文件"), 8, 0)
        grid.addWidget(self.sync_state_path_edit, 8, 1, 1, 2)
        grid.addWidget(state_browse_button, 8, 3)
        grid.addWidget(self.sync_allow_quality_checkbox, 9, 0, 1, 2)

        button_row = QHBoxLayout()
        button_row.addWidget(command_button)
        button_row.addWidget(self.sync_start_button)
        button_row.addWidget(self.sync_pause_button)
        button_row.addWidget(state_summary_button)
        button_row.addStretch(1)
        grid.addLayout(button_row, 10, 0, 1, 4)

        self.sync_progress = QProgressBar()
        self.sync_progress.setRange(0, 1)
        self.sync_progress.setValue(0)

        self.sync_command_preview = QPlainTextEdit()
        self.sync_command_preview.setReadOnly(True)
        self.sync_command_preview.setPlaceholderText("这里会显示本次实际执行的命令。")
        self.sync_command_preview.setMaximumHeight(90)

        self.sync_log_edit = QPlainTextEdit()
        self.sync_log_edit.setReadOnly(True)

        self.sync_state_summary = QPlainTextEdit()
        self.sync_state_summary.setReadOnly(True)
        self.sync_state_summary.setMaximumHeight(180)

        layout.addWidget(controls)
        layout.addWidget(self.sync_progress)
        layout.addWidget(QLabel("执行命令"))
        layout.addWidget(self.sync_command_preview)
        layout.addWidget(QLabel("同步日志"))
        layout.addWidget(self.sync_log_edit, stretch=1)
        layout.addWidget(QLabel("状态摘要"))
        layout.addWidget(self.sync_state_summary)
        return widget

    def _build_qmt_sync_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        controls = QGroupBox("miniQMT 同步")
        grid = QGridLayout(controls)

        self.qmt_sync_all_checkbox = QCheckBox("同步全A股")
        self.qmt_sync_all_checkbox.setChecked(True)
        self.qmt_sync_all_checkbox.toggled.connect(self._toggle_qmt_stock_codes)
        self.qmt_include_etf_checkbox = QCheckBox("包含 ETF")
        self.qmt_include_etf_checkbox.setChecked(True)
        self.qmt_stock_codes_edit = QLineEdit()
        self.qmt_stock_codes_edit.setPlaceholderText("开启全量同步时可留空；多个代码用逗号分隔")
        self.qmt_stock_codes_edit.setEnabled(False)
        self.qmt_start_edit = self._make_datetime_edit(DEFAULT_START)
        self.qmt_end_edit = self._make_datetime_edit(DEFAULT_END)
        self.qmt_timeframe_checks = self._build_timeframe_checkboxes(
            ["1m", "5m", "15m", "30m", "1h", "1d"],
            default_checked=["5m", "15m", "30m", "1h", "1d"],
        )
        self.qmt_dividend_combo = QComboBox()
        self.qmt_dividend_combo.addItem("前复权", "front")
        self.qmt_dividend_combo.addItem("后复权", "back")
        self.qmt_dividend_combo.addItem("不复权", "none")
        self.qmt_resume_checkbox = QCheckBox("从本地最新数据续传")
        self.qmt_resume_checkbox.setChecked(True)
        self.qmt_allow_quality_checkbox = QCheckBox("允许质量问题继续写入")
        self.qmt_ip_edit = QLineEdit()
        self.qmt_ip_edit.setPlaceholderText("可选：miniQMT IP")
        self.qmt_port_spin = self._make_spin(58610, 0, 65535)
        self.qmt_port_spin.setSpecialValueText("Auto")
        self.qmt_port_spin.setValue(0)

        self.qmt_test_button = QPushButton("测试连接")
        self.qmt_test_button.clicked.connect(self._test_qmt_connection)
        self.qmt_start_button = QPushButton("开始同步")
        self.qmt_start_button.clicked.connect(self._start_qmt_sync)

        grid.addWidget(self.qmt_sync_all_checkbox, 0, 0, 1, 2)
        grid.addWidget(self.qmt_include_etf_checkbox, 0, 2, 1, 2)
        grid.addWidget(QLabel("股票代码"), 1, 0)
        grid.addWidget(self.qmt_stock_codes_edit, 1, 1, 1, 3)
        grid.addWidget(QLabel("开始时间"), 2, 0)
        grid.addWidget(self.qmt_start_edit, 2, 1)
        grid.addWidget(QLabel("结束时间"), 2, 2)
        grid.addWidget(self.qmt_end_edit, 2, 3)
        grid.addWidget(QLabel("同步周期"), 3, 0, alignment=Qt.AlignTop)
        grid.addWidget(self.qmt_timeframe_checks, 3, 1, 1, 3)
        grid.addWidget(QLabel("复权方式"), 4, 0)
        grid.addWidget(self.qmt_dividend_combo, 4, 1)
        grid.addWidget(QLabel("miniQMT IP"), 4, 2)
        grid.addWidget(self.qmt_ip_edit, 4, 3)
        grid.addWidget(QLabel("端口"), 5, 0)
        grid.addWidget(self.qmt_port_spin, 5, 1)
        grid.addWidget(self.qmt_resume_checkbox, 5, 2)
        grid.addWidget(self.qmt_allow_quality_checkbox, 5, 3)

        button_row = QHBoxLayout()
        button_row.addWidget(self.qmt_test_button)
        button_row.addWidget(self.qmt_start_button)
        button_row.addStretch(1)
        grid.addLayout(button_row, 6, 0, 1, 4)

        self.qmt_progress = QProgressBar()
        self.qmt_progress.setRange(0, 1)
        self.qmt_progress.setValue(0)
        self.qmt_progress.setFormat("空闲")

        self.qmt_connection_browser = QTextBrowser()
        self.qmt_connection_browser.setMinimumHeight(90)
        self.qmt_log_edit = QPlainTextEdit()
        self.qmt_log_edit.setReadOnly(True)

        layout.addWidget(controls)
        layout.addWidget(self.qmt_progress)
        layout.addWidget(QLabel("连接信息"))
        layout.addWidget(self.qmt_connection_browser)
        layout.addWidget(QLabel("miniQMT 同步日志"))
        layout.addWidget(self.qmt_log_edit, stretch=1)
        return widget

    def _build_convert_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        controls = QGroupBox("本地周期转换")
        grid = QGridLayout(controls)

        self.convert_source_combo = QComboBox()
        self.convert_source_combo.addItems(["1m", "5m", "15m", "30m", "1h"])
        self.convert_source_combo.setCurrentText("5m")
        self.convert_target_checks = self._build_timeframe_checkboxes(
            ["15m", "30m", "1h", "1d"],
            default_checked=["15m", "30m", "1h"],
        )
        self.convert_stock_codes_edit = QLineEdit()
        self.convert_stock_codes_edit.setPlaceholderText("为空时按市场范围筛本地已有数据")
        self.convert_market_checkboxes = self._build_market_group_checkboxes(default_checked=["all_a"])
        self.convert_start_edit = self._make_datetime_edit(DEFAULT_START)
        self.convert_end_edit = self._make_datetime_edit(DEFAULT_END)
        self.convert_start_button = QPushButton("开始转换")
        self.convert_start_button.clicked.connect(self._start_local_conversion)

        grid.addWidget(QLabel("源周期"), 0, 0)
        grid.addWidget(self.convert_source_combo, 0, 1)
        grid.addWidget(QLabel("目标周期"), 0, 2, alignment=Qt.AlignTop)
        grid.addWidget(self.convert_target_checks, 0, 3)
        grid.addWidget(QLabel("股票代码"), 1, 0)
        grid.addWidget(self.convert_stock_codes_edit, 1, 1, 1, 3)
        grid.addWidget(QLabel("市场范围"), 2, 0, alignment=Qt.AlignTop)
        grid.addWidget(self.convert_market_checkboxes, 2, 1, 1, 3)
        grid.addWidget(QLabel("开始时间"), 3, 0)
        grid.addWidget(self.convert_start_edit, 3, 1)
        grid.addWidget(QLabel("结束时间"), 3, 2)
        grid.addWidget(self.convert_end_edit, 3, 3)
        grid.addWidget(self.convert_start_button, 4, 0, 1, 2)

        self.convert_progress = QProgressBar()
        self.convert_progress.setRange(0, 1)
        self.convert_progress.setValue(0)
        self.convert_progress.setTextVisible(True)
        self.convert_progress.setFormat("空闲")

        self.convert_status_label = QLabel("状态：空闲")
        self.convert_status_label.setStyleSheet("color: #475569;")

        self.convert_summary_browser = QTextBrowser()
        self.convert_summary_browser.setMinimumHeight(100)
        self.convert_table = QTableWidget()
        self.convert_table.setAlternatingRowColors(True)
        self.convert_table.setSortingEnabled(False)

        layout.addWidget(controls)
        layout.addWidget(self.convert_status_label)
        layout.addWidget(self.convert_progress)
        layout.addWidget(QLabel("转换摘要"))
        layout.addWidget(self.convert_summary_browser)
        layout.addWidget(QLabel("转换结果"))
        layout.addWidget(self.convert_table, stretch=1)
        return widget

    def _service(self) -> LocalDataWorkbenchService:
        return LocalDataWorkbenchService(
            db_path=self.db_path_edit.text().strip() or DEFAULT_DB_PATH,
            parquet_root=self.parquet_root_edit.text().strip() or DEFAULT_PARQUET_ROOT,
            workspace_root=Path.cwd(),
        )

    def _choose_db_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "选择 DuckDB 文件", self.db_path_edit.text().strip() or DEFAULT_DB_PATH, "DuckDB (*.duckdb);;All Files (*)")
        if path:
            self.db_path_edit.setText(path)

    def _choose_parquet_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择 Parquet 目录", self.parquet_root_edit.text().strip() or DEFAULT_PARQUET_ROOT)
        if path:
            self.parquet_root_edit.setText(path)

    def _choose_state_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "选择状态文件", self.sync_state_path_edit.text().strip() or DEFAULT_BAOSTOCK_STATE_PATH, "JSON (*.json);;All Files (*)")
        if path:
            self.sync_state_path_edit.setText(path)

    def _refresh_local_overview(self) -> None:
        try:
            rows = self._service().query_local_overview()
        except Exception as exc:
            self.local_overview_browser.setPlainText(str(exc))
            return
        if not rows:
            self.local_overview_browser.setPlainText("本地库里还没有 K 线数据。")
            return
        lines = [
            f"{row.timeframe}: 股票 {row.stock_count} 只, K线 {row.bar_count} 条, {row.first_trade_date or '-'} -> {row.latest_trade_date or '-'}"
            for row in rows
        ]
        self.local_overview_browser.setPlainText("\n".join(lines))

    def _run_summary_query(self) -> None:
        try:
            rows = self._service().query_local_summary(
                timeframe=self.query_timeframe_combo.currentText().strip(),
                stock_codes_text=self.query_stock_codes_edit.text().strip(),
                market_groups=self._checked_market_groups(self.query_market_checkboxes),
                start_time=self._datetime_value(self.query_start_edit),
                end_time=self._datetime_value(self.query_end_edit),
                limit=self.query_summary_limit_spin.value(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "查询失败", str(exc))
            return
        self._populate_table(self.summary_table, [asdict(row) for row in rows])

    def _run_bar_query(self) -> None:
        timeframe = self.query_timeframe_combo.currentText().strip()
        if not timeframe:
            QMessageBox.information(self, "请选择周期", "明细查询需要先选择周期。")
            return
        try:
            frame = self._service().query_local_bars(
                timeframe=timeframe,
                stock_codes_text=self.query_stock_codes_edit.text().strip(),
                market_groups=self._checked_market_groups(self.query_market_checkboxes),
                start_time=self._datetime_value(self.query_start_edit),
                end_time=self._datetime_value(self.query_end_edit),
                limit=self.query_bar_limit_spin.value(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "查询失败", str(exc))
            return
        self._populate_table(self.bars_table, self._frame_to_rows(frame))

    def _preview_sync_command(self) -> None:
        try:
            command = self._build_sync_command()
        except Exception as exc:
            QMessageBox.critical(self, "参数错误", str(exc))
            return
        self.sync_command_preview.setPlainText(subprocess.list2cmdline(command))

    def _start_baostock_sync(self) -> None:
        if self._sync_thread is not None and self._sync_thread.isRunning():
            QMessageBox.information(self, "正在同步", "当前同步任务还没结束。")
            return
        try:
            sync_kwargs = self._collect_sync_kwargs()
            if not self._ensure_sync_state_ready(sync_kwargs):
                return
            command = self._service().build_baostock_bulk_sync_command(**sync_kwargs)
        except Exception as exc:
            QMessageBox.critical(self, "参数错误", str(exc))
            return

        self.sync_command_preview.setPlainText(subprocess.list2cmdline(command))
        self.sync_log_edit.clear()
        self.sync_progress.setRange(0, 0)
        self.sync_start_button.setEnabled(False)
        self.sync_pause_button.setEnabled(True)
        self.sync_state_summary.clear()

        self._sync_thread = BaoStockSyncThread(command=command, workdir=str(Path.cwd()))
        self._sync_thread.line_emitted.connect(self._append_sync_log)
        self._sync_thread.completed.connect(self._handle_sync_completed)
        self._sync_thread.failed.connect(self._handle_sync_failed)
        self._sync_thread.start()

    def _pause_baostock_sync(self) -> None:
        if self._sync_thread is None or not self._sync_thread.isRunning():
            QMessageBox.information(self, "暂停同步", "当前没有正在运行的同步任务。")
            return

        answer = QMessageBox.question(
            self,
            "暂停同步",
            "暂停会停止当前同步进程。\n下次点击“开始同步”时，会使用同一个状态文件继续。\n\n确定暂停吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return

        self.sync_pause_button.setEnabled(False)
        self._append_sync_log("已请求暂停同步。当前子进程结束后，可再次点击开始同步继续。")
        self._sync_thread.request_stop()

    def _handle_sync_completed(self, exit_code: int) -> None:
        was_paused = bool(self._sync_thread.stop_requested) if self._sync_thread is not None else False
        self.sync_progress.setRange(0, 1)
        self.sync_progress.setValue(1 if exit_code == 0 and not was_paused else 0)
        self.sync_start_button.setEnabled(True)
        self.sync_pause_button.setEnabled(False)
        if was_paused:
            self._append_sync_log("同步已暂停。再次点击开始同步，可使用同一状态文件继续。")
        else:
            self._append_sync_log(f"同步任务结束，退出码：{exit_code}")
        self._refresh_state_summary()
        if exit_code != 0 and not was_paused:
            QMessageBox.warning(self, "同步失败", f"BaoStock 同步退出码为 {exit_code}。")
        self._sync_thread = None

    def _handle_sync_failed(self, message: str, detail: str) -> None:
        self.sync_progress.setRange(0, 1)
        self.sync_progress.setValue(0)
        self.sync_start_button.setEnabled(True)
        self.sync_pause_button.setEnabled(False)
        self.sync_log_edit.appendPlainText(detail)
        QMessageBox.critical(self, "同步失败", message)
        self._sync_thread = None

    def _append_sync_log(self, line: str) -> None:
        if line:
            self.sync_log_edit.appendPlainText(line)

    def _refresh_state_summary(self) -> None:
        try:
            summary = self._service().summarize_baostock_state(self.sync_state_path_edit.text().strip() or DEFAULT_BAOSTOCK_STATE_PATH)
        except Exception as exc:
            summary = str(exc)
        self.sync_state_summary.setPlainText(summary)

    def _collect_sync_kwargs(self) -> dict:
        return {
            "start_time": self._datetime_value(self.sync_start_edit),
            "end_time": self._datetime_value(self.sync_end_edit),
            "fetch_timeframes": self._checked_timeframes(self.sync_fetch_timeframe_checks),
            "derive_source_timeframe": self.sync_derive_source_combo.currentText().strip(),
            "derive_timeframes": self._checked_timeframes(self.sync_derive_target_checks),
            "stock_codes_text": self.sync_stock_codes_edit.text().strip(),
            "market_groups": self._checked_market_groups(self.sync_market_checkboxes),
            "sync_all": self.sync_all_checkbox.isChecked(),
            "adjustflag": str(self.sync_adjust_combo.currentData()),
            "max_retries": self.sync_retry_spin.value(),
            "state_path": self.sync_state_path_edit.text().strip() or DEFAULT_BAOSTOCK_STATE_PATH,
            "user_id": self.sync_user_edit.text().strip(),
            "password": self.sync_password_edit.text(),
            "reset_state": self.sync_reset_state_checkbox.isChecked(),
            "allow_quality_issues": self.sync_allow_quality_checkbox.isChecked(),
        }

    def _ensure_sync_state_ready(self, sync_kwargs: dict) -> bool:
        if bool(sync_kwargs.get("reset_state")):
            return True

        service = self._service()
        run_config = service.build_baostock_bulk_sync_run_config(
            start_time=sync_kwargs["start_time"],
            end_time=sync_kwargs["end_time"],
            fetch_timeframes=sync_kwargs["fetch_timeframes"],
            derive_source_timeframe=sync_kwargs["derive_source_timeframe"],
            derive_timeframes=sync_kwargs["derive_timeframes"],
            stock_codes_text=sync_kwargs["stock_codes_text"],
            market_groups=sync_kwargs["market_groups"],
            sync_all=sync_kwargs["sync_all"],
            adjustflag=sync_kwargs["adjustflag"],
            max_retries=sync_kwargs["max_retries"],
            user_id=sync_kwargs["user_id"],
            password=sync_kwargs["password"],
        )
        inspection = service.inspect_baostock_state_file(
            state_path=sync_kwargs["state_path"],
            run_config=run_config,
        )
        if not inspection["exists"] or inspection["matches"]:
            return True

        message_box = QMessageBox(self)
        message_box.setIcon(QMessageBox.Warning)
        message_box.setWindowTitle("状态文件不匹配")
        message_box.setText("当前状态文件属于另一组同步任务，不能直接续跑。")
        message_box.setInformativeText(str(inspection["message"]))
        reset_button = message_box.addButton("重置并继续", QMessageBox.AcceptRole)
        new_file_button = message_box.addButton("新建状态文件", QMessageBox.ActionRole)
        cancel_button = message_box.addButton("取消", QMessageBox.RejectRole)
        message_box.setDefaultButton(reset_button)
        message_box.exec()

        clicked = message_box.clickedButton()
        if clicked == reset_button:
            self.sync_reset_state_checkbox.setChecked(True)
            sync_kwargs["reset_state"] = True
            return True
        if clicked == new_file_button:
            new_path = service.suggest_baostock_state_path(
                state_path=sync_kwargs["state_path"],
                run_config=run_config,
            )
            self.sync_state_path_edit.setText(new_path)
            sync_kwargs["state_path"] = new_path
            self._refresh_state_summary()
            return True
        if clicked == cancel_button:
            return False
        return False

    def _ensure_sync_state_ready(self, sync_kwargs: dict) -> bool:
        if bool(sync_kwargs.get("reset_state")):
            return True

        service = self._service()
        run_config = service.build_baostock_bulk_sync_run_config(
            start_time=sync_kwargs["start_time"],
            end_time=sync_kwargs["end_time"],
            fetch_timeframes=sync_kwargs["fetch_timeframes"],
            derive_source_timeframe=sync_kwargs["derive_source_timeframe"],
            derive_timeframes=sync_kwargs["derive_timeframes"],
            stock_codes_text=sync_kwargs["stock_codes_text"],
            market_groups=sync_kwargs["market_groups"],
            sync_all=sync_kwargs["sync_all"],
            adjustflag=sync_kwargs["adjustflag"],
            max_retries=sync_kwargs["max_retries"],
            user_id=sync_kwargs["user_id"],
            password=sync_kwargs["password"],
        )
        inspection = service.inspect_baostock_state_file(
            state_path=sync_kwargs["state_path"],
            run_config=run_config,
        )
        if not inspection["exists"] or inspection["matches"]:
            return True

        self._append_sync_log("状态文件与当前任务配置不完全一致。启动时会先检查本地 DuckDB 数据覆盖，并从未完成的股票继续同步。")
        self._append_sync_log(str(inspection["message"]))
        return True

    def _build_sync_command(self) -> list[str]:
        return self._service().build_baostock_bulk_sync_command(**self._collect_sync_kwargs())

    def _toggle_qmt_stock_codes(self, checked: bool) -> None:
        self.qmt_stock_codes_edit.setEnabled(not checked)
        if checked:
            self.qmt_stock_codes_edit.clear()

    def _collect_qmt_sync_kwargs(self) -> dict:
        port_value = self.qmt_port_spin.value()
        return {
            "stock_codes_text": self.qmt_stock_codes_edit.text().strip(),
            "sync_all": self.qmt_sync_all_checkbox.isChecked(),
            "include_etf": self.qmt_include_etf_checkbox.isChecked(),
            "start_time": self._datetime_value(self.qmt_start_edit),
            "end_time": self._datetime_value(self.qmt_end_edit),
            "timeframes": self._checked_timeframes(self.qmt_timeframe_checks),
            "dividend_type": str(self.qmt_dividend_combo.currentData()),
            "ip": self.qmt_ip_edit.text().strip(),
            "port": None if port_value <= 0 else int(port_value),
            "allow_quality_issues": self.qmt_allow_quality_checkbox.isChecked(),
            "resume_from_latest_local": self.qmt_resume_checkbox.isChecked(),
        }

    def _test_qmt_connection(self) -> None:
        try:
            kwargs = self._collect_qmt_sync_kwargs()
            info = self._service().get_qmt_connection_info(
                ip=kwargs["ip"],
                port=kwargs["port"],
                dividend_type=kwargs["dividend_type"],
            )
        except Exception as exc:
            self.qmt_connection_browser.setPlainText(str(exc))
            QMessageBox.critical(self, "miniQMT 连接失败", str(exc))
            return

        lines = ["miniQMT 连接成功"]
        for key, value in info.items():
            lines.append(f"{key}: {value}")
        self.qmt_connection_browser.setPlainText("\n".join(lines))

    def _start_qmt_sync(self) -> None:
        if self._qmt_sync_thread is not None and self._qmt_sync_thread.isRunning():
            QMessageBox.information(self, "miniQMT 同步", "miniQMT 同步任务仍在运行中。")
            return
        try:
            kwargs = self._collect_qmt_sync_kwargs()
            if not kwargs["sync_all"] and not kwargs["stock_codes_text"]:
                raise ValueError("请输入股票代码，或勾选同步全A股。")
            if not kwargs["timeframes"]:
                raise ValueError("请至少选择一个同步周期。")
        except Exception as exc:
            QMessageBox.critical(self, "miniQMT 同步参数错误", str(exc))
            return

        self.qmt_log_edit.clear()
        self.qmt_progress.setRange(0, 0)
        self.qmt_progress.setFormat("准备中")
        self.qmt_start_button.setEnabled(False)
        self.qmt_test_button.setEnabled(False)
        self._qmt_sync_thread = QMTSyncThread(service=self._service(), kwargs=kwargs)
        self._qmt_sync_thread.line_emitted.connect(self._append_qmt_log)
        self._qmt_sync_thread.progress.connect(self._handle_qmt_progress)
        self._qmt_sync_thread.completed.connect(self._handle_qmt_completed)
        self._qmt_sync_thread.failed.connect(self._handle_qmt_failed)
        self._qmt_sync_thread.start()

    def _handle_qmt_progress(self, payload: object) -> None:
        current = int(getattr(payload, "current", 0) or 0)
        total = int(getattr(payload, "total", 0) or 0)
        status = str(getattr(payload, "status", "") or "")
        stock_code = str(getattr(payload, "stock_code", "") or "")
        message = str(getattr(payload, "message", "") or "")
        if total > 0:
            self.qmt_progress.setRange(0, total)
            self.qmt_progress.setValue(min(current, total))
            self.qmt_progress.setFormat(f"{status} {min(current, total)}/{total}")
        if message and stock_code:
            self.qmt_connection_browser.setPlainText(f"{stock_code}\n{message}")

    def _handle_qmt_completed(self, payload: object) -> None:
        results_by_timeframe, stock_codes = payload
        self.qmt_progress.setRange(0, 1)
        self.qmt_progress.setValue(1)
        self.qmt_progress.setFormat("已完成")
        self.qmt_start_button.setEnabled(True)
        self.qmt_test_button.setEnabled(True)
        total_rows = sum(result.rows_written for result in results_by_timeframe.values())
        total_parquet = sum(len(result.parquet_files) for result in results_by_timeframe.values())
        total_failed = sum(len(result.failed_stock_codes) for result in results_by_timeframe.values())
        total_empty = sum(len(result.empty_stock_codes) for result in results_by_timeframe.values())
        total_skipped = sum(len(result.skipped_stock_codes) for result in results_by_timeframe.values())
        self.qmt_connection_browser.setPlainText(
            "\n".join(
                [
                    "miniQMT 同步完成",
                    f"同步周期: {', '.join(results_by_timeframe.keys())}",
                    f"股票数量: {len(stock_codes)}",
                    f"写入行数: {total_rows}",
                    f"Parquet 文件: {total_parquet}",
                    f"失败数量: {total_failed}",
                    f"空结果数量: {total_empty}",
                    f"跳过数量: {total_skipped}",
                ]
            )
        )
        self._qmt_sync_thread = None

    def _handle_qmt_failed(self, message: str, detail: str) -> None:
        self.qmt_progress.setRange(0, 1)
        self.qmt_progress.setValue(0)
        self.qmt_progress.setFormat("失败")
        self.qmt_start_button.setEnabled(True)
        self.qmt_test_button.setEnabled(True)
        self.qmt_log_edit.appendPlainText(detail)
        QMessageBox.critical(self, "miniQMT 同步失败", message)
        self._qmt_sync_thread = None

    def _append_qmt_log(self, line: str) -> None:
        if line:
            self.qmt_log_edit.appendPlainText(line)

    def closeEvent(self, event) -> None:
        if self._sync_thread is not None and self._sync_thread.isRunning():
            answer = QMessageBox.question(
                self,
                "关闭窗口",
                "当前正在同步数据。关闭窗口会先暂停同步，下次可继续。\n\n确定要关闭吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self._append_sync_log("正在关闭窗口，已请求暂停同步。")
            self._sync_thread.request_stop()
            self._sync_thread.wait(5000)
        super().closeEvent(event)

    def _start_local_conversion(self) -> None:
        if self._convert_thread is not None and self._convert_thread.isRunning():
            QMessageBox.information(self, "正在转换", "当前转换任务还没结束。")
            return
        kwargs = {
            "source_timeframe": self.convert_source_combo.currentText().strip(),
            "target_timeframes": self._checked_timeframes(self.convert_target_checks),
            "stock_codes_text": self.convert_stock_codes_edit.text().strip(),
            "market_groups": self._checked_market_groups(self.convert_market_checkboxes),
            "start_time": self._datetime_value(self.convert_start_edit),
            "end_time": self._datetime_value(self.convert_end_edit),
        }

        self.convert_progress.setRange(0, 0)
        self.convert_progress.setFormat("准备中...")
        self.convert_start_button.setEnabled(False)
        self.convert_summary_browser.setPlainText("准备开始本地周期转换，正在统计股票范围与目标周期。")
        self._populate_table(self.convert_table, [])
        self._set_convert_status("转换中", "#0f766e")
        self._convert_thread = ConvertThread(service=self._service(), kwargs=kwargs)
        self._convert_thread.progress.connect(self._handle_convert_progress)
        self._convert_thread.completed.connect(self._handle_convert_completed)
        self._convert_thread.failed.connect(self._handle_convert_failed)
        self._convert_thread.start()

    def _handle_convert_progress(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return

        stage = str(payload.get("stage") or "")
        total_steps = max(0, int(payload.get("total_steps") or 0))
        current_step = max(0, int(payload.get("current_step") or 0))

        if stage == "start":
            source = str(payload.get("source_timeframe") or "-")
            targets = [str(item) for item in payload.get("target_timeframes", [])]
            stock_count = max(0, int(payload.get("stock_count") or 0))
            self.convert_progress.setRange(0, max(total_steps, 1))
            self.convert_progress.setValue(0)
            self.convert_progress.setFormat(f"0/{total_steps}")
            self.convert_summary_browser.setPlainText(
                "\n".join(
                    [
                        "状态：转换中",
                        f"源周期：{source}",
                        f"目标周期：{', '.join(targets) if targets else '-'}",
                        f"股票数量：{stock_count}",
                        f"总步骤：{total_steps}",
                    ]
                )
            )
            return

        if stage == "step":
            stock_code = str(payload.get("stock_code") or "-")
            target = str(payload.get("target_timeframe") or "-")
            status = str(payload.get("status") or "-")
            display_total = max(total_steps, 1)
            display_current = min(current_step, display_total)
            self.convert_progress.setRange(0, display_total)
            self.convert_progress.setValue(display_current)
            self.convert_progress.setFormat(f"{display_current}/{display_total}")
            self._set_convert_status(f"转换中：{stock_code} -> {target}", "#0f766e")
            lines = [
                "状态：转换中",
                f"当前进度：{display_current}/{display_total}",
                f"当前股票：{stock_code}",
                f"目标周期：{target}",
                f"本步结果：{status}",
            ]
            latest_trade_date = str(payload.get("latest_trade_date") or "").strip()
            if latest_trade_date:
                lines.append(f"最新交易日：{latest_trade_date}")
            message = str(payload.get("message") or "").strip()
            if message:
                lines.append(f"说明：{message}")
            self.convert_summary_browser.setPlainText("\n".join(lines))
            return

        if stage == "done":
            display_total = max(total_steps, 1)
            display_current = min(current_step, display_total)
            self.convert_progress.setRange(0, display_total)
            self.convert_progress.setValue(display_current)
            self.convert_progress.setFormat(f"{display_current}/{display_total}")

    def _handle_convert_completed(self, result) -> None:
        self.convert_progress.setRange(0, 1)
        self.convert_progress.setValue(1)
        self.convert_start_button.setEnabled(True)

        lines = [
            f"股票数: {result.stock_count}",
            f"结果条目: {len(result.rows)}",
            f"写入总行数: {result.total_rows_written}",
        ]
        self.convert_summary_browser.setPlainText("\n".join(lines))
        self._populate_table(self.convert_table, [asdict(row) for row in result.rows])

    def _handle_convert_failed(self, message: str, detail: str) -> None:
        self.convert_progress.setRange(0, 1)
        self.convert_progress.setValue(0)
        self.convert_start_button.setEnabled(True)
        self.convert_summary_browser.setPlainText(detail)
        QMessageBox.critical(self, "转换失败", message)

    def _handle_convert_completed(self, result) -> None:
        self.convert_progress.setRange(0, 1)
        self.convert_progress.setValue(1)
        self.convert_progress.setFormat("done")
        self.convert_start_button.setEnabled(True)
        self._set_convert_status("done", "#166534")
        self.convert_summary_browser.setPlainText(
            "\n".join(
                [
                    "status: done",
                    f"stocks: {result.stock_count}",
                    f"rows: {len(result.rows)}",
                    f"written: {result.total_rows_written}",
                ]
            )
        )
        self._populate_table(self.convert_table, [asdict(row) for row in result.rows])
        self._convert_thread = None

    def _handle_convert_failed(self, message: str, detail: str) -> None:
        self.convert_progress.setRange(0, 1)
        self.convert_progress.setValue(0)
        self.convert_progress.setFormat("failed")
        self.convert_start_button.setEnabled(True)
        self._set_convert_status("failed", "#b91c1c")
        self.convert_summary_browser.setPlainText(f"status: failed\n\n{detail}")
        QMessageBox.critical(self, "转换失败", message)
        self._convert_thread = None

    def _set_convert_idle_state(self) -> None:
        self.convert_progress.setRange(0, 1)
        self.convert_progress.setValue(0)
        self.convert_progress.setFormat("idle")
        self._set_convert_status("idle", "#475569")
        if not self.convert_summary_browser.toPlainText().strip():
            self.convert_summary_browser.setPlainText("status: idle\nNo conversion task is running.")

    def _set_convert_status(self, text: str, color: str) -> None:
        self.convert_status_label.setText(f"Status: {text}")
        self.convert_status_label.setStyleSheet(f"color: {color}; font-weight: 600;")

    @staticmethod
    def _make_datetime_edit(value: datetime) -> QDateTimeEdit:
        edit = QDateTimeEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        edit.setDateTime(QDateTime(value.year, value.month, value.day, value.hour, value.minute, value.second))
        return edit

    @staticmethod
    def _make_spin(value: int, minimum: int, maximum: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    @staticmethod
    def _datetime_value(widget: QDateTimeEdit) -> datetime:
        return widget.dateTime().toPython()

    @staticmethod
    def _build_market_group_checkboxes(*, default_checked: list[str]) -> QWidget:
        container = QWidget()
        layout = QGridLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(6)
        container._market_checkboxes = {}
        for index, key in enumerate(MARKET_GROUP_DISPLAY_ORDER):
            checkbox = QCheckBox(MARKET_GROUP_LABELS.get(key, key))
            checkbox.setProperty("market_group", key)
            checkbox.setChecked(key in default_checked)
            layout.addWidget(checkbox, index // 4, index % 4)
            container._market_checkboxes[key] = checkbox
        return container

    @staticmethod
    def _build_timeframe_checkboxes(values: list[str], *, default_checked: list[str]) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        container._timeframe_checkboxes = {}
        for value in values:
            checkbox = QCheckBox(value)
            checkbox.setProperty("timeframe", value)
            checkbox.setChecked(value in default_checked)
            layout.addWidget(checkbox)
            container._timeframe_checkboxes[value] = checkbox
        layout.addStretch(1)
        return container

    @staticmethod
    def _checked_market_groups(container: QWidget) -> list[str]:
        checkboxes = getattr(container, "_market_checkboxes", {})
        return [key for key, checkbox in checkboxes.items() if checkbox.isChecked()]

    @staticmethod
    def _checked_timeframes(container: QWidget) -> list[str]:
        checkboxes = getattr(container, "_timeframe_checkboxes", {})
        return [key for key, checkbox in checkboxes.items() if checkbox.isChecked()]

    @staticmethod
    def _populate_table(table: QTableWidget, rows: list[dict]) -> None:
        if not rows:
            table.clear()
            table.setRowCount(0)
            table.setColumnCount(0)
            return
        headers = list(rows[0].keys())
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, header in enumerate(headers):
                value = row.get(header, "")
                item = QTableWidgetItem("" if value is None else str(value))
                table.setItem(row_index, column_index, item)
        table.resizeColumnsToContents()

    @staticmethod
    def _frame_to_rows(frame: pd.DataFrame) -> list[dict]:
        if frame.empty:
            return []
        prepared = frame.copy()
        for column in prepared.columns:
            if pd.api.types.is_datetime64_any_dtype(prepared[column]):
                prepared[column] = prepared[column].dt.strftime("%Y-%m-%d %H:%M:%S")
        return prepared.fillna("").to_dict(orient="records")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("本地数据同步与检索")
    window = LocalDataWorkbenchWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
