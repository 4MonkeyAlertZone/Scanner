#!/usr/bin/env python3
"""Strategy lab 5: FAST signals. Do volume surges and a rising share of buyer-initiated ("taker buy") volume on 1-hour, 2-hour or 4-hour candles
catch a move early enough to still be profitable after costs? About 3 years of 1-hour candles with taker-buy volume (Binance.US) are built
into 2-hour and 4-hour candles. Every rule is compared with ordinary entries on the same timeframe (the "no skill" benchmark), split into an
older and a newer half of history, shown BEFORE and AFTER the 0.2% costs (fast trades pay costs more often), and sorted by how much the price
had already risen when the signal fired ("lateness", in ATRs). Writes lab5_summary.txt and lab5_results.csv."""
import csv, json, os, random, time
from bisect import bisect_right
from multiprocessing import Pool
import scanner, backtest as B, backtest_lab3 as L3, backtest_lab4 as L4

N_COINS = int(os.environ.get("LAB5_COINS", "60"))
NEED = int(os.environ.get("LAB5_HOURS", "26500"))          # about 3 years of 1-hour candles
TFS = (("1h", 1, 72), ("2h", 2, 60), ("4h", 4, 42))        # name, hours per candle, time limit in candles (3 / 5 / 7 days)
RULES = ("buy surge (volume 2x, buyers 58%+, green)", "buy surge + above 50-avg", "buying pressure building (3 candles)", "buy surge + 4H uptrend", "ANY CANDLE (benchmark)")
STOP_ATR, COOL, LOOK = 2.5, 12, 24
OUT = scanner.HERE
BTC = {}

def hist1h(sym):
    out, end = [], int(time.time() * 1000)
    while len(out) < NEED:
        k = json.loads(scanner.http(f"https://api.binance.us/api/v3/klines?symbol={sym}USDT&interval=1h&endTime={end}&limit=1000"))
        if not k: break
        out = [(x[0] / 1000, float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5]), float(x[9])) for x in k] + out
        end = int(k[0][0]) - 1
        if len(k) < 1000: break
    return B.clean(out)[:-1]

