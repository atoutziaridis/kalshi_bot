"""Event-driven backtesting simulator with order book microstructure."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field


class Side(str, Enum):
    YES = "yes"
    NO = "no"


@dataclass
class Position:
    """Open position in a market."""

    ticker: str
    side: Side
    quantity: int
    entry_price: float
    entry_time: datetime
    current_value: float = 0.0


@dataclass
class Trade:
    """Executed trade record."""

    timestamp: datetime
    ticker: str
    action: str
    side: Side
    quantity: int
    price: float
    cost: float
    fees: float
    pnl: float = 0.0


@dataclass
class MarketState:
    """Snapshot of market state at a point in time."""

    timestamp: datetime
    ticker: str
    bid: float
    ask: float
    last_price: float
    volume: int = 0
    open_interest: int = 0

    @property
    def mid_price(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass
class Signal:
    """Trading signal from strategy."""

    action: str
    side: Side | None = None
    quantity: int = 0
    reason: str = ""


class BacktestMetrics(BaseModel):
    """Comprehensive backtest performance metrics."""

    total_return: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration_days: float = 0.0

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0

    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_trade_pnl: float = 0.0
    edge_per_contract: float = 0.0

    kelly_optimal: float = 0.0
    kelly_fraction_used: float = 0.0

    final_equity: float = 0.0
    peak_equity: float = 0.0


class EventDrivenBacktester:
    """
    Event-driven backtester with realistic Kalshi microstructure.

    Features:
    - Bid-ask spread modeling
    - Fee calculation (Kalshi formula)
    - Slippage simulation
    - Position mark-to-market
    - Binary contract payoff at resolution
    """

    def __init__(
        self,
        initial_capital: float = 10000.0,
        fee_rate: float = 0.07,
        slippage_bps: float = 5.0,
    ):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps / 10000

        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.equity_curve: list[tuple[datetime, float]] = []

        self._peak_equity = initial_capital
        self._max_drawdown = 0.0

    def calculate_fee(self, price: float, quantity: int) -> float:
        """Calculate Kalshi fee: 0.07 * p * (1-p) per contract."""
        if price <= 0 or price >= 1:
            return 0.0
        fee_per_contract = self.fee_rate * price * (1 - price)
        fee_per_contract = max(0.01, np.ceil(fee_per_contract * 100) / 100)
        return fee_per_contract * quantity

    def run(
        self,
        market_data: list[MarketState],
        signal_func: Callable[[MarketState, dict], Signal],
        resolutions: dict[str, bool] | None = None,
    ) -> BacktestMetrics:
        """
        Run event-driven backtest.

        Args:
            market_data: Chronological list of market states
            signal_func: Strategy function(market_state, context) -> Signal
            resolutions: Dict mapping ticker to resolution (True=YES won)

        Returns:
            BacktestMetrics with performance statistics
        """
        resolutions = resolutions or {}
        context = {"positions": self.positions, "capital": self.capital}

        for state in market_data:
            signal = signal_func(state, context)

            if signal.action == "buy" and signal.side:
                self._execute_buy(state, signal)
            elif signal.action == "sell":
                self._execute_sell(state, signal)

            self._mark_to_market(state)
            self._record_equity(state.timestamp)

            context["positions"] = self.positions
            context["capital"] = self.capital

        self._settle_positions(resolutions)

        return self._calculate_metrics()

    def _execute_buy(self, state: MarketState, signal: Signal) -> None:
        """Execute buy order with slippage and fees."""
        if signal.quantity <= 0:
            return

        if signal.side == Side.YES:
            price = state.ask * (1 + self.slippage_bps)
        else:
            price = (1 - state.bid) * (1 + self.slippage_bps)

        price = min(0.99, max(0.01, price))
        fees = self.calculate_fee(price, signal.quantity)
        cost = price * signal.quantity + fees

        if cost > self.capital:
            max_qty = int((self.capital - fees) / price)
            if max_qty <= 0:
                return
            signal.quantity = max_qty
            cost = price * signal.quantity + fees

        self.capital -= cost

        if state.ticker in self.positions:
            pos = self.positions[state.ticker]
            total_qty = pos.quantity + signal.quantity
            pos.entry_price = (
                (pos.entry_price * pos.quantity + price * signal.quantity)
                / total_qty
            )
            pos.quantity = total_qty
        else:
            self.positions[state.ticker] = Position(
                ticker=state.ticker,
                side=signal.side,
                quantity=signal.quantity,
                entry_price=price,
                entry_time=state.timestamp,
            )

        self.trades.append(Trade(
            timestamp=state.timestamp,
            ticker=state.ticker,
            action="BUY",
            side=signal.side,
            quantity=signal.quantity,
            price=price,
            cost=cost,
            fees=fees,
        ))

    def _execute_sell(self, state: MarketState, signal: Signal) -> None:
        """Execute sell/close order."""
        if state.ticker not in self.positions:
            return

        pos = self.positions[state.ticker]
        qty_to_sell = min(signal.quantity or pos.quantity, pos.quantity)

        if pos.side == Side.YES:
            price = state.bid * (1 - self.slippage_bps)
        else:
            price = (1 - state.ask) * (1 - self.slippage_bps)

        price = min(0.99, max(0.01, price))
        fees = self.calculate_fee(price, qty_to_sell)
        proceeds = price * qty_to_sell - fees

        if pos.side == Side.YES:
            pnl = (price - pos.entry_price) * qty_to_sell - fees
        else:
            pnl = (pos.entry_price - price) * qty_to_sell - fees

        self.capital += proceeds

        self.trades.append(Trade(
            timestamp=state.timestamp,
            ticker=state.ticker,
            action="SELL",
            side=pos.side,
            quantity=qty_to_sell,
            price=price,
            cost=-proceeds,
            fees=fees,
            pnl=pnl,
        ))

        if qty_to_sell >= pos.quantity:
            del self.positions[state.ticker]
        else:
            pos.quantity -= qty_to_sell

    def _mark_to_market(self, state: MarketState) -> None:
        """Update position values based on current market."""
        if state.ticker in self.positions:
            pos = self.positions[state.ticker]
            if pos.side == Side.YES:
                pos.current_value = pos.quantity * state.mid_price
            else:
                pos.current_value = pos.quantity * (1 - state.mid_price)

    def _record_equity(self, timestamp: datetime) -> None:
        """Record equity curve point."""
        position_value = sum(p.current_value for p in self.positions.values())
        total_equity = self.capital + position_value

        self.equity_curve.append((timestamp, total_equity))

        if total_equity > self._peak_equity:
            self._peak_equity = total_equity

        if self._peak_equity > 0:
            dd = (self._peak_equity - total_equity) / self._peak_equity
            self._max_drawdown = max(self._max_drawdown, dd)

    def _settle_positions(self, resolutions: dict[str, bool]) -> None:
        """Settle remaining positions at resolution."""
        for ticker, pos in list(self.positions.items()):
            resolved_yes = resolutions.get(ticker, False)

            if pos.side == Side.YES:
                if resolved_yes:
                    payout = pos.quantity * 1.0
                    pnl = payout - pos.entry_price * pos.quantity
                else:
                    payout = 0.0
                    pnl = -pos.entry_price * pos.quantity
            else:
                if resolved_yes:
                    payout = 0.0
                    pnl = -pos.entry_price * pos.quantity
                else:
                    payout = pos.quantity * 1.0
                    pnl = payout - pos.entry_price * pos.quantity

            self.capital += payout

            self.trades.append(Trade(
                timestamp=datetime.now(),
                ticker=ticker,
                action="SETTLE",
                side=pos.side,
                quantity=pos.quantity,
                price=1.0 if resolved_yes else 0.0,
                cost=0.0,
                fees=0.0,
                pnl=pnl,
            ))

        self.positions.clear()

    def _calculate_metrics(self) -> BacktestMetrics:
        """Calculate comprehensive backtest metrics."""
        if not self.equity_curve:
            return BacktestMetrics(final_equity=self.capital)

        equity_df = pd.DataFrame(self.equity_curve, columns=["timestamp", "equity"])
        returns = equity_df["equity"].pct_change().dropna()

        total_return = (self.capital - self.initial_capital) / self.initial_capital

        if len(self.equity_curve) > 1:
            days = (
                self.equity_curve[-1][0] - self.equity_curve[0][0]
            ).total_seconds() / 86400
            if days > 0:
                annualized = (1 + total_return) ** (365 / days) - 1
            else:
                annualized = 0.0
        else:
            annualized = 0.0

        if len(returns) > 1 and returns.std() > 0:
            sharpe = returns.mean() / returns.std() * np.sqrt(252)
        else:
            sharpe = 0.0

        negative_returns = returns[returns < 0]
        if len(negative_returns) > 0 and negative_returns.std() > 0:
            sortino = returns.mean() / negative_returns.std() * np.sqrt(252)
        else:
            sortino = 0.0

        pnls = [t.pnl for t in self.trades if t.pnl != 0]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        win_rate = len(wins) / len(pnls) if pnls else 0.0
        avg_win = np.mean(wins) if wins else 0.0
        avg_loss = abs(np.mean(losses)) if losses else 0.0
        profit_factor = sum(wins) / abs(sum(losses)) if losses else 0.0

        total_contracts = sum(t.quantity for t in self.trades)
        edge_per_contract = sum(pnls) / total_contracts if total_contracts > 0 else 0.0

        if win_rate > 0 and win_rate < 1 and avg_win > 0 and avg_loss > 0:
            b = avg_win / avg_loss
            kelly = win_rate - (1 - win_rate) / b
        else:
            kelly = 0.0

        return BacktestMetrics(
            total_return=total_return,
            annualized_return=annualized,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=self._max_drawdown,
            total_trades=len(self.trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_trade_pnl=np.mean(pnls) if pnls else 0.0,
            edge_per_contract=edge_per_contract,
            kelly_optimal=kelly,
            final_equity=self.capital,
            peak_equity=self._peak_equity,
        )

    def print_report(self, metrics: BacktestMetrics) -> str:
        """Generate formatted backtest report."""
        lines = [
            "=" * 60,
            "BACKTEST PERFORMANCE REPORT",
            "=" * 60,
            "",
            "RETURNS",
            "-" * 30,
            f"Total Return:      {metrics.total_return:>10.2%}",
            f"Annualized Return: {metrics.annualized_return:>10.2%}",
            f"Final Equity:      ${metrics.final_equity:>9,.2f}",
            f"Peak Equity:       ${metrics.peak_equity:>9,.2f}",
            "",
            "RISK METRICS",
            "-" * 30,
            f"Sharpe Ratio:      {metrics.sharpe_ratio:>10.2f}",
            f"Sortino Ratio:     {metrics.sortino_ratio:>10.2f}",
            f"Max Drawdown:      {metrics.max_drawdown:>10.2%}",
            "",
            "TRADE STATISTICS",
            "-" * 30,
            f"Total Trades:      {metrics.total_trades:>10}",
            f"Winning Trades:    {metrics.winning_trades:>10}",
            f"Losing Trades:     {metrics.losing_trades:>10}",
            f"Win Rate:          {metrics.win_rate:>10.1%}",
            "",
            "PROFITABILITY",
            "-" * 30,
            f"Profit Factor:     {metrics.profit_factor:>10.2f}",
            f"Avg Win:           ${metrics.avg_win:>9.2f}",
            f"Avg Loss:          ${metrics.avg_loss:>9.2f}",
            f"Edge/Contract:     ${metrics.edge_per_contract:>9.4f}",
            "",
            "POSITION SIZING",
            "-" * 30,
            f"Kelly Optimal:     {metrics.kelly_optimal:>10.2%}",
            "=" * 60,
        ]
        return "\n".join(lines)
