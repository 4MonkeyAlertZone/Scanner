#!/usr/bin/env python3
"""Lab 39: HOW ROBUST IS THE BTC REGIME GATE? Labs 37-38 found that the live swing scanner adds nothing, and that simply holding BTC or ETH while the BTC regime is IN did better with smaller drawdowns. This lab stress-tests that simpler idea before anything is built on it.
Data: BTC and ETH daily closes only. Gate = BTC close above its SLOW average AND above its FAST average (live rule: slow 200, fast 50; fast 0 means slow only). Signal at close i-1 earns day i; cost per unit of turnover as stated.
 PART 1  PARAMETER PLATEAU. Grid: slow in 100,125,150,175,200,250,300 x fast in 0,20,50,100 (fast must be below slow). Held asset: BTC, ETH, or 50/50 BTC+ETH (daily rebalanced, rebalancing cost ignored). For each cell: final x and Calmar (annual return / worst drawdown). A real effect shows as a broad plateau of good cells; a lucky setting shows as one good cell among poor neighbours. Reports the live setting's rank, the grid median/min/max, and how many cells beat buy&hold.
 PART 2  TIME-SHIFT PLACEBO. The live gate series is shifted around the calendar by a random amount (30 to n-30 days, circular), 500 times. This keeps the share of time IN and the length of every IN/OUT episode but breaks the link to the price. Reports where the real gate's final x and Calmar fall among the shifted ones (a percentile; 50 = no information, 95+ = unusual).
 PART 3  EXECUTION STRESS on the live setting: cost per unit of turnover 0.1%, 0.3%, 0.5% (fees plus slippage), and signal acted on 0, 1 or 2 days late.
 PART 4  STABILITY: the live setting and buy&hold in thirds of the history, and the number of separate IN episodes (few episodes = little independent evidence).
Benchmarks: buy&hold BTC, ETH and 50/50. SURVIVORSHIP: BTC and ETH are the two survivors everybody knows; a gate tested on assets chosen in hindsight looks better than it will. SELECTION: this is lab 39 on the same history. Not financial advice. Writes lab39_summary.txt."""
import os, random, statistics as S
import scanner
import backtest_lab36 as L36

OUT = scanner.HERE
fd = L36.fd; sma = L36.sma; metrics = L36.metrics
SLOWS = [100, 125, 150, 175, 200, 250, 300]; FASTS = [0, 20, 50, 100]
LIVE = (200, 50)

def build(data):
    days = sorted(set(data["BTC"]) & set(data["ETH"])); n = len(days)
    btc = [data["BTC"][d][0] for d in days]; eth = [data["ETH"][d][0] for d in days]
    return days, n, btc, eth

def gate_series(btc, slow, fast):
    m_s = sma(btc, slow); m_f = sma(btc, fast) if fast else None
    return [m_s[i] is not None and btc[i] > m_s[i] and (m_f is None or (m_f[i] is not None and btc[i] > m_f[i])) for i in range(len(btc))]

def run(rets, gate, i0, n, cost, delay=0):
    """rets: list of daily returns (index i = day i vs i-1). gate decided at close i-1-delay earns day i."""
    eq = 1.0; curve = [eq]; prev = 0.0; switches = 0
    for i in range(i0, n):
        w = 1.0 if i - 1 - delay >= 0 and gate[i - 1 - delay] else 0.0
        if w != prev: switches += 1
        r = w * rets[i] - cost * abs(w - prev); prev = w; eq *= 1 + r; curve.append(eq)
    yrs = (n - i0) / 365.0
    cagr = eq ** (1 / yrs) - 1 if eq > 0 else -1.0; dd = metrics(curve)
    return dict(final=eq, cagr=cagr, dd=dd, calmar=(cagr * 100 / abs(dd)) if dd < 0 else float("inf"), curve=curve, switches=switches)

