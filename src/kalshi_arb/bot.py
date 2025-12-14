"""Main trading bot integrating all components."""
from __future__ import annotations


import asyncio
import logging
from datetime import datetime
from pathlib import Path

from kalshi_arb.api.client import KalshiClient
from kalshi_arb.engine.constraint_engine import ConstraintEngine
from kalshi_arb.execution.execution_engine import ExecutionEngine
from kalshi_arb.models.market import Market
from kalshi_arb.models.position import Position
from kalshi_arb.monitoring.alerts import AlertManager
from kalshi_arb.monitoring.monitor import Monitor
from kalshi_arb.risk.position_sizer import PositionSizer, SizingConfig
from kalshi_arb.risk.risk_manager import RiskManager, RiskConfig, DrawdownAction
from kalshi_arb.signals.rebalancing_detector import RebalancingDetector
from kalshi_arb.signals.signal_generator import SignalGenerator

logger = logging.getLogger(__name__)


class BotConfig:
    """Trading bot configuration."""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        paper_trading: bool = True,
        scan_interval: float = 2.0,
        min_edge_threshold: float = 0.01,
        constraints_path: Path | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper_trading = paper_trading
        self.scan_interval = scan_interval
        self.min_edge_threshold = min_edge_threshold
        self.constraints_path = constraints_path


