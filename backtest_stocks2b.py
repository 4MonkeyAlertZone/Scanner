#!/usr/bin/env python3
"""Stocks step 2b: GROWTH, SECTOR PICKING and LEVERAGE with the regime rule. All variants declared before running, ALL printed. Cash earns the 13-week T-bill rate (^IRX) in this step. 0.1% per unit of weight changed (0.05% x leverage in part C).
Regime = S&P 500 price index 200-day average with a 2% band (IN above 1.02x, OUT below 0.98x), the rule chosen in step 2.
A. GROWTH INDEX: Nasdaq-100 price index (^NDX, from 1985) buy-and-hold vs 200-day / 200-day band 2% / band 2% + 50-day; periods all, before 2000, 2000-now.
B. SECTOR PICKING (no hindsight, no survivorship: the 9 SPDR sector funds that exist since 1999: XLB XLE XLF XLI XLK XLP XLU XLV XLY): monthly, hold the top 2 or 3 sectors by 6-month or 12-month return, equal weight; each with regime filter ON (cash when OUT) and OFF; compared with all 9 equal weight, XLK alone, and the S&P regime rule alone.
C. LEVERAGE: 1x/2x/3x daily-reset on S&P 500 total return (^SP500TR, from 1988) and Nasdaq-100 (^NDX price, dividends ~1% ignored), buy-and-hold vs regime rule (own index 200-day band 2%). Daily return = L*r - (L-1)*T-bill - 0.9%/yr fund cost (L>1). Shows lowest point of 1.0 and worst drawdown. Funding/fees are approximations; a real 3x fund can also gap or close in a crash.
D. (HINDSIGHT-BIASED upper bound, NOT a result) top 5 of ~30 of today's famous growth stocks by 6-month momentum, monthly, 2013-now, with/without the regime; labelled biased because the list was picked knowing who won.
Writes stocks2b_summary.txt."""
import os, json, time, calendar, urllib.parse
import scanner
OUT = scanner.HERE; fd = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))
def d0(y, m, dd): return calendar.timegm((y, m, dd, 0, 0, 0)) // 86400
COST = 0.001

