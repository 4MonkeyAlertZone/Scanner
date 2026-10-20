#!/usr/bin/env python3
"""CHART DATA + RSI TIMEFRAME TEST. Builds chart_data.json for the interactive charts and rsi_stats.txt.
RSI = Wilder RSI(14) on the closes of bars of each timeframe: 1h 2h 4h 6h 8h 1d 2d 3d 1w 2w 1M. Only COMPLETED bars are used (no peeking at the bar still forming). Bars: hourly ones aligned to UTC midnight, 2d/3d anchored on 1 Jan 1970, weeks start Monday 00:00 UTC, 2w = pairs of those weeks, months = calendar months.
Daily chart sampling: each RSI is read at every daily close (00:00 UTC), i.e. the moment the daily GET IN / GET OUT signal is decided. Hourly chart sampling: each hourly close.
Signals come from signals_history.csv (the replay of regime_alert.py and intraday_watch.py), which must already be in the repo.
STATS (one row per timeframe, nothing tuned): AUC = chance that a random IN day has a higher RSI than a random OUT day (0.5 = useless, 1 = perfect); agree = % of days where RSI>50 matches IN and RSI<=50 matches OUT; lag = median days between a regime flip and the nearest same-direction RSI cross of 50 within +/-30 days (negative = RSI moved first), found = % of flips with such a cross; crosses/yr = how often RSI crosses 50 (noise); fwd14 = BTC average 14-day return after RSI>50 minus after RSI<=50 and hit = % of days where 'RSI>50 -> price up in 14 days' was right.
Caution: 11 timeframes were tried, overlapping 14-day windows, only ~3 market phases: a small edge between two timeframes is noise."""
import os, csv, json, time, calendar, bisect
import scanner, backtest as B, signals_history as SH

HERE = scanner.HERE; P = lambda f: os.path.join(HERE, f)
START = SH.START; TFS = ["1h", "2h", "4h", "6h", "8h", "1d", "2d", "3d", "1w", "2w", "1M"]
HOURS = {"1h": 1, "2h": 2, "4h": 4, "6h": 6, "8h": 8}

def wilder(cl, n=14):
    out = [None] * len(cl)
    if len(cl) <= n: return out
    g = [max(cl[i] - cl[i - 1], 0) for i in range(1, n + 1)]; l = [max(cl[i - 1] - cl[i], 0) for i in range(1, n + 1)]
    ag, al = sum(g) / n, sum(l) / n
    out[n] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(cl)):
        ch = cl[i] - cl[i - 1]; ag = (ag * (n - 1) + max(ch, 0)) / n; al = (al * (n - 1) + max(-ch, 0)) / n
        out[i] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    return out

