#!/usr/bin/env python3
"""Stocks step 2c: WHERE IS THE MONEY GOING? Asset-class relative strength, crypto vs AI, volume, and a rotation backtest. All variants declared before running, ALL printed.
Universe (dividend-adjusted Yahoo closes): SPY (S&P 500), QQQ (Nasdaq-100), IWM (Russell 2000 small caps), SMH (semiconductors, the AI proxy), XLE (energy sector), GLD (gold), SLV (silver), DBC (broad commodities), TLT (long bonds), EFA (developed international), EEM (emerging), VNQ (real estate); crypto BTC-USD, ETH-USD (used only where stated).
Parts: 1 SNAPSHOT today (1/3/6/12-month returns, % vs 200-day, 12-month return vs SPY, dollar-volume trend = 20-day vs 250-day average of close x volume).
 2 CRYPTO vs AI: BTC and ETH against SMH, QQQ, SPY, GLD over 1, 2 and 3 years; how the BTC/SMH ratio moved; months BTC beat SMH.
 3 ROTATION BACKTEST (monthly, 2007-03 to now, cash earns T-bills, 0.1% per unit of weight changed): hold the top k of the 12 ETFs by 6- or 12-month return; k = 2 or 3; filters: none / S&P regime (200-day band 2%) / asset must be above its own 200-day. Compared with SPY and QQQ buy-and-hold, QQQ with the regime rule, and all 12 equal weight. Halves: 2007-2016, 2017-now.
    3b Same with BTC and ETH added to the list, 2018-now only, against the same rules without crypto over the same dates.
 4 VOLUME TEST: each month, do the top 3 funds by dollar-volume trend beat the average fund over the NEXT month? (and the same for top 3 by 6-month momentum). Mean excess return, hit rate, t-statistic. A weak result is the expected honest answer for volume.
Writes stocks2c_summary.txt."""
import os, json, time, calendar, urllib.parse, math, statistics as S
import scanner
import backtest_stocks2b as B2
OUT = scanner.HERE; fd = B2.fd; d0 = B2.d0
ETF = "SPY QQQ IWM SMH XLE GLD SLV DBC TLT EFA EEM VNQ".split(); CRY = ["BTC-USD", "ETH-USD"]
NAMES = {"SPY": "S&P 500", "QQQ": "Nasdaq-100", "IWM": "Russell 2000", "SMH": "Semiconductors (AI)", "XLE": "Energy sector", "GLD": "Gold", "SLV": "Silver", "DBC": "Commodities", "TLT": "Long bonds", "EFA": "Developed intl", "EEM": "Emerging mkts", "VNQ": "Real estate", "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum"}

