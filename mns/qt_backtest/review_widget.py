from __future__ import annotations

from dataclasses import dataclass
from math import ceil

import pandas as pd

from mns.factors.technical import ema

try:
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen, QWheelEvent
    from PySide6.QtWidgets import QWidget
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit("PySide6 is required. Install with `pip install -e .[qt]`.") from exc


# Tonghuashun-like look: white canvas, red-up green-down, light grids.
UP_COLOR = QColor("#e60012")
DOWN_COLOR = QColor("#00a65a")
EMA_FAST_COLOR = QColor("#f59e0b")
EMA_SLOW_COLOR = QColor("#4f6bdc")
TRADE_LINE_COLOR = QColor("#1f6feb")
NET_COLOR = QColor("#1d4ed8")
DD_COLOR = QColor("#ef4444")
GRID_COLOR = QColor("#e8edf3")
AXIS_COLOR = QColor("#6b7280")
TEXT_COLOR = QColor("#1f2937")
BORDER_COLOR = QColor("#d6dde6")
BG_COLOR = QColor("#f5f7fb")
PANEL_BG = QColor("#ffffff")
HOVER_COLOR = QColor("#94a3b8")


@dataclass(frozen=True)
class TradeOverlay:
    entry_index: int
    exit_index: int
    buy_price: float
    sell_price: float
    stop_price: float | None
    pnl: float
    exit_label: str


class FastReviewChartPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMouseTracking(True)
        self.setMinimumSize(760, 480)
        self.setAutoFillBackground(False)

        self._message = "运行回测后，这里会显示复盘图。按住左键拖动，滚轮缩放，双击重置视图。"
        self._frame = pd.DataFrame()
        self._trades: list[TradeOverlay] = []
        self._stock_code: str | None = None
        self._run_id = ""
        self._strategy_id = ""
        self._timeframe = ""
        self._summary: dict[str, float | int] = {}
        self._initial_cash = 1_000_000.0
        self._fast_period = 21
        self._slow_period = 55
        self._risk_per_trade = 5_000.0

        self._visible_count = 260
        self._viewport_start = 0
        self._default_visible = 260
        self._drag_anchor_x: float | None = None
        self._drag_anchor_start = 0
        self._is_dragging = False

        self._panel_rects: dict[str, QRectF] = {}
        self._hover_index: int | None = None

    def set_result(
        self,
        *,
        result,
        request,
        stock_code: str | None,
    ) -> None:
        self._stock_code = stock_code
        self._run_id = str(result.run_id)
        self._strategy_id = str(result.strategy_id)
        self._timeframe = str(request.timeframe)
        self._summary = dict(result.summary or {})
        self._initial_cash = float(request.initial_cash)

        params = request.params or {}
        if result.strategy_id == "ema_cross":
            self._fast_period = int(params.get("fast_period", 21))
            self._slow_period = int(params.get("slow_period", 55))
            self._risk_per_trade = float(params.get("risk_per_trade", 5_000.0))
        else:
            self._fast_period = 20
            self._slow_period = 50
            self._risk_per_trade = float(request.initial_cash) * float(params.get("risk_per_trade_pct", 0.008))

        self._frame = self._prepare_frame(result.kline, result.portfolio_snapshots, stock_code)
        self._trades = self._prepare_trades(result.trades, stock_code)
        self._hover_index = None
        self._is_dragging = False

        if self._frame.empty:
            self._message = "没有可展示的 K 线数据。"
            self.update()
            return

        self._default_visible = min(max(260, 60), len(self._frame))
        self._visible_count = self._default_visible
        self._viewport_start = max(len(self._frame) - self._visible_count, 0)
        self._message = ""
        self.update()

    def show_message(self, message: str) -> None:
        self._message = message
        self._frame = pd.DataFrame()
        self._trades = []
        self._hover_index = None
        self._is_dragging = False
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._frame.empty or event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._price_rect().contains(event.position()):
            return
        self._drag_anchor_x = float(event.position().x())
        self._drag_anchor_start = self._viewport_start
        self._is_dragging = True

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._frame.empty:
            return

        self._hover_index = self._index_for_x(float(event.position().x()))
        if self._drag_anchor_x is None:
            self.update()
            return

        price_rect = self._price_rect()
        candle_step = price_rect.width() / max(self._visible_count, 1)
        if candle_step <= 0:
            return
        shift = int(round((self._drag_anchor_x - float(event.position().x())) / candle_step))
        target_start = self._clamp_viewport_start(self._drag_anchor_start + shift)
        if target_start != self._viewport_start:
            self._viewport_start = target_start
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_anchor_x = None
        self._is_dragging = False
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._frame.empty or event.button() != Qt.MouseButton.LeftButton:
            return
        self._visible_count = self._default_visible
        self._viewport_start = max(len(self._frame) - self._visible_count, 0)
        self._is_dragging = False
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._frame.empty:
            return

        delta = event.angleDelta().y()
        if delta == 0:
            return

        anchor = self._anchor_ratio(float(event.position().x()))
        factor = 0.82 if delta > 0 else 1.22
        target_visible = int(round(self._visible_count * factor))
        target_visible = max(20, min(target_visible, len(self._frame)))
        if target_visible == self._visible_count:
            return

        anchor_index = self._viewport_start + (self._visible_count * anchor)
        target_start = int(round(anchor_index - (target_visible * anchor)))
        self._visible_count = target_visible
        self._viewport_start = self._clamp_viewport_start(target_start)
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover_index = None
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), BG_COLOR)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        if self._frame.empty:
            self._draw_message(painter)
            return

        panel = self._compute_layout()
        self._panel_rects = panel
        start, end = self._visible_range()
        visible = self._frame.iloc[start:end]
        if visible.empty:
            self._draw_message(painter)
            return

        visible_trades = [trade for trade in self._trades if not (trade.exit_index < start or trade.entry_index >= end)]
        price_min, price_max = self._price_bounds(visible, visible_trades)
        net_min, net_max = self._value_bounds(visible["net_value"], pad_ratio=0.12, min_pad=0.6)
        _, dd_max = self._value_bounds(visible["drawdown_pct"], pad_ratio=0.08, min_pad=0.6, include_zero=True)

        self._draw_headers(painter)
        self._draw_panel_frames(painter, panel)
        self._draw_price_grid(painter, panel["price"], price_min, price_max)
        self._draw_value_grid(painter, panel["net"], net_min, net_max, percent=False)
        self._draw_value_grid(painter, panel["drawdown"], 0.0, dd_max, percent=True, invert=True)
        self._draw_candles(painter, panel["price"], visible, start, price_min, price_max)
        self._draw_polyline(painter, panel["price"], visible["ema_fast"], start, price_min, price_max, EMA_FAST_COLOR, 1.2)
        self._draw_polyline(painter, panel["price"], visible["ema_slow"], start, price_min, price_max, EMA_SLOW_COLOR, 1.2)
        self._draw_trades(painter, panel["price"], visible_trades, start, price_min, price_max, simplified=self._is_dragging)
        self._draw_polyline(painter, panel["net"], visible["net_value"], start, net_min, net_max, NET_COLOR, 1.35)
        self._draw_polyline(painter, panel["drawdown"], visible["drawdown_pct"], start, 0.0, dd_max, DD_COLOR, 1.2, invert=True)
        self._draw_axis_tags(painter, panel, visible, price_min, price_max)
        self._draw_time_axis(painter, panel["drawdown"], visible, start)

        if not self._is_dragging:
            self._draw_info_box(painter, panel["price"])
            self._draw_hover(painter, panel, visible, start)

    def _prepare_frame(self, kline: pd.DataFrame, portfolio: pd.DataFrame, stock_code: str | None) -> pd.DataFrame:
        if kline.empty:
            return pd.DataFrame()
        frame = kline.copy()
        if stock_code and "stock_code" in frame.columns:
            selected = frame[frame["stock_code"].astype(str) == str(stock_code)]
            if not selected.empty:
                frame = selected

        frame["bar_time"] = pd.to_datetime(frame["bar_time"], errors="coerce")
        frame = frame.dropna(subset=["bar_time"]).sort_values("bar_time").reset_index(drop=True)
        for column in ("open", "high", "low", "close"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
        if frame.empty:
            return frame

        frame["ema_fast"] = ema(frame["close"], self._fast_period)
        frame["ema_slow"] = ema(frame["close"], self._slow_period)

        aligned = pd.DataFrame({"bar_time": frame["bar_time"]})
        if portfolio is not None and not portfolio.empty:
            port = portfolio.copy()
            port["snapshot_time"] = pd.to_datetime(port["snapshot_time"], errors="coerce")
            port = port.dropna(subset=["snapshot_time"]).sort_values("snapshot_time")
            aligned = aligned.merge(
                port[["snapshot_time", "total_equity", "drawdown"]],
                left_on="bar_time",
                right_on="snapshot_time",
                how="left",
            )
            aligned["total_equity"] = pd.to_numeric(aligned["total_equity"], errors="coerce").ffill().bfill()
            aligned["drawdown"] = pd.to_numeric(aligned["drawdown"], errors="coerce").fillna(0.0)
        else:
            aligned["total_equity"] = self._initial_cash
            aligned["drawdown"] = 0.0

        frame["net_value"] = aligned["total_equity"].astype(float) / max(self._initial_cash, 1.0) * 1000.0
        frame["drawdown_pct"] = aligned["drawdown"].astype(float).abs() * 100.0
        return frame

    def _prepare_trades(self, trades: pd.DataFrame, stock_code: str | None) -> list[TradeOverlay]:
        if trades is None or trades.empty or self._frame.empty:
            return []
        frame = trades.copy()
        if stock_code and "stock_code" in frame.columns:
            frame = frame[frame["stock_code"].astype(str) == str(stock_code)]
        if frame.empty:
            return []

        time_lookup = {timestamp: index for index, timestamp in enumerate(self._frame["bar_time"])}
        overlays: list[TradeOverlay] = []
        for _, trade in frame.iterrows():
            entry_time = pd.to_datetime(trade.get("buy_time"), errors="coerce")
            exit_time = pd.to_datetime(trade.get("sell_time"), errors="coerce")
            if pd.isna(entry_time) or pd.isna(exit_time):
                continue
            entry_index = time_lookup.get(entry_time)
            exit_index = time_lookup.get(exit_time)
            if entry_index is None or exit_index is None:
                continue

            buy_price = pd.to_numeric(trade.get("buy_price"), errors="coerce")
            sell_price = pd.to_numeric(trade.get("sell_price"), errors="coerce")
            if pd.isna(buy_price) or pd.isna(sell_price):
                continue

            stop_price = pd.to_numeric(trade.get("stop_loss"), errors="coerce")
            pnl = pd.to_numeric(trade.get("pnl"), errors="coerce")
            overlays.append(
                TradeOverlay(
                    entry_index=entry_index,
                    exit_index=exit_index,
                    buy_price=float(buy_price),
                    sell_price=float(sell_price),
                    stop_price=None if pd.isna(stop_price) else float(stop_price),
                    pnl=0.0 if pd.isna(pnl) else float(pnl),
                    exit_label=self._trade_exit_label(str(trade.get("exit_reason") or trade.get("exit_type") or "")),
                )
            )
        return overlays

    def _trade_exit_label(self, reason: str) -> str:
        text = reason.upper()
        if text == "INITIAL_STOP":
            return "SL"
        if text in {"BREAKEVEN_STOP", "BREAKEVEN"}:
            return "BE"
        if text.startswith("TRAILING_STOP_"):
            return text.replace("TRAILING_STOP_", "")
        if text == "TREND_STOP":
            return "TR"
        if text == "END_OF_TEST":
            return "平"
        return "SL"

    def _compute_layout(self) -> dict[str, QRectF]:
        width = max(self.width(), 960)
        height = max(self.height(), 420)
        left = 58.0
        right = 88.0
        top = 62.0
        bottom = 34.0
        panel_gap = 12.0

        inner_width = max(width - left - right, 100.0)
        inner_height = max(height - top - bottom, 180.0)
        drawdown_height = max(76.0, min(116.0, inner_height * 0.16))
        net_height = max(86.0, min(150.0, inner_height * 0.22))
        price_height = max(inner_height - net_height - drawdown_height - panel_gap * 2, 160.0)

        price = QRectF(left, top, inner_width, price_height)
        net = QRectF(left, price.bottom() + panel_gap, inner_width, net_height)
        drawdown = QRectF(left, net.bottom() + panel_gap, inner_width, drawdown_height)
        return {"price": price, "net": net, "drawdown": drawdown}

    def _visible_range(self) -> tuple[int, int]:
        if self._frame.empty:
            return 0, 0
        visible = max(20, min(self._visible_count, len(self._frame)))
        start = self._clamp_viewport_start(self._viewport_start)
        end = min(start + visible, len(self._frame))
        return start, end

    def _clamp_viewport_start(self, start: int) -> int:
        max_start = max(len(self._frame) - self._visible_count, 0)
        return max(0, min(int(start), max_start))

    def _price_rect(self) -> QRectF:
        return self._panel_rects.get("price", QRectF())

    def _anchor_ratio(self, x: float) -> float:
        rect = self._price_rect()
        if rect.width() <= 0:
            return 0.5
        return min(max((x - rect.left()) / rect.width(), 0.0), 1.0)

    def _index_for_x(self, x: float) -> int | None:
        rect = self._price_rect()
        if rect.width() <= 0 or not rect.contains(QPointF(x, rect.center().y())):
            return None
        start, end = self._visible_range()
        visible_count = max(end - start, 1)
        candle_step = rect.width() / visible_count
        offset = int((x - rect.left()) / candle_step)
        return start + max(0, min(offset, visible_count - 1))

    def _price_bounds(self, visible: pd.DataFrame, visible_trades: list[TradeOverlay]) -> tuple[float, float]:
        values: list[float] = []
        for column in ("high", "low", "ema_fast", "ema_slow"):
            values.extend(pd.to_numeric(visible[column], errors="coerce").dropna().astype(float).tolist())
        for trade in visible_trades:
            values.extend([trade.buy_price, trade.sell_price])
            if trade.stop_price is not None:
                values.append(trade.stop_price)
        if not values:
            values = [1.0, 2.0]
        minimum = min(values)
        maximum = max(values)
        if maximum <= minimum:
            maximum += 1.0
            minimum -= 1.0
        pad = max((maximum - minimum) * 0.08, 1e-4)
        return minimum - pad, maximum + pad

    def _value_bounds(self, series: pd.Series, *, pad_ratio: float, min_pad: float, include_zero: bool = False) -> tuple[float, float]:
        minimum = float(series.min())
        maximum = float(series.max())
        if include_zero:
            minimum = min(minimum, 0.0)
            maximum = max(maximum, 0.0)
        if maximum <= minimum:
            maximum += 1.0
            minimum -= 1.0
        pad = max((maximum - minimum) * pad_ratio, min_pad)
        return minimum - pad, maximum + pad

    def _draw_message(self, painter: QPainter) -> None:
        painter.setPen(TEXT_COLOR)
        painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self._message)

    def _draw_headers(self, painter: QPainter) -> None:
        summary = self._summary or {}
        total_pnl = float(summary.get("total_pnl", 0.0))
        win_rate = float(summary.get("win_rate", 0.0))
        max_drawdown = float(summary.get("max_drawdown", 0.0))
        ending_equity = float(summary.get("ending_equity", 0.0))
        trade_count = int(summary.get("trade_count", 0))

        lines = [
            "回测K线图：同花顺风格显示，支持平滑拖动、缩放、交易路径、净值曲线和回撤曲线。",
            f"运行编号：{self._run_id} | 标的：{self._stock_code or '-'} | 周期：{self._timeframe} | 策略：{self._strategy_id} | EMA：{self._fast_period}/{self._slow_period} | 单笔风险：{self._risk_per_trade:,.0f}",
            f"交易：{trade_count} | 胜率：{win_rate:.2%} | 总盈亏：{total_pnl:,.2f} | 最大回撤：{max_drawdown:.2%} | 期末权益：{ending_equity:,.2f}",
        ]
        painter.setPen(TEXT_COLOR)
        y = 18
        for line in lines:
            painter.drawText(12, y, self.width() - 24, 16, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), line)
            y += 20

    def _draw_panel_frames(self, painter: QPainter, panel: dict[str, QRectF]) -> None:
        painter.setPen(QPen(BORDER_COLOR, 1))
        painter.setBrush(PANEL_BG)
        for rect in panel.values():
            painter.drawRect(rect)

    def _draw_price_grid(self, painter: QPainter, rect: QRectF, price_min: float, price_max: float) -> None:
        for index in range(5):
            value = price_min + ((price_max - price_min) * index / 4)
            y = self._y_for_value(value, rect, price_min, price_max)
            painter.setPen(QPen(GRID_COLOR, 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setPen(AXIS_COLOR)
            painter.drawText(QRectF(0, y - 9, rect.left() - 8, 18), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), self._format_price_axis(value))

    def _draw_value_grid(self, painter: QPainter, rect: QRectF, value_min: float, value_max: float, *, percent: bool, invert: bool = False) -> None:
        for index in range(4):
            value = value_min + ((value_max - value_min) * index / 3)
            y = self._y_for_value(value, rect, value_min, value_max, invert=invert)
            painter.setPen(QPen(GRID_COLOR, 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setPen(AXIS_COLOR)
            text = f"{value:.2f}%" if percent else f"{value:.2f}"
            painter.drawText(QRectF(0, y - 9, rect.left() - 8, 18), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), text)

    def _draw_candles(self, painter: QPainter, rect: QRectF, visible: pd.DataFrame, start: int, price_min: float, price_max: float) -> None:
        visible_count = len(visible)
        candle_step = rect.width() / max(visible_count, 1)
        body_width = max(2.0, min(candle_step * 0.66, 9.0))
        dense_mode = visible_count >= 280 or self._is_dragging

        for offset, (_, row) in enumerate(visible.iterrows()):
            index = start + offset
            x = self._x_for(index, start, visible_count, rect)
            open_price = float(row["open"])
            high_price = float(row["high"])
            low_price = float(row["low"])
            close_price = float(row["close"])
            color = UP_COLOR if close_price >= open_price else DOWN_COLOR
            high_y = self._y_for_value(high_price, rect, price_min, price_max)
            low_y = self._y_for_value(low_price, rect, price_min, price_max)
            painter.setPen(QPen(color, 1))
            painter.drawLine(QPointF(x, high_y), QPointF(x, low_y))

            if dense_mode:
                painter.drawLine(QPointF(x, self._y_for_value(open_price, rect, price_min, price_max)), QPointF(x, self._y_for_value(close_price, rect, price_min, price_max)))
                continue

            open_y = self._y_for_value(open_price, rect, price_min, price_max)
            close_y = self._y_for_value(close_price, rect, price_min, price_max)
            top = min(open_y, close_y)
            bottom = max(open_y, close_y)
            if abs(bottom - top) < 1.0:
                bottom = top + 1.0
            body_rect = QRectF(x - body_width / 2, top, body_width, bottom - top)
            if close_price >= open_price:
                painter.fillRect(body_rect, color)
                painter.drawRect(body_rect)
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(body_rect)

    def _draw_polyline(
        self,
        painter: QPainter,
        rect: QRectF,
        series: pd.Series,
        start: int,
        value_min: float,
        value_max: float,
        color: QColor,
        width: float,
        *,
        invert: bool = False,
    ) -> None:
        points: list[QPointF] = []
        visible_count = len(series)
        stride = max(1, visible_count // 900) if self._is_dragging else 1
        values = series.tolist()
        for offset, value in enumerate(values):
            if offset % stride != 0 and offset != visible_count - 1:
                continue
            if pd.isna(value):
                continue
            index = start + offset
            x = self._x_for(index, start, visible_count, rect)
            y = self._y_for_value(float(value), rect, value_min, value_max, invert=invert)
            points.append(QPointF(x, y))
        if len(points) < 2:
            return
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        painter.setPen(QPen(color, width))
        painter.drawPath(path)

    def _draw_trades(self, painter: QPainter, rect: QRectF, trades: list[TradeOverlay], start: int, price_min: float, price_max: float, *, simplified: bool) -> None:
        visible_count = self._visible_range()[1] - start
        for trade in trades:
            entry_x = self._x_for(trade.entry_index, start, visible_count, rect)
            exit_x = self._x_for(trade.exit_index, start, visible_count, rect)
            entry_y = self._y_for_value(trade.buy_price, rect, price_min, price_max)
            exit_y = self._y_for_value(trade.sell_price, rect, price_min, price_max)

            painter.setPen(QPen(TRADE_LINE_COLOR, 1.1))
            painter.drawLine(QPointF(entry_x, entry_y), QPointF(exit_x, exit_y))

            if trade.stop_price is not None and not simplified:
                painter.setPen(QPen(QColor("#ff6b6b"), 1, Qt.PenStyle.DashLine))
                stop_y = self._y_for_value(trade.stop_price, rect, price_min, price_max)
                painter.drawLine(QPointF(entry_x, stop_y), QPointF(exit_x, stop_y))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(TRADE_LINE_COLOR)
            painter.drawEllipse(QPointF(entry_x, entry_y), 3.0, 3.0)

            exit_color = QColor("#16a34a") if trade.pnl >= 0 else QColor("#d92d20")
            painter.setBrush(exit_color)
            painter.drawEllipse(QPointF(exit_x, exit_y), 3.5, 3.5)

            if simplified:
                continue

            badge_w = 28
            badge_h = 18
            badge_x = exit_x + 6 if exit_x < rect.right() - 42 else exit_x - badge_w - 6
            badge_y = exit_y - badge_h / 2
            painter.setBrush(exit_color)
            painter.drawRoundedRect(QRectF(badge_x, badge_y, badge_w, badge_h), 3, 3)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(QRectF(badge_x, badge_y, badge_w, badge_h), int(Qt.AlignmentFlag.AlignCenter), trade.exit_label)

    def _draw_axis_tags(self, painter: QPainter, panel: dict[str, QRectF], visible: pd.DataFrame, price_min: float, price_max: float) -> None:
        last = visible.iloc[-1]
        close_price = float(last["close"])
        close_y = self._y_for_value(close_price, panel["price"], price_min, price_max)
        close_color = UP_COLOR if close_price >= float(last["open"]) else DOWN_COLOR
        painter.setPen(close_color)
        painter.drawText(QRectF(panel["price"].right() + 8, close_y - 10, 74, 20), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), f"收 {close_price:.4f}")

        for value, color, label in (
            (last.get("ema_fast"), EMA_FAST_COLOR, f"EMA({self._fast_period})"),
            (last.get("ema_slow"), EMA_SLOW_COLOR, f"EMA({self._slow_period})"),
        ):
            if pd.notna(value):
                y = self._y_for_value(float(value), panel["price"], price_min, price_max)
                painter.setPen(color)
                painter.drawText(QRectF(panel["price"].right() + 8, y - 10, 78, 20), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)

        painter.setPen(NET_COLOR)
        painter.drawText(QRectF(panel["net"].right() + 8, panel["net"].top() + 8, 82, 20), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "净值曲线")
        painter.setPen(DD_COLOR)
        painter.drawText(QRectF(panel["drawdown"].right() + 8, panel["drawdown"].top() + 8, 96, 20), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "回撤曲线(%)")

    def _draw_time_axis(self, painter: QPainter, rect: QRectF, visible: pd.DataFrame, start: int) -> None:
        visible_count = len(visible)
        target_labels = min(8, max(4, ceil(visible_count / 45)))
        if target_labels <= 1:
            indices = [start]
        else:
            indices = [
                start + int(round((visible_count - 1) * index / (target_labels - 1)))
                for index in range(target_labels)
            ]
        indices = sorted(set(index for index in indices if start <= index < start + visible_count))
        painter.setPen(AXIS_COLOR)
        intraday = any(timestamp.hour != 0 or timestamp.minute != 0 for timestamp in self._frame["bar_time"])
        fmt = "%m-%d\n%H:%M" if intraday else "%Y-%m-%d"
        for index in indices:
            x = self._x_for(index, start, visible_count, rect)
            painter.drawLine(QPointF(x, rect.bottom()), QPointF(x, rect.bottom() + 5))
            text = pd.Timestamp(self._frame.iloc[index]["bar_time"]).strftime(fmt)
            painter.drawText(QRectF(x - 34, rect.bottom() + 6, 68, 28), int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop), text)

    def _draw_info_box(self, painter: QPainter, rect: QRectF) -> None:
        focus_index = self._hover_index if self._hover_index is not None else self._visible_range()[1] - 1
        if focus_index is None or focus_index < 0 or focus_index >= len(self._frame):
            return
        row = self._frame.iloc[focus_index]
        box = QRectF(rect.left() + 10, rect.top() + 8, 208, 118)
        painter.setPen(BORDER_COLOR)
        painter.setBrush(QColor(255, 255, 255, 246))
        painter.drawRect(box)

        lines = [
            f"时间：{pd.Timestamp(row['bar_time']).strftime('%Y-%m-%d %H:%M')}",
            f"开/高/低/收：{float(row['open']):.4f} / {float(row['high']):.4f} / {float(row['low']):.4f} / {float(row['close']):.4f}",
            f"EMA({self._fast_period})：{float(row['ema_fast']):.4f}" if pd.notna(row["ema_fast"]) else f"EMA({self._fast_period})：-",
            f"EMA({self._slow_period})：{float(row['ema_slow']):.4f}" if pd.notna(row["ema_slow"]) else f"EMA({self._slow_period})：-",
            f"净值曲线：{float(row['net_value']):.2f}",
            f"当前回撤：{float(row['drawdown_pct']):.2f}%",
        ]
        painter.setPen(TEXT_COLOR)
        y = box.top() + 10
        for line in lines:
            painter.drawText(QRectF(box.left() + 8, y, box.width() - 16, 18), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), line)
            y += 18

    def _draw_hover(self, painter: QPainter, panel: dict[str, QRectF], visible: pd.DataFrame, start: int) -> None:
        if self._hover_index is None or self._hover_index < start or self._hover_index >= start + len(visible):
            return
        x = self._x_for(self._hover_index, start, len(visible), panel["price"])
        painter.setPen(QPen(HOVER_COLOR, 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(x, panel["price"].top()), QPointF(x, panel["drawdown"].bottom()))

    def _x_for(self, index: int, start: int, visible_count: int, rect: QRectF) -> float:
        candle_step = rect.width() / max(visible_count, 1)
        return rect.left() + ((index - start) * candle_step) + (candle_step / 2)

    def _y_for_value(self, value: float, rect: QRectF, value_min: float, value_max: float, *, invert: bool = False) -> float:
        if value_max <= value_min:
            return rect.center().y()
        ratio = (value - value_min) / (value_max - value_min)
        if not invert:
            ratio = 1.0 - ratio
        return rect.top() + (ratio * rect.height())

    def _format_price_axis(self, value: float) -> str:
        absolute = abs(value)
        if absolute >= 1000:
            return f"{value:.1f}"
        if absolute >= 1:
            return f"{value:.2f}"
        if absolute >= 0.1:
            return f"{value:.4f}"
        return f"{value:.5f}"
