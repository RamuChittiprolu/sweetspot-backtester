# Sweet Spot v3.2.1 Multi-Strike Probability Backtester

New Python backtester for the Sweet Spot strategy using 5-minute NIFTY option CSV data.

## Folder Layout

- `data/raw` - option CSV files
- `data/nifty_spot` - NIFTY spot/index CSV files
- `data/processed` - optional normalized data exports
- `configs` - strategy YAML configs
- `src` - backtester source
- `output/trades` - trade-level CSV outputs
- `output/reports` - daily/monthly/strategy reports
- `output/probability` - historical probability reports
- `tests` - pytest tests

## Run

```powershell
pip install -r requirements.txt
python -m src.main --config configs/multistrike_atm_pm50.yaml
```

The loader auto-detects common CSV columns and can extract `strike` and `CE`/`PE` from filenames when those columns are absent.

Required data:

- Option candles with datetime, open, high, low, close, strike, and option type.
- NIFTY spot/index candles with datetime and open. The 09:15 open is used for ATM selection.

## Core Rules Implemented

- Daily NIFTY 09:15 open selects nearest ATM strike.
- Configurable strike universe: ATM only, ATM +/- 50, ATM +/- 100, ATM +/- 150, or all real-time available strikes.
- Same-strike pivot = `(CE 09:15 open + PE 09:15 open) / 2`.
- CE and PE are scanned separately, with only one active trade at a time.
- Entry only on close above pivot and at or below `pivot + 20`.
- Anti-chase max entry candle range is configurable.
- Setup priority: retest/bounce, vacuum breakout, normal breakout.
- Hard SL exits on close below the same strike pivot.
- At +20 points, C2C protection exits exactly at entry if hit.
- At +40 points, trailing SL follows option candle lows while C2C remains active.

## Outputs

- `output/trades/all_trades.csv`
- `output/reports/daily_summary.csv`
- `output/reports/monthly_summary.csv`
- `output/reports/strategy_summary.csv`
- `output/reports/bad_day_analysis.csv`
- `output/probability/probability_report.csv`
- `output/probability/setup_probability.csv`
- `output/probability/time_bucket_probability.csv`
- `output/probability/strike_probability.csv`
- `output/probability/take_skip_candidates.csv`
