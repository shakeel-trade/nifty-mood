# NIFTY 50 Market Mood — daily pipeline

Every trading day after market close, this job scores the mood of all 50 NIFTY 50 stocks,
explains why each one moved, and writes a dashboard (`output/dashboard.html`) in the same
layout as the prototype.

## What it does

1. **Prices**: one year of daily prices and volume for the 50 stocks and the NIFTY 50 index
   (Yahoo Finance, NSE tickers ending in `.NS`).
2. **Mood score (0–100)** from four factors:
   | Factor | Weight | Based on |
   |---|---|---|
   | Price action | 40% | today's % change, close vs 20-day average |
   | Volume | 20% | today's volume vs 20-day average, in the direction of the move |
   | Sector | 15% | average move of the other NIFTY 50 stocks in the same industry |
   | News sentiment | 25% | tone of today's headlines (weight shared out to the others when there's no news) |

   60 or above = Bullish, 41–59 = Neutral, 40 or below = Bearish.
3. **Headlines**: today's news per company from Google News (India edition).
4. **"Why it moved"**:
   - with `ANTHROPIC_API_KEY` set, Claude writes a 2–3 sentence explanation using only the
     price facts and today's headlines, and says "No clear trigger found" when nothing explains the move;
   - without a key, a rule-based summary (move, volume, sector, market).
5. **Output**:
   - `output/dashboard.html`: today's dashboard (open it in any browser)
   - `output/archive/mood_YYYY-MM-DD.html` and `.json`: one copy per day
   - `data/history.db`: SQLite tables `daily_mood` and `daily_market` with every day's scores

## Extra stocks (watchlist)

`watchlist.csv` lists stocks monitored alongside the NIFTY 50 in all three reports
(currently Ashok Leyland, Canara Bank, Cupid, Federal Bank, Groww and Shipping Corporation of India).
Add one line per stock: `NSE_SYMBOL,Company name,Industry`. Stocks already in the NIFTY 50 are skipped.

## Growth screen

`growth_screen.py` checks every stock in `nifty50.csv` plus `watchlist.csv` against six criteria
(profit growth, revenue growth, debt, promoter/insider holding, market cap, price trend) and writes
`screen.html`, linked from the dashboard's "Growth screen" button. Stocks meeting 5 or more criteria,
including profit growth, are flagged, with risk warnings such as a very high P/E.

- Add stocks to check in `watchlist.csv` (one line each: `SYMBOL,Name,Industry`, NSE symbol).
- Change the thresholds at the top of `growth_screen.py`.
- It is a research list, not a buy list.

## Results report

`results_report.py` writes `results.html` (the "Results" button) with each company's latest quarter:
revenue, net profit and EPS with growth vs the same quarter last year; EPS vs the analysts' estimate
(Beat / In line within ±5% / Miss); one-time (exceptional) items flagged when they are 10% or more of
net profit, with approximate profit excluding them; and the next expected results date.
Yahoo has no analyst estimate for many Indian companies; those show "No estimate".

## Setup (Linux / macOS / Windows, Python 3.9+)

```sh
cd nifty_mood
python3 -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python mood_pipeline.py --demo  # offline test with random numbers
python mood_pipeline.py         # real run (needs internet)
```

Optional AI explanations: create an API key at console.anthropic.com, then
`export ANTHROPIC_API_KEY="sk-ant-..."` before running. The default model is
`claude-haiku-5-5` (set `MOOD_MODEL` to change it). That's 50 short requests a day.

A full run takes about 2–3 minutes (mostly the 1-second pause between news requests).
Use `--no-news` to skip headlines.

## Run it on GitHub (no server needed)

The workflow in `.github/workflows/daily-mood.yml` runs on GitHub's computers every hour from
09:15 to 17:15 IST on weekdays (the growth screen and results report refresh only at 17:15). During
market hours the dashboard is an intraday snapshot, and volume is compared with what is normally traded by
that time of day. GitHub may start scheduled runs 5-30 minutes late at busy times. Each run saves the dashboard to `docs/index.html` and the history to `data/history.db`,
and GitHub Pages publishes it at `https://<your-username>.github.io/<repository-name>/`.
Use the "Run workflow" button on the Actions tab to run it on demand.

## Run it every trading day on your own machine

**Linux / AIX cron** (17:30 IST, Monday–Friday; server clock in IST):

```
mkdir -p logs
crontab -e
30 17 * * 1-5 /path/to/nifty_mood/run_daily.sh
```

**Windows**: Task Scheduler → Create Basic Task → Daily at 17:30, weekdays →
Program: `C:\path\to\nifty_mood\.venv\Scripts\python.exe`,
Arguments: `mood_pipeline.py`, Start in: `C:\path\to\nifty_mood`.

On exchange holidays the job still runs; the dashboard shows the last trading day's data
and the log warns if some stocks have no price for that day.

## Keep the stock list current

`nifty50.csv` holds the 50 stocks (symbol, name, industry). NSE Indices reviews the index
twice a year (changes take effect at the end of March and September). After each review, compare the file
with the official list ("Download List of Nifty 50 stocks (.csv)" on the NIFTY 50 page of
niftyindices.com / nseindia.com) and edit it. The current file reflects BSE Ltd replacing Wipro on
30 September 2026.

If a stock prints "no price data" in the log, its Yahoo symbol has probably changed; check it on
finance.yahoo.com and correct the `symbol` column.

## Things to know

- **Data terms**: Yahoo Finance and Google News data are for personal use. For a product other people use,
  switch to a licensed source (a broker API such as Zerodha Kite Connect, Upstox or Angel One SmartAPI,
  or a data vendor) by replacing `fetch_prices()`.
- **Explanations can be wrong**: the AI only sees headlines, not full articles, and news can be
  unrelated to the move. The dashboard always shows the sources so the reason can be checked.
- **Not advice**: the tool describes past moves. If you publish it, keep it descriptive and check SEBI's
  research-analyst rules first.
- **Using Oracle instead of SQLite**: replace `save_history()`; the two tables map directly to Oracle tables
  (`trade_date DATE`, numeric columns `NUMBER`, text `VARCHAR2`/`CLOB`).
