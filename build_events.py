"""Phase 3: build data/events.csv from official sources (Federal Reserve + BLS), cross-checked with ALFRED.

FOMC: federalreserve.gov meeting calendar (decision day = 2nd day; cross-checked
      against the date in the statement press-release link).
CPI:  BLS CPI news-release archive (bls.gov blocks scripts with HTTP 403, so the
      archive link list was captured with a web fetcher into
      data/raw/bls_cpi_archive_links.txt); cross-checked with ALFRED first-release
      vintage dates of CPIAUCSL. An event is verified=True only if both agree.
"""
import re
from pathlib import Path

import pandas as pd

import provenance
from config import START, END, FOMC_CALENDAR_URL, BLS_CPI_ARCHIVE_URL, CPI_SERIES
from data_loader import fetch_html, get_alfred_all_releases

_FULL = ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"]
MONTHS = {m: i for i, m in enumerate(_FULL, 1)} | {m[:3]: i for i, m in enumerate(_FULL, 1)}
FED = "https://www.federalreserve.gov"
BLS_LINKS_FILE = Path("data/raw/bls_cpi_archive_links.txt")


def parse_fomc_calendar(html: str) -> pd.DataFrame:
    """Parse every meeting row of the Fed calendar page.

    Returns columns: year, month_label, days_label, decision_date, statement_date,
    scheduled, source_url.

    Intuition: a two-day meeting "Apr/May 30-1" decides on the SECOND day, which
    can fall in the next month — so the month comes from the second month label
    whenever the second day number is smaller than the first.
    """
    out = []
    parts = re.split(r"(\d{4}) FOMC Meetings</a>", html)
    for k in range(1, len(parts), 2):
        year, body = int(parts[k]), parts[k + 1]
        for row in re.split(r'<div class="[^"]*row fomc-meeting"', body)[1:]:
            m_lab = re.search(r"fomc-meeting__month[^>]*><strong>([^<]+)</strong>", row).group(1).strip()
            d_lab = re.search(r"fomc-meeting__date[^>]*>([^<]+)</div>", row).group(1).strip()
            nums = [int(x) for x in re.findall(r"\d+", d_lab.split("(")[0])]
            months = [MONTHS[x] for x in m_lab.split("/")]
            day = nums[-1]
            month = months[-1] if (len(nums) > 1 and nums[-1] < nums[0]) else months[0]
            st = re.findall(r"monetary(\d{8})a\.htm", row)
            unscheduled = bool(re.search(r"notation vote|unscheduled|conference call", d_lab, re.I))
            out.append({"year": year, "month_label": m_lab, "days_label": d_lab,
                        "decision_date": pd.Timestamp(year, month, day),
                        "statement_date": pd.Timestamp(st[0]) if st else pd.NaT,
                        "scheduled": not unscheduled,
                        "source_url": f"{FED}/newsevents/pressreleases/monetary{st[0]}a.htm" if st else FOMC_CALENDAR_URL})
    return pd.DataFrame(out)


