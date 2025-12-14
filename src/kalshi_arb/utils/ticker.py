"""Ticker parsing utilities for Kalshi markets."""
from __future__ import annotations


import re
from datetime import datetime
from typing import NamedTuple


class ParsedTicker(NamedTuple):
    """Parsed components of a Kalshi ticker."""

    series: str
    expiration_date: datetime
    strike_type: str
    strike_id: int
    raw: str


MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
    "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
    "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

TICKER_PATTERN = re.compile(r"^([A-Z0-9]+)-(\d{2})([A-Z]{3})(\d{2})-([A-Z])(\d+)$")


def parse_ticker(ticker: str) -> ParsedTicker | None:
    """
    Parse a Kalshi ticker into its components.

    Ticker format: {SERIES}-{YYMMDD}-{STRIKE_TYPE}{STRIKE_ID}
    Example: KXHIGHNY-24JAN01-T60

    Args:
        ticker: Raw ticker string

    Returns:
        ParsedTicker if valid, None otherwise
    """
    match = TICKER_PATTERN.match(ticker)
    if not match:
        return None

    series, yy, month_str, dd, strike_type, strike_id = match.groups()

    month = MONTH_MAP.get(month_str)
    if month is None:
        return None

    try:
        expiration = datetime(
            year=2000 + int(yy),
            month=month,
            day=int(dd),
        )
    except ValueError:
        return None

    return ParsedTicker(
        series=series,
        expiration_date=expiration,
        strike_type=strike_type,
        strike_id=int(strike_id),
        raw=ticker,
    )


def extract_series(ticker: str) -> str | None:
    """Extract series from ticker without full parsing."""
    parts = ticker.split("-")
    return parts[0] if parts else None
