#!/usr/bin/env python3
"""Paper-trading ledger + daily performance report.
Every alert that passed your filters becomes an imagined trade ($100 each): bought at the alert price, sold when the stop or the
target is hit (or after 14 days). BTC/ETH SHORT SIGNALs are imagined short trades. Results go to paper_trades.csv and a daily
report is sent to your phone. Used by tracker.py. Not real trades: no slippage beyond a 0.2% round-trip cost."""
import csv, os, time
from collections import defaultdict
from datetime import datetime, timezone
import scanner

def P(n): return os.path.join(scanner.HERE, n)
LEDGER, REPORT, META = P("paper_trades.csv"), P("daily_report.md"), P("summary_state.json")
COLS = ["id", "token", "market", "side", "verdict", "score", "open_epoch", "open_time", "entry", "stop", "target", "status",
        "close_epoch", "close_time", "exit", "reason", "ret_pct", "pnl_usd", "hours", "R", "max_hours"]
COST = 0.002                  # round-trip fees + slippage
STAKE = 100.0                 # imagined money per trade
MAX_HOLD_H = 14 * 24          # close at market after this long
REOPEN_H = 24                 # don't re-enter the same token/side within this many hours of closing
SUMMARY_HOUR = int(os.environ.get("SUMMARY_HOUR_UTC", "7"))   # daily report goes out after this UTC hour (08:00 London in summer)
PRICES = {}

try:
    from zoneinfo import ZoneInfo
    LOCAL = ZoneInfo(os.environ.get("REPORT_TZ", "Europe/London"))
except Exception:
    LOCAL = timezone.utc

def stamp(t): return datetime.fromtimestamp(t, LOCAL).strftime("%d %b %H:%M")
def g(x): return "" if x is None else f"{x:.8g}"
def dur(h):
    h = float(h)
    return "<1h" if h < 1 else f"{h:.0f}h" if h < 48 else f"{h / 24:.1f}d"

def read():
    try:
        with open(LEDGER, newline="") as f: return list(csv.DictReader(f))
    except Exception: return []

def write(rows):
    with open(LEDGER, "w", newline="") as f:
        w = csv.DictWriter(f, COLS, extrasaction="ignore"); w.writeheader(); w.writerows(rows)

def key_of(r): return ("STOCK:" if r["market"] == "stock" else "") + r["token"]

def price_of(r):
    k = key_of(r)
    if k not in PRICES: PRICES[k] = scanner.candles(k, "1d" if r["market"] == "stock" else "4h")[-1]["c"]
    return PRICES[k]

def close_positions(rows):
    n, now = 0, time.time()
    for r in rows:
        if r["status"] != "open": continue
        if r["market"] == "stock" and not (os.environ.get("STOCKS_ANYTIME") or scanner.us_open()): continue
        try: p = price_of(r)
        except Exception as e: print("paper: could not price", r["token"], str(e)[:40]); continue
        e, s = float(r["entry"]), float(r["stop"]); t = float(r["target"]) if r["target"] else None
        long = r["side"] == "long"
        reason = ex = None
        if (long and p <= s) or (not long and p >= s): reason, ex = "stop", p          # stops fill at the current price (can be worse)
        elif t and ((long and p >= t) or (not long and p <= t)): reason, ex = "target", t
        elif now - float(r["open_epoch"]) > float(r.get("max_hours") or MAX_HOLD_H) * 3600: reason, ex = "time limit", p
        if not reason: continue
        net = ((ex - e) / e if long else (e - ex) / e) - COST
        risk = abs(e - s) / e
        r.update(status="closed", close_epoch=int(now), close_time=stamp(now), exit=g(ex), reason=reason, ret_pct=f"{net * 100:.2f}",
                 pnl_usd=f"{STAKE * net:.2f}", hours=f"{(now - float(r['open_epoch'])) / 3600:.1f}", R=f"{net / risk:.2f}" if risk > 0 else "")
        n += 1
    return n

