"""
Live Trading Signals - Fetch current markets and apply momentum strategy.

Fetches markets expiring within 2 days and applies the validated strategy:
- Buy YES when 65% < price < 78%
- Buy NO when 22% < price < 40%
- Volume >= 50
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import httpx


def fetch_active_markets() -> list[dict]:
    """Fetch active (open) markets from Kalshi - limited for speed."""
    print("Fetching active markets (quick scan)...")
    client = httpx.Client(timeout=15.0)
    base_url = "https://api.elections.kalshi.com/trade-api/v2"

    all_markets = []
    cursor = None

    for _ in range(3):
        params = {"limit": 100, "status": "open"}
        if cursor:
            params["cursor"] = cursor
        try:
            response = client.get(f"{base_url}/markets", params=params)
            if response.status_code == 429:
                time.sleep(1)
                continue
            response.raise_for_status()
            data = response.json()
            markets = data.get("markets", [])
            all_markets.extend(markets)
            cursor = data.get("cursor")
            if not cursor or not markets:
                break
            print(f"  ...{len(all_markets)} markets so far")
        except Exception as e:
            print(f"  Error: {e}")
            break

    client.close()
    print(f"  {len(all_markets)} active markets fetched")
    return all_markets


def filter_expiring_soon(markets: list[dict], max_days: int = 7) -> list[dict]:
    """Filter markets expiring within max_days."""
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=max_days)

    expiring = []
    for m in markets:
        exp_str = m.get("expiration_time") or m.get("close_time")
        if not exp_str:
            m["_hours_left"] = 999
            expiring.append(m)
            continue
        try:
            exp_time = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
            if now < exp_time <= cutoff:
                m["_hours_left"] = (exp_time - now).total_seconds() / 3600
                expiring.append(m)
        except Exception:
            m["_hours_left"] = 999
            expiring.append(m)

    return expiring


def apply_momentum_strategy(markets: list[dict]) -> list[dict]:
    """
    Apply the validated momentum strategy:
    - Buy YES when 65% < price < 78%
    - Buy NO when 22% < price < 40%
    - Volume >= 50
    """
    signals = []

    for m in markets:
        ticker = m.get("ticker", "")
        title = m.get("title", "")
        volume = m.get("volume", 0) or 0

        yes_bid = m.get("yes_bid", 0) or 0
        yes_ask = m.get("yes_ask", 0) or 0

        if yes_bid == 0 and yes_ask == 0:
            last_price = m.get("last_price", 0)
            if last_price:
                price = last_price / 100
            else:
                continue
        else:
            price = (yes_bid + yes_ask) / 2 / 100 if yes_bid and yes_ask else 0

        if price == 0:
            last_price = m.get("last_price", 0)
            if last_price:
                price = last_price / 100
            else:
                continue

        if volume < 50:
            continue

        hours_left = m.get("_hours_left", 48)
        signal = None

        if 0.65 < price < 0.78:
            signal = {
                "ticker": ticker,
                "title": title[:60],
                "action": "BUY YES",
                "price": price,
                "volume": volume,
                "hours_left": hours_left,
                "confidence": "HIGH" if 0.68 < price < 0.75 else "MEDIUM",
            }
        elif 0.22 < price < 0.40:
            signal = {
                "ticker": ticker,
                "title": title[:60],
                "action": "BUY NO",
                "price": price,
                "volume": volume,
                "hours_left": hours_left,
                "confidence": "HIGH" if 0.25 < price < 0.35 else "MEDIUM",
            }

        if signal:
            signals.append(signal)

    return signals


def run_live_signals():
    print("=" * 70)
    print("LIVE TRADING SIGNALS")
    print("=" * 70)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\nStrategy: Momentum (bet WITH the crowd at moderate confidence)")
    print("  - Buy YES when 65% < price < 78%")
    print("  - Buy NO when 22% < price < 40%")
    print("  - Volume >= 50 contracts")

    markets = fetch_active_markets()
    if not markets:
        print("No markets fetched")
        return

    expiring = filter_expiring_soon(markets, max_days=7)
    print(f"\nMarkets within 7 days or active: {len(expiring)}")

    signals = apply_momentum_strategy(expiring)

    print("\n" + "=" * 70)
    print("TRADE SIGNALS")
    print("=" * 70)

    if not signals:
        print("\nNo signals matching strategy criteria.")
        print("\nChecking all expiring markets for context...")

        for m in sorted(expiring, key=lambda x: x.get("volume", 0), reverse=True)[:10]:
            ticker = m.get("ticker", "")
            title = m.get("title", "")[:50]
            volume = m.get("volume", 0)
            last_price = m.get("last_price", 0)
            hours = m.get("_hours_left", 0)
            print(f"  {ticker}: {last_price}¢, vol={volume}, {hours:.1f}h - {title}")
    else:
        signals.sort(key=lambda x: (-1 if x["confidence"] == "HIGH" else 0, -x["volume"]))

        print(f"\nFound {len(signals)} signals:\n")

        for s in signals:
            conf_icon = "🟢" if s["confidence"] == "HIGH" else "🟡"
            print(f"{conf_icon} {s['action']} @ {s['price']:.0%}")
            print(f"   Ticker: {s['ticker']}")
            print(f"   Title:  {s['title']}")
            print(f"   Volume: {s['volume']} | Expires in: {s['hours_left']:.1f}h")
            print()

        print("=" * 70)
        print("RECOMMENDED TRADES (sorted by confidence + volume)")
        print("=" * 70)

        for i, s in enumerate(signals[:5], 1):
            print(f"\n{i}. {s['action']} on {s['ticker']}")
            print(f"   Price: {s['price']:.0%} | Volume: {s['volume']}")
            print(f"   {s['title']}")

    print("\n" + "=" * 70)
    print("⚠️  DISCLAIMER: Paper trade first. This is not financial advice.")
    print("=" * 70)


if __name__ == "__main__":
    run_live_signals()
