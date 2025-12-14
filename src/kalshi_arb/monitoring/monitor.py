"""System monitoring and status tracking."""
from __future__ import annotations


import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from kalshi_arb.models.position import Position
from kalshi_arb.models.signal import DirectionalSignal
from kalshi_arb.risk.risk_manager import RiskMetrics

logger = logging.getLogger(__name__)


class SystemStatus(BaseModel):
    """Current system status."""

    is_running: bool = False
    is_paused: bool = False
    started_at: datetime | None = None
    last_scan_at: datetime | None = None

    markets_monitored: int = 0
    constraints_active: int = 0

    signals_generated: int = 0
    signals_executed: int = 0

    current_positions: int = 0
    total_pnl: float = 0.0


class PerformanceMetrics(BaseModel):
    """Trading performance metrics."""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0

    total_pnl: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0

    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0

    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0


class Monitor:
    """
    System monitoring and performance tracking.

    Tracks:
    - System status
    - Position P&L
    - Signal history
    - Performance metrics
    """

    def __init__(self, log_dir: Path | None = None):
        self.log_dir = log_dir
        self._status = SystemStatus()
        self._positions: dict[str, Position] = {}
        self._signal_history: list[DirectionalSignal] = []
        self._trade_history: list[dict] = []
        self._risk_history: list[RiskMetrics] = []

    def start(self) -> None:
        """Mark system as started."""
        self._status.is_running = True
        self._status.is_paused = False
        self._status.started_at = datetime.now()
        logger.info("Monitor started")

    def stop(self) -> None:
        """Mark system as stopped."""
        self._status.is_running = False
        logger.info("Monitor stopped")

    def pause(self) -> None:
        """Pause monitoring."""
        self._status.is_paused = True
        logger.info("Monitor paused")

    def resume(self) -> None:
        """Resume monitoring."""
        self._status.is_paused = False
        logger.info("Monitor resumed")

    def record_scan(
        self,
        markets_count: int,
        constraints_count: int,
    ) -> None:
        """Record a market scan."""
        self._status.last_scan_at = datetime.now()
        self._status.markets_monitored = markets_count
        self._status.constraints_active = constraints_count

    def record_signal(self, signal: DirectionalSignal) -> None:
        """Record a generated signal."""
        self._signal_history.append(signal)
        self._status.signals_generated += 1

        if len(self._signal_history) > 1000:
            self._signal_history = self._signal_history[-500:]

    def record_execution(
        self,
        signal: DirectionalSignal,
        success: bool,
        order_id: str = "",
    ) -> None:
        """Record an execution attempt."""
        if success:
            self._status.signals_executed += 1

        self._trade_history.append({
            "timestamp": datetime.now().isoformat(),
            "ticker": signal.ticker,
            "direction": signal.direction.value,
            "edge": signal.net_edge,
            "success": success,
            "order_id": order_id,
        })

    def update_positions(self, positions: list[Position]) -> None:
        """Update current positions."""
        self._positions = {p.ticker: p for p in positions}
        self._status.current_positions = len(positions)
        self._status.total_pnl = sum(p.total_pnl for p in positions)

    def record_risk_metrics(self, metrics: RiskMetrics) -> None:
        """Record risk metrics snapshot."""
        self._risk_history.append(metrics)

        if len(self._risk_history) > 1000:
            self._risk_history = self._risk_history[-500:]

    def get_status(self) -> SystemStatus:
        """Get current system status."""
        return self._status.model_copy()

    def get_positions(self) -> list[Position]:
        """Get current positions."""
        return list(self._positions.values())

    def get_performance(self) -> PerformanceMetrics:
        """Calculate performance metrics."""
        metrics = PerformanceMetrics()

        if not self._trade_history:
            return metrics

        successful = [t for t in self._trade_history if t["success"]]
        metrics.total_trades = len(successful)

        pnl_list = []
        for position in self._positions.values():
            pnl_list.append(position.total_pnl)
            if position.total_pnl > 0:
                metrics.winning_trades += 1
            elif position.total_pnl < 0:
                metrics.losing_trades += 1

        metrics.total_pnl = sum(pnl_list)
        metrics.realized_pnl = sum(p.realized_pnl for p in self._positions.values())
        metrics.unrealized_pnl = sum(p.unrealized_pnl for p in self._positions.values())

        if metrics.total_trades > 0:
            metrics.win_rate = metrics.winning_trades / metrics.total_trades

        wins = [p for p in pnl_list if p > 0]
        losses = [p for p in pnl_list if p < 0]

        if wins:
            metrics.avg_win = sum(wins) / len(wins)
        if losses:
            metrics.avg_loss = abs(sum(losses) / len(losses))

        if metrics.avg_loss > 0:
            metrics.profit_factor = metrics.avg_win / metrics.avg_loss

        if self._risk_history:
            metrics.max_drawdown = max(r.max_drawdown for r in self._risk_history)

        return metrics

    def get_recent_signals(self, limit: int = 20) -> list[DirectionalSignal]:
        """Get recent signals."""
        return self._signal_history[-limit:]

    def get_trade_history(self, limit: int = 100) -> list[dict]:
        """Get trade history."""
        return self._trade_history[-limit:]

    def export_state(self) -> dict:
        """Export current state for persistence."""
        return {
            "status": self._status.model_dump(),
            "positions": [p.model_dump() for p in self._positions.values()],
            "trade_count": len(self._trade_history),
            "signal_count": len(self._signal_history),
        }

    def save_state(self, path: Path | None = None) -> None:
        """Save state to file."""
        save_path = path or (self.log_dir / "monitor_state.json" if self.log_dir else None)
        if not save_path:
            return

        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(json.dumps(self.export_state(), indent=2, default=str))

    def print_status(self) -> str:
        """Generate status string for CLI display."""
        status = self._status
        perf = self.get_performance()

        lines = [
            "=" * 50,
            "KALSHI ARB MONITOR",
            "=" * 50,
            f"Status: {'RUNNING' if status.is_running else 'STOPPED'}",
            f"Started: {status.started_at or 'N/A'}",
            f"Last Scan: {status.last_scan_at or 'N/A'}",
            "",
            f"Markets: {status.markets_monitored}",
            f"Constraints: {status.constraints_active}",
            f"Positions: {status.current_positions}",
            "",
            f"Signals Generated: {status.signals_generated}",
            f"Signals Executed: {status.signals_executed}",
            "",
            f"Total P&L: ${perf.total_pnl:.2f}",
            f"Win Rate: {perf.win_rate:.1%}",
            f"Max Drawdown: {perf.max_drawdown:.1%}",
            "=" * 50,
        ]

        return "\n".join(lines)
