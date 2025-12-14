"""Directional signal generator from constraint violations."""
from __future__ import annotations


from datetime import datetime, timedelta

from kalshi_arb.engine.constraint_engine import ConstraintEngine
from kalshi_arb.models.constraint import ProbabilityBound
from kalshi_arb.models.market import Market
from kalshi_arb.models.signal import (
    DirectionalSignal,
    RebalancingOpportunity,
    SignalDirection,
    SignalType,
)
from kalshi_arb.utils.fees import calculate_fee


class SignalGenerator:
    """
    Generate trading signals from constraint violations.

    Signals are generated when market prices violate logical bounds
    by more than fees + spread + safety margin.
    """

    def __init__(
        self,
        constraint_engine: ConstraintEngine,
        min_edge_threshold: float = 0.01,
        safety_margin: float = 0.005,
        signal_ttl_seconds: int = 300,
    ):
        self.constraint_engine = constraint_engine
        self.min_edge_threshold = min_edge_threshold
        self.safety_margin = safety_margin
        self.signal_ttl_seconds = signal_ttl_seconds

    def generate_signal(
        self,
        ticker: str,
        current_price: float,
        bound: ProbabilityBound,
        spread: float = 0.0,
    ) -> DirectionalSignal | None:
        """
        Generate signal from a single bound violation.

        Args:
            ticker: Market ticker
            current_price: Current market price (decimal)
            bound: Probability bound from constraints
            spread: Current bid-ask spread

        Returns:
            DirectionalSignal if edge exceeds threshold, None otherwise
        """
        violation = bound.violation(current_price)
        if violation <= 0:
            return None

        fee = calculate_fee(current_price)

        if current_price < bound.lower:
            direction = SignalDirection.BUY_YES
            bound_price = bound.lower
            raw_edge = bound.lower - current_price
        else:
            direction = SignalDirection.BUY_NO
            bound_price = bound.upper
            raw_edge = current_price - bound.upper

        total_costs = fee + spread + self.safety_margin
        net_edge = raw_edge - total_costs

        if net_edge < self.min_edge_threshold:
            return None

        return DirectionalSignal(
            ticker=ticker,
            direction=direction,
            signal_type=SignalType.CONSTRAINT_VIOLATION,
            current_price=current_price,
            bound_price=bound_price,
            raw_edge=raw_edge,
            estimated_fee=fee,
            estimated_spread=spread,
            net_edge=net_edge,
            confidence=bound.confidence,
            source_constraint_id=bound.source_constraint_id,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(seconds=self.signal_ttl_seconds),
        )

    def generate_signals(
        self,
        markets: list[Market],
        spreads: dict[str, float] | None = None,
    ) -> list[DirectionalSignal]:
        """
        Generate signals for all markets with constraint violations.

        Args:
            markets: List of markets to scan
            spreads: Optional dict of spreads by ticker

        Returns:
            List of valid signals sorted by net edge
        """
        spreads = spreads or {}
        prices = {m.ticker: m.mid_price_decimal for m in markets}

        bounds = self.constraint_engine.calculate_all_bounds(prices)
        signals = []

        for ticker, bound in bounds.items():
            if ticker not in prices:
                continue

            current_price = prices[ticker]
            spread = spreads.get(ticker, 0.0)

            signal = self.generate_signal(ticker, current_price, bound, spread)
            if signal:
                signals.append(signal)

        return sorted(signals, key=lambda s: s.net_edge, reverse=True)

    def generate_from_rebalancing(
        self,
        opportunity: RebalancingOpportunity,
    ) -> list[DirectionalSignal]:
        """
        Convert rebalancing opportunity to directional signals.

        For long rebalancing (sum < 1): Generate BUY YES signals
        For short rebalancing (sum > 1): Generate BUY NO signals
        """
        signals = []
        direction = (
            SignalDirection.BUY_YES if opportunity.is_long else SignalDirection.BUY_NO
        )

        edge_per_condition = opportunity.profit_post_fee / len(opportunity.conditions)

        for ticker, price in zip(opportunity.conditions, opportunity.prices):
            fee = calculate_fee(price)

            signal = DirectionalSignal(
                ticker=ticker,
                direction=direction,
                signal_type=SignalType.REBALANCING,
                current_price=price,
                bound_price=1.0 / len(opportunity.conditions),
                raw_edge=edge_per_condition + fee,
                estimated_fee=fee,
                estimated_spread=0.0,
                net_edge=edge_per_condition,
                confidence=1.0,
                source_constraint_id=opportunity.market_id,
                created_at=datetime.now(),
                expires_at=datetime.now() + timedelta(seconds=self.signal_ttl_seconds),
            )
            signals.append(signal)

        return signals

    def validate_signal(
        self,
        signal: DirectionalSignal,
        current_price: float,
        max_price_drift: float = 0.02,
    ) -> bool:
        """
        Validate that a signal is still valid before execution.

        Args:
            signal: Signal to validate
            current_price: Current market price
            max_price_drift: Maximum allowed price change

        Returns:
            True if signal is still valid
        """
        if not signal.is_valid:
            return False

        price_drift = abs(current_price - signal.current_price)
        if price_drift > max_price_drift:
            return False

        if signal.direction == SignalDirection.BUY_YES:
            if current_price >= signal.bound_price:
                return False
        else:
            if current_price <= signal.bound_price:
                return False

        return True

    def filter_by_execution_rules(
        self,
        signals: list[DirectionalSignal],
        markets: dict[str, Market],
    ) -> list[DirectionalSignal]:
        """
        Filter signals based on execution rules.

        Rules:
        - Cross spread only if edge > 2× spread
        - Do not hold through final hour unless edge > 3%
        """
        filtered = []

        for signal in signals:
            market = markets.get(signal.ticker)
            if not market:
                continue

            if signal.estimated_spread > 0:
                if signal.net_edge < 2 * signal.estimated_spread:
                    continue

            if market.days_to_expiration is not None:
                hours_to_exp = market.days_to_expiration * 24
                if hours_to_exp < 1 and signal.net_edge < 0.03:
                    continue

            filtered.append(signal)

        return filtered

    def rank_signals(
        self,
        signals: list[DirectionalSignal],
    ) -> list[DirectionalSignal]:
        """
        Rank signals by quality score.

        Score = net_edge * confidence
        """
        def score(s: DirectionalSignal) -> float:
            return s.net_edge * s.confidence

        return sorted(signals, key=score, reverse=True)
