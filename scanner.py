#!/usr/bin/env python3
"""Support Scanner: checks MEXC tokens on 4H + 1D and tells you when price is at a good buy zone.
No installs needed (Python 3.8+). Run:  python scanner.py        or:  python scanner.py NEAR SOL
Analysis of past price only. Not financial advice."""
import json, os, sys, time, urllib.request
from datetime import datetime

# ---------------- SETTINGS (edit these) ----------------
TOKENS = [t.strip().upper() for t in os.environ.get("TOKENS", "NEAR,SOL,ETH").split(",") if t.strip()]
CHECK_EVERY_MINUTES = int(os.environ.get("CHECK_EVERY_MINUTES", "15"))   # 0 = check once and stop
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")   # phone alerts: a long random name, e.g. "near-alerts-k39x7q2m"
# -------------------------------------------------------

API = "https://api.mexc.com/api/v3/klines?symbol={}USDT&interval={}&limit=500"
STATE = "alerts.json"
try: alerted = json.load(open(STATE))
except Exception: alerted = {}

def http(url, data=None, headers=None):
    h = {"User-Agent": "support-scanner"}
    h.update(headers or {})
    return urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=20).read()

def candles(tok, tf):
    return [dict(o=float(r[1]), h=float(r[2]), l=float(r[3]), c=float(r[4]), v=float(r[5]))
            for r in json.loads(http(API.format(tok, tf)))]

def fmt(p):
    return f"{p:.{2 if p >= 1000 else 3 if p >= 10 else 4 if p >= 1 else 5 if p >= .01 else 8}f}"

def zones(d):
    n, K, last = len(d), 5, d[-1]["c"]
    tr = [max(r["h"] - r["l"], abs(r["h"] - d[i-1]["c"]), abs(r["l"] - d[i-1]["c"])) if i else r["h"] - r["l"]
          for i, r in enumerate(d)]
    atr = sum(tr[-14:]) / 14
    tol = max(atr * .6, last * .004)
    av = sum(r["v"] for r in d) / n or 1
    piv = []
    for i in range(K, n - K):
        w = d[i-K:i+K+1]
        if d[i]["l"] <= min(r["l"] for r in w): piv.append((d[i]["l"], i, d[i]["v"]))
        if d[i]["h"] >= max(r["h"] for r in w): piv.append((d[i]["h"], i, d[i]["v"]))
    piv.sort()
    groups = []
    for p, i, v in piv:
        if groups and p - groups[-1]["m"] <= tol:
            g = groups[-1]; g["q"].append((p, i, v)); g["m"] = sum(x[0] for x in g["q"]) / len(g["q"])
        else:
            groups.append({"q": [(p, i, v)], "m": p})
    lv = []
    for g in groups:
        q, m = g["q"], g["m"]
        lv.append(dict(p=m, lo=min(min(x[0] for x in q), m - atr * .15), hi=max(max(x[0] for x in q), m + atr * .15),
                       t=len(q), sc=len(q) * 2 + sum(x[1] / n for x in q) * 2 + sum(x[2] / av for x in q) * .5))
    strong = [x for x in lv if x["t"] >= 2]
    if len(strong) >= 3: lv = strong
    mx = max([x["sc"] for x in lv] or [1])
    for x in lv: x["s"] = x["sc"] / mx
    return lv, last, atr, tol

def sweep(d, z, atr):
    """Most recent wick below the zone in the last 12 candles -> (candles ago, reclaimed?, wick low)."""
    n, last = len(d), d[-1]["c"]
    for k in range(n - 1, max(0, n - 13), -1):
        if d[k]["l"] < z["lo"] - atr * .05:
            return n - 1 - k, last >= z["lo"] and any(c["c"] >= z["lo"] for c in d[k:k+4]), d[k]["l"]
    return None

def liq_below(d, z, atr):
    """Estimated unswept long-liquidation cluster just under the zone (5x/10x/25x leverage)."""
    av = sum(r["v"] for r in d) / len(d) or 1
    for i, r in enumerate(d[:-1]):
        if r["v"] < 1.5 * av: continue
        after = min(x["l"] for x in d[i+1:])
        for L in (5, 10, 25):
            lp = r["c"] * (1 - .95 / L)
            if after > lp and z["lo"] - 2.5 * atr < lp < z["lo"]: return True
    return False

