#!/usr/bin/env python3
"""Strategy lab 3: "when BTC is in a rising mini-cycle, pick the best altcoin setups". Tests, on real 4H history:
  1) five definitions of a rising BTC market (a gate), against random altcoin entries in the same conditions,
  2) six altcoin buy-signal families (breakouts, pullbacks in uptrends, relative-strength leaders...),
  3) whether ranking signals (relative strength vs BTC, volume, volatility, headroom to the old high) really finds the better ones,
  4) a take-profit ladder: sell a third at TP1 (1x risk), TP2 (2x), TP3 (3x), with how often each is hit and the % gain.
Entry is the NEXT candle's open; the stop is checked before any target inside the same candle; costs of 0.2% are included.
Same honest method as the other labs: variants are chosen on the older two thirds of history and judged on the newest third.
Needs scanner.py, backtest.py, backtest_lab.py, backtest_lab2.py in the same folder.
Writes lab3_summary.txt, lab3_results.csv, lab3_candidates.csv.gz.  Run: python backtest_lab3.py"""
import csv, gzip, math, os, random
from bisect import bisect_right
from datetime import datetime, timezone
from multiprocessing import Pool
import scanner, backtest as B, backtest_lab2 as L2

N_COINS = int(os.environ.get("LAB3_COINS", "60"))
MONTHS = int(os.environ.get("LAB3_MONTHS", "36"))
STOPS = (1.5, 2.5)                  # stop distance below entry, in ATRs
HORS = (42, 84)                     # time limit in 4H candles: 7 days / 14 days
COST = B.COST
OUT = scanner.HERE
MIN_N = int(os.environ.get("LAB3_MIN_N", "100"))
REGS = ("any BTC", "BTC above 50-avg", "BTC rising (20>50, above 50)", "BTC 7-day up + above 20-avg", "BTC above 200-avg", "BTC strong rise (rising + 7d > +3%)")
BTC = {}
FAMS = ("breakout 20 + volume", "breakout 55", "breakout 20 + leads BTC", "pullback in uptrend (RSI<=40)", "20/50 cross up", "leader pullback (RSI<=45)")

def ladder(e, stop, fut):
    """Sell a third at 1x, 2x and 3x the risk. Unfilled thirds are stopped at -1 R or closed at the end. Stop is checked first in each candle."""
    risk = e - stop
    if risk <= 0 or not fut: return None
    tp = (e + risk, e + 2 * risk, e + 3 * risk); hit = [False] * 3; stopped = False
    for _, o, h, l, c, v in fut:
        if l <= stop: stopped = True; break
        for k in range(3):
            if h >= tp[k]: hit[k] = True
        if hit[2]: break
    mtm = (fut[-1][4] - e) / risk
    cost = COST * e / risk
    leg = lambda k: (k + 1) if hit[k] else (-1.0 if stopped else mtm)
    return dict(ladder=sum(leg(k) for k in range(3)) / 3 - cost, single=leg(1) - cost, hit="".join("1" if x else "0" for x in hit))

def btc_setup():
    m = B.hist_crypto("BTC", "4h", MONTHS * 180 + 520)
    I = L2.indicators(m); c = I["c"]; flags = []
    for i in range(len(m)):
        s20, s50, s200 = I["sma20"][i], I["sma50"][i], I["sma200"][i]
        r42 = c[i] / c[i - 42] - 1 if i >= 42 else 0.0
        f50 = bool(s50 and c[i] > s50); up = bool(s20 and s50 and s20 > s50 and c[i] > s50)
        mom = bool(s20 and r42 > 0 and c[i] > s20); f200 = bool(s200 and c[i] > s200)
        flags.append((1, int(f50), int(up), int(mom), int(f200), int(up and r42 > .03)))
    BTC.update(ep=[r[0] for r in m], c=c, flags=flags)

def fams(I, i, rs30, rs60):
    c, out = I["c"][i], []
    hh20, hh55, vr, s50, s200, rsi, rp = I["hh20"][i], I["hh55"][i], I["volr"][i], I["sma50"][i], I["sma200"][i], I["rsi"][i], I["rsi"][i-1]
    if None in (hh20, hh55, vr, s50, s200, rsi, rp, I["sma20"][i], I["sma20"][i-1], I["sma50"][i-1]): return out
    if c > hh20 and vr >= 1.5: out.append(FAMS[0])
    if c > hh55: out.append(FAMS[1])
    if c > hh20 and rs30 > 0: out.append(FAMS[2])
    if rsi <= 40 < rp and c > s200 and s50 > s200: out.append(FAMS[3])
    if I["sma20"][i] > I["sma50"][i] and I["sma20"][i-1] <= I["sma50"][i-1] and c > s200: out.append(FAMS[4])
    if rsi <= 45 < rp and c > s50 and rs60 > .10: out.append(FAMS[5])
    return out

