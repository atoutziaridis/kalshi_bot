"""Trade execution simulator for backtesting."""
from __future__ import annotations


import random
from datetime import datetime

from pydantic import BaseModel, Field

from kalshi_arb.models.position import Order, OrderAction, OrderSide, OrderStatus, OrderType
from kalshi_arb.models.signal import DirectionalSignal, SignalDirection
from kalshi_arb.utils.fees import calculate_fee


class SimulatedFill(BaseModel):
    """Result of a simulated order fill."""

    order_id: str
    ticker: str
    side: OrderSide
    filled_quantity: int
    fill_price: float
    fee: float
    slippage: float
    timestamp: datetime = Field(default_factory=datetime.now)


class TradeSimulator:
    """
    Simulate trade execution for backtesting.

    Accounts for:
    - Slippage based on order size and liquidity
    - Fees per Kalshi schedule
    - Partial fills
    - Fill probability
    """

    def __init__(
        self,
        base_slippage: float = 0.005,
        fill_probability: float = 0.9,
        max_slippage: float = 0.02,
    ):
        self.base_slippage = base_slippage
        self.fill_probability = fill_probability
        self.max_slippage = max_slippage
        self._order_counter = 0

    def simulate_order(
        self,
        signal: DirectionalSignal,
        quantity: int,
        available_liquidity: int = 1000,
    ) -> SimulatedFill | None:
        """
        Simulate order execution.

        Args:
            signal: Trading signal
            quantity: Number of contracts
            available_liquidity: Available depth at price level

        Returns:
            SimulatedFill if order fills, None if rejected
        """
        if random.random() > self.fill_probability:
            return None

        fill_ratio = min(1.0, available_liquidity / max(1, quantity))
        filled_quantity = int(quantity * fill_ratio)

        if filled_quantity < 1:
            return None

        size_factor = min(1.0, quantity / max(1, available_liquidity))
        slippage = self.base_slippage * (1 + size_factor)
        slippage = min(slippage, self.max_slippage)

        if signal.direction == SignalDirection.BUY_YES:
            fill_price = signal.current_price + slippage
            side = OrderSide.YES
        else:
            fill_price = signal.current_price - slippage
            side = OrderSide.NO

        fill_price = max(0.01, min(0.99, fill_price))

        fee = calculate_fee(fill_price, filled_quantity)

        self._order_counter += 1

        return SimulatedFill(
            order_id=f"sim_{self._order_counter}",
            ticker=signal.ticker,
            side=side,
            filled_quantity=filled_quantity,
            fill_price=fill_price,
            fee=fee,
            slippage=slippage,
        )

    def simulate_exit(
        self,
        ticker: str,
        side: OrderSide,
        quantity: int,
        current_price: float,
        available_liquidity: int = 1000,
    ) -> SimulatedFill | None:
        """Simulate exiting a position."""
        if random.random() > self.fill_probability:
            return None

        fill_ratio = min(1.0, available_liquidity / max(1, quantity))
        filled_quantity = int(quantity * fill_ratio)

        if filled_quantity < 1:
            return None

        size_factor = min(1.0, quantity / max(1, available_liquidity))
        slippage = self.base_slippage * (1 + size_factor)

        if side == OrderSide.YES:
            fill_price = current_price - slippage
        else:
            fill_price = current_price + slippage

        fill_price = max(0.01, min(0.99, fill_price))
        fee = calculate_fee(fill_price, filled_quantity)

        self._order_counter += 1

        return SimulatedFill(
            order_id=f"sim_exit_{self._order_counter}",
            ticker=ticker,
            side=side,
            filled_quantity=filled_quantity,
            fill_price=fill_price,
            fee=fee,
            slippage=slippage,
        )

    def calculate_pnl(
        self,
        entry_fill: SimulatedFill,
        exit_fill: SimulatedFill,
    ) -> float:
        """Calculate P&L from entry and exit fills."""
        if entry_fill.side == OrderSide.YES:
            pnl = (exit_fill.fill_price - entry_fill.fill_price) * entry_fill.filled_quantity
        else:
            pnl = (entry_fill.fill_price - exit_fill.fill_price) * entry_fill.filled_quantity

        total_fees = entry_fill.fee + exit_fill.fee
        return pnl - total_fees

    def calculate_resolution_pnl(
        self,
        fill: SimulatedFill,
        resolved_yes: bool,
    ) -> float:
        """Calculate P&L if position held to resolution."""
        if fill.side == OrderSide.YES:
            if resolved_yes:
                pnl = (1.0 - fill.fill_price) * fill.filled_quantity
            else:
                pnl = -fill.fill_price * fill.filled_quantity
        else:
            if resolved_yes:
                pnl = -fill.fill_price * fill.filled_quantity
            else:
                pnl = (1.0 - fill.fill_price) * fill.filled_quantity

        return pnl - fill.fee
