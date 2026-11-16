#!/usr/bin/env python3
"""How does the current bear market compare with the previous ones (2013, 2017, 2021 cycles)? A record and comparison, not a prediction: nobody can know from this data whether the low is in.
Data: BTC/USD daily closes from Bitstamp (2011-09-13 on, so the 2011 cycle is not covered). Peaks = highest close in a window around each cycle top (2013: Oct 2013-Feb 2014; 2017: Nov 2017-Jan 2018; 2021: Oct-Dec 2021; current: highest close since 2025-01-01). Lows = lowest close in the 600 days after the peak (the lowest close so far for the current cycle).
Sections: 1 cycle table; 2 drawdown from the peak at the same age; 3 where each cycle stood at today's age relative to its own final low; 4 what the 200/50 gate did inside each bear (IN rallies, OUT signals and the further fall after them, first IN signal after the low).
Writes cycle_compare.txt. Not financial advice."""
import os
import scanner
import backtest_lab36 as L36
import backtest_lab39 as L39
import backtest_lab40 as L40
import backtest_lab44 as L44

OUT = scanner.HERE; fd = L36.fd; day_of = L44.day_of

def main(days=None, closes=None, src="synthetic"):
    if days is None: days, closes, src = L40.load()
    n = len(days); c = closes
    ix = lambda y, m, d: next(i for i, x in enumerate(days) if x >= day_of(y, m, d))
    def argmax(a, b): return max(range(a, b), key=lambda i: c[i])
    def argmin(a, b): return min(range(a, b), key=lambda i: c[i])
    spec = [("2013-14", ix(2013, 10, 1), ix(2014, 3, 1)), ("2017-18", ix(2017, 11, 1), ix(2018, 2, 1)), ("2021-22", ix(2021, 10, 1), ix(2022, 1, 1))]
    cyc = []
    for nm, a, b in spec:
        p = argmax(a, b); t = argmin(p, min(n, p + 600)); cyc.append(dict(nm=nm, p=p, t=t, end=t + 1, done=True))
    pc = argmax(ix(2025, 1, 1), n); tc = argmin(pc, n); cyc.append(dict(nm="2025-now", p=pc, t=tc, end=n, done=False))
    age_now = n - 1 - pc
    out = [f"CYCLE COMPARISON  source {src}; {fd(days[0])} to {fd(days[-1])}; today is day {age_now} after the current peak", "",
           "1. CYCLES (peak = highest close; low = lowest close after it; current low is 'so far')",
           f"{'cycle':<9}{'peak date':<12}{'peak':>9}{'low date':<12}{'low':>9}{'days peak->low':>15}{'depth %':>9}{'now/low %':>10}"]
    for k in cyc:
        p, t = k["p"], k["t"]
        out.append(f"{k['nm']:<9}{fd(days[p]):<12}{c[p]:>9,.0f}{fd(days[t]):<12}{c[t]:>9,.0f}{t - p:>15}{(c[t] / c[p] - 1) * 100:>9.0f}" + (f"{(c[-1] / c[t] - 1) * 100:>10.0f}" if not k["done"] else ""))
    out += ["", f"   current price {c[-1]:,.0f} = {(c[-1] / c[pc] - 1) * 100:.0f}% from the peak; the lowest close since the peak ({c[tc]:,.0f} on {fd(days[tc])}) is {(c[-1] / c[tc] - 1) * 100:+.0f}% from here.", "",
            "2. DRAWDOWN FROM THE PEAK AT THE SAME AGE (%, close at peak + k days vs peak close)"]
    ages = [100, 200, 300, 365, 400, 450, 500]
    out.append(f"{'cycle':<9}" + "".join(f"{'day ' + str(a):>9}" for a in ages) + f"{'day ' + str(age_now) + ' (today)':>16}")
    for k in cyc:
        p = k["p"]; row = f"{k['nm']:<9}"
        for a in ages: row += f"{(c[p + a] / c[p] - 1) * 100:>9.0f}" if p + a < n else f"{'-':>9}"
        row += f"{(c[min(n - 1, p + age_now)] / c[p] - 1) * 100:>16.0f}" if p + age_now < n else f"{'-':>16}"
        out.append(row)
    out += ["", f"3. AT TODAY'S AGE (day {age_now}): WAS THE FINAL LOW ALREADY IN?"]
    for k in cyc[:3]:
        p, t = k["p"], k["t"]; a = min(n - 1, p + age_now)
        out.append(f"   {k['nm']}: the low came on day {t - p} ({'before' if t - p <= age_now else 'after'} day {age_now}); at day {age_now} the price was {(c[a] / c[t] - 1) * 100:+.0f}% from that final low and {(c[a] / c[p] - 1) * 100:.0f}% from the peak")
    out.append(f"   2025-now: lowest close so far came on day {tc - pc}; the price is {(c[-1] / c[tc] - 1) * 100:+.0f}% from it and {(c[-1] / c[pc] - 1) * 100:.0f}% from the peak. Whether it is the final low cannot be known.")
    gate = L39.gate_series(c, 200, 50); first = next(i for i in range(n) if L40.sma_ok(c, i)); eps = L40.episodes(gate, first)
    out += ["", "4. WHAT THE 200/50 GATE DID INSIDE EACH BEAR"]
    for k in cyc:
        p, t, end = k["p"], k["t"], k["end"]
        out.append(f"{k['nm']}:")
        ins = [e for e in eps if e["state"] and p < e["a"] < end]
        outs = [e for e in eps if not e["state"] and p < e["a"] < end and (e["b"] - e["a"] >= 15 or e["b"] >= n)]
        for e in outs:
            a = e["a"]; b = min(e["b"], n - 1); low = argmin(a, min(n, end)); length = (n - a) if e["b"] >= n else e["b"] - a
            out.append(f"   OUT signal {fd(days[a])} at {c[a]:,.0f} ({(c[a] / c[p] - 1) * 100:.0f}% from the peak), {length} days{' (open)' if e['b'] >= n else ''}: the lowest close after it was {c[low]:,.0f} on {fd(days[low])} ({(c[low] / c[a] - 1) * 100:+.0f}% from the signal, {low - a} days later)")
        for e in ins:
            a = e["a"]; b = min(e["b"], n - 1)
            out.append(f"   IN rally {fd(days[a])} to {'open' if e['b'] >= n else fd(days[e['b']])}: {(n - a) if e['b'] >= n else e['b'] - a} days, BTC {(c[b] / c[a] - 1) * 100:+.0f}%")
        if k["done"]:
            nxt = next((e for e in eps if e["state"] and e["a"] > t), None)
            if nxt: out.append(f"   first IN signal after the low: {fd(days[nxt['a']])}, {nxt['a'] - t} days after the low, BTC already {(c[nxt['a']] / c[t] - 1) * 100:+.0f}% above it")
        else:
            cur = [e for e in eps if not e["state"] and e["b"] >= n][-1]
            m200 = sum(c[-200:]) / 200; m50 = sum(c[-50:]) / 50; need = max(m200, m50)
            out.append(f"   to flip IN today: a close above {need:,.0f} (200-day {m200:,.0f}, 50-day {m50:,.0f}), which is {(need / c[-1] - 1) * 100:+.0f}% from here and {(need / c[tc] - 1) * 100:+.0f}% above the lowest close so far")
    text = "\n".join(out); open(os.path.join(OUT, "cycle_compare.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
