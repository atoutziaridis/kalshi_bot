"""
Improved backtest with refined strategy.

Key improvements:
1. Only trade TRUE binary partitions (2 outcomes that sum to 1)
2. Look for YES/NO mispricing within single markets
3. Use mean reversion on extreme prices
4. Filter for liquid markets only
5. Tighter edge thresholds
"""

from __future__ import annotations

import httpx
import numpy as np


def fetch_markets() -> list[dict]:
    """Fetch markets from Kalshi."""
    print("Fetching markets...")
    client = httpx.Client(timeout=60.0)
    base_url = "https://api.elections.kalshi.com/trade-api/v2"
    
    all_markets = []
    cursor = None
    
    for _ in range(15):
        params = {"limit": 200, "status": "settled"}
        if cursor:
            params["cursor"] = cursor
        
        try:
            response = client.get(f"{base_url}/markets", params=params)
            response.raise_for_status()
            data = response.json()
            markets = data.get("markets", [])
            all_markets.extend(markets)
            cursor = data.get("cursor")
            if not cursor or not markets:
                break
        except Exception as e:
            print(f"  Error: {e}")
            break
    
    client.close()
    print(f"  Fetched {len(all_markets)} markets")
    return all_markets


def find_binary_events(markets: list[dict]) -> dict[str, list[dict]]:
    """Find events with exactly 2 markets (true binary)."""
    by_event = {}
    for m in markets:
        event = m.get("event_ticker", "")
        if event:
            if event not in by_event:
                by_event[event] = []
            by_event[event].append(m)
    
    binary = {k: v for k, v in by_event.items() if len(v) == 2}
    print(f"  Found {len(binary)} true binary events")
    return binary


def calculate_fee(price: float) -> float:
    """Kalshi fee."""
    if price <= 0 or price >= 1:
        return 0.0
    return max(0.01, np.ceil(0.07 * price * (1 - price) * 100) / 100)


def strategy_1_partition_arb(binary_events: dict) -> list[dict]:
    """
    Strategy 1: True partition arbitrage.
    If two mutually exclusive outcomes don't sum to 1, trade the gap.
    """
    signals = []
    
    for event, markets in binary_events.items():
        if len(markets) != 2:
            continue
        
        p1 = markets[0].get("last_price", 0) / 100
        p2 = markets[1].get("last_price", 0) / 100
        
        if p1 < 0.05 or p1 > 0.95 or p2 < 0.05 or p2 > 0.95:
            continue
        
        total = p1 + p2
        gap = abs(total - 1.0)
        
        fees = calculate_fee(p1) + calculate_fee(p2)
        spread = 0.02
        net_edge = gap - fees - spread
        
        if net_edge > 0.02:
            r1 = markets[0].get("result", "").lower() == "yes"
            r2 = markets[1].get("result", "").lower() == "yes"
            
            if total < 1.0:
                cost = p1 + p2 + fees + spread
                payout = 1.0
                pnl = payout - cost
            else:
                cost = (1 - p1) + (1 - p2) + fees + spread
                payout = 1.0
                pnl = payout - cost
            
            signals.append({
                "event": event,
                "strategy": "partition_arb",
                "p1": p1,
                "p2": p2,
                "sum": total,
                "gap": gap,
                "net_edge": net_edge,
                "pnl": pnl,
                "r1": r1,
                "r2": r2,
            })
    
    return signals


def strategy_2_mean_reversion(markets: list[dict]) -> list[dict]:
    """
    Strategy 2: Mean reversion on extreme prices.
    Bet against extreme prices (< 0.10 or > 0.90) that tend to revert.
    """
    signals = []
    
    for m in markets:
        price = m.get("last_price", 0) / 100
        result = m.get("result", "").lower() == "yes"
        volume = m.get("volume", 0)
        
        if volume < 100:
            continue
        
        if price < 0.08:
            cost = price + calculate_fee(price) + 0.01
            if result:
                pnl = 1.0 - cost
            else:
                pnl = -cost
            
            signals.append({
                "ticker": m.get("ticker"),
                "strategy": "mean_reversion_low",
                "price": price,
                "result": result,
                "pnl": pnl,
                "volume": volume,
            })
        
        elif price > 0.92:
            cost = (1 - price) + calculate_fee(1 - price) + 0.01
            if not result:
                pnl = 1.0 - cost
            else:
                pnl = -cost
            
            signals.append({
                "ticker": m.get("ticker"),
                "strategy": "mean_reversion_high",
                "price": price,
                "result": result,
                "pnl": pnl,
                "volume": volume,
            })
    
    return signals


