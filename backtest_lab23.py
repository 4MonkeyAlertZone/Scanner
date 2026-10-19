#!/usr/bin/env python3
"""Lab 23: BTC pullback anatomy (descriptive study + simple predictiveness test). No trading rules are fitted here.
Part A: every BTC pullback of 5%+ since Oct 2020 (zigzag on daily highs/lows): depth, days down, days to recover, fib extension of the peak,
        RSI/stretch at the peak, and what a basket of alts did (peak->trough, did alts top before BTC?).
Part B: do 'fib extension reached', 'stretched above 50-day', 'RSI hot' flag days that really precede a 10%+ BTC drop within 14 days, versus the base rate?
Part C: stablecoin supply (DefiLlama, USDT/USDC) and alt/BTC ratio (a dominance proxy) around peaks and troughs; optional dominance.csv (date,btc_d,usdt_d,usdc_d) if you add one.
Writes lab23_summary.txt and lab23_events.csv."""
import csv, json, os, statistics as st, calendar
from datetime import datetime, timezone
from multiprocessing import Pool
import scanner, backtest as B

W0 = calendar.timegm((2020, 10, 1, 0, 0, 0)); W1 = calendar.timegm((2025, 9, 1, 0, 0, 0))
STABLES = {"USDT", "USDC", "DAI", "TUSD", "FDUSD", "USDE", "USD1", "PYUSD", "USDD", "BUSD", "USDP", "FRAX", "WBTC", "BTC", "STETH", "WSTETH", "WBETH"}
dstr = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")

def load(sym):
    try: return sym, B.hist_crypto(sym, "1d", 2600)
    except Exception: return sym, []

def zig(h, l, thr):
    """Zigzag pivots [(idx, price, 'H'|'L', confirm_idx)] using highs/lows; the last unconfirmed swing is not returned."""
    n = len(h); piv = []; mode = None; hi = lo = 0
    for i in range(1, n):
        if h[i] > h[hi]: hi = i
        if l[i] < l[lo]: lo = i
        if mode is None:
            if h[i] >= l[lo] * (1 + thr): piv.append((lo, l[lo], "L", i)); mode = "up"; hi = i
            elif l[i] <= h[hi] * (1 - thr): piv.append((hi, h[hi], "H", i)); mode = "down"; lo = i
        elif mode == "up":
            if l[i] <= h[hi] * (1 - thr): piv.append((hi, h[hi], "H", i)); mode = "down"; lo = i
        else:
            if h[i] >= l[lo] * (1 + thr): piv.append((lo, l[lo], "L", i)); mode = "up"; hi = i
    return piv

def rsi_series(c, n=14):
    out = [50.0] * len(c)
    if len(c) <= n: return out
    g = sum(max(c[i] - c[i-1], 0) for i in range(1, n + 1)) / n; l = sum(max(c[i-1] - c[i], 0) for i in range(1, n + 1)) / n
    for i in range(n, len(c)):
        if i > n:
            x = c[i] - c[i-1]; g = (g * (n - 1) + max(x, 0)) / n; l = (l * (n - 1) + max(-x, 0)) / n
        out[i] = 100 - 100 / (1 + g / l) if l else 100.0
    return out

def med(x): return st.median(x) if x else float("nan")
def fx(v, f="{:+.0%}"): return f.format(v) if v == v else "--"

