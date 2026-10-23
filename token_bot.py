#!/usr/bin/env python3
"""TELEGRAM TOKEN ANALYSIS BOT. Message your bot a token name (for example  NEAR   or   SUI 4h   or   /a ONDO) and it replies with a chart (candles, 50/200-day lines, support and resistance, Fibonacci retracements and extensions, RSI, volume)
and a written swing-trade map: trend state, key levels, entry zone, stop, targets and risk/reward. Commands: /help, /regime.
How it runs: GitHub Actions cannot listen for messages, so a scheduled workflow checks for new messages every 5 minutes (a reply takes roughly 5-15 minutes; GitHub schedules are best effort). It only answers YOUR chat (TELEGRAM_CHAT_ID).
Honest status: support/resistance and Fibonacci levels are a map of where price reacted before, not predictions. In this project's own tests the trend/regime state mattered much more than the levels, so every reply starts with the trend state and flags longs against a downtrend. Not financial advice."""
import os, sys, io, json, time, math, re, uuid, urllib.parse, urllib.request
import scanner, backtest as B

TOK = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(); CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
ALIAS = {"BITCOIN": "BTC", "ETHEREUM": "ETH", "ETHER": "ETH", "SOLANA": "SOL", "RIPPLE": "XRP", "CARDANO": "ADA", "DOGECOIN": "DOGE", "POLKADOT": "DOT", "CHAINLINK": "LINK", "AVALANCHE": "AVAX", "HEDERA": "HBAR", "RNDR": "RENDER", "NEARPROTOCOL": "NEAR", "BINANCECOIN": "BNB", "LITECOIN": "LTC", "POLYGON": "POL", "MATIC": "POL"}
TFS = {"1h": "1h", "4h": "4h", "1d": "1d", "d": "1d", "daily": "1d", "4hr": "4h", "h4": "4h"}
HERE = scanner.HERE

def tg_call(method, data=None, timeout=30):
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOK}/{method}", data=urllib.parse.urlencode(data).encode() if data is not None else None)
    try: return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except urllib.error.HTTPError as e: return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e: return {"ok": False, "error": type(e).__name__}

def send_text(text):
    for i in range(0, len(text), 3900): tg_call("sendMessage", {"chat_id": CHAT, "text": text[i:i + 3900], "disable_web_page_preview": "true"})

def send_photo(png, caption=""):
    b = "----bot" + uuid.uuid4().hex; parts = []
    for k, v in (("chat_id", CHAT), ("caption", caption[:1000])):
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="photo"; filename="chart.png"\r\nContent-Type: image/png\r\n\r\n'.encode() + png + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOK}/sendPhoto", data=b"".join(parts), headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    try: return json.loads(urllib.request.urlopen(req, timeout=60).read()).get("ok")
    except Exception as e: print("sendPhoto failed", type(e).__name__); return False

def pending():
    r = tg_call("getUpdates", {"timeout": 0})
    ups = r.get("result") or []; mine = []
    for u in ups:
        m = u.get("message") or {}; c = str((m.get("chat") or {}).get("id", ""))
        if c == CHAT and m.get("text"): mine.append((u["update_id"], m["text"].strip()))
    return ups, mine

# ------------------------------------------------------------------ maths
def sma(x, k): return [None if i < k - 1 else sum(x[i - k + 1:i + 1]) / k for i in range(len(x))]
def rsi(c, n=14):
    out = [None] * len(c)
    if len(c) <= n: return out
    g = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]; l = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
    ag = sum(g[:n]) / n; al = sum(l[:n]) / n; out[n] = 100 - 100 / (1 + ag / al) if al else 100
    for i in range(n, len(g)):
        ag = (ag * (n - 1) + g[i]) / n; al = (al * (n - 1) + l[i]) / n; out[i + 1] = 100 - 100 / (1 + ag / al) if al else 100
    return out
