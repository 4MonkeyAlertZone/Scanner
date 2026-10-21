#!/usr/bin/env python3
"""Stocks step 2: the regime rule on a BASKET of 30 large US stocks, 2000 to now (dividend-adjusted Yahoo closes, so dividends are included; cash earns 0).
SURVIVORSHIP WARNING: the basket is 30 stocks that were large in 2000 AND still trade today (some did badly: GE, INTC, CSCO, C, BAC). Companies that failed or were bought (Enron, WorldCom, Lehman, Nortel, Lucent...) are missing, so buy-and-hold is flattered and any 'sell' rule looks less valuable than it would have been.
Signal at the close of day i earns day i+1 (no peeking); cost 0.1% per unit of weight changed (single stocks); equal weight 1/30 per slot, unused slots are cash.
Variants (declared before running, ALL printed):
 BH            buy and hold all 30
 IDX200        all 30 only while the S&P 500 index is above its 200-day average
 IDX200 band2  same with a 2% band (in above 1.02x, out below 0.98x)
 IDX200+50     S&P above its 200-day AND 50-day (the crypto rule)
 BASKET200     the equal-weight basket's own index above its 200-day
 OWN200        each stock held only while above its OWN 200-day average
 IDX200+OWN200 both conditions per stock
 BREADTH>=40/50/60   whole basket held only while at least that % of the 30 stocks are above their own 200-day
 IDX200+BREADTH50    S&P above 200-day AND breadth >= 50%
Periods: all (2000-2026), H1 = 2000-2012, H2 = 2013-now. Also: the four big falls (2000-02, 2007-09, Feb-Mar 2020, 2022): buy-and-hold change vs each variant's account change over the same dates; a random-timing null for IDX200; and today's live status (index vs lines, breadth, traffic light). Writes stocks2_summary.txt."""
import os, json, time, random, calendar, urllib.parse
import scanner
OUT = scanner.HERE; fd = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))
def d0(y, m, dd): return calendar.timegm((y, m, dd, 0, 0, 0)) // 86400
COST = 0.001
TICKERS = "MSFT INTC CSCO IBM ORCL AAPL GE XOM CVX JNJ PFE MRK KO PEP PG WMT HD MCD DIS T VZ C JPM BAC WFC AMGN UNH MMM CAT BA".split()

