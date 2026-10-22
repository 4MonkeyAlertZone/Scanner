#!/usr/bin/env python3
"""Step 3: COMBINED PORTFOLIO of three engines, each with its own on/off switch (all splits declared before running, ALL printed):
 CORE   = Nasdaq-100 (QQQ) held while the S&P 500 is in its regime (200-day average with a 2% band), else T-bills
 TREND  = the 12 ETFs (SPY QQQ IWM SMH XLE GLD SLV DBC TLT EFA EEM VNQ), each held while above its own 200-day average, inverse-volatility weights (60-day, updated monthly), else T-bills
 CRYPTO = BTC and ETH half each while BTC is above its 200-day AND 50-day average (OI warning not used: history too short), else T-bills
Portfolio = fixed split (core/trend/crypto), rebalanced daily to the split (idealised), 0.1% per unit of weight changed, cash earns T-bills. Period 2018-01-02 to now (BTC/ETH data), halves: 2018-2021 and 2022-now. ONLY ~9 YEARS, one crypto cycle: treat as a robustness check, not proof.
Splits tested: 100/0/0, 0/100/0, 0/0/100, 60/40/0, 50/50/0, 50/30/20, 40/40/20, 60/30/10, 40/30/30, 34/33/33, 70/0/30, 0/70/30, 80/0/20, 50/40/10, plus a GRID: core in {0,20,40,60,80} x crypto in {0,10,20,30}, trend = the rest (Sharpe and worst drawdown matrices, to see whether the answer depends on one exact split).
Benchmarks: SPY and QQQ buy-and-hold, 60/40 SPY/TLT, BTC buy-and-hold. Also: calendar years for four splits, share of time with 0/1/2/3 engines IN, and today's state. Writes portfolio3_summary.txt."""
import os, time, math, statistics as S
import scanner
import backtest_stocks2b as B2
import backtest_stocks2c as C2
OUT = scanner.HERE; fd = B2.fd; d0 = B2.d0
ETF = C2.ETF; CRY = C2.CRY

def prep(data, days):
    pr = {}
    for t in data:
        if t.startswith("^"): continue
        last = None; col = []
        for d in days:
            if d in data[t]: last = data[t][d][0]
            col.append(last)
        pr[t] = col
    return pr

def own200(col, n):
    out = [False] * n
    for i in range(199, n):
        seg = [x for x in col[i - 199:i + 1] if x]
        out[i] = bool(col[i]) and len(seg) >= 150 and col[i] > sum(seg) / len(seg)
    return out

def trend_W(pr, univ, n, days_m):
    """inverse-vol weights (updated at month end), asset held while above its own 200-day. Returns W (list of weight lists)."""
    N = len(univ); fl = [own200(pr[t], n) for t in univ]
    R = [[0.0] + [(pr[t][i] / pr[t][i - 1] - 1) if pr[t][i] and pr[t][i - 1] else 0.0 for i in range(1, n)] for t in univ]
    wts = [1.0 / N] * N; W = []
    for i in range(n):
        if i >= 61 and i + 1 < n and days_m[i] != days_m[i + 1]:
            iv = []
            for s in range(N):
                w = R[s][i - 59:i + 1]; sd = S.pstdev(w) * math.sqrt(252) if len(w) == 60 else 0
                iv.append(1.0 / sd if sd > 0.001 else 0.0)
            tot = sum(iv)
            if tot > 0: wts = [x / tot for x in iv]
        W.append([wts[s] if fl[s][i] else 0.0 for s in range(N)])
    return W

def setup(data):
    """shared setup for the engines: returns a dict used by the step 3b test and the live paper accounts."""
    spy = data["SPY"]; days = [d for d in sorted(spy) if d >= d0(2016, 6, 1)]; n = len(days)
    B2.days_m = [time.strftime("%Y-%m", time.gmtime(d * 86400)) for d in days]
    pr = prep(data, days)
    def col(k):
        out = []; last = None
        for d in days:
            if d in data[k]: last = data[k][d][0]
            out.append(last)
        return out
    gs = [x or 1 for x in col("^GSPC")]; irx = col("^IRX"); cash = [0.0] + [((x or 0) / 100 / 252) for x in irx[1:]]
    band = B2.hyst(gs, B2.sma(gs, 200), .02)
    U = list(ETF) + CRY; idx = {t: k for k, t in enumerate(U)}
    R = [[0.0] + [(pr[t][i] / pr[t][i - 1] - 1) if pr[t][i] and pr[t][i - 1] else 0.0 for i in range(1, n)] for t in U]
    Wt = trend_W(pr, ETF, n, B2.days_m)
    btc = pr["BTC-USD"]; m200 = B2.sma([x or 1 for x in btc], 200); m50 = B2.sma([x or 1 for x in btc], 50)
    cry_in = [bool(btc[i]) and m200[i] is not None and btc[i] > m200[i] and btc[i] > m50[i] for i in range(n)]
    return dict(days=days, n=n, pr=pr, cash=cash, band=band, U=U, idx=idx, R=R, Wt=Wt, cry_in=cry_in)

