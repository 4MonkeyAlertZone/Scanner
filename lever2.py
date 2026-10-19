#!/usr/bin/env python3
"""STRICTER ENTRY FOR LEVERAGE. Same engine as lever.py (isolated margin, liquidation on daily LOW, 0.05% fee, funding 0.03%/day for 2x/3x). The EXIT rule is unchanged (leave when the base regime rule turns OUT).
Only ENTRY is stricter: a leveraged position is opened only when the base rule is IN AND the extra filter is true on that day; once open it stays until the base rule says OUT.
Filters (second round, after 7-day waits and 200d+10% were found too strict): base | 50d +1/2/3/4/5% | 200d +3/5% | 50d +2% & 200d +3% | 50d +3% & 200d +5%.
For each: $10,000 from 1 Oct 2020 (final value, worst account dip, trades, liquidations) and the 30-day-start test (median/worst final multiple, starts ending below 1x). Past prices only; filters picked in advance (this list), but small sample (~40 IN spells) and the base OI flag was chosen with hindsight: differences between filters are mostly noise unless large and consistent across BTC and ETH."""
import os, time, statistics as S
import scanner, lever as LV

def main():
    bt = LV.ohlc("BTC"); et = LV.ohlc("ETH")
    days = [d for d in sorted(bt) if d in et and d >= LV.START - 260]; n = len(days)
    base, oi_ok = LV.signals(bt, days); C = [bt[d][2] for d in days]
    m50 = [sum(C[i - 49:i + 1]) / 50 if i >= 49 else None for i in range(n)]
    m200 = [sum(C[i - 199:i + 1]) / 200 if i >= 199 else None for i in range(n)]
    age = [0] * n
    for i in range(n): age[i] = (age[i - 1] + 1 if i and base[i] else 0) if base[i] else 0
    a50 = lambda p: [bool(m50[i]) and C[i] > m50[i] * (1 + p) for i in range(n)]
    a200 = lambda p: [bool(m200[i]) and C[i] > m200[i] * (1 + p) for i in range(n)]
    old7 = [age[i] >= 7 for i in range(n)]
    AND = lambda *xs: [all(x[i] for x in xs) for i in range(n)]
    F = [("base (current alert)", [True] * n), ("50d +1%", a50(.01)), ("50d +2%", a50(.02)), ("50d +3%", a50(.03)), ("50d +4%", a50(.04)), ("50d +5%", a50(.05)), ("200d +3%", a200(.03)), ("200d +5%", a200(.05)), ("50d +2% & 200d +3%", AND(a50(.02), a200(.03))), ("50d +3% & 200d +5%", AND(a50(.03), a200(.05)))]
    def hyst(E):
        w = [False] * n
        for i in range(n): w[i] = base[i] and (E[i] or (i > 0 and w[i - 1]))
        return w
    i0 = next(i for i, d in enumerate(days) if d >= LV.START)
    out = ["STRICTER ENTRY FOR LEVERAGE  (data to " + LV.fd(days[-1]) + ")  entry filter added to the regime rule; exit unchanged", "BAD data: " + ("; ".join(LV.BAD) if LV.BAD else "none"), ""]
    for nm, px in (("BTC", bt), ("ETH", et)):
        for L in (2, 3):
            out.append(f"== {nm} {L}x ==")
            out.append(f"{'entry filter':<24}{'$10k became':>14}{'worst dip':>11}{'trades':>8}{'liq':>5}   {'30d-start test: median x':>26}{'worst x':>9}{'below 1x':>10}{'liquidated':>12}")
            for fn, E in F:
                sg = hyst(E)
                cur, tr, dead = LV.sim(px, days, sg, L, i0)
                ks = sorted(cur); pk = 0; wd = 0
                for i in ks: pk = max(pk, cur[i]); wd = min(wd, cur[i] / pk - 1 if pk else 0)
                fin = []; lq = 0
                for s in range(i0, n - 60, 30):
                    c2, t2, d2 = LV.sim(px, days, sg, L, s)
                    lq += d2 is not None; fin.append(c2[max(c2)])
                out.append(f"{fn:<24}{'$%s' % format(10000 * cur[max(cur)], ',.0f'):>14}{wd * 100:>10.0f}%{len(tr):>8}{sum(t[3] == 'LIQUIDATED' for t in tr):>5}   {S.median(fin):>25.2f}x{min(fin):>8.2f}x{sum(f < 1 for f in fin):>10}{lq:>12}")
            out.append("")
    out.append("Read: a stricter filter is only worth adopting if it improves the worst dip / worst start without a big loss in final value, on BOTH BTC and ETH, at both 2x and 3x. Otherwise it is noise from a small sample.")
    t = "\n".join(out); open(os.path.join(scanner.HERE, "lever2_report.txt"), "w").write(t + "\n"); print(t)

if __name__ == "__main__":
    main()
