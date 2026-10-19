#!/usr/bin/env python3
"""LEVERAGE TEST: BTC and ETH with 1x / 2x / 3x leverage, held through everything vs. the alt-regime rule (BTC above 200-day AND 50-day average, no BTC open-interest warning C in the last 14 days).
Model = isolated-margin perpetual futures, long only. A position is opened at the close of the first IN day with ALL account equity as margin (notional = L x equity), held until the rule says OUT (closed at that close, signal at close, fill at close).
LIQUIDATION: if a later day's LOW trades at or below entry x (1 - (1 - mm*L)/L) the position is wiped (mm = 0.5% maintenance margin; real exchanges also take a liquidation fee, so this is slightly kind). Wiped = account goes to zero and stays there.
COSTS: 0.05% taker fee per side on notional; funding assumed 0.03% per day on notional for 2x/3x (1x is treated as spot, no funding) (typical when longs are crowded; real funding varies, can be negative). Not modelled: slippage, gaps between daily candles beyond the low, exchange outages, auto-deleveraging.
Part A: $10,000 from 1 Oct 2020 to now, per phase. Part B: the same but starting on every 30th day (does the answer depend on the start date?). Part C: how deep each IN spell dipped below its entry (the number that decides liquidation).
Part D: where liquidation prices would sit if you entered at the latest close. Past prices only; BTC/ETH survived, OI flag chosen with hindsight (OI data starts 2021-01, no warnings before)."""
import csv, os, calendar, time, statistics as S
from datetime import datetime
import scanner, backtest as B

ts = lambda y, m, d: calendar.timegm((y, m, d, 0, 0, 0)) // 86400
START = ts(2020, 10, 1)
PH = [("cycle 1", ts(2020, 10, 1), ts(2021, 11, 10)), ("bear", ts(2021, 11, 10), ts(2022, 11, 21)), ("cycle 2", ts(2022, 11, 21), ts(2025, 10, 6)), ("since 2025 top", ts(2025, 10, 6), None)]
BAD = []; MM = 0.005; FEE = 0.0005; FUND = 0.0003
fd = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))

