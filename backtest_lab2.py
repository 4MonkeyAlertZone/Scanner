#!/usr/bin/env python3
"""Strategy lab 2: different strategy FAMILIES (trend breakouts, pullbacks inside trends, moving-average crosses, oversold/overbought
bounces), long and short, each with and without a market-trend filter (BTC for crypto, SPY for stocks). Signals use only closed candles,
entry is the NEXT candle's open (realistic for an alert), trades never overlap per symbol, and costs are included.
Same honest method as backtest_lab.py: variants are chosen ONLY on the older two thirds of each market's history and judged on the
newest third, which the search never saw; a rule counts as HOLDS only if it also beats random entries with the same stop and target.
Needs scanner.py, backtest.py and backtest_lab.py in the same folder.  Writes lab2_summary.txt, lab2_results.csv, lab2_candidates.csv.gz."""
import csv, gzip, math, os, random
from bisect import bisect_right
from datetime import datetime, timezone
from multiprocessing import Pool
import scanner, backtest as B, backtest_lab as L

N_CRYPTO = int(os.environ.get("LAB2_CRYPTO", "30"))
N_STOCKS = int(os.environ.get("LAB2_STOCKS", "30"))
MONTHS = int(os.environ.get("LAB2_MONTHS", "36"))
STOCK_YEARS = int(os.environ.get("LAB2_STOCK_YEARS", "8"))
HOR = {"crypto": (42, 84), "stock": (10, 20)}      # two holding limits (candles): 7 / 14 days of 4H, 10 / 20 trading days
STOP_ATR = (1.5, 2.5)                              # stop distance from entry, in ATRs
TARGETS = ("2R", "3R", "none")                     # take profit at 2x / 3x the risk, or just hold to the time limit
OUT = scanner.HERE
MIN_TRAIN_N = int(os.environ.get("LAB2_MIN_N", "150"))
REG = {}                                           # market -> (epochs, 1 if the reference index is above its 200-candle average)

# ---------------------------------------------------------------- indicators and signal definitions
def prefix(x):
    p = [0.0]
    for a in x: p.append(p[-1] + a)
    return p

def indicators(m):
    n = len(m); c = [r[4] for r in m]; h = [r[2] for r in m]; l = [r[3] for r in m]; v = [r[5] for r in m]
    pc, pv = prefix(c), prefix(v)
    def sma(k): return [None] * (k - 1) + [(pc[i + 1] - pc[i + 1 - k]) / k for i in range(k - 1, n)]
    I = dict(c=c, sma20=sma(20), sma50=sma(50), sma200=sma(200))
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1])) for i in range(1, n)]
    pt = prefix(tr)
    I["atr"] = [None] * 14 + [(pt[i + 1] - pt[i - 13]) / 14 for i in range(14, n)]
    I["volr"] = [None] * 20 + [v[i] / ((pv[i] - pv[i - 20]) / 20) if pv[i] - pv[i - 20] > 0 else None for i in range(20, n)]
    for N in (20, 55):
        I[f"hh{N}"] = [None] * N + [max(h[i - N:i]) for i in range(N, n)]
        I[f"ll{N}"] = [None] * N + [min(l[i - N:i]) for i in range(N, n)]
    g = lo = 0.0; rsi = [None] * n
    for i in range(1, n):
        x = c[i] - c[i-1]
        if i <= 14:
            g += max(x, 0); lo += max(-x, 0)
            if i == 14: g, lo = g / 14, lo / 14; rsi[i] = 100 - 100 / (1 + g / lo) if lo else 100.0
        else:
            g = (g * 13 + max(x, 0)) / 14; lo = (lo * 13 + max(-x, 0)) / 14
            rsi[i] = 100 - 100 / (1 + g / lo) if lo else 100.0
    I["rsi"] = rsi
    bl, bu = [None] * n, [None] * n
    for i in range(19, n):
        w = c[i - 19:i + 1]; mu = I["sma20"][i]; sd = math.sqrt(sum((x - mu) ** 2 for x in w) / 20)
        bl[i], bu[i] = mu - 2 * sd, mu + 2 * sd
    I["bbl"], I["bbu"] = bl, bu
    return I

