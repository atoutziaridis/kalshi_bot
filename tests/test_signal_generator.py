"""Tests for signal generator."""

import pytest

from kalshi_arb.engine.constraint_engine import ConstraintEngine
from kalshi_arb.models.market import Market
from kalshi_arb.models.signal import SignalDirection
from kalshi_arb.signals.signal_generator import SignalGenerator


class TestSignalGeneration:
    """Tests for signal generation from constraints."""

    def test_generate_signal_from_violation(self):
        """Generate signal when price violates bound."""
        engine = ConstraintEngine()
        engine.register_subset("TRUMP", "GOP")

        generator = SignalGenerator(
            constraint_engine=engine,
            min_edge_threshold=0.01,
        )

        markets = [
            Market(ticker="TRUMP", last_price=42, yes_bid=41, yes_ask=43),
            Market(ticker="GOP", last_price=38, yes_bid=37, yes_ask=39),
        ]

        signals = generator.generate_signals(markets)

        assert len(signals) > 0

        gop_signals = [s for s in signals if s.ticker == "GOP"]
        assert len(gop_signals) > 0
        assert gop_signals[0].direction == SignalDirection.BUY_YES

    def test_no_signal_when_valid(self):
        """No signal when prices are valid."""
        engine = ConstraintEngine()
        engine.register_subset("TRUMP", "GOP")

        generator = SignalGenerator(
            constraint_engine=engine,
            min_edge_threshold=0.01,
        )

        markets = [
            Market(ticker="TRUMP", last_price=35, yes_bid=34, yes_ask=36),
            Market(ticker="GOP", last_price=45, yes_bid=44, yes_ask=46),
        ]

        signals = generator.generate_signals(markets)

        significant_signals = [s for s in signals if s.net_edge >= 0.01]
        assert len(significant_signals) == 0


class TestSignalValidation:
    """Tests for signal validation."""

    def test_validate_signal_price_drift(self):
        """Reject signal if price drifted too much."""
        engine = ConstraintEngine()
        generator = SignalGenerator(constraint_engine=engine)

        from kalshi_arb.models.signal import DirectionalSignal, SignalType

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

        is_valid = generator.validate_signal(signal, current_price=0.50)
        assert not is_valid

        is_valid = generator.validate_signal(signal, current_price=0.41)
        assert is_valid
