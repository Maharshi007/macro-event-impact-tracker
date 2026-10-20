"""Phase 5: impact ratios, Welch t-test, Mann-Whitney U, Bonferroni, placebo."""
import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu, ttest_ind

from config import ALPHA

MEASURES = ["2Y", "5Y", "10Y", "30Y", "2s10s", "5s30s"]


def impact_ratio(event_abs: np.ndarray, normal_abs: np.ndarray) -> float:
    """Mean |Δ| on event days divided by mean |Δ| on normal days (1 = no effect)."""
    return float(np.mean(event_abs) / np.mean(normal_abs))


def impact_table(changes: pd.DataFrame, tags: pd.Series, measures=MEASURES, alpha: float = ALPHA) -> pd.DataFrame:
    """Impact table for every (event, measure): means, IR, std, Welch & MWU one-sided p, Bonferroni flags.

    Intuition: compare like with like — mean |bp| vs mean |bp|. The tests ask
    "are event-day absolute moves larger?" (one-sided). With m tests run together,
    Bonferroni demands p < alpha/m so the chance of ANY false positive stays <= alpha.
    """
    rows = []
    absd = changes[measures].abs()
    normal = absd[tags == "NORMAL"]
    for ev in ["CPI", "FOMC"]:
        evd = absd[tags == ev]
        for m in measures:
            e, n = evd[m].values, normal[m].values
            rows.append({
                "event": ev, "measure": m, "n_event": len(e), "n_normal": len(n),
                "mean_abs_event_bp": e.mean(), "mean_abs_normal_bp": n.mean(),
                "impact_ratio": impact_ratio(e, n),
                "std_event_bp": changes.loc[tags == ev, m].std(),
                "std_normal_bp": changes.loc[tags == "NORMAL", m].std(),
                "welch_p": ttest_ind(e, n, equal_var=False, alternative="greater").pvalue,
                "mannwhitney_p": mannwhitneyu(e, n, alternative="greater").pvalue,
            })
    t = pd.DataFrame(rows)
    m_tests = len(t)
    t["bonferroni_alpha"] = alpha / m_tests
    t["welch_sig_raw"] = t.welch_p < alpha
    t["welch_sig_bonf"] = t.welch_p < alpha / m_tests
    t["mw_sig_bonf"] = t.mannwhitney_p < alpha / m_tests
    return t


def placebo_comparison(real: pd.DataFrame, placebo: pd.DataFrame) -> pd.DataFrame:
    """Side-by-side real vs placebo impact ratios per (event, measure)."""
    k = ["event", "measure"]
    return real[k + ["n_event", "impact_ratio", "welch_p"]].merge(
        placebo[k + ["n_event", "impact_ratio", "welch_p"]], on=k, suffixes=("_real", "_placebo"))
