from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from .loader import (
        PROJECT_ROOT,
        PairedSession,
        build_paired_sessions,
        extract_zip,
        load_option_sessions,
    )
except ImportError:
    from loader import (
        PROJECT_ROOT,
        PairedSession,
        build_paired_sessions,
        extract_zip,
        load_option_sessions,
    )


ENTRY_START_TIME = "09:20"
MIN_CONTRACT_CLOSE = 120.0
MAX_ENTRY_ABOVE_PIVOT = 20.0
HARD_SL_POINTS = 15.0
COST_SL_TRIGGER = 20.0
TSL_TRIGGER = 40.0
TSL_CLOSE_OFFSET = 20.0
MAX_LOSING_TRADES_PER_DAY = 3
DAILY_STOP_LOSS = -50.0
ANTI_CHASE_MAX_ENTRY_CANDLE_RANGE = 15.0
CSV_FLOAT_FORMAT = "%.2f"


@dataclass(frozen=True)
class Trade:
    trade_date: str
    strike: int
    side: str
    entry_setup: str
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    pnl: float
    exit_reason: str
    pivot: float
    mfe: float
    mae: float
    plus20_hit: bool
    plus40_hit: bool
    loss_count_after_trade: int
    daily_pnl_after_trade: float
    entry_ema20: float
    entry_above_ema20: bool
    distance_from_ema20: float
    previous_candle_touched_ema20: bool
    current_candle_touched_ema20: bool
    entry_candle_color: str
    entry_near_ema20_5pts: bool
    entry_near_ema20_10pts: bool
    entry_near_ema20_15pts: bool
    entry_candle_high: float
    entry_candle_low: float
    entry_candle_range: float
    anti_chase_pass: bool


@dataclass(frozen=True)
class SkippedAntiChase:
    date: str
    symbol: str
    side: str
    entry_time: str
    entry_price: float
    entry_candle_high: float
    entry_candle_low: float
    entry_candle_range: float
    reason: str


@dataclass(frozen=True)
class VacuumDiagnostic:
    trade_date: str
    side: str
    strike: int
    datetime: str
    close: float
    pivot: float
    ema20: float
    previous_close: float | None
    previous_ema20: float | None
    entry_candle_color: str
    entry_candle_range: float
    close_above_pivot: bool
    close_above_ema20: bool
    within_pivot_plus_20: bool
    anti_chase_pass: bool
    green_candle_pass: bool
    cross_pivot_pass: bool
    cross_ema20_pass: bool
    left_space_pass: bool
    rejection_reason: str


@dataclass(frozen=True)
class StrategyConfig:
    name: str = "v2"
    entry_start_time: str = ENTRY_START_TIME
    min_premium: float | None = MIN_CONTRACT_CLOSE
    apply_premium_filter_only_when_pivot_at_least: float | None = None
    max_entry_above_pivot: float = MAX_ENTRY_ABOVE_PIVOT
    hard_sl_points: float = HARD_SL_POINTS
    cost_sl_trigger: float = COST_SL_TRIGGER
    tsl_trigger: float = TSL_TRIGGER
    tsl_close_offset: float = TSL_CLOSE_OFFSET
    max_losing_trades_per_day: int = MAX_LOSING_TRADES_PER_DAY
    daily_stop_loss: float = DAILY_STOP_LOSS
    require_entry_candle_touches_ema20: bool = False
    entry_ema20_quality_gate: bool = False
    entry_ema20_near_points: float = 10.0
    entry_mode: str = "immediate"
    max_entry_candle_range: float | None = ANTI_CHASE_MAX_ENTRY_CANDLE_RANGE
    max_entry_distance_from_ema20: float | None = None
    hard_sl_mode: str = "fixed_points"
    tsl_mode: str = "highest_close_offset"
    enable_vacuum_breakout: bool = False
    ema_period: int = 20
    vacuum_lookback_candles: int = 6
    vacuum_resistance_buffer: float = 5.0
    vacuum_max_entry_candle_range: float | None = 25.0
    vacuum_pivot_sl_buffer: float = 0.0
    require_vacuum_green_candle: bool = True
    require_vacuum_cross_ema20: bool = True
    require_vacuum_cross_pivot: bool = True
    block_side_after_pivot_sl: bool = False
    cooldown_candles_after_pivot_sl: int = 0
    max_pivot_sl_per_day: int | None = None
    max_trades_per_day: int | None = None
    data_dir: str | None = None


