"""Phase 2: FRED Treasury yields -> daily changes in basis points + curve measures + data-quality report."""
from pathlib import Path

import pandas as pd

import provenance
from config import TENORS, FED_TARGET
from data_loader import get_fred

BP_PER_PCT = 100  # 1 percentage point = 100 basis points


def pct_to_bp(x):
    """Convert yields/changes quoted in % to basis points (0.01% = 1 bp)."""
    return x * BP_PER_PCT


def load_yield_levels(start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (levels on trading days, raw levels incl. NaN rows) for 2Y/5Y/10Y/30Y in %.

    Intuition: FRED stores Treasury-market holidays as NaN. We DROP those rows
    (never forward-fill): a filled value would fake a 0 bp 'move' on a day the
    market was shut and dilute the normal-day baseline.
    """
    raw = pd.concat({t: get_fred(sid, start, end) for t, sid in TENORS.items()}, axis=1)
    for t, sid in TENORS.items():
        provenance.record(f"FRED {sid} ({t} CMT yield)", f"{raw[t].notna().sum()} non-NaN daily obs {start}..{end}",
                          f"https://fred.stlouisfed.org/series/{sid}", "fredapi Fred.get_series, cached in data/raw/")
    return raw.dropna(how="any"), raw


def bp_changes(levels: pd.DataFrame) -> pd.DataFrame:
    """Daily yield changes in bp for each tenor plus 2s10s and 5s30s spread changes.

    Intuition: a spread change is just the difference of the two legs' changes,
    e.g. Δ2s10s = Δ10Y − Δ2Y. Positive = steepening, negative = flattening.
    The first row has no previous day, so it is dropped.
    """
    lv = pct_to_bp(levels)
    lv["2s10s"] = lv["10Y"] - lv["2Y"]
    lv["5s30s"] = lv["30Y"] - lv["5Y"]
    return lv.diff().dropna().round(6)


def curve_levels(levels: pd.DataFrame) -> pd.DataFrame:
    """2s10s and 5s30s spread LEVELS in bp (negative = inverted curve)."""
    lv = pct_to_bp(levels)
    return pd.DataFrame({"2s10s": lv["10Y"] - lv["2Y"], "5s30s": lv["30Y"] - lv["5Y"]})


def load_fed_target(start: str, end: str) -> pd.Series:
    """Fed funds target upper bound (%), daily, NaN dropped."""
    s = get_fred(FED_TARGET, start, end).dropna()
    provenance.record(f"FRED {FED_TARGET} (Fed funds target upper bound)",
                      f"{len(s)} obs; {s.iloc[0]:.2f}% -> {s.iloc[-1]:.2f}%",
                      f"https://fred.stlouisfed.org/series/{FED_TARGET}", "fredapi Fred.get_series")
    return s


def data_quality_report(raw: pd.DataFrame, changes: pd.DataFrame, fed: pd.Series, path: str) -> str:
    """Write a markdown data-quality report and return it as text.

    Intuition: before any statistics, prove the data is sane — how many days were
    dropped and why, and whether the biggest moves sit on dates you can explain.
    """
    nan_rows = raw[raw.isna().any(axis=1)]
    partial = raw.isna().any(axis=1) & raw.notna().any(axis=1)
    lines = ["# Data-quality report (FRED yields)", "",
             f"- Calendar rows downloaded: {len(raw)}; trading days kept: {len(raw) - len(nan_rows)}; "
             f"NaN rows dropped (Treasury-market holidays): {len(nan_rows)}",
             f"- Partial-NaN rows (some tenors missing): {int(partial.sum())}",
             f"- Daily-change observations: {len(changes)} ({changes.index[0].date()} .. {changes.index[-1].date()})",
             "", "## Dropped dates", ", ".join(d.strftime("%Y-%m-%d") for d in nan_rows.index), "",
             "## Daily change statistics (bp)", changes.describe().round(2).to_markdown(), "",
             "## Largest absolute daily moves (bp)"]
    for c in changes.columns:
        top = changes[c].abs().nlargest(3)
        lines.append(f"- {c}: " + "; ".join(f"{d.date()} {changes.at[d, c]:+.0f}" for d in top.index))
    steps = fed.diff()
    steps = steps[steps != 0].dropna()
    lines += ["", "## Fed funds target upper bound changes (DFEDTARU)",
              f"{len(steps)} changes: " + "; ".join(f"{d.date()} {v*100:+.0f}bp" for d, v in steps.items())]
    text = "\n".join(lines) + "\n"
    Path(path).parent.mkdir(exist_ok=True, parents=True)
    Path(path).write_text(text, encoding="utf-8")
    return text
