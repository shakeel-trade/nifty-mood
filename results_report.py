#!/usr/bin/env python3
"""
Results report - latest quarterly results for every stock in nifty50.csv + watchlist.csv:

  * actual revenue, net profit and EPS, with growth vs the same quarter last year
  * EPS vs analysts' estimate (beat / in line / miss)
  * one-time ("exceptional") items that distort profit, flagged when large
  * the next expected results date

Writes MOOD_OUTPUT_DIR/results.html (docs/results.html on GitHub).

Usage:
  python3 results_report.py          # real run (needs internet)
  python3 results_report.py --demo   # offline demo with random numbers
"""

import argparse
import datetime as dt
import html
import json
import os
import random
import sys
import time

from mood_pipeline import BASE_DIR, IST, OUTPUT_DIR, log
from growth_screen import load_screen_universe

TEMPLATE_HTML = os.path.join(BASE_DIR, "results_template.html")
CRORE = 1e7

IN_LINE_BAND = 5.0        # EPS within ±5% of the estimate counts as "in line"
ONE_TIME_SHARE = 0.10     # flag one-time items worth 10% or more of net profit ...
ONE_TIME_MIN_CR = 1.0     # ... and at least ₹1 crore
RECENT_DAYS = 100         # "latest season" = quarter ended within this many days (results come 30-60 days after)

ROW_NAMES = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "net_income": ["Net Income", "Net Income Common Stockholders", "Net Income From Continuing Operation Net Minority Interest"],
    "eps": ["Diluted EPS", "Basic EPS"],
    "unusual": ["Total Unusual Items", "Total Unusual Items Excluding Goodwill", "Special Income Charges"],
    "normalized": ["Normalized Income"],
}


def num(v):
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def row(df, key, col):
    """Value of the first matching row name in a yfinance statement for column index col."""
    if df is None or getattr(df, "empty", True) or col >= df.shape[1]:
        return None
    for name in ROW_NAMES[key]:
        if name in df.index:
            v = num(df.loc[name].iloc[col])
            if v is not None:
                return v
    return None


def fy_quarter(d):
    """Indian financial-year label for a quarter-end date, e.g. 2026-09-30 -> 'Q2 FY27'."""
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(d.month)
    fy = d.year + 1 if d.month >= 4 else d.year
    return f"Q{q} FY{fy % 100:02d}" if q else d.strftime("%b %Y")


def growth(cur, prev):
    if cur is None or prev is None or prev == 0:
        return None
    if prev < 0 and cur >= 0:
        return None   # turned from loss to profit: % growth is meaningless
    return (cur - prev) / abs(prev)


# --------------------------------------------------------------------------- fetching

def fetch_one(yf, u):
    t = yf.Ticker(u["yahoo"])
    out = {"u": u}

    stmt = None
    for attempt in range(3):
        try:
            stmt = t.quarterly_income_stmt
            break
        except Exception as e:
            log(f"  {u['symbol']}: results attempt {attempt + 1} failed ({e})")
            time.sleep(2 * (attempt + 1))
    if stmt is not None and not stmt.empty:
        stmt = stmt.loc[:, sorted(stmt.columns, reverse=True)]   # newest quarter first
        out["quarter_end"] = stmt.columns[0].date()
        yoy_col = None
        for i, c in enumerate(stmt.columns[1:], start=1):        # same quarter last year
            if abs((stmt.columns[0] - c).days - 365) <= 20:
                yoy_col = i
                break
        for key in ("revenue", "net_income", "eps", "unusual", "normalized"):
            out[key] = row(stmt, key, 0)
            out[key + "_ly"] = row(stmt, key, yoy_col) if yoy_col is not None else None
        out["qoq_rev_prev"] = row(stmt, "revenue", 1)
        out["qoq_ni_prev"] = row(stmt, "net_income", 1)

    # EPS estimate vs actual for the latest reported quarter
    try:
        eh = t.earnings_history
        if eh is not None and not eh.empty:
            eh = eh.sort_index(ascending=False)
            r = eh.iloc[0]
            qd = getattr(eh.index[0], "date", lambda: None)()
            if qd and out.get("quarter_end") and abs((qd - out["quarter_end"]).days) > 45:
                raise ValueError(f"estimate is for {qd}, not the latest quarter")
            out["eps_actual"] = num(r.get("epsActual"))
            out["eps_estimate"] = num(r.get("epsEstimate"))
            sp = num(r.get("surprisePercent"))
            out["surprise"] = sp * 100 if sp is not None else None   # Yahoo gives a fraction (0.05 = 5%)
    except Exception as e:
        log(f"  {u['symbol']}: no estimate data ({e})")

    # Next results date
    try:
        cal = t.calendar
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if dates:
            nxt = min(d for d in dates if d is not None)
            out["next_date"] = nxt.isoformat() if hasattr(nxt, "isoformat") else str(nxt)
    except Exception:
        pass
    return out


def fetch_real(universe):
    try:
        import yfinance as yf
    except ImportError:
        sys.exit("yfinance is not installed. Run: pip install -r requirements.txt")
    rows = []
    for u in universe:
        rows.append(fetch_one(yf, u))
        time.sleep(0.5)
    return rows


