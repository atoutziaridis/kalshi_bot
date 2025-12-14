"""Backtesting engine for strategy validation."""
from __future__ import annotations


import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from kalshi_arb.backtest.simulator import TradeSimulator, SimulatedFill
from kalshi_arb.engine.constraint_engine import ConstraintEngine
from kalshi_arb.models.signal import DirectionalSignal
from kalshi_arb.risk.position_sizer import PositionSizer, SizingConfig
from kalshi_arb.signals.signal_generator import SignalGenerator

logger = logging.getLogger(__name__)


class BacktestConfig(BaseModel):
    """Backtesting configuration."""

    initial_capital: float = 10000.0
    start_date: datetime | None = None
    end_date: datetime | None = None
    min_edge_threshold: float = 0.01
    kelly_fraction: float = 0.25
    max_position_pct: float = 0.05


class TradeRecord(BaseModel):
    """Record of a single trade."""

    timestamp: datetime
    ticker: str
    direction: str
    entry_price: float
    exit_price: float | None = None
    quantity: int
    pnl: float = 0.0
    fees: float = 0.0
    resolved: bool = False
    resolution: str | None = None


class BacktestResult(BaseModel):
    """Results of a backtest run."""

    config: BacktestConfig
    start_date: datetime
    end_date: datetime

    initial_capital: float
    final_capital: float
    total_return: float
    total_pnl: float

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float

    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0

    sharpe_ratio: float = 0.0

    trades: list[TradeRecord] = Field(default_factory=list)
    equity_curve: list[tuple[datetime, float]] = Field(default_factory=list)


