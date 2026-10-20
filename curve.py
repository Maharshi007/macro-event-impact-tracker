"""Phase 6b: curve-shape classification, market-implied surprise, CPI first print, signed moves, beta, regimes."""
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import mannwhitneyu, pearsonr, spearmanr

from analysis import MEASURES, impact_ratio

SHAPES = ["bear steepener", "bear flattener", "bull steepener", "bull flattener", "parallel/unchanged", "twist (no level move)"]


def classify_shape(d2: float, d10: float) -> str:
    """Classify a day's curve move from the 2Y and 10Y changes (bp).

    Intuition: two questions. (1) Did yields go up or down overall?
    level = Δ2Y + Δ10Y > 0 -> BEAR (prices fall), < 0 -> BULL.
    (2) Did 2s10s widen or narrow? Δ2s10s = Δ10Y − Δ2Y > 0 -> STEEPENER, < 0 -> FLATTENER.
    E.g. 2Y +23, 10Y +11: level +34 (bear), Δ2s10s −12 (flattener) -> bear flattener.
    Δ2s10s = 0 -> parallel/unchanged; level = 0 with a slope change -> twist.
    """
    slope, level = d10 - d2, d2 + d10
    if slope == 0:
        return "parallel/unchanged"
    if level == 0:
        return "twist (no level move)"
    return f"{'bear' if level > 0 else 'bull'} {'steepener' if slope > 0 else 'flattener'}"


def shape_series(changes: pd.DataFrame) -> pd.Series:
    """Apply classify_shape to every day."""
    return pd.Series([classify_shape(a, b) for a, b in zip(changes["2Y"], changes["10Y"])],
                     index=changes.index, name="shape")


def surprise_buckets(changes: pd.DataFrame, tags: pd.Series) -> pd.Series:
    """Hawkish / neutral / dovish label per event day from terciles of that event type's Δ2Y.

    Intuition: the 2Y yield is the market's real-time read of the expected policy
    path, so a big Δ2Y on the release day = a big surprise vs what was priced.
    Terciles are computed separately for CPI and FOMC; ties are broken by order
    (rank 'first') so the three groups are equal-sized.
    """
    out = pd.Series(index=tags.index, dtype=object, name="surprise")
    for ev in ["CPI", "FOMC"]:
        d2 = changes.loc[tags == ev, "2Y"]
        if len(d2) < 3:
            continue
        b = pd.qcut(d2.rank(method="first"), 3, labels=["dovish", "neutral", "hawkish"])
        out.loc[b.index] = b.astype(str)
    return out


def shape_table(shapes: pd.Series, tags: pd.Series, surprise: pd.Series) -> pd.DataFrame:
    """Counts and % of each curve shape for CPI, FOMC, NORMAL and the hawkish/dovish event groups."""
    groups = {"CPI": tags == "CPI", "FOMC": tags == "FOMC", "NORMAL": tags == "NORMAL",
              "hawkish (CPI+FOMC)": surprise == "hawkish", "dovish (CPI+FOMC)": surprise == "dovish"}
    rows = []
    for g, mask in groups.items():
        s = shapes[mask]
        vc = s.value_counts()
        for sh in SHAPES:
            rows.append({"group": g, "shape": sh, "count": int(vc.get(sh, 0)), "n": len(s),
                         "pct": 100 * vc.get(sh, 0) / len(s) if len(s) else np.nan})
    return pd.DataFrame(rows)


def signed_moves(changes: pd.DataFrame, tags: pd.Series, surprise: pd.Series) -> pd.DataFrame:
    """Average signed bp move per measure for each (event, surprise bucket), with n.

    Intuition: |Δ| tells you HOW MUCH; the sign tells you WHICH WAY — e.g. on
    hawkish days do 10Y yields rise less than 2Y (flattening)?
    """
    rows = []
    for ev in ["CPI", "FOMC", "ALL"]:
        evmask = tags.isin(["CPI", "FOMC"]) if ev == "ALL" else tags == ev
        for b in ["hawkish", "neutral", "dovish"]:
            mask = evmask & (surprise == b)
            r = {"event": ev, "surprise": b, "n": int(mask.sum())}
            r.update({f"mean_{m}_bp": changes.loc[mask, m].mean() for m in MEASURES})
            rows.append(r)
    return pd.DataFrame(rows)