def ohlc(sym):
    rows = B.hist_crypto(sym, "1d", 2600); out = {}; prev = None
    for r in rows:
        d = int(r[0] // 86400); h, l, c = r[2], r[3], r[4]
        if prev and l < 0.5 * min(prev, c):          # a low more than 50% under both closes = bad data print, not a real trade
            BAD.append(f"{sym} {fd(d)}: low {l:,.2f} vs closes {prev:,.2f}/{c:,.2f} -> replaced by {0.97 * min(prev, c):,.2f}"); l = 0.97 * min(prev, c)
        out[d] = (h, l, c); prev = c
    return out

def signals(bt, days):
    n = len(days); C = [bt[d][2] for d in days]; ok = [False] * n; g200 = [False] * n; g50 = [False] * n
    for i in range(n):
        if i >= 199: g200[i] = C[i] > sum(C[i - 199:i + 1]) / 200
        if i >= 49: g50[i] = C[i] > sum(C[i - 49:i + 1]) / 50
    oi = {}; mp = os.path.join(scanner.HERE, "btc_metrics_daily.csv")
    if os.path.exists(mp):
        for r in csv.DictReader(open(mp)):
            try: oi[calendar.timegm(datetime.strptime(r["date"], "%Y-%m-%d").timetuple()) // 86400] = float(r["open_interest_btc"])
            except Exception: pass
    OI = [oi.get(d) for d in days]; W = [False] * n
    for i in range(n):
        prev = [x for x in OI[max(0, i - 180):i] if x]
        if OI[i] and len(prev) > 100 and OI[i] >= max(prev) and i >= 30 and OI[i - 30] and OI[i] / OI[i - 30] - 1 >= .15: W[i] = True
    cool = [False] * n; left = 0
    for i in range(n):
        if W[i]: left = 14
        cool[i] = left > 0
        if left > 0: left -= 1
    return [g200[i] and g50[i] and not cool[i] for i in range(n)], bool(oi)

def sim(px, days, sig, L, i0, i1=None):
    """px: dict day->(h,l,c). sig[i]=IN at close of day i (None = always in). Returns (equity curve list by index, trades, liquidated_day)."""
    n = len(days); i1 = n - 1 if i1 is None else i1; eq = 1.0; curve = {i0: 1.0}; pos = None; trades = []; dead = None
    for i in range(i0, i1 + 1):
        h, l, c = px[days[i]]
        if dead is None and pos is not None and i > pos["i"]:
            liq = pos["entry"] * (1 - (1 - MM * L) / L)
            pos["mae"] = min(pos["mae"], l / pos["entry"] - 1)
            pos["days"] += 1
            fund = FUND * L * pos["m0"] * pos["days"] if L > 1 else 0.0
            if l <= liq or pos["m0"] * (1 + L * (c / pos["entry"] - 1)) - fund <= MM * L * pos["m0"]:
                trades.append((pos["i"], i, pos["mae"], "LIQUIDATED")); dead = i; eq = 0.0; pos = None
            else:
                pos["val"] = pos["m0"] * (1 + L * (c / pos["entry"] - 1)) - fund
                eq = pos["val"]
        if dead is None:
            want = True if sig is None else sig[i]
            if pos is not None and (not want or i == i1 and False):
                eq = pos["val"] - FEE * L * pos["m0"] * (pos["val"] / pos["m0"]); trades.append((pos["i"], i, pos["mae"], "closed")); pos = None
            elif pos is None and want and i < i1:
                eq -= FEE * L * eq; pos = {"i": i, "entry": c, "m0": eq, "val": eq, "mae": 0.0, "days": 0}
        curve[i] = eq if pos is None else pos["val"]
    if pos is not None: trades.append((pos["i"], i1, pos["mae"], "open"))
    return curve, trades, dead

def at(curve, d, days, i0):
    i = max(i0, min(d, len(days) - 1)); 
    while i not in curve and i > i0: i -= 1
    return curve.get(i, 0.0)

def main():
    bt = ohlc("BTC"); et = ohlc("ETH")
    days = [d for d in sorted(bt) if d in et and d >= START - 260]; n = len(days)
    sig, oi_ok = signals(bt, days); idx = {d: i for i, d in enumerate(days)}
    i0 = next(i for i, d in enumerate(days) if d >= START)
    pe = [idx.get(PH[k][2], n - 1) if PH[k][2] else n - 1 for k in range(4)]
    L_ = ["LEVERAGE TEST: BTC and ETH at 1x / 2x / 3x, held vs. the alt-regime rule  (data to " + fd(days[-1]) + ")",
          "Rule: IN only while BTC > 200-day avg AND > 50-day avg AND no BTC open-interest warning C in the last 14 days. Isolated-margin long perpetual; liquidation checked against each day's LOW; 0.05% fee/side, funding 0.03%/day on notional (assumed).",
          "OI data " + ("loaded (from 2021-01)" if oi_ok else "NOT found, so the OI part of the rule is off") + ".",
          "Bad-data check (daily lows more than 50% below both neighbouring closes are treated as data glitches): " + ("; ".join(BAD) if BAD else "none found"), ""]
    sets = [("BTC", bt), ("ETH", et)]
    # ---- Part A
    L_ += ["== A. $10,000 on 1 Oct 2020, value at the end of each phase (LIQ = wiped out on that date; account stays at $0) =="]
    L_.append(f"{'':<26}" + "".join(f"{p[0]:>16}" for p in PH) + f"{'trades':>8}{'liq':>6}{'worst dip':>11}")
    for nm, px in sets:
        for rule in ("hold", "rule"):
            for L in (1, 2, 3):
                cur, tr, dead = sim(px, days, None if rule == "hold" else sig, L, i0)
                cells = []
                for k in range(4):
                    cells.append("LIQ " + fd(days[dead]) if dead is not None and dead <= pe[k] else "$%s" % format(10000 * at(cur, pe[k], days, i0), ",.0f"))
                ks = sorted(cur); peak = 0; wd = 0
                for i in ks: peak = max(peak, cur[i]); wd = min(wd, cur[i] / peak - 1 if peak else 0)
                L_.append(f"{nm + ' ' + rule + ' ' + str(L) + 'x':<26}" + "".join(f"{c:>16}" for c in cells) + f"{len(tr):>8}{sum(t[3] == 'LIQUIDATED' for t in tr):>6}{wd * 100:>10.0f}%")
        L_.append("")
    L_ += ["(worst dip = biggest fall of the account from a peak, measured at daily closes.)", ""]
    # ---- Part B
    L_ += ["== B. Does the start date matter? Same strategy started on every 30th day from 1 Oct 2020 (about 60 start dates), each run to the latest day =="]
    L_.append(f"{'':<22}{'starts':>8}{'liquidated':>12}{'median final x':>16}{'worst final x':>15}{'best final x':>14}{'ended below 1x':>16}")
    for nm, px in sets:
        for rule in ("hold", "rule"):
            for L in (1, 2, 3):
                fin = []; liqn = 0; starts = list(range(i0, n - 60, 30))
                for s in starts:
                    cur, tr, dead = sim(px, days, None if rule == "hold" else sig, L, s)
                    if dead is not None: liqn += 1
                    fin.append(cur[max(cur)])
                L_.append(f"{nm + ' ' + rule + ' ' + str(L) + 'x':<22}{len(starts):>8}{liqn:>12}{S.median(fin):>15.2f}x{min(fin):>14.2f}x{max(fin):>13.2f}x{sum(f < 1 for f in fin):>16}")
        L_.append("")
    # ---- Part C
    L_ += ["== C. How far did each IN spell fall below its entry price (intraday low)? This is what decides liquidation. Liquidation distance: 2x = 49.5%, 3x = 33.0%, 5x = 19.0% =="]
    L_.append(f"{'asset':<8}{'IN spells':>10}{'median dip':>12}{'worst dip':>11}{'>=19% (5x dead)':>17}{'>=33% (3x dead)':>17}{'>=49.5% (2x dead)':>19}")
    for nm, px in sets:
        cur, tr, dead = sim(px, days, sig, 1, i0)
        m = [t[2] for t in tr]
        if m: L_.append(f"{nm:<8}{len(m):>10}{S.median(m) * 100:>11.0f}%{min(m) * 100:>10.0f}%{sum(x <= -.19 for x in m):>17}{sum(x <= -.33 for x in m):>17}{sum(x <= -.495 for x in m):>19}")
    mm = []
    for nm, px in sets:
        cur, tr, dead = sim(px, days, sig, 1, i0)
        for a, b, mae, st in tr: mm.append((mae, nm, fd(days[a]), fd(days[b])))
    L_.append("Five worst IN spells (entry date -> exit date, deepest dip below entry):")
    for mae, nm, a, b in sorted(mm)[:5]: L_.append(f"   {nm}  {a} -> {b}   {mae * 100:.0f}%")
    L_.append("")
    # ---- Part D
    L_ += ["== D. If you entered at the latest daily close (" + fd(days[-1]) + "), where would liquidation sit? =="]
    for nm, px in sets:
        c = px[days[-1]][2]
        L_.append(f"{nm} close {c:,.2f}:  " + "   ".join(f"{L}x liquidates at {c * (1 - (1 - MM * L) / L):,.2f} (-{(1 - MM * L) / L * 100:.1f}%)" for L in (2, 3, 5)))
    L_ += ["", "Read: leverage multiplies both the gain and the dip. A position survives only if no intraday dip below entry reaches the liquidation distance; part C shows how often that happened to the rule's IN spells, part B shows how much the answer depends on when you start.",
           "Caveats: daily candles hide intraday wicks that could liquidate sooner than the low we see only if the low itself is reached (we do use the low), but real exchange mark-price wicks, funding spikes, and fees can differ; BTC and ETH are survivors; OI flag chosen with hindsight; only ~3 market phases; not advice."]
    text = "\n".join(L_); open(os.path.join(scanner.HERE, "lever_report.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