def main(data=None):
    if data is None: data = L36.load(["BTC", "ETH"])
    assert "BTC" in data and "ETH" in data, "BTC or ETH history missing"
    days, n, btc, eth = build(data)
    rb = [0.0] + [btc[i] / btc[i - 1] - 1 for i in range(1, n)]; re_ = [0.0] + [eth[i] / eth[i - 1] - 1 for i in range(1, n)]
    r5 = [(a + b) / 2 for a, b in zip(rb, re_)]
    assets = {"BTC": rb, "ETH": re_, "50/50": r5}
    i0 = max(SLOWS) + 1; split = (i0 + n) // 2; COST = L36.CT
    allon = [True] * n
    bh = {a: run(r, allon, i0, n, 0.0) for a, r in assets.items()}
    out = [f"LAB 39: BTC REGIME GATE ROBUSTNESS  data {fd(days[0])} to {fd(days[-1])} ({n} days); all rows start {fd(days[i0])} so every setting has its average; cost {COST * 100:.1f}% per unit of turnover unless stated",
           "BENCHMARKS (buy&hold, no cost): " + "; ".join(f"{a} {b['final']:.2f}x, DD {b['dd']:.0f}%, Calmar {b['calmar']:.2f}" for a, b in bh.items()), ""]
    # ---------- Part 1
    out.append("PART 1: PARAMETER PLATEAU (final x / Calmar per cell; * = live setting 200/50; cells beating buy&hold Calmar marked +)")
    grids = {}
    for a, r in assets.items():
        out.append(f"  held asset {a}   (buy&hold: {bh[a]['final']:.2f}x, Calmar {bh[a]['calmar']:.2f})")
        out.append("  slow\\fast  " + "".join(f"{('none' if f == 0 else f):>16}" for f in FASTS))
        cells = {}
        for sl in SLOWS:
            row = f"  {sl:<10} "
            for f in FASTS:
                if f and f >= sl: row += f"{'-':>16}"; continue
                g = gate_series(btc, sl, f); x = run(r, g, i0, n, COST); cells[(sl, f)] = x
                mark = ("*" if (sl, f) == LIVE else " ") + ("+" if x["calmar"] > bh[a]["calmar"] else " ")
                row += f"{x['final']:>9.2f}/{x['calmar']:<4.2f}{mark}"
            out.append(row)
        grids[a] = cells
        fin = sorted(c["final"] for c in cells.values()); cal = sorted(c["calmar"] for c in cells.values())
        live = cells[LIVE]
        rank = 1 + sum(c["calmar"] > live["calmar"] for c in cells.values())
        out.append(f"  {a}: {len(cells)} cells; final x min {fin[0]:.2f} median {S.median(fin):.2f} max {fin[-1]:.2f}; Calmar min {cal[0]:.2f} median {S.median(cal):.2f} max {cal[-1]:.2f}; "
                   f"{sum(c['calmar'] > bh[a]['calmar'] for c in cells.values())} of {len(cells)} cells beat buy&hold Calmar; {sum(c['final'] > bh[a]['final'] for c in cells.values())} beat its final x; live setting ranks {rank} of {len(cells)} on Calmar")
        out.append("")
    # ---------- Part 2
    live_gate = gate_series(btc, *LIVE); rng = random.Random(39)
    out.append("PART 2: TIME-SHIFT PLACEBO (500 shifts of the live gate; same time IN, same episode lengths, link to price broken)")
    for a, r in assets.items():
        real = run(r, live_gate, i0, n, COST); fin = []; cal = []
        for _ in range(500):
            k = rng.randrange(30, n - 30); g = live_gate[k:] + live_gate[:k]
            x = run(r, g, i0, n, COST); fin.append(x["final"]); cal.append(x["calmar"])
        pf = 100 * sum(v < real["final"] for v in fin) / len(fin); pc = 100 * sum(v < real["calmar"] for v in cal) / len(cal)
        fs = sorted(fin); cs = sorted(cal)
        out.append(f"  {a}: real final {real['final']:.2f}x -> percentile {pf:.0f} (shifted median {S.median(fin):.2f}, 5th-95th {fs[25]:.2f} to {fs[475]:.2f}); real Calmar {real['calmar']:.2f} -> percentile {pc:.0f} (shifted median {S.median(cal):.2f}, 5th-95th {cs[25]:.2f} to {cs[475]:.2f})")
    out.append("")
    # ---------- Part 3
    out.append("PART 3: EXECUTION STRESS (live setting 200/50; final x / worst DD% per held asset)")
    out.append(f"  {'case':<34}" + "".join(f"{a:>18}" for a in assets))
    for cost, delay in ((0.001, 0), (0.003, 0), (0.005, 0), (0.001, 1), (0.001, 2), (0.005, 2)):
        row = f"  cost {cost * 100:.1f}%, signal {delay} day(s) late".ljust(36)
        for a, r in assets.items():
            x = run(r, live_gate, i0, n, cost, delay); row += f"{x['final']:>10.2f}x /{x['dd']:>4.0f}%"
        out.append(row)
    out.append("")
    # ---------- Part 4
    out.append("PART 4: STABILITY IN THIRDS OF THE HISTORY (final x in each third, live gate vs buy&hold)")
    cuts = [i0, i0 + (n - i0) // 3, i0 + 2 * (n - i0) // 3, n]
    for a, r in assets.items():
        parts = []
        for t in range(3):
            lo, hi = cuts[t], cuts[t + 1]; g = 1.0; b = 1.0; prev = 0.0
            for i in range(lo, hi):
                w = 1.0 if live_gate[i - 1] else 0.0; g *= 1 + w * r[i] - COST * abs(w - prev); prev = w; b *= 1 + r[i]
            parts.append(f"{fd(days[lo])[:7]}..{fd(days[hi - 1])[:7]} gate {g:.2f}x vs hold {b:.2f}x")
        out.append(f"  {a}: " + " | ".join(parts))
    eps = sum(1 for i in range(i0 + 1, n) if live_gate[i] and not live_gate[i - 1]); inpct = 100 * sum(live_gate[i0:n]) / (n - i0)
    out.append(f"  IN episodes in the live gate: {eps} (separate decisions that carry the whole result); IN {inpct:.0f}% of days")
    out += ["", "Read:",
            "- Plateau: many cells beating buy&hold on Calmar, with the live setting near the median rather than the top, means the gate is robust. One standout cell among weak neighbours means a lucky parameter.",
            "- Placebo: a real-gate percentile near 50 means the timing carries no information beyond being out of the market part of the time; 95+ is unusual, but with so few episodes treat even that as suggestive only.",
            "- Execution: if 0.5% cost or a 2-day delay erases the advantage, it will not survive real trading.",
            "- Few IN episodes (a handful) means little independent evidence. SURVIVORSHIP (BTC and ETH chosen in hindsight) and 38 earlier labs on this history flatter these numbers. Not financial advice."]
    text = "\n".join(out); open(os.path.join(OUT, "lab39_summary.txt"), "w").write(text + "\n"); print(text)

if __name__ == "__main__":
    main()
