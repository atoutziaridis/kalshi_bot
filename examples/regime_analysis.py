"""
Regime Analysis - Why does chronological test fail but random splits work?

Investigate if there's a time-based regime change in market efficiency.
"""

from __future__ import annotations

import time
from datetime import datetime

import httpx
import numpy as np
from scipy import stats


def fetch_markets(max_markets: int = 30000) -> list[dict]:
    """Fetch settled markets."""
    print(f"Fetching {max_markets} markets...")
    client = httpx.Client(timeout=60.0)
    base_url = "https://api.elections.kalshi.com/trade-api/v2"

    all_markets = []
    cursor = None
    retries = 0

    while len(all_markets) < max_markets and retries < 30:
        params = {"limit": 200, "status": "settled"}
        if cursor:
            params["cursor"] = cursor
        try:
            response = client.get(f"{base_url}/markets", params=params)
            if response.status_code == 429:
                retries += 1
                time.sleep(2)
                continue
            response.raise_for_status()
            data = response.json()
            markets = data.get("markets", [])
            all_markets.extend(markets)
            cursor = data.get("cursor")
            if not cursor or not markets:
                break
            retries = 0
        except Exception:
            retries += 1
            time.sleep(1)

    client.close()
    print(f"  Total: {len(all_markets)} markets")
    return all_markets


def analyze_by_settlement_date(markets: list[dict]):
    """Analyze strategy performance by settlement date."""
    print("\nAnalyzing by settlement date...")

    dated_markets = []
    for m in markets:
        settle_str = m.get("settlement_date") or m.get("close_time")
        if settle_str:
            try:
                settle = datetime.fromisoformat(settle_str.replace("Z", "+00:00"))
                dated_markets.append((settle, m))
            except:
                pass

    if not dated_markets:
        print("No settlement dates found")
        return

    dated_markets.sort(key=lambda x: x[0])

    print(f"Date range: {dated_markets[0][0].date()} to {dated_markets[-1][0].date()}")

    chunk_size = len(dated_markets) // 5
    for i in range(5):
        start_idx = i * chunk_size
        end_idx = (i + 1) * chunk_size if i < 4 else len(dated_markets)
        chunk = [m for _, m in dated_markets[start_idx:end_idx]]

        signals = generate_signals(chunk)
        if signals:
            wins = sum(1 for s in signals if s["won"])
            wr = wins / len(signals)
            avg_pnl = np.mean([s["pnl"] for s in signals])

            start_date = dated_markets[start_idx][0].date()
            end_date = dated_markets[end_idx - 1][0].date()

            print(f"\nPeriod {i+1}: {start_date} to {end_date}")
            print(f"  Trades: {len(signals)}")
            print(f"  Win rate: {wr:.1%}")
            print(f"  Avg PnL: {avg_pnl:+.4f}")


def generate_signals(markets: list[dict]) -> list[dict]:
    """Generate signals with original config."""
    signals = []

    for m in markets:
        last_price = m.get("last_price", 0)
        if not last_price:
            continue

        price = last_price / 100.0
        volume = m.get("volume", 0) or 0
        result = m.get("result", "").lower() == "yes"

        if volume < 50:
            continue

        if 0.65 < price < 0.78:
            fee = max(0.01, 0.07 * price * (1 - price))
            cost = price + fee + 0.01
            if cost < 1.0:
                pnl = (1.0 - cost) if result else -cost
                signals.append({"won": result, "pnl": pnl, "price": price})

        elif 0.22 < price < 0.40:
            no_price = 1 - price
            fee = max(0.01, 0.07 * no_price * (1 - no_price))
            cost = no_price + fee + 0.01
            if cost < 1.0:
                pnl = (1.0 - cost) if not result else -cost
                signals.append({"won": not result, "pnl": pnl, "price": price})

    return signals


