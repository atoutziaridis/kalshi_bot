"""Tests for fee calculation utilities."""

import pytest

from kalshi_arb.utils.fees import calculate_fee, calculate_total_fees, fee_as_percentage


class TestCalculateFee:
    """Tests for calculate_fee function."""

    def test_fee_at_50_cents(self):
        """Fee is highest at 50 cents."""
        fee = calculate_fee(0.50, 1)
        assert fee == 0.02  # 0.07 * 0.5 * 0.5 = 0.0175, rounds up to 2 cents

    def test_fee_at_low_price(self):
        """Fee is lower at extreme prices."""
        fee = calculate_fee(0.10, 1)
        assert fee == 0.01  # 0.07 * 0.1 * 0.9 = 0.0063, rounds up to 1 cent

    def test_fee_at_high_price(self):
        """Fee is lower at high prices."""
        fee = calculate_fee(0.90, 1)
        assert fee == 0.01  # 0.07 * 0.9 * 0.1 = 0.0063, rounds up to 1 cent

    def test_fee_multiple_contracts(self):
        """Fee scales with number of contracts."""
        fee_1 = calculate_fee(0.50, 1)
        fee_10 = calculate_fee(0.50, 10)
        assert fee_10 == fee_1 * 10

    def test_fee_invalid_price(self):
        """Fee is 0 for invalid prices."""
        assert calculate_fee(0.0, 1) == 0.0
        assert calculate_fee(1.0, 1) == 0.0
        assert calculate_fee(-0.1, 1) == 0.0
        assert calculate_fee(1.1, 1) == 0.0


class TestCalculateTotalFees:
    """Tests for calculate_total_fees function."""

    def test_total_fees_multiple_prices(self):
        """Total fees sum correctly."""
        prices = [0.30, 0.40, 0.30]
        total = calculate_total_fees(prices, 1)
        expected = sum(calculate_fee(p, 1) for p in prices)
        assert total == expected

    def test_total_fees_empty_list(self):
        """Empty list returns 0."""
        assert calculate_total_fees([], 1) == 0.0


class TestFeeAsPercentage:
    """Tests for fee_as_percentage function."""

    def test_fee_percentage_at_50_cents(self):
        """Fee percentage at 50 cents."""
        pct = fee_as_percentage(0.50)
        assert 0.03 <= pct <= 0.04  # ~3.5%

    def test_fee_percentage_at_10_cents(self):
        """Fee percentage higher at low prices."""
        pct = fee_as_percentage(0.10)
        assert pct >= 0.05  # Higher percentage at low prices
