"""Phase 8: matplotlib PNG charts (static, light surface, validated reference palette)."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Reference categorical palette (fixed order, never cycled) + text/surface tokens.
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
GRAY = "#a8a7a2"
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
EVENT_COLORS = {"CPI": BLUE, "FOMC": ORANGE}
TENOR_COLORS = {"2Y": BLUE, "5Y": ORANGE, "10Y": AQUA, "30Y": YELLOW}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.titleweight": "bold", "axes.titlesize": 12, "font.size": 10, "legend.frameon": False,
})


def _grouped_bars(ax, categories, series: dict, colors: dict, width=0.38, labels_fmt=None, legend=None):
    """Grouped vertical bars with a small surface gap between neighbours; legend maps series -> label."""
    x = np.arange(len(categories))
    k = len(series)
    for i, (name, vals) in enumerate(series.items()):
        pos = x + (i - (k - 1) / 2) * width
        bars = ax.bar(pos, vals, width * 0.92, color=colors[name], label=(legend or {}).get(name, name), edgecolor=SURFACE, linewidth=1)
        if labels_fmt:
            for b, v, lab in zip(bars, vals, labels_fmt(name)):
                ax.annotate(lab, (b.get_x() + b.get_width() / 2, v), xytext=(0, 3 if v >= 0 else -11),
                            textcoords="offset points", ha="center", fontsize=8, color=INK2)
    ax.set_xticks(x, categories)
    lo, hi = ax.get_ylim()
    ax.set_ylim(lo * (1.12 if lo < 0 else 1), hi * 1.15)
    return x


def plot_impact_bars(impact, path):
    """Impact ratio per measure, CPI vs FOMC; '*' = Welch significant after Bonferroni."""
    fig, ax = plt.subplots(figsize=(9, 4.8))
    meas = list(dict.fromkeys(impact.measure))
    series, stars = {}, {}
    for ev in ["CPI", "FOMC"]:
        t = impact[impact.event == ev].set_index("measure").loc[meas]
        series[ev] = t.impact_ratio.values
        stars[ev] = [f"{v:.2f}{'*' if s else ''}" for v, s in zip(t.impact_ratio, t.welch_sig_bonf)]
    n = impact.groupby("event").n_event.first()
    _grouped_bars(ax, meas, series, EVENT_COLORS, labels_fmt=lambda ev: stars[ev],
                  legend={ev: f"{ev} (n={n[ev]})" for ev in n.index})
    ax.axhline(1, ls="--", lw=1, color=INK2)
    ax.set_ylabel("Impact ratio  (mean |Δ bp| event / normal)")
    ax.set_title("Event-day impact on the Treasury curve, 2021–2025")
    ax.legend(loc="upper center", ncol=2)
    ax.text(0, -0.16, "* Welch one-sided p < 0.05/12 (Bonferroni). Dashed line = no effect. Source: FRED DGS2/5/10/30.",
            transform=ax.transAxes, fontsize=8, color=INK2)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def plot_event_window(win, event, path):
    """Mean |Δ bp| at offsets −k..+k for each tenor (2px lines, 8px markers)."""
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for ten, col in TENOR_COLORS.items():
        ax.plot(win.index, win[ten], marker="o", ms=6, lw=2, color=col, label=ten)
    ax.axvline(0, ls="--", lw=1, color=INK2)
    ax.set_xticks(win.index)
    ax.set_xlabel("Trading days relative to event"); ax.set_ylabel("Mean |Δ yield| (bp)")
    ax.set_title(f"{event} days: average absolute yield move around the release (n={int(win['n'].iloc[2])})")
    ax.legend(ncol=4, loc="upper left")
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def plot_curve_shapes(shape_tab, path):
    """Two panels of % frequency by curve shape: CPI/FOMC/NORMAL and hawkish/dovish."""
    shapes = ["bear flattener", "bear steepener", "bull flattener", "bull steepener", "parallel/unchanged"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), sharey=True)
    panels = [(["CPI", "FOMC", "NORMAL"], {"CPI": BLUE, "FOMC": ORANGE, "NORMAL": GRAY}, 0.27),
              (["hawkish (CPI+FOMC)", "dovish (CPI+FOMC)"], {"hawkish (CPI+FOMC)": ORANGE, "dovish (CPI+FOMC)": BLUE}, 0.38)]
    for ax, (groups, cols, w) in zip(axes, panels):
        series, ns = {}, {}
        for g in groups:
            t = shape_tab[shape_tab.group == g].set_index("shape").loc[shapes]
            series[g], ns[g] = t.pct.values, int(t.n.iloc[0])
        _grouped_bars(ax, [s.replace(" ", "\n", 1) for s in shapes], series, cols, width=w)
        ax.legend([f"{g} (n={ns[g]})" for g in groups], loc="upper right")
        ax.set_ylabel("% of days")
    axes[0].set_title("Curve shape on event vs normal days")
    axes[1].set_title("Curve shape by market-implied surprise")
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def plot_signed_moves(signed, path):
    """Average signed bp move per measure on hawkish vs dovish event days (CPI+FOMC)."""
    meas = ["2Y", "5Y", "10Y", "30Y", "2s10s", "5s30s"]
    t = signed[signed.event == "ALL"].set_index("surprise")
    fig, ax = plt.subplots(figsize=(9, 4.8))
    series = {"hawkish": t.loc["hawkish", [f"mean_{m}_bp" for m in meas]].values.astype(float),
              "dovish": t.loc["dovish", [f"mean_{m}_bp" for m in meas]].values.astype(float)}
    _grouped_bars(ax, meas, series, {"hawkish": ORANGE, "dovish": BLUE},
                  labels_fmt=lambda b: [f"{v:+.1f}" for v in series[b]],
                  legend={"hawkish": f"hawkish: top third of event-day Δ2Y (n={int(t.loc['hawkish','n'])})",
                          "dovish": f"dovish: bottom third (n={int(t.loc['dovish','n'])})"})
    ax.axhline(0, lw=1, color=INK2)
    ax.set_ylabel("Average signed change (bp)")
    ax.set_title("Hawkish vs dovish event days: front end moves most, curve flattens / steepens")
    ax.legend(loc="upper right")
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def plot_placebo(plc, path):
    """Real vs placebo (+10 trading days) impact ratios, one panel per event."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), sharey=True)
    for ax, ev in zip(axes, ["CPI", "FOMC"]):
        t = plc[plc.event == ev]
        series = {"real": t.impact_ratio_real.values, "placebo": t.impact_ratio_placebo.values}
        _grouped_bars(ax, list(t.measure), series, {"real": EVENT_COLORS[ev], "placebo": GRAY},
                      labels_fmt=lambda k: [f"{v:.2f}" for v in series[k]],
                      legend={"real": f"real event days (n={int(t.n_event_real.iloc[0])})",
                              "placebo": f"placebo: +10 trading days (n={int(t.n_event_placebo.iloc[0])})"})
        ax.axhline(1, ls="--", lw=1, color=INK2)
        ax.set_title(f"{ev}: real vs placebo impact ratio")
        ax.legend(loc="upper right")
    axes[0].set_ylabel("Impact ratio")
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def plot_dollars(usd, path):
    """Average |$ move| per futures contract on CPI / FOMC / normal days (via empirical DV01)."""
    t = usd[usd.group.isin(["CPI", "FOMC", "NORMAL"])]
    tenors = list(dict.fromkeys(t.tenor))
    labels = [f"{ten}\n{tk}" for ten, tk in dict.fromkeys(zip(t.tenor, t.ticker))]
    series = {g: t[t.group == g].set_index("tenor").loc[tenors, "usd_per_contract_via_dv01"].values for g in ["CPI", "FOMC", "NORMAL"]}
    fig, ax = plt.subplots(figsize=(9, 4.8))
    _grouped_bars(ax, labels, series, {"CPI": BLUE, "FOMC": ORANGE, "NORMAL": GRAY}, width=0.27,
                  labels_fmt=lambda g: [f"${v:,.0f}" for v in series[g]])
    ax.set_ylabel("Mean |$ change| per contract")
    ax.set_title("Average daily move per Treasury futures contract (mean |Δbp| × empirical DV01)")
    ax.legend(loc="upper left")
    ax.text(0, -0.17, "Contract face values from CME spec pages via search results (not directly fetched — verified=False).",
            transform=ax.transAxes, fontsize=8, color=INK2)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def make_all(res: dict, out: Path):
    """Render every chart into `out`."""
    plot_impact_bars(res["impact"], out / "impact_ratio_bar.png")
    for ev, win in res["windows"].items():
        plot_event_window(win, ev, out / f"event_window_{ev}.png")
    plot_curve_shapes(res["shape_tab"], out / "curve_shape_freq.png")
    plot_signed_moves(res["signed"], out / "signed_moves_hawk_dove.png")
    plot_placebo(res["placebo"], out / "placebo_vs_real.png")
    plot_dollars(res["usd"], out / "futures_dollars_per_contract.png")
