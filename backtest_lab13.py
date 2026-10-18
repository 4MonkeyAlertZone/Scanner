#!/usr/bin/env python3
"""Strategy lab 13: is it better to just HOLD alts, or hold them only while BTC is in an uptrend?
Window: 21 Nov 2022 (BTC about $16-17K bottom) to today. Daily candles, up to 99 coins (top-100 list minus BTC), equal weight among the coins that already exist
(coins with no data yet are skipped on that day), rebalanced to equal weight every 30 days. Cost 0.1% per side on whatever is bought or sold.
Strategies:
  A  buy and hold the alt basket
  B  hold the basket only while BTC closed above its 200-day average (yesterday's close/average, no peeking); cash otherwise
  C  same with the 100-day average     D  same with the 50-day average
  E  hold BTC only      F  hold BTC only while above its 200-day average
Reports final value of 1000, best/worst year, max drawdown (biggest peak-to-trough fall) and number of switches.
It does NOT include our short-term reclaim alerts (those are lab 12). Survivorship bias: only coins still listed today, which flatters holding the basket most.
Writes lab13_summary.txt and lab13_results.csv."""
import os, csv, time, calendar
from multiprocessing import Pool
import scanner, backtest as B

START = calendar.timegm((2022, 11, 21, 0, 0, 0)); COST = 0.001; REB = 30
fmt = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))

def load(tok):
    try:
        m = B.hist_crypto(tok, "1d", 2100)
        return tok, {int(r[0] // 86400): r[4] for r in m}, ""
    except Exception as e:
        return tok, {}, str(e)[:60]

def avg_flags(days, px, k):
    """flag[d] = BTC close on day d-1 > average of the k closes ending d-1 (so day d's decision uses only past data)."""
    f = {}; hist = []
    for d in days:
        if len(hist) >= k: f[d] = hist[-1] > sum(hist[-k:]) / k
        else: f[d] = None
        hist.append(px[d])
    return f

def simulate(days, prices, flag, basket):
    """prices[tok][day]; w = fraction of equity in each coin, rest cash. Returns equity curve and number of switches in/out."""
    eq = 1.0; w = {}; curve = []; sw = 0; last_reb = -10**9; inv = False
    for i, d in enumerate(days):
        if i > 0 and w:
            pd = days[i - 1]; grown = {}
            for t, wt in w.items():
                a, b = prices[t].get(pd), prices[t].get(d)
                grown[t] = wt * ((b / a) if a and b else 1.0)
            new_eq = eq * (1 - sum(w.values()) + sum(grown.values()))
            w = {t: v * eq / new_eq for t, v in grown.items()}; eq = new_eq
        want_in = True if flag is None else bool(flag.get(d))
        avail = [t for t in basket if d in prices[t]]
        target = None
        if want_in and avail:
            if not w or i - last_reb >= REB: target = {t: 1.0 / len(avail) for t in avail}
        elif not want_in and w:
            target = {}
        if want_in != inv and (want_in and avail or not want_in): sw += 1; inv = want_in
        if target is not None:
            turn = sum(abs(target.get(t, 0) - w.get(t, 0)) for t in set(target) | set(w))
            eq *= (1 - COST * turn); w = target
            if target: last_reb = i
        curve.append(eq)
    return curve, sw

def stats(days, curve):
    dd = 0.0; peak = curve[0]
    for x in curve: peak = max(peak, x); dd = min(dd, x / peak - 1)
    yrs = {}
    for d, x in zip(days, curve):
        y = time.strftime("%Y", time.gmtime(d * 86400)); yrs.setdefault(y, [x, x]); yrs[y][1] = x
    out = []; prev = 1.0
    for y in sorted(yrs):
        out.append((y, yrs[y][1] / prev - 1)); prev = yrs[y][1]
    return curve[-1], dd, out

def main():
    coins = [c for c in scanner.top100() if c != "BTC"][:99]
    print(f"Lab 13: loading {len(coins)} coins + BTC...", flush=True)
    with Pool(max(1, os.cpu_count() or 1)) as p: res = p.map(load, ["BTC"] + coins)
    prices = {t: px for t, px, e in res if len(px) > 200}
    if "BTC" not in prices: raise SystemExit("no BTC data")
    bpx = prices["BTC"]; alls = sorted(bpx)
    alts = [t for t in prices if t != "BTC"]
    days = [d for d in alls if d * 86400 >= START]
    # moving-average flags need history before START, so compute on all days then restrict
    flags = {k: avg_flags(alls, bpx, k) for k in (200, 100, 50)}
    # fill gaps: prices on missing days are skipped (rare)
    strat = [("A  hold the alt basket", alts, None), ("B  basket, only while BTC above its 200-day avg", alts, flags[200]),
             ("C  basket, only while BTC above its 100-day avg", alts, flags[100]), ("D  basket, only while BTC above its 50-day avg", alts, flags[50]),
             ("E  hold BTC", ["BTC"], None), ("F  hold BTC, only while above its 200-day avg", ["BTC"], flags[200])]
    pr = {t: prices[t] for t in prices}
    text = [f"LAB 13: {len(alts)} alts with data (of {len(coins)} asked), {fmt(days[0])} to {fmt(days[-1])} ({len(days)} days). Start value 1000. Costs 0.1% per side. Rebalance every {REB} days.", ""]
    rows = []
    for name, basket, fl in strat:
        curve, sw = simulate(days, pr, fl, basket)
        fin, dd, yrs = stats(days, curve)
        text.append(f"{name}")
        text.append(f"     final value {1000 * fin:>8,.0f}   max drawdown {dd * 100:5.0f}%   switches in/out {sw}   per year: " + "  ".join(f"{y} {g * 100:+.0f}%" for y, g in yrs))
        rows.append(dict(strategy=name, final=round(1000 * fin), max_drawdown_pct=round(dd * 100), switches=sw))
    text += ["", "HOW TO READ: compare final value AND max drawdown. If B/C/D end near A with a much smaller drawdown, the trend exit protected the profit; if they end far lower, the exits sold too early / whipsawed. Overlapping rebalances, survivorship bias (only coins listed today) and one cycle mean this is a single historical path, not a forecast. Ending value of 'hold the basket' is flattered most by survivorship bias."]
    out = "\n".join(text)
    with open(os.path.join(scanner.HERE, "lab13_results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    open(os.path.join(scanner.HERE, "lab13_summary.txt"), "w").write(out + "\n"); print(out)
    try: scanner.notify("Strategy lab 13 finished", "Hold vs trend-exit test done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
