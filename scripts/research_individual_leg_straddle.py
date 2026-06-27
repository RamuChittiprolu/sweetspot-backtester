from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.research_straddle_strategies import select_expiry
from src.data_loader import load_market_data
from src.strategy import add_indicators, nearest_atm


QTY = 130
SIGNAL_TIME = "09:20"
SQUAREOFF_TIME = "15:15"

ENTRY_MODES = ["next_candle_open"]
TARGET_PCTS = [0.10, 0.15, 0.20, 0.25, 0.35, 0.50, 0.75, 1.00, 1.50, 2.00]
LEG_SL_PCTS = [0.0, 0.50, 0.70]
ENTRY_SLIPPAGES = [1.0]
MARKET_EXIT_SLIPPAGES = [1.0]
DAY_FILTERS = [
    "all_days",
    "expiry_days",
    "non_expiry_days",
    "weekday_Monday",
    "weekday_Tuesday",
    "weekday_Wednesday",
    "weekday_Thursday",
    "weekday_Friday",
]
BASKETS = {
    "atm_only": [0],
    "atm_minus50_only": [-50],
    "atm_minus50_atm": [-50, 0],
    "atm_pm50": [-50, 0, 50],
}

BROKERAGE_PER_ORDER = 20.0
STT_SELL_RATE = 0.0015
STAMP_BUY_RATE = 0.00003
EXCHANGE_TXN_RATE = 0.0003503
SEBI_RATE = 0.000001
GST_RATE = 0.18


@dataclass(frozen=True)
class Variant:
    day_filter: str
    basket_name: str
    entry_mode: str
    target_pct: float
    leg_sl_pct: float
    entry_slippage: float
    market_exit_slippage: float


def charges_for_option_leg(entry_exec: float, exit_exec: float) -> float:
    buy_turnover = entry_exec * QTY
    sell_turnover = exit_exec * QTY
    brokerage = BROKERAGE_PER_ORDER * 2
    stt = sell_turnover * STT_SELL_RATE
    stamp_duty = buy_turnover * STAMP_BUY_RATE
    exchange_txn = (buy_turnover + sell_turnover) * EXCHANGE_TXN_RATE
    sebi_fee = (buy_turnover + sell_turnover) * SEBI_RATE
    gst = (brokerage + exchange_txn + sebi_fee) * GST_RATE
    return brokerage + stt + stamp_duty + exchange_txn + sebi_fee + gst


def week_start_monday(value: date) -> date:
    return value - timedelta(days=value.weekday())


def expiry_dates_from_available(dates: list[date]) -> set[date]:
    weeks: dict[date, list[date]] = {}
    for value in sorted(dates):
        weeks.setdefault(week_start_monday(value), []).append(value)

    expiry_dates: set[date] = set()
    for monday, week_dates in weeks.items():
        revised_rule = week_dates[0] >= date(2025, 9, 1)
        target = monday + timedelta(days=1 if revised_rule else 3)
        candidates = [value for value in week_dates if value <= target]
        if candidates:
            expiry_dates.add(max(candidates))
    return expiry_dates


