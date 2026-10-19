#!/usr/bin/env python3
"""ALT REGIME ALERT: phone notification when the 'alts in / alts out' state changes. Runs once a day just after the daily candle closes.
State = IN only when ALL of: (1) BTC closed above its 200-day average, (2) BTC closed above its 50-day average, (3) no BTC open-interest warning C in the last 14 days
(C = BTC futures open interest at a new 180-day high AND up 15%+ in 30 days; data from data.binance.vision, cached in basketgate_oi.csv by basket_paper.py).
Otherwise OUT. These are the 'gate + 50-day' and 'gate + OI C-14' rules from the majors/coins5 reports, combined. Rules fixed on 19 Oct 2026, never changed.
Honest status: the OI part was chosen after seeing the data (not out-of-sample); backtests are survivorship-flattered and cover ~3 phases. Use as a prompt to look, not an order.
Writes regime_state.json, regime_log.csv, regime_report.txt. Sends a phone alert on every change (and once on first run). Also sends a separate LEVERAGE note daily while IN (louder with a warning when BTC is within 2% of the 50-day exit line, or price is 10%+ (BTC) / 15%+ (ETH) below the IN entry)."""
import os, csv, json, time
import scanner, backtest as B, basket_paper as BP

P = BP.P; fd = BP.fd; COOL = 14

def main():
    today = int(time.time() // 86400)
    m = B.hist_crypto("BTC", "1d", 400)
    cl = {int(r[0] // 86400): r[4] for r in m}
    days = [d for d in sorted(cl) if d < today]
    c = [cl[d] for d in days]; n = len(days)
    ma = lambda k: sum(c[-k:]) / k
    g200 = c[-1] > ma(200); g50 = c[-1] > ma(50)
    try:
        oi = BP.get_oi(days); a, b = BP.warnings(days, oi); oi_ok = bool(oi)
    except Exception as e:
        a = b = [False] * n; oi_ok = False
    cw = [x and y for x, y in zip(a, b)]
    recent = [i for i in range(max(0, n - COOL), n) if cw[i]]
    oi_warn = bool(recent)
    state = "IN" if (g200 and g50 and not oi_warn) else "OUT"
    reasons = []
    if not g200: reasons.append("BTC below its 200-day average")
    if not g50: reasons.append("BTC below its 50-day average")
    if oi_warn: reasons.append(f"BTC open-interest warning on {fd(days[recent[-1]])} (cash until {fd(days[recent[-1]] + COOL)})")
    sp = P("regime_state.json")
    old = json.load(open(sp)) if os.path.exists(sp) else None
    try:
        e = B.hist_crypto("ETH", "1d", 10); eth = e[-1][4]
    except Exception: eth = None
    cur = {"state": state, "g200": g200, "g50": g50, "oi_warn": oi_warn, "date": fd(days[-1]), "btc": round(c[-1], 2), "eth": round(eth, 2) if eth else None}
    # entry prices of the current IN spell (kept while IN, cleared when OUT)
    if state == "IN":
        cur["entry_btc"] = (old or {}).get("entry_btc") if old and old.get("state") == "IN" and old.get("entry_btc") else cur["btc"]
        cur["entry_eth"] = (old or {}).get("entry_eth") if old and old.get("state") == "IN" and old.get("entry_eth") else cur["eth"]
    msg = (f"BTC {c[-1]:,.0f}  200d avg {ma(200):,.0f} ({'above' if g200 else 'below'})  50d avg {ma(50):,.0f} ({'above' if g50 else 'below'})\n"
           f"OI warning in last {COOL}d: {'YES' if oi_warn else 'no'}" + ("" if oi_ok else " (OI data unavailable, treated as no)") + "\n"
           + ("Why OUT: " + "; ".join(reasons) if state == "OUT" else "All three conditions clear.") + "\nSignal from the daily close; rule-based prompt, not advice.")
    MM = 0.005
    def lev(name, entry, now):
        if not entry or not now: return ""
        out = f"{name} since IN {entry:,.0f} (now {now:,.0f}, {(now / entry - 1) * 100:+.1f}%): "
        out += "; ".join(f"{L}x liq {entry * (1 - (1 - MM * L) / L):,.0f} ({(1 - entry * (1 - (1 - MM * L) / L) / now) * 100:.0f}% below now)" for L in (2, 3))
        return out
    if state == "IN":
        msg += "\nLEVERAGE VIEW (if you opened at the IN price; 0.5% maintenance margin, exchange fees/funding extra):\n" + lev("BTC", cur.get("entry_btc"), cur["btc"]) + "\n" + lev("ETH", cur.get("entry_eth"), cur["eth"])
        msg += f"\nBTC exit trigger: close below 50-day avg {ma(50):,.0f} ({(1 - ma(50) / c[-1]) * 100:.1f}% below now). Past worst dip below entry in IN spells: BTC 10%, ETH 19% (40 spells) - a fast wick can still hit before a daily signal."
    changed = old is None or old["state"] != state
    parts = ""
    if old and not changed:
        ch = [k for k in ("g200", "g50", "oi_warn") if old.get(k) != cur[k]]
        if ch: parts = "component change: " + ", ".join(ch)
    if changed:
        title = ("ALTS: GET IN" if state == "IN" else "ALTS: GET OUT") if old else f"Alt regime started: {state}"
        scanner.notify(title, msg, scanner.NTFY_TOPIC, "green_circle" if state == "IN" else "red_circle", 4 if state == "OUT" else 3)
    elif parts:
        scanner.notify("Alt regime: " + state + " (" + parts + ")", msg, scanner.NTFY_TOPIC, "yellow_circle", 2)
    # ---- separate LEVERAGE alert (own title/tag). While IN: one note a day; louder when something needs attention.
    if state == "IN":
        lv = lev("BTC", cur.get("entry_btc"), cur["btc"]) + "\n" + lev("ETH", cur.get("entry_eth"), cur["eth"])
        gap = (1 - ma(50) / c[-1]) * 100
        dip = (1 - cur["btc"] / cur["entry_btc"]) * 100 if cur.get("entry_btc") else 0
        dipe = (1 - cur["eth"] / cur["entry_eth"]) * 100 if cur.get("entry_eth") and cur.get("eth") else 0
        warn = []
        if gap < 2: warn.append(f"BTC is only {gap:.1f}% above its 50-day exit line ({ma(50):,.0f})")
        if dip >= 10 or dipe >= 15: warn.append(f"price is {max(dip, dipe):.0f}% below the IN entry; 3x liquidation is 33% away, 2x is 50%")
        body = lv + f"\nExit line: BTC daily close below {ma(50):,.0f} ({gap:.1f}% below now).\nFast wicks can liquidate before a daily signal; use your own fill price and an exchange stop."
        if warn: scanner.notify("LEVERAGE WARNING: " + warn[0][:60], "\n".join(warn) + "\n" + body, scanner.NTFY_TOPIC, "warning", 4)
        else: scanner.notify("Leverage levels (alts IN)", body, scanner.NTFY_TOPIC, "chart_with_upwards_trend", 2)
    json.dump(cur, open(sp, "w"))
    lp = P("regime_log.csv"); new = not os.path.exists(lp)
    with open(lp, "a", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(["date", "state", "btc", "above_200d", "above_50d", "oi_warning_14d"])
        w.writerow([cur["date"], state, cur["btc"], g200, g50, oi_warn])
    open(P("regime_report.txt"), "w").write(f"ALT REGIME  data to {cur['date']}: {state}\n{msg}\n")
    print(open(P("regime_report.txt")).read())

if __name__ == "__main__":
    main()