def atr(h, l, c, n=14):
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    return sum(tr[-n:]) / n if len(tr) >= n else None
def pivots(h, l, k=5):
    ph, pl = [], []
    for i in range(k, len(h) - k):
        if h[i] == max(h[i - k:i + k + 1]): ph.append((i, h[i]))
        if l[i] == min(l[i - k:i + k + 1]): pl.append((i, l[i]))
    return ph, pl
def cluster(pts, tol, n_bars):
    pts = sorted(pts, key=lambda p: p[1]); groups = []
    for i, p in pts:
        if groups and abs(p - sum(g[1] for g in groups[-1]) / len(groups[-1])) <= tol: groups[-1].append((i, p))
        else: groups.append([(i, p)])
    out = []
    for g in groups:
        price = sum(p for _, p in g) / len(g); touches = len(g); recent = sum(1 for i, _ in g if i > n_bars - 80)
        out.append((price, touches, touches + recent * 0.5))
    return out
def fmt(x):
    if x is None: return "-"
    if x >= 1000: return f"{x:,.0f}"
    if x >= 100: return f"{x:.1f}"
    if x >= 1: return f"{x:.3f}"
    return f"{x:.5f}".rstrip("0")

def analyze(rows, tf, btc_rows=None, sym="X"):
    t = [r[0] for r in rows]; o = [r[1] for r in rows]; h = [r[2] for r in rows]; l = [r[3] for r in rows]; c = [r[4] for r in rows]; v = [r[5] for r in rows]; n = len(c)
    px = c[-1]; A = atr(h, l, c); s50 = sma(c, 50); s200 = sma(c, 200); R = rsi(c)
    ph, pl = pivots(h, l, 5); tol = 0.75 * A
    cl = cluster(ph + pl, tol, n); cl = [x for x in cl if x[1] >= 2]
    sup = sorted([x for x in cl if x[0] < px - 0.2 * A], key=lambda x: -x[0])[:3]; res = sorted([x for x in cl if x[0] > px + 0.2 * A], key=lambda x: x[0])[:3]
    W = min(n, 180 if tf == "1d" else 240); wh = h[-W:]; wl = l[-W:]; iH = max(range(W), key=lambda i: wh[i]); iL = min(range(W), key=lambda i: wl[i]); H = wh[iH]; Lo = wl[iL]
    up = iL < iH; rng = H - Lo
    if up:
        ret = {r: H - r * rng for r in (0.236, 0.382, 0.5, 0.618, 0.786)}; ext = {e: Lo + e * rng for e in (1.272, 1.618)}
    else:
        ret = {r: Lo + r * rng for r in (0.236, 0.382, 0.5, 0.618, 0.786)}; ext = {e: H - e * rng for e in (1.272, 1.618)}
    return dict(t=t, o=o, h=h, l=l, c=c, v=v, n=n, px=px, A=A, s50=s50, s200=s200, rsi=R, sup=sup, res=res, up=up, H=H, Lo=Lo, iH=n - W + iH, iL=n - W + iL, ret=ret, ext=ext, tf=tf)