def main():
    btc = B.hist_crypto("BTC", "1d", 2600)
    bad = 0; fixed = []
    for r in btc:                                   # clip bad ticks: a wick more than 25% beyond the candle body is a data error (one 138,070 high in June 2023 spoiled the first run)
        t, o, h, l, c, v = r; hb, lb = max(o, c), min(o, c)
        h2, l2 = min(h, hb * 1.25), max(l, lb / 1.25)
        bad += (h2 != h) + (l2 != l); fixed.append((t, o, h2, l2, c, v))
    btc = fixed; print("bad ticks clipped:", bad)
    T = [r[0] for r in btc]; O = [r[1] for r in btc]; H = [r[2] for r in btc]; L = [r[3] for r in btc]; C = [r[4] for r in btc]
    n = len(btc); pos = {t: i for i, t in enumerate(T)}
    rsi = rsi_series(C); ma50 = [sum(C[max(0, i-49):i+1]) / min(50, i + 1) for i in range(n)]
    coins = [t for t in scanner.top100()[:45] if t.upper() not in STABLES]
    with Pool(2) as p: res = p.map(load, coins, chunksize=1)
    A = {s: {r[0]: r[4] for r in rows} for s, rows in res if len(rows) > 500}
    # equal-weight alt index (daily rebalanced, coins with data on both days) and ratio to BTC
    idx = [1.0]
    for i in range(1, n):
        rets = [A[s][T[i]] / A[s][T[i-1]] - 1 for s in A if T[i] in A[s] and T[i-1] in A[s]]
        idx.append(idx[-1] * (1 + (sum(rets) / len(rets) if rets else 0)))
    ratio = [idx[i] / C[i] for i in range(n)]
    def alt_move(i0, i1):
        r = [A[s][T[i1]] / A[s][T[i0]] - 1 for s in A if T[i0] in A[s] and T[i1] in A[s]]
        return (st.mean(r), med(r), len(r)) if r else (float("nan"), float("nan"), 0)
    # ---------- Part A: events ----------
    p5 = zig(H, L, .05); p20 = zig(H, L, .20); ev = []
    for k in range(len(p5) - 1):
        a, b = p5[k], p5[k+1]
        if not (a[2] == "H" and b[2] == "L") or not (W0 <= T[a[0]] < W1) or b[0] <= a[0]: continue
        pi, ti = a[0], b[0]; peak, tr = a[1], b[1]
        kext = None
        if k >= 3 and p5[k-1][2] == "L" and p5[k-2][2] == "H" and p5[k-3][2] == "L":
            sw = p5[k-2][1] - p5[k-3][1]; kext = (peak - p5[k-1][1]) / sw if sw > 0 else None
        e20 = None
        ups = [q for q in p20 if q[3] < pi + 1 and q[2] == "L"]       # last 20% low confirmed by then
        if ups:
            Lc = ups[-1]; hs = [q for q in p20 if q[2] == "H" and q[0] < Lc[0]]; ls = [q for q in p20 if q[2] == "L" and q[0] < Lc[0]]
            if hs and ls and hs[-1][1] > ls[-1][1] and Lc[0] < pi: e20 = (peak - Lc[1]) / (hs[-1][1] - ls[-1][1])
        rec = next((j for j in range(ti, n) if H[j] > peak), None)
        am = alt_move(pi, ti); lead = None
        lo_, hi_ = max(0, pi - 25), min(n - 1, pi + 10)
        if hi_ > lo_: lead = pi - max(range(lo_, hi_ + 1), key=lambda j: idx[j])
        pre = (ratio[pi] / ratio[max(0, pi - 30)] - 1)
        ev.append(dict(peak_date=dstr(T[pi]), peak=round(peak), trough_date=dstr(T[ti]), depth=round(1 - tr / peak, 3), days_down=ti - pi,
                       days_to_recover=(rec - pi) if rec else "", ext5=round(kext, 2) if kext else "", ext20=round(e20, 2) if e20 else "",
                       rsi=round(rsi[pi]), above50=round(C[pi] / ma50[pi] - 1, 3), alt_mean=round(am[0], 3), alt_median=round(am[1], 3), n_alts=am[2],
                       alts_peak_lead_days=lead if lead is not None else "", altbtc_30d_before=round(pre, 3), usdt30="", pi=pi, ti=ti))
    # ---------- Part C data: stablecoins ----------
    stab = {}
    for name, sid in (("USDT", 1), ("USDC", 2)):
        try:
            j = json.loads(scanner.http(f"https://stablecoins.llama.fi/stablecoincharts/all?stablecoin={sid}"))
            stab[name] = {int(x["date"]): float(x["totalCirculating"]["peggedUSD"]) for x in j}
        except Exception as e: stab[name] = {}; print("stablecoin data failed:", name, str(e)[:60])
    def sup(name, i, back):
        d = stab.get(name) or {}
        if not d: return None
        f = lambda ii: next((d[t] for t in (T[ii], T[ii] - 86400, T[ii] + 86400) if t in d), None)
        a, b = f(i), f(max(0, i - back)); return a / b - 1 if a and b else None
    dom = {}
    def addcol(path, key):
        """TradingView export: columns time (ISO text or epoch seconds) and close."""
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            r = {k.strip().lower(): v for k, v in r.items()}
            try:
                tv = r.get("time") or r.get("date"); v = float(r.get("close") or r.get(key))
                t = int(float(tv)) if tv.replace(".", "").isdigit() else calendar.timegm(datetime.strptime(tv[:10], "%Y-%m-%d").timetuple())
                dom.setdefault(t - t % 86400, {})[key] = v
            except Exception: pass
    for key in ("btc_d", "usdt_d", "usdc_d"):
        for nm in (f"{key}.csv", f"{key.replace('_', '')}.csv"):
            p = os.path.join(scanner.HERE, nm)
            if os.path.exists(p): addcol(p, key); break
    if os.path.exists(os.path.join(scanner.HERE, "dominance.csv")):
        for r in csv.DictReader(open(os.path.join(scanner.HERE, "dominance.csv"))):
            try: dom.setdefault(calendar.timegm(datetime.strptime(r["date"][:10], "%Y-%m-%d").timetuple()), {}).update({k: float(v) for k, v in r.items() if k != "date" and v})
            except Exception: pass
    # ---------- Part B: predictiveness ----------
    def future_dd(i, days=14):
        j = min(n - 1, i + days)
        return 1 - min(L[i+1:j+1]) / C[i] if j > i else None
    def ext_today(i):
        ups = [q for q in p20 if q[3] < i]
        if len(ups) < 3 or ups[-1][2] != "L": return None
        Lc, Hp, Lpp = ups[-1], ups[-2], ups[-3]
        return (C[i] - Lc[1]) / (Hp[1] - Lpp[1]) if Hp[1] > Lpp[1] else None
    days = [i for i in range(220, n - 15) if W0 <= T[i] < W1]
    ext = {i: ext_today(i) for i in days}
    def near(lv): return lambda i: ext[i] is not None and abs(ext[i] - lv) <= .05
    preds = [("ALL DAYS (base rate)", lambda i: True), ("close within 5% of 1.0x previous 20% swing", near(1.0)), ("... of 1.272x", near(1.272)), ("... of 1.618x", near(1.618)), ("... of 2.0x", near(2.0)),
             ("close >25% above 50-day avg", lambda i: C[i] / ma50[i] > 1.25), ("close >35% above 50-day avg", lambda i: C[i] / ma50[i] > 1.35),
             ("daily RSI >= 75", lambda i: rsi[i] >= 75), ("daily RSI >= 80", lambda i: rsi[i] >= 80),
             ("up >30% in 30 days", lambda i: C[i] / C[i-30] > 1.30), ("alts weak vs BTC (alt/BTC down 10% in 30d)", lambda i: ratio[i] / ratio[i-30] < .90),
             ("alt/BTC up >15% in 30d (alt season)", lambda i: ratio[i] / ratio[i-30] > 1.15)]
    def stat(f):
        fl = [i for i in days if f(i)]
        if not fl: return None
        hit = [future_dd(i) >= .10 for i in fl]
        eps = []; last = -99
        if len(fl) == len(days): eps = fl[::14]      # base rate: one sample per 14-day block
        else:
            for i in fl:
                if i - last > 7: eps.append(i)
                last = i
        eh = [future_dd(i) >= .10 for i in eps]
        return len(fl), sum(hit) / len(fl), len(eps), sum(eh) / len(eps), med([future_dd(i) for i in fl])
    # ---------- write ----------
    Lx = [f"LAB 23 (v2: bad ticks clipped: {bad})  {datetime.now(timezone.utc):%Y-%m-%d}  BTC pullback anatomy, Oct 2020 - Aug 2025. Alt basket = equal-weight of {len(A)} large coins (listed today = survivorship).", ""]
    Lx.append("== A. Summary by pullback size (peak to trough, daily highs/lows) ==")
    Lx.append(f"{'size':<8}{'count':>6}{'med depth':>10}{'med days down':>14}{'recover<=30d':>13}{'alt basket med':>15}{'alt/BTC drop':>13}")
    for thr in (.05, .08, .10, .15, .20):
        s = [e for e in ev if e["depth"] >= thr]
        if not s: continue
        rec30 = sum(1 for e in s if e["days_to_recover"] != "" and e["days_to_recover"] <= 30) / len(s)
        mult = med([e["alt_mean"] / -e["depth"] for e in s if e["alt_mean"] == e["alt_mean"]])
        Lx.append(f"{'>=%d%%' % round(thr*100):<8}{len(s):>6}{-med([e['depth'] for e in s]):>10.0%}{med([e['days_down'] for e in s]):>14.0f}{rec30:>13.0%}{fx(med([e['alt_mean'] for e in s])):>15}{mult:>12.1f}x")
    Lx += ["", "== A. Every pullback of 10%+ ==  (ext5 = peak vs previous 5% swing, ext20 = peak vs previous 20% swing, in multiples; alts lead = days the alt basket peaked BEFORE BTC, negative = after)",
           f"{'peak':<11}{'BTC':>8}{'depth':>7}{'dn':>4}{'rec':>5}{'ext5':>6}{'ext20':>6}{'RSI':>5}{'>50d':>6}{'alts':>7}{'a/BTC':>6}{'lead':>5}{'alt/BTC 30d pre':>16}"]
    for e in ev:
        if e["depth"] < .10: continue
        Lx.append(f"{e['peak_date']:<11}{e['peak']:>8}{-e['depth']:>7.0%}{e['days_down']:>4}{str(e['days_to_recover']):>5}{str(e['ext5']):>6}{str(e['ext20']):>6}{e['rsi']:>5}{e['above50']:>6.0%}{e['alt_mean']:>7.0%}{e['alt_mean']/-e['depth']:>5.1f}x{str(e['alts_peak_lead_days']):>5}{e['altbtc_30d_before']:>16.0%}")
    Lx += ["", "== B. Do these flag days really precede a 10%+ BTC drop within 14 days? ==",
           "days = flagged days; episodes = flagged days merged if within 7 days of each other (the honest count). hit = share followed by a 10%+ fall (low vs close) within 14 days. Only past data used.",
           f"{'flag':<44}{'days':>6}{'hit':>6}{'episodes':>9}{'hit':>6}{'median fall':>12}"]
    base = stat(lambda i: True)
    for name, f in preds:
        s = stat(f)
        Lx.append(f"{name:<44}" + (f"{s[0]:>6}{s[1]:>6.0%}{s[2]:>9}{s[3]:>6.0%}{s[4]:>12.1%}" if s else "     0"))
    Lx += ["Read: a flag only means something if its hit rate is clearly above the base-rate row, in many EPISODES, not just days.", "", "== C. Stablecoin supply and dominance proxies at peaks and troughs (10%+ pullbacks) =="]
    pk = [e for e in ev if e["depth"] >= .10]
    for nm in ("USDT", "USDC"):
        if not stab.get(nm): Lx.append(f"{nm} supply: data not available from this runner."); continue
        a = [sup(nm, e["pi"], 30) for e in pk]; b = [sup(nm, e["ti"], 30) for e in pk]; allv = [sup(nm, i, 30) for i in days]
        a, b, allv = [x for x in a if x is not None], [x for x in b if x is not None], [x for x in allv if x is not None]
        Lx.append(f"{nm} supply, 30-day change: at peaks median {fx(med(a), '{:+.1%}')}, at troughs {fx(med(b), '{:+.1%}')}, all days {fx(med(allv), '{:+.1%}')}  (n={len(a)} events)")
    ar = [e["altbtc_30d_before"] for e in pk]
    Lx.append(f"alt/BTC ratio in the 30 days before 10%+ peaks: median {fx(med(ar))}, share negative {sum(1 for x in ar if x < 0)/max(1, len(ar)):.0%}; all days median {fx(med([ratio[i]/ratio[i-30]-1 for i in days]))}")
    if dom:
        for key in sorted({k for v in dom.values() for k in v}):
            def dd(i, back=14):
                a = dom.get(T[i], {}).get(key); b = dom.get(T[max(0, i - back)], {}).get(key); return a - b if a is not None and b is not None else None
            a = [x for x in (dd(e["pi"]) for e in pk) if x is not None]; b = [x for x in (dd(e["ti"]) for e in pk) if x is not None]
            Lx.append(f"{key} (percentage points, 14-day change): before peaks median {fx(med(a), '{:+.2f}')}, before troughs {fx(med(b), '{:+.2f}')} (n={len(a)})")
    else:
        Lx.append("True dominance history (BTC.D, USDT.D, USDC.D) not loaded. To add it: upload the TradingView exports as btc_d.csv, usdt_d.csv and usdc_d.csv (or one dominance.csv with columns date,btc_d,usdt_d,usdc_d) into the repo and rerun.")
    text = "\n".join(Lx)
    open(os.path.join(scanner.HERE, "lab23_summary.txt"), "w").write(text + "\n"); print(text)
    with open(os.path.join(scanner.HERE, "lab23_events.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, [k for k in ev[0] if k not in ("pi", "ti")]); w.writeheader()
        for e in ev: w.writerow({k: v for k, v in e.items() if k not in ("pi", "ti")})
    try: scanner.notify("Strategy lab 23 finished", "BTC pullback study done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
