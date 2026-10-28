#!/usr/bin/env python3
"""Lab 36: SWING SCANNER ON THE TOP-100 COINS. Does a 200/50-day trend filter (plus fresh-cross, volume and relative-strength conditions) work beyond BTC/ETH?
Universe: today's top 100 coins by market cap that trade as USDT pairs (scanner.top100(), minus coins with under 450 days of daily history). SURVIVORSHIP WARNING: these are coins that are in the top 100 TODAY, so dead and fallen coins are missing and every buy-and-hold number below is flattered.
Rules (all declared before running; all rows printed):
 PART A, portfolio of trend states (equal weight across coins that are IN; cash if none; signal at close i earns i+1, cost 0.1% per unit of turnover):
  A0 all coins IN when close > 200d and 50d average        A1 = A0 only while BTC is IN (BTC above its 200d and 50d)
  A2 = A0 but only coins with 90-day return above BTC's      A3 = A2 and BTC IN
  A4 = A3 but only the 10 coins with the best 90-day relative strength
  Baselines: equal-weight buy-and-hold of all coins (daily rebalanced, flattered by survivorship) and BTC buy-and-hold.
 PART B, event study of ENTRY triggers: event = close crosses above the 50-day average while above the 200-day (events within 14 days on the same coin dropped).
  B1 cross only | B2 cross + volume >= 1.5x its 20-day average | B3 = B2 + 90-day relative strength vs BTC > 0 | B4 = B3 + BTC IN | B5 = B1 + BTC IN.
  Each event: buy at that close, sell at the first close below the 50-day (round trip cost 0.2%); also the fixed 30-day forward return. Compared with 30-day forward returns from random coin-days (that had a 200-day average), 2000 draws, as a percentile.
  Because the same dates hit many coins at once, the number of distinct event dates is shown, and an average over dates (each date counts once).
Also split by halves of the history. Writes lab36_summary.txt."""
import os, time, random, statistics as S
import scanner, backtest as B
OUT = scanner.HERE; fd = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))
CT = 0.001; CR = 0.002

def sma(x, k):
    out = [None] * len(x); s = 0.0
    for i, v in enumerate(x):
        s += v
        if i >= k: s -= x[i - k]
        if i >= k - 1: out[i] = s / k
    return out

