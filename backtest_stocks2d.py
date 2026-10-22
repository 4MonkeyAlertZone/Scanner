#!/usr/bin/env python3
"""Stocks step 2d: FIVE IDEAS TESTED HONESTLY. Every hypothesis is declared here before running and ALL results are printed (no cherry-picking); where many tests are run, the number of 'significant' results is compared with the number luck alone would give.
 1. DIVERSIFIED TREND-FOLLOWING: hold each of the 12 ETFs (SPY QQQ IWM SMH XLE GLD SLV DBC TLT EFA EEM VNQ) whenever it is above its own 200-day average (or its 12-month return is positive), cash (T-bill rate) otherwise; weights equal or inverse-volatility (60-day), with/without the S&P regime overlay; 2007-03 to now; separate version with BTC and ETH from 2018. 0.1% per unit of weight changed. Shows CAGR, worst drawdown, Sharpe, halves, calendar years.
 2. MONEY TRADED IN DOLLARS: 20-day vs 250-day average DAILY DOLLAR VOLUME (price x volume) of each ETF and BTC/ETH, in $ billions and change in $ billions. This is money TRADED, not net inflow, and not market cap (fund size / market cap needs data we do not have free).
 3. SEASONALITY: S&P 500 since 1950 (price index): Nov-Apr vs May-Oct, month-of-year (12 tests), turn-of-month window, day-of-week; sector funds by month vs SPY (108 cells; luck alone gives about 5 with |t|>2); BTC by month (2014-now, ~12 years only); a Nov-Apr-only strategy vs buy-and-hold. Halves: before 2000 vs 2000-now.
 4. LEAD-LAG INDICATORS: does the state of an indicator predict the NEXT month / NEXT quarter of S&P returns? Indicators: copper/gold, Russell 2000/S&P, high-yield/investment-grade bonds (HYG/LQD), utilities/S&P (XLU/SPY), dollar index, 10-year yield, yield curve (10y minus 3m), VIX. States: 3-month change up vs down, and above vs below own 10-month average. Reports t-stats for all, the count of |t|>2 vs the ~5% expected by luck, and whether the sign is the same in both halves.
 5. AI CHAIN PANEL: SMH (chips), IGV (software), XLU (utilities/power), URA (uranium), COPX (copper miners), GRID (grid equipment), SRVR (data-center real estate), XLE (energy) with BTC and SPY for reference: returns, trend, and acceleration (last 3 months minus the 3 months before). Strength = market already pricing scarcity, not a forecast.
Writes stocks2d_summary.txt."""
import os, json, time, math, urllib.parse, statistics as S
import scanner
import backtest_stocks2b as B2
import backtest_stocks2c as C2
OUT = scanner.HERE; fd = B2.fd; d0 = B2.d0
ETF = C2.ETF; CRY = C2.CRY; NAMES = dict(C2.NAMES)
NAMES.update({"IGV": "Software", "XLU": "Utilities", "URA": "Uranium", "COPX": "Copper miners", "GRID": "Grid equipment", "SRVR": "Data-center REITs"})
SECT = "XLB XLE XLF XLI XLK XLP XLU XLV XLY".split()
EXTRA = "IGV URA COPX GRID SRVR HYG LQD".split()
LONGS = {"^GSPC": -631152000, "^IRX": -631152000, "^RUT": -631152000, "DX-Y.NYB": -631152000, "^TNX": -631152000, "^VIX": -631152000, "GC=F": 883612800, "HG=F": 883612800}

