#!/usr/bin/env python3
"""Strategy lab 6: the traders' chart idea, tested as rules. Reading ~12 of Gauls' chart images, the same picture came up again and again on 4-hour charts:
a coin that has dropped, spent days in a base (range), and now climbs back above its 50-period average (EMA50) and/or above the middle of the range
(roughly the volume point of control), with the stop just under the range low and the target above. Rules tested on about 3 years of 4H candles, 60 coins:
  EMA50 reclaim:  closes back above its EMA50 after spending most of the last 30 candles below it
  range-mid reclaim: after sitting in the lower third of a 60-candle range (range at least 15% tall), closes back above the middle of that range
  both together
Two stops: just under the 40-candle low (his style, tight; skipped if that is less than 1% or more than 12% away) or 2.5 ATR. Sell a third at 1x, 2x and 3x risk.
Every rule is compared with random entries on the same coins with the same stop and target distances, split into older and newer halves of history,
and split by whether BTC was above its 200-candle average. Writes lab6_summary.txt and lab6_results.csv."""
import csv, os, random
from bisect import bisect_right
from multiprocessing import Pool
import scanner, backtest as B, backtest_lab3 as L3, backtest_lab4 as L4

N_COINS = int(os.environ.get("LAB6_COINS", "60"))
MONTHS = int(os.environ.get("LAB6_MONTHS", "36"))
HORS = (42, 84)
RULES = ("EMA50 reclaim", "range-mid reclaim", "both together", "ANY CANDLE (benchmark)")
STOPS = ("range-low stop (his style)", "2.5 ATR stop")
OUT = scanner.HERE
BTC = {}
GATES = (("4H 50-avg (about 8 days)", 50), ("4H 100-avg (about 17 days)", 100), ("4H 200-avg (about 33 days)", 200), ("4H 600-avg (about 100 days)", 600), ("4H 1200-avg (about 200 days)", 1200))

def ema(c, k):
    a = 2 / (k + 1); out = [c[0]]
    for x in c[1:]: out.append(out[-1] + a * (x - out[-1]))
    return out

def btc_setup():
    m = B.hist_crypto("BTC", "4h", MONTHS * 180 + 520); I = L4.ind(m)
    c = [r[4] for r in m]; pre = [0.0]
    for x in c: pre.append(pre[-1] + x)
    def above(i, k): return int(i >= k - 1 and c[i] > (pre[i + 1] - pre[i + 1 - k]) / k)
    BTC["ep"] = [r[0] for r in m]; BTC["g"] = [tuple(above(i, k) for _, k in GATES) for i in range(len(m))]

def coin(tok):
    try:
        m = B.hist_crypto(tok, "4h", MONTHS * 180 + 520)
        if len(m) < 600: return tok, [], "not enough history"
        c = [r[4] for r in m]
        if max(c) / min(c) < 1.3: return tok, [], "pegged coin, skipped"
        I = L4.ind(m); E = ema(c, 50); hi = [r[2] for r in m]; lo = [r[3] for r in m]
        n = len(m); Hmax = max(HORS); first = max(260, n - Hmax - 2 - MONTHS * 180); rnd = random.Random(tok); rows = []; nxt = [0, 0, 0]
        for i in range(first, n - Hmax - 2):
            a = I["atr"][i]
            if a is None or a <= 0: continue
            below = sum(1 for k in range(i - 30, i) if c[k] < E[k])
            r1 = below >= 20 and c[i - 1] <= E[i - 1] and c[i] > E[i]
            lo60, hi60 = min(lo[i - 60:i]), max(hi[i - 60:i]); mid = (lo60 + hi60) / 2; third = lo60 + (hi60 - lo60) / 3
            r2 = hi60 / lo60 > 1.15 and min(c[i - 10:i]) <= third and c[i - 1] <= mid and c[i] > mid
            sig = [k for k, f in ((0, r1), (1, r2), (2, r1 and r2)) if f and i >= nxt[k]]
            bench = i % 6 == 0
            if not sig and not bench: continue
            e = m[i + 1][1]; j = max(0, __import__("bisect").bisect_right(BTC["ep"], m[i][0]) - 1); g = BTC["g"][j]
            stops = {0: min(lo[i - 39:i + 1]) * 0.998, 1: e - 2.5 * a}
            for si, st in stops.items():
                if st <= 0 or st >= e: continue
                rp = (e - st) / e
                if si == 0 and not 0.01 <= rp <= 0.12: continue
                for h, H in enumerate(HORS):
                    lad = L3.ladder(e, st, m[i + 1:i + 1 + H])
                    if not lad: continue
                    cost = B.COST * e / (e - st)
                    # control: random entry on the same coin with the same stop distance (share of price) and the same time limit
                    ctl = []
                    for _ in range(3):
                        k = rnd.randrange(first, n - Hmax - 2); ek = m[k + 1][1]; r2_ = L3.ladder(ek, ek * (1 - rp), m[k + 1:k + 1 + H])
                        if r2_: ctl.append(r2_["ladder"])
                    cm = sum(ctl) / len(ctl) if ctl else 0.0
                    for k in (sig if sig else []):
                        rows.append((tok, int(m[i][0]), k, si, h, round(lad["ladder"], 4), round(cost, 4), g, round(cm, 4)))
                    if bench: rows.append((tok, int(m[i][0]), 3, si, h, round(lad["ladder"], 4), round(cost, 4), g, round(cm, 4)))
            for k in sig: nxt[k] = i + 12
        return tok, rows, ""
    except Exception as ex:
        return tok, [], str(ex)[:80]

