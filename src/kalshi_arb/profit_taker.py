"""Profit-taking mechanism for automatic position management."""
from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from kalshi_arb.models.position import Position, OrderSide

logger = logging.getLogger(__name__)


class TakeProfitStrategy(str, Enum):
    """Profit-taking strategy types."""

    FIXED_PERCENT = "fixed_percent"
    TRAILING_STOP = "trailing_stop"
    TIERED = "tiered"


class ProfitTakerConfig(BaseModel):
    """Configuration for profit-taking."""

    enabled: bool = True

    take_profit_pct: float = Field(
        default=0.15,
        description="Close position when profit reaches this percentage (15% default)",
    )

    stop_loss_pct: float = Field(
        default=0.10,
        description="Close position when loss reaches this percentage (10% default)",
    )

    trailing_stop_pct: float = Field(
        default=0.05,
        description="Trailing stop percentage from peak profit (5% default)",
    )

    use_trailing_stop: bool = Field(
        default=True,
        description="Enable trailing stop after hitting initial profit target",
    )

    tiered_targets: list[tuple[float, float]] = Field(
        default=[(0.10, 0.25), (0.20, 0.50), (0.30, 0.75)],
        description="Tiered profit targets: (profit_pct, close_fraction)",
    )

    min_hold_seconds: int = Field(
        default=60,
        description="Minimum time to hold position before taking profit",
    )

    check_interval_seconds: float = Field(
        default=5.0,
        description="How often to check positions for profit-taking",
    )


class PositionTracker(BaseModel):
    """Track position state for profit-taking decisions."""

    ticker: str
    side: OrderSide
    entry_price: float
    entry_time: datetime
    quantity: int

    peak_price: float = 0.0
    peak_profit_pct: float = 0.0

    tiers_closed: list[int] = Field(default_factory=list)
    trailing_stop_active: bool = False
    trailing_stop_price: float = 0.0

    def update_peak(self, current_price: float) -> None:
        """Update peak price and profit tracking."""
        profit_pct = self.calculate_profit_pct(current_price)

        if profit_pct > self.peak_profit_pct:
            self.peak_profit_pct = profit_pct
            self.peak_price = current_price

    def calculate_profit_pct(self, current_price: float) -> float:
        """Calculate current profit percentage."""
        if self.side == OrderSide.YES:
            return (current_price - self.entry_price) / self.entry_price
        else:
            return (self.entry_price - current_price) / self.entry_price


class ProfitTakeAction(BaseModel):
    """Action to take for profit-taking."""

    ticker: str
    action: str  # "close_full", "close_partial", "set_trailing", "stop_loss"
    quantity: int
    reason: str
    current_profit_pct: float
    target_price: float | None = None


