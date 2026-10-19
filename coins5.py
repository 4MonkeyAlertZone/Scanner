#!/usr/bin/env python3
"""What would $10,000 split equally across HBAR, NEAR, ONDO, RENDER and SUI be worth after each market phase?
Daily closes from the same exchange data the labs use (hist_crypto). Phases (BTC-based): cycle 1 = 1 Oct 2020 -> 10 Nov 2021 (BTC top); bear = 10 Nov 2021 -> 21 Nov 2022 (BTC low);
cycle 2 = 21 Nov 2022 -> 6 Oct 2025 (BTC top); since the 2025 top = 6 Oct 2025 -> latest.
Coins not yet listed when a phase starts keep their 1/5 share in cash until their first trading day, then buy at that day's close (0.1% cost on each buy).
Part 1: each coin alone. Part 2: a fresh $10,000 at the start of each phase (buy and hold). Part 3: one $10,000 started 1 Oct 2020, split equally again at each phase start.
Part 4: same coins with the lab rules (equal-weight basket of whichever coins exist, daily rebalanced): hold, BTC 200-day gate, gate + BTC above 50-day average, gate + OI warning (C, 14 days cash).
Writes coins5_report.txt. Past prices only; coins that died are not here by construction (you picked survivors), so treat results as an upper-end picture."""
import csv, os, calendar, time
from datetime import datetime, timezone
import scanner, backtest as B

COINS = {"HBAR": ["HBAR"], "NEAR": ["NEAR"], "ONDO": ["ONDO"], "RENDER": ["RNDR", "RENDER"], "SUI": ["SUI"]}
ts = lambda y, m, d: calendar.timegm((y, m, d, 0, 0, 0)) // 86400
START = ts(2020, 10, 1)
PH = [("cycle 1", ts(2020, 10, 1), ts(2021, 11, 10)), ("bear", ts(2021, 11, 10), ts(2022, 11, 21)), ("cycle 2", ts(2022, 11, 21), ts(2025, 10, 6)), ("since 2025 top", ts(2025, 10, 6), None)]
COST = 0.001
fd = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))