def fetch(sym, p1=-631152000, adj=True, need=1500):
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?interval=1d&period1={p1}&period2={int(time.time())}&includePrePost=false"
    j = json.loads(scanner.http(u, headers=scanner.UA))["chart"]["result"][0]
    c = (j["indicators"].get("adjclose") or [{}])[0].get("adjclose") if adj else None
    c = c or j["indicators"]["quote"][0]["close"]; out = {}
    for t, x in zip(j["timestamp"], c):
        if x is not None: out[int(t // 86400)] = x
    if len(out) < need: raise ValueError(f"{sym}: only {len(out)} rows")
    return out

def sma(C, k):
    out = [None] * len(C); s = 0.0
    for i, x in enumerate(C):
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

def stats(curve, flips, inm, nd):
    pk = 0; dd = 0
    for x in curve: pk = max(pk, x); dd = min(dd, x / pk - 1)
    yrs = max(.5, nd / 365.25); eq = curve[-1]
    return dict(final=eq, cagr=(eq ** (1 / yrs) - 1) * 100, dd=dd * 100, low=min(curve), flips=flips / yrs, tim=inm / max(1, nd) * 100, curve=curve)

def run_w(W, Rl, cash, a, b):
    N = len(Rl); eq = 1.0; curve = [1.0]; prev = [0.0] * N; flips = 0; inm = 0; last = False
    for i in range(a, b - 1):
        w = W[i]; sw = sum(w); g = sum(w[s] * Rl[s][i + 1] for s in range(N)) + (1 - sw) * cash[i + 1]
        turn = sum(abs(w[s] - prev[s]) for s in range(N)); eq *= 1 + g - COST * turn; prev = w; curve.append(eq)
        isin = sw > 0.5
        if isin != last: flips += 1
        last = isin; inm += sw
    return stats(curve, flips, inm, b - 1 - a)

def run_lev(pos, r, cash, L, a, b):
    eq = 1.0; curve = [1.0]; prev = 0.0; flips = 0; inm = 0; last = False
    for i in range(a, b - 1):
        p = 1.0 if pos[i] else 0.0
        lr = max(-0.999, L * r[i + 1] - (L - 1) * cash[i + 1] - ((0.009 / 252) if L > 1 else 0))
        g = p * lr + (1 - p) * cash[i + 1] - COST * L * 0.5 * abs(p - prev)
        eq *= max(1e-9, 1 + g); prev = p; curve.append(eq)
        if (p > 0) != last: flips += 1
        last = p > 0; inm += p
    return stats(curve, flips, inm, b - 1 - a)

TAB = f"{'rule':<34}{'all x':>9}{'CAGR%':>7}{'DD%':>6}{'low':>6}{'flips':>6}{'in%':>5}"
def row(lab, m): return f"{lab:<34}{m['final']:>9.2f}{m['cagr']:>7.1f}{m['dd']:>6.0f}{m['low']:>6.2f}{m['flips']:>6.1f}{m['tim']:>5.0f}"

def rotate(P, names, regime, lb, k, n, i0):
    """monthly top-k by lb-day return; weights per day; regime None = always on."""
    N = len(names); hold = [0.0] * N; W = []; dm = None
    for i in range(n):
        if i >= lb and i + 1 < n and days_m[i] != days_m[i + 1]:
            sc = [(P[t][i] / P[t][i - lb] - 1 if (P[t][i] and P[t][i - lb]) else -9) for t in names]
            top = sorted(range(N), key=lambda s: -sc[s])[:k]
            hold = [1.0 / k if s in top else 0.0 for s in range(N)]
        W.append(hold if (regime is None or regime[i]) else [0.0] * N)
    return W

def align(data, names, days):
    P = {}
    for t in names:
        last = None; col = []
        for d in days:
            if d in data[t]: last = data[t][d]
            col.append(last)
        P[t] = col
    return P

days_m = []
def main(data=None):
    global days_m
    SEC = "XLB XLE XLF XLI XLK XLP XLU XLV XLY".split()
    BIG = "AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO NFLX CRM ADBE AMD V MA LLY UNH COST HD NOW INTU ISRG REGN VRTX AMGN MU QCOM TXN AMAT LRCX KLAC PANW FTNT SNPS CDNS ANET".split()
    if data is None:
        data = {"GSPC": fetch("^GSPC", adj=False), "NDX": fetch("^NDX", adj=False), "SPTR": fetch("^SP500TR", adj=False), "IRX": fetch("^IRX", adj=False, need=1000)}
        for t in SEC + BIG:
            try: data[t] = fetch(t, p1=883612800)
            except Exception as e: print("skipped", t, e)
    g = data["GSPC"]; days = [d for d in sorted(g) if d >= d0(1985, 6, 1)]; n = len(days)
    days_m = [time.strftime("%Y-%m", time.gmtime(d * 86400)) for d in days]
    def col(key):
        out = []; last = None
        for d in days:
            if d in data[key]: last = data[key][d]
            out.append(last)
        first = next(i for i, x in enumerate(out) if x is not None)
        return [x if x is not None else out[first] for x in out], first
    CG, _ = col("GSPC"); CN, nfirst = col("NDX"); CT, tfirst = col("SPTR")
    irx, _ = col("IRX"); cash = [0.0] + [(x or 0) / 100 / 252 for x in irx[1:]]
    ret = lambda C: [0.0] + [C[i] / C[i - 1] - 1 for i in range(1, n)]
    RG, RN, RT = ret(CG), ret(CN), ret(CT)
    m200 = sma(CG, 200); m50 = sma(CG, 50)
    band = hyst(CG, m200, .02); idx200 = [m200[i] is not None and CG[i] > m200[i] for i in range(n)]
    i2000 = next(i for i, d in enumerate(days) if d >= d0(2000, 1, 3)); i_end = n
    L = ["STOCKS STEP 2b: GROWTH, SECTOR PICKING, LEVERAGE", "", f"Data to {fd(days[-1])}. Cash earns the T-bill rate in this step. 'low' = the lowest point $1 ever fell to. DD = worst drawdown.", ""]
    # ---- A
    L += ["== A. GROWTH INDEX (Nasdaq-100 price index, own 200-day line, band 2%) ==", TAB + "   [all | before 2000 | 2000-now CAGR%/DD%]"]
    mn = sma(CN, 200); mn50 = sma(CN, 50); bn = hyst(CN, mn, .02); n200 = [mn[i] is not None and CN[i] > mn[i] for i in range(n)]; n50 = [mn50[i] is not None and CN[i] > mn50[i] for i in range(n)]
    a0 = max(nfirst + 200, 0)
    for lab, pos in (("buy and hold", [True] * n), ("200d", n200), ("200d band 2%", bn), ("200d band 2% + above 50d", [bn[i] and n50[i] for i in range(n)]),
                     ("S&P 200d band 2% on Nasdaq-100", band)):
        row_ = []
        for a, b in ((a0, n), (a0, i2000), (i2000, n)):
            W = [[1.0 if pos[i] else 0.0] for i in range(n)]; row_.append(run_w(W, [RN], cash, a, b))
        L.append(row(lab, row_[0]) + f"   | {row_[1]['cagr']:>5.1f}/{row_[1]['dd']:>4.0f} | {row_[2]['cagr']:>5.1f}/{row_[2]['dd']:>4.0f}")
    # ---- B
    L += ["", "== B. SECTOR PICKING (9 sector funds, monthly, equal weight of the top k) ==", TAB + "   [2000-12 CAGR%/DD% | 2013-now CAGR%/DD%]"]
    names = [t for t in SEC if t in data]; P = align(data, names, days); Rl = [[0.0] + [(P[t][i] / P[t][i - 1] - 1) if P[t][i] and P[t][i - 1] else 0.0 for i in range(1, n)] for t in names]
    s0 = next(i for i, d in enumerate(days) if d >= d0(2000, 1, 3)); s1 = next(i for i, d in enumerate(days) if d >= d0(2013, 1, 1)); N = len(names)
    def show(lab, W, Rl_, a=s0):
        r = [run_w(W, Rl_, cash, a, n), run_w(W, Rl_, cash, a, s1), run_w(W, Rl_, cash, s1, n)]
        L.append(row(lab, r[0]) + f"   | {r[1]['cagr']:>5.1f}/{r[1]['dd']:>4.0f} | {r[2]['cagr']:>5.1f}/{r[2]['dd']:>4.0f}")
    show("S&P 500 buy and hold", [[1.0] for _ in range(n)], [RG]); show("S&P 500 regime rule only", [[1.0 if band[i] else 0.0] for i in range(n)], [RG])
    show("all 9 sectors equal weight", [[1.0 / N] * N for _ in range(n)], Rl)
    if "XLK" in names: show("XLK (technology) alone", [[1.0 if t == "XLK" else 0.0 for t in names] for _ in range(n)], Rl)
    for lb in (126, 252):
        for k in (2, 3):
            for rg, nm in ((None, "no regime"), (band, "regime")):
                show(f"top {k} by {lb // 21}m momentum, {nm}", rotate(P, names, rg, lb, k, n, s0), Rl)
    # ---- C
    L += ["", "== C. LEVERAGE (daily reset, T-bill funding, 0.9%/yr fund cost) ==", TAB]
    ia = max(tfirst + 200, 0)
    for lab, R_, pos, a0_ in (("S&P TR", RT, band, ia), ("Nasdaq-100", RN, bn, a0)):
        for Lv in (1, 2, 3):
            L.append(row(f"{lab} {Lv}x buy and hold", run_lev([True] * n, R_, cash, Lv, a0_, n)))
            L.append(row(f"{lab} {Lv}x with regime rule", run_lev(pos, R_, cash, Lv, a0_, n)))
    # ---- D
    L += ["", "== D. HINDSIGHT-BIASED: top 5 of ~30 famous growth stocks (list chosen knowing who won) by 6m momentum, 2013-now. UPPER BOUND, NOT A RESULT ==", TAB]
    bn_ = [t for t in BIG if t in data and min(data[t]) <= d0(2013, 1, 31)]
    if len(bn_) >= 10:
        P2 = align(data, bn_, days); R2 = [[0.0] + [(P2[t][i] / P2[t][i - 1] - 1) if P2[t][i] and P2[t][i - 1] else 0.0 for i in range(1, n)] for t in bn_]
        N2 = len(bn_)
        L.append(f"(universe: {len(bn_)} stocks: {' '.join(bn_)})")
        L.append(row("equal weight all, buy and hold", run_w([[1.0 / N2] * N2 for _ in range(n)], R2, cash, s1, n)))
        L.append(row("top 5 momentum, no regime", run_w(rotate(P2, bn_, None, 126, 5, n, s1), R2, cash, s1, n)))
        L.append(row("top 5 momentum, regime", run_w(rotate(P2, bn_, band, 126, 5, n, s1), R2, cash, s1, n)))
        L.append(row("S&P 500 buy and hold (same dates)", run_w([[1.0] for _ in range(n)], [RG], cash, s1, n)))
    else: L.append("(not enough history for the list)")
    # live leaders
    sc = sorted(((P[t][-1] / P[t][-127] - 1, P[t][-1] / P[t][-253] - 1, t) for t in names if P[t][-253]), reverse=True)
    L += ["", f"LIVE: regime {'IN' if band[-1] else 'OUT'} (S&P {(CG[-1] / m200[-1] - 1) * 100:+.1f}% vs 200-day). Sector funds ranked by 6-month return: " + ", ".join(f"{t} {a * 100:+.0f}% (12m {b * 100:+.0f}%)" for a, b, t in sc),
          "", "Read: compare each variant against its own buy-and-hold and against the plain S&P regime rule. Anything that only wins in one period, or only in D, is not evidence. Leverage rows are approximations; real leveraged funds also carry tracking error and can be halted or reset in a crash."]
    t = "\n".join(L); open(os.path.join(OUT, "stocks2b_summary.txt"), "w").write(t + "\n"); print(t)

if __name__ == "__main__":
    main()
