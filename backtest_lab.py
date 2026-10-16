#!/usr/bin/env python3
"""Strategy lab. Replays the scanner over past candles (never peeking at the future) for LONG and SHORT signals, records every
candidate once with extra context (trend, RSI, volume), then tries thousands of rule variants (score, risk/reward, trend, stop
distance, target type...) on the OLDER two thirds of the history and checks the best of them on the NEWEST third, which the
search never saw. This is the honest way to ask: "is there a version of these rules that makes money, or are we just fitting the past?"
Needs scanner.py and backtest.py in the same folder. Writes lab_summary.txt, lab_results.csv, lab_candidates.csv.gz.  Run: python backtest_lab.py"""
import csv, gzip, itertools, math, os, random
from bisect import bisect_right
from datetime import datetime, timezone
from multiprocessing import Pool
import scanner, backtest as B

N_CRYPTO = int(os.environ.get("LAB_CRYPTO", "30"))
N_STOCKS = int(os.environ.get("LAB_STOCKS", "30"))
MONTHS = int(os.environ.get("LAB_MONTHS", "24"))              # months of 4H crypto history to replay
STOCK_YEARS = int(os.environ.get("LAB_STOCK_YEARS", "5"))     # years of daily stock history to replay
HORIZON = {"crypto": 42, "stock": 10}   # candles to wait for target/stop (7 days of 4H, 10 trading days)
COOL = {"crypto": 6, "stock": 3}        # ignore repeat signals on the same zone for this many candles
STOPS = (0.5, 1.0, 1.5)                 # stop distance beyond the zone, in ATRs (the scanner uses 0.5)
TARGETS = ("res", "1.5R", "2R", "3R")   # res = nearest resistance/support (scanner default); kR = fixed multiple of the risk
KR = {"1.5R": 1.5, "2R": 2.0, "3R": 3.0}
COST = B.COST
LONG_V, SHORT_V = ("BUY SIGNAL", "IN ZONE", "IN ZONE - WAIT"), ("SHORT SIGNAL", "AT TOP - WAIT")
OUT = scanner.HERE
MIN_TRAIN_N = 200

def sim(side, e, stop, target, fut):
    """R-multiple result after costs. If one candle touches both stop and target, the stop counts first."""
    risk = (e - stop) if side == "long" else (stop - e)
    if risk <= 0 or not fut: return None
    cost = COST * e / risk
    for _, o, h, l, c, v in fut:
        if side == "long":
            if l <= stop: return -1 - cost
            if target and h >= target: return (target - e) / risk - cost
        else:
            if h >= stop: return -1 - cost
            if target and l <= target: return (e - target) / risk - cost
    last = fut[-1][4]
    return ((last - e) if side == "long" else (e - last)) / risk - cost

def atr_of(d):
    tr = [max(r["h"] - r["l"], abs(r["h"] - d[i-1]["c"]), abs(r["l"] - d[i-1]["c"])) if i else r["h"] - r["l"] for i, r in enumerate(d[-15:])]
    return sum(tr[-14:]) / 14

def make(side, sym, market, m, i, first, H, edge, atr, res_target, feats, rnd):
    """One candidate -> a record holding the result under every stop/target combination, plus a random-entry control for each."""
    c, fut = m[i][4], m[i+1:i+1+H]
    rec = dict(side=side, market=market, sym=sym, epoch=int(m[i][0]), **feats)
    for s, mult in enumerate(STOPS):
        stop = edge - mult * atr if side == "long" else edge + mult * atr
        risk = (c - stop) if side == "long" else (stop - c)
        if risk <= 0:
            if s == 0: return None
            continue
        res = res_target if res_target and ((res_target > c) if side == "long" else (res_target < c)) else None
        rec[f"RR{s}"] = round(abs(res - c) / risk, 3) if res else ""
        for t, tn in enumerate(TARGETS):
            if tn == "res": tgt = res
            else: tgt = c + KR[tn] * risk if side == "long" else c - KR[tn] * risk
            r = sim(side, c, stop, tgt, fut)
            sp, tp = risk / c, (abs(tgt - c) / c if tgt else None)
            k = rnd.randrange(first, len(m) - H); e = m[k][4]
            cs = e * (1 - sp) if side == "long" else e * (1 + sp)
            ct = (e * (1 + tp) if side == "long" else e * (1 - tp)) if tp else None
            rec[f"R{s}{t}"] = "" if r is None else round(r, 4)
            rec[f"C{s}{t}"] = ""
            x = sim(side, e, cs, ct, m[k+1:k+1+H])
            if x is not None: rec[f"C{s}{t}"] = round(x, 4)
    return rec

