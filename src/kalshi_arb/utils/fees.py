"""Fee calculation utilities for Kalshi contracts."""
from __future__ import annotations


import math


def calculate_fee(price: float, num_contracts: int = 1) -> float:
    """
    Calculate Kalshi fee for a trade.

    Fee formula: 0.07 × price × (1 - price) per contract, rounded up to nearest cent.

    Args:
        price: Contract price as decimal (0.01 to 0.99)
        num_contracts: Number of contracts

    Returns:
        Total fee in dollars
    """
    if not 0 < price < 1:
        return 0.0

    fee_per_contract = 0.07 * price * (1 - price)
    fee_cents = math.ceil(fee_per_contract * 100)
    return (fee_cents / 100) * num_contracts


def calculate_total_fees(prices: list[float], num_contracts: int = 1) -> float:
    """
    Calculate total fees for multiple contracts.

    Args:
        prices: List of contract prices as decimals
        num_contracts: Number of contracts per position

    Returns:
        Total fees in dollars
    """
    return sum(calculate_fee(p, num_contracts) for p in prices)


def fee_as_percentage(price: float) -> float:
    """
    Calculate fee as percentage of contract cost.

    Args:
        price: Contract price as decimal

    Returns:
        Fee as percentage of cost
    """
    if not 0 < price < 1:
        return 0.0

    fee = calculate_fee(price, 1)
    return fee / price