def analyze_by_volume_buckets(markets: list[dict]):
    """Check if strategy works better on high/low volume markets."""
    print("\n" + "=" * 80)
    print("VOLUME BUCKET ANALYSIS")
    print("=" * 80)

    volumes = [m.get("volume", 0) for m in markets if m.get("volume")]
    if not volumes:
        return

    p25 = np.percentile(volumes, 25)
    p50 = np.percentile(volumes, 50)
    p75 = np.percentile(volumes, 75)

    print(f"\nVolume percentiles: 25%={p25:.0f}, 50%={p50:.0f}, 75%={p75:.0f}")

    buckets = [
        ("Low (0-25%)", 0, p25),
        ("Med-Low (25-50%)", p25, p50),
        ("Med-High (50-75%)", p50, p75),
        ("High (75-100%)", p75, float('inf')),
    ]

    for name, low, high in buckets:
        bucket_markets = [m for m in markets
                         if low <= m.get("volume", 0) < high]
        signals = generate_signals(bucket_markets)

        if len(signals) >= 20:
            wins = sum(1 for s in signals if s["won"])
            wr = wins / len(signals)
            avg_pnl = np.mean([s["pnl"] for s in signals])

            print(f"\n{name}:")
            print(f"  Markets: {len(bucket_markets)}")
            print(f"  Trades: {len(signals)}")
            print(f"  Win rate: {wr:.1%}")
            print(f"  Avg PnL: {avg_pnl:+.4f}")


def analyze_by_price_buckets(markets: list[dict]):
    """Check if certain price ranges work better."""
    print("\n" + "=" * 80)
    print("PRICE RANGE ANALYSIS")
    print("=" * 80)

    price_ranges = [
        ("YES 65-70%", 0.65, 0.70, "YES"),
        ("YES 70-75%", 0.70, 0.75, "YES"),
        ("YES 75-78%", 0.75, 0.78, "YES"),
        ("NO 22-28%", 0.22, 0.28, "NO"),
        ("NO 28-34%", 0.28, 0.34, "NO"),
        ("NO 34-40%", 0.34, 0.40, "NO"),
    ]

    for name, low, high, side in price_ranges:
        signals = []

        for m in markets:
            last_price = m.get("last_price", 0)
            if not last_price:
                continue

            price = last_price / 100.0
            volume = m.get("volume", 0) or 0
            result = m.get("result", "").lower() == "yes"

            if volume < 50:
                continue

            if low < price < high:
                if side == "YES":
                    fee = max(0.01, 0.07 * price * (1 - price))
                    cost = price + fee + 0.01
                    if cost < 1.0:
                        pnl = (1.0 - cost) if result else -cost
                        signals.append({"won": result, "pnl": pnl})
                else:
                    no_price = 1 - price
                    fee = max(0.01, 0.07 * no_price * (1 - no_price))
                    cost = no_price + fee + 0.01
                    if cost < 1.0:
                        pnl = (1.0 - cost) if not result else -cost
                        signals.append({"won": not result, "pnl": pnl})

        if len(signals) >= 10:
            wins = sum(1 for s in signals if s["won"])
            wr = wins / len(signals)
            avg_pnl = np.mean([s["pnl"] for s in signals])

            print(f"\n{name}:")
            print(f"  Trades: {len(signals)}")
            print(f"  Win rate: {wr:.1%}")
            print(f"  Avg PnL: {avg_pnl:+.4f}")


def run_regime_analysis():
    print("=" * 80)
    print("REGIME ANALYSIS - Finding What Works")
    print("=" * 80)

    markets = fetch_markets(30000)

    analyze_by_settlement_date(markets)
    analyze_by_volume_buckets(markets)
    analyze_by_price_buckets(markets)

    print("\n" + "=" * 80)
    print("CONCLUSIONS")
    print("=" * 80)
    print("\nThis analysis shows:")
    print("  1. Which time periods the strategy works/fails")
    print("  2. Which volume levels are most profitable")
    print("  3. Which specific price ranges have edge")
    print("\nUse these insights to refine the strategy.")
    print("=" * 80)


if __name__ == "__main__":
    run_regime_analysis()
