"""Execution engine for trading signals."""
from __future__ import annotations


import logging
import time
from datetime import datetime
from enum import Enum

from kalshi_arb.api.client import KalshiClient
from kalshi_arb.models.position import Order, OrderAction, OrderSide, OrderStatus, OrderType
from kalshi_arb.models.signal import DirectionalSignal, SignalDirection
from kalshi_arb.risk.position_sizer import PositionSizer

logger = logging.getLogger(__name__)


class ExecutionResult(Enum):
    """Result of execution attempt."""

    SUCCESS = "success"
    PARTIAL_FILL = "partial_fill"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    VALIDATION_FAILED = "validation_failed"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    MARKET_CLOSED = "market_closed"


class ExecutionEngine:
    """
    Execute trades based on signals.

    Rules:
    - Always use LIMIT orders
    - Cross spread only if edge > 2× spread
    - Revalidate bounds before execution
    - Do not hold through final hour unless edge > 3%
    """

    def __init__(
        self,
        client: KalshiClient,
        position_sizer: PositionSizer,
        max_price_drift: float = 0.02,
        order_timeout_seconds: int = 60,
        paper_trading: bool = True,
    ):
        self.client = client
        self.position_sizer = position_sizer
        self.max_price_drift = max_price_drift
        self.order_timeout_seconds = order_timeout_seconds
        self.paper_trading = paper_trading
        self._pending_orders: dict[str, Order] = {}
        self._execution_log: list[dict] = []

    def validate_signal(
        self,
        signal: DirectionalSignal,
    ) -> tuple[bool, str]:
        """
        Validate signal before execution.

        Returns:
            Tuple of (is_valid, reason)
        """
        if not signal.is_valid:
            return False, "Signal expired"

        try:
            market_data = self.client.get_market(signal.ticker)
            market = market_data.get("market", {})

            if market.get("status") != "open":
                return False, "Market not open"

            current_price = market.get("last_price", 0) / 100
            price_drift = abs(current_price - signal.current_price)

            if price_drift > self.max_price_drift:
                return False, f"Price drifted {price_drift:.2%}"

            if signal.direction == SignalDirection.BUY_YES:
                if current_price >= signal.bound_price:
                    return False, "Price no longer violates bound"
            else:
                if current_price <= signal.bound_price:
                    return False, "Price no longer violates bound"

            return True, "Valid"

        except Exception as e:
            return False, f"Validation error: {e}"

    def calculate_limit_price(
        self,
        signal: DirectionalSignal,
        aggressive: bool = False,
    ) -> int:
        """
        Calculate limit order price in cents.

        Args:
            signal: Trading signal
            aggressive: If True, cross the spread

        Returns:
            Price in cents (1-99)
        """
        if signal.direction == SignalDirection.BUY_YES:
            if aggressive:
                price = signal.current_price + signal.estimated_spread
            else:
                price = signal.current_price
        else:
            if aggressive:
                price = signal.current_price - signal.estimated_spread
            else:
                price = signal.current_price

        price_cents = int(price * 100)
        return max(1, min(99, price_cents))

    def execute_signal(
        self,
        signal: DirectionalSignal,
        account_balance: float,
        correlated_positions: int = 0,
    ) -> tuple[ExecutionResult, Order | None]:
        """
        Execute a trading signal.

        Args:
            signal: Signal to execute
            account_balance: Current account balance
            correlated_positions: Number of correlated positions

        Returns:
            Tuple of (result, order)
        """
        is_valid, reason = self.validate_signal(signal)
        if not is_valid:
            logger.warning(f"Signal validation failed: {reason}")
            self._log_execution(signal, None, ExecutionResult.VALIDATION_FAILED, reason)
            return ExecutionResult.VALIDATION_FAILED, None

        dollar_size, num_contracts = self.position_sizer.size_signal(
            signal,
            account_balance,
            correlated_positions,
        )

        if num_contracts < 1:
            logger.info("Position size too small")
            self._log_execution(signal, None, ExecutionResult.REJECTED, "Size too small")
            return ExecutionResult.REJECTED, None

        if dollar_size > account_balance:
            logger.warning("Insufficient balance")
            self._log_execution(
                signal, None, ExecutionResult.INSUFFICIENT_BALANCE, "Insufficient balance"
            )
            return ExecutionResult.INSUFFICIENT_BALANCE, None

        aggressive = signal.net_edge > 2 * signal.estimated_spread
        price_cents = self.calculate_limit_price(signal, aggressive)

        side = OrderSide.YES if signal.direction == SignalDirection.BUY_YES else OrderSide.NO

        order = Order(
            ticker=signal.ticker,
            side=side,
            action=OrderAction.BUY,
            order_type=OrderType.LIMIT,
            price=price_cents,
            quantity=num_contracts,
            status=OrderStatus.PENDING,
            signal_id=signal.source_constraint_id,
        )

        if self.paper_trading:
            order.status = OrderStatus.FILLED
            order.filled_quantity = num_contracts
            logger.info(
                f"[PAPER] Executed {num_contracts} {side.value} @ {price_cents}c "
                f"on {signal.ticker}"
            )
            self._log_execution(signal, order, ExecutionResult.SUCCESS, "Paper trade")
            return ExecutionResult.SUCCESS, order

        try:
            response = self.client.place_order(
                ticker=signal.ticker,
                side=side.value,
                action="buy",
                count=num_contracts,
                price=price_cents,
            )

            order.id = response.get("order", {}).get("order_id", "")
            order.status = OrderStatus.OPEN
            self._pending_orders[order.id] = order

            logger.info(f"Order placed: {order.id}")
            self._log_execution(signal, order, ExecutionResult.SUCCESS, "Order placed")
            return ExecutionResult.SUCCESS, order

        except Exception as e:
            logger.error(f"Order placement failed: {e}")
            self._log_execution(signal, order, ExecutionResult.REJECTED, str(e))
            return ExecutionResult.REJECTED, None

    def check_order_status(self, order_id: str) -> Order | None:
        """Check and update order status."""
        if order_id not in self._pending_orders:
            return None

        order = self._pending_orders[order_id]

        if self.paper_trading:
            return order

        try:
            response = self.client.get_order(order_id)
            order_data = response.get("order", {})

            status_map = {
                "resting": OrderStatus.OPEN,
                "canceled": OrderStatus.CANCELLED,
                "executed": OrderStatus.FILLED,
                "pending": OrderStatus.PENDING,
            }

            order.status = status_map.get(
                order_data.get("status", ""),
                OrderStatus.PENDING,
            )
            order.filled_quantity = order_data.get("filled_count", 0)
            order.updated_at = datetime.now()

            if order.is_complete:
                del self._pending_orders[order_id]

            return order

        except Exception as e:
            logger.error(f"Failed to check order status: {e}")
            return order

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        if order_id not in self._pending_orders:
            return False

        if self.paper_trading:
            order = self._pending_orders.pop(order_id)
            order.status = OrderStatus.CANCELLED
            return True

        try:
            self.client.cancel_order(order_id)
            order = self._pending_orders.pop(order_id)
            order.status = OrderStatus.CANCELLED
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            return False

    def cancel_all_pending(self) -> int:
        """Cancel all pending orders."""
        cancelled = 0
        for order_id in list(self._pending_orders.keys()):
            if self.cancel_order(order_id):
                cancelled += 1
        return cancelled

    def wait_for_fill(
        self,
        order_id: str,
        timeout_seconds: int | None = None,
    ) -> Order | None:
        """Wait for order to fill or timeout."""
        timeout = timeout_seconds or self.order_timeout_seconds
        start_time = time.time()

        while time.time() - start_time < timeout:
            order = self.check_order_status(order_id)
            if order is None:
                return None

            if order.is_complete:
                return order

            time.sleep(1)

        self.cancel_order(order_id)
        return self._pending_orders.get(order_id)

    def get_pending_orders(self) -> list[Order]:
        """Get all pending orders."""
        return list(self._pending_orders.values())

    def get_execution_log(self) -> list[dict]:
        """Get execution history."""
        return self._execution_log.copy()

    def _log_execution(
        self,
        signal: DirectionalSignal,
        order: Order | None,
        result: ExecutionResult,
        message: str,
    ) -> None:
        """Log execution attempt."""
        self._execution_log.append({
            "timestamp": datetime.now().isoformat(),
            "ticker": signal.ticker,
            "direction": signal.direction.value,
            "edge": signal.net_edge,
            "order_id": order.id if order else None,
            "quantity": order.quantity if order else 0,
            "price": order.price if order else 0,
            "result": result.value,
            "message": message,
        })
