"""
Final backtest with corrected strategies.

The key insight: We need to find where market prices DISAGREE with outcomes.
"""

from __future__ import annotations

import httpx
import numpy as np


def fetch_markets() -> list[dict]:
    """Fetch settled markets."""
    print("Fetching markets...")
    client = httpx.Client(timeout=60.0)
    base_url = "https://api.elections.kalshi.com/trade-api/v2"
    
    all_markets = []
    cursor = None
    
    for _ in range(10):
        params = {"limit": 200, "status": "settled"}
        if cursor:
            params["cursor"] = cursor
        
        try:
            response = client.get(f"{base_url}/markets", params=params)
            if response.status_code == 429:
                break
            response.raise_for_status()
            data = response.json()
            markets = data.get("markets", [])
            all_markets.extend(markets)
            cursor = data.get("cursor")
            if not cursor or not markets:
                break
        except Exception:
            break
    
    client.close()
    print(f"  Got {len(all_markets)} markets")
    return all_markets


def calculate_fee(price: float) -> float:
    if price <= 0 or price >= 1:
        return 0.0
    return max(0.01, np.ceil(0.07 * price * (1 - price) * 100) / 100)


def strategy_contrarian(markets: list[dict]) -> list[dict]:
    """
    Contrarian: Bet AGAINST extreme consensus.
    When price > 90%, bet NO. When price < 10%, bet YES.
    Hypothesis: Extreme prices often overshoot.
    """
    signals = []
    
    for m in markets:
        price = m.get("last_price", 0) / 100
        result = m.get("result", "").lower() == "yes"
        volume = m.get("volume", 0)
        
        if volume < 50:
            continue
        
        if price > 0.90:
            cost = (1 - price) + calculate_fee(1 - price) + 0.01
            pnl = (1.0 - cost) if not result else -cost
            signals.append({
                "ticker": m.get("ticker"),
                "strategy": "contrarian_high",
                "price": price,
                "bet": "NO",
                "result": result,
                "pnl": pnl,
            })
        
        elif price < 0.10:
            cost = price + calculate_fee(price) + 0.01
            pnl = (1.0 - cost) if result else -cost
            signals.append({
                "ticker": m.get("ticker"),
                "strategy": "contrarian_low",
                "price": price,
                "bet": "YES",
                "result": result,
                "pnl": pnl,
            })
    
    return signals


def strategy_momentum(markets: list[dict]) -> list[dict]:
    """
    Momentum: Bet WITH the crowd on moderate prices.
    When 60% < price < 85%, bet YES. When 15% < price < 40%, bet NO.
    Hypothesis: Moderate consensus is usually right.
    """
    signals = []
    
    for m in markets:
        price = m.get("last_price", 0) / 100
        result = m.get("result", "").lower() == "yes"
        volume = m.get("volume", 0)
        
        if volume < 100:
            continue
        
        if 0.60 < price < 0.85:
            cost = price + calculate_fee(price) + 0.01
            pnl = (1.0 - cost) if result else -cost
            signals.append({
                "ticker": m.get("ticker"),
                "strategy": "momentum_yes",
                "price": price,
                "bet": "YES",
                "result": result,
                "pnl": pnl,
            })
        
        elif 0.15 < price < 0.40:
            cost = (1 - price) + calculate_fee(1 - price) + 0.01
            pnl = (1.0 - cost) if not result else -cost
            signals.append({
                "ticker": m.get("ticker"),
                "strategy": "momentum_no",
                "price": price,
                "bet": "NO",
                "result": result,
                "pnl": pnl,
            })
    
    return signals


def strategy_value(markets: list[dict]) -> list[dict]:
    """
    Value: Look for mispriced 50/50 events.
    When price is near 50% but outcome is decisive, there was edge.
    """
    signals = []
    
    for m in markets:
        price = m.get("last_price", 0) / 100
        result = m.get("result", "").lower() == "yes"
        volume = m.get("volume", 0)
        
        if volume < 200:
            continue
        
        if 0.45 < price < 0.55:
            cost = price + calculate_fee(price) + 0.01
            pnl = (1.0 - cost) if result else -cost
            signals.append({
                "ticker": m.get("ticker"),
                "strategy": "value_50_50",
                "price": price,
                "bet": "YES",
                "result": result,
                "pnl": pnl,
            })
    
    return signals


def evaluate_strategy(name: str, signals: list[dict]) -> dict:
    """Evaluate a strategy's performance."""
    if not signals:
        return {"name": name, "trades": 0, "return": 0}
    
    pnls = [s["pnl"] for s in signals]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    
    initial = 10000.0
    capital = initial
    
    for s in signals[:100]:
        position = min(capital * 0.03, 300)
        scale = position / 0.5
        capital += s["pnl"] * scale
        if capital < 1000:
            break
    
    total_return = (capital - initial) / initial
    win_rate = len(wins) / len(pnls) if pnls else 0
    
    return {
        "name": name,
        "trades": len(signals),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "return": total_return,
        "final": capital,
        "avg_pnl": np.mean(pnls),
    }


def run_final_backtest():
    print("=" * 60)
    print("FINAL BACKTEST - FINDING WHAT WORKS")
    print("=" * 60)
    
    markets = fetch_markets()
    if not markets:
        print("No data")
        return
    
    strategies = [
        ("Contrarian", strategy_contrarian(markets)),
        ("Momentum", strategy_momentum(markets)),
        ("Value 50/50", strategy_value(markets)),
    ]
    
    print("\n" + "=" * 60)
    print("STRATEGY COMPARISON")
    print("=" * 60)
    
    results = []
    for name, signals in strategies:
        r = evaluate_strategy(name, signals)
        results.append(r)
        
        print(f"\n{name}:")
        print(f"  Trades:     {r['trades']}")
        if r['trades'] > 0:
            print(f"  Win Rate:   {r['win_rate']:.1%}")
            print(f"  Return:     {r['return']:+.2%}")
            print(f"  Final:      ${r['final']:,.2f}")
            print(f"  Avg P&L:    ${r['avg_pnl']:.4f}")
    
    best = max(results, key=lambda x: x['return'])
    
    print("\n" + "=" * 60)
    print("ANALYSIS")
    print("=" * 60)
    
    if best['return'] > 0.10:
        print(f"\n✓ PROFITABLE: {best['name']}")
        print(f"  Return: {best['return']:+.2%}")
        print(f"  Win Rate: {best['win_rate']:.1%}")
        print("\n  This strategy shows real edge!")
        print("  Next steps:")
        print("    1. Paper trade for 2 weeks")
        print("    2. Start with small positions")
        print("    3. Track execution slippage")
    elif best['return'] > 0:
        print(f"\n~ MARGINAL: {best['name']}")
        print(f"  Return: {best['return']:+.2%}")
        print("\n  Small edge exists but may not survive costs.")
    else:
        print("\n✗ NO EDGE FOUND")
        print("\n  All strategies lost money.")
        print("  The market is efficient for simple rules.")
        print("\n  To find edge, you need:")
        print("    - Domain expertise (sports, politics, etc)")
        print("    - Faster information sources")
        print("    - Better probability models")
        print("    - Or: become a market maker")


if __name__ == "__main__":
    run_final_backtest()