def definitions():
    """(name, side, test(I, i)). Every test uses only data up to and including closed candle i."""
    D = []
    def ok(*xs): return all(x is not None for x in xs)
    for N in (20, 55):
        for vol in (0, 1.5):
            for tr in (0, 1):
                nm = f"breakout {N}-candle high{' + volume>=1.5x' if vol else ''}{' + above 200-avg' if tr else ''}"
                D.append((nm, "long", lambda I, i, N=N, vol=vol, tr=tr: ok(I[f"hh{N}"][i], I["sma200"][i], I["volr"][i]) and I["c"][i] > I[f"hh{N}"][i]
                          and (not vol or I["volr"][i] >= vol) and (not tr or I["c"][i] > I["sma200"][i])))
                nm = f"breakdown {N}-candle low{' + volume>=1.5x' if vol else ''}{' + below 200-avg' if tr else ''}"
                D.append((nm, "short", lambda I, i, N=N, vol=vol, tr=tr: ok(I[f"ll{N}"][i], I["sma200"][i], I["volr"][i]) and I["c"][i] < I[f"ll{N}"][i]
                          and (not vol or I["volr"][i] >= vol) and (not tr or I["c"][i] < I["sma200"][i])))
    for T in (30, 40):
        D.append((f"pullback in uptrend: RSI falls to <={T}", "long", lambda I, i, T=T: ok(I["rsi"][i], I["rsi"][i-1], I["sma200"][i], I["sma50"][i])
                  and I["c"][i] > I["sma200"][i] and I["sma50"][i] > I["sma200"][i] and I["rsi"][i] <= T < I["rsi"][i-1]))
        D.append((f"bounce in downtrend: RSI rises to >={100 - T}", "short", lambda I, i, T=T: ok(I["rsi"][i], I["rsi"][i-1], I["sma200"][i], I["sma50"][i])
                  and I["c"][i] < I["sma200"][i] and I["sma50"][i] < I["sma200"][i] and I["rsi"][i] >= 100 - T > I["rsi"][i-1]))
    D.append(("20/50 average cross up, above 200-avg", "long", lambda I, i: ok(I["sma20"][i-1], I["sma50"][i-1], I["sma200"][i]) and I["sma20"][i] > I["sma50"][i]
              and I["sma20"][i-1] <= I["sma50"][i-1] and I["c"][i] > I["sma200"][i]))
    D.append(("20/50 average cross down, below 200-avg", "short", lambda I, i: ok(I["sma20"][i-1], I["sma50"][i-1], I["sma200"][i]) and I["sma20"][i] < I["sma50"][i]
              and I["sma20"][i-1] >= I["sma50"][i-1] and I["c"][i] < I["sma200"][i]))
    D.append(("oversold: RSI falls to <=20", "long", lambda I, i: ok(I["rsi"][i], I["rsi"][i-1]) and I["rsi"][i] <= 20 < I["rsi"][i-1]))
    D.append(("overbought: RSI rises to >=80", "short", lambda I, i: ok(I["rsi"][i], I["rsi"][i-1]) and I["rsi"][i] >= 80 > I["rsi"][i-1]))
    D.append(("closes below lower Bollinger band + RSI<=30", "long", lambda I, i: ok(I["bbl"][i], I["rsi"][i]) and I["c"][i] < I["bbl"][i] and I["rsi"][i] <= 30))
    D.append(("closes above upper Bollinger band + RSI>=70", "short", lambda I, i: ok(I["bbu"][i], I["rsi"][i]) and I["c"][i] > I["bbu"][i] and I["rsi"][i] >= 70))
    return D

DEFS = definitions()

