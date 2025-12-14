"""Kalshi Arbitrage Trading System.

A trading system that exploits logical constraint violations in Kalshi
prediction markets using static arbitrage principles.
"""
from __future__ import annotations

__version__ = "0.1.0"

from kalshi_arb.bot import TradingBot, BotConfig, run_bot
from kalshi_arb.profit_taker import ProfitTaker, ProfitTakerConfig
from kalshi_arb.daemon import TradingDaemon, run_daemon

__all__ = [
    "TradingBot",
    "BotConfig",
    "run_bot",
    "ProfitTaker",
    "ProfitTakerConfig",
    "TradingDaemon",
    "run_daemon",
]
