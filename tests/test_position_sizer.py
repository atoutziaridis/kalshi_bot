"""Tests for position sizing."""

import pytest

from kalshi_arb.models.signal import DirectionalSignal, SignalDirection, SignalType
from kalshi_arb.risk.position_sizer import PositionSizer, SizingConfig


class TestKellyCalculation:
    """Tests for Kelly criterion calculation."""

    def test_kelly_positive_edge(self, position_sizer):
        """Kelly fraction for positive edge."""
        kelly = position_sizer.calculate_kelly(0.60, 1.0)
        assert kelly == pytest.approx(0.20, abs=0.01)

    def test_kelly_no_edge(self, position_sizer):
        """Kelly fraction is 0 for no edge."""
        kelly = position_sizer.calculate_kelly(0.50, 1.0)
        assert kelly == 0.0

    def test_kelly_negative_edge(self, position_sizer):
        """Kelly fraction is 0 for negative edge."""
        kelly = position_sizer.calculate_kelly(0.40, 1.0)
        assert kelly == 0.0

    def test_kelly_from_edge(self, position_sizer):
        """Calculate Kelly from edge and price."""
        kelly = position_sizer.calculate_kelly_from_edge(0.05, 0.50)
        assert kelly > 0


class TestFractionalKelly:
    """Tests for fractional Kelly adjustment."""

    def test_fractional_kelly_25_percent(self):
        """Apply 25% fractional Kelly."""
        sizer = PositionSizer(SizingConfig(kelly_fraction=0.25))
        kelly = sizer.calculate_kelly(0.60, 1.0)
        fractional = sizer.apply_fractional_kelly(kelly)
        assert fractional == pytest.approx(kelly * 0.25, abs=0.001)


class TestCorrelationAdjustment:
    """Tests for correlation adjustment."""

    def test_no_correlation_adjustment(self, position_sizer):
        """No adjustment with 0 correlated positions."""
        adjusted = position_sizer.adjust_for_correlation(0.10, 0)
        assert adjusted == 0.10

    def test_correlation_reduces_size(self, position_sizer):
        """Correlated positions reduce size."""
        original = 0.10
        adjusted = position_sizer.adjust_for_correlation(original, 2)
        assert adjusted < original


class TestPositionSizing:
    """Tests for full position sizing."""

    def test_size_signal(self, position_sizer):
        """Size a trading signal."""
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

        dollar_size, num_contracts = position_sizer.size_signal(
            signal,
            account_balance=10000,
            correlated_positions=0,
        )

        assert dollar_size >= 0
        assert num_contracts >= 0

    def test_respects_max_position(self):
        """Position size respects maximum."""
        sizer = PositionSizer(SizingConfig(max_position_per_market=0.05))

        signal = DirectionalSignal(
            ticker="TEST",
            direction=SignalDirection.BUY_YES,
            signal_type=SignalType.CONSTRAINT_VIOLATION,
            current_price=0.40,
            bound_price=0.60,
            raw_edge=0.20,
            estimated_fee=0.02,
            estimated_spread=0.01,
            net_edge=0.17,
            confidence=1.0,
        )

        dollar_size, _ = sizer.size_signal(signal, 10000, 0)
        assert dollar_size <= 10000 * 0.05
