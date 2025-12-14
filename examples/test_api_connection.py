"""Test Kalshi API connection with RSA-PSS authentication."""

from __future__ import annotations

import os
import sys

from kalshi_arb.api.client import KalshiClient


def test_demo_connection():
    """Test connection to Kalshi demo API."""
    print("=" * 50)
    print("KALSHI API CONNECTION TEST")
    print("=" * 50)

    api_key = os.getenv("KALSHI_API_KEY", "")
    private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "trade.txt")
    demo = os.getenv("KALSHI_DEMO", "true").lower() == "true"

    print(f"\nConfiguration:")
    print(f"  API Key: {api_key[:8]}..." if api_key else "  API Key: NOT SET")
    print(f"  Private Key: {private_key_path}")
    print(f"  Demo Mode: {demo}")

    if not api_key:
        print("\nERROR: KALSHI_API_KEY not set")
        print("Set it via: export KALSHI_API_KEY=your-api-key-id")
        return False

    if not os.path.exists(private_key_path):
        print(f"\nERROR: Private key file not found: {private_key_path}")
        return False

    print("\nInitializing client...")
    client = KalshiClient(
        api_key=api_key,
        private_key_path=private_key_path,
        demo=demo,
    )

    print(f"  Base URL: {client.base_url}")
    print(f"  Authenticated: {client.is_authenticated()}")

    if not client.is_authenticated():
        print("\nERROR: Failed to load private key")
        return False

    print("\n1. Testing Balance Endpoint...")
    try:
        balance = client.get_balance()
        print(f"   ✓ Balance: ${balance.get('balance', 0) / 100:.2f}")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
        return False

    print("\n2. Testing Markets Endpoint...")
    try:
        markets = client.get_markets(limit=5)
        market_list = markets.get("markets", [])
        print(f"   ✓ Retrieved {len(market_list)} markets")
        for m in market_list[:3]:
            print(f"      - {m.get('ticker')}: {m.get('title', '')[:40]}...")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
        return False

    print("\n3. Testing Positions Endpoint...")
    try:
        positions = client.get_positions()
        pos_list = positions.get("market_positions", [])
        print(f"   ✓ Retrieved {len(pos_list)} positions")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
        return False

    print("\n" + "=" * 50)
    print("ALL TESTS PASSED ✓")
    print("=" * 50)

    client.close()
    return True


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    success = test_demo_connection()
    sys.exit(0 if success else 1)