def alt_symbol(tok):
    try:
        m = B.hist_crypto(tok, "4h", MONTHS * 180 + 520); ntest = MONTHS * 180
        if len(m) < 500: return tok, [], "not enough history"
        cl = [r[4] for r in m]
        if max(cl) / min(cl) < 1.15: return tok, [], "pegged coin, skipped"
        I = L2.indicators(m); Hmax = max(HORS)
        first = max(260, len(m) - Hmax - 2 - ntest); last = len(m) - 1
        rnd, rows, nxt = random.Random(tok), [], {f: 0 for f in FAMS}
        ep, bc, fl = BTC["ep"], BTC["c"], BTC["flags"]
        for i in range(first, last - Hmax - 1):
            if I["atr"][i] is None or i < 70: continue
            j = bisect_right(ep, m[i][0]) - 1
            if j < 70: continue
            rs30 = (cl[i] / cl[i - 30] - 1) - (bc[j] / bc[j - 30] - 1); rs60 = (cl[i] / cl[i - 60] - 1) - (bc[j] / bc[j - 60] - 1)
            sig = [f for f in fams(I, i, rs30, rs60) if i >= nxt[f]]
            if not sig: continue
            e, atr = m[i + 1][1], I["atr"][i]
            k = rnd.randrange(first, last - Hmax - 1); ce = m[k + 1][1]
            jc = bisect_right(ep, m[k][0]) - 1
            base = dict(sym=tok, epoch=int(m[i][0]), rs30=round(rs30 * 100, 2), rs60=round(rs60 * 100, 2), volr=round(I["volr"][i], 2),
                        atrp=round(atr / cl[i] * 100, 2), room=round(max(0.0, (max(r[2] for r in m[i - 120:i]) - cl[i]) / atr), 1))
            for g, v in enumerate(fl[j]): base[f"g{g}"] = v
            for g, v in enumerate(fl[max(jc, 0)]): base[f"cg{g}"] = v
            ok = True; ex = {}
            for s, sm in enumerate(STOPS):
                stop = e - sm * atr
                if stop <= 0 or stop >= e: ok = False; break
                ex[f"RK{s}"] = round((e - stop) / e * 100, 2); cstop = ce * (1 - (e - stop) / e)
                for h, H in enumerate(HORS):
                    a, b = ladder(e, stop, m[i + 1:i + 1 + H]), ladder(ce, cstop, m[k + 1:k + 1 + H])
                    if not a or not b: ok = False; break
                    ex[f"L{s}{h}"], ex[f"S{s}{h}"], ex[f"T{s}{h}"] = round(a["ladder"], 4), round(a["single"], 4), a["hit"]
                    ex[f"CL{s}{h}"], ex[f"CS{s}{h}"] = round(b["ladder"], 4), round(b["single"], 4)
                if not ok: break
            if not ok: continue
            for f in sig:
                nxt[f] = i + HORS[0]
                rows.append(dict(base, fam=f, **ex))
        return tok, rows, ""
    except Exception as e:
        return tok, [], str(e)[:80]

# ---------------------------------------------------------------- analysis
def mean_ci(a):
    n = a[0]
    if not n: return 0.0, 0.0
    mu = a[1] / n
    if n < 2: return mu, 0.0
    return mu, 1.96 * math.sqrt(max(0.0, (a[2] - n * mu * mu) / (n - 1)) / n)

def tstat(a):
    mu, ci = mean_ci(a)
    return mu / (ci / 1.96) if ci > 0 else 0.0

def new(): return [0, 0.0, 0.0]
def push(a, x): a[0] += 1; a[1] += x; a[2] += x * x
def f_acc(a): mu, ci = mean_ci(a); return f"n={a[0]:>5} {mu:+.2f}R (+/-{ci:.2f})"

def baselines(rows):
    """Average result of RANDOM altcoin entries made while each BTC condition held, per third of history, for every exit style."""
    out = {}
    for ck in [f"C{st}{s}{h}" for st in "LS" for s in range(2) for h in range(2)]:
        for g in range(len(REGS)):
            for fo in range(3):
                a = new()
                for r in rows:
                    if r["fold"] == fo and r[f"cg{g}"]: push(a, r[ck])
                out[(ck, g, fo)] = a[1] / a[0] if a[0] else 0.0
    return out

def variant(rows, fam, g, key, base):
    A = [new() for _ in range(3)]; rk = [0.0, 0]
    for r in rows:
        if r["fam"] != fam or (g and not r[f"g{g}"]): continue
        push(A[r["fold"]], r[key])
    return A

