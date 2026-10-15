#!/usr/bin/env python3
"""Signal tracker: runs the scanner once, logs every signal to signals.csv, and (every 6 hours)
fills in what price did afterwards, so we can later measure which signals actually worked.
Needs scanner.py in the same folder. Run:  python tracker.py"""
import csv, json, os, sys, time
from datetime import datetime, timezone
import scanner, paper

LOG = os.path.join(scanner.HERE, "signals.csv")
COLS = ["epoch", "time_utc", "market", "token", "verdict", "passed_filters", "price", "zone_lo", "zone_hi", "entry", "stop",
        "target", "rr", "score", "quality", "htf_match", "fib_match", "strength", "touches", "dist_pct",
        "status", "ret_24h", "ret_72h", "ret_7d", "max_gain", "max_drop", "result", "result_hours"]
SIGNALS = ("BUY SIGNAL", "IN ZONE", "IN ZONE - WAIT")
seen = []

_analyse = scanner.analyse
def analyse(tok):
    o = _analyse(tok)
    if o["zone"] and o["verdict"] in SIGNALS: seen.append((tok, o))
    return o
scanner.analyse = analyse   # scanner.run() now reports every signal to us as well

def g(x): return "" if x is None else f"{x:.8g}"

def read():
    try:
        with open(LOG, newline="") as f: return list(csv.DictReader(f))
    except Exception: return []

def write(rows):
    with open(LOG, "w", newline="") as f:
        w = csv.DictWriter(f, COLS, extrasaction="ignore"); w.writeheader(); w.writerows(rows)

def log_new():
    rows, now, added = read(), time.time(), 0
    for tok, o in seen:
        z, name, rr = o["zone"], o["tok"], scanner.rr_of(o)
        mid = (z["lo"] + z["hi"]) / 2
        if any(r["token"] == name and r["verdict"] == o["verdict"] and now - float(r["epoch"]) < scanner.COOLDOWN_H * 3600
               and abs(mid / ((float(r["zone_lo"]) + float(r["zone_hi"])) / 2) - 1) < .02 for r in rows): continue
        passed = z["pts"] >= scanner.MIN_SCORE and (rr is None or rr >= scanner.MIN_RR)
        rows.append(dict(epoch=int(now), time_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                         market="stock" if tok.startswith("STOCK:") else "crypto", token=name, verdict=o["verdict"],
                         passed_filters=int(passed), price=g(o["last"]), zone_lo=g(z["lo"]), zone_hi=g(z["hi"]), entry=g(z["entry"]),
                         stop=g(z["stop"]), target=g(o["target"]), rr=g(rr), score=z["pts"], quality=z["base"],
                         htf_match=int(z["htf"]), fib_match=int(z["fib"]), strength=g(z["s"]), touches=z["t"],
                         dist_pct=g(z["dist"]), status="open"))
        added += 1
    if added: write(rows)
    print(f"\nSignal log: {added} new, {len(rows)} total")

def candles_after(r):
    """Hourly (high, low, close) candles that started after the signal."""
    t0 = float(r["epoch"])
    if r["market"] == "stock":
        j = json.loads(scanner.http(scanner.YAHOO.format(r["token"], "1h", "1mo"), headers=scanner.UA))["chart"]["result"][0]
        q = j["indicators"]["quote"][0]
        out = [(t, h, l, c) for t, h, l, c in zip(j["timestamp"], q["high"], q["low"], q["close"]) if None not in (h, l, c) and t > t0]
    else:
        start = (int(t0) // 3600 + 1) * 3600 * 1000
        k = json.loads(scanner.http(f"https://api.mexc.com/api/v3/klines?symbol={r['token']}USDT&interval=60m&startTime={start}&limit=500"))
        out = [(x[0] / 1000, float(x[2]), float(x[3]), float(x[4])) for x in k]
    return sorted(out)

def evaluate(r, cs=None):
    t0, e, stop = float(r["epoch"]), float(r["entry"]), float(r["stop"])
    tg = float(r["target"]) if r["target"] else None
    cs = candles_after(r) if cs is None else cs
    gain = drop = 0.0; res = hrs = ""; rets = {24: "", 72: "", 168: ""}; last_age = 0
    for t, h, l, c in cs:
        age = (t + 3600 - t0) / 3600
        if age > 168: break
        last_age = age
        gain, drop = max(gain, h / e - 1), min(drop, l / e - 1)
        if not res:
            if l <= stop: res, hrs = "stop", round(age)      # if one candle touched both, assume the stop came first
            elif tg and h >= tg: res, hrs = "target", round(age)
        for H in rets:
            if age <= H: rets[H] = f"{c / e - 1:.4f}"
    for H in rets:
        if last_age < H - 1: rets[H] = ""                   # not enough time has passed yet
    r.update(ret_24h=rets[24], ret_72h=rets[72], ret_7d=rets[168], max_gain=f"{gain:.4f}", max_drop=f"{drop:.4f}",
             result=res or ("none yet" if time.time() - t0 < 7 * 86400 else "neither"), result_hours=hrs,
             status="final" if time.time() - t0 >= 7 * 86400 + 3600 else "open")

def evaluate_all(limit=60):
    rows, n = read(), 0
    for r in rows:
        if r["status"] == "final" or time.time() - float(r["epoch"]) < 3600: continue
        if n >= limit: break
        try: evaluate(r); n += 1
        except Exception as ex: print("could not evaluate", r["token"], str(ex)[:60])
    if rows: write(rows)
    print(f"Outcomes updated for {n} signals")

if __name__ == "__main__":
    toks = [a.upper() for a in sys.argv[1:]] or scanner.TOKENS
    scanner.run(toks)
    log_new()
    paper.update(seen, scanner.SHORTS)
    paper.daily()
    now = datetime.now(timezone.utc)
    if (now.hour % 6 == 0 and now.minute < 5) or os.environ.get("EVALUATE_NOW"): evaluate_all()