def plan(a):
    px, A = a["px"], a["A"]; s50, s200 = a["s50"][-1], a["s200"][-1]; lines = []
    above200 = s200 is not None and px > s200; above50 = s50 is not None and px > s50
    cands = [(p, f"support {fmt(p)} ({tc} touches)") for p, tc, sc in a["sup"]]
    if a["up"]:
        for r in (0.382, 0.5, 0.618):
            if a["ret"][r] < px - 0.2 * A: cands.append((a["ret"][r], f"fib {r} at {fmt(a['ret'][r])}"))
    if s50 and s50 < px - 0.2 * A: cands.append((s50, f"50-day line {fmt(s50)}"))
    cands.sort(key=lambda x: -x[0]); entry = cands[0] if cands else None
    tgts = [p for p, tc, sc in a["res"]]
    if a["up"]:
        tgts += [e for e in a["ext"].values() if e > px]
    tgts = sorted(set(round(x, 8) for x in tgts if x > px + 0.5 * A))[:3]
    if above200 and above50: bias = "UPTREND (above 200-day and 50-day): pullback longs are with the trend."
    elif above200: bias = "MIXED (above 200-day, below 50-day): trend is weakening; wait for a reclaim of the 50-day before adding."
    else: bias = "DOWNTREND (below the 200-day): our rules say no long swing setups here. Levels below are a map only."
    lines.append("BIAS: " + bias)
    if entry and tgts:
        lo, hi = entry[0] - 0.25 * A, entry[0] + 0.25 * A; stop = entry[0] - 1.0 * A; mid = entry[0]
        lines.append(f"PULLBACK IDEA (long): entry zone {fmt(lo)} to {fmt(hi)} (around {entry[1]}); stop below {fmt(stop)} (1 ATR under the level).")
        for k, tgt in enumerate(tgts[:2], 1):
            rr = (tgt - mid) / (mid - stop) if mid > stop else float("nan"); lines.append(f"  target {k}: {fmt(tgt)} (+{(tgt / mid - 1) * 100:.1f}%), risk/reward about {rr:.1f}")
        risk = (mid - stop) / mid * 100; lines.append(f"  stop distance {risk:.1f}%; risking 1% of your account means a position of about {1.0 / risk * 100:.0f}% of the account.")
    if a["res"]:
        r1 = a["res"][0][0]; lines.append(f"BREAKOUT IDEA: a daily close above {fmt(r1)} would clear the nearest resistance; stop under {fmt(r1 - A)}.")
    if not above200: lines.append(f"RECLAIM LEVEL to watch: {fmt(s200)} (200-day) / {fmt(s50)} (50-day).")
    return "\n".join(lines)