@dataclass
class ActiveTrade:
    side: str
    entry_time: pd.Timestamp
    entry_price: float
    hard_sl: float
    highest_close: float
    entry_setup: str = "normal"
    mfe: float = 0.0
    mae: float = 0.0
    plus20_hit: bool = False
    plus40_hit: bool = False
    entry_ema20: float = 0.0
    entry_above_ema20: bool = False
    distance_from_ema20: float = 0.0
    previous_candle_touched_ema20: bool = False
    current_candle_touched_ema20: bool = False
    entry_candle_color: str = "doji"
    entry_near_ema20_5pts: bool = False
    entry_near_ema20_10pts: bool = False
    entry_near_ema20_15pts: bool = False
    entry_candle_high: float = 0.0
    entry_candle_low: float = 0.0
    entry_candle_range: float = 0.0
    anti_chase_pass: bool = True
    pivot: float = 0.0
    current_stop: float = 0.0
    trailing_sl: float | None = None
    last_confirmed_candle_low: float = 0.0


def _trade_date_rows(candles: pd.DataFrame, trade_date: pd.Timestamp) -> pd.DataFrame:
    rows = candles[candles["datetime"].dt.date == trade_date.date()]
    return rows.sort_values("datetime").reset_index(drop=True)


def _timestamp(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _price(value: object) -> float:
    return float(value)


def _candle_touched_ema20(row: pd.Series | None) -> bool:
    if row is None or pd.isna(row["ema20"]):
        return False
    return _price(row["low"]) <= _price(row["ema20"]) <= _price(row["high"])


def _candle_color(row: pd.Series) -> str:
    close = _price(row["close"])
    open_ = _price(row["open"])
    if close > open_:
        return "green"
    if close < open_:
        return "red"
    return "doji"


def _candle_range(row: pd.Series) -> float:
    return _price(row["high"]) - _price(row["low"])


def _anti_chase_passes(row: pd.Series, config: StrategyConfig) -> bool:
    if config.max_entry_candle_range is None:
        return True
    return _candle_range(row) <= config.max_entry_candle_range


def _vacuum_range_passes(row: pd.Series, config: StrategyConfig) -> bool:
    max_range = config.vacuum_max_entry_candle_range
    if max_range is None:
        max_range = config.max_entry_candle_range
    if max_range is None:
        return True
    return _candle_range(row) <= max_range


def _active_stop(trade: ActiveTrade, config: StrategyConfig) -> float:
    if config.hard_sl_mode == "pivot_close":
        stops = [trade.current_stop]
        if trade.plus20_hit:
            stops.append(trade.entry_price)
        if trade.plus40_hit and trade.trailing_sl is not None:
            stops.append(trade.trailing_sl)
        return max(stops)

    stops = [trade.hard_sl]
    if trade.plus20_hit:
        stops.append(trade.entry_price)
    if trade.plus40_hit:
        stops.append(trade.highest_close - config.tsl_close_offset)
    return max(stops)


def _make_trade(
    pair: PairedSession,
    active: ActiveTrade,
    exit_time: pd.Timestamp,
    exit_price: float,
    exit_reason: str,
    loss_count: int,
    daily_pnl: float,
) -> Trade:
    pnl = exit_price - active.entry_price
    loss_count_after_trade = loss_count + (1 if pnl < 0 else 0)
    daily_pnl_after_trade = daily_pnl + pnl

    return Trade(
        trade_date=pair.trade_date.date().isoformat(),
        strike=pair.strike,
        side=active.side,
        entry_setup=active.entry_setup,
        entry_time=_timestamp(active.entry_time),
        entry_price=active.entry_price,
        exit_time=_timestamp(exit_time),
        exit_price=exit_price,
        pnl=pnl,
        exit_reason=exit_reason,
        pivot=float(pair.pivot),
        mfe=active.mfe,
        mae=active.mae,
        plus20_hit=active.plus20_hit,
        plus40_hit=active.plus40_hit,
        loss_count_after_trade=loss_count_after_trade,
        daily_pnl_after_trade=daily_pnl_after_trade,
        entry_ema20=active.entry_ema20,
        entry_above_ema20=active.entry_above_ema20,
        distance_from_ema20=active.distance_from_ema20,
        previous_candle_touched_ema20=active.previous_candle_touched_ema20,
        current_candle_touched_ema20=active.current_candle_touched_ema20,
        entry_candle_color=active.entry_candle_color,
        entry_near_ema20_5pts=active.entry_near_ema20_5pts,
        entry_near_ema20_10pts=active.entry_near_ema20_10pts,
        entry_near_ema20_15pts=active.entry_near_ema20_15pts,
        entry_candle_high=active.entry_candle_high,
        entry_candle_low=active.entry_candle_low,
        entry_candle_range=active.entry_candle_range,
        anti_chase_pass=active.anti_chase_pass,
    )


def _premium_filter_passes(close: float, pivot: float, config: StrategyConfig) -> bool:
    if config.min_premium is None:
        return True
    if (
        config.apply_premium_filter_only_when_pivot_at_least is not None
        and pivot < config.apply_premium_filter_only_when_pivot_at_least
    ):
        return True
    return close >= config.min_premium


def _ema20_distance_passes(row: pd.Series, config: StrategyConfig) -> bool:
    if config.max_entry_distance_from_ema20 is None:
        return True
    distance_from_ema20 = _price(row["close"]) - _price(row["ema20"])
    return distance_from_ema20 <= config.max_entry_distance_from_ema20


def _ema20_quality_gate_passes(
    row: pd.Series,
    previous_row: pd.Series | None,
    config: StrategyConfig,
) -> bool:
    if not config.entry_ema20_quality_gate:
        return True
    distance_from_ema20 = _price(row["close"]) - _price(row["ema20"])
    return (
        _candle_touched_ema20(row)
        or _candle_touched_ema20(previous_row)
        or abs(distance_from_ema20) <= config.entry_ema20_near_points
    )


def _entry_candidate_before_anti_chase(
    row: pd.Series,
    pivot: float,
    config: StrategyConfig,
    previous_row: pd.Series | None = None,
) -> bool:
    close = _price(row["close"])
    return (
        _premium_filter_passes(close, pivot, config)
        and close > pivot
        and close <= pivot + config.max_entry_above_pivot
        and _ema20_distance_passes(row, config)
        and _ema20_quality_gate_passes(row, previous_row, config)
        and (
            not config.require_entry_candle_touches_ema20
            or _candle_touched_ema20(row)
        )
    )


def _entry_candidate(
    row: pd.Series,
    pivot: float,
    config: StrategyConfig,
    previous_row: pd.Series | None = None,
) -> bool:
    return _entry_candidate_before_anti_chase(
        row,
        pivot,
        config,
        previous_row,
    ) and _anti_chase_passes(
        row,
        config,
    )


def _breakout_candidate(row: pd.Series, pivot: float) -> bool:
    return _price(row["close"]) > pivot


def _retest_entry_candidate_before_anti_chase(
    row: pd.Series,
    pivot: float,
    config: StrategyConfig,
    previous_row: pd.Series | None = None,
) -> bool:
    return (
        _entry_candidate_before_anti_chase(row, pivot, config, previous_row)
        and _price(row["low"]) <= pivot <= _price(row["high"])
    )


def _retest_entry_candidate(
    row: pd.Series,
    pivot: float,
    config: StrategyConfig,
    previous_row: pd.Series | None = None,
) -> bool:
    return _retest_entry_candidate_before_anti_chase(
        row,
        pivot,
        config,
        previous_row,
    ) and _anti_chase_passes(row, config)


def _evaluate_vacuum_breakout(
    history_rows: list[pd.Series],
    row: pd.Series,
    previous_row: pd.Series | None,
    pivot: float,
    config: StrategyConfig,
) -> dict[str, object]:
    close = _price(row["close"])
    ema20 = _price(row["ema20"])
    previous_close = _price(previous_row["close"]) if previous_row is not None else None
    previous_ema20 = _price(previous_row["ema20"]) if previous_row is not None else None
    entry_candle_color = _candle_color(row)
    entry_candle_range = _candle_range(row)
    lookback = max(config.vacuum_lookback_candles, 0)
    resistance_level = close - config.vacuum_resistance_buffer
    left_space_pass = not any(
        _price(history_row["high"]) >= resistance_level
        for history_row in (history_rows[-lookback:] if lookback else [])
    )

    close_above_pivot = close > pivot
    close_above_ema20 = close > ema20
    within_pivot_plus_20 = close <= pivot + config.max_entry_above_pivot
    ema20_distance_pass = _ema20_distance_passes(row, config)
    ema20_quality_gate_pass = _ema20_quality_gate_passes(row, previous_row, config)
    anti_chase_pass = _vacuum_range_passes(row, config)
    green_candle_pass = (
        not config.require_vacuum_green_candle or entry_candle_color == "green"
    )
    cross_pivot_pass = (
        previous_close is not None
        and (not config.require_vacuum_cross_pivot or previous_close <= pivot)
    )
    cross_ema20_pass = (
        True
        if not config.require_vacuum_cross_ema20
        else (
            previous_close is not None
            and previous_ema20 is not None
            and previous_close <= previous_ema20
        )
    )

    rejection_reason = "accepted"
    if not within_pivot_plus_20:
        rejection_reason = "outside_pivot_plus_20"
    elif not close_above_ema20:
        rejection_reason = "not_above_ema20"
    elif not ema20_distance_pass:
        rejection_reason = "entry_distance_from_ema20_gt_limit"
    elif not ema20_quality_gate_pass:
        rejection_reason = "entry_ema20_quality_gate_failed"
    elif not anti_chase_pass:
        rejection_reason = "entry_candle_range_gt_limit"
    elif not green_candle_pass:
        rejection_reason = "not_green"
    elif not cross_pivot_pass:
        rejection_reason = "not_cross_pivot"
    elif not cross_ema20_pass:
        rejection_reason = "not_cross_ema20"
    elif not left_space_pass:
        rejection_reason = "left_resistance_nearby"

    accepted = (
        config.enable_vacuum_breakout
        and close_above_pivot
        and close_above_ema20
        and within_pivot_plus_20
        and ema20_distance_pass
        and ema20_quality_gate_pass
        and anti_chase_pass
        and green_candle_pass
        and cross_pivot_pass
        and cross_ema20_pass
        and left_space_pass
    )

    return {
        "accepted": accepted,
        "close": close,
        "pivot": pivot,
        "ema20": ema20,
        "previous_close": previous_close,
        "previous_ema20": previous_ema20,
        "entry_candle_color": entry_candle_color,
        "entry_candle_range": entry_candle_range,
        "close_above_pivot": close_above_pivot,
        "close_above_ema20": close_above_ema20,
        "within_pivot_plus_20": within_pivot_plus_20,
        "anti_chase_pass": anti_chase_pass,
        "green_candle_pass": green_candle_pass,
        "cross_pivot_pass": cross_pivot_pass,
        "cross_ema20_pass": cross_ema20_pass,
        "left_space_pass": left_space_pass,
        "rejection_reason": "accepted" if accepted else rejection_reason,
    }


def _vacuum_breakout_candidate(
    history_rows: list[pd.Series],
    row: pd.Series,
    previous_row: pd.Series | None,
    pivot: float,
    config: StrategyConfig,
) -> bool:
    return bool(
        _evaluate_vacuum_breakout(
            history_rows,
            row,
            previous_row,
            pivot,
            config,
        )["accepted"]
    )


def _vacuum_diagnostic(
    pair: PairedSession,
    side: str,
    row: pd.Series,
    previous_row: pd.Series | None,
    history_rows: list[pd.Series],
    pivot: float,
    config: StrategyConfig,
) -> VacuumDiagnostic:
    evaluation = _evaluate_vacuum_breakout(
        history_rows,
        row,
        previous_row,
        pivot,
        config,
    )
    return VacuumDiagnostic(
        trade_date=pair.trade_date.date().isoformat(),
        side=side,
        strike=pair.strike,
        datetime=_timestamp(row["datetime"]),
        close=float(evaluation["close"]),
        pivot=float(evaluation["pivot"]),
        ema20=float(evaluation["ema20"]),
        previous_close=evaluation["previous_close"],
        previous_ema20=evaluation["previous_ema20"],
        entry_candle_color=str(evaluation["entry_candle_color"]),
        entry_candle_range=float(evaluation["entry_candle_range"]),
        close_above_pivot=bool(evaluation["close_above_pivot"]),
        close_above_ema20=bool(evaluation["close_above_ema20"]),
        within_pivot_plus_20=bool(evaluation["within_pivot_plus_20"]),
        anti_chase_pass=bool(evaluation["anti_chase_pass"]),
        green_candle_pass=bool(evaluation["green_candle_pass"]),
        cross_pivot_pass=bool(evaluation["cross_pivot_pass"]),
        cross_ema20_pass=bool(evaluation["cross_ema20_pass"]),
        left_space_pass=bool(evaluation["left_space_pass"]),
        rejection_reason=str(evaluation["rejection_reason"]),
    )


def _symbol(pair: PairedSession, side: str) -> str:
    return f"NIFTY_{pair.trade_date.date().isoformat()}_{pair.strike}{side}"


def _skipped_anti_chase(
    pair: PairedSession,
    side: str,
    row: pd.Series,
) -> SkippedAntiChase:
    entry_price = _price(row["close"])
    high = _price(row["high"])
    low = _price(row["low"])
    candle_range = high - low
    return SkippedAntiChase(
        date=pair.trade_date.date().isoformat(),
        symbol=_symbol(pair, side),
        side=side,
        entry_time=_timestamp(row["datetime"]),
        entry_price=entry_price,
        entry_candle_high=high,
        entry_candle_low=low,
        entry_candle_range=candle_range,
        reason="entry_candle_range_gt_15",
    )


def _new_active_trade(
    side: str,
    row: pd.Series,
    previous_row: pd.Series | None,
    config: StrategyConfig,
    pivot: float,
    entry_setup: str = "normal",
) -> ActiveTrade:
    entry_price = _price(row["close"])
    entry_time = row["datetime"]
    entry_ema20 = _price(row["ema20"])
    distance_from_ema20 = entry_price - entry_ema20
    entry_candle_high = _price(row["high"])
    entry_candle_low = _price(row["low"])
    entry_candle_range = entry_candle_high - entry_candle_low
    hard_sl = pivot if config.hard_sl_mode == "pivot_close" else entry_price - config.hard_sl_points
    return ActiveTrade(
        side=side,
        entry_time=entry_time,
        entry_price=entry_price,
        hard_sl=hard_sl,
        highest_close=entry_price,
        entry_setup=entry_setup,
        entry_ema20=entry_ema20,
        entry_above_ema20=entry_price > entry_ema20,
        distance_from_ema20=distance_from_ema20,
        previous_candle_touched_ema20=_candle_touched_ema20(previous_row),
        current_candle_touched_ema20=_candle_touched_ema20(row),
        entry_candle_color=_candle_color(row),
        entry_near_ema20_5pts=abs(distance_from_ema20) <= 5,
        entry_near_ema20_10pts=abs(distance_from_ema20) <= 10,
        entry_near_ema20_15pts=abs(distance_from_ema20) <= 15,
        entry_candle_high=entry_candle_high,
        entry_candle_low=entry_candle_low,
        entry_candle_range=entry_candle_range,
        anti_chase_pass=_anti_chase_passes(row, config),
        pivot=pivot,
        current_stop=hard_sl,
        trailing_sl=None,
        last_confirmed_candle_low=entry_candle_low,
    )


def _update_active_trade(active: ActiveTrade, row: pd.Series, config: StrategyConfig) -> None:
    high = _price(row["high"])
    low = _price(row["low"])
    close = _price(row["close"])
    previous_confirmed_low = active.last_confirmed_candle_low

    active.mfe = max(active.mfe, high - active.entry_price)
    active.mae = min(active.mae, low - active.entry_price)
    active.highest_close = max(active.highest_close, close)

    if high >= active.entry_price + config.cost_sl_trigger:
        active.plus20_hit = True
    if high >= active.entry_price + config.tsl_trigger:
        active.plus40_hit = True
    if active.plus40_hit and config.tsl_mode == "candle_low":
        if active.trailing_sl is None:
            active.trailing_sl = max(previous_confirmed_low, low)
        else:
            active.trailing_sl = max(active.trailing_sl, previous_confirmed_low, low)

    active.current_stop = _active_stop(active, config)
    active.last_confirmed_candle_low = low


def _exit_signal(
    active: ActiveTrade,
    row: pd.Series,
    config: StrategyConfig,
) -> tuple[bool, str]:
    close = _price(row["close"])

    if config.hard_sl_mode == "pivot_close":
        if active.plus40_hit and active.trailing_sl is not None:
            effective_stop = max(active.entry_price, active.trailing_sl)
            if close <= effective_stop:
                if active.trailing_sl >= active.entry_price:
                    return True, "tsl_candle_low"
                return True, "cost_to_cost"
        if active.plus20_hit and close <= active.entry_price:
            return True, "cost_to_cost"
        if (
            not active.plus20_hit
            and active.entry_setup == "vacuum_breakout"
            and close < active.pivot - config.vacuum_pivot_sl_buffer
        ):
            return True, "vacuum_pivot_buffer_sl"
        if (
            not active.plus20_hit
            and active.entry_setup != "vacuum_breakout"
            and close < active.pivot
        ):
            return True, "pivot_close_sl"
        return False, ""

    stop = _active_stop(active, config)
    if close <= stop:
        return True, "stop"
    return False, ""


def _exit_price(
    active: ActiveTrade,
    close: float,
    exit_reason: str,
    config: StrategyConfig,
) -> float:
    if config.hard_sl_mode != "pivot_close":
        return close
    if exit_reason == "cost_to_cost":
        return active.entry_price
    if exit_reason == "tsl_candle_low":
        if active.trailing_sl is None:
            return active.entry_price
        return max(active.entry_price, active.trailing_sl)
    return close


def run_strategy_for_pair(
    pair: PairedSession,
    config: StrategyConfig | None = None,
    skipped_anti_chase: list[SkippedAntiChase] | None = None,
    vacuum_diagnostics: list[VacuumDiagnostic] | None = None,
) -> list[Trade]:
    config = config or StrategyConfig()
    if pair.pivot is None or pd.isna(pair.pivot):
        return []

    pivot = float(pair.pivot)
    ce_rows = _trade_date_rows(pair.ce, pair.trade_date)
    pe_rows = _trade_date_rows(pair.pe, pair.trade_date)

    by_time: dict[pd.Timestamp, dict[str, pd.Series]] = {}
    previous_by_time: dict[pd.Timestamp, dict[str, pd.Series | None]] = {}
    history_by_time: dict[pd.Timestamp, dict[str, list[pd.Series]]] = {}
    for side, rows in (("CE", ce_rows), ("PE", pe_rows)):
        previous_row: pd.Series | None = None
        history_rows: list[pd.Series] = []
        for _, row in rows.iterrows():
            by_time.setdefault(row["datetime"], {})[side] = row
            previous_by_time.setdefault(row["datetime"], {})[side] = previous_row
            history_by_time.setdefault(row["datetime"], {})[side] = list(history_rows)
            history_rows.append(row)
            previous_row = row

    trades: list[Trade] = []
    active: ActiveTrade | None = None
    loss_count = 0
    trade_count = 0
    daily_pnl = 0.0
    stop_trading = False
    last_row_by_side: dict[str, pd.Series] = {}
    breakout_seen = {"CE": False, "PE": False}
    blocked_sides = {"CE": False, "PE": False}
    cooldown_candles = {"CE": 0, "PE": 0}

    for candle_time in sorted(by_time):
        side_rows = by_time[candle_time]
        last_row_by_side.update(side_rows)

        if config.enable_vacuum_breakout and vacuum_diagnostics is not None:
            for side, row in side_rows.items():
                close = _price(row["close"])
                if close > pivot and close <= pivot + config.max_entry_above_pivot:
                    previous_row = previous_by_time.get(row["datetime"], {}).get(side)
                    history_rows = history_by_time.get(row["datetime"], {}).get(side, [])
                    vacuum_diagnostics.append(
                        _vacuum_diagnostic(
                            pair,
                            side,
                            row,
                            previous_row,
                            history_rows,
                            pivot,
                            config,
                        )
                    )

        if active is not None:
            active_row = side_rows.get(active.side)
            if active_row is not None and candle_time > active.entry_time:
                _update_active_trade(active, active_row, config)
                should_exit, exit_reason = _exit_signal(active, active_row, config)
                close = _price(active_row["close"])
                if should_exit:
                    trade = _make_trade(
                        pair=pair,
                        active=active,
                        exit_time=candle_time,
                        exit_price=_exit_price(active, close, exit_reason, config),
                        exit_reason=exit_reason,
                        loss_count=loss_count,
                        daily_pnl=daily_pnl,
                    )
                    trades.append(trade)
                    loss_count = trade.loss_count_after_trade
                    daily_pnl = trade.daily_pnl_after_trade
                    if config.block_side_after_pivot_sl and exit_reason == "pivot_close_sl":
                        blocked_sides[active.side] = True
                    if exit_reason == "pivot_close_sl" and config.cooldown_candles_after_pivot_sl > 0:
                        cooldown_candles[active.side] = config.cooldown_candles_after_pivot_sl
                    active = None
                    stop_trading = (
                        loss_count >= config.max_losing_trades_per_day
                        or daily_pnl <= config.daily_stop_loss
                    )
                    continue

        if active is not None or stop_trading:
            continue
        if (
            config.max_trades_per_day is not None
            and trade_count >= config.max_trades_per_day
        ):
            continue
        if candle_time.strftime("%H:%M") < config.entry_start_time:
            continue

        candidates = []
        for side in ("CE", "PE"):
            row = side_rows.get(side)
            if row is None:
                continue
            if blocked_sides[side]:
                continue
            if cooldown_candles[side] > 0:
                cooldown_candles[side] -= 1
                continue
            previous_row = previous_by_time.get(row["datetime"], {}).get(side)
            history_rows = history_by_time.get(row["datetime"], {}).get(side, [])
            if config.entry_mode == "retest_only":
                if breakout_seen[side] and _retest_entry_candidate(
                    row,
                    pivot,
                    config,
                    previous_row,
                ):
                    candidates.append((row["datetime"], side, row, "normal"))
                elif (
                    breakout_seen[side]
                    and _retest_entry_candidate_before_anti_chase(
                        row,
                        pivot,
                        config,
                        previous_row,
                    )
                    and not _anti_chase_passes(row, config)
                ):
                    if skipped_anti_chase is not None:
                        skipped_anti_chase.append(_skipped_anti_chase(pair, side, row))
                elif not breakout_seen[side] and _breakout_candidate(row, pivot):
                    breakout_seen[side] = True
            elif config.entry_mode == "retest_or_breakout":
                if _vacuum_breakout_candidate(
                    history_rows,
                    row,
                    previous_row,
                    pivot,
                    config,
                ):
                    candidates.append((row["datetime"], side, row, "vacuum_breakout"))
                elif _retest_entry_candidate(row, pivot, config, previous_row):
                    candidates.append((row["datetime"], side, row, "normal"))
                elif _entry_candidate(row, pivot, config, previous_row):
                    candidates.append((row["datetime"], side, row, "normal"))
                elif (
                    _entry_candidate_before_anti_chase(
                        row,
                        pivot,
                        config,
                        previous_row,
                    )
                    and not _anti_chase_passes(row, config)
                ):
                    if skipped_anti_chase is not None:
                        skipped_anti_chase.append(_skipped_anti_chase(pair, side, row))
            elif _entry_candidate(row, pivot, config, previous_row):
                candidates.append((row["datetime"], side, row, "normal"))
            elif (
                _entry_candidate_before_anti_chase(
                    row,
                    pivot,
                    config,
                    previous_row,
                )
                and not _anti_chase_passes(row, config)
            ):
                if skipped_anti_chase is not None:
                    skipped_anti_chase.append(_skipped_anti_chase(pair, side, row))

        if candidates:
            _, side, row, entry_setup = sorted(
                candidates,
                key=lambda item: (item[0], item[1]),
            )[0]
            previous_row = previous_by_time.get(row["datetime"], {}).get(side)
            active = _new_active_trade(
                side,
                row,
                previous_row,
                config,
                pivot,
                entry_setup,
            )
            trade_count += 1
            breakout_seen = {"CE": False, "PE": False}

    if active is not None:
        exit_row = last_row_by_side.get(active.side)
        if exit_row is not None:
            if exit_row["datetime"] > active.entry_time:
                _update_active_trade(active, exit_row, config)
            trade = _make_trade(
                pair=pair,
                active=active,
                exit_time=exit_row["datetime"],
                exit_price=_price(exit_row["close"]),
                exit_reason="end_of_day",
                loss_count=loss_count,
                daily_pnl=daily_pnl,
            )
            trades.append(trade)

    return trades


def run_strategy_for_pairs(
    pairs: list[PairedSession],
    config: StrategyConfig | None = None,
    skipped_anti_chase: list[SkippedAntiChase] | None = None,
    vacuum_diagnostics: list[VacuumDiagnostic] | None = None,
) -> list[Trade]:
    trades: list[Trade] = []
    for pair in pairs:
        trades.extend(
            run_strategy_for_pair(
                pair,
                config=config,
                skipped_anti_chase=skipped_anti_chase,
                vacuum_diagnostics=vacuum_diagnostics,
            )
        )
    return trades


def trades_to_dataframe(trades: list[Trade]) -> pd.DataFrame:
    return pd.DataFrame([asdict(trade) for trade in trades])


def skipped_anti_chase_to_dataframe(skipped: list[SkippedAntiChase]) -> pd.DataFrame:
    return pd.DataFrame([asdict(row) for row in skipped])


def vacuum_diagnostics_to_dataframe(
    diagnostics: list[VacuumDiagnostic],
) -> pd.DataFrame:
    return pd.DataFrame([asdict(row) for row in diagnostics])


def _parse_scalar(raw_value: str) -> Any:
    value = raw_value.strip()
    lowered = value.lower()
    if lowered in {"null", "none", "~"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def load_strategy_config(path: str | Path) -> StrategyConfig:
    config_path = Path(path)
    values: dict[str, Any] = {}

    for line_number, line in enumerate(config_path.read_text().splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "#" in stripped:
            stripped = stripped.split("#", 1)[0].strip()
        if ":" not in stripped:
            raise ValueError(f"{config_path}:{line_number}: expected 'key: value'")

        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"{config_path}:{line_number}: empty config key")
        values[key] = _parse_scalar(raw_value)

    return StrategyConfig(**values)


def main() -> None:
    extract_dir = extract_zip()
    sessions = load_option_sessions(extract_dir)
    pairs = build_paired_sessions(sessions)
    trades = run_strategy_for_pairs(pairs)
    trades_df = trades_to_dataframe(trades)

    output_path = Path(PROJECT_ROOT) / "output" / "trades.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    trades_df.to_csv(output_path, index=False, float_format=CSV_FLOAT_FORMAT)

    if trades_df.empty:
        print("No trades generated.")
    else:
        print(trades_df.to_string(index=False))
    print(f"\nSaved trades to {output_path}")


if __name__ == "__main__":
    main()
