#!/usr/bin/env python3
"""
Growth screen - a daily research list of stocks with Cupid-like growth characteristics.

For every stock in nifty50.csv plus watchlist.csv it checks six criteria using Yahoo Finance
data and writes docs/screen.html (or MOOD_OUTPUT_DIR/screen.html).

This is a research list, NOT a buy list. Passing the screen says nothing about future returns.

Usage:
  python3 growth_screen.py          # real run (needs internet)
  python3 growth_screen.py --demo   # offline demo with random numbers
"""

import argparse
import datetime as dt
import html
import json
import os
import random
import sys
import time

from mood_pipeline import BASE_DIR, IST, OUTPUT_DIR, load_universe, log

WATCHLIST_CSV = os.path.join(BASE_DIR, "watchlist.csv")
TEMPLATE_HTML = os.path.join(BASE_DIR, "screen_template.html")

# ---- The criteria. Edit the numbers here to make the screen stricter or looser. ----------------
MIN_PROFIT_GROWTH = 0.50     # latest quarter net profit vs same quarter last year (+50%)
MIN_REVENUE_GROWTH = 0.30    # latest quarter revenue vs same quarter last year (+30%)
MAX_DEBT_TO_EQUITY = 0.50    # total debt / shareholders' equity
MIN_INSIDER_HOLDING = 0.40   # promoter + insider holding (Yahoo "held by insiders")
MAX_MARKET_CAP_CR = 10000    # market cap in ₹ crore (small/mid companies have more room to grow)
FLAG_MIN_MET = 5             # flagged when at least this many of the 6 criteria are met ...
#                              ... and the profit-growth criterion is one of them

# Risk warnings shown next to flagged stocks
HIGH_PE = 80
SHARP_RUN_6M = 1.50          # already up more than 150% in 6 months


