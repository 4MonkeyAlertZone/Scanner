#!/usr/bin/env python3
"""Strategy lab 14: Fibonacci pullback buying on alts, 21 Nov 2022 (BTC bottom, about $16-17K) to 31 Aug 2025.
Setup (daily candles, no peeking): a swing high is confirmed when it is the highest high of the 5 days either side (so we only know it 5 days later). The swing low L is the lowest low in the 60 days
before it. The swing must be a rise of 30% or more from L to H. We then place a limit buy at one Fibonacci retracement of that rise (0.382 / 0.5 / 0.618 / 0.786 of the way back down from H toward L).
The setup is cancelled if price closes above H first, or touches the stop, or 30 days pass without a fill. Stop = a fixed percentage below the entry price, tested at 1%, 2%, 3%, 4%, 5% and 6% (nothing wider). The setup is also dropped if price falls more than 1% below the swing low before filling. If the fill candle itself also trades down to the stop we count the stop as hit (worst case). Target = L + e*(H-L) with e = 1.0 (back to the high), 1.272 or 1.618 (Fibonacci extensions).
After a fill: stop is checked before target in the same candle; exit at the close after 60 days. Costs 0.2% round trip. Result in R (units of risk).
72 combinations are tested (4 entry levels x 3 targets x 6 stop sizes). Because picking the best of 72 on the same data is overfitting, the window is split in two halves: the best combination in the OLDER half is then reported in the NEWER half only.
A matched random control is run for every combination: random entry days on the same coin with the same stop distance and target distance.
Writes lab14_summary.txt and lab14_results.csv."""
import os, csv, time, calendar, random
from multiprocessing import Pool
import scanner, backtest as B

START = calendar.timegm((2022, 11, 21, 0, 0, 0)); END = calendar.timegm((2025, 9, 1, 0, 0, 0)); MID = (START + END) // 2
K = 5; LOOK = 60; MINRISE = 0.30; WAIT = 30; HOLD = 60; COST = 0.002
ENT = (0.382, 0.5, 0.618, 0.786); EXT = (1.0, 1.272, 1.618); BUF = (0.01, 0.02, 0.03, 0.04, 0.05, 0.06)
day = lambda e: time.strftime("%Y-%m-%d", time.gmtime(e))

def exit_r(h, l, c, i0, entry, stop, target, first=1):
    """simulate from candle i0+1; returns (R before costs, days held, price return before costs)."""
    risk = entry - stop; n = len(c)
    for j in range(i0 + first, min(n, i0 + 1 + HOLD)):
        if l[j] <= stop: return (stop - entry) / risk, j - i0, stop / entry - 1
        if h[j] >= target: return (target - entry) / risk, j - i0, target / entry - 1
    j = min(n - 1, i0 + HOLD); return (c[j] - entry) / risk, j - i0, c[j] / entry - 1

def coin(tok):
    try: m = B.hist_crypto(tok, "1d", 2100)
    except Exception as ex: return tok, [], [], str(ex)[:60]
    if len(m) < 300: return tok, [], [], "not enough history"
    ep = [r[0] for r in m]; h = [r[2] for r in m]; l = [r[3] for r in m]; c = [r[4] for r in m]; n = len(m)
    rng = random.Random(tok); rows = []; ctrl = []
    for iH in range(max(K, LOOK), n - K - 1):
        if not (h[iH] == max(h[iH - K:iH + K + 1]) and h[iH] > max(h[iH - K:iH])): continue
        if not (START <= ep[iH + K] < END): continue
        lo = min(range(iH - LOOK, iH), key=lambda x: l[x]); L = l[lo]; H = h[iH]
        if L <= 0 or H / L - 1 < MINRISE: continue
        conf = iH + K
        for bf in BUF:
          for f in ENT:
            level = H - f * (H - L); stop = level * (1 - bf)
            fill = None
            for j in range(conf + 1, min(n, conf + 1 + WAIT)):
                if c[j] > H or l[j] <= L * 0.99: break
                if l[j] <= level: fill = j; break
            if fill is None: continue
            for e in EXT:
                target = L + e * (H - L)
                if target <= level: continue
                r0, d, p0 = exit_r(h, l, c, fill, level, stop, target, first=0)
                r = r0 - COST / bf
                rp = bf; tp = (target - level) / level; vals = []; pv = []
                for _ in range(3):
                    k = rng.randrange(260, n - HOLD - 2); en = c[k]
                    x = exit_r(h, l, c, k, en, en * (1 - rp), en * (1 + tp)); vals.append(x[0] - COST / rp); pv.append(x[2] - COST)
                rows.append((tok, ep[fill], f, e, r, d, sum(vals) / len(vals), bf, 100 * (p0 - COST), 100 * sum(pv) / len(pv)))
    return tok, rows, [], ""

