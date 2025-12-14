"""Tests for risk management."""

import pytest

from kalshi_arb.models.position import Position, OrderSide
from kalshi_arb.models.signal import DirectionalSignal, SignalDirection, SignalType
from kalshi_arb.risk.risk_manager import RiskManager, RiskConfig, DrawdownAction


class TestDrawdownTracking:
    """Tests for drawdown tracking."""

    def test_track_drawdown(self):
        """Track drawdown as value declines."""
        manager = RiskManager()

        manager.update_account_value(10000)
        metrics = manager.update_account_value(9000)

        assert metrics.current_drawdown == pytest.approx(0.10, abs=0.01)
        assert metrics.peak_value == 10000

    def test_drawdown_action_warning(self):
        """Trigger warning at 10% drawdown."""
        manager = RiskManager(RiskConfig(max_drawdown_warning=0.10))

        manager.update_account_value(10000)
        metrics = manager.update_account_value(8900)

        assert metrics.drawdown_action == DrawdownAction.WARNING

    def test_drawdown_action_reduce(self):
        """Trigger reduce at 20% drawdown."""
        manager = RiskManager(RiskConfig(max_drawdown_reduce=0.20))

        manager.update_account_value(10000)
        metrics = manager.update_account_value(7900)

        assert metrics.drawdown_action == DrawdownAction.REDUCE

    def test_drawdown_action_stop(self):
        """Trigger stop at 30% drawdown."""
        manager = RiskManager(RiskConfig(max_drawdown_stop=0.30))

        manager.update_account_value(10000)
        metrics = manager.update_account_value(6900)

        assert metrics.drawdown_action == DrawdownAction.STOP


class TestSignalApproval:
    """Tests for signal approval."""

    def test_approve_valid_signal(self):
        """Approve signal within limits."""
        manager = RiskManager()
        manager.update_account_value(10000)

        signal = DirectionalSignal(
            ticker="TEST",
            direction=SignalDirection.BUY_YES,
            signal_type=SignalType.CONSTRAINT_VIOLATION,
            current_price=0.40,
            bound_price=0.45,
            raw_edge=0.05,
            estimated_fee=0.02,
            estimated_spread=0.01,
            net_edge=0.02,
            confidence=1.0,
        )

        approved, reason = manager.approve_signal(
            signal=signal,
            proposed_size=500,
            current_positions=[],
            account_value=10000,
        )

        assert approved

    def test_reject_oversized_position(self):
        """Reject position exceeding limit."""
        manager = RiskManager(RiskConfig(max_single_position=0.05))
        manager.update_account_value(10000)

        signal = DirectionalSignal(
            ticker="TEST",
            direction=SignalDirection.BUY_YES,
            signal_type=SignalType.CONSTRAINT_VIOLATION,
            current_price=0.40,
            bound_price=0.45,
            raw_edge=0.05,
            estimated_fee=0.02,
            estimated_spread=0.01,
            net_edge=0.02,
            confidence=1.0,
        )

        approved, reason = manager.approve_signal(
            signal=signal,
            proposed_size=1000,
            current_positions=[],
            account_value=10000,
        )

        assert not approved
        assert "limit" in reason.lower()


class TestExpirationRisk:
    """Tests for expiration cliff detection."""

    def test_detect_expiration_risk(self):
        """Detect positions near expiration."""
        manager = RiskManager(RiskConfig(min_days_to_expiration=0.5))

        positions = [
            Position(ticker="NEAR", side=OrderSide.YES, quantity=10, average_price=0.50),
            Position(ticker="FAR", side=OrderSide.YES, quantity=10, average_price=0.50),
        ]

        days_to_exp = {"NEAR": 0.1, "FAR": 5.0}

        close_tickers = manager.check_expiration_risk(positions, days_to_exp)

        assert "NEAR" in close_tickers
        assert "FAR" not in close_tickers
