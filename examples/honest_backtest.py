"""
Honest backtest using real Kalshi market structure.

This backtest:
1. Fetches ALL available settled markets from Kalshi
2. Looks for ACTUAL mispricings (partition sum != 1)
3. Simulates what would have happened with realistic execution
4. Reports results WITHOUT bias
"""

from __future__ import annotations

import httpx
import numpy as np


def fetch_all_settled_markets() -> list[dict]:
    """Fetch settled markets from Kalshi public API."""
    print("Fetching settled markets from Kalshi...")
    
    client = httpx.Client(timeout=60.0)
    base_url = "https://api.elections.kalshi.com/trade-api/v2"
    
    all_markets = []
    cursor = None
    
    try:
        for _ in range(10):
            params = {"limit": 200, "status": "settled"}
            if cursor:
                params["cursor"] = cursor
            
            response = client.get(f"{base_url}/markets", params=params)
            response.raise_for_status()
            data = response.json()
            
            markets = data.get("markets", [])
            all_markets.extend(markets)
            
            cursor = data.get("cursor")
            if not cursor or not markets:
                break
        
        print(f"  Fetched {len(all_markets)} total settled markets")
        return all_markets
    except Exception as e:
        print(f"  API Error: {e}")
        return []
    finally:
        client.close()


def find_partition_violations(markets: list[dict]) -> list[dict]:
    """
    Find markets where partition sum != 1.
    
    In a proper partition (mutually exclusive outcomes), 
    sum of YES prices should equal 1.0
    """
    by_event = {}
    for m in markets:
        event = m.get("event_ticker", "")
        if event:
            if event not in by_event:
                by_event[event] = []
            by_event[event].append(m)
    
    violations = []
    
    for event, event_markets in by_event.items():
        if len(event_markets) < 2:
            continue
        
        prices = []
        for m in event_markets:
            price = m.get("last_price", 0) / 100
            if 0.01 <= price <= 0.99:
                prices.append(price)
        
        if len(prices) < 2:
            continue
        
        price_sum = sum(prices)
        deviation = abs(price_sum - 1.0)
        
        if deviation > 0.02:
            violations.append({
                "event": event,
                "markets": event_markets,
                "prices": prices,
                "sum": price_sum,
                "deviation": deviation,
                "side": "long" if price_sum < 1.0 else "short",
            })
    
    return violations


def calculate_fee(price: float) -> float:
    """Kalshi fee: 0.07 * p * (1-p), min 1 cent."""
    if price <= 0 or price >= 1:
        return 0.0
    return max(0.01, np.ceil(0.07 * price * (1 - price) * 100) / 100)


def simulate_partition_trade(violation: dict) -> dict:
    """
    Simulate trading a partition violation.
    
    Strategy:
    - If sum < 1: Buy all YES contracts (guaranteed $1 payout)
    - If sum > 1: Sell all YES / Buy all NO
    """
    prices = violation["prices"]
    markets = violation["markets"]
    
    total_cost = sum(prices)
    total_fees = sum(calculate_fee(p) for p in prices)
    spread_cost = 0.02 * len(prices)
    
    if violation["side"] == "long":
        entry_cost = total_cost + total_fees + spread_cost
        payout = 1.0
        pnl = payout - entry_cost
    else:
        entry_cost = (len(prices) - total_cost) + total_fees + spread_cost
        payout = 1.0
        pnl = payout - entry_cost
    
    results = []
    for m in markets:
        result = m.get("result", "").lower()
        results.append(result)
    
    return {
        "event": violation["event"],
        "num_markets": len(prices),
        "price_sum": total_cost,
        "deviation": violation["deviation"],
        "side": violation["side"],
        "entry_cost": entry_cost,
        "pnl": pnl,
        "results": results,
    }


def run_honest_backtest():
    """Run backtest on real partition violations."""
    print("=" * 60)
    print("HONEST BACKTEST - PARTITION ARBITRAGE")
    print("=" * 60)
    print("\nLooking for REAL mispricings in historical Kalshi data.")
    print("No synthetic data. No bias.\n")
    
    markets = fetch_all_settled_markets()
    
    if not markets:
        print("\nCannot proceed without market data.")
        return
    
    violations = find_partition_violations(markets)
    print(f"\nFound {len(violations)} partition violations (sum != 1)")
    
    if not violations:
        print("\nNo exploitable violations found in historical data.")
        print("This suggests the market is efficient or fees eliminate edge.")
        return
    
    trades = []
    initial_capital = 10000.0
    capital = initial_capital
    
    for v in violations[:30]:
        if capital < 100:
            break
        
        trade = simulate_partition_trade(v)
        
        position_size = min(capital * 0.10, 1000)
        scale = position_size / max(trade["entry_cost"], 0.01)
        
        scaled_pnl = trade["pnl"] * scale
        capital += scaled_pnl
        
        trade["scaled_pnl"] = scaled_pnl
        trade["capital_after"] = capital
        trades.append(trade)
    
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    
    if not trades:
        print("\nNo trades executed.")
        return
    
    pnls = [t["scaled_pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    
    total_return = (capital - initial_capital) / initial_capital
    win_rate = len(wins) / len(pnls) if pnls else 0
    
    print(f"\nCAPITAL")
    print(f"  Initial:      ${initial_capital:,.2f}")
    print(f"  Final:        ${capital:,.2f}")
    print(f"  Return:       {total_return:+.2%}")
    
    print(f"\nTRADES")
    print(f"  Total:        {len(trades)}")
    print(f"  Winners:      {len(wins)}")
    print(f"  Losers:       {len(losses)}")
    print(f"  Win Rate:     {win_rate:.1%}")
    
    if wins:
        print(f"  Avg Win:      ${np.mean(wins):,.2f}")
    if losses:
        print(f"  Avg Loss:     ${abs(np.mean(losses)):,.2f}")
    
    print(f"\nSAMPLE VIOLATIONS FOUND:")
    for t in trades[:5]:
        status = "WIN" if t["scaled_pnl"] > 0 else "LOSS"
        print(f"  {t['event'][:30]:30} | "
              f"sum={t['price_sum']:.2f} | "
              f"P&L=${t['scaled_pnl']:+.2f} [{status}]")
    
    print(f"\nHONEST CONCLUSION")
    print("-" * 40)
    
    if total_return > 0.05 and win_rate > 0.6:
        print("Strategy shows potential edge.")
        print("BUT: This is historical - execution would have been harder.")
        print("Real slippage and timing would reduce returns significantly.")
    elif total_return > 0:
        print("Marginal positive returns.")
        print("Edge is likely too small to survive real trading costs.")
    else:
        print("Strategy shows NEGATIVE returns.")
        print("Fees and spreads eliminate any theoretical edge.")
        print("Market is efficient for this type of arbitrage.")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    run_honest_backtest()
