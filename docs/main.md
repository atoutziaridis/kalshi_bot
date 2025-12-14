Core Idea (One Sentence)

Use logical arbitrage constraints to define no-loss probability bounds, then take directional positions only when market prices violate those bounds by a margin larger than fees and execution risk.

You are not predicting outcomes.
You are trading incoherence.

System Architecture (Minimal but Complete)
Kalshi Markets
   ↓
Logical Constraint Engine
   ↓
Probability Bounds (Hard)
   ↓
Directional Signal Generator
   ↓
Position Sizer (Fractional Kelly + Bounds)
   ↓
Execution (YES / NO)

Step 1: Define Constraint Types (Start with 3 Only)

Implement only these initially.

1. Subset Constraint (Highest Alpha)

If event A ⊂ event B, then:

𝑝
(
𝐴
)
≤
𝑝
(
𝐵
)
p(A)≤p(B)

Examples:

Trump wins ⊂ GOP wins

BTC > 250k by Jan 15 ⊂ BTC > 250k by Feb 1

Bound:

𝑝
(
𝐵
)
≥
𝑝
(
𝐴
)
p(B)≥p(A)
2. Partition Constraint (Exhaustive Outcomes)

For mutually exclusive outcomes:

∑
𝑖
𝑝
𝑖
=
1
i
∑
	​

p
i
	​

=1

Deviation defines implicit bounds on each outcome:

𝑝
𝑖
≤
1
−
∑
𝑗
≠
𝑖
𝑝
𝑗
p
i
	​

≤1−
j

=i
∑
	​

p
j
	​

3. Temporal Nesting (Calendar)

Earlier event is subset of later:

𝑝
(
𝑇
1
)
≤
𝑝
(
𝑇
2
)
p(T
1
	​

)≤p(T
2
	​

)

Same as subset, but auto-derivable from expiration metadata.

Step 2: Constraint Engine (Deterministic)

No LLMs yet.

class Constraint:
    type: Literal["subset", "partition"]
    lhs: list[str]   # tickers
    rhs: list[str]   # tickers


Output hard bounds:

class ProbabilityBound:
    ticker: str
    lower: float
    upper: float
    source: str  # constraint id


Example:

Trump wins (A) ⊂ GOP wins (B)

→ bound(B).lower = price(A)
→ bound(A).upper = price(B)

Step 3: Directional Signal Logic

For each market:

edge_up   = bound.lower - market_price
edge_down = market_price - bound.upper


Trade only if:

max(edge_up, edge_down) > fee + spread + safety_margin


Direction:

If edge_up > threshold → BUY YES

If edge_down > threshold → BUY NO

This is directional, not arb.

Step 4: Position Sizing (Critical)

Use arb-bounded Kelly, not full Kelly.

effective_edge = edge - costs
f = min(
    0.25 * effective_edge / (1 - market_price),
    max_position_per_market
)


Rules:

Never exceed 5–10% of account per constraint cluster

If multiple constraints point same direction → additive confidence, not leverage

Step 5: Execution Rules

Always use limit orders

Cross spread only if edge > 2× spread

Revalidate bounds right before execution

Do not hold through final hour unless edge > 3%

Example (Concrete)

Markets:

Trump wins: 0.42

GOP wins: 0.38

Constraint:

Trump ⊂ GOP
→ p(GOP) ≥ 0.42


Observed:

Market p(GOP) = 0.38
Violation = 0.04
Fees+spread ≈ 0.015
Net edge ≈ 0.025


Action:

BUY YES on GOP

Size via fractional Kelly

Hold until convergence or resolution

This is not arbitrage, but it is logically one-sided.

Why This Has Real Alpha

Bounds are absolute, not statistical

Market cannot resolve without respecting them

Fees do not eliminate large logical gaps

Competition focuses on pure arb, not “almost arb”

Scales with confidence, not liquidity gaps