def lab_symbol(a):
    tok, market = a
    try:
        name = tok if market == "crypto" else "STOCK:" + tok
        if market == "crypto":
            m, hi = B.hist_crypto(tok, "4h", MONTHS * 180 + 520), B.hist_crypto(tok, "1d", MONTHS * 30 + 520)
            per, hper, tm, ntest = 4 * 3600, 86400, "4h", MONTHS * 180
        else:
            m, hi = B.hist_stock(tok, "1d"), B.hist_stock(tok, "1wk")
            per, hper, tm, ntest = 86400, 7 * 86400, "1d", STOCK_YEARS * 252
        H, COOLN = HORIZON[market], COOL[market]
        if len(m) < 560: return tok, [], "not enough history"
        scanner.candles = B.fake_candles
        B.CTX["tm"] = tm
        hi_ts = [r[0] for r in hi]
        first = max(500, len(m) - H - ntest)
        recs, rnd, last_l, last_s = [], random.Random(tok), {}, {}
        for i in range(first, len(m) - H):
            j = bisect_right(hi_ts, m[i][0] + per - hper)
            c = m[i][4]
            main = B.D(m[i-499:i+1]) + [dict(o=c, h=c, l=c, c=c, v=0)]
            B.CTX["main"] = main
            B.CTX["high"] = B.D(hi[max(0, j - 500):j])
            lo, sh = scanner.analyse(name), scanner.short_check(name)
            want_l = lo["zone"] and lo["verdict"] in LONG_V
            want_s = sh["verdict"] in SHORT_V and sh.get("stop") is not None
            if not (want_l or want_s): continue
            cl = [r[4] for r in m[i-199:i+1]]
            sma50, sma200 = sum(cl[-50:]) / 50, sum(cl) / 200
            atr = atr_of(main)
            vols = [r[5] for r in m[i-20:i]]
            common = dict(rsi=round(scanner.rsi14(main[:-1]), 1), volr=round(m[i][5] / (sum(vols) / 20), 2) if sum(vols) else "",
                          atrp=round(atr / c * 100, 2))
            if want_l:
                z = lo["zone"]; mid = (z["lo"] + z["hi"]) / 2; prev = last_l.get(lo["verdict"])
                if not (prev and i - prev[0] < COOLN and abs(mid / prev[1] - 1) < .02):
                    last_l[lo["verdict"]] = (i, mid)
                    f = dict(verdict=lo["verdict"], pts=z["pts"], htf=int(z["htf"]), fib=int(z["fib"]), dist=round(z["dist"], 2),
                             strength=round(z["s"], 2), touches=z["t"], tr50=int(c > sma50), tr200=int(c > sma200), **common)
                    r = make("long", tok, market, m, i, first, H, z["lo"], atr, lo["target"], f, rnd)
                    if r: recs.append(r)
            if want_s:
                mid = sh["level"]; prev = last_s.get(sh["verdict"])
                if not (prev and i - prev[0] < COOLN and abs(mid / prev[1] - 1) < .02):
                    last_s[sh["verdict"]] = (i, mid)
                    f = dict(verdict=sh["verdict"], pts=sh["pts"], htf=int(sh["htf"]), fib=int(sh["fib"]), dist="", strength="", touches="",
                             tr50=int(c < sma50), tr200=int(c < sma200), **common)
                    r = make("short", tok, market, m, i, first, H, sh["stop"] - .5 * atr, atr, sh["target"], f, rnd)
                    if r: recs.append(r)
        return tok, recs, ""
    except Exception as e:
        return tok, [], str(e)[:80]

# ---------------------------------------------------------------- analysis
def acc_new(): return [0, 0.0, 0.0, 0.0]          # n, sum R, sum R^2, sum (R - control)

def add(a, x, cx):
    a[0] += 1; a[1] += x; a[2] += x * x; a[3] += x - (cx if cx != "" else 0)

def mean_ci(a):
    n = a[0]
    if not n: return 0.0, 0.0
    mu = a[1] / n
    if n < 2: return mu, 0.0
    var = max(0.0, (a[2] - n * mu * mu) / (n - 1))
    return mu, 1.96 * math.sqrt(var / n)

def merge(a, b): return [a[k] + b[k] for k in range(4)]

def filters(side):
    mk = ("all", "crypto", "stock")
    vs = ((LONG_V[:1], LONG_V[:2], LONG_V) if side == "long" else (SHORT_V[:1], SHORT_V))
    pts = (3, 4, 5) if side == "long" else (2, 3, 4, 5)
    return itertools.product(mk, vs, pts, (0, 1), (0, 1), (0, 50, 200), (None, 40) if side == "long" else (None, 65))

