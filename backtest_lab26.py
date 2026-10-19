#!/usr/bin/env python3
"""Lab 26: does crowded futures positioning (open interest, long/short ratios, taker flow) flag BTC pullbacks of 10%+?
Free data: Binance USD-M futures daily 'metrics' files (data.binance.vision), BTCUSDT, 5-minute rows from early 2021 aggregated to days.
Flags are declared in advance and use only data up to that day (percentiles use the trailing 365 days). Same test as lab 23 part B:
a flag only counts if it beats the base rate in many EPISODES and in more than one period. Writes lab26_summary.txt and btc_metrics_daily.csv."""
import csv, io, os, zipfile, time, calendar, statistics as st, urllib.request, math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import scanner, backtest as B
from backtest_lab23 import zig, rsi_series, dstr, med

START = datetime(2021, 1, 1, tzinfo=timezone.utc).date()
URL = "https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-%s.zip"

def fetch_day(d):
    for k in range(3):
        try:
            r = urllib.request.urlopen(urllib.request.Request(URL % d.isoformat(), headers={"User-Agent": "Mozilla/5.0"}), timeout=30)
            z = zipfile.ZipFile(io.BytesIO(r.read())); rows = list(csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())))
            f = lambda key: [float(x[key]) for x in rows if x.get(key) not in (None, "")]
            oi, oiv = f("sum_open_interest"), f("sum_open_interest_value")
            if not oi: return d, None
            mean = lambda a: sum(a) / len(a) if a else None
            return d, dict(oi=oi[-1], oiv=oiv[-1], top_ls=mean(f("sum_toptrader_long_short_ratio")), glob_ls=mean(f("count_long_short_ratio")), taker=mean(f("sum_taker_long_short_vol_ratio")))
        except Exception as e:
            if getattr(e, "code", None) == 404: return d, None
            time.sleep(1.5)
    return d, None

def pct_rank(series, i, win=365, minn=120):
    """Share of the previous `win` values (not including i) that are below series[i]; None if too little history or missing."""
    v = series[i]
    if v is None: return None
    prev = [x for x in series[max(0, i - win):i] if x is not None]
    return sum(1 for x in prev if x < v) / len(prev) if len(prev) >= minn else None

