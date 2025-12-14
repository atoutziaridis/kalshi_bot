"""Position sizing using fractional Kelly criterion."""
from __future__ import annotations


from pydantic import BaseModel, Field

from kalshi_arb.models.signal import DirectionalSignal, SignalDirection


class SizingConfig(BaseModel):
    """Configuration for position sizing."""

    kelly_fraction: float = Field(default=0.25, ge=0.0, le=1.0)
    max_position_per_market: float = Field(default=0.05, ge=0.0, le=1.0)
    max_cluster_allocation: float = Field(default=0.10, ge=0.0, le=1.0)
    min_position_size: float = Field(default=10.0, ge=0.0)
    correlation_adjustment_per_position: float = Field(default=0.20, ge=0.0, le=1.0)


class PositionSizer:
    """
    Calculate position sizes using arb-bounded Kelly criterion.

    Binary payoffs create nonlinear risk - position sizing IS the risk management.
    """

    def __init__(self, config: SizingConfig | None = None):
        self.config = config or SizingConfig()

    def calculate_kelly(
        self,
        win_probability: float,
        odds: float = 1.0,
    ) -> float:
        """
        Calculate full Kelly fraction.

        Kelly formula: f* = (p * b - q) / b
        Where:
            p = win probability
            q = 1 - p
            b = odds (net profit ratio)

        Args:
            win_probability: Probability of winning (0-1)
            odds: Net profit ratio (1.0 for even odds)

        Returns:
            Kelly fraction (0-1)
        """
        if win_probability <= 0 or win_probability >= 1:
            return 0.0
        if odds <= 0:
            return 0.0

        q = 1 - win_probability
        kelly = (win_probability * odds - q) / odds

        return max(0.0, min(1.0, kelly))

    def calculate_kelly_from_edge(
        self,
        edge: float,
        price: float,
    ) -> float:
        """
        Calculate Kelly fraction from edge and price.

        For binary contracts:
        - If buying YES at price p with edge e: win_prob = p + e
        - Odds = (1 - p) / p for YES

        Args:
            edge: Net edge after costs
            price: Current price (decimal)

        Returns:
            Kelly fraction
        """
        if edge <= 0 or price <= 0 or price >= 1:
            return 0.0

        win_prob = min(0.99, price + edge)
        odds = (1 - price) / price

        return self.calculate_kelly(win_prob, odds)

    def apply_fractional_kelly(self, kelly: float) -> float:
        """Apply fractional Kelly adjustment."""
        return kelly * self.config.kelly_fraction

    def adjust_for_correlation(
        self,
        size: float,
        correlated_positions: int,
    ) -> float:
        """
        Reduce size based on number of correlated positions.

        Each additional correlated position reduces size by adjustment factor.
        """
        if correlated_positions <= 0:
            return size

        adjustment = 1.0 - (
            self.config.correlation_adjustment_per_position * correlated_positions
        )
        return size * max(0.1, adjustment)

    def adjust_for_costs(
        self,
        size: float,
        spread: float,
        fee: float,
    ) -> float:
        """
        Reduce size to account for execution costs.

        f_adjusted = f * (1 - 2*(spread + slippage) - fee)
        """
        cost_factor = 1.0 - 2 * spread - fee
        return size * max(0.5, cost_factor)

    def calculate_position_size(
        self,
        signal: DirectionalSignal,
        account_balance: float,
        correlated_positions: int = 0,
    ) -> float:
        """
        Calculate final position size in dollars.

        Args:
            signal: Trading signal
            account_balance: Current account balance
            correlated_positions: Number of correlated open positions

        Returns:
            Position size in dollars
        """
        kelly = self.calculate_kelly_from_edge(signal.net_edge, signal.current_price)
        fractional = self.apply_fractional_kelly(kelly)

        adjusted = self.adjust_for_correlation(fractional, correlated_positions)
        adjusted = self.adjust_for_costs(
            adjusted,
            signal.estimated_spread,
            signal.estimated_fee,
        )

        max_size = account_balance * self.config.max_position_per_market
        position_size = min(adjusted * account_balance, max_size)

        if position_size < self.config.min_position_size:
            return 0.0

        return position_size

    def calculate_contracts(
        self,
        position_size: float,
        price: float,
    ) -> int:
        """
        Convert dollar position size to number of contracts.

        Args:
            position_size: Size in dollars
            price: Contract price (decimal)

        Returns:
            Number of contracts (rounded down)
        """
        if price <= 0 or position_size <= 0:
            return 0

        return int(position_size / price)

    def size_signal(
        self,
        signal: DirectionalSignal,
        account_balance: float,
        correlated_positions: int = 0,
    ) -> tuple[float, int]:
        """
        Calculate both dollar size and contract count for a signal.

        Returns:
            Tuple of (dollar_size, num_contracts)
        """
        dollar_size = self.calculate_position_size(
            signal,
            account_balance,
            correlated_positions,
        )

        price = signal.current_price
        if signal.direction == SignalDirection.BUY_NO:
            price = 1.0 - signal.current_price

        num_contracts = self.calculate_contracts(dollar_size, price)

        return dollar_size, num_contracts

    def validate_cluster_limits(
        self,
        new_size: float,
        cluster_exposure: float,
        account_balance: float,
    ) -> float:
        """
        Ensure cluster allocation limits are respected.

        Args:
            new_size: Proposed new position size
            cluster_exposure: Current exposure in this cluster
            account_balance: Total account balance

        Returns:
            Adjusted size respecting cluster limits
        """
        max_cluster = account_balance * self.config.max_cluster_allocation
        available = max_cluster - cluster_exposure

        if available <= 0:
            return 0.0

        return min(new_size, available)

    def calculate_risk_of_ruin(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        bet_fraction: float,
    ) -> float:
        """
        Estimate risk of ruin for given parameters.

        RoR = (q/p)^(bankroll / bet_size)

        This is a simplified estimate assuming independent bets.
        """
        if win_rate <= 0 or win_rate >= 1:
            return 1.0
        if bet_fraction <= 0:
            return 0.0

        q = 1 - win_rate
        p = win_rate

        if p <= q:
            return 1.0

        exponent = 1.0 / bet_fraction
        ror = (q / p) ** exponent

        return min(1.0, ror)
