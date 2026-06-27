from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


class DataValidationError(ValueError):
    """Raised when input market data cannot support a valid backtest."""


@dataclass(frozen=True)
class MarketData:
    options: pd.DataFrame
    spot: pd.DataFrame
    warnings: list[str]


COLUMN_ALIASES = {
    "datetime": {
        "datetime", "date_time", "timestamp", "time_stamp", "date time",
        "time", "dt", "candle_time",
    },
    "date": {"date", "trading_date", "trade_date"},
    "time": {"time", "candle_time"},
    "open": {"open", "o", "open_price", "open price"},
    "high": {"high", "h", "high_price", "high price"},
    "low": {"low", "l", "low_price", "low price"},
    "close": {"close", "c", "ltp", "close_price", "close price"},
    "strike": {"strike", "strike_price", "strike price", "strik price"},
    "option_type": {"option_type", "option type", "type", "instrument_type", "right", "ce_pe"},
}


def _clean_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(name).strip().lower()).strip()


def _column_map(columns: Iterable[str]) -> dict[str, str]:
    cleaned = {_clean_name(c): c for c in columns}
    result: dict[str, str] = {}
    for target, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in cleaned:
                result[target] = cleaned[alias]
                break
    return result


def _read_csv(path: Path, **kwargs) -> pd.DataFrame:
    try:
        return pd.read_csv(path, **kwargs)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="latin1", **kwargs)


def _parse_filename(path: Path) -> tuple[int | None, str | None, object | None]:
    stem = path.stem.upper()
    option_type = None
    if re.search(r"(^|[^A-Z])CE([^A-Z]|$)", stem) or stem.endswith("CE"):
        option_type = "CE"
    elif re.search(r"(^|[^A-Z])PE([^A-Z]|$)", stem) or stem.endswith("PE"):
        option_type = "PE"

    strike = None
    match = re.search(r"(?<!\d)(\d{5})(?:\D|$)", stem)
    if match:
        strike = int(match.group(1))

    expiry_date = None
    expiry_match = re.search(r"(\d{4}-\d{2}-\d{2})", stem)
    if expiry_match:
        expiry_date = pd.to_datetime(expiry_match.group(1), errors="coerce").date()
    return strike, option_type, expiry_date


def _normalize_datetime(df: pd.DataFrame, mapping: dict[str, str], path: Path) -> pd.Series:
    if "datetime" in mapping:
        raw = df[mapping["datetime"]]
        dt = pd.to_datetime(raw, errors="coerce")
    elif "date" in mapping and "time" in mapping:
        raw = df[mapping["date"]].astype(str).str.strip() + " " + df[mapping["time"]].astype(str).str.strip()
        dt = pd.to_datetime(raw, errors="coerce")
    elif "date" in mapping:
        raw = df[mapping["date"]]
        dt = pd.to_datetime(raw, errors="coerce")
        if dt.isna().all():
            cleaned = raw.astype(str).str.replace(r"\s+GMT([+-]\d{4})\s+\(.+\)$", r" \1", regex=True)
            dt = pd.to_datetime(cleaned, errors="coerce", format="%a %b %d %Y %H:%M:%S %z")
        if not dt.isna().all() and dt.dt.time.nunique(dropna=True) <= 1:
            raise DataValidationError(
                f"{path}: found a date column but no intraday time values. Expected full candle timestamps or separate date/time columns."
            )
    else:
        raise DataValidationError(
            f"{path}: missing datetime column. Expected a datetime/timestamp column or separate date and time columns."
        )
    if dt.isna().all():
        raise DataValidationError(f"{path}: datetime parsing failed for every row.")
    return dt


def _normalize_price_frame(df: pd.DataFrame, path: Path, require_option_fields: bool) -> pd.DataFrame:
    mapping = _column_map(df.columns)
    missing = [c for c in ["open", "high", "low", "close"] if c not in mapping]
    if missing:
        raise DataValidationError(f"{path}: missing required OHLC columns: {missing}. Found: {list(df.columns)}")

    out = pd.DataFrame()
    out["datetime"] = _normalize_datetime(df, mapping, path)
    for col in ["open", "high", "low", "close"]:
        out[col] = pd.to_numeric(df[mapping[col]], errors="coerce")

    if require_option_fields:
        filename_strike, filename_type, filename_expiry = _parse_filename(path)
        if "strike" in mapping:
            out["strike"] = pd.to_numeric(df[mapping["strike"]], errors="coerce")
        elif filename_strike is not None:
            out["strike"] = filename_strike
        else:
            raise DataValidationError(f"{path}: missing strike column and no 5-digit strike found in filename.")

        if "option_type" in mapping:
            out["option_type"] = df[mapping["option_type"]].astype(str).str.upper().str.extract(r"(CE|PE)", expand=False)
        elif filename_type is not None:
            out["option_type"] = filename_type
        else:
            raise DataValidationError(f"{path}: missing option_type column and no CE/PE marker found in filename.")

        out["strike"] = out["strike"].astype("Int64")
        out["expiry_date"] = filename_expiry
        out["source_file"] = path.name

    out = out.dropna(subset=["datetime", "open", "high", "low", "close"])
    out["date"] = out["datetime"].dt.date
    out["time"] = out["datetime"].dt.strftime("%H:%M")
    return out