def agg(sel):
    n = len(sel)
    if n == 0: return None
    r = [x[4] for x in sel]; m = sum(r) / n; sd = (sum((v - m) ** 2 for v in r) / max(1, n - 1)) ** .5
    return n, m, sd / n ** .5, 100 * sum(1 for v in r if v > 0) / n, sum(x[6] for x in sel) / n, sum(x[5] for x in sel) / n, len({x[0] for x in sel}), sum(x[8] for x in sel) / n, sum(x[9] for x in sel) / n

def main():
    coins = [c for c in scanner.top100() if c != "BTC"][:99]
    print(f"Lab 14: {len(coins)} coins...", flush=True)
    with Pool(max(1, os.cpu_count() or 1)) as p: res = p.map(coin, coins)
    rows = [r for _, rs, _, _ in res for r in rs]
    text = [f"LAB 14 Fibonacci pullbacks: {len(rows)} filled trades from {len({r[0] for r in rows})} coins, {day(START)} to {day(END)}; older half before {day(MID)}, newer half after. R after 0.2% costs. 'random' = matched random entries.",
            "Entries within the same coin and week overlap and coins move together, so the effective number of independent trades is far smaller than n; treat edges under about 0.1R as noise.", ""]
    out = []; best = None
    for half, name in ((0, "OLDER HALF"), (1, "NEWER HALF"), (2, "WHOLE WINDOW")):
        text.append(f"{name}:  entry level x target -> n | avg R (+/-) | win% | random | avg days | coins")
        for bf in BUF:
          for f in ENT:
            for e in EXT:
                sel = [r for r in rows if r[7] == bf and r[2] == f and r[3] == e and (half == 2 or (r[1] >= MID) == bool(half))]
                a = agg(sel)
                if not a: continue
                n, m, se, w, rnd, dd, nc, pc, pr = a
                text.append(f"   stop {int(bf*100)}% below entry, retrace {f:<5} target {e:<5} n={n:>4} {m:+.2f}R (+/-{se:.2f}) = {pc:+.1f}% per trade (random {pr:+.1f}%) win {w:4.0f}%  {dd:3.0f}d")
                out.append(dict(half=name, stop_buffer=bf, entry_level=f, target=e, n=n, avg_R=round(m, 3), se=round(se, 3), avg_pct=round(pc, 2), random_pct=round(pr, 2), win_pct=round(w), days=round(dd), coins=nc))
                if half == 0 and n >= 30 and (best is None or pc - pr > best[0]): best = (pc - pr, bf, f, e)
        text.append("")
    if best:
        _, bf, f, e = best
        sel = lambda cond: [r for r in rows if r[7] == bf and r[2] == f and r[3] == e and cond(r)]
        a1 = agg(sel(lambda r: r[1] < MID)); a2 = agg(sel(lambda r: r[1] >= MID))
        text.append(f"WALK-FORWARD: best combination in the older half (largest % per trade above random, n>=30) = stop {int(bf*100)}% below entry, retrace {f}, target {e}: {a1[7]:+.1f}% per trade vs random {a1[8]:+.1f}% (n={a1[0]}). In the newer half it made " + (f"{a2[7]:+.1f}% per trade vs random {a2[8]:+.1f}% ({a2[1]:+.2f}R, n={a2[0]})." if a2 else "no trades."))
        text.append("If the newer-half result is not clearly positive and above random, the 'best level' was luck. Choosing the maximum of 12 combinations on one window always looks good in hindsight.")
    text.append("")
    text.append("HOW TO READ: a bigger stop gives a smaller R per loss, so compare the '% per trade' (price return of one trade, same money in every trade) against its random control, not R alone. Tight stops on daily coins that move 3-5% a day are hit by ordinary noise, so watch the win rate and the days held. win% shows how often a trade reaches its target; low-retrace/high-target combinations have low win rates but bigger wins. Compare with lab 13: holding BTC made 5.2x over a similar period. Survivorship bias (today's listed coins) flatters every long strategy here. Not financial advice.")
    t = "\n".join(text)
    if out:
        with open(os.path.join(scanner.HERE, "lab14_results.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, list(out[0].keys())); w.writeheader(); w.writerows(out)
    open(os.path.join(scanner.HERE, "lab14_summary.txt"), "w").write(t + "\n"); print(t)
    try: scanner.notify("Strategy lab 14 finished", "Fibonacci test done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as ex: print("(phone send failed:", ex, ")")

if __name__ == "__main__":
    main()
