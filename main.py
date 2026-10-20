"""Orchestrates the full pipeline: data -> events -> impact -> curve/surprise -> futures -> charts."""
import json
from pathlib import Path

import pandas as pd

import analysis
import curve
import futures
import provenance
import yields
from build_events import build as build_events
from config import CONTRACT_SPECS, CPI_SERIES, END, PLACEBO_SHIFT, REGIME_YEAR, START, WINDOW
from data_loader import get_alfred_all_releases
from events import load_events, shift_tags, tag_days
from window import event_window

OUT = Path("outputs")


def main(make_plots: bool = True) -> dict:
    """Run every phase and write all tables/charts to outputs/. Returns key objects for inspection."""
    OUT.mkdir(exist_ok=True)

    # Phase 2: yields
    levels, raw = yields.load_yield_levels(START, END)
    changes = yields.bp_changes(levels)
    fed = yields.load_fed_target(START, END)
    yields.data_quality_report(raw, changes, fed, OUT / "data_quality.md")
    changes.to_csv(OUT / "yield_changes_bp.csv")

    # Phase 3-4: events + tagging
    build_events(START, END)
    ev = load_events()
    tags = tag_days(changes.index, ev)
    print(tags.value_counts().to_string())

    # Phase 5: impact + placebo
    impact = analysis.impact_table(changes, tags)
    impact.to_csv(OUT / "impact_table.csv", index=False)
    placebo_tags = shift_tags(tags, PLACEBO_SHIFT)
    placebo = analysis.impact_table(changes, placebo_tags)
    plc = analysis.placebo_comparison(impact, placebo)
    plc.to_csv(OUT / "placebo_table.csv", index=False)

    # Phase 6: windows, curve shape, surprise, signed, beta, regimes
    windows = {e: event_window(changes, tags, e, WINDOW) for e in ["CPI", "FOMC"]}
    pd.concat(windows, names=["event"]).to_csv(OUT / "event_window_table.csv")
    shapes = curve.shape_series(changes)
    surprise = curve.surprise_buckets(changes, tags)
    shape_tab = curve.shape_table(shapes, tags, surprise)
    shape_tab.to_csv(OUT / "curve_shape_table.csv", index=False)
    signed = curve.signed_moves(changes, tags, surprise)
    signed.to_csv(OUT / "signed_moves_table.csv", index=False)
    beta = curve.beta_10y_on_2y(changes, tags)
    beta.to_csv(OUT / "beta_10y_on_2y.csv", index=False)
    regime = curve.regime_split(changes, tags, REGIME_YEAR)
    regime.to_csv(OUT / "regime_table.csv", index=False)
    first_print = curve.cpi_first_print_mom(get_alfred_all_releases(CPI_SERIES))
    cpi_join, cpi_corr = curve.cpi_print_vs_2y(first_print, changes, tags)
    cpi_join.to_csv(OUT / "cpi_first_print_vs_2y.csv", index=False)
    provenance.record("CPI first-print MoM % (ALFRED CPIAUCSL, same-vintage)", f"{cpi_corr['n']} releases joined to event-day Δ2Y",
                      f"https://alfred.stlouisfed.org/series?seid={CPI_SERIES}", "fredapi get_series_all_releases; curve.cpi_first_print_mom")
    event_detail = pd.DataFrame({"tag": tags, "surprise": surprise, "shape": shapes}).join(changes)
    event_detail[tags != "NORMAL"].to_csv(OUT / "event_days_detail.csv")

    # Phase 7: futures
    for t, spec in CONTRACT_SPECS.items():
        provenance.record(f"CME contract unit {t}", f"face ${spec['face_usd']:,} -> ${spec['face_usd'] // 100:,} per 1.00 point",
                          spec["url"], "cmegroup.com blocks scripts (403) and web fetcher (timeout); value taken from "
                          "cmegroup.com pages as shown in web-search results — confirm manually", verified=spec["verified"])
    dv01, usd, roll_rep, _ = futures.futures_analysis(changes, tags, surprise, levels.index, START, END)
    dv01.to_csv(OUT / "dv01_table.csv", index=False)
    usd.to_csv(OUT / "futures_event_dollars.csv", index=False)
    (OUT / "roll_report.json").write_text(json.dumps(roll_rep, indent=2), encoding="utf-8")
    zq_df, zq = futures.fed_funds_module(changes, tags, levels.index, START, END)
    if zq_df is not None:
        zq_df.to_csv(OUT / "zq_implied_rate_changes.csv")
    (OUT / "zq_summary.json").write_text(json.dumps(zq, indent=2, default=str), encoding="utf-8")

    res = dict(changes=changes, levels=levels, tags=tags, impact=impact, placebo=plc, windows=windows,
               shapes=shapes, surprise=surprise, shape_tab=shape_tab, signed=signed, beta=beta, regime=regime,
               cpi_corr=cpi_corr, dv01=dv01, usd=usd, roll=roll_rep, zq=zq, fed=fed)
    if make_plots:
        import plots
        plots.make_all(res, OUT)
    return res


if __name__ == "__main__":
    main()
