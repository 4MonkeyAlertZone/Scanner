#!/usr/bin/env python3
"""ALT REGIME ALERT: phone notification when the 'alts in / alts out' state changes. Runs once a day just after the daily candle closes.
State = IN only when ALL of: (1) BTC closed above its 200-day average, (2) BTC closed above its 50-day average, (3) no BTC open-interest warning C in the last 14 days
(C = BTC futures open interest at a new 180-day high AND up 15%+ in 30 days; data from data.binance.vision, cached in basketgate_oi.csv by basket_paper.py).
Otherwise OUT. These are the 'gate + 50-day' and 'gate + OI C-14' rules from the majors/coins5 reports, combined. Rules fixed on 19 Oct 2026, never changed.
Honest status: the OI part was chosen after seeing the data (not out-of-sample); backtests are survivorship-flattered and cover ~3 phases. Use as a prompt to look, not an order.
Writes regime_state.json, regime_log.csv, regime_report.txt. Sends ONE short phone alert only when the traffic light changes (and once on first run); nothing while the state stays the same. The traffic light is: GREEN 2%+ above the BTC 50-day average, ORANGE 0-2% above, RED below / regime OUT; louder when the colour changes. A matching SPOT traffic-light note is sent too (same colours, wording for unleveraged alt holdings)."""
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
    # ---- ONE short alert, sent ONLY when the traffic light (or the IN/OUT state) changes, and once on the first run. No daily repeat while nothing changes
    # (changed 25 Nov 2026 at the owner's request; the rules and thresholds are untouched). GREEN = 2%+ above the 50-day line, ORANGE = 0-2% above, RED = OUT.
    gap = (c[-1] / ma(50) - 1) * 100
    color = "RED" if state == "OUT" else ("GREEN" if gap >= 2 else "ORANGE")
    cur["lev_color"] = color; cur["spot_color"] = color
    prev_color = (old or {}).get("lev_color"); changed = old is None or old.get("state") != state or prev_color != color
    if changed:
        EMO = {"GREEN": "green_circle", "ORANGE": "orange_circle", "RED": "red_circle"}
        head = {"GREEN": "ALTS GREEN: hold / buy", "ORANGE": "ALTS ORANGE: hold, don't add", "RED": "ALTS RED: sell to cash, no leverage"}[color]
        body = [f"BTC {c[-1]:,.0f} ({gap:+.1f}% vs 50d {ma(50):,.0f}; 200d {ma(200):,.0f} {'above' if g200 else 'below'})"]
        if state == "OUT": body.append("Why: " + "; ".join(reasons) + ".")
        else:
            body.append(f"Exit line: close below {ma(50):,.0f}.")
            body.append("Leverage 2x or less only." if color == "GREEN" else "No new leverage; exit line is close.")
        body.append("Prompt, not advice.")
        scanner.notify(head, "\n".join(body), scanner.NTFY_TOPIC, EMO[color], 4 if color == "RED" else 3)
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
