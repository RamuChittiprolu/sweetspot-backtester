from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_loader import load_market_data
from src.strategy import add_indicators, nearest_atm


ORB_ENDS = ["09:30", "09:45", "10:00"]
ENTRY_UNTILS = ["12:00", "13:30", "14:30"]
OFFSETS = [-100, -50, 0, 50, 100]
STOPS = [15, 20, 25, 30]
TARGETS = [40, 60, 80, 100, None]


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle)
    for key in ["options_dir", "spot_dir"]:
        cfg["data"][key] = str(ROOT / cfg["data"][key])
    return cfg


def select_expiry(day_options: pd.DataFrame, trade_date, strike: int) -> object | None:
    open_915 = day_options[(day_options["time"] == "09:15") & (day_options["strike"] == strike)]
    expiries = sorted(x for x in open_915["expiry_date"].dropna().unique() if x >= trade_date)
    return expiries[0] if expiries else None


def first_orb_signal(day_spot: pd.DataFrame, orb_end: str, entry_until: str):
    range_spot = day_spot[(day_spot["time"] >= "09:15") & (day_spot["time"] < orb_end)]
    scan_spot = day_spot[(day_spot["time"] >= orb_end) & (day_spot["time"] <= entry_until)]
    if range_spot.empty or scan_spot.empty:
        return None
    orb_high = float(range_spot["high"].max())
    orb_low = float(range_spot["low"].min())
    for _, row in scan_spot.sort_values("datetime").iterrows():
        if float(row["close"]) > orb_high:
            return row["datetime"], "CE", orb_high, orb_low
        if float(row["close"]) < orb_low:
            return row["datetime"], "PE", orb_high, orb_low
    return None


def build_entry_paths(options: pd.DataFrame, spot: pd.DataFrame) -> pd.DataFrame:
    rows = []
    options_by_date = {date: df for date, df in options.groupby("date", sort=True)}
    for trade_date, day_spot in spot.groupby("date", sort=True):
        day_options = options_by_date.get(trade_date)
        if day_options is None or day_options.empty:
            continue
        spot_915 = day_spot[day_spot["time"] == "09:15"]
        if spot_915.empty:
            continue
        atm = nearest_atm(float(spot_915.sort_values("datetime").iloc[0]["open"]), 50)
        signals = {
            (orb_end, entry_until): first_orb_signal(day_spot, orb_end, entry_until)
            for orb_end in ORB_ENDS
            for entry_until in ENTRY_UNTILS
        }
        instrument_cache = {}
        for (orb_end, entry_until), signal in signals.items():
            if signal is None:
                continue
            entry_time, side, orb_high, orb_low = signal
            for offset in OFFSETS:
                strike = atm + offset
                cache_key = (strike, side)
                if cache_key not in instrument_cache:
                    expiry = select_expiry(day_options, trade_date, strike)
                    if expiry is None:
                        instrument_cache[cache_key] = None
                    else:
                        inst = day_options[
                            (day_options["strike"] == strike)
                            & (day_options["option_type"] == side)
                            & (day_options["expiry_date"] == expiry)
                        ].sort_values("datetime")
                        instrument_cache[cache_key] = (expiry, inst)
                cached = instrument_cache[cache_key]
                if cached is None:
                    continue
                expiry, inst = cached
                entry_rows = inst[inst["datetime"] == entry_time]
                if entry_rows.empty:
                    continue
                entry = entry_rows.iloc[0]
                future = inst[inst["datetime"] > entry_time]
                if future.empty:
                    continue
                rows.append(
                    {
                        "date": trade_date,
                        "month": pd.Timestamp(trade_date).strftime("%Y-%m"),
                        "entry_time": entry_time,
                        "orb_end": orb_end,
                        "entry_until": entry_until,
                        "side": side,
                        "strike_offset": offset,
                        "strike": strike,
                        "expiry_date": expiry,
                        "entry_price": float(entry["close"]),
                        "future": future[["time", "high", "low", "close"]].to_dict("records"),
                    }
                )
    return pd.DataFrame(rows)


