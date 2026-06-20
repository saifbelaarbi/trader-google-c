# Research — Better Returns for `ClaudeBreakout` (faster, more gain, smarter)

**Status:** Research / analysis only. Nothing here is a recommendation to touch the
**live paper bot** during the Phase-3 window (started 2026-06-12, gate ≥4 weeks /
≥30 trades). Every behavioural change below is a **backtest task on the PC first**,
walk-forward validated, and deployed only *after* the paper window closes.
This cloud session cannot reach Bybit or run freqtrade — these are PC jobs.

**Subject:** `ftbot/strategies/ClaudeBreakout.py` (V4 turtle-style Donchian breakout).

---

## 0. TL;DR — the ranked levers

| # | Change | Primary lever | Overfit risk | Phase |
|---|--------|---------------|--------------|-------|
| 1 | **Risk-based unit sizing** (size ∝ 1/ATR) | Return **and** DD | Low | Backtest now → deploy after window |
| 2 | **Pyramiding** (add units in favour, stop trails up) | Return (fat tail) | Low-Med | Backtest now → deploy after |
| 3 | **Funding + slippage in the backtest** | *Realism* (decides if edge is real) | None | **Do first** |
| 4 | **Correlation-aware exposure cap** | Drawdown / Sharpe | Low | Backtest now |
| 5 | **Breadth → 15–20 pairs or dynamic VolumePairList** | Return | Low-Med | Backtest now |
| 6 | **Chandelier exit** vs fixed Donchian exit | Avg winner size | Low | Backtest A/B now |
| 7 | **Walk-forward hyperopt toward the slow gradient** | Return + DD | **High** | After window |
| 8 | **Longer history** (2021 bull, 2022 bear) | Confidence | None | Now |
| 9 | **Modest leverage 1.25–1.5×** | Return (+DD 1:1) | High | Only after #1 lowers base DD |

