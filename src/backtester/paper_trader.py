"""Paper trading engine and backtester for analyst recommendations.

Simulates a portfolio that executes trades based on analyst consensus,
tracks positions, and measures performance against a benchmark (SPY).
"""

import logging
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ── Position sizing strategies ──
# How much of the portfolio to allocate per trade signal
CONVICTION_ALLOCATION = {"HIGH": 0.05, "MEDIUM": 0.03, "LOW": 0.01}


@dataclass
class Position:
    """An open paper-trading position."""
    ticker: str
    shares: float
    entry_price: float
    entry_date: str
    direction: str  # "long" or "short"
    analyst: str  # which analyst triggered the trade
    conviction: str

    @property
    def cost_basis(self) -> float:
        return self.shares * self.entry_price


@dataclass
class ClosedTrade:
    """A completed (closed) trade with realized P&L."""
    ticker: str
    direction: str
    shares: float
    entry_price: float
    exit_price: float
    entry_date: str
    exit_date: str
    analyst: str
    conviction: str

    @property
    def pnl(self) -> float:
        if self.direction == "long":
            return (self.exit_price - self.entry_price) * self.shares
        else:
            return (self.entry_price - self.exit_price) * self.shares

    @property
    def return_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        if self.direction == "long":
            return (self.exit_price - self.entry_price) / self.entry_price * 100
        else:
            return (self.entry_price - self.exit_price) / self.entry_price * 100


@dataclass
class PortfolioSnapshot:
    """Portfolio state at a point in time."""
    date: str
    cash: float
    positions_value: float
    total_value: float
    num_positions: int