def split_weights(c, t, k, X, i, core_in, cry_in_i):
    """weights over U for day i given shares c/t/k of core/trend/crypto (already adjusted by the caller)."""
    U, idx, Wt = X["U"], X["idx"], X["Wt"]; w = [0.0] * len(U)
    if core_in: w[idx["QQQ"]] += c
    for s, tk in enumerate(ETF): w[idx[tk]] += t * Wt[i][s]
    if cry_in_i: w[idx["BTC-USD"]] += k / 2; w[idx["ETH-USD"]] += k / 2
    return w

def main(data=None):
    if data is None:
        data = {"^GSPC": {d: (v, 0) for d, v in B2.fetch("^GSPC", adj=False).items()}, "^IRX": {d: (v, 0) for d, v in B2.fetch("^IRX", adj=False, need=1000).items()}}
        for t in ETF + CRY: data[t] = C2.fetch_v(t, need=900 if t not in CRY else 800)
    spy = data["SPY"]; days = [d for d in sorted(spy) if d >= d0(2016, 6, 1)]; n = len(days)
    # crypto trades 7 days; calendar = SPY days (forward fill)
    B2.days_m = [time.strftime("%Y-%m", time.gmtime(d * 86400)) for d in days]
    pr = prep(data, days)
    def col(k):
        out = []; last = None
        for d in days:
            if d in data[k]: last = data[k][d][0]
            out.append(last)
        return out
    gs = [x or 1 for x in col("^GSPC")]; irx = col("^IRX"); cash = [0.0] + [((x or 0) / 100 / 252) for x in irx[1:]]
    band = B2.hyst(gs, B2.sma(gs, 200), .02)
    U = list(ETF) + CRY; idx = {t: k for k, t in enumerate(U)}; NU = len(U)
    R = [[0.0] + [(pr[t][i] / pr[t][i - 1] - 1) if pr[t][i] and pr[t][i - 1] else 0.0 for i in range(1, n)] for t in U]
    Wt = trend_W(pr, ETF, n, B2.days_m)
    btc = pr["BTC-USD"]; m200 = B2.sma([x or 1 for x in btc], 200); m50 = B2.sma([x or 1 for x in btc], 50)
    cry_in = [bool(btc[i]) and m200[i] is not None and btc[i] > m200[i] and btc[i] > m50[i] for i in range(n)]
    def engines(i):
        core = [0.0] * NU; trend = [0.0] * NU; cry = [0.0] * NU
        if band[i]: core[idx["QQQ"]] = 1.0
        for s, t in enumerate(ETF): trend[idx[t]] = Wt[i][s]
        if cry_in[i]: cry[idx["BTC-USD"]] = cry[idx["ETH-USD"]] = 0.5
        return core, trend, cry
    E = [engines(i) for i in range(n)]
    a0 = next(i for i, d in enumerate(days) if d >= d0(2018, 1, 2)); a1 = next(i for i, d in enumerate(days) if d >= d0(2022, 1, 1))
    def Wsplit(c, t, k):
        return [[c * E[i][0][s] + t * E[i][1][s] + k * E[i][2][s] for s in range(NU)] for i in range(n)]
    cm = S.mean(cash[a0:n])
    def sharpe(cv):
        r = [cv[i] / cv[i - 1] - 1 for i in range(1, len(cv))]; sd = S.stdev(r)
        return (S.mean(r) - cm) / sd * math.sqrt(252) if sd > 0 else float("nan")
    def ev(W, a=a0, b=n):
        m = B2.run_w(W, R, cash, a, b); m["sharpe"] = sharpe(m["curve"]); m["expo"] = S.mean(sum(W[i]) for i in range(a, b)) * 100; return m
    L = ["STEP 3: COMBINED PORTFOLIO (core / trend / crypto)", "", f"Data to {fd(days[-1])}, test period 2018-01-02 to now (~{(n - a0) / 252:.1f} years). Cash earns T-bills. Idealised daily rebalancing to the split.", "",
         f"{'split core/trend/crypto':<26}{'CAGR%':>7}{'DD%':>6}{'Sharpe':>7}{'expo%':>7} |{'2018-21 CAGR/DD':>17} |{'2022-now CAGR/DD':>18}"]
    def row(lab, W):
        m = ev(W); h1 = ev(W, a0, a1); h2 = ev(W, a1, n)
        L.append(f"{lab:<26}{m['cagr']:>7.1f}{m['dd']:>6.0f}{m['sharpe']:>7.2f}{m['expo']:>7.0f} |{h1['cagr']:>9.1f}/{h1['dd']:>4.0f}   |{h2['cagr']:>10.1f}/{h2['dd']:>4.0f}"); return m
    one = lambda t: [[1.0 if s == idx[t] else 0.0 for s in range(NU)]] * n
    row("SPY buy and hold", one("SPY")); row("QQQ buy and hold", one("QQQ")); row("BTC buy and hold", one("BTC-USD"))
    row("60/40 SPY/TLT", [[0.6 if s == idx["SPY"] else (0.4 if s == idx["TLT"] else 0.0) for s in range(NU)]] * n)
    splits = [(100, 0, 0), (0, 100, 0), (0, 0, 100), (60, 40, 0), (50, 50, 0), (50, 30, 20), (40, 40, 20), (60, 30, 10), (40, 30, 30), (34, 33, 33), (70, 0, 30), (0, 70, 30), (80, 0, 20), (50, 40, 10)]
    for c, t, k in splits: row(f"{c}/{t}/{k}", Wsplit(c / 100, t / 100, k / 100))
    L += ["", "GRID (trend = the rest): Sharpe, then worst drawdown %", f"{'core% \\ crypto%':<18}" + "".join(f"{k:>8}" for k in (0, 10, 20, 30)) + "   |   " + "".join(f"{k:>7}" for k in (0, 10, 20, 30))]
    for c in (0, 20, 40, 60, 80):
        a_ = []; b_ = []
        for k in (0, 10, 20, 30):
            m = ev(Wsplit(c / 100, (100 - c - k) / 100, k / 100)); a_.append(f"{m['sharpe']:>8.2f}"); b_.append(f"{m['dd']:>7.0f}")
        L.append(f"{c:<18}" + "".join(a_) + "   |   " + "".join(b_))
    L += ["", "Calendar years (%): SPY | 50/30/20 | 40/40/20 | 0/100/0 | 100/0/0"]
    cvs = [ev(one("SPY"))["curve"], ev(Wsplit(.5, .3, .2))["curve"], ev(Wsplit(.4, .4, .2))["curve"], ev(Wsplit(0, 1, 0))["curve"], ev(Wsplit(1, 0, 0))["curve"]]
    ye = {}
    for i in range(a0, n): ye[time.gmtime(days[i] * 86400).tm_year] = i
    prev = None
    for y in sorted(ye):
        e = ye[y]; a = (prev - a0) if prev else 0
        L.append(f"  {y}: " + " ".join(f"{(cv[e - a0] / cv[a] - 1) * 100:>7.1f}" for cv in cvs)); prev = e
    cnt = [0] * 4; ti = [sum(1 for x in (band[i], any(Wt[i]), cry_in[i]) if x) for i in range(a0, n)]
    for x in ti: cnt[x] += 1
    L += ["", "Share of days with 0 / 1 / 2 / 3 engines IN: " + " / ".join(f"{100 * c / len(ti):.0f}%" for c in cnt)]
    now = [("core (S&P regime)", band[-1]), ("trend sleeve (any asset above its 200-day)", any(Wt[-1])), ("crypto (BTC > 200d and 50d)", cry_in[-1])]
    L.append("TODAY: " + "; ".join(f"{k}: {'IN' if v else 'OUT'}" for k, v in now) + f"  ->  {sum(v for k, v in now)} of 3 engines IN")
    held = sorted(((Wt[-1][s], t) for s, t in enumerate(ETF) if Wt[-1][s] > 0), reverse=True)
    L.append("Trend sleeve holds now: " + (", ".join(f"{t} {w * 100:.0f}%" for w, t in held) or "nothing") + f"; cash {100 * (1 - sum(w for w, t in held)):.0f}%")
    L += ["", "Read: choose a split only if its neighbours in the grid look similar (no single lucky cell). Crypto adds return but also the biggest swings; the trend sleeve and core partly cover each other's weak years. About nine years and one crypto cycle: this is a sanity check on how the pieces combine, not a forecast."]
    t = "\n".join(L); open(os.path.join(OUT, "portfolio3_summary.txt"), "w").write(t + "\n"); print(t)

if __name__ == "__main__":
    main()