def open_new(rows, seen, shorts, trend=()):
    now, c, n = time.time(), [], 0
    for o in trend:   # trend-breakout paper test (trend.py): crypto longs with their own stop, target and time limit
        c.append(dict(token=o["tok"], market="crypto", side="long", verdict=o["verdict"], score="", entry=o["last"], stop=o["stop"],
                      target=o["target"], max_hours=o["max_hours"]))
    for tok, o in seen:
        z, rr = o["zone"], scanner.rr_of(o)
        if z["pts"] >= scanner.MIN_SCORE and (rr is None or rr >= scanner.MIN_RR):
            c.append(dict(token=o["tok"], market="stock" if tok.startswith("STOCK:") else "crypto", side="long", verdict=o["verdict"],
                          score=z["pts"], entry=o["last"], stop=z["stop"], target=o["target"]))
    for o in shorts:
        if o["verdict"] == "SHORT SIGNAL" and o.get("passed"):
            c.append(dict(token=o["tok"], market="stock" if o["key"].startswith("STOCK:") else "crypto", side="short", verdict="SHORT SIGNAL", score=o["pts"], entry=o["last"], stop=o["stop"], target=o["target"]))
    for x in c:
        if (x["side"] == "long" and x["stop"] >= x["entry"]) or (x["side"] == "short" and x["stop"] <= x["entry"]): continue
        grp = lambda v: v if str(v).startswith(("BREAKOUT", "CROSS", "RECLAIM")) else "SR"      # each trend rule is tracked separately from the support-zone signals
        if any(r["token"] == x["token"] and r["side"] == x["side"] and grp(r["verdict"]) == grp(x["verdict"])
               and (r["status"] == "open" or now - float(r["close_epoch"] or 0) < REOPEN_H * 3600) for r in rows): continue
        rows.append(dict(id=len(rows) + 1, token=x["token"], market=x["market"], side=x["side"], verdict=x["verdict"], score=x["score"],
                         open_epoch=int(now), open_time=stamp(now), entry=g(x["entry"]), stop=g(x["stop"]), target=g(x["target"]), status="open",
                         max_hours=x.get("max_hours", "")))
        n += 1
    return n

def update(seen, shorts, trend=()):
    rows = read()
    c = close_positions(rows); o = open_new(rows, seen, shorts, trend)
    if c or o: write(rows)
    print(f"Paper trades: {o} opened, {c} closed, {sum(r['status'] == 'open' for r in rows)} open")

def stats(rs):
    n = len(rs)
    if not n: return None
    rets = [float(r["ret_pct"]) for r in rs]
    return dict(n=n, wins=sum(x > 0 for x in rets), avg=sum(rets) / n, pnl=sum(float(r["pnl_usd"]) for r in rs), hold=sum(float(r["hours"]) for r in rs) / n)

def line(label, s): return f"{label}: none yet" if not s else f"{label}: {s['n']} trade{'' if s['n'] == 1 else 's'}, {s['wins'] / s['n']:.0%} won, avg {s['avg']:+.2f}%, total {s['pnl']:+.0f}$, avg hold {dur(s['hold'])}"

