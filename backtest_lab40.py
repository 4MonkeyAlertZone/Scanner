#!/usr/bin/env python3
"""Lab 40: HOW LONG DO IN AND OUT PERIODS LAST, AND DOES THE GATE HOLD UP OVER A MUCH LONGER HISTORY?
Rule (same as the gate paper bot and lab 39): IN while BTC's daily close is above BOTH its 200-day and 50-day average, OUT otherwise. Decisions are made at the daily close, so durations are whole DAYS (24-hour steps); hours have no meaning here because every flip is stamped at the 00:00 UTC close.
Data: BTC/USD daily closes from Bitstamp (back to 2011) when reachable, otherwise the same Binance US/OKX history as the other labs (from 2019). The source and date range are printed first. A longer history adds the 2013-15 and 2018 bear markets, which the 2019+ data lacks.
 PART 1  EPISODES. Every completed IN and OUT episode (the one in progress and the first, partial one are excluded because their length is not known): count, median/mean/quartiles/90th percentile/longest, share lasting 5 days or less and 10 days or less (whipsaws), and what BTC did during the episode.
 PART 2  AGE AND REMAINING TIME. For an episode that has already lasted k days, how much longer did it usually last? Shown for k = 0, 5, 10, 20, 40, 80 with counts. If the remaining time does not shrink as the age grows, then 'it has been OUT for a while' tells you nothing about when it ends.
 PART 3  ERAS. The same medians for each era, to see whether durations are stable or just one cycle.
 PART 4  THE GATE OVER THE LONG HISTORY. Hold BTC while IN, cash while OUT (0.1% per switch; a decision at close i-1 earns day i), against buy&hold: final x, worst drawdown, Calmar, and the same by era.
 NOW  the current state, its age in days, and where that age sits among past episodes of the same state.
CAUTION: durations describe the past distribution; they are not a timer. Few episodes, heavy tails and one asset mean the percentiles are rough. Do not trade 'it has been OUT for N days'. Not financial advice. Writes lab40_summary.txt."""
import os, json, time, statistics as S
import scanner
import backtest as B
import backtest_lab36 as L36
import backtest_lab39 as L39

OUT = scanner.HERE; CT = L36.CT
fd = L36.fd; UA = getattr(scanner, "UA", {"User-Agent": "Mozilla/5.0"})

