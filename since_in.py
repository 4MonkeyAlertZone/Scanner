#!/usr/bin/env python3
"""What would $10,000 be worth since the 20 Aug 2026 GET IN (bought at the 19 Aug daily close = signal price)? Writes since_in_report.txt."""
import time, calendar
import backtest as B, scanner
fd = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))
E = calendar.timegm((2026, 8, 19, 0, 0, 0)) // 86400
def get(t):
    for s in ([t] + (["RNDR"] if t == "RENDER" else [])):
        try:
            m = B.hist_crypto(s, "1d", 120); d = {int(r[0] // 86400): r for r in m}
            if E in d: return d
        except Exception as e: print(t, e)
    return {}
D = {t: get(t) for t in ["BTC", "ETH", "NEAR", "ONDO", "HBAR", "SUI", "RENDER"]}
alts = ["NEAR", "ONDO", "HBAR", "SUI", "RENDER"]
L = ["SINCE THE 20 AUG 2026 GET IN: $10,000 bought at the 19 Aug daily close (the signal price)", ""]
last = min(max(d) for d in D.values() if d); L.append(f"Latest completed daily close used: {fd(last)}"); L.append("")
def val(t, amt):
    d = D[t]
    if E not in d or last not in d: return None
    e = d[E][4]; now = d[last][4]; low = min(d[k][3] for k in d if E < k <= last)
    return amt * now / e, e, now, low / e - 1
L.append(f"{'asset':<8}{'entry':>12}{'now':>12}{'change':>9}{'worth':>11}{'worst low vs entry':>20}")
for t in D:
    v = val(t, 10000)
    L.append(f"{t:<8}{v[1]:>12.5g}{v[2]:>12.5g}{(v[0]/10000-1)*100:>+8.1f}%{v[0]:>11,.0f}{v[3]*100:>+19.1f}%" if v else f"{t:<8} no data")
w = [val(t, 2000) for t in alts]
if all(w):
    tot = sum(x[0] for x in w); L += ["", f"EQUAL ALT BASKET ($2,000 each in NEAR, ONDO, HBAR, SUI, RENDER): ${tot:,.0f} ({(tot/10000-1)*100:+.1f}%)"]
    for t, x in zip(alts, w): L.append(f"  {t:<8} ${x[0]:,.0f}")
    b = [(sum(2000 * D[t][k][4] / D[t][E][4] for t in alts) / 10000 - 1) * 100 for k in sorted(D["BTC"]) if E < k <= last]
    L.append(f"  worst closing dip of the basket versus entry: {min(b):+.1f}%")

P = ["", "PEAK VALUE OF EACH PORTFOLIO (best daily close since entry) and how far it is now below that peak:"]
ks = [k for k in sorted(D["BTC"]) if E <= k <= last]
def ser(w): return [sum(a * D[t][k][4] / D[t][E][4] for t, a in w.items()) for k in ks]
for name, w in [("BTC", {"BTC": 10000}), ("ETH", {"ETH": 10000}), ("Alt basket", {t: 2000 for t in alts})] + [(t, {t: 10000}) for t in alts]:
    v = ser(w); i = max(range(len(v)), key=v.__getitem__)
    P.append(f"  {name:<11} peak ${v[i]:>9,.0f} on {fd(ks[i])} ({(v[i]/10000-1)*100:+.1f}%)   now ${v[-1]:>9,.0f}   {(v[-1]/v[i]-1)*100:+.1f}% from peak")
L += P
L += ["", "Prices are daily closes, no fees or slippage; the real fill would be around the 20 Aug morning price."]
open("since_in_report.txt", "w").write("\n".join(L) + "\n"); print("\n".join(L))
