"""Phase 6a: event window -k..+k trading days."""
import numpy as np
import pandas as pd


def event_window(changes: pd.DataFrame, tags: pd.Series, event: str, k: int = 2, signed: bool = False) -> pd.DataFrame:
    """Mean |Δ bp| (or signed Δ) at each trading-day offset around `event` days.

    Intuition: work in row POSITIONS, not dates, so +1 always means "next trading
    day" and weekends/holidays are handled for free. Offsets falling outside the
    sample are dropped. Rows = offset, columns = measures, plus an n column.
    """
    vals = changes if signed else changes.abs()
    vals = vals.reset_index(drop=True)
    positions = np.where(tags.values == event)[0]
    out, ns = {}, {}
    for off in range(-k, k + 1):
        idx = positions + off
        idx = idx[(idx >= 0) & (idx < len(vals))]
        out[off] = vals.iloc[idx].mean()
        ns[off] = len(idx)
    df = pd.DataFrame(out).T
    df["n"] = pd.Series(ns)
    df.index.name = "offset"
    return df