def fetch(sym, p1=883612800, need=250):
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?interval=1d&period1={p1}&period2={int(time.time())}&includePrePost=false"
    j = json.loads(scanner.http(u, headers=scanner.UA))["chart"]["result"][0]
    ac = (j["indicators"].get("adjclose") or [{}])[0].get("adjclose") or j["indicators"]["quote"][0]["close"]
    vol = j["indicators"]["quote"][0].get("volume") or [0] * len(ac); out = {}
    for t, x, v in zip(j["timestamp"], ac, vol):
        if x is not None: out[int(t // 86400)] = (x, v or 0)
    if len(out) < need: raise ValueError(f"{sym}: only {len(out)} rows")
    return out

def welch(a, b):
    if len(a) < 5 or len(b) < 5: return float("nan")
    se = math.sqrt(S.variance(a) / len(a) + S.variance(b) / len(b)); return (S.mean(a) - S.mean(b)) / se if se > 0 else float("nan")
def tstat(x): return S.mean(x) / (S.stdev(x) / math.sqrt(len(x))) if len(x) > 5 and S.stdev(x) > 0 else float("nan")

def monthly(series):
    """{day:(c,v)} -> list of (year, month, last close)."""
    last = {}
    for d in sorted(series):
        t = time.gmtime(d * 86400); last[(t.tm_year, t.tm_mon)] = series[d][0]
    return [(y, m, c) for (y, m), c in sorted(last.items())]

def sharpe(curve, cashm):
    r = [curve[i] / curve[i - 1] - 1 for i in range(1, len(curve))]
    if len(r) < 50: return float("nan")
    sd = S.stdev(r); return (S.mean(r) - cashm) / sd * math.sqrt(252) if sd > 0 else float("nan")

def main(data=None):
    if data is None:
        data = {}
        for t in ETF + CRY + EXTRA + SECT + list(LONGS):
            try: data[t] = fetch(t, LONGS.get(t, 883612800), 3000 if t in LONGS and LONGS[t] < 0 and t not in ("DX-Y.NYB", "^RUT", "^VIX", "^TNX") else 250)
            except Exception as e: print("skipped", t, e)
    today = int(time.time() // 86400)
    for t in CRY:
        if t in data: data[t] = {d: v for d, v in data[t].items() if d < today}
    spy = data["SPY"]; days = [d for d in sorted(spy) if d >= d0(2000, 1, 3)]; n = len(days)
    B2.days_m = [time.strftime("%Y-%m", time.gmtime(d * 86400)) for d in days]
    def al(t, w=0):
        out = []; last = None
        for d in days:
            if d in data[t]: last = data[t][d][w]
            out.append(last)
        return out
    pr = {t: al(t) for t in data if not t.startswith("^") and "=" not in t and t != "DX-Y.NYB"}; vl = {t: al(t, 1) for t in pr}
    gs = al("^GSPC"); irx = al("^IRX"); cash = [0.0] + [((x or 0) / 100 / 252) for x in irx[1:]]
    ma200 = B2.sma([x or 1 for x in gs], 200); band = B2.hyst([x or 1 for x in gs], ma200, .02)
    L = ["STOCKS STEP 2d: FIVE IDEAS TESTED HONESTLY", "", f"Data to {fd(days[-1])}. Dividend-adjusted ETF closes; S&P tests use the price index; cash earns T-bill rates.", ""]
    # ================= 1 trend following
    have = lambda t: t in pr
    s0 = next(i for i, d in enumerate(days) if d >= d0(2007, 3, 1)); s1 = next(i for i, d in enumerate(days) if d >= d0(2017, 1, 1)); s2 = next(i for i, d in enumerate(days) if d >= d0(2018, 1, 2))
    R = lambda t: [0.0] + [(pr[t][i] / pr[t][i - 1] - 1) if pr[t][i] and pr[t][i - 1] else 0.0 for i in range(1, n)]
    def inma(t): return [bool(pr[t][i]) and i >= 199 and len([x for x in pr[t][i - 199:i + 1] if x]) >= 150 and pr[t][i] > sum(x for x in pr[t][i - 199:i + 1] if x) / len([x for x in pr[t][i - 199:i + 1] if x]) for i in range(n)]
    def intm(t): return [i >= 252 and bool(pr[t][i]) and bool(pr[t][i - 252]) and pr[t][i] > pr[t][i - 252] for i in range(n)]
    def volm(t):
        r = R(t); out = [None] * n
        for i in range(61, n):
            w = r[i - 59:i + 1]; sd = S.pstdev(w) * math.sqrt(252) if len(w) == 60 else None; out[i] = sd if sd and sd > 0.001 else None
        return out
    cacheV = {}; cacheI = {}
    def tf(univ, mode, inv, regime):
        N = len(univ); fl = [cacheI.setdefault((t, mode), (inma(t) if mode == "ma" else intm(t))) for t in univ]
        vv = [cacheV.setdefault(t, volm(t)) for t in univ]; wts = [1.0 / N] * N; W = []
        for i in range(n):
            if i + 1 < n and B2.days_m[i] != B2.days_m[i + 1] and inv:
                iv = [(1.0 / vv[s][i]) if vv[s][i] else 0.0 for s in range(N)]; tot = sum(iv)
                if tot > 0: wts = [x / tot for x in iv]
            w = [wts[s] if fl[s][i] else 0.0 for s in range(N)]
            W.append(w if (regime is None or regime[i]) else [0.0] * N)
        return W
    def ev(W, univ, a, b):
        m = B2.run_w(W, [R(t) for t in univ], cash, a, b); cm = S.mean(cash[a:b]); m["sharpe"] = sharpe(m["curve"], cm); return m
    univ = [t for t in ETF if have(t)]
    L += ["== 1. DIVERSIFIED TREND-FOLLOWING (12 ETFs, from 2007-03) ==", B2.TAB + f"{'Sharpe':>7}   [2007-16 CAGR%/DD% | 2017-now CAGR%/DD%]"]
    def show(lab, W, u, a=s0, b=s1):
        m = ev(W, u, a, n); h1 = ev(W, u, a, b); h2 = ev(W, u, b, n)
        L.append(B2.row(lab, m) + f"{m['sharpe']:>7.2f}   | {h1['cagr']:>5.1f}/{h1['dd']:>4.0f} | {h2['cagr']:>5.1f}/{h2['dd']:>4.0f}"); return m
    N = len(univ); idx = lambda t: [[1.0 if x == t else 0.0 for x in univ]] * n
    show("SPY buy and hold", idx("SPY"), univ); show("all 12 equal weight, buy and hold", [[1.0 / N] * N] * n, univ)
    sp = [[0.6 if x == "SPY" else (0.4 if x == "TLT" else 0.0) for x in univ]] * n; show("60/40 SPY/TLT", sp, univ)
    res = {}
    for mode, mn in (("ma", "own 200-day"), ("tm", "12-month return > 0")):
        for inv, iname in ((False, "equal weight"), (True, "inverse-vol weight")):
            for rg, rname in ((None, ""), (band, " + S&P regime")):
                lab = f"trend ({mn}), {iname}{rname}"; res[lab] = show(lab, tf(univ, mode, inv, rg), univ)
    # calendar years
    L += ["", "Calendar-year returns (%): SPY buy and hold | trend (200-day, inverse-vol) | trend (200-day, equal weight) | 60/40"]
    Wb = tf(univ, "ma", True, None); We = tf(univ, "ma", False, None); curves = [ev(idx("SPY"), univ, s0, n)["curve"], ev(Wb, univ, s0, n)["curve"], ev(We, univ, s0, n)["curve"], ev(sp, univ, s0, n)["curve"]]
    yr_end = {}
    for i in range(s0, n): yr_end[time.gmtime(days[i] * 86400).tm_year] = i
    prev = None
    for y in sorted(yr_end):
        e = yr_end[y]; row = f"  {y}: "
        for cv in curves:
            a = prev - s0 if prev else 0; row += f"{(cv[e - s0] / cv[a] - 1) * 100:>7.1f} "
        L.append(row); prev = e
    # with crypto
    if have("BTC-USD") and have("ETH-USD"):
        u2 = univ + ["BTC-USD", "ETH-USD"]; L += ["", "== 1b. WITH BTC AND ETH ADDED (2018-now), same rules ==", B2.TAB + f"{'Sharpe':>7}"]
        for lab, W, u in (("SPY buy and hold", idx("SPY"), univ), ("trend 200-day, inverse-vol, 12 ETFs", tf(univ, "ma", True, None), univ), ("trend 200-day, inverse-vol, 12 ETFs + BTC/ETH", tf(u2, "ma", True, None), u2),
                          ("trend 12m, inverse-vol, 12 ETFs", tf(univ, "tm", True, None), univ), ("trend 12m, inverse-vol, 12 ETFs + BTC/ETH", tf(u2, "tm", True, None), u2)):
            m = ev(W, u, s2, n); L.append(B2.row(lab, m) + f"{m['sharpe']:>7.2f}")
    # ================= 2 dollar volume
    L += ["", "== 2. MONEY TRADED, IN DOLLARS (average daily dollar volume, $ billions) ==", f"{'asset':<26}{'20d avg':>9}{'250d avg':>10}{'change':>9}{'change %':>10}"]
    rows = []
    for t in [x for x in ETF + EXTRA + CRY if have(x)]:
        dv = [((vl[t][i] or 0) if t in CRY else (pr[t][i] or 0) * (vl[t][i] or 0)) / 1e9 for i in range(n - 250, n)]; a20 = sum(dv[-20:]) / 20; a250 = sum(dv) / 250
        if a250 > 0: rows.append((a20 - a250, f"{NAMES.get(t, t) + ' ' + t:<26}{a20:>9.2f}{a250:>10.2f}{a20 - a250:>+9.2f}{(a20 / a250 - 1) * 100:>+10.0f}"))
    L += [r for _, r in sorted(rows, reverse=True)] + ["(sorted by dollar change; ETF volume is traded dollars in the fund, not the size of the asset class; BTC/ETH volume is Yahoo's aggregated spot volume)"]
    # ================= 3 seasonality
    g = data["^GSPC"]; gm = monthly(g); rets = []
    for i in range(1, len(gm)): rets.append((gm[i][0], gm[i][1], gm[i][2] / gm[i - 1][2] - 1))
    L += ["", f"== 3. SEASONALITY (S&P 500 price index, {gm[0][0]}-{gm[-1][0]}) ==", ""]
    def halloween(rs):
        w = [r for y, m, r in rs if m in (11, 12, 1, 2, 3, 4)]; s = [r for y, m, r in rs if m in (5, 6, 7, 8, 9, 10)]
        return S.mean(w) * 100, S.mean(s) * 100, welch(w, s)
    for lab, rs in (("all", rets), ("before 2000", [x for x in rets if x[0] < 2000]), ("2000-now", [x for x in rets if x[0] >= 2000])):
        a, b, t = halloween(rs); L.append(f"Nov-Apr vs May-Oct, {lab}: {a:+.2f}%/month vs {b:+.2f}%/month, difference t-stat {t:+.1f}")
    L += ["", "Month of year (12 tests; luck-adjusted threshold |t| > 2.9):", f"{'month':<7}{'mean%':>7}{'%up':>6}{'t':>6}   {'before 2000':>12}{'2000-now':>10}"]
    for m in range(1, 13):
        x = [r for y, mm, r in rets if mm == m]; xa = [r for y, mm, r in rets if mm == m and y < 2000]; xb = [r for y, mm, r in rets if mm == m and y >= 2000]
        L.append(f"{m:<7}{S.mean(x) * 100:>7.2f}{100 * sum(v > 0 for v in x) / len(x):>6.0f}{tstat(x):>6.1f}   {S.mean(xa) * 100:>11.2f}%{S.mean(xb) * 100:>9.2f}%")
    # strategy
    irxm = {(y, m): c for y, m, c in monthly(data["^IRX"])} if "^IRX" in data else {}
    def strat(sel, y0, y1):
        eq = 1.0; bh = 1.0; c1 = [1.0]; c2 = [1.0]
        for y, m, r in rets:
            if y < y0 or y > y1: continue
            cr = (irxm.get((y, m), 0) / 100 / 12) if irxm else 0.0
            eq *= 1 + (r if sel(m) else cr); bh *= 1 + r; c1.append(eq); c2.append(bh)
        yrs = max(1, sum(1 for y, m, r in rets if y0 <= y <= y1) / 12)
        dd = lambda c: min(x / max(c[:k + 1]) - 1 for k, x in enumerate(c)) * 100
        return (eq ** (1 / yrs) - 1) * 100, dd(c1), (bh ** (1 / yrs) - 1) * 100, dd(c2)
    L += [""]
    for lab, y0, y1 in (("1960-now", 1960, 3000), ("1960-1999", 1960, 1999), ("2000-now", 2000, 3000)):
        a, b, c, d = strat(lambda m: m in (11, 12, 1, 2, 3, 4), y0, y1)
        L.append(f"Strategy 'S&P Nov-Apr, T-bills May-Oct' {lab}: CAGR {a:.1f}% / worst DD {b:.0f}%  vs buy and hold (price only) CAGR {c:.1f}% / DD {d:.0f}%")
    # daily effects
    gd = sorted(g); dr = [(gd[i], g[gd[i]][0] / g[gd[i - 1]][0] - 1) for i in range(1, len(gd))]
    dm = [time.strftime("%Y-%m", time.gmtime(d * 86400)) for d, r in dr]; tom = [False] * len(dr)
    for i in range(len(dr)):
        if i + 1 < len(dr) and dm[i] != dm[i + 1]: tom[i] = True
        if i >= 1 and dm[i] != dm[i - 1]: tom[i] = tom[i + 1] = tom[min(i + 2, len(dr) - 1)] = True
    for lab, f_ in (("all", lambda d: True), ("before 2000", lambda d: d < d0(2000, 1, 1)), ("2000-now", lambda d: d >= d0(2000, 1, 1))):
        a = [r for (d, r), tm in zip(dr, tom) if tm and f_(d)]; b = [r for (d, r), tm in zip(dr, tom) if not tm and f_(d)]
        L.append(f"Turn-of-month window (last day + first 3 days), {lab}: {S.mean(a) * 100:+.3f}%/day vs {S.mean(b) * 100:+.3f}%/day elsewhere, t {welch(a, b):+.1f}")
    L.append("Day of week (mean %/day, t): " + "; ".join(f"{nm} {S.mean([r for d, r in dr if (d + 3) % 7 == k]) * 100:+.3f} ({tstat([r for d, r in dr if (d + 3) % 7 == k]):+.1f})" for k, nm in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri"])))
    # sectors by month
    sm = {t: {(y, m): (c) for y, m, c in monthly(data[t])} for t in SECT if t in data}; spm = {(y, m): c for y, m, c in monthly(data["SPY"])}
    cells = []
    for t, md in sm.items():
        keys = sorted(md)
        ex = {}
        for k0, k1 in zip(keys, keys[1:]):
            if k1 in spm and k0 in spm and md[k0] and spm[k0]: ex[k1] = (md[k1] / md[k0] - 1) - (spm[k1] / spm[k0] - 1)
        for m in range(1, 13):
            x = [v for (y, mm), v in ex.items() if mm == m]; a = [v for (y, mm), v in ex.items() if mm == m and y < 2013]; b = [v for (y, mm), v in ex.items() if mm == m and y >= 2013]
            if len(x) >= 10 and len(a) >= 3 and len(b) >= 3: cells.append((abs(tstat(x)), t, m, S.mean(x) * 100, tstat(x), S.mean(a) * 100, S.mean(b) * 100))
    if cells:
        sig = sum(1 for c in cells if c[0] > 2)
        L += ["", f"Sector funds by calendar month, excess return vs SPY: {len(cells)} cells, {sig} with |t| > 2 (luck alone would give about {0.05 * len(cells):.0f}). Strongest 8:"]
        for c in sorted(cells, reverse=True)[:8]: L.append(f"  {c[1]} month {c[2]:>2}: {c[3]:+.2f}%/month (t {c[4]:+.1f}); 1999-2012 {c[5]:+.2f}% | 2013-now {c[6]:+.2f}%  {'same sign in both halves' if c[5] * c[6] > 0 else 'SIGN FLIPS'}")
    if "BTC-USD" in data:
        bm = monthly(data["BTC-USD"]); br = [(bm[i][0], bm[i][1], bm[i][2] / bm[i - 1][2] - 1) for i in range(1, len(bm))]
        L += ["", f"BTC by calendar month (only {len(br) // 12} years, very noisy; mean %, % of months up, t):"]
        L.append("  " + "; ".join(f"{m}: {S.mean([r for y, mm, r in br if mm == m]) * 100:+.0f}% ({100 * sum(r > 0 for y, mm, r in br if mm == m) / max(1, len([1 for y, mm, r in br if mm == m])):.0f}%, t {tstat([r for y, mm, r in br if mm == m]):+.1f})" for m in range(1, 13) if len([1 for y, mm, r in br if mm == m]) > 5))
    # ================= 4 lead-lag
    def ser(a, b=None, op="ratio"):
        if a not in data: return None
        da = {d: v[0] for d, v in data[a].items()}
        if b is None: return da
        if b not in data: return None
        db = {d: v[0] for d, v in data[b].items()}; return {d: da[d] / db[d] for d in da if d in db and db[d]}
    inds = {"copper/gold": ser("HG=F", "GC=F"), "Russell 2000/S&P": ser("^RUT", "^GSPC"), "HYG/LQD (credit)": ser("HYG", "LQD"), "XLU/SPY (defensives)": ser("XLU", "SPY"),
            "dollar index": ser("DX-Y.NYB"), "10-year yield": ser("^TNX"), "VIX": ser("^VIX")}
    if "^TNX" in data and "^IRX" in data: inds["yield curve (10y-3m)"] = {d: data["^TNX"][d][0] - data["^IRX"][d][0] for d in data["^TNX"] if d in data["^IRX"]}
    gmm = {(y, m): c for y, m, c in gm}; keys = sorted(gmm)
    def mon_series(sr):
        last = {}
        for d in sorted(sr): t = time.gmtime(d * 86400); last[(t.tm_year, t.tm_mon)] = sr[d]
        return last
    out = []
    for nm, sr in inds.items():
        if not sr: continue
        ms = mon_series(sr); ks = [k for k in keys if k in ms]
        for stn in ("3m change up", "above 10m avg"):
            for hz in (1, 3):
                up = []; dn = []; upa = []; dna = []; upb = []; dnb = []
                for idx_, k in enumerate(ks):
                    if idx_ < 10 or idx_ + hz >= len(ks) or ks[idx_ + hz] not in gmm: continue
                    if hz == 3 and idx_ % 3: continue
                    if stn == "3m change up": s_ = ms[k] > ms[ks[idx_ - 3]]
                    else: s_ = ms[k] > sum(ms[ks[q]] for q in range(idx_ - 9, idx_ + 1)) / 10
                    fr = gmm[ks[idx_ + hz]] / gmm[k] - 1
                    (up if s_ else dn).append(fr); (upa if (s_ and k[0] < 2000) else dna if k[0] < 2000 else upb if s_ else dnb).append(fr)
                if len(up) > 15 and len(dn) > 15:
                    sa = welch(upa, dna) if len(upa) > 5 and len(dna) > 5 else float("nan"); sb = welch(upb, dnb) if len(upb) > 5 and len(dnb) > 5 else float("nan")
                    out.append((nm, stn, hz, S.mean(up) * 100, S.mean(dn) * 100, welch(up, dn), sa, sb, len(up) + len(dn)))
    L += ["", f"== 4. LEAD-LAG INDICATORS vs NEXT-MONTH / NEXT-QUARTER S&P RETURN ({len(out)} tests; luck alone gives about {0.05 * len(out):.0f} with |t|>2) ==",
          f"{'indicator':<24}{'state':<15}{'horizon':>8}{'if yes %':>9}{'if no %':>9}{'t':>6}{'t early':>8}{'t late':>8}{'n':>5}"]
    for o in sorted(out, key=lambda x: -abs(x[5])): L.append(f"{o[0]:<24}{o[1]:<15}{str(o[2]) + 'm':>8}{o[3]:>9.2f}{o[4]:>9.2f}{o[5]:>6.1f}{o[6]:>8.1f}{o[7]:>8.1f}{o[8]:>5}")
    L.append(f"Significant (|t|>2): {sum(1 for o in out if abs(o[5]) > 2)} of {len(out)}; of those, same sign and |t|>1 in both halves: {sum(1 for o in out if abs(o[5]) > 2 and o[6] * o[7] > 0 and abs(o[6]) > 1 and abs(o[7]) > 1)}. ('yes' = indicator rising / above its 10-month average; 'early' = before 2000, 'late' = 2000 on.)")
    # ================= 5 AI chain panel
    L += ["", "== 5. AI CHAIN PANEL (returns %, vs own 200-day, acceleration = last 3 months minus the 3 months before) ==", f"{'asset':<26}{'1m':>6}{'3m':>6}{'6m':>6}{'12m':>6}{'vs200d':>8}{'accel':>7}"]
    rows = []
    for t in ["SMH", "IGV", "XLU", "URA", "COPX", "GRID", "SRVR", "XLE", "BTC-USD", "SPY"]:
        if not have(t) or not pr[t][-253]: continue
        r = lambda k: (pr[t][-1] / pr[t][-1 - k] - 1) * 100 if pr[t][-1 - k] else float("nan")
        seg = [x for x in pr[t][-200:] if x]; v200 = (pr[t][-1] / (sum(seg) / len(seg)) - 1) * 100
        acc = r(63) - ((pr[t][-64] / pr[t][-127] - 1) * 100 if pr[t][-127] else float("nan"))
        rows.append((r(252), f"{NAMES.get(t, t) + ' ' + t:<26}{r(21):>6.0f}{r(63):>6.0f}{r(126):>6.0f}{r(252):>6.0f}{v200:>8.0f}{acc:>7.0f}"))
    L += [x for _, x in sorted(rows, reverse=True)]
    L += ["", "Read: a result counts only if it holds in BOTH halves, survives the luck-count, and still helps after costs. Seasonal and lead-lag effects are usually small and unstable; trend-following's value is mostly smoother drawdowns (check the 2008 and 2022 rows), not higher returns. Rotation and flows were not shown to beat QQQ + regime in step 2c."]
    t = "\n".join(L); open(os.path.join(OUT, "stocks2d_summary.txt"), "w").write(t + "\n"); print(t)

if __name__ == "__main__":
    main()
