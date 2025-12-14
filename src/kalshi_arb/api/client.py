"""Kalshi API client for market data and trading operations."""
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import httpx

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.backends import default_backend
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


class KalshiClient:
    """
    Client for interacting with the Kalshi API.

    Handles authentication, rate limiting, and caching for market data.
    """

    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
    DEMO_URL = "https://demo-api.kalshi.co/trade-api/v2"

    def __init__(
        self,
        api_key: str = "",
        private_key_path: str | None = None,
        base_url: str | None = None,
        cache_ttl: int = 30,
        demo: bool = False,
    ):
        self.api_key = api_key
        self.private_key_path = private_key_path
        self._private_key = None

        if demo:
            self.base_url = base_url or self.DEMO_URL
        else:
            self.base_url = base_url or self.BASE_URL

        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, Any]] = {}
        self._client = httpx.Client(timeout=30.0)

        if private_key_path and HAS_CRYPTO:
            self._load_private_key(private_key_path)

    def _load_private_key(self, key_path: str) -> None:
        """Load RSA private key from PEM file."""
        with open(key_path, "rb") as key_file:
            self._private_key = serialization.load_pem_private_key(
                key_file.read(),
                password=None,
                backend=default_backend(),
            )

    def _sign_request(self, method: str, path: str) -> dict[str, str]:
        """
        Generate RSA-PSS signature headers for Kalshi API.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API endpoint path (without query params)

        Returns:
            Dict with KALSHI-ACCESS-* headers
        """
        if not self._private_key or not self.api_key:
            return {}

        timestamp_ms = int(time.time() * 1000)
        timestamp_str = str(timestamp_ms)

        path_without_query = path.split("?")[0]
        message = f"{timestamp_str}{method}{path_without_query}"

        signature = self._private_key.sign(
            message.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )

        sig_b64 = base64.b64encode(signature).decode("utf-8")

        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": sig_b64,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_str,
        }

    def _get_cached(self, key: str) -> Any | None:
        """Get cached response if still valid."""
        if key in self._cache:
            timestamp, data = self._cache[key]
            if time.time() - timestamp < self.cache_ttl:
                return data
            del self._cache[key]
        return None

    def _set_cache(self, key: str, data: Any) -> None:
        """Cache response with timestamp."""
        self._cache[key] = (time.time(), data)

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        auth_required: bool = False,
    ) -> dict[str, Any]:
        """Make HTTP request to Kalshi API."""
        url = f"{self.base_url}{endpoint}"
        headers = {"Content-Type": "application/json"}

        if auth_required and self._private_key:
            full_path = f"/trade-api/v2{endpoint}"
            auth_headers = self._sign_request(method.upper(), full_path)
            headers.update(auth_headers)

        response = self._client.request(
            method=method,
            url=url,
            params=params,
            json=json_data,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

    def is_authenticated(self) -> bool:
        """Check if client has valid authentication credentials."""
        return self._private_key is not None and bool(self.api_key)

    def test_connection(self) -> bool:
        """
        Test API connection by fetching balance.

        Returns:
            True if connection successful
        """
        if not self.is_authenticated():
            return False

        try:
            self.get_balance()
            return True
        except httpx.HTTPError:
            return False

    def get_markets(
        self,
        limit: int = 1000,
        cursor: str | None = None,
        status: str | None = None,
        series_ticker: str | None = None,
    ) -> dict[str, Any]:
        """
        Get list of markets.

        Args:
            limit: Maximum number of markets to return
            cursor: Pagination cursor
            status: Filter by status (open, closed, settled)
            series_ticker: Filter by series

        Returns:
            API response with markets list
        """
        cache_key = f"markets:{limit}:{cursor}:{status}:{series_ticker}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if status:
            params["status"] = status
        if series_ticker:
            params["series_ticker"] = series_ticker

        result = self._request("GET", "/markets", params=params)
        self._set_cache(cache_key, result)
        return result

    def get_market(self, ticker: str) -> dict[str, Any]:
        """
        Get single market details.

        Args:
            ticker: Market ticker

        Returns:
            Market data
        """
        cache_key = f"market:{ticker}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        result = self._request("GET", f"/markets/{ticker}")
        self._set_cache(cache_key, result)
        return result

    def get_orderbook(self, ticker: str, depth: int | None = None) -> dict[str, Any]:
        """
        Get order book for a market.

        Args:
            ticker: Market ticker
            depth: Order book depth

        Returns:
            Order book data with YES bids
        """
        cache_key = f"orderbook:{ticker}:{depth}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        params = {"depth": depth} if depth else None
        result = self._request("GET", f"/markets/{ticker}/orderbook", params=params)
        self._set_cache(cache_key, result)
        return result

    def get_series(self, series_ticker: str) -> dict[str, Any]:
        """
        Get series metadata.

        Args:
            series_ticker: Series ticker

        Returns:
            Series data
        """
        cache_key = f"series:{series_ticker}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        result = self._request("GET", f"/series/{series_ticker}")
        self._set_cache(cache_key, result)
        return result

    def get_candlesticks(
        self,
        ticker: str,
        period_interval: int = 60,
        start_ts: int | None = None,
        end_ts: int | None = None,
    ) -> dict[str, Any]:
        """
        Get OHLC candlestick data.

        Args:
            ticker: Market ticker
            period_interval: Candle period in minutes
            start_ts: Start timestamp
            end_ts: End timestamp

        Returns:
            Candlestick data
        """
        params: dict[str, Any] = {"period_interval": period_interval}
        if start_ts:
            params["start_ts"] = start_ts
        if end_ts:
            params["end_ts"] = end_ts

        return self._request("GET", f"/markets/{ticker}/candlesticks", params=params)

    def get_positions(self) -> dict[str, Any]:
        """Get current positions (requires auth)."""
        return self._request("GET", "/portfolio/positions", auth_required=True)

    def get_balance(self) -> dict[str, Any]:
        """Get account balance (requires auth)."""
        return self._request("GET", "/portfolio/balance", auth_required=True)

    def place_order(
        self,
        ticker: str,
        side: str,
        action: str,
        count: int,
        price: int,
        order_type: str = "limit",
    ) -> dict[str, Any]:
        """
        Place an order.

        Args:
            ticker: Market ticker
            side: "yes" or "no"
            action: "buy" or "sell"
            count: Number of contracts
            price: Price in cents (1-99)
            order_type: "limit" or "market"

        Returns:
            Order response
        """
        return self._request(
            "POST",
            "/portfolio/orders",
            json_data={
                "ticker": ticker,
                "side": side,
                "action": action,
                "count": count,
                "type": order_type,
                "yes_price" if side == "yes" else "no_price": price,
            },
            auth_required=True,
        )

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an order."""
        return self._request(
            "DELETE",
            f"/portfolio/orders/{order_id}",
            auth_required=True,
        )

    def get_order(self, order_id: str) -> dict[str, Any]:
        """Get order status."""
        return self._request(
            "GET",
            f"/portfolio/orders/{order_id}",
            auth_required=True,
        )

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> "KalshiClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