class PaperTrader:
    """Simulates a portfolio that executes trades based on analyst signals.

    Supports:
    - Position sizing by conviction level
    - Long and short positions
    - Automatic exit after hold period (based on analyst horizon)
    - Daily portfolio valuation
    - Performance metrics (total return, Sharpe, max drawdown)
    """

    HOLD_PERIODS = {"short": 20, "medium": 60, "long": 120}  # trading days

    def __init__(self, starting_capital: float = 100_000,
                 max_position_pct: float = 0.10,
                 stop_loss_pct: float = 0.15):
        """
        Args:
            starting_capital: Initial cash balance.
            max_position_pct: Max % of portfolio per position.
            stop_loss_pct: Auto-exit if loss exceeds this %.
        """
        self.starting_capital = starting_capital
        self.cash = starting_capital
        self.max_position_pct = max_position_pct
        self.stop_loss_pct = stop_loss_pct

        self.positions: list[Position] = []
        self.closed_trades: list[ClosedTrade] = []
        self.snapshots: list[PortfolioSnapshot] = []
        self.trade_log: list[dict] = []

    def _portfolio_value(self, current_prices: dict) -> float:
        """Total portfolio value = cash + positions marked to market."""
        pos_value = 0.0
        for p in self.positions:
            price = current_prices.get(p.ticker, p.entry_price)
            if p.direction == "long":
                pos_value += p.shares * price
            else:
                # Short: profit when price drops
                pos_value += p.shares * (2 * p.entry_price - price)
        return self.cash + pos_value

    def _positions_value(self, current_prices: dict) -> float:
        val = 0.0
        for p in self.positions:
            price = current_prices.get(p.ticker, p.entry_price)
            if p.direction == "long":
                val += p.shares * price
            else:
                val += p.shares * (2 * p.entry_price - price)
        return val

    def open_position(self, ticker: str, direction: str, price: float,
                      date: str, analyst: str, conviction: str,
                      current_prices: dict):
        """Open a new paper position."""
        # Check if we already have a position in this ticker + direction
        for p in self.positions:
            if p.ticker == ticker and p.direction == direction:
                logger.debug(f"Already have {direction} position in {ticker}, skipping")
                return

        portfolio_val = self._portfolio_value(current_prices)
        alloc_pct = CONVICTION_ALLOCATION.get(conviction, 0.01)
        alloc = min(alloc_pct * portfolio_val, self.max_position_pct * portfolio_val)
        alloc = min(alloc, self.cash)  # can't spend more than we have

        if alloc < 100 or price <= 0:
            return

        shares = alloc / price
        self.cash -= alloc

        pos = Position(
            ticker=ticker, shares=shares, entry_price=price,
            entry_date=date, direction=direction,
            analyst=analyst, conviction=conviction,
        )
        self.positions.append(pos)

        self.trade_log.append({
            "date": date, "action": f"OPEN {direction.upper()}",
            "ticker": ticker, "shares": round(shares, 4),
            "price": price, "analyst": analyst, "conviction": conviction,
        })
        logger.debug(f"Opened {direction} {ticker}: {shares:.2f} shares @ ${price:.2f}")

    def close_position(self, position: Position, exit_price: float, exit_date: str):
        """Close a position and record the trade."""
        trade = ClosedTrade(
            ticker=position.ticker, direction=position.direction,
            shares=position.shares, entry_price=position.entry_price,
            exit_price=exit_price, entry_date=position.entry_date,
            exit_date=exit_date, analyst=position.analyst,
            conviction=position.conviction,
        )
        self.closed_trades.append(trade)

        if position.direction == "long":
            proceeds = position.shares * exit_price
        else:
            proceeds = position.shares * (2 * position.entry_price - exit_price)
        self.cash += proceeds

        self.trade_log.append({
            "date": exit_date, "action": f"CLOSE {position.direction.upper()}",
            "ticker": position.ticker, "shares": round(position.shares, 4),
            "price": exit_price, "pnl": round(trade.pnl, 2),
            "return_pct": round(trade.return_pct, 2),
        })

        self.positions.remove(position)
        logger.debug(
            f"Closed {position.direction} {position.ticker}: "
            f"PnL ${trade.pnl:.2f} ({trade.return_pct:.1f}%)"
        )

    def check_exits(self, date: str, current_prices: dict, hold_days_map: dict):
        """Check for stop-loss hits and hold-period expirations."""
        to_close = []
        for p in self.positions:
            price = current_prices.get(p.ticker)
            if not price:
                continue

            # Stop loss
            if p.direction == "long":
                loss_pct = (p.entry_price - price) / p.entry_price
            else:
                loss_pct = (price - p.entry_price) / p.entry_price

            if loss_pct >= self.stop_loss_pct:
                to_close.append((p, price, "stop_loss"))
                continue

            # Hold period expiry
            max_hold = hold_days_map.get(p.analyst, 60)
            entry_dt = datetime.strptime(p.entry_date, "%Y-%m-%d")
            current_dt = datetime.strptime(date, "%Y-%m-%d")
            if (current_dt - entry_dt).days >= max_hold:
                to_close.append((p, price, "hold_expired"))

        for p, price, reason in to_close:
            self.close_position(p, price, date)

    def take_snapshot(self, date: str, current_prices: dict):
        """Record portfolio state for equity curve."""
        total = self._portfolio_value(current_prices)
        pos_val = self._positions_value(current_prices)
        self.snapshots.append(PortfolioSnapshot(
            date=date, cash=self.cash,
            positions_value=round(pos_val, 2),
            total_value=round(total, 2),
            num_positions=len(self.positions),
        ))

    def get_metrics(self) -> dict:
        """Calculate performance summary."""
        if not self.snapshots:
            return {"error": "No data — run a backtest first"}

        values = [s.total_value for s in self.snapshots]
        total_return_pct = (values[-1] - self.starting_capital) / self.starting_capital * 100

        # Max drawdown
        peak = values[0]
        max_dd = 0
        for v in values:
            peak = max(peak, v)
            dd = (peak - v) / peak
            max_dd = max(max_dd, dd)

        # Daily returns for Sharpe ratio
        daily_returns = []
        for i in range(1, len(values)):
            if values[i - 1] > 0:
                daily_returns.append((values[i] - values[i - 1]) / values[i - 1])

        avg_return = sum(daily_returns) / len(daily_returns) if daily_returns else 0
        if len(daily_returns) > 1:
            variance = sum((r - avg_return) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
            std_return = variance ** 0.5
            sharpe = (avg_return / std_return * (252 ** 0.5)) if std_return > 0 else 0
        else:
            sharpe = 0

        # Win rate
        wins = [t for t in self.closed_trades if t.pnl > 0]
        losses = [t for t in self.closed_trades if t.pnl <= 0]
        win_rate = len(wins) / len(self.closed_trades) * 100 if self.closed_trades else 0

        # Per-analyst breakdown
        analyst_pnl = defaultdict(lambda: {"pnl": 0, "trades": 0, "wins": 0})
        for t in self.closed_trades:
            analyst_pnl[t.analyst]["pnl"] += t.pnl
            analyst_pnl[t.analyst]["trades"] += 1
            if t.pnl > 0:
                analyst_pnl[t.analyst]["wins"] += 1

        analyst_breakdown = {}
        for analyst, data in analyst_pnl.items():
            analyst_breakdown[analyst] = {
                "pnl": round(data["pnl"], 2),
                "trades": data["trades"],
                "win_rate": round(data["wins"] / data["trades"] * 100, 1) if data["trades"] else 0,
            }

        return {
            "starting_capital": self.starting_capital,
            "ending_value": round(values[-1], 2),
            "total_return_pct": round(total_return_pct, 2),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "total_trades": len(self.closed_trades),
            "open_positions": len(self.positions),
            "win_rate": round(win_rate, 1),
            "total_pnl": round(sum(t.pnl for t in self.closed_trades), 2),
            "avg_trade_return": round(
                sum(t.return_pct for t in self.closed_trades) / len(self.closed_trades), 2
            ) if self.closed_trades else 0,
            "best_trade": max(
                ({"ticker": t.ticker, "return_pct": round(t.return_pct, 2), "analyst": t.analyst}
                 for t in self.closed_trades), key=lambda x: x["return_pct"], default=None
            ),
            "worst_trade": min(
                ({"ticker": t.ticker, "return_pct": round(t.return_pct, 2), "analyst": t.analyst}
                 for t in self.closed_trades), key=lambda x: x["return_pct"], default=None
            ),
            "analyst_breakdown": analyst_breakdown,
            "period": {
                "start": self.snapshots[0].date,
                "end": self.snapshots[-1].date,
                "trading_days": len(self.snapshots),
            },
        }

    def get_equity_curve(self) -> list[dict]:
        """Return equity curve data for charting."""
        return [
            {"date": s.date, "value": s.total_value, "cash": s.cash,
             "positions": s.positions_value, "num_positions": s.num_positions}
            for s in self.snapshots
        ]
