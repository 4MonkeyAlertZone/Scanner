#!/usr/bin/env python3
"""Strategy lab 4: DAILY candles over the longest history we can download (about 2018 to now, two full BTC cycles), crypto altcoins.
Questions: (1) do the simple rules behave differently in different phases of the BTC cycle? (2) does rising volume, or a rising share of
buyer-initiated volume ("taker buy"), make the signals better? Every rule is compared with entering on ordinary days with the same stop
distance (the "no skill" benchmark) in the SAME phase, and results are split into an older and a newer half of history, so a result that
only works in one half is visible. Writes lab4_summary.txt and lab4_results.csv."""
import csv, json, os, random, time
from multiprocessing import Pool
import scanner, backtest as B, backtest_lab3 as L3

N_COINS = int(os.environ.get("LAB4_COINS", "50"))
NEED = int(os.environ.get("LAB4_DAYS", "3300"))
STOP_ATR, HOR, COOL = 2.5, 20, 5
OUT = scanner.HERE
RULES = ("cross 20/50 above 200-avg", "cross 20/50 (any trend)", "breakout 20 + volume 1.5x", "pullback in uptrend (RSI<=40)", "ANY DAY (benchmark)")
PHASES = ("UP (above 200-avg, rising)", "TOPPING (above 200-avg, falling)", "DOWN (below 200-avg, falling)", "BASING (below 200-avg, rising)")
DDS = ("drawdown < 20%", "drawdown 20-50%", "drawdown > 50%")
BTC = {}
DAY = lambda t: int((t + 28800) // 86400)      # OKX daily bars open at 16:00 UTC, Binance at 00:00 UTC: both map to the same day number

def binance_daily(sym, need):
    out, end = [], int(time.time() * 1000)
    while len(out) < need:
        k = json.loads(scanner.http(f"https://api.binance.us/api/v3/klines?symbol={sym}USDT&interval=1d&endTime={end}&limit=1000"))
        if not k: break
        out = [(x[0] / 1000, float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5]), float(x[9])) for x in k] + out
        end = int(k[0][0]) - 1
        if len(k) < 1000: break
    return out

def history(sym, need):
    """Daily rows (t,o,h,l,c,v,taker_buy_or_None), oldest first. Binance.US where it has the coin (has taker volume); OKX fills older days."""
    rows = {}
    try:
        for r in B.clean(binance_daily(sym, need)): rows[DAY(r[0])] = r
    except Exception: pass
    if len(rows) < need * .9:
        try:
            for r in B.clean(B._okx(sym, "1d", need)): rows.setdefault(DAY(r[0]), r + (None,))
        except Exception: pass
    out = [rows[d] for d in sorted(rows)]
    return out[:-1]     # drop today's forming candle

def ind(m):
    n = len(m); c = [r[4] for r in m]; v = [r[5] for r in m]
    def sma(k): return [None if i < k - 1 else sum(c[i - k + 1:i + 1]) / k for i in range(n)]
    tr = [0.0] + [max(m[i][2] - m[i][3], abs(m[i][2] - c[i - 1]), abs(m[i][3] - c[i - 1])) for i in range(1, n)]
    atr = [None] * n
    for i in range(14, n): atr[i] = sum(tr[i - 13:i + 1]) / 14
    rsi = [None] * n; ag = al = 0.0
    for i in range(1, n):
        d = c[i] - c[i - 1]; g, l = max(d, 0), max(-d, 0)
        if i <= 14:
            ag += g / 14; al += l / 14
            if i == 14: rsi[i] = 100 - 100 / (1 + ag / al) if al else 100
        else:
            ag = (ag * 13 + g) / 14; al = (al * 13 + l) / 14
            rsi[i] = 100 - 100 / (1 + ag / al) if al else 100
    mv = lambda i, k: sum(v[i - k + 1:i + 1]) / k
    return dict(c=c, s20=sma(20), s50=sma(50), s200=sma(200), atr=atr, rsi=rsi, mv=mv)

def btc_setup():
    m = history("BTC", NEED + 100)
    I = ind(m); n = len(m); c = I["c"]
    st = {}
    for i in range(365, n):
        s2, s2p = I["s200"][i], I["s200"][i - 30]
        if s2 is None or s2p is None: continue
        up = s2 > s2p
        ph = (0 if up else 1) if c[i] > s2 else (3 if up else 2)
        dd = 1 - c[i] / max(c[i - 365:i + 1])
        db = 0 if dd < .2 else 1 if dd < .5 else 2
        vol = I["mv"](i, 5) / I["mv"](i, 30) > 1.0
        st[DAY(m[i][0])] = (ph, db, vol)
    BTC["state"] = st; BTC["m"] = m; BTC["I"] = I

