"""Daemon service for 24/7 automated trading."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

from kalshi_arb.bot import BotConfig, TradingBot
from kalshi_arb.profit_taker import ProfitTaker, ProfitTakerConfig

logger = logging.getLogger(__name__)

PID_FILE = Path.home() / ".kalshi_bot.pid"
LOG_FILE = Path.home() / ".kalshi_bot.log"


class TradingDaemon:
    """
    Daemon wrapper for 24/7 automated trading.

    Features:
    - Runs as background process
    - Auto-restarts on failure
    - Graceful shutdown on signals
    - Profit-taking integration
    - Health monitoring
    """

    def __init__(
        self,
        bot_config: BotConfig,
        profit_config: ProfitTakerConfig | None = None,
        max_restarts: int = 10,
        restart_delay: float = 30.0,
    ):
        self.bot_config = bot_config
        self.profit_config = profit_config or ProfitTakerConfig()
        self.max_restarts = max_restarts
        self.restart_delay = restart_delay

        self._bot: TradingBot | None = None
        self._profit_taker: ProfitTaker | None = None
        self._running = False
        self._restart_count = 0
        self._last_restart: datetime | None = None

    async def start(self) -> None:
        """Start the daemon."""
        self._running = True
        self._write_pid()
        self._setup_signal_handlers()

        logger.info("Trading daemon starting...")
        logger.info(f"PID file: {PID_FILE}")

        while self._running and self._restart_count < self.max_restarts:
            try:
                await self._run_bot()
            except Exception as e:
                logger.error(f"Bot crashed: {e}")
                self._restart_count += 1
                self._last_restart = datetime.now()

                if self._restart_count < self.max_restarts:
                    logger.info(
                        f"Restarting in {self.restart_delay}s "
                        f"(attempt {self._restart_count}/{self.max_restarts})"
                    )
                    await asyncio.sleep(self.restart_delay)
                else:
                    logger.critical("Max restarts exceeded, stopping daemon")

        self._cleanup()

    async def stop(self) -> None:
        """Stop the daemon gracefully."""
        logger.info("Stopping trading daemon...")
        self._running = False

        if self._bot:
            await self._bot.stop()

        self._cleanup()

    async def _run_bot(self) -> None:
        """Run the trading bot with profit-taking."""
        self._bot = TradingBot(self.bot_config)
        self._profit_taker = ProfitTaker(self.profit_config)

        logger.info("Bot initialized, starting main loop...")

        self._bot._running = True
        self._bot._paused = False
        self._bot.monitor.start()

        if self._bot.config.api_key:
            if self._bot.client.login():
                logger.info("Authenticated with Kalshi")
                await self._bot._update_account_balance()
            else:
                logger.warning("Auth failed, running in read-only mode")

        while self._running and self._bot._running:
            try:
                await self._bot._scan_cycle()
                await self._check_profit_taking()
                await asyncio.sleep(self._bot.config.scan_interval)
            except Exception as e:
                logger.error(f"Error in scan cycle: {e}")
                await asyncio.sleep(5)

    async def _check_profit_taking(self) -> None:
        """Check positions for profit-taking opportunities."""
        if not self._bot or not self._profit_taker:
            return

        positions = self._bot._positions
        if not positions:
            return

        current_prices = {}
        for pos in positions:
            market = self._bot._markets.get(pos.ticker)
            if market:
                current_prices[pos.ticker] = market.last_price_decimal

        actions = self._profit_taker.check_positions(positions, current_prices)

        for action in actions:
            logger.info(
                f"Profit-take action: {action.action} {action.ticker} "
                f"({action.reason})"
            )

            if self._bot.config.paper_trading:
                logger.info(f"[PAPER] Would close {action.quantity} contracts")
                continue

            try:
                market = self._bot._markets.get(action.ticker)
                if not market:
                    continue

                pos = next(
                    (p for p in positions if p.ticker == action.ticker),
                    None,
                )
                if not pos:
                    continue

                exit_side = "no" if pos.side.value == "yes" else "yes"
                exit_price = int(market.last_price_decimal * 100)

                self._bot.client.place_order(
                    ticker=action.ticker,
                    side=exit_side,
                    action="buy",
                    count=action.quantity,
                    price=exit_price,
                )
                logger.info(f"Profit-take order placed for {action.ticker}")

            except Exception as e:
                logger.error(f"Failed to execute profit-take: {e}")

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        def handle_signal(signum, frame):
            logger.info(f"Received signal {signum}")
            self._running = False

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

    def _write_pid(self) -> None:
        """Write PID file for daemon management."""
        try:
            PID_FILE.write_text(str(os.getpid()))
        except Exception as e:
            logger.warning(f"Failed to write PID file: {e}")

    def _cleanup(self) -> None:
        """Cleanup on shutdown."""
        try:
            if PID_FILE.exists():
                PID_FILE.unlink()
        except Exception as e:
            logger.warning(f"Failed to remove PID file: {e}")

    def get_status(self) -> dict:
        """Get daemon status."""
        return {
            "running": self._running,
            "restart_count": self._restart_count,
            "last_restart": (
                self._last_restart.isoformat() if self._last_restart else None
            ),
            "bot_status": self._bot.get_status() if self._bot else None,
            "profit_taker": (
                self._profit_taker.get_summary() if self._profit_taker else None
            ),
        }


def setup_logging(log_file: Path | None = None, level: str = "INFO") -> None:
    """Setup logging for daemon."""
    handlers = [logging.StreamHandler(sys.stdout)]

    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )


def is_daemon_running() -> tuple[bool, int | None]:
    """Check if daemon is already running."""
    if not PID_FILE.exists():
        return False, None

    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True, pid
    except (ProcessLookupError, ValueError):
        PID_FILE.unlink(missing_ok=True)
        return False, None


def stop_daemon() -> bool:
    """Stop running daemon."""
    running, pid = is_daemon_running()
    if not running or pid is None:
        print("Daemon is not running")
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to daemon (PID {pid})")
        return True
    except Exception as e:
        print(f"Failed to stop daemon: {e}")
        return False


async def run_daemon(
    api_key: str = "",
    api_secret: str = "",
    paper_trading: bool = True,
    take_profit_pct: float = 0.15,
    stop_loss_pct: float = 0.10,
    trailing_stop_pct: float = 0.05,
    scan_interval: float = 2.0,
) -> None:
    """Run the trading daemon."""
    running, pid = is_daemon_running()
    if running:
        print(f"Daemon already running (PID {pid})")
        return

    setup_logging(LOG_FILE)

    bot_config = BotConfig(
        api_key=api_key,
        api_secret=api_secret,
        paper_trading=paper_trading,
        scan_interval=scan_interval,
    )

    profit_config = ProfitTakerConfig(
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
        trailing_stop_pct=trailing_stop_pct,
    )

    daemon = TradingDaemon(bot_config, profit_config)

    try:
        await daemon.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        await daemon.stop()


def main() -> None:
    """CLI entry point for daemon."""
    from dotenv import load_dotenv

    load_dotenv()

    import argparse

    parser = argparse.ArgumentParser(description="Kalshi Trading Daemon")
    parser.add_argument(
        "command",
        choices=["start", "stop", "status"],
        help="Daemon command",
    )
    parser.add_argument(
        "--paper",
        action="store_true",
        default=True,
        help="Paper trading mode (default: True)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Live trading mode",
    )
    parser.add_argument(
        "--take-profit",
        type=float,
        default=0.15,
        help="Take profit percentage (default: 0.15)",
    )
    parser.add_argument(
        "--stop-loss",
        type=float,
        default=0.10,
        help="Stop loss percentage (default: 0.10)",
    )
    parser.add_argument(
        "--trailing-stop",
        type=float,
        default=0.05,
        help="Trailing stop percentage (default: 0.05)",
    )

    args = parser.parse_args()

    if args.command == "stop":
        stop_daemon()
        return

    if args.command == "status":
        running, pid = is_daemon_running()
        if running:
            print(f"Daemon is running (PID {pid})")
            print(f"Log file: {LOG_FILE}")
        else:
            print("Daemon is not running")
        return

    if args.command == "start":
        paper_trading = not args.live

        asyncio.run(
            run_daemon(
                api_key=os.getenv("KALSHI_API_KEY", ""),
                api_secret=os.getenv("KALSHI_API_SECRET", ""),
                paper_trading=paper_trading,
                take_profit_pct=args.take_profit,
                stop_loss_pct=args.stop_loss,
                trailing_stop_pct=args.trailing_stop,
            )
        )


if __name__ == "__main__":
    main()
