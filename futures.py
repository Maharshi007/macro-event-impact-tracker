"""Phase 7: Treasury futures — roll-artifact detection, empirical DV01, $ per contract; ZQ money-markets module."""
import numpy as np
import pandas as pd
import statsmodels.api as sm

import provenance
from config import CONTRACT_SPECS, FED_FUNDS_FUTURE, FUTURES, ROLL_RESID_Z
from data_loader import get_futures


def load_futures_on(index: pd.DatetimeIndex, start: str, end: str, tickers=None) -> pd.DataFrame:
    """Futures closes re-indexed onto the FRED trading calendar, then usable for differencing.

    Intuition: futures trade on some bond-market holidays (e.g. Columbus Day).
    Differencing on the futures calendar would compare a different pair of days
    than the FRED yield change, so we first keep only FRED trading days.
    """
    tickers = tickers or list(FUTURES.values())
    closes = {}
    for t in tickers:
        df = get_futures(t, start, end)
        c = df["Close"].dropna()
        closes[t] = c
        provenance.record(f"yfinance {t} daily close", f"{len(c)} rows {c.index.min().date()}..{c.index.max().date()}",
                          f"https://finance.yahoo.com/quote/{t}", "yfinance.download, cached in data/raw/")
    return pd.concat(closes, axis=1).reindex(index)


