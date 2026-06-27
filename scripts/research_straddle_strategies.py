from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_loader import load_market_data
from src.strategy import add_indicators, nearest_atm


ENTRY_TIMES = ["09:20", "09:30", "09:45", "10:00", "11:00", "13:00"]
OFFSETS = [-100, -50, 0, 50, 100]
SL_PCTS = [0, 0.10, 0.15, 0.20, 0.25]
TARGET_PCTS = [0, 0.15, 0.25, 0.35, 0.50, 0.75, 1.00]


def select_expiry(day_options: pd.DataFrame, trade_date, strike: int) -> object | None:
    open_915 = day_options[(day_options["time"] == "09:15") & (day_options["strike"] == strike)]
    expiries = sorted(x for x in open_915["expiry_date"].dropna().unique() if x >= trade_date)
    return expiries[0] if expiries else None


def build_paths(options: pd.DataFrame, spot: pd.DataFrame) -> pd.DataFrame:
    rows = []
    options_by_date = {date: df for date, df in options.groupby("date", sort=True)}
    for trade_date, day_spot in spot.groupby("date", sort=True):
        day_options = options_by_date.get(trade_date)
        if day_options is None:
            continue
        s915 = day_spot[day_spot["time"] == "09:15"]
        if s915.empty:
            continue
        atm = nearest_atm(float(s915.sort_values("datetime").iloc[0]["open"]), 50)
        for offset in OFFSETS:
            strike = atm + offset
            expiry = select_expiry(day_options, trade_date, strike)
            if expiry is None:
                continue
            ce = day_options[
                (day_options["strike"] == strike)
                & (day_options["option_type"] == "CE")
                & (day_options["expiry_date"] == expiry)
            ].sort_values("datetime")
            pe = day_options[
                (day_options["strike"] == strike)
                & (day_options["option_type"] == "PE")
                & (day_options["expiry_date"] == expiry)
            ].sort_values("datetime")
            if ce.empty or pe.empty:
                continue
            merged = ce[["datetime", "time", "open", "high", "low", "close"]].merge(
                pe[["datetime", "time", "open", "high", "low", "close"]],
                on=["datetime", "time"],
                suffixes=("_ce", "_pe"),
            )
            for entry_time in ENTRY_TIMES:
                entry_rows = merged[merged["time"] == entry_time]
                if entry_rows.empty:
                    continue
                entry = entry_rows.iloc[0]
                future = merged[merged["datetime"] > entry["datetime"]]
                if future.empty:
                    continue
                entry_price = float(entry["close_ce"] + entry["close_pe"])
                rows.append(
                    {
                        "date": trade_date,
                        "month": pd.Timestamp(trade_date).strftime("%Y-%m"),
                        "entry_time": entry_time,
                        "strike_offset": offset,
                        "strike": strike,
                        "expiry_date": expiry,
                        "entry_price": entry_price,
                        "future": future[
                            ["time", "high_ce", "low_ce", "close_ce", "high_pe", "low_pe", "close_pe"]
                        ].to_dict("records"),
                    }
                )
    return pd.DataFrame(rows)


def simulate(entry_price: float, future: list[dict], sl_pct: float, target_pct: float):
    stop = entry_price * (1 - sl_pct) if sl_pct else None
    target = entry_price * (1 + target_pct) if target_pct else None
    max_fav = 0.0
    last = future[-1]
    for row in future:
        high = float(row["high_ce"] + row["high_pe"])
        low = float(row["low_ce"] + row["low_pe"])
        close = float(row["close_ce"] + row["close_pe"])
        max_fav = max(max_fav, high - entry_price)
        if stop and low <= stop:
            return stop, "SL", max_fav
        if target and high >= target:
            return target, "TARGET", max_fav
        if row["time"] >= "15:15":
            return close, "SQUAREOFF", max_fav
    return float(last["close_ce"] + last["close_pe"]), "END", max_fav


def evaluate(paths: pd.DataFrame) -> pd.DataFrame:
    summaries = []
    for entry_time in ENTRY_TIMES:
        for offset in OFFSETS:
            subset = paths[(paths["entry_time"] == entry_time) & (paths["strike_offset"] == offset)]
            if subset.empty:
                continue
            for sl_pct in SL_PCTS:
                for target_pct in TARGET_PCTS:
                    pnls = []
                    reasons = []
                    months = []
                    for _, path in subset.iterrows():
                        exit_price, reason, _ = simulate(float(path["entry_price"]), path["future"], sl_pct, target_pct)
                        pnls.append(exit_price - float(path["entry_price"]))
                        reasons.append(reason)
                        months.append(path["month"])
                    df = pd.DataFrame({"month": months, "pnl": pnls, "reason": reasons})
                    monthly = df.groupby("month")["pnl"].sum()
                    complete = monthly[~monthly.index.isin(["2025-08"])]
                    if complete.empty:
                        continue
                    summaries.append(
                        {
                            "entry_time": entry_time,
                            "strike_offset": offset,
                            "sl_pct": sl_pct,
                            "target_pct": target_pct,
                            "trades": len(df),
                            "points": round(float(df["pnl"].sum()), 2),
                            "avg_trade": round(float(df["pnl"].mean()), 2),
                            "win_rate": round(float((df["pnl"] > 0).mean() * 100), 2),
                            "avg_month": round(float(complete.mean()), 2),
                            "best_month": round(float(complete.max()), 2),
                            "worst_month": round(float(complete.min()), 2),
                            "months_350": int((complete >= 350).sum()),
                            "positive_months": int((complete > 0).sum()),
                            "months": int(complete.size),
                        }
                    )
    return pd.DataFrame(summaries).sort_values(["avg_month", "points"], ascending=False)


def main() -> int:
    market = load_market_data(ROOT / "data/raw", ROOT / "data/nifty_spot", 5)
    options = add_indicators(market.options, 20)
    out_dir = ROOT / "output" / "research_straddle"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = build_paths(options, market.spot)
    paths.drop(columns=["future"]).to_csv(out_dir / "straddle_entry_paths.csv", index=False)
    summary = evaluate(paths)
    summary.to_csv(out_dir / "straddle_summary.csv", index=False)
    print("paths", len(paths))
    print(summary.head(40).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
