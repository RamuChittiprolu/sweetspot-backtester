from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .data_loader import DataValidationError, load_market_data
from .strategy import Signal, add_indicators, build_daily_context, find_signals


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    date: object
    expiry_date: object
    strike: int
    option_type: str
    setup: str
    entry_price: float
    exit_price: float
    pnl: float
    exit_reason: str
    pivot: float
    max_favorable_points: float
    c2c_activated: bool
    trailing_activated: bool
    strike_distance: int
    candle_range: float
    stop_level: float | None = None
    vix_status: str = ""
    vix_reason: str = ""


def _parse_time(value: str) -> str:
    return pd.to_datetime(value).strftime("%H:%M")


def _blocked_entry_time(time_value: str, config: dict[str, Any]) -> bool:
    for window in config["strategy"].get("blocked_entry_windows", []):
        start = _parse_time(window["start"])
        end = _parse_time(window["end"])
        if start <= time_value < end:
            return True
    return False


def _daily_guard_hit(daily_pnl: float, daily_pivot_sl_count: int, config: dict[str, Any]) -> bool:
    risk = config["strategy"].get("daily_risk", {})
    max_loss = risk.get("max_daily_loss")
    max_pivot_sl = risk.get("max_pivot_close_sl")
    if max_loss is not None and daily_pnl <= -abs(float(max_loss)):
        return True
    if max_pivot_sl is not None and daily_pivot_sl_count >= int(max_pivot_sl):
        return True
    return False


def _body_quality(row: pd.Series) -> tuple[float, float, float]:
    candle_range = float(row["high"] - row["low"])
    body = abs(float(row["close"]) - float(row["open"]))
    body_ratio = body / candle_range if candle_range > 0 else 0.0
    close_position = (float(row["close"]) - float(row["low"])) / candle_range if candle_range > 0 else 0.0
    return candle_range, body_ratio, close_position


def _load_vix(config: dict[str, Any]) -> pd.DataFrame:
    path = config["strategy"].get("vix_file")
    if not path:
        return pd.DataFrame()
    vix_path = Path(path)
    if not vix_path.is_absolute():
        vix_path = Path.cwd() / vix_path
    if not vix_path.exists():
        return pd.DataFrame()
    vix = pd.read_csv(vix_path)
    vix.columns = [c.strip().lower() for c in vix.columns]
    if "date" not in vix.columns:
        return pd.DataFrame()
    vix["datetime"] = pd.to_datetime(vix["date"], errors="coerce").dt.tz_localize(None)
    vix = vix.dropna(subset=["datetime"]).sort_values("datetime")
    vix["day"] = vix["datetime"].dt.date
    vix["time"] = vix["datetime"].dt.strftime("%H:%M")
    for col in ["open", "high", "low", "close"]:
        if col in vix.columns:
            vix[col] = pd.to_numeric(vix[col], errors="coerce")
    return vix


def _vix_context(vix: pd.DataFrame, date: object, timestamp: pd.Timestamp) -> tuple[str, str]:
    if vix.empty:
        return "REVIEW", "No VIX data file"
    day = vix[vix["day"] == date]
    if day.empty:
        return "REVIEW", "No VIX data for date"
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    open_915 = day.loc[day["time"] == "09:15", "open"]
    upto = day[day["datetime"] <= ts].tail(4)
    entry = day[day["datetime"] == ts]
    if open_915.empty or entry.empty or upto.empty:
        return "REVIEW", "Missing VIX 09:15 or entry candle"
    vix_open = float(open_915.iloc[0])
    vix_entry = float(entry["close"].iloc[0])
    change_pct = ((vix_entry / vix_open) - 1.0) * 100 if vix_open else 0.0
    change_15m = float(upto["close"].iloc[-1] - upto["close"].iloc[0])
    if change_15m <= -0.15 or change_pct <= -5.0:
        return "SHARP_FALL", f"VIX sharp fall: open change {change_pct:.2f}%, 15m {change_15m:.2f}"
    if change_15m < -0.02 or change_pct < 0:
        return "MILD_FALL", f"VIX mild fall: open change {change_pct:.2f}%, 15m {change_15m:.2f}"
    return "OK", f"VIX OK: open change {change_pct:.2f}%, 15m {change_15m:.2f}"