def in_roll_window(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Two boolean roll-window masks per date.

    prompt_window : day>=20 of Feb/May/Aug/Nov or day<=5 of Mar/Jun/Sep/Dec (the
                    usual liquidity roll before first notice day).
    expiry_window : day>=15 of Mar/Jun/Sep/Dec or day<=5 of Jan/Apr/Jul/Oct —
                    where Yahoo's continuous series actually switches contract
                    (it rolls at expiry; seen in the residuals, see notes).
    """
    m, d = dates.month, dates.day
    prompt = (np.isin(m, [2, 5, 8, 11]) & (d >= 20)) | (np.isin(m, [3, 6, 9, 12]) & (d <= 5))
    expiry = (np.isin(m, [3, 6, 9, 12]) & (d >= 15)) | (np.isin(m, [1, 4, 7, 10]) & (d <= 5))
    return pd.DataFrame({"prompt_window": prompt, "expiry_window": expiry}, index=dates)


def robust_z(x: pd.Series) -> pd.Series:
    """(x − median) / (1.4826·MAD): a z-score that big outliers cannot inflate."""
    med = x.median()
    mad = (x - med).abs().median()
    return (x - med) / (1.4826 * mad)


def detect_roll_artifacts(dprice: pd.Series, dyield_bp: pd.Series, z_thresh: float = ROLL_RESID_Z) -> pd.DataFrame:
    """Flag days inside roll windows whose futures move is inconsistent with the yield move.

    Intuition: normally Δprice ≈ β·Δyield. On a contract switch the price jumps by
    the calendar spread while the yield does not, leaving a huge residual.
    Steps: OLS on all days -> robust z of residuals -> flag |z| > threshold inside
    a roll window. Large residuals OUTSIDE windows are reported, not excluded.
    """
    d = pd.concat([dprice.rename("dp"), dyield_bp.rename("dy")], axis=1).dropna()
    beta = np.polyfit(d.dy, d.dp, 1)
    d["resid"] = d.dp - np.polyval(beta, d.dy)
    d["z"] = robust_z(d.resid)
    w = in_roll_window(d.index)
    d = d.join(w)
    d["in_window"] = d.prompt_window | d.expiry_window
    d["roll_flag"] = d.in_window & (d.z.abs() > z_thresh)
    d["outlier_outside_window"] = ~d.in_window & (d.z.abs() > z_thresh)
    return d


def empirical_dv01(diag: pd.DataFrame) -> dict:
    """Regress Δprice (points) on Δyield (bp) on NON-roll-window days -> points per bp.

    Intuition: the slope is how many price points the contract moves per 1 bp of
    its tenor's yield (negative: yield up, price down). Times $ per point = DV01.
    """
    d = diag[~diag.in_window]
    res = sm.OLS(d.dp, sm.add_constant(d.dy)).fit(cov_type="HC1")
    return {"n_fit": len(d), "points_per_bp": res.params["dy"], "se": res.bse["dy"], "r2": res.rsquared}


def dollars_per_point(ticker: str) -> tuple[float | None, bool]:
    """$ value of a 1.00-point price move = face value / 100 (prices quoted in % of par)."""
    spec = CONTRACT_SPECS[ticker]
    return (spec["face_usd"] / 100 if spec["face_usd"] else None), spec["verified"]


def futures_analysis(changes: pd.DataFrame, tags: pd.Series, surprise: pd.Series, trading_index: pd.DatetimeIndex,
                     start: str, end: str):
    """Run roll detection + DV01 + $-per-contract translation for each tenor.

    Returns (dv01_table, dollar_table, roll_report dict, diagnostics dict).
    """
    closes = load_futures_on(trading_index, start, end)
    dv_rows, usd_rows, roll_rep, diags = [], [], {}, {}
    for tenor, t in FUTURES.items():
        c = closes[t]
        dp = c.diff().reindex(changes.index)
        diag = detect_roll_artifacts(dp, changes[tenor])
        diags[t] = diag
        fit = empirical_dv01(diag)
        usd_pt, verified = dollars_per_point(t)
        dv01 = -fit["points_per_bp"] * usd_pt if usd_pt else np.nan
        flagged = diag.index[diag.roll_flag]
        roll_rep[t] = {"n_days": len(diag), "n_in_window": int(diag.in_window.sum()),
                       "n_flagged": len(flagged),
                       "n_flagged_prompt_window": int((diag.roll_flag & diag.prompt_window).sum()),
                       "n_flagged_expiry_window": int((diag.roll_flag & diag.expiry_window).sum()),
                       "flagged_dates": [d.strftime("%Y-%m-%d") for d in flagged],
                       "flagged_event_days": [f"{d.date()} {tags.get(d)}" for d in flagged if tags.get(d) != "NORMAL"],
                       "outliers_outside_window": [d.strftime("%Y-%m-%d") for d in diag.index[diag.outlier_outside_window]]}
        dv_rows.append({"tenor": tenor, "ticker": t, "n_fit": fit["n_fit"], "points_per_bp": fit["points_per_bp"],
                        "points_per_bp_se": fit["se"], "r2": fit["r2"], "usd_per_point": usd_pt,
                        "dv01_usd_per_contract": dv01, "contract_spec_verified": verified,
                        "n_roll_flagged_excluded": len(flagged)})
        ok = ~diag.roll_flag
        for ev in ["CPI", "FOMC", "NORMAL"]:
            mask = (tags == ev).reindex(diag.index) & ok
            mean_bp = changes.loc[mask[mask].index, tenor].abs().mean()
            mean_pts = diag.loc[mask, "dp"].abs().mean()
            usd_rows.append({"tenor": tenor, "ticker": t, "group": ev, "n": int(mask.sum()),
                             "mean_abs_yield_bp": mean_bp, "dv01_usd": dv01,
                             "usd_per_contract_via_dv01": mean_bp * dv01,
                             "mean_abs_futures_points": mean_pts,
                             "usd_per_contract_direct": mean_pts * usd_pt if usd_pt else np.nan,
                             "contract_spec_verified": verified})
        for b in ["hawkish", "dovish"]:
            mask = (surprise == b).reindex(diag.index).fillna(False).astype(bool) & ok
            mean_bp = changes.loc[mask[mask].index, tenor].mean()
            usd_rows.append({"tenor": tenor, "ticker": t, "group": f"{b} (signed, long 1 contract)", "n": int(mask.sum()),
                             "mean_abs_yield_bp": mean_bp, "dv01_usd": dv01,
                             "usd_per_contract_via_dv01": -mean_bp * dv01,
                             "mean_abs_futures_points": diag.loc[mask, "dp"].mean(),
                             "usd_per_contract_direct": diag.loc[mask, "dp"].mean() * usd_pt if usd_pt else np.nan,
                             "contract_spec_verified": verified})
    usd = pd.DataFrame(usd_rows).rename(columns={"mean_abs_yield_bp": "mean_yield_bp (abs, or signed for hawkish/dovish)",
                                                 "mean_abs_futures_points": "mean_futures_points (abs, or signed)"})
    return pd.DataFrame(dv_rows), usd, roll_rep, diags


def fed_funds_module(changes: pd.DataFrame, tags: pd.Series, trading_index: pd.DatetimeIndex, start: str, end: str) -> tuple[pd.DataFrame | None, dict]:
    """ZQ=F implied rate (100 − price) changes on FOMC days vs normal days.

    Intuition: a 30-day fed funds future settles on the month's AVERAGE effective
    fed funds rate, so 100 − price = the market's expected average rate. The
    front-month contract switches on the first trading day of each month, so those
    days are excluded as roll days.
    """
    try:
        z = load_futures_on(trading_index, start, end, [FED_FUNDS_FUTURE])[FED_FUNDS_FUTURE]
    except Exception as exc:  # noqa: BLE001
        return None, {"available": False, "reason": str(exc)}
    if z.dropna().empty:
        return None, {"available": False, "reason": "no data"}
    implied = 100 - z
    d = (implied.diff() * 100).reindex(changes.index).rename("d_implied_bp")
    idx = changes.index
    first_of_month = pd.Series(idx.to_period("M"), index=idx).ne(pd.Series(idx.to_period("M"), index=idx).shift())
    df = pd.DataFrame({"d_implied_bp": d, "d2y_bp": changes["2Y"], "tag": tags, "roll_day": first_of_month.values})
    ok = df[~df.roll_day].dropna()
    fomc, normal = ok[ok.tag == "FOMC"], ok[ok.tag == "NORMAL"]
    summary = {"available": True, "n_fomc": len(fomc), "n_normal": len(normal),
               "n_fomc_dropped_roll_day": int(((df.tag == "FOMC") & df.roll_day).sum()),
               "mean_abs_fomc_bp": fomc.d_implied_bp.abs().mean(), "mean_abs_normal_bp": normal.d_implied_bp.abs().mean(),
               "ir": fomc.d_implied_bp.abs().mean() / normal.d_implied_bp.abs().mean(),
               "corr_with_d2y_fomc": fomc[["d_implied_bp", "d2y_bp"]].corr().iloc[0, 1],
               "max_fomc_move": (fomc.d_implied_bp.abs().idxmax().date(), fomc.d_implied_bp.loc[fomc.d_implied_bp.abs().idxmax()])}
    return df, summary