def simulate_exit(entry_price: float, future: list[dict], sl: float, target: float | None):
    stop = entry_price - sl
    target_price = entry_price + target if target is not None else None
    trail_after = 40 if target is None else None
    trail = None
    max_fav = 0.0
    last = future[-1]
    for row in future:
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        max_fav = max(max_fav, high - entry_price)
        if low <= stop:
            return stop, "SL", max_fav
        if target_price is not None and high >= target_price:
            return target_price, "TARGET", max_fav
        if trail_after is not None and max_fav >= trail_after:
            if trail is not None and low <= trail:
                return trail, "TRAIL", max_fav
            trail = max(trail or entry_price, low)
        if row["time"] >= "15:15":
            return close, "SQUAREOFF", max_fav
    return float(last["close"]), "END", max_fav


def evaluate(entries: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    summaries = []
    best_trades = None
    best_score = -10**9
    for orb_end in ORB_ENDS:
        for entry_until in ENTRY_UNTILS:
            for offset in OFFSETS:
                subset = entries[
                    (entries["orb_end"] == orb_end)
                    & (entries["entry_until"] == entry_until)
                    & (entries["strike_offset"] == offset)
                ]
                if subset.empty:
                    continue
                for sl in STOPS:
                    for target in TARGETS:
                        trades = []
                        for _, entry in subset.iterrows():
                            exit_price, reason, mfe = simulate_exit(float(entry["entry_price"]), entry["future"], sl, target)
                            trades.append(
                                {
                                    "date": entry["date"],
                                    "month": entry["month"],
                                    "entry_time": entry["entry_time"],
                                    "side": entry["side"],
                                    "strike_offset": offset,
                                    "strike": entry["strike"],
                                    "expiry_date": entry["expiry_date"],
                                    "entry_price": round(float(entry["entry_price"]), 2),
                                    "exit_price": round(exit_price, 2),
                                    "pnl": round(exit_price - float(entry["entry_price"]), 2),
                                    "exit_reason": reason,
                                    "max_favorable_points": round(mfe, 2),
                                }
                            )
                        trade_df = pd.DataFrame(trades)
                        monthly = trade_df.groupby("month")["pnl"].sum()
                        complete = monthly[~monthly.index.isin(["2025-08"])]
                        if complete.empty:
                            continue
                        wins = trade_df["pnl"] > 0
                        summary = {
                            "orb_end": orb_end,
                            "entry_until": entry_until,
                            "strike_offset": offset,
                            "sl": sl,
                            "target": target or 0,
                            "exit_model": "trail_after_40" if target is None else f"target_{target}",
                            "trades": len(trade_df),
                            "points": round(float(trade_df["pnl"].sum()), 2),
                            "avg_trade": round(float(trade_df["pnl"].mean()), 2),
                            "win_rate": round(float(wins.mean() * 100), 2),
                            "avg_month": round(float(complete.mean()), 2),
                            "best_month": round(float(complete.max()), 2),
                            "worst_month": round(float(complete.min()), 2),
                            "months_350": int((complete >= 350).sum()),
                            "positive_months": int((complete > 0).sum()),
                            "months": int(complete.size),
                        }
                        summaries.append(summary)
                        score = summary["avg_month"] - abs(min(summary["worst_month"], 0)) * 0.3
                        if score > best_score and summary["months"] >= 8:
                            best_score = score
                            best_trades = trade_df.assign(
                                orb_end=orb_end,
                                entry_until=entry_until,
                                sl=sl,
                                target=target or 0,
                                exit_model=summary["exit_model"],
                            )
    return pd.DataFrame(summaries), best_trades if best_trades is not None else pd.DataFrame()


def main() -> int:
    cfg = load_config(ROOT / "configs" / "multistrike_atm_pm50.yaml")
    market = load_market_data(cfg["data"]["options_dir"], cfg["data"]["spot_dir"], int(cfg["data"].get("candle_minutes", 5)))
    options = add_indicators(market.options, 20)

    out_dir = ROOT / "output" / "research_orb"
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = build_entry_paths(options, market.spot)
    entries.drop(columns=["future"]).to_csv(out_dir / "orb_entry_paths.csv", index=False)
    summary, best_trades = evaluate(entries)
    summary = summary.sort_values(["avg_month", "points"], ascending=False)
    summary.to_csv(out_dir / "orb_variant_summary.csv", index=False)
    best_trades.to_csv(out_dir / "best_orb_trades.csv", index=False)
    print("entries", len(entries))
    print(summary.head(40).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