def parse_bls_archive(text: str) -> pd.DataFrame:
    """Parse the captured BLS archive list -> reference_month, release_date, source_url.

    Intuition: BLS encodes the release date in each archive file name
    (cpi_MMDDYYYY.htm), so the date is read from the official link itself.
    Entries without a link (e.g. "NOT PUBLISHED") get release_date = NaT.
    """
    rows = []
    for line in text.splitlines():
        if line.startswith("#") or "|" not in line:
            continue
        ref, rest = [x.strip() for x in line.split("|", 1)]
        m = re.search(r"cpi_(\d{2})(\d{2})(\d{4})\.htm", rest)
        rows.append({"reference_month": ref,
                     "release_date": pd.Timestamp(int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else pd.NaT,
                     "source_url": f"https://www.bls.gov{rest}" if m else rest})
    return pd.DataFrame(rows)


def alfred_release_dates(alfred: pd.DataFrame) -> pd.DataFrame:
    """First-publication date of each CPI observation month from ALFRED vintages.

    Intuition: the earliest realtime_start at which month t has a value is the day
    BLS first published month t.
    """
    a = alfred.dropna(subset=["value"])
    first = a.groupby("date")["realtime_start"].min().rename("release_date").reset_index()
    return first.rename(columns={"date": "reference_month_date"})


def build(start: str = START, end: str = END, out: str = "data/events.csv") -> tuple[pd.DataFrame, dict]:
    """Build events.csv (date, event, source_url, verified, note) and return (events, report dict).

    Intuition: two independent official sources per event type; an event counts as
    verified only when they agree, so a parsing slip cannot silently enter the study.
    """
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    fomc = parse_fomc_calendar(fetch_html(FOMC_CALENDAR_URL, "fomccalendars.htm"))
    fomc = fomc[(fomc.decision_date >= s) & (fomc.decision_date <= e)]
    fomc_sched = fomc[fomc.scheduled].copy()
    fomc_sched["verified"] = fomc_sched.decision_date == fomc_sched.statement_date
    unsched = fomc[~fomc.scheduled]

    bls_all = parse_bls_archive(BLS_LINKS_FILE.read_text(encoding="utf-8"))
    not_published = bls_all[bls_all.release_date.isna()]
    bls = bls_all.dropna(subset=["release_date"])
    bls = bls[(bls.release_date >= s) & (bls.release_date <= e)].copy()
    alfred = alfred_release_dates(get_alfred_all_releases(CPI_SERIES))
    bls["verified"] = bls.release_date.isin(set(alfred.release_date))
    alfred_in = alfred[(alfred.release_date >= s) & (alfred.release_date <= e)]
    alfred_only = sorted(set(alfred_in.release_date) - set(bls.release_date))

    ev = pd.concat([
        pd.DataFrame({"date": bls.release_date, "event": "CPI", "source_url": bls.source_url,
                      "verified": bls.verified, "note": "ref month " + bls.reference_month}),
        pd.DataFrame({"date": fomc_sched.decision_date, "event": "FOMC", "source_url": fomc_sched.source_url,
                      "verified": fomc_sched.verified,
                      "note": "meeting " + fomc_sched.month_label + " " + fomc_sched.days_label}),
    ]).sort_values(["date", "event"]).reset_index(drop=True)
    ev["date"] = ev["date"].dt.strftime("%Y-%m-%d")
    ev.to_csv(out, index=False)
    unsched[["decision_date", "days_label", "source_url"]].to_csv("data/fomc_unscheduled_excluded.csv", index=False)

    n_cpi, n_fomc = int((ev.event == "CPI").sum()), int((ev.event == "FOMC").sum())
    provenance.record("CPI release dates (BLS archive)",
                      f"{n_cpi} releases {start}..{end}; {int(bls.verified.sum())} match ALFRED vintages",
                      BLS_CPI_ARCHIVE_URL,
                      "bls.gov returns 403 to scripts; archive link list captured via web fetcher "
                      "-> data/raw/bls_cpi_archive_links.txt; date parsed from cpi_MMDDYYYY link",
                      verified=bool(bls.verified.all()))
    provenance.record("CPI release-date cross-check (ALFRED CPIAUCSL vintages)",
                      f"{len(alfred_in)} first-release dates in period",
                      f"https://alfred.stlouisfed.org/series?seid={CPI_SERIES}", "fredapi get_series_all_releases")
    provenance.record("FOMC decision dates (scheduled)",
                      f"{n_fomc} meetings; {int(fomc_sched.verified.sum())} match statement-link date",
                      FOMC_CALENDAR_URL, "requests GET, cached data/raw/fomccalendars.htm, regex parse",
                      verified=bool(fomc_sched.verified.all()))
    provenance.record("FOMC unscheduled actions (excluded)",
                      f"{len(unsched)}: " + ", ".join(unsched.decision_date.dt.strftime("%Y-%m-%d")),
                      FOMC_CALENDAR_URL, "rows labelled notation vote / unscheduled; saved data/fomc_unscheduled_excluded.csv")

    counts = pd.crosstab(pd.to_datetime(ev.date).dt.year, ev.event)
    report = {"counts": counts, "unscheduled": unsched, "not_published": not_published,
              "alfred_only": alfred_only, "unverified": ev[~ev.verified],
              "same_day": ev[ev.duplicated("date", keep=False)]}
    return ev, report


if __name__ == "__main__":
    ev, rep = build()
    print(rep["counts"])
    for k in ["unscheduled", "not_published", "alfred_only", "unverified", "same_day"]:
        print(f"\n{k}:\n{rep[k]}")
