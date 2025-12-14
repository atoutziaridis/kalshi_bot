"""Backtesting framework module."""
from __future__ import annotations

from kalshi_arb.backtest.backtester import Backtester
from kalshi_arb.backtest.data_fetcher import KalshiDataFetcher
from kalshi_arb.backtest.event_simulator import (
    EventDrivenBacktester,
    MarketState,
    Signal,
    Side,
    BacktestMetrics,
)
from kalshi_arb.backtest.monte_carlo import MonteCarloValidator, MonteCarloResult
from kalshi_arb.backtest.simulator import TradeSimulator

__all__ = [
    "Backtester",
    "TradeSimulator",
    "KalshiDataFetcher",
    "EventDrivenBacktester",
    "MarketState",
    "Signal",
    "Side",
    "BacktestMetrics",
    "MonteCarloValidator",
    "MonteCarloResult",
]
