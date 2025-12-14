"""Historical data fetching from Kalshi API for backtesting."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from kalshi_arb.api.client import KalshiClient


class KalshiDataFetcher:
    """
    Fetch historical market data from Kalshi API.
    
    Supports:
    - Candlestick (OHLC) data
    - Market metadata
    - Historical order book snapshots (when available)
    """

    def __init__(self, client: KalshiClient | None = None):
        self.client = client or KalshiClient()

    def fetch_candlesticks(
        self,
        ticker: str,
        period_interval: int = 60,
        start_ts: int | None = None,
        end_ts: int | None = None,
        limit: int = 200,
    ) -> pd.DataFrame:
        """
        Fetch OHLC candlestick data from Kalshi API.

        Args:
            ticker: Market ticker
            period_interval: Candle period in minutes (1, 5, 15, 60, 1440)
            start_ts: Start timestamp (Unix seconds)
            end_ts: End timestamp (Unix seconds)
            limit: Max candles to fetch (API max: 200)

        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        response = self.client.get_candlesticks(
            ticker=ticker,
            period_interval=period_interval,
            start_ts=start_ts,
            end_ts=end_ts,
        )

        candlesticks = response.get("candlesticks", [])
        if not candlesticks:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

        df = pd.DataFrame(candlesticks)

        if "ts" in df.columns:
            df["timestamp"] = pd.to_datetime(df["ts"], unit="s")
        elif "end_period_ts" in df.columns:
            df["timestamp"] = pd.to_datetime(df["end_period_ts"], unit="s")

        column_map = {
            "open_price": "open",
            "high_price": "high",
            "low_price": "low",
            "close_price": "close",
            "yes_price": "close",
        }
        df = df.rename(columns=column_map)

        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = df[col] / 100.0

        if "volume" not in df.columns:
            df["volume"] = 0

        return df[["timestamp", "open", "high", "low", "close", "volume"]]

    def fetch_market_history(
        self,
        ticker: str,
        days: int = 30,
        interval_minutes: int = 60,
    ) -> pd.DataFrame:
        """
        Fetch complete market history for backtesting.

        Args:
            ticker: Market ticker
            days: Number of days of history
            interval_minutes: Candle interval

        Returns:
            DataFrame with OHLCV data
        """
        end_ts = int(datetime.now().timestamp())
        start_ts = int((datetime.now() - timedelta(days=days)).timestamp())

        all_data = []
        current_end = end_ts

        while current_end > start_ts:
            df = self.fetch_candlesticks(
                ticker=ticker,
                period_interval=interval_minutes,
                end_ts=current_end,
            )

            if df.empty:
                break

            all_data.append(df)

            earliest = df["timestamp"].min()
            current_end = int(earliest.timestamp()) - 1

            if current_end <= start_ts:
                break

        if not all_data:
            return pd.DataFrame()

        combined = pd.concat(all_data, ignore_index=True)
        combined = combined.drop_duplicates(subset=["timestamp"])
        combined = combined.sort_values("timestamp").reset_index(drop=True)

        return combined

    def fetch_closed_markets(
        self,
        series_ticker: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Fetch list of closed/settled markets for backtesting.

        Args:
            series_ticker: Filter by series
            limit: Max markets to fetch

        Returns:
            List of market metadata dicts
        """
        response = self.client.get_markets(
            limit=limit,
            status="settled",
            series_ticker=series_ticker,
        )

        return response.get("markets", [])

    def build_backtest_dataset(
        self,
        tickers: list[str],
        days: int = 30,
        interval_minutes: int = 60,
    ) -> pd.DataFrame:
        """
        Build combined dataset for multiple markets.

        Args:
            tickers: List of market tickers
            days: Days of history
            interval_minutes: Candle interval

        Returns:
            DataFrame with ticker column for multi-market backtesting
        """
        all_data = []

        for ticker in tickers:
            df = self.fetch_market_history(
                ticker=ticker,
                days=days,
                interval_minutes=interval_minutes,
            )

            if not df.empty:
                df["ticker"] = ticker
                all_data.append(df)

        if not all_data:
            return pd.DataFrame()

        combined = pd.concat(all_data, ignore_index=True)
        combined = combined.sort_values(["timestamp", "ticker"]).reset_index(drop=True)

        return combined

    def get_market_resolution(self, ticker: str) -> dict[str, Any]:
        """
        Get market resolution outcome.

        Returns:
            Dict with result ('yes', 'no', None) and settlement details
        """
        response = self.client.get_market(ticker)
        market = response.get("market", {})

        return {
            "ticker": ticker,
            "result": market.get("result"),
            "status": market.get("status"),
            "settlement_time": market.get("settlement_time"),
        }