def fire(I, i):
    c, s20, s50, s200, p20, p50 = I["c"][i], I["s20"][i], I["s50"][i], I["s200"][i], I["s20"][i - 1], I["s50"][i - 1]
    if None in (s20, s50, s200, p20, p50): return []
    out = []; x = s20 > s50 and p20 <= p50
    if x and c > s200: out.append(0)
    if x: out.append(1)
    hi = max(r for r in I["_h"][i - 20:i])
    if c > hi and I["vr"][i] >= 1.5: out.append(2)
    if I["rsi"][i] is not None and c > s200 and I["rsi"][i] <= 40: out.append(3)
    return out

def coin(tok):
    try:
        m = history(tok, NEED)
        if len(m) < 500: return tok, [], "not enough history"
        c = [r[4] for r in m]
        if max(c) / min(c) < 1.3: return tok, [], "pegged coin, skipped"
        I = ind(m); n = len(m); I["_h"] = [r[2] for r in m]
        I["vr"] = [None if i < 20 else m[i][5] / (sum(r[5] for r in m[i - 20:i]) / 20 or 1) for i in range(n)]
        rnd, rows, nxt = random.Random(tok), [], [0] * 4
        for i in range(230, n - HOR - 2):
            st = BTC["state"].get(DAY(m[i][0]))
            if st is None or I["atr"][i] is None: continue
            e = m[i + 1][1]; stop = e - STOP_ATR * I["atr"][i]
            if stop <= 0 or stop >= e: continue
            a = L3.ladder(e, stop, [r[:6] for r in m[i + 1:i + 1 + HOR]])
            if not a: continue
            volup = I["mv"](i, 5) / (I["mv"](i, 30) or 1) > 1.2
            tb = [r[6] for r in m[i - 4:i + 1]]
            tk = None if None in tb else (sum(tb) / (I["mv"](i, 5) * 5) > 0.52 if I["mv"](i, 5) else None)
            rec = lambda k: (tok, int(m[i][0]), k, st[0], st[1], st[2], round(a["ladder"], 4), int(volup), None if tk is None else int(tk))
            for k in fire(I, i):
                if i >= nxt[k]: nxt[k] = i + COOL; rows.append(rec(k))
            if i % 3 == 0: rows.append(rec(4))
        return tok, rows, ""
    except Exception as ex:
        return tok, [], str(ex)[:80]

def stat(xs):
    a = L3.new()
    for x in xs: L3.push(a, x)
    return a

def f_acc(xs): return L3.f_acc(stat(xs))

