"""
Authenticated Live Trading Signals

Uses your existing Kalshi API client to fetch live, tradeable markets.
Run this script to get current signals for the momentum strategy.
"""

from __future__ import annotations

import sys
import os
from datetime import datetime, timezone, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kalshi_arb.api.client import KalshiClient


def fetch_live_markets(client: KalshiClient, limit: int = 500) -> list[dict]:
    """Fetch live markets using authenticated API."""
    print(f"Fetching {limit} live markets from Kalshi...")
    
    markets = []
    cursor = None
    
    while len(markets) < limit:
        try:
            response = client.get_markets(
                limit=min(200, limit - len(markets)),
                cursor=cursor,
                status="open"
            )
            batch = response.get("markets", [])
            markets.extend(batch)
            cursor = response.get("cursor")
            
            print(f"  ...{len(markets)} markets fetched")
            
            if not cursor or not batch:
                break
        except Exception as e:
            print(f"  Error fetching batch: {e}")
            break
    
    print(f"  Total: {len(markets)} markets")
    return markets


def apply_momentum_strategy(markets: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Apply momentum strategy:
    - Buy YES when 65% < price < 78%
    - Buy NO when 22% < price < 40%
    - Volume >= 50
    """
    yes_signals = []
    no_signals = []
    
    for m in markets:
        ticker = m.get("ticker", "")
        title = m.get("title", "")
        volume = m.get("volume", 0) or 0
        
        # Skip low volume
        if volume < 50:
            continue
        
        # Get price from bid/ask or last trade
        yes_bid = m.get("yes_bid", 0) or 0
        yes_ask = m.get("yes_ask", 0) or 0
        last_price = m.get("last_price", 0) or 0
        
        if yes_bid and yes_ask:
            price = (yes_bid + yes_ask) / 2 / 100
        elif last_price:
            price = last_price / 100
        else:
            continue
        
        # Calculate days to expiry
        exp_str = m.get("close_time") or m.get("expiration_time", "")
        days_left = "N/A"
        if exp_str:
            try:
                exp_time = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                days_left = (exp_time - datetime.now(timezone.utc)).days
            except:
                pass
        
        signal = {
            "ticker": ticker,
            "title": title[:50],
            "price": price,
            "volume": volume,
            "days_left": days_left,
        }
        
        # Apply strategy
        if 0.65 < price < 0.78:
            signal["action"] = "BUY YES"
            yes_signals.append(signal)
        elif 0.22 < price < 0.40:
            signal["action"] = "BUY NO"
            no_signals.append(signal)
    
    return yes_signals, no_signals


def run_authenticated_signals():
    print("=" * 70)
    print("AUTHENTICATED LIVE TRADING SIGNALS")
    print("=" * 70)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\nStrategy: Momentum (bet WITH the crowd at moderate confidence)")
    print("  - Buy YES when 65% < price < 78%")
    print("  - Buy NO when 22% < price < 40%")
    print("  - Volume >= 50 contracts")
    
    try:
        # Initialize client with your credentials
        client = KalshiClient()
        print("\n✓ API client initialized successfully")
    except Exception as e:
        print(f"\n✗ Failed to initialize API client: {e}")
        print("\nMake sure your .env file has:")
        print("  KALSHI_KEY_ID=your-key-id")
        print("  KALSHI_PRIVATE_KEY_PATH=./path/to/your/key")
        print("  KALSHI_BASE_URL=https://trading-api.kalshi.com")
        return
    
    # Fetch markets
    markets = fetch_live_markets(client, limit=1000)
    
    if not markets:
        print("\nNo markets fetched")
        return
    
    # Apply strategy
    yes_signals, no_signals = apply_momentum_strategy(markets)
    
    print(f"\nFound {len(yes_signals)} YES signals and {len(no_signals)} NO signals")
    
    # Sort by volume
    yes_signals.sort(key=lambda x: x["volume"], reverse=True)
    no_signals.sort(key=lambda x: x["volume"], reverse=True)
    
    # Display results
    print("\n" + "=" * 70)
    print("TOP BUY YES SIGNALS (65-78% price)")
    print("=" * 70)
    
    for s in yes_signals[:10]:
        print(f"\n{s['price']:.0%} @ {s['ticker']}")
        print(f"  Volume: {s['volume']:,} | Expires: {s['days_left']} days")
        print(f"  {s['title']}")
    
    print("\n" + "=" * 70)
    print("TOP BUY NO SIGNALS (22-40% price)")
    print("=" * 70)
    
    for s in no_signals[:10]:
        print(f"\n{s['price']:.0%} @ {s['ticker']}")
        print(f"  Volume: {s['volume']:,} | Expires: {s['days_left']} days")
        print(f"  {s['title']}")
    
    # Recommendations
    print("\n" + "=" * 70)
    print("RECOMMENDED TRADES")
    print("=" * 70)
    
    top_yes = yes_signals[:3]
    top_no = no_signals[:3]
    
    print("\n🟢 BUY YES:")
    for i, s in enumerate(top_yes, 1):
        print(f"{i}. {s['ticker']} @ {s['price']:.0%} (vol: {s['volume']:,})")
        print(f"   {s['title']}")
    
    print("\n🔴 BUY NO:")
    for i, s in enumerate(top_no, 1):
        print(f"{i}. {s['ticker']} @ {s['price']:.0%} (vol: {s['volume']:,})")
        print(f"   {s['title']}")
    
    print("\n" + "=" * 70)
    print("⚠️  DISCLAIMER:")
    print("- Paper trade first before risking real capital")
    print("- Position size: 2% of capital, max $200 per trade")
    print("- This strategy is not 95% statistically significant")
    print("=" * 70)


if __name__ == "__main__":
    run_authenticated_signals()