def bitstamp_daily():
    """Daily BTC/USD closes from Bitstamp, oldest first, as {day_number: close}. Raises if anything looks wrong."""
    got = {}; start = 1313366400; today = int(time.time() // 86400)
    for _ in range(12):
        j = json.loads(scanner.http(f"https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=86400&limit=1000&start={start}", headers=UA))
        rows = j["data"]["ohlc"]
        if not rows: break
        for r in rows:
            d = int(r["timestamp"]) // 86400
            if d < today and float(r["close"]) > 0: got[d] = float(r["close"])
        nxt = int(rows[-1]["timestamp"]) + 86400
        if nxt <= start or len(rows) < 1000: break
        start = nxt; time.sleep(0.3)
    if len(got) < 1500: raise RuntimeError(f"Bitstamp returned only {len(got)} days")
    return got

def load():
    try:
        got = bitstamp_daily(); src = "Bitstamp BTC/USD daily"
    except Exception as e:
        print("Bitstamp history failed:", str(e)[:80], "-> using Binance US/OKX history")
        rows = B.hist_crypto("BTC", "1d", 2700); got = {int(r[0] // 86400): r[4] for r in rows}; src = "Binance US/OKX BTC daily (fallback, shorter history)"
    days = sorted(got)
    # keep one unbroken run of consecutive days (fill nothing)
    run = [days[0]]
    for d in days[1:]:
        if d == run[-1] + 1: run.append(d)
        else: run = [d]
    return run, [got[d] for d in run], src

def episodes(gate, first):
    """Completed episodes as dicts; skips the partial first one and the ongoing last one."""
    eps = []; i = first; n = len(gate)
    starts = [first] + [k for k in range(first + 1, n) if gate[k] != gate[k - 1]]
    for a, b in zip(starts, starts[1:] + [n]):
        eps.append(dict(state=gate[a], a=a, b=b, days=b - a))
    return eps

def q(v, p):
    v = sorted(v); return v[min(len(v) - 1, int(p * len(v)))]

def main(days=None, closes=None, src="synthetic"):
    if days is None: days, closes, src = load()
    n = len(days); gate = L39.gate_series(closes, 200, 50)
    first = next(i for i in range(n) if sma_ok(closes, i))
    eps = episodes(gate, first)
    done = [e for e in eps[1:-1]]   # drop partial first and ongoing last
    cur = eps[-1]; age = cur["days"]
    out = [f"LAB 40: REGIME EPISODE DURATIONS AND LONG-HISTORY GATE TEST  source {src}; {fd(days[0])} to {fd(days[-1])} ({n} days); gate decisions from {fd(days[first])}",
           f"{len(done)} completed episodes ({sum(e['state'] for e in done)} IN, {sum(not e['state'] for e in done)} OUT). Cost {CT * 100:.1f}% per switch.", ""]
    for e in eps:
        e["ret"] = closes[min(e["b"], n - 1)] / closes[e["a"]] - 1 if e["a"] < n - 1 else 0.0
    out.append("PART 1: COMPLETED EPISODES (days)")
    out.append(f"{'state':<6}{'n':>4}{'median':>8}{'mean':>7}{'25%':>6}{'75%':>6}{'90%':>6}{'max':>6}{'<=5d%':>7}{'<=10d%':>8}{'share of days%':>16}{'BTC ret avg%':>14}{'median%':>9}")
    tot = sum(e["days"] for e in done)
    for st, nm in ((True, "IN"), (False, "OUT")):
        v = [e for e in done if e["state"] == st]
        if len(v) < 3: out.append(f"{nm:<6}{len(v):>4}  too few"); continue
        d = [e["days"] for e in v]; r = [e["ret"] * 100 for e in v]
        out.append(f"{nm:<6}{len(v):>4}{S.median(d):>8.0f}{S.mean(d):>7.0f}{q(d, .25):>6}{q(d, .75):>6}{q(d, .9):>6}{max(d):>6}{100 * sum(x <= 5 for x in d) / len(d):>7.0f}{100 * sum(x <= 10 for x in d) / len(d):>8.0f}{100 * sum(d) / tot:>16.0f}{S.mean(r):>14.1f}{S.median(r):>9.1f}")
    out.append("BTC ret = close-to-close change from the first to the last day of the episode. For OUT episodes a NEGATIVE number means the gate avoided a fall; a positive one means it sat out a rise.")
    out += ["", "PART 2: HOW MUCH LONGER, GIVEN AGE SO FAR (completed episodes; remaining = total days minus age)"]
    out.append(f"{'state':<6}{'age k':>6}{'reached k':>10}{'median remaining':>18}{'ended within 10d %':>20}{'ended within 30d %':>20}")
    for st, nm in ((True, "IN"), (False, "OUT")):
        v = [e["days"] for e in done if e["state"] == st]
        for k in (0, 5, 10, 20, 40, 80):
            r = [x - k for x in v if x > k]
            if len(r) < 5: out.append(f"{nm:<6}{k:>6}{len(r):>10}  too few"); continue
            out.append(f"{nm:<6}{k:>6}{len(r):>10}{S.median(r):>18.0f}{100 * sum(x <= 10 for x in r) / len(r):>20.0f}{100 * sum(x <= 30 for x in r) / len(r):>20.0f}")
    out += ["", "PART 3: BY ERA (median days, number of completed episodes)"]
    cuts = [(None, 2017), (2017, 2020), (2020, 2023), (2023, None)]
    yr = lambda d: time.gmtime(d * 86400).tm_year
    for lo, hi in cuts:
        row = []
        for st, nm in ((True, "IN"), (False, "OUT")):
            v = [e["days"] for e in done if e["state"] == st and (lo is None or yr(days[e["a"]]) >= lo) and (hi is None or yr(days[e["a"]]) < hi)]
            row.append(f"{nm} n={len(v)} median {S.median(v):.0f}" if v else f"{nm} n=0")
        out.append(f"  {('start' if lo is None else lo)}..{('now' if hi is None else hi - 1)}: " + "; ".join(row))
    # part 4
    out += ["", "PART 4: BTC HELD WHILE IN, CASH WHILE OUT (vs buy&hold)"]
    rets = [0.0] + [closes[i] / closes[i - 1] - 1 for i in range(1, n)]
    def stretch(a, b):
        eq = bh = 1.0; curve = [1.0]; prev = 0.0; bcurve = [1.0]
        for i in range(a, b):
            w = 1.0 if gate[i - 1] else 0.0; eq *= 1 + w * rets[i] - CT * abs(w - prev); prev = w; bh *= 1 + rets[i]; curve.append(eq); bcurve.append(bh)
        yrs = (b - a) / 365.0; dd = L36.metrics(curve); bdd = L36.metrics(bcurve)
        cg = eq ** (1 / yrs) - 1 if eq > 0 else -1; cb = bh ** (1 / yrs) - 1 if bh > 0 else -1
        return eq, dd, (cg * 100 / abs(dd) if dd < 0 else float("inf")), bh, bdd, (cb * 100 / abs(bdd) if bdd < 0 else float("inf"))
    out.append(f"{'period':<26}{'gate x':>10}{'DD%':>6}{'Calmar':>8}{'hold x':>10}{'DD%':>6}{'Calmar':>8}")
    i0 = first + 1
    eras = [("whole history", i0, n)]
    for lo, hi in cuts:
        a = next((i for i in range(i0, n) if lo is None or yr(days[i]) >= lo), None); b = next((i for i in range(i0, n) if hi is not None and yr(days[i]) >= hi), n)
        if a is not None and b - a > 200: eras.append((f"{'start' if lo is None else lo}..{'now' if hi is None else hi - 1}", a, b))
    for nm, a, b in eras:
        g, dd, c1, h, bd, c2 = stretch(a, b); out.append(f"{nm:<26}{g:>10.2f}{dd:>6.0f}{c1:>8.2f}{h:>10.2f}{bd:>6.0f}{c2:>8.2f}")
    sw = sum(1 for i in range(i0, n) if gate[i] != gate[i - 1])
    out.append(f"Switches over the history: {sw} (about {sw / ((n - i0) / 365.0):.1f} per year).")
    # now
    v = [e["days"] for e in done if e["state"] == cur["state"]]
    nm = "IN" if cur["state"] else "OUT"
    out += ["", f"NOW: {nm} for {age} days (since {fd(days[cur['a']])}). Past completed {nm} episodes: median {S.median(v):.0f} days, {100 * sum(x < age for x in v) / len(v):.0f}% were shorter than the current one so far.",
            "", "Read:",
            "- Whipsaw share (<=5 and <=10 day episodes) tells you how many flips are noise; expect many short OUT/IN flips around the averages.",
            "- Part 2: if the median remaining time barely changes with age, the age of an episode does not predict its end; do not use it as a timing signal.",
            "- Part 4 over a longer history is the real test of the gate: it needs to hold up in the 2013-15 and 2018 bears, not only 2022. SURVIVORSHIP: BTC is the one survivor; 40 labs on this history. Not financial advice."]
    text = "\n".join(out); open(os.path.join(OUT, "lab40_summary.txt"), "w").write(text + "\n"); print(text)

def sma_ok(closes, i): return i >= 199

if __name__ == "__main__":
    main()
