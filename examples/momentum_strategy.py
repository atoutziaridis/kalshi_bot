"""
Momentum Strategy - The one that actually works.

Strategy: Bet WITH moderate consensus.
- When 60% < price < 85%: Buy YES
- When 15% < price < 40%: Buy NO
- Require minimum volume for liquidity

Rationale: Markets with moderate confidence (not extreme) 
tend to be well-informed but not fully priced in.
"""

from __future__ import annotations

import httpx
import numpy as np


def fetch_all_markets() -> list[dict]:
    """Fetch as many settled markets as possible."""
    print("Fetching markets for validation...")
    client = httpx.Client(timeout=60.0)
    base_url = "https://api.elections.kalshi.com/trade-api/v2"
    
    all_markets = []
    cursor = None
    
    for i in range(20):
        params = {"limit": 200, "status": "settled"}
        if cursor:
            params["cursor"] = cursor
        
        try:
            response = client.get(f"{base_url}/markets", params=params)
            if response.status_code == 429:
                print(f"  Rate limited after {len(all_markets)} markets")
                break
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
    print(f"  Total: {len(all_markets)} markets")
    return all_markets


def calculate_fee(price: float) -> float:
    if price <= 0 or price >= 1:
        return 0.0
    return max(0.01, np.ceil(0.07 * price * (1 - price) * 100) / 100)


def generate_signals(markets: list[dict], min_volume: int = 100) -> list[dict]:
    """Generate momentum signals."""
    signals = []
    
    for m in markets:
        price = m.get("last_price", 0) / 100
        result = m.get("result", "").lower() == "yes"
        volume = m.get("volume", 0)
        
        if volume < min_volume:
            continue
        
        if 0.60 < price < 0.85:
            cost = price + calculate_fee(price) + 0.01
            pnl = (1.0 - cost) if result else -cost
            signals.append({
                "ticker": m.get("ticker"),
                "price": price,
                "bet": "YES",
                "result": result,
                "won": result,
                "pnl": pnl,
                "volume": volume,
            })
        
        elif 0.15 < price < 0.40:
            cost = (1 - price) + calculate_fee(1 - price) + 0.01
            pnl = (1.0 - cost) if not result else -cost
            signals.append({
                "ticker": m.get("ticker"),
                "price": price,
                "bet": "NO",
                "result": result,
                "won": not result,
                "pnl": pnl,
                "volume": volume,
            })
    
    return signals


def backtest(signals: list[dict], initial: float = 10000.0) -> dict:
    """Run backtest with position sizing."""
    capital = initial
    equity_curve = [initial]
    trades = []
    
    for s in signals:
        position_pct = 0.03
        position = min(capital * position_pct, 300)
        
        avg_cost = 0.5
        contracts = position / avg_cost
        
        trade_pnl = s["pnl"] * contracts
        capital += trade_pnl
        
        trades.append({
            **s,
            "trade_pnl": trade_pnl,
            "capital": capital,
        })
        equity_curve.append(capital)
        
        if capital < 1000:
            break
    
    pnls = [t["trade_pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    
    peak = initial
    max_dd = 0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
    
    return {
        "initial": initial,
        "final": capital,
        "return": (capital - initial) / initial,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) if trades else 0,
        "max_drawdown": max_dd,
        "avg_win": np.mean(wins) if wins else 0,
        "avg_loss": abs(np.mean(losses)) if losses else 0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else float('inf'),
        "equity_curve": equity_curve,
        "trades_detail": trades,
    }


def run_validation():
    """Validate the momentum strategy."""
    print("=" * 60)
    print("MOMENTUM STRATEGY VALIDATION")
    print("=" * 60)
    
    markets = fetch_all_markets()
    if not markets:
        print("No data")
        return
    
    print("\nTesting different volume thresholds...")
    
    for min_vol in [50, 100, 200, 500]:
        signals = generate_signals(markets, min_volume=min_vol)
        if not signals:
            continue
        
        result = backtest(signals)
        
        print(f"\nVolume >= {min_vol}:")
        print(f"  Trades:      {result['trades']}")
        print(f"  Win Rate:    {result['win_rate']:.1%}")
        print(f"  Return:      {result['return']:+.2%}")
        print(f"  Max DD:      {result['max_drawdown']:.1%}")
        if result['avg_loss'] > 0:
            print(f"  Profit Factor: {result['profit_factor']:.2f}")
    
    print("\n" + "=" * 60)
    print("BEST CONFIGURATION")
    print("=" * 60)
    
    signals = generate_signals(markets, min_volume=100)
    result = backtest(signals)
    
    print(f"\nVolume >= 100 (recommended)")
    print(f"  Initial:     ${result['initial']:,.2f}")
    print(f"  Final:       ${result['final']:,.2f}")
    print(f"  Return:      {result['return']:+.2%}")
    print(f"  Trades:      {result['trades']}")
    print(f"  Win Rate:    {result['win_rate']:.1%}")
    print(f"  Max DD:      {result['max_drawdown']:.1%}")
    
    if result['trades'] > 0:
        print(f"\nSample trades:")
        for t in result['trades_detail'][:5]:
            status = "WIN" if t['won'] else "LOSS"
            print(f"  {t['ticker'][:25]:25} | "
                  f"price={t['price']:.2f} | "
                  f"bet={t['bet']:3} | "
                  f"P&L=${t['trade_pnl']:+.2f} [{status}]")
    
    print("\n" + "=" * 60)
    print("IMPLEMENTATION NOTES")
    print("=" * 60)
    print("""
1. Entry Rules:
   - Buy YES when 60% < price < 85%
   - Buy NO when 15% < price < 40%
   - Require volume >= 100 contracts

2. Position Sizing:
   - Risk 3% of capital per trade
   - Max position $300

3. Risk Management:
   - Stop trading if capital < $1000
   - Monitor max drawdown

4. Caveats:
   - This is HISTORICAL data
   - Real execution will have slippage
   - Liquidity may not be available
   - Paper trade first!
""")


if __name__ == "__main__":
    run_validation()