def agg(rows, k):
    """Build k-hour candles from 1-hour candles, only from complete bins."""
    if k == 1: return rows
    bins = {}
    for r in rows: bins.setdefault(int(r[0] // (3600 * k)), []).append(r)
    out = []
    for b in sorted(bins):
        g = bins[b]
        if len(g) < k: continue
        out.append((b * 3600 * k, g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[-1][4], sum(x[5] for x in g), sum(x[6] for x in g)))
    return out

def prep(m):
    I = L4.ind(m); n = len(m)
    v = [r[5] for r in m]; tb = [r[6] for r in m]
    I["tk"] = [tb[i] / v[i] if v[i] > 0 else 0.5 for i in range(n)]
    I["vr"] = [None] * n; I["tk3"] = [None] * n; I["tkb"] = [None] * n; I["v3"] = [None] * n
    for i in range(LOOK + 12, n):
        base = sum(v[i - LOOK:i]) / LOOK
        if base <= 0: continue
        I["vr"][i] = v[i] / base
        s3 = sum(v[i - 2:i + 1]); I["v3"][i] = (s3 / 3) / base
        if s3 > 0: I["tk3"][i] = sum(tb[i - 2:i + 1]) / s3
        pv = sum(v[i - 14:i - 2]); I["tkb"][i] = sum(tb[i - 14:i - 2]) / pv if pv > 0 else None
    return I

def trendflags(m4, I4):
    """Per 4H candle: (uptrend 20>50 and above 50, above 200-avg)."""
    out = []
    for i in range(len(m4)):
        c, a, b, d = I4["c"][i], I4["s20"][i], I4["s50"][i], I4["s200"][i]
        out.append((a is not None and b is not None and a > b and c > b, d is not None and c > d))
    return out

def btc_setup():
    m = agg(hist1h("BTC"), 4); I = L4.ind(m)
    BTC["start"] = [r[0] for r in m]; BTC["fl"] = trendflags(m, I)

def lookup(starts, flags, t_close):
    j = bisect_right(starts, t_close - 4 * 3600) - 1       # last 4H candle that has already closed
    return flags[j] if j >= 0 else (False, False)

def coin(tok):
    try:
        base = hist1h(tok)
        if len(base) < 6000: return tok, [], "not on Binance.US or too little history"
        c1 = [r[4] for r in base]
        if max(c1) / min(c1) < 1.3: return tok, [], "pegged coin, skipped"
        m4 = agg(base, 4); I4 = prep(m4); f4 = trendflags(m4, I4); s4 = [r[0] for r in m4]
        rows = []; rnd = random.Random(tok)
        for ti, (tn, hrs, hor) in enumerate(TFS):
            m = agg(base, hrs); I = prep(m); n = len(m); nxt = [0] * 4
            for i in range(260, n - hor - 2):
                a = I["atr"][i]; vr = I["vr"][i]
                if a is None or vr is None or a <= 0: continue
                e = m[i + 1][1]; stop = e - STOP_ATR * a
                if stop <= 0 or stop >= e: continue
                tclose = m[i][0] + hrs * 3600
                up4, g200 = lookup(s4, f4, tclose)
                c = I["c"][i]; tk = I["tk"][i]
                sig = []
                surge = vr >= 2 and tk >= 0.58 and c > m[i][1]
                if surge: sig.append(0)
                if surge and I["s50"][i] is not None and c > I["s50"][i]: sig.append(1)
                if I["tk3"][i] is not None and I["tkb"][i] is not None and I["s20"][i] is not None and I["v3"][i] >= 1.3 and I["tk3"][i] >= 0.55 and I["tk3"][i] > I["tkb"][i] + 0.03 and c > I["s20"][i]: sig.append(2)
                if surge and up4: sig.append(3)
                bench = i % 6 == 0
                if not sig and not bench: continue
                lad = L3.ladder(e, stop, [r[:6] for r in m[i + 1:i + 1 + hor]])
                if not lad: continue
                risk = e - stop; costR = B.COST * e / risk
                late = (c - min(r[3] for r in m[i - LOOK:i])) / a
                rec = lambda k: (tok, int(m[i][0]), ti, k, int(g200), round(lad["ladder"], 4), round(costR, 4), round(late, 2))
                for k in sig:
                    if i >= nxt[k]: nxt[k] = i + COOL; rows.append(rec(k))
                if bench: rows.append(rec(4))
        return tok, rows, ""
    except Exception as ex:
        return tok, [], str(ex)[:80]

stat, f_acc = L4.stat, L4.f_acc

def summarise(rows, errs):
    ep = sorted(r[1] for r in rows); cut = ep[len(ep) // 2]
    L = []; res = []
    L.append(f"{len(rows)} entries, {len({r[0] for r in rows})} coins; era 1 = before {time.strftime('%Y-%m-%d', time.gmtime(cut))}, era 2 = after. R = profit in units of risk (stop 2.5 ATR of that candle size), sell a third at 1x/2x/3x risk, 0.2% round-trip costs. 'gross' = before costs.")
    if errs: L.append("skipped: " + "; ".join(f"{t} ({e})" for t, e in errs[:10]) + (" ..." if len(errs) > 10 else ""))
    L.append("")
    L.append("A. EACH RULE ON EACH TIMEFRAME. edge = rule net average minus the benchmark's on the same timeframe. HOLDS = n>=60 in both eras, net average above zero and above the benchmark in both eras.")
    for ti, (tn, hrs, hor) in enumerate(TFS):
        bench = [r for r in rows if r[2] == ti and r[3] == 4]
        bm = L3.mean_ci(stat([r[5] for r in bench]))[0]
        L.append(f"  {tn} candles (time limit {hor} candles). Benchmark: {f_acc([r[5] for r in bench])}, typical cost drag {sorted(r[6] for r in bench)[len(bench) // 2]:.2f}R per trade" if bench else f"  {tn}: no data")
        for k in range(4):
            sel = [r for r in rows if r[2] == ti and r[3] == k]
            if not sel: continue
            net = [r[5] for r in sel]; gross = [r[5] + r[6] for r in sel]
            parts = []; ok = True
            for era in (0, 1):
                xs = [r[5] for r in sel if (r[1] >= cut) == bool(era)]; bs = [r[5] for r in bench if (r[1] >= cut) == bool(era)]
                a = stat(xs); mu = L3.mean_ci(a)[0]; mb = L3.mean_ci(stat(bs))[0]
                parts.append(f"era{era + 1} n={a[0]:>4} {mu:+.2f}R vs {mb:+.2f}R")
                ok = ok and a[0] >= 60 and mu > 0 and mu > mb
            mu = L3.mean_ci(stat(net))[0]
            L.append(f"     {RULES[k]:42} net {f_acc(net)}  gross {L3.mean_ci(stat(gross))[0]:+.2f}R  edge {mu - bm:+.2f}R | {' | '.join(parts)}{'  <-- HOLDS' if ok else ''}")
            res.append(dict(tf=tn, rule=RULES[k], n=len(sel), net_R=round(mu, 3), gross_R=round(L3.mean_ci(stat(gross))[0], 3), bench_R=round(bm, 3), holds=int(ok)))
    L.append("")
    L.append("B. LATENESS. How far price had already risen from its lowest low of the last 24 candles when the signal fired (in ATRs). Signals of rules 1-4 pooled per timeframe, split into thirds: early / middle / late.")
    for ti, (tn, hrs, hor) in enumerate(TFS):
        sel = sorted((r for r in rows if r[2] == ti and r[3] < 4), key=lambda r: r[7])
        if len(sel) < 30: continue
        t = len(sel) // 3; parts = (sel[:t], sel[t:2 * t], sel[2 * t:])
        L.append(f"  {tn}: " + " | ".join(f"{nm} (rise {p[0][7]:.1f}-{p[-1][7]:.1f} ATR) {f_acc([r[5] for r in p])}" for nm, p in zip(("EARLY", "MIDDLE", "LATE"), parts)))
    L.append("")
    L.append("C. DOES THE BTC TREND MATTER? Same rules, split by whether BTC (4H) was above its own 200-candle average when the signal fired. Benchmark in same split.")
    for ti, (tn, hrs, hor) in enumerate(TFS):
        for k in list(range(4)) + [4]:
            sel = [r for r in rows if r[2] == ti and r[3] == k]
            if not sel: continue
            L.append(f"  {tn} {RULES[k]:42} BTC above 200-avg: {f_acc([r[5] for r in sel if r[4]])} | below: {f_acc([r[5] for r in sel if not r[4]])}")
    L.append("")
    L.append("D. HOW TO READ: only a line marked HOLDS in A is worth a live paper test. Compare 'gross' with 'net': a rule that only works before costs is not tradable. Entries overlap in time and across coins, so true error margins are wider than printed. Only coins listed on Binance.US and in today's top list are included (survivorship bias). About 3 years is a single market cycle phase mix, so treat results as hints.")
    return "\n".join(L), res

def main():
    btc_setup()
    print(f"BTC 4H candles: {len(BTC['start'])}", flush=True)
    coins = [c for c in scanner.top100() if c != "BTC"][:N_COINS]
    print(f"Testing 4 fast rules + benchmark on 3 timeframes, {len(coins)} coins...", flush=True)
    with Pool(3) as p: res = p.map(coin, coins)
    rows = [r for _, rs, _ in res for r in rs]; errs = [(t, e) for t, _, e in res if e]
    if not rows: text, results = "No entries found. " + str(errs[:3]), []
    else:
        text, results = summarise(rows, errs)
        text = B.coverage([dict(market="crypto", epoch=r[1]) for r in rows]) + "\n" + text
    if results:
        with open(os.path.join(OUT, "lab5_results.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, list(results[0].keys())); w.writeheader(); w.writerows(results)
    with open(os.path.join(OUT, "lab5_summary.txt"), "w") as f: f.write(text + "\n")
    print("\n" + text)
    try: scanner.notify("Strategy lab 5 finished", "Fast-signal lab done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