def fetch(sym, adj=True):
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?interval=1d&period1=883612800&period2={int(time.time())}&includePrePost=false&events=div%7Csplit"
    j = json.loads(scanner.http(u, headers=scanner.UA))["chart"]["result"][0]
    c = (j["indicators"].get("adjclose") or [{}])[0].get("adjclose") if adj else None
    c = c or j["indicators"]["quote"][0]["close"]; out = {}
    for t, x in zip(j["timestamp"], c):
        if x: out[int(t // 86400)] = x
    if len(out) < 3000: raise ValueError(f"{sym}: only {len(out)} rows")
    return out

def sma(C, k):
    out = [None] * len(C); s = 0.0
    for i, x in enumerate(C):
        if x is None: return out
        s += x
        if i >= k: s -= C[i - k]
        if i >= k - 1: out[i] = s / k
    return out

def hyst(C, m, h):
    out = [False] * len(C); st = False
    for i in range(len(C)):
        if m[i] is None: continue
        if st and C[i] < m[i] * (1 - h): st = False
        elif not st and C[i] > m[i] * (1 + h): st = True
        out[i] = st
    return out

def run_w(W, R, a, b):
    """W[i] = list of weights decided at close i, earn R[i+1] (list per stock)."""
    N = len(R); eq = 1.0; curve = [1.0]; prev = [0.0] * N; flips = 0; inm = 0; last = False
    for i in range(a, b - 1):
        w = W[i]; g = sum(w[s] * R[s][i + 1] for s in range(N)); turn = sum(abs(w[s] - prev[s]) for s in range(N))
        eq *= 1 + g - COST * turn; prev = w; curve.append(eq)
        isin = sum(w) > 0.5
        if isin != last: flips += 1
        last = isin; inm += sum(w)
    pk = 0; dd = 0
    for x in curve: pk = max(pk, x); dd = min(dd, x / pk - 1)
    yrs = max(.5, (b - 1 - a) / 365.25)
    return dict(final=eq, cagr=(eq ** (1 / yrs) - 1) * 100, dd=dd * 100, flips=flips / yrs, tim=inm / max(1e-9, (b - 1 - a)) * 100, curve=curve)

def main(data=None):
    if data is None:
        data = {"IDX": fetch("^GSPC", adj=False)}
        for t in TICKERS:
            try: data[t] = fetch(t)
            except Exception as e: print("skipped", t, e)
    idx = data["IDX"]; names = [t for t in TICKERS if t in data]; N = len(names)
    days = [d for d in sorted(idx) if d >= d0(1999, 1, 1)]; n = len(days)
    CI = [idx[d] for d in days]
    P = {t: [None] * n for t in names}
    for t in names:
        last = None
        for i, d in enumerate(days):
            if d in data[t]: last = data[t][d]
            P[t][i] = last
    R = {t: [0.0] + [(P[t][i] / P[t][i - 1] - 1) if P[t][i] and P[t][i - 1] else 0.0 for i in range(1, n)] for t in names}
    Rl = [R[t] for t in names]
    i0 = next(i for i, d in enumerate(days) if d >= d0(2000, 1, 3)); isp = next(i for i, d in enumerate(days) if d >= d0(2013, 1, 1))
    m200 = sma(CI, 200); m50 = sma(CI, 50)
    idx200 = [m200[i] is not None and CI[i] > m200[i] for i in range(n)]; idx50 = [m50[i] is not None and CI[i] > m50[i] for i in range(n)]
    band = hyst(CI, m200, .02)
    own = {}
    for t in names:
        mt = sma([x if x else None for x in P[t]], 200) if all(x for x in P[t]) else [None] * n
        if not all(x for x in P[t]):                      # stock listed later than 1999: compute on available part
            pt = P[t]; mt = [None] * n; k0 = next(i for i, x in enumerate(pt) if x); seg = sma(pt[k0:], 200); mt[k0:] = seg
        own[t] = [mt[i] is not None and P[t][i] is not None and P[t][i] > mt[i] for i in range(n)]
    breadth = [100.0 * sum(own[t][i] for t in names) / N for i in range(n)]
    # basket index
    bi = [1.0]
    for i in range(1, n): bi.append(bi[-1] * (1 + sum(R[t][i] for t in names) / N))
    mb = sma(bi, 200); bask200 = [mb[i] is not None and bi[i] > mb[i] for i in range(n)]
    eqw = 1.0 / N
    full = lambda cond: [[eqw if cond[i] else 0.0] * N for i in range(n)]
    V = {"BH": full([True] * n), "IDX200": full(idx200), "IDX200 band2": full(band), "IDX200+50": full([idx200[i] and idx50[i] for i in range(n)]),
         "BASKET200": full(bask200),
         "OWN200": [[eqw if own[t][i] else 0.0 for t in names] for i in range(n)],
         "IDX200+OWN200": [[eqw if (own[t][i] and idx200[i]) else 0.0 for t in names] for i in range(n)]}
    for th in (40, 50, 60): V[f"BREADTH>={th}"] = full([breadth[i] >= th for i in range(n)])
    V["IDX200+BREADTH50"] = full([idx200[i] and breadth[i] >= 50 for i in range(n)])
    res = {k: (run_w(W, Rl, i0, n), run_w(W, Rl, i0, isp), run_w(W, Rl, isp, n)) for k, W in V.items()}
    L = ["STOCKS STEP 2: 30-STOCK BASKET REGIME BACKTEST", "",
         f"Basket ({N}): {' '.join(names)}.  Dividend-adjusted closes, cash earns 0, 0.1% per unit of weight changed, from {fd(days[i0])} to {fd(days[-1])}.",
         "SURVIVORSHIP WARNING: only companies that survived to today are in the basket; failures are missing, so buy-and-hold is flattered and avoidance rules look less valuable than they were.", "",
         f"{'rule':<20}{'all x':>8}{'CAGR%':>7}{'DD%':>6}{'flips':>6}{'in%':>5} |{'H1 x':>7}{'CAGR%':>7}{'DD%':>6} |{'H2 x':>7}{'CAGR%':>7}{'DD%':>6}"]
    for k, (a, h1, h2) in res.items():
        L.append(f"{k:<20}{a['final']:>8.2f}{a['cagr']:>7.1f}{a['dd']:>6.0f}{a['flips']:>6.1f}{a['tim']:>5.0f} |{h1['final']:>7.2f}{h1['cagr']:>7.1f}{h1['dd']:>6.0f} |{h2['final']:>7.2f}{h2['cagr']:>7.1f}{h2['dd']:>6.0f}")
    L += ["", "FOUR BIG FALLS: account change from peak date to trough date (basket buy-and-hold vs each rule)"]
    wins = [("2000-03-24", "2002-10-09"), ("2007-10-09", "2009-03-09"), ("2020-02-19", "2020-03-23"), ("2022-01-03", "2022-10-12")]
    L.append(f"{'rule':<20}" + "".join(f"{(a[:7] + '..' + b[:7]):>18}" for a, b in wins))
    dix = {fd(d): i for i, d in enumerate(days)}
    near = lambda s: next(dix[x] for x in sorted(dix) if x >= s)
    for k, (a, h1, h2) in res.items():
        cv = a["curve"]; row = f"{k:<20}"
        for s, e in wins:
            ia = near(s) - i0; ie = near(e) - i0
            row += f"{(cv[ie] / cv[ia] - 1) * 100:>17.0f}%"
        L.append(row)
    rng = random.Random(7); base = res["IDX200"][0]; cf = cd = 0; Nn = 800; W0 = V["IDX200"]
    for _ in range(Nn):
        sh = rng.randrange(250, n - 250); Ws = W0[-sh:] + W0[:-sh]; m = run_w(Ws, Rl, i0, n)
        cf += m["final"] >= base["final"]; cd += m["dd"] >= base["dd"]
    L += ["", f"Random-timing null for IDX200 (800 circular shifts): share ending at least as high {cf / Nn:.2f}; share with a drawdown at least as small {cd / Nn:.2f}"]
    gap50 = (CI[-1] / m50[-1] - 1) * 100; gap200 = (CI[-1] / m200[-1] - 1) * 100
    col = "RED" if not idx200[-1] else ("GREEN" if idx50[-1] else "ORANGE")
    L += ["", f"LIVE STATUS {fd(days[-1])}: S&P 500 {CI[-1]:,.0f}, {gap200:+.1f}% vs 200-day, {gap50:+.1f}% vs 50-day; breadth {breadth[-1]:.0f}% of the 30 above their own 200-day; traffic light would be {col} (GREEN above 200d and 50d, ORANGE above 200d but below 50d, RED below 200d).",
          "", "Read: compare each rule's H2 (2013-now) with its H1: a rule that only worked in 2000-12 is not trustworthy. Dividends are included here but cash interest is not, which slightly understates every rule that sits in cash."]
    t = "\n".join(L); open(os.path.join(OUT, "stocks2_summary.txt"), "w").write(t + "\n"); print(t)

if __name__ == "__main__":
    main()