class TradingBot:
    """
    Main trading bot orchestrating all components.

    Architecture:
    Kalshi Markets → Constraint Engine → Probability Bounds →
    Signal Generator → Position Sizer → Execution Engine
    """

    def __init__(self, config: BotConfig):
        self.config = config
        self._running = False
        self._paused = False

        self.client = KalshiClient(
            api_key=config.api_key,
            api_secret=config.api_secret,
        )

        self.constraint_engine = ConstraintEngine(
            storage_path=config.constraints_path,
        )

        self.rebalancing_detector = RebalancingDetector(
            min_profit_threshold=config.min_edge_threshold,
        )

        self.signal_generator = SignalGenerator(
            constraint_engine=self.constraint_engine,
            min_edge_threshold=config.min_edge_threshold,
        )

        self.position_sizer = PositionSizer(SizingConfig())
        self.risk_manager = RiskManager(RiskConfig())

        self.execution_engine = ExecutionEngine(
            client=self.client,
            position_sizer=self.position_sizer,
            paper_trading=config.paper_trading,
        )

        self.monitor = Monitor()
        self.alert_manager = AlertManager()

        self._markets: dict[str, Market] = {}
        self._positions: list[Position] = []
        self._account_balance: float = 10000.0

    async def start(self) -> None:
        """Start the trading bot."""
        logger.info("Starting trading bot...")
        self._running = True
        self._paused = False
        self.monitor.start()

        if self.config.api_key:
            if self.client.login():
                logger.info("Authenticated with Kalshi")
                await self._update_account_balance()
            else:
                logger.warning("Authentication failed, running in read-only mode")

        await self._run_main_loop()

    async def stop(self) -> None:
        """Stop the trading bot."""
        logger.info("Stopping trading bot...")
        self._running = False

        cancelled = self.execution_engine.cancel_all_pending()
        if cancelled:
            logger.info(f"Cancelled {cancelled} pending orders")

        self.monitor.stop()
        self.client.close()

    async def pause(self) -> None:
        """Pause trading (continue monitoring)."""
        logger.info("Pausing trading...")
        self._paused = True
        self.monitor.pause()

    async def resume(self) -> None:
        """Resume trading."""
        logger.info("Resuming trading...")
        self._paused = False
        self.monitor.resume()

    async def _run_main_loop(self) -> None:
        """Main trading loop."""
        while self._running:
            try:
                await self._scan_cycle()
                await asyncio.sleep(self.config.scan_interval)
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(5)

    async def _scan_cycle(self) -> None:
        """Single scan cycle."""
        await self._fetch_markets()

        self.monitor.record_scan(
            markets_count=len(self._markets),
            constraints_count=len(self.constraint_engine.get_all_constraints()),
        )

        signals = self._generate_signals()

        for signal in signals:
            self.monitor.record_signal(signal)

            if self._paused:
                continue

            approved, reason = self.risk_manager.approve_signal(
                signal=signal,
                proposed_size=self._calculate_proposed_size(signal),
                current_positions=self._positions,
                account_value=self._account_balance,
            )

            if not approved:
                logger.debug(f"Signal rejected: {reason}")
                continue

            correlated = self._count_correlated_positions(signal.ticker)

            result, order = self.execution_engine.execute_signal(
                signal=signal,
                account_balance=self._account_balance,
                correlated_positions=correlated,
            )

            self.monitor.record_execution(
                signal=signal,
                success=order is not None and order.is_complete,
                order_id=order.id if order else "",
            )

        await self._update_risk_metrics()

    async def _fetch_markets(self) -> None:
        """Fetch current market data."""
        try:
            response = self.client.get_markets(limit=1000, status="open")
            markets = response.get("markets", [])

            self._markets = {}
            for m in markets:
                market = Market.from_api_response({"market": m})
                self._markets[market.ticker] = market

        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")

    def _generate_signals(self) -> list:
        """Generate trading signals from current market state."""
        markets = list(self._markets.values())

        spreads = {
            m.ticker: m.spread_decimal
            for m in markets
        }

        signals = self.signal_generator.generate_signals(markets, spreads)

        signals = self.signal_generator.filter_by_execution_rules(
            signals,
            self._markets,
        )

        return self.signal_generator.rank_signals(signals)[:10]

    def _calculate_proposed_size(self, signal) -> float:
        """Calculate proposed position size for risk approval."""
        dollar_size, _ = self.position_sizer.size_signal(
            signal,
            self._account_balance,
            correlated_positions=0,
        )
        return dollar_size

    def _count_correlated_positions(self, ticker: str) -> int:
        """Count positions correlated with ticker."""
        series = ticker.split("-")[0] if "-" in ticker else ""
        count = 0
        for pos in self._positions:
            pos_series = pos.ticker.split("-")[0] if "-" in pos.ticker else ""
            if pos_series == series:
                count += 1
        return count

    async def _update_account_balance(self) -> None:
        """Update account balance from API."""
        try:
            response = self.client.get_balance()
            self._account_balance = response.get("balance", 10000) / 100
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")

    async def _update_risk_metrics(self) -> None:
        """Update risk metrics and check for actions."""
        metrics = self.risk_manager.calculate_portfolio_risk(
            positions=self._positions,
            account_value=self._account_balance,
        )

        self.monitor.record_risk_metrics(metrics)

        self.alert_manager.check_drawdown(
            current_drawdown=metrics.current_drawdown,
        )

        if metrics.drawdown_action == DrawdownAction.STOP:
            await self.pause()
            self.alert_manager.create_alert(
                level=self.alert_manager.AlertLevel.CRITICAL,
                title="Trading Stopped",
                message="Drawdown exceeded stop threshold",
            )

    def get_status(self) -> dict:
        """Get current bot status."""
        return {
            "running": self._running,
            "paused": self._paused,
            "markets": len(self._markets),
            "positions": len(self._positions),
            "balance": self._account_balance,
            "paper_trading": self.config.paper_trading,
        }

    def print_status(self) -> str:
        """Print formatted status."""
        return self.monitor.print_status()


async def run_bot(config: BotConfig) -> None:
    """Run the trading bot."""
    bot = TradingBot(config)

    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        await bot.stop()


def main() -> None:
    """Entry point for the trading bot."""
    import os
    from dotenv import load_dotenv

    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    config = BotConfig(
        api_key=os.getenv("KALSHI_API_KEY", ""),
        api_secret=os.getenv("KALSHI_API_SECRET", ""),
        paper_trading=True,
        scan_interval=2.0,
    )

    asyncio.run(run_bot(config))


if __name__ == "__main__":
    main()