def load(syms):
    data = {}
    for s in syms:
        try: rows = B.hist_crypto(s, "1d", 2700)
        except Exception: rows = []
        if len(rows) >= 450: data[s] = {int(r[0] // 86400): (r[4], r[5]) for r in rows}
        else: print("skipped", s, len(rows))
    return data

def metrics(eq):
    pk = 0; dd = 0
    for x in eq: pk = max(pk, x); dd = min(dd, x / pk - 1)
    return dd * 100

def main(data=None):
    random.seed(36)
    if data is None:
        syms = [s for s in scanner.top100() if s != "BTC"]; data = load(["BTC"] + syms)
    assert "BTC" in data, "BTC history missing"
    days = sorted(data["BTC"]); n = len(days); idx = {d: i for i, d in enumerate(days)}
    coins = [s for s in data if s != "BTC"]
    C = {}; V = {}; M50 = {}; M200 = {}; VM = {}; R90 = {}
    for s in data:
        c = [data[s].get(d, (None, None)) for d in days]
        cl = []; vo = []; last = None
        for x in c:
            if x[0] is not None: last = x
            cl.append(last[0] if last else None); vo.append(last[1] if last else None)
        C[s] = cl; V[s] = vo
        ok0 = next((i for i, x in enumerate(cl) if x is not None), None)
        if ok0 is None: continue
        sub = cl[ok0:]; sm50 = [None] * ok0 + sma(sub, 50); sm200 = [None] * ok0 + sma(sub, 200); vm = [None] * ok0 + sma(vo[ok0:], 20)
        M50[s] = sm50; M200[s] = sm200; VM[s] = vm
        R90[s] = [None] * (ok0 + 90) + [cl[i] / cl[i - 90] - 1 for i in range(ok0 + 90, n)]
    bt = C["BTC"]; btin = [M200["BTC"][i] is not None and bt[i] > M200["BTC"][i] and bt[i] > M50["BTC"][i] for i in range(n)]
    isin = lambda s, i: M200[s][i] is not None and C[s][i] is not None and C[s][i] > M200[s][i] and C[s][i] > M50[s][i]
    RET = {s: [None] + [(C[s][i] / C[s][i - 1] - 1) if C[s][i] and C[s][i - 1] else None for i in range(1, n)] for s in data}
    ncov = [sum(1 for s in coins if M200[s][i] is not None) for i in range(n)]
    i0 = next(i for i in range(n) if ncov[i] >= 20); split = (i0 + n) // 2
    L = [f"LAB 36: TOP-100 SWING SCANNER  data {fd(days[0])} to {fd(days[-1])}; {len(coins)} coins with 450+ days; portfolio tests start {fd(days[i0])} (20+ coins have a 200-day average), halves split at {fd(days[split])}",
         "SURVIVORSHIP: only coins that are in the top 100 today. Dead coins are missing, so baselines and also trend rows look better than a real-time scan would have.", ""]
    # ---------- Part A
    def sim(sel, ct=CT):
        eq = 1.0; curve = [1.0]; prev = {}; h1 = h2 = 1.0; held = []; inm = 0
        for i in range(i0, n - 1):
            w = sel(i); cnt = len(w); r = 0.0; newprev = {}
            for s in w:
                x = RET[s][i + 1]; r += (x or 0.0) / cnt; newprev[s] = 1.0 / cnt
            turn = sum(abs(newprev.get(s, 0) - prev.get(s, 0)) for s in set(newprev) | set(prev))
            r -= ct * turn; eq *= 1 + r; curve.append(eq); prev = newprev; held.append(cnt); inm += cnt > 0
            if i + 1 < split: h1 *= 1 + r
            else: h2 *= 1 + r
        return eq, metrics(curve), h1, h2, S.mean(held), 100 * inm / len(held)
    base_in = lambda i: [s for s in coins if isin(s, i)]
    def rs_ok(s, i): return R90[s][i] is not None and R90["BTC"][i] is not None and R90[s][i] > R90["BTC"][i]
    A = {"A0 trend coins": lambda i: base_in(i),
         "A1 trend coins, BTC IN only": lambda i: base_in(i) if btin[i] else [],
         "A2 trend + beating BTC (90d)": lambda i: [s for s in base_in(i) if rs_ok(s, i)],
         "A3 = A2, BTC IN only": lambda i: [s for s in base_in(i) if rs_ok(s, i)] if btin[i] else [],
         "A4 = A3, best 10 by 90d strength": lambda i: sorted([s for s in base_in(i) if rs_ok(s, i)], key=lambda s: -R90[s][i])[:10] if btin[i] else [],
         "BASE equal-weight buy&hold all coins": lambda i: [s for s in coins if C[s][i] and C[s][i - 1]],
         "BASE BTC buy&hold": lambda i: ["BTC"]}
    L.append("PART A: PORTFOLIO"); L.append(f"{'row':<40}{'final x':>9}{'worst DD%':>11}{'H1 x':>8}{'H2 x':>8}{'avg held':>10}{'in-mkt%':>9}")
    for nm, f in A.items():
        e, d, h1, h2, ah, im = sim(f); L.append(f"{nm:<40}{e:>9.2f}{d:>11.0f}{h1:>8.2f}{h2:>8.2f}{ah:>10.1f}{im:>9.0f}")
    L.append("COST CHECK: same rows with ZERO trading cost (if these are far better, turnover/costs are what hurts; if not, the rule itself is the problem):")
    for nm in ("A0 trend coins", "A1 trend coins, BTC IN only", "A3 = A2, BTC IN only"):
        e, d, h1, h2, ah, im = sim(A[nm], 0.0); L.append(f"{nm + ' (no cost)':<40}{e:>9.2f}{d:>11.0f}{h1:>8.2f}{h2:>8.2f}{ah:>10.1f}{im:>9.0f}")
    to = []
    prevw = {}
    for i in range(i0, n - 1):
        w = A["A0 trend coins"](i); c = len(w); nw = {s: 1.0 / c for s in w} if c else {}
        to.append(sum(abs(nw.get(s, 0) - prevw.get(s, 0)) for s in set(nw) | set(prevw))); prevw = nw
    L.append(f"A0 turnover: average {S.mean(to) * 100:.1f}% of the portfolio traded per day = {S.mean(to) * 365 * 100:.0f}% per year; cost drag about {S.mean(to) * 365 * CT * 100:.0f} points per year.")
    # ---------- Part B
    def events(cond):
        ev = []
        for s in coins:
            last = -99
            for i in range(max(1, i0 - 100), n - 1):
                if M200[s][i] is None or M50[s][i] is None or M50[s][i - 1] is None or C[s][i] is None or C[s][i - 1] is None: continue
                if not (C[s][i] > M50[s][i] and C[s][i - 1] <= M50[s][i - 1] and C[s][i] > M200[s][i]): continue
                if i - last < 14 or not cond(s, i): continue
                last = i; ev.append((s, i))
        return ev
    def trade(s, i):
        j = i + 1
        while j < n and not (M50[s][j] is not None and C[s][j] is not None and C[s][j] < M50[s][j]): j += 1
        done = j < n; j = min(j, n - 1); return C[s][j] / C[s][i] - 1 - CR, j - i, done
    def f30(s, i): return C[s][i + 30] / C[s][i] - 1 - CR if i + 30 < n and C[s][i + 30] and C[s][i] else None
    pool = [(s, i) for s in coins for i in range(i0, n - 31) if M200[s][i] is not None and C[s][i] and C[s][i + 30]]
    allf = [f30(s, i) for s, i in pool]
    L += ["", "PART B: ENTRY EVENTS (buy at the cross close, sell at first close below the 50-day; fixed 30d forward return alongside)",
          f"reference: random coin-days with a 200-day average: avg 30d {S.mean(allf) * 100:.1f}%, win {100 * sum(x > 0 for x in allf) / len(allf):.0f}%  (n={len(allf)})", "",
          f"{'trigger':<34}{'events':>7}{'dates':>6}{'trade avg%':>11}{'median%':>9}{'win%':>6}{'days held':>10}{'30d avg%':>9}{'30d win%':>9}{'pctile':>7}{'by-date 30d%':>13}{'H1 30d%':>8}{'H2 30d%':>8}"]
    cond = {"B1 cross only": lambda s, i: True,
            "B2 cross + volume>=1.5x": lambda s, i: VM[s][i] and V[s][i] and V[s][i] >= 1.5 * VM[s][i],
            "B3 = B2 + beats BTC 90d": lambda s, i: VM[s][i] and V[s][i] and V[s][i] >= 1.5 * VM[s][i] and rs_ok(s, i),
            "B4 = B3 + BTC IN": lambda s, i: btin[i] and VM[s][i] and V[s][i] and V[s][i] >= 1.5 * VM[s][i] and rs_ok(s, i),
            "B5 = B1 + BTC IN": lambda s, i: btin[i]}
    for nm, cf in cond.items():
        ev = events(cf); tr = [trade(s, i) for s, i in ev]; fw = [(f30(s, i), i) for s, i in ev]; fv = [x for x, _ in fw if x is not None]
        if len(ev) < 3: L.append(f"{nm:<34}{len(ev):>7}  too few"); continue
        m = S.mean(fv); draws = [S.mean(random.sample(allf, len(fv))) for _ in range(2000)]; pc = 100 * sum(d < m for d in draws) / len(draws)
        bd = {}
        for x, i in fw:
            if x is not None: bd.setdefault(i, []).append(x)
        bydate = S.mean([S.mean(v) for v in bd.values()]) * 100
        h1 = [x for x, i in fw if x is not None and i < split]; h2 = [x for x, i in fw if x is not None and i >= split]
        rt = [t[0] for t in tr]
        L.append(f"{nm:<34}{len(ev):>7}{len(bd):>6}{S.mean(rt) * 100:>11.1f}{S.median(rt) * 100:>9.1f}{100 * sum(x > 0 for x in rt) / len(rt):>6.0f}{S.mean([t[1] for t in tr]):>10.0f}{m * 100:>9.1f}{100 * sum(x > 0 for x in fv) / len(fv):>9.0f}{pc:>7.0f}{bydate:>13.1f}{(S.mean(h1) * 100 if h1 else float('nan')):>8.1f}{(S.mean(h2) * 100 if h2 else float('nan')):>8.1f}")
    L += ["", "Read: PART A matters most. A trend filter is useful if it keeps a good share of the return with a much smaller worst drawdown than the equal-weight buy&hold, in BOTH halves; the BTC gate and relative-strength rows show whether those add anything (compare A0 vs A1 vs A2/A3). Trend rows and the baseline are both flattered by survivorship.",
          "PART B: 'pctile' = where the event average 30-day return falls among random coin-days (95+ = unusual, 50 = nothing, 5- = worse than random). 'dates' = distinct calendar days with events; when it is far below 'events', many coins fired together and the real evidence is the by-date column. A trigger that does not beat random at 30d, in both halves, is not worth an alert."]
    text = "\n".join(L); open(os.path.join(OUT, "lab36_summary.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
