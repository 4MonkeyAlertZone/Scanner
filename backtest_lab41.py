#!/usr/bin/env python3
"""Lab 41: WHY ARE THE CRYPTO PAPER RULES LOSING? A same-weeks random-entry placebo for paper_trades.csv.
The paper review shows RECLAIM A/B/C and the crypto support-zone BUY SIGNAL at about -0.8R to -1.1R per trade while the backtest said about 0 to +0.1R. Three explanations are possible and this lab separates them:
  1. THE MARKET: the live weeks were bad for any long entry (alts fell), so even random entries would have lost.   -> random entries below zero too, edge near zero
  2. THE RULE: the rule picked worse moments than random.                                                          -> edge clearly negative against random in the SAME weeks
  3. NOISE: a handful of correlated trades.                                                                         -> wide confidence interval that includes zero
Method: for every closed CRYPTO trade in the ledger take its token, stop distance (% of entry), target distance (% of entry), and its time limit (168h for the CROSS/RECLAIM legs, 336h otherwise). Draw 40 random 4-hour candles for that same token inside the ledger's weeks (entry = that candle's close, only candles whose whole time limit has been observed), apply the same stop/target percentages and the same 0.2% round trip cost, stop first if one candle touches both. The random average for the trade is the mean of the 40 draws.
Per group: n trades, distinct open days, actual average R, random average R, EDGE = actual minus random, and a 95% interval from resampling open DAYS (trades opened on the same day move together, so days not trades are the unit of evidence).
Also shown: the average realised sample size once clustered (distinct days), because three RECLAIM legs per signal and 50+ signals at one moment are not independent evidence.
Reads paper_trades.csv; writes lab41_summary.txt."""
import csv, os, random, statistics as S, time
import scanner, backtest as B

OUT = scanner.HERE; COST = B.COST; K = 40
GROUPS = [("RECLAIM A (legs)", lambda r: r["verdict"].startswith("RECLAIM A")), ("RECLAIM B (legs)", lambda r: r["verdict"].startswith("RECLAIM B")),
          ("RECLAIM C (legs)", lambda r: r["verdict"].startswith("RECLAIM C")), ("CROSS A/B/C (legs)", lambda r: r["verdict"].startswith("CROSS")),
          ("crypto BUY SIGNAL", lambda r: r["verdict"] == "BUY SIGNAL"), ("crypto IN ZONE (+WAIT)", lambda r: r["verdict"].startswith("IN ZONE"))]
day = lambda e: time.strftime("%Y-%m-%d", time.gmtime(int(e)))

def sim(entry_i, c, entry, risk_pct, tgt_pct, horizon_c):
    """c: list of candles (t,o,h,l,cl,v). Enter at close of candle entry_i, watch the next horizon_c candles."""
    stop = entry * (1 - risk_pct); target = entry * (1 + tgt_pct); risk = entry - stop
    fut = c[entry_i + 1: entry_i + 1 + horizon_c]
    if len(fut) < horizon_c or risk <= 0: return None
    cost = COST * entry / risk
    for t, o, h, l, cl, v in fut:
        if l <= stop: return -1 - cost
        if h >= target: return (target - entry) / risk - cost
    return (fut[-1][4] - entry) / risk - cost

def main(rows=None, load=None):
    if rows is None: rows = list(csv.DictReader(open(os.path.join(OUT, "paper_trades.csv"))))
    load = load or (lambda tok: B.hist_crypto(tok, "4h", 600))
    cr = [r for r in rows if r["market"] == "crypto" and r["status"] == "closed" and r["R"] and r["entry"] and r["stop"] and r["target"]]
    w0 = min(int(r["open_epoch"]) for r in rows); toks = sorted({r["token"] for r in cr}); data = {}
    for tok in toks:
        try:
            d = load(tok)
            if d and len(d) > 60: data[tok] = d
        except Exception as e: print("no candles for", tok, str(e)[:40])
    rng = random.Random(41); out = [f"LAB 41: SAME-WEEKS RANDOM-ENTRY PLACEBO FOR THE CRYPTO PAPER RULES  ledger from {day(w0)}; {len(cr)} closed crypto legs; {len(data)}/{len(toks)} tokens with 4h candles; {K} random entries per trade, cost {COST * 100:.1f}% round trip", ""]
    out.append(f"{'group':<26}{'trades':>7}{'days':>6}{'actual R':>10}{'random R':>10}{'edge R':>9}{'95% low':>9}{'95% high':>9}  verdict")
    allr = []
    for name, sel in GROUPS:
        per_day = {}; n = 0
        for r in cr:
            if not sel(r) or r["token"] not in data: continue
            e, s, t = float(r["entry"]), float(r["stop"]), float(r["target"])
            if e <= 0 or s <= 0 or not (s < e < t): continue
            d = data[r["token"]]; hz = 42 if (r["verdict"].startswith(("CROSS", "RECLAIM"))) else 84
            lo = next((i for i, x in enumerate(d) if x[0] >= w0), None)
            if lo is None: continue
            cand = [i for i in range(max(lo, 1), len(d) - hz - 1)]
            if not cand: continue
            draws = []
            for _ in range(K):
                i = cand[rng.randrange(len(cand))]; x = sim(i, d, d[i][4], (e - s) / e, (t - e) / e, hz)
                if x is not None: draws.append(x)
            if len(draws) < K // 2: continue
            per_day.setdefault(day(r["open_epoch"]), []).append((float(r["R"]), S.mean(draws))); n += 1
        if n < 5 or len(per_day) < 2: out.append(f"{name:<26}{n:>7}{len(per_day):>6}  too few trades or days"); continue
        flat = [x for v in per_day.values() for x in v]; a = S.mean(x[0] for x in flat); b = S.mean(x[1] for x in flat); dv = list(per_day.values())
        bs = []
        for _ in range(4000):
            pick = [dv[rng.randrange(len(dv))] for _ in dv]; f = [x for g in pick for x in g]; bs.append(S.mean(x[0] - x[1] for x in f))
        bs.sort(); lo_, hi_ = bs[100], bs[3899]
        verdict = "rule worse than random" if hi_ < 0 else "rule better than random" if lo_ > 0 else "cannot tell from random"
        out.append(f"{name:<26}{n:>7}{len(per_day):>6}{a:>10.2f}{b:>10.2f}{a - b:>9.2f}{lo_:>9.2f}{hi_:>9.2f}  {verdict}")
    out += ["", "Read:",
            "- random R below zero too: the live weeks were hostile to any long entry; the rule is not the main problem.",
            "- edge clearly negative: the rule chose worse moments than random in the same weeks; check the live entry timing and the backtest definition.",
            "- 'days' is the real sample size. RECLAIM A and B each rest on only a few days, so a 95% interval that includes zero is expected there.",
            "SURVIVORSHIP: random entries use only tokens that appear in the ledger. Not financial advice."]
    text = "\n".join(out); open(os.path.join(OUT, "lab41_summary.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