def summarise(rows, errs):
    ep = sorted(r[1] for r in rows); cut = ep[len(ep) // 2]
    yr = lambda t: int(time.strftime("%Y", time.gmtime(t)))
    L = []; res = []
    L.append(f"{len(rows)} entries across {len({r[0] for r in rows})} coins; era 1 = before {time.strftime('%Y-%m-%d', time.gmtime(cut))}, era 2 = after. R = profit in units of risk, sell a third at 1x/2x/3x risk, stop 2.5 ATR, 20-day limit, 0.2% costs.")
    if errs: L.append("skipped: " + "; ".join(f"{t} ({e})" for t, e in errs[:12]) + (" ..." if len(errs) > 12 else ""))
    L.append("")
    L.append("A. HOW OFTEN WAS BTC IN EACH PHASE (days) and what an ordinary-day altcoin entry earned (the benchmark)")
    bench = [r for r in rows if r[2] == 4]
    for p, name in enumerate(PHASES):
        xs = [r[6] for r in bench if r[3] == p]
        years = sorted({yr(r[1]) for r in bench if r[3] == p})
        L.append(f"  {name:36} {f_acc(xs)}   years seen: {years[0] if years else '-'}-{years[-1] if years else '-'}")
    L.append("")
    L.append("B. EACH RULE BY BTC PHASE. 'edge' = rule average minus benchmark average in the same phase. HOLDS = n>=40 in both eras, positive edge in both eras.")
    for k, rn in enumerate(RULES[:4]):
        L.append(f"  {rn}")
        for p, pn in enumerate(PHASES):
            allr = [r[6] for r in rows if r[2] == k and r[3] == p]
            if not allr: continue
            bm = [r[6] for r in bench if r[3] == p]
            parts = []; ok = True
            for era in (0, 1):
                xs = [r[6] for r in rows if r[2] == k and r[3] == p and (r[1] >= cut) == bool(era)]
                bs = [r[6] for r in bench if r[3] == p and (r[1] >= cut) == bool(era)]
                a, b = stat(xs), stat(bs)
                mu, mb = L3.mean_ci(a)[0], L3.mean_ci(b)[0]
                parts.append(f"era{era + 1} n={a[0]:>4} {mu:+.2f}R vs {mb:+.2f}R")
                ok = ok and a[0] >= 40 and b[0] >= 40 and mu - mb > 0
            mu = L3.mean_ci(stat(allr))[0]; mb = L3.mean_ci(stat(bm))[0]
            L.append(f"     {pn:36} all {f_acc(allr)}  edge {mu - mb:+.2f}R | {' | '.join(parts)} {'  <-- HOLDS' if ok else ''}")
            res.append(dict(rule=rn, phase=pn, n=len(allr), mean_R=round(mu, 3), bench_R=round(mb, 3), holds=int(ok)))
    L.append("")
    L.append("C. EACH RULE BY BTC DRAWDOWN FROM ITS 1-YEAR HIGH (all rules, average R; benchmark last)")
    for k, rn in enumerate(RULES):
        L.append(f"  {rn:34} " + " | ".join(f"{dn}: {f_acc([r[6] for r in rows if r[2] == k and r[4] == d])}" for d, dn in enumerate(DDS)))
    L.append("")
    L.append("D. EACH RULE BY YEAR (average R, n)")
    years = sorted({yr(r[1]) for r in rows})
    L.append("  " + " " * 34 + " ".join(f"{y:>12}" for y in years))
    for k, rn in enumerate(RULES):
        cells = []
        for y in years:
            a = stat([r[6] for r in rows if r[2] == k and yr(r[1]) == y])
            cells.append(f"{L3.mean_ci(a)[0]:+.2f}({a[0]})" if a[0] else "-")
        L.append(f"  {rn:34} " + " ".join(f"{c:>12}" for c in cells))
    L.append("")
    L.append("E. DOES VOLUME HELP? Same rules, split by (1) coin's volume rising (5-day avg > 1.2x its 30-day avg), (2) buyers dominating (taker-buy share > 52% over 5 days, Binance.US days only), (3) BTC's own volume rising. Benchmark in same split.")
    for k, rn in enumerate(RULES):
        sel = [r for r in rows if r[2] == k]
        L.append(f"  {rn}")
        for lab, f in (("coin volume rising", lambda r: r[7] == 1), ("coin volume NOT rising", lambda r: r[7] == 0),
                       ("buyers dominate", lambda r: r[8] == 1), ("sellers dominate", lambda r: r[8] == 0),
                       ("BTC volume rising", lambda r: r[5]), ("BTC volume falling", lambda r: not r[5])):
            L.append(f"     {lab:24} {f_acc([r[6] for r in sel if f(r)])}")
    L.append("")
    L.append("F. VERDICT RULES: only a line marked HOLDS in B (both eras, beats the benchmark in the same phase) deserves a live paper test. Entries overlap in time and across coins, so true error margins are wider than printed. Only coins in today's top list are included (survivorship bias). Phases rest on very few independent cycles, so treat any pattern here as a hint, not proof.")
    return "\n".join(L), res

def main():
    btc_setup()
    d = BTC["m"]; print(f"BTC daily history: {len(d)} days", flush=True)
    coins = [c for c in scanner.top100() if c != "BTC"][:N_COINS]
    print(f"Testing {len(RULES) - 1} rules + benchmark on {len(coins)} altcoins, daily...", flush=True)
    with Pool(3) as p: res = p.map(coin, coins)
    rows = [r for _, rs, _ in res for r in rs]; errs = [(t, e) for t, _, e in res if e]
    if not rows: text, results = "No entries found. " + str(errs[:3]), []
    else:
        text, results = summarise(rows, errs)
        text = B.coverage([dict(market="crypto", epoch=r[1]) for r in rows]) + "\n" + text
    if results:
        with open(os.path.join(OUT, "lab4_results.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, list(results[0].keys())); w.writeheader(); w.writerows(results)
    with open(os.path.join(OUT, "lab4_summary.txt"), "w") as f: f.write(text + "\n")
    print("\n" + text)
    try:
        import paper
        scanner.notify("Strategy lab 4 finished", "Cycle-phase lab done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
