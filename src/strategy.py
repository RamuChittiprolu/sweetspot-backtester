from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Signal:
    datetime: pd.Timestamp
    date: object
    expiry_date: object
    strike: int
    option_type: str
    setup: str
    priority: int
    entry_price: float
    pivot: float
    distance_from_pivot: float
    strike_distance: int
    candle_range: float
    stop_level: float | None = None
    vix_status: str = ""
    vix_reason: str = ""


SETUP_PRIORITY = {
    "fresh_reclaim": 1,
    "continuation_base_breakout": 2,
    "first_breakout": 3,
    "side_switch": 4,
    "retest_bounce": 5,
    "vacuum_breakout": 6,
    "normal_breakout": 7,
}


def nearest_atm(spot_open: float, strike_step: int) -> int:
    return int(round(float(spot_open) / strike_step) * strike_step)


def add_indicators(options: pd.DataFrame, ema_period: int) -> pd.DataFrame:
    df = options.copy()
    df = df.drop_duplicates(["datetime", "strike", "option_type", "expiry_date"], keep="first")
    df = df.sort_values(["date", "strike", "option_type", "expiry_date", "datetime"])
    intraday_group = ["date", "strike", "option_type", "expiry_date"]
    df["ema"] = (
        df.groupby(intraday_group, group_keys=False)["close"]
        .transform(lambda s: s.ewm(span=ema_period, adjust=False).mean())
    )
    df["prev_close"] = df.groupby(intraday_group)["close"].shift(1)
    df["prev_open"] = df.groupby(intraday_group)["open"].shift(1)
    df["prev_high"] = df.groupby(intraday_group)["high"].shift(1)
    df["prev_low"] = df.groupby(intraday_group)["low"].shift(1)
    df["day_low_so_far"] = df.groupby(intraday_group)["low"].cummin()
    df["day_high_so_far"] = df.groupby(intraday_group)["high"].cummax()
    return df


def build_daily_context(day_options: pd.DataFrame, day_spot: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any] | None:
    strat = config["strategy"]
    date = day_options["date"].iloc[0]
    spot_915 = day_spot.loc[day_spot["time"] == "09:15"]
    if spot_915.empty:
        return None
    spot_open = float(spot_915.sort_values("datetime").iloc[0]["open"])
    atm = nearest_atm(spot_open, int(strat.get("strike_step", 50)))
    open_915 = day_options.loc[day_options["time"] == "09:15"]
    if open_915.empty:
        return None

    pairs = (
        open_915.pivot_table(index=["expiry_date", "strike"], columns="option_type", values="open", aggfunc="first")
        .dropna(subset=["CE", "PE"], how="any")
        .reset_index()
    )
    if pairs.empty:
        return None
    valid_expiry = pairs["expiry_date"].isna() | pairs["expiry_date"].map(lambda value: value >= date if pd.notna(value) else True)
    pairs = pairs[valid_expiry]
    if pairs.empty:
        return None
    pairs["pivot"] = (pairs["CE"] + pairs["PE"]) / 2.0
    pairs = pairs.sort_values(["strike", "expiry_date"], na_position="last").drop_duplicates("strike", keep="first")

    universe_cfg = strat.get("universe", {"mode": "offsets", "offsets": [0]})
    mode = universe_cfg.get("mode", "offsets")
    if mode == "all_available":
        strikes = sorted(int(x) for x in pairs["strike"])
    else:
        offsets = universe_cfg.get("offsets", [0])
        strikes = sorted({atm + int(offset) for offset in offsets})
        strikes = [s for s in strikes if s in set(pairs["strike"])]
    if not strikes:
        return None

    selected = pairs[pairs["strike"].isin(strikes)].copy()
    pivots = {int(row["strike"]): float(row["pivot"]) for _, row in selected.iterrows()}
    expiries = {int(row["strike"]): row["expiry_date"] for _, row in selected.iterrows()}
    return {"spot_open": spot_open, "atm": atm, "strikes": strikes, "pivots": pivots, "expiries": expiries}