def regime(market, t, side):
    ep, up = REG[market]
    j = bisect_right(ep, t) - 1
    if j < 0: return 0
    return int(up[j] if side == "long" else not up[j])    # 1 = the market trend agrees with the trade direction

def exits(side, m, i, I, mk, rnd, first, last):
    """Result under every stop / target / holding-limit combination (entry = next candle open), plus a matched random-entry control."""
    e, atr = m[i + 1][1], I["atr"][i]
    out = {}
    for s, sm in enumerate(STOP_ATR):
        stop = e - sm * atr if side == "long" else e + sm * atr
        risk = abs(e - stop)
        if risk <= 0 or stop <= 0: return None
        for t, tn in enumerate(TARGETS):
            k = {"2R": 2, "3R": 3}.get(tn)
            tgt = None if k is None else (e + k * risk if side == "long" else e - k * risk)
            for hi, H in enumerate(HOR[mk]):
                fut = m[i + 1:i + 1 + H]
                r = L.sim(side, e, stop, tgt, fut)
                if r is None: return None
                x = rnd.randrange(first, last - H); ce = m[x + 1][1]
                sp, tp = risk / e, (abs(tgt - e) / e if tgt else None)
                cs = ce * (1 - sp) if side == "long" else ce * (1 + sp)
                ct = (ce * (1 + tp) if side == "long" else ce * (1 - tp)) if tp else None
                cr = L.sim(side, ce, cs, ct, m[x + 1:x + 1 + H])
                out[f"R{s}{t}{hi}"] = round(r, 4); out[f"C{s}{t}{hi}"] = "" if cr is None else round(cr, 4)
    return out

def lab_symbol(a):
    tok, market = a
    try:
        if market == "crypto": m = B.hist_crypto(tok, "4h", MONTHS * 180 + 520); ntest = MONTHS * 180
        else: m = B.hist_stock(tok, "1d"); ntest = STOCK_YEARS * 252
        if len(m) < 500: return tok, [], "not enough history"
        I = indicators(m)
        Hmax = HOR[market][1]
        first = max(210, len(m) - Hmax - 2 - ntest); last = len(m) - 1
        rnd, rows = random.Random(tok), []
        nxt = {nm: 0 for nm, _, _ in DEFS}           # index before which this definition may not fire again (no overlapping trades)
        for i in range(first, last - Hmax - 1):
            if I["atr"][i] is None: continue
            for nm, side, fn in DEFS:
                if i < nxt[nm] or not fn(I, i): continue
                ex = exits(side, m, i, I, market, rnd, first, last - 1)
                if not ex: continue
                nxt[nm] = i + HOR[market][0]
                rows.append(dict(side=side, rule=nm, market=market, sym=tok, epoch=int(m[i][0]), reg=regime(market, m[i][0], side), **ex))
        return tok, rows, ""
    except Exception as e:
        return tok, [], str(e)[:80]

def ref_regime(market):
    m = B.hist_crypto("BTC", "4h", MONTHS * 180 + 520) if market == "crypto" else B.hist_stock("SPY", "1d")
    I = indicators(m)
    ep = [r[0] for r in m]; up = [bool(I["sma200"][i] and I["c"][i] > I["sma200"][i]) for i in range(len(m))]
    return ep, up

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

def fmt_acc(a):
    mu, ci = mean_ci(a)
    return f"n={a[0]:>5}  avg R {mu:+.2f} (+/-{ci:.2f})"

def evaluate(rows, reg, mk, key):
    A = [[0, 0.0, 0.0, 0.0] for _ in range(3)]
    ck = "C" + key[1:]
    for r in rows:
        if reg and not r["reg"]: continue
        if mk != "all" and r["market"] != mk: continue
        x = r.get(key, "")
        if x == "": continue
        a = A[r["fold"]]; c = r.get(ck, "")
        a[0] += 1; a[1] += x; a[2] += x * x; a[3] += x - (c if c != "" else 0)
    return A