class Backtester:
    """
    Backtest trading strategies on historical data.

    Supports:
    - Constraint-based signal generation
    - Realistic execution simulation
    - Performance metrics calculation
    """

    def __init__(self, config: BacktestConfig | None = None):
        self.config = config or BacktestConfig()
        self.simulator = TradeSimulator()
        self.constraint_engine = ConstraintEngine()
        self.position_sizer = PositionSizer(
            SizingConfig(
                kelly_fraction=self.config.kelly_fraction,
                max_position_per_market=self.config.max_position_pct,
            )
        )
        self.signal_generator = SignalGenerator(
            constraint_engine=self.constraint_engine,
            min_edge_threshold=self.config.min_edge_threshold,
        )

        self._capital = self.config.initial_capital
        self._trades: list[TradeRecord] = []
        self._equity_curve: list[tuple[datetime, float]] = []
        self._peak_capital = self.config.initial_capital
        self._max_drawdown = 0.0

    def load_data(self, data_path: Path) -> pd.DataFrame:
        """Load historical market data."""
        if data_path.suffix == ".csv":
            return pd.read_csv(data_path, parse_dates=["timestamp"])
        elif data_path.suffix == ".parquet":
            return pd.read_parquet(data_path)
        else:
            raise ValueError(f"Unsupported file format: {data_path.suffix}")

    def run(
        self,
        price_data: pd.DataFrame,
        resolution_data: dict[str, bool] | None = None,
    ) -> BacktestResult:
        """
        Run backtest on historical data.

        Args:
            price_data: DataFrame with columns [timestamp, ticker, price]
            resolution_data: Dict mapping ticker to resolution (True=YES won)

        Returns:
            BacktestResult with performance metrics
        """
        resolution_data = resolution_data or {}

        self._capital = self.config.initial_capital
        self._trades = []
        self._equity_curve = []
        self._peak_capital = self.config.initial_capital
        self._max_drawdown = 0.0

        timestamps = price_data["timestamp"].unique()
        timestamps = sorted(timestamps)

        open_positions: dict[str, SimulatedFill] = {}

        for ts in timestamps:
            ts_data = price_data[price_data["timestamp"] == ts]
            prices = dict(zip(ts_data["ticker"], ts_data["price"]))

            signals = self._generate_signals_from_prices(prices, ts)

            for signal in signals[:5]:
                if signal.ticker in open_positions:
                    continue

                dollar_size, num_contracts = self.position_sizer.size_signal(
                    signal,
                    self._capital,
                    correlated_positions=len(open_positions),
                )

                if num_contracts < 1:
                    continue

                fill = self.simulator.simulate_order(
                    signal=signal,
                    quantity=num_contracts,
                )

                if fill:
                    open_positions[signal.ticker] = fill
                    self._capital -= fill.fill_price * fill.filled_quantity + fill.fee

            self._update_equity(ts, open_positions, prices)

        for ticker, fill in open_positions.items():
            resolved_yes = resolution_data.get(ticker, False)
            pnl = self.simulator.calculate_resolution_pnl(fill, resolved_yes)
            self._capital += pnl + fill.fill_price * fill.filled_quantity

            self._trades.append(TradeRecord(
                timestamp=fill.timestamp,
                ticker=ticker,
                direction=fill.side.value,
                entry_price=fill.fill_price,
                quantity=fill.filled_quantity,
                pnl=pnl,
                fees=fill.fee,
                resolved=True,
                resolution="yes" if resolved_yes else "no",
            ))

        return self._calculate_results()

    def _generate_signals_from_prices(
        self,
        prices: dict[str, float],
        timestamp: datetime,
    ) -> list[DirectionalSignal]:
        """Generate signals from price snapshot."""
        from kalshi_arb.models.market import Market

        markets = []
        for ticker, price in prices.items():
            market = Market(
                ticker=ticker,
                last_price=int(price * 100),
                yes_bid=int(price * 100) - 1,
                yes_ask=int(price * 100) + 1,
            )
            markets.append(market)

        return self.signal_generator.generate_signals(markets)

    def _update_equity(
        self,
        timestamp: datetime,
        positions: dict[str, SimulatedFill],
        prices: dict[str, float],
    ) -> None:
        """Update equity curve with current value."""
        position_value = 0.0
        for ticker, fill in positions.items():
            current_price = prices.get(ticker, fill.fill_price)
            if fill.side.value == "yes":
                position_value += current_price * fill.filled_quantity
            else:
                position_value += (1 - current_price) * fill.filled_quantity

        total_equity = self._capital + position_value
        self._equity_curve.append((timestamp, total_equity))

        if total_equity > self._peak_capital:
            self._peak_capital = total_equity

        if self._peak_capital > 0:
            drawdown = (self._peak_capital - total_equity) / self._peak_capital
            self._max_drawdown = max(self._max_drawdown, drawdown)

    def _calculate_results(self) -> BacktestResult:
        """Calculate final backtest results."""
        total_pnl = sum(t.pnl for t in self._trades)
        wins = [t for t in self._trades if t.pnl > 0]
        losses = [t for t in self._trades if t.pnl < 0]

        win_rate = len(wins) / len(self._trades) if self._trades else 0.0
        avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(t.pnl for t in losses) / len(losses)) if losses else 0.0
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 0.0

        start_date = self._equity_curve[0][0] if self._equity_curve else datetime.now()
        end_date = self._equity_curve[-1][0] if self._equity_curve else datetime.now()

        return BacktestResult(
            config=self.config,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.config.initial_capital,
            final_capital=self._capital,
            total_return=(self._capital - self.config.initial_capital) / self.config.initial_capital,
            total_pnl=total_pnl,
            total_trades=len(self._trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            max_drawdown=self._max_drawdown,
            trades=self._trades,
            equity_curve=self._equity_curve,
        )

    def print_report(self, result: BacktestResult) -> str:
        """Generate printable backtest report."""
        lines = [
            "=" * 50,
            "BACKTEST REPORT",
            "=" * 50,
            f"Period: {result.start_date} to {result.end_date}",
            "",
            f"Initial Capital: ${result.initial_capital:,.2f}",
            f"Final Capital: ${result.final_capital:,.2f}",
            f"Total Return: {result.total_return:.2%}",
            f"Total P&L: ${result.total_pnl:,.2f}",
            "",
            f"Total Trades: {result.total_trades}",
            f"Winning Trades: {result.winning_trades}",
            f"Losing Trades: {result.losing_trades}",
            f"Win Rate: {result.win_rate:.1%}",
            "",
            f"Avg Win: ${result.avg_win:.2f}",
            f"Avg Loss: ${result.avg_loss:.2f}",
            f"Profit Factor: {result.profit_factor:.2f}",
            f"Max Drawdown: {result.max_drawdown:.1%}",
            "=" * 50,
        ]
        return "\n".join(lines)
