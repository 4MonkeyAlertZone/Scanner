#!/usr/bin/env python3
"""Replays a trader's posted calls (coin, side, entry, stop, target, post time) against real 15-minute prices and reports what actually happened,
after 0.2% costs, compared with random entries on the same coins with the same stop and target distances.
Input: calls_<name>.csv made by parse_telegram.py. Environment: CALLS=calls_gauls.csv, LABEL=Gauls. Output: replay_<LABEL>.txt and replay_<LABEL>.csv.
Entry models: MARKET = buy at the open of the first 15-minute candle after the post (what a follower who acts at once gets);
LIMIT = wait up to 48 hours for the price to come back to the stated entry (the low end for a 'CMP till X' zone) and fill there.
The stop is checked before the target inside the same candle. Trades still open after 30 days are closed at the market."""
import csv, json, os, random, time
from multiprocessing import Pool
import scanner

CALLS = os.environ.get("CALLS", "calls_gauls.csv")
LABEL = os.environ.get("LABEL", "Gauls")
COST = 0.002
HOLD = 30 * 96             # 30 days of 15-minute candles
WAIT = 48 * 4              # limit order waits 48 hours
CONTROLS = 5
OUT = scanner.HERE

def candles(coin, start, end):
    """15-minute rows (t, o, h, l, c) from Binance.US between start and end (epoch seconds), oldest first."""
    out, t = [], int(start * 1000)
    while t < end * 1000:
        k = json.loads(scanner.http(f"https://api.binance.us/api/v3/klines?symbol={coin}USDT&interval=15m&startTime={t}&limit=1000"))
        if not k: break
        out += [(x[0] / 1000, float(x[1]), float(x[2]), float(x[3]), float(x[4])) for x in k]
        t = int(k[-1][0]) + 1
        if len(k) < 1000: break
    seen, rows = set(), []
    for r in out:
        if r[0] not in seen: seen.add(r[0]); rows.append(r)
    return rows

def walk(m, i, entry, sl, tp, side):
    """Trade entered at `entry` during candle index i (the stop and target are checked from the NEXT candle, after the entry candle for a limit fill
    handled by the caller). Returns (R after costs, outcome, candles held)."""
    risk = abs(entry - sl)
    if risk <= 0: return None
    cost = COST * entry / risk
    end = min(len(m), i + HOLD)
    for j in range(i, end):
        _, o, h, l, c = m[j]
        if side == "long":
            if l <= sl: return -1 - cost, "stop", j - i
            if h >= tp: return (tp - entry) / risk - cost, "target", j - i
        else:
            if h >= sl: return -1 - cost, "stop", j - i
            if l <= tp: return (entry - tp) / risk - cost, "target", j - i
    last = m[end - 1][4]
    if end - i < HOLD and end == len(m): return None            # still running and not old enough to judge
    return ((last - entry) if side == "long" else (entry - last)) / risk - cost, "time", end - i

def first_idx(m, epoch):
    lo, hi = 0, len(m)
    while lo < hi:
        mid = (lo + hi) // 2
        if m[mid][0] >= epoch: hi = mid
        else: lo = mid + 1
    return lo

def level(spec, e, sl, side):
    """Target price for a spec: ('abs', price) = the trader's stated level, ('r', k) = k times the risk from the entry."""
    if spec[0] == "abs": return spec[1]
    risk = abs(e - sl)
    return e + spec[1] * risk if side == "long" else e - spec[1] * risk