def classify_setup(row: pd.Series, pivot: float, config: dict[str, Any]) -> str | None:
    strat = config["strategy"]
    candle_range = float(row["high"] - row["low"])
    if candle_range > float(strat.get("max_entry_candle_range", 13)):
        return None
    close = float(row["close"])
    if close <= pivot or close > pivot + float(strat.get("max_entry_distance_from_pivot", 20)):
        return None

    is_green = float(row["close"]) > float(row["open"])
    prev_close = row.get("prev_close", np.nan)
    broke_from_below = pd.isna(prev_close) or float(prev_close) <= pivot
    near_pivot = float(row["low"]) <= pivot + float(strat.get("retest_tolerance", 3))
    body = abs(float(row["close"]) - float(row["open"]))
    body_ratio = body / candle_range if candle_range > 0 else 0.0
    close_position = (close - float(row["low"])) / candle_range if candle_range > 0 else 0.0
    max_pre_entry_move = strat.get("max_pre_entry_move_from_day_low")
    if max_pre_entry_move is not None:
        day_low_so_far = row.get("day_low_so_far", np.nan)
        if pd.notna(day_low_so_far) and close - float(day_low_so_far) > float(max_pre_entry_move):
            return None

    min_body_ratio = strat.get("min_entry_body_ratio")
    if min_body_ratio is not None and body_ratio < float(min_body_ratio):
        return None

    min_close_position = strat.get("min_entry_close_position")
    if min_close_position is not None and close_position < float(min_close_position):
        return None

    if is_green and near_pivot:
        min_close_position = strat.get("min_retest_close_position")
        if min_close_position is not None and close_position < float(min_close_position):
            return None
        if strat.get("reject_retest_after_strong_red_prev", False):
            prev_open = row.get("prev_open", np.nan)
            if pd.notna(prev_open) and pd.notna(prev_close):
                prev_range = float(row.get("prev_high", 0) - row.get("prev_low", 0))
                prev_body = abs(float(prev_open) - float(prev_close))
                prev_body_ratio = prev_body / prev_range if prev_range > 0 else 0.0
                if float(prev_close) < float(prev_open) and prev_body_ratio >= float(strat.get("strong_red_body_ratio", 0.55)):
                    return None
        return "retest_bounce"
    if (
        strat.get("enable_vacuum", True)
        and is_green
        and broke_from_below
        and close > float(row.get("ema", close))
        and body_ratio >= float(strat.get("vacuum_min_body_ratio", 0.55))
    ):
        return "vacuum_breakout"
    if broke_from_below:
        return "normal_breakout"
    return None


def find_signals(candle_rows: pd.DataFrame, daily_context: dict[str, Any], config: dict[str, Any]) -> list[Signal]:
    signals: list[Signal] = []
    strat = config["strategy"]
    atm = int(daily_context["atm"])
    pivots: dict[int, float] = daily_context["pivots"]
    expiries = daily_context.get("expiries", {})
    rows = candle_rows[candle_rows["strike"].isin(pivots.keys())]
    if expiries:
        rows = rows[rows.apply(lambda row: row["expiry_date"] == expiries.get(int(row["strike"])), axis=1)]
    allowed_types = {item.upper() for item in strat.get("allowed_option_types", ["CE", "PE"])}
    allowed_setups = set(strat.get("allowed_setups", ["retest_bounce", "vacuum_breakout", "normal_breakout"]))
    for _, row in rows.iterrows():
        if row["option_type"] not in allowed_types:
            continue
        strike = int(row["strike"])
        pivot = pivots[strike]
        setup = classify_setup(row, pivot, config)
        if not setup or setup not in allowed_setups:
            continue
        signals.append(
            Signal(
                datetime=row["datetime"],
                date=row["date"],
                expiry_date=row["expiry_date"],
                strike=strike,
                option_type=row["option_type"],
                setup=setup,
                priority=SETUP_PRIORITY[setup],
                entry_price=float(row["close"]),
                pivot=pivot,
                distance_from_pivot=float(row["close"] - pivot),
                strike_distance=strike - atm,
                candle_range=float(row["high"] - row["low"]),
            )
        )
    return sorted(signals, key=lambda s: (s.priority, s.distance_from_pivot, abs(s.strike_distance), s.option_type))