def label(side, f, s, t, rrmin):
    mk, vs, pt, ht, fb, tr, rs = f
    v = "+".join(x.replace(" SIGNAL", "").replace(" - WAIT", "-WAIT") for x in vs)
    p = [side, mk, v, f"score>={pt}"]
    if ht: p.append("needs higher-timeframe match")
    if fb: p.append("needs fib match")
    if tr: p.append(f"{'above' if side == 'long' else 'below'} {tr}-candle average")
    if rs: p.append(f"RSI {'<=' if side == 'long' else '>='} {rs}")
    p.append(f"stop {STOPS[s]} ATR"); p.append("target " + ("nearest level" if TARGETS[t] == "res" else TARGETS[t].replace("R", "x risk")))
    if rrmin: p.append(f"R/R>={rrmin}")
    return " | ".join(p)

def search(rows, side):
    """Try every rule variant; return list of dicts with train (folds 0+1) and test (fold 2) statistics."""
    out = []
    for f in filters(side):
        mk, vs, pt, ht, fb, tr, rs = f
        idx = [r for r in rows if (mk == "all" or r["market"] == mk) and r["verdict"] in vs and r["pts"] >= pt and (not ht or r["htf"])
               and (not fb or r["fib"]) and (tr == 0 or r[f"tr{tr}"]) and (rs is None or (r["rsi"] <= rs if side == "long" else r["rsi"] >= rs))]
        if len(idx) < 60: continue
        seen = set()
        for s in range(len(STOPS)):
            for t in range(len(TARGETS)):
                for rrmin in ((0, 1.2, 2, 3) if TARGETS[t] == "res" else (0,)):
                    A = [acc_new() for _ in range(3)]
                    rk, ck, rrk = f"R{s}{t}", f"C{s}{t}", f"RR{s}"
                    for r in idx:
                        x = r.get(rk, "")
                        if x == "" or r["fold"] < 0: continue
                        if rrmin:
                            rr = r.get(rrk, "")
                            if rr == "" or rr < rrmin: continue
                        add(A[r["fold"]], x, r.get(ck, ""))
                    tr_acc = merge(A[0], A[1])
                    if tr_acc[0] < MIN_TRAIN_N: continue
                    sig = (round(tr_acc[1], 3), tr_acc[0], A[2][0])
                    if sig in seen: continue          # identical trade set already counted
                    seen.add(sig)
                    out.append(dict(f=f, s=s, t=t, rrmin=rrmin, A=A, tr=tr_acc, side=side))
    return out

def tstat(a):
    mu, ci = mean_ci(a)
    return mu / (ci / 1.96) if ci > 0 else 0.0

def fmt_acc(a):
    mu, ci = mean_ci(a)
    return f"n={a[0]:>5}  avg R {mu:+.2f} (+/-{ci:.2f})"