def replay_coin(args):
    coin, calls = args
    try:
        t0 = min(c["epoch"] for c in calls) - 86400; t1 = time.time()
        m = candles(coin, t0, t1)
        if len(m) < 500: return coin, [], "not on Binance.US or too little history"
        rnd = random.Random(coin); rows = []
        for c in calls:
            i = first_idx(m, c["epoch"])
            if i >= len(m) - 2 or m[i][0] - c["epoch"] > 3600: continue      # no price data right after the post
            side = c["side"]
            specs = [("1R", ("r", 1)), ("2R", ("r", 2)), ("3R", ("r", 3))]
            if c["tp1"] is not None: specs = [("TP1", ("abs", c["tp1"])), ("last TP", ("abs", c["tp_last"]))] + specs
            for tpn, spec in specs:
                # MARKET: enter at the open of the first candle after the post
                e = m[i][1]; tp = level(spec, e, c["sl"], side)
                ok = (c["sl"] < e < tp) if side == "long" else (c["sl"] > e > tp)
                if ok:
                    r = walk(m, i, e, c["sl"], tp, side)
                    if r: rows.append((coin, c["epoch"], side, "MARKET", tpn, r[0], r[1], r[2], round(abs(tp - e) / abs(e - c["sl"]), 2), 0))
                else:
                    rows.append((coin, c["epoch"], side, "MARKET-SKIP", tpn, 0.0, "skip", 0, 0, 0))   # price was already beyond the stop or target when we could act
                    continue
                # CONTROL: random market entries on the same coin, same stop and target distances (as a share of price)
                sp, tpp = abs(e - c["sl"]) / e, abs(tp - e) / e
                for _ in range(CONTROLS):
                    k = rnd.randrange(0, max(1, len(m) - HOLD - 2)); ek = m[k][1]
                    s2 = ek * (1 - sp) if side == "long" else ek * (1 + sp); t2 = ek * (1 + tpp) if side == "long" else ek * (1 - tpp)
                    r = walk(m, k, ek, s2, t2, side)
                    if r: rows.append((coin, m[k][0], side, "RANDOM", tpn, r[0], r[1], r[2], round(tpp / sp, 2), 1))
                # LIMIT: wait for the stated entry price (the deeper one if he gives two)
                lim = c["entry_lo"] if side == "long" else c["entry_hi"]
                for j in range(i, min(len(m) - 1, i + WAIT)):
                    _, o, h, l, cl = m[j]
                    hit = (l <= lim) if side == "long" else (h >= lim)
                    if hit:
                        fill = min(o, lim) if side == "long" else max(o, lim)
                        tl = level(spec, fill, c["sl"], side)
                        ok2 = (c["sl"] < fill < tl) if side == "long" else (c["sl"] > fill > tl)
                        if ok2:
                            r = walk(m, j, fill, c["sl"], tl, side)
                            if r: rows.append((coin, c["epoch"], side, "LIMIT", tpn, r[0], r[1], r[2], round(abs(tl - fill) / abs(fill - c["sl"]), 2), 0))
                        break
                else:
                    rows.append((coin, c["epoch"], side, "LIMIT-NOFILL", tpn, 0.0, "nofill", 0, 0, 0))
        return coin, rows, ""
    except Exception as ex:
        return coin, [], str(ex)[:80]

def mean_ci(xs):
    n = len(xs)
    if not n: return 0.0, 0.0
    mu = sum(xs) / n
    if n < 2: return mu, 0.0
    v = sum((x - mu) ** 2 for x in xs) / (n - 1)
    return mu, 1.96 * (v / n) ** .5

def line(xs, outs=None):
    mu, ci = mean_ci(xs)
    s = f"n={len(xs):>4} avg {mu:+.2f}R (+/-{ci:.2f})"
    if outs:
        s += f"  target {sum(o == 'target' for o in outs) / len(outs) * 100:3.0f}%  stop {sum(o == 'stop' for o in outs) / len(outs) * 100:3.0f}%  timeout {sum(o == 'time' for o in outs) / len(outs) * 100:3.0f}%"
    return s

