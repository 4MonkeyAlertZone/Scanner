#!/usr/bin/env python3
"""STOCKS REGIME ALERT (from stocks steps 1, 2 and 2b). Runs weekdays after the US close. Regime = S&P 500 price index vs its 200-day average with a 2% band:
IN after a close above 1.02 x the 200-day average, OUT after a close below 0.98 x it, unchanged in between (computed from 1985 history every run, so nothing can get out of sync).
Traffic light: GREEN = IN and above the 50-day average; ORANGE = IN but below the 50-day average (hold, do not add); RED = OUT (sell to cash / T-bills).
What to hold when IN (tested in step 2b): Nasdaq-100 (growth, with the S&P as the regime signal) or the top 3 sector funds by 12-month return (listed in the note). A 2x S&P fund is the optional leveraged version.
Sends: a phone alert when the regime changes (GET IN / GET OUT, loud), a daily traffic-light note (louder when the colour changes). Also runs a SILENT paper test since the first run day (stocks_start.txt):
accounts for Nasdaq-100 + regime, top-3 sectors by 12m momentum + regime, S&P + regime, two diversified trend sleeves (12 ETFs, with and without BTC/ETH; each asset held while above its own 200-day, inverse-volatility weights), versus buy-and-hold of S&P and Nasdaq-100. Writes stocks_state.json, stocks_report.txt, stocks_log.csv.
Honest status: backtests are price-based, no hindsight picks in the rule itself, but only ~3 big bear markets (2000-02, 2008, 2020) decide the result. Use as a prompt to look, not an order. Not financial advice."""
import os, csv, json, time
import scanner
import backtest_stocks2b as B2
import backtest_stocks2c as C2
import backtest_portfolio3 as PF

P = lambda f: os.path.join(scanner.HERE, f); fd = B2.fd
PORTFOLIO_SPLIT = (40, 40, 20)   # core / trend / crypto shares used in the weekly Friday portfolio note (your choice of risk, not a finding)
SEC = "XLB XLE XLF XLI XLK XLP XLU XLV XLY".split()

