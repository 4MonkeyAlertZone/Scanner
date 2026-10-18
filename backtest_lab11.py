#!/usr/bin/env python3
"""Strategy lab 11: did a short-term trader's posted Bitcoin stance predict what BTC did next?
Input trader2_stance.csv: one row per BTC post (about 48 posts, July-October 2026) (epoch, stance +1 bullish / -1 bearish / 0 neutral). The stance labels are a human reading of each
report's conclusion (subjective); no report text is stored. Compared with BTC daily closes: forward returns after bullish, bearish and neutral reports,
hit rates, what following him (long when bullish, short when bearish, flat when neutral) would have earned versus just holding, and the same split
before and after the October 2025 turn in his view. Writes lab11_summary.txt."""
import csv, os, time
import scanner, backtest as B

OUT = scanner.HERE
HS = (3, 7, 14)
tf = lambda t: time.strftime("%Y-%m-%d", time.gmtime(t))

def mean(x): return sum(x) / len(x) if x else 0.0
def sd(x):
    if len(x) < 2: return 0.0
    m = mean(x); return (sum((v - m) ** 2 for v in x) / (len(x) - 1)) ** .5
def pm(x): return f"{mean(x):+5.1f}% (+/-{1.96 * sd(x) / max(1, len(x)) ** .5:.1f})" if x else "n/a"

def main():
    rows = [(int(r["epoch"]), int(r["stance"])) for r in csv.DictReader(open(os.path.join(scanner.HERE, "trader2_stance.csv")))]
    m = B.hist_crypto("BTC", "1d", 1500); day = {int(r[0] // 86400): r[4] for r in m}
    def price(ep, back=0):
        d = int(ep // 86400) + back
        return day.get(d)
    L = [f"{len(rows)} posts, {tf(rows[0][0])} to {tf(rows[-1][0])}. BTC daily closes {tf(m[0][0])} to {tf(m[-1][0])}. Forward returns are measured from the close of the report's day, so there is no peeking.",
         f"Stances: {sum(1 for _, s in rows if s > 0)} bullish, {sum(1 for _, s in rows if s < 0)} bearish, {sum(1 for _, s in rows if s == 0)} neutral/unclear. Labels are a human reading of each conclusion, so a few are debatable.", ""]
    cut = sorted(e[0] for e in rows)[len(rows) // 2]
    ev = []
    for ep, s in rows:
        p0 = price(ep)
        if not p0: continue
        r = {h: (price(ep, h) / p0 - 1) * 100 if price(ep, h) else None for h in HS}
        ev.append((ep, s, r))
    for name, sel in (("WHOLE PERIOD", ev), ("EARLIER HALF", [e for e in ev if e[0] < cut]), ("LATER HALF", [e for e in ev if e[0] >= cut])):
        L.append(name + f"   ({len(sel)} reports)")
        for h in HS:
            allr = [e[2][h] for e in sel if e[2][h] is not None]
            L.append(f"  {h:2d} days ahead. All reports: avg {pm(allr)}, up {sum(1 for x in allr if x > 0) / max(1, len(allr)) * 100:.0f}% of the time")
            for lab, st in (("bullish", 1), ("neutral", 0), ("bearish", -1)):
                xs = [e[2][h] for e in sel if e[1] == st and e[2][h] is not None]
                if not xs: continue
                right = sum(1 for x in xs if (x > 0 if st > 0 else x < 0 if st < 0 else False))
                L.append(f"       after {lab:8} n={len(xs):3d}  avg {pm(xs)}" + (f"  call was right {right / len(xs) * 100:.0f}%" if st else ""))
        w = [(s, r[3]) for _, s, r in sel if r[3] is not None]
        if w:
            fol = [s * x for s, x in w]; hold = [x for _, x in w]
            L.append(f"  FOLLOWING HIM post by post (long when bullish, short when bearish, flat when neutral), 3-day moves: avg {mean(fol):+.2f}% per report vs {mean(hold):+.2f}% for just holding; total {sum(fol):+.0f}% vs {sum(hold):+.0f}% (simple sum, no compounding, no fees)")
        L.append("")
    L.append("WHEN HE CHANGED HIS MIND (stance flips): date, new stance, BTC 14 days later")
    prev = None
    for ep, s, r in ev:
        if prev is not None and s != prev and s != 0: L.append(f"   {tf(ep)}  turned {'BULLISH' if s > 0 else 'BEARISH'}  BTC ${price(ep):,.0f}, 14 days later {r[14]:+.1f}%" if r[14] is not None else f"   {tf(ep)}  turned {'BULLISH' if s > 0 else 'BEARISH'}  BTC ${price(ep):,.0f}")
        if s != 0: prev = s
    L.append("")
    L.append("EPISODES: each stretch of the same stance, from the first post to the first post with a different stance (a held position). Return of following him over that stretch.")
    cur = None; tot = 0.0; wins = 0; n = 0
    for i, (e_, s, r) in enumerate(ev):
        if s == 0: continue
        if cur is None or s != cur[1]:
            if cur is not None:
                p1 = price(e_); ret = (p1 / cur[2] - 1) * 100 * cur[1]; tot += ret; n += 1; wins += ret > 0
                L.append(f"   {tf(cur[0])} to {tf(e_)}  {'LONG ' if cur[1] > 0 else 'SHORT'}  BTC ${cur[2]:,.0f} -> ${p1:,.0f}   result of following him {ret:+.1f}%")
            cur = (e_, s, price(e_))
    if cur is not None:
        p1 = m[-1][4]; ret = (p1 / cur[2] - 1) * 100 * cur[1]; tot += ret; n += 1; wins += ret > 0
        L.append(f"   {tf(cur[0])} to now        {'LONG ' if cur[1] > 0 else 'SHORT'}  BTC ${cur[2]:,.0f} -> ${p1:,.0f}   result of following him {ret:+.1f}% (still open)")
    if n: L.append(f"   {n} stretches, {wins} profitable, total {tot:+.1f}% (simple sum, no fees); compare with BTC itself over the same period: {(m[-1][4] / price(ev[0][0]) - 1) * 100:+.1f}%")
    L.append("")
    L.append("HOW TO READ: 'right' means BTC moved the way he said over that horizon. A bullish stance in a rising market is easy to get right, so compare with 'all reports' and with holding. About 45 posts over about 15 weeks, overlapping windows, one asset, one trader and subjective labels: this can show whether his direction had obvious value, not prove a small edge.")
    text = "\n".join(L)
    open(os.path.join(OUT, "lab11_summary.txt"), "w").write(text + "\n"); print(text)
    try: scanner.notify("Strategy lab 11 finished", "Short-term stance test done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
