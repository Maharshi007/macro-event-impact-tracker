"""Central configuration: period, series IDs, tickers and analysis settings."""

START, END = "2021-01-01", "2025-12-31"

# FRED constant-maturity Treasury yields (daily, % p.a.)
TENORS = {"2Y": "DGS2", "5Y": "DGS5", "10Y": "DGS10", "30Y": "DGS30"}
FED_TARGET = "DFEDTARU"            # Fed funds target range, upper bound (%)
CPI_SERIES = "CPIAUCSL"            # CPI-U, seasonally adjusted (ALFRED vintages)

# yfinance continuous front-month Treasury futures, matched to the FRED tenor
FUTURES = {"2Y": "ZT=F", "5Y": "ZF=F", "10Y": "ZN=F", "30Y": "ZB=F"}
FED_FUNDS_FUTURE = "ZQ=F"
ROLL_RESID_Z = 4.0                 # |robust z| of the regression residual that flags a roll artifact
# Roll windows are defined in futures.in_roll_window (prompt's end-Feb/May/Aug/Nov window
# + the expiry window where Yahoo's continuous series actually switches contract).

# Contract face value per CME contract specs. cmegroup.com blocks scripts (403) and the
# web fetcher (timeout); values come from cmegroup.com pages as shown in web-search
# results, so verified=False until someone opens the spec pages and confirms.
CONTRACT_SPECS = {
    "ZT=F": {"face_usd": 200_000, "verified": False,
             "url": "https://www.cmegroup.com/markets/interest-rates/us-treasury/2-year-us-treasury-note.contractSpecs.html"},
    "ZF=F": {"face_usd": 100_000, "verified": False,
             "url": "https://www.cmegroup.com/markets/interest-rates/us-treasury/5-year-us-treasury-note.contractSpecs.html"},
    "ZN=F": {"face_usd": 100_000, "verified": False,
             "url": "https://www.cmegroup.com/markets/interest-rates/us-treasury/10-year-us-treasury-note.contractSpecs.html"},
    "ZB=F": {"face_usd": 100_000, "verified": False,
             "url": "https://www.cmegroup.com/markets/interest-rates/us-treasury/us-treasury-bond.contractSpecs.html"},
}

WINDOW = 2                 # event window: -2..+2 trading days
PLACEBO_SHIFT = 10         # placebo: shift every event +10 trading days
ALPHA = 0.05
REGIME_YEAR = 2022         # hiking cycle vs other years

FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BLS_CPI_ARCHIVE_URL = "https://www.bls.gov/bls/news-release/cpi.htm"
BLS_CPI_SCHEDULE_URL = "https://www.bls.gov/schedule/news_release/cpi.htm"
