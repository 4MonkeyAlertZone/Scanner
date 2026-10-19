#!/usr/bin/env python3
"""Lab 25: plain rules, no fitting. Lab 24 found one pattern in every period: among the top-K coins by size, calmer and more BTC-correlated coins beat the wild ones.
Here it is turned into simple strategies, chosen BEFORE seeing results: every 10 days hold the 3 top-scoring coins of the top-K (K=10 and 20; K ranks by trailing traded value) for 10 days.
V1 lowest 30d volatility | V2 highest 30d correlation with BTC | V3 both (average rank) | V3g = V3 only while BTC is above its 200-day average, else cash |
V4 the 3 biggest | V6 highest volatility (should do WORSE if the pattern is real) | basket = all top-K equally | BTC hold. Cost 0.1% per rebalance on the positions (full turnover assumed).
Reported per period (cycle 1, bear year, cycle 2, recent): final multiple, worst fall, Sharpe, average excess per trade vs the basket, and a chance test (random shifts of the same scores).
Writes lab25_summary.txt."""
import os, sys, calendar, random
from datetime import datetime, timezone
from multiprocessing import Pool
import numpy as np
import scanner, backtest as B
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.tree import DecisionTreeRegressor, export_text

STABLES = {"USDT", "USDC", "DAI", "TUSD", "FDUSD", "USDE", "USD1", "PYUSD", "USDD", "BUSD", "USDP", "FRAX", "WBTC", "BTC", "STETH", "WSTETH", "WBETH"}
NC = int(os.environ.get("LAB24_COINS", "90")); HOLD = 10; COST = float(os.environ.get("LAB_COST", "0.001")); TOPN = 3
ts = lambda y, m, d: calendar.timegm((y, m, d, 0, 0, 0))
PER = {  # signal-date windows (purged by ~12 days at the edges)
    "cycle 2 (train A)": (ts(2022, 11, 21), ts(2025, 8, 19)),
    "cycle 1": (ts(2020, 10, 1), ts(2021, 11, 1)),
    "bear year": (ts(2021, 11, 23), ts(2022, 11, 8)),
    "recent": (ts(2025, 9, 15), ts(2099, 1, 1)),
}
dstr = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")

def load(sym):
    try:
        rows = B.hist_crypto(sym, "1d", 2800); out = []
        for t, o, h, l, c, v in rows:
            hb, lb = max(o, c), min(o, c); out.append((t, o, min(h, hb * 1.25), max(l, lb / 1.25), c, v))
        return sym, out
    except Exception: return sym, []

def sma(x, n):
    out = np.full_like(x, np.nan); cs = np.nancumsum(np.where(np.isnan(x), 0, x), axis=1); cn = np.cumsum(~np.isnan(x), axis=1)
    s = cs.copy(); k = cn.copy(); s[:, n:] = cs[:, n:] - cs[:, :-n]; k[:, n:] = cn[:, n:] - cn[:, :-n]
    ok = k >= n * 0.9; out[ok] = s[ok] / k[ok]; return out

def lag(x, k):
    out = np.full_like(x, np.nan); out[:, k:] = x[:, :-k] if k else x; return out if k else x.copy()

def roll_std(x, n):
    m = sma(x, n); m2 = sma(x * x, n); return np.sqrt(np.maximum(m2 - m * m, 0))

def rsi14(c):
    d = np.diff(c, axis=1, prepend=np.nan); g = np.where(d > 0, d, 0); l = np.where(d < 0, -d, 0)
    ag, al = sma(g, 14), sma(l, 14); return 100 - 100 / (1 + ag / np.where(al == 0, np.nan, al))

def spearman_days(F, Y, idx):
    """Mean per-day cross-sectional rank correlation between feature matrix F (coins x days) and target Y."""
    out = []
    for j in idx:
        f, y = F[:, j], Y[:, j]; ok = ~np.isnan(f) & ~np.isnan(y)
        if ok.sum() < 6 or np.ptp(f[ok]) == 0: continue   # market-wide features are identical for every coin on a day: no cross-sectional information
        rf = np.argsort(np.argsort(f[ok])); ry = np.argsort(np.argsort(y[ok]))
        c = np.corrcoef(rf, ry)[0, 1]
        if c == c: out.append(c)
    return (np.mean(out), len(out)) if out else (np.nan, 0)

