#!/usr/bin/env python3
"""Lab 38: PORTFOLIO SIMULATION OF THE LIVE SWING SCANNER RULES. Lab 37 showed the trigger beats random days in an event study; this lab asks what an account following the rules would actually have done, and whether it beats just holding BTC or ETH while BTC is IN.
Signal (mirrors swing_scan.py): close crosses ABOVE the coin's 50-day average while above its 200-day, day's volume >= 1.5x its 20-day average, same coin not re-signalled within 14 days (silent signals count for the 14 days). Alert only when BTC is IN (BTC above its 200d and 50d at that close).
Account rules: start 1.0; max 5 open positions (if more signals than slots, highest volume multiple first); each position sized so a close at the 50-day stop loses 1% of current equity, capped at 25% of equity and at available cash; exit at the first close below the coin's 50-day average; cost 0.1% of value per side; positions marked to market every day.
Rows:
  S1 live rules, enter at the signal close
  S2 same, but enter at the NEXT day's close (delay test: an alert is acted on a day late)
  S3 = S1 and also exit when BTC turns OUT
  S4 = S1 with fixed 20% of equity per position instead of risk sizing
  S5 PLACEBO: same exits and sizing, but entries are RANDOM coins (already above their 50d and 200d) on random BTC-IN days, at the same average signal rate; 30 random seeds, shows median and 10th-90th percentile of final value. If S1 is not clearly above this range, the volume cross adds nothing beyond 'a coin in an uptrend while BTC is IN'.
  Benchmarks, same dates and costs: BTC held only while BTC IN, ETH held only while BTC IN, BTC buy&hold.
Output per row: final value x, worst drawdown, H1 x, H2 x (halves of history), trades, win%, average and median trade after costs, average days held, share of days with a position, and for S1-S4 the share of total profit that came from the best 3 trades.
SURVIVORSHIP: universe is today's top 100; every row is flattered by it and the entry rows are probably flattered more. SELECTION: 37 labs on the same data. Writes lab38_summary.txt."""
import os, random, statistics as S
import scanner
import backtest_lab36 as L36
import backtest_lab37 as L37

OUT = scanner.HERE
CT = L36.CT; fd = L36.fd; metrics = L36.metrics
MAXOPEN = 5; RISK = 0.01; CAP = 0.25; GAP = 14; VOLX = 1.5