def main():
    today = datetime.now(timezone.utc).date(); ds = [START + timedelta(days=k) for k in range((today - START).days)]
    with ThreadPoolExecutor(12) as ex: got = dict(ex.map(fetch_day, ds))
    have = {d: v for d, v in got.items() if v}
    print("daily metrics files read:", len(have), "of", len(ds))
    btc = B.hist_crypto("BTC", "1d", 2600); fixed = []; bad = 0
    for t, o, h, l, c, v in btc:
        hb, lb = max(o, c), min(o, c); h2, l2 = min(h, hb * 1.25), max(l, lb / 1.25); bad += (h2 != h) + (l2 != l); fixed.append((t, o, h2, l2, c, v))
    btc = fixed; T = [r[0] for r in btc]; H = [r[2] for r in btc]; L = [r[3] for r in btc]; C = [r[4] for r in btc]; n = len(btc)
    day_of = lambda t: datetime.fromtimestamp(t, timezone.utc).date()
    M = [have.get(day_of(t)) for t in T]
    col = lambda k: [m[k] if m else None for m in M]
    OI, OIV, TOP, GLB, TAK = col("oi"), col("oiv"), col("top_ls"), col("glob_ls"), col("taker")
    rsi = rsi_series(C)
    with open(os.path.join(scanner.HERE, "btc_metrics_daily.csv"), "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["date", "open_interest_btc", "open_interest_usd", "toptrader_ls", "global_ls", "taker_ls"])
        for i in range(n):
            if M[i]: w.writerow([dstr(T[i]), round(OI[i], 1), round(OIV[i]), round(TOP[i] or 0, 4), round(GLB[i] or 0, 4), round(TAK[i] or 0, 4)])
    ch = lambda s, i, k: (s[i] / s[i - k] - 1) if i >= k and s[i] and s[i - k] else None
    def fut_dd(i, d=14):
        j = min(n - 1, i + d); return 1 - min(L[i + 1:j + 1]) / C[i] if j > i else None
    first = next((i for i in range(n) if M[i]), None)
    if first is None: print("no metrics data"); return
    days = [i for i in range(first + 120, n - 15) if M[i] and OI[i]]
    pr = lambda s: {i: pct_rank(s, i) for i in days}
    pTOP, pGLB, pTAK, pOI = pr(TOP), pr(GLB), pr(TAK), pr(OI)
    pc = lambda i, k=30: ch(C, i, k)
    def gt(x, v): return x is not None and x >= v
    def lt(x, v): return x is not None and x <= v
    flags = [("ALL DAYS (base rate)", lambda i: True),
             ("OI (coins) up >=15% in 30d", lambda i: gt(ch(OI, i, 30), .15)), ("OI (coins) up >=25% in 30d", lambda i: gt(ch(OI, i, 30), .25)),
             ("OI (coins) up >=10% in 7d", lambda i: gt(ch(OI, i, 7), .10)), ("OI (USD) up >=40% in 30d", lambda i: gt(ch(OIV, i, 30), .40)),
             ("OI at top 5% of its past year", lambda i: gt(pOI[i], .95)),
             ("price up >=20% in 30d AND OI up >=15%", lambda i: gt(pc(i), .20) and gt(ch(OI, i, 30), .15)),
             ("price up >=15% in 30d BUT OI flat/down", lambda i: gt(pc(i), .15) and lt(ch(OI, i, 30), 0)),
             ("top-trader long/short in top 10% of past year", lambda i: gt(pTOP[i], .90)), ("top-trader long/short in bottom 10%", lambda i: lt(pTOP[i], .10)),
             ("all-account long/short in top 10%", lambda i: gt(pGLB[i], .90)), ("all-account long/short in bottom 10%", lambda i: lt(pGLB[i], .10)),
             ("taker buy/sell ratio in top 10%", lambda i: gt(pTAK[i], .90)), ("taker buy/sell ratio in bottom 10%", lambda i: lt(pTAK[i], .10)),
             ("OI top 5% AND all-account long/short top 10%", lambda i: gt(pOI[i], .95) and gt(pGLB[i], .90))]
    periods = [("cycle 1 (to Nov 2021)", lambda t: t < calendar.timegm((2021, 12, 1, 0, 0, 0))), ("bear (Dec 2021-Nov 2022)", lambda t: calendar.timegm((2021, 12, 1, 0, 0, 0)) <= t < calendar.timegm((2022, 12, 1, 0, 0, 0))), ("cycle 2 (Dec 2022 on)", lambda t: t >= calendar.timegm((2022, 12, 1, 0, 0, 0)))]
    def episodes(fl, allflag):
        if allflag: return fl[::14]
        eps = []; last = -99
        for i in fl:
            if i - last > 7: eps.append(i)
            last = i
        return eps
    def stat(f, sub=None, allflag=False):
        fl = [i for i in days if f(i) and (sub is None or sub(T[i]))]
        if not fl: return None
        eps = episodes(fl, allflag); eh = [fut_dd(i) >= .10 for i in eps]
        return len(fl), len(eps), sum(eh) / len(eps), med([fut_dd(i) for i in fl])
    base = stat(flags[0][1], allflag=True); pbase = [stat(flags[0][1], sub, True) for _, sub in periods]
    Lx = [f"LAB 26  {datetime.now(timezone.utc):%Y-%m-%d}  Futures positioning (Binance BTCUSDT metrics, {len(have)} daily files, {dstr(T[days[0]])} to {dstr(T[days[-1]])}); bad price ticks clipped: {bad}", "",
          "Does a crowded-positioning flag precede a 10%+ BTC fall (low vs close) within 14 days? episodes = flagged days merged if within 7 days. z = (hit - base)/sqrt(base(1-base)/episodes); with 14 flags expect one |z|>2 by luck.",
          f"{'flag':<48}{'days':>6}{'eps':>5}{'hit':>6}{'z':>6}{'med fall':>9}   " + "  ".join(f"{p[0][:7]:>12}" for p in periods)]
    b = base[2]
    for name, f in flags:
        s = stat(f, allflag=(name.startswith("ALL")))
        if not s: Lx.append(f"{name:<48}     0"); continue
        z = (s[2] - b) / math.sqrt(b * (1 - b) / s[1]) if s[1] and 0 < b < 1 else float("nan")
        cells = []
        for (pn, sub), pb in zip(periods, pbase):
            ps = stat(f, sub, allflag=name.startswith("ALL"))
            cells.append(f"{(str(ps[1]) + ' eps ' + format(ps[2], '.0%') + ' (b ' + format(pb[2], '.0%') + ')') if ps and pb else '--':>12}")
        Lx.append(f"{name:<48}{s[0]:>6}{s[1]:>5}{s[2]:>6.0%}{z:>6.1f}{s[3]:>9.1%}   " + "  ".join(cells))
    # descriptive: feature levels at the 10%+ peaks vs all days
    p5 = zig(H, L, .05); peaks = []
    for k in range(len(p5) - 1):
        a, c2 = p5[k], p5[k + 1]
        if a[2] == "H" and c2[2] == "L" and c2[0] > a[0] and 1 - c2[1] / a[1] >= .10 and a[0] in set(days): peaks.append(a[0])
    Lx += ["", f"== At the {len(peaks)} peaks of 10%+ pullbacks vs all days (median) ==",
           f"{'':<34}{'peaks':>10}{'all days':>10}"]
    for nm, fn in (("OI change 30d (coins)", lambda i: ch(OI, i, 30)), ("OI change 7d (coins)", lambda i: ch(OI, i, 7)), ("OI percentile in past year", lambda i: pOI[i]),
                   ("top-trader L/S percentile", lambda i: pTOP[i]), ("all-account L/S percentile", lambda i: pGLB[i]), ("taker ratio percentile", lambda i: pTAK[i]), ("price change 30d", lambda i: pc(i))):
        a = [fn(i) for i in peaks if fn(i) is not None]; c3 = [fn(i) for i in days if fn(i) is not None]
        Lx.append(f"{nm:<34}{med(a):>10.2f}{med(c3):>10.2f}")
    Lx += ["", "Read: a flag matters only if its hit rate is clearly above the base rate in many episodes AND in at least two of the three periods. Thin episode counts or one-period results are noise.",
           "Caveats: one asset (BTC), about 3 market phases, 15 flags tried; Binance metrics only (other exchanges and liquidation events themselves are not in free history)."]
    text = "\n".join(Lx); open(os.path.join(scanner.HERE, "lab26_summary.txt"), "w").write(text + "\n"); print(text)
    try: scanner.notify("Strategy lab 26 finished", "Futures positioning study done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
