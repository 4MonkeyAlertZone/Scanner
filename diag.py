#!/usr/bin/env python3
"""Data-source check: how much 4-hour history can each free exchange API really give us? Writes diag_output.txt."""
import json, time, urllib.request
from datetime import datetime, timezone
OUT = []
def say(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); OUT.append(s)
def get(url, tries=2):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=25).read().decode()
        except Exception as e:
            err = str(e)[:80]; time.sleep(1)
    return "ERR " + err
D = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M")
def span(name, ts, extra=""):
    if not ts: say(f"{name}: NO DATA {extra}"); return
    dup = len(ts) - len(set(ts))
    say(f"{name}: {len(ts)} candles, {D(min(ts))} -> {D(max(ts))}, duplicates {dup}, sorted {ts == sorted(ts)} {extra}")
now = int(time.time())
# 1) MEXC, what the scanner used: page backwards with endTime
ts = []; end = now * 1000
for p in range(4):
    r = get(f"https://api.mexc.com/api/v3/klines?symbol=BTCUSDT&interval=4h&endTime={end}&limit=500")
    if r.startswith("ERR"): say("MEXC endTime page", p, r); break
    k = json.loads(r)
    if not k: break
    say(f"MEXC endTime page {p}: {len(k)} candles, {D(k[0][0] / 1000)} -> {D(k[-1][0] / 1000)}")
    ts += [x[0] / 1000 for x in k]; end = int(k[0][0]) - 1
span("MEXC endTime paging, all pages together", ts)
# 2) MEXC paging forward with startTime (3 years ago)
ts = []; start = (now - 3 * 365 * 86400) * 1000
for p in range(3):
    r = get(f"https://api.mexc.com/api/v3/klines?symbol=BTCUSDT&interval=4h&startTime={start}&limit=500")
    if r.startswith("ERR"): say("MEXC startTime page", p, r); break
    k = json.loads(r)
    if not k: break
    say(f"MEXC startTime page {p}: {len(k)} candles, {D(k[0][0] / 1000)} -> {D(k[-1][0] / 1000)}")
    ts += [x[0] / 1000 for x in k]; start = int(k[-1][0]) + 1
span("MEXC startTime paging", ts)
# 3) Bybit v5 spot
ts = []; end = now * 1000
for p in range(4):
    r = get(f"https://api.bybit.com/v5/market/kline?category=spot&symbol=BTCUSDT&interval=240&limit=1000&end={end}")
    if r.startswith("ERR"): say("Bybit", r); break
    try: k = json.loads(r)["result"]["list"]
    except Exception: say("Bybit odd reply:", r[:120]); break
    if not k: break
    t = [int(x[0]) / 1000 for x in k]; ts += t; end = int(min(t) * 1000) - 1
span("Bybit spot (1000 per page, 4 pages)", ts)
# 4) OKX
ts = []; after = ""
for p in range(8):
    r = get("https://www.okx.com/api/v5/market/history-candles?instId=BTC-USDT&bar=4H&limit=100" + (f"&after={after}" if after else ""))
    if r.startswith("ERR"): say("OKX", r); break
    try: k = json.loads(r)["data"]
    except Exception: say("OKX odd reply:", r[:120]); break
    if not k: break
    t = [int(x[0]) / 1000 for x in k]; ts += t; after = str(int(min(t) * 1000))
span("OKX history-candles (100 per page, 8 pages)", ts)
# 5) Binance (often blocked for US servers) and Binance.US
for nm, host in (("Binance", "api.binance.com"), ("Binance.US", "api.binance.us")):
    ts = []; end = now * 1000
    for p in range(3):
        r = get(f"https://{host}/api/v3/klines?symbol=BTCUSDT&interval=4h&endTime={end}&limit=1000")
        if r.startswith("ERR") or not r.startswith("["): say(nm, r[:100]); break
        k = json.loads(r)
        if not k: break
        ts += [x[0] / 1000 for x in k]; end = int(k[0][0]) - 1
    span(nm + " (1000 per page, 3 pages)", ts)
# 6) CryptoCompare hourly, aggregated to 4h
ts = []; to = now
for p in range(3):
    r = get(f"https://min-api.cryptocompare.com/data/v2/histohour?fsym=BTC&tsym=USDT&limit=2000&aggregate=4&toTs={to}")
    if r.startswith("ERR"): say("CryptoCompare", r); break
    try: k = json.loads(r)["Data"]["Data"]
    except Exception: say("CryptoCompare odd reply:", r[:120]); break
    if not k: break
    t = [x["time"] for x in k]; ts += t; to = min(t) - 1
span("CryptoCompare 4h (2000 per page, 3 pages)", ts)
# 7) Yahoo Finance hourly for a coin (limit ~2 years)
r = get("https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?interval=1h&range=2y")
try:
    j = json.loads(r)["chart"]["result"][0]; span("Yahoo BTC-USD 1h, 2y", j["timestamp"])
except Exception: say("Yahoo:", r[:120])
with open("diag_output.txt", "w") as f: f.write("\n".join(OUT) + "\n")