def strategy_3_volume_weighted(markets: list[dict]) -> list[dict]:
    """
    Strategy 3: Fade low-volume extreme moves.
    Low volume + extreme price = likely overreaction.
    """
    signals = []
    
    volume_sorted = sorted(markets, key=lambda x: x.get("volume", 0))
    low_vol_markets = volume_sorted[:len(volume_sorted) // 4]
    
    for m in low_vol_markets:
        price = m.get("last_price", 0) / 100
        result = m.get("result", "").lower() == "yes"
        
        if 0.15 < price < 0.35:
            cost = price + calculate_fee(price) + 0.01
            if result:
                pnl = 1.0 - cost
            else:
                pnl = -cost
            
            signals.append({
                "ticker": m.get("ticker"),
                "strategy": "low_vol_underpriced",
                "price": price,
                "result": result,
                "pnl": pnl,
            })
        
        elif 0.65 < price < 0.85:
            cost = (1 - price) + calculate_fee(1 - price) + 0.01
            if not result:
                pnl = 1.0 - cost
            else:
                pnl = -cost
            
            signals.append({
                "ticker": m.get("ticker"),
                "strategy": "low_vol_overpriced",
                "price": price,
                "result": result,
                "pnl": pnl,
            })
    
    return signals


def run_improved_backtest():
    """Run backtest with multiple strategies."""
    print("=" * 60)
    print("IMPROVED BACKTEST - MULTIPLE STRATEGIES")
    print("=" * 60)
    
    markets = fetch_markets()
    if not markets:
        print("No data available")
        return
    
    binary_events = find_binary_events(markets)
    
    print("\nRunning strategies...")
    
    s1_signals = strategy_1_partition_arb(binary_events)
    print(f"  Strategy 1 (Partition Arb): {len(s1_signals)} signals")
    
    s2_signals = strategy_2_mean_reversion(markets)
    print(f"  Strategy 2 (Mean Reversion): {len(s2_signals)} signals")
    
    s3_signals = strategy_3_volume_weighted(markets)
    print(f"  Strategy 3 (Volume Fade): {len(s3_signals)} signals")
    
    all_strategies = [
        ("Partition Arb", s1_signals),
        ("Mean Reversion", s2_signals),
        ("Volume Fade", s3_signals),
    ]
    
    print("\n" + "=" * 60)
    print("RESULTS BY STRATEGY")
    print("=" * 60)
    
    best_strategy = None
    best_return = -999
    
    for name, signals in all_strategies:
        if not signals:
            print(f"\n{name}: No signals")
            continue
        
        pnls = [s["pnl"] for s in signals]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        
        initial = 10000
        capital = initial
        for s in signals[:50]:
            position = min(capital * 0.05, 500)
            scale = position / 0.5
            capital += s["pnl"] * scale
        
        total_return = (capital - initial) / initial
        win_rate = len(wins) / len(pnls) if pnls else 0
        
        print(f"\n{name}:")
        print(f"  Signals:    {len(signals)}")
        print(f"  Win Rate:   {win_rate:.1%}")
        print(f"  Return:     {total_return:+.2%}")
        print(f"  Final:      ${capital:,.2f}")
        
        if wins:
            print(f"  Avg Win:    ${np.mean(wins):.4f}")
        if losses:
            print(f"  Avg Loss:   ${abs(np.mean(losses)):.4f}")
        
        if total_return > best_return:
            best_return = total_return
            best_strategy = name
    
    print("\n" + "=" * 60)
    print("CONCLUSION")
    print("=" * 60)
    
    if best_return > 0.05:
        print(f"\nBest Strategy: {best_strategy}")
        print(f"Return: {best_return:+.2%}")
        print("\nThis shows potential. Consider:")
        print("  - Paper trading to validate")
        print("  - Tighter position sizing")
        print("  - Real-time execution testing")
    elif best_return > 0:
        print(f"\nBest Strategy: {best_strategy}")
        print(f"Return: {best_return:+.2%}")
        print("\nMarginal edge. Needs refinement.")
    else:
        print("\nNo profitable strategy found.")
        print("Market appears efficient for these approaches.")
        print("\nConsider:")
        print("  - Information-based edge (news, research)")
        print("  - Market making (provide liquidity)")
        print("  - Event-specific expertise")


if __name__ == "__main__":
    run_improved_backtest()
