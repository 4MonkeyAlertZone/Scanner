#!/usr/bin/env python3
"""Strategy lab 9: Benjamin Cowen-style market-regime filters, tested on our 50-average reclaim rule.
His public framework is slow and about BTC and the cycle, so we use it as FILTERS on the same reclaim/range rules as lab 7 (100 coins, up to ~7 years):
  1 BTC above its weekly 200-period average (200 weeks)         - his famous bear-market floor
  2 BTC above its 200-day average
  3-5 'log-regression risk': we fit ln(price) against ln(days) on BTC using ONLY data up to each day (no look-ahead), and measure how far today's
      price sits above or below that curve in standard deviations (z). Below the curve = low risk. Buckets: z<0, z<-0.5 (LOW), z<0.5 (not HIGH).
      This is our own approximation of the public idea, NOT his proprietary risk metric.
  6 ETH/BTC above its own 50-day average                         - 'altcoins strengthening versus Bitcoin'
  7 ETH/BTC above its 50-day AND BTC above its 200-day
  0 BTC above its 200 four-hour-candle average (about 33 days), the filter the live tool uses, as the baseline to beat.
Same rules, stops, random controls and older/newer split as lab 6 and lab 7. Writes lab9_summary.txt and lab9_results.csv."""
import os, shutil, math
os.environ.setdefault("LAB6_MONTHS", "84")
import scanner, backtest as B, backtest_lab6 as L6, backtest_lab7 as L7

GATES = (("BTC above 4H 200-avg (about 33 days) [current filter]", 0), ("BTC above WEEKLY 200-avg (200 weeks)", 0), ("BTC above 200-DAY avg", 0),
         ("log-regression risk below the curve (z<0)", 0), ("log-regression risk LOW (z<-0.5)", 0), ("log-regression risk not HIGH (z<+0.5)", 0),
         ("ETH/BTC above its 50-day avg", 0), ("ETH/BTC above 50-day AND BTC above 200-day", 0))

def daily_series(m):
    return [int(r[0] // 86400) for r in m], [r[4] for r in m]

def sma_flags(c, k):
    pre = [0.0]
    for x in c: pre.append(pre[-1] + x)
    return [i >= k - 1 and c[i] > (pre[i + 1] - pre[i + 1 - k]) / k for i in range(len(c))]

def zscores(c, min_days=730):
    """Expanding-window fit of ln(price) = a + b*ln(day number): only past data is used for each day."""
    n = len(c); out = [None] * n; sx = sy = sxx = sxy = syy = 0.0
    for i in range(n):
        x = math.log(i + 30); y = math.log(c[i])
        sx += x; sy += y; sxx += x * x; sxy += x * y; syy += y * y; k = i + 1
        if k < min_days: continue
        vx = sxx - sx * sx / k
        if vx <= 0: continue
        b = (sxy - sx * sy / k) / vx; a = (sy - b * sx) / k
        sse = syy - a * sy - b * sxy
        sd = (max(sse, 1e-12) / (k - 2)) ** .5
        out[i] = (y - (a + b * x)) / sd
    return out

def btc_setup():
    need = 4400
    btc = B.hist_crypto("BTC", "1d", need); eth = B.hist_crypto("ETH", "1d", need)
    d, c = daily_series(btc); ed = dict(zip(*daily_series(eth)))
    wk = [sum(c[max(0, i - 1399):i + 1]) / min(1400, i + 1) for i in range(len(c))]            # 200 weeks = 1400 days
    wk_ok = [c[i] > wk[i] if i >= 1399 else None for i in range(len(c))]
    s200 = sma_flags(c, 200); z = zscores(c)
    ratio = [(dd, ed[dd] and c[i] / ed[dd]) for i, dd in enumerate(d) if dd in ed]
    rd = {}
    pre = [0.0]; rr = [x for _, x in ratio]
    for i, (dd, _) in enumerate(ratio):
        pre.append(pre[-1] + (1 / rr[i]))                                                        # ETH per BTC
    for i, (dd, _) in enumerate(ratio):
        er = 1 / rr[i]; rd[dd] = (i >= 49 and er > (pre[i + 1] - pre[i + 1 - 50]) / 50)
    daily = {}
    for i, dd in enumerate(d):
        eb = rd.get(dd)
        daily[dd] = (wk_ok[i], s200[i], None if z[i] is None else z[i] < 0, None if z[i] is None else z[i] < -0.5, None if z[i] is None else z[i] < 0.5, eb,
                     None if eb is None else (eb and s200[i]))
    m4 = B.hist_crypto("BTC", "4h", L6.MONTHS * 180 + 520); c4 = [r[4] for r in m4]
    pre4 = [0.0]
    for x in c4: pre4.append(pre4[-1] + x)
    L6.BTC["ep"] = [r[0] for r in m4]; g = []
    for i, r in enumerate(m4):
        g4 = int(i >= 199 and c4[i] > (pre4[i + 1] - pre4[i + 1 - 200]) / 200)
        dv = daily.get(int(r[0] // 86400) - 1, (None,) * 7)           # last COMPLETED day, so no peeking
        g.append((g4,) + tuple(-1 if v is None else int(bool(v)) for v in dv))
    L6.BTC["g"] = g
    first = [dd for dd in d if daily[dd][0] is not None][0] if any(daily[dd][0] is not None for dd in d) else None
    print(f"BTC daily history {len(c)} days; weekly-200 filter usable from {time_str(first)}", flush=True)

def time_str(day): return "never (history too short)" if day is None else __import__("time").strftime("%Y-%m-%d", __import__("time").gmtime(day * 86400))

def main():
    L6.GATES = GATES; L6.btc_setup = btc_setup
    tmp = os.path.join(scanner.HERE, "lab9_tmp"); os.makedirs(tmp, exist_ok=True)
    L7.OUT = tmp; notify, scanner.notify = scanner.notify, (lambda *a, **k: None)
    try: L7.main()
    finally: scanner.notify = notify
    text = open(os.path.join(tmp, "lab7_summary.txt")).read()
    note = ("LAB 9 = lab 7's rules with new BTC-regime filters. In section B, 'above' = the filter said yes, 'below' = no; entries where the filter had no data yet (-1) count as 'below', "
            "so the weekly-200 and risk filters only look good if 'above' clearly beats the benchmark. Compare every filter with line 1, the filter the live tool uses now.\n\n")
    open(os.path.join(scanner.HERE, "lab9_summary.txt"), "w").write(note + text)
    shutil.copy(os.path.join(tmp, "lab7_results.csv"), os.path.join(scanner.HERE, "lab9_results.csv")); shutil.rmtree(tmp, ignore_errors=True)
    try: scanner.notify("Strategy lab 9 finished", "Market-regime filter lab done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
