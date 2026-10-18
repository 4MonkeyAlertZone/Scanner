#!/usr/bin/env python3
"""Strategy lab 17: does 'buy a coin after a very sharp drop' survive a harder look?
Lab 16 found edge on the 10 big alts, but (a) the coin list contains only survivors, (b) many trades come from the same crash days, (c) it did not work on BTC/ETH alone.
Here the idea is tested on three groups of coins: ranks 1-10 (large, least survivorship), 11-40, 41-99 (smaller, most survivorship). If the edge is mostly survivorship, it should grow as coins get smaller.
Drops of 8/12/16/20% over 2 days, holds 5 and 10 days, entry at the next open, 0.2% round-trip cost (LAB_SIDE per side), compared with random entries on the same coins.
For every line: trades (n), distinct signal DAYS (episodes), the average over episodes (days counted once, so one crash day does not count 30 times), older/newer half, and the same split by BTC regime and by
market-wide drop (BTC also fell 4%+ in the same 2 days) versus a coin-specific drop. Writes lab17_summary.txt."""
import os, time, random, math, calendar
from multiprocessing import Pool
import scanner, backtest as B
import backtest_lab16 as L16

START = L16.START; RT = L16.RT; fmt = L16.fmt

def stat(tr, rnd, imid, label, days):
    if len(tr) < 8: return f"   {label:<44} n={len(tr):>3}  too few trades"
    r = [x for _, x, _ in tr]; m = sum(r) / len(r) * 100; rm = sum(rnd) / len(rnd) * 100 if rnd else 0
    byday = {}
    for i, x, _ in tr: byday.setdefault(i, []).append(x)
    ep = [sum(v) / len(v) * 100 for v in byday.values()]; em = sum(ep) / len(ep)
    es = (sum((x - em) ** 2 for x in ep) / max(1, len(ep) - 1)) ** .5 / len(ep) ** .5 if len(ep) > 1 else 0
    a = [x for i, x, _ in tr if i < imid]; b = [x for i, x, _ in tr if i >= imid]
    f = lambda v: f"{sum(v) / len(v) * 100:+.1f}%" if v else " n/a"
    return f"   {label:<44} n={len(tr):>4} days={len(ep):>3}  trade avg {m:+5.1f}% vs random {rm:+4.1f}% (edge {m - rm:+5.1f}%) | by day {em:+5.1f}% (+/-{es:.1f}), edge {em - rm:+5.1f}% | older {f(a)}/newer {f(b)} ({len(a)}/{len(b)})"

def main():
    toks = [c for c in scanner.top100() if c not in ("BTC", "ETH")][:97]
    groups = [("ranks 1-10 (large)", toks[:10]), ("ranks 11-40", toks[10:40]), ("ranks 41-99 (small, most survivorship)", toks[40:])]
    with Pool(max(1, os.cpu_count() or 1)) as p: res = p.map(L16.load, ["BTC"] + toks)
    data = {t: d for t, d, e in res if len(d) > 300}
    days = sorted(data["BTC"]); n = len(days); idx = {d: i for i, d in enumerate(days)}
    i0 = next(i for i, d in enumerate(days) if d * 86400 >= START); imid = (i0 + n - 1) // 2
    A = {}
    for t in data:
        s = [data[t].get(d) for d in days]; A[t] = (([x[0] if x else None for x in s]), [x[3] if x else None for x in s])
    cb = A["BTC"][1]
    btc2 = [cb[i] / cb[i - 2] - 1 if i >= 2 and cb[i] and cb[i - 2] else 0 for i in range(n)]
    reg = [i >= 199 and cb[i] is not None and cb[i] > sum(x for x in cb[i - 199:i + 1] if x) / 200 for i in range(n)]
    rng = random.Random(11)
    text = [f"LAB 17: {fmt(days[i0])} to {fmt(days[-1])}; older half to {fmt(days[imid])}. Cost {RT:.2%} round trip. 'by day' = each signal day counted once. edge = rule minus random entries on the same coins and hold time.", ""]
    for gname, glist in groups:
        glist = [c for c in glist if c in A]
        text.append(f"{gname}: {len(glist)} coins")
        for X in (0.08, 0.12, 0.16, 0.20):
            for hold in (5, 10):
                tr = []; rnd = []; tr_reg = {True: [], False: []}; tr_mkt = {True: [], False: []}
                for t in glist:
                    O, C = A[t]
                    sig = [i >= 2 and C[i] and C[i - 2] and C[i] / C[i - 2] - 1 <= -X for i in range(n)]
                    got = L16.trades(sig, O, C, hold, i0, n); rnd += L16.randoms(O, C, hold, i0, n, 300, rng)
                    for i, x in got:
                        tr.append((i, x, t)); tr_reg[bool(reg[i])].append((i, x, t)); tr_mkt[btc2[i] <= -0.04].append((i, x, t))
                text.append(stat(tr, rnd, imid, f"drop >= {int(X * 100)}%, hold {hold}d", days))
                if X == 0.12 and hold == 10:
                    text.append(stat(tr_reg[True], rnd, imid, "   only while BTC above 200-day avg", days))
                    text.append(stat(tr_reg[False], rnd, imid, "   only while BTC below 200-day avg", days))
                    text.append(stat(tr_mkt[True], rnd, imid, "   market-wide drop (BTC -4% too)", days))
                    text.append(stat(tr_mkt[False], rnd, imid, "   coin-specific drop (BTC fine)", days))
        text.append("")
    text += ["HOW TO READ: (1) if the edge is bigger for small coins, survivorship is likely inflating it. (2) 'by day' removes the crash-day clustering: if the by-day edge is small or its +/- is as large as the average, there are too few independent events. (3) A real effect should show the same sign in the older and newer half, and in both BTC regimes. 'Buying a falling coin' that goes to zero is invisible here because dead coins are not in the data."]
    t = "\n".join(text)
    open(os.path.join(scanner.HERE, "lab17_summary.txt"), "w").write(t + "\n"); print(t)
    try: scanner.notify("Strategy lab 17 finished", "Sharp-drop retest done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
