#!/usr/bin/env python3
"""BTC-gated large-coin basket: paper test. Runs once a day after the daily candle closes.
Rule, on completed daily candles: while BTC closes above its 200-day average, hold the 10 biggest coins (by market size order of the coin list, BTC and stablecoins excluded),
equal weight, refreshed every 30 days (rank = the market-size order of the scanner's coin list on the day of the refresh, stored in basketgate_baskets.json so history is never re-ranked with hindsight). When BTC closes below its 200-day average, move to cash. Re-enter at the close of the first day BTC is back above it.
Paper account of 1000, 0.1% cost per side on the amount traded. Fills are at the signal day's close (a real order would be placed the next morning, so real fills will differ).
Two extra variants add an open-interest (OI) warning from lab 26/27, declared in advance on 19 Oct 2026 and never changed: (A) OI up 15% or more in 30 days, (B) OI at a new 180-day high. After a warning the account sits in cash for 7 days, on top of the BTC switch. OI = Binance BTCUSDT futures open interest (daily files from data.binance.vision, cached in basketgate_oi.csv); if today's file is not out yet, the last known value is carried forward.
Compared with: BTC held over the same days, and the same basket held WITHOUT the BTC switch (to show what the switch costs or saves).
The record is rebuilt each day from daily candles starting on the first run day (basketgate_start.txt). Writes basketgate_report.txt, basketgate_trades.csv; quiet phone note on entries, exits and refreshes."""
import os, csv, time, json, io, zipfile, urllib.request
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Pool
import scanner, backtest as B

QUIET_TESTS = True   # paper tests keep collecting data and writing reports, but send no phone notes. Set False to turn their phone notes back on.
def note(*a, **k):
    if not QUIET_TESTS: scanner.notify(*a, **k)


TOPK = 10; REFRESH = 30; SIDE = 0.001; GATE_N = 200; COOL = 7
STABLES = {"USDT", "USDC", "DAI", "TUSD", "FDUSD", "USDE", "USD1", "PYUSD", "USDD", "BUSD", "USDP", "FRAX", "WBTC", "BTC", "STETH", "WSTETH", "WBETH"}
HERE = scanner.HERE; P = lambda f: os.path.join(HERE, f)
fd = lambda d: time.strftime("%Y-%m-%d", time.gmtime(d * 86400))

def load(a):
    tok, need = a
    try:
        m = B.hist_crypto(tok, "1d", need)
        return tok, {int(r[0] // 86400): (r[4], r[5]) for r in m}, ""
    except Exception as e: return tok, {}, str(e)[:60]

def pick(C, coins, i, days, store):
    """The first TOPK coins of the size-ordered list that have a price on day i. The choice is stored the first time it is made, so later daily rebuilds reuse it (no re-ranking with hindsight)."""
    key = fd(days[i])
    if key in store: return [c for c in store[key] if c in C and C[c][i] is not None]
    basket = [c for c in coins if C[c][i] is not None and sum(x is not None for x in C[c][max(0, i - 89):i + 1]) >= 80][:TOPK]
    store[key] = basket; return basket

def run(days, C, coins, i0, gated, store, warn=None):
    n = len(days); cb = C["BTC"]; val = {}; cash = 1.0; last_ref = None; hist = []; trades = []; events = []; curve = {i0: 1.0}
    for i in range(i0, n):
        if i > i0:                                     # mark holdings to today's close
            for c in list(val):
                a, b = C[c][i - 1], C[c][i]
                if a and b: val[c] *= b / a
        seg = [x for x in cb[max(0, i - GATE_N + 1):i + 1] if x is not None]
        g = i >= GATE_N - 1 and cb[i] is not None and len(seg) >= GATE_N * 0.9 and cb[i] > sum(seg) / len(seg)
        cool = bool(warn) and any(warn[max(0, i - COOL + 1):i + 1])
        invest = (g or not gated) and not cool
        total = cash + sum(val.values())
        if invest and (not val or last_ref is None or i - last_ref >= REFRESH):
            basket = pick(C, coins, i, days, store)
            if basket:
                new = {c: total / len(basket) for c in basket}
                cost = SIDE * sum(abs(new.get(c, 0) - val.get(c, 0)) for c in set(new) | set(val))   # amount bought + sold
                total -= cost; new = {c: total / len(basket) for c in basket}
                kind = "ENTER" if not val else "REFRESH"
                trades.append(dict(date=fd(days[i]), action=kind, coins=" ".join(basket), account=round(total * 1000, 2), gate="on" if g else "off"))
                events.append((i, kind, basket)); val = new; cash = 0.0; last_ref = i
        elif not invest and val:
            total -= SIDE * sum(val.values()); cash = total; val = {}; last_ref = None
            trades.append(dict(date=fd(days[i]), action="EXIT TO CASH", coins="", account=round(total * 1000, 2), gate="on" if g else "off")); events.append((i, "EXIT", []))
        curve[i] = cash + sum(val.values())
    return val, trades, events, curve, g

OIURL = "https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-%s.zip"
def oi_day(d):
    for k in range(3):
        try:
            r = urllib.request.urlopen(urllib.request.Request(OIURL % fd(d), headers={"User-Agent": "Mozilla/5.0"}), timeout=30)
            z = zipfile.ZipFile(io.BytesIO(r.read())); rows = list(csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())))
            v = [float(x["sum_open_interest"]) for x in rows if x.get("sum_open_interest")]
            return d, (v[-1] if v else None)
        except Exception as e:
            if getattr(e, "code", None) == 404: return d, None
            time.sleep(1.5)
    return d, None

