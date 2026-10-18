#!/usr/bin/env python3
"""Strategy lab 10: did a trader's weekly Bitcoin stance predict what BTC did next?
Input dp_stance.csv: one row per weekly BTC report (epoch, stance +1 bullish / -1 bearish / 0 neutral). The stance labels are a human reading of each
report's conclusion (subjective); no report text is stored. Compared with BTC daily closes: forward returns after bullish, bearish and neutral reports,
hit rates, what following him (long when bullish, short when bearish, flat when neutral) would have earned versus just holding, and the same split
before and after the October 2025 turn in his view. Writes lab10_summary.txt."""
import csv, os, time
import scanner, backtest as B

OUT = scanner.HERE
HS = (7, 14, 28)
tf = lambda t: time.strftime("%Y-%m-%d", time.gmtime(t))

def mean(x): return sum(x) / len(x) if x else 0.0
def sd(x):
    if len(x) < 2: return 0.0
    m = mean(x); return (sum((v - m) ** 2 for v in x) / (len(x) - 1)) ** .5
def pm(x): return f"{mean(x):+5.1f}% (+/-{1.96 * sd(x) / max(1, len(x)) ** .5:.1f})" if x else "n/a"

def main():
    rows = [(int(r["epoch"]), int(r["stance"])) for r in csv.DictReader(open(os.path.join(scanner.HERE, "dp_stance.csv")))]
    m = B.hist_crypto("BTC", "1d", 1500); day = {int(r[0] // 86400): r[4] for r in m}
    def price(ep, back=0):
        d = int(ep // 86400) + back
        return day.get(d)
    L = [f"{len(rows)} weekly reports, {tf(rows[0][0])} to {tf(rows[-1][0])}. BTC daily closes {tf(m[0][0])} to {tf(m[-1][0])}. Forward returns are measured from the close of the report's day, so there is no peeking.",
         f"Stances: {sum(1 for _, s in rows if s > 0)} bullish, {sum(1 for _, s in rows if s < 0)} bearish, {sum(1 for _, s in rows if s == 0)} neutral/unclear. Labels are a human reading of each conclusion, so a few are debatable.", ""]
    cut = int(time.mktime((2025, 10, 1, 0, 0, 0, 0, 0, 0)))
    ev = []
    for ep, s in rows:
        p0 = price(ep)
        if not p0: continue
        r = {h: (price(ep, h) / p0 - 1) * 100 if price(ep, h) else None for h in HS}
        ev.append((ep, s, r))
    for name, sel in (("WHOLE PERIOD", ev), ("BEFORE 1 Oct 2025 (his bullish phase)", [e for e in ev if e[0] < cut]), ("FROM 1 Oct 2025 (his bearish phase)", [e for e in ev if e[0] >= cut])):
        L.append(name + f"   ({len(sel)} reports)")
        for h in HS:
            allr = [e[2][h] for e in sel if e[2][h] is not None]
            L.append(f"  {h:2d} days ahead. All reports: avg {pm(allr)}, up {sum(1 for x in allr if x > 0) / max(1, len(allr)) * 100:.0f}% of the time")
            for lab, st in (("bullish", 1), ("neutral", 0), ("bearish", -1)):
                xs = [e[2][h] for e in sel if e[1] == st and e[2][h] is not None]
                if not xs: continue
                right = sum(1 for x in xs if (x > 0 if st > 0 else x < 0 if st < 0 else False))
                L.append(f"       after {lab:8} n={len(xs):3d}  avg {pm(xs)}" + (f"  call was right {right / len(xs) * 100:.0f}%" if st else ""))
        w = [(s, r[7]) for _, s, r in sel if r[7] is not None]
        if w:
            fol = [s * x for s, x in w]; hold = [x for _, x in w]
            L.append(f"  FOLLOWING HIM week by week (long when bullish, short when bearish, flat when neutral), 7-day moves: avg {mean(fol):+.2f}% per report vs {mean(hold):+.2f}% for just holding; total {sum(fol):+.0f}% vs {sum(hold):+.0f}% (simple sum, no compounding, no fees)")
        L.append("")
    L.append("WHEN HE CHANGED HIS MIND (stance flips): date, new stance, BTC 28 days later")
    prev = None
    for ep, s, r in ev:
        if prev is not None and s != prev and s != 0: L.append(f"   {tf(ep)}  turned {'BULLISH' if s > 0 else 'BEARISH'}  BTC ${price(ep):,.0f}, 28 days later {r[28]:+.1f}%" if r[28] is not None else f"   {tf(ep)}  turned {'BULLISH' if s > 0 else 'BEARISH'}  BTC ${price(ep):,.0f}")
        if s != 0: prev = s
    L.append("")
    L.append("HOW TO READ: 'right' means BTC moved the way he said over that horizon. A bullish stance in a rising market is easy to get right, so compare with 'all reports' and with holding. About 85 reports, overlapping windows, one asset, one trader and subjective labels: this can show whether his direction had obvious value, not prove a small edge.")
    text = "\n".join(L)
    open(os.path.join(OUT, "lab10_summary.txt"), "w").write(text + "\n"); print(text)
    try: scanner.notify("Strategy lab 10 finished", "Weekly stance test done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
