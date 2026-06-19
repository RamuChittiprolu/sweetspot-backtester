# Experiment Log

Record each config run here with the command, config changes, and result summary.

| Date | Config | Trades | Trading Days | Total P&L | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| 2026-06-19 | v2A_no_premium | 42 | 14 | 71.05 | No premium filter. |
| 2026-06-19 | v2B_premium_100 | 33 | 12 | 105.40 | Premium must be >= 100. |
| 2026-06-19 | v2C_conditional | 42 | 14 | 71.05 | Premium >= 100 only when pivot >= 100. |
| 2026-06-19 | v2_1_final | 33 | 12 | 105.40 | Final config currently matches v2B. |
| 2026-06-19 | v3_ema20_bounce | 14 | 7 | -97.05 | v2B plus current entry candle must touch EMA20. |
| 2026-06-19 | v3_retest_only | 18 | 11 | 141.35 | Config: configs/v3_retest_only.yaml; Wins: 8; Losses: 10; Win rate: 44.44%; Avg P&L: 7.85; Best day: 118.95; Worst day: -62.10; Max drawdown: -136.95. |
