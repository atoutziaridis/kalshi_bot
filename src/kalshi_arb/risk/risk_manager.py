"""Risk management system for binary contract portfolios."""
from __future__ import annotations


import logging
from collections import defaultdict
from datetime import datetime
from enum import Enum

import numpy as np
from pydantic import BaseModel, Field

from kalshi_arb.models.position import Position, PortfolioSummary
from kalshi_arb.models.signal import DirectionalSignal

logger = logging.getLogger(__name__)


class DrawdownAction(str, Enum):
    """Actions triggered by drawdown levels."""

    NONE = "none"
    WARNING = "warning"
    REDUCE = "reduce"
    STOP = "stop"


class RiskConfig(BaseModel):
    """Risk management configuration."""

    max_drawdown_warning: float = Field(default=0.10)
    max_drawdown_reduce: float = Field(default=0.20)
    max_drawdown_stop: float = Field(default=0.30)

    max_cluster_exposure: float = Field(default=0.50)
    max_single_position: float = Field(default=0.10)
    min_days_to_expiration: float = Field(default=0.2)

    correlation_spike_threshold: float = Field(default=0.50)
    stress_correlation: float = Field(default=1.0)


class RiskMetrics(BaseModel):
    """Current risk metrics snapshot."""

    timestamp: datetime = Field(default_factory=datetime.now)
    account_value: float = 0.0
    peak_value: float = 0.0
    current_drawdown: float = 0.0
    max_drawdown: float = 0.0

    var_95: float = 0.0
    cvar_95: float = 0.0

    position_count: int = 0
    cluster_exposures: dict[str, float] = Field(default_factory=dict)
    total_exposure: float = 0.0

    drawdown_action: DrawdownAction = DrawdownAction.NONE


