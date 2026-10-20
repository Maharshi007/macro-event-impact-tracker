"""Phase 4: load the official event calendar, map events to trading days and tag every day."""
import numpy as np
import pandas as pd

EVENT_TYPES = ("CPI", "FOMC")


def load_events(path: str = "data/events.csv", verified_only: bool = True) -> pd.DataFrame:
    """Read events.csv; keep CPI/FOMC rows (and only verified ones by default)."""
    ev = pd.read_csv(path, parse_dates=["date"])
    ev = ev[ev["event"].isin(EVENT_TYPES)]
    if verified_only and "verified" in ev:
        ev = ev[ev["verified"].astype(bool)]
    return ev.reset_index(drop=True)


def map_to_trading_day(event_dates, trading_index: pd.DatetimeIndex) -> pd.Series:
    """Map each event date to the same or next available trading day.

    Intuition: searchsorted binary-searches where the date would be inserted in the
    sorted trading calendar -> the index of the first trading day >= the date.
    Events after the last trading day are dropped.
    """
    dates = pd.to_datetime(pd.Series(event_dates)).values
    pos = trading_index.searchsorted(dates)
    pos = pos[pos < len(trading_index)]
    return pd.Series(trading_index[pos])


def tag_days(index: pd.DatetimeIndex, events: pd.DataFrame) -> pd.Series:
    """Label every trading day CPI, FOMC, BOTH or NORMAL.

    Intuition: set membership per event type; a day in both sets is BOTH and is
    later excluded so one day's move is never attributed to two events.
    """
    cpi = set(map_to_trading_day(events.loc[events.event == "CPI", "date"], index))
    fomc = set(map_to_trading_day(events.loc[events.event == "FOMC", "date"], index))
    labels = np.where([d in cpi and d in fomc for d in index], "BOTH",
                      np.where([d in cpi for d in index], "CPI",
                               np.where([d in fomc for d in index], "FOMC", "NORMAL")))
    return pd.Series(labels, index=index, name="tag")


def shift_tags(tags: pd.Series, k: int) -> pd.Series:
    """Placebo tags: move every CPI/FOMC label k trading days later (positional shift).

    Intuition: if the effect is truly caused by the release, the same number of
    'fake' event days 10 sessions later should look like normal days (IR ~ 1).
    Placebo days that land on a real event day are dropped (labelled EXCLUDED),
    and real event days are never used as the normal baseline.
    """
    out = pd.Series("NORMAL", index=tags.index, name="tag")
    real_event = tags.isin(["CPI", "FOMC", "BOTH"]).values
    out[real_event] = "EXCLUDED"
    for ev in EVENT_TYPES:
        pos = np.where(tags.values == ev)[0] + k
        pos = pos[pos < len(tags)]
        pos = pos[~real_event[pos]]
        out.iloc[pos] = ev
    return out