def fetch_v(sym, need=900):
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?interval=1d&period1=883612800&period2={int(time.time())}&includePrePost=false"
    j = json.loads(scanner.http(u, headers=scanner.UA))["chart"]["result"][0]
    ac = (j["indicators"].get("adjclose") or [{}])[0].get("adjclose") or j["indicators"]["quote"][0]["close"]
    vol = j["indicators"]["quote"][0].get("volume") or [0] * len(ac); out = {}
    for t, x, v in zip(j["timestamp"], ac, vol):
        if x is not None: out[int(t // 86400)] = (x, v or 0)
    if len(out) < need: raise ValueError(f"{sym}: only {len(out)} rows")
    return out

def main(data=None):
    if data is None:
        data = {"GSPC": {d: (v, 0) for d, v in B2.fetch("^GSPC", adj=False).items()}, "IRX": {d: (v, 0) for d, v in B2.fetch("^IRX", adj=False, need=1000).items()}}
        for t in ETF + CRY:
            try: data[t] = fetch_v(t)
            except Exception as e: print("skipped", t, e)
    today = int(time.time() // 86400)
    for t in CRY:
        if t in data and max(data[t]) >= today: data[t] = {d: v for d, v in data[t].items() if d < today}
    spy = data["SPY"]; days = [d for d in sorted(spy) if d >= d0(2000, 1, 3)]; n = len(days)
    B2.days_m = [time.strftime("%Y-%m", time.gmtime(d * 86400)) for d in days]
    def aligned(t, which=0):
        out = []; last = None
        for d in days:
            if d in data[t]: last = data[t][d][which]
            out.append(last)
        return out
    pr = {t: aligned(t) for t in data if t not in ("GSPC", "IRX")}; vl = {t: aligned(t, 1) for t in pr}
    gs = aligned("GSPC"); irx = aligned("IRX"); cash = [0.0] + [((x or 0) / 100 / 252) for x in irx[1:]]
    band = B2.hyst([x if x else 1 for x in gs], B2.sma([x if x else 1 for x in gs], 200), .02)
    have = lambda t: t in pr
    L = ["STOCKS STEP 2c: WHERE IS THE MONEY GOING?", "", f"Data to {fd(days[-1])}. Dividend-adjusted closes (crypto = spot). Cash earns the T-bill rate.", ""]
    # ---- 1 snapshot
    ret = lambda t, k: (pr[t][-1] / pr[t][-1 - k] - 1) * 100 if pr[t][-1 - k] else None
    def m200(t): s = [x for x in pr[t][-200:] if x]; return (pr[t][-1] / (sum(s) / len(s)) - 1) * 100 if len(s) >= 150 else None
    def vtrend(t):
        dv = [(pr[t][i] or 0) * (vl[t][i] or 0) for i in range(n - 250, n)]
        a20 = sum(dv[-20:]) / 20; a250 = sum(dv) / 250
        return (a20 / a250 - 1) * 100 if a250 > 0 else None
    f = lambda x, w=7, p=0: (f"{x:>{w}.{p}f}" if x is not None else " " * (w - 1) + "-")
    L += ["== 1. SNAPSHOT ==", f"{'asset':<24}{'1m%':>7}{'3m%':>7}{'6m%':>7}{'12m%':>7}{'vs200d%':>9}{'12m vs SPY':>11}{'$vol trend%':>12}"]
    spy12 = ret("SPY", 252); rows = []
    for t in [x for x in ETF + CRY if have(x)]:
        k1, k3, k6, k12 = (ret(t, 21), ret(t, 63), ret(t, 126), ret(t, 252)); rel = (k12 - spy12) if k12 is not None and spy12 is not None else None
        vt = vtrend(t) if t not in CRY else None
        rows.append((k12 if k12 is not None else -999, f"{NAMES[t] + ' ' + t:<24}{f(k1)}{f(k3)}{f(k6)}{f(k12)}{f(m200(t), 9)}{f(rel, 11)}{f(vt, 12)}"))
    L += [r for _, r in sorted(rows, reverse=True)]
    L += ["(sorted by 12-month return; $vol trend = 20-day vs 250-day average dollar volume; crypto volume not comparable and omitted)", ""]
    # ---- 2 crypto vs AI
    L += ["== 2. CRYPTO vs AI ==", f"{'':<22}{'1 year':>9}{'2 years':>9}{'3 years':>9}"]
    for t in ["BTC-USD", "ETH-USD", "SMH", "QQQ", "SPY", "GLD"]:
        if have(t): L.append(f"{NAMES[t] + ' ' + t:<22}" + "".join(f(ret(t, k), 9) + "%" if False else f"{(ret(t, k) if ret(t, k) is not None else float('nan')):>8.0f}%" for k in (252, 504, 756)))
    if have("BTC-USD") and have("SMH"):
        r = [pr["BTC-USD"][i] / pr["SMH"][i] if pr["BTC-USD"][i] and pr["SMH"][i] else None for i in range(n)]
        L.append("BTC divided by SMH (a falling ratio = money preferring AI chips over BTC): " + ", ".join(f"{lab} {(r[-1] / r[-1 - k] - 1) * 100:+.0f}%" for lab, k in (("1y", 252), ("2y", 504), ("3y", 756)) if r[-1 - k]))
        wins = tot = 0
        for j in range(1, 25):
            a, b = n - 1 - 21 * j, n - 1 - 21 * (j - 1)
            if pr["BTC-USD"][a] and pr["SMH"][a]: tot += 1; wins += (pr["BTC-USD"][b] / pr["BTC-USD"][a]) > (pr["SMH"][b] / pr["SMH"][a])
        L.append(f"Months in the last 24 where BTC beat SMH: {wins} of {tot}")
        ma = B2.sma([x if x else 0 for x in r], 200); L.append(f"BTC/SMH ratio is {'above' if r[-1] > ma[-1] else 'below'} its own 200-day average (relative trend {'favours BTC' if r[-1] > ma[-1] else 'favours AI chips'}).")
    L.append("")
    # ---- 3 rotation
    s0 = next(i for i, d in enumerate(days) if d >= d0(2007, 3, 1)); s1 = next(i for i, d in enumerate(days) if d >= d0(2017, 1, 1))
    names = [t for t in ETF if have(t)]; P = {t: pr[t] for t in names}
    R = lambda t: [0.0] + [(pr[t][i] / pr[t][i - 1] - 1) if pr[t][i] and pr[t][i - 1] else 0.0 for i in range(1, n)]
    own200 = {t: [(lambda s: bool(s) and pr[t][i] is not None and len(s) >= 150 and pr[t][i] > sum(s) / len(s))([x for x in pr[t][max(0, i - 199):i + 1] if x]) for i in range(n)] for t in set(names + [x for x in CRY if have(x)])}
    def rot(univ, lb, k, regime, absf):
        N = len(univ); hold = [0.0] * N; W = []
        for i in range(n):
            if i >= lb and i + 1 < n and B2.days_m[i] != B2.days_m[i + 1]:
                sc = [(pr[t][i] / pr[t][i - lb] - 1) if (pr[t][i] and pr[t][i - lb]) else -9 for t in univ]
                top = sorted(range(N), key=lambda s: -sc[s])[:k]; hold = [1.0 / k if s in top else 0.0 for s in range(N)]
            w = [hold[s] if (own200[univ[s]][i] or not absf) else 0.0 for s in range(N)]
            W.append(w if (regime is None or regime[i]) else [0.0] * N)
        return W
    def show(lab, W, Rl, a, b2=None):
        r = [B2.run_w(W, Rl, cash, a, n), B2.run_w(W, Rl, cash, a, s1), B2.run_w(W, Rl, cash, s1, n)]
        L.append(B2.row(lab, r[0]) + f"   | {r[1]['cagr']:>5.1f}/{r[1]['dd']:>4.0f} | {r[2]['cagr']:>5.1f}/{r[2]['dd']:>4.0f}")
    L += ["== 3. ROTATION BACKTEST (12 ETFs, monthly, from 2007-03) ==", B2.TAB + "   [2007-16 CAGR%/DD% | 2017-now CAGR%/DD%]"]
    RL = [R(t) for t in names]; N = len(names)
    show("SPY buy and hold", [[1.0 if t == "SPY" else 0.0 for t in names]] * n, RL, s0)
    show("QQQ buy and hold", [[1.0 if t == "QQQ" else 0.0 for t in names]] * n, RL, s0)
    show("QQQ with S&P regime rule", [[1.0 if (t == "QQQ" and band[i]) else 0.0 for t in names] for i in range(n)], RL, s0)
    show("all 12 equal weight", [[1.0 / N] * N] * n, RL, s0)
    for lb in (126, 252):
        for k in (2, 3):
            for rg, ab, nm in ((None, False, "no filter"), (band, False, "S&P regime"), (None, True, "own 200-day")):
                show(f"top {k} by {lb // 21}m, {nm}", rot(names, lb, k, rg, ab), RL, s0)
    # 3b crypto
    cn = [t for t in CRY if have(t)]
    if len(cn) == 2:
        L += ["", "== 3b. WITH BTC AND ETH ADDED (2018-now), against the same rules without crypto over the same dates ==", B2.TAB]
        s2 = next(i for i, d in enumerate(days) if d >= d0(2018, 1, 2)); u2 = names + cn; RL2 = [R(t) for t in u2]
        for lb, k in ((126, 3), (252, 3)):
            for rg, ab, nm in ((band, False, "S&P regime"), (None, True, "own 200-day")):
                L.append(B2.row(f"top {k} by {lb // 21}m, {nm}, NO crypto", B2.run_w(rot(names, lb, k, rg, ab), RL, cash, s2, n)))
                L.append(B2.row(f"top {k} by {lb // 21}m, {nm}, WITH crypto", B2.run_w(rot(u2, lb, k, rg, ab), RL2, cash, s2, n)))
        L.append(B2.row("BTC buy and hold", B2.run_w([[1.0 if t == "BTC-USD" else 0.0 for t in u2]] * n, RL2, cash, s2, n)))
    # ---- 4 volume test
    def vt_at(t, i):
        dv = [(pr[t][j] or 0) * (vl[t][j] or 0) for j in range(i - 249, i + 1)]; a250 = sum(dv) / 250
        return (sum(dv[-20:]) / 20) / a250 if a250 > 0 else None
    ex_v = []; ex_m = []
    for i in range(max(s0, 260), n - 22):
        if B2.days_m[i] == B2.days_m[i + 1]: continue
        j = next((q for q in range(i + 1, n) if B2.days_m[q] != B2.days_m[i + 1]), None)
        if j is None: break
        fw = {t: pr[t][j] / pr[t][i] - 1 for t in names if pr[t][i] and pr[t][j]}
        if len(fw) < 10: continue
        avg = sum(fw.values()) / len(fw); vtv = {t: vt_at(t, i) for t in fw}; vtv = {t: v for t, v in vtv.items() if v}
        mom = {t: pr[t][i] / pr[t][i - 126] - 1 for t in fw if pr[t][i - 126]}
        if len(vtv) >= 10: ex_v.append(sum(fw[t] for t in sorted(vtv, key=lambda x: -vtv[x])[:3]) / 3 - avg)
        if len(mom) >= 10: ex_m.append(sum(fw[t] for t in sorted(mom, key=lambda x: -mom[x])[:3]) / 3 - avg)
    L += ["", "== 4. VOLUME TEST: top 3 funds by signal vs the average fund over the NEXT month =="]
    for lab, ex in (("top 3 by dollar-volume trend (20d vs 250d)", ex_v), ("top 3 by 6-month momentum", ex_m)):
        if len(ex) > 12:
            m = S.mean(ex); se = S.stdev(ex) / math.sqrt(len(ex)); L.append(f"  {lab}: {len(ex)} months, mean excess {m * 100:+.2f}%/month, hit rate {100 * sum(x > 0 for x in ex) / len(ex):.0f}%, t-stat {m / se:+.1f}  (|t| below 2 = indistinguishable from chance)")
    top = sorted(((ret(t, 126) or -999, ret(t, 252) or -999, t) for t in names + cn), reverse=True)[:3]
    L += ["", "LIVE: top 3 by 6-month return now: " + ", ".join(f"{NAMES[t]} ({a:+.0f}% 6m)" for a, b, t in top) + f". Stock regime {'IN' if band[-1] else 'OUT'}.",
          "", "Read: a rotation rule only matters if it beats QQQ with the regime rule (or SPY) in BOTH halves with a similar or lower drawdown; ETF history is short and covers few regimes. Crypto rows begin in 2018 only."]
    t = "\n".join(L); open(os.path.join(OUT, "stocks2c_summary.txt"), "w").write(t + "\n"); print(t)

if __name__ == "__main__":
    main()