def beta_10y_on_2y(changes: pd.DataFrame, tags: pd.Series) -> pd.DataFrame:
    """OLS Δ10Y = a + β·Δ2Y for CPI, FOMC and NORMAL days (HC1 robust SEs).

    Intuition: β < 1 means the 10Y moves LESS than the 2Y -> a hawkish (2Y up)
    shock flattens 2s10s and a dovish one steepens it; β > 1 the opposite.
    """
    rows = []
    for g in ["CPI", "FOMC", "NORMAL"]:
        d = changes[tags == g]
        res = sm.OLS(d["10Y"], sm.add_constant(d["2Y"])).fit(cov_type="HC1")
        b, se = res.params["2Y"], res.bse["2Y"]
        rows.append({"group": g, "n": len(d), "beta": b, "beta_se": se,
                     "beta_ci_low": b - 1.96 * se, "beta_ci_high": b + 1.96 * se,
                     "p_beta_eq_1": float(res.t_test("2Y = 1").pvalue), "r2": res.rsquared})
    return pd.DataFrame(rows)


def cpi_first_print_mom(alfred: pd.DataFrame) -> pd.DataFrame:
    """Month-on-month CPI % change exactly as first printed, with its release date.

    Intuition: for reference month t, take the ALFRED vintage released on t's
    first-publication day and compute value_t / value_{t-1} − 1 WITHIN that
    vintage — the same numbers BLS printed in that release (later revisions
    excluded). If month t−1 was never published (Oct 2025), MoM is NaN.
    """
    a = alfred.dropna(subset=["value"]).sort_values("realtime_start")
    first = a.groupby("date")["realtime_start"].min()
    rows = []
    for t, rel in first.items():
        prev = t - pd.DateOffset(months=1)
        cur_v = a[(a.date == t) & (a.realtime_start == rel)]["value"]
        prev_v = a[(a.date == prev) & (a.realtime_start <= rel)].sort_values("realtime_start")["value"]
        mom = (cur_v.iloc[0] / prev_v.iloc[-1] - 1) * 100 if len(prev_v) and len(cur_v) else np.nan
        rows.append({"reference_month": t, "release_date": rel, "mom_first_print_pct": mom})
    return pd.DataFrame(rows)


def cpi_print_vs_2y(first_print: pd.DataFrame, changes: pd.DataFrame, tags: pd.Series) -> tuple[pd.DataFrame, dict]:
    """Join first-print MoM CPI to the release-day Δ2Y; Pearson & Spearman correlation."""
    cpi_days = changes.index[tags.isin(["CPI", "BOTH"])]
    fp = first_print.copy()
    pos = changes.index.searchsorted(fp.release_date)
    fp = fp[pos < len(changes)]
    fp["trading_day"] = changes.index[pos[pos < len(changes)]]
    fp = fp[fp.trading_day.isin(cpi_days)].dropna(subset=["mom_first_print_pct"])
    fp["d2y_bp"] = changes.loc[fp.trading_day, "2Y"].values
    pr, pp = pearsonr(fp.mom_first_print_pct, fp.d2y_bp)
    sr, sp = spearmanr(fp.mom_first_print_pct, fp.d2y_bp)
    return fp, {"n": len(fp), "pearson_r": pr, "pearson_p": pp, "spearman_rho": sr, "spearman_p": sp}


def regime_split(changes: pd.DataFrame, tags: pd.Series, year: int, measures=MEASURES) -> pd.DataFrame:
    """Impact ratios in `year` vs all other years, each against its own regime's normal days.

    Intuition: 2022 was a high-vol hiking cycle, so normal days were also wilder;
    comparing each regime's events to its OWN baseline isolates the event effect.
    mw_p_event_abs tests whether event-day |Δ| itself was larger in `year`.
    """
    rows = []
    absd = changes[measures].abs()
    in_reg = changes.index.year == year
    for ev in ["CPI", "FOMC"]:
        for m in measures:
            r = {"event": ev, "measure": m}
            for lab, mask in [(str(year), in_reg), ("other", ~in_reg)]:
                e = absd.loc[(tags == ev) & mask, m]
                n = absd.loc[(tags == "NORMAL") & mask, m]
                r.update({f"n_event_{lab}": len(e), f"mean_abs_event_{lab}": e.mean(),
                          f"mean_abs_normal_{lab}": n.mean(), f"ir_{lab}": impact_ratio(e, n)})
            r["mw_p_event_abs"] = mannwhitneyu(absd.loc[(tags == ev) & in_reg, m],
                                               absd.loc[(tags == ev) & ~in_reg, m],
                                               alternative="two-sided").pvalue
            rows.append(r)
    return pd.DataFrame(rows)
