"""Downloads with a local cache in data/raw/: FRED/ALFRED (fredapi), futures (yfinance), HTML pages."""
import os
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

RAW = Path("data/raw")
RAW.mkdir(parents=True, exist_ok=True)
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def _fred():
    """Build a fredapi client from FRED_API_KEY in .env (never hard-coded)."""
    from fredapi import Fred
    load_dotenv(Path(__file__).with_name(".env"))
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise RuntimeError("FRED_API_KEY missing from .env")
    return Fred(api_key=key)


def get_fred(series_id: str, start: str, end: str) -> pd.Series:
    """Daily FRED series, cached as CSV. NaNs (non-trading days) are kept here; callers drop them.

    Intuition: cache the raw download exactly as received so every later step is
    reproducible offline and the data-quality report can count the NaN days.
    """
    path = RAW / f"fred_{series_id}_{start}_{end}.csv"
    if path.exists():
        s = pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
    else:
        s = _fred().get_series(series_id, observation_start=start, observation_end=end)
        s.to_frame(series_id).to_csv(path)
    s.name = series_id
    s.index.name = "date"
    return s.astype(float)


def get_alfred_all_releases(series_id: str, realtime_start: str = "2020-11-01") -> pd.DataFrame:
    """Every ALFRED vintage of a series: columns realtime_start, date, value (cached).

    Intuition: realtime_start of the first vintage containing month t is the day
    the agency first published month t — i.e. the actual release date.
    """
    path = RAW / f"alfred_{series_id}_from_{realtime_start}.csv"
    if path.exists():
        df = pd.read_csv(path, parse_dates=["realtime_start", "date"])
    else:
        df = _fred().get_series_all_releases(series_id, realtime_start=realtime_start)
        df["realtime_start"] = pd.to_datetime(df["realtime_start"])
        df["date"] = pd.to_datetime(df["date"])
        df.to_csv(path, index=False)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df


def get_futures(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Daily OHLC for a yfinance futures ticker, cached as CSV.

    Intuition: yfinance's `end` is exclusive, so we ask for one extra day.
    """
    import yfinance as yf
    safe = ticker.replace("=", "_")
    path = RAW / f"yf_{safe}_{start}_{end}.csv"
    if path.exists():
        return pd.read_csv(path, index_col=0, parse_dates=True)
    end_excl = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = yf.download(ticker, start=start, end=end_excl, progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.index.name = "date"
    df.to_csv(path)
    return df


def fetch_html(url: str, filename: str) -> str:
    """GET a page once and cache it; raise on HTTP errors (e.g. 403 from bls.gov)."""
    path = RAW / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    r = requests.get(url, headers=_HEADERS, timeout=60)
    r.raise_for_status()
    path.write_text(r.text, encoding="utf-8")
    return r.text
