# sweetspot_backtester

## Download NIFTY 15-minute candles from Zerodha

Set your Kite Connect credentials in the shell:

```powershell
$env:KITE_API_KEY="your_api_key"
$env:KITE_ACCESS_TOKEN="your_access_token"
```

Then download NIFTY 50 index candles from 1-Jan-2026 through today:

```powershell
python src\download_kite_historical.py
```

The default output is written to `data\nifty_15minute_2026-01-01_to_<today>.csv`.

Useful overrides:

```powershell
python src\download_kite_historical.py --from-date 2026-01-01 --to-date 2026-06-19 --output data\nifty_15minute.csv
```

Defaults:

- Instrument token: `256265` (`NSE:NIFTY 50`)
- Interval: `15minute`
- Market time window: `09:15:00` to `15:30:00`

## Extract daily 09:15 open strike

Create a daily file with the NIFTY 09:15 open and nearest 50-point strike:

```powershell
python src\extract_daily_open_strikes.py
```

The default output is `data\nifty_daily_0915_open_strikes.csv`.

Useful overrides:

```powershell
python src\extract_daily_open_strikes.py --input data\nifty_15minute_2026-01-01_to_2026-06-19.csv --strike-step 50
```

## Create empty daily CE/PE text files

Create empty text files for both CE and PE using the daily nearest strike:

```powershell
python src\create_daily_option_txt_files.py
```

The default output folder is `data\daily_option_txt_files`, grouped by month with filenames like `Apr\8-Apr-23850-CE.txt`.