def load_options(options_dir: str | Path) -> pd.DataFrame:
    root = Path(options_dir)
    if not root.exists():
        raise DataValidationError(f"Options directory does not exist: {root}")
    files = sorted(root.rglob("*.csv"))
    if not files:
        raise DataValidationError(f"No option CSV files found in {root}")
    frames = []
    skipped: list[str] = []
    for path in files:
        filename_strike, filename_type, _ = _parse_filename(path)
        if filename_strike is None or filename_type is None:
            header = _read_csv(path, nrows=0)
            mapping = _column_map(header.columns)
            if "strike" not in mapping or "option_type" not in mapping:
                skipped.append(path.name)
                continue
        frames.append(_normalize_price_frame(_read_csv(path), path, True))
    if not frames:
        skipped_msg = f" Skipped non-option CSVs: {skipped[:5]}" if skipped else ""
        raise DataValidationError(f"No usable option CSV files found in {root}.{skipped_msg}")
    data = pd.concat(frames, ignore_index=True)
    data["option_type"] = data["option_type"].str.upper()
    bad_type = data[~data["option_type"].isin(["CE", "PE"])]
    if not bad_type.empty:
        examples = bad_type[["source_file", "option_type"]].drop_duplicates().head(5).to_dict("records")
        raise DataValidationError(f"Invalid option types found. Expected CE/PE. Examples: {examples}")
    return data.sort_values(["datetime", "strike", "option_type"]).reset_index(drop=True)


def load_spot(spot_dir: str | Path) -> pd.DataFrame:
    root = Path(spot_dir)
    if not root.exists():
        raise DataValidationError(f"NIFTY spot directory does not exist: {root}")
    files = sorted(root.rglob("*.csv"))
    if not files:
        raise DataValidationError(f"No NIFTY spot/index CSV files found in {root}")
    frames = [_normalize_price_frame(_read_csv(path), path, False).assign(source_file=path.name) for path in files]
    return pd.concat(frames, ignore_index=True).sort_values("datetime").reset_index(drop=True)


def validate_market_data(options: pd.DataFrame, spot: pd.DataFrame, candle_minutes: int = 5) -> list[str]:
    warnings: list[str] = []
    spot_915_dates = set(spot.loc[spot["time"] == "09:15", "date"])
    option_915_dates = set(options.loc[options["time"] == "09:15", "date"])
    missing_spot = sorted(set(options["date"]) - spot_915_dates)
    missing_options = sorted(set(spot["date"]) - option_915_dates)
    if missing_spot:
        warnings.append(f"Missing NIFTY 09:15 open for {len(missing_spot)} option dates. Examples: {missing_spot[:5]}")
    if missing_options:
        warnings.append(f"Missing option 09:15 candles for {len(missing_options)} spot dates. Examples: {missing_options[:5]}")

    dupes = options.duplicated(["datetime", "strike", "option_type", "expiry_date"]).sum()
    if dupes:
        warnings.append(f"Found {dupes} duplicate option candles by datetime/strike/type/expiry; keeping first during strategy joins.")

    expected_gap = pd.Timedelta(minutes=candle_minutes)
    for (date, strike, opt_type), group in options.groupby(["date", "strike", "option_type"], sort=False):
        diffs = group.sort_values("datetime")["datetime"].diff().dropna()
        large_gaps = diffs[diffs > expected_gap]
        if not large_gaps.empty:
            warnings.append(f"Missing candles around {date} {strike}{opt_type}; first large gap is {large_gaps.iloc[0]}.")
            if len(warnings) >= 20:
                warnings.append("Additional missing-candle warnings suppressed.")
                break
    return warnings


def load_market_data(options_dir: str | Path, spot_dir: str | Path, candle_minutes: int = 5) -> MarketData:
    options = load_options(options_dir)
    spot = load_spot(spot_dir)
    warnings = validate_market_data(options, spot, candle_minutes)
    return MarketData(options=options, spot=spot, warnings=warnings)