def fetch_demo(universe):
    rnd = random.Random(11)
    rows = []
    for u in universe:
        rev = rnd.uniform(500, 60000) * CRORE
        ni = rev * rnd.uniform(-0.02, 0.25)
        unusual = rnd.choice([0, 0, 0, ni * rnd.uniform(-0.6, 0.6)])
        eps = rnd.uniform(2, 120)
        est = eps * rnd.uniform(0.85, 1.15)
        rows.append({
            "u": u, "quarter_end": dt.date(2026, 9, 30),
            "revenue": rev, "revenue_ly": rev / rnd.uniform(0.8, 1.6),
            "net_income": ni, "net_income_ly": ni / rnd.uniform(0.6, 2.0),
            "eps": eps, "eps_ly": eps / 1.1, "unusual": unusual, "unusual_ly": 0,
            "normalized": ni - unusual * 0.75 if unusual else None,
            "eps_actual": eps, "eps_estimate": rnd.choice([None, est]),
            "surprise": None, "next_date": "2027-02-1" + str(rnd.randint(0, 9)),
        })
    return rows


# --------------------------------------------------------------------------- shaping

def shape(r, today):
    u = r["u"]
    s = {"ticker": u["symbol"], "name": u["name"], "sector": u["industry"], "source": u["source"]}
    qe = r.get("quarter_end")
    if qe is None:
        s.update({"has_results": False, "quarter": "n/a", "notes": ["No results data on Yahoo"]})
        return s
    cr = lambda v: None if v is None else round(v / CRORE, 1)
    s["has_results"] = True
    s["quarter"] = fy_quarter(qe)
    s["quarter_end"] = qe.isoformat()
    s["recent"] = (today - qe).days <= RECENT_DAYS
    s["revenue_cr"] = cr(r.get("revenue"))
    s["revenue_yoy"] = growth(r.get("revenue"), r.get("revenue_ly"))
    s["profit_cr"] = cr(r.get("net_income"))
    s["profit_yoy"] = growth(r.get("net_income"), r.get("net_income_ly"))
    s["eps"] = r.get("eps_actual") if r.get("eps_actual") is not None else r.get("eps")
    s["eps_estimate"] = r.get("eps_estimate")

    # Beat / miss vs estimate (computed from actual and estimate when both exist)
    sp = None
    if s["eps"] is not None and s["eps_estimate"] not in (None, 0):
        sp = (s["eps"] - s["eps_estimate"]) / abs(s["eps_estimate"]) * 100
    elif r.get("surprise") is not None:
        sp = r["surprise"]
    s["surprise_pct"] = None if sp is None else round(sp, 1)
    if sp is None:
        s["verdict"] = "No estimate"
    elif sp > IN_LINE_BAND:
        s["verdict"] = "Beat"
    elif sp < -IN_LINE_BAND:
        s["verdict"] = "Miss"
    else:
        s["verdict"] = "In line"

    # One-time items
    unusual, ni = r.get("unusual"), r.get("net_income")
    s["one_time_cr"] = cr(unusual) if unusual else None
    s["one_time_share"] = None
    s["one_time_flag"] = False
    if unusual and ni:
        share = abs(unusual) / abs(ni)
        s["one_time_share"] = round(share * 100)
        s["one_time_flag"] = share >= ONE_TIME_SHARE and abs(unusual) / CRORE >= ONE_TIME_MIN_CR
    s["profit_ex_one_time_cr"] = cr(r.get("normalized")) if s["one_time_flag"] else None

    notes = []
    if s["one_time_flag"]:
        kind = "gain" if unusual > 0 else "charge"
        notes.append(f"Profit includes a one-time {kind} of about ₹{abs(unusual) / CRORE:,.0f} cr "
                     f"({s['one_time_share']}% of net profit); underlying growth may differ.")
    if s["profit_yoy"] is None and r.get("net_income_ly") is not None and r["net_income_ly"] < 0 <= (ni or -1):
        notes.append("Turned from a loss to a profit vs last year.")
    if r.get("revenue_ly") is None:
        notes.append("Same quarter last year not available; growth not shown.")
    s["notes"] = notes
    s["next_date"] = r.get("next_date")
    return s


def main():
    ap = argparse.ArgumentParser(description="Quarterly results report")
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()

    universe = load_screen_universe()
    rows = fetch_demo(universe) if args.demo else fetch_real(universe)
    today = dt.datetime.now(IST).date()
    stocks = [shape(r, today) for r in rows]
    for s in stocks:
        log(f"  {s['ticker']:<11} {s['quarter']:<9} {s.get('verdict', '-'):<12}"
            f"{'  ONE-TIME ITEMS' if s.get('one_time_flag') else ''}")

    order = {"Beat": 0, "Miss": 1, "In line": 2, "No estimate": 3}
    stocks.sort(key=lambda s: (not s.get("has_results"),
                               -int(s["quarter_end"].replace("-", "")) if s.get("quarter_end") else 0,
                               order.get(s.get("verdict"), 9), s["name"]))
    payload = {
        "date": today.isoformat(),
        "generated_at": dt.datetime.now(IST).strftime("%d %b %Y %H:%M IST"),
        "demo": bool(args.demo),
        "in_line_band": IN_LINE_BAND,
        "one_time_share": int(ONE_TIME_SHARE * 100),
        "stocks": stocks,
    }
    with open(TEMPLATE_HTML, encoding="utf-8") as f:
        page = f.read()
    page = page.replace("__RESULTS_DATA__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
    page = page.replace("__TITLE_DATE__", html.escape(payload["date"]))
    os.makedirs(os.path.join(OUTPUT_DIR, "archive"), exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "results.html"), "w", encoding="utf-8") as f:
        f.write(page)
    with open(os.path.join(OUTPUT_DIR, "archive", f"results_{payload['date']}.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    log(f"Done. {len(stocks)} stocks. Page: {os.path.join(OUTPUT_DIR, 'results.html')}")


if __name__ == "__main__":
    main()