def summarise(rows, errs):
    T = [f"STRATEGY LAB 3  {datetime.now(timezone.utc):%Y-%m-%d}   ({N_COINS} altcoins by market cap, {MONTHS} months of 4H; entry at the next candle's open)",
         "R = profit in units of the risk to the stop, after 0.2% costs. 'excess' = result minus RANDOM altcoin entries made while the same BTC condition held.",
         "Choices are made on the older two thirds; the newest third is the unseen test. Altcoins move together, so real error margins are wider than printed.", ""]
    base = baselines(rows)
    T += ["== 1) Does a rising BTC help ANY altcoin buy? Random altcoin entries only, average R by BTC condition (stop 2.5 ATR, 7-day limit, TP ladder) ==",
          "   Columns: oldest third / middle third / NEWEST third"]
    for g in range(len(REGS)):
        T.append(f"   {REGS[g]:<42}" + "  ".join(f"{base[('CL10', g, fo)]:+.2f}R" for fo in range(3)))
    T += ["", "== 2) Every signal family under every BTC condition (stop 2.5 ATR, 7-day limit, TP ladder 1x/2x/3x risk) ==",
          "   Each cell: signals, avg R (excess vs random in the same BTC condition).  Columns: oldest / middle / NEWEST", ""]
    for fam in FAMS:
        T.append(fam)
        for g in range(len(REGS)):
            A = variant(rows, fam, g, "L10", base)
            if sum(a[0] for a in A) < 40: continue
            T.append(f"   {REGS[g]:<42}" + " | ".join(f"n={A[fo][0]:>4} {mean_ci(A[fo])[0]:+.2f} ({mean_ci(A[fo])[0] - base[('CL10', g, fo)]:+.2f})" for fo in range(3)))
    V = []
    for fam in FAMS:
        for g in range(len(REGS)):
            for s in range(2):
                for h in range(2):
                    for st, nm in (("L", "ladder"), ("S", "single 2x target")):
                        A = variant(rows, fam, g, f"{st}{s}{h}", base); tr = [A[0][k] + A[1][k] for k in range(3)]
                        if tr[0] >= MIN_N: V.append(dict(fam=fam, g=g, s=s, h=h, st=st, nm=nm, A=A, tr=tr))
    good = [v for v in V if tstat(v["tr"]) >= 2]
    T += ["", f"== 3) Search: {len(V)} variants with enough trades; {len(good)} looked clearly profitable in training (t>=2) =="]
    if good:
        pos = sum(1 for v in good if v["A"][2][1] > 0); tm = sum(mean_ci(v["A"][2])[0] for v in good if v["A"][2][0]) / max(1, sum(1 for v in good if v["A"][2][0]))
        T.append(f"Overfitting meter: {pos} of {len(good)} ({pos / len(good):.0%}) were also positive on the unseen newest third; their average test R was {tm:+.3f}. (Pure noise: ~50% and ~-0.03.)")
    elig = [v for v in V if v["A"][0][0] and v["A"][1][0] and v["A"][0][1] > 0 and v["A"][1][1] > 0 and tstat(v["tr"]) >= 2]
    elig.sort(key=lambda v: -tstat(v["tr"]))
    top, seen = [], set()
    for v in elig:
        k = (round(v["tr"][1], 2), v["tr"][0])
        if k in seen: continue
        seen.add(k); top.append(v)
        if len(top) == 12: break
    T += ["", f"Top {len(top)} picked ONLY from training, then checked on the unseen newest third:"]
    holds, results = [], []
    for v in top:
        te = v["A"][2]; mu, ci = mean_ci(te); ex = mu - base[(("C" + v["st"] + f"{v['s']}{v['h']}"), v["g"], 2)]
        status = "HOLDS" if te[0] >= 40 and mu - ci > 0 and ex > 0 else "WEAK" if te[0] >= 40 and mu > 0 else "FAILS"
        if status == "HOLDS": holds.append(v)
        lab = f"{v['fam']} | {REGS[v['g']]} | stop {STOPS[v['s']]} ATR | limit {'7' if v['h'] == 0 else '14'} days | {v['nm']}"
        T += [f"- {lab}", f"    train {f_acc(v['tr'])}   TEST {f_acc(te)}   vs random in same BTC condition {ex:+.2f}   [{status}]"]
        results.append(dict(rule=lab, train_n=v["tr"][0], train_avgR=round(mean_ci(v["tr"])[0], 3), test_n=te[0], test_avgR=round(mu, 3), test_ci=round(ci, 3), vs_random=round(ex, 3), status=status))
    tested = [v for v in top if v["A"][2][0] >= 40]
    avg = sum(mean_ci(v["A"][2])[0] for v in tested) / len(tested) if tested else 0
    npos = sum(1 for v in tested if v["A"][2][1] > 0)
    T += ["", f"Procedure result: average TEST result {avg:+.3f}R, {npos} of {len(tested)} positive, {len(holds)} clearly holding."]
    # take-profit ladder and ranking for the best candidates
    focus = holds[:3] or top[:2]
    if focus:
        T += ["", "== 4) Take-profit ladder for the leading rules: how often each target was reached, and the % gain if it is =="]
        for v in focus:
            sub = [r for r in rows if r["fam"] == v["fam"] and (not v["g"] or r[f"g{v['g']}"])]
            for nm, sel in (("all history", sub), ("NEWEST third only", [r for r in sub if r["fold"] == 2])):
                if not sel: continue
                n = len(sel); T1, T2, T3 = (sum(r[f"T{v['s']}{v['h']}"][k] == "1" for r in sel) / n for k in range(3))
                rk = sum(r[f"RK{v['s']}"] for r in sel) / n
                T.append(f"- {v['fam']} | {REGS[v['g']]} | stop {STOPS[v['s']]} ATR ({rk:.1f}% below entry) | {nm}, {n} signals: "
                         f"TP1 hit {T1:.0%} (+{rk:.1f}%), TP2 hit {T2:.0%} (+{2 * rk:.1f}%), TP3 hit {T3:.0%} (+{3 * rk:.1f}%)")
        v = focus[0]
        T += ["", f"== 5) Does ranking work? '{v['fam']}' under '{REGS[v['g']]}': average ladder R by tercile of each ranking number (cut-offs from training data only) =="]
        sub = [r for r in rows if r["fam"] == v["fam"] and (not v["g"] or r[f"g{v['g']}"])]
        key = f"L{v['s']}{v['h']}"
        for feat, nm in (("rs30", "strength vs BTC (30 candles)"), ("volr", "volume vs normal"), ("atrp", "volatility (ATR %)"), ("room", "room below the old high (ATRs)")):
            tr = sorted(r[feat] for r in sub if r["fold"] < 2)
            if len(tr) < 30: continue
            c1, c2 = tr[len(tr) // 3], tr[2 * len(tr) // 3]
            parts = []
            for lab, f in (("low", lambda x: x <= c1), ("middle", lambda x: c1 < x <= c2), ("high", lambda x: x > c2)):
                a, b = new(), new()
                for r in sub:
                    if f(r[feat]): push(a if r["fold"] < 2 else b, r[key])
                parts.append(f"{lab}: train {mean_ci(a)[0]:+.2f}R (n={a[0]}), TEST {mean_ci(b)[0]:+.2f}R (n={b[0]})")
            T.append(f"   {nm}:  " + "   |   ".join(parts))
    if len(holds) >= 3 and avg > 0.05: verdict = "Some BTC-gated altcoin rules held up on unseen data. Worth building the ranked alert as a paper test first."
    elif tested and avg > 0 and npos >= len(tested) * .6: verdict = "Weak hints only. Not enough to build an alert on."
    else: verdict = "NOTHING survived. BTC-gated altcoin buying did not beat random entries on unseen data."
    T += ["", "VERDICTS", verdict]
    if errs: T += ["", "Not tested: " + ", ".join(f"{t} ({e})" for t, e in errs[:8])]
    return "\n".join(T), results

def main():
    btc_setup()
    coins = [c for c in scanner.top100() if c != "BTC"][:N_COINS]
    print(f"Testing {len(FAMS)} signal families on {len(coins)} altcoins against {len(REGS)} BTC conditions...", flush=True)
    with Pool(max(1, os.cpu_count() or 1)) as p: res = p.map(alt_symbol, coins)
    rows = [r for _, rs, _ in res for r in rs]; errs = [(t, e) for t, _, e in res if e]
    if rows:
        ep = sorted(r["epoch"] for r in rows); c1, c2 = ep[len(ep) // 3], ep[2 * len(ep) // 3]
        for r in rows: r["fold"] = 0 if r["epoch"] < c1 else 1 if r["epoch"] < c2 else 2
        cols = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("fam", "sym", "epoch", "fold"), k))
        with gzip.open(os.path.join(OUT, "lab3_candidates.csv.gz"), "wt", newline="") as f:
            w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)
    text, results = summarise(rows, errs) if rows else ("No signals found. " + str(errs[:3]), [])
    if rows: text = B.coverage([dict(market="crypto", epoch=r["epoch"]) for r in rows]) + "\n" + text
    if results:
        with open(os.path.join(OUT, "lab3_results.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, list(results[0].keys())); w.writeheader(); w.writerows(results)
    with open(os.path.join(OUT, "lab3_summary.txt"), "w") as f: f.write(text + "\n")
    print("\n" + text)
    try:
        import paper
        scanner.notify("Strategy lab 3 finished", "VERDICTS" + text.split("VERDICTS")[-1], scanner.NTFY_TOPIC, "microscope")
        paper.attach(os.path.join(OUT, "lab3_summary.txt"))
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