def analyse(tok):
    d4, d1 = candles(tok, "4h"), candles(tok, "1d")
    lv, last, atr, tol = zones(d4)
    lv1, _, _, tol1 = zones(d1)
    seg = d4[-120:]
    hh, ll = max(r["h"] for r in seg), min(r["l"] for r in seg)
    fibs = [hh - r * (hh - ll) for r in (.236, .382, .5, .618, .786)]
    sup = sorted([z for z in lv if z["lo"] < last], key=lambda z: -z["p"])[:5]
    res = sorted([z for z in lv if z["lo"] >= last], key=lambda z: z["p"])
    for z in sup:
        z["dist"] = max(0, (last - z["hi"]) / last * 100)
        z["htf"] = any(abs(y["p"] - z["p"]) <= max(tol, tol1) for y in lv1)
        z["fib"] = any(abs(f - z["p"]) <= tol for f in fibs)
        z["pts"] = (2 if z["s"] >= .66 else 1 if z["s"] >= .4 else 0) + z["htf"] + z["fib"] + (z["dist"] <= 3)
        z["stop"] = z["lo"] - atr * .5
    target = res[0]["p"] if res else None
    out = dict(tok=tok, last=last, verdict="WAIT", zone=None, target=target, note="")
    near = [z for z in sup if z["dist"] <= 3]
    if not near:
        out["zone"] = sup[0] if sup else None
        out["note"] = "No strong support within 3% of price"
        return out
    z = max(near, key=lambda z: (z["pts"], -z["dist"]))
    out["zone"] = z
    if z["pts"] < 2:
        out["note"] = "Nearby support is weak"
        return out
    sw, risk = sweep(d4, z, atr), liq_below(d4, z, atr)
    if sw and sw[1] and sw[0] <= 3:
        out.update(verdict="BUY SIGNAL", note=f"Price dipped to {fmt(sw[2])}, then closed back above the zone")
    elif z["dist"] <= 1:
        out.update(verdict="IN ZONE - WAIT" if risk else "IN ZONE",
                   note="Liquidations likely just below: wait for a candle to close back above the zone" if risk
                   else "At support. Scale in with 2-3 smaller orders")
    else:
        out.update(verdict="WATCH", note=f"{z['dist']:.1f}% above the zone")
    return out

def show(o):
    z = o["zone"]
    print(f'{o["tok"]:<6}{fmt(o["last"]):>11}   {o["verdict"]}')
    if z:
        rr = ""
        if o["target"] and z["p"] > z["stop"]:
            rr = f'  target {fmt(o["target"])}  risk/reward {(o["target"] - z["p"]) / (z["p"] - z["stop"]):.1f}'
        print(f'        zone {fmt(z["lo"])}-{fmt(z["hi"])}  stop {fmt(z["stop"])}{rr}  score {z["pts"]}/5')
    if o["note"]: print(f'        {o["note"]}')

def notify(title, msg):
    if not NTFY_TOPIC: return
    try: http("https://ntfy.sh/" + NTFY_TOPIC, msg.encode(), {"Title": title})
    except Exception as e: print("        (phone alert failed:", e, ")")

def run(tokens):
    print("\n" + datetime.now().strftime("%d %b %H:%M"), "-" * 40)
    for t in tokens:
        try: o = analyse(t)
        except Exception as e: print(f"{t:<6} could not check ({e})"); continue
        show(o)
        z = o["zone"]
        if z and o["verdict"] in ("BUY SIGNAL", "IN ZONE", "IN ZONE - WAIT"):
            key = f'{t}|{round(z["p"], 4)}|{o["verdict"]}'
            if time.time() - alerted.get(key, 0) > 6 * 3600:
                alerted[key] = time.time()
                try: json.dump(alerted, open(STATE, "w"))
                except Exception: pass
                notify(f'{t}: {o["verdict"]}', f'Price {fmt(o["last"])}. Zone {fmt(z["lo"])}-{fmt(z["hi"])}, stop {fmt(z["stop"])}. {o["note"]}')

if __name__ == "__main__":
    toks = [a.upper() for a in sys.argv[1:]] or TOKENS
    while True:
        run(toks)
        if not CHECK_EVERY_MINUTES: break
        time.sleep(CHECK_EVERY_MINUTES * 60)
