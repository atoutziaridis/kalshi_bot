# Examples Directory

This directory contains all backtesting scripts and analysis tools for the Kalshi Momentum Strategy.

## 🎯 Main Scripts (Run These)

### 1. `optimal_range_finder.py` ⭐ **RECOMMENDED**
**The final, comprehensive backtest that found the optimal strategy.**

- Tests 13 different price range configurations
- Uses 30,000 settled markets
- Validates with both chronological and random splits (20 iterations)
- Reports optimal YES (65-78%) and NO (22-30%) ranges

**Run:**
```bash
python examples/optimal_range_finder.py
```

**Output:**
- Best NO range: 22-30% (+10.94% avg return, 82% win rate)
- Best YES range: 65-78% (+8.66% avg return, 82.5% win rate)
- Combined strategy: +10.99% avg return, 81.8% win rate

---

### 2. `regime_analysis.py`
**Analyzes when and where the strategy works best.**

- Breaks down performance by time period
- Analyzes by volume buckets (low/med/high)
- Tests specific price ranges (22-28%, 28-34%, etc.)

**Run:**
```bash
python examples/regime_analysis.py
```

**Key Findings:**
- NO 22-28%: 81.3% win rate (best performance)
- High volume markets (75-100%): 77.1% win rate
- Period 4 showed regime change (59% win rate)

---

### 3. `corrected_momentum_backtest.py`
**Comprehensive validation with multiple strategies.**

- Tests 5 strategy variations
- Uses proper chronological and random splits
- Validates on 30,000 markets

**Run:**
```bash
python examples/corrected_momentum_backtest.py
```

---

### 4. `authenticated_signals.py`
**Generate live trading signals using your Kalshi API.**

Requires API authentication (set up `.env` file first).

**Run:**
```bash
python examples/authenticated_signals.py
```

**Output:**
- Top 10 BUY YES signals (65-78% price range)
- Top 10 BUY NO signals (22-30% price range)
- Sorted by volume for best liquidity

---

## 📊 Historical/Research Scripts

### `unbiased_final_test.py`
Initial unbiased backtest that revealed the strategy's potential.
- First test showing +44.69% chronological return
- Led to deeper investigation

### `final_momentum_strategy.py`
Early comprehensive test (before optimization).
- Tested 8 strategy variations
- Found all strategies failed in test period
- Led to corrected methodology

### `momentum_final.py`
3-way split validation (train/validate/test).
- Tested fine-tuned parameters
- Identified "Asymm 65-78/22-40 v50" as promising

### `momentum_deep_test.py`
Deep parameter search with 18 configurations.
- Used 60/40 train/test split
- Found "Balanced 62-78/22-38, v50" candidate

---

## 🔍 How to Use These Scripts

### For Research/Validation:
1. Start with `optimal_range_finder.py` to see final results
2. Run `regime_analysis.py` to understand when strategy works
3. Review `corrected_momentum_backtest.py` for methodology validation

### For Live Trading:
1. Set up `.env` with your Kalshi API credentials
2. Run `authenticated_signals.py` to get current signals
3. Paper trade the signals for 4+ weeks before live deployment

---

## 📈 Evolution of Testing

The scripts evolved as we discovered issues and refined methodology:

1. **Initial Tests** (`unbiased_final_test.py`)
   - Found promising +44% return
   - Small sample size, needed validation

2. **Comprehensive Search** (`final_momentum_strategy.py`)
   - Tested 8 variations, all failed
   - Revealed methodology issues

3. **Corrected Methodology** (`corrected_momentum_backtest.py`)
   - Fixed data issues (using last_price not bid/ask)
   - Proper chronological ordering
   - Found +16.79% avg return

4. **Regime Analysis** (`regime_analysis.py`)
   - Discovered NO 22-28% has 81% win rate
   - Found NO 34-40% loses money
   - Identified volume and time dependencies

5. **Final Optimization** (`optimal_range_finder.py`)
   - Tested narrow ranges based on regime findings
   - Found optimal: YES 65-78%, NO 22-30%
   - Validated with 20 random splits: +10.99% avg

---

## ⚠️ Important Notes

- All scripts use **settled markets** (historical data)
- Fees included: 0.07 × p × (1-p), minimum 1¢
- Spread cost: 1¢ per trade
- Position sizing: 2% of capital, max $200
- Scripts require `httpx`, `numpy`, `scipy` packages

---

## 🚀 Quick Reference

| Script | Purpose | Runtime |
|--------|---------|---------|
| `optimal_range_finder.py` | Find best parameters | ~5 min |
| `regime_analysis.py` | Analyze performance patterns | ~3 min |
| `corrected_momentum_backtest.py` | Validate methodology | ~4 min |
| `authenticated_signals.py` | Get live signals | ~30 sec |

All scripts fetch 30,000 markets by default. Adjust `max_markets` parameter to change sample size.