def exit_label(s, t, h, mk):
    hs = "/".join(str(x) for x in HOR["crypto" if mk == "crypto" else "stock"]) if mk != "all" else "time limit"
    return f"stop {STOP_ATR[s]} ATR, target {TARGETS[t] if TARGETS[t] != 'none' else 'none (time exit)'}, hold {'short' if h == 0 else 'long'} limit"

def summarise(rows, errs):
    L_ = [f"STRATEGY LAB 2  {datetime.now(timezone.utc):%Y-%m-%d}   (crypto: {MONTHS} months of 4H; stocks: {STOCK_YEARS} years daily; entry at the next candle's open)",
          "R = profit in units of the risk to the stop, after 0.2% costs. Variants are chosen on the older two thirds of history; the newest third is the unseen test.",
          "Trades never overlap per symbol and rule, but different symbols move together, so real error margins are wider than printed.", ""]
    by = {}
    for r in rows: by.setdefault((r["side"], r["rule"]), []).append(r)
    variants = []
    for (side, rule), rs in by.items():
        for reg in (0, 1):
            for mk in ("all", "crypto", "stock"):
                for s in range(len(STOP_ATR)):
                    for t in range(len(TARGETS)):
                        for h in range(2):
                            A = evaluate(rs, reg, mk, f"R{s}{t}{h}")
                            tr = [A[0][k] + A[1][k] for k in range(4)]
                            if tr[0] >= MIN_TRAIN_N: variants.append(dict(side=side, rule=rule, reg=reg, mk=mk, s=s, t=t, h=h, A=A, tr=tr))
    L_.append(f"{len(rows)} trades simulated. Variants with enough trades to judge: {len(variants)}.")
    good = [v for v in variants if tstat(v["tr"]) >= 2]
    L_.append(f"{len(good)} looked clearly profitable in training (t>=2).")
    if good:
        pos = sum(1 for v in good if v["A"][2][1] > 0)
        tm = sum(v["A"][2][1] / v["A"][2][0] for v in good if v["A"][2][0]) / max(1, sum(1 for v in good if v["A"][2][0]))
        L_.append(f"Overfitting meter: of those, {pos} ({pos / len(good):.0%}) were also positive on the unseen test period; their average test R was {tm:+.3f}. (Pure noise: about 50% and about -0.03.)")
    L_ += ["", "-- Every strategy family at a plain setting (stop 1.5 ATR, target 2x risk, short holding limit, all markets), by third of history --",
           "   'excess' = average R minus random entries with the same stop and target.  Columns: oldest / middle / NEWEST", ""]
    for (side, rule), rs in sorted(by.items()):
        for reg in (0, 1):
            A = evaluate(rs, reg, "all", "R010")
            if A[0][0] + A[1][0] + A[2][0] < 90: continue
            L_.append(f"{side:<5} {rule}{'  [only when market trend agrees]' if reg else ''}")
            L_.append("      " + "   |   ".join(f"{['old', 'mid', 'NEW'][k]} n={A[k][0]} {mean_ci(A[k])[0]:+.2f}R (excess {(A[k][3] / A[k][0] if A[k][0] else 0):+.2f})" for k in range(3)))
    elig = [v for v in variants if v["A"][0][0] and v["A"][1][0] and v["A"][0][1] > 0 and v["A"][1][1] > 0 and tstat(v["tr"]) >= 2]
    elig.sort(key=lambda v: -tstat(v["tr"]))
    top, seen = [], set()
    for v in elig:
        k = (v["side"], round(v["tr"][1], 2), v["tr"][0])
        if k in seen: continue
        seen.add(k); top.append(v)
        if len(top) == 15: break
    L_ += ["", f"-- Top {len(top)} variants picked ONLY from training (profitable in both training periods, t>=2), then checked on the unseen test period --"]
    results, holds = [], 0
    for v in top:
        te = v["A"][2]; mu, ci = mean_ci(te); ex = te[3] / te[0] if te[0] else 0
        status = "HOLDS" if te[0] >= 40 and mu - ci > 0 and ex > 0 else "WEAK" if te[0] >= 40 and mu > 0 else "FAILS"
        holds += status == "HOLDS"
        lab = f"{v['side']} | {v['mk']} | {v['rule']}{' | only when market trend agrees' if v['reg'] else ''} | {exit_label(v['s'], v['t'], v['h'], v['mk'])}"
        L_ += [f"- {lab}", f"    train {fmt_acc(v['tr'])}   TEST {fmt_acc(te)}   vs random {ex:+.2f}   [{status}]"]
        results.append(dict(rule=lab, train_n=v["tr"][0], train_avgR=round(mean_ci(v["tr"])[0], 3), test_n=te[0], test_avgR=round(mu, 3), test_ci=round(ci, 3), vs_random=round(ex, 3), status=status))
    tested = [v for v in top if v["A"][2][0] >= 40]
    avg = sum(v["A"][2][1] / v["A"][2][0] for v in tested) / len(tested) if tested else 0
    npos = sum(1 for v in tested if v["A"][2][1] > 0)
    L_ += ["", f"Procedure result: 'pick the best in training' gave an average TEST result of {avg:+.3f}R, {npos} of {len(tested)} positive, {holds} clearly holding."]
    if holds >= 3 and avg > 0.05: verdict = "Some rules held up on unseen data. Worth paper-trading forward before any real money."
    elif tested and avg > 0 and npos >= len(tested) * .6: verdict = "Weak hints only. Not enough to rely on."
    else: verdict = "NOTHING survived. Rules that looked good in training did not hold on unseen data."
    L_ += ["", "VERDICTS", verdict]
    if errs: L_ += ["", "Could not test: " + ", ".join(f"{t} ({e})" for t, e in errs[:6])]
    return "\n".join(L_), results