def main(data=None, send=None, extra=None):
    send = send or scanner.notify
    if data is None:
        data = {"GSPC": B2.fetch("^GSPC", adj=False), "NDX": B2.fetch("^NDX", adj=False), "IRX": B2.fetch("^IRX", adj=False, need=1000)}
        for t in SEC: data[t] = B2.fetch(t, p1=883612800)
    now = time.gmtime(); today = int(time.time() // 86400)
    g = dict(data["GSPC"])
    if max(g) >= today and now.tm_hour * 60 + now.tm_min < 21 * 60 + 30: g.pop(max(g))       # latest bar still forming
    days = [d for d in sorted(g) if d >= B2.d0(1985, 6, 1)]; n = len(days)
    B2.days_m = [time.strftime("%Y-%m", time.gmtime(d * 86400)) for d in days]
    def col(key):
        out = []; last = None
        for d in days:
            if d in data[key]: last = data[key][d]
            out.append(last)
        first = next(i for i, x in enumerate(out) if x is not None)
        return [x if x is not None else out[first] for x in out]
    CG = col("GSPC"); CN = col("NDX"); irx = col("IRX"); cash = [0.0] + [(x or 0) / 100 / 252 for x in irx[1:]]
    m200 = B2.sma(CG, 200); m50 = B2.sma(CG, 50); band = B2.hyst(CG, m200, .02)
    state = "IN" if band[-1] else "OUT"; last = days[-1]
    gap200 = (CG[-1] / m200[-1] - 1) * 100; gap50 = (CG[-1] / m50[-1] - 1) * 100
    color = "RED" if state == "OUT" else ("GREEN" if gap50 > 0 else "ORANGE")
    # sector leaders (12m and 6m)
    names = [t for t in SEC if t in data]; Pp = B2.align(data, names, days)
    sc = sorted(((Pp[t][-1] / Pp[t][-253] - 1, Pp[t][-1] / Pp[t][-127] - 1, t) for t in names if Pp[t][-253] and Pp[t][-127]), reverse=True)
    lead = ", ".join(f"{t} ({a * 100:+.0f}% 12m)" for a, b, t in sc[:3]); allr = "; ".join(f"{t} {a * 100:+.0f}%/{b * 100:+.0f}%" for a, b, t in sc)
    # paper test
    sp = P("stocks_start.txt")
    if not os.path.exists(sp): open(sp, "w").write(str(last))
    start = int(open(sp).read().strip()); i0 = next((i for i, d in enumerate(days) if d >= start), n - 1)
    RG = [0.0] + [CG[i] / CG[i - 1] - 1 for i in range(1, n)]; RN = [0.0] + [CN[i] / CN[i - 1] - 1 for i in range(1, n)]
    Rl = [[0.0] + [(Pp[t][i] / Pp[t][i - 1] - 1) if Pp[t][i] and Pp[t][i - 1] else 0.0 for i in range(1, n)] for t in names]
    acc = {"Nasdaq-100 + regime": B2.run_w([[1.0 if band[i] else 0.0] for i in range(n)], [RN], cash, i0, n),
           "Top-3 sectors (12m) + regime": B2.run_w(B2.rotate(Pp, names, band, 252, 3, n, i0), Rl, cash, i0, n),
           "S&P 500 + regime": B2.run_w([[1.0 if band[i] else 0.0] for i in range(n)], [RG], cash, i0, n),
           "Nasdaq-100 buy and hold": B2.run_w([[1.0]] * n, [RN], cash, i0, n), "S&P 500 buy and hold": B2.run_w([[1.0]] * n, [RG], cash, i0, n)}
    # ---- silent trend-sleeve paper test (12 ETFs + BTC/ETH variants), tail of the calendar only; never allowed to break the alert
    sleeve_lines = []
    try:
        ex = extra if extra is not None else {t: C2.fetch_v(t, need=800) for t in C2.ETF + C2.CRY}
        T = 1500; dts = days[-T:]; B2.days_m = [time.strftime("%Y-%m", time.gmtime(d * 86400)) for d in dts]
        prs = PF.prep(ex, dts); nt = len(dts); cashT = cash[-T:]; i0t = next((i for i, d in enumerate(dts) if d >= start), nt - 1)
        Rt = lambda t: [0.0] + [(prs[t][i] / prs[t][i - 1] - 1) if prs[t][i] and prs[t][i - 1] else 0.0 for i in range(1, nt)]
        for lab, u in (("Trend sleeve: 12 ETFs", list(C2.ETF)), ("Trend sleeve: 12 ETFs + BTC/ETH", list(C2.ETF) + list(C2.CRY))):
            u = [t for t in u if t in prs]; Wt = PF.trend_W(prs, u, nt, B2.days_m); m = B2.run_w(Wt, [Rt(t) for t in u], cashT, i0t, nt)
            acc[lab] = m
            held = sorted(((Wt[-1][s], t) for s, t in enumerate(u) if Wt[-1][s] > 0), reverse=True)
            sleeve_lines.append(f"{lab} holds now: " + (", ".join(f"{t} {w * 100:.0f}%" for w, t in held) or "nothing") + f"; cash {100 * (1 - sum(w for w, t in held)):.0f}%")
    except Exception as e:
        sleeve_lines.append(f"(trend sleeve paper test unavailable today: {str(e)[:80]})")
    # ---- silent combined-portfolio paper accounts (40/40/20 and 50/30/20) and the weekly Friday portfolio note
    pf_note = None
    try:
        dx = dict(ex); dx["^GSPC"] = {d: (v, 0) for d, v in data["GSPC"].items()}; dx["^IRX"] = {d: (v, 0) for d, v in data["IRX"].items()}
        X = PF.setup(dx); Xn = X["n"]; Xi0 = next((i for i, d in enumerate(X["days"]) if d >= start), Xn - 1)
        for c, t_, k in ((40, 40, 20), (50, 30, 20)):
            W = [PF.split_weights(c / 100, t_ / 100, k / 100, X, i, X["band"][i], X["cry_in"][i]) for i in range(Xn)]
            acc[f"Portfolio {c}/{t_}/{k} (core/trend/crypto)"] = B2.run_w(W, X["R"], X["cash"], Xi0, Xn)
        # live crypto engine = the crypto regime alert's own state (includes the open-interest warning) when available
        cin = X["cry_in"][-1]; src = "BTC above 200d and 50d"
        try:
            cs_ = json.load(open(P("regime_state.json"))); cin = (cs_.get("state") == "IN"); src = "your crypto regime alert"
        except Exception: pass
        c, t_, k = PORTFOLIO_SPLIT; core_in = band[-1]; hold = {}
        if core_in: hold["QQQ"] = c
        for s_, tk in enumerate(C2.ETF):
            if X["Wt"][-1][s_] > 0: hold[tk] = hold.get(tk, 0) + t_ * X["Wt"][-1][s_]
        if cin: hold["BTC"] = k / 2; hold["ETH"] = k / 2
        inv = sum(hold.values()); engines_in = sum([bool(core_in), True, bool(cin)])
        lines = [f"Portfolio split {c}/{t_}/{k} (core/trend/crypto). Engines: core (S&P regime) {'IN' if core_in else 'OUT'}; trend sleeve IN (per-asset); crypto {'IN' if cin else 'OUT'} ({src}).",
                 "Target weights: " + ", ".join(f"{a} {w:.0f}%" for a, w in sorted(hold.items(), key=lambda x: -x[1])) + f"; cash {100 - inv:.0f}%.", "Backtest 2018-now: this mix returned about the Nasdaq-100 with roughly half the drawdown, but crypto's share of the gain came from one bull run. Not advice."]
        pf_note = ("PORTFOLIO (weekly): " + f"{engines_in} of 3 engines IN, {inv:.0f}% invested", "\n".join(lines))
        sleeve_lines.append(lines[1])
    except Exception as e:
        sleeve_lines.append(f"(portfolio paper accounts unavailable today: {str(e)[:80]})")
    rep = [f"STOCKS REGIME  data to {fd(last)}  state {state}  light {color}",
           f"S&P 500 {CG[-1]:,.0f}: {gap200:+.1f}% vs 200-day ({m200[-1]:,.0f}), {gap50:+.1f}% vs 50-day ({m50[-1]:,.0f}). " + (f"Exit if a close is below {0.98 * m200[-1]:,.0f} ({(0.98 * m200[-1] / CG[-1] - 1) * 100:.1f}%)." if state == "IN" else f"Re-enter on a close above {1.02 * m200[-1]:,.0f} ({(1.02 * m200[-1] / CG[-1] - 1) * 100:+.1f}%)."),
           f"Sector funds, 12m / 6m return: {allr}", "",
           f"SILENT PAPER TEST since {fd(days[i0])} ({n - 1 - i0} days; percent change, cash earns T-bill rate):"] + [f"  {k:<30}{(v['final'] - 1) * 100:>+7.1f}%" for k, v in acc.items()] + [""] + sleeve_lines + ["", "Early weeks mean nothing; judge after months and after a real fall."]
    open(P("stocks_report.txt"), "w").write("\n".join(rep) + "\n"); print("\n".join(rep))
    lp = P("stocks_log.csv"); rows = {}
    if os.path.exists(lp):
        for r in csv.reader(open(lp)):
            if r and r[0] != "date": rows[r[0]] = r
    rows[fd(last)] = [fd(last), state, color, f"{CG[-1]:.2f}", f"{gap200:.2f}", f"{gap50:.2f}"] + [f"{(v['final'] - 1) * 100:.2f}" for v in acc.values()]
    with open(lp, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "state", "light", "sp500", "gap200_pct", "gap50_pct"] + list(acc)); [w.writerow(rows[k]) for k in sorted(rows)]
    # alerts
    stp = P("stocks_state.json"); old = json.load(open(stp)) if os.path.exists(stp) else None
    cur = {"state": state, "color": color, "date": fd(last)}
    if old and old.get("date") == cur["date"]: print("same day already processed, no alert"); return
    EMO = {"GREEN": "green_circle", "ORANGE": "orange_circle", "RED": "red_circle"}
    body_lines = f"S&P 500 {CG[-1]:,.0f}: {gap200:+.1f}% vs 200-day, {gap50:+.1f}% vs 50-day."
    changed = old is None or old["state"] != state
    if changed:
        title = ("STOCKS: GET IN" if state == "IN" else "STOCKS: GET OUT") if old else f"Stocks regime started: {state}"
        act = ("Hold or buy: Nasdaq-100, or the top sector funds: " + lead + ". Optional: 2x S&P fund (bigger swings).") if state == "IN" else "Sell stock-fund holdings to cash / T-bills. Regime is OUT."
        send(title, f"{act}\n{body_lines}\n" + rep[1].split(". ", 1)[-1] + "\nSignal from the daily close; rule-based prompt, not advice.", scanner.NTFY_TOPIC, "green_circle" if state == "IN" else "red_circle", 4 if state == "OUT" else 3)
    head = {"GREEN": "STOCKS GREEN: OK to hold or buy", "ORANGE": "STOCKS ORANGE: hold, do not add", "RED": "STOCKS RED: out, stay in cash"}[color]
    act = {"GREEN": "ACTION: hold or buy Nasdaq-100 or sector leaders: " + lead + ".", "ORANGE": "ACTION: do not add. Hold what you have; the 200-day exit is " + f"{(0.98 * m200[-1] / CG[-1] - 1) * 100:.1f}% away.", "RED": "ACTION: stay in cash / T-bills until the S&P closes above " + f"{1.02 * m200[-1]:,.0f}."}[color]
    chg = (old or {}).get("color") != color
    send(head, f"{act}\n{body_lines}\nColours: GREEN = IN and above 50-day; ORANGE = IN but below 50-day; RED = below the 200-day band.\nBacktest 1985-2026: this rule cut Nasdaq-100 drawdown from -83% to -36% for about 1% a year of return. Not advice.", scanner.NTFY_TOPIC, EMO[color], 4 if (chg and color == "RED") else (3 if chg else 2))
    try:
        if pf_note and (last + 3) % 7 == 4: send(pf_note[0], pf_note[1], scanner.NTFY_TOPIC, "bar_chart", 2)
    except Exception as e: print("(weekly portfolio note failed:", e, ")")
    json.dump(cur, open(stp, "w"))

if __name__ == "__main__":
    main()