def build_leg_paths(options: pd.DataFrame, spot: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    options_by_date = {trade_date: df for trade_date, df in options.groupby("date", sort=True)}
    all_offsets = sorted({offset for offsets in BASKETS.values() for offset in offsets})

    for trade_date, day_spot in spot.groupby("date", sort=True):
        day_options = options_by_date.get(trade_date)
        if day_options is None:
            continue

        spot_915 = day_spot[day_spot["time"] == "09:15"]
        if spot_915.empty:
            continue
        nifty_open = float(spot_915.sort_values("datetime").iloc[0]["open"])
        atm = nearest_atm(nifty_open, 50)

        for offset in all_offsets:
            strike = atm + offset
            expiry = select_expiry(day_options, trade_date, strike)
            if expiry is None:
                continue
            for side in ["CE", "PE"]:
                leg = day_options[
                    (day_options["strike"] == strike)
                    & (day_options["option_type"] == side)
                    & (day_options["expiry_date"] == expiry)
                ].sort_values("datetime")
                if leg.empty:
                    continue

                signal_rows = leg[leg["time"] == SIGNAL_TIME]
                if signal_rows.empty:
                    continue
                after_signal = leg[leg["datetime"] > signal_rows.iloc[0]["datetime"]]
                if after_signal.empty:
                    continue

                rows.append(
                    {
                        "date": trade_date,
                        "month": pd.Timestamp(trade_date).strftime("%Y-%m"),
                        "atm": atm,
                        "offset": offset,
                        "strike": strike,
                        "side": side,
                        "close_0920_entry_raw": float(signal_rows.iloc[0]["close"]),
                        "next_open_entry_raw": float(after_signal.iloc[0]["open"]),
                        "future_after_signal": after_signal[
                            ["time", "open", "high", "low", "close"]
                        ].to_dict("records"),
                    }
                )
    return pd.DataFrame(rows)


def simulate_leg(path: pd.Series, variant: Variant) -> dict[str, object]:
    if variant.entry_mode == "next_candle_open":
        entry_raw = float(path["next_open_entry_raw"])
    else:
        entry_raw = float(path["close_0920_entry_raw"])

    entry_exec = entry_raw + variant.entry_slippage
    target_exec = entry_exec * (1 + variant.target_pct)
    stop_exec = entry_exec * (1 - variant.leg_sl_pct) if variant.leg_sl_pct else None

    for row in path["future_after_signal"]:
        close_market = max(0.0, float(row["close"]) - variant.market_exit_slippage)
        if stop_exec and close_market <= stop_exec:
            return {
                "entry_exec": entry_exec,
                "exit_exec": close_market,
                "exit_time": row["time"],
                "exit_reason": "LEG_SL_CLOSE",
            }

        # Resting target limit order: using individual option high is reasonable here.
        if float(row["high"]) >= target_exec:
            return {
                "entry_exec": entry_exec,
                "exit_exec": target_exec,
                "exit_time": row["time"],
                "exit_reason": "TARGET_LIMIT",
            }

        if row["time"] >= SQUAREOFF_TIME:
            return {
                "entry_exec": entry_exec,
                "exit_exec": close_market,
                "exit_time": row["time"],
                "exit_reason": "SQUAREOFF_CLOSE",
            }

    last = path["future_after_signal"][-1]
    return {
        "entry_exec": entry_exec,
        "exit_exec": max(0.0, float(last["close"]) - variant.market_exit_slippage),
        "exit_time": last["time"],
        "exit_reason": "END_CLOSE",
    }


def evaluate(paths: pd.DataFrame, variant: Variant, expiry_dates: set[date]) -> tuple[dict[str, object], pd.DataFrame]:
    offsets = BASKETS[variant.basket_name]
    subset = paths[paths["offset"].isin(offsets)].copy()
    if variant.day_filter == "expiry_days":
        subset = subset[subset["date"].isin(expiry_dates)]
    elif variant.day_filter == "non_expiry_days":
        subset = subset[~subset["date"].isin(expiry_dates)]
    elif variant.day_filter.startswith("weekday_"):
        wanted = variant.day_filter.removeprefix("weekday_")
        subset = subset[pd.to_datetime(subset["date"]).dt.day_name() == wanted]
    if subset.empty:
        return {}, pd.DataFrame()

    leg_rows: list[dict[str, object]] = []
    for _, path in subset.iterrows():
        result = simulate_leg(path, variant)
        entry_exec = float(result["entry_exec"])
        exit_exec = float(result["exit_exec"])
        points = exit_exec - entry_exec
        charges = charges_for_option_leg(entry_exec, exit_exec)
        leg_rows.append(
            {
                "date": path["date"],
                "month": path["month"],
                "atm": path["atm"],
                "offset": path["offset"],
                "strike": path["strike"],
                "side": path["side"],
                "entry_exec": entry_exec,
                "exit_exec": exit_exec,
                "exit_time": result["exit_time"],
                "exit_reason": result["exit_reason"],
                "points": points,
                "gross_rupee_pnl": points * QTY,
                "charges": charges,
                "net_rupee_pnl": points * QTY - charges,
            }
        )

    legs = pd.DataFrame(leg_rows)
    daily = (
        legs.groupby(["date", "month"], as_index=False)
        .agg(
            option_legs=("side", "count"),
            points=("points", "sum"),
            gross_rupee_pnl=("gross_rupee_pnl", "sum"),
            charges=("charges", "sum"),
            net_rupee_pnl=("net_rupee_pnl", "sum"),
            target_legs=("exit_reason", lambda s: int((s == "TARGET_LIMIT").sum())),
            sl_legs=("exit_reason", lambda s: int((s == "LEG_SL_CLOSE").sum())),
        )
        .sort_values("date")
    )
    monthly = daily.groupby("month")["points"].sum()
    complete_months = monthly[monthly.index != "2025-08"]
    daily["equity"] = daily["points"].cumsum()
    daily["peak"] = daily["equity"].cummax()
    daily["drawdown"] = daily["equity"] - daily["peak"]

    summary = {
        "day_filter": variant.day_filter,
        "basket_name": variant.basket_name,
        "entry_mode": variant.entry_mode,
        "target_pct": variant.target_pct,
        "leg_sl_pct": variant.leg_sl_pct,
        "entry_slippage": variant.entry_slippage,
        "market_exit_slippage": variant.market_exit_slippage,
        "days": int(len(daily)),
        "option_legs": int(len(legs)),
        "total_points": round(float(daily["points"].sum()), 2),
        "net_rupee_pnl": round(float(daily["net_rupee_pnl"].sum()), 0),
        "daily_win_rate_pct": round(float((daily["net_rupee_pnl"] > 0).mean() * 100), 2),
        "avg_month_ex_aug": round(float(complete_months.mean()), 2) if not complete_months.empty else 0.0,
        "best_month": round(float(complete_months.max()), 2) if not complete_months.empty else 0.0,
        "worst_month": round(float(complete_months.min()), 2) if not complete_months.empty else 0.0,
        "positive_months": int((complete_months > 0).sum()),
        "months_350_plus": int((complete_months >= 350).sum()),
        "max_drawdown_points": round(float(daily["drawdown"].min()), 2),
        "target_legs_pct": round(float((legs["exit_reason"] == "TARGET_LIMIT").mean() * 100), 2),
        "sl_legs_pct": round(float((legs["exit_reason"] == "LEG_SL_CLOSE").mean() * 100), 2),
    }
    return summary, daily


def main() -> int:
    market = load_market_data(ROOT / "data/raw", ROOT / "data/nifty_spot", 5)
    options = add_indicators(market.options, 20)
    paths = build_leg_paths(options, market.spot)
    expiry_dates = expiry_dates_from_available(list(paths["date"].unique()))

    summaries: list[dict[str, object]] = []
    selected_daily: dict[str, pd.DataFrame] = {}
    for day_filter in DAY_FILTERS:
        for basket_name in BASKETS:
            for entry_mode in ENTRY_MODES:
                for target_pct in TARGET_PCTS:
                    for leg_sl_pct in LEG_SL_PCTS:
                        for entry_slippage in ENTRY_SLIPPAGES:
                            for market_exit_slippage in MARKET_EXIT_SLIPPAGES:
                                variant = Variant(
                                    day_filter,
                                    basket_name,
                                    entry_mode,
                                    target_pct,
                                    leg_sl_pct,
                                    entry_slippage,
                                    market_exit_slippage,
                                )
                                summary, daily = evaluate(paths, variant, expiry_dates)
                                if not summary:
                                    continue
                                summaries.append(summary)
                                key = (
                                    f"{day_filter}__{basket_name}__{entry_mode}"
                                    f"__target_{target_pct:g}__legsl_{leg_sl_pct:g}"
                                    f"__entryslip_{entry_slippage:g}__exitslip_{market_exit_slippage:g}"
                                )
                                selected_daily[key] = daily

    out_dir = ROOT / "output" / "research_straddle"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_df = pd.DataFrame(summaries).sort_values(
        ["avg_month_ex_aug", "total_points"], ascending=False
    )
    summary_df.to_csv(out_dir / "individual_leg_straddle_summary.csv", index=False)

    realistic = summary_df[
        (summary_df["entry_mode"] == "next_candle_open")
        & (summary_df["entry_slippage"] >= 1.0)
        & (summary_df["market_exit_slippage"] >= 1.0)
    ].copy()
    realistic.to_csv(out_dir / "individual_leg_straddle_realistic_summary.csv", index=False)

    for _, row in realistic.head(5).iterrows():
        key = (
            f"{row['day_filter']}__{row['basket_name']}__{row['entry_mode']}"
            f"__target_{row['target_pct']:g}__legsl_{row['leg_sl_pct']:g}"
            f"__entryslip_{row['entry_slippage']:g}__exitslip_{row['market_exit_slippage']:g}"
        )
        daily = selected_daily.get(key)
        if daily is not None:
            daily.to_csv(out_dir / f"individual_leg_top_{key}_daily.csv", index=False)

    print("All variants:", len(summary_df))
    print("\nTop 25 all individual-leg variants")
    print(summary_df.head(25).to_string(index=False))
    print("\nTop 25 realistic individual-leg variants: next open, >=1pt entry slip, >=1pt market exit slip")
    print(realistic.head(25).to_string(index=False))
    print(f"\nSaved {out_dir / 'individual_leg_straddle_summary.csv'}")
    print(f"Saved {out_dir / 'individual_leg_straddle_realistic_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