def _is_weak_quality(body_ratio: float, close_position: float, config: dict[str, Any]) -> bool:
    strat = config["strategy"]
    return body_ratio < float(strat.get("strong_body_ratio", 0.50)) or close_position < float(strat.get("strong_close_position", 0.70))


def _make_signal(
    row: pd.Series,
    setup: str,
    priority: int,
    pivot: float,
    atm: int,
    candle_range: float,
    stop_level: float | None,
    vix_status: str,
    vix_reason: str,
) -> Signal:
    strike = int(row["strike"])
    return Signal(
        datetime=row["datetime"],
        date=row["date"],
        expiry_date=row["expiry_date"],
        strike=strike,
        option_type=row["option_type"],
        setup=setup,
        priority=priority,
        entry_price=float(row["close"]),
        pivot=pivot,
        distance_from_pivot=float(row["close"] - pivot),
        strike_distance=strike - atm,
        candle_range=candle_range,
        stop_level=stop_level,
        vix_status=vix_status,
        vix_reason=vix_reason,
    )


def _v322_signals(
    timestamp: pd.Timestamp,
    candle_rows: pd.DataFrame,
    tradable: pd.DataFrame,
    context: dict[str, Any],
    config: dict[str, Any],
    state: dict[str, Any],
    vix: pd.DataFrame,
) -> list[Signal]:
    strat = config["strategy"]
    atm = int(context["atm"])
    pivots: dict[int, float] = context["pivots"]
    expiries = context.get("expiries", {})
    signals: list[Signal] = []
    allowed_types = {item.upper() for item in strat.get("allowed_option_types", ["CE", "PE"])}

    for _, row in candle_rows.iterrows():
        if row["option_type"] not in allowed_types:
            continue
        strike = int(row["strike"])
        if strike not in pivots:
            continue
        if expiries and row["expiry_date"] != expiries.get(strike):
            continue

        side = row["option_type"]
        pivot = float(pivots[strike])
        close = float(row["close"])
        if close <= pivot:
            continue

        hist = tradable[
            (tradable["datetime"] < timestamp)
            & (tradable["strike"] == strike)
            & (tradable["option_type"] == side)
            & (tradable["expiry_date"] == row["expiry_date"])
        ].sort_values("datetime")
        prev2 = hist.tail(2)
        prev3 = hist.tail(3)
        candle_range, body_ratio, close_position = _body_quality(row)
        vix_status, vix_reason = _vix_context(vix, row["date"], row["datetime"])
        weak = _is_weak_quality(body_ratio, close_position, config)
        side_trades = state["side_counts"].get(side, 0)
        last_exit_time = state.get("last_exit_time")
        candles_after_exit = None
        if last_exit_time is not None:
            candles_after_exit = len(hist[hist["datetime"] > last_exit_time])

        # Strict first pivot breakout.
        prev_close = row.get("prev_close", np.nan)
        broke_from_below = pd.isna(prev_close) or float(prev_close) <= pivot
        day_low_so_far = row.get("day_low_so_far", np.nan)
        not_overextended = pd.isna(day_low_so_far) or close - float(day_low_so_far) <= float(strat.get("max_pre_entry_move_from_day_low", 35))
        if (
            side_trades == 0
            and broke_from_below
            and close <= pivot + float(strat.get("max_entry_distance_from_pivot", 20))
            and candle_range <= float(strat.get("max_entry_candle_range", 13))
            and body_ratio >= float(strat.get("min_entry_body_ratio", 0.35))
            and close_position >= float(strat.get("min_entry_close_position", 0.60))
            and not_overextended
            and not (vix_status == "SHARP_FALL" and weak)
        ):
            signals.append(_make_signal(row, "first_breakout", 3, pivot, atm, candle_range, None, vix_status, vix_reason))

        previous_exit_ok = state.get("last_exit_reason") in {"PIVOT_CLOSE_SL", "C2C"}
        wait_ok = candles_after_exit is not None and candles_after_exit >= int(strat.get("reclaim_wait_candles", 2))
        closes_above_prev2_high = not prev2.empty and close > float(prev2["high"].max())
        prev5 = hist.tail(5)
        recent_washout = not prev5.empty and float(prev5["low"].min()) < pivot

        # Wide reclaim / ignition candle. This is intentionally separate from the normal
        # anti-chase filter because the candle begins from a washout/base and closes strong.
        if (
            strat.get("enable_ignition_reclaim", False)
            and row["time"] >= _parse_time(strat.get("ignition_start_time", "10:00"))
            and recent_washout
            and (closes_above_prev2_high or broke_from_below)
            and close > float(row.get("ema", close))
            and close <= pivot + float(strat.get("ignition_max_entry_distance", 30))
            and candle_range <= float(strat.get("ignition_max_candle_range", 70))
            and body_ratio >= float(strat.get("ignition_min_body_ratio", 0.60))
            and close_position >= float(strat.get("ignition_min_close_position", 0.70))
            and side_trades < int(strat.get("max_trades_per_side_per_day", 2))
            and not (vix_status == "SHARP_FALL" and weak)
        ):
            base_low = float(prev5["low"].min())
            signals.append(_make_signal(row, "ignition_reclaim", 1, pivot, atm, candle_range, base_low, vix_status, vix_reason))

        # Fresh reclaim after failed/closed prior trade.
        if (
            previous_exit_ok
            and wait_ok
            and state.get("last_exit_side") == side
            and side_trades < int(strat.get("max_trades_per_side_per_day", 2))
            and closes_above_prev2_high
            and close > float(row.get("ema", close))
            and close <= pivot + float(strat.get("reclaim_max_entry_distance", 30))
            and candle_range <= float(strat.get("reclaim_max_candle_range", 18))
            and not (vix_status == "SHARP_FALL" and weak)
        ):
            base_low = float(prev2["low"].min()) if not prev2.empty else float(row["low"])
            signals.append(_make_signal(row, "fresh_reclaim", 1, pivot, atm, candle_range, base_low, vix_status, vix_reason))

        # Continuation/base breakout. No day-low overextension rule; use base-low distance instead.
        if len(prev3) >= 3:
            held = bool(((prev3["close"] > pivot) | (prev3["close"] > prev3["ema"])).all())
            base_high = float(prev3["high"].max())
            base_low = float(prev3["low"].min())
            if (
                held
                and close > base_high
                and close <= pivot + float(strat.get("continuation_max_entry_distance", 40))
                and candle_range <= float(strat.get("continuation_max_candle_range", 18))
                and close - base_low <= float(strat.get("continuation_max_distance_from_base_low", 20))
                and side_trades < int(strat.get("max_trades_per_side_per_day", 2))
                and not (vix_status == "SHARP_FALL" and weak)
            ):
                signals.append(_make_signal(row, "continuation_base_breakout", 2, pivot, atm, candle_range, base_low, vix_status, vix_reason))

        # Side switch after prior side exits by SL/C2C.
        if (
            previous_exit_ok
            and state.get("last_exit_side") not in {None, side}
            and state.get("side_switches", 0) < int(strat.get("max_side_switches_per_day", 1))
            and closes_above_prev2_high
            and close > float(row.get("ema", close))
            and close <= pivot + float(strat.get("side_switch_max_entry_distance", 30))
            and candle_range <= float(strat.get("side_switch_max_candle_range", 18))
            and not (vix_status == "SHARP_FALL" and weak)
        ):
            base_low = float(prev2["low"].min()) if not prev2.empty else None
            signals.append(_make_signal(row, "side_switch", 4, pivot, atm, candle_range, base_low, vix_status, vix_reason))

    return sorted(signals, key=lambda s: (s.priority, s.distance_from_pivot, abs(s.strike_distance), s.option_type))


