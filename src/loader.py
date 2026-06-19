from __future__ import annotations

import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ZIP_PATH = PROJECT_ROOT / "data" / "Jun.zip"
EXTRACT_DIR = PROJECT_ROOT / "data" / "Jun_extracted"
SESSION_OPEN_TIME = "09:15"


@dataclass(frozen=True)
class OptionFile:
    path: Path
    trade_date: pd.Timestamp
    strike: int
    option_type: str


@dataclass(frozen=True)
class PairedSession:
    trade_date: pd.Timestamp
    strike: int
    ce: pd.DataFrame
    pe: pd.DataFrame
    ce_0915_open: float | None
    pe_0915_open: float | None
    pivot: float | None
    ce_ema9_0915: float | None
    ce_ema20_0915: float | None
    pe_ema9_0915: float | None
    pe_ema20_0915: float | None


def extract_zip(zip_path: Path = ZIP_PATH, extract_dir: Path = EXTRACT_DIR) -> Path:
    if not zip_path.exists():
        raise FileNotFoundError(f"Input zip not found: {zip_path}")

    if extract_dir.exists():
        shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(extract_dir)

    return extract_dir


def parse_option_file(path: Path) -> OptionFile | None:
    match = re.search(
        r"_(\d{4}-\d{2}-\d{2})_(\d+)(CE|PE)(?:_|\.|$)",
        path.name,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    return OptionFile(
        path=path,
        trade_date=pd.Timestamp(match.group(1)),
        strike=int(match.group(2)),
        option_type=match.group(3).upper(),
    )


def _clean_column_name(column: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(column).strip().lower())


def _find_column(columns: dict[str, str], candidates: set[str]) -> str | None:
    for normalized, original in columns.items():
        if normalized in candidates:
            return original
    return None


def _parse_datetime(raw: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(raw, errors="coerce", format="mixed")

    if getattr(parsed.dt, "tz", None) is not None:
        return parsed.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)

    return parsed


def normalize_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    columns = {_clean_column_name(column): column for column in df.columns}

    datetime_col = _find_column(
        columns,
        {"datetime", "date", "time", "timestamp", "candle_time", "candletime"},
    )
    date_col = _find_column(columns, {"date"})
    time_col = _find_column(columns, {"time"})

    if date_col and time_col and date_col != time_col:
        raw_datetime = df[date_col].astype(str).str.strip() + " " + df[time_col].astype(str).str.strip()
    elif datetime_col:
        raw_datetime = df[datetime_col]
    else:
        raise ValueError(f"{path.name}: could not find a datetime/date/time column")

    normalized = pd.DataFrame()
    normalized["datetime"] = _parse_datetime(raw_datetime)

    for target in ("open", "high", "low", "close"):
        source = _find_column(columns, {target})
        if source is None:
            raise ValueError(f"{path.name}: missing required column '{target}'")
        normalized[target] = pd.to_numeric(df[source], errors="coerce")

    normalized = normalized.dropna(subset=["datetime", "open", "high", "low", "close"])
    return normalized.sort_values("datetime").reset_index(drop=True)


def add_indicators(candles: pd.DataFrame) -> pd.DataFrame:
    candles = candles.copy()
    candles["ema9"] = candles["close"].ewm(span=9, adjust=False).mean()
    candles["ema20"] = candles["close"].ewm(span=20, adjust=False).mean()
    return candles


def load_option_sessions(extract_dir: Path) -> dict[tuple[pd.Timestamp, int, str], pd.DataFrame]:
    sessions: dict[tuple[pd.Timestamp, int, str], pd.DataFrame] = {}

    for csv_path in sorted(extract_dir.rglob("*.csv")):
        option_file = parse_option_file(csv_path)
        if option_file is None:
            print(f"Skipping unrecognized filename: {csv_path.name}")
            continue

        candles = add_indicators(normalize_csv(csv_path))
        key = (option_file.trade_date, option_file.strike, option_file.option_type)
        if key in sessions:
            candles = pd.concat([sessions[key], candles], ignore_index=True)
            candles = candles.drop_duplicates(subset=["datetime"], keep="first")
            candles = candles.sort_values("datetime").reset_index(drop=True)
            candles = add_indicators(candles.drop(columns=["ema9", "ema20"]))
        sessions[key] = candles

    return sessions


def _trade_date_rows(session: pd.DataFrame, trade_date: pd.Timestamp) -> pd.DataFrame:
    return session[session["datetime"].dt.date == trade_date.date()]


def _row_at_0915(session: pd.DataFrame, trade_date: pd.Timestamp) -> pd.Series | None:
    trade_rows = _trade_date_rows(session, trade_date)
    rows = trade_rows[trade_rows["datetime"].dt.strftime("%H:%M") == SESSION_OPEN_TIME]
    if rows.empty:
        return None
    return rows.iloc[0]


def _value(row: pd.Series | None, column: str) -> float | None:
    if row is None:
        return None
    value = row[column]
    if pd.isna(value):
        return None
    return float(value)


def build_paired_sessions(
    sessions: dict[tuple[pd.Timestamp, int, str], pd.DataFrame],
) -> list[PairedSession]:
    grouped: dict[tuple[pd.Timestamp, int], dict[str, pd.DataFrame]] = {}
    for (trade_date, strike, option_type), session in sessions.items():
        grouped.setdefault((trade_date, strike), {})[option_type] = session

    paired_sessions: list[PairedSession] = []
    for (trade_date, strike), legs in sorted(grouped.items()):
        ce_session = legs.get("CE")
        pe_session = legs.get("PE")
        if ce_session is None or pe_session is None:
            continue

        ce_0915 = _row_at_0915(ce_session, trade_date)
        pe_0915 = _row_at_0915(pe_session, trade_date)
        ce_0915_open = _value(ce_0915, "open")
        pe_0915_open = _value(pe_0915, "open")
        pivot = None
        if ce_0915_open is not None and pe_0915_open is not None:
            pivot = (ce_0915_open + pe_0915_open) / 2

        paired_sessions.append(
            PairedSession(
                trade_date=trade_date,
                strike=strike,
                ce=ce_session,
                pe=pe_session,
                ce_0915_open=ce_0915_open,
                pe_0915_open=pe_0915_open,
                pivot=pivot,
                ce_ema9_0915=_value(ce_0915, "ema9"),
                ce_ema20_0915=_value(ce_0915, "ema20"),
                pe_ema9_0915=_value(pe_0915, "ema9"),
                pe_ema20_0915=_value(pe_0915, "ema20"),
            )
        )

    return paired_sessions


def build_paired_summary(sessions: dict[tuple[pd.Timestamp, int, str], pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for paired in build_paired_sessions(sessions):
        rows.append(
            {
                "trade_date": paired.trade_date.date().isoformat(),
                "strike": paired.strike,
                "ce_total_rows": len(paired.ce),
                "pe_total_rows": len(paired.pe),
                "ce_trade_date_rows": len(_trade_date_rows(paired.ce, paired.trade_date)),
                "pe_trade_date_rows": len(_trade_date_rows(paired.pe, paired.trade_date)),
                "ce_0915_open": paired.ce_0915_open,
                "pe_0915_open": paired.pe_0915_open,
                "pivot": paired.pivot,
                "ce_ema9_0915": paired.ce_ema9_0915,
                "ce_ema20_0915": paired.ce_ema20_0915,
                "pe_ema9_0915": paired.pe_ema9_0915,
                "pe_ema20_0915": paired.pe_ema20_0915,
            }
        )

    return pd.DataFrame(
        rows,
        columns=[
            "trade_date",
            "strike",
            "ce_total_rows",
            "pe_total_rows",
            "ce_trade_date_rows",
            "pe_trade_date_rows",
            "ce_0915_open",
            "pe_0915_open",
            "pivot",
            "ce_ema9_0915",
            "ce_ema20_0915",
            "pe_ema9_0915",
            "pe_ema20_0915",
        ],
    )


def main() -> None:
    extract_dir = extract_zip()
    sessions = load_option_sessions(extract_dir)
    summary = build_paired_summary(sessions)

    if summary.empty:
        print("No paired CE/PE sessions found.")
        return

    output_path = PROJECT_ROOT / "output" / "session_summary.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_path, index=False)
    print(summary.to_string(index=False))
    print(f"\nSaved summary to {output_path}")


if __name__ == "__main__":
    main()
