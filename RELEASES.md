# Sweet Spot Releases

This file records stable strategy milestones, the rules attached to each baseline,
and the main lessons learned from the June backtests.

## v1 backup

Tag: `v1_backup`

Purpose:
- Preserves the earliest recoverable project snapshot before the v2/v3 strategy
  experiments.
- Kept as a rollback point for code and data-loader history.

Strategy rules:
- No finalized strategy release rules are recorded for this snapshot.
- Treat this tag as a code backup, not a validated trading baseline.

Backtest results:
- No formal backtest report is recorded for this release.

Major insights:
- Keep stable tags before strategy refactors.
- Separate loader correctness from strategy experimentation.
- Preserve reproducible reports for every later baseline.

## v2B baseline

Tag: `v2B-baseline`

Config: `configs/v2B_premium_100.yaml`

Strategy rules:
- Use filename trade date as the official trading session.
- Use previous-day candles only for EMA warm-up.
- Pivot = `(09:15 CE open + 09:15 PE open) / 2`.
- Start checking entries from `09:20`.
- Premium filter: contract close must be `>= 100`.
- Entry requires close above pivot.
- Entry price must be `<= pivot + 20`.
- Trade CE or PE, whichever gives the first valid signal.
- One active trade at a time.
- Re-entry is allowed after exit.
- Hard stop loss = `entry_price - 15`.
- Move stop to cost after `+20` high is reached.
- Activate trailing stop after `+40` high is reached.
- TSL = highest close since entry minus `20`.
- Active stop = max hard SL, cost SL, and TSL when active.
- Stop trading after 3 losing trades in a day or daily P&L `<= -50`.
- Exit open trades at last candle close.

Backtest results:
- Trading days: 12
- Trades: 33
- Wins: 11
- Losses: 22
- Win rate: 33.33%
- Total P&L: 105.40
- Average P&L per trade: 3.19
- Best day: 92.30
- Worst day: -55.60
- Max drawdown: -119.90

Major insights:
- `premium >= 100` improved over no-premium filtering.
- v2A no-premium and v2C conditional premium both produced 42 trades and
  71.05 P&L on this data.
- v2B reduced trade count to 33 and improved total P&L to 105.40.
- First trades of the day were weak: 12 trades, 2 wins, 10 losses, -80.80 P&L.
- Re-entry trades carried performance: 21 trades, 9 wins, 12 losses, 186.20 P&L.
- EMA20-touch-only entry was not enough by itself; it reduced trades but hurt P&L.

## v3 retest baseline

Tag: `v3-retest-baseline`

Branch: `stable-v3-retest`

Config: `configs/v3_retest_only.yaml`

Strategy rules:
- Keep all v2B risk, premium, pivot, and exit rules unchanged.
- Change entry timing only:
  - First pivot breakout does not enter.
  - Mark breakout when a candle closes above pivot.
  - Wait for a later candle to retest pivot.
  - Retest requires `low <= pivot <= high`.
  - Retest candle must close above pivot.
  - Enter at retest candle close.

Backtest results:
- Trading days: 11
- Trades: 18
- Wins: 8
- Losses: 10
- Win rate: 44.44%
- Total P&L: 141.35
- Average P&L per trade: 7.85
- Best day: 118.95
- Worst day: -62.10
- Max drawdown: -136.95

Major insights:
- Waiting for a pivot retest improved trade quality.
- v3 retest-only reduced trades from 33 to 18.
- Net P&L improved from 105.40 to 141.35.
- Win rate improved from 33.33% to 44.44%.
- Max drawdown worsened slightly, from -119.90 to -136.95.
- The retest rule appears more useful than the standalone EMA20-touch filter on
  this June sample.