**One-line conclusion:** the current code is only the *entry/exit skeleton* of a
Turtle system. The two changes that turn it into the real thing — **risk-based
sizing (#1)** and **pyramiding (#2)** — are where "more gain, faster" actually
lives. But **#3 comes first**, because it decides whether the backtested +40.9% /
PF 1.15 survives funding and slippage at all.

---

## 1. Baseline — where the money currently comes from

`ClaudeBreakout` (4h candles, `can_short=True`, 9 USDT-perp pairs, 4 slots):

- **Entry** (`populate_entry_trend`, L171): close breaks prior 20-bar high (long) /
  low (short), *and* on the correct side of EMA200, *and* volume > 0.
- **Exit** (`populate_exit_trend`, L188): close crosses the opposite **10-bar**
  Donchian extreme. No fixed target, no trail — the channel *is* the trail.
- **Stop** (`custom_stoploss`, L226): fixed **2×ATR(14)** from open, via
  `stoploss_from_open`. Hard failsafe `stoploss = -0.20`.
- **Sizing** (`custom_stake_amount`, L194): `min($40, 20% × equity)` — a flat
  *notional* stake. `leverage()` (L213) hard-returns **1.0**.
- **Protections** (L140): Cooldown 1 candle, StoplossGuard (4 stops / 84 candles →
  12-candle halt), MaxDrawdown (15% over 180 candles → 42-candle halt).

Backtest 2024-06-01 → 2026-06-12, $200, 0.06% fee, market ≈ −28% to −41%:
**+40.9%, PF 1.15, win 30.8%, max DD 25.9%, ~0.8 trades/day.**

Two load-bearing facts from `OVERHAUL_PLAN.md`:

1. **Breadth is the edge.** 3 pairs → +0.2% (breakeven). Same rules, 9 pairs →
   +40.9%. The P&L is a few multi-day winners; more independent shots = more tail.
2. **The slow gradient dominates.** Slow 30/15 → PF **1.31**, DD **22.7%**.
   EMA250 → PF **1.25**, DD **20.3%**. Both beat default on return *and* DD.
   (Default was pre-registered to avoid selection bias — see §7 for how to adopt
   the gradient *honestly* rather than just grabbing the prettiest number.)

### 1a. The expectancy arithmetic (why win rate is a red herring)

With win rate `W ≈ 0.31`, the system is only profitable because the average
winner dwarfs the average loser. Expectancy per trade:

```
E = W × avg_win − (1 − W) × avg_loss
PF = (W × avg_win) / ((1 − W) × avg_loss)
```

PF 1.15 at W=0.31 implies `avg_win / avg_loss ≈ 2.56` (payoff ratio). Every lever
below is really an attack on one of three numbers:

- **#2 pyramiding, #6 chandelier** → raise `avg_win` (fatten the right tail).
- **#1 sizing, #4 correlation cap** → stabilise `avg_loss` in dollar terms and cut
  the variance of the equity curve (lets you carry more total size safely).
- **#3 funding/slippage** → make sure `avg_win`/`avg_loss` are *honest* before you
  bet real money on them.

Note: a low-win-rate system has a **deep losing-streak distribution**. At W=0.31 the
probability of ≥10 losers in a row is far from negligible; the log already warns
streaks past 20 are within norms. That is exactly why sizing (§2) and the
StoplossGuard/MaxDrawdown protections matter — *surviving the streak is the
precondition for collecting on the tail.*

---

## 2. Lever #1 — Risk-based ("unit") position sizing  ★ highest impact

### The bug-shaped inefficiency

`custom_stake_amount` (L194) hands every trade the **same notional** stake
(`min($40, 20%×equity)`). But the stop is **2×ATR**, and ATR% differs a lot across
the 9 pairs. So **dollar risk per trade is effectively random**: a high-vol pair
(SOL/AVAX/DOGE) on its 2×ATR stop loses several times more dollars than BTC for the
identical stake. The volatile pairs silently dominate the drawdown, and the
"diversification" across 9 names is weaker than the slot count suggests.

### The Turtle fix

Size so **every trade risks the same fraction of equity at its stop**:

```
risk_dollars = equity × risk_fraction          # e.g. 0.5%–1.0%
stop_distance_frac = 2 × atr_pct               # the actual 2×ATR stop
stake_notional = risk_dollars / stop_distance_frac
stake = min(stake_notional, max_stake_cap, max_stake)
```

`atr_pct` is already computed (`dataframe["atr_pct"]`, L163) and already read in
`custom_stoploss` via `_last_candle_value`, so the plumbing exists. Sketch:

```python
def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake,
                        min_stake, max_stake, leverage, entry_tag, side, **kwargs):
    equity = self.wallets.get_total_stake_amount() if self.wallets else 200.0
    atr_pct = max(self._last_candle_value(pair, "atr_pct") or 0.02, 0.005)
    risk_dollars = equity * self.risk_fraction          # new param, e.g. 0.0075
    stake = risk_dollars / (2 * atr_pct)                # invert the stop distance
    stake = min(stake, equity * self.wallet_fraction)   # keep a notional ceiling
    if min_stake:
        stake = max(stake, min_stake)
    return min(stake, max_stake)
```

### Why it's the top lever

- Equalises $-risk → **volatile pairs stop owning the drawdown** → DD falls.
- A smoother equity curve has **higher risk-adjusted return**, which *justifies a
  higher overall `risk_fraction`* — i.e. you can safely run more total size than the
  flat-notional version, so raw return rises too.
- It's the precondition for #2 (pyramiding) and #9 (leverage) — neither is safe on
  top of random per-trade risk.

### Calibration / risk-of-ruin

`risk_fraction` is the master dial. Rough guide for a W≈0.31, payoff≈2.5 system:

- 0.5% → very conservative, DD likely < 20%, slower growth.
- 1.0% → aggressive for this win rate given 4 correlated slots (effective risk per
  *cluster* is ~4× the per-trade figure — see §4).
- **Full-Kelly is far too hot here** (low win rate ⇒ Kelly fraction is small and the
  variance is brutal). Use **¼–½ Kelly at most**; in practice pick `risk_fraction`
  by backtesting the DD you can actually stomach, not by a Kelly formula.

**Backtest task:** sweep `risk_fraction ∈ {0.4, 0.6, 0.8, 1.0}%`, report
CAGR / MaxDD / Calmar / PF for each. Pick on Calmar (return per unit DD), not return.

---

## 3. Lever #2 — Pyramiding (add to winners)  ★ the fat-tail engine

A breakout book lives on a handful of trades that run for weeks. Today you take
**one unit and ride**. The original Turtle system **adds a unit every 0.5×ATR in
favour**, up to ~4 units, ratcheting the stop up with each add so the aggregate
position is never risking more than ~1–2 units of equity.

Freqtrade supports this natively:

```jsonc
// config: enable position adjustment
"position_adjustment_enable": true,
"max_entry_position_adjustment": 3   // up to 3 adds → 4 units total
```

```python
def adjust_trade_position(self, trade, current_time, current_rate, current_profit,
                          min_stake, max_stake, current_entry_rate,
                          current_exit_rate, current_entry_profit,
                          current_exit_profit, **kwargs):
    atr_pct = max(self._last_candle_value(trade.pair, "atr_pct") or 0.02, 0.005)
    # count adds so far via trade.nr_of_successful_entries
    adds = trade.nr_of_successful_entries - 1
    if adds >= self.max_units - 1:
        return None
    # last fill price; add when price has moved +0.5×ATR in favour
    move = (current_rate / trade.open_rate - 1) * (−1 if trade.is_short else 1)
    if move >= (adds + 1) * 0.5 * atr_pct:
        return self._unit_stake(trade.pair)   # same risk-based unit as §2
    return None
```

### Why it's clean

- **Only winners get scaled.** Losers never add — they hit the stop at 1 unit.
  This is the structurally honest way to "gain faster": more capital onto trades the
  market is already validating.
- Expected effect: win rate dips slightly, **avg winner rises a lot**, PF rises in
  trending years (2024H2, late-2025) and is ~flat in chop.
- Pair it with a **trailing stop on the aggregate** (chandelier, §6) so the
  multi-unit position can't round-trip a big open profit.

### Caveat

Adds increase exposure exactly when correlated pairs are *also* breaking out → the
book can become very directional fast. Pyramiding **must** be combined with the
correlation cap (§4) or DD will spike. Backtest the two together, not separately.

---

## 4. Lever #4 — Correlation-aware exposure  ★ the "smarter" core

### The hidden truth in the DD number

All 9 pairs are **BTC-beta**. BTC/ETH/SOL/BNB/XRP/DOGE/ADA/LINK/AVAX co-move,
especially in the breakouts this system trades (everything breaks out together in a
regime shift). So **4 simultaneous longs ≈ one ~4× leveraged BTC bet.** That is the
real reason DD reaches 26% on a "diversified" 9-pair book — the diversification is
partly an illusion, and the slot count *understates* true risk.

### Two coherent responses (pick by temperament, but pick *one*)

**(a) Risk-down — smoother curve, higher Sharpe:**
scale each new entry down by how many same-direction positions are already open, or
cap *net directional units*:

```python
# in custom_stake_amount, before returning:
open_same_dir = sum(1 for t in Trade.get_open_trades() if t.is_short == is_short)
crowding_factor = 1.0 / (1 + 0.5 * open_same_dir)   # 1.0, 0.67, 0.5, 0.4...
stake *= crowding_factor
```

**(b) Risk-up — lean into the regime:**
when *everything* breaks out at once, that synchronization *is* the signal; accept
the concentrated bet for higher return and higher DD.

Either is defensible. What's not defensible is the **current state: unmanaged.**
Right now the book silently takes (b) without having chosen it. Measuring realized
rolling correlation across the 9 pairs and sizing against it is the single most
*intelligent* upgrade available, and it directly attacks the 26% DD that sits right
against the go-live gate (≤~26%).

**Backtest task:** compute the trade-level correlation of simultaneous positions in
the 2024–26 run; then A/B the crowding factor. Expect lower DD at a small return
cost — and a *much* better Calmar, which is what unlocks #9.

---

## 5. Lever #5 — Breadth and slot count

Breadth made this strategy (3→9 pairs, §1). Two extensions:

- **More pairs (15–20 liquid Bybit perps).** More independent shots at the tail.
  But see §4 — adding more BTC-beta names adds *shots*, not much *independence*.
  Prioritise names with the **lowest correlation to the existing basket** (historically
  some L1/alt names decouple in their own narratives) over simply "more majors".
- **Dynamic universe (`VolumePairList`).** Replace the static 9 with a top-N-by-quote-
  volume list so the universe self-refreshes and you're always trading what's liquid
  and active, not a hand-picked 2026 snapshot. Reduces a subtle survivorship/selection
  bias baked into the static list. (Backtest with `--pairs` from a historical volume
  ranking to avoid look-ahead.)
- **Slot count.** `max_open_trades: 4` on 9 pairs means in a synchronized rally you
  fill 4 and **miss the rest of the move**. Raising slots captures more trend — but
  every extra slot is more correlated exposure (§4). The right move is to raise slots
  *and* turn on the crowding factor together, so breadth is captured without the DD
  blowing out. Backtest `max_open_trades ∈ {4, 6, 8}` × crowding on/off as a grid.

---

## 6. Lever #6 — Exit upgrade: chandelier vs fixed Donchian

The 10-bar Donchian exit (L188) gives back a fixed slice of every winner before it
triggers. A **chandelier exit** trails from the highest-high-since-entry (long) minus
`N×ATR`:

```python
# indicator: rolling max of high since entry is per-trade, so compute in custom_exit
# or approximate with a chandelier line in populate_indicators using a long window.
chandelier_long  = highest_high_since_entry - n_atr * atr
chandelier_short = lowest_low_since_entry  + n_atr * atr
```

Typically holds strong trends **longer** (line rises with price) and exits **faster**
when momentum dies, lifting the average winner — the exact term PF is most sensitive
to at low win rate. Implement via `custom_exit` so it's per-trade from the real entry.

**Backtest A/B:** Donchian-10 (incumbent) vs chandelier `N ∈ {2.5, 3, 3.5}`. Low
overfit risk — it's a structural swap, not a tuned entry filter. Judge on avg-winner
and PF, and confirm it doesn't wreck the 2022-style chop (run §8 history).

---

## 7. Lever #7 — Walk-forward hyperopt toward the slow gradient (carefully)

The slow gradient is *known* better in-sample (30/15 PF 1.31; EMA250 PF 1.25, DD
20.3%). The temptation is to just adopt it. **Don't** — that re-introduces the exact
selection bias the pre-registration avoided. The honest path:

1. **Parameterise** `entry_window`, `exit_window`, `trend_ema`, ATR stop multiple,
   and `risk_fraction` as freqtrade hyperopt `IntParameter`/`DecimalParameter`s.
2. **Walk-forward**: optimise on 2024, validate untouched on 2025+; or rolling
   train/test windows. Report the *validation* PF, never the in-sample PF.
3. **Accept a region, not a point.** The robustness table already shows the whole
   neighbourhood is positive — so target a *parameter region* (e.g. "slow-ish, deep
   EMA") and pick a central value, not the single best cell. A real edge is a plateau;
   a spike is noise.
4. **Gate:** only adopt if validation PF ≥ 1.3 *after funding+slippage* (§3) and DD
   ≤ the current live gate. Otherwise keep default.

Hyperopt loss: prefer `CalmarHyperOptLoss` or `SortinoHyperOptLoss` over raw profit —
you want return-per-drawdown, given the gate is a DD gate.

---

## 8. Lever #8 — Longer history & regime coverage (free confidence)

The campaign backtests start **2024-06**. That window is mostly one macro regime.
A trend-breakout system's character is defined by how it behaves across *all* of:

- **2021 H1** parabolic bull (does the slow exit give back too much at blow-off tops?)
- **2022** grinding bear (does the short side actually carry, or just churn fees?)
- **2023** low-vol chop (the system's worst enemy — quantify the bleed)
- **2024–25** the current sample.

**Backtest task:** `download-data` back to 2021 for the pairs that existed, re-run the
full grid. If PF stays > 1 across regimes, the edge is structural and you can size up
with confidence; if it only works 2024–26, treat the headline as regime-lucky and keep
sizing conservative. This costs only compute and is the cheapest confidence you can buy.

Add two analyses on top of the long backtest:
- **Monte Carlo trade-order shuffle** (freqtrade `--timeframe-detail` + external
  resample, or shuffle the trade-return series): gives a *distribution* of max-DD and
  final equity instead of one path. The single 25.9% DD is one sample; the 95th-pct DD
  is what you should actually budget for. This usually reveals DD can be noticeably
  worse than the realised path — critical for setting `risk_fraction` and the gate.
- **Per-pair and per-month attribution** (`--breakdown month`, already in the
  SETUP commands): confirm the edge isn't one pair / one quarter. If 80% of profit is
  one 2024 SOL run, the "edge" is fragile.

---

## 9. Realism gaps — DO THIS FIRST (§3 in priority terms)

`OVERHAUL_PLAN.md` says it plainly: *dry-run always flatters.* Two costs are likely
missing/understated, and both attack the *gross* PF 1.15 directly:

### Funding (futures, isolated, multi-day holds)
You pay/receive funding every 8h. Week-long winners on perps accrue real funding
drag that a naive spot-style backtest ignores. At, say, 0.01%/8h that's ~0.09%/day —
on a 6-day winner, ~0.5% off the trade, which is material when PF is 1.15.
- Enable funding in the backtest if not already (`trading_mode: futures` should pull
  funding rate data — verify the `funding_rate` data is downloaded and applied).
- **Smarter:** bias entries toward the side funding *pays you*, or at minimum log
  cumulative funding per trade so you can see the drag in analysis.

### Slippage on breakout fills
You enter *into* momentum with `order_book_top: 1`. Breakout fills slip worse than
random fills (you're crossing a moving book). A flat backtest fill at the close
overstates entries.
- Re-run with a slippage assumption (e.g. 0.05–0.10% adverse on entry) and/or model
  it. A gross-PF-1.15 strategy can become net-PF-1.0 if entries are optimistic.

**Why first:** these don't add features — they tell you whether the +40.9% is *real*.
Everything in §2–§7 is wasted effort if the honest net PF is ≤ 1.0. Spend the first
PC session here.

---

## 10. Lever #9 — Leverage (the literal "faster", handled honestly)

`leverage()` returns 1.0 (L213). Futures allows more. With **risk-based sizing (§2)**,
leverage scales return **and DD ~1:1** — 2× turns ~26% DD into ~50%, blowing the
go-live gate (DD ≤ ~26%). So:

- **Not now, not a free lunch.** It's last on the list for a reason.
- Sequence: first land §2 (which *lowers* base DD) + §4 (lowers it more). *Then*, if
  the de-risked book sits at, say, 15% DD, a **1.25–1.5×** leverage brings it back
  toward the gate while lifting return — a deliberate trade, measured, post-validation.
- Never raise leverage and `risk_fraction` at the same time; they multiply.

---

## 11. What NOT to do (degrees of freedom that will burn you)

- **Don't switch the live bot to slow params mid-window.** Invalidates Phase 3 and
  re-introduces selection bias. Slow gradient is a *post-window hyperopt direction*.
- **Don't bolt on discretionary entry filters** ("skip if extended above EMA200",
  volume-spike gates, RSI confirmation) without walk-forward proof. Each tuned filter
  is a degree of freedom that inflates the backtest and disappoints live. V1's autopsy
  (PF 0.40, "inverted confluence") is the cautionary tale — more signals made it worse.
- **Don't shorten the timeframe.** 15m failed twice on fee math (V1 −96.8%, V2 −76.7%).
  4h is the fee/noise sweet spot. "Faster" comes from sizing/pyramiding, not candles.
- **Don't optimise on the 2024–26 window alone.** See §7/§8.
- **Don't touch `ClaudeBreakout` parameters or logic during paper trading** without
  explicit sign-off (CLAUDE.md hard rule). All of the above is backtest-branch work.

---

## 12. Concrete PC test plan (ordered)

All commands run on the user's PC (this cloud env can't reach the exchange). Use a
**separate strategy class / branch** so the live `ClaudeBreakout` is never touched.

```powershell
# 0. Longer history first (free confidence + realism baseline)
freqtrade download-data --userdir ftbot --config ftbot/config.dry.json `
  --timeframes 4h --timerange 20210101-

# 1. REALISM (do first): re-run baseline WITH funding + a slippage assumption.
#    Confirm net PF before building anything. (Add slippage via config/feemodel.)
freqtrade backtesting --userdir ftbot --config ftbot/config.dry.json `
  --strategy ClaudeBreakout --timerange 20210101- --breakdown month

# 2. Risk-based sizing sweep (new ClaudeBreakoutRisk subclass; param risk_fraction)
#    Judge on Calmar (return/DD), not raw return.

# 3. Pyramiding (position_adjustment_enable) + chandelier exit, A/B vs baseline.

# 4. Correlation cap: measure simultaneous-position correlation, A/B crowding factor.

# 5. Breadth/slots grid: pairs {9,15} × max_open_trades {4,6,8} × crowding {on,off}.

# 6. Walk-forward hyperopt toward the slow region (validate on held-out 2025+):
freqtrade hyperopt --userdir ftbot --config ftbot/config.dry.json `
  --hyperopt-loss CalmarHyperOptLoss --strategy ClaudeBreakoutHO `
  --timerange 20210101-20241231 --epochs 300 --spaces buy sell stoploss
#  then validate the chosen params untouched on 20250101- .

# 7. Monte Carlo / trade-shuffle on the winning config → budget the 95th-pct DD.
```

**Decision rule for each step:** keep a change only if it improves **Calmar on the
validation period after funding+slippage** without breaking the DD gate. Adopt regions,
not points. One change per backtest so attribution is clean.

### Implementation map (backtest-only code)

The levers above are implemented as **backtest-only** code so they can be measured
without touching the live `ClaudeBreakout` paper bot:

- `ftbot/strategies/research_sizing.py` — pure, dependency-free math
  (`risk_based_stake`, `pyramid_should_add`, `crowding_factor`, `chandelier_stop`),
  unit-tested in CI (`tests/test_research_sizing.py`) without freqtrade/TA-Lib.
- `ftbot/strategies/breakout_research.py` — `ClaudeBreakout` subclasses wiring those
  helpers into freqtrade callbacks:
  `ClaudeBreakoutRisk` (sizing), `ClaudeBreakoutCorr` (+crowding),
  `ClaudeBreakoutPyramid` (+pyramiding), `ClaudeBreakoutChandelier` (+chandelier exit),
  `ClaudeBreakoutPro` (all). Each isolates one lever for clean A/B attribution.
- `.github/workflows/ftbot-ci.yml` — lints the helpers, byte-compiles the strategies,
  runs the unit tests on every fqtrader branch / ftbot PR.

These ship the *mechanism*; the numbers (Calmar, DD, net-of-funding PF) still come from
running the backtests on the PC per the plan above.

---

## 13. Summary

- The current strategy is a **sound but bare** turtle skeleton riding on **breadth**.
- The real "more gain, faster" upgrades are **risk-based sizing** + **pyramiding** —
  they complete the Turtle design and attack the payoff ratio and the fat tail
  directly, not the win rate.
- The "smarter" upgrades are **correlation-aware exposure** and **honest backtesting
  (funding/slippage, longer history, Monte-Carlo DD)** — they convert a flattering
  single-path backtest into a risk you can actually size against.
- **Do realism (#3/§9) first.** Then sizing, then pyramiding, then exposure control,
  then breadth, then a careful walk-forward toward the slow gradient. Leverage last,
  and only after the book is de-risked.
- **None of it touches the live paper bot until the Phase-3 window closes.**
