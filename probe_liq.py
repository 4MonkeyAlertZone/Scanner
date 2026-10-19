"""Probe: what free liquidation / positioning history can the Actions runner reach? Writes probe_liq_report.txt. Read-only; no trading."""
import urllib.request, json, io, zipfile, time, os
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = []
def say(s): print(s); OUT.append(s)
def get(url, n=300000, t=25):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=t)
        return r.status, r.read(n)
    except Exception as e:
        return getattr(e, "code", None), str(e)[:150].encode()
def exists(url):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"}), timeout=25); return r.status
    except Exception as e: return getattr(e, "code", str(e)[:60])

say("PROBE: free liquidation / positioning data  " + time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()))
say("\n1) data.binance.vision futures daily files (BTCUSDT): which dataset exists on which dates")
base = "https://data.binance.vision/data/futures/um/daily"
for ds, name in [("metrics", "BTCUSDT-metrics-%s.zip"), ("liquidationSnapshot", "BTCUSDT-liquidationSnapshot-%s.zip"), ("bookTicker", "BTCUSDT-bookTicker-%s.zip")]:
    row = []
    for d in ["2020-06-15", "2021-03-15", "2021-11-10", "2022-06-15", "2023-06-15", "2024-06-15", "2025-06-15", "2026-09-15"]:
        row.append(d + "=" + str(exists("%s/%s/BTCUSDT/%s" % (base, ds, name % d))))
    say("  %-20s %s" % (ds, "  ".join(row)))

say("\n2) Sample content of one metrics file (open interest + long/short ratios)")
st, b = get(base + "/metrics/BTCUSDT/BTCUSDT-metrics-2024-06-15.zip", 2000000)
if st == 200:
    try:
        z = zipfile.ZipFile(io.BytesIO(b)); t = z.read(z.namelist()[0]).decode().splitlines()
        say("  rows: %d" % len(t)); [say("  " + l) for l in t[:3]]
    except Exception as e: say("  could not parse: %s" % e)
else: say("  status %s" % st)

say("\n3) Binance futures REST (recent only)")
for u in ["https://fapi.binance.com/fapi/v1/allForceOrders?symbol=BTCUSDT&limit=5",
          "https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1d&limit=500",
          "https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=1d&limit=500"]:
    st, b = get(u); txt = b.decode("utf8", "ignore")
    extra = ""
    if st == 200:
        try:
            j = json.loads(txt); extra = " items=%d" % len(j) if isinstance(j, list) else ""
            if isinstance(j, list) and j and "timestamp" in j[0]: extra += " oldest=" + time.strftime("%Y-%m-%d", time.gmtime(j[0]["timestamp"] / 1000))
        except Exception: pass
    say("  %s -> %s%s %s" % (u.split("com")[1][:70], st, extra, "" if st == 200 else txt[:100]))

say("\n4) OKX public liquidation orders (recent only)")
st, b = get("https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&uly=BTC-USDT&state=filled&limit=100")
txt = b.decode("utf8", "ignore"); say("  status %s  %s" % (st, txt[:200]))
st, b = get("https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume?ccy=BTC&period=1D")
txt = b.decode("utf8", "ignore")
try:
    j = json.loads(txt)["data"]; say("  OKX open-interest-volume 1D: rows=%d oldest=%s" % (len(j), time.strftime("%Y-%m-%d", time.gmtime(int(j[-1][0]) / 1000))))
except Exception: say("  OKX open-interest-volume status %s %s" % (st, txt[:120]))

say("\n5) Bybit (recent only)")
st, b = get(b"https://api.bybit.com/v5/market/open-interest?category=linear&symbol=BTCUSDT&intervalTime=1d&limit=200".decode())
txt = b.decode("utf8", "ignore")
try:
    j = json.loads(txt)["result"]["list"]; say("  Bybit OI 1d: rows=%d oldest=%s" % (len(j), time.strftime("%Y-%m-%d", time.gmtime(int(j[-1]["timestamp"]) / 1000))))
except Exception: say("  Bybit status %s %s" % (st, txt[:120]))
open(os.path.join(HERE, "probe_liq_report.txt"), "w").write("\n".join(OUT) + "\n")