def get_oi(days):
    """Daily BTC open interest (coins), cached in basketgate_oi.csv; fetches only missing days of the last ~280."""
    p = P("basketgate_oi.csv"); have = {}
    if os.path.exists(p):
        for r in csv.DictReader(open(p)): have[int(r["day"])] = float(r["oi"])
    want = [d for d in days[-280:] if d not in have]
    if want:
        with ThreadPoolExecutor(12) as ex:
            for d, v in ex.map(oi_day, want):
                if v: have[d] = v
        with open(p, "w", newline="") as f:
            w = csv.writer(f); w.writerow(["day", "oi", "date"])
            for d in sorted(have): w.writerow([d, have[d], fd(d)])
    return have

def warnings(days, oi):
    """Two pre-declared warnings per day index (True = warning on that day). Missing OI days carry the last known value forward."""
    n = len(days); s = []; last = None
    for d in days:
        if d in oi: last = oi[d]
        s.append(last)
    a = [False] * n; b = [False] * n
    for i in range(n):
        if s[i] is None: continue
        if i >= 30 and s[i - 30]: a[i] = s[i] / s[i - 30] - 1 >= .15
        prev = [x for x in s[max(0, i - 180):i] if x]
        if len(prev) > 100: b[i] = s[i] >= max(prev)
    return a, b