def day_groups(days, tf):
    """-> list of (end_day, close_day_index) of COMPLETED bars; partial first bar dropped."""
    if tf == "1d": key = lambda d: d; last = lambda g: g; first = lambda g: g
    elif tf == "2d": key = lambda d: d // 2; last = lambda g: g * 2 + 1; first = lambda g: g * 2
    elif tf == "3d": key = lambda d: d // 3; last = lambda g: g * 3 + 2; first = lambda g: g * 3
    elif tf == "1w": key = lambda d: (d + 3) // 7; last = lambda g: g * 7 - 3 + 6; first = lambda g: g * 7 - 3
    elif tf == "2w": key = lambda d: (d + 3) // 14; last = lambda g: g * 14 - 3 + 13; first = lambda g: g * 14 - 3
    else:
        def ym(d): t = time.gmtime(d * 86400); return t.tm_year * 12 + t.tm_mon - 1
        key = ym
        last = lambda g: calendar.timegm((g // 12 + (g % 12 + 1) // 12, (g % 12 + 1) % 12 + 1, 1, 0, 0, 0)) // 86400 - 1
        first = lambda g: calendar.timegm((g // 12, g % 12 + 1, 1, 0, 0, 0)) // 86400
    ds = sorted(days); gs = {}
    for d in ds: gs.setdefault(key(d), []).append(d)
    bars = []
    for g in sorted(gs):
        if gs[g][0] > first(g) and g == key(ds[0]): continue            # partial first bar
        e = last(g)
        if e > ds[-1]: continue                                          # still forming
        bars.append((e, days[e] if e in days else days[gs[g][-1]]))
    return bars

def sample_daily(days, tf):
    bars = day_groups(days, tf); cl = [b[1] for b in bars]; r = wilder(cl); ends = [b[0] for b in bars]
    return ends, r

def main(daily=None, hourly=None, rows=None):
    daily = daily or {d: c for d, c in ((int(r[0] // 86400), r[4]) for r in reversed(B.hist_crypto("BTC", "1d", 2700)))}
    hr = hourly or SH.hourly("BTC", (START - 45) * 86400)
    rows = rows or list(csv.DictReader(open(P("signals_history.csv"))))
    dd = sorted(daily); dmap = daily
    # ---- daily RSI for 1d..1M, as of each daily close
    rsi_end = {}
    for tf in TFS[5:]:
        ends, r = sample_daily(dmap, tf); rsi_end[tf] = (ends, r)
    def at_day(tf, d):
        ends, r = rsi_end[tf]; i = bisect.bisect_right(ends, d) - 1
        return r[i] if i >= 0 else None
    # ---- hourly bars -> RSI for 1h..8h
    ht = [x[0] for x in hr]; hc = [x[4] for x in hr]
    hrsi = {}
    for tf, k in HOURS.items():
        bars = {}
        for t, c in zip(ht, hc): bars.setdefault(int(t // 3600) // k, []).append((t, c))
        gl = sorted(bars); ends = []; cl = []
        for g in gl:
            lst = bars[g]
            if len(lst) < k: continue                                    # incomplete (first/last) bar
            ends.append((g + 1) * k * 3600); cl.append(lst[-1][1])
        r = wilder(cl); hrsi[tf] = (ends, r)
    def at_time(tf, T):
        ends, r = hrsi[tf]; i = bisect.bisect_right(ends, T) - 1
        return r[i] if i >= 0 else None
    # ---- regime state / colour timeline from the replay csv
    st_ev = sorted((float(x["time_utc"]), x["signal"]) for x in rows if x["category"] == "REGIME")
    co_ev = sorted((float(x["time_utc"]), x["signal"]) for x in rows if x["category"].startswith("LEVERAGE"))
    def state_at(T):
        s = None
        for t, sg in st_ev:
            if t <= T: s = "IN" if sg.endswith("IN") else "OUT"
        return s
    def col_at(T):
        c = None
        for t, sg in co_ev:
            if t <= T: c = sg.split()[-1]
        return c
    D = [d for d in dd if d >= START]
    daily_out = {"t": [(d + 1) * 86400 for d in D], "c": [round(dmap[d], 2) for d in D],
                 "state": [state_at((d + 1) * 86400 + 3000) for d in D], "col": [col_at((d + 1) * 86400 + 3000) for d in D], "rsi": {}}
    for tf in TFS:
        if tf in HOURS:
            vals = [at_time(tf, (d + 1) * 86400) for d in D]
        else:
            vals = [at_day(tf, d) for d in D]
        daily_out["rsi"][tf] = [None if v is None else round(v, 1) for v in vals]
    H = [(t + 3600, c) for t, c in zip(ht, hc) if t >= START * 86400]
    hourly_out = {"t": [int(x[0]) for x in H], "c": [round(x[1], 2) for x in H], "rsi": {}}
    for tf in list(HOURS) + ["1d"]:
        v = []
        for T, _ in H:
            x = at_time(tf, T) if tf in HOURS else at_day(tf, int(T // 86400) - 1)
            v.append(None if x is None else round(x, 1))
        hourly_out["rsi"][tf] = v
    sig = [{"t": float(x["time_utc"]), "cat": x["category"], "sig": x["signal"], "a": x["asset"], "p": float(x["price_at_signal"]) if x["price_at_signal"] else None, "d": x["detail"]} for x in rows]
    # ---- stats
    L = ["RSI TIMEFRAME TEST vs the regime signals (daily sampling at each daily close, from 1 Oct 2020)", "", "Benchmark: the regime state itself (IN = up call, OUT = down call) for the 14-day direction test.", ""]
    idx = {d: i for i, d in enumerate(D)}; st = daily_out["state"]; cc = daily_out["c"]
    def fwd(i, h=14): return cc[i + h] / cc[i] - 1 if i + h < len(cc) else None
    base_up = sum(1 for i in range(len(D)) if fwd(i) is not None and fwd(i) > 0) / max(1, sum(1 for i in range(len(D)) if fwd(i) is not None))
    ins = [i for i in range(len(D)) if st[i] == "IN" and fwd(i) is not None]; outs = [i for i in range(len(D)) if st[i] == "OUT" and fwd(i) is not None]
    mi = sum(fwd(i) for i in ins) / len(ins); mo = sum(fwd(i) for i in outs) / len(outs)
    hit_reg = (sum(1 for i in ins if fwd(i) > 0) + sum(1 for i in outs if fwd(i) <= 0)) / (len(ins) + len(outs))
    flips = [(float(x["time_utc"]), x["signal"]) for x in rows if x["category"] == "REGIME" and x["signal"] in ("GET IN", "GET OUT")]
    L.append(f"Base rate: BTC was up over the next 14 days on {base_up * 100:.0f}% of days. Regime: IN days avg 14d return {mi * 100:+.1f}%, OUT days {mo * 100:+.1f}% (spread {(mi - mo) * 100:+.1f} pts), 'IN=up/OUT=down' right {hit_reg * 100:.0f}% of days.")
    L.append("")
    L.append(f"{'tf':<4}{'days':>6}{'AUC':>7}{'agree%':>8}{'lag IN':>8}{'found%':>8}{'lag OUT':>9}{'found%':>8}{'crosses/yr':>12}{'fwd14 spread':>14}{'hit%':>7}{'RSI@IN':>8}{'RSI@OUT':>9}")
    srow = {}
    for tf in TFS:
        r = daily_out["rsi"][tf]; ok = [i for i in range(len(D)) if r[i] is not None and st[i]]
        a = [r[i] for i in ok if st[i] == "IN"]; b = [r[i] for i in ok if st[i] == "OUT"]
        if not a or not b: L.append(f"{tf:<4} not enough data"); continue
        allv = sorted(a + b); rk = {}
        for j, v in enumerate(allv): rk.setdefault(v, []).append(j + 1)
        rsum = sum(sum(rk[v]) / len(rk[v]) for v in a); auc = (rsum - len(a) * (len(a) + 1) / 2) / (len(a) * len(b))
        agree = sum(1 for i in ok if (r[i] > 50) == (st[i] == "IN")) / len(ok)
        cu = [D[i] for i in range(1, len(D)) if r[i] is not None and r[i - 1] is not None and r[i] > 50 >= r[i - 1]]
        cd = [D[i] for i in range(1, len(D)) if r[i] is not None and r[i - 1] is not None and r[i] <= 50 < r[i - 1]]
        yrs = len(ok) / 365.0
        def lags(kind, cross):
            out = []; nf = 0; n = 0
            for t, s in flips:
                if s != kind: continue
                n += 1; d0 = int(t // 86400) - 1
                near = [c - d0 for c in cross if abs(c - d0) <= 30]
                if near: out.append(min(near, key=abs))
            out.sort(); return (out[len(out) // 2] if out else None), (100 * len(out) / n if n else 0)
        lin, fin = lags("GET IN", cu); lout, fout = lags("GET OUT", cd)
        up = [i for i in ok if r[i] > 50 and fwd(i) is not None]; dn = [i for i in ok if r[i] <= 50 and fwd(i) is not None]
        spread = (sum(fwd(i) for i in up) / len(up) - sum(fwd(i) for i in dn) / len(dn)) * 100 if up and dn else float("nan")
        hit = (sum(1 for i in up if fwd(i) > 0) + sum(1 for i in dn if fwd(i) <= 0)) / (len(up) + len(dn)) * 100
        def med(x): x = sorted(x); return x[len(x) // 2] if x else float("nan")
        ri = [r[idx[int(t // 86400) - 1]] for t, s in flips if s == "GET IN" and int(t // 86400) - 1 in idx and r[idx[int(t // 86400) - 1]] is not None]
        ro = [r[idx[int(t // 86400) - 1]] for t, s in flips if s == "GET OUT" and int(t // 86400) - 1 in idx and r[idx[int(t // 86400) - 1]] is not None]
        fl = lambda v: "n/a" if v is None else f"{v:+d}d"
        L.append(f"{tf:<4}{len(ok):>6}{auc:>7.2f}{agree * 100:>8.0f}{fl(lin):>8}{fin:>8.0f}{fl(lout):>9}{fout:>8.0f}{(len(cu) + len(cd)) / yrs:>12.1f}{spread:>13.1f}%{hit:>7.0f}{med(ri):>8.0f}{med(ro):>9.0f}")
        srow[tf] = dict(auc=round(auc, 3), agree=round(agree * 100, 1), lag_in=lin, found_in=round(fin), lag_out=lout, found_out=round(fout), crosses_yr=round((len(cu) + len(cd)) / yrs, 1), spread=round(spread, 2), hit=round(hit, 1), rsi_in=med(ri), rsi_out=med(ro))
    # intraday: median hourly RSI at the hour of each warning type vs all hours
    L += ["", "INTRADAY WARNINGS: median RSI of each hourly timeframe at the moment (previous hourly close) a BTC warning fired, versus the median over all hours. Lower than 'all hours' = RSI already weak when the warning came.", ""]
    types = ["FAST DROP BTC", "BTC BELOW 50-DAY LINE", "BTC BELOW 200-DAY LINE", "BTC NEAR 50-DAY LINE (<1% above)"]
    tfh = list(HOURS) + ["1d"]; L.append(f"{'':<34}{'n':>5}" + "".join(f"{t:>7}" for t in tfh))
    hidx = {t: i for i, (t, _) in enumerate(H)}
    def med(x): x = sorted(x); return x[len(x) // 2] if x else float("nan")
    L.append(f"{'all hours':<34}{len(H):>5}" + "".join(f"{med([v for v in hourly_out['rsi'][tf] if v is not None]):>7.0f}" for tf in tfh))
    for ty in types:
        ev = [x for x in sig if x["cat"] == "INTRADAY" and x["sig"] == ty]
        pos = [hidx.get(int(x["t"])) for x in ev]; pos = [p for p in pos if p is not None]
        L.append(f"{ty[:33]:<34}{len(pos):>5}" + "".join(f"{med([hourly_out['rsi'][tf][p] for p in pos if hourly_out['rsi'][tf][p] is not None]):>7.0f}" for tf in tfh))
    L += ["", "Read: higher AUC and agree% mean the RSI timeframe separates IN from OUT days; small |lag| with high found% means its 50-cross arrives near the regime flip; fewer crosses/yr means fewer false flips; positive fwd14 spread with hit% above the base rate means it carries direction information. The regime rule itself is in the benchmark line above."]
    open(P("rsi_stats.txt"), "w").write("\n".join(L) + "\n"); print("\n".join(L))
    json.dump({"tfs": TFS, "daily": daily_out, "hourly": hourly_out, "signals": sig, "stats": srow,
               "bench": {"base_up": round(base_up * 100, 1), "in_ret": round(mi * 100, 2), "out_ret": round(mo * 100, 2), "hit": round(hit_reg * 100, 1)}}, open(P("chart_data.json"), "w"), separators=(",", ":"))
    print("chart_data.json bytes:", os.path.getsize(P("chart_data.json")))

if __name__ == "__main__":
    main()