def main():
    for mk in ("crypto", "stock"):
        try: REG[mk] = ref_regime(mk)
        except Exception as e: print("could not load the", mk, "market reference:", e); REG[mk] = ([0], [False])
    jobs = [(t, "crypto") for t in scanner.top100()[:N_CRYPTO]] + [(s, "stock") for s in scanner.BIG_STOCKS[:N_STOCKS]]
    print(f"Testing {len(DEFS)} rule definitions on {len(jobs)} symbols...", flush=True)
    with Pool(max(1, os.cpu_count() or 1)) as p: res = p.map(lab_symbol, jobs)
    rows = [r for _, rs, _ in res for r in rs]; errs = [(t, e) for t, _, e in res if e]
    for mk in ("crypto", "stock"):
        ep = sorted(r["epoch"] for r in rows if r["market"] == mk)
        if not ep: continue
        c1, c2 = ep[len(ep) // 3], ep[2 * len(ep) // 3]
        for r in rows:
            if r["market"] == mk: r["fold"] = 0 if r["epoch"] < c1 else 1 if r["epoch"] < c2 else 2
    if rows:
        cols = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("side", "rule", "market", "sym", "epoch", "fold", "reg"), k))
        with gzip.open(os.path.join(OUT, "lab2_candidates.csv.gz"), "wt", newline="") as f:
            w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)
    text, results = summarise(rows, errs) if rows else ("No signals found. " + str(errs[:3]), [])
    if rows: text = B.coverage(rows) + "\n" + text
    if results:
        with open(os.path.join(OUT, "lab2_results.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, list(results[0].keys())); w.writeheader(); w.writerows(results)
    with open(os.path.join(OUT, "lab2_summary.txt"), "w") as f: f.write(text + "\n")
    print("\n" + text)
    try:
        import paper
        scanner.notify("Strategy lab 2 finished", "VERDICTS" + text.split("VERDICTS")[-1], scanner.NTFY_TOPIC, "microscope")
        paper.attach(os.path.join(OUT, "lab2_summary.txt"))
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