def main():
    sp = P("basketgate_start.txt"); today = int(time.time() // 86400)
    start = int(open(sp).read().strip()) if os.path.exists(sp) else today - 1
    if not os.path.exists(sp): open(sp, "w").write(str(start))
    need = 330 + max(0, today - start)
    coins = [c for c in scanner.top100() if c.upper() not in STABLES][:99]
    with Pool(max(1, os.cpu_count() or 1)) as p: res = p.map(load, [(t, need) for t in ["BTC"] + coins])
    data = {t: d for t, d, e in res if len(d) > 100}
    if "BTC" not in data: raise SystemExit("no BTC data")
    days = sorted(data["BTC"]); n = len(days); idx = {d: i for i, d in enumerate(days)}
    C, V = {}, {}
    for t, d in data.items():
        c = [None] * n; v = [None] * n
        for dd, (cc, vv) in d.items():
            if dd in idx: c[idx[dd]] = cc; v[idx[dd]] = vv
        C[t], V[t] = c, v
    alts = [t for t in data if t != "BTC" and max(x for x in C[t] if x) / min(x for x in C[t] if x) >= 1.3]
    i0 = next((i for i, d in enumerate(days) if d >= start), n - 1)
    bp = P("basketgate_baskets.json"); store = json.load(open(bp)) if os.path.exists(bp) else {}
    val, trades, events, curve, g = run(days, C, alts, i0, True, store)
    _, _, _, curve_u, _ = run(days, C, alts, i0, False, store)
    try: oi = get_oi(days); wa, wb = warnings(days, oi); oi_note = f"OI data to {fd(max(oi))}" if oi else "OI data unavailable"
    except Exception as e: oi = {}; wa = wb = [False] * n; oi_note = "OI data unavailable (" + str(e)[:40] + ")"
    vA = run(days, C, alts, i0, True, store, wa); vB = run(days, C, alts, i0, True, store, wb)
    json.dump(store, open(bp, "w"))
    cb = C["BTC"]; gate_now = cb[-1] > sum(cb[-GATE_N:]) / GATE_N; last = days[-1]
    eq, equ, btc = curve[n - 1], curve_u[n - 1], cb[n - 1] / cb[i0]
    L_ = [f"BTC-GATED BASKET PAPER TEST  data to {fd(last)} (completed daily candles)   started {fd(days[i0])}   universe {len(alts)} coins",
          f"BTC {'ABOVE' if gate_now else 'BELOW'} its 200-day average -> {'basket held' if gate_now else 'cash'}. Rule: top-{TOPK} coins by market size order, equal weight, refreshed every {REFRESH} days; cash while BTC is below its 200-day average.",
          f"Paper account (1000 start, 0.1% per side): {1000 * eq:,.0f} ({(eq - 1) * 100:+.1f}%)   |   same basket WITHOUT the BTC switch: {1000 * equ:,.0f} ({(equ - 1) * 100:+.1f}%)   |   BTC held: {1000 * btc:,.0f} ({(btc - 1) * 100:+.1f}%)", ""]
    if val:
        tot = sum(val.values()); L_.append(f"HOLDING ({len(val)} coins, last refreshed {[t['date'] for t in trades if t['action'] in ('ENTER', 'REFRESH')][-1]}):")
        for c, v_ in sorted(val.items(), key=lambda x: -x[1]): L_.append(f"  {c:<8} {100 * v_ / tot:4.1f}% of account   price {C[c][-1]:.6g}")
    else: L_.append("HOLDING: cash")
    L_ += ["", f"OI WARNING VARIANTS ({oi_note}; cash {COOL} days after a warning, on top of the BTC switch):"]
    for nm, v_, w_ in (("A: OI up 15%+ in 30 days", vA, wa), ("B: OI at a new 180-day high", vB, wb)):
        e_ = v_[3][n - 1]; wd = [fd(days[i]) for i in range(i0, n) if w_[i]]
        L_.append(f"  {nm:<30} account {1000 * e_:,.0f} ({(e_ - 1) * 100:+.1f}%)   {'holding ' + str(len(v_[0])) + ' coins' if v_[0] else 'in cash'}   warning today: {'YES' if w_[n - 1] else 'no'}   warning days since start: {len(wd)}" + (f" (last {wd[-1]})" if wd else ""))
    L_ += ["", f"ACTIONS ({len(trades)}):"] + [f"  {t['date']}  {t['action']:<13} {t['coins']}   account {t['account']}" for t in trades[-10:]]
    L_ += ["", "Judge it only after a full BTC bull-to-bear switch has happened, or many months. The lab 25 test showed the switch avoids most bear-market losses but gives up much of the bull-market profit; this paper test shows whether that holds live."]
    open(P("basketgate_report.txt"), "w").write("\n".join(L_) + "\n"); print("\n".join(L_))
    if trades:
        with open(P("basketgate_trades.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, list(trades[0].keys())); w.writeheader(); w.writerows(trades)
    ev = [e for e in events if e[0] == n - 1]; np_ = P("basketgate_notified.txt")
    done = open(np_).read().strip() if os.path.exists(np_) else ""
    if ev and done != str(last):
        msg = "; ".join(f"{k} {' '.join(b)}" for _, k, b in ev)
        try: note("Basket paper test: " + ", ".join(k for _, k, _ in ev), msg + "\nPaper test - signals from the daily close.", scanner.NTFY_TOPIC, "bar_chart", 2)
        except Exception as e: print("(phone send failed:", e, ")")
        open(np_, "w").write(str(last))

if __name__ == "__main__":
    main()
