"""Phase 9 test suite: date mapping, BOTH exclusion, IR maths, placebo, curve shapes, bp, parsers, rolls, provenance."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import analysis  # noqa: E402
import curve  # noqa: E402
import futures  # noqa: E402
import yields  # noqa: E402
from build_events import parse_bls_archive, parse_fomc_calendar  # noqa: E402
from config import CONTRACT_SPECS, FED_TARGET, FUTURES, TENORS  # noqa: E402
from events import map_to_trading_day, shift_tags, tag_days  # noqa: E402
from window import event_window  # noqa: E402


# ---------- date mapping & tagging ----------
def test_maps_holiday_to_next_trading_day():
    idx = pd.DatetimeIndex(["2025-01-06", "2025-01-07", "2025-01-09"])
    out = map_to_trading_day(pd.to_datetime(["2025-01-08"]), idx)
    assert out.iloc[0] == pd.Timestamp("2025-01-09")


def test_maps_same_day_and_drops_after_end():
    idx = pd.DatetimeIndex(["2025-01-06", "2025-01-07"])
    out = map_to_trading_day(pd.to_datetime(["2025-01-07", "2025-01-10"]), idx)
    assert list(out) == [pd.Timestamp("2025-01-07")]


def test_both_label_and_exclusion():
    idx = pd.bdate_range("2024-06-10", periods=6)
    ev = pd.DataFrame({"date": pd.to_datetime(["2024-06-12", "2024-06-12", "2024-06-13"]),
                       "event": ["CPI", "FOMC", "CPI"]})
    tags = tag_days(idx, ev)
    assert tags["2024-06-12"] == "BOTH" and tags["2024-06-13"] == "CPI"
    ch = pd.DataFrame({m: [1.0, 1, 100, 3, 1, 1] for m in analysis.MEASURES}, index=idx)
    t = analysis.impact_table(ch, tags)
    cpi = t[(t.event == "CPI") & (t.measure == "2Y")].iloc[0]
    assert cpi.n_event == 1 and cpi.mean_abs_event_bp == 3      # the 100 bp BOTH day is not in CPI
    assert cpi.n_normal == 4 and cpi.mean_abs_normal_bp == 1    # nor in NORMAL


# ---------- impact-ratio maths ----------
def test_impact_ratio_maths():
    e = np.array([9, 5, 7, 11, 3.0])
    n = np.full(100, 3.0)
    assert round(analysis.impact_ratio(e, n), 2) == 2.33


def test_bonferroni_threshold():
    idx = pd.bdate_range("2023-01-02", periods=60)
    rng = np.random.default_rng(0)
    ch = pd.DataFrame(rng.normal(0, 5, (60, 6)), index=idx, columns=analysis.MEASURES)
    tags = pd.Series(["NORMAL"] * 60, index=idx)
    tags.iloc[::6] = "CPI"
    tags.iloc[3::6] = "FOMC"
    t = analysis.impact_table(ch, tags)
    assert len(t) == 12 and np.allclose(t.bonferroni_alpha, 0.05 / 12)
    assert (t.welch_sig_bonf <= t.welch_sig_raw).all()   # Bonferroni can only remove significance


# ---------- placebo ----------
def test_placebo_shift_positions_and_overlap():
    idx = pd.bdate_range("2024-01-01", periods=30)
    tags = pd.Series("NORMAL", index=idx)
    tags.iloc[2] = "CPI"
    tags.iloc[12] = "FOMC"      # CPI+10 lands on a real FOMC day -> dropped
    tags.iloc[5] = "CPI"
    p = shift_tags(tags, 10)
    assert p.iloc[15] == "CPI"            # 5 + 10
    assert p.iloc[22] == "FOMC"           # 12 + 10
    assert p.iloc[12] == "EXCLUDED"       # real event never in placebo normal baseline
    assert (p == "CPI").sum() == 1


# ---------- curve-shape classifier ----------
@pytest.mark.parametrize("d2,d10,expected", [
    (23, 11, "bear flattener"),     # real: 2022-06-10 CPI (2Y +23, 10Y +11)
    (2, 8, "bear steepener"),
    (-10, -4, "bull steepener"),
    (-3, -9, "bull flattener"),
    (5, 5, "parallel/unchanged"),
    (-4, 4, "twist (no level move)"),
])
def test_classify_shape(d2, d10, expected):
    assert curve.classify_shape(d2, d10) == expected


def test_surprise_terciles_equal_and_ordered():
    idx = pd.bdate_range("2024-01-01", periods=9)
    ch = pd.DataFrame({"2Y": [-9, -5, -1, 0, 0, 1, 4, 8, 12.0]}, index=idx)
    tags = pd.Series("CPI", index=idx)
    s = curve.surprise_buckets(ch, tags)
    assert list(s) == ["dovish"] * 3 + ["neutral"] * 3 + ["hawkish"] * 3


# ---------- bp conversion ----------
def test_bp_conversion_and_spreads():
    assert yields.pct_to_bp(0.34) == pytest.approx(34)
    lv = pd.DataFrame({"2Y": [2.83, 3.06], "5Y": [3.07, 3.25], "10Y": [3.04, 3.15], "30Y": [3.18, 3.20]},
                      index=pd.to_datetime(["2022-06-09", "2022-06-10"]))
    ch = yields.bp_changes(lv).iloc[0]
    assert ch["2Y"] == pytest.approx(23) and ch["10Y"] == pytest.approx(11)
    assert ch["2s10s"] == pytest.approx(ch["10Y"] - ch["2Y"]) == pytest.approx(-12)


# ---------- event window ----------
def test_event_window_offsets():
    idx = pd.bdate_range("2024-01-01", periods=7)
    ch = pd.DataFrame({"2Y": [1, 2, 3, 10, 5, 6, 7.0]}, index=idx)
    tags = pd.Series("NORMAL", index=idx)
    tags.iloc[3] = "CPI"
    w = event_window(ch, tags, "CPI", 2)
    assert w.loc[0, "2Y"] == 10 and w.loc[-1, "2Y"] == 3 and w.loc[2, "2Y"] == 6


# ---------- official-calendar parsers ----------
FED_SNIPPET = """<h4><a>2024 FOMC Meetings</a></h4>
<div class="row fomc-meeting" "><div class="fomc-meeting__month col"><strong>Apr/May</strong></div>
<div class="fomc-meeting__date col">30-1</div><a href="/newsevents/pressreleases/monetary20240501a.htm">HTML</a></div>
<div class="row fomc-meeting" "><div class="fomc-meeting__month col"><strong>June</strong></div>
<div class="fomc-meeting__date col">11-12*</div><a href="/newsevents/pressreleases/monetary20240612a.htm">HTML</a></div>
<div class="row fomc-meeting" "><div class="fomc-meeting__month col"><strong>August</strong></div>
<div class="fomc-meeting__date col">22 (notation vote)</div><a href="/newsevents/pressreleases/monetary20240822a.htm">HTML</a></div>"""


def test_fomc_parser_second_day_and_unscheduled():
    f = parse_fomc_calendar(FED_SNIPPET)
    assert list(f.decision_date) == [pd.Timestamp("2024-05-01"), pd.Timestamp("2024-06-12"), pd.Timestamp("2024-08-22")]
    assert list(f.scheduled) == [True, True, False]
    assert (f.decision_date == f.statement_date).all()


def test_bls_parser_reads_date_from_link():
    b = parse_bls_archive("May 2022 | /news.release/archives/cpi_06102022.htm\nOctober 2025 | NOT PUBLISHED")
    assert b.release_date.iloc[0] == pd.Timestamp("2022-06-10") and pd.isna(b.release_date.iloc[1])


# ---------- roll-artifact detection ----------
def test_roll_artifact_flagged_only_in_window():
    idx = pd.bdate_range("2023-02-01", "2023-04-28")
    rng = np.random.default_rng(1)
    dy = pd.Series(rng.normal(0, 5, len(idx)), index=idx)
    dp = -0.07 * dy + rng.normal(0, 0.02, len(idx))
    dp[pd.Timestamp("2023-03-22")] += 1.5          # contract switch inside expiry window
    dp[pd.Timestamp("2023-04-12")] += 1.5          # same jump outside any window -> reported, not flagged
    d = futures.detect_roll_artifacts(dp, dy)
    assert d.loc["2023-03-22", "roll_flag"]
    assert not d.loc["2023-04-12", "roll_flag"] and d.loc["2023-04-12", "outlier_outside_window"]


# ---------- provenance ----------
def test_every_event_has_official_source():
    ev = pd.read_csv(ROOT / "data" / "events.csv")
    assert ev.source_url.notna().all()
    ok = ev.source_url.str.startswith(("https://www.bls.gov/", "https://www.federalreserve.gov/"))
    assert ok.all(), ev[~ok]
    assert ev.verified.all(), ev[~ev.verified]
    assert not ev.duplicated(["date", "event"]).any()


def test_every_input_has_a_source_row():
    reg = json.loads((ROOT / "data" / "sources.json").read_text(encoding="utf-8"))
    keys = " | ".join(reg)
    required = list(TENORS.values()) + [FED_TARGET] + list(FUTURES.values()) + \
        [f"CME contract unit {t}" for t in CONTRACT_SPECS] + ["CPI release dates", "FOMC decision dates", "ALFRED"]
    missing = [r for r in required if r not in keys]
    assert not missing, f"inputs without a SOURCES.md row: {missing}"
    for k, r in reg.items():
        assert r["url"].startswith("https://"), k
        assert r["as_of"] and r["how"], k