class RiskManager:
    """
    Comprehensive risk management for binary portfolios.

    Handles:
    - Drawdown monitoring and triggers
    - CVaR estimation
    - Correlation monitoring
    - Position limit enforcement
    - Expiration cliff risk
    """

    def __init__(self, config: RiskConfig | None = None):
        self.config = config or RiskConfig()
        self._peak_value: float = 0.0
        self._max_drawdown: float = 0.0
        self._value_history: list[tuple[datetime, float]] = []
        self._correlation_history: dict[str, list[float]] = defaultdict(list)

    def update_account_value(self, value: float) -> RiskMetrics:
        """Update account value and calculate metrics."""
        self._value_history.append((datetime.now(), value))

        if value > self._peak_value:
            self._peak_value = value

        current_drawdown = 0.0
        if self._peak_value > 0:
            current_drawdown = (self._peak_value - value) / self._peak_value

        if current_drawdown > self._max_drawdown:
            self._max_drawdown = current_drawdown

        action = self._determine_drawdown_action(current_drawdown)

        return RiskMetrics(
            account_value=value,
            peak_value=self._peak_value,
            current_drawdown=current_drawdown,
            max_drawdown=self._max_drawdown,
            drawdown_action=action,
        )

    def _determine_drawdown_action(self, drawdown: float) -> DrawdownAction:
        """Determine action based on drawdown level."""
        if drawdown >= self.config.max_drawdown_stop:
            logger.critical(f"STOP: Drawdown {drawdown:.1%} exceeds stop threshold")
            return DrawdownAction.STOP
        elif drawdown >= self.config.max_drawdown_reduce:
            logger.warning(f"REDUCE: Drawdown {drawdown:.1%} exceeds reduce threshold")
            return DrawdownAction.REDUCE
        elif drawdown >= self.config.max_drawdown_warning:
            logger.warning(f"WARNING: Drawdown {drawdown:.1%} exceeds warning threshold")
            return DrawdownAction.WARNING
        return DrawdownAction.NONE

    def calculate_portfolio_risk(
        self,
        positions: list[Position],
        account_value: float,
    ) -> RiskMetrics:
        """Calculate comprehensive portfolio risk metrics."""
        metrics = self.update_account_value(account_value)

        metrics.position_count = len(positions)
        metrics.total_exposure = sum(p.cost_basis for p in positions)

        cluster_exposures = self._calculate_cluster_exposures(positions)
        metrics.cluster_exposures = cluster_exposures

        if positions:
            var, cvar = self._estimate_var_cvar(positions, account_value)
            metrics.var_95 = var
            metrics.cvar_95 = cvar

        return metrics

    def _calculate_cluster_exposures(
        self,
        positions: list[Position],
    ) -> dict[str, float]:
        """Calculate exposure by cluster (series)."""
        exposures: dict[str, float] = defaultdict(float)

        for position in positions:
            series = position.ticker.split("-")[0] if "-" in position.ticker else "other"
            exposures[series] += position.cost_basis

        return dict(exposures)

    def _estimate_var_cvar(
        self,
        positions: list[Position],
        account_value: float,
        alpha: float = 0.05,
    ) -> tuple[float, float]:
        """
        Estimate VaR and CVaR for binary portfolio.

        For binary contracts, worst case is total loss of position.
        We estimate using stress correlation assumptions.
        """
        if not positions or account_value <= 0:
            return 0.0, 0.0

        total_exposure = sum(p.cost_basis for p in positions)

        worst_case_loss = total_exposure

        stress_prob = min(1.0, self.config.stress_correlation ** len(positions))
        var_95 = worst_case_loss * stress_prob

        cvar_95 = worst_case_loss * min(1.0, stress_prob * 1.5)

        return var_95 / account_value, cvar_95 / account_value

    def approve_signal(
        self,
        signal: DirectionalSignal,
        proposed_size: float,
        current_positions: list[Position],
        account_value: float,
    ) -> tuple[bool, str]:
        """
        Approve or reject a signal based on risk limits.

        Returns:
            Tuple of (approved, reason)
        """
        metrics = self.calculate_portfolio_risk(current_positions, account_value)

        if metrics.drawdown_action == DrawdownAction.STOP:
            return False, "Trading stopped due to drawdown"

        if metrics.drawdown_action == DrawdownAction.REDUCE:
            proposed_size *= 0.5
            if proposed_size < 10:
                return False, "Position too small after drawdown reduction"

        if proposed_size / account_value > self.config.max_single_position:
            return False, f"Position exceeds {self.config.max_single_position:.0%} limit"

        series = signal.ticker.split("-")[0] if "-" in signal.ticker else "other"
        current_cluster = metrics.cluster_exposures.get(series, 0)
        new_cluster = current_cluster + proposed_size

        if new_cluster / account_value > self.config.max_cluster_exposure:
            return False, f"Cluster exposure exceeds {self.config.max_cluster_exposure:.0%}"

        return True, "Approved"

    def check_expiration_risk(
        self,
        positions: list[Position],
        days_to_expiration: dict[str, float],
    ) -> list[str]:
        """
        Check for positions approaching expiration cliff.

        Returns list of tickers that should be closed.
        """
        close_tickers = []

        for position in positions:
            days = days_to_expiration.get(position.ticker, float("inf"))

            if days < self.config.min_days_to_expiration:
                logger.warning(
                    f"Expiration cliff: {position.ticker} has {days:.2f} days remaining"
                )
                close_tickers.append(position.ticker)

        return close_tickers

    def stress_test(
        self,
        positions: list[Position],
        correlation: float = 1.0,
    ) -> float:
        """
        Stress test portfolio assuming given correlation.

        Returns maximum loss as fraction of total exposure.
        """
        if not positions:
            return 0.0

        total_exposure = sum(p.cost_basis for p in positions)

        if correlation >= 1.0:
            return 1.0

        n = len(positions)
        loss_prob = correlation ** n

        return loss_prob

    def get_position_reduction_targets(
        self,
        positions: list[Position],
        reduction_pct: float = 0.5,
    ) -> list[tuple[str, int]]:
        """
        Get positions to reduce during drawdown.

        Returns list of (ticker, contracts_to_close).
        """
        targets = []

        sorted_positions = sorted(
            positions,
            key=lambda p: p.unrealized_pnl,
        )

        for position in sorted_positions:
            contracts_to_close = int(position.quantity * reduction_pct)
            if contracts_to_close > 0:
                targets.append((position.ticker, contracts_to_close))

        return targets

    def calculate_correlation_change(
        self,
        ticker: str,
        new_correlation: float,
    ) -> float:
        """Track correlation changes over time."""
        history = self._correlation_history[ticker]
        history.append(new_correlation)

        if len(history) > 30:
            history.pop(0)

        if len(history) < 2:
            return 0.0

        old_avg = np.mean(history[:-1])
        change = (new_correlation - old_avg) / max(0.01, old_avg)

        if change > self.config.correlation_spike_threshold:
            logger.warning(f"Correlation spike detected for {ticker}: {change:.1%}")

        return change

    def get_risk_summary(self) -> dict:
        """Get summary of current risk state."""
        return {
            "peak_value": self._peak_value,
            "max_drawdown": self._max_drawdown,
            "history_length": len(self._value_history),
            "config": self.config.model_dump(),
        }

    def reset(self) -> None:
        """Reset risk tracking state."""
        self._peak_value = 0.0
        self._max_drawdown = 0.0
        self._value_history.clear()
        self._correlation_history.clear()