def report(rows, now):
    closed = [r for r in rows if r["status"] == "closed"]; opn = [r for r in rows if r["status"] == "open"]
    day = [r for r in closed if now - float(r["close_epoch"]) < 86400]
    unreal = []
    for r in opn:
        try:
            p, e = price_of(r), float(r["entry"])
            unreal.append((r, ((p - e) / e if r["side"] == "long" else (e - p) / e) * 100 - COST * 100))
        except Exception: pass
    def tl(r): return f"{r['token']} {r['side']} {float(r['ret_pct']):+.1f}% in {dur(r['hours'])} ({r['reason']})"
    a, d = stats(closed), stats(day)
    T = [f"Daily report {datetime.fromtimestamp(now, LOCAL):%d %b %Y}", ""]
    T.append(line("Last 24h", d) if d else "Last 24h: no trades closed")
    T += [" - " + tl(r) for r in day[:6]]
    if unreal: T.append(f"Open now: {len(unreal)} positions, average {sum(u for _, u in unreal) / len(unreal):+.1f}% so far")
    elif opn: T.append(f"Open now: {len(opn)} positions")
    T.append(line("All time", a))
    if closed:
        b = max(closed, key=lambda r: float(r["ret_pct"])); w = min(closed, key=lambda r: float(r["ret_pct"]))
        T.append(f"Best: {b['token']} {float(b['ret_pct']):+.1f}%  Worst: {w['token']} {float(w['ret_pct']):+.1f}%")
        for v in sorted({r["verdict"] for r in closed}):
            s = stats([r for r in closed if r["verdict"] == v]); T.append(f"{v}: n={s['n']}, avg {s['avg']:+.2f}%, {s['wins'] / s['n']:.0%} won")
    if not a or a["n"] < 30: T.append("Small sample: fewer than 30 closed trades, so treat these numbers as noise.")
    T.append("Imagined $100 per trade, 0.2% costs. Full report attached.")
    M = ["# Signal performance report", f"Generated {datetime.fromtimestamp(now, LOCAL):%d %b %Y %H:%M}. Times are {os.environ.get('REPORT_TZ', 'Europe/London')}.", "",
         "Method: every alert that passed your filters is an imagined $100 trade. Longs are bought at the alert price and sold at the target "
         "(nearest resistance), the stop, or after the time limit (14 days; 7 days for CROSS and RECLAIM trend trades, a paper-only test). Costs 0.2% per trade. "
         "Prices are checked every ~5 minutes, so real fills can be worse, especially for stops.", "", "## Summary", ""]
    M += [line("All trades", a), line("Longs", stats([r for r in closed if r["side"] == "long"])), line("Shorts", stats([r for r in closed if r["side"] == "short"])),
          line("Crypto", stats([r for r in closed if r["market"] == "crypto"])), line("Stocks", stats([r for r in closed if r["market"] == "stock"])), ""]
    M += ["## By signal type", ""] + [line(v, stats([r for r in closed if r["verdict"] == v])) for v in sorted({r["verdict"] for r in closed})]
    M += ["", "## By token (closed trades)", ""]
    by = defaultdict(list)
    for r in closed: by[r["token"]].append(r)
    for tk in sorted(by, key=lambda k: -sum(float(r["pnl_usd"]) for r in by[k])): M.append(line(tk, stats(by[tk])))
    M += ["", "## Open positions", ""]
    M += [f"- {r['token']} {r['side']} ({r['verdict']}) opened {r['open_time']} at {r['entry']}, stop {r['stop']}, target {r['target'] or 'none'}: {u:+.1f}% so far" for r, u in unreal] or ["None"]
    M += ["", "## Every closed trade, by token", ""]
    for tk in sorted(by):
        M.append(f"### {tk}")
        for r in sorted(by[tk], key=lambda r: float(r["open_epoch"])):
            M.append(f"- {r['side'].upper()} {r['verdict']}: {r['open_time']} at {r['entry']} -> {r['close_time']} at {r['exit']}  "
                     f"{float(r['ret_pct']):+.2f}% ({float(r['pnl_usd']):+.2f}$ per $100), held {dur(r['hours'])}, exit: {r['reason']}")
    return "\n".join(T), "\n".join(M) + "\n"

def attach(path):
    """Send a file to the phone as an ntfy attachment (kept by ntfy.sh for about 3 hours)."""
    if not scanner.NTFY_TOPIC or not os.path.exists(path): return
    try:
        with open(path, "rb") as f: data = f.read()
        name = os.path.basename(path)
        scanner.urllib.request.urlopen(scanner.urllib.request.Request("https://ntfy.sh/" + scanner.NTFY_TOPIC, data=data, method="PUT",
                                       headers={"Filename": name, "Title": name, "Tags": "page_facing_up", "User-Agent": "support-scanner"}), timeout=30).read()
    except Exception as e: print("(could not attach", path, ":", e, ")")

def daily(force=False):
    now = datetime.now(timezone.utc); today = now.strftime("%Y-%m-%d")
    meta = scanner.load(META)
    if not force and (now.hour < SUMMARY_HOUR or meta.get("last") == today): return
    text, md = report(read(), time.time())
    with open(REPORT, "w") as f: f.write(md)
    meta["last"] = today; scanner.save(META, meta)
    if not scanner.QUIET_OLD: scanner.notify("Daily signal report", text[:3900], scanner.NTFY_TOPIC, "bar_chart")
    attach(REPORT); attach(LEDGER)
    print("Daily report sent")

if __name__ == "__main__":   # python paper.py   -> prints the report now and sends it to your phone
    daily(force=True)
    print(report(read(), time.time())[0])