class ProfitTaker:
    """
    Automatic profit-taking and stop-loss management.

    Features:
    - Fixed percentage take-profit
    - Trailing stop after hitting profit target
    - Tiered profit-taking (close portions at different levels)
    - Stop-loss protection
    """

    def __init__(self, config: ProfitTakerConfig | None = None):
        self.config = config or ProfitTakerConfig()
        self._tracked_positions: dict[str, PositionTracker] = {}
        self._closed_positions: list[dict] = []

    def track_position(
        self,
        position: Position,
        entry_time: datetime | None = None,
    ) -> None:
        """Start tracking a position for profit-taking."""
        if position.ticker in self._tracked_positions:
            return

        tracker = PositionTracker(
            ticker=position.ticker,
            side=position.side,
            entry_price=position.average_price,
            entry_time=entry_time or datetime.now(),
            quantity=position.quantity,
            peak_price=position.average_price,
        )

        self._tracked_positions[position.ticker] = tracker
        logger.info(f"Tracking position: {position.ticker} @ {position.average_price:.2f}")

    def untrack_position(self, ticker: str) -> None:
        """Stop tracking a position."""
        if ticker in self._tracked_positions:
            del self._tracked_positions[ticker]

    def check_positions(
        self,
        positions: list[Position],
        current_prices: dict[str, float],
    ) -> list[ProfitTakeAction]:
        """
        Check all tracked positions and return actions to take.

        Args:
            positions: Current open positions
            current_prices: Dict of ticker -> current price

        Returns:
            List of profit-taking actions to execute
        """
        if not self.config.enabled:
            return []

        actions = []

        for position in positions:
            if position.ticker not in self._tracked_positions:
                self.track_position(position)

            current_price = current_prices.get(position.ticker)
            if current_price is None:
                continue

            action = self._evaluate_position(position, current_price)
            if action:
                actions.append(action)

        tickers_to_remove = [
            ticker for ticker in self._tracked_positions
            if ticker not in {p.ticker for p in positions}
        ]
        for ticker in tickers_to_remove:
            self.untrack_position(ticker)

        return actions

    def _evaluate_position(
        self,
        position: Position,
        current_price: float,
    ) -> ProfitTakeAction | None:
        """Evaluate a single position for profit-taking."""
        tracker = self._tracked_positions.get(position.ticker)
        if not tracker:
            return None

        hold_time = (datetime.now() - tracker.entry_time).total_seconds()
        if hold_time < self.config.min_hold_seconds:
            return None

        tracker.update_peak(current_price)
        profit_pct = tracker.calculate_profit_pct(current_price)

        if profit_pct <= -self.config.stop_loss_pct:
            return ProfitTakeAction(
                ticker=position.ticker,
                action="stop_loss",
                quantity=position.quantity,
                reason=f"Stop loss triggered at {profit_pct:.1%}",
                current_profit_pct=profit_pct,
            )

        if tracker.trailing_stop_active:
            drawdown_from_peak = tracker.peak_profit_pct - profit_pct
            if drawdown_from_peak >= self.config.trailing_stop_pct:
                return ProfitTakeAction(
                    ticker=position.ticker,
                    action="close_full",
                    quantity=position.quantity,
                    reason=f"Trailing stop: {drawdown_from_peak:.1%} from peak",
                    current_profit_pct=profit_pct,
                )

        if profit_pct >= self.config.take_profit_pct:
            if self.config.use_trailing_stop and not tracker.trailing_stop_active:
                tracker.trailing_stop_active = True
                logger.info(
                    f"Trailing stop activated for {position.ticker} "
                    f"at {profit_pct:.1%} profit"
                )
                return None

            return ProfitTakeAction(
                ticker=position.ticker,
                action="close_full",
                quantity=position.quantity,
                reason=f"Take profit at {profit_pct:.1%}",
                current_profit_pct=profit_pct,
            )

        for i, (target_pct, close_fraction) in enumerate(self.config.tiered_targets):
            if i in tracker.tiers_closed:
                continue

            if profit_pct >= target_pct:
                close_qty = int(position.quantity * close_fraction)
                if close_qty > 0:
                    tracker.tiers_closed.append(i)
                    return ProfitTakeAction(
                        ticker=position.ticker,
                        action="close_partial",
                        quantity=close_qty,
                        reason=f"Tier {i+1}: {target_pct:.0%} target hit",
                        current_profit_pct=profit_pct,
                    )

        return None

    def get_tracked_positions(self) -> dict[str, PositionTracker]:
        """Get all tracked positions."""
        return self._tracked_positions.copy()

    def get_summary(self) -> dict:
        """Get profit-taker summary."""
        return {
            "enabled": self.config.enabled,
            "tracked_count": len(self._tracked_positions),
            "take_profit_pct": self.config.take_profit_pct,
            "stop_loss_pct": self.config.stop_loss_pct,
            "trailing_stop_pct": self.config.trailing_stop_pct,
            "positions": {
                ticker: {
                    "entry_price": t.entry_price,
                    "peak_profit_pct": t.peak_profit_pct,
                    "trailing_active": t.trailing_stop_active,
                    "tiers_closed": t.tiers_closed,
                }
                for ticker, t in self._tracked_positions.items()
            },
        }

    def reset(self) -> None:
        """Reset all tracking state."""
        self._tracked_positions.clear()
        self._closed_positions.clear()