def _exit_trade(signal: Signal, future: pd.DataFrame, config: dict[str, Any]) -> Trade:
    strat = config["strategy"]
    c2c_trigger = float(strat.get("c2c_trigger", 20))
    trailing_trigger = float(strat.get("trailing_trigger", 40))
    squareoff_time = _parse_time(strat.get("squareoff_time", "15:25"))

    c2c = False
    trailing = False
    trailing_sl: float | None = None
    max_fav = 0.0

    if future.empty:
        return Trade(
            entry_time=signal.datetime,
            exit_time=signal.datetime,
            date=signal.date,
            expiry_date=signal.expiry_date,
            strike=signal.strike,
            option_type=signal.option_type,
            setup=signal.setup,
            entry_price=signal.entry_price,
            exit_price=signal.entry_price,
            pnl=0.0,
            exit_reason="NO_FUTURE_CANDLES",
            pivot=signal.pivot,
            max_favorable_points=0.0,
            c2c_activated=False,
            trailing_activated=False,
            strike_distance=signal.strike_distance,
            candle_range=signal.candle_range,
            stop_level=signal.stop_level,
            vix_status=signal.vix_status,
            vix_reason=signal.vix_reason,
        )

    last_row = future.iloc[-1]
    for _, row in future.iterrows():
        high_profit = float(row["high"] - signal.entry_price)
        max_fav = max(max_fav, high_profit)
        if high_profit >= c2c_trigger:
            c2c = True
        if high_profit >= trailing_trigger:
            trailing = True

        close = float(row["close"])
        base_stop_hit = signal.stop_level is not None and close < float(signal.stop_level)
        pivot_stop_hit = close < signal.pivot and signal.setup != "continuation_base_breakout"
        if pivot_stop_hit or base_stop_hit:
            exit_price = float(row["close"])
            reason = "BASE_LOW_SL" if base_stop_hit and not pivot_stop_hit else "PIVOT_CLOSE_SL"
            return _make_trade(signal, row, exit_price, reason, max_fav, c2c, trailing)
        c2c_exit_mode = strat.get("c2c_exit_mode", "touch")
        c2c_hit = (
            float(row["close"]) <= signal.entry_price
            if c2c_exit_mode == "close_below_entry"
            else float(row["low"]) <= signal.entry_price
        )
        if c2c and c2c_hit:
            return _make_trade(signal, row, signal.entry_price, "C2C", max_fav, c2c, trailing)
        if trailing and trailing_sl is not None and float(row["low"]) <= trailing_sl:
            return _make_trade(signal, row, trailing_sl, "TRAILING_SL", max_fav, c2c, trailing)
        if row["time"] >= squareoff_time:
            return _make_trade(signal, row, float(row["close"]), "SQUAREOFF", max_fav, c2c, trailing)

        if trailing:
            trailing_sl = max(trailing_sl or signal.entry_price, float(row["low"]))

    return _make_trade(signal, last_row, float(last_row["close"]), "END_OF_DATA", max_fav, c2c, trailing)