def summarise(rows, calls, errs):
    L = []
    t = lambda e: time.strftime("%Y-%m-%d", time.gmtime(e))
    L.append(f"REPLAY OF {LABEL}'S POSTED CALLS: {len(calls)} calls with numbers in the text ({t(min(c['epoch'] for c in calls))} to {t(max(c['epoch'] for c in calls))}), {len({r[0] for r in rows})} coins tested.")
    if errs: L.append("not testable: " + "; ".join(f"{c} ({e})" for c, e in errs[:15]) + (" ..." if len(errs) > 15 else ""))
    L.append("R = profit in units of the stated risk (entry minus stop), after 0.2% costs. 'target %' = how often the stated target was reached before the stop.")
    L.append("")
    for tpn in [t for t in ("TP1", "last TP", "1R", "2R", "3R") if any(r[4] == t for r in rows)]:
        L.append(f"A. TARGET = {tpn.upper()}" + ("  (his own stated level)" if tpn in ("TP1", "last TP") else "  (1R/2R/3R = that many times the distance from entry to his stop, our standard test when his targets are only on a chart)"))
        for mod, nm in (("MARKET", "buy at once after the post"), ("LIMIT", "wait for the stated entry price"), ("RANDOM", "random entries, same stop/target distances (no-skill control)")):
            sel = [r for r in rows if r[3] == mod and r[4] == tpn]
            if not sel: continue
            L.append(f"   {mod:7} {nm:62} {line([r[5] for r in sel], [r[6] for r in sel])}   avg reward:risk {sum(r[8] for r in sel) / len(sel):.1f}")
        nf = [r for r in rows if r[3] == "LIMIT-NOFILL" and r[4] == tpn]
        lim = [r for r in rows if r[3] == "LIMIT" and r[4] == tpn]
        if nf or lim: L.append(f"           limit orders filled: {len(lim)} of {len(lim) + len(nf)}")
        sk = [r for r in rows if r[3] == "MARKET-SKIP" and r[4] == tpn]
        if sk: L.append(f"           calls skipped because price was already past the stop or target when the post came: {len(sk)}")
        L.append("")
    L.append("B. MARKET entry, by half of the period and by side (targets 1R | 2R | 3R)")
    mk = [r for r in rows if r[3] == "MARKET"]
    cut = sorted(r[1] for r in mk)[len(mk) // 2] if mk else 0
    for nm, f in (("older half", lambda r: r[1] < cut), ("newer half", lambda r: r[1] >= cut), ("longs", lambda r: r[2] == "long"), ("shorts", lambda r: r[2] == "short")):
        L.append(f"   {nm:11} " + "  |  ".join(line([r[5] for r in mk if f(r) and r[4] == k]) for k in ("1R", "2R", "3R")))
    L.append("")
    L.append("C. MARKET entry, 2R target, by month of the post (is it steady, or one lucky stretch?)")
    byc = {}
    for r in mk:
        if r[4] == "2R": byc.setdefault(time.strftime("%Y-%m", time.gmtime(r[1])), []).append(r[5])
    L.append("   " + "  ".join(f"{k} {sum(v) / len(v):+.2f}({len(v)})" for k, v in sorted(byc.items())))
    L.append("")
    L.append("D. HOW TO READ: compare MARKET and LIMIT with RANDOM. If they are not clearly above it, the picks add nothing beyond the stop/target shape. Calls whose levels are only drawn on a chart image are not in this test, and a channel can delete or edit posts, so a good record here is the best case. Overlapping calls (several coins at once) move together, so true error margins are wider than printed.")
    return "\n".join(L)

def main():
    calls = []
    for r in csv.DictReader(open(os.path.join(OUT, CALLS))):
        if r["valid"] != "1": continue
        calls.append(dict(coin=r["coin"], side=r["side"], epoch=int(r["epoch"]), sl=float(r["sl"]), tp1=float(r["tp1"]) if r["tp1"] else None, tp_last=float(r["tp_last"]) if r["tp_last"] else None,
                          entry_lo=float(r["entry_lo"]), entry_hi=float(r["entry_hi"])))
    by = {}
    for c in calls: by.setdefault(c["coin"], []).append(c)
    print(f"{len(calls)} usable calls on {len(by)} coins", flush=True)
    with Pool(3) as p: res = p.map(replay_coin, sorted(by.items()))
    rows = [r for _, rs, _ in res for r in rs]; errs = [(c, e) for c, _, e in res if e]
    done = {r[0] for r in rows}
    text = summarise(rows, [c for c in calls if c["coin"] in done], errs) if rows else "No calls could be replayed. " + str(errs[:3])
    with open(os.path.join(OUT, f"replay_{LABEL}.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["coin", "epoch", "side", "model", "target", "R", "outcome", "candles_held", "reward_risk", "is_control"]); w.writerows(rows)
    with open(os.path.join(OUT, f"replay_{LABEL}.txt"), "w") as f: f.write(text + "\n")
    print("\n" + text)

if __name__ == "__main__":
    main()