def summarise(rows, errs):
    ep = sorted(r[1] for r in rows); cut = ep[len(ep) // 2]
    L = [f"{len(rows)} entries, {len({r[0] for r in rows})} coins; era 1 = before {__import__('time').strftime('%Y-%m-%d', __import__('time').gmtime(cut))}, era 2 = after. R = profit in units of risk after 0.2% costs; a third sold at 1x, 2x, 3x risk; time limit 7 or 14 days."]
    if errs: L.append("skipped: " + "; ".join(f"{t} ({e})" for t, e in errs[:10]))
    L.append("")
    L.append("A. EACH RULE. 'random' = random entries on the same coins with the same stop distance (matched to each signal). edge = rule minus random. HOLDS = n>=60 in both eras, average above zero and above random in both eras.")
    res = []
    for si, sn in enumerate(STOPS):
        for h, H in enumerate(HORS):
            L.append(f"  {sn}, time limit {H} candles ({H // 6} days)")
            bm = [r for r in rows if r[2] == 3 and r[3] == si and r[4] == h]
            L.append(f"     benchmark (every 6th candle): {L4.f_acc([r[5] for r in bm])}")
            for k in range(3):
                sel = [r for r in rows if r[2] == k and r[3] == si and r[4] == h]
                if not sel: continue
                mu = L3.mean_ci(L4.stat([r[5] for r in sel]))[0]; mr = sum(r[8] for r in sel) / len(sel); gr = L3.mean_ci(L4.stat([r[5] + r[6] for r in sel]))[0]
                parts = []; ok = True
                for era in (0, 1):
                    xs = [r for r in sel if (r[1] >= cut) == bool(era)]
                    a = L3.mean_ci(L4.stat([r[5] for r in xs]))[0]; b = sum(r[8] for r in xs) / len(xs) if xs else 0
                    parts.append(f"era{era + 1} n={len(xs):>4} {a:+.2f}R vs {b:+.2f}R"); ok = ok and len(xs) >= 60 and a > 0 and a > b
                L.append(f"     {RULES[k]:20} {L4.f_acc([r[5] for r in sel])}  gross {gr:+.2f}R  random {mr:+.2f}R  edge {mu - mr:+.2f}R | {' | '.join(parts)}{'  <-- HOLDS' if ok else ''}")
                res.append(dict(rule=RULES[k], stop=sn, horizon=H, n=len(sel), net_R=round(mu, 3), random_R=round(mr, 3), holds=int(ok)))
    L.append("")
    L.append("B. WHICH BTC TREND FILTER HELPS? Entries with the range-low stop and 7-day limit, split by whether BTC was above its moving average (4H candles) when the signal fired. 'share' = how often BTC was above it (benchmark entries).")
    for k in range(4):
        L.append(f"  {RULES[k]}")
        for gi, (gn, _) in enumerate(GATES):
            sel = [r for r in rows if r[2] == k and r[3] == 0 and r[4] == 0]
            if not sel: continue
            bm = [r for r in rows if r[2] == 3 and r[3] == 0 and r[4] == 0]
            sh = sum(r[7][gi] for r in bm) / len(bm) * 100 if bm else 0
            ab = [r[5] for r in sel if r[7][gi]]; be = [r[5] for r in sel if not r[7][gi]]
            e1 = [r[5] for r in sel if r[7][gi] and r[1] < cut]; e2 = [r[5] for r in sel if r[7][gi] and r[1] >= cut]
            L.append(f"     BTC above {gn:30} above: {L4.f_acc(ab)} | below: {L4.f_acc(be)} | above, older half {L3.mean_ci(L4.stat(e1))[0]:+.2f}R, newer half {L3.mean_ci(L4.stat(e2))[0]:+.2f}R | BTC above it {sh:.0f}% of the time")
    L.append("")
    L.append("C. HOW TO READ: only a HOLDS line deserves a live paper test. The traders' charts also use a volume profile, trendlines and judgement that these simple definitions only approximate, so a failure here says the simple version has no edge, not that the trader has none. Entries overlap in time and across coins, so true error margins are wider than printed. Coins are the ones in today's top list (survivorship bias).")
    return "\n".join(L), res

def main():
    btc_setup()
    coins = [c for c in scanner.top100() if c != "BTC"][:N_COINS]
    print(f"Testing 3 chart-pattern rules on {len(coins)} coins...", flush=True)
    with Pool(max(1, os.cpu_count() or 1)) as p: res = p.map(coin, coins)
    rows = [r for _, rs, _ in res for r in rs]; errs = [(t, e) for t, _, e in res if e]
    if rows: text, results = summarise(rows, errs)
    else: text, results = "No entries found. " + str(errs[:3]), []
    if rows: text = B.coverage([dict(market="crypto", epoch=r[1]) for r in rows]) + "\n" + text
    if results:
        with open(os.path.join(OUT, "lab6_results.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, list(results[0].keys())); w.writeheader(); w.writerows(results)
    with open(os.path.join(OUT, "lab6_summary.txt"), "w") as f: f.write(text + "\n")
    print("\n" + text)
    try: scanner.notify("Strategy lab 6 finished", "Chart-pattern lab done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