def _make_trade(signal: Signal, row: pd.Series, exit_price: float, reason: str, max_fav: float, c2c: bool, trailing: bool) -> Trade:
    return Trade(
        entry_time=signal.datetime,
        exit_time=row["datetime"],
        date=signal.date,
        expiry_date=signal.expiry_date,
        strike=signal.strike,
        option_type=signal.option_type,
        setup=signal.setup,
        entry_price=round(signal.entry_price, 2),
        exit_price=round(float(exit_price), 2),
        pnl=round(float(exit_price - signal.entry_price), 2),
        exit_reason=reason,
        pivot=round(signal.pivot, 2),
        max_favorable_points=round(max_fav, 2),
        c2c_activated=c2c,
        trailing_activated=trailing,
        strike_distance=signal.strike_distance,
        candle_range=round(signal.candle_range, 2),
        stop_level=round(signal.stop_level, 2) if signal.stop_level is not None else None,
        vix_status=signal.vix_status,
        vix_reason=signal.vix_reason,
    )


def run_backtest(config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    data_cfg = config["data"]
    market = load_market_data(data_cfg["options_dir"], data_cfg["spot_dir"], int(data_cfg.get("candle_minutes", 5)))
    return run_backtest_with_market(config, market.options, market.spot, list(market.warnings))


def run_backtest_with_market(
    config: dict[str, Any], options_raw: pd.DataFrame, spot: pd.DataFrame, warnings: list[str] | None = None
) -> tuple[pd.DataFrame, list[str]]:
    options = add_indicators(options_raw, int(config["strategy"].get("ema_period", 20)))
    vix = _load_vix(config)
    warnings = list(warnings or [])
    trades: list[Trade] = []

    start_time = _parse_time(config["strategy"].get("trade_start_time", "09:15"))
    end_time = _parse_time(config["strategy"].get("trade_end_time", "15:25"))

    for date, day_options in options.groupby("date", sort=True):
        day_spot = spot.loc[spot["date"] == date]
        context = build_daily_context(day_options, day_spot, config)
        if context is None:
            warnings.append(f"{date}: skipped because 09:15 spot/options or CE/PE pivot pair is missing.")
            continue

        active_until = None
        daily_pnl = 0.0
        daily_pivot_sl_count = 0
        state: dict[str, Any] = {
            "side_counts": {"CE": 0, "PE": 0},
            "side_switches": 0,
            "last_exit_time": None,
            "last_exit_side": None,
            "last_exit_reason": None,
        }
        tradable = day_options[
            (day_options["time"] >= start_time)
            & (day_options["time"] <= end_time)
            & (day_options["strike"].isin(context["strikes"]))
        ].sort_values("datetime")

        for timestamp, candle_rows in tradable.groupby("datetime", sort=True):
            if active_until is not None and timestamp <= active_until:
                continue
            candle_time = candle_rows.iloc[0]["time"]
            if _blocked_entry_time(candle_time, config):
                continue
            if _daily_guard_hit(daily_pnl, daily_pivot_sl_count, config):
                continue
            if config["strategy"].get("version") == "3.2.2":
                signals = _v322_signals(timestamp, candle_rows, tradable, context, config, state, vix)
            else:
                signals = find_signals(candle_rows, context, config)
            if not signals:
                continue
            signal = signals[0]
            future = tradable[
                (tradable["datetime"] > signal.datetime)
                & (tradable["strike"] == signal.strike)
                & (tradable["option_type"] == signal.option_type)
                & (tradable["expiry_date"] == signal.expiry_date)
            ].sort_values("datetime")
            trade = _exit_trade(signal, future, config)
            trades.append(trade)
            daily_pnl += trade.pnl
            if trade.exit_reason in {"PIVOT_CLOSE_SL", "BASE_LOW_SL"}:
                daily_pivot_sl_count += 1
            if config["strategy"].get("version") == "3.2.2":
                previous_side = state.get("last_exit_side")
                if previous_side is not None and previous_side != trade.option_type and trade.setup == "side_switch":
                    state["side_switches"] += 1
                state["side_counts"][trade.option_type] = state["side_counts"].get(trade.option_type, 0) + 1
                state["last_exit_time"] = trade.exit_time
                state["last_exit_side"] = trade.option_type
                state["last_exit_reason"] = trade.exit_reason
            active_until = trade.exit_time

    trade_df = pd.DataFrame([asdict(t) for t in trades])
    return trade_df, warnings


def write_trades(trades: pd.DataFrame, output_dir: str | Path) -> Path:
    path = Path(output_dir) / "trades" / "all_trades.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(path, index=False)
    return path


def run_and_write(config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    trades, warnings = run_backtest(config)
    write_trades(trades, config["data"].get("output_dir", "output"))
    return trades, warnings
