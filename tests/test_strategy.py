import pandas as pd

from src.strategy import classify_setup, nearest_atm


def test_nearest_atm_uses_configured_step():
    assert nearest_atm(22476, 50) == 22500
    assert nearest_atm(22474, 50) == 22450


def test_retest_signal_respects_pivot_distance_and_range():
    row = pd.Series({
        "open": 101,
        "high": 110,
        "low": 99,
        "close": 108,
        "prev_close": 98,
        "ema": 100,
    })
    config = {"strategy": {"max_entry_candle_range": 13, "max_entry_distance_from_pivot": 20, "retest_tolerance": 3, "enable_vacuum": True}}
    assert classify_setup(row, 100, config) == "retest_bounce"


def test_anti_chase_rejects_large_range():
    row = pd.Series({
        "open": 100,
        "high": 120,
        "low": 99,
        "close": 110,
        "prev_close": 98,
        "ema": 100,
    })
    config = {"strategy": {"max_entry_candle_range": 13, "max_entry_distance_from_pivot": 20, "retest_tolerance": 3, "enable_vacuum": True}}
    assert classify_setup(row, 100, config) is None