def main():
    btc = dict(load("BTC")[1]) if False else None
    _, brows = load("BTC")
    toks = [t for t in scanner.top100()[:NC + 15] if t.upper() not in STABLES][:NC]
    with Pool(2) as p: res = p.map(load, toks, chunksize=1)
    data = {s: r for s, r in res if len(r) > 450}
    T = np.array([r[0] for r in brows]); nD = len(T); pos = {int(t): i for i, t in enumerate(T)}
    names = list(data); nC = len(names)
    O = np.full((nC, nD), np.nan); H = O.copy(); L = O.copy(); C = O.copy(); V = O.copy()
    for k, s in enumerate(names):
        for t, o, h, l, c, v in data[s]:
            j = pos.get(int(t))
            if j is not None: O[k, j], H[k, j], L[k, j], C[k, j], V[k, j] = o, h, l, c, v
    bO = np.array([[r[1] for r in brows]]); bC = np.array([[r[4] for r in brows]])
    # ---- features (information up to close of day t) ----
    F = {}; ret = lambda x, n: x / lag(x, n) - 1
    for n in (1, 2, 3, 5, 10, 20, 30, 60): F[f"ret_{n}d"] = ret(C, n)
    bret = {n: ret(bC, n) for n in (1, 2, 3, 5, 10, 20, 30, 60)}
    for n in (1, 3, 10, 30): F[f"rel_btc_{n}d"] = F[f"ret_{n}d"] - bret[n]
    for n in (1, 3, 10, 30): F[f"btc_ret_{n}d"] = np.repeat(bret[n], nC, axis=0)
    F["btc_ret_1d_lag1"] = lag(np.repeat(bret[1], nC, axis=0), 1)
    b200, b50 = sma(bC, 200), sma(bC, 50)
    F["btc_vs_200d"] = np.repeat(bC / b200 - 1, nC, axis=0); F["btc_vs_50d"] = np.repeat(bC / b50 - 1, nC, axis=0)
    for n in (20, 50, 200): F[f"vs_ma{n}"] = C / sma(C, n) - 1
    hi60 = np.full_like(C, np.nan); lo60 = hi60.copy()
    for j in range(60, nD): hi60[:, j] = np.nanmax(H[:, j-59:j+1], axis=1); lo60[:, j] = np.nanmin(L[:, j-59:j+1], axis=1)
    F["off_60d_high"] = C / hi60 - 1; F["above_60d_low"] = C / lo60 - 1
    F["rsi14"] = rsi14(C); dr = ret(C, 1)
    F["vol_10d"] = roll_std(dr, 10); F["vol_30d"] = roll_std(dr, 30); F["vol_ratio"] = F["vol_10d"] / F["vol_30d"]
    F["range_today"] = (H - L) / C; rg = np.where(H > L, H - L, np.nan); F["close_loc"] = (C - L) / rg
    F["body_today"] = (C - O) / O
    F["vol_surge"] = V / sma(V, 20); F["vol_5v30"] = sma(V, 5) / sma(V, 30)
    ew = np.nanmean(dr, axis=0, keepdims=True); basket = np.nancumprod(1 + np.nan_to_num(ew, nan=0.0), axis=1)
    for n in (1, 5, 10, 30): F[f"basket_ret_{n}d"] = np.repeat(basket / np.concatenate([np.full((1, n), np.nan), basket[:, :-n]], axis=1) - 1, nC, axis=0)
    ratio = basket / bC
    for n in (10, 30): F[f"basket_vs_btc_{n}d"] = np.repeat(ratio / np.concatenate([np.full((1, n), np.nan), ratio[:, :-n]], axis=1) - 1, nC, axis=0)
    above50 = (C > sma(C, 50)).astype(float); above50[np.isnan(sma(C, 50))] = np.nan
    F["breadth_above_50d"] = np.repeat(np.nanmean(above50, axis=0, keepdims=True), nC, axis=0)
    cor = np.full_like(C, np.nan)
    for j in range(30, nD):
        b = bret[1][0, j-29:j+1]
        for k in range(nC):
            x = dr[k, j-29:j+1]; ok = ~np.isnan(x) & ~np.isnan(b)
            if ok.sum() > 20: cor[k, j] = np.corrcoef(x[ok], b[ok])[0, 1]
    F["corr_btc_30d"] = cor
    F["resid_vs_btc_1d"] = F["ret_1d"] - cor * F["btc_ret_1d"]
    dv = sma(C * V, 60)                                   # trailing 60-day average traded value in USD
    rk = np.full_like(C, np.nan)
    for j in range(nD):
        m = ~np.isnan(dv[:, j])
        if m.sum(): rk[m, j] = np.argsort(np.argsort(-dv[m, j])) + 1
    F["size_rank"] = rk
    fn = list(F); X3 = np.stack([F[k] for k in fn], axis=2)           # coins x days x features
    # ---- strategies ----
    Oa = np.concatenate([O, np.full((nC, HOLD + 2), np.nan)], axis=1)
    R = np.full((nC, nD), np.nan)
    for j in range(nD - HOLD - 1): R[:, j] = Oa[:, j + 1 + HOLD] / Oa[:, j + 1] - 1
    bOa = np.concatenate([bO, np.full((1, HOLD + 2), np.nan)], axis=1)[0]
    RB = np.full(nD, np.nan)
    for j in range(nD - HOLD - 1): RB[j] = bOa[j + 1 + HOLD] / bOa[j + 1] - 1
    gate = (bC / b200)[0] > 1
    PERS = {"cycle 1": (ts(2020, 10, 1), ts(2021, 11, 10)), "bear year": (ts(2021, 11, 10), ts(2022, 11, 21)),
            "cycle 2": (ts(2022, 11, 21), ts(2025, 8, 31)), "recent": (ts(2025, 9, 1), ts(2099, 1, 1))}
    vol, cor = F["vol_30d"], F["corr_btc_30d"]
    def cs_rank(x, U):
        out = np.full_like(x, np.nan)
        for j in range(nD):
            m = U[:, j] & ~np.isnan(x[:, j])
            if m.sum() >= 3: out[m, j] = (np.argsort(np.argsort(x[m, j])) + 1) / m.sum()
        return out
    rnd = random.Random(7)
    out_all = [f"LAB 25  {datetime.now(timezone.utc):%Y-%m-%d}  plain rules from the lab 24 pattern. Pool {nC} coins (survivors), hold {HOLD}d, top {TOPN} of the top-K by size, cost {COST:.2%} per rebalance.",
               "Cell: x = final multiple (average over 10 start offsets) | dd = worst fall | S = Sharpe | ex = average excess per trade vs the top-K basket | p = chance test (p below ~0.1 and ex>0 in EVERY period to count).", ""]
    for K in (10, 20):
        U = (rk <= K) & ~np.isnan(R); cnt = U.sum(axis=0); need = max(6, int(K * .7))
        v_s, c_s = cs_rank(-vol, U), cs_rank(cor, U)
        SC = {"V1 low volatility": v_s, "V2 high BTC correlation": c_s, "V3 low vol + high corr": (v_s + c_s) / 2, "V3g  V3, cash when BTC < 200d": (v_s + c_s) / 2,
              "V4 the 3 biggest": cs_rank(-rk, U), "V6 HIGH volatility (opposite)": cs_rank(vol, U)}
        def trade(S, j, gated=False):
            m = U[:, j] & ~np.isnan(S[:, j])
            if cnt[j] < need or m.sum() < need: return None
            r = R[m, j]; o = np.argsort(S[m, j])[-TOPN:]
            if gated and not gate[j]: return 0.0, r.mean()                   # cash (no cost) vs basket
            return r[o].mean() - COST, r.mean()
        def stats(rets):
            r = np.array(rets); eq = np.cumprod(1 + r); dd = (eq / np.maximum.accumulate(eq) - 1).min()
            sh = r.mean() / r.std() * np.sqrt(365 / HOLD) if r.std() > 0 else 0.0
            return eq[-1], dd, sh
        out_all += [f"################ TOP {K} BY SIZE RANK ################", f"{'strategy':<32}" + "".join(f"{p:>34}" for p in PERS)]
        names_rows = list(SC) + ["basket (all top-K equally)", "BTC hold"]
        table = {n: [] for n in names_rows}
        for pname, (lo, hi) in PERS.items():
            days = [j for j in range(220, nD - HOLD - 1) if lo <= T[j] < hi and cnt[j] >= need]
            if len(days) < 30:
                for n in names_rows: table[n].append("n/a (too few coins)")
                continue
            for n in names_rows:
                mults, dds, shs = [], [], []; exs = []
                for off in range(10):
                    js = days[off::10]; rr, ee = [], []
                    for j in js:
                        if n == "BTC hold": rr.append(RB[j]); continue
                        if n.startswith("basket"):
                            t = trade(SC["V4 the 3 biggest"], j)
                            if t: rr.append(t[1])
                            continue
                        t = trade(SC[n], j, gated=n.startswith("V3g"))
                        if t: rr.append(t[0]); ee.append(t[0] - t[1])
                    if len(rr) < 5: continue
                    m, d, s_ = stats(rr); mults.append(m); dds.append(d); shs.append(s_); exs += ee
                if not mults: table[n].append("n/a"); continue
                cell = f"x{np.mean(mults):.2f} dd{np.mean(dds):.0%} S{np.mean(shs):.1f}"
                if exs and n in SC:
                    js0 = days[::10]; base = np.mean(exs)
                    nullm = []
                    for _ in range(150):                       # circular-shift null on the same scores
                        Sh = np.empty_like(SC[n])
                        for k in range(nC): Sh[k] = np.roll(SC[n][k], rnd.randrange(40, nD - 40))
                        e = [trade(Sh, j, gated=n.startswith("V3g")) for j in js0]; e = [x[0] - x[1] for x in e if x]
                        if e: nullm.append(np.mean(e))
                    p = float(np.mean(np.array(nullm) >= base)) if nullm else float("nan")
                    cell += f" ex{base:+.1%} p{p:.2f}"
                table[n].append(cell)
        for n in names_rows: out_all.append(f"{n:<32}" + "".join(f"{c:>34}" for c in table[n]))
        out_all.append("")
    out_all += ["HOW TO READ: the pattern is only real if V1/V2/V3 beat the basket (ex > 0) in EVERY period with small p, AND V6 (the opposite) does worse. Profit versus BTC hold is a separate question: compare the multiples.",
                "Pool = coins listed today; size = trailing traded value, not true market cap; top 20 has too few coins in 2020-21. Treat any positive result as a lead to paper-trade, not proof."]
    text = "\n".join(out_all); open(os.path.join(scanner.HERE, "lab25_summary.txt"), "w").write(text + "\n"); print(text)
    try: scanner.notify("Strategy lab 25 finished", "Plain-rules test done - results are in the repo.", scanner.NTFY_TOPIC, "microscope")
    except Exception as e: print("(phone send failed:", e, ")")

if __name__ == "__main__":
    main()