def series(names):
    out = {}; used = []
    for nm in names:
        try:
            rows = B.hist_crypto(nm, "1d", 2600)
            if rows:
                used.append(nm)
                for r in rows: out.setdefault(int(r[0] // 86400), r[4])      # earlier name wins on overlap
        except Exception as e: print(nm, "failed:", str(e)[:60])
    return out, used

def main():
    D = {}; notes = []
    for c, names in COINS.items():
        d, used = series(names); D[c] = d
        notes.append(f"{c}: {'+'.join(used) if used else 'NO DATA'}  first day {fd(min(d)) if d else '--'}  last {fd(max(d)) if d else '--'}  ({len(d)} days)")
    btc, _ = series(["BTC"]); last = max(btc); end_of = lambda e: last if e is None else e
    L = ["$10,000 EQUALLY IN HBAR, NEAR, ONDO, RENDER, SUI: what it would be worth after each market phase", f"data to {fd(last)}", ""] + ["Data found: "] + ["  " + x for x in notes] + [
         "If a coin's first day is later than its real listing, this exchange data starts late and the true result would differ.", ""]
    def px(c, d, back=True):
        """close on day d, or the nearest earlier day within 5 days"""
        for k in range(6):
            if d - k in D[c]: return d - k, D[c][d - k]
        return None, None
    def first_day_at_or_after(c, d):
        ds = [x for x in D[c] if x >= d]; return min(ds) if ds else None
    # ---- part 1 ----
    L += ["== 1. Each coin alone: price multiple over each phase (bought on the phase's first day, or on its first trading day if listed later) =="]
    L.append(f"{'coin':<8}" + "".join(f"{p[0]:>22}" for p in PH) + f"{'whole (to now)':>18}")
    for c in COINS:
        cells = []
        for pn, a, b in PH:
            e = end_of(b); fa = first_day_at_or_after(c, a)
            if fa is None or fa >= e: cells.append(f"{'not listed yet':>22}"); continue
            _, p0 = px(c, fa); _, p1 = px(c, e)
            if not p1: cells.append(f"{'--':>22}"); continue
            tag = "" if fa - a <= 5 else f" (from {fd(fa)[2:]})"
            cells.append(f"{'x%.2f%s' % (p1 / p0, tag):>22}")
        f0 = min(D[c]) if D[c] else None
        whole = f"x{D[c][max(D[c])] / D[c][f0]:.2f}" if f0 else "--"
        L.append(f"{c:<8}" + "".join(cells) + f"{whole:>18}")
    # ---- part 2 ----
    def hold_value(start_val, a, b, slots=5):
        """equal slots; unlisted coins' slots stay cash until first trading day (buy with 0.1% cost); returns value at day b"""
        e = end_of(b); tot = 0.0; per = start_val / slots; rows = []
        for c in COINS:
            fa = first_day_at_or_after(c, a)
            if fa is None or fa >= e: tot += per; rows.append((c, per, "not listed")); continue
            _, p0 = px(c, fa); _, p1 = px(c, e)
            v = per * (1 - COST) * (p1 / p0) if p1 else per; tot += v; rows.append((c, v, ""))
        return tot, rows
    L += ["", "== 2. A fresh $10,000 at the START of each phase, split equally, held to the END of that phase =="]
    for pn, a, b in PH:
        v, rows = hold_value(10000.0, a, b)
        L.append(f"{pn:<16} ({fd(a)} -> {fd(end_of(b))}):  $10,000 -> ${v:,.0f}   ({'; '.join(f'{c} ${x:,.0f}' + (' [cash: not listed]' if note else '') for c, x, note in rows)})")
    # ---- part 3 ----
    L += ["", "== 3. ONE $10,000 started 1 Oct 2020, re-split equally across the five at each phase start =="]
    val = 10000.0
    for pn, a, b in PH:
        v, rows = hold_value(val, a, b); L.append(f"after {pn:<15} ({fd(end_of(b))}): ${v:,.0f}   (phase multiple x{v / val:.2f})"); val = v
    L.append(f"=> $10,000 became ${val:,.0f} by {fd(last)} (buying and holding through the bear year and everything else, no switching).")
    # ---- part 4 ----
    days = sorted(btc); idx = {d: i for i, d in enumerate(days)}; n = len(days); C = [btc[d] for d in days]
    ma = lambda k: [sum(C[max(0, i - k + 1):i + 1]) / min(k, i + 1) for i in range(n)]
    m50 = ma(50); gate = [i >= 199 and C[i] > sum(C[i - 199:i + 1]) / 200 for i in range(n)]
    ret = [0.0] * n
    for i in range(1, n):
        r = []
        for c in COINS:
            a, b = D[c].get(days[i - 1]), D[c].get(days[i])
            if a and b: r.append(b / a - 1)
        ret[i] = sum(r) / len(r) if r else 0.0
    has = [any(D[c].get(days[i]) for c in COINS) for i in range(n)]
    out_c = None; mpath = os.path.join(scanner.HERE, "btc_metrics_daily.csv")
    if os.path.exists(mpath):
        oi = {}
        for r in csv.DictReader(open(mpath)):
            try: oi[calendar.timegm(datetime.strptime(r["date"], "%Y-%m-%d").timetuple()) // 86400] = float(r["open_interest_btc"])
            except Exception: pass
        OI = [oi.get(d) for d in days]; W = [False] * n
        for i in range(n):
            prev = [x for x in OI[max(0, i - 180):i] if x]
            if OI[i] and len(prev) > 100 and OI[i] >= max(prev) and i >= 30 and OI[i - 30] and OI[i] / OI[i - 30] - 1 >= .15: W[i] = True
        out_c = [False] * n; left = 0
        for i in range(n):
            if W[i]: left = 14
            out_c[i] = left > 0
            if left > 0: left -= 1
    rules = [("hold (daily-rebalanced basket)", [True] * n), ("BTC 200-day gate", gate[:]), ("gate + BTC above 50-day avg", [gate[i] and C[i] > m50[i] for i in range(n)])]
    if out_c: rules.append(("gate + OI warning (C, 14d cash)", [gate[i] and not out_c[i] for i in range(n)]))
    L += ["", "== 4. Same five coins under the lab rules (equal-weight basket of the coins that exist, rebalanced daily, 0.1% per switch, signals at the close). Phase multiples, then $10,000 chained from 1 Oct 2020 =="]
    L.append(f"{'rule':<34}" + "".join(f"{p[0]:>16}" for p in PH) + f"{'$10,000 became':>18}")
    for nm, ex in rules:
        cells = []; eq_all = 10000.0
        for pn, a, b in PH:
            lo = idx.get(first_day_at_or_after("BTC", a) if False else a, None)
            lo = next((i for i in range(n) if days[i] >= a), None); hi = next((i for i in range(n - 1, -1, -1) if days[i] <= end_of(b)), None)
            eq = 1.0; prev = 0
            for i in range(lo, hi):
                e_ = 1 if ex[i] and has[i + 1] else 0; eq *= 1 + ret[i + 1] * e_ - COST * abs(e_ - prev); prev = e_
            cells.append(f"x{eq:.2f}".rjust(16)); eq_all *= eq
        L.append(f"{nm:<34}" + "".join(cells) + f"{'$%s' % format(eq_all, ',.0f'):>18}")
    L += ["", "Read: parts 2-3 are plain buy-and-hold. Part 4 shows what the gate and the OI/50-day filters would have changed on the same coins (daily rebalanced, so it is not identical to part 3). Gains in cycle 1 are limited by how few of the five existed; SUI and ONDO only exist from 2023-24.",
          "Caveats: you chose five survivors that did well enough to be on your list (survivorship); exchange data may start after real listing; no tax; fills at daily closes."]
    text = "\n".join(L); open(os.path.join(scanner.HERE, "coins5_report.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