def summarise(rows, errs):
    L = [f"STRATEGY LAB  {datetime.now(timezone.utc):%Y-%m-%d}   (crypto: {MONTHS} months of 4H, stocks: {STOCK_YEARS} years daily)",
         "R = profit in units of the risk to the stop, after 0.2% costs. The search uses only the OLDER two thirds of each market's history (train);",
         "the NEWEST third (test) is never looked at while searching. Signals overlap in time, so real error margins are wider than printed.", ""]
    results, verdicts = [], []
    for side in ("long", "short"):
        sr = [r for r in rows if r["side"] == side]
        L += [f"==================== {side.upper()} ====================", f"{len(sr)} signals replayed"]
        base = [acc_new() for _ in range(3)]
        for r in sr:
            if r.get("R00", "") != "" and r["fold"] >= 0: add(base[r["fold"]], r["R00"], r.get("C00", ""))
        L += ["Current rules, no filters (default stop and target), by period:",
              "  oldest third   " + fmt_acc(base[0]), "  middle third   " + fmt_acc(base[1]), "  newest third   " + fmt_acc(base[2]), ""]
        var = search(sr, side)
        good = [v for v in var if tstat(v["tr"]) >= 2 and v["tr"][0] >= MIN_TRAIN_N]
        L.append(f"Variants tried: {len(var)}.  Of those, {len(good)} looked clearly profitable in training (t>=2).")
        if good:
            pos = sum(1 for v in good if v["A"][2][1] > 0)
            tm = sum(v["A"][2][1] / v["A"][2][0] for v in good if v["A"][2][0]) / max(1, sum(1 for v in good if v["A"][2][0]))
            L.append(f"Overfitting meter: of those {len(good)} 'training winners', {pos} ({pos / len(good):.0%}) were also positive on the unseen test period; "
                     f"their average test R was {tm:+.3f}. (Pure noise would give about 50% and about -0.03.)")
        elig = [v for v in var if v["A"][0][0] and v["A"][1][0] and v["A"][0][1] > 0 and v["A"][1][1] > 0]
        elig.sort(key=lambda v: -tstat(v["tr"]))
        top, seen = [], set()
        for v in elig:
            k = (round(v["tr"][1], 2), v["tr"][0])
            if k in seen: continue
            seen.add(k); top.append(v)
            if len(top) == 15: break
        L += ["", f"Top {len(top)} variants chosen ONLY from training (profitable in both training periods), then checked on the unseen test period:"]
        holds = 0
        for v in top:
            te, ctl = v["A"][2], v["A"][2]
            mu, ci = mean_ci(te)
            beat = te[0] and te[3] / te[0] > 0        # must also beat matched random entries
            status = "HOLDS" if te[0] >= 40 and mu - ci > 0 and beat else "WEAK" if te[0] >= 40 and mu > 0 else "FAILS"
            holds += status == "HOLDS"
            L += [f"- {label(side, v['f'], v['s'], v['t'], v['rrmin'])}",
                  f"    train {fmt_acc(v['tr'])}   TEST {fmt_acc(te)}   vs random {(te[3] / te[0] if te[0] else 0):+.2f}   [{status}]"]
            results.append(dict(side=side, rule=label(side, v["f"], v["s"], v["t"], v["rrmin"]), train_n=v["tr"][0], train_avgR=round(mean_ci(v["tr"])[0], 3),
                                test_n=te[0], test_avgR=round(mu, 3), test_ci=round(ci, 3), status=status))
        tested = [v for v in top if v["A"][2][0] >= 40]
        avg_test = sum(v["A"][2][1] / v["A"][2][0] for v in tested) / len(tested) if tested else 0
        npos = sum(1 for v in tested if v["A"][2][1] > 0)
        L += ["", f"Procedure result: following 'pick the best in training' gave an average TEST result of {avg_test:+.3f}R, {npos} of {len(tested)} positive, {holds} clearly holding."]
        if holds >= 3 and avg_test > 0.05: v = f"{side.upper()}: some rules held up on unseen data. Worth forward-testing with paper trades before any real money."
        elif tested and avg_test > 0 and npos >= len(tested) * .6: v = f"{side.upper()}: weak hints only. Not enough to rely on."
        else: v = f"{side.upper()}: NOTHING survived. Rules that looked good in training did not hold on unseen data, so no variant here is a real edge."
        verdicts.append(v); L += ["", v, ""]
    L += ["VERDICTS"] + verdicts
    if errs: L += ["", "Could not test: " + ", ".join(f"{t} ({e})" for t, e in errs[:6])]
    return "\n".join(L), results

def main():
    jobs = [(t, "crypto") for t in scanner.top100()[:N_CRYPTO]] + [(s, "stock") for s in scanner.BIG_STOCKS[:N_STOCKS]]
    print(f"Replaying {len(jobs)} symbols (long and short)...", flush=True)
    with Pool(max(1, os.cpu_count() or 1)) as p: res = p.map(lab_symbol, jobs)
    rows = [r for _, rs, _ in res for r in rs]
    errs = [(t, e) for t, _, e in res if e]
    for mk in ("crypto", "stock"):                     # folds = oldest / middle / newest third of each market's history
        ep = sorted(r["epoch"] for r in rows if r["market"] == mk)
        if not ep: continue
        c1, c2 = ep[len(ep) // 3], ep[2 * len(ep) // 3]
        for r in rows:
            if r["market"] == mk: r["fold"] = 0 if r["epoch"] < c1 else 1 if r["epoch"] < c2 else 2
    for r in rows: r.setdefault("fold", -1)
    if rows:
        cols = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("side", "market", "sym", "epoch", "fold", "verdict"), k))
        with gzip.open(os.path.join(OUT, "lab_candidates.csv.gz"), "wt", newline="") as f:
            w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)
    text, results = summarise(rows, errs) if rows else ("No candidates found. " + str(errs[:3]), [])
    if results:
        with open(os.path.join(OUT, "lab_results.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, list(results[0].keys())); w.writeheader(); w.writerows(results)
    with open(os.path.join(OUT, "lab_summary.txt"), "w") as f: f.write(text + "\n")
    print("\n" + text)
    try:
        import paper
        scanner.notify("Strategy lab finished", "VERDICTS" + text.split("VERDICTS")[-1], scanner.NTFY_TOPIC, "microscope")
        paper.attach(os.path.join(OUT, "lab_summary.txt"))
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