def read_csv(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        header = [h.strip() for h in f.readline().strip().split(",")]
        for line in f:
            parts = [p.strip() for p in line.strip().split(",")]
            if len(parts) >= 3 and parts[0]:
                rec = dict(zip(header, parts))
                rec["yahoo"] = rec["symbol"] + ".NS"
                rows.append(rec)
    return rows


def load_screen_universe():
    stocks = {u["symbol"]: dict(u, source="NIFTY 50") for u in load_universe()}
    if os.path.exists(WATCHLIST_CSV):
        for u in read_csv(WATCHLIST_CSV):
            stocks.setdefault(u["symbol"], dict(u, source="Watchlist"))
    return list(stocks.values())


def num(v):
    try:
        f = float(v)
        return None if f != f else f   # NaN -> None
    except (TypeError, ValueError):
        return None


def fetch_real(universe):
    try:
        import yfinance as yf
    except ImportError:
        sys.exit("yfinance is not installed. Run: pip install -r requirements.txt")

    tickers = [u["yahoo"] for u in universe]
    log(f"Downloading 1 year of prices for {len(tickers)} stocks ...")
    prices = yf.download(tickers, period="1y", interval="1d", group_by="ticker",
                         auto_adjust=False, progress=False, threads=True)
    rows = []
    for u in universe:
        info = {}
        for attempt in range(3):
            try:
                info = yf.Ticker(u["yahoo"]).info or {}
                break
            except Exception as e:
                log(f"  {u['symbol']}: fundamentals attempt {attempt + 1} failed ({e})")
                time.sleep(2 * (attempt + 1))
        close = None
        try:
            close = prices[u["yahoo"]]["Close"].dropna()
        except Exception:
            pass
        last = float(close.iloc[-1]) if close is not None and len(close) else num(info.get("currentPrice"))
        dma200 = float(close.iloc[-200:].mean()) if close is not None and len(close) >= 150 else None
        ret6m = (last / float(close.iloc[-126]) - 1.0) if close is not None and len(close) >= 126 else None
        dte = num(info.get("debtToEquity"))
        rows.append({
            "u": u,
            "price": last,
            "market_cap_cr": (num(info.get("marketCap")) / 1e7) if num(info.get("marketCap")) else None,
            "profit_growth": num(info.get("earningsQuarterlyGrowth")),
            "revenue_growth": num(info.get("revenueGrowth")),
            "debt_to_equity": (dte / 100.0) if dte is not None else None,   # Yahoo reports it as a percentage
            "insider": num(info.get("heldPercentInsiders")),
            "pe": num(info.get("trailingPE")),
            "dma200": dma200,
            "ret6m": ret6m,
        })
        time.sleep(0.5)
    return rows


def fetch_demo(universe):
    rnd = random.Random(7)
    rows = []
    for u in universe:
        price = rnd.uniform(100, 5000)
        rows.append({
            "u": u, "price": price,
            "market_cap_cr": rnd.choice([rnd.uniform(2000, 9000), rnd.uniform(20000, 900000)]),
            "profit_growth": rnd.choice([None, rnd.uniform(-0.3, 1.6)]),
            "revenue_growth": rnd.uniform(-0.1, 1.0),
            "debt_to_equity": rnd.choice([None, rnd.uniform(0, 1.5)]),
            "insider": rnd.uniform(0, 0.75),
            "pe": rnd.choice([None, rnd.uniform(8, 300)]),
            "dma200": price * rnd.uniform(0.7, 1.2),
            "ret6m": rnd.uniform(-0.3, 2.5),
        })
    return rows


def pct(v):
    return "n/a" if v is None else f"{v * 100:+.0f}%"


def evaluate(r):
    """Return the six criteria as {key, label, value, ok} with ok True / False / None (no data)."""
    def check(value, test):
        return None if value is None else bool(test(value))

    trend_ok = None
    if r["price"] is not None and r["dma200"] is not None and r["ret6m"] is not None:
        trend_ok = r["price"] > r["dma200"] and r["ret6m"] > 0
    return [
        {"key": "profit", "label": "Profit growth", "value": pct(r["profit_growth"]),
         "ok": check(r["profit_growth"], lambda v: v >= MIN_PROFIT_GROWTH)},
        {"key": "revenue", "label": "Revenue growth", "value": pct(r["revenue_growth"]),
         "ok": check(r["revenue_growth"], lambda v: v >= MIN_REVENUE_GROWTH)},
        {"key": "debt", "label": "Debt / equity",
         "value": "n/a" if r["debt_to_equity"] is None else f"{r['debt_to_equity']:.2f}",
         "ok": check(r["debt_to_equity"], lambda v: v <= MAX_DEBT_TO_EQUITY)},
        {"key": "insider", "label": "Promoter / insider",
         "value": "n/a" if r["insider"] is None else f"{r['insider'] * 100:.0f}%",
         "ok": check(r["insider"], lambda v: v >= MIN_INSIDER_HOLDING)},
        {"key": "size", "label": "Market cap",
         "value": "n/a" if r["market_cap_cr"] is None else f"₹{r['market_cap_cr']:,.0f} cr",
         "ok": check(r["market_cap_cr"], lambda v: v <= MAX_MARKET_CAP_CR)},
        {"key": "trend", "label": "Price trend",
         "value": "n/a" if r["ret6m"] is None else f"{pct(r['ret6m'])} 6m",
         "ok": trend_ok},
    ]


def risks(r):
    out = []
    if r["pe"] is not None and r["pe"] >= HIGH_PE:
        out.append(f"Very high P/E ({r['pe']:.0f})")
    if r["ret6m"] is not None and r["ret6m"] >= SHARP_RUN_6M:
        out.append(f"Already up {r['ret6m'] * 100:.0f}% in 6 months")
    if r["pe"] is None:
        out.append("P/E not available (may be loss-making)")
    return out


def main():
    ap = argparse.ArgumentParser(description="Growth screen")
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()

    universe = load_screen_universe()
    rows = fetch_demo(universe) if args.demo else fetch_real(universe)

    stocks = []
    for r in rows:
        crit = evaluate(r)
        met = sum(1 for c in crit if c["ok"] is True)
        known = sum(1 for c in crit if c["ok"] is not None)
        flagged = met >= FLAG_MIN_MET and crit[0]["ok"] is True
        u = r["u"]
        stocks.append({
            "ticker": u["symbol"], "name": u["name"], "sector": u["industry"], "source": u["source"],
            "price": round(r["price"], 2) if r["price"] is not None else None,
            "pe": round(r["pe"], 1) if r["pe"] is not None else None,
            "criteria": crit, "met": met, "known": known, "flagged": flagged, "risks": risks(r),
        })
        log(f"  {u['symbol']:<11} {met}/6 met ({known} with data){'  FLAGGED' if flagged else ''}")

    stocks.sort(key=lambda s: (not s["flagged"], -s["met"], s["name"]))
    payload = {
        "date": dt.datetime.now(IST).strftime("%Y-%m-%d"),
        "generated_at": dt.datetime.now(IST).strftime("%d %b %Y %H:%M IST"),
        "demo": bool(args.demo),
        "thresholds": {
            "profit": f"≥ +{MIN_PROFIT_GROWTH * 100:.0f}% vs same quarter last year",
            "revenue": f"≥ +{MIN_REVENUE_GROWTH * 100:.0f}% vs same quarter last year",
            "debt": f"≤ {MAX_DEBT_TO_EQUITY:.1f}",
            "insider": f"≥ {MIN_INSIDER_HOLDING * 100:.0f}% of shares",
            "size": f"≤ ₹{MAX_MARKET_CAP_CR:,} crore",
            "trend": "above 200-day average and up over 6 months",
            "flag": f"{FLAG_MIN_MET} or more of 6, including profit growth",
        },
        "stocks": stocks,
    }

    with open(TEMPLATE_HTML, encoding="utf-8") as f:
        page = f.read()
    page = page.replace("__SCREEN_DATA__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
    page = page.replace("__TITLE_DATE__", html.escape(payload["date"]))
    os.makedirs(os.path.join(OUTPUT_DIR, "archive"), exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "screen.html"), "w", encoding="utf-8") as f:
        f.write(page)
    with open(os.path.join(OUTPUT_DIR, "archive", f"screen_{payload['date']}.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    log(f"Done. {sum(s['flagged'] for s in stocks)} flagged of {len(stocks)}. "
        f"Page: {os.path.join(OUTPUT_DIR, 'screen.html')}")


if __name__ == "__main__":
    main()