def text_report(sym, rows, a, btc_rows):
    px, c = a["px"], a["c"]; ret = lambda k: (px / c[-1 - k] - 1) * 100 if a["n"] > k else float("nan")
    ath = max(a["h"]); s50, s200 = a["s50"][-1], a["s200"][-1]; R = a["rsi"][-1]
    tfn = "daily" if a["tf"] == "1d" else a["tf"]; d = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(a["t"][-1]))
    L = [f"{sym}/USDT {tfn} analysis (last candle {d})", f"Price {fmt(px)}   7d {ret(7):+.0f}%   30d {ret(30):+.0f}%   90d {ret(90):+.0f}%   from high in data {((px / ath - 1) * 100):+.0f}%"]
    L.append(f"TREND: {'above' if s200 and px > s200 else 'below'} 200-day ({fmt(s200)}, {((px / s200 - 1) * 100) if s200 else 0:+.0f}%), {'above' if s50 and px > s50 else 'below'} 50-day ({fmt(s50)}, {((px / s50 - 1) * 100) if s50 else 0:+.0f}%); RSI14 {R:.0f}; ATR14 {fmt(a['A'])} ({a['A'] / px * 100:.1f}% of price)")
    vol5 = sum(a["v"][-5:]) / 5; vol50 = sum(a["v"][-50:]) / 50 if a["n"] >= 50 else None
    if vol50: L.append(f"Volume: last 5 candles {vol5 / vol50:.1f}x the 50-candle average")
    if btc_rows and sym != "BTC" and len(btc_rows) > 100:
        bc = {int(r[0] // 86400): r[4] for r in btc_rows}; ts = {int(t // 86400): x for t, x in zip(a["t"], a["c"])}; common = sorted(set(bc) & set(ts))
        if len(common) > 95:
            rr = lambda k: ((ts[common[-1]] / bc[common[-1]]) / (ts[common[-1 - k]] / bc[common[-1 - k]]) - 1) * 100
            L.append(f"VS BTC (ratio change): 30d {rr(30):+.0f}%, 90d {rr(90):+.0f}%  ({'outperforming' if rr(90) > 0 else 'lagging'} BTC over 90d)")
    L += ["", "SUPPORT: " + (", ".join(f"{fmt(p)} ({tc}x)" for p, tc, sc in a["sup"]) or "none clear nearby"), "RESISTANCE: " + (", ".join(f"{fmt(p)} ({tc}x)" for p, tc, sc in a["res"]) or "none clear nearby (price near the top of its range)")]
    sw = "up-swing" if a["up"] else "down-swing"
    L.append(f"FIB ({sw}, low {fmt(a['Lo'])} to high {fmt(a['H'])}): " + ", ".join(f"{k} {fmt(v)}" for k, v in a["ret"].items()) + " | extensions " + ", ".join(f"{k} {fmt(v)}" for k, v in a["ext"].items()))
    L += ["", plan(a)]
    return "\n".join(L)

def chart(sym, a):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    N = min(a["n"], 150); s = a["n"] - N; x = list(range(N)); o, h, l, c, v = (a[k][s:] for k in ("o", "h", "l", "c", "v"))
    fig, (ax, axr, axv) = plt.subplots(3, 1, figsize=(10, 8), sharex=True, gridspec_kw={"height_ratios": [6, 1.6, 1.4]}); fig.patch.set_facecolor("white")
    up, dn = "#1b9e77", "#d6455d"
    for i in x:
        col = up if c[i] >= o[i] else dn; ax.vlines(i, l[i], h[i], color=col, lw=0.8); ax.bar(i, c[i] - o[i] if abs(c[i] - o[i]) > 1e-12 else h[i] * 1e-4, bottom=o[i], width=0.7, color=col)
    for key, col, nm in (("s50", "#2b6cb0", "50"), ("s200", "#8e5ea2", "200")):
        ser = a[key][s:]; xs = [i for i in x if ser[i] is not None]
        if xs: ax.plot(xs, [ser[i] for i in xs], color=col, lw=1.4, label=f"{nm} avg")
    xr = N - 1
    for p, tc, sc in a["sup"]: ax.axhline(p, color=up, ls="--", lw=1, alpha=.8); ax.text(xr + 1, p, f"S {fmt(p)}", color=up, fontsize=8, va="center")
    for p, tc, sc in a["res"]: ax.axhline(p, color=dn, ls="--", lw=1, alpha=.8); ax.text(xr + 1, p, f"R {fmt(p)}", color=dn, fontsize=8, va="center")
    lo, hi = min(l), max(h); pad = (hi - lo) * 0.25
    for k, vv in list(a["ret"].items()) + [(f"ext {k}", vv) for k, vv in a["ext"].items()]:
        if lo - pad <= vv <= hi + pad: ax.axhline(vv, color="#888", ls=":", lw=0.8); ax.text(0, vv, f" fib {k}", color="#666", fontsize=7, va="bottom")
    ax.set_ylim(lo - pad, hi + pad); ax.set_xlim(-1, N + 9); ax.set_title(f"{sym}/USDT  {'daily' if a['tf'] == '1d' else a['tf']}   price {fmt(a['px'])}", loc="left", fontsize=12); ax.legend(loc="upper left", fontsize=8, frameon=False)
    r = a["rsi"][s:]; axr.plot([i for i in x if r[i] is not None], [r[i] for i in x if r[i] is not None], color="#444", lw=1); axr.axhline(70, color=dn, lw=.6, ls=":"); axr.axhline(30, color=up, lw=.6, ls=":"); axr.set_ylim(0, 100); axr.set_ylabel("RSI", fontsize=8)
    axv.bar(x, v, color=[up if c[i] >= o[i] else dn for i in x], width=0.7, alpha=.6); axv.set_ylabel("Vol", fontsize=8)
    ticks = list(range(0, N, max(1, N // 6))); axv.set_xticks(ticks); axv.set_xticklabels([time.strftime("%d %b" if a["tf"] == "1d" else "%d %b %Hh", time.gmtime(a["t"][s + i])) for i in ticks], fontsize=8)
    for q in (ax, axr, axv): q.grid(alpha=.15); [sp.set_visible(False) for k, sp in q.spines.items() if k in ("top", "right")]
    fig.tight_layout(); buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=110); plt.close(fig); return buf.getvalue()

def parse(text):
    t = text.strip(); low = t.lower()
    if low.startswith(("/start", "/help", "help")): return ("help", None, None)
    if low.startswith("/regime") or low == "regime": return ("regime", None, None)
    t = re.sub(r"^/(a|analyze|analyse|t)\b", "", t, flags=re.I).strip(); words = re.split(r"[\s,]+", t); sym = None; tf = None
    for w in words:
        if not w: continue
        if w.lower() in TFS: tf = TFS[w.lower()]; continue
        if sym is None: sym = re.sub(r"[^A-Za-z0-9]", "", w.split("/")[0]).upper()
    if not sym: return ("help", None, None)
    return ("analyze", ALIAS.get(sym, sym), tf)

HELP = ("Send a token name and I reply with a chart and a swing-trade map.\nExamples:  NEAR   |   SUI 4h   |   /a ONDO   |   bitcoin\nTimeframes: 1d (default, also adds a 4h chart), 4h, 1h.   /regime shows the crypto and stocks regime states.\n"
        "Replies take about 5-15 minutes (the bot checks for messages every 5 minutes). Levels are a map of past reactions, not predictions; trend and regime matter more. Not financial advice.")

def regime_text():
    out = []
    for f, nm in (("regime_state.json", "Crypto regime"), ("stocks_state.json", "Stocks regime")):
        try:
            s = json.load(open(os.path.join(HERE, f))); out.append(f"{nm}: {s.get('state')}  light {s.get('lev_color') or s.get('color')}  (data {s.get('date')})")
        except Exception: out.append(f"{nm}: unavailable")
    return "\n".join(out)

def handle(sym, tf):
    send_text(f"Analysing {sym}...")
    btc = None
    try: btc = B.hist_crypto("BTC", "1d", 400)
    except Exception: pass
    frames = [tf] if tf else ["1d", "4h"]; done = False
    for fr in frames:
        try: rows = B.hist_crypto(sym, fr, 900 if fr == "1d" else 600)
        except Exception as e: rows = []
        if len(rows) < 80:
            if not done: send_text(f"I could not find enough {fr} history for {sym}/USDT on Binance.US or OKX (found {len(rows)} candles). Check the ticker, or it may be too new/small."); return
            continue
        a = analyze(rows, fr, btc, sym); rep = text_report(sym, rows, a, btc if fr == "1d" else None)
        if not done: rep = ("Crypto regime context: " + regime_text().split("\n")[0] + "\n\n") + rep
        try: png = chart(sym, a)
        except Exception as e: print("chart failed", type(e).__name__, str(e)[:100]); png = None
        if png: send_photo(png, f"{sym}/USDT {'daily' if fr == '1d' else fr}")
        send_text(rep); done = True
        if fr == "1d" and tf is None: rep_note = None

def main():
    if not TOK or not CHAT: raise SystemExit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing")
    ups, mine = pending()
    if "--check" in sys.argv:
        flag = "true" if mine else "false"; print("pending messages:", len(mine))
        if os.environ.get("GITHUB_OUTPUT"): open(os.environ["GITHUB_OUTPUT"], "a").write(f"pending={flag}\n")
        return
    done = 0
    for uid, text in mine:
        kind, sym, tf = parse(text)
        if done >= 4: send_text("Too many requests at once; I handled 4. Send the rest again in a few minutes."); break
        try:
            if kind == "help": send_text(HELP)
            elif kind == "regime": send_text(regime_text())
            else: handle(sym, tf)
        except Exception as e:
            print("error", type(e).__name__, str(e)[:120]); send_text(f"Sorry, something went wrong analysing that ({type(e).__name__}). Try again later.")
        done += 1
    if ups: tg_call("getUpdates", {"offset": max(u["update_id"] for u in ups) + 1, "timeout": 0})     # confirm so they are not handled twice

if __name__ == "__main__":
    main()