def main(data=None):
    if data is None:
        syms = [s for s in scanner.top100() if s != "BTC"]; data = L36.load(["BTC"] + syms)
    assert "BTC" in data, "BTC history missing"
    days, n, coins, C, V, M50, M200, VM, R90 = L37.prep(data)
    bt = C["BTC"]
    btin = [M200["BTC"][i] is not None and bt[i] > M200["BTC"][i] and bt[i] > M50["BTC"][i] for i in range(n)]
    ncov = [sum(1 for s in coins if M200[s][i] is not None) for i in range(n)]
    i0 = next(i for i in range(n) if ncov[i] >= 20); split = (i0 + n) // 2
    px = lambda s, i: C[s][i]
    up = lambda s, i: M200[s][i] is not None and M50[s][i] is not None and C[s][i] is not None and C[s][i] > M200[s][i] and C[s][i] > M50[s][i]

    # live signals by day (mirrors swing_scan.py): cross + volume + GAP, then alert only if BTC IN
    sig = {}; last = {}
    for i in range(i0, n - 1):
        for s in coins:
            if M200[s][i] is None or M50[s][i] is None or M50[s][i - 1] is None or C[s][i] is None or C[s][i - 1] is None: continue
            if not (C[s][i] > M50[s][i] and C[s][i - 1] <= M50[s][i - 1] and C[s][i] > M200[s][i]): continue
            if not (VM[s][i] and V[s][i] and V[s][i] >= VOLX * VM[s][i]): continue
            if i - last.get(s, -99) < GAP: continue
            last[s] = i
            if btin[i]: sig.setdefault(i, []).append((s, V[s][i] / VM[s][i]))
    nsig = sum(len(v) for v in sig.values()); btin_days = sum(1 for i in range(i0, n - 1) if btin[i])
    rate = nsig / max(1, btin_days)

    def simulate(signals, delay=0, btc_exit=False, fixed=None):
        cash = 1.0; pos = {}; curve = [1.0]; trades = []; h1 = h2 = None; days_pos = 0; eq_prev = 1.0
        for i in range(i0, n):
            # exits at this close
            for s in list(pos):
                p = pos[s]
                if i <= p["i"]: continue
                c = px(s, i)
                if c is None: continue
                if (M50[s][i] is not None and c < M50[s][i]) or (btc_exit and not btin[i]):
                    proceeds = p["u"] * c * (1 - CT); cash += proceeds
                    trades.append(dict(coin=s, ret=proceeds / p["cost"] - 1, pnl=proceeds - p["cost"], held=i - p["i"])); del pos[s]
            eq = cash + sum(p["u"] * (px(s, i) or p["last"]) for s, p in pos.items())
            for s, p in pos.items():
                if px(s, i): p["last"] = px(s, i)
            # entries at this close: signals from day i-delay
            todo = sorted(signals.get(i - delay, []), key=lambda x: -x[1])
            for s, vx in todo:
                if len(pos) >= MAXOPEN or s in pos or px(s, i) is None or M50[s][i] is None: continue
                c = px(s, i); risk = (c - M50[s][i]) / c
                if risk <= 0: continue
                frac = fixed if fixed else min(RISK / risk, CAP)
                value = min(frac * eq, cash / (1 + CT))
                if value <= 1e-9: continue
                cost = value * (1 + CT); cash -= cost; pos[s] = dict(u=value / c, cost=cost, i=i, last=c)
            eq = cash + sum(p["u"] * (px(s, i) or p["last"]) for s, p in pos.items())
            if i < n - 1 or True:
                curve.append(eq); days_pos += bool(pos)
            if i == split - 1: h1 = eq
            eq_prev = eq
        h1 = h1 or 1.0
        res = dict(final=curve[-1], dd=metrics(curve), h1=h1, h2=curve[-1] / h1, trades=trades, inpos=100 * days_pos / (n - i0))
        return res

    def bench(asset, sel):
        eq = 1.0; curve = [1.0]; prev = 0.0; h1 = None; inm = 0
        for i in range(i0, n):
            w = 1.0 if sel(i - 1) else 0.0   # decided at close i-1, earns day i
            r = w * (C[asset][i] / C[asset][i - 1] - 1) if C[asset][i] and C[asset][i - 1] else 0.0
            r -= CT * abs(w - prev); prev = w; eq *= 1 + r; curve.append(eq); inm += w > 0
            if i == split - 1: h1 = eq
        h1 = h1 or 1.0
        return dict(final=curve[-1], dd=metrics(curve), h1=h1, h2=curve[-1] / h1, trades=[], inpos=100 * inm / (n - i0))

    btc_sel = lambda i: btin[i]
    bh_sel = lambda i: True

    out = [f"LAB 38: PORTFOLIO SIMULATION OF THE LIVE SWING RULES  data {fd(days[0])} to {fd(days[-1])}; {len(coins)} coins; account starts {fd(days[i0])}, halves split at {fd(days[split])}",
           f"Live-rule signals while BTC IN: {nsig} over {btin_days} BTC-IN days ({rate:.3f} per day). Max {MAXOPEN} open, 1% risk to the 50-day, 25% cap, 0.1% cost per side.", ""]
    hdr = f"{'row':<46}{'final x':>8}{'worst DD%':>10}{'H1 x':>7}{'H2 x':>7}{'trades':>7}{'win%':>6}{'avg%':>7}{'med%':>7}{'days':>6}{'in-pos%':>8}{'top3 share%':>12}"
    out += [hdr]
    def line(nm, r):
        t = r["trades"]
        if t:
            rt = [x["ret"] for x in t]; tot = sum(x["pnl"] for x in t); top = sum(sorted((x["pnl"] for x in t), reverse=True)[:3])
            tail = f"{len(t):>7}{100 * sum(x > 0 for x in rt) / len(rt):>6.0f}{S.mean(rt) * 100:>7.1f}{S.median(rt) * 100:>7.1f}{S.mean(x['held'] for x in t):>6.0f}{r['inpos']:>8.0f}{(100 * top / tot if tot > 0 else float('nan')):>12.0f}"
        else:
            tail = f"{'':>7}{'':>6}{'':>7}{'':>7}{'':>6}{r['inpos']:>8.0f}{'':>12}"
        out.append(f"{nm:<46}{r['final']:>8.2f}{r['dd']:>10.0f}{r['h1']:>7.2f}{r['h2']:>7.2f}" + tail)
    R = {"S1 live rules, enter at signal close": simulate(sig),
         "S2 enter at NEXT day's close": simulate(sig, delay=1),
         "S3 = S1 + exit when BTC turns OUT": simulate(sig, btc_exit=True),
         "S4 = S1, fixed 20% per position": simulate(sig, fixed=0.20)}
    for nm, r in R.items(): line(nm, r)
    # placebo
    finals = []; h2s = []
    pool_days = [i for i in range(i0, n - 1) if btin[i]]
    for seed in range(30):
        rng = random.Random(3800 + seed); rs = {}
        for i in pool_days:
            if rng.random() < rate:
                cand = [s for s in coins if up(s, i)]
                if cand: rs.setdefault(i, []).append((rng.choice(cand), 1.0))
        r = simulate(rs); finals.append(r["final"]); h2s.append(r["h2"])
    finals.sort(); h2s.sort()
    out.append(f"{'S5 PLACEBO random uptrend coins, 30 seeds':<46}{S.median(finals):>8.2f}  median; 10th-90th pct {finals[3]:.2f} to {finals[26]:.2f}; H2 median {S.median(h2s):.2f} ({h2s[3]:.2f} to {h2s[26]:.2f})")
    out += ["", "BENCHMARKS (same dates, same cost per unit traded)"]
    line("BTC held only while BTC IN", bench("BTC", btc_sel))
    if "ETH" in C: line("ETH held only while BTC IN", bench("ETH", btc_sel))
    line("BTC buy&hold", bench("BTC", bh_sel))
    s1 = R["S1 live rules, enter at signal close"]
    out += ["", "Read:",
            "- S1 vs S5: if S1 is not clearly above the placebo range, the volume cross adds nothing beyond 'coin in an uptrend while BTC is IN'.",
            "- S1 vs the BTC/ETH benchmarks in BOTH halves, and in drawdown: the scanner is only worth running if it beats simply holding BTC or ETH while BTC is IN.",
            "- S2 shows how much a one-day delay costs. top3 share close to 100 means a few trades carry the whole result.",
            "SURVIVORSHIP and 37 labs of selection both flatter these numbers. Treat as an upper bound. Not financial advice."]
    text = "\n".join(out); open(os.path.join(OUT, "lab38_summary.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